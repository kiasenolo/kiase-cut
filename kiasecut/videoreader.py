"""Video pictures for the live renderer (preview and filter export), streamed by ffmpeg.

Seeking the source for every frame (what the engine does) costs far more than decoding:
playing reads a file front to back, so a reader keeps an ffmpeg process streaming raw RGBA
frames from where it last jumped to, and only a jump starts a new one. The size asked for is
rounded up to the source's size halved a whole number of times, so zooming a clip does not
restart its reader; the painter scales the rest of the way (at most 2x, so it stays clean).
Heavy codecs are decoded and scaled on the GPU when gpu.py says it can (and fall back to
the CPU if that fails).

Starting a stream takes 100-250 ms, more than the engine needs for one picture, so a
stream is only started for a request that follows on from a recent one (playing, exporting,
dragging forward); get() returns None for a jump, and when ffmpeg cannot read the file, and
the caller then asks the engine for that one picture.

Readers belong to one thread (the player's worker, or an export): each makes its own.
"""
import json
import math
import os
import subprocess
import threading

from PySide6.QtGui import QImage

from . import gpu
from .build import find_ffmpeg

US = 1_000_000
AHEAD_S = 2.0                 # a request this far after the stream's position reads on to it
FOLLOW_S = 0.5                # a request this soon after an earlier one (same file) starts a stream
MAX_STREAMS = 6
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_info = {}
_info_lock = threading.Lock()


def info(path):
    """{w, h, fps, codec, matrix, alpha} of a video file's first picture stream (cached), or None.
    matrix is the YUV -> RGB matrix: the file's own, or for an untagged file BT.709 from 720
    lines up and BT.601 below, as MLT (the engine and the export) decides. alpha: a WebM
    stream carries transparency (its alpha_mode tag)."""
    with _info_lock:
        if path in _info:
            return _info[path]
    ff = find_ffmpeg() or "ffmpeg"
    ffprobe = os.path.join(os.path.dirname(ff), os.path.basename(ff).replace("ffmpeg", "ffprobe"))
    if not os.path.exists(ffprobe):
        ffprobe = "ffprobe"
    res = None
    try:
        r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height,avg_frame_rate,r_frame_rate,codec_name,color_space:stream_tags=alpha_mode",
                            "-of", "json", path],
                           capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
        s = json.loads(r.stdout)["streams"][0]

        def rate(text):
            n, _, d = (text or "0/0").partition("/")
            return float(n) / float(d) if d and float(d) else 0.0

        fps = rate(s.get("avg_frame_rate")) or rate(s.get("r_frame_rate")) or 30.0
        tagged = s.get("color_space") not in (None, "", "unknown", "reserved")
        matrix = "auto" if tagged else ("bt709" if int(s["height"]) >= 720 else "bt601")
        res = {"w": int(s["width"]), "h": int(s["height"]), "fps": fps, "codec": s.get("codec_name", ""),
               "matrix": matrix, "alpha": (s.get("tags") or {}).get("alpha_mode") == "1"}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError):
        res = None
    with _info_lock:
        _info[path] = res
    return res


def stream_size(src_w, src_h, w, h):
    """The source size halved as often as it can be while staying at least w x h (even)."""
    k = 1
    while src_w / (k * 2) >= w and src_h / (k * 2) >= h and src_w / (k * 2) >= 16:
        k *= 2
    return max(2, round(src_w / k / 2) * 2), max(2, round(src_h / k / 2) * 2)


def alpha_decoder(inf):
    """The decoder that keeps a transparent WebM's alpha (ffmpeg's own VP8 / VP9 decoders,
    and the GPU's, drop it), or None."""
    if inf.get("alpha"):
        return {"vp8": "libvpx", "vp9": "libvpx-vp9"}.get(inf["codec"])
    return None


class Stream:
    """One ffmpeg process sending frames of `path` from start_us on, at w x h; decoder: the
    one to use instead of ffmpeg's choice (alpha_decoder)."""

    def __init__(self, path, start_us, w, h, fps, hw, matrix="auto", decoder=None):
        self.path, self.start_us, self.w, self.h, self.fps, self.hw = path, start_us, w, h, fps, hw
        self.index = -1                      # frame last read (frame i is at start_us + i / fps)
        self.image = None
        self.used = 0
        cmd = [find_ffmpeg(), "-v", "error", "-nostdin"]
        if hw:
            cmd += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
        if decoder:
            cmd += ["-c:v", decoder]
        cmd += ["-ss", f"{max(0, start_us) / US:.6f}", "-i", path, "-an", "-sn", "-dn"]
        to_rgb = f"in_color_matrix={matrix},format=rgba"
        vf = (f"scale_cuda=w={w}:h={h}:format=nv12,hwdownload,format=nv12,scale={to_rgb}" if hw
              else f"scale={w}:{h}:flags=bicubic:{to_rgb}")
        cmd += ["-vf", vf, "-fps_mode", "cfr", "-r", f"{fps:.6f}", "-f", "rawvideo", "-pix_fmt", "rgba", "-"]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     bufsize=w * h * 4 * 2, creationflags=NO_WINDOW)

    def index_of(self, us):
        return math.floor((us - self.start_us) * self.fps / US + 1e-3)

    def read_to(self, i):
        """The picture of frame i (i >= index); the last one at the end of the file; None when
        ffmpeg gave nothing at all."""
        size = self.w * self.h * 4
        while self.index < i:
            data = self.proc.stdout.read(size)
            if len(data) < size:                 # the end of the file: hold the last picture
                break
            self.index += 1
            if self.index == i:                  # (frames skipped over are not converted)
                self.image = QImage(data, self.w, self.h, self.w * 4, QImage.Format_RGBA8888).copy()
        return self.image

    def close(self):
        try:
            self.proc.kill()
            self.proc.stdout.close()
            self.proc.wait(timeout=2)
        except Exception:
            pass


class Readers:
    def __init__(self):
        self.streams = []
        self.clock = 0
        self.no_gpu = set()                  # files the GPU could not decode: CPU from then on
        self.recent = {}                     # path -> the last few source times asked for

    def get(self, path, us, w, h):
        """QImage of video `path` at source time us, at least w x h (or the source size)."""
        inf = info(path)
        if inf is None or not find_ffmpeg():
            return None
        recent = self.recent.setdefault(path, [])
        follows = any(0 < us - t <= FOLLOW_S * US for t in recent)
        recent.append(us)
        del recent[:-4]
        sw, sh = stream_size(inf["w"], inf["h"], w, h)
        self.clock += 1
        best = None
        for s in self.streams:
            if s.path == path and (s.w, s.h) == (sw, sh):
                i = s.index_of(us)
                if s.index <= i <= s.index + AHEAD_S * s.fps and (s.index >= 0 or i >= 0):
                    if best is None or i - s.index < best[1] - best[0].index:
                        best = (s, i)
        if best is not None:
            s, i = best
            img = s.read_to(i) if i > s.index else s.image
            if img is not None:
                s.used = self.clock
                return img
        if not follows:                          # a jump: the engine is quicker for one picture
            return None
        return self._start(path, us, sw, sh, inf)

    def _start(self, path, us, w, h, inf):
        decoder = alpha_decoder(inf)
        hw = not decoder and path not in self.no_gpu and gpu.decode_on_gpu(inf["codec"])
        while len(self.streams) >= MAX_STREAMS:
            old = min(self.streams, key=lambda s: s.used)
            old.close()
            self.streams.remove(old)
        s = Stream(path, us, w, h, inf["fps"], hw, inf["matrix"], decoder)
        img = s.read_to(0)
        if img is None:
            s.close()
            if hw:                               # the card could not: the CPU does it from now on
                self.no_gpu.add(path)
                return self._start(path, us, w, h, inf)
            return None
        s.used = self.clock
        self.streams.append(s)
        return img

    def close(self):
        for s in self.streams:
            s.close()
        self.streams.clear()
