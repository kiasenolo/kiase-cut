"""Preview playback on a worker thread, drawn by the live renderer (render.py).

The preview never builds MLT documents: it renders frames straight from a snapshot of
the project, so an edit or a drag shows on the next frame. Exports still go through MLT.
Scrubbing coalesces requests (only the newest position is drawn). While playing, audio
from the mixer goes to a QAudioSink, queued a little ahead of the pictures, and the clock the
pictures follow is put back to the sound whenever the sound falls behind it, so audio is the clock.
Video pictures come from ffmpeg streams while playing (videoreader.py, on the GPU for
heavy codecs) and from the engine for a single jump.

The sound output is made anew each time playing starts, on the system's default output at
that moment, and again while playing when the outputs change (headphones out or back in), so
the sound follows the device without restarting the program.

Positions are frames of view["fps"], the editor's own rate (時間線精度, which can be finer
than the project's). Playing shows a picture every step() of them, at view["play_fps"] (the
project's frame rate), so a fine timeline costs nothing more while playing.

播放速度 (set_rate): playing goes at rate times the real speed (0.5: half as fast, 2: twice) -
the clock runs that much faster or slower, pictures that cannot keep up are skipped as ever,
and the sound is made to fit: at its own pitch with 保持音高 (set_keep_pitch, stretch.py), else
resampled, its pitch following like a tape (speed_pcm).

Seek prefetch: when the playhead rests PREFETCH_REST_S after a jump, the video streams the
picture there needs are started and PREFETCH_S of them decoded into memory
(videoreader.Readers.prefetch), so pressing play right after does not stall on ffmpeg starting;
the sound is decoded per clip when the project is set (audiomix), so it is ready already.
"""
import math
import os
import sys
import threading
import time

import numpy as np

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

from .. import framecache, fx, glrender, gpu, render, sharedgl, stretch, sysmem, videoreader
from ..audiomix import CHANNELS, RATE, Mixer

PREVIEW_W = 960            # until the preview reports its size
MIN_W = 160
LEAD = 6                    # pictures of sound kept queued ahead of the picture while playing, at least
SINK_S = 0.5                # seconds of sound the output's buffer holds: room for the lead of a slow picture
LATE_S = 0.06               # the sound heard this far behind the clock: the clock is put back to it
PLAY_SCALES = (1.0, 0.5) if sys.platform == "android" else (1.0,)     # sizes pictures are drawn at while playing (預覽畫質 自動): a tablet that cannot keep up draws them smaller
SCRUB_S = 0.3               # stopped pictures asked for closer together than this are a drag (of the playhead, of a clip, of a number)
ROUGH_OVER_S = 0.05         # ... and are drawn smaller too when one at its size takes longer than this, till the drag rests
RATES = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 4.0)     # 播放速度 choices
PREFETCH_REST_S = 0.15      # the playhead rests this long after a jump: its video streams start ahead
PREFETCH_S = 0.5            # and decode this much of it into memory
CACHE_SHARE = 0.25          # RAM 預覽快取: the share of the system's memory its frames may take (設定)
CACHE_BAR_S = 0.1           # the timeline's bar of kept frames is sent at most this often


def cache_limit(share=CACHE_SHARE):
    """Bytes the RAM preview may keep: share of the system's memory (2 GB where that is not known; a phone or tablet
    at most 1 GB, its memory being the card's too)."""
    a = sysmem.available()
    total = a[1] if a else 8 << 30
    return int(min(total * share, sysmem.scaled(total, 1 << 30)))


def speed_pcm(pcm, rate, carry=0.0):
    """Interleaved int16 sound played rate times as fast (fewer samples, or more), and the
    fraction of a sample left over (carry: from the last piece, so pieces add up exactly)."""
    a = np.frombuffer(pcm, np.int16).reshape(-1, CHANNELS)
    if rate == 1.0 or not len(a):
        return pcm, carry
    want = len(a) / rate + carry
    n = int(want)
    if n <= 0:
        return b"", want
    at = (np.arange(n) + 0.5) * len(a) / n - 0.5
    src = np.arange(len(a))
    out = np.stack([np.interp(at, src, a[:, ch]) for ch in range(CHANNELS)], axis=1)
    return np.round(out).astype(np.int16).tobytes(), want - n


class Worker(QObject):
    frameReady = Signal(QImage, int)
    textureReady = Signal(object, int)       # a glrender.GpuFrame, position: the frame stays in the GPU (sharedgl.py)
    thumbsReady = Signal(dict)                      # {effect id: {node id: {output: (w, h, RGBA bytes)}}} the node editor shows
    loaded = Signal(dict)
    failed = Signal(str)
    stateChanged = Signal(bool)
    levels = Signal(float, float)       # left / right peak (0..1) of each played frame
    cacheChanged = Signal(object)       # [(first, end)] runs of frames in the RAM preview at the preview's size

    def __init__(self):
        super().__init__()
        self.cv = threading.Condition()
        self.view = None            # the project snapshot being shown (set on the worker thread)
        self.want = None            # newest scrub position
        self.new_view = None        # newest project snapshot (view, cache dir)
        self.playing = False
        self.pos = 0
        self.length = 0
        self.quit = False
        self.engine = None          # started on first use, for video pictures only
        self.loop = None            # (first, last) frame: playback stays inside (time selection)
        self.render_w = PREVIEW_W   # width in px the frames are drawn at (the preview's own size)
        self.quality = None         # a fraction of the project's width the frames are drawn at (1, 1/2, 1/4), None: the preview's size
        self.big = False            # the last frame was drawn by part (set_region)
        self.region = None          # the part of the canvas the preview shows (left, top, right, bottom: fractions of it): drawn alone when the canvas is too big to be drawn whole
        self.overflow = 0.0         # the fraction of the canvas drawn round it too (what lies outside the canvas)
        self.t0 = 0.0               # playback clock: when the first picture was due
        self.shown_n = self.audio_n = 0     # pictures shown / sound frames queued since playing began
        self.audio_f = None         # next frame whose sound is to be queued
        self.peaks = {}             # sound frame number -> (left, right) level, shown with its picture
        self.new_output = False     # the sound outputs changed: open the default one again
        self.rate = 1.0             # 播放速度
        self.new_rate = False       # it changed while playing: the clock and the sound start over
        self.rate_carry = 0.0       # (speed_pcm's leftover fraction of a sample)
        self.volume = 1.0           # 預覽音量: the volume of the preview alone (the export never hears it)
        self.keep_pitch = True      # 保持音高: the sound keeps its pitch at other speeds
        self.stretcher = None       # (the stretch.Stretch doing it, from where the sound began)
        self.pending = b""          # the rest of a piece of sound the output had no room for yet
        self.sink_bytes = 0         # the size of the output's buffer
        self.took = 0.0             # seconds a picture takes to draw while playing (smoothed)
        self.play_scale = 1.0       # the fraction of their size pictures are drawn at while playing (PLAY_SCALES)
        self.rough = False          # the stopped picture shown was drawn smaller (a drag): drawn at its size once it rests
        self.last_still = 0.0       # when the last stopped picture was asked for
        self.still_took = 0.0       # seconds the last stopped picture drawn at its size took
        self.asked = []             # video pictures the last stopped picture needed (path, us, w, h)
        self.prefetch = None        # those, to stream ahead once the playhead rests (seek prefetch)
        self.cache = framecache.FrameCache(cache_limit())       # RAM 預覽快取 (framecache.py), on the worker thread
        self.cache_cfg = None       # (on, draw ahead while resting, share of the memory) asked for by the UI, not taken yet
        self.cache_on = True
        self.cache_idle = True      # the frames after the playhead are drawn ahead while it rests
        self.cache_gen = fx.generation
        self.fill_pending = False   # frames are still to be drawn ahead (once the playhead rests)
        self.bar_at = 0.0           # when the timeline's bar was last sent
        self.bar_sent = None

    # called from the UI thread -----------------------------------------------------------
    def set_view(self, view, cache_dir):
        """Show a new project state (after an edit, or a live drag) from the next frame."""
        with self.cv:
            self.new_view = (view, cache_dir)
            self.cv.notify()

    def request_seek(self, pos):
        with self.cv:
            self.want = max(0, min(pos, self.length - 1)) if self.length else max(0, pos)
            self.cv.notify()

    def set_render_width(self, w):
        """Draw frames at w px wide (the size the preview shows them at; never above the
        project's own size). A stopped picture is redrawn at once."""
        w = max(MIN_W, int(w))
        with self.cv:
            if abs(w - self.render_w) < 8:
                return
            self.render_w = w
            if not self.playing and self.view is not None and self.want is None:
                self.want = self.pos
                self.cv.notify()

    def set_quality(self, q):
        """Draw frames at q times the project's size (1, 0.5, 0.25), or at the size the preview shows them (None).
        A stopped picture is redrawn at once."""
        with self.cv:
            if q == self.quality:
                return
            self.quality = q
            if not self.playing and self.view is not None and self.want is None:
                self.want = self.pos
                self.cv.notify()

    def set_region(self, region):
        """The part of the canvas the preview shows now, (left, top, right, bottom) as fractions of the canvas (they may reach past it).
        Only a canvas too big for the card's textures is drawn by part; a stopped picture is redrawn at once then."""
        with self.cv:
            if region == self.region:
                return
            self.region = region
            if self.big and not self.playing and self.view is not None and self.want is None:
                self.want = self.pos
                self.cv.notify()

    def set_overflow(self, margin):
        """Draw margin (a fraction of the canvas) more round the canvas, or 0 for the canvas alone. A stopped picture is redrawn at once."""
        with self.cv:
            if margin == self.overflow:
                return
            self.overflow = margin
            if not self.playing and self.view is not None and self.want is None:
                self.want = self.pos
                self.cv.notify()

    def set_cache(self, on, idle, share):
        """RAM 預覽快取: keep the frames drawn (on), draw the next ones while the playhead rests (idle), in up to share
        of the system's memory."""
        with self.cv:
            self.cache_cfg = (bool(on), bool(idle), float(share))
            self.cv.notify()

    def set_loop(self, span):
        """Loop playback inside frames (first, last), or None (FL Studio's time selection)."""
        with self.cv:
            self.loop = span

    def set_playing(self, on):
        with self.cv:
            self.playing = on and self.length > 0
            if self.playing and self.loop and not self.loop[0] <= self.pos <= self.loop[1]:
                self.pos = self.loop[0]                 # start at the selection
            elif self.playing and self.pos >= self.length - 1:
                self.pos = 0
            self.cv.notify()

    def set_rate(self, rate):
        """Play at rate times the real speed (RATES), from now on."""
        with self.cv:
            self.rate = max(0.05, float(rate))
            self.new_rate = True
            self.cv.notify()

    def set_volume(self, v):
        """預覽音量: the preview's sound times v (linear), apart from the project's master volume."""
        self.volume = max(0.0, float(v))

    def set_keep_pitch(self, on):
        """保持音高 at other speeds (else the pitch follows the speed, like a tape)."""
        with self.cv:
            self.keep_pitch = bool(on)
            self.new_rate = True
            self.cv.notify()

    def outputs_changed(self):
        """A sound device came or went (or the default changed): playing goes on there."""
        with self.cv:
            self.new_output = True
            self.cv.notify()

    def stop(self):
        with self.cv:
            self.quit = True
            self.cv.notify()

    # worker thread -----------------------------------------------------------------------
    def _video(self, path, us, w, h):
        """A video picture: from a streaming reader while playing (videoreader.py), from the
        engine for a single jump."""
        if not self.playing:
            self.asked.append((path, us, w, h))
        img = self.readers.get(path, us, w, h)
        if img is not None:
            return img
        try:
            if self.engine is None:
                from ..client import EngineClient
                self.engine = EngineClient(3840, 2160)          # the engine sends pictures at their own size (4K fits)
            px, w, h = self.engine.media_frame(path, us, self.view["fps"], w, h)
            return QImage(px, w, h, w * 4, QImage.Format_RGBA8888).copy()
        except Exception as exc:
            self.failed.emit(f"影片畫面：{exc}")
            return None

    @Slot()
    def run(self):
        self.view, self.renderer, self.mixer = None, self._renderer(), None
        self.readers = videoreader.Readers()
        sink = out = None
        was_playing = False
        while True:
            with self.cv:
                while not (self.quit or self.new_view or self.want is not None or self.playing
                           or was_playing or self.cache_cfg is not None):
                    later = self.prefetch or self.rough or self.fill_pending
                    if later and not self.cv.wait(PREFETCH_REST_S):
                        break                           # resting there: stream ahead, the picture at its size, frames drawn ahead (below)
                    if not later:
                        self.cv.wait()
                if self.quit:
                    break
                cfg, self.cache_cfg = self.cache_cfg, None
                rest = not (self.new_view or self.want is not None or self.playing or was_playing)
                new, self.new_view = self.new_view, None
                want, self.want = self.want, None
                moved_output, self.new_output = self.new_output, False
                new_rate, self.new_rate = self.new_rate, False
                playing = self.playing
            if cfg is not None:
                self.cache_on, self.cache_idle = cfg[0], cfg[1]
                self.cache.set_limit(cache_limit(cfg[2]) if cfg[0] else 0)
                self.fill_pending = True
                self._send_bar(force=True)
            if rest:
                if self.rough and self.view is not None:        # (a drag's smaller picture: now at its size)
                    try:
                        self._show_still(sharp=True)
                    except Exception as exc:
                        self.rough = False
                        self.failed.emit(f"{type(exc).__name__}: {exc}")
                self._prefetch()
                try:
                    self._fill_ahead()
                except Exception as exc:
                    self.fill_pending = False
                    self.failed.emit(f"RAM 預覽：{type(exc).__name__}: {exc}")
                continue
            try:
                if new:
                    view, cache = new
                    first = self.view is None
                    self.view = view
                    self.cache.set_view(view, fx.generation)
                    self.cache_gen = fx.generation
                    self.fill_pending = True
                    self._send_bar()
                    self.cache_dir = self.renderer.cache_dir = cache
                    self.readers.proxy_dir = os.path.join(cache, "proxy") if cache else None     # 預覽代理檔 (proxies.py)
                    if self.mixer is None or self.mixer.dir != os.path.join(cache, "audio"):   # (設定 > 緩存位置)
                        self.mixer = Mixer(cache)
                    self.mixer.set_view(view)
                    self.length = render.frame_count(view)
                    if first or self.pos >= self.length:
                        self.pos = min(self.pos, self.length - 1)
                    self.loaded.emit({"length": self.length, "fps": view["fps"],
                                      "width": view["width"], "height": view["height"]})
                    if want is None and not playing:
                        want = self.pos
                if playing != was_playing:
                    if playing:
                        sink, out = self._start_sink(sink)
                        self.t0 = time.monotonic()
                        self.shown_n = self.audio_n = 0
                        self.audio_f, self.peaks, self.rate_carry, self.stretcher, self.pending = None, {}, 0.0, None, b""
                    else:
                        sink = out = self._stop_sink(sink)
                        if self.play_scale != 1.0 and want is None:
                            want = self.pos                     # (the pictures were drawn smaller: where it stops, at its size)
                    was_playing = playing
                    self.stateChanged.emit(playing)
                elif playing and (want is not None or moved_output or new_rate):
                    # a jump while playing, another sound device or speed: sound and clock start over
                    sink, out = self._start_sink(sink)
                    self.t0 = time.monotonic()
                    self.shown_n = self.audio_n = 0
                    self.audio_f, self.peaks, self.rate_carry, self.stretcher, self.pending = None, {}, 0.0, None, b""
                if want is not None:
                    self.pos = min(want, self.length - 1)
                self.fill_pending = True                # (once it rests again: draw ahead from where it is)
                if self.view is None:
                    continue
                if playing:
                    self._play_one(out, sink)
                elif want is not None:
                    self._show_still()
            except Exception as exc:
                self.failed.emit(f"{type(exc).__name__}: {exc}")
                with self.cv:
                    self.playing = False
        self._stop_sink(sink)
        self.readers.close()
        if self.engine:
            self.engine.close()

    def _prefetch(self):
        """Seek prefetch: the playhead rests after a jump - start the video streams it shows from
        there and decode PREFETCH_S ahead (given up as soon as anything else comes in)."""
        todo, self.prefetch = self.prefetch or [], None
        stop = lambda: bool(self.new_view or self.want is not None or self.playing or self.quit)
        for path, us, w, h in todo:
            try:
                self.readers.prefetch(path, us, w, h, PREFETCH_S, stop)
            except Exception:                           # (a stream that cannot start: the engine is used, as before)
                pass

    def _renderer(self):
        """The GPU compositor when GPU acceleration is on (and works here), else QPainter."""
        r = glrender.make(self._video, shared=sharedgl.ENABLED) if gpu.enabled else render.Renderer(self._video)
        r.cache_dir = getattr(self, "cache_dir", None)           # (the sound an Audio Visualizer looks at)
        return r

    def _start_sink(self, old):
        """(sink, its device to write to): a new sound output on the default device as it is
        now (old is stopped first), with room for SINK_S of sound, and for LEAD frames and a
        few more: a buffer shorter than the lead (30 fps: 6 frames are 200 ms) kept every
        picture late, so most were skipped (~8 fps). Without a sound device it plays
        silently: (None, None)."""
        self._stop_sink(old)
        device = QMediaDevices.defaultAudioOutput()
        if device.isNull():
            return None, None
        fmt = QAudioFormat()
        fmt.setSampleRate(RATE)
        fmt.setChannelCount(CHANNELS)
        fmt.setSampleFormat(QAudioFormat.Int16)
        sink = QAudioSink(device, fmt)
        per_frame = RATE * CHANNELS * 2 / max(1.0, self._play_fps() * self.rate)     # (one picture's sound)
        size = max(int(RATE * CHANNELS * 2 * SINK_S), int(per_frame * (LEAD + 3)))
        sink.setBufferSize(size)
        out = sink.start()
        got = sink.bufferSize() if hasattr(sink, "bufferSize") else 0      # (the size the device gave, which may be another)
        self.sink_bytes = got if got > 0 else size
        return (sink, out) if out is not None else (None, None)

    @staticmethod
    def _stop_sink(sink):
        if sink is not None:
            sink.stop()
        return None

    def _geometry(self):
        """(w, h, margin, region) a frame is drawn at now; sets self.big (the canvas is drawn by part)."""
        v = self.view
        w = max(2, round(v["width"] * self.quality)) if self.quality else max(2, min(self.render_w, v["width"]))
        if not self.quality:
            w = max(2, round(w * (self.play_scale if self.playing else PLAY_SCALES[-1] if self.rough else 1.0)))
        h = max(2, round(w * v["height"] / v["width"]))
        margin = self.overflow
        try:
            limit = int(self.renderer.gl.ctx.info["GL_MAX_TEXTURE_SIZE"])       # (a picture wider than the card's textures cannot be drawn: a compound of another, huge, size)
        except Exception:
            limit = 0
        region = None
        self.big = False
        if limit > 0 and max(w, h) * (1 + 2 * margin) > limit:
            self.big = True
            r = self.region
            if r:                                        # only what the preview shows, a little more round it, at the size asked for
                pad = 0.04 * max(r[2] - r[0], r[3] - r[1])
                region = (max(r[0] - pad, -margin), max(r[1] - pad, -margin), min(r[2] + pad, 1 + margin), min(r[3] + pad, 1 + margin))
                if region[2] <= region[0] or region[3] <= region[1]:
                    region = None
            span = max((region[2] - region[0]) * w, (region[3] - region[1]) * h) if region else max(w, h) * (1 + 2 * margin)
            if span > limit:                             # (a view too big for one frame: the whole is drawn smaller)
                k = limit / span
                w, h = max(2, int(w * k)), max(2, int(h * k))
        return w, h, margin, region

    def _cache_key(self, w, h, margin, region):
        """The RAM preview's geometry of a frame drawn so, or None when such frames are not kept: a canvas drawn by
        part, a smaller picture of a drag or of a tablet that cannot keep up, the node editor's thumbnails wanted
        (they come from drawing the frame)."""
        if not self.cache_on or region is not None or self.rough or (self.playing and self.play_scale != 1.0) \
                or self.view.get("thumbs"):
            return None
        if fx.generation != self.cache_gen:              # (a filter's file changed: the frames drawn with it are old)
            self.cache.clear()
            self.cache_gen = fx.generation
        return (w, h, margin, isinstance(self.renderer, glrender.GLRenderer))

    def _shared(self):
        return sharedgl.ENABLED and getattr(getattr(self.renderer, "gl", None), "shared", False)

    def _show(self, pos):
        v = self.view
        if gpu.enabled != isinstance(self.renderer, glrender.GLRenderer):     # the 設定 switch changed
            self.renderer = self._renderer()
        w, h, margin, region = self._geometry()
        key = self._cache_key(w, h, margin, region)
        kept = self.cache.get(pos, key) if key is not None else None
        self.asked = []
        shown = img = None
        self.readers.next_frame()
        with gpu.ui_lock:                                # (the layer list renders thumbnails on the UI thread: never both at once)
            if kept is not None:
                img = kept
                if self._shared():
                    try:
                        shown = self.renderer.gpu_frame_of(kept, margin)
                    except Exception:
                        shown = None
            else:
                if self._shared():
                    try:
                        shown = self.renderer.render_gpu(v, pos, w, h, margin, region)
                    except Exception as exc:                 # (no way to show textures here: pictures from now on)
                        sharedgl.ENABLED = False
                        self.failed.emit(f"預覽直接用 GPU 貼圖失敗，改用一般方式：{exc}")
                if shown is None:
                    img = self.renderer.render(v, pos, w, h, margin=margin, region=region) if margin or region else self.renderer.render(v, pos, w, h)
                    img.setText("margin", repr(margin))          # (the preview needs to know where the canvas is in it)
                if key is not None:
                    self.cache.put(pos, key, img if shown is None else self.renderer.read_frame(shown), self._low_memory)
        if shown is not None:
            self.textureReady.emit(shown, pos)
        else:
            self.frameReady.emit(img, pos)
        if kept is None and self.renderer.thumbs:
            self.thumbsReady.emit(self.renderer.thumbs)
        if not self.playing:
            self.prefetch = list(self.asked)            # (streamed ahead if the playhead rests here)
        if self.renderer.errors:
            self.failed.emit("；".join(dict.fromkeys(self.renderer.errors)))
            self.renderer.errors.clear()
        self._send_bar()

    @staticmethod
    def _low_memory(more=0):
        """Whether the system is short of memory (with `more` bytes more taken): below 8 % of it, 768 MB to 2 GB."""
        a = sysmem.available()
        return a is not None and a[0] - more < min(max(a[1] * 0.08, 768 << 20), 2 << 30)

    def _send_bar(self, force=False):
        """The timeline's bar of the frames kept (at most every CACHE_BAR_S)."""
        if self.view is None or not (force or self.cache.changed):
            return
        now = time.monotonic()
        if not force and now - self.bar_at < CACHE_BAR_S:
            return
        self.bar_at = now
        self.cache.changed = False
        try:
            key = self._cache_key(*self._geometry())
        except Exception:
            key = None
        bar = framecache.runs(self.cache.positions(key), self.step()) if key is not None else []
        if bar != self.bar_sent:
            self.bar_sent = bar
            self.cacheChanged.emit(bar)

    def _busy(self):
        return bool(self.quit or self.new_view or self.want is not None or self.playing or self.cache_cfg is not None)

    def _fill_ahead(self):
        """While the playhead rests: draw the frames after it that are not kept yet (inside the time selection when
        there is one, from its start again after its end), as long as they fit in the RAM preview and in what the system
        has left without dropping any it keeps (short of memory, it halved what was kept and drew on: the kept frames
        walked off forward, the ones behind dropped); anything else asked for stops it at once."""
        if not self.fill_pending:
            return
        if not (self.cache_on and self.cache_idle) or self.view is None or self.length <= 0:
            self.fill_pending = False
            return
        w, h, margin, region = self._geometry()
        key = self._cache_key(w, h, margin, region)
        if key is None:
            self.fill_pending = False
            return
        step = self.step()
        lo, hi = (self.loop[0], self.loop[1] + 1) if self.loop else (0, self.length)
        here = min(max(self.pos, lo), hi - 1)
        order = list(range(here, hi, step))
        if self.loop:
            order += range(here - (here - lo) // step * step, here, step)
        asked, self.asked = self.asked, []                  # (the video pictures the frame shown asked for stay what is streamed ahead)
        try:
            for p in order:
                if self._busy():
                    return                                   # (still pending: on from here when it rests again)
                if self.cache.has(p, key):
                    continue
                if not self.cache.room_for(w * h * 4) or self._low_memory(w * h * 4):
                    break                                    # (what the system has left too: never drop kept frames to draw ahead)
                self.readers.next_frame()
                with gpu.ui_lock:
                    img = self.renderer.render(self.view, p, w, h, margin=margin) if margin else self.renderer.render(self.view, p, w, h)
                img.setText("margin", repr(margin))
                self.renderer.errors.clear()                 # (they show when the frame itself is shown)
                self.cache.put(p, key, img)                  # (no halving when memory runs short: drawing ahead stops above)
                self._send_bar()
        finally:
            self.asked = asked
        self.fill_pending = False
        self._send_bar(force=True)

    def _show_still(self, sharp=False):
        """The picture where the playhead stopped. On a tablet (PLAY_SCALES) the pictures of a drag - asked for one
        after the other while the playhead, a clip or a number is dragged - are drawn smaller when one at its size
        is slow, and the last of them again at its size (sharp) once the drag rests."""
        began = time.monotonic()
        self.rough = (not sharp and len(PLAY_SCALES) > 1 and not self.quality and began - self.last_still < SCRUB_S
                      and self.still_took > ROUGH_OVER_S)
        self.last_still = began
        self._show(self.pos)
        if not self.rough:
            self.still_took = time.monotonic() - began

    def _next(self, f, n=1):
        """The frame n after f, looping inside the time selection."""
        for _ in range(n):
            f += 1
            if self.loop and f > self.loop[1] and f - 1 <= self.loop[1]:
                f = self.loop[0]
        return f

    def _play_fps(self):
        v = self.view or {}
        return min(v.get("fps", 30.0), v.get("play_fps") or v.get("fps", 30.0))

    def step(self):
        """Frames (of view["fps"]) per picture shown while playing."""
        return max(1, round(self.view["fps"] / self._play_fps()))

    def _interrupted(self):
        return bool(self.new_view or self.want is not None or not self.playing or self.quit or self.new_output
                    or self.new_rate)

    def _lead(self):
        """Frames of sound kept queued ahead of the clock: LEAD pictures, or what two pictures take to draw when that
        is more (the output must not run empty while a slow picture is drawn), as far as the output's buffer goes."""
        fps, step = self.view["fps"] * self.rate, self.step()
        lead = max(LEAD * step, math.ceil(2 * self.took * fps / step) * step)
        if self.sink_bytes:
            room = int(self.sink_bytes * fps / (RATE * CHANNELS * 2))      # frames of sound the buffer holds
            lead = min(lead, max(step, room - 2 * step))
        return lead

    def _follow_sound(self, sink):
        """The clock follows the sound. What is heard now is what was queued less what the output still holds; when
        that is behind the clock (the output ran empty while a picture was drawn, or took a moment to start) the
        clock is put back to it. Left alone, the sound stayed that late for good: the output was then full whenever
        more was due, each picture waited for room in it, and the pictures came slower and slower (2 a second)."""
        if sink is None or not self.sink_bytes:
            return
        fps = self.view["fps"] * self.rate
        held = max(0, self.sink_bytes - sink.bytesFree()) + len(self.pending)
        heard = self.audio_n - held * fps / (RATE * CHANNELS * 2)          # frames since playing began
        late = time.monotonic() - self.t0 - heard / fps
        if late > LATE_S:
            self.t0 += late

    def _feed(self, out, sink):
        """Queue the sound up to _lead() frames ahead of the clock, as far as the output has room: what it has no
        room for waits for the next time (self.pending). Nothing waits for the output here - the pictures wait for
        the clock, and the clock follows the sound (_follow_sound)."""
        fps, step = self.view["fps"], self.step()
        if self.audio_f is None:
            self.audio_f = self.pos
        ahead = max(self.shown_n, int((time.monotonic() - self.t0) * fps * self.rate)) + self._lead()
        while not self._interrupted():                      # (react to edits / seeks at once)
            if self.pending:
                free = sink.bytesFree()
                n = out.write(bytes(self.pending[:free])) if free > 0 else 0
                self.pending = self.pending[max(0, n):]
                if n <= 0 or self.pending:
                    return
            if self.audio_n > ahead or self.audio_f >= self.length:
                return
            pcm = self.mixer.mix(self.audio_f / step, fps / step)      # one picture's sound
            a = np.frombuffer(pcm, np.int16).reshape(-1, CHANNELS)
            if len(a):
                peak = np.abs(a.astype(np.int32)).max(axis=0) / 32768.0
                self.peaks[self.audio_n] = (float(peak[0]), float(peak[-1]))
            if self.volume != 1.0:
                pcm = np.clip(a.astype(np.float32) * self.volume, -32768, 32767).astype(np.int16).tobytes()
            if self.keep_pitch and self.rate != 1.0:
                if self.stretcher is None:
                    self.stretcher = stretch.Stretch(self.rate, CHANNELS)
                pcm, self.rate_carry = self.stretcher.feed(pcm, self.rate_carry)
            else:
                pcm, self.rate_carry = speed_pcm(pcm, self.rate, self.rate_carry)
            if out is not None:
                self.pending = memoryview(pcm)
            self.audio_f = self._next(self.audio_f, step)
            self.audio_n += step

    def _play_one(self, out, sink):
        """One picture, on time: the sound is queued first and the pictures follow the clock
        that started with it (a picture that is late is skipped, not shown late)."""
        fps, step = self.view["fps"] * self.rate, self.step()      # (frames per second of the clock)
        self._follow_sound(sink)
        self._feed(out, sink)
        due = self.t0 + self.shown_n / fps
        while not self._interrupted():
            wait = due - time.monotonic()
            if wait <= 0:
                break
            time.sleep(min(wait, 0.004))
        if self._interrupted():
            return
        behind = int((time.monotonic() - due) * fps) // step         # pictures
        for _ in range(behind if behind >= 2 else 0):
            self.pos = self._next(self.pos, step)
            self.shown_n += step
        last = self.pos >= self.length - 1
        self.pos = min(self.pos, self.length - 1)
        began = time.monotonic()
        self._show(self.pos)
        took = time.monotonic() - began
        self.took = took if not self.took else 0.7 * self.took + 0.3 * took
        if len(PLAY_SCALES) > 1:                            # (pictures that cannot keep up are drawn smaller, and at their size again once they could)
            each = step / fps                               # seconds a picture is shown
            if self.took > 1.2 * each:
                self.play_scale = PLAY_SCALES[-1]
            elif self.took < 0.4 * each:
                self.play_scale = PLAY_SCALES[0]
        for k in [k for k in self.peaks if k < self.shown_n]:
            del self.peaks[k]
        lv = self.peaks.pop(self.shown_n, None)
        if lv:
            self.levels.emit(*lv)
        self.shown_n += step
        if last:
            with self.cv:
                self.playing = False
            return
        self.pos = self._next(self.pos, step)
        if self.pos >= self.length:
            self.pos = self.length - 1
            with self.cv:
                self.playing = False


class Player(QObject):
    """UI-side handle; signals arrive on the UI thread."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread = QThread()
        self.worker = Worker()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.devices = QMediaDevices(self)                 # (its signals come on this, the UI, thread)
        self.devices.audioOutputsChanged.connect(self.worker.outputs_changed, Qt.DirectConnection)
        self.thread.start()

    def shutdown(self):
        self.worker.stop()
        self.thread.quit()
        self.thread.wait(5000)
