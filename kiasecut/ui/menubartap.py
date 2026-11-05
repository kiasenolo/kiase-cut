"""Going from one title of the menu bar to the next (or back to the same one) with a finger.

With a menu up, a press outside it goes to the menu (it has the grab) and closes it; a desktop's window system then lets the press
through to the menu bar, which opens the title it was on. Android does not: the press only closes the menu, so a finger that went
from one title to the next - or tapped the open one - left no menu at all, or the menu came up and was shut by the release.
Moves and hover over a menu or the menu bar are let through only with the finger down (a slide; see eventFilter). Here the press on a title of the bar, while one of its menus is up, is taken by the program: the same title closes the menu,
another title swaps it for its own; the release that follows is eaten.
"""
import sys

import shiboken6
from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMenu, QMenuBar

REDRAW_MS = (16, 60, 150, 400)     # a menu is drawn again this long after it comes up (see _redraw)
FORCE = False              # on for a desktop too (tests)


def active():
    return FORCE or sys.platform == "android"


class _Watch(QObject):
    def __init__(self):
        super().__init__()
        self.eat = False           # the release of a press taken here

    def eventFilter(self, obj, e):
        t = e.type()
        if t in (QEvent.MouseMove, QEvent.HoverMove, QEvent.HoverEnter) and isinstance(obj, (QMenu, QMenuBar)):
            if t == QEvent.MouseMove and e.buttons() & Qt.LeftButton:
                return False          # (a finger held down and slid over the titles or the items: that is a slide, as with a mouse)
            return True               # (but a hover - a finger lifted, or moved over before any press - opened and shut the menus a hundred
                                      #  times a second, a submenu open under another title among them, and the program crashed)
        if t == QEvent.Show and isinstance(obj, QMenu) and obj.isWindow():
            for ms in REDRAW_MS:
                QTimer.singleShot(ms, lambda m=obj: self._redraw(m))
            return False
        if t in (QEvent.Leave, QEvent.HoverLeave) and isinstance(obj, QMenu):
            return True               # (a menu that a submenu has come up over gets a Leave, and its sloppy-submenu timer then shut the submenu
                                      #  300 ms after a tap - there is no pointer to leave on a touch screen)
        if t == QEvent.MouseButtonRelease and self.eat and e.button() == Qt.LeftButton:
            self.eat = False
            return True
        if t == QEvent.MouseButtonPress and e.button() == Qt.LeftButton and isinstance(obj, QMenu) and obj.isWindow() \
                and isinstance(obj.parent(), QMenuBar) and obj.isVisible():
            return self._press(obj, e.globalPosition().toPoint())
        return False

    def _press(self, menu, g):
        if menu.rect().contains(menu.mapFromGlobal(g)):
            return False                                     # (inside the menu: its own)
        bar = menu.parent()
        act = bar.actionAt(bar.mapFromGlobal(g))
        if act is None or act.menu() is None:
            return False
        self.eat = True
        new = act.menu()
        menu.hide()
        if new is not menu:
            at = bar.mapToGlobal(bar.actionGeometry(act).bottomLeft())
            QTimer.singleShot(0, lambda: self._open(bar, act, new, at))      # (after the press is over and the old menu's hiding with it)
        return True


    @staticmethod
    def _redraw(menu):
        """A menu hidden and another shown within a few milliseconds (a slide over the titles) left the last one up for Qt and blank on the
        screen: its first drawing was made before the system's surface for it was there and Qt never drew it again. Drawn again here, a few
        times while it is up, it is on the screen whenever the surface comes. And raised: the menu's surface can be put behind the window's (it is up for Qt, takes
        the finger, and is not seen), and a raise puts it back on top."""
        if shiboken6.isValid(menu) and menu.isVisible():
            menu.raise_()
            menu.update()
            handle = menu.windowHandle()
            if handle is not None:
                handle.raise_()
                handle.requestUpdate()

    @staticmethod
    def _open(bar, act, new, at):
        if shiboken6.isValid(bar) and shiboken6.isValid(new):
            bar.setActiveAction(act)
            new.popup(at)


_watch = None


def install():
    global _watch
    if active() and _watch is None:
        _watch = _Watch()
        QApplication.instance().installEventFilter(_watch)


def uninstall():
    global _watch
    if _watch is not None and shiboken6.isValid(_watch):
        QApplication.instance().removeEventFilter(_watch)
    _watch = None
