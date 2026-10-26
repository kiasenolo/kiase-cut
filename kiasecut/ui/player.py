"""Preview playback on a worker thread, drawn by the live renderer (render.py).

The preview never builds MLT documents: it renders frames straight from a snapshot of
the project, so an edit or a drag shows on the next frame. Exports still go through MLT.
Scrubbing coalesces requests (only the newest position is drawn). While playing, audio
from the mixer goes to a QAudioSink whose buffer paces the loop, so audio is the clock.
Video pictures come from ffmpeg streams while playing (videoreader.py, on the GPU for
heavy codecs) and from the engine for a single jump.

The sound output is made anew each time playing starts, on the system's default output at
that moment, and again while playing when the outputs change (headphones out or back in), so
the sound follows the device without restarting the program.

Positions are frames of view["fps"], the editor's own rate (時間線精度, which can be finer
than the project's). Playing shows a picture every step() of them, at view["play_fps"] (the
project's frame rate), so a fine timeline costs nothing more while playing.
"""
import os
import threading
import time

import numpy as np

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

from .. import glrender, gpu, render, videoreader
from ..audiomix import CHANNELS, RATE, Mixer

PREVIEW_W = 960            # until the preview reports its size
MIN_W = 160
LEAD = 6                    # frames of sound kept queued ahead of the picture while playing


class Worker(QObject):
    frameReady = Signal(QImage, int)
    loaded = Signal(dict)
    failed = Signal(str)
    stateChanged = Signal(bool)
    levels = Signal(float, float)       # left / right peak (0..1) of each played frame

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
        self.t0 = 0.0               # playback clock: when the first picture was due
        self.shown_n = self.audio_n = 0     # pictures shown / sound frames queued since playing began
        self.audio_f = None         # next frame whose sound is to be queued
        self.peaks = {}             # sound frame number -> (left, right) level, shown with its picture
        self.new_output = False     # the sound outputs changed: open the default one again

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
                           or was_playing):
                    self.cv.wait()
                if self.quit:
                    break
                new, self.new_view = self.new_view, None
                want, self.want = self.want, None
                moved_output, self.new_output = self.new_output, False
                playing = self.playing
            try:
                if new:
                    view, cache = new
                    first = self.view is None
                    self.view = view
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
                        self.audio_f, self.peaks = None, {}
                    else:
                        sink = out = self._stop_sink(sink)
                    was_playing = playing
                    self.stateChanged.emit(playing)
                elif playing and (want is not None or moved_output):
                    # a jump while playing, or another sound device: sound and clock start over
                    sink, out = self._start_sink(sink)
                    self.t0 = time.monotonic()
                    self.shown_n = self.audio_n = 0
                    self.audio_f, self.peaks = None, {}
                if want is not None:
                    self.pos = min(want, self.length - 1)
                if self.view is None:
                    continue
                if playing:
                    self._play_one(out, sink)
                elif want is not None:
                    self._show(self.pos)
            except Exception as exc:
                self.failed.emit(f"{type(exc).__name__}: {exc}")
                with self.cv:
                    self.playing = False
        self._stop_sink(sink)
        self.readers.close()
        if self.engine:
            self.engine.close()

    def _renderer(self):
        """The GPU compositor when GPU acceleration is on (and works here), else QPainter."""
        return glrender.make(self._video) if gpu.enabled else render.Renderer(self._video)

    def _start_sink(self, old):
        """(sink, its device to write to): a new sound output on the default device as it is
        now (old is stopped first), with room for LEAD frames and a few more: a buffer shorter
        than the lead (30 fps: 6 frames are 200 ms) kept every picture late, so most were
        skipped (~8 fps). Without a sound device it plays silently: (None, None)."""
        self._stop_sink(old)
        device = QMediaDevices.defaultAudioOutput()
        if device.isNull():
            return None, None
        fmt = QAudioFormat()
        fmt.setSampleRate(RATE)
        fmt.setChannelCount(CHANNELS)
        fmt.setSampleFormat(QAudioFormat.Int16)
        sink = QAudioSink(device, fmt)
        per_frame = RATE * CHANNELS * 2 / max(1.0, self._play_fps())
        sink.setBufferSize(max(RATE * CHANNELS * 2 // 8, int(per_frame * (LEAD + 3))))
        out = sink.start()
        return (sink, out) if out is not None else (None, None)

    @staticmethod
    def _stop_sink(sink):
        if sink is not None:
            sink.stop()
        return None

    def _show(self, pos):
        v = self.view
        if gpu.enabled != isinstance(self.renderer, glrender.GLRenderer):     # the 設定 switch changed
            self.renderer = self._renderer()
        w = max(2, min(self.render_w, v["width"]))
        h = max(2, round(w * v["height"] / v["width"]))
        self.frameReady.emit(self.renderer.render(v, pos, w, h), pos)
        if self.renderer.errors:
            self.failed.emit("；".join(dict.fromkeys(self.renderer.errors)))
            self.renderer.errors.clear()

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
        return bool(self.new_view or self.want is not None or not self.playing or self.quit or self.new_output)

    def _feed(self, out, sink):
        """Queue the sound up to LEAD frames ahead of the picture. Playing begins with the
        queue empty, so this is also what keeps the picture from racing ahead at the start."""
        fps, step = self.view["fps"], self.step()
        if self.audio_f is None:
            self.audio_f = self.pos
        while self.audio_n <= self.shown_n + LEAD * step and self.audio_f < self.length:
            pcm = self.mixer.mix(self.audio_f / step, fps / step)      # one picture's sound
            a = np.frombuffer(pcm, np.int16).reshape(-1, CHANNELS)
            if len(a):
                peak = np.abs(a.astype(np.int32)).max(axis=0) / 32768.0
                self.peaks[self.audio_n] = (float(peak[0]), float(peak[-1]))
            if out is not None:
                view = memoryview(pcm)
                while view:
                    if self._interrupted():
                        return                              # react to edits / seeks at once
                    free = sink.bytesFree()
                    if free <= 0:
                        time.sleep(0.002)
                        continue
                    n = out.write(bytes(view[:free]))
                    view = view[n:]
            self.audio_f = self._next(self.audio_f, step)
            self.audio_n += step

    def _play_one(self, out, sink):
        """One picture, on time: the sound is queued first and the pictures follow the clock
        that started with it (a picture that is late is skipped, not shown late)."""
        fps, step = self.view["fps"], self.step()
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
        self._show(self.pos)
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
