"""Output level meter with the master volume fader (right of the timeline).

The meter shows the left / right peak of what is playing (after the master volume) on a dB
scale, with a peak-hold line; above 0 dB the output clips (red). The fader sets the
project's master volume (-60 ... +12 dB, double-click for 0 dB), which the preview and the
export both apply.
"""
import math
import time

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLabel, QSlider, QVBoxLayout, QHBoxLayout, QWidget

DB_LO, DB_HI = -60.0, 6.0
HOLD_S, FALL_DB_S = 1.2, 30.0
FADER_LO, FADER_HI = -60.0, 12.0


def to_db(v):
    return 20 * math.log10(v) if v > 1e-6 else -120.0


class Bars(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(30)
        self.level = [DB_LO, DB_LO]        # shown dB (falls smoothly)
        self.hold = [DB_LO, DB_LO]
        self.hold_t = [0.0, 0.0]
        self.last = time.monotonic()
        self.timer = QTimer(self, interval=33)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def feed(self, left, right):
        now = time.monotonic()
        for i, v in enumerate((left, right)):
            db = to_db(v)
            if db >= self.level[i]:
                self.level[i] = db
            if db >= self.hold[i]:
                self.hold[i], self.hold_t[i] = db, now

    def _tick(self):
        now = time.monotonic()
        dt, self.last = now - self.last, now
        changed = False
        for i in range(2):
            if self.level[i] > DB_LO:
                self.level[i] = max(DB_LO, self.level[i] - FALL_DB_S * dt)
                changed = True
            if self.hold[i] > DB_LO and now - self.hold_t[i] > HOLD_S:
                self.hold[i] = max(DB_LO, self.hold[i] - FALL_DB_S * dt)
                changed = True
        if changed:
            self.update()

    def _y(self, db, top, h):
        f = (min(max(db, DB_LO), DB_HI) - DB_LO) / (DB_HI - DB_LO)
        return top + (1 - f) * h

    def paintEvent(self, _):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#1c1c1e"))
        top, hh = 4, h - 8
        bw = (w - 6) / 2
        for i in range(2):
            x = 2 + i * (bw + 2)
            p.fillRect(QRectF(x, top, bw, hh), QColor("#101012"))
            # the usual meter colours: green, yellow from -12 dB, red from -3 dB (and clipping)
            y = self._y(self.level[i], top, hh)
            for lo, hi, col in ((DB_LO, -12.0, "#3fbf5a"), (-12.0, -3.0, "#e0c23a"), (-3.0, DB_HI, "#e8463c")):
                if self.level[i] <= lo:
                    break
                ya, yb = self._y(min(self.level[i], hi), top, hh), self._y(lo, top, hh)
                p.fillRect(QRectF(x, ya, bw, yb - ya), QColor(col))
            if self.hold[i] > DB_LO:
                hy = self._y(self.hold[i], top, hh)
                p.fillRect(QRectF(x, hy, bw, 2), QColor("#e8463c") if self.hold[i] > -3 else QColor("#e0e0e2"))
        f = p.font()
        f.setPixelSize(9)
        p.setFont(f)
        for db in (0, -6, -12, -24, -48):
            y = self._y(db, top, hh)
            p.setPen(QColor(0, 0, 0, 140))
            p.drawLine(2, round(y), w - 2, round(y))
            p.setPen(QColor("#6a6a72"))
            p.drawText(QRectF(0, y - 6, w, 12), Qt.AlignCenter, str(db))


class Fader(QSlider):
    """Master volume in tenths of a dB; the wheel never moves it, double-click resets."""

    def wheelEvent(self, e):
        e.ignore()

    def mouseDoubleClickEvent(self, e):
        self.setValue(0)
        self.sliderReleased.emit()


class MeterPanel(QWidget):
    masterChanged = Signal(float, bool)    # linear gain, final (released) or live

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(78)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(3)
        title = QLabel("輸出")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #9a9aa0;")
        lay.addWidget(title)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.bars = Bars()
        self.fader = Fader(Qt.Vertical)
        self.fader.setRange(round(FADER_LO * 10), round(FADER_HI * 10))
        self.fader.setValue(0)
        self.fader.setToolTip("主音量（預覽和匯出都會套用）；按兩下回到 0 dB")
        self.fader.valueChanged.connect(self._moved)
        self.fader.sliderReleased.connect(lambda: self.masterChanged.emit(self.gain(), True))
        row.addWidget(self.bars, 1)
        row.addWidget(self.fader)
        lay.addLayout(row, 1)
        self.db_lbl = QLabel("0.0 dB")
        self.db_lbl.setAlignment(Qt.AlignCenter)
        self.db_lbl.setStyleSheet("font-family: Consolas, monospace; color: #cfcfd4;")
        lay.addWidget(self.db_lbl)

    def gain(self):
        db = self.fader.value() / 10
        return 0.0 if db <= FADER_LO else 10 ** (db / 20)

    def set_gain(self, g):
        db = max(FADER_LO, min(FADER_HI, to_db(g)))
        self.fader.blockSignals(True)
        self.fader.setValue(round(db * 10))
        self.fader.blockSignals(False)
        self._label()

    def _label(self):
        db = self.fader.value() / 10
        self.db_lbl.setText("-∞ dB" if db <= FADER_LO else f"{db:+.1f} dB")

    def _moved(self, _v):
        self._label()
        self.masterChanged.emit(self.gain(), not self.fader.isSliderDown())
