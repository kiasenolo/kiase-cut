"""The Esc key leaves a field, and Android's Back key is Esc.

Esc in a number, a line of text or a text box takes the focus out of it (a turn later, when whatever else handles Esc there - an
editor that closes itself, a dialog that is dismissed - has had its say; if the focus is still in the field then, it is taken out).
The text typed is kept, as when the focus leaves in any other way.

On Android the system's Back key arrives as Key_Back, which the program would end by: it is made an Esc key (pressed and released)
at the widget that has the focus, or the menu that is open - so Back closes a menu, leaves a field, puts a fullscreen preview or a tool
away, as Esc does on a desktop.
"""
import sys

import shiboken6
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QLineEdit, QPlainTextEdit, QTextEdit

from . import appevents

FORCE = False                   # Back is Esc on a desktop too (tests)
_installed = False


def is_field(w):
    """Whether w is a field text is typed in (and not one that only shows text)."""
    if isinstance(w, (QLineEdit, QAbstractSpinBox)):
        return not (isinstance(w, QLineEdit) and w.isReadOnly())
    if isinstance(w, (QPlainTextEdit, QTextEdit)):
        return not w.isReadOnly()
    return False


def leave(w):
    """Take the focus out of w if it is still there."""
    if not shiboken6.isValid(w) or QApplication.focusWidget() is not w:
        return
    w.clearFocus()


def target():
    """The widget a key goes to: the open menu, else the one with the focus, else the window."""
    app = QApplication.instance()
    return app.activePopupWidget() or app.focusWidget() or app.activeWindow()


def back_is_esc():
    return FORCE or sys.platform == "android"


def install():
    global _installed
    if _installed:
        return
    _installed = True

    def pressed(obj, e):
        if e.key() == Qt.Key_Back and back_is_esc() and not e.isAutoRepeat():
            to = target()
            if to is not None:
                for kind in (QEvent.KeyPress, QEvent.KeyRelease):
                    QApplication.sendEvent(to, QKeyEvent(kind, Qt.Key_Escape, Qt.NoModifier))
            return True                                     # (taken: Back does not end the program)
        if e.key() == Qt.Key_Escape and not e.modifiers() and not e.isAutoRepeat():
            w = QApplication.focusWidget()
            if w is not None and is_field(w) and QApplication.activePopupWidget() is None:
                QTimer.singleShot(0, lambda w=w: leave(w))
        return False

    def override(obj, e):
        # (Esc is a shortcut of the window - 返回上一層 - and a shortcut is made before a key press is: the field says it takes the key)
        if e.key() == Qt.Key_Escape and not e.modifiers():
            w = QApplication.focusWidget()
            if w is not None and is_field(w) and QApplication.activePopupWidget() is None:
                e.accept()
        return False

    def released(obj, e):
        return e.key() == Qt.Key_Back and back_is_esc()    # (its release goes with it)

    app = QApplication.instance()
    appevents.watch(app, [QEvent.KeyPress], pressed)
    appevents.watch(app, [QEvent.KeyRelease], released)
    appevents.watch(app, [QEvent.ShortcutOverride], override)
