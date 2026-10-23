"""Audio peaks for drawing waveforms on the timeline.

Each media file is decoded once (mono, low rate) into peak levels per BIN_S seconds and
cached as .npy next to the other caches. Decoding runs on a background thread; `on_ready`
is called (from that thread) when a file's peaks are available. Times are media times:
the stream's start_time (an MP3's encoder delay) is applied, as the mixer does.
"""
import hashlib
import os
import subprocess
import threading

import numpy as np

from .build import find_ffmpeg, media_start

BIN_S = 0.005                 # 200 peaks per second: one per pixel up to 200 px/s
RATE = 8000


class Peaks:
    def __init__(self, cache_dir, on_ready=None):
        self.dir = os.path.join(cache_dir, "peaks")
        os.makedirs(self.dir, exist_ok=True)
        self.on_ready = on_ready
        self.done = {}                    # path -> (peaks float32 0..1, start seconds)
        self.queue = []
        self.lock = threading.Lock()
        self.thread = None

    def get(self, path):
        """(peaks, start_s) if decoded, else None (and decoding is queued)."""
        with self.lock:
            if path in self.done:
                return self.done[path]
            if path not in self.queue:
                self.queue.append(path)
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._work, daemon=True)
                self.thread.start()
        return None

    def _work(self):
        while True:
            with self.lock:
                if not self.queue:
                    return
                path = self.queue.pop(0)
            try:
                res = self._decode(path)
            except Exception:
                res = (np.zeros(0, np.float32), 0.0)
            with self.lock:
                self.done[path] = res
            if self.on_ready:
                self.on_ready(path)

    def _decode(self, path):
        st = os.stat(path)
        name = hashlib.sha1(repr((path, st.st_size, st.st_mtime, BIN_S)).encode()).hexdigest()[:16]
        cached = os.path.join(self.dir, name + ".npy")
        start = media_start(path)
        if os.path.exists(cached):
            return np.load(cached), start
        r = subprocess.run([find_ffmpeg(), "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(RATE),
                            "-f", "s16le", "-"], capture_output=True, timeout=600)
        pcm = np.abs(np.frombuffer(r.stdout, np.int16).astype(np.float32)) / 32768.0
        n = round(RATE * BIN_S)
        pcm = pcm[: len(pcm) // n * n]
        peaks = pcm.reshape(-1, n).max(axis=1) if len(pcm) else np.zeros(0, np.float32)
        np.save(cached, peaks.astype(np.float32))
        return peaks.astype(np.float32), start


def columns(peaks, start_s, t0_s, t1_s, n):
    """Peak per column for media time t0..t1 split into n columns (0 where there is none)."""
    out = np.zeros(max(n, 0), np.float32)
    if n <= 0 or not len(peaks):
        return out
    e = (np.linspace(t0_s, t1_s, n + 1) - start_s) / BIN_S
    lo = np.floor(e[:-1]).astype(np.int64)            # columns share edges, so lo is sorted
    ok = (lo >= 0) & (lo < len(peaks))
    if not ok.any():
        return out
    end = min(max(int(np.ceil(e[-1])), int(lo[ok][-1]) + 1), len(peaks))
    out[ok] = np.maximum.reduceat(peaks[:end], lo[ok])
    return out
