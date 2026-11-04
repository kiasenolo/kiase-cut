"""Inertia for a view that is moved by dragging it (the middle button on the timeline, the node editor, the preview, the curve
editor), as the same views glide on after two fingers (touch.py): when the button is let go while the pointer was still moving,
the view goes on in that direction, slowing down.

A ViewGlide belongs to one view: sample(x, y) with each move of the drag (where the pointer is, in the view's coordinates, the
drag's own - past the wraps), release() when the button is let go, stop() when anything else takes the view over (a press, the
wheel). `move(dx, dy)` is called for the whole pixels the view has gone on by, as the drag would have moved it for a pointer that
moved dx, dy. `scale` makes the glide shorter (0.5: half as far).
"""
import math
import time

from PySide6.QtCore import QObject, QPointF, QTimer

TAU = 0.35               # s: the speed falls to 1/e this long after (the same as the fingers' glide, touch.GLIDE_TAU)
MIN_SPEED = 25.0         # px / s: slower than this when the button is let go is no glide, and the glide ends below it
MAX_SPEED = 6000.0
SPAN_S = 0.1             # the speed is read over this last stretch
STILL_S = 0.08           # a pointer that has stopped for this long has no speed
FRAME_MS = 8


class ViewGlide(QObject):
    def __init__(self, view, move, scale=1.0, tau=TAU):
        super().__init__(view)
        self.move, self.scale, self.tau = move, scale, tau
        self.samples = []
        self.v = QPointF()
        self.rest = QPointF()
        self.last = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(FRAME_MS)
        self.timer.timeout.connect(self._step)

    def running(self):
        return self.timer.isActive()

    def stop(self):
        self.timer.stop()
        self.samples = []

    def sample(self, x, y):
        now = time.monotonic()
        self.samples = [s for s in self.samples if now - s[0] <= SPAN_S] + [(now, x, y)]

    def release(self):
        now = time.monotonic()
        recent = [s for s in self.samples if now - s[0] <= SPAN_S]
        self.samples = []
        if len(recent) < 2 or now - recent[-1][0] > STILL_S:
            return
        span = max(recent[-1][0] - recent[0][0], 0.03)
        vx = (recent[-1][1] - recent[0][1]) / span * self.scale
        vy = (recent[-1][2] - recent[0][2]) / span * self.scale
        speed = math.hypot(vx, vy)
        if speed < MIN_SPEED * (1 + self.scale):
            return
        if speed > MAX_SPEED:
            vx, vy = vx * MAX_SPEED / speed, vy * MAX_SPEED / speed
        self.v, self.rest, self.last = QPointF(vx, vy), QPointF(), now
        self.timer.start()

    def _step(self):
        now = time.monotonic()
        dt, self.last = now - self.last, now
        k = math.exp(-dt / self.tau)
        self.rest += QPointF(self.v.x() * dt, self.v.y() * dt)
        self.v = QPointF(self.v.x() * k, self.v.y() * k)
        whole = QPointF(int(self.rest.x()), int(self.rest.y()))
        if whole.x() or whole.y():
            self.rest -= whole
            self.move(int(whole.x()), int(whole.y()))
        if math.hypot(self.v.x(), self.v.y()) < MIN_SPEED:
            self.stop()
