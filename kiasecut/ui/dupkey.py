"""Shift+D, as in the node editor, on a list: the window's own Shift+D (copies of the selected clips) is not taken there, the
list's own copy action runs instead."""
from PySide6.QtCore import QEvent, QObject, Qt


class DuplicateKey(QObject):
    def __init__(self, widget, fn):
        super().__init__(widget)
        self.fn = fn
        widget.installEventFilter(self)

    def eventFilter(self, obj, e):
        t = e.type()
        if t in (QEvent.ShortcutOverride, QEvent.KeyPress) and e.key() == Qt.Key_D \
                and e.modifiers() & ~Qt.KeypadModifier == Qt.ShiftModifier:
            e.accept()
            if t == QEvent.KeyPress:
                self.fn()
            return True
        return False
