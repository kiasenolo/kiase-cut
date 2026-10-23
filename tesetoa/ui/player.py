"""Preview playback: a worker thread that owns an engine process.

Scrubbing coalesces requests (only the newest position is rendered). Playing pulls
frames in order; audio is written to a QAudioSink and the sink's buffer paces the loop,
so audio is the clock and video follows it.
"""
import threading
import time

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

from ..client import EngineClient
from ..engine import CHANNELS, RATE

PREVIEW_W, PREVIEW_H = 960, 540


class Worker(QObject):
    frameReady = Signal(QImage, int)
    loaded = Signal(dict)
    failed = Signal(str)
    stateChanged = Signal(bool)

    def __init__(self):
        super().__init__()
        self.cv = threading.Condition()
        self.want = None            # newest scrub position
        self.xml = None             # newest project to load
        self.playing = False
        self.pos = 0
        self.length = 0
        self.quit = False

    # called from the UI thread -----------------------------------------------------------
    def request_load(self, xml):
        with self.cv:
            self.xml, self.playing = xml, False
            self.cv.notify()

    def request_seek(self, pos):
        with self.cv:
            self.want = max(0, min(pos, self.length - 1)) if self.length else pos
            self.cv.notify()

    def set_playing(self, on):
        with self.cv:
            self.playing = on and self.length > 0
            if self.playing and self.pos >= self.length - 1:
                self.pos = 0
            self.cv.notify()

    def stop(self):
        with self.cv:
            self.quit = True
            self.cv.notify()

    # worker thread -----------------------------------------------------------------------
    @Slot()
    def run(self):
        try:
            engine = EngineClient(PREVIEW_W, PREVIEW_H)
        except Exception as exc:
            self.failed.emit(f"Engine failed to start: {exc}")
            return
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
                while not (self.quit or self.xml or self.want is not None or self.playing):
                    self.cv.wait()
                if self.quit:
                    break
                xml, self.xml = self.xml, None
                want, self.want = self.want, None
                playing = self.playing
            try:
                if xml:
                    info = engine.load(xml)
                    self.length = info["length"]
                    self.loaded.emit(info)
                    want = min(self.pos, self.length - 1)
                if playing != was_playing:
                    if playing:
                        out = sink.start()
                    else:
                        sink.stop()
                        out = None
                    was_playing = playing
                    self.stateChanged.emit(playing)
                if want is not None:
                    self.pos = want
                if playing:
                    self._play_one(engine, out, sink)
                elif want is not None:
                    self._show(engine, self.pos, False)
            except Exception as exc:
                self.failed.emit(str(exc))
                with self.cv:
                    self.playing = False
        sink.stop()
        engine.close()

    def _show(self, engine, pos, audio):
        px, w, h, pcm = engine.frame(pos, PREVIEW_W, PREVIEW_H, audio)
        img = QImage(px, w, h, w * 4, QImage.Format_RGBA8888).copy()
        self.frameReady.emit(img, pos)
        return pcm

    def _play_one(self, engine, out, sink):
        pcm = self._show(engine, self.pos, True)
        if pcm and out is not None:
            view = memoryview(pcm)
            while view:
                free = sink.bytesFree()
                if free <= 0:
                    time.sleep(0.002)
                    continue
                n = out.write(bytes(view[:free]))
                view = view[n:]
        self.pos += 1
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
