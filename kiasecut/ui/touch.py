"""Touch screens: fingers on the views that are zoomed and scrolled (the preview, the timeline, the node editor, the curve editor).

One finger is the mouse: the widget is sent a left-button press, moves and release at the finger, so every drag, click and
menu works as it does with a mouse. (Qt would make those itself from touches nobody takes, but then lets go of the touch
as well, and a second finger never arrives; so the touches are taken here and the mouse is made here.)
  * the press waits PRESS_MS, so a second finger that lands a moment after the first does not click under it; the finger must
    leave a SLOP_PX circle before it moves anything (a tap is not a drag by a finger's tremble);
  * a second tap on the same spot soon after the first is a double click (the widget gets MouseButtonDblClick);
  * a finger held still (about half a second) and then lifted is a right click: the menu a right click opens, at the finger;
    a finger held and then moved is the drag it always was (the hold only matters if the finger comes up where it was) - but
    where enable()'s hold_right says so it is a drag with the right button (the timeline's selection of time).
Where enable()'s hold_left says a thing there is only dragged once the finger has been held (the timeline's clips), the hold is
what lets go of it: the finger lights it (the lit callback: it goes white) and buzzes, and from then on it is dragged; a finger
that moves before that is a swipe of the view (as in a scroll area), not a drag. The same swipe comes before a right-button hold.
Beyond that, for a widget given to enable():
  * two fingers pinch (a zoom, as a touchpad's pinch: a native gesture event) and move the view (a scroll, as a touchpad's
    two-finger scroll: a wheel event with pixel motion), both at once if the fingers do both - the views already read those;
    lifting them while still moving lets the scroll glide on and slow down (wheel events of the momentum phase);
  * two or three fingers put down and lifted together, without moving, are a tap of that many fingers: on_tap(n, f) calls f
    (the main window makes two undo and three redo).
For a scroll area (enable(viewport, scroll=True); install_scrolling() does that for every one in the program) one finger that
moves before the hold is a swipe: the area scrolls (wheel events, and it glides on after the finger lifts); the mouse press
is made only when the finger is lifted, or held for HOLD_MS - then a move is the drag it is with a mouse (dragging an item
out of a list, scrubbing a number) and lifting in place is the right click.
scale() tells the views how much bigger to make what is to be hit: 1 for a mouse, FINGER_SCALE after the last input was a finger.
The first finger's mouse press is taken back as soon as a second finger comes: a mouse release goes to the widget, so a
drag that had begun ends where it stands.
"""
import math
import time

import shiboken6

from PySide6.QtCore import QEvent, QObject, QPointF, QPoint, Qt, QTimer
from PySide6.QtGui import (QContextMenuEvent, QEventPoint, QGuiApplication, QMouseEvent, QNativeGestureEvent, QPointingDevice,
                           QWheelEvent)
from PySide6.QtWidgets import QAbstractScrollArea, QApplication

from .. import haptic
from . import appevents

HOLD_MS = 550            # a finger this long on the same spot is a right click (when lifted there)
PRESS_MS = 70            # the mouse press waits this long for a second finger
SLOP_PX = 10             # a finger moves nothing until it has gone this far from where it came down (at least: see slop())
SLOP_DP = 12             # ... or this far in dp on a screen of many pixels to the inch: a finger held still still wanders
DOUBLE_S, DOUBLE_PX = 0.35, 30      # a second tap this soon and this near the first is a double click
TAP_S = 0.35             # fingers down and up within this long, without moving, are a tap
MIN_ZOOM = 0.003         # a pinch step smaller than this (as a ratio) is not sent
GLIDE_MIN = 120.0        # px/s: a scroll slower than this when the fingers lift does not glide
GLIDE_STOP = 25.0        # px/s: a glide slower than this stops
GLIDE_TAU = 0.35         # s: the glide's speed falls to 1/e this long after
GLIDE_FRAME_MS = 16
SAMPLE_S = 0.1           # the speed of a scroll is read over this last stretch
FINGER_SCALE = 2.0       # how much bigger hit areas and handles are for a finger

RELEASED = QEventPoint.State.Released
_TOUCH = (QEvent.TouchBegin, QEvent.TouchUpdate, QEvent.TouchEnd, QEvent.TouchCancel)

_finger = False          # the last input was a finger
_taps = {}               # number of fingers -> what to call


def slop():
    """How far (px) a finger may wander from where it came down and still be a held or tapping one: SLOP_DP dp (160 dpi), not less than
    SLOP_PX. A finger on a tablet drifts a few mm while it is held, and 10 px there is little more than 1 mm: the hold was lost."""
    screen = QGuiApplication.primaryScreen()
    dpi = screen.logicalDotsPerInch() if screen is not None else 160.0
    return max(float(SLOP_PX), SLOP_DP * dpi / 160.0)


def scale():
    """1 for the mouse, FINGER_SCALE when the last thing used was a finger: multiply the sizes that are hit (or drawn to be hit) by it."""
    return FINGER_SCALE if _finger else 1.0


def on_tap(fingers, func):
    """Call func when `fingers` (2 or 3) tap a widget given to enable()."""
    _taps[fingers] = func


class Finger:
    def __init__(self, pos):
        self._pos = pos

    def position(self):
        return self._pos


def _dist(a, b):
    return math.hypot(a.x() - b.x(), a.y() - b.y())


class _Gestures(QObject):
    def __init__(self, widget, scroll=False, hold_right=None, hold_left=None, lit=None):
        super().__init__(widget)
        self.w = widget
        self.hold_right = hold_right           # f(point) -> whether a finger held at point and then moved drags with the RIGHT button
        self.hold_left = hold_left             # f(point) -> whether what is at point is dragged (left button) only after a hold
        self.lit = lit                         # f(point or None, on): what was held at point is lit (goes white) / is not any more
        self.lit_on = False
        self.gated = False                     # this finger came down where a hold comes first
        self.waits = False                     # ... or where the press waits for the first move or the hold
        self.right = self.right_down = False   # ... the hold was such a one / the right button is down
        self.scroll = scroll                   # a scroll area's viewport: one finger swipes before it holds
        self.swiping = False                   # ... and has begun to
        self.swipe_from = QPointF()
        self.grab = None                       # the widget that got the press (it gets the moves and the release too)
        self.mode = "idle"                      # idle, one (a finger down: the mouse), multi (pinch / scroll / tap)
        self.hold = QTimer(self)
        self.hold.setSingleShot(True)
        self.hold.setInterval(HOLD_MS)
        self.hold.timeout.connect(self._held)
        self.defer = QTimer(self)
        self.defer.setSingleShot(True)
        self.defer.setInterval(PRESS_MS)
        self.defer.timeout.connect(self._press)
        self.flush = QTimer(self)                  # the finger's moves are sent once for each turn of the event loop (see _drag)
        self.flush.setSingleShot(True)
        self.flush.setInterval(0)
        self.flush.timeout.connect(self._flush_move)
        self.queued = None
        self.glide = QTimer(self)
        self.glide.setInterval(GLIDE_FRAME_MS)
        self.glide.timeout.connect(self._glide)
        self.start = self.last = QPointF()
        self.fingers = {}                       # touch point id -> where it is, for the fingers down
        self.rest = QPointF()                   # the scroll motion not yet sent (whole pixels only)
        self.scrolling = False
        self.pressed = self.moved = self.held = self.double = False
        self.tap_t, self.tap_at = 0.0, QPointF()          # the last tap of one finger (for a double click)
        self.sending = False                    # a mouse event of ours is being sent
        self.samples = []                       # (time, dx, dy) of the scroll sent lately
        self.speed = (0.0, 0.0)
        self.glide_at = QPointF()
        self.glide_t = 0.0
        self.prev = self.origin = (0.0, 0.0, 0.0)
        self.t_multi, self.peak, self.tapping = 0.0, 0, False
        widget.setAttribute(Qt.WA_AcceptTouchEvents, True)
        widget.setProperty("kcTouch", True)
        widget.installEventFilter(self)

    def eventFilter(self, obj, e):
        global _finger
        if obj is not self.w:
            return False
        t = e.type()
        if t in (QEvent.MouseButtonPress, QEvent.MouseMove) and not self.sending \
                and e.source() == Qt.MouseEventNotSynthesized:
            _finger = False                                # (a real mouse: the small hit areas again)
            return False
        if t not in _TOUCH:
            return False
        _finger = True
        taken = self._touch(e)
        if taken:
            e.accept()                      # (a TouchBegin counts as taken only when accepted: the following touches come to the widget then)
        return taken

    # -- the touch event ------------------------------------------------------------------------------------------------
    def _touch(self, e):
        if e.type() == QEvent.TouchCancel:
            if self.mode == "one" and not self.swiping:
                self._lift()
            self.swiping = False
            self._finish()
            return True
        for p in e.points():                               # (a finger may come as a TouchBegin of its own, or only the moved ones come)
            if p.state() == RELEASED:
                self.fingers.pop(p.id(), None)
            else:
                self.fingers[p.id()] = p.position()
        down = [Finger(pos) for pos in self.fingers.values()]
        now = time.monotonic()
        if self.mode == "idle" and down:
            self.glide.stop()
            self._begin(down[0].position(), now)
        if self.mode == "one":
            if len(down) >= 2:                             # a second finger: the first one's press is taken back
                self._to_multi(down, now)
            elif down:
                self._drag(down[0].position())
            else:                                          # the finger is up
                self._up(now)
        elif self.mode == "multi" and len(down) >= 2:
            self.peak = max(self.peak, len(down))
            self._pinch(down, now)
        if self.mode == "multi" and not down:
            self._tap_or_glide(now)
            self._finish()
        return True

    def _finish(self):
        self._light(None, False)
        self.fingers.clear()
        self.hold.stop()
        self.defer.stop()
        if self.scrolling:
            self._wheel(QPoint(0, 0), Qt.ScrollEnd)
        self.scrolling = False
        self.mode = "idle"

    # -- one finger: the mouse ----------------------------------------------------------------------------------------------
    def _begin(self, at, now):
        self.mode = "one"
        self.start = self.last = at
        self.pressed = self.moved = self.held = self.swiping = self.right = False
        kind = self._kind(at)
        self.gated = kind in ("right", "left")             # (a hold comes first; "late": the drag is at once if the finger moves first)
        self.waits = kind is not None
        self.double = now - self.tap_t < DOUBLE_S and _dist(at, self.tap_at) < DOUBLE_PX
        if not self.scroll and not self.waits:                   # (what waits for the hold - a left or a right drag, or a swipe
            self.defer.start()                                  #  - is pressed at the first move or the hold, as a scroll area's is)
        self.hold.start()

    def _press(self):
        """The mouse press at the finger (the second tap of a double click is sent as one)."""
        if self.mode != "one" or self.pressed:
            return
        self.pressed = True
        self._mouse(QEvent.MouseButtonDblClick if self.double else QEvent.MouseButtonPress, self.start, Qt.LeftButton, Qt.LeftButton)

    def _drag(self, at):
        self.last = at
        if self.swiping:
            self._swipe(at)
            return
        if not self.moved and _dist(at, self.start) > slop():
            self.hold.stop()
            self.defer.stop()
            if (self.scroll or self.gated) and not self.pressed and not self.held:    # (before the hold: the view is scrolled, nothing is pressed)
                self.swiping, self.swipe_from = True, self.start
                self.rest, self.samples, self.scrolling = QPointF(), [], False
                self._swipe(at)
                return
            self.moved, self.held = True, False
            if self.right:                                 # (held first: the right button's drag - the timeline's selection of time)
                self.right_down = self.pressed = True
                self._mouse(QEvent.MouseButtonPress, self.start, Qt.RightButton, Qt.RightButton)
            else:
                self._press()
        if self.moved:                                     # (a move is sent when the event loop is next free: what a slow reaction to
            self.queued = at                               #  one move - a preview drawn - would hold up, the finger's moves piling up behind
            if not self.flush.isActive():                  #  it, comes as one move to where the finger is, and the screen is drawn between)
                self.flush.start()

    def _kind(self, at):
        """What a hold at `at` makes of the finger: "right" (a right-button drag), "left" (the thing there is let go to be dragged), or
        None (nothing is waited for)."""
        if self.hold_right is not None:
            r = self.hold_right(at)
            if r:
                return "right_late" if r == "late" else "right"
        if self.hold_left is not None and self.hold_left(at):
            return "left"
        return None

    def _light(self, at, on):
        if on == self.lit_on:
            return
        self.lit_on = on
        if self.lit is not None:
            self.lit(at, on)

    def _flush_move(self):
        at, self.queued = self.queued, None
        if at is not None and self.mode == "one" and self.moved and not self.swiping:
            self._mouse(QEvent.MouseMove, at, Qt.NoButton, Qt.RightButton if self.right_down else Qt.LeftButton)

    def _swipe(self, at):
        self.rest += QPointF(at.x() - self.swipe_from.x(), at.y() - self.swipe_from.y())
        self.swipe_from = at
        self._scroll_by(time.monotonic(), at)

    def _scroll_by(self, now, centre):
        """Send the whole pixels of self.rest as a scroll at centre."""
        whole = QPoint(int(self.rest.x()), int(self.rest.y()))
        if whole.x() or whole.y():
            self.rest -= QPointF(whole)
            self._wheel(whole, Qt.ScrollUpdate if self.scrolling else Qt.ScrollBegin, centre)
            self.scrolling = True
            self.samples = [s for s in self.samples if now - s[0] <= SAMPLE_S] + [(now, whole.x(), whole.y())]

    def _lift(self):
        """The release that ends the press (made first if the finger was up before the press was due)."""
        self.hold.stop()
        self.defer.stop()
        self._press()
        self._flush_move()
        self._mouse(QEvent.MouseButtonRelease, self.last, Qt.RightButton if self.right_down else Qt.LeftButton, Qt.NoButton)
        self.pressed = self.right_down = self.right = False
        self._light(None, False)

    def _up(self, now):
        if self.swiping:
            self.swiping, self.tap_t = False, 0.0
            self.mode = "idle"
            self.hold.stop()
            self._glide_from(now, self.last)
            if self.scrolling:
                self._wheel(QPoint(0, 0), Qt.ScrollEnd, self.last)
            self.scrolling = False
            return
        self._lift()
        if self.held and not self.moved:
            self.tap_t = 0.0
            self._right_click(self.last)
        elif not self.moved:                               # a tap (what a double click may follow)
            self.tap_t, self.tap_at = (0.0 if self.double else now), self.last
        else:
            self.tap_t = 0.0
        self.held = False
        self.mode = "idle"

    # -- the hold: a right click when the finger is lifted where it was ----------------------------------------------------
    def _held(self):
        if self.mode == "one" and not self.moved and not self.swiping:
            self.held = True
            kind = self._kind(self.start)
            if kind in ("right", "right_late"):
                self.right = True                          # (nothing is pressed yet: the first move presses the right button)
            elif kind == "left":
                self._press()                              # (what was held is let go: pressed, and lit, and dragged by the moves)
                self._light(self.start, True)
            elif self.scroll:
                self._press()                              # (the press a scroll area waited with)
            haptic.tick()

    def _right_click(self, at):
        self._mouse(QEvent.MouseButtonPress, at, Qt.RightButton, Qt.RightButton)
        target = self.w.childAt(at.toPoint()) or self.w
        local = target.mapFrom(self.w, at.toPoint())
        self._send(target, QContextMenuEvent(QContextMenuEvent.Mouse, local, target.mapToGlobal(local)))
        self._mouse(QEvent.MouseButtonRelease, at, Qt.RightButton, Qt.NoButton)

    # -- more fingers: pinch, two-finger scroll, taps ---------------------------------------------------------------------
    def _to_multi(self, down, now):
        self.hold.stop()
        self.defer.stop()
        if self.pressed:
            self._lift()
        if self.swiping and self.scrolling:
            self._wheel(QPoint(0, 0), Qt.ScrollEnd, self.last)
        self.swiping = self.held = False
        self.tap_t = 0.0
        self.mode = "multi"
        self.prev = self.origin = self._measure(down)
        self.rest = QPointF()
        self.scrolling = False
        self.samples = []
        self.t_multi, self.peak, self.tapping = now, len(down), True

    @staticmethod
    def _measure(points):
        """(centre x, centre y, distance) of the first two fingers."""
        a, b = points[0].position(), points[1].position()
        return (a.x() + b.x()) / 2, (a.y() + b.y()) / 2, math.hypot(a.x() - b.x(), a.y() - b.y())

    def _pinch(self, points, now):
        cx, cy, dist = self._measure(points)
        if self.tapping:                                   # (nothing is sent until the fingers have really moved)
            ox, oy, od = self.origin
            if math.hypot(cx - ox, cy - oy) <= slop() and abs(dist - od) <= slop() and now - self.t_multi < TAP_S:
                return
            self.tapping = False
        px, py, pdist = self.prev
        self.prev = (cx, cy, dist)
        centre = QPointF(cx, cy)
        if pdist > 1.0 and dist > 1.0:
            f = dist / pdist
            if abs(f - 1.0) >= MIN_ZOOM:
                self._native(centre, math.log(f))
        self.rest += QPointF(cx - px, cy - py)
        self._scroll_by(now, centre)

    def _tap_or_glide(self, now):
        if self.tapping:
            if now - self.t_multi < TAP_S and self.peak in _taps:
                _taps[self.peak]()
            return
        self._glide_from(now, QPointF(self.prev[0], self.prev[1]))

    def _glide_from(self, now, at):
        """Let the scroll go on after the fingers lift, at the speed they had (if they were still moving)."""
        recent = [s for s in self.samples if now - s[0] <= SAMPLE_S]
        if not self.scrolling or len(recent) < 2:
            return
        span = max(now - recent[0][0], 1e-3)
        vx, vy = sum(s[1] for s in recent) / span, sum(s[2] for s in recent) / span
        if math.hypot(vx, vy) >= GLIDE_MIN:
            self.speed, self.glide_t = (vx, vy), now
            self.glide_at = QPointF(at)
            self.rest = QPointF()
            self.glide.start()

    def _glide(self):
        now = time.monotonic()
        dt, self.glide_t = now - self.glide_t, now
        k = math.exp(-dt / GLIDE_TAU)
        vx, vy = self.speed
        self.rest += QPointF(vx * dt, vy * dt)
        self.speed = (vx * k, vy * k)
        whole = QPoint(int(self.rest.x()), int(self.rest.y()))
        if whole.x() or whole.y():
            self.rest -= QPointF(whole)
            self._wheel(whole, Qt.ScrollMomentum, self.glide_at)
        if math.hypot(*self.speed) < GLIDE_STOP:
            self.glide.stop()
            self._wheel(QPoint(0, 0), Qt.ScrollEnd, self.glide_at)

    def _native(self, at, value):
        g = self.w.mapToGlobal(at.toPoint())
        ev = QNativeGestureEvent(Qt.NativeGestureType.ZoomNativeGesture, QPointingDevice.primaryPointingDevice(), 2,
                                 at, at, QPointF(g), value, QPointF())
        QApplication.sendEvent(self.w, ev)

    def _scroll_areas(self, pixels):
        """Move the scroll area under the finger by pixels; what it cannot take (it fits, or it is at its end) goes to the scroll
        area around it - the panels whose lists are as tall as their items are scrolled by the tab they are in."""
        areas = []
        w = self.w.parentWidget()
        while w is not None:
            if isinstance(w, QAbstractScrollArea):
                areas.append(w)
            w = w.parentWidget()
        for d, bar_of in ((pixels.x(), QAbstractScrollArea.horizontalScrollBar), (pixels.y(), QAbstractScrollArea.verticalScrollBar)):
            for area in areas if d else ():
                bar = bar_of(area)
                v = bar.value()
                bar.setValue(v - d)
                if bar.value() != v:
                    break

    def _wheel(self, pixels, phase, at=None):
        if self.scroll:                                    # (a scroll area moves by the pixels, exactly: its wheel counts lines)
            self._scroll_areas(pixels)
            return
        at = at if at is not None else QPointF(self.prev[0], self.prev[1])
        g = self.w.mapToGlobal(at.toPoint())
        ev = QWheelEvent(at, QPointF(g), pixels, pixels, Qt.NoButton, Qt.NoModifier, phase, False)
        QApplication.sendEvent(self.w, ev)

    # -- sending ------------------------------------------------------------------------------------------------------------
    def _send(self, target, ev):
        self.sending = True
        try:
            QApplication.sendEvent(target, ev)
        finally:
            self.sending = False

    def _mouse(self, kind, at, button, buttons):
        if kind in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick) or self.grab is None or not shiboken6.isValid(self.grab):
            self.grab = self.w.childAt(at.toPoint()) or self.w     # (a box laid over the canvas gets its own clicks)
        target = self.grab                                         # (and keeps the moves and the release, as under a mouse)
        local = QPointF(target.mapFrom(self.w, at.toPoint())) if target is not self.w else at
        g = QPointF(target.mapToGlobal(local.toPoint()))
        self._send(target, QMouseEvent(kind, local, g, button, buttons, Qt.NoModifier))
        if kind == QEvent.MouseButtonRelease:
            self.grab = None


def enable(widget, scroll=False, hold_right=None, hold_left=None, lit=None):
    """Fingers zoom, scroll and right-click on widget (see the module notes; scroll: widget is a scroll area's viewport;
    hold_right: f(point), true where a finger that is held and then moved drags with the right button, as the timeline's
    selection of time ("late": a finger that moves first is the left button's drag at once, not a swipe - the ruler) - elsewhere on the widget a held finger is the left button's drag, as it is without it); hold_left:
    f(point), true where the thing is dragged only once held, and lit(point, on) lights it from the hold to the lifting
    (a finger that moves first swipes the view).
    Returns the helper (kept alive by widget)."""
    return _Gestures(widget, scroll, hold_right, hold_left, lit)


def install_scrolling():
    """Every scroll area in the program (lists, trees, panels; not a menu's or a combo box's popup) is scrolled by one finger
    and its items dragged after a hold, once it is shown."""
    def shown(obj, e):
        if isinstance(obj, QAbstractScrollArea):
            view = obj.viewport()
            if view is not None and not view.property("kcTouch") and obj.window().windowType() != Qt.Popup:
                enable(view, scroll=True)
        return False
    appevents.watch(QApplication.instance(), [QEvent.Show], shown)
