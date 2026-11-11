"""The 進階對齊編輯器's big picture: a sound's waveform over source time with the BPM grid on it.

Times here are the sound's own (source time, us): the clip shows the stretch source_start_us ..
source_start_us + duration * speed of it, so that stretch is drawn bright and the rest dimmed, and
the grid's lines are edit.source_grid's (offset_us is the first beat's time in the sound).

The view (t0..t1) moves with the wheel (a notch: a tenth of the view), zooms with Ctrl + wheel, a
touchpad's pinch, or Ctrl + the middle button; the middle button alone drags it, endless and with
a little glide after (as the curve editor's, wrapdrag.py / viewglide.py).
"""
import math
import time

import numpy as np
from PySide6.QtCore import QEvent, QLineF, QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QMenu, QWidget

from .. import build, edit, project, waveform
from . import inertia, touch, viewglide, wheel
from .timeline import BEAT_COLORS, BEAT_PX, US
from .wrapdrag import WrapDrag

RULER_H = 22
MIN_SPAN = 0.02 * US                       # the view never shows less than 20 ms
STEPS = (0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600)


class WaveView(QWidget):
    viewChanged = Signal()                 # t0 / t1 moved
    seekRequested = Signal(float)          # a click: the playhead there (source us)
    pointAdd = Signal(float)               # a change point wanted at this time (source us)
    pointMove = Signal(int, float)         # point index dragged to this time
    userMoved = Signal()                   # the view was moved by hand (a drag, the wheel): playback stops following it
    pointSelected = Signal(object)         # index of the change point picked, None: none
    pointRemove = Signal(int)

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
        self.playhead = None                # source us, None: none
        self.sel_point = None               # index of the change point picked
        self._wheel_queue = {}              # what the wheel has asked for and the view has not done yet
        self._wheel_x = 0.0
        self._wheel_last = 0.0
        self._wheel_timer = QTimer(self, interval=8)
        self._wheel_timer.timeout.connect(self._wheel_step)
        self.glide = viewglide.ViewGlide(self, self._glide_pan)
        self.wrap = WrapDrag(self, lambda: QRectF(0, 0, self.width(), self.height()), axes="x")

    # -- the clip -------------------------------------------------------------------------------
    def set_clip(self, c, peaks, keep_view=True):
        first = self.clip is None or self.clip["id"] != c["id"]
        self.clip, self.peaks = c, peaks
        if first or not keep_view:
            self.fit()
        if first or self.sel_point is not None and self.sel_point >= len(self._pts()):
            self.select_point(None)
        self.update()

    def select_point(self, i):
        self.sel_point = i
        self.pointSelected.emit(i)
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

    # -- change points (變速點 / 變拍點) ----------------------------------------------------------
    HIT_PX = 6
    SNAP_PX = 8

    def _pts(self):
        return (self.clip.get("beat") or {}).get("points") or [] if self.clip else []

    def point_at(self, x):
        """Index of the change point under pixel x, else None."""
        best = None
        for i, pt in enumerate(self._pts()):
            d = abs(self.x_of(pt["time_us"]) - x)
            if d <= self.HIT_PX and (best is None or d < best[0]):
                best = (d, i)
        return best[1] if best else None

    def snapped(self, t, skip=None, free=False):
        """t moved to the nearest grid line within a few pixels (the grid without point `skip`, as it is when that
        one is moved); free (Alt): as it is."""
        if free:
            return t
        beat = dict(self.clip.get("beat") or {})
        beat["points"] = [pt for i, pt in enumerate(self._pts()) if i != skip]
        reach = self.SNAP_PX / max(1, self.width()) * (self.t1 - self.t0)
        lines = [x for x, _ in edit.source_grid(beat, t - reach, t + reach)]
        return min(lines, key=lambda x: abs(x - t)) if lines else t

    def contextMenuEvent(self, e):
        if not self.clip:
            return
        i = self.point_at(e.pos().x())
        t = max(0.0, self.snapped(self.t_of(e.pos().x())))
        menu = QMenu(self)
        if i is None:
            menu.addAction("在此處新增變速點／變拍點", lambda: self.pointAdd.emit(t))
        else:
            self.select_point(i)
            menu.addAction("刪除", lambda: self.pointRemove.emit(i))
        menu.exec(e.globalPos())

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.LeftButton or not self.clip:
            return
        if self.point_at(e.position().x()) is None:
            self.pointAdd.emit(max(0.0, self.snapped(self.t_of(e.position().x()), free=bool(e.modifiers() & Qt.AltModifier))))

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.sel_point is not None:
            self.pointRemove.emit(self.sel_point)
        else:
            super().keyPressEvent(e)

    FOLLOW_AT = 0.3                        # where in the view the playhead stays while it is followed

    def set_playhead(self, t, follow=False):
        """The playhead at t. follow (the 跟隨 switch, while playing): the view scrolls with it continuously - the playhead
        goes on to FOLLOW_AT of the view's width and stays there while the sound moves under it - and jumps to there when the
        playhead is outside the view (the loop's start, a seek)."""
        self.playhead = t
        if follow and self.drag is None and t is not None and not self.glide.running():
            span = self.t1 - self.t0
            if not 0 <= (t - self.t0) / span <= self.FOLLOW_AT:
                self.t0, self.t1 = t - span * self.FOLLOW_AT, t + span * (1 - self.FOLLOW_AT)
                self._moved()
                return
        self.update()
        self.viewChanged.emit()                              # (the overview's playhead)

    def _glide_pan(self, dx, _dy):
        self.pan(-dx / max(1, self.width()) * (self.t1 - self.t0))

    # -- events ---------------------------------------------------------------------------------
    WHEEL_CHANNEL = {"dx": "timeline_scroll", "zoom": "timeline_zoom"}      # (inertia.py: the timeline's settings)

    def wheelEvent(self, e):
        """As the timeline's wheel: a notch scrolls a tenth of the view, Ctrl + a notch zooms 1.25 times around the mouse; the
        motion is queued and let out as the glide setting says (a touchpad's own motion is applied as it comes)."""
        if e.modifiers() & Qt.ControlModifier:
            part = {"zoom": wheel.notch(e)}
            self._wheel_x = e.position().x()
        else:
            dx, dy = wheel.pixels(e, self.width() / 10, self.width() / 10)
            part = {"dx": -(dx if abs(dx) > abs(dy) else dy)}
            self.userMoved.emit()
        glide = {k: v for k, v in part.items() if not wheel.touchpad(e) and inertia.percent(self.WHEEL_CHANNEL[k])}
        self._wheel_apply({k: v for k, v in part.items() if k not in glide})
        if glide:
            for k, v in glide.items():
                self._wheel_queue[k] = self._wheel_queue.get(k, 0.0) + v
            if not self._wheel_timer.isActive():
                self._wheel_last = time.monotonic()
                self._wheel_timer.start()
        e.accept()

    def _wheel_step(self):
        now = time.monotonic()
        dt = (now - self._wheel_last) * 1000.0
        self._wheel_last = now
        part = {}
        for key, left in list(self._wheel_queue.items()):
            k = 1.0 - 0.5 ** (dt / max(inertia.half_life_ms(self.WHEEL_CHANNEL[key]), 1.0))
            small = 0.5 if key == "dx" else 0.01
            take = left if abs(left) * (1 - k) < small else left * k
            part[key] = take
            if take == left:
                del self._wheel_queue[key]
            else:
                self._wheel_queue[key] = left - take
        if not self._wheel_queue:
            self._wheel_timer.stop()
        self._wheel_apply(part)

    def _wheel_apply(self, part):
        if "zoom" in part:
            self.zoom(1.25 ** -part["zoom"], self._wheel_x)
        if "dx" in part:
            self.pan(part["dx"] / max(1, self.width()) * (self.t1 - self.t0))

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
        elif e.button() == Qt.LeftButton:
            i = self.point_at(e.position().x())
            if i != self.sel_point:
                self.select_point(i)
            if i is not None:                                # a change point: dragged along time
                self.drag = {"kind": "point", "i": i, "at": self._pts()[i]["time_us"]}
                self.update()
                return
            self.drag = {"kind": "seek"}                     # else the playhead goes there (and is dragged)
            self.seekRequested.emit(self.t_of(e.position().x()))
            self.update()

    def mouseMoveEvent(self, e):
        d = self.drag
        if d is None:
            return
        if d["kind"] == "seek":
            self.seekRequested.emit(self.t_of(e.position().x()))
            return
        if d["kind"] == "point":
            t = max(0.0, self.snapped(self.t_of(e.position().x()), d["i"], bool(e.modifiers() & Qt.AltModifier)))
            if abs(t - d["at"]) >= 1:
                d["at"] = t
                self.pointMove.emit(d["i"], t)
            return
        if not d.get("wrap"):                                # (this drag's first move)
            d["wrap"] = True
            self.wrap.start()
            self.userMoved.emit()
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
        if d is not None and d["kind"] in ("seek", "point"):
            return
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
        self._draw_points(p, wave)
        if self.playhead is not None:
            x = self.x_of(self.playhead)
            p.setPen(QPen(QColor("#ff4d4d"), 1.5))
            p.drawLine(QLineF(x, 0, x, h))
        self._draw_ruler(p, h)

    def _draw_points(self, p, r):
        """Change points: a solid pink line where the BPM changes, a dashed blue one where only the meter does, with
        what they set on top (BPM and meter together in one label)."""
        p.setFont(QFont(self.font().family(), 9))
        for i, pt in enumerate(self._pts()):
            x = self.x_of(pt["time_us"])
            if not -40 <= x <= self.width() + 40:
                continue
            col = QColor("#ff5d9e" if pt.get("bpm") else "#5dc8ff")
            pen = QPen(col, 3 if i == self.sel_point else 2)
            if not pt.get("bpm"):
                pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.drawLine(QLineF(x, 0, x, r.height()))
            text = " · ".join(([f"{pt['bpm']:g} BPM"] if pt.get("bpm") else [])
                              + ([f"{pt['meter']} 拍" if pt["meter"] else "不分小節"] if pt.get("meter") is not None else []))
            box = QRectF(x + 3, 3, p.fontMetrics().horizontalAdvance(text) + 10, 18)
            p.fillRect(box, col)
            p.setPen(QColor("#101012"))
            p.drawText(box, Qt.AlignCenter, text)

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


class Overview(QWidget):
    """The whole sound in one strip (as FL Studio's Edison has): the stretch the clip plays lit, the big picture's
    view as a frame. A click puts the frame there (its middle), a drag moves it; grabbed inside the frame it
    keeps its place under the pointer."""
    HEIGHT = 64

    def __init__(self, wave, parent=None):
        super().__init__(parent)
        self.wave = wave
        self.setFixedHeight(self.HEIGHT)
        self.setMouseTracking(True)
        self.drag = None                    # pointer's time minus the view's middle when grabbed
        self._cols = None                   # (key, hi, lo): the strip's columns
        wave.viewChanged.connect(self.update)

    def _span(self):
        """The time the strip covers (source us): the sound, and the view if it reaches past it."""
        w = self.wave
        return 0.0, max(w.total(), w.t1, 1.0)

    def x_of(self, t):
        a, b = self._span()
        return (t - a) / (b - a) * self.width()

    def t_of(self, x):
        a, b = self._span()
        return a + x / max(1, self.width()) * (b - a)

    def _columns(self):
        w = self.wave
        res = w._res()
        if res is None:
            return None
        a, b = self._span()
        key = (id(res[0]), len(res[0]), self.width(), b)
        if self._cols is None or self._cols[0] != key:
            hi, lo = waveform.columns(res[0], res[1], a / US, b / US, max(1, self.width()))
            self._cols = (key, hi, lo)
        return self._cols[1:]

    def paintEvent(self, _e):
        w = self.wave
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#141416"))
        if not w.clip:
            return
        h = self.height()
        a, b = w.trim()
        xa, xb = self.x_of(a), self.x_of(b)
        p.fillRect(QRectF(xa, 0, max(xb - xa, 1), h), QColor("#26262b"))
        cols = self._columns()
        if cols is not None:
            hi, lo = cols
            shape = lambda v: np.sign(v) * np.clip(np.abs(v), 0, 1) ** 0.7
            hi, lo = np.maximum(shape(hi), 0.01), np.minimum(shape(lo), -0.01)
            half = h / 2
            xs = np.arange(len(hi)) + 0.5
            for lit, color in ((False, "#5b5e66"), (True, "#cfd3da")):
                keep = (xs >= xa) & (xs <= xb)
                keep = keep if lit else ~keep
                p.setPen(QPen(QColor(color), 1))
                p.drawLines([QLineF(x, half - t * half, x, half - b_ * half)
                             for x, t, b_ in zip(xs[keep], hi[keep], lo[keep])])
        else:
            p.setPen(QColor("#8a8a90"))
            p.drawText(self.rect(), Qt.AlignCenter, "波形讀取中…")
        p.setPen(QPen(QColor("#e8e8ea"), 1.5))                  # the clip's in / out
        for x in (xa, xb):
            p.drawLine(QLineF(x, 0, x, h))
        for pt in w._pts():
            p.setPen(QPen(QColor("#ff5d9e" if pt.get("bpm") else "#5dc8ff"), 1.5))
            p.drawLine(QLineF(self.x_of(pt["time_us"]), 0, self.x_of(pt["time_us"]), h))
        if w.playhead is not None:
            p.setPen(QPen(QColor("#ff4d4d"), 1.5))
            p.drawLine(QLineF(self.x_of(w.playhead), 0, self.x_of(w.playhead), h))
        x0, x1 = self.x_of(w.t0), self.x_of(w.t1)                # the big picture's view
        p.fillRect(QRectF(x0, 0, x1 - x0, h), QColor(77, 160, 255, 45))
        p.setPen(QPen(QColor("#4da0ff"), 2))
        p.drawRect(QRectF(x0 + 1, 1, max(x1 - x0 - 2, 1), h - 2))

    def _move_to(self, t):
        """The view's middle to t, its size kept."""
        w = self.wave
        span = w.t1 - w.t0
        w.t0, w.t1 = t - span / 2, t + span / 2
        w._moved()

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton or not self.wave.clip:
            return
        w = self.wave
        w.glide.stop()
        w.userMoved.emit()
        t = self.t_of(e.position().x())
        mid = (w.t0 + w.t1) / 2
        inside = w.t0 <= t <= w.t1
        self.drag = t - mid if inside else 0.0
        if not inside:
            self._move_to(t)

    def mouseMoveEvent(self, e):
        if self.drag is not None:
            self._move_to(self.t_of(e.position().x()) - self.drag)
        else:
            self.setCursor(Qt.SizeHorCursor if self.wave.t0 <= self.t_of(e.position().x()) <= self.wave.t1
                           else Qt.PointingHandCursor)

    def mouseReleaseEvent(self, _e):
        self.drag = None
