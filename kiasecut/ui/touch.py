"""Touch screens: fingers on the views that are zoomed and scrolled (the preview, the timeline, the node editor, the curve editor).

One finger is the mouse: the widget is sent a left-button press, moves and release at the finger, so every drag, click and
menu works as it does with a mouse. (Qt would make those itself from touches nobody takes, but then lets go of the touch
as well, and a second finger never arrives; so the touches are taken here and the mouse is made here.)
Beyond that, for a widget given to enable():
  * two fingers pinch (a zoom, as a touchpad's pinch: a native gesture event) and move the view (a scroll, as a touchpad's
    two-finger scroll: a wheel event with pixel motion), both at once if the fingers do both - the views already read those;
  * a finger held still (about half a second) is a right click: the menu a right click opens, at the finger.
The first finger's mouse press is taken back as soon as it is known not to be a plain touch (a second finger came, or the hold
became a right click): a mouse release goes to the widget, so a drag that had begun ends where it stands.
"""
import math

from PySide6.QtCore import QEvent, QObject, QPointF, QPoint, Qt, QTimer
from PySide6.QtGui import (QContextMenuEvent, QEventPoint, QMouseEvent, QNativeGestureEvent, QPointingDevice,
                           QWheelEvent)
from PySide6.QtWidgets import QApplication

HOLD_MS = 550            # a finger this long on the same spot is a right click
SLOP_PX = 12             # ... and moves less than this
MIN_ZOOM = 0.003         # a pinch step smaller than this (as a ratio) is not sent

RELEASED = QEventPoint.State.Released
_TOUCH = (QEvent.TouchBegin, QEvent.TouchUpdate, QEvent.TouchEnd, QEvent.TouchCancel)


class Finger:
    def __init__(self, pos):
        self._pos = pos

    def position(self):
        return self._pos


class _Gestures(QObject):
    def __init__(self, widget):
        super().__init__(widget)
        self.w = widget
        self.mode = "idle"                      # idle, one (a finger down: the mouse), multi (pinch / scroll), hold (a right click was made)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(HOLD_MS)
        self.timer.timeout.connect(self._held)
        self.start = self.last = QPointF()
        self.fingers = {}                       # touch point id -> where it is, for the fingers down
        self.rest = QPointF()                   # the scroll motion not yet sent (whole pixels only)
        self.scrolling = False
        widget.setAttribute(Qt.WA_AcceptTouchEvents, True)
        widget.installEventFilter(self)

    def eventFilter(self, obj, e):
        if obj is not self.w or e.type() not in _TOUCH:
            return False
        taken = self._touch(e)
        if taken:
            e.accept()                      # (a TouchBegin counts as taken only when accepted: the following touches come to the widget then)
        return taken

    # -- the touch event ------------------------------------------------------------------------------------------------
    def _touch(self, e):
        if e.type() == QEvent.TouchCancel:
            if self.mode == "one":
                self._mouse(QEvent.MouseButtonRelease, self.last, Qt.LeftButton, Qt.NoButton)
            self._finish()
            return True
        for p in e.points():                               # (a finger may come as a TouchBegin of its own, or only the moved ones come)
            if p.state() == RELEASED:
                self.fingers.pop(p.id(), None)
            else:
                self.fingers[p.id()] = p.position()
        down = [Finger(pos) for pos in self.fingers.values()]
        began = False
        if self.mode == "idle" and down:
            self.mode, began = "one", True
            self.start = self.last = down[0].position()
            self._mouse(QEvent.MouseButtonPress, self.last, Qt.LeftButton, Qt.LeftButton)
            self.timer.start()
        if self.mode == "one":
            if len(down) >= 2:                             # a second finger: the first one's press is taken back
                self.timer.stop()
                self._mouse(QEvent.MouseButtonRelease, self.last, Qt.LeftButton, Qt.NoButton)
                self.mode = "multi"
                self.prev = self._measure(down)
                self.rest = QPointF()
                self.scrolling = False
            elif down:
                if not began:
                    self.last = down[0].position()
                    if math.hypot(self.last.x() - self.start.x(), self.last.y() - self.start.y()) > SLOP_PX:
                        self.timer.stop()
                    self._mouse(QEvent.MouseMove, self.last, Qt.NoButton, Qt.LeftButton)
            else:                                          # the finger is up
                self.timer.stop()
                self._mouse(QEvent.MouseButtonRelease, self.last, Qt.LeftButton, Qt.NoButton)
                self.mode = "idle"
        elif self.mode == "multi" and len(down) >= 2:
            self._pinch(down)
        if self.mode in ("multi", "hold") and not down:
            self._finish()
        return True

    def _finish(self, cancel=False):
        self.fingers.clear()
        self.timer.stop()
        if self.scrolling:
            self._wheel(QPoint(0, 0), Qt.ScrollEnd)
        self.scrolling = False
        self.mode = "idle"

    # -- pinch and two-finger scroll ----------------------------------------------------------------------------------------
    @staticmethod
    def _measure(points):
        """(centre x, centre y, distance) of the first two fingers."""
        a, b = points[0].position(), points[1].position()
        return (a.x() + b.x()) / 2, (a.y() + b.y()) / 2, math.hypot(a.x() - b.x(), a.y() - b.y())

    def _pinch(self, points):
        cx, cy, dist = self._measure(points)
        px, py, pdist = self.prev
        self.prev = (cx, cy, dist)
        centre = QPointF(cx, cy)
        if pdist > 1.0 and dist > 1.0:
            f = dist / pdist
            if abs(f - 1.0) >= MIN_ZOOM:
                self._native(centre, math.log(f))
        self.rest += QPointF(cx - px, cy - py)
        whole = QPoint(int(self.rest.x()), int(self.rest.y()))
        if whole.x() or whole.y():
            self.rest -= QPointF(whole)
            self._wheel(whole, Qt.ScrollUpdate if self.scrolling else Qt.ScrollBegin, centre)
            self.scrolling = True

    def _native(self, at, value):
        g = self.w.mapToGlobal(at.toPoint())
        ev = QNativeGestureEvent(Qt.NativeGestureType.ZoomNativeGesture, QPointingDevice.primaryPointingDevice(), 2,
                                 at, at, QPointF(g), value, QPointF())
        QApplication.sendEvent(self.w, ev)

    def _wheel(self, pixels, phase, at=None):
        at = at if at is not None else QPointF(self.prev[0], self.prev[1])
        g = self.w.mapToGlobal(at.toPoint())
        ev = QWheelEvent(at, QPointF(g), pixels, pixels, Qt.NoButton, Qt.NoModifier, phase, False)
        QApplication.sendEvent(self.w, ev)

    # -- the hold: a right click ----------------------------------------------------------------------------------------
    def _held(self):
        if self.mode != "one" or math.hypot(self.last.x() - self.start.x(), self.last.y() - self.start.y()) > SLOP_PX:
            return
        self.mode = "hold"
        at = self.last
        self._mouse(QEvent.MouseButtonRelease, at, Qt.LeftButton, Qt.NoButton)
        self._mouse(QEvent.MouseButtonPress, at, Qt.RightButton, Qt.RightButton)
        target = self.w.childAt(at.toPoint()) or self.w
        local = target.mapFrom(self.w, at.toPoint())
        QApplication.sendEvent(target, QContextMenuEvent(QContextMenuEvent.Mouse, local, target.mapToGlobal(local)))
        self._mouse(QEvent.MouseButtonRelease, at, Qt.RightButton, Qt.NoButton)

    def _mouse(self, kind, at, button, buttons):
        target = self.w.childAt(at.toPoint()) or self.w            # (a box laid over the canvas gets its own clicks)
        local = QPointF(target.mapFrom(self.w, at.toPoint())) if target is not self.w else at
        g = QPointF(target.mapToGlobal(local.toPoint()))
        QApplication.sendEvent(target, QMouseEvent(kind, local, g, button, buttons, Qt.NoModifier))


def enable(widget):
    """Fingers zoom, scroll and right-click on widget (see the module notes). Returns the helper (kept alive by widget)."""
    return _Gestures(widget)
