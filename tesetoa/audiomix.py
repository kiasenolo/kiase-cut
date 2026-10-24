"""Preview audio: decode each sounding clip's source range once, mix per frame.

Follows the export rules (build.py / MLT): a clip plays source time source_start + t,
volume and fades apply as in build.Builder.audio, and an MP3's start_time (encoder delay)
shifts its sound later. Decoding runs in a background thread; clips not decoded yet are
silent until they are.
"""
import hashlib
import os
import subprocess
import threading

import numpy as np

from . import curves, project
from .build import find_ffmpeg, media_start

RATE, CHANNELS = 48000, 2
US = 1_000_000


class Source:
    def __init__(self, clip, start_us, win, gain=1.0):
        self.clip = clip
        self.gain = gain                      # track gains (and mute / solo) above it
        self.start_us = start_us              # clip start on the mixed timeline
        self.win = win                        # (lo, hi) us where it may sound
        self.pcm = None                       # int16 [n, 2] once decoded
        self.offset = 0                       # samples of leading silence (encoder delay)

    def key(self):
        c = self.clip
        return (c["media"]["path"], c.get("source_start_us", 0), c["duration_us"])


def sources(tracks, offset_us=0, win=(0, float("inf")), gain=1.0):
    """Every clip that makes sound, compound clips included, with its timeline placement."""
    out = []
    for tr in tracks:
        g = gain * project.sounds(tr, tracks)
        if g <= 0:
            continue
        for c in tr["clips"]:
            s = offset_us + c["start_us"]
            e = s + c["duration_us"]
            lo, hi = max(s, win[0]), min(e, win[1])
            if hi <= lo:
                continue
            if c["type"] in ("audio", "video") and c.get("media"):
                out.append(Source(c, s, (lo, hi), g))
            elif c["type"] == "compound":
                out += sources(c["compound"]["tracks"], s - c.get("source_start_us", 0), (lo, hi), g)
    return out


class Mixer:
    def __init__(self, cache_dir):
        self.dir = os.path.join(cache_dir, "audio")
        os.makedirs(self.dir, exist_ok=True)
        self.decoded = {}                     # key -> (pcm, offset)
        self.sources = []
        self.lock = threading.Lock()
        self.queue = []
        self.thread = None
        self.master = 1.0                     # the project's master volume

    def set_view(self, view):
        self.master = float(view.get("master_gain", 1.0))
        srcs = sources(view["tracks"])
        with self.lock:
            for s in srcs:
                if s.key() in self.decoded:
                    s.pcm, s.offset = self.decoded[s.key()]
            self.sources = srcs
            self.queue = [s for s in srcs if s.pcm is None]
        if self.queue and (self.thread is None or not self.thread.is_alive()):
            self.thread = threading.Thread(target=self._decode_all, daemon=True)
            self.thread.start()

    def _decode_all(self):
        while True:
            with self.lock:
                if not self.queue:
                    return
                s = self.queue.pop(0)
                if s.key() in self.decoded:
                    s.pcm, s.offset = self.decoded[s.key()]
                    continue
            try:
                pcm, offset = self._decode(s)
            except Exception:
                pcm, offset = np.zeros((0, CHANNELS), np.int16), 0
            with self.lock:
                self.decoded[s.key()] = (pcm, offset)
                for o in self.sources:
                    if o.key() == s.key():
                        o.pcm, o.offset = pcm, offset

    def _decode(self, s):
        path, src_us, dur_us = s.key()
        st = os.stat(path)
        name = hashlib.sha1(repr((path, st.st_size, st.st_mtime, src_us, dur_us)).encode()).hexdigest()[:16]
        cached = os.path.join(self.dir, name + ".npy")
        lead = media_start(path)                        # the stream's first sample time
        offset = max(0, round((lead - src_us / US) * RATE))
        if os.path.exists(cached):
            return np.load(cached), offset
        start = max(src_us / US, lead)
        r = subprocess.run([find_ffmpeg(), "-v", "error", "-ss", f"{start:.6f}", "-t", f"{dur_us / US + 0.1:.6f}",
                            "-i", path, "-vn", "-f", "s16le", "-ac", str(CHANNELS), "-ar", str(RATE), "-"],
                           capture_output=True, timeout=120)
        pcm = np.frombuffer(r.stdout, np.int16).reshape(-1, CHANNELS).copy()
        np.save(cached, pcm)
        return pcm, offset

    def mix(self, frame, fps):
        """PCM bytes (s16 stereo) for one frame."""
        a = round(frame * RATE / fps)
        b = round((frame + 1) * RATE / fps)
        n = b - a
        acc = np.zeros((n, CHANNELS), np.float32)
        t_frame = frame / fps * US
        with self.lock:
            srcs = list(self.sources)
        for s in srcs:
            if s.pcm is None or not (s.win[0] <= t_frame < s.win[1]):
                continue
            c = s.clip
            t = t_frame - s.start_us                    # time into the clip
            g = curves.value(c.get("volume", 1.0), t) * s.gain
            fi, fo, dur = c.get("fade_in_us", 0), c.get("fade_out_us", 0), c["duration_us"]
            if fi and t < fi:
                g *= max(0.0, t / fi)
            if fo and t > dur - fo:
                g *= max(0.0, (dur - t) / fo)
            if g <= 0:
                continue
            i0 = round(t / US * RATE) - s.offset        # sample index into the decoded range
            lo, hi = max(i0, 0), min(i0 + n, len(s.pcm))
            if hi > lo:
                acc[lo - i0:hi - i0] += s.pcm[lo:hi] * g
        return np.clip(acc * self.master, -32768, 32767).astype(np.int16).tobytes()
