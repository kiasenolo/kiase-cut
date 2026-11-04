"""Motion for the interface, after Kilo's CSS (styles/globals.scss: every property transitions in .5 s on cubic-bezier(0, .5, 0, 1);
kiaseStyle.scss: a button turns white at once under the mouse, fades back slowly when it leaves, goes grey in .3 s when pressed).

Qt's style sheets cannot animate (and the program-wide `QWidget { color }` rule makes Qt's style sheet style draw a button's text
itself, in that colour), so a push or tool button paints itself: its Fader takes the paint event and draws the fill, icon and
text from the two colours it keeps, the fill and the ink. The Fader watches the button (mouse in and out, press, release, checked,
enabled) and moves both colours to what the new state asks, in the time that state asks (0 for the mouse arriving: no tween).
"""
import shiboken6
from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPointF, QRect, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QPushButton, QToolButton

REST = QColor("#262626")             # Color(.15)
GREY = QColor("#808080")             # Color(.5): pressed, checked
WHITE = QColor("#ffffff")
BLACK = QColor("#000000")
GONE = QColor(0, 0, 0, 0)
FAINT = QColor(153, 153, 153, 26)    # Color(.6, .1): a disabled button's fill
FAINT_INK = QColor(255, 255, 255, 128)

FADE_MS = 500                        # DefaultTransition(): leaving, and everything else that changes
PRESS_MS = 300                       # a button being pressed


def out_curve():
    """cubic-bezier(0, .5, 0, 1): most of the change at once, a long soft end."""
    c = QEasingCurve(QEasingCurve.BezierSpline)
    c.addCubicBezierSegment(QPointF(0, 0.5), QPointF(0, 1), QPointF(1, 1))
    return c


def tinted(icon, size, colour, dpr=1.0, state=QIcon.Off):
    """icon at size, every opaque part of it in colour."""
    out = QPixmap(icon.pixmap(size, dpr, QIcon.Normal, state))
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(out.rect(), colour)
    p.end()
    return out


def mix(a, b, t):
    """Colour a moved t of the way to colour b (alpha too)."""
    return QColor(*(round(x + (y - x) * t) for x, y in zip(a.getRgb(), b.getRgb())))


class Fader(QObject):
    """The colours of one button, now and on their way."""

    def __init__(self, button):
        super().__init__(button)
        self.button = button
        self.flat = isinstance(button, QToolButton) or button.objectName() == "tool"       # (no fill at rest: an icon on the panel)
        self.bg, self.ink = self.want()[:2]
        self.src = self.dst = (self.bg, self.ink)
        self.anim = QVariantAnimation(self)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(out_curve())
        self.anim.valueChanged.connect(self._step)
        button.installEventFilter(self)
        button.toggled.connect(lambda _c: self.sync())       # (a button may become checkable later)

    def want(self):
        """(fill, ink, milliseconds to get there) for the button as it is now."""
        b = self.button
        if not b.isEnabled():
            return (GONE if self.flat else FAINT), FAINT_INK, FADE_MS
        if b.isDown():
            return GREY, WHITE, PRESS_MS
        if b.underMouse():
            return WHITE, BLACK, 0
        if b.isCheckable() and b.isChecked():
            return GREY, WHITE, FADE_MS
        return (GONE if self.flat else REST), WHITE, FADE_MS

    def sync(self, jump=False):
        if not shiboken6.isValid(self.button):               # (the button went before a deferred sync came)
            return
        bg, ink, ms = self.want()
        if (bg, ink) == self.dst:
            return
        self.anim.stop()
        self.src, self.dst = (self.bg, self.ink), (bg, ink)
        if jump or ms == 0 or not self.button.isVisible():
            self.bg, self.ink = bg, ink
            self.button.update()
            return
        self.anim.setDuration(ms)
        self.anim.start()

    def _step(self, v):
        t = float(v)
        self.bg, self.ink = mix(self.src[0], self.dst[0], t), mix(self.src[1], self.dst[1], t)
        self.button.update()

    def dark(self):
        """The ink is black-ish (the fill white-ish): icons are then drawn in it too."""
        return self.ink.alpha() == 255 and self.ink.lightness() < 250

    def paint(self):
        """The whole button: fill, then icon and text in the ink."""
        b = self.button
        p = QPainter(b)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(b.rect(), self.bg)
        tool = isinstance(b, QToolButton)
        text = b.text().replace("&&", "\0").replace("&", "").replace("\0", "&")
        if tool and b.toolButtonStyle() == Qt.ToolButtonIconOnly and not b.icon().isNull():
            text = ""
        has_menu = b.menu() is not None and (not tool or b.popupMode() != QToolButton.DelayedPopup)
        area = b.rect().adjusted(0, 0, -14 if has_menu else 0, 0)
        icon = b.icon()
        enabled = b.isEnabled()
        size = b.iconSize() if b.iconSize().isValid() else QSize(16, 16)
        pm = None
        if not icon.isNull():
            dpr = b.devicePixelRatioF()
            state = QIcon.On if b.isChecked() else QIcon.Off
            if not enabled:
                pm = icon.pixmap(size, dpr, QIcon.Disabled, state)
            elif self.dark():
                pm = tinted(icon, size, self.ink, dpr, state)
            else:
                pm = icon.pixmap(size, dpr, QIcon.Normal, state)
        fm = b.fontMetrics()
        gap = 4 if text and pm is not None else 0
        tw = fm.horizontalAdvance(text) if text else 0
        under = tool and b.toolButtonStyle() == Qt.ToolButtonTextUnderIcon and text and pm is not None
        if under:
            total_h = size.height() + 2 + fm.height()
            top = area.center().y() - total_h // 2
            p.drawPixmap(QRect(area.center().x() - size.width() // 2, top, size.width(), size.height()), pm)
            p.setPen(self.ink)
            p.drawText(QRect(area.left(), top + size.height() + 2, area.width(), fm.height()), Qt.AlignHCenter | Qt.AlignTop, text)
        else:
            total = (size.width() if pm is not None else 0) + gap + tw
            x = area.center().x() - total // 2 + (1 if total % 2 else 0)
            if pm is not None:
                p.drawPixmap(QRect(x, area.center().y() - size.height() // 2, size.width(), size.height()), pm)
                x += size.width() + gap
            if text:
                p.setPen(self.ink)
                p.drawText(QRect(x, area.top(), tw + 2, area.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
        if has_menu:                                  # (the chevron of a button that opens a menu)
            from . import look
            chevron = look.arrow_icon("-down")
            at = QRect(b.rect().right() - 15 + 1, b.height() // 2 - 6, 12, 12)
            if self.dark():
                p.drawPixmap(at, tinted(chevron, QSize(12, 12), self.ink, b.devicePixelRatioF()))
            else:
                chevron.paint(p, at)
        p.end()

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Paint:
            self.paint()
            return True
        if e.type() in (QEvent.Enter, QEvent.Leave, QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
                        QEvent.MouseButtonDblClick, QEvent.EnabledChange, QEvent.Show, QEvent.KeyPress, QEvent.KeyRelease):
            QTimer.singleShot(0, self.sync)          # (after the button has handled it: isDown and the rest are then true)
        return False


def of(widget):
    """The Fader of a button, or None."""
    f = widget.property("kcFader") if widget is not None else None
    return f if isinstance(f, Fader) else None


def attach(widget):
    """Give a button its Fader (once)."""
    if isinstance(widget, (QPushButton, QToolButton)) and of(widget) is None:
        widget.setProperty("kcFader", Fader(widget))
