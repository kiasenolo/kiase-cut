"""A label whose words change many times a second (the playhead's time, while playing).

A QLabel asks its layout to be worked out again each time its words change, and the request goes up through every
layout above it to the window's: the panels were laid out, and all that lay between the label and the window painted,
for every picture played. This one keeps the size of its words with every digit a 0, so words that differ only in their
digits ask for nothing; and with `back`, the colour it lies on, it fills itself, so nothing under it is painted either.
"""
import re

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLabel

_DIGIT = re.compile(r"\d")
_NO_LIMIT = 16777215                     # (QWIDGETSIZE_MAX)


class SteadyLabel(QLabel):
    def __init__(self, text="", back=None, parent=None):
        super().__init__(parent)
        self._shape = None
        self._back = QColor(back) if back else None
        self.setText(text)
        self._fills()

    def _fills(self):
        """It paints all of itself. Said again after each polish: a style sheet takes it back from a label whose
        background it calls transparent."""
        if self._back is not None:
            self.setAttribute(Qt.WA_OpaquePaintEvent)

    def setText(self, text):
        shape = _DIGIT.sub("0", text)
        if shape != self._shape:
            self._shape = shape
            self.setMinimumSize(0, 0)
            self.setMaximumSize(_NO_LIMIT, _NO_LIMIT)
            super().setText(shape)
            self.ensurePolished()                    # (the style sheet's font)
            self.setFixedSize(self.sizeHint())
        super().setText(text)

    def event(self, e):
        done = super().event(e)
        if e.type() == QEvent.Polish:
            self._fills()
        return done

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (QEvent.FontChange, QEvent.StyleChange) and self._shape is not None:
            self._shape = None                       # (other letters: their size again)
            self.setText(self.text())
            self._fills()

    def paintEvent(self, e):
        if self._back is not None:
            p = QPainter(self)
            p.fillRect(self.rect(), self._back)
            p.end()
        super().paintEvent(e)
