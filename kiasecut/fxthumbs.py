"""Filter thumbnails, made by a process of their own (python -m kiasecut.fxthumbs).

The first compile of a big filter (a Blender export can be thousands of lines) can take the
graphics driver half a minute, and moderngl holds Python's lock all that time, so even a thread
would freeze the window. A process does not; and what the driver compiled stays in its disk
cache, so the preview later gets the same filter quickly.

Protocol: the UI writes one filter ref per line on stdin; for each, the process writes
width, height (uint32, little-endian) and that many RGBA8 premultiplied pixels on stdout
(0 x 0 when the filter could not run). A line "anim<TAB>ref" asks for the filter moving instead:
ANIM_FRAMES pictures, one after the other, of the moments 0, 1/ANIM_FPS, 2/ANIM_FPS ... s
(what a filter that changes with time does). Worker() is the UI's end.
"""
import os
import struct
import subprocess
import sys

import numpy as np

from . import fx

HEADER = struct.Struct("<II")
ANIM_FRAMES, ANIM_FPS = 24, 12            # (2 seconds, as the thumbnail is shown on hover)


def sample_picture(w=160, h=90):
    """A small picture to show what a filter does: colour ramp, a disc, a square and stripes
    (premultiplied RGBA, uint8)."""
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.zeros((h, w, 4), np.float32)
    img[..., 0] = 255 * x / w
    img[..., 1] = 90 + 60 * y / h
    img[..., 2] = 255 * (1 - x / w)
    img[..., 3] = 255
    disc = (x - w * 0.55) ** 2 + (y - h * 0.5) ** 2 < (h * 0.3) ** 2
    img[disc] = (255, 220, 40, 255)
    img[int(h * 0.15):int(h * 0.4), int(w * 0.08):int(w * 0.25)] = (20, 200, 90, 255)
    img[int(h * 0.8):int(h * 0.86), :] = 255
    return img.round().astype(np.uint8)


def thumbnail(engine, ref, moment=None):
    """The filter at its default settings over sample_picture(), or None; moment: the time in
    seconds (the default one for the still thumbnail)."""
    d = fx.get(ref)
    if d.error:
        return None
    vals = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
    if moment is not None:                                               # (a "每格不同" switch is on, to show it move)
        vals.update({p.name: True for p in d.params if p.type == "bool" and p.name == "animated"})
    pic = sample_picture()
    unit = pic.shape[0] / 1080                                           # (as on a 1080p canvas)
    if moment is None:
        return engine.run(d, vals, pic, time=0.7, progress=0.5, frame=17, unit=unit)
    return engine.run(d, vals, pic, time=moment, progress=min(1.0, moment / 2), frame=round(moment * 30), unit=unit)


def animation(engine, ref):
    """ANIM_FRAMES pictures of the filter over time, or None; [] when it looks the same all the time."""
    frames = [thumbnail(engine, ref, i / ANIM_FPS) for i in range(ANIM_FRAMES)]
    if frames[0] is None:
        return None
    return frames if any(not np.array_equal(frames[0], f) for f in frames[1:]) else []


class Worker:
    """The thumbnail process, seen from the UI: make(ref) -> RGBA array or None. Raises
    OSError when the process is gone (no OpenGL, or it crashed)."""

    def __init__(self):
        env = dict(os.environ)
        pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env["PYTHONPATH"] = pkg_root + os.pathsep + env.get("PYTHONPATH", "")
        # built for Windows (no console), this program has no stderr to pass on: printing a
        # failure there (no OpenGL, say) raised, and the launcher showed it in a window
        err = subprocess.DEVNULL if getattr(sys, "frozen", False) and sys.platform == "win32" else None
        self.proc = subprocess.Popen([sys.executable, "-m", "kiasecut.fxthumbs"], env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def _read(self, n):
        data = b""
        while len(data) < n:
            part = self.proc.stdout.read(n - len(data))
            if not part:
                raise OSError("filter thumbnail process ended")
            data += part
        return data

    def make(self, ref):
        self.proc.stdin.write(ref.encode("utf-8") + b"\n")
        self.proc.stdin.flush()
        w, h = HEADER.unpack(self._read(HEADER.size))
        if not w or not h:
            return None
        return np.frombuffer(self._read(w * h * 4), np.uint8).reshape(h, w, 4)

    def make_anim(self, ref):
        """The filter moving: a list of RGBA arrays, [] when it does not change, None when it cannot run."""
        self.proc.stdin.write(b"anim\t" + ref.encode("utf-8") + b"\n")
        self.proc.stdin.flush()
        w, h = HEADER.unpack(self._read(HEADER.size))
        if not w or not h:
            return None
        n = struct.unpack("<I", self._read(4))[0]
        return [np.frombuffer(self._read(w * h * 4), np.uint8).reshape(h, w, 4) for _ in range(n)]

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass


def main():
    out = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)                        # anything a library prints goes to stderr, not into the pictures
    try:
        engine = fx.Engine()
    except fx.FilterError as exc:
        print(exc, file=sys.stderr)
        return 1
    for line in sys.stdin.buffer:
        ref = line.rstrip(b"\r\n").decode("utf-8")
        if ref.startswith("anim\t"):
            try:
                frames = animation(engine, ref[5:])
            except Exception as exc:
                print(f"{ref}: {exc}", file=sys.stderr)
                frames = None
            if frames is None:
                out.write(HEADER.pack(0, 0))
            else:
                h, w = (frames[0] if frames else sample_picture()).shape[:2]
                out.write(HEADER.pack(w, h) + struct.pack("<I", len(frames)) +
                          b"".join(np.ascontiguousarray(f).tobytes() for f in frames))
            out.flush()
            continue
        try:
            img = thumbnail(engine, ref)
        except Exception as exc:
            print(f"{ref}: {exc}", file=sys.stderr)
            img = None
        if img is None:
            out.write(HEADER.pack(0, 0))
        else:
            h, w = img.shape[:2]
            out.write(HEADER.pack(w, h) + np.ascontiguousarray(img).tobytes())
        out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
