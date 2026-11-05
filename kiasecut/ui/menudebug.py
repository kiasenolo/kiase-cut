"""A log of what happens to the menu bar and its menus (on Android it goes to logcat, tag `python`; KIASECUT_MENUDEBUG=1 on a desktop
prints it to stderr): every mouse press / release (and moves, thinned out) and touch that goes to a menu, a menu bar or the widget
under it, and every menu shown or hidden, with where, what made the mouse event (a real mouse or the program's touch) and which
popup is up. Taken out once the menu trouble on the tablet is found."""
import os
import sys
import time

import shiboken6
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QMenu, QMenuBar

from . import appevents

KINDS = {QEvent.MouseButtonPress: "press", QEvent.MouseButtonRelease: "release", QEvent.MouseMove: "move",
         QEvent.TouchBegin: "touch-begin", QEvent.TouchEnd: "touch-end", QEvent.TouchCancel: "touch-cancel",
         QEvent.Show: "show", QEvent.Hide: "hide", QEvent.WindowActivate: "win-activate", QEvent.WindowDeactivate: "win-deactivate",
         QEvent.FocusOut: "focus-out", QEvent.FocusIn: "focus-in", QEvent.Close: "close", QEvent.ApplicationDeactivate: "app-deactivate",
         QEvent.ApplicationActivate: "app-activate", QEvent.Leave: "leave", QEvent.ContextMenu: "context-menu",
         QEvent.HoverLeave: "hover-leave", QEvent.ShortcutOverride: "shortcut-override", QEvent.KeyPress: "key"}
OTHER = (QEvent.WindowActivate, QEvent.WindowDeactivate, QEvent.FocusOut, QEvent.FocusIn, QEvent.Close, QEvent.ApplicationDeactivate,
         QEvent.ApplicationActivate, QEvent.Leave, QEvent.ContextMenu, QEvent.HoverLeave, QEvent.KeyPress)
_last_move = [0.0]


def active():
    return sys.platform == "android" or bool(os.environ.get("KIASECUT_MENUDEBUG"))


def log(text):
    print(f"[menudbg {time.monotonic() % 1000:8.3f}] {text}", file=sys.stderr, flush=True)


def name(w):
    if w is None:
        return "-"
    n = type(w).__name__
    if isinstance(w, QMenu):
        n += f"({w.title() or w.objectName()})"
    return f"{n}@{id(w) & 0xffff:04x}"


def popup_up():
    return QApplication.activePopupWidget() is not None


def watched(obj):
    return isinstance(obj, (QMenu, QMenuBar))


def handler(obj, e):
    t = e.type()
    if not isinstance(obj, __import__("PySide6.QtWidgets", fromlist=["QWidget"]).QWidget) or not shiboken6.isValid(obj):
        return False
    if t in OTHER:
        if popup_up() or isinstance(obj, (QMenu, QMenuBar)):
            log(f"{KINDS[t]:<14} on {name(obj)} popup={name(QApplication.activePopupWidget())}")
        return False
    if t in (QEvent.TouchBegin, QEvent.TouchEnd, QEvent.TouchCancel) and popup_up():
        log(f"{KINDS[t]:<11} on {name(obj)} popup={name(QApplication.activePopupWidget())}")
        return False
    if t in (QEvent.Show, QEvent.Hide):
        if isinstance(obj, QMenu):
            log(f"{KINDS[t]:<6} {name(obj)} parent={name(obj.parent())} popup={name(QApplication.activePopupWidget())}")
        return False
    popup = QApplication.activePopupWidget()
    if not (watched(obj) or watched(popup)) and t in (QEvent.MouseMove, QEvent.TouchBegin, QEvent.TouchEnd, QEvent.TouchCancel):
        return False
    if t == QEvent.MouseMove:
        now = time.monotonic()
        if now - _last_move[0] < 0.15:
            return False
        _last_move[0] = now
    if t in (QEvent.TouchBegin, QEvent.TouchEnd, QEvent.TouchCancel):
        log(f"{KINDS[t]:<11} on {name(obj)} popup={name(popup)}")
        return False
    g = e.globalPosition().toPoint()
    bar = popup.parent() if isinstance(popup, QMenu) and isinstance(popup.parent(), QMenuBar) else None
    act = bar.actionAt(bar.mapFromGlobal(g)) if bar is not None else None
    log(f"{KINDS[t]:<7} on {name(obj)} at {g.x()},{g.y()} src={int(e.source().value) if hasattr(e.source(), 'value') else e.source()} "
        f"popup={name(popup)} title_under={act.text() if act is not None else '-'}")
    return False


def install():
    if not active():
        return
    app = QApplication.instance()
    appevents.watch(app, [QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseMove, QEvent.TouchBegin, QEvent.TouchEnd,
                          QEvent.TouchCancel, QEvent.Show, QEvent.Hide, *OTHER], handler)
    log("menu debug on")
