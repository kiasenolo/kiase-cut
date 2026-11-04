"""The lines between panels, by finger: held first, then dragged.

A finger that lands on the line between two panels (a main window's dock separator, a splitter's handle) pressed it and moved it
at once, so a swipe that happened to start there resized the panels. Now the line is let go only after the finger has been held
(HOLD_MS): it goes white and buzzes, and from then on it is dragged as with a mouse. A finger that leaves the spot before that
(a swipe) or is lifted (a tap) moves nothing.

The press is let through at once (Qt starts the move of the separator and keeps the drag in the right widget), but the moves are
kept from it until the hold; a finger that goes before then has the press taken back with a release where it came down.
Only mouse events the touch screen made (Qt makes them from touches nobody takes) are watched, never a real mouse's.
"""
import sys

import shiboken6
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication, QMainWindow, QSplitterHandle, QWidget

from .. import haptic

HOLD_MS = 450
SLOP_PX = 10
THIN = 40                  # px: a gap between panels thicker than this is not a line
FORCE = False              # on for a desktop too (tests)


def active():
    return FORCE or sys.platform == "android"


class Light(QWidget):
    """A white bar over a line between panels: it is let go."""

    def __init__(self, parent, rect):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setGeometry(rect)
        self.raise_()
        self.show()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.white)


def synthesized(e):
    return e.source() != Qt.MouseEventNotSynthesized


def gap_rect(window, at):
    """The strip of empty space round `at` between the panels of a main window (a line), or None when it is wide (not a line)."""
    def reaches(x, y):
        return not window.rect().contains(x, y) or window.childAt(x, y) is not None

    x, y = at.x(), at.y()
    left = right = x
    while not reaches(left - 1, y) and left > x - 400:
        left -= 1
    while not reaches(right + 1, y) and right < x + 400:
        right += 1
    top = bottom = y
    while not reaches(x, top - 1) and top > y - 4000:
        top -= 1
    while not reaches(x, bottom + 1) and bottom < y + 4000:
        bottom += 1
    w, h = right - left + 1, bottom - top + 1
    if min(w, h) > THIN or (w <= 1 and h <= 1):
        return None
    from PySide6.QtCore import QRect
    return QRect(left, top, w, h)


class _Watch(QObject):
    def __init__(self):
        super().__init__()
        self.obj = None                  # the widget the line's press went to
        self.start = QPoint()
        self.armed = self.dead = False
        self.light = None
        self.replaying = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(HOLD_MS)
        self.timer.timeout.connect(self._arm)

    # -- which press is on a line -------------------------------------------------------------------------------------------
    @staticmethod
    def line_at(obj, e):
        """(widget to put the light on, its rect there) when the press at e is on a line between panels, else None."""
        if isinstance(obj, QSplitterHandle):
            return obj, obj.rect()
        if isinstance(obj, QMainWindow):
            at = e.position().toPoint()
            if obj.childAt(at) is None:
                r = gap_rect(obj, at)
                if r is not None:
                    return obj, r
        return None

    def eventFilter(self, obj, e):
        if self.replaying:
            return False
        t = e.type()
        if t == QEvent.MouseButtonPress:
            if e.button() == Qt.LeftButton and synthesized(e):
                found = self.line_at(obj, e)
                if found is not None:
                    self._begin(obj, e, found)
            return False
        if self.obj is None or obj is not self.obj or not shiboken6.isValid(obj):
            return False
        if t == QEvent.MouseMove:
            if self.armed:
                return False
            if self.dead:
                return True
            if (e.position().toPoint() - self.start).manhattanLength() > SLOP_PX:
                self._take_back()                         # (a swipe: the press is undone where it was made)
            return True                                   # (nothing moves before the hold)
        if t == QEvent.MouseButtonRelease:
            swallow = self.dead
            self._end()
            return swallow
        return False

    def _begin(self, obj, e, found):
        self._end()
        self.obj, (host, rect) = obj, found
        self.start = e.position().toPoint()
        self.armed = self.dead = False
        self.host, self.rect = host, rect
        self.timer.start()

    def _arm(self):
        if self.obj is None or not shiboken6.isValid(self.obj) or self.dead:
            return
        self.armed = True
        self.light = Light(self.host, self.rect)
        haptic.tick()

    def _take_back(self):
        self.dead = True
        self.timer.stop()
        obj = self.obj
        g = obj.mapToGlobal(self.start)
        self.replaying = True
        try:
            QApplication.sendEvent(obj, QMouseEvent(QEvent.MouseButtonRelease, QPointF(self.start), QPointF(g), Qt.LeftButton,
                                                    Qt.NoButton, Qt.NoModifier))
        finally:
            self.replaying = False

    def _end(self):
        self.timer.stop()
        if self.light is not None and shiboken6.isValid(self.light):
            self.light.hide()
            self.light.deleteLater()
        self.light = None
        self.obj, self.armed, self.dead = None, False, False


_watch = None


def install():
    global _watch
    if active() and _watch is None:
        _watch = _Watch()
        QApplication.instance().installEventFilter(_watch)


def uninstall():
    global _watch
    if _watch is not None:
        _watch._end()
        QApplication.instance().removeEventFilter(_watch)
        _watch = None
