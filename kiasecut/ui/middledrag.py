"""Middle-button drag on anything that scrolls (中鍵拖拽): pressing the middle button inside a
scrolled area's content and dragging moves the content with the pointer, both ways it scrolls.

One watcher on the whole program does it for every scroll area - panels, lists, text boxes,
dialogs - so none needs code of its own. The area dragged is the nearest one around the press
that can scroll at all: a text box or list with nothing to scroll hands it on to the panel it
sits in. Widgets that drag their own view with the middle button (the timeline, the preview, the
curve editor) are not in a scroll area and keep it. A press on a scroll bar is left to it.
"""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QPlainTextEdit, QWidget

from . import appevents


def _area_at(w):
    """The nearest scroll area whose content holds widget w and that can scroll, else None."""
    inner = w
    while w is not None:
        if isinstance(w, QAbstractScrollArea) and inner is w.viewport() and (
                w.horizontalScrollBar().maximum() > w.horizontalScrollBar().minimum()
                or w.verticalScrollBar().maximum() > w.verticalScrollBar().minimum()):
            return w
        inner, w = w, w.parentWidget()
    return None


class _Drag(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.area = None
        appevents.watch(self, (QEvent.MouseButtonPress,), self._press)

    def _press(self, obj, e):
        if self.area is not None or e.button() != Qt.MiddleButton or not isinstance(obj, QWidget):
            return False
        area = _area_at(obj)
        if area is None:
            return False
        self.area, self.at = area, e.globalPosition()
        h, v = area.horizontalScrollBar(), area.verticalScrollBar()
        self.start = (h.value(), v.value())
        # a plain text box scrolls by lines up and down, everything else by pixels
        self.unit = area.fontMetrics().lineSpacing() if isinstance(area, QPlainTextEdit) else 1
        area.destroyed.connect(self._end)
        QGuiApplication.setOverrideCursor(Qt.ClosedHandCursor)
        self.app.installEventFilter(self)            # moves and the release, only while dragging
        return True

    def eventFilter(self, obj, e):
        t = e.type()
        if t == QEvent.MouseMove:
            if not e.buttons() & Qt.MiddleButton:    # (the release went somewhere unseen)
                self._end()
                return False
            d = e.globalPosition() - self.at
            h, v = self.area.horizontalScrollBar(), self.area.verticalScrollBar()
            h.setValue(self.start[0] - round(d.x()))
            v.setValue(self.start[1] - round(d.y() / self.unit))
            return True
        if t == QEvent.MouseButtonRelease and e.button() == Qt.MiddleButton:
            self._end()
            return True
        return t in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick)   # other buttons wait

    def _end(self, *_a):
        if self.area is None:
            return
        try:
            self.area.destroyed.disconnect(self._end)
        except (RuntimeError, TypeError):
            pass
        self.area = None
        self.app.removeEventFilter(self)
        QGuiApplication.restoreOverrideCursor()


_drag = None


def install():
    """Middle-button drag for every scroll area in the program (once)."""
    global _drag
    app = QApplication.instance()
    if _drag is None or _drag.app is not app:
        _drag = _Drag(app)
