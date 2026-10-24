"""Export through the live renderer (the same picture as the preview), for projects with filters.

The MLT export (build.py) cannot run GLSL filters, so a project that uses any is rendered here:
every frame is drawn by render.Renderer (filters run on the GPU), piped to ffmpeg together
with the mixed sound (audiomix.Mixer, as in the preview). Runs on a worker thread.
"""
import os
import subprocess
import time
import wave

from PySide6.QtGui import QImage

from . import audiomix, project, render
from .build import find_ffmpeg

US = 1_000_000


def uses_filters(proj):
    """Whether any clip of the project has an effect, or is a filter clip."""
    return any(c["type"] == "filter" or c.get("effects") for c in project.all_clips(proj))


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

    def video(path, us, w, h):
        nonlocal engine
        if engine is None:
            from .client import EngineClient
            engine = EngineClient(CAP_W, CAP_H)
        k = min(1.0, (CAP_W * CAP_H / max(1, w * h)) ** 0.5)       # never more than the shared buffer holds
        px, rw, rh = engine.media_frame(path, us, fps, max(1, int(w * k)), max(1, int(h * k)))
        return QImage(px, rw, rh, rw * 4, QImage.Format_RGBA8888).copy()

    CAP_W, CAP_H = max(W, 1920), max(H, 1080)
    renderer = render.Renderer(video)
    cmd = [ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-r", f"{fps:g}",
           "-i", "-", "-i", wav, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-crf", str(opts.get("crf", 18)),
           "-preset", opts.get("preset", "medium"), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k",
           "-shortest", "-movflags", "+faststart", out]
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
    return {"done": out, "elapsed": time.time() - t0, "errors": errors}
