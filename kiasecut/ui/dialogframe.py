"""A window frame for dialogs where the system gives none (Android): a title bar with the title, a ✕ that closes the dialog, the
bar dragged to move it, and an outline, so a question or the project manager is a window and not a patch of colour over the program.

install() watches for dialogs being made ready to show: each top-level QDialog that is not frameless already (nor a popup) is made
frameless, its contents moved down by the bar's height, and a Bar and an Outline laid over it as children (so nothing in the dialog's
own layout changes).
"""
from PySide6.QtCore import QEvent, QObject, QRect, Qt
from PySide6.QtGui import QFont, QPainter, QPalette, QPen
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from . import appevents

BAR_H = 48               # the title bar's height (a finger's)
CLOSE_W = 64             # the ✕'s width
OUTLINE = 2


class Bar(QWidget):
    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.drag = None                                       # (global press, dialog position) while it is moved
        self.setFixedHeight(BAR_H)
        dialog.windowTitleChanged.connect(lambda _t: self.update())

    def close_rect(self):
        return QRect(self.width() - CLOSE_W, 0, CLOSE_W, self.height())

    def paintEvent(self, e):
        pal = self.palette()
        p = QPainter(self)
        p.fillRect(self.rect(), pal.color(QPalette.Button).darker(115))
        text = pal.color(QPalette.WindowText)
        font = QFont(self.font())
        font.setBold(True)
        p.setFont(font)
        p.setPen(text)
        title = self.dialog.windowTitle() or QApplication.applicationDisplayName() or "KiaseCut"
        room = self.width() - CLOSE_W - 24
        p.drawText(QRect(16, 0, room, self.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   p.fontMetrics().elidedText(title, Qt.ElideRight, room))
        c = self.close_rect().center()
        d = 7
        p.setPen(QPen(text, 2.2))
        p.drawLine(c.x() - d, c.y() - d, c.x() + d, c.y() + d)
        p.drawLine(c.x() - d, c.y() + d, c.x() + d, c.y() - d)
        p.setPen(QPen(pal.color(QPalette.Mid), 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not self.close_rect().contains(e.position().toPoint()):
            self.drag = (e.globalPosition().toPoint(), self.dialog.pos())

    def mouseMoveEvent(self, e):
        if self.drag is not None:
            start, pos = self.drag
            at = pos + e.globalPosition().toPoint() - start
            screen = self.dialog.screen().availableGeometry()
            at.setX(max(screen.left() - self.dialog.width() + CLOSE_W, min(at.x(), screen.right() - CLOSE_W)))
            at.setY(max(screen.top(), min(at.y(), screen.bottom() - BAR_H)))
            self.dialog.move(at)

    def mouseReleaseEvent(self, e):
        moved, self.drag = self.drag is not None and e.globalPosition().toPoint() != self.drag[0], None
        if not moved and e.button() == Qt.LeftButton and self.close_rect().contains(e.position().toPoint()):
            self.dialog.reject()


class Outline(QWidget):
    """The dialog's border, drawn over its contents (the mouse goes through it)."""

    def __init__(self, dialog):
        super().__init__(dialog)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setPen(QPen(self.palette().color(QPalette.Mid).lighter(130), OUTLINE))
        p.drawRect(self.rect().adjusted(OUTLINE // 2, OUTLINE // 2, -OUTLINE // 2 - 1, -OUTLINE // 2 - 1))


class _Frame(QObject):
    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.bar, self.outline = Bar(dialog), Outline(dialog)
        m = dialog.contentsMargins()
        dialog.setContentsMargins(m.left() + OUTLINE, m.top() + BAR_H, m.right() + OUTLINE, m.bottom() + OUTLINE)
        dialog.installEventFilter(self)
        self.place()

    def place(self):
        d = self.dialog
        self.bar.setGeometry(OUTLINE, OUTLINE, max(0, d.width() - 2 * OUTLINE), BAR_H - OUTLINE)
        self.outline.setGeometry(0, 0, d.width(), d.height())
        self.outline.raise_()
        self.bar.raise_()

    def eventFilter(self, obj, e):
        if obj is self.dialog and e.type() in (QEvent.Resize, QEvent.Show, QEvent.ChildAdded, QEvent.LayoutRequest):
            self.place()
        return False


def frame(dialog):
    """Give dialog the frame (once)."""
    if dialog.property("kcFramed"):
        return
    dialog.setProperty("kcFramed", True)
    dialog.setWindowFlag(Qt.FramelessWindowHint, True)
    _Frame(dialog)


def install():
    def polished(obj, e):
        if isinstance(obj, QDialog) and obj.isWindow() and not obj.property("kcFramed") \
                and obj.windowType() != Qt.Popup and not obj.windowFlags() & Qt.FramelessWindowHint:
            frame(obj)
        return False
    appevents.watch(QApplication.instance(), [QEvent.Polish], polished)
