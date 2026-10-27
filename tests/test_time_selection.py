"""The time selection (as in FL Studio): a right drag selects time; one that starts at an end of
the selection moves only that end, one that starts elsewhere selects anew."""
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


class TimeSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tl = Timeline()
        self.tl.resize(900, 400)
        p = proj()
        p["duration_us"] = 60_000_000
        self.tl.set_project(p)
        self.tl.px_per_s, self.tl.scroll_s = 100.0, 0.0
        self.tl._snap = lambda t, clip: t                 # (snapping is not what is tested)

    def x(self, frame):
        return round(self.tl._x(frame / self.tl.fps))

    def rdrag(self, x0, x1, y=200):
        QTest.mousePress(self.tl, Qt.RightButton, NONE, QPoint(x0, y))
        QTest.mouseMove(self.tl, QPoint((x0 + x1) // 2, y))
        QTest.mouseMove(self.tl, QPoint(x1, y))
        QTest.mouseRelease(self.tl, Qt.RightButton, NONE, QPoint(x1, y))

    def marks(self):
        return self.tl.mark_in, self.tl.mark_out

    def test_drag_selects(self):
        fps = self.tl.fps
        self.rdrag(self.x(fps), self.x(3 * fps))
        self.assertEqual(self.marks(), (fps, 3 * fps - 1))

    def test_drag_from_the_end_moves_only_the_end(self):
        fps = self.tl.fps
        self.tl.mark_in, self.tl.mark_out = fps, 3 * fps - 1
        self.rdrag(self.x(3 * fps) + 3, self.x(5 * fps))
        self.assertEqual(self.marks(), (fps, 5 * fps - 1))
        self.rdrag(self.x(5 * fps), self.x(2 * fps))      # back in, past nothing
        self.assertEqual(self.marks(), (fps, 2 * fps - 1))

    def test_drag_from_the_start_moves_only_the_start(self):
        fps = self.tl.fps
        self.tl.mark_in, self.tl.mark_out = 2 * fps, 4 * fps - 1
        self.rdrag(self.x(2 * fps) - 4, self.x(fps))
        self.assertEqual(self.marks(), (fps, 4 * fps - 1))

    def test_an_end_dragged_past_the_other_turns_the_selection_over(self):
        fps = self.tl.fps
        self.tl.mark_in, self.tl.mark_out = 2 * fps, 4 * fps - 1
        self.rdrag(self.x(2 * fps), self.x(6 * fps))
        self.assertEqual(self.marks(), (4 * fps, 6 * fps - 1))

    def test_drag_elsewhere_selects_anew(self):
        fps = self.tl.fps
        self.tl.mark_in, self.tl.mark_out = fps, 3 * fps - 1
        self.rdrag(self.x(5 * fps), self.x(7 * fps))
        self.assertEqual(self.marks(), (5 * fps, 7 * fps - 1))


if __name__ == "__main__":
    unittest.main()
