"""Audio peaks for drawing waveforms on the timeline.

Each media file is decoded once (mono) into the highest and lowest sample of every BIN_S
seconds (an N x 2 array, -1..1) and cached as .npy next to the other caches. Decoding runs on a background thread; `on_ready`
is called (from that thread) when a file's peaks are available. Times are media times:
the stream's start_time (an MP3's encoder delay) is applied, as the mixer does.
"""
import hashlib
import os
import subprocess
import threading

import numpy as np

from .build import find_ffmpeg, media_start

BIN_S = 0.001                 # 1000 bins per second: one per pixel up to 1000 px/s
RATE = 24000
FORMAT = 2                    # 2: signed max / min per bin (1 was one absolute peak)


class Peaks:
    def __init__(self, cache_dir, on_ready=None):
        self.dir = os.path.join(cache_dir, "peaks")
        os.makedirs(self.dir, exist_ok=True)
        self.on_ready = on_ready
        self.done = {}                    # path -> (peaks float32 N x 2: max, min; start seconds)
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
                res = (np.zeros((0, 2), np.float32), 0.0)
            with self.lock:
                self.done[path] = res
            if self.on_ready:
                self.on_ready(path)

    def _decode(self, path):
        st = os.stat(path)
        name = hashlib.sha1(repr((path, st.st_size, st.st_mtime, BIN_S, RATE, FORMAT)).encode()).hexdigest()[:16]
        cached = os.path.join(self.dir, name + ".npy")
        start = media_start(path)
        if os.path.exists(cached):
            return np.load(cached), start
        r = subprocess.run([find_ffmpeg(), "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(RATE),
                            "-f", "s16le", "-"], capture_output=True, timeout=600)
        pcm = np.frombuffer(r.stdout, np.int16)          # (bins found on the samples: no float copy of it all)
        n = round(RATE * BIN_S)
        pcm = pcm[: len(pcm) // n * n].reshape(-1, n)
        peaks = np.stack([pcm.max(axis=1), pcm.min(axis=1)], axis=1).astype(np.float32) / 32768.0
        np.save(cached, peaks)
        return peaks, start


def columns(peaks, start_s, t0_s, t1_s, n):
    """Media time t0..t1 split into n columns: for N x 2 peaks the (highest, lowest) sample
    of each column, for one-column peaks the peak of each (0 where there is none)."""
    signed = peaks.ndim == 2
    out = np.zeros((max(n, 0), 2) if signed else max(n, 0), np.float32)
    if n > 0 and len(peaks):
        e = (np.linspace(t0_s, t1_s, n + 1) - start_s) / BIN_S
        lo = np.floor(e[:-1]).astype(np.int64)        # columns share edges, so lo is sorted
        ok = (lo >= 0) & (lo < len(peaks))
        if ok.any():
            end = min(max(int(np.ceil(e[-1])), int(lo[ok][-1]) + 1), len(peaks))
            if signed:
                out[ok, 0] = np.maximum.reduceat(peaks[:end, 0], lo[ok])
                out[ok, 1] = np.minimum.reduceat(peaks[:end, 1], lo[ok])
            else:
                out[ok] = np.maximum.reduceat(peaks[:end], lo[ok])
    return (out[:, 0], out[:, 1]) if signed else out
