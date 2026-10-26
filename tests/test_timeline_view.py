"""The timeline's view: the middle button drags it, Ctrl+middle-drag zooms it around where the
drag started (as in the curve editor: sideways the time, up and down the track height)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut.ui.timeline import Timeline  # noqa: E402
from test_tracks import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
NONE = Qt.KeyboardModifier.NoModifier


def drag(w, a, b, mods=NONE):
    QTest.mousePress(w, Qt.MiddleButton, mods, a)
    QTest.mouseMove(w, b)
    QTest.mouseRelease(w, Qt.MiddleButton, mods, b)


class TimelineViewTests(unittest.TestCase):
    def setUp(self):
        self.tl = Timeline()
        self.tl.resize(900, 400)
        p = proj()
        for i in range(8):                               # enough rows to scroll
            p["tracks"].append({"id": f"x{i}", "kind": "video", "name": f"x{i}", "clips": []})
        self.tl.set_project(p)
        self.tl.px_per_s, self.tl.scroll_s = 100.0, 2.0

    def test_middle_drag_pans(self):
        drag(self.tl, QPoint(500, 200), QPoint(450, 200))
        self.assertAlmostEqual(self.tl.scroll_s, 2.5)
        self.assertEqual((self.tl.px_per_s, self.tl.vzoom), (100.0, 1.0))

    def test_ctrl_middle_drag_zooms_both_ways_around_the_press(self):
        at = QPoint(500, 150)
        t = self.tl._sec(at.x())
        i, f = self.tl._row_part(at.y())
        drag(self.tl, at, QPoint(600, 100), Qt.ControlModifier)     # right and up: in
        self.assertGreater(self.tl.px_per_s, 130)
        self.assertGreater(self.tl.vzoom, 1.15)
        self.assertAlmostEqual(self.tl._sec(at.x()), t, places=6)   # the time pressed stays put
        self.assertEqual(self.tl._row_part(at.y())[0], i)           # so does the track
        self.assertAlmostEqual(self.tl._row_part(at.y())[1], f, delta=0.1)
        self.assertIsNone(self.tl.drag)
        px, vz = self.tl.px_per_s, self.tl.vzoom
        drag(self.tl, at, QPoint(450, 200), Qt.ControlModifier)     # left and down: out
        self.assertLess(self.tl.px_per_s, px)
        self.assertLess(self.tl.vzoom, vz)

    def test_ctrl_middle_drag_one_way_zooms_one_way(self):
        drag(self.tl, QPoint(500, 150), QPoint(500, 250), Qt.ControlModifier)
        self.assertEqual(self.tl.px_per_s, 100.0)
        self.assertLess(self.tl.vzoom, 1.0)

    def test_hand_sized_tracks_keep_their_height_after_zooming_back(self):
        self.tl.heights["x0"] = 61
        a = QPoint(500, 150)
        QTest.mousePress(self.tl, Qt.MiddleButton, Qt.ControlModifier, a)
        for y in range(140, 0, -10):
            QTest.mouseMove(self.tl, QPoint(500, y))
        QTest.mouseMove(self.tl, a)
        QTest.mouseRelease(self.tl, Qt.MiddleButton, Qt.ControlModifier, a)
        self.assertEqual((self.tl.vzoom, self.tl.heights["x0"]), (1.0, 61))


if __name__ == "__main__":
    unittest.main()
