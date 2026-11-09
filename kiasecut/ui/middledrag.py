"""Middle-button drag on anything that scrolls (中鍵拖拽): pressing the middle button inside a
scrolled area's content and dragging moves the content with the pointer, both ways it scrolls.

One watcher on the whole program does it for every scroll area - panels, lists, text boxes,
dialogs - so none needs code of its own. The area dragged is the nearest one around the press
that can scroll at all: a text box or list with nothing to scroll hands it on to the panel it
sits in. Widgets that drag their own view with the middle button (the timeline, the preview, the
curve editor) are not in a scroll area and keep it, as does a scroll area whose keeps_middle(event) says yes (the node editor,
on Alt). A press on a scroll bar is left to it.

The drag is endless (無邊界, wrapdrag.py), as number fields and the timeline are: the pointer
reaching an edge of the area's view jumps to the other side (the ways it scrolls) and the
content keeps following; the pointer hides while dragging and comes back where the drag ended up.
"""
import math
import time

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QPlainTextEdit, QWidget

from . import appevents, inertia, wheel
from .wrapdrag import WrapDrag


FRICTION = 9.0            # per second: the speed left falls by e^-9 a second - a short glide, not a long one
MIN_SPEED = 25.0          # px / s, below which the glide is over
MAX_SPEED = 4000.0
SPAN_MS = (30, 100)       # the speed is the motion over the last 100 ms (at least 30 of them), and none if it stopped for 80
STILL_MS = 80


class Glide(QObject):
    """The content going on a little after the middle button is let go, slowing down, as a phone's does."""

    def __init__(self, area, vx, vy, unit):
        super().__init__(area)
        self.area, self.v, self.unit = area, [vx, vy], unit
        self.pos = [float(area.horizontalScrollBar().value()), float(area.verticalScrollBar().value())]
        self.shown = [area.horizontalScrollBar().value(), area.verticalScrollBar().value()]
        self.last = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(8)
        self.timer.timeout.connect(self.step)
        self.timer.start()

    def stop(self):
        self.timer.stop()
        self.deleteLater()

    def step(self):
        now = time.monotonic()
        dt, self.last = now - self.last, now
        bars = (self.area.horizontalScrollBar(), self.area.verticalScrollBar())
        k = math.exp(-FRICTION * dt * 100.0 / max(inertia.percent("drag"), 1))
        for i, bar in enumerate(bars):
            if bar.value() != self.shown[i]:                 # (moved by something else: not ours any more)
                self.v[i] = 0.0
                self.pos[i] = float(bar.value())
            self.v[i] *= k
            self.pos[i] += self.v[i] * dt
            if self.pos[i] < bar.minimum() or self.pos[i] > bar.maximum():    # (hit the end)
                self.pos[i] = min(max(self.pos[i], bar.minimum()), bar.maximum())
                self.v[i] = 0.0
            bar.setValue(round(self.pos[i]))
            self.shown[i] = bar.value()
        if max(abs(self.v[0]), abs(self.v[1])) < MIN_SPEED:
            self.stop()


def _area_at(w):
    """The nearest scroll area whose content holds widget w and that can scroll, else None."""
    inner = w
    while w is not None:
        if isinstance(w, QAbstractScrollArea) and inner is w.viewport() and (
                w.horizontalScrollBar().maximum() > w.horizontalScrollBar().minimum()
                or w.verticalScrollBar().maximum() > w.verticalScrollBar().minimum()):
            return w
        inner, w = w, w.parentWidget()
    return None


class _Drag(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.area = None
        self.glide = None
        appevents.watch(self, (QEvent.MouseButtonPress, QEvent.Wheel), self._press)
        # a drag whose release never comes (a screen plugged in or out under it) must not go on
        for sig in (app.screenAdded, app.screenRemoved, app.primaryScreenChanged):
            sig.connect(lambda *_a: self._end(None))

    def _stop_glide(self):
        if self.glide is not None:
            try:
                self.glide.stop()
            except RuntimeError:
                pass
            self.glide = None

    def _press(self, obj, e):
        if e.type() == QEvent.Wheel or e.type() == QEvent.MouseButtonPress:
            self._stop_glide()                                # (a touch of the content stops it)
        if e.type() == QEvent.Wheel:
            return False
        if self.area is not None or e.button() != Qt.MiddleButton or not isinstance(obj, QWidget):
            return False
        area = _area_at(obj)
        if area is None or (hasattr(area, "keeps_middle") and area.keeps_middle(e)):     # (a view with a drag of its own, on a modifier)
            return False
        vp = area.viewport()
        h, v = area.horizontalScrollBar(), area.verticalScrollBar()
        axes = ("x" if h.maximum() > h.minimum() else "") + ("y" if v.maximum() > v.minimum() else "")
        self.wrap = WrapDrag(vp, lambda: vp.rect(), axes)
        self.wrap.start()
        self.area, self.at = area, vp.mapFromGlobal(e.globalPosition())
        self.last = self.at
        self.samples = [(time.monotonic(), self.last)]
        self.rest = [0.0, 0.0]                       # the part of a move not yet a whole step
        # a plain text box scrolls by lines up and down, everything else by pixels
        self.unit = area.fontMetrics().lineSpacing() if isinstance(area, QPlainTextEdit) else 1
        area.destroyed.connect(self._end)
        QGuiApplication.setOverrideCursor(Qt.ClosedHandCursor)
        self.app.installEventFilter(self)            # moves and the release, only while dragging
        return True

    def eventFilter(self, obj, e):
        t = e.type()
        if t == QEvent.MouseMove:
            if not e.buttons() & Qt.MiddleButton:    # (the release went somewhere unseen)
                self._end()
                return False
            self.last = self.wrap.pos(e)             # (viewport coordinates, past its edges)
            now = time.monotonic()
            self.samples = [x for x in self.samples if now - x[0] < SPAN_MS[1] / 1000.0] + [(now, self.last)]
            d, self.at = self.last - self.at, self.last
            # the motion is only added to where the content is, not what sets it: the wheel (or anything else)
            # moving it meanwhile is kept, and the two do not fight
            self._scroll(-d.x(), -d.y() / self.unit)
            return True
        if t == QEvent.Wheel:                        # wherever the pointer is, the wheel scrolls the content being dragged
            nx, ny = wheel.notches(e)
            h, v = self.area.horizontalScrollBar(), self.area.verticalScrollBar()
            if wheel.touchpad(e):
                px, py = wheel.pixels(e, 0, 0)
                self._scroll(-px, -py / self.unit)
            else:
                self._scroll(-nx * h.singleStep() * 3, -ny * v.singleStep() * 3)
            return True
        if t == QEvent.MouseButtonRelease and e.button() == Qt.MiddleButton:
            self._end(glide=True)
            return True
        if t in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):     # (any other press: the drag is over,
            self._end()                                                    #  and the press is not lost)
        return False

    def _scroll(self, dx, dy):
        """Move the content by (dx, dy) scroll units; the fractions wait for the next move."""
        for i, (bar, d) in enumerate(((self.area.horizontalScrollBar(), dx), (self.area.verticalScrollBar(), dy))):
            if bar.maximum() <= bar.minimum():
                continue
            self.rest[i] += d
            whole = int(self.rest[i])
            self.rest[i] -= whole
            if whole:
                bar.setValue(bar.value() + whole)

    def _velocity(self):
        """(vx, vy) in scroll units a second the content was moving at when the button was let go."""
        now = time.monotonic()
        if len(self.samples) < 2 or now - self.samples[-1][0] > STILL_MS / 1000.0:
            return 0.0, 0.0
        (t0, a), (t1, b) = self.samples[0], self.samples[-1]
        if (t1 - t0) * 1000.0 < SPAN_MS[0]:
            return 0.0, 0.0
        d = (b - a) / (t1 - t0)
        cap = lambda v: max(-MAX_SPEED, min(MAX_SPEED, v))
        return cap(-d.x()), cap(-d.y() / self.unit)

    def _end(self, *_a, glide=False):
        if self.area is None:
            return
        if glide:
            vx, vy = self._velocity()
            h, v = self.area.horizontalScrollBar(), self.area.verticalScrollBar()
            vx = vx if h.maximum() > h.minimum() else 0.0
            vy = vy if v.maximum() > v.minimum() else 0.0
            if max(abs(vx), abs(vy)) >= MIN_SPEED and inertia.percent("drag"):
                self._stop_glide()
                self.glide = Glide(self.area, vx, vy, self.unit)
        try:
            self.area.destroyed.disconnect(self._end)
        except (RuntimeError, TypeError):
            pass
        self.area = None
        self.app.removeEventFilter(self)
        try:
            self.wrap.stop(None if _a else self.last)    # (the pointer back where the drag ended up)
        except RuntimeError:                         # (its view is gone already)
            self.wrap.stop(None)
        QGuiApplication.restoreOverrideCursor()


_drag = None


def install():
    """Middle-button drag for every scroll area in the program (once)."""
    global _drag
    app = QApplication.instance()
    if _drag is None or _drag.app is not app:
        _drag = _Drag(app)
