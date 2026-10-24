"""Export through the live renderer (the same picture as the preview), for projects with filters.

The MLT export (build.py) cannot run GLSL filters, blend modes, keyframed mask shapes /
inverts or static clips, so a project that uses any of them is rendered here:
every frame is drawn by render.Renderer (filters run on the GPU), piped to ffmpeg together
with the mixed sound (audiomix.Mixer, as in the preview). Runs on a worker thread.
"""
import os
import subprocess
import time
import wave

from PySide6.QtGui import QImage

from . import audiomix, curves, gpu, project, render, videoreader
from .build import find_ffmpeg

US = 1_000_000


def _blend_or_mask_keys(c):
    """Whether a clip has a blend mode, or a mask whose shape or invert has keyframes (a
    keyframed font MLT can do: build.py renders such a text frame by frame)."""
    if curves.is_animated(c.get("blend")) or c.get("blend", "normal") != "normal":
        return True
    m = c.get("mask") or {}
    return curves.is_animated(m.get("kind")) or curves.is_animated(m.get("invert"))


def needs_renderer(proj):
    """Whether the project needs this export rather than MLT's: a clip has an effect, is a
    filter clip or a static clip, has a blend mode or a keyframed mask shape / invert."""
    return any(c["type"] == "filter" or c.get("effects") or project.is_static(c) or _blend_or_mask_keys(c)
               for c in project.all_clips(proj))


def export(proj, out, size, fps, first, last, opts, on_progress=None, cache_dir=None, cancelled=lambda: False):
    """Render frames first..last (inclusive, at `fps`) of the project to the file out.
    size: (width, height). opts: crf, preset (as the export dialog gives them)."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("找不到 ffmpeg")
    W, H = size
    view = dict(proj, fps=float(fps), width=proj["width"], height=proj["height"])
    cache = cache_dir or os.path.dirname(out)
    os.makedirs(cache, exist_ok=True)
    t0 = time.time()
    total = last - first + 1

    wav = os.path.join(cache, "export-sound.wav")
    mix = audiomix.Mixer(cache)
    mix.set_view(view)
    while mix.thread is not None and mix.thread.is_alive():       # decode every source first
        mix.thread.join(0.2)
        if cancelled():
            raise RuntimeError("已取消")
    with wave.open(wav, "wb") as wf:
        wf.setnchannels(audiomix.CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(audiomix.RATE)
        for f in range(first, last + 1):
            wf.writeframes(mix.mix(f, fps))

    engine = None
    readers = videoreader.Readers()          # an export reads every video front to back: streamed

    def video(path, us, w, h):
        nonlocal engine
        img = readers.get(path, us, w, h)
        if img is not None:
            return img
        if engine is None:
            from .client import EngineClient
            engine = EngineClient(CAP_W, CAP_H)
        k = min(1.0, (CAP_W * CAP_H / max(1, w * h)) ** 0.5)       # never more than the shared buffer holds
        px, rw, rh = engine.media_frame(path, us, fps, max(1, int(w * k)), max(1, int(h * k)))
        return QImage(px, rw, rh, rw * 4, QImage.Format_RGBA8888).copy()

    CAP_W, CAP_H = max(W, 3840), max(H, 2160)      # (the engine sends pictures at their own size)
    renderer = render.Renderer(video)
    cmd = [ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-r", f"{fps:g}",
           "-i", "-", "-i", wav, "-map", "0:v", "-map", "1:a", *gpu.ffmpeg_video_args(opts, (W, H)),
           "-c:a", "aac", "-b:a", "320k", "-shortest", "-movflags", "+faststart", out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for i, f in enumerate(range(first, last + 1)):
            if cancelled():
                raise RuntimeError("已取消")
            img = renderer.render(view, f, W, H)
            img = img.convertToFormat(QImage.Format_RGBA8888)
            proc.stdin.write(bytes(img.constBits())[: W * H * 4])
            if on_progress and i % 2 == 0:
                on_progress((i + 1) / total)
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg：{err.strip()[-400:]}")
    except Exception:
        proc.kill()
        raise
    finally:
        readers.close()
        if engine is not None:
            engine.close()
        try:
            os.remove(wav)
        except OSError:
            pass
    if renderer.errors:
        errors = sorted(set(renderer.errors))[:5]
    else:
        errors = []
    return {"done": out, "elapsed": time.time() - t0, "errors": errors,
            "encoder": "NVENC (GPU)" if gpu.nvenc_for((W, H)) else "x264 (CPU)"}
