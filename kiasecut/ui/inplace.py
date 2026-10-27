"""Renaming and colour picking where the thing is, not in a window in the middle of the screen.

ask_name lays a name field over the item's own name (its row in a list, a clip's label, a track
header, a tab), the old name selected: Enter or a click elsewhere keeps what was typed, Esc
leaves the old name. ColorPopup (colorpick.pick_color) opens just under the item - the swatch
button pressed, the clip, the track - so the eye stays where it was.

Both are child widgets of the item's window (no window of their own: placed exactly, and the
input method works as in any other field). While one is open, the first click outside it only
closes it (that click goes nowhere else) and the window's shortcuts stay off.

Where they open: the place a panel gave with hint() just before it asked for the rename / the
colour (main window's handlers do not know which panel asked: the layer list and the timeline
rename the same clip), else the `anchor` the caller passes, else the button under the pointer,
else the pointer itself. An anchor is a widget (all of it) or (widget, QRect in its coordinates).
"""
from PySide6.QtCore import QEvent, QEventLoop, QObject, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QAbstractButton, QApplication, QFrame, QLineEdit, QListView, QTreeWidget, QWidget

_hint = None


def hint(widget, rect=None):
    """The next ask_name / pick_color opens at rect of widget (its coordinates; all of it by
    default). Forgotten as soon as the events of now are done."""
    global _hint
    _hint = (widget, QRect(rect) if rect is not None else widget.rect())
    QTimer.singleShot(0, _forget)


def _forget():
    global _hint
    _hint = None


def item_hint(view, item, column=0):
    """hint() at the name of a QListWidget / QTreeWidget item (its column), when it is in view."""
    if item is None:
        return
    tree = isinstance(view, QTreeWidget)
    r = view.visualRect(view.indexFromItem(item, column) if tree else view.indexFromItem(item))
    if isinstance(view, QListView) and view.viewMode() == QListView.IconMode:
        r.setTop(r.top() + view.iconSize().height() + 4)       # (the name under the picture)
        r.setHeight(view.fontMetrics().height() + 8)
    elif not (item.icon(column) if tree else item.icon()).isNull():
        r.setLeft(r.left() + view.iconSize().width() + 4)
    if r.isValid() and view.viewport().rect().intersects(r):
        hint(view.viewport(), r)


def anchor_of(anchor=None):
    """(widget, QRect) where to open: the hint, else anchor, else the button / point under the pointer."""
    a = _hint or anchor
    if isinstance(a, QWidget):
        a = (a, a.rect())
    if a is not None and a[0] is not None and a[0].isVisible():
        return a[0], QRect(a[1])
    gp = QCursor.pos()
    w = QApplication.widgetAt(gp)
    if w is None:
        w = QApplication.activeWindow()
        return (w, QRect(w.rect().center(), QSize(1, 1))) if w is not None else (None, QRect())
    b = w
    while b is not None and not isinstance(b, QAbstractButton):
        b = b.parentWidget()
    if b is not None and b.window() is w.window():
        return b, b.rect()
    return w, QRect(w.mapFromGlobal(gp), QSize(1, 1))


class Overlay(QFrame):
    """A frame over its window, run() until finish(): True kept, False not."""

    def __init__(self, widget):
        super().__init__(widget.window())
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.loop, self.ok, self._done = QEventLoop(), False, False

    def run(self, focus):
        app = QApplication.instance()
        before = app.focusWidget()
        app.installEventFilter(self)
        self.show()
        self.raise_()
        focus.setFocus(Qt.PopupFocusReason)
        self.loop.exec()
        app.removeEventFilter(self)
        self.hide()
        self.deleteLater()
        if before is not None and before.isVisible():
            before.setFocus(Qt.OtherFocusReason)
        return self.ok

    def finish(self, ok):
        if not self._done:
            self._done, self.ok = True, ok
            self.about_to_finish(ok)
            self.loop.quit()

    def about_to_finish(self, ok):
        pass

    def _inside(self, obj):
        return isinstance(obj, QWidget) and (obj is self or self.isAncestorOf(obj))

    def eventFilter(self, obj, e):
        t = e.type()
        if self._done:
            return False
        if t in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick, QEvent.Wheel):
            gp = e.globalPosition().toPoint()
            if not QRect(self.mapToGlobal(QPoint(0, 0)), self.size()).contains(gp):
                self.finish(True)                        # (the click only closes it)
                return True
        elif t == QEvent.ShortcutOverride and self._inside(obj):
            e.accept()                                   # keys go to the field, not the window's shortcuts
        elif t == QEvent.KeyPress and self._inside(obj):
            if e.key() == Qt.Key_Escape:
                self.finish(False)
                return True
            if e.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.finish(True)
                return True
        elif t == QEvent.ApplicationDeactivate:
            self.finish(True)
        return False


def window_rect(widget, rect):
    """rect of widget in its window's coordinates."""
    return QRect(widget.mapTo(widget.window(), rect.topLeft()), rect.size())


def ask_name(parent, text, anchor=None):
    """(name, ok) as QInputDialog.getText: a field over the item's name, the old one selected;
    not ok when the name was left as it was."""
    w, r = anchor_of(anchor)
    if w is None:
        return text, False
    win = w.window()
    r = window_rect(w, r.intersected(w.rect()) if w.rect().intersects(r) else r)
    ov = Overlay(w)
    ov.setObjectName("inplace")
    ov.setStyleSheet("QFrame#inplace { background: transparent; }"
                     "QLineEdit { background: #141416; color: #f2f2f2; border: 1px solid #5b8cff;"
                     " border-radius: 2px; padding: 1px 4px; selection-background-color: #3d5fb0; }")
    field = QLineEdit(text, ov)
    fm = field.fontMetrics()
    h = max(fm.height() + 8, min(r.height(), fm.height() + 12))
    wd = max(160, min(r.width(), 420), fm.horizontalAdvance(text) + 40)
    x = max(0, min(r.left(), win.width() - wd))
    y = max(0, min(r.center().y() - h // 2 + 1, win.height() - h))
    ov.setGeometry(x, y, min(wd, win.width()), h)
    field.setGeometry(0, 0, ov.width(), h)
    field.selectAll()
    ok = ov.run(field)
    return field.text(), ok and field.text() != text
