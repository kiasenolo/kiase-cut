"""The 進階對齊編輯器's big picture: a sound's waveform over source time with the BPM grid on it.

Times here are the sound's own (source time, us): the clip shows the stretch source_start_us ..
source_start_us + duration * speed of it, so that stretch is drawn bright and the rest dimmed, and
the grid's lines are edit.source_grid's (offset_us is the first beat's time in the sound).

The view (t0..t1) moves with the wheel (a notch: a tenth of the view), zooms with Ctrl + wheel, a
touchpad's pinch, or Ctrl + the middle button; the middle button alone drags it, endless and with
a little glide after (as the curve editor's, wrapdrag.py / viewglide.py).
"""
import math

import numpy as np
from PySide6.QtCore import QEvent, QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .. import build, edit, project, waveform
from . import touch, viewglide, wheel
from .timeline import BEAT_COLORS, BEAT_PX, US
from .wrapdrag import WrapDrag

RULER_H = 22
MIN_SPAN = 0.02 * US                       # the view never shows less than 20 ms
STEPS = (0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600)


class WaveView(QWidget):
    viewChanged = Signal()                 # t0 / t1 moved

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 200)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        touch.enable(self)
        self.clip = None
        self.peaks = None                   # waveform.Peaks (the timeline's)
        self.t0, self.t1 = 0.0, float(US)   # the view, source us
        self.drag = None
        self.glide = viewglide.ViewGlide(self, self._glide_pan)
        self.wrap = WrapDrag(self, lambda: QRectF(0, 0, self.width(), self.height()), axes="x")

    # -- the clip -------------------------------------------------------------------------------
    def set_clip(self, c, peaks, keep_view=True):
        first = self.clip is None or self.clip["id"] != c["id"]
        self.clip, self.peaks = c, peaks
        if first or not keep_view:
            self.fit()
        self.update()

    def trim(self):
        """The stretch of the sound the clip plays (source us): (in, out)."""
        c = self.clip
        a = c.get("source_start_us", 0)
        return a, a + c["duration_us"] * project.speed(c)

    def _res(self):
        c = self.clip
        if self.peaks is None or not c or not c.get("media"):
            return None
        res = self.peaks.get(c["media"]["path"], build.audio_stream(c))
        return res if res is not None and len(res[0]) else None

    def total(self):
        """How long the sound is (source us): its peaks' end, else the media's length, else the clip's out point."""
        res = self._res()
        if res is not None:
            return (res[1] + len(res[0]) * waveform.BIN_S) * US
        return max(self.clip["media"].get("duration_us") or 0, self.trim()[1])

    def fit(self):
        """The view on the clip's stretch with a little around it."""
        a, b = self.trim()
        pad = (b - a) * 0.04
        self.t0, self.t1 = a - pad, b + pad
        self._limit()
        self.viewChanged.emit()
        self.update()

    # -- the view -------------------------------------------------------------------------------
    def x_of(self, t):
        return (t - self.t0) / (self.t1 - self.t0) * self.width()

    def t_of(self, x):
        return self.t0 + x / max(1, self.width()) * (self.t1 - self.t0)

    def _limit(self):
        span = min(max(self.t1 - self.t0, MIN_SPAN), max(self.total() * 1.2, MIN_SPAN * 2))
        mid = min(max((self.t0 + self.t1) / 2, 0), max(self.total(), 0))
        self.t0, self.t1 = mid - span / 2, mid + span / 2

    def _moved(self):
        self._limit()
        self.viewChanged.emit()
        self.update()

    def pan(self, dt):
        self.t0, self.t1 = self.t0 + dt, self.t1 + dt
        self._moved()

    def zoom(self, f, x):
        """Zoom time by f (below 1: in) around the pixel x."""
        a = self.t_of(x)
        k = x / max(1, self.width())
        span = (self.t1 - self.t0) * f
        self.t0, self.t1 = a - span * k, a - span * k + span
        self._moved()

    def _glide_pan(self, dx, _dy):
        self.pan(-dx / max(1, self.width()) * (self.t1 - self.t0))

    # -- events ---------------------------------------------------------------------------------
    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.zoom(0.8 ** wheel.notch(e), e.position().x())
        else:                                                # a notch: a tenth of the view (either wheel way moves along time)
            dx, dy = wheel.pixels(e, self.width() / 10, self.width() / 10)
            self.pan(-(dx if abs(dx) > abs(dy) else dy) / max(1, self.width()) * (self.t1 - self.t0))
        e.accept()

    def event(self, e):
        f = wheel.pinch(e)
        if f is not None:
            self.zoom(1 / f, e.position().x())
            return True
        return super().event(e)

    def mousePressEvent(self, e):
        self.glide.stop()
        if e.button() == Qt.MiddleButton:
            zoom = bool(e.modifiers() & Qt.ControlModifier)
            self.drag = {"kind": "zoom" if zoom else "pan", "pos": e.position(), "t0": self.t0, "t1": self.t1,
                         "at": self.t_of(e.position().x()), "x": e.position().x()}

    def mouseMoveEvent(self, e):
        d = self.drag
        if d is None:
            return
        if not d.get("wrap"):                                # (this drag's first move)
            d["wrap"] = True
            self.wrap.start()
        pos = self.wrap.pos(e)
        if d["kind"] == "pan":
            dt = (pos.x() - d["pos"].x()) / max(1, self.width()) * (d["t1"] - d["t0"])
            self.t0, self.t1 = d["t0"] - dt, d["t1"] - dt
            self.glide.sample(pos.x(), pos.y())
        else:                                                # around the press; right: in
            span = (d["t1"] - d["t0"]) * 2 ** (-(pos.x() - d["pos"].x()) / 200)
            k = d["x"] / max(1, self.width())
            self.t0, self.t1 = d["at"] - span * k, d["at"] - span * k + span
        self._moved()

    def mouseReleaseEvent(self, e):
        d, self.drag = self.drag, None
        self.wrap.stop()
        if d is not None and d["kind"] == "pan":
            self.glide.release()

    # -- drawing --------------------------------------------------------------------------------
    def paintEvent(self, _e):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#18181b"))
        if not self.clip:
            return
        wave = QRectF(0, 0, w, h - RULER_H)
        a, b = self.trim()
        xa, xb = self.x_of(a), self.x_of(b)
        p.fillRect(QRectF(max(xa, 0), 0, min(xb, w) - max(xa, 0), wave.height()), QColor("#202024"))
        self._draw_wave(p, wave, xa, xb)
        self._draw_grid(p, wave)
        for x in (xa, xb):                                   # the clip's in / out
            p.setPen(QPen(QColor("#e8e8ea"), 1.5))
            p.drawLine(QLineF(x, 0, x, wave.height()))
        self._draw_ruler(p, h)

    def _draw_wave(self, p, r, xa, xb):
        res = self._res()
        if res is None:
            p.setPen(QColor("#8a8a90"))
            p.drawText(r, Qt.AlignCenter, "波形讀取中…")
            return
        peaks, lead = res
        n = max(1, self.width())
        hi, lo = waveform.columns(peaks, lead, self.t0 / US, self.t1 / US, n)
        shape = lambda v: np.sign(v) * np.clip(np.abs(v), 0, 1) ** 0.7
        hi, lo = np.maximum(shape(hi), 0.01), np.minimum(shape(lo), -0.01)
        half = r.height() / 2
        top, bottom = half - hi * half, half - lo * half
        xs = np.arange(n) + 0.5
        for dim, color in ((False, "#cfd3da"), (True, "#5b5e66")):
            p.setPen(QPen(QColor(color), 1))
            keep = (xs >= xa) & (xs <= xb)
            keep = keep if not dim else ~keep
            p.drawLines([QLineF(x, t, x, bt) for x, t, bt in zip(xs[keep], top[keep], bottom[keep])])

    def _draw_grid(self, p, r):
        beat = dict(edit.BEAT_DEFAULT, **(self.clip.get("beat") or {}))
        on = bool(beat["on"])
        period_px = 60 * US / beat["bpm"] / (self.t1 - self.t0) * self.width()
        if period_px < BEAT_PX:                              # (too dense to tell apart)
            return
        for t, d in edit.source_grid(beat, self.t0, self.t1, bars=True):
            if period_px / max(d, 1) < BEAT_PX:
                continue
            col = QColor(BEAT_COLORS.get(d, BEAT_COLORS[1]))
            col.setAlpha(230 if on else 90)
            x = self.x_of(t)
            if d == 0:
                p.setPen(QPen(col, 2.5))
                p.drawLine(QLineF(x, 0, x, r.height()))
            else:
                p.setPen(QPen(col, 1.4 if d == 1 else 1.0))
                p.drawLine(QLineF(x, 0, x, r.height() * (1 if d == 1 else 0.35)))
        if not on:
            p.setPen(QColor("#ffb86b"))
            p.drawText(r.adjusted(8, 6, -8, 0), Qt.AlignTop | Qt.AlignLeft, "BPM 對齊未啟用（格線只供參考）")

    def _draw_ruler(self, p, h):
        y = h - RULER_H
        p.fillRect(QRectF(0, y, self.width(), RULER_H), QColor("#222226"))
        span_s = (self.t1 - self.t0) / US
        px_s = self.width() / span_s
        step = next((s for s in STEPS if s * px_s >= 80), STEPS[-1])
        p.setFont(QFont(self.font().family(), 8))
        k = math.ceil(self.t0 / US / step - 1e-9)
        while k * step * US <= self.t1:
            t = k * step
            x = self.x_of(t * US)
            p.setPen(QColor("#6c6c74"))
            p.drawLine(QLineF(x, y, x, y + 6))
            p.setPen(QColor("#a8a8b0"))
            m, s = divmod(t, 60)
            p.drawText(QPointF(x + 3, y + 17), f"{int(m)}:{s:06.3f}".rstrip("0").rstrip(".") if step < 1 else f"{int(m)}:{int(s):02d}")
            k += 1
