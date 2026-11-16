"""KiaseCut's own status bar along the top of the window (Android): the time and date in the middle of a black bar, a thin
white line under it. Drawn after the design (the Lunacy sketch: 7 of 172 high, the line 0.5, the text 3).

The window is fullscreen, so Android's own bars are hidden; a swipe from an edge brings them back over this bar for a few
seconds, and then this one is hidden (androidbars.system_bars_shown is asked a few times a second), to be shown again
when theirs go. The bar floats over the top of the window, which keeps a margin of the same height so nothing sits under it.
"""
import sys
from datetime import datetime

from PySide6.QtCore import QEvent, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QWidget

from .. import androidbars

BAR_OF_WINDOW = 7 / 172            # the bar's height of the window's
LINE_OF_BAR = 0.5 / 7 / 2          # the line's of the bar's: half of the sketch's, the line is to be thinner
TEXT_OF_BAR = 3 / 7                # the text's height of the bar's, in the sketch
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
POLL_MS = 150


def stamp(now):
    """'10:24 / 2045 April 06' (months in English, whatever the language of the system)."""
    return f"{now:%H:%M} / {now.year} {MONTHS[now.month - 1]} {now.day:02d}"


class AndroidBar(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window_ = window
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAutoFillBackground(False)
        self.text = ""
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
        self.raise_()
        self.update()

    def tick(self):
        text = stamp(datetime.now())
        if text != self.text:
            self.text = text
            self.update()

    def follow_system_bars(self):
        self.setVisible(not androidbars.system_bars_shown())

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
    return window.android_bar
