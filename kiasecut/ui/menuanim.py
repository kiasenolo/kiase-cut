"""Menus open and close the way Kilo's (the e621 app's) do: unrolled from the top, `clip-path: polygon(0 0, 100% 0, 100% 0, 0 0)`
to `polygon(0 0, 100% 0, 100% 100%, 0 100%)`, in a quarter of a second on cubic-bezier(0, .5, 0, 1) - most of it at once,
a long soft end - and rolled up and faded out the same way when they close.

There the menu is one element shared by all that open: going from one to another is no animation, only the opening of the
first and the closing of the last are. Here the menus of a menu bar are windows of their own, so moving from one to another
(one is hidden and the next shown in the same turn of the event loop, or the next shown while the last is still up) is only
a swap, with nothing animated; every other opening (a lone menu, a context menu, a submenu, a combo box's list) is unrolled,
and every other closing is a picture of the menu, a child widget of the window it was over that lets the mouse through, rolled up
and gone. (Not a window of its own: on Wayland a window of the popup kind, made and destroyed while the next menu's popup is up,
makes the compositor dismiss that popup - clicking from one title to the next, or to the same one, made the menu vanish.)

A menu (the menu bar's, a context menu, a combo box's list) is a window of its own, so it is not the page's clip-path: a
QGraphicsEffect on it draws it clipped to the part from the top down that the animation has got to, the effect going when
the animation ends. A QMenu window is made frameless and without the window manager's shadow (square, flat).
install() watches for menus and combo lists being made ready and being shown.
"""
import os
import sys
import time

import shiboken6
from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QApplication, QComboBox, QGraphicsEffect, QMenu, QMenuBar, QWidget

from . import appevents, motion

DURATION_MS = 250
DEBUG = bool(os.environ.get("KIASECUT_MENUANIM_DEBUG"))      # set it and run the program from a terminal: every opening is logged


def log(menu, what):
    if DEBUG:
        title = menu.title() if hasattr(menu, "title") else type(menu).__name__
        print(f"[menuanim {time.monotonic() % 1000:8.3f}] {what:<8} {title or type(menu).__name__} @{id(menu) & 0xffff:04x}", file=sys.stderr, flush=True)


def animated():
    """Whether menus animate: everywhere, the tablet too (KIASECUT_MENUANIM=0 turns it off). The invisible menus and the crashes the tablet
    had with it were found elsewhere - a slide over the titles switching menus faster than Android could show them (menubartap.py)."""
    return os.environ.get("KIASECUT_MENUANIM") != "0"


def curve():
    return motion.out_curve()                         # cubic-bezier(0, .5, 0, 1)


class Pop(QGraphicsEffect):
    """The menu drawn from its top down to `t` of its height (0: nothing yet, 1: all of it)."""

    def __init__(self, menu):
        super().__init__(menu)
        self.t = 0.0
        self.anim = None                                   # starts when the menu is first drawn, not when it is shown
        self.begun = False

    def draw(self, painter):
        if not self.begun:                                 # (a menu that is slow to come up - its items built, the program busy - would
            self.begun = True                              #  have run its half second before anything of it was on screen)
            QTimer.singleShot(0, self._begin)
        pm = self.sourcePixmap(Qt.LogicalCoordinates)
        if pm.isNull() or self.t >= 1.0:
            self.drawSource(painter)
            return
        t = max(0.0, self.t)
        off = self.sourceBoundingRect(Qt.LogicalCoordinates).topLeft()
        size = pm.deviceIndependentSize()
        if t > 0.0:                                          # (the top part of the picture: a clip, drawn as a piece of it)
            painter.drawPixmap(QRectF(off.x(), off.y(), size.width(), size.height() * t), pm,
                               QRectF(0, 0, pm.width(), pm.height() * t))

    def _begin(self):
        if not shiboken6.isValid(self):                    # (the menu was closed, or opened again, before it was first drawn)
            return
        log(self.parent(), "begin")
        if self.anim is not None and shiboken6.isValid(self.anim) and self.anim.state() != QVariantAnimation.Running:
            self.anim.start()


def pop(menu):
    """Prepare the opening of menu (shown just now): it runs from the first time the menu is drawn."""
    log(menu, "shown")
    old = menu.property("kcPop")
    if old is not None and shiboken6.isValid(old):         # (the one of an earlier opening that has not finished: gone, with its effect)
        old.stop()
        old.deleteLater()
    effect = Pop(menu)
    menu.setGraphicsEffect(effect)                         # (this deletes the effect an earlier opening left)
    anim = QVariantAnimation(menu)
    anim.setDuration(DURATION_MS)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(curve())
    effect.anim = anim

    def step(v):
        effect.t = float(v)
        effect.update()

    def done():
        if shiboken6.isValid(effect) and menu.graphicsEffect() is effect:
            menu.setGraphicsEffect(None)
        if menu.property("kcPop") is anim:
            menu.setProperty("kcPop", None)
        log(menu, "done")
        anim.deleteLater()                                 # (one animation made for each opening: none left behind on a menu that is opened often)

    anim.valueChanged.connect(step)
    anim.finished.connect(done)
    menu.setProperty("kcPop", anim)
    step(0.0)


def popup_window(obj):
    """Whether obj is a menu window or the window of a combo box's list."""
    if not isinstance(obj, QWidget):                  # (Show events also come for a QWindow)
        return False
    if isinstance(obj, QMenu):
        return obj.isWindow()
    return obj.isWindow() and obj.metaObject().className() == "QComboBoxPrivateContainer"


def bar_menu(obj):
    """Whether obj is one of a menu bar's menus (the title of one is in the bar)."""
    return isinstance(obj, QMenu) and isinstance(obj.parent(), QMenuBar)


def others_open(menu):
    """Whether another menu of the same menu bar is up: moving from one title to the next."""
    bar = menu.parent()
    for a in bar.actions():
        m = a.menu()
        if m is not None and m is not menu and shiboken6.isValid(m) and m.isVisible():
            return True
    return False


def settle(menu):
    """Show menu as it is, with nothing animated (a swap of one menu for another)."""
    old = menu.property("kcPop")
    if old is not None and shiboken6.isValid(old):
        old.stop()
        old.deleteLater()
    menu.setProperty("kcPop", None)
    if menu.graphicsEffect() is not None:
        menu.setGraphicsEffect(None)


class Ghost(QWidget):
    """What a closed menu was, rolled up and faded out: a picture over the window, a child of it that lets the mouse through."""

    def __init__(self, parent, picture, rect, t0):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.picture = picture
        self.t = t0
        self.source = None
        self.setGeometry(QRect(parent.mapFromGlobal(rect.topLeft()), rect.size()))     # (rect: the menu's, on the screen)
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(DURATION_MS)
        self.anim.setStartValue(t0)
        self.anim.setEndValue(0.0)
        self.anim.setEasingCurve(curve())
        self.anim.valueChanged.connect(self._step)
        self.anim.finished.connect(self.end)
        self.destroyed.connect(lambda _o=None, me=self: _ghosts.remove(me) if me in _ghosts else None)

    def _step(self, v):
        self.t = float(v)
        self.update()

    def paintEvent(self, e):
        if self.t <= 0.0:
            return
        p = QPainter(self)
        p.setOpacity(self.t)
        size = self.picture.deviceIndependentSize()
        p.drawPixmap(QRectF(0, 0, size.width(), size.height() * self.t), self.picture,
                     QRectF(0, 0, self.picture.width(), self.picture.height() * self.t))

    def start(self):
        self.show()
        self.raise_()
        self.anim.start()

    def end(self):
        if self in _ghosts:
            _ghosts.remove(self)
        self.hide()
        self.deleteLater()


_ghosts = []
_pending = []          # the closing of a menu bar's menu, waiting to see whether another one opens in its place


def drop_ghosts(source=None):
    for g in list(_ghosts):
        if source is None or g.source is source:
            g.anim.stop()
            g.end()


def close_ghost(menu, picture, rect, t0):
    parent = menu.parentWidget()
    while parent is not None and parent.windowType() == Qt.Popup:      # (a submenu's parent is a menu: the picture goes on the window under them,
        parent = parent.parentWidget()                                 #  a popup is no place for a child widget - it brought the program down)
    parent = parent.window() if parent is not None else QApplication.activeWindow()
    if parent is not None and parent.windowType() == Qt.Popup:
        parent = None
    if parent is None or not QRect(parent.mapToGlobal(QPoint(0, 0)), parent.size()).contains(rect):
        return                                            # (a menu out over the edge of its window has no picture to roll up: it only goes)
    g = Ghost(parent, picture, rect, t0)
    g.source = menu
    _ghosts.append(g)
    log(menu, "closing")
    g.start()


def closed(menu):
    """menu has just been hidden: its picture rolls up (unless another menu of its bar takes its place)."""
    if QApplication.closingDown() or not animated():
        return
    if bar_menu(menu) and others_open(menu):
        settle(menu)
        return
    effect, t0 = menu.graphicsEffect(), 1.0
    if isinstance(effect, Pop) and effect.t < 1.0:
        t0 = max(0.0, effect.t)                           # (closed while it was still opening: it rolls back from where it was)
    settle(menu)
    picture = menu.grab()
    rect = QRect(menu.geometry())
    if picture.isNull() or rect.isEmpty() or t0 <= 0.0:
        return
    if bar_menu(menu):
        job = [menu, picture, rect, t0]
        _pending.append(job)

        def later():
            if job in _pending:                           # (no other menu has been shown meanwhile)
                _pending.remove(job)
                close_ghost(*job)
        QTimer.singleShot(0, later)
    else:
        close_ghost(menu, picture, rect, t0)


def opened(menu):
    """menu has just been shown."""
    if not animated():
        return
    if bar_menu(menu):
        swapped = bool(_pending) or others_open(menu)
        del _pending[:]                                   # (a menu of the bar closed just before: this one takes its place)
        for g in list(_ghosts):
            if bar_menu(g.source):
                g.anim.stop()
                g.end()
        if swapped:
            log(menu, "swapped")
            settle(menu)
            return
    pop(menu)


def install():
    def made(obj, e):
        if isinstance(obj, QMenu) and obj.isWindow() and not obj.windowFlags() & Qt.FramelessWindowHint:
            obj.setWindowFlags(obj.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)     # (flat: no frame, no shadow)
        return False

    def shown(obj, e):
        if popup_window(obj):
            try:
                opened(obj)
            except RuntimeError:
                pass
        return False

    def hidden(obj, e):
        if popup_window(obj):
            try:
                box = obj.parentWidget()
                if isinstance(box, QComboBox) and not box.isEditable():
                    box.clearFocus()                          # (list closed, chosen or not: the box is not left focused)
                closed(obj)
            except RuntimeError:                              # (the menu is being deleted: a Hide comes as its window goes)
                pass
        return False

    app = QApplication.instance()
    appevents.watch(app, [QEvent.Polish], made)
    appevents.watch(app, [QEvent.Show], shown)
    appevents.watch(app, [QEvent.Hide], hidden)
