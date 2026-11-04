"""A window frame for dialogs where the system gives none (Android): a title bar (after Kilo's window: the title centred, a slanted ✕
button) that closes the dialog, the bar dragged to move it, and an outline, so a question or the project manager is a window and not a patch of colour over the program.

install() watches for dialogs being made ready to show: each top-level QDialog that is not frameless already (nor a popup) is made
frameless, its contents moved down by the bar's height, and a Bar and an Outline laid over it as children (so nothing in the dialog's
own layout changes).
"""
from PySide6.QtCore import QEvent, QObject, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from . import appevents

BAR_H = 32               # the title bar's height
BTN_W = 64               # the ✕ button's width at its top edge
SKEW = 0.5774            # tan 30 degrees: the button's left edge leans this far per pixel of height
OUTLINE = 2
ICON = 6                 # half the width of the ✕


class Bar(QWidget):
    """The title bar after Kilo's window: the title centred, a slanted button at the right (it turns white under the finger or mouse)."""

    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.drag = None                                       # (global press, dialog position) while it is moved
        self.last = None                                       # the finger's last reading
        self.down = self.over = False                          # the ✕ is pressed / under the mouse
        self.setFixedHeight(BAR_H)
        self.setMouseTracking(True)
        dialog.windowTitleChanged.connect(lambda _t: self.update())

    def close_shape(self):
        h, w = self.height(), self.width()
        k = h * SKEW
        return QPolygonF([QPointF(w - BTN_W, 0), QPointF(w, 0), QPointF(w, h), QPointF(w - BTN_W + k, h)])

    def on_close(self, pos):
        return self.close_shape().containsPoint(QPointF(pos), Qt.OddEvenFill)

    def paintEvent(self, e):
        pal = self.palette()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), pal.color(QPalette.Window).lighter(145))
        text = pal.color(QPalette.WindowText)
        font = QFont(self.font())
        p.setFont(font)
        p.setPen(text)
        title = self.dialog.windowTitle() or QApplication.applicationDisplayName() or "KiaseCut"
        room = self.width() - 2 * BTN_W - 8
        p.drawText(QRect((self.width() - room) // 2, 0, room, self.height()), Qt.AlignCenter,
                   p.fontMetrics().elidedText(title, Qt.ElideRight, room))
        hot = self.down or self.over
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 255 if hot else 30))
        p.drawPolygon(self.close_shape())
        c = QPointF(self.width() - BTN_W / 2 + self.height() * SKEW / 4, self.height() / 2)
        p.setPen(QPen(QColor("#111114") if hot else text, 1.8, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(c.x() - ICON, c.y() - ICON), QPointF(c.x() + ICON, c.y() + ICON))
        p.drawLine(QPointF(c.x() - ICON, c.y() + ICON), QPointF(c.x() + ICON, c.y() - ICON))

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self.on_close(e.position().toPoint()):
            self.down = True
            self.update()
        else:
            self.drag, self.last = (e.globalPosition().toPoint(), self.dialog.pos()), None

    def mouseMoveEvent(self, e):
        over = self.on_close(e.position().toPoint())
        if over != self.over:
            self.over = over
            self.update()
        if self.drag is not None:
            start, pos = self.drag
            # (where the finger is comes from the window's position when the event was made, which lags the one asked for, now
            # by one step and then by none: the two last readings are averaged, or the window shakes as it follows the finger)
            g = e.globalPosition()
            seen, self.last = (g if self.last is None else (g + self.last) / 2), g
            at = pos + seen.toPoint() - start
            screen = self.dialog.screen().availableGeometry()
            at.setX(max(screen.left() - self.dialog.width() + BTN_W, min(at.x(), screen.right() - BTN_W)))
            at.setY(max(screen.top(), min(at.y(), screen.bottom() - BAR_H)))
            self.dialog.move(at)

    def leaveEvent(self, e):
        self.over = False
        self.update()

    def mouseReleaseEvent(self, e):
        closing = self.down and self.on_close(e.position().toPoint())
        self.down, self.drag = False, None
        self.update()
        if closing and e.button() == Qt.LeftButton:
            self.dialog.reject()


class Outline(QWidget):
    """The dialog's border, drawn over its contents (the mouse goes through it)."""

    def __init__(self, dialog):
        super().__init__(dialog)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setPen(QPen(QColor(255, 255, 255, 60), OUTLINE))
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
