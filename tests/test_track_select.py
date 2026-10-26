"""Tracks picked by their headers (Ctrl / Shift for several), deleted together, and 清除空軌道."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit  # noqa: E402
from kiasecut.ui.timeline import Timeline  # noqa: E402
from test_tracks import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
NONE = Qt.KeyboardModifier.NoModifier


def with_empty(p):
    """proj() with two empty tracks: a picture one on top, a sound one at the bottom."""
    p["tracks"].insert(1, {"id": "e1", "kind": "video", "name": "e1", "clips": []})
    p["tracks"].append({"id": "e2", "kind": "audio", "name": "e2", "clips": []})
    return p


class EditTests(unittest.TestCase):
    def test_delete_tracks(self):
        p = with_empty(proj())
        self.assertEqual(edit.delete_tracks(p, ["a1", "e1", "a1"]), 2)
        self.assertEqual([t["id"] for t in p["tracks"]], ["v", "a2", "e2"])

    def test_remove_empty_tracks(self):
        p = with_empty(proj())
        self.assertEqual(edit.remove_empty_tracks(p), 2)
        self.assertEqual([t["id"] for t in p["tracks"]], ["v", "a1", "a2"])
        with self.assertRaises(edit.EditError):
            edit.remove_empty_tracks(p)

    def test_one_undo_step(self):
        p = with_empty(proj())
        h = edit.History(p)
        h.do("清除空軌道", edit.remove_empty_tracks)
        h.undo()
        self.assertEqual(len(p["tracks"]), 5)


class HeaderTests(unittest.TestCase):
    def setUp(self):
        self.tl = Timeline()
        self.tl.resize(900, 400)
        self.tl.set_project(with_empty(proj()))         # rows: e1, v, a1, a2, e2

    def click(self, row, mods=NONE):
        y = self.tl.tops[row] + 5
        QTest.mouseClick(self.tl, Qt.LeftButton, mods, QPoint(30, int(y)))

    def test_click_ctrl_shift(self):
        rows = [t["id"] for t in self.tl.rows]
        self.assertEqual(rows, ["e1", "v", "a1", "a2", "e2"])
        self.click(1)
        self.assertEqual(self.tl.selected_tracks, {"v"})
        self.click(3, Qt.ControlModifier)
        self.assertEqual(self.tl.selected_tracks, {"v", "a2"})
        self.click(1, Qt.ControlModifier)                  # out again
        self.assertEqual(self.tl.selected_tracks, {"a2"})
        self.click(0)
        self.click(2, Qt.ShiftModifier)                    # from the last one picked
        self.assertEqual(self.tl.selected_tracks, {"e1", "v", "a1"})

    def test_tracks_and_clips_exclude_each_other(self):
        self.tl.set_selection({"vid"}, "vid")
        self.click(0)
        self.assertEqual(self.tl.selected_ids, set())
        self.tl.set_selection({"vid"}, "vid")
        self.assertEqual(self.tl.selected_tracks, set())

    def test_gone_tracks_leave_the_selection(self):
        self.click(0)
        p = self.tl.proj
        edit.delete_tracks(p, ["e1"])
        self.tl.set_project(p, keep_view=True)
        self.assertEqual(self.tl.selected_tracks, set())


if __name__ == "__main__":
    unittest.main()
