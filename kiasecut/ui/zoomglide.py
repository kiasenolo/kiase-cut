"""Smooth zoom (平滑縮放) for a view whose mouse wheel zooms: the notches are collected and spent over about a
fifth of a second (the distance left halves every 55 ms, as smoothscroll's glide), each step zooming a fraction of a
notch around the pointer. A touchpad and a pinch zoom directly, they are smooth already."""
import time

from PySide6.QtCore import QObject, QTimer

from . import inertia

TICK_MS = 8
SMALL = 0.01              # notches: what is left below this is spent at once


class ZoomGlide(QObject):
    def __init__(self, owner, apply, channel):
        """apply(notches, anchor): zoom by that many (fractions of) notches around anchor; channel: inertia's."""
        super().__init__(owner)
        self.channel = channel
        self.apply, self.left, self.anchor, self.last = apply, 0.0, None, time.monotonic()
        self.timer = QTimer(self, interval=TICK_MS)
        self.timer.timeout.connect(self.step)

    def add(self, notches, anchor):
        if inertia.percent(self.channel) == 0:                   # (no glide: all at once)
            self.apply(notches, anchor)
            return
        self.left += notches
        self.anchor = anchor
        if not self.timer.isActive():
            self.last = time.monotonic()
            self.timer.start()

    def step(self):
        now = time.monotonic()
        k = 1.0 - 0.5 ** ((now - self.last) * 1000.0 / max(inertia.half_life_ms(self.channel), 1.0))
        self.last = now
        take = self.left if abs(self.left) * (1.0 - k) < SMALL else self.left * k
        self.left -= take
        if take == self.left or abs(self.left) < 1e-9:
            self.left = 0.0
        if self.left == 0.0:
            self.timer.stop()
        self.apply(take, self.anchor)
