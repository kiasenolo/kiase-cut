"""KiaseCut's own status bar along the top of the window (Android): the time and date in the middle of a black bar, a thin
white line under it. Drawn after the design (the Lunacy sketch: 7 of 172 high, the line 0.5, the text 3).

Three parts: on the left the window-wide buttons (undo, redo, save), the time exactly in the middle of the bar (it is
drawn from the bar's width, so what the sides hold never moves it), the right is empty for now.

The window is fullscreen, so Android's own bars are hidden; a swipe from an edge brings them back over this bar for a few
seconds, and then this one is hidden (androidbars.system_bars_shown is asked a few times a second), to be shown again
when theirs go. The bar floats over the top of the window, which keeps a margin of the same height so nothing sits under it.
"""
import sys
from datetime import datetime

from PySide6.QtCore import QEasingCurve, QEvent, QPointF, QRect, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QRegion
from PySide6.QtWidgets import QToolButton, QWidget

from .. import androidbars
from . import icons

BAR_OF_WINDOW = 7 / 172            # the bar's height of the window's
LINE_OF_BAR = 0.5 / 7 / 2          # the line's of the bar's: half of the sketch's, the line is to be thinner
TEXT_OF_BAR = 3 / 7 * 4 / 5         # the text's height of the bar's: the sketch's 3 of 7, four fifths of it
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
POLL_MS = 150
# the bar goes away like the CSS clip-path from polygon(0 0, 100% 0, 100% 100%, 0 100%) to polygon(0 100%, 100% 100%, 100% 100%, 0 100%)
# (its top edge sinks to its bottom), and comes back the same way in reverse; the curves are cubic-bezier(x1, y1, x2, y2)
HIDE_MS, HIDE_CURVE = 500, (.12, .57, .61, .86)
BACK_MS, BACK_CURVE = 300, (0, .67, .14, .98)
ICON_OF_BAR = 0.62                 # a button's icon of the bar's height
LEFT_BUTTONS = (("undo", "復原（Ctrl+Z）", "do_undo"), ("redo", "重做（Ctrl+Y）", "do_redo"), ("save", "儲存專案（Ctrl+S）", "save_project"))
BUTTON_STYLE = "QToolButton{background:transparent;border:0}QToolButton:pressed{background:#3a3a3a}"


def stamp(now):
    """'10:24 / 2045 April 06' (months in English, whatever the language of the system)."""
    return f"{now:%H:%M} / {now.year} {MONTHS[now.month - 1]} {now.day:02d}"


class AndroidBar(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window_ = window
        self.setAutoFillBackground(False)
        self.buttons = {}
        for key, tip, method in LEFT_BUTTONS:
            b = QToolButton(self)
            b.setStyleSheet(BUTTON_STYLE)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, m=method: getattr(window, m)())      # (not save_project(True): the click's argument is dropped)
            self.buttons[key] = b
        self.text = ""
        self.gone = 0.0                  # 0: the whole bar shows, 1: clipped away
        self.wanted = True
        self.anim = QVariantAnimation(self, valueChanged=self.clip)
        self.bar_h = 0
        self.line_h = 1
        window.installEventFilter(self)
        self.clock = QTimer(self, interval=1000, timeout=self.tick)
        self.clock.start()
        self.watch = QTimer(self, interval=POLL_MS, timeout=self.follow_system_bars)
        if sys.platform == "android":
            self.watch.start()
        self.fit()
        self.tick()

    def eventFilter(self, obj, event):
        if obj is self.window_ and event.type() == QEvent.Resize:
            self.fit()
        return False

    def fit(self):
        h = max(1, round(self.window_.height() * BAR_OF_WINDOW))
        self.line_h = max(1, round(h * LINE_OF_BAR))
        if h != self.bar_h:
            self.bar_h = h
            self.window_.setContentsMargins(0, h, 0, 0)
        self.setGeometry(0, 0, self.window_.width(), h)
        for i, (key, b) in enumerate(self.buttons.items()):
            b.setIcon(icons.icon(key))
            b.setIconSize(QSize(round(h * ICON_OF_BAR), round(h * ICON_OF_BAR)))
            b.setGeometry(i * h, 0, h, h - self.line_h)
        self.raise_()
        self.clip(self.gone)
        self.update()

    def tick(self):
        text = stamp(datetime.now())
        if text != self.text:
            self.text = text
            self.update()

    def refresh(self):
        """The buttons' enabled state, from the window's (its undo history, a project open)."""
        w = self.window_
        h = getattr(w, "history", None)
        self.buttons["undo"].setEnabled(bool(h and h.undo_stack))
        self.buttons["redo"].setEnabled(bool(h and h.redo_stack))
        self.buttons["save"].setEnabled(getattr(w, "proj", None) is not None)

    def follow_system_bars(self):
        self.show_bar(not androidbars.system_bars_shown())

    def show_bar(self, on):
        """The bar away (on False) or back, animated from where it is."""
        if on == self.wanted:
            return
        self.wanted = on
        ms, (x1, y1, x2, y2) = (BACK_MS, BACK_CURVE) if on else (HIDE_MS, HIDE_CURVE)
        curve = QEasingCurve(QEasingCurve.BezierSpline)
        curve.addCubicBezierSegment(QPointF(x1, y1), QPointF(x2, y2), QPointF(1, 1))
        start, end = self.gone, 0.0 if on else 1.0              # (read first: setting the animation's values moves the bar)
        self.anim.stop()
        self.anim.setEasingCurve(curve)
        self.anim.setStartValue(start)
        self.anim.setEndValue(end)
        self.anim.setDuration(max(1, round(ms * abs(end - start))))      # (from half way: the rest of the time)
        self.anim.start()

    def clip(self, gone):
        """Only the part of the bar under its sinking top edge shows (the buttons too: a mask)."""
        self.gone = float(gone)
        y = round(self.gone * self.height())
        if self.gone >= 1 or y >= self.height():
            self.hide()
            return
        self.setMask(QRegion(0, y, self.width(), self.height() - y))
        self.show()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("black"))
        p.fillRect(QRect(0, self.height() - self.line_h, self.width(), self.line_h), QColor("white"))
        font = QFont(self.font())
        font.setPixelSize(max(6, round(self.bar_h * TEXT_OF_BAR)))
        p.setFont(font)
        p.setPen(QColor("white"))
        p.drawText(QRect(0, 0, self.width(), self.height() - self.line_h), Qt.AlignCenter, self.text)


def install(window):
    """The bar over the top of `window` (kept by it)."""
    window.android_bar = AndroidBar(window)
    window.android_bar.refresh()
    return window.android_bar
