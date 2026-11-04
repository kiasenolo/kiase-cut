"""Motion for the interface, after Kilo's CSS (styles/globals.scss: every property transitions in .5 s on cubic-bezier(0, .5, 0, 1);
kiaseStyle.scss: a button turns white at once under the mouse, fades back slowly when it leaves, goes grey in .3 s when pressed).

Qt's style sheets cannot animate (and the program-wide `QWidget { color }` rule makes Qt's style sheet style draw a button's text
itself, in that colour), so a push or tool button paints itself: its Fader takes the paint event and draws the fill, icon and
text from the two colours it keeps, the fill and the ink. The Fader watches the button (mouse in and out, press, release, checked,
enabled) and moves both colours to what the new state asks, in the time that state asks (0 for the mouse arriving: no tween).
"""
import shiboken6
from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPointF, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QLineEdit, QPlainTextEdit, QPushButton,
                               QRadioButton, QTextEdit, QToolButton, QWidget)

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


# -- input fields ---------------------------------------------------------------------------------------------------------
# Kilo's input.scss: an outline of Color(.5), Color(.7) under the mouse; typing in it, the outline goes and a white line stays
# under it, with a grey wash over the field - all moving in .3 s. The field keeps its style sheet's (invisible) 2 px border for room;
# a Frame laid over it draws the real one from the two numbers a FieldFader moves: hover and focus, each 0 to 1.

SIDE = QColor("#808080")             # Color(.5)
SIDE_HOT = QColor("#b3b3b3")         # Color(.7)
SIDE_OFF = QColor("#4d4d4d")         # (a disabled field's)
WASH = 0.3                           # Color(.5, .3) over the field while it is typed in
BORDER = 2
IN_MS = 300                          # towards hover / focus


class Frame(QWidget):
    """The outline, line and wash of a field, over it (the mouse goes through)."""

    def __init__(self, field):
        super().__init__(field)
        self.field = field
        self.hover = self.focus = 0.0
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.NoFocus)

    def paintEvent(self, e):
        r = self.rect()
        p = QPainter(self)
        side = mix(SIDE, SIDE_HOT, self.hover) if self.field.isEnabled() else SIDE_OFF
        if self.focus > 0.01:
            p.setCompositionMode(QPainter.CompositionMode_Lighten)    # (a wash that lightens the dark, leaves the text white)
            p.setOpacity(WASH * self.focus)
            p.fillRect(r, SIDE)
            p.setOpacity(1.0)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        keep = QColor(side)
        keep.setAlpha(round(side.alpha() * (1.0 - self.focus)))         # (the outline goes as the line comes)
        w, h = r.width(), r.height()
        p.fillRect(QRect(0, 0, w, BORDER), keep)
        p.fillRect(QRect(0, BORDER, BORDER, h - 2 * BORDER), keep)
        p.fillRect(QRect(w - BORDER, BORDER, BORDER, h - 2 * BORDER), keep)
        p.fillRect(QRect(0, h - BORDER, w, BORDER), mix(side, WHITE, self.focus))
        p.end()


class FieldFader(QObject):
    def __init__(self, field):
        super().__init__(field)
        self.field = field
        self.frame = Frame(field)
        self.anims = {}
        for name in ("hover", "focus"):
            a = QVariantAnimation(self)
            a.setEasingCurve(out_curve())
            a.valueChanged.connect(lambda v, n=name: self._set(n, float(v)))
            self.anims[name] = a
        field.installEventFilter(self)
        QApplication.instance().focusChanged.connect(lambda *_: self.sync())
        self._place()
        self.frame.show()
        self.frame.raise_()

    def _place(self):
        self.frame.setGeometry(self.field.rect())

    def _set(self, name, v):
        setattr(self.frame, name, v)
        self.frame.update()

    def wanted(self):
        f = self.field
        fw = QApplication.focusWidget()
        focus = fw is not None and (fw is f or f.isAncestorOf(fw))
        if isinstance(f, QComboBox) and f.view().isVisible():
            focus = True
        return f.underMouse() and f.isEnabled(), focus and f.isEnabled()

    def sync(self):
        if not shiboken6.isValid(self.field):
            return
        for name, want in zip(("hover", "focus"), self.wanted()):
            a = self.anims[name]
            target = 1.0 if want else 0.0
            if a.endValue() == target and (a.state() == QVariantAnimation.Running or getattr(self.frame, name) == target):
                continue
            a.stop()
            a.setStartValue(getattr(self.frame, name))
            a.setEndValue(target)
            a.setDuration(IN_MS if want else FADE_MS)
            if self.field.isVisible():
                a.start()
            else:
                self._set(name, target)

    def eventFilter(self, obj, e):
        t = e.type()
        if t == QEvent.Resize:
            self._place()
            self.frame.raise_()
        elif t in (QEvent.Enter, QEvent.Leave, QEvent.EnabledChange, QEvent.Show, QEvent.FocusIn, QEvent.FocusOut):
            QTimer.singleShot(0, self.sync)
            if t == QEvent.Show:
                self._place()
                self.frame.raise_()
        elif t == QEvent.ChildAdded:
            QTimer.singleShot(0, self.frame.raise_)
        return False


def attach_field(widget):
    """Give an input field its frame (once): line edits and text edits, spin boxes, combo boxes - not the line edit inside one."""
    if not isinstance(widget, (QLineEdit, QAbstractSpinBox, QComboBox, QPlainTextEdit, QTextEdit)):
        return
    if widget.property("kcField") is not None or isinstance(widget.parentWidget(), (QAbstractSpinBox, QComboBox)):
        return
    if isinstance(widget, QLineEdit) and not widget.hasFrame():
        return
    widget.setProperty("kcField", FieldFader(widget))


# -- the hop of a number being dragged ------------------------------------------------------------------------------------
# A number dragged up (bigger) hops up, dragged down (smaller) hops down: the text is kicked HOP_PX that way at once and springs
# back past where it was (OutBack) and settles. A line edit has no offset for its text, but it has margins: more room under the
# text lifts it, more above lowers it (by half the margin).

HOP_PX = 3
HOP_MS = 380


class Hop(QObject):
    """The hop of one number. `owner` is its line edit (the text moves with margins), or None with `apply(off)` given: whatever
    paints the number (a node's field) reads `off`, pixels with up positive, and is asked to repaint."""

    def __init__(self, owner=None, apply=None):
        super().__init__(owner)
        self.edit = owner
        self.apply = apply
        self.dir = 0
        self.off = 0.0                        # pixels, up is positive
        self.anim = QVariantAnimation(self)
        c = QEasingCurve(QEasingCurve.OutBack)
        c.setOvershoot(2.5)
        self.anim.setEasingCurve(c)
        self.anim.setDuration(HOP_MS)
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.valueChanged.connect(lambda v: self._set(self.dir * HOP_PX * float(v)))
        self.anim.finished.connect(lambda: self._set(0.0))

    def _set(self, off):
        self.off = off
        if self.apply is not None:
            self.apply(off)
            return
        n = round(2 * abs(off))
        self.edit.setTextMargins(0, n if off < 0 else 0, 0, n if off > 0 else 0)

    def kick(self, direction):
        """The number went up (1) or down (-1)."""
        if not direction or (self.edit is not None and not self.edit.isVisible()):
            return
        running = self.anim.state() == QVariantAnimation.Running
        if running and direction == self.dir and self.anim.currentTime() < HOP_MS * 0.3:
            return                            # (a hop that has only just begun goes on: a fast drag is not a shiver)
        self.anim.stop()
        self.dir = 1 if direction > 0 else -1
        self._set(self.dir * HOP_PX)
        self.anim.start()


# -- check boxes and radio buttons ----------------------------------------------------------------------------------------
# A flat 2 px square (a ring for a radio button) in Color(.5), Color(.7) under the mouse; checked, it turns white with a black tick
# drawn into it (a dot grown in the ring), in .3 s. look.Style draws the indicator (PE_IndicatorCheckBox / RadioButton) from the
# Toggle of the button: `on` and `hover`, each 0 to 1, moved by it.

BOX = 16                             # the indicator's size
ON_MS = 300


class Toggle(QObject):
    def __init__(self, button):
        super().__init__(button)
        self.button = button
        self.on = 1.0 if button.isChecked() else 0.0
        self.hover = 0.0
        self.anims = {}
        for name in ("on", "hover"):
            a = QVariantAnimation(self)
            a.setEasingCurve(out_curve())
            a.valueChanged.connect(lambda v, n=name: self._set(n, float(v)))
            self.anims[name] = a
        button.installEventFilter(self)
        button.toggled.connect(lambda *_: self.sync())
        if hasattr(button, "stateChanged"):
            button.stateChanged.connect(lambda *_: self.sync())

    def _set(self, name, v):
        setattr(self, name, v)
        self.button.update()

    def want(self):
        b = self.button
        checked = b.isChecked() or (hasattr(b, "checkState") and b.checkState() == Qt.PartiallyChecked)
        return (1.0 if checked else 0.0), (1.0 if b.underMouse() and b.isEnabled() else 0.0)

    def sync(self):
        if not shiboken6.isValid(self.button):
            return
        for name, target in zip(("on", "hover"), self.want()):
            a = self.anims[name]
            if a.state() == QVariantAnimation.Running and a.endValue() == target:
                continue
            a.stop()
            if getattr(self, name) == target:
                continue
            if not self.button.isVisible():
                self._set(name, target)
                continue
            a.setStartValue(getattr(self, name))
            a.setEndValue(target)
            a.setDuration(ON_MS if (name == "hover" and target) or (name == "on" and target) else FADE_MS)
            a.start()

    def eventFilter(self, obj, e):
        if e.type() in (QEvent.Enter, QEvent.Leave, QEvent.EnabledChange, QEvent.Show):
            QTimer.singleShot(0, self.sync)
        return False


def attach_toggle(widget):
    if isinstance(widget, (QCheckBox, QRadioButton)) and widget.property("kcToggle") is None:
        widget.setProperty("kcToggle", Toggle(widget))


def paint_indicator(painter, option, widget, radio):
    """The indicator of a check box or radio button, from its Toggle (or, for one without, from its state)."""
    from PySide6.QtWidgets import QStyle
    st = option.state
    t = widget.property("kcToggle") if widget is not None else None
    if t is not None:
        on, hover = t.on, t.hover
    else:
        on = 1.0 if st & (QStyle.State_On | QStyle.State_NoChange) else 0.0
        hover = 1.0 if st & QStyle.State_MouseOver else 0.0
    down = bool(st & QStyle.State_Sunken)
    enabled = bool(st & QStyle.State_Enabled)
    partial = bool(st & QStyle.State_NoChange)
    r = QRect(0, 0, min(BOX, option.rect.width(), option.rect.height()), min(BOX, option.rect.width(), option.rect.height()))
    r.moveCenter(option.rect.center())
    side = mix(SIDE, SIDE_HOT, hover)
    ring = mix(side, WHITE, on)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, radio)
    painter.setPen(Qt.NoPen)
    if not enabled:
        painter.setOpacity(0.4)
    if radio:
        outer = QRectF(r)
        painter.setBrush(ring)
        painter.drawEllipse(outer)
        painter.setBrush(QColor("#111111"))                           # (the ring: the middle shows the panel again)
        painter.drawEllipse(outer.adjusted(BORDER, BORDER, -BORDER, -BORDER))
        k = (r.width() / 2 - BORDER - 2) * on
        if down:
            painter.setBrush(GREY)
            k = max(k, 3.0)
        else:
            painter.setBrush(WHITE)
        if k > 0.2:
            painter.drawEllipse(QPointF(outer.center()), k, k)
    else:
        fill = mix(QColor(0, 0, 0, 0), WHITE, on) if not down else GREY
        painter.fillRect(r, ring if not down else GREY)
        inner = r.adjusted(BORDER, BORDER, -BORDER, -BORDER)
        painter.fillRect(inner, QColor("#0a0a0a"))
        painter.fillRect(inner, fill)
        if on > 0.01:                                         # (the tick or dash, black on the white)
            painter.setRenderHint(QPainter.Antialiasing)
            ink = WHITE if down else BLACK
            p = QPen(ink, 2.0)
            p.setCapStyle(Qt.SquareCap)
            p.setJoinStyle(Qt.MiterJoin)
            painter.setPen(p)
            x, y, s = r.x(), r.y(), r.width() / 16.0
            if partial:
                painter.drawLine(QPointF(x + 4 * s, y + 8 * s), QPointF(x + (4 + 8 * on) * s, y + 8 * s))
            else:
                a, b, c = QPointF(x + 4 * s, y + 8.5 * s), QPointF(x + 7 * s, y + 11.5 * s), QPointF(x + 12 * s, y + 5 * s)
                first = min(1.0, on / 0.4)
                painter.drawLine(a, a + (b - a) * first)
                if on > 0.4:
                    painter.drawLine(b, b + (c - b) * min(1.0, (on - 0.4) / 0.6))
    painter.restore()
