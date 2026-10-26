"""Wheel events from a touchpad as well as a mouse: zooms and scrolls go as far as the event
moved (a touchpad's many small events, and the empty ones that start and end its gesture, do
not each zoom a whole step), a two-finger scroll moves both ways at once, a pinch zooms, and
lists scroll by pixels."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QNativeGestureEvent, QPointingDevice, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QAbstractItemView, QApplication, QListWidget  # noqa: E402

from kiasecut.ui import wheel  # noqa: E402
from kiasecut.ui.curve_editor import CurveCanvas  # noqa: E402
from kiasecut.ui.timeline import Timeline  # noqa: E402
from test_edit import S, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
NONE = Qt.KeyboardModifier.NoModifier
AT = QPointF(500, 200)


def send(w, angle=(0, 0), pixel=(0, 0), phase=Qt.NoScrollPhase, mods=NONE):
    e = QWheelEvent(AT, w.mapToGlobal(AT), QPoint(*pixel), QPoint(*angle), Qt.NoButton, mods, phase, False)
    w.wheelEvent(e)


def pad(w, dx, dy, mods=NONE):
    """A touchpad gesture: begin, the moves (as many small events), end."""
    send(w, phase=Qt.ScrollBegin, mods=mods)
    for _ in range(10):
        send(w, (dx * 8 // 10, dy * 8 // 10), (dx // 10, dy // 10), Qt.ScrollUpdate, mods)
    send(w, phase=Qt.ScrollEnd, mods=mods)


def pinch(w, value):
    e = QNativeGestureEvent(Qt.ZoomNativeGesture, QPointingDevice.primaryPointingDevice(), 2, AT, AT,
                            w.mapToGlobal(AT), value, QPointF(), 0)
    return w.event(e)


class HelperTests(unittest.TestCase):
    def test_notches(self):
        e = QWheelEvent(AT, AT, QPoint(), QPoint(0, 120), Qt.NoButton, NONE, Qt.NoScrollPhase, False)
        self.assertEqual(wheel.notches(e), (0, 1))
        self.assertFalse(wheel.touchpad(e))
        e = QWheelEvent(AT, AT, QPoint(30, -50), QPoint(240, -400), Qt.NoButton, NONE, Qt.ScrollUpdate, False)
        self.assertTrue(wheel.touchpad(e))
        self.assertEqual(wheel.notches(e), (0.3, -0.5))
        self.assertEqual(wheel.notch(e), -0.5)
        self.assertEqual(wheel.pixels(e, 80, 40), (30, -50))

    def test_lists_scroll_by_pixels(self):
        style = wheel.Style("fusion")
        lst = QListWidget()
        lst.setStyle(style)
        self.assertEqual(lst.verticalScrollMode(), QAbstractItemView.ScrollPerPixel)


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.tl = Timeline()
        self.tl.resize(1000, 400)
        self.tl.set_project(proj())
        self.tl.px_per_s, self.tl.scroll_s = 100.0, 5.0
        self.tl.set_vzoom(3.0)

    def test_empty_events_change_nothing(self):
        z, v = self.tl.px_per_s, self.tl.vzoom
        for mods in (Qt.ControlModifier, Qt.AltModifier):
            send(self.tl, phase=Qt.ScrollBegin, mods=mods)
            send(self.tl, phase=Qt.ScrollEnd, mods=mods)
        self.assertEqual((self.tl.px_per_s, self.tl.vzoom), (z, v))

    def test_ctrl_touchpad_zooms_by_how_far_it_moved(self):
        pad(self.tl, 0, 100, Qt.ControlModifier)                 # a notch's worth, in ten events
        self.assertAlmostEqual(self.tl.px_per_s, 125.0, places=6)
        send(self.tl, (0, 120), mods=Qt.ControlModifier)          # a wheel notch: the same
        self.assertAlmostEqual(self.tl.px_per_s, 125.0 * 1.25, places=6)

    def test_two_finger_scroll_moves_both_ways(self):
        self.tl.set_vzoom(4.0)
        y = self.tl.scroll_y = 0
        pad(self.tl, 50, -30)
        self.assertAlmostEqual(self.tl.scroll_s, 4.5, places=6)    # 50 px at 100 px/s: earlier
        self.assertEqual(self.tl.scroll_y, y + 30)

    def test_mouse_wheel_steps_as_before(self):
        self.tl.set_vzoom(4.0)
        self.tl.scroll_y = 0
        send(self.tl, (0, -120))
        self.assertEqual(self.tl.scroll_y, 40)
        send(self.tl, (0, 120), mods=Qt.ShiftModifier)
        self.assertAlmostEqual(self.tl.scroll_s, 5.0 - 0.8, places=6)

    def test_pinch_zooms_time_around_the_mouse(self):
        at = self.tl._sec(AT.x())
        self.assertTrue(pinch(self.tl, 0.2))
        self.assertGreater(self.tl.px_per_s, 120)
        self.assertAlmostEqual(self.tl._sec(AT.x()), at, places=6)


class CurveTests(unittest.TestCase):
    def setUp(self):
        self.cv = CurveCanvas()
        self.cv.resize(800, 400)
        keys = [[0, 0.0, 0, 0, 0, 0], [2 * S, 100.0, 0, 0, 0, 0]]
        self.cv.set_curves([{"label": "x", "factor": 1.0, "keys": keys, "static": 0.0}], 2 * S, 30.0, 0)

    def test_empty_events_change_nothing(self):
        before = (self.cv.t0, self.cv.t1, self.cv.vrange)
        for mods in (NONE, Qt.ControlModifier, Qt.AltModifier):
            send(self.cv, phase=Qt.ScrollBegin, mods=mods)
        self.assertEqual((self.cv.t0, self.cv.t1, self.cv.vrange), before)

    def test_two_finger_scroll_follows_the_fingers(self):
        t = self.cv.t_of(300)
        p = self.cv.p_of(200)
        pad(self.cv, 50, -30)
        self.assertAlmostEqual(self.cv.t_of(350), t, delta=1)       # what was under x 300 is at 350
        self.assertAlmostEqual(self.cv.p_of(170), p, places=6)

    def test_mouse_wheel_moves_a_tenth(self):
        span = self.cv.t1 - self.cv.t0
        t0 = self.cv.t0
        send(self.cv, (0, 120), mods=Qt.ShiftModifier)
        self.assertAlmostEqual(self.cv.t0, t0 - span / 10, delta=1)

    def test_pinch_zooms_time(self):
        span = self.cv.t1 - self.cv.t0
        self.assertTrue(pinch(self.cv, 0.2))
        self.assertLess(self.cv.t1 - self.cv.t0, span)


if __name__ == "__main__":
    unittest.main()
