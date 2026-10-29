"""Export through the live renderer (the same picture as the preview), for projects with filters.

The MLT export (build.py) cannot run GLSL filters, blend modes, keyframed mask shapes /
inverts or static clips, so a project that uses any of them is rendered here:
every frame is drawn by render.Renderer (filters run on the GPU), piped to ffmpeg together
with the mixed sound (audiomix.Mixer, as in the preview). Runs on a worker thread; a thread
of its own hands the drawn frames to ffmpeg, so the next frame is drawn meanwhile.

Every export format but MP4 / H.264 comes here too (formats.py): HEVC, ProRes, transparent
MOVs, WebM, GIF, picture sequences, sound alone; and the stems: each track's sound in a
file of its own, or as one more sound stream of the video.
"""
import os
import queue
import subprocess
import threading
import time
import wave

from PySide6.QtGui import QImage

from . import assets, audiomix, components, curves, formats, glrender, gpu, project, render, sysmem, videoreader
from .build import find_ffmpeg

US = 1_000_000
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _blend_or_mask_keys(c):
    """Whether a clip has a blend mode, or a mask whose shape or invert has keyframes (a
    keyframed font MLT can do: build.py renders such a text frame by frame)."""
    if curves.is_animated(c.get("blend")) or c.get("blend", "normal") != "normal":
        return True
    m = c.get("mask") or {}
    return curves.is_animated(m.get("kind")) or curves.is_animated(m.get("invert")) or m.get("kind") in ("compound", "image", "video")


def needs_renderer(proj):
    """Whether the project needs this export rather than MLT's: a clip has an effect, is a
    filter clip or a static clip, has a blend mode, a keyframed mask shape / invert or a
    compound mask, a speed or a frozen frame, is a group, is a text with a mask (build.py fits a
    text's picture in its own way), or is a built-in asset with keyframes or an outline
    reaching out of its frame, or a component's clip with values of its own (MLT would show
    the component's)."""
    return any(c["type"] == "filter" or c.get("effects") or project.is_static(c) or _blend_or_mask_keys(c)
               or ((c.get("params") or c.get("places")) and components.of_clip(c) is not None)
               or project.speed(c) != 1.0 or project.frozen(c) is not None or project.is_group(c)
               or (c["type"] == "text" and project.active_mask(c))
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
            if i % 50 == 0:
                if cancelled():
                    raise RuntimeError("已取消")
                if on_progress:
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
           spec=None, on_stage=None):
    """Render frames first..last (inclusive, at `fps`) of the project to the file out.
    size: (width, height). opts: crf, preset (as the export dialog gives them).
    spec: the advanced settings {format: a formats.py key, alpha: a transparent background,
    audio: the mixed sound in the file, stems: None or the extension of a file per track,
    multitrack: each track's sound as one more sound stream}; None: MP4 / H.264 with sound.
    on_stage(text): told what the export is doing now (the progress window shows it).
    cancelled(): asked between frames; True stops the export with RuntimeError("已取消")."""
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
    stage = on_stage or (lambda s: None)

    mix = audiomix.Mixer(cache)
    wav, stem_wavs, temps = None, [], []
    try:
        if fmt.audio and (spec["audio"] or not fmt.has_video):
            wav = os.path.join(cache, "export-sound.wav")
            temps.append(wav)
            stage("混音")
            _sound(mix, view, wav, fps, first, last, cancelled, on_progress=None if fmt.has_video else progress)
        multitrack = bool(spec.get("multitrack")) and fmt.multitrack
        if spec.get("stems") or multitrack:
            stage("各軌道的聲音")
            stem_wavs = _stem_wavs(mix, view, cache, fps, first, last, cancelled)
            temps += [w for _, w in stem_wavs]
        if fmt.has_video:
            sounds = ([("混音", wav)] if wav else []) + (stem_wavs if multitrack else [])
            stage("繪製與編碼畫面")
            errors = _pictures(view, out, fmt, bool(spec.get("alpha")) and fmt.can_alpha, size, fps, first, last,
                               opts, sounds, progress, cancelled, os.path.join(cache, "export-profile.log"))
            encoder = formats.encoder_name(fmt, size)
        else:
            stage("編碼聲音")
            _run([ffmpeg, "-y", "-v", "error", "-i", wav, *formats.audio_args(fmt.audio), out])
            errors, encoder = [], formats.encoder_name(fmt, size)
        if spec.get("stems"):
            stage("分軌音檔")
        files = _encode_stems(stem_wavs, out, spec["stems"]) if spec.get("stems") else []
    finally:
        _remove(temps)
    return {"done": sequence_dir(out) if fmt.kind == "sequence" else out, "elapsed": time.time() - t0,
            "errors": errors, "encoder": encoder, "stems": files}


# 截取並匯出當下幀: one frame as a picture file
STILL_FORMATS = (("PNG", ".png", True), ("JPEG", ".jpg", False), ("WebP", ".webp", True),
                 ("TIFF", ".tif", True), ("BMP", ".bmp", False))      # (name, extension, can be transparent)


def still(view, t_us, size, out, alpha=True, background=None, quality=92):
    """Draw the moment t_us of a project-like view at size (w, h) and save it to out (its
    extension picks the format): on a transparent background with alpha (where the format
    keeps it), else on background (a QColor, black when None). The clips the renderer could
    not draw are returned."""
    from PySide6.QtGui import QColor, QPainter
    W, H = size
    readers = videoreader.Readers()
    engine = None

    def video(path, us, w, h):
        nonlocal engine
        img = readers.get(path, us, w, h)
        if img is not None:
            return img
        if engine is None:
            from .client import EngineClient
            engine = EngineClient(max(W, 3840), max(H, 2160))
        px, rw, rh = engine.media_frame(path, us, view["fps"], max(1, int(w)), max(1, int(h)))
        return QImage(px, rw, rh, rw * 4, QImage.Format_RGBA8888).copy()

    renderer = glrender.make(video) if gpu.enabled else render.Renderer(video)
    try:
        frame = round(t_us * view["fps"] / US)
        img = renderer.render(view, frame, W, H, alpha=True)
    finally:
        readers.close()
    ext = os.path.splitext(out)[1].lower()
    keeps = next((a for _n, e, a in STILL_FORMATS if e == ext or (ext == ".jpeg" and e == ".jpg")), False)
    if not (alpha and keeps):
        flat = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
        flat.fill(background if background is not None else QColor("black"))
        p = QPainter(flat)
        p.drawImage(0, 0, img)
        p.end()
        img = flat
    if not img.save(out, None, quality):
        raise RuntimeError(f"無法寫入 {out}")
    return list(renderer.errors)


def sequence_dir(out):
    """The folder a picture sequence export out is written to."""
    return os.path.splitext(out)[0]


def _profile(renderer, readers, log, i, spent, waited):
    """One line of the export's profile log (every PROFILE_EVERY frames): how long drawing a
    frame took lately, how long it waited for ffmpeg, the memory in use and what the renderer's
    caches hold - to see what grows when an export slows down."""
    gl = getattr(renderer, "gl", None)
    parts = [f"frame {i}", f"draw {spent / PROFILE_EVERY * 1000:.0f} ms", f"wait {waited / PROFILE_EVERY * 1000:.0f} ms",
             f"memory {sysmem.gb(sysmem.used() or 0)}", f"images {len(renderer.images)}", f"texts {len(renderer.texts)}"
             f" ({renderer.text_bytes >> 20} MB)", f"stills {len(renderer.stills)}", f"streams {len(readers.streams)}"]
    if gl is not None:
        parts += [f"textures {len(gl.textures)} ({gl.tex_bytes >> 20} MB)",
                  f"layers {sum(len(v) for v in gl.free.values())} ({gl.free_bytes >> 20} MB)",
                  f"gl stills {len(renderer.gl_stills)}"]
    try:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(", ".join(parts) + "\n")
    except OSError:
        pass


PROFILE_EVERY = 250


def _pictures(view, out, fmt, alpha, size, fps, first, last, opts, sounds, progress, cancelled, log=None):
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
    frames = queue.Queue(maxsize=3)        # drawn, not yet written (None: no more)
    broke = []                              # why writing stopped (ffmpeg ended)

    def write():
        while (img := frames.get()) is not None:
            if broke:
                continue                    # (taken off the queue, so drawing never waits on it)
            try:
                img = img.convertToFormat(QImage.Format_RGBA8888)       # (straight alpha for ffmpeg)
                proc.stdin.write(img.constBits()[: W * H * 4])
            except Exception as exc:
                broke.append(exc)

    writer = threading.Thread(target=write, name="export frames", daemon=True)
    writer.start()
    spent = waited = 0.0
    try:
        for i, f in enumerate(range(first, last + 1)):
            if cancelled():
                raise RuntimeError("已取消")
            if broke:
                break                       # (ffmpeg's own message is below)
            t0 = time.time()
            img = renderer.render(view, f, W, H, alpha=alpha)
            t1 = time.time()
            frames.put(img)
            spent += t1 - t0
            waited += time.time() - t1
            if log and (i + 1) % PROFILE_EVERY == 0:
                _profile(renderer, readers, log, i + 1, spent, waited)
                spent = waited = 0.0
            if i % 2 == 0:
                progress((i + 1) / total)
        frames.put(None)
        writer.join()
        if not broke:
            proc.stdin.close()
        err = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0 or broke:
            raise RuntimeError(f"ffmpeg：{err.strip()[-400:] or broke[0]}")
    except Exception:
        proc.kill()
        if writer.is_alive():
            broke.append(None)              # (it lets go of what is left)
            frames.put(None)
            writer.join()
        raise
    finally:
        proc.stderr.close()
        readers.close()
        if engine is not None:
            engine.close()
    return sorted(set(renderer.errors))[:5]
