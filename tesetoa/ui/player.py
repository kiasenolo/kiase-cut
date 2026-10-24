"""Preview playback on a worker thread, drawn by the live renderer (render.py).

The preview never builds MLT documents: it renders frames straight from a snapshot of
the project, so an edit or a drag shows on the next frame. Exports still go through MLT.
Scrubbing coalesces requests (only the newest position is drawn). While playing, audio
from the mixer goes to a QAudioSink whose buffer paces the loop, so audio is the clock.
"""
import threading
import time

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

from .. import render
from ..audiomix import CHANNELS, RATE, Mixer

PREVIEW_W = 960


class Worker(QObject):
    frameReady = Signal(QImage, int)
    loaded = Signal(dict)
    failed = Signal(str)
    stateChanged = Signal(bool)

    def __init__(self):
        super().__init__()
        self.cv = threading.Condition()
        self.want = None            # newest scrub position
        self.new_view = None        # newest project snapshot (view, cache dir)
        self.playing = False
        self.pos = 0
        self.length = 0
        self.quit = False
        self.engine = None          # started on first use, for video pictures only
        self.loop = None            # (first, last) frame: playback stays inside (time selection)

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

    def stop(self):
        with self.cv:
            self.quit = True
            self.cv.notify()

    # worker thread -----------------------------------------------------------------------
    def _video(self, path, us, w, h):
        try:
            if self.engine is None:
                from ..client import EngineClient
                self.engine = EngineClient(1920, 1080)
            px, w, h = self.engine.media_frame(path, us, self.view["fps"], w, h)
            return QImage(px, w, h, w * 4, QImage.Format_RGBA8888).copy()
        except Exception as exc:
            self.failed.emit(f"影片畫面：{exc}")
            return None

    @Slot()
    def run(self):
        self.view, self.renderer, self.mixer = None, render.Renderer(self._video), None
        fmt = QAudioFormat()
        fmt.setSampleRate(RATE)
        fmt.setChannelCount(CHANNELS)
        fmt.setSampleFormat(QAudioFormat.Int16)
        sink = QAudioSink(QMediaDevices.defaultAudioOutput(), fmt)
        sink.setBufferSize(RATE * CHANNELS * 2 // 8)        # ~125 ms
        out = None
        was_playing = False
        while True:
            with self.cv:
                while not (self.quit or self.new_view or self.want is not None or self.playing):
                    self.cv.wait()
                if self.quit:
                    break
                new, self.new_view = self.new_view, None
                want, self.want = self.want, None
                playing = self.playing
            try:
                if new:
                    view, cache = new
                    first = self.view is None
                    self.view = view
                    if self.mixer is None:
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
                        out = sink.start()
                    else:
                        sink.stop()
                        out = None
                    was_playing = playing
                    self.stateChanged.emit(playing)
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
        sink.stop()
        if self.engine:
            self.engine.close()

    def _show(self, pos):
        v = self.view
        h = round(PREVIEW_W * v["height"] / v["width"])
        self.frameReady.emit(self.renderer.render(v, pos, PREVIEW_W, h), pos)
        if self.renderer.errors:
            self.failed.emit("；".join(dict.fromkeys(self.renderer.errors)))
            self.renderer.errors.clear()

    def _play_one(self, out, sink):
        self._show(self.pos)
        pcm = self.mixer.mix(self.pos, self.view["fps"])
        if out is not None:
            view = memoryview(pcm)
            while view:
                if self.new_view or self.want is not None or not self.playing or self.quit:
                    break                                   # react to edits / seeks at once
                free = sink.bytesFree()
                if free <= 0:
                    time.sleep(0.002)
                    continue
                n = out.write(bytes(view[:free]))
                view = view[n:]
        self.pos += 1
        if self.loop and self.pos > self.loop[1] and self.pos - 1 <= self.loop[1]:
            self.pos = self.loop[0]
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
        self.thread.start()

    def shutdown(self):
        self.worker.stop()
        self.thread.quit()
        self.thread.wait(5000)
