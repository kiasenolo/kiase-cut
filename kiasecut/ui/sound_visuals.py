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


class Dynamics(QWidget):
    """A compressor, limiter, gate, expander or clipper at work: its curve (level out over
    level in) with a dot where the sound is, and the last seconds of the level in, the level
    out and how much it is turned down. The threshold (or ceiling) is dragged sideways; the
    ratio's handle, at the curve's right end, up and down."""
    live = Signal(dict)
    done = Signal(dict)
    LO, HI = -72.0, 6.0
    KEEP = 150                              # points of history (5 s at 30 a second)

    def __init__(self, kind, height=170):
        super().__init__()
        self.kind = kind
        self.values = {}
        self.now = None                     # (level in dB, level out dB, turned down dB)
        self.history = []
        self.drag = None                    # (what, press position, value then, changed)
        try:
            self.fx = dsp.Processor(kind)
        except dsp.DspError:
            self.fx = None
        self.setMinimumHeight(height)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setMouseTracking(True)

    def sizeHint(self):
        return QSize(320, self.minimumHeight())

    def set_values(self, values):
        if self.drag is None and values != self.values:
            self.values = dict(values)
            self.update()

    def feed_meters(self, meters):
        """meters: the effect's (None: silent now)."""
        if meters is None:
            if self.now is None and not any(h[2] > 0 for h in self.history):
                return
            self.now = None
            self.history.append((self.LO, self.LO, 0.0))
        else:
            level = lambda v: 20 * math.log10(max(float(v), 1e-6))
            self.now = (level(meters[0]), level(meters[1]), float(meters[2]))
            self.history.append(self.now)
        del self.history[:-self.KEEP]
        self.update()

    # -- places ------------------------------------------------------------------------------------
    def side(self):
        return min(self.height(), int(self.width() * 0.55))

    def at(self, in_db, out_db):
        s, k = self.side(), 1.0 / (self.HI - self.LO)
        return QPointF((in_db - self.LO) * k * s, self.height() - (out_db - self.LO) * k * self.height())

    def threshold_key(self):
        return "ceil" if self.kind in ("limiter", "clip") else "thr"

    def handle(self):
        """Where the ratio's handle is, or None."""
        if "ratio" not in self.values or self.fx is None:
            return None
        return self.at(0.0, max(self.LO, min(self.HI, float(self.fx.response([0.0])[0]))))

    def paintEvent(self, _e):
        p = QPainter(self)
        w, h, s = self.width(), self.height(), self.side()
        p.fillRect(self.rect(), QColor("#0b0b0b"))
        for db in (-60, -48, -36, -24, -12, 0):
            p.setPen(QColor(255, 255, 255, 50 if db == 0 else 18))
            at = self.at(db, db)
            p.drawLine(QPointF(at.x(), 0), QPointF(at.x(), h))
            p.drawLine(QPointF(0, at.y()), QPointF(s, at.y()))
            text(p, 2, at.y() - 2, str(db))
        if self.fx is not None and self.values:
            for name, v in self.values.items():
                self.fx.set(name, v)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(QPen(QColor(255, 255, 255, 50), 1, Qt.DashLine))
            p.drawLine(self.at(self.LO, self.LO), self.at(self.HI, self.HI))
            levels = np.linspace(self.LO, self.HI, 160)
            path = QPainterPath()
            for n, (x, y) in enumerate(zip(levels, self.fx.response(levels))):
                point = self.at(x, max(self.LO - 20, min(self.HI + 20, float(y))))
                path.lineTo(point) if n else path.moveTo(point)
            p.save()
            p.setClipRect(QRectF(0, 0, s, h))
            p.setPen(QPen(QColor("#ffffff"), 1.8))
            p.drawPath(path)
            thr = self.values.get(self.threshold_key())
            if thr is not None:
                # where the curve bends: for what has a pre gain, the level before it
                x = self.at(thr - self.values.get("gain", 0.0), 0).x()
                p.setPen(QPen(QColor("#ffb347"), 1.2, Qt.DashLine))
                p.drawLine(QPointF(x, 0), QPointF(x, h))
            handle = self.handle()
            if handle is not None:
                p.setPen(QPen(QColor("#000000"), 1))
                p.setBrush(QColor("#ffb347"))
                p.drawEllipse(handle, 5.5, 5.5)
            if self.now is not None:
                before = self.now[0] - (self.values.get("gain", 0.0) if self.kind != "clip" else 0.0)
                p.setBrush(QColor("#52ffae"))
                p.setPen(Qt.NoPen)
                p.drawEllipse(self.at(max(self.LO, before), max(self.LO, self.now[1])), 4.5, 4.5)
            p.restore()
        # the last seconds
        p.setPen(QColor("#000000"))
        p.drawLine(s + 1, 0, s + 1, h)
        span = w - s - 4
        if span < 30 or not self.history:
            return
        y_of = lambda db: h * (self.HI - max(self.LO, min(self.HI, db))) / (self.HI - self.LO)
        step = span / self.KEEP
        x0 = w - len(self.history) * step
        for k, colour in ((0, QColor(255, 255, 255, 70)), (1, QColor("#52ffae"))):
            path = QPainterPath()
            for n, entry in enumerate(self.history):
                point = QPointF(x0 + n * step, y_of(entry[k]))
                path.lineTo(point) if n else path.moveTo(point)
            p.setPen(QPen(colour, 1.2))
            p.drawPath(path)
        path = QPainterPath(QPointF(x0, 0))
        for n, entry in enumerate(self.history):
            path.lineTo(QPointF(x0 + n * step, min(h, entry[2] / 36.0 * h)))
        path.lineTo(QPointF(w, 0))
        p.setPen(QPen(QColor("#ff6b6b"), 1))
        p.setBrush(QColor(255, 107, 107, 60))
        p.drawPath(path)
        if self.now is not None and self.now[2] > 0.05:
            text(p, w - 54, h - 6, f"-{self.now[2]:.1f} dB", "#ff8f8f", 11)

    # -- hands -------------------------------------------------------------------------------------
    def _what(self, pos):
        handle = self.handle()
        if handle is not None and (handle - pos).manhattanLength() <= 16:
            return "ratio"
        thr = self.values.get(self.threshold_key())
        if thr is not None and pos.x() <= self.side() and \
                abs(self.at(thr - self.values.get("gain", 0.0), 0).x() - pos.x()) <= 7:
            return self.threshold_key()
        return None

    def mousePressEvent(self, e):
        what = self._what(e.position())
        if what and e.button() == Qt.LeftButton:
            self.drag = (what, e.position(), self.values[what], {})

    def mouseMoveEvent(self, e):
        if self.drag is None:
            what = self._what(e.position())
            self.setCursor(Qt.SizeVerCursor if what == "ratio" else Qt.SizeHorCursor if what else Qt.ArrowCursor)
            return
        what, start, was, changed = self.drag
        d = e.position() - start
        spec = next(p for p in soundfx.EFFECTS[self.kind]["params"] if p["name"] == what)
        if what == "ratio":                  # up: a steeper expander, a gentler compressor
            sign = 1 if self.kind == "expander" else -1
            v = was * math.exp(sign * d.y() / 60.0)
        else:
            v = was + d.x() / self.side() * (self.HI - self.LO)
        changed[what] = round(max(spec["min"], min(spec["max"], v)), 2)
        self.values.update(changed)
        self.update()
        self.live.emit(dict(changed))

    def mouseReleaseEvent(self, _e):
        if self.drag is not None:
            changed = self.drag[3]
            self.drag = None
            if changed:
                self.done.emit(dict(changed))
