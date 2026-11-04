"""Motion for the interface, after Kilo's CSS (styles/globals.scss: every property transitions in .5 s on cubic-bezier(0, .5, 0, 1);
kiaseStyle.scss: a button turns white at once under the mouse, fades back slowly when it leaves, goes grey in .3 s when pressed).

Qt's style sheets cannot animate (and the program-wide `QWidget { color }` rule makes Qt's style sheet style draw a button's text
itself, in that colour), so a push or tool button paints itself: its Fader takes the paint event and draws the fill, icon and
text from the two colours it keeps, the fill and the ink. The Fader watches the button (mouse in and out, press, release, checked,
enabled) and moves both colours to what the new state asks, in the time that state asks (0 for the mouse arriving: no tween).
"""
import re

import shiboken6
from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPointF, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QLineEdit, QPlainTextEdit, QPushButton,
                               QMenuBar, QRadioButton, QScrollBar, QStyle, QStyleOptionSlider, QTabBar, QTextEdit, QToolButton,
                               QWidget)

REST = QColor("#262626")             # Color(.15)
GREY = QColor("#808080")             # Color(.5): pressed
ACTIVE = QColor("#666666")           # Color(.4): checked (a little darker than a press, so a button that is on is not as loud)
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
        self._sheet, self._swatch = "", None
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
            return ACTIVE, WHITE, FADE_MS
        return (GONE if self.flat else REST), WHITE, FADE_MS

    def swatch(self):
        """(fill, ink) a button asks for in its own style sheet ("background: #rrggbb; color: #000" - the colour buttons), or None."""
        sheet = self.button.styleSheet()
        if not sheet:
            return None
        if sheet != self._sheet:
            self._sheet = sheet
            fill = _sheet_colour(sheet, r"background(?:-color)?")
            self._swatch = None if fill is None else (fill, _sheet_colour(sheet, r"color"))
        return self._swatch

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
        if self.want()[:2] != self.dst and self.anim.state() != QVariantAnimation.Running:
            QTimer.singleShot(0, self.sync)                  # (a state changed without a signal, a blocked toggled: catch up)
        p = QPainter(b)
        p.setRenderHint(QPainter.Antialiasing)
        swatch = self.swatch()
        ink = self.ink
        if swatch is not None:                               # a colour button: its colour, in a frame that lights as a button does
            fill, own = swatch
            p.fillRect(b.rect(), fill)
            ink = own if own is not None else (BLACK if fill.lightness() > 140 else WHITE)
            if self.bg.alpha():
                frame = QPen(self.bg, 2)
                frame.setJoinStyle(Qt.MiterJoin)
                p.setPen(frame)
                p.setBrush(Qt.NoBrush)
                p.setRenderHint(QPainter.Antialiasing, False)
                p.drawRect(b.rect().adjusted(1, 1, -1, -1))
                p.setRenderHint(QPainter.Antialiasing)
        else:
            p.fillRect(b.rect(), self.bg)
        tool = isinstance(b, QToolButton)
        text = b.text().replace("&&", "\0").replace("&", "").replace("\0", "&")
        if tool and b.toolButtonStyle() == Qt.ToolButtonIconOnly and (not b.icon().isNull() or b.arrowType() != Qt.NoArrow):
            text = ""
        has_menu = b.menu() is not None and (not tool or b.popupMode() != QToolButton.DelayedPopup)
        area = b.rect().adjusted(0, 0, -14 if has_menu else 0, 0)
        icon = b.icon()
        if tool and icon.isNull() and b.arrowType() != Qt.NoArrow:        # (setArrowType: no icon of its own, the style's chevron)
            from . import look
            icon = look.arrow_icon({Qt.UpArrow: "-up", Qt.DownArrow: "-down", Qt.LeftArrow: "-left", Qt.RightArrow: "-right"}[b.arrowType()])
        enabled = b.isEnabled()
        size = b.iconSize() if b.iconSize().isValid() else QSize(16, 16)
        pm = None
        if not icon.isNull():
            dpr = b.devicePixelRatioF()
            state = QIcon.On if b.isChecked() else QIcon.Off
            if not enabled:
                pm = icon.pixmap(size, dpr, QIcon.Disabled, state)
            elif (ink.alpha() == 255 and ink.lightness() < 250):
                pm = tinted(icon, size, ink, dpr, state)
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
            p.setPen(ink)
            p.drawText(QRect(area.left(), top + size.height() + 2, area.width(), fm.height()), Qt.AlignHCenter | Qt.AlignTop, text)
        else:
            total = (size.width() if pm is not None else 0) + gap + tw
            x = area.center().x() - total // 2 + (1 if total % 2 else 0)
            if pm is not None:
                p.drawPixmap(QRect(x, area.center().y() - size.height() // 2, size.width(), size.height()), pm)
                x += size.width() + gap
            if text:
                p.setPen(ink)
                p.drawText(QRect(x, area.top(), tw + 2, area.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
        if has_menu:                                  # (the chevron of a button that opens a menu)
            from . import look
            chevron = look.arrow_icon("-down")
            at = QRect(b.rect().right() - 15 + 1, b.height() // 2 - 6, 12, 12)
            if (ink.alpha() == 255 and ink.lightness() < 250):
                p.drawPixmap(at, tinted(chevron, QSize(12, 12), ink, b.devicePixelRatioF()))
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


def _sheet_colour(sheet, prop):
    """The colour a style sheet gives for prop ("background", "color"), or None."""
    m = re.search(r"(?<![-\w])" + prop + r"\s*:\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\)|[a-zA-Z]+)", sheet)
    if m is None:
        return None
    text = m.group(1)
    if text.startswith("rgb"):
        nums = [float(x) for x in re.findall(r"[\d.]+", text)]
        return QColor(*(int(x) for x in nums[:3])) if len(nums) >= 3 else None
    c = QColor(text)
    return c if c.isValid() else None


def of(widget):
    """The Fader of a button, or None."""
    f = widget.property("kcFader") if widget is not None else None
    return f if isinstance(f, Fader) else None


def attach(widget):
    """Give a button its Fader (once)."""
    if isinstance(widget, (QPushButton, QToolButton)) and of(widget) is None and not widget.property("kcMaking"):
        widget.setProperty("kcMaking", True)                 # (making one polishes the widget again: not a second)
        widget.setProperty("kcFader", Fader(widget))


# -- input fields ---------------------------------------------------------------------------------------------------------
# Kilo's input.scss: an outline of Color(.5), Color(.7) under the mouse; typing in it, the outline goes and a white line stays
# under it, with a grey wash over the field - all moving in .3 s. The field keeps its style sheet's (invisible) 2 px border for room;
# a Frame laid over it draws the real one from the two numbers a FieldFader moves: hover and focus, each 0 to 1.

SIDE = QColor("#4d4d4d")             # Color(.3): the outline of a field at rest
SIDE_HOT = QColor("#808080")         # Color(.5): under the mouse
SIDE_OFF = QColor("#2e2e2e")         # (a disabled field's)
WASH_COLOUR = QColor("#808080")      # Color(.5)
WASH = 0.3                           # Color(.5, .3) over the field while it is typed in
LINE = 1                             # the outline of a field
UNDER = 2                            # the line under the one being typed in
BORDER = 2                           # (a check box's)
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
            p.fillRect(r, WASH_COLOUR)
            p.setOpacity(1.0)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        keep = QColor(side)
        keep.setAlpha(round(side.alpha() * (1.0 - self.focus)))         # (the outline goes as the line comes)
        w, h = r.width(), r.height()
        p.fillRect(QRect(0, 0, w, LINE), keep)
        p.fillRect(QRect(0, LINE, LINE, h - 2 * LINE), keep)
        p.fillRect(QRect(w - LINE, LINE, LINE, h - 2 * LINE), keep)
        p.fillRect(QRect(0, h - LINE, w, LINE), keep)
        if self.focus > 0.01:
            line = QColor(WHITE)
            line.setAlpha(round(255 * self.focus))
            p.fillRect(QRect(0, h - UNDER, w, UNDER), line)
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
        field, frame = getattr(self, "field", None), getattr(self, "frame", None)      # (not made yet, or going)
        if field is None or frame is None or not (shiboken6.isValid(field) and shiboken6.isValid(frame)):
            return False
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
            QTimer.singleShot(0, self._raise)
        return False

    def _raise(self):
        if shiboken6.isValid(self.frame):
            self.frame.raise_()


def attach_field(widget):
    """Give an input field its frame (once): line edits and text edits, spin boxes, combo boxes - not the line edit inside one."""
    if not isinstance(widget, (QLineEdit, QAbstractSpinBox, QComboBox, QPlainTextEdit, QTextEdit)):
        return
    if widget.property("kcField") is not None or widget.property("kcMaking") or isinstance(widget.parentWidget(), (QAbstractSpinBox, QComboBox)):
        return
    if isinstance(widget, QLineEdit) and not widget.hasFrame():
        return
    widget.setProperty("kcMaking", True)
    widget.setProperty("kcField", FieldFader(widget))


# -- the hop of a number being dragged ------------------------------------------------------------------------------------
# A number dragged up (bigger) hops up, dragged down (smaller) hops down: the text is put HOP_PX that way at once and goes back to
# where it is (Kilo's `@keyframes 0% translate(+-offset) 100% translate(0)`, on the usual cubic-bezier(0, .5, 0, 1), no overshoot). A line edit has no offset for its text, but it has margins: more room under the
# text lifts it, more above lowers it (by half the margin).

HOP_PX = 3
HOP_MS = 500


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
        self.anim.setEasingCurve(out_curve())
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
LIST_PAD = 6                         # how far the text of a combo box's list is moved in (a menu's is its icon column)
ON_MS = 300


class Toggle(QObject):
    def __init__(self, button):
        super().__init__(button)
        self.button = button
        self.on = 1.0 if button.isChecked() else 0.0
        self.hover = 0.0
        self.goal = self.want()
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
        self.goal = self.want()
        for name, target in zip(("on", "hover"), self.goal):
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
    if isinstance(widget, (QCheckBox, QRadioButton)) and widget.property("kcToggle") is None and not widget.property("kcMaking"):
        widget.setProperty("kcMaking", True)
        widget.setProperty("kcToggle", Toggle(widget))


def paint_indicator(painter, option, widget, radio):
    """The indicator of a check box or radio button, from its Toggle (or, for one without, from its state)."""
    from PySide6.QtWidgets import QStyle
    st = option.state
    t = widget.property("kcToggle") if widget is not None else None
    if t is not None:
        if t.want() != t.goal:
            QTimer.singleShot(0, t.sync)                      # (it was ticked without a signal: catch up)
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


# -- tabs -----------------------------------------------------------------------------------------------------------------
# Grey text that goes white under the mouse, a faint white wash, and for the open tab its own ground and a white 2 px line that
# grows from the middle - all moved in .3 s (back in .5 s). The TabFader of a tab bar keeps two numbers for every tab, hover and
# selected; look.Style draws the tabs from them (the style sheet cannot move anything).

TAB_TEXT = QColor("#808080")
TAB_GROUND = {"": (QColor("#0b0b0b"), QColor("#161616")), "layouts": (None, None), "timelines": (QColor("#0b0b0b"), QColor("#1f1f1f"))}
TAB_WASH = 13                        # alpha of the white wash under the mouse
TAB_LINE = 2


class TabFader(QObject):
    def __init__(self, bar):
        super().__init__(bar)
        self.bar = bar
        self.v = {}                  # tab -> [hover, selected]
        self.anims = {}
        self.count = bar.count()
        bar.setMouseTracking(True)
        bar.installEventFilter(self)
        bar.currentChanged.connect(lambda *_: self.sync())

    def reset(self):
        for a in self.anims.values():
            a.stop()
        self.anims, self.v, self.count = {}, {}, self.bar.count()

    def get(self, i):
        """[hover, selected] of tab i, each 0 to 1."""
        if self.bar.count() != self.count:                # (tabs came or went: the numbers start again, still)
            self.reset()
        return self.v.setdefault(i, [0.0, 1.0 if i == self.bar.currentIndex() else 0.0])

    def _go(self, i, k, target):
        cur = self.get(i)
        a = self.anims.get((i, k))
        if a is not None and a.state() == QVariantAnimation.Running and a.endValue() == target:
            return
        if a is not None:
            a.stop()
        if cur[k] == target:
            return
        if not self.bar.isVisible():
            cur[k] = target
            return
        if a is None:
            a = self.anims[(i, k)] = QVariantAnimation(self)
            a.setEasingCurve(out_curve())
            a.valueChanged.connect(lambda v, i=i, k=k: self._set(i, k, float(v)))
        a.setStartValue(cur[k])
        a.setEndValue(target)
        a.setDuration(ON_MS if target else FADE_MS)
        a.start()

    def _set(self, i, k, v):
        if i in self.v:
            self.v[i][k] = v
        self.bar.update()

    def sync(self):
        if not shiboken6.isValid(self.bar):
            return
        over = -1
        if self.bar.underMouse():
            over = self.bar.tabAt(self.bar.mapFromGlobal(QCursor.pos()))
        for i in range(self.bar.count()):
            self._go(i, 0, 1.0 if i == over and self.bar.isTabEnabled(i) else 0.0)
            self._go(i, 1, 1.0 if i == self.bar.currentIndex() else 0.0)

    def eventFilter(self, obj, e):
        if e.type() in (QEvent.MouseMove, QEvent.Enter, QEvent.Leave, QEvent.Show, QEvent.EnabledChange):
            QTimer.singleShot(0, self.sync)
        return False


def attach_tabs(widget):
    if isinstance(widget, QTabBar) and widget.property("kcTabs") is None and not widget.property("kcMaking"):
        widget.setProperty("kcMaking", True)
        widget.setProperty("kcTabs", TabFader(widget))


def tab_ink(hover, sel):
    return mix(TAB_TEXT, WHITE, max(hover, sel))


def paint_tab(painter, option, widget):
    """The ground, wash and line of one tab (its text: tab_ink, drawn by the base style)."""
    f = widget.property("kcTabs") if widget is not None else None
    i = widget.tabAt(option.rect.center()) if f is not None else -1
    hover, sel = f.get(i) if f is not None and i >= 0 else (0.0, 1.0 if option.state & QStyle.State_Selected else 0.0)
    rest, chosen = TAB_GROUND.get(widget.objectName() if widget is not None else "", TAB_GROUND[""])
    r = option.rect
    if rest is not None:
        painter.fillRect(r, mix(rest, chosen, sel))
    if hover > 0.01 and sel < 0.99:
        wash = QColor(255, 255, 255, round(TAB_WASH * hover * (1.0 - sel)))
        painter.fillRect(r, wash)
    if sel > 0.01:
        w = round(r.width() * sel)
        painter.fillRect(QRect(r.center().x() - w // 2, r.bottom() - TAB_LINE + 1, w, TAB_LINE), WHITE)


# -- scroll bars ----------------------------------------------------------------------------------------------------------
# Kilo's: a 15 px track that shows nothing, in it a flat thumb 5 px thick (BasColor(.7), white under the mouse, BasColor(.3) held).
# The style sheet lays the bar out (its handle is see-through); a Thumb laid over the bar draws the real one in a colour that
# follows what the bar is doing, as the other fades do.

BAR_THUMB = 5
BAR_REST = QColor("#b3b3b3")
BAR_HOT = WHITE
BAR_HELD = QColor("#4d4d4d")


class Thumb(QWidget):
    """The thumb of a scroll bar, drawn over it (the mouse goes through) and moved by the bar's own events."""

    def __init__(self, bar):
        super().__init__(bar)
        self.bar = bar
        self.colour = BAR_REST
        self.goal = BAR_REST
        self.start = BAR_REST
        self.held = False
        self.over = False
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.anim = QVariantAnimation(self)
        self.anim.setEasingCurve(out_curve())
        self.anim.valueChanged.connect(self._step)
        bar.installEventFilter(self)
        bar.setMouseTracking(True)
        bar.valueChanged.connect(lambda *_: self._refresh())
        bar.rangeChanged.connect(lambda *_: self._refresh())
        self.setGeometry(bar.rect())
        self.show()
        self.raise_()

    def _refresh(self, *_):
        if shiboken6.isValid(self):
            self.update()

    def rect_of_thumb(self):
        """Where the bar's handle is (the style sheet's layout), drawn BAR_THUMB thick in the middle of the bar."""
        bar = self.bar
        o = QStyleOptionSlider()
        o.initFrom(bar)
        o.orientation = bar.orientation()
        o.minimum, o.maximum, o.pageStep, o.singleStep = bar.minimum(), bar.maximum(), bar.pageStep(), bar.singleStep()
        o.sliderPosition, o.sliderValue = bar.sliderPosition(), bar.value()
        o.upsideDown = bar.invertedAppearance()
        o.subControls = QStyle.SC_All
        return bar.style().subControlRect(QStyle.CC_ScrollBar, o, QStyle.SC_ScrollBarSlider, bar)

    def paintEvent(self, e):
        if self.bar.maximum() <= self.bar.minimum():
            return
        r = self.rect_of_thumb()
        if r.isEmpty():
            return
        if self.bar.orientation() == Qt.Horizontal:
            r = QRect(r.x(), (self.height() - BAR_THUMB) // 2, r.width(), BAR_THUMB)
        else:
            r = QRect((self.width() - BAR_THUMB) // 2, r.y(), BAR_THUMB, r.height())
        p = QPainter(self)
        p.fillRect(r, self.colour)
        p.end()

    def _step(self, v):
        self.colour = mix(self.start, self.goal, float(v))
        self.update()

    def go(self, goal, ms):
        if goal == self.goal:
            return
        self.anim.stop()
        self.start, self.goal = self.colour, goal
        if ms and self.bar.isVisible():
            self.anim.setDuration(ms)
            self.anim.setStartValue(0.0)
            self.anim.setEndValue(1.0)
            self.anim.start()
        else:
            self.colour = goal
            self.update()

    def sync(self):
        if self.held:
            self.go(BAR_HELD, PRESS_MS)
        elif self.over:
            self.go(BAR_HOT, 0)
        else:
            self.go(BAR_REST, FADE_MS)

    def eventFilter(self, obj, e):
        bar = getattr(self, "bar", None)                                      # (not yet made, or its bar is being deleted: events still come)
        if bar is None or not (shiboken6.isValid(self) and shiboken6.isValid(bar)):
            return False
        t = e.type()
        if t == QEvent.Resize:
            self.setGeometry(self.bar.rect())
            self.raise_()
        elif t in (QEvent.MouseMove, QEvent.HoverMove, QEvent.Enter):
            pos = e.position().toPoint() if hasattr(e, "position") else self.bar.mapFromGlobal(QCursor.pos())
            was, self.over = self.over, self.rect_of_thumb().contains(pos) and self.bar.maximum() > self.bar.minimum()
            if self.over != was:
                self.sync()
        elif t == QEvent.Leave:
            if self.over or self.held:
                self.over = False
                self.sync()
        elif t == QEvent.MouseButtonPress and e.button() == Qt.LeftButton:
            if self.rect_of_thumb().contains(e.position().toPoint()):
                self.held = True
                self.sync()
        elif t == QEvent.MouseButtonRelease and self.held:
            self.held = False
            self.over = self.rect_of_thumb().contains(e.position().toPoint())
            self.sync()
        elif t == QEvent.ChildAdded or t == QEvent.Show:
            QTimer.singleShot(0, self.raise_)
        return False


def attach_bar(widget):
    if isinstance(widget, QScrollBar) and widget.property("kcThumb") is None and not widget.property("kcMaking"):
        widget.setProperty("kcMaking", True)
        widget.setProperty("kcThumb", Thumb(widget))


# -- menu bar -------------------------------------------------------------------------------------------------------------
# After Kilo's window menu (data/components/Window): the title under the mouse or with its menu open is a white tab, slanted
# 30 degrees ("/" on both sides: the foot is further left than the top), with black text; the first one's left side is flat, it
# is the window's edge. White at once when it is chosen, back to nothing in .5 s when it is not, as a button.

SLANT = 0.5773502691896257           # tan 30 degrees
MENU_VPAD = 8                        # a title is the height of its text and this
MENU_GAP = 10                        # room between a title's text and the slanted edge (at the middle of the tab's height)


def menu_slant(widget):
    """How far a title's slanted sides lean over the height of the bar's items, in pixels."""
    text = widget.fontMetrics().height() if widget is not None else 16
    return round((text + MENU_VPAD) * SLANT)


def menu_pad(widget):
    """Room added left and right of a title's text: half a lean (a tab's sides slant over its height) and the gap."""
    return menu_slant(widget) // 2 + MENU_GAP


class MenuBarFader(QObject):
    def __init__(self, bar):
        super().__init__(bar)
        self.bar = bar
        self.v = {}                  # title -> how white it is, 0 to 1
        self.anims = {}
        self.strip = Strip(bar, self)

    def go(self, key, target):
        cur = self.v.setdefault(key, 0.0)
        a = self.anims.get(key)
        if a is not None and a.state() == QVariantAnimation.Running and a.endValue() == target:
            return cur
        if cur == target and (a is None or a.state() != QVariantAnimation.Running):
            return cur
        if a is None:
            a = self.anims[key] = QVariantAnimation(self)
            a.setEasingCurve(out_curve())
            a.valueChanged.connect(lambda v, k=key: self._set(k, float(v)))
        a.stop()
        if target >= cur or not self.bar.isVisible():            # (white at once; the way back takes its time)
            self.v[key] = target
            return target
        a.setStartValue(cur)
        a.setEndValue(target)
        a.setDuration(FADE_MS)
        a.start()
        return cur

    def _set(self, key, v):
        self.v[key] = v
        self.bar.update()
        self.strip.update()


class Strip(QWidget):
    """The titles of a menu bar, drawn over it: a tab's slanted sides reach into the next title's room, which the style cannot
    draw into (each title is clipped to its own box) and so cannot make tabs that meet with no space between."""

    def __init__(self, bar, fader):
        super().__init__(bar)
        self.bar, self.fader = bar, fader
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        bar.installEventFilter(self)
        self.setGeometry(bar.rect())
        self.show()
        self.raise_()
        self.timer = QTimer(self)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self._stale)
        self.timer.start()

    def _stale(self):
        """Qt leaves a title lit when the mouse left the bar without its Leave event (or the menu was closed with the mouse
        elsewhere): nothing is chosen then, and nothing should stay white."""
        bar = getattr(self, "bar", None)
        if bar is None or not (shiboken6.isValid(self) and shiboken6.isValid(bar)) or not bar.isVisible():
            return
        a = bar.activeAction()
        if a is None:                                          # (Alt navigation is off: no title is lit by the keyboard without its menu open)
            return
        menu = a.menu()
        if menu is not None and menu.isVisible():
            return
        lean = menu_slant(bar)
        over = bar.actionGeometry(a).adjusted(-lean, 0, lean, 0).contains(bar.mapFromGlobal(QCursor.pos()))
        if not over:
            bar.setActiveAction(None)

    def eventFilter(self, obj, e):
        bar = getattr(self, "bar", None)
        if bar is None or not (shiboken6.isValid(self) and shiboken6.isValid(bar)):
            return False
        if e.type() == QEvent.Resize:
            self.setGeometry(bar.rect())
            self.raise_()
        elif e.type() in (QEvent.ActionChanged, QEvent.ActionAdded, QEvent.ActionRemoved, QEvent.Show):
            QTimer.singleShot(0, self._refresh)
        return False

    def _refresh(self):
        if shiboken6.isValid(self):
            self.raise_()
            self.update()

    def paintEvent(self, e):
        from PySide6.QtGui import QPolygonF
        bar = self.bar
        actions = [a for a in bar.actions() if a.isVisible() and not a.isSeparator()]
        if not actions:
            return
        s = menu_slant(bar)
        active = bar.activeAction()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for n, a in enumerate(actions):
            r = QRectF(bar.actionGeometry(a))
            enabled = a.isEnabled()
            white = self.fader.go(a.text(), 1.0 if enabled and a is active else 0.0)
            first = n == 0
            if white > 0.005:                                                # (the foot of a tab is the left of its box, where the menu that opens under it
                foot = r.left()                                              #  starts; the top leans a whole lean to the right of it. The first is flat on its
                top = r.left() if first else r.left() + s                    #  left, it is the window's edge.)
                lap = 0.75                                                   # (a little over the joint: two edges of one line leave a faint seam)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, round(255 * white)))
                p.drawPolygon(QPolygonF([QPointF(top, r.top()), QPointF(r.right() + s + lap, r.top()),
                                         QPointF(r.right() + lap, r.bottom()), QPointF(foot, r.bottom())]))
            base = bar.palette().color(QPalette.Active if enabled else QPalette.Disabled, QPalette.WindowText)
            p.setPen(BLACK if enabled and white > 0.5 else base)                 # (not mixed: half way the text would be the colour of the ground)
            p.setFont(bar.font())
            p.drawText(r.translated(s / 4.0 if first else s / 2.0, 0), Qt.AlignCenter | Qt.TextHideMnemonic, a.text())   # (centred in the tab)
        p.end()


def attach_menubar(widget):
    if isinstance(widget, QMenuBar) and widget.property("kcMenuBar") is None and not widget.property("kcMaking"):
        widget.setProperty("kcMaking", True)
        widget.setProperty("kcMenuBar", MenuBarFader(widget))
