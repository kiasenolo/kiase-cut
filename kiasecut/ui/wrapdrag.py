"""Endless drags (無邊界, Blender's continuous grab): while a drag is on, the pointer reaching an
edge of its area jumps to the opposite edge and the drag carries on as if there were no edge.

A WrapDrag belongs to one widget. start() when a drag begins, pos(e) for each mouse move
instead of e.position(): where the drag is in the widget's coordinates, counting every jump
(so it goes on past the widget's edges), stop() when it ends. `area` is the rectangle (widget
coordinates) the pointer wraps inside, None for the whole window; `axes` which ways it wraps.

Moves Qt had queued before a jump still come in at the old place after it: they are told apart
by which of the two places they are nearer. Where the pointer cannot be moved (on Wayland it
needs the compositor's pointer-warp protocol, which Qt 6.10+ and KWin 6.5+ have) no jump
arrives, and after a few moves the drag stops trying and simply ends at the edge as before.
"""
from PySide6.QtCore import QPointF, QRectF, QSizeF
from PySide6.QtGui import QCursor, QGuiApplication

MARGIN = 3              # px inside the area's edge that count as reaching it
SMALLEST = 40           # an area narrower than this does not wrap that way
PATIENCE = 12           # moves to wait for a jump before taking the pointer as unmovable


def _far(a, b):
    d = a - b
    return d.x() * d.x() + d.y() * d.y()


class WrapDrag:
    def __init__(self, widget, area=None, axes="xy"):
        self.widget, self.area, self.axes = widget, area, axes
        self.on = False
        self.off = QPointF()             # global px the pointer has jumped, taken off what it reads
        self.pending = None              # (where it was sent, where it was, the offset before, moves since)
        self.stuck = False               # a jump never arrived: no more this drag

    def start(self, axes=None):
        self.on, self.off, self.pending, self.stuck = True, QPointF(), None, False
        if axes is not None:
            self.axes = axes

    def stop(self):
        self.on, self.pending = False, None

    @property
    def wrapped(self):
        """Whether the pointer has jumped in this drag."""
        return self.on and (self.off.x() != 0 or self.off.y() != 0)

    def pos(self, e):
        """Where the drag is (widget coordinates) for mouse event e."""
        if not self.on:
            return e.position()
        g = QPointF(e.globalPosition())
        if self.pending is not None:
            to, was, before, n = self.pending
            if _far(g, to) < _far(g, was):
                self.pending = None                          # the jump has arrived
            elif n >= PATIENCE:
                self.pending, self.off, self.stuck = None, before, True
                return self.widget.mapFromGlobal(g + self.off)
            else:
                self.pending = (to, was, before, n + 1)      # a move from before the jump
                return self.widget.mapFromGlobal(g + before)
        out = self.widget.mapFromGlobal(g + self.off)
        if not self.stuck:
            self._wrap(g)
        return out

    def bounds(self):
        """The area the pointer wraps inside, in global coordinates."""
        if self.area is not None:
            r = QRectF(self.area())
            return QRectF(self.widget.mapToGlobal(r.topLeft()), r.size())
        win = self.widget.window()
        r = QRectF(win.mapToGlobal(QPointF(0, 0)), QSizeF(win.size()))
        screen = win.screen()
        if screen is not None and QGuiApplication.platformName() != "wayland":   # (Wayland places no window)
            r = r.intersected(QRectF(screen.geometry()))
        return r

    def _wrap(self, g):
        r = self.bounds().adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
        to = QPointF(g)
        if "x" in self.axes and r.width() >= SMALLEST:
            if g.x() <= r.left():
                to.setX(r.right() - 1)
            elif g.x() >= r.right():
                to.setX(r.left() + 1)
        if "y" in self.axes and r.height() >= SMALLEST:
            if g.y() <= r.top():
                to.setY(r.bottom() - 1)
            elif g.y() >= r.bottom():
                to.setY(r.top() + 1)
        if to == g:
            return
        to = QPointF(to.toPoint())                           # (the pointer lands on whole px)
        self.pending = (to, g, QPointF(self.off), 0)
        self.off -= to - g
        QCursor.setPos(to.toPoint())
