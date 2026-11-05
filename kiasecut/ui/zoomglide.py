"""Smooth zoom (平滑縮放) for a view whose mouse wheel zooms: the notches are collected and spent over about a
fifth of a second (the distance left halves every 55 ms, as smoothscroll's glide), each step zooming a fraction of a
notch around the pointer. A touchpad and a pinch zoom directly, they are smooth already."""
import time

from PySide6.QtCore import QObject, QTimer

HALF_LIFE_MS = 55.0
TICK_MS = 8
SMALL = 0.01              # notches: what is left below this is spent at once


class ZoomGlide(QObject):
    def __init__(self, owner, apply):
        """apply(notches, anchor): zoom by that many (fractions of) notches around anchor."""
        super().__init__(owner)
        self.apply, self.left, self.anchor, self.last = apply, 0.0, None, time.monotonic()
        self.timer = QTimer(self, interval=TICK_MS)
        self.timer.timeout.connect(self.step)

    def add(self, notches, anchor):
        self.left += notches
        self.anchor = anchor
        if not self.timer.isActive():
            self.last = time.monotonic()
            self.timer.start()

    def step(self):
        now = time.monotonic()
        k = 1.0 - 0.5 ** ((now - self.last) * 1000.0 / HALF_LIFE_MS)
        self.last = now
        take = self.left if abs(self.left) * (1.0 - k) < SMALL else self.left * k
        self.left -= take
        if take == self.left or abs(self.left) < 1e-9:
            self.left = 0.0
        if self.left == 0.0:
            self.timer.stop()
        self.apply(take, self.anchor)
