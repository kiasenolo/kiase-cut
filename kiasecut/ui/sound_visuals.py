"""What the sound effects draw: spectra, the equaliser's curve (dragged), a filter's curve.
Used by the 聲音 page's panels and by the sound node editor's nodes."""
import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .. import dsp, soundfx
from .menukeys import Menu

RATE = 48000
LO, HI = 20.0, 20000.0
BAND_COLORS = ["#ff6b6b", "#ffb347", "#ffe042", "#52ffae", "#6ab0ff", "#a78bfa", "#f472b6", "#94a3b8"]
EQ_RANGES = (6.0, 12.0, 18.0, 24.0)


def x_of(hz, w):
    return w * math.log(max(hz, 1e-3) / LO) / math.log(HI / LO)


def hz_of(x, w):
    return LO * (HI / LO) ** (x / max(w, 1))


def text(p, x, y, s, colour="#6a6a72", px=9):
    f = p.font()
    f.setPixelSize(px)
    p.setFont(f)
    p.setPen(QColor(colour))
    p.drawText(QPointF(x, y), s)


def freq_grid(p, w, h):
    for hz in (50, 100, 200, 500, 1000, 2000, 5000, 10000):
        strong = hz in (100, 1000, 10000)
        p.setPen(QColor(255, 255, 255, 36 if strong else 16))
        p.drawLine(QPointF(x_of(hz, w), 0), QPointF(x_of(hz, w), h))
        if strong:
            text(p, x_of(hz, w) + 2, h - 3, f"{hz // 1000}k" if hz >= 1000 else str(hz))


class Analysis:
    """The levels of a stretch of sound in bands spaced by pitch, falling slowly."""
    N = 4096
    FLOOR = -90.0

    def __init__(self, bands=120):
        self.levels = np.full(bands, self.FLOOR)
        self.window = np.hanning(self.N).astype(np.float32)
        edges = np.geomspace(LO, HI, bands + 1) * self.N / RATE
        self.bins = [(int(a), max(int(a) + 1, int(math.ceil(b)))) for a, b in zip(edges, edges[1:])]

    def feed(self, mono):
        """Take in N samples; True when what is shown changed."""
        mag = np.abs(np.fft.rfft(mono * self.window)) / (self.N / 4)
        now = np.array([20 * math.log10(max(float(mag[a:b].max()), 1e-6)) for a, b in self.bins])
        shown = np.maximum(now, self.levels - 2.5)                  # (up at once, down slowly)
        if np.abs(shown - self.levels).max() <= 0.05:
            return False
        self.levels = np.clip(shown, self.FLOOR, 6.0)
        return True

    def path(self, w, h, top=6.0):
        path = QPainterPath(QPointF(0, h))
        for i, db in enumerate(self.levels):
            path.lineTo(QPointF(w * (i + 0.5) / len(self.levels), h * (top - db) / (top - self.FLOOR)))
        path.lineTo(QPointF(w, h))
        return path


class Spectrum(QWidget):
    N = Analysis.N

    def __init__(self, height=0):
        super().__init__()
        self.analysis = Analysis()
        if height:
            self.setMinimumHeight(height)
        else:
            self.setMinimumWidth(220)
        self.setAttribute(Qt.WA_OpaquePaintEvent)

    def feed(self, mono):
        if self.analysis.feed(mono):
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#0b0b0b"))
        freq_grid(p, w, h)
        for db in (0, -24, -48, -72):
            y = h * (6.0 - db) / (6.0 - Analysis.FLOOR)
            p.setPen(QColor(255, 255, 255, 28))
            p.drawLine(QPointF(0, y), QPointF(w, y))
            text(p, 2, y - 2, str(db))
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#7ad0ff"), 1.2))
        p.setBrush(QColor(122, 208, 255, 60))
        p.drawPath(self.analysis.path(w, h))


class Response(QWidget):
    """The gain of an effect over the frequencies, with its sound's spectrum behind.

    For the equaliser (kind "eq") the bands are dots: dragged (across: frequency, up and
    down: gain; Shift: one of them only), the wheel on one sets its Q, a double click on
    empty space turns a spare band on there (on a dot: off), a right click has its type.
    live(values) while a band is dragged, done(values) when it is let go: {name: value}."""
    live = Signal(dict)
    done = Signal(dict)
    bandPicked = Signal(int)

    def __init__(self, kind, height=210):
        super().__init__()
        self.kind = kind
        self.values = {}
        self.band = 1
        self.range = 18.0
        self.analysis = Analysis()
        self.drag = None                    # (band, press position, its f and g then, the values changed)
        try:
            self.fx = dsp.Processor(kind)
        except dsp.DspError:
            self.fx = None
        self.hz = np.geomspace(LO, HI, 240)
        self.setMinimumHeight(height)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setMouseTracking(kind == "eq")

    def sizeHint(self):
        return QSize(320, self.minimumHeight())

    def set_values(self, values):
        if self.drag is None and values != self.values:
            self.values = dict(values)
            self.update()

    def feed(self, mono):
        if self.analysis.feed(mono):
            self.update()

    # -- places -----------------------------------------------------------------------------------
    def y_of(self, db):
        return self.height() / 2 - db / self.range * (self.height() / 2 - 8)

    def db_of(self, y):
        return (self.height() / 2 - y) / (self.height() / 2 - 8) * self.range

    def dot(self, i):
        v = self.values
        gain = v[f"g{i}"] if round(v[f"t{i}"]) in soundfx.EQ_GAIN_TYPES else 0.0
        return QPointF(x_of(v[f"f{i}"], self.width()), self.y_of(max(-self.range, min(self.range, gain))))

    def dot_at(self, pos):
        if self.kind != "eq" or not self.values:
            return None
        near = [(( self.dot(i) - pos).manhattanLength(), i) for i in range(1, soundfx.EQ_BANDS + 1)
                if self.values.get(f"o{i}", 0) > 0.5]
        near = [n for n in near if n[0] <= 16]
        return min(near)[1] if near else None

    # -- drawing -----------------------------------------------------------------------------------
    def curve(self, part=-1):
        w = self.width()
        path = QPainterPath()
        for n, (hz, db) in enumerate(zip(self.hz, self.fx.response(self.hz, part))):
            point = QPointF(x_of(hz, w), self.y_of(max(-80.0, min(80.0, float(db)))))
            if n:
                path.lineTo(point)
            else:
                path.moveTo(point)
        return path

    def paintEvent(self, _e):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#0b0b0b"))
        freq_grid(p, w, h)
        step = self.range / 3
        for k in range(-2, 3):
            y = self.y_of(k * step)
            p.setPen(QColor(255, 255, 255, 60 if k == 0 else 20))
            p.drawLine(QPointF(0, y), QPointF(w, y))
            if k:
                text(p, 2, y - 2, f"{k * step:+.0f}")
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(122, 208, 255, 38))
        p.drawPath(self.analysis.path(w, h))
        if self.fx is None or not self.values:
            return
        for name, v in self.values.items():
            self.fx.set(name, v)
        p.setBrush(Qt.NoBrush)
        if self.kind == "eq":
            for i in range(1, soundfx.EQ_BANDS + 1):
                if self.values.get(f"o{i}", 0) > 0.5:
                    c = QColor(BAND_COLORS[i - 1])
                    c.setAlpha(200 if i == self.band else 90)
                    p.setPen(QPen(c, 1.2))
                    p.drawPath(self.curve(i - 1))
        p.setPen(QPen(QColor("#ffffff"), 1.8))
        p.drawPath(self.curve())
        if self.kind == "eq":
            for i in range(1, soundfx.EQ_BANDS + 1):
                if self.values.get(f"o{i}", 0) > 0.5:
                    at = self.dot(i)
                    p.setPen(QPen(QColor("#ffffff") if i == self.band else QColor("#000000"), 1.5))
                    p.setBrush(QColor(BAND_COLORS[i - 1]))
                    p.drawEllipse(at, 7, 7)
                    text(p, at.x() - 2.5, at.y() + 3.5, str(i), "#000000", 10)

    # -- hands (the equaliser) ------------------------------------------------------------------------
    def pick(self, i):
        self.band = i
        self.bandPicked.emit(i)
        self.update()

    def mousePressEvent(self, e):
        i = self.dot_at(e.position())
        if i is None or e.button() != Qt.LeftButton:
            if i is not None:
                self.pick(i)
            return
        self.pick(i)
        self.drag = (i, e.position(), self.values[f"f{i}"], self.values[f"g{i}"], {})

    def mouseMoveEvent(self, e):
        if self.drag is None:
            self.setCursor(Qt.SizeAllCursor if self.dot_at(e.position()) else Qt.ArrowCursor)
            return
        i, start, f, g, changed = self.drag
        d = e.position() - start
        only = None
        if e.modifiers() & Qt.ShiftModifier:
            only = "f" if abs(d.x()) >= abs(d.y()) else "g"
        if only != "g":
            hz = hz_of(x_of(f, self.width()) + d.x(), self.width())
            changed[f"f{i}"] = round(max(LO, min(HI, hz)), 1)
        elif f"f{i}" in changed:
            changed[f"f{i}"] = f
        if round(self.values[f"t{i}"]) in soundfx.EQ_GAIN_TYPES:
            if only != "f":
                changed[f"g{i}"] = round(max(-24.0, min(24.0, g - d.y() / (self.height() / 2 - 8) * self.range)), 2)
            elif f"g{i}" in changed:
                changed[f"g{i}"] = g
        self.values.update(changed)
        self.update()
        self.live.emit(dict(changed))

    def mouseReleaseEvent(self, _e):
        if self.drag is not None:
            changed = self.drag[4]
            self.drag = None
            if changed:
                self.done.emit(dict(changed))

    def mouseDoubleClickEvent(self, e):
        if self.kind != "eq" or not self.values or e.button() != Qt.LeftButton:
            return
        self.drag = None
        i = self.dot_at(e.position())
        if i is not None:
            self.done.emit({f"o{i}": 0})
            return
        spare = next((k for k in range(1, soundfx.EQ_BANDS + 1) if self.values.get(f"o{k}", 0) <= 0.5), None)
        if spare is not None:
            self.pick(spare)
            hz = max(LO, min(HI, hz_of(e.position().x(), self.width())))
            gain = max(-24.0, min(24.0, self.db_of(e.position().y())))
            kind = 3 if hz < 40 else 4 if hz > 16000 else 0
            self.done.emit({f"o{spare}": 1, f"t{spare}": kind, f"f{spare}": round(hz, 1), f"g{spare}": round(gain, 2)})

    def wheelEvent(self, e):
        i = self.dot_at(e.position())
        if i is None or round(self.values[f"t{i}"]) not in soundfx.EQ_Q_TYPES:
            e.ignore()
            return
        self.pick(i)
        q = self.values[f"q{i}"] * 1.12 ** (e.angleDelta().y() / 120)
        q = round(max(0.1, min(18.0, q)), 3)
        self.values[f"q{i}"] = q
        self.done.emit({f"q{i}": q})

    def contextMenuEvent(self, e):
        i = self.dot_at(QPointF(e.pos()))
        if i is None:
            return
        self.pick(i)
        menu = Menu(self)
        for k, name in enumerate(soundfx.EQ_TYPES):
            a = menu.addAction(name, lambda k=k: self.done.emit({f"t{i}": k}))
            a.setCheckable(True)
            a.setChecked(round(self.values[f"t{i}"]) == k)
        if round(self.values[f"t{i}"]) in soundfx.EQ_CUT_TYPES:
            slope = menu.addMenu("斜率")
            for k in range(4):
                a = slope.addAction(f"{12 * (k + 1)} dB/oct", lambda k=k: self.done.emit({f"s{i}": k}))
                a.setCheckable(True)
                a.setChecked(round(self.values[f"s{i}"]) == k)
        menu.addSeparator()
        menu.addAction("關掉這個頻段", lambda: self.done.emit({f"o{i}": 0}))
        menu.exec(e.globalPos())
