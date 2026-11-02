"""The curve editor's view: the middle button drags it, Ctrl+middle-drag zooms it around where
the drag started (as in Blender's graph editor: sideways zooms time, up and down values)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut.ui.curve_editor import CurveCanvas  # noqa: E402

APP = QApplication.instance() or QApplication([])
NONE = Qt.KeyboardModifier.NoModifier
S = 1_000_000


def drag(w, a, b, mods=NONE):
    QTest.mousePress(w, Qt.MiddleButton, mods, a)
    QTest.mouseMove(w, b)
    QTest.mouseRelease(w, Qt.MiddleButton, mods, b)


class CurveViewTests(unittest.TestCase):
    def setUp(self):
        self.cv = CurveCanvas()
        self.cv.resize(800, 400)
        keys = [[0, 0.0, 0, 0, 0, 0], [2 * S, 100.0, 0, 0, 0, 0]]
        self.cv.set_curves([{"label": "x", "factor": 1.0, "keys": keys, "static": 0.0}], 2 * S, 30.0, 0)

    def span(self):
        lo, hi = self.cv.vrange
        return self.cv.t1 - self.cv.t0, hi - lo

    def test_middle_drag_pans(self):
        ts, vs = self.span()
        t0, lo = self.cv.t0, self.cv.vrange[0]
        drag(self.cv, QPoint(400, 200), QPoint(450, 230))
        self.assertEqual(self.span(), (ts, vs))
        self.assertLess(self.cv.t0, t0)              # dragged right: earlier times come into view
        self.assertGreater(self.cv.vrange[0], lo)    # dragged down: higher values come into view

    def test_ctrl_middle_drag_zooms_both_axes_around_the_press(self):
        at = QPoint(300, 150)
        before = (self.cv.t_of(at.x()), self.cv.p_of(at.y()))
        ts, vs = self.span()
        drag(self.cv, at, QPoint(400, 100), Qt.ControlModifier)      # right and up: in
        nts, nvs = self.span()
        self.assertLess(nts, ts * 0.8)
        self.assertLess(nvs, vs * 0.9)
        self.assertAlmostEqual(self.cv.t_of(at.x()), before[0], delta=1)
        self.assertAlmostEqual(self.cv.p_of(at.y()), before[1], places=6)
        self.assertIsNone(self.cv.drag)
        drag(self.cv, at, QPoint(250, 200), Qt.ControlModifier)      # left and down: out
        self.assertGreater(self.span()[0], nts)
        self.assertGreater(self.span()[1], nvs)

    def test_ctrl_middle_drag_one_way_zooms_one_axis(self):
        ts, vs = self.span()
        drag(self.cv, QPoint(300, 150), QPoint(400, 150), Qt.ControlModifier)
        self.assertLess(self.span()[0], ts)
        self.assertAlmostEqual(self.span()[1], vs)


class DragLockTests(unittest.TestCase):
    """Shift keeps a dragged keyframe to the time axis, Alt to the values; a handle with Shift to one direction."""

    def setUp(self):
        self.cv = CurveCanvas()
        self.cv.resize(800, 400)
        keys = [[0, 0.0, 0, 0, S // 4, 5.0], [S, 50.0, -S // 4, -5.0, S // 4, 5.0], [2 * S, 100.0, -S // 4, -5.0, 0, 0]]
        self.cv.set_curves([{"label": "x", "factor": 1.0, "keys": keys, "static": 0.0}], 2 * S, 30.0, 0)

    def move(self, to, mods=NONE):
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent
        g = self.cv.mapToGlobal(QPointF(to))
        self.cv.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(to), g, Qt.NoButton, Qt.LeftButton, mods))

    def key(self):
        return list(self.cv.curves[0]["keys"][1])

    def press_key(self):
        a = self.cv.key_point(0, 1).toPoint()
        QTest.mousePress(self.cv, Qt.LeftButton, NONE, a)
        return a

    def test_plain_drag_moves_both(self):
        a = self.press_key()
        self.move(a + QPoint(60, -40))
        self.move(a + QPoint(60, -40))
        k = self.key()
        QTest.mouseRelease(self.cv, Qt.LeftButton, NONE, a + QPoint(60, -40))
        self.assertNotEqual(k[0], S)
        self.assertNotEqual(k[1], 50.0)

    def test_shift_keeps_to_the_time_and_alt_to_the_values(self):
        a = self.press_key()
        self.move(a + QPoint(60, -40), Qt.ShiftModifier)
        k = self.key()
        self.assertNotEqual(k[0], S)
        self.assertEqual(k[1], 50.0)                                       # (the value stayed)
        self.move(a + QPoint(60, -40), Qt.AltModifier)
        k = self.key()
        self.assertEqual(k[0], S)                                          # (the time stayed)
        self.assertGreater(k[1], 50.0)
        QTest.mouseRelease(self.cv, Qt.LeftButton, NONE, a)

    def test_a_handle_with_shift_keeps_one_direction(self):
        a = self.press_key()
        QTest.mouseRelease(self.cv, Qt.LeftButton, NONE, a)                # (selected: its handles show)
        (side, hp), = [h for h in self.cv._handle_points(0, 1) if h[0] == "r"]
        hp = hp.toPoint()
        before = self.key()
        QTest.mousePress(self.cv, Qt.LeftButton, NONE, hp)
        self.move(hp + QPoint(50, 8), Qt.ShiftModifier)                    # (mostly across)
        across = self.key()
        self.assertGreater(across[4], before[4])
        self.assertEqual(across[5], before[5])
        self.move(hp + QPoint(6, -60), Qt.ShiftModifier)                   # (mostly up)
        up = self.key()
        self.assertEqual(up[4], before[4])
        self.assertGreater(up[5], before[5])
        self.move(hp + QPoint(50, -60))                                    # (no Shift: free)
        free = self.key()
        self.assertGreater(free[4], before[4])
        self.assertGreater(free[5], before[5])
        QTest.mouseRelease(self.cv, Qt.LeftButton, NONE, hp)


if __name__ == "__main__":
    unittest.main()
