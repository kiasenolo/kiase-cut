"""Preview audio: decode each sounding clip's source range once, mix per frame.

Follows the export rules (build.py / MLT): a clip plays source time source_start + t,
volume and fades apply as in build.Builder.audio, and an MP3's start_time (encoder delay)
shifts its sound later. A clip with a speed (project.speed) plays its source faster or slower
- resampled, so the pitch follows, as a tape would (with 保持音高, clip["keep_pitch"], it is
time-stretched once at its own pitch instead: stretch.stretch_all) - and so does everything inside a compound
clip with a speed; a frozen clip (凍結幀) is silent. Decoding runs in a background thread; clips not decoded yet are
silent until they are.
"""
import hashlib
import os
import subprocess
import threading

import numpy as np

from . import curves, normalize, project, stretch
from .build import audio_stream, find_ffmpeg, media_start

RATE, CHANNELS = 48000, 2
US = 1_000_000


class Source:
    def __init__(self, clip, start_us, win, gain=1.0, rate=1.0):
        self.clip = clip
        self.gain = gain                      # track gains (and mute / solo) above it
        self.start_us = start_us              # clip start on the mixed timeline
        self.rate = rate                      # clip time per mixed time (compounds with a speed above it)
        self.win = win                        # (lo, hi) us where it may sound
        self.pcm = None                       # int16 [n, 2] once decoded
        self.offset = 0                       # samples of leading silence (encoder delay)
        sp = project.speed(clip)
        self.pitched = bool(clip.get("keep_pitch")) and abs(sp - 1.0) > 1e-9 and not clip.get("speed_curve")

    def key(self):
        return key_of(self.clip)

    def dkey(self):
        """What its decoded sound is kept under: the source range, and with 保持音高 the speed it
        was stretched to (that sound is already at the clip's pace)."""
        return self.key() + (("pitch", project.speed(self.clip)) if self.pitched else ())


def key_of(c):
    """(file, first source us, source us decoded, sound stream): the source range clip c plays."""
    return (c["media"]["path"], c.get("source_start_us", 0), round(c["duration_us"] * project.speed(c)),
            audio_stream(c))


def decode(cache_dir, key):
    """(int16 [n, 2] pcm, samples of leading silence) of a source range (key_of), decoded once
    into the cache's audio folder."""
    folder = os.path.join(cache_dir, "audio")
    path, src_us, dur_us, stream = key
    st = os.stat(path)
    name = hashlib.sha1(repr((path, st.st_size, st.st_mtime, src_us, dur_us)
                             + ((stream,) if stream else ())).encode()).hexdigest()[:16]
    cached = os.path.join(folder, name + ".npy")
    lead = media_start(path, stream)                    # the stream's first sample time
    offset = max(0, round((lead - src_us / US) * RATE))
    if os.path.exists(cached):
        return np.load(cached), offset
    start = max(src_us / US, lead)
    r = subprocess.run([find_ffmpeg(), "-v", "error", "-ss", f"{start:.6f}", "-t", f"{dur_us / US + 0.1:.6f}",
                        "-i", path, "-map", f"0:a:{stream}", "-vn", "-f", "s16le", "-ac", str(CHANNELS), "-ar", str(RATE), "-"],
                       capture_output=True, timeout=120 + dur_us / US / 5)   # (an hour off a USB drive)
    if r.returncode != 0 and not r.stdout:
        raise RuntimeError(r.stderr.decode(errors="replace")[-300:])
    pcm = np.frombuffer(r.stdout, np.int16)
    pcm = pcm[: len(pcm) // CHANNELS * CHANNELS].reshape(-1, CHANNELS).copy()
    os.makedirs(folder, exist_ok=True)                  # (the project's cache may have been cleared)
    np.save(cached, pcm)
    return pcm, offset


def sources(tracks, offset_us=0, win=(0, float("inf")), gain=1.0, only=None, rate=1.0, level=()):
    """Every clip that makes sound, compound clips included, with its timeline placement.
    only: one of tracks, to hear that track alone (as it sounds in the mix: an export's stem);
    level: the tracks 參考 tracks sound on (project.level_tracks).
    Inside a compound clip with a speed, its content's time runs rate times the mix's: a clip
    at content time s sounds at offset_us + s / rate."""
    out = []
    for tr in tracks:
        if only is not None and tr is not only:
            continue
        g = gain * project.sounds(tr, tracks, level)
        if g <= 0:
            continue
        for c in tr["clips"]:
            s = offset_us + c["start_us"] / rate
            e = s + c["duration_us"] / rate
            lo, hi = max(s, win[0]), min(e, win[1])
            if hi <= lo or project.frozen(c) is not None:            # (a frozen clip is silent)
                continue
            if c["type"] in ("audio", "video") and c.get("media"):
                out.append(Source(c, s, (lo, hi), g, rate))
            elif project.is_group(c):                                    # a group's clips: in its time
                out += sources(c["tracks"], s, (lo, hi), g, rate=rate, level=level)
            elif c["type"] == "compound" and not project.is_static(c):     # a static one is a picture
                inner = rate * project.speed(c)
                out += sources(c["compound"]["tracks"], s - c.get("source_start_us", 0) / inner, (lo, hi), g,
                               rate=inner)
    return out


class Mixer:
    def __init__(self, cache_dir):
        self.cache_dir = cache_dir
        self.dir = os.path.join(cache_dir, "audio")
        os.makedirs(self.dir, exist_ok=True)
        self.decoded = {}                     # key -> (pcm, offset)
        self.sources = []
        self.lock = threading.Lock()
        self.queue = []
        self.thread = None
        self.master = 1.0                     # the project's master volume

    def set_view(self, view, only=None):
        """only: one of the view's tracks, to mix that track alone."""
        self.master = float(view.get("master_gain", 1.0))
        srcs = sources(view["tracks"], only=only, level=project.level_tracks(view))
        with self.lock:
            for s in srcs:
                if s.dkey() in self.decoded:
                    s.pcm, s.offset = self.decoded[s.dkey()]
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
                if s.dkey() in self.decoded:
                    s.pcm, s.offset = self.decoded[s.dkey()]
                    continue
            try:
                pcm, offset = self._decode(s)
            except Exception:                           # silent for now; the next set_view tries again
                with self.lock:
                    s.pcm, s.offset = np.zeros((0, CHANNELS), np.int16), 0
                continue
            normalize.remember(s.key(), pcm)
            if s.pitched:                               # 保持音高: stretched to the clip's pace once
                sp = project.speed(s.clip)
                pcm, offset = stretch.stretch_all(pcm, sp), round(offset / sp)
            with self.lock:
                self.decoded[s.dkey()] = (pcm, offset)
                for o in self.sources:
                    if o.dkey() == s.dkey():
                        o.pcm, o.offset = pcm, offset

    def _decode(self, s):
        return decode(self.cache_dir, s.key())

    def mix(self, frame, fps):
        """PCM bytes (s16 stereo) for one frame."""
        a = round(frame * RATE / fps)
        b = round((frame + 1) * RATE / fps)
        with self.lock:
            srcs = list(self.sources)
        acc = mix_window(srcs, b - a, frame / fps * US, self.master)
        return np.clip(acc, -32768, 32767).astype(np.int16).tobytes()


def mix_window(srcs, n, t_us, master=1.0):
    """n samples (float32 [n, 2], not clipped) of the decoded sources srcs starting at mixed
    time t_us: volumes, fades, speeds and 標準化 as the clips sound."""
    acc = np.zeros((n, CHANNELS), np.float32)
    t_frame = t_us
    for s in srcs:
        if s.pcm is None or not (s.win[0] <= t_frame < s.win[1]):
            continue
        c = s.clip
        t = (t_frame - s.start_us) * s.rate         # time into the clip
        g = curves.value(c.get("volume", 1.0), t) * s.gain
        if normalize.target(c) is not None:         # 標準化: on top of 音量
            g *= normalize.gain_of(c, normalize.peak(s.key(), s.pcm))
        fi, fo, dur = c.get("fade_in_us", 0), c.get("fade_out_us", 0), c["duration_us"]
        if fi and t < fi:
            g *= max(0.0, t / fi)
        if fo and t > dur - fo:
            g *= max(0.0, (dur - t) / fo)
        if g <= 0:
            continue
        sp = 1.0 if s.pitched else project.speed(c)    # (保持音高: decoded at the clip's pace already)
        step = s.rate * sp                          # source samples per mixed sample
        if c.get("speed_curve"):                    # 曲線變速: each sample where the curve has got to
            pos = project.curve_source_offsets(c, t + np.arange(n) * s.rate * US / RATE) / US * RATE - s.offset
            ok = (pos >= 0) & (pos < len(s.pcm) - 1)
            if ok.any():
                i = pos[ok].astype(np.int64)
                f = (pos[ok] - i)[:, None]
                acc[ok] += (s.pcm[i] * (1 - f) + s.pcm[i + 1] * f) * g
        elif abs(step - 1.0) < 1e-9:
            i0 = round(t * sp / US * RATE) - s.offset    # sample index into the decoded range
            lo, hi = max(i0, 0), min(i0 + n, len(s.pcm))
            if hi > lo:
                acc[lo - i0:hi - i0] += s.pcm[lo:hi] * g
        else:                                       # faster / slower: resampled (pitch follows)
            pos = t * sp / US * RATE - s.offset + np.arange(n) * step
            ok = (pos >= 0) & (pos < len(s.pcm) - 1)
            if ok.any():
                i = pos[ok].astype(np.int64)
                f = (pos[ok] - i)[:, None]
                acc[ok] += (s.pcm[i] * (1 - f) + s.pcm[i + 1] * f) * g
    return acc * master


def stem_tracks(view):
    """The tracks heard in the mix (not muted, not silenced by another's solo) that have a
    clip making sound: one stem file each."""
    return [tr for tr in view["tracks"] if project.sounds(tr, view["tracks"]) > 0 and sources([tr])]
