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
from . import touch

HOLD_MS = 450
THIN = 40                  # px: a gap between panels thicker than this is not a line
MIN_LINE = 30              # px: and one shorter than this is not either
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

    def extent(dx, dy, limit):
        """How many px from `at` the empty space goes in this direction (steps of 1 for the short way, coarse and then 1 for the
        long way): at most `limit`."""
        n = 0
        step = 1 if limit <= THIN else 8
        while n < limit and not reaches(at.x() + dx * (n + step), at.y() + dy * (n + step)):
            n += step
        while n < limit and not reaches(at.x() + dx * (n + 1), at.y() + dy * (n + 1)):
            n += 1
        return n

    x, y = at.x(), at.y()
    across_x = extent(-1, 0, THIN) + extent(1, 0, THIN) + 1            # a vertical line is thin this way
    across_y = extent(0, -1, THIN) + extent(0, 1, THIN) + 1            # a horizontal line is thin this way
    if min(across_x, across_y) > THIN:
        return None
    from PySide6.QtCore import QRect
    if across_x <= across_y:                                           # a vertical line: long along y
        up, down = extent(0, -1, window.height()), extent(0, 1, window.height())
        r = QRect(x - extent(-1, 0, THIN), y - up, across_x, up + down + 1)
    else:                                                              # a horizontal one: long along x
        left, right = extent(-1, 0, window.width()), extent(1, 0, window.width())
        r = QRect(x - left, y - extent(0, -1, THIN), left + right + 1, across_y)
    return r if max(r.width(), r.height()) >= MIN_LINE else None       # (a crumb of space between panels is not a line)


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
        self.watchdog = QTimer(self)                      # (a light left up because no release came for the line: put out)
        self.watchdog.setInterval(150)
        self.watchdog.timeout.connect(self._check)

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
        if t == QEvent.MouseButtonRelease and self.obj is not None and obj is not self.obj and e.button() == Qt.LeftButton:
            self._end()                                   # (the release went to another widget: the line is let go all the same)
            return False
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
                at = e.position().toPoint()
                QTimer.singleShot(0, lambda at=at: self._follow(at))
                QTimer.singleShot(60, lambda at=at: self._follow(at))      # (and again when the layout has caught up)
                return False
            if self.dead:
                return True
            if (e.position().toPoint() - self.start).manhattanLength() > touch.slop():
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
        self.watchdog.start()
        haptic.tick()

    def _check(self):
        if not QApplication.mouseButtons() & Qt.LeftButton:
            self._end()

    def _follow(self, at):
        """The line has moved with the finger: the light goes with it."""
        if self.light is None or self.obj is None or not shiboken6.isValid(self.obj) or not shiboken6.isValid(self.light):
            return
        found = None
        horizontal = self.rect.width() > self.rect.height()
        for k in range(0, 16):                            # (the line is a little behind or ahead of the finger that drags it)
            for sign in (1, -1) if k else (1,):
                d = QPoint(0, 3 * k * sign) if horizontal else QPoint(3 * k * sign, 0)
                found = self.line_at_pos(self.obj, at + d)
                if found is not None:
                    break
            if found is not None:
                break
        if found is not None:
            self.light.setParent(found[0])
            self.light.setGeometry(found[1])
            self.rect = found[1]
            self.light.show()
            self.light.raise_()

    @staticmethod
    def line_at_pos(obj, at):
        if isinstance(obj, QSplitterHandle):
            return obj, obj.rect()
        if isinstance(obj, QMainWindow):
            r = gap_rect(obj, at)
            return (obj, r) if r is not None else None
        return None

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
        self.watchdog.stop()
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
