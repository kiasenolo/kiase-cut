"""Playing the stretch of a sound a clip plays, for the 進階對齊編輯器 - only that stretch (the clip's in .. out), not
the whole file, and on a sound output of its own: the timeline's player and its clock are not touched.

The stretch is decoded once (ffmpeg, stereo 44.1 kHz, at the clip's speed: atempo keeps the pitch) on a thread and kept; a
QAudioSink pulls from it. The clock is the sink's own processed time, so the playhead (source time, us) is what is heard;
without a sound device a plain timer is the clock. At the out point it loops (loop) or stops there.
"""
import subprocess
import threading
import time

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QTimer, Signal
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

from ..build import find_ffmpeg

US = 1_000_000
RATE, CHANNELS, FRAME = 44100, 2, 4
TICK_MS = 15


def tempo_filter(k):
    """atempo chain for speed k (one atempo takes 0.5 .. 2)."""
    parts = []
    while k > 2.0:
        parts.append(2.0)
        k /= 2.0
    while k < 0.5:
        parts.append(0.5)
        k /= 0.5
    parts.append(k)
    return ",".join(f"atempo={p:.6f}" for p in parts)


class Preview(QObject):
    positionChanged = Signal(float)         # the playhead, source us
    playingChanged = Signal(bool)
    failed = Signal(str)
    _decoded = Signal(object, object)       # key, PCM bytes or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loop = True
        self.playing = False
        self.key = None                     # (path, stream, in us, out us, speed)
        self.pcm = None
        self.buf = None
        self.sink = None
        self._decoding = None               # the key being decoded
        self.want = None                    # play from here (source us) once decoded
        self.pos = 0.0                      # the playhead, source us
        self.offset_us = 0.0                # stretched time the sink's start was at
        self.began = 0.0                    # (no device) monotonic time of the start
        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self._tick)
        self._decoded.connect(self._on_decoded)

    # -- the source -----------------------------------------------------------------------------
    def set_source(self, path, stream, a, b, k):
        """The stretch to play: source us a..b of the file's sound stream, at speed k. A change stops playing."""
        key = (path, stream, round(a), round(b), round(k, 6))
        if key == self.key:
            return
        self.stop()
        self.key, self.pcm, self.buf, self.want, self._decoding = key, None, None, None, None
        self.pos = a

    def _span(self):
        return self.key[2], self.key[3], self.key[4]

    def _decode(self):
        key = self.key
        path, stream, a, b, k = key

        def work():
            try:
                r = subprocess.run([find_ffmpeg(), "-v", "error", "-ss", f"{a / US:.6f}", "-t", f"{(b - a) / US:.6f}",
                                    "-i", path, "-map", f"0:a:{stream}", "-vn", "-af", tempo_filter(k),
                                    "-ac", str(CHANNELS), "-ar", str(RATE), "-f", "s16le", "-"],
                                   capture_output=True, timeout=600)
                data = r.stdout if r.returncode == 0 or r.stdout else None
            except Exception:
                data = None
            self._decoded.emit(key, data)
        threading.Thread(target=work, daemon=True).start()

    def _on_decoded(self, key, data):
        if key != self.key:
            return
        if not data:
            self.want, self._decoding = None, None
            self.failed.emit("讀不到這段聲音")
            return
        data = data[: len(data) // FRAME * FRAME]
        self.pcm = data
        self.buf = QBuffer(self)
        self.buf.setData(QByteArray(data))
        self.buf.open(QIODevice.ReadOnly)
        if self.want is not None:
            want, self.want = self.want, None
            self._begin(want)

    # -- playing --------------------------------------------------------------------------------
    def play(self, from_us=None):
        """Play from from_us (source us; the playhead, or the in point when it is not inside the stretch)."""
        if self.key is None:
            return
        a, b, _ = self._span()
        t = self.pos if from_us is None else from_us
        if not a <= t < b - 1000:
            t = a
        if self.pcm is None:
            self.want = t
            self.pos = t
            self._decode_once()
            return
        self._begin(t)

    def _decode_once(self):
        if self._decoding != self.key:
            self._decoding = self.key
            self._decode()

    def _begin(self, t):
        a, b, k = self._span()
        self._end_sink()
        self.offset_us = max(0.0, (t - a) / k)
        byte = min(int(self.offset_us * RATE / US) * FRAME, len(self.pcm))
        self.buf.seek(byte)
        device = QMediaDevices.defaultAudioOutput()
        if not device.isNull():
            fmt = QAudioFormat()
            fmt.setSampleRate(RATE)
            fmt.setChannelCount(CHANNELS)
            fmt.setSampleFormat(QAudioFormat.Int16)
            self.sink = QAudioSink(device, fmt)
            self.sink.start(self.buf)
        self.began = time.monotonic()
        self.pos = t
        self._set_playing(True)
        self.timer.start()

    def _end_sink(self):
        if self.sink is not None:
            self.sink.stop()
            self.sink.deleteLater()
            self.sink = None

    def _set_playing(self, on):
        if on != self.playing:
            self.playing = on
            self.playingChanged.emit(on)

    def pause(self):
        """Stop where it is (play() goes on from there)."""
        self.timer.stop()
        self.want = None
        self._end_sink()
        self._set_playing(False)

    stop = pause

    def seek(self, t):
        """The playhead to t; playing goes on from there."""
        a, b, _ = self._span() if self.key else (t, t, 1)
        t = min(max(t, a), b)
        if self.playing and self.pcm is not None:
            self._begin(t)
        else:
            self.pos = t
            self.positionChanged.emit(t)

    def _clock_us(self):
        """Stretched time heard so far."""
        if self.sink is not None:
            return self.offset_us + self.sink.processedUSecs()
        return self.offset_us + (time.monotonic() - self.began) * US

    def _tick(self):
        a, b, k = self._span()
        total = len(self.pcm) / FRAME / RATE * US
        s = self._clock_us()
        if s >= total - 5000:
            if self.loop:
                self._begin(a)
            else:
                self.pause()
                self.pos = b
                self.positionChanged.emit(b)
            return
        self.pos = a + s * k
        self.positionChanged.emit(self.pos)
