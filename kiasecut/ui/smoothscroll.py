"""Wheel scrolling that glides (平滑捲動): a notch of a mouse wheel moves the content by what it always did, but over
a fifth of a second instead of at once, so the content slides and several notches in a row run together.

Done for every scroll area of the program that scrolls as Qt does (panels, lists, text boxes, dialogs); one that handles
the wheel itself (the timeline, preview, curve and node views zoom and pan with it) has its own code and is left alone, and so
is a touchpad (its fingers already move the content smoothly), Shift / Ctrl / Alt (sideways, zoom...) and a sideways wheel.
The filter sits on the area's viewport, so it sees only what the widgets inside did not take (a number field ignores the wheel,
and the event goes on to the area around it); at the end of the range it lets the event go on to the next area out, as Qt does.
"""
import time

import shiboken6
from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import QAbstractScrollArea, QApplication

from . import inertia, wheel

TICK_MS = 8
HALF_LIFE_MS = 55.0       # the distance still to go halves in this long: about 0.2 s to come to rest


def python_wheel(area):
    """Whether the area's class (or one below it) is written in Python with its own wheelEvent."""
    for cls in type(area).__mro__:
        if cls.__module__.startswith("PySide6") or cls is object:
            continue
        if "wheelEvent" in cls.__dict__:
            return True
    return False


class Glide(QObject):
    def __init__(self, area):
        super().__init__(area)
        self.area = area
        self.pos = float(area.verticalScrollBar().value())      # where the glide is (it keeps the fraction the bar cannot)
        self.target = self.pos
        self.shown = area.verticalScrollBar().value()           # what we last put in the bar (anything else is the user's)
        self.last = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self.step)
        area.viewport().installEventFilter(self)

    def bar(self):
        return self.area.verticalScrollBar()

    def eventFilter(self, obj, e):
        area = getattr(self, "area", None)
        if area is None or not shiboken6.isValid(area):          # (not made yet, or the area is being deleted)
            return False
        if e.type() != QEvent.Wheel or e.modifiers() != Qt.NoModifier or wheel.touchpad(e):
            return False
        a = e.angleDelta()
        if a.y() == 0 or abs(a.x()) > abs(a.y()):
            return False
        bar = self.bar()
        if bar.maximum() <= bar.minimum() or inertia.percent("scroll") == 0:
            return False                                         # (no glide: Qt scrolls as it always did)
        if bar.value() != self.shown:                            # (moved by something else since: start from there)
            self.pos = self.target = float(bar.value())
            self.shown = bar.value()
        step = bar.singleStep() * QApplication.wheelScrollLines()
        step = min(step, bar.pageStep()) if bar.pageStep() > 0 else step
        goal = min(max(self.target - a.y() / 120.0 * step, bar.minimum()), bar.maximum())
        if goal == self.target and not self.timer.isActive():
            return False                                         # (at the end: the area around may take it)
        self.target = goal
        if not self.timer.isActive():
            self.last = time.monotonic()
            self.timer.start()
        e.accept()
        return True

    def step(self):
        now = time.monotonic()
        dt = (now - self.last) * 1000.0
        self.last = now
        bar = self.bar()
        if bar.value() != self.shown:
            self.timer.stop()
            return
        k = 0.5 ** (dt / max(inertia.half_life_ms("scroll"), 1.0))
        self.pos = self.target + (self.pos - self.target) * k
        if abs(self.target - self.pos) < 0.5:
            self.pos = self.target
            self.timer.stop()
        self.shown = round(self.pos)
        bar.setValue(self.shown)
        self.shown = bar.value()


def attach(area):
    """Make a scroll area glide under the wheel (once), if it scrolls as Qt does."""
    if not isinstance(area, QAbstractScrollArea) or area.property("kcGlide") is not None or area.property("kcMaking") \
            or python_wheel(area):
        return
    area.setProperty("kcMaking", True)
    area.setProperty("kcGlide", Glide(area))
