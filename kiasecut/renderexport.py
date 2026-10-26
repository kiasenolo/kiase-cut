"""Export through the live renderer (the same picture as the preview), for projects with filters.

The MLT export (build.py) cannot run GLSL filters, blend modes, keyframed mask shapes /
inverts or static clips, so a project that uses any of them is rendered here:
every frame is drawn by render.Renderer (filters run on the GPU), piped to ffmpeg together
with the mixed sound (audiomix.Mixer, as in the preview). Runs on a worker thread.

Every export format but MP4 / H.264 comes here too (formats.py): HEVC, ProRes, transparent
MOVs, WebM, GIF, picture sequences, sound alone; and the stems: each track's sound in a
file of its own, or as one more sound stream of the video.
"""
import os
import subprocess
import time
import wave

from PySide6.QtGui import QImage

from . import assets, audiomix, curves, formats, glrender, gpu, project, render, videoreader
from .build import find_ffmpeg

US = 1_000_000
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _blend_or_mask_keys(c):
    """Whether a clip has a blend mode, or a mask whose shape or invert has keyframes (a
    keyframed font MLT can do: build.py renders such a text frame by frame)."""
    if curves.is_animated(c.get("blend")) or c.get("blend", "normal") != "normal":
        return True
    m = c.get("mask") or {}
    return curves.is_animated(m.get("kind")) or curves.is_animated(m.get("invert")) or m.get("kind") == "compound"


def needs_renderer(proj):
    """Whether the project needs this export rather than MLT's: a clip has an effect, is a
    filter clip or a static clip, has a blend mode, a keyframed mask shape / invert or a
    compound mask, or is a built-in asset with keyframes or an outline reaching out of its frame."""
    return any(c["type"] == "filter" or c.get("effects") or project.is_static(c) or _blend_or_mask_keys(c)
               or assets.animated(c.get("asset")) or (c.get("asset") and assets.overflow(assets.at(c["asset"], 0)))
               for c in project.all_clips(proj))


def uses_mlt(spec):
    """Whether an export with these advanced settings (export()'s spec) can go through MLT:
    MP4 / H.264 with the mixed sound, no transparency, no extra sound streams. Stem files
    are written next to it by stems()."""
    return (spec.get("format", formats.DEFAULT) == "mp4_h264" and spec.get("audio", True)
            and not spec.get("alpha") and not spec.get("multitrack"))


# -- sound ------------------------------------------------------------------------------------------
def _sound(mix, view, path, fps, first, last, cancelled, only=None, on_progress=None):
    """Write frames first..last of the view's sound (only: one track's alone) to a WAV file."""
    mix.set_view(view, only)
    while mix.thread is not None and mix.thread.is_alive():       # decode every source first
        mix.thread.join(0.2)
        if cancelled():
            raise RuntimeError("已取消")
    total = last - first + 1
    with wave.open(path, "wb") as wf:
        wf.setnchannels(audiomix.CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(audiomix.RATE)
        for i, f in enumerate(range(first, last + 1)):
            wf.writeframes(mix.mix(f, fps))
            if on_progress and i % 50 == 0:
                on_progress((i + 1) / total)


def _safe(name):
    """A name Windows accepts as a file name."""
    return "".join("_" if ch in '<>:"/\\|?*' or ord(ch) < 32 else ch for ch in name).strip(" .") or "track"


def track_names(tracks):
    """A file name for each stem track: its place among them and its name."""
    return [f"{n + 1:02d} {_safe(tr.get('name') or tr['kind'])}" for n, tr in enumerate(tracks)]


def stems_dir(out):
    """The folder the stem files of the export out go to, next to it."""
    return os.path.splitext(out)[0] + " - 分軌"


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg：{r.stderr.decode(errors='replace').strip()[-400:]}")


def _stem_wavs(mix, view, cache, fps, first, last, cancelled):
    """[(name, WAV path)]: the sound of each track heard in the mix."""
    tracks = audiomix.stem_tracks(view)
    wavs = []
    for name, tr in zip(track_names(tracks), tracks):
        wav = os.path.join(cache, f"export-stem-{len(wavs)}.wav")
        wavs.append((name, wav))
        _sound(mix, view, wav, fps, first, last, cancelled, only=tr)
    return wavs


def _encode_stems(wavs, out, ext):
    """The stem WAVs [(name, path)] as ext files in out's stems folder; their paths."""
    folder = stems_dir(out)
    os.makedirs(folder, exist_ok=True)
    done = []
    for name, wav in wavs:
        dst = os.path.join(folder, f"{name}.{ext}")
        _run([find_ffmpeg(), "-y", "-v", "error", "-i", wav, *formats.audio_args(formats.stem_codec(ext)), dst])
        done.append(dst)
    return done


def _remove(paths):
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass


def stems(proj, out, fps, first, last, ext, cache_dir=None, cancelled=lambda: False):
    """Each sounding track's sound, frames first..last, as an ext file in out's stems folder
    (after an export that went through MLT); their paths."""
    view = dict(proj, fps=float(fps))
    cache = cache_dir or os.path.dirname(out)
    os.makedirs(cache, exist_ok=True)
    wavs = []
    try:
        wavs = _stem_wavs(audiomix.Mixer(cache), view, cache, fps, first, last, cancelled)
        return _encode_stems(wavs, out, ext)
    finally:
        _remove([w for _, w in wavs])


# -- the export -------------------------------------------------------------------------------------
def export(proj, out, size, fps, first, last, opts, on_progress=None, cache_dir=None, cancelled=lambda: False,
           spec=None):
    """Render frames first..last (inclusive, at `fps`) of the project to the file out.
    size: (width, height). opts: crf, preset (as the export dialog gives them).
    spec: the advanced settings {format: a formats.py key, alpha: a transparent background,
    audio: the mixed sound in the file, stems: None or the extension of a file per track,
    multitrack: each track's sound as one more sound stream}; None: MP4 / H.264 with sound."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("找不到 ffmpeg")
    spec = dict({"format": formats.DEFAULT, "audio": True}, **(spec or {}))
    fmt = formats.get(spec["format"])
    view = dict(proj, fps=float(fps), width=proj["width"], height=proj["height"])
    cache = cache_dir or os.path.dirname(out)
    os.makedirs(cache, exist_ok=True)
    t0 = time.time()
    progress = on_progress or (lambda p: None)

    mix = audiomix.Mixer(cache)
    wav, stem_wavs, temps = None, [], []
    try:
        if fmt.audio and (spec["audio"] or not fmt.has_video):
            wav = os.path.join(cache, "export-sound.wav")
            temps.append(wav)
            _sound(mix, view, wav, fps, first, last, cancelled, on_progress=None if fmt.has_video else progress)
        multitrack = bool(spec.get("multitrack")) and fmt.multitrack
        if spec.get("stems") or multitrack:
            stem_wavs = _stem_wavs(mix, view, cache, fps, first, last, cancelled)
            temps += [w for _, w in stem_wavs]
        if fmt.has_video:
            sounds = ([("混音", wav)] if wav else []) + (stem_wavs if multitrack else [])
            errors = _pictures(view, out, fmt, bool(spec.get("alpha")) and fmt.can_alpha, size, fps, first, last,
                               opts, sounds, progress, cancelled)
            encoder = formats.encoder_name(fmt, size)
        else:
            _run([ffmpeg, "-y", "-v", "error", "-i", wav, *formats.audio_args(fmt.audio), out])
            errors, encoder = [], formats.encoder_name(fmt, size)
        files = _encode_stems(stem_wavs, out, spec["stems"]) if spec.get("stems") else []
    finally:
        _remove(temps)
    return {"done": sequence_dir(out) if fmt.kind == "sequence" else out, "elapsed": time.time() - t0,
            "errors": errors, "encoder": encoder, "stems": files}


def sequence_dir(out):
    """The folder a picture sequence export out is written to."""
    return os.path.splitext(out)[0]


def _pictures(view, out, fmt, alpha, size, fps, first, last, opts, sounds, progress, cancelled):
    """Draw frames first..last and pipe them to ffmpeg with the sound streams sounds
    [(title, WAV path)], encoded as fmt; the clips the renderer could not draw."""
    W, H = size
    total = last - first + 1
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
    renderer = glrender.make(video) if gpu.enabled else render.Renderer(video)

    inputs, maps = [], [] if fmt.kind == "gif" else ["-map", "0:v"]       # (GIF's filter graph names its output)
    audio = ["-an"]
    if sounds:
        audio = formats.audio_args(fmt.audio) + ["-shortest"]
        for i, (title, path) in enumerate(sounds):
            inputs += ["-i", path]
            maps += ["-map", f"{i + 1}:a"]
            audio += [f"-metadata:s:a:{i}", f"title={title}",            # (MKV / WebM show the title,
                      f"-metadata:s:a:{i}", f"handler_name={title}"]     # MOV / MP4 the handler name)
    target = out
    if fmt.kind == "sequence":
        folder = sequence_dir(out)
        os.makedirs(folder, exist_ok=True)
        target = os.path.join(folder, os.path.basename(folder) + "_%05d.png")
    container = ["-movflags", "+faststart"] if fmt.ext in (".mp4", ".mov") else []
    cmd = [find_ffmpeg(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}",
           "-r", f"{fps:g}", "-i", "-", *inputs, *maps, *formats.video_args(fmt, opts, (W, H), alpha), *audio,
           *container, target]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    try:
        for i, f in enumerate(range(first, last + 1)):
            if cancelled():
                raise RuntimeError("已取消")
            img = renderer.render(view, f, W, H, alpha=alpha)
            img = img.convertToFormat(QImage.Format_RGBA8888)          # (straight alpha for ffmpeg)
            proc.stdin.write(bytes(img.constBits())[: W * H * 4])
            if i % 2 == 0:
                progress((i + 1) / total)
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg：{err.strip()[-400:]}")
    except Exception:
        proc.kill()
        raise
    finally:
        proc.stderr.close()
        readers.close()
        if engine is not None:
            engine.close()
    return sorted(set(renderer.errors))[:5]
