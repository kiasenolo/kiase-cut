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

The pointer is hidden from the drag's first move to its end, as in Blender: what is dragged
shows where the drag is. stop(back) then puts it at `back` (widget coordinates, held inside the
area) when it has jumped, so it comes back where the drag ended up rather than wherever the
jumps left it. A drag that ends without stop() (its widget dropped it) shows the pointer again
at the next release or move without buttons.
"""
from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QCursor, QGuiApplication

MARGIN = 3              # px inside the area's edge that count as reaching it
SMALLEST = 40           # an area narrower than this does not wrap that way
PATIENCE = 12           # moves to wait for a jump before taking the pointer as unmovable


def _far(a, b):
    d = a - b
    return d.x() * d.x() + d.y() * d.y()


class _Hider(QObject):
    """Hides the pointer (one override cursor) until show() or the end of the drag."""

    def __init__(self):
        super().__init__()
        self.hidden = False

    def hide(self):
        if not self.hidden:
            self.hidden = True
            QGuiApplication.setOverrideCursor(Qt.BlankCursor)
            QGuiApplication.instance().installEventFilter(self)

    def show(self):
        if self.hidden:
            self.hidden = False
            QGuiApplication.instance().removeEventFilter(self)
            QGuiApplication.restoreOverrideCursor()

    def eventFilter(self, obj, e):
        t = e.type()
        if t == QEvent.MouseButtonRelease or t == QEvent.MouseMove and not e.buttons():
            self.show()                                      # (a drag that ended without stop())
        return False


_hider = None


def hider():
    global _hider
    if _hider is None:
        _hider = _Hider()
    return _hider


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

    def stop(self, back=None):
        """The drag ended; back: where to put the pointer (widget coordinates) if it has jumped."""
        if self.wrapped and back is not None and not self.stuck:
            r = self.bounds().adjusted(MARGIN + 1, MARGIN + 1, -MARGIN - 1, -MARGIN - 1)
            g = self.widget.mapToGlobal(QPointF(back))
            if r.width() > 0 and r.height() > 0:
                g = QPointF(min(max(g.x(), r.left()), r.right()), min(max(g.y(), r.top()), r.bottom()))
            QCursor.setPos(g.toPoint())
        self.on, self.pending = False, None
        hider().show()

    @property
    def wrapped(self):
        """Whether the pointer has jumped in this drag."""
        return self.on and (self.off.x() != 0 or self.off.y() != 0)

    def pos(self, e):
        """Where the drag is (widget coordinates) for mouse event e."""
        if not self.on:
            return e.position()
        hider().hide()
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
