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


if __name__ == "__main__":
    unittest.main()
