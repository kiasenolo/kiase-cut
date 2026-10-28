"""時間線標記: markers kept by the open level (the project's timeline entry, a compound's content),
saved with it; on the ruler a click goes to one, a drag moves it, hovering shows its name."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, project  # noqa: E402
from kiasecut.ui.timeline import Timeline  # noqa: E402
from test_edit import S, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
NONE = Qt.KeyboardModifier.NoModifier


class MarkerEditTests(unittest.TestCase):
    def test_add_rename_colour_move_delete(self):
        p = proj()
        a = edit.add_marker(p, 2 * S)
        self.assertEqual((a["name"], a["color"]), ("標記 1", edit.MARKER_COLORS[0][1]))
        self.assertIn(a, project.timeline(p)["markers"])                   # (the open timeline's)
        edit.set_marker_color(p, a["id"], "#e5484d")
        b = edit.add_marker(p, S)
        self.assertEqual(b["color"], "#e5484d")                             # the last one's colour
        self.assertEqual([m["id"] for m in edit.markers_of(p)], [b["id"], a["id"]])
        with self.assertRaises(edit.EditError):
            edit.add_marker(p, S)                                           # one there already
        edit.rename_marker(p, a["id"], "  副歌  ")
        self.assertEqual(a["name"], "副歌")
        edit.move_marker(p, a["id"], 3 * S)
        self.assertEqual(a["t_us"], 3 * S)
        with self.assertRaises(edit.EditError):
            edit.move_marker(p, a["id"], S)
        edit.delete_marker(p, b["id"])
        self.assertEqual(edit.markers_of(p), [a])
        edit.delete_marker(p, None)
        self.assertEqual(edit.markers_of(p), [])

    def test_saved_with_the_timeline(self):
        p = proj()
        edit.add_marker(p, S, "A")
        out = project.detached(p)
        self.assertEqual(out["timelines"][0]["markers"][0]["name"], "A")

    def test_each_timeline_has_its_own(self):
        p = proj()
        edit.add_marker(p, S)
        edit.add_timeline(p)
        self.assertEqual(edit.markers_of(p), [])
        edit.open_timeline(p, p["timelines"][0]["id"])
        self.assertEqual(len(edit.markers_of(p)), 1)


class RulerTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.tl = Timeline()
        self.tl.resize(900, 400)
        self.tl.set_project(self.p)
        self.tl.px_per_s, self.tl.scroll_s = 100.0, 0.0
        self.m = edit.add_marker(self.p, 2 * S, "副歌")

    def x(self, t_us):
        return round(self.tl._x(t_us / S))

    def test_hit_and_rect(self):
        self.assertIs(self.tl._marker_at(QPoint(self.x(2 * S) + 3, 8)), self.m)
        self.assertIsNone(self.tl._marker_at(QPoint(self.x(2 * S) + 20, 8)))
        self.assertIsNone(self.tl._marker_at(QPoint(self.x(2 * S), 100)))   # (below the ruler)
        self.assertIsNotNone(self.tl.marker_rect(self.m["id"]))

    def test_click_goes_there_and_drag_moves_it(self):
        seeks, moves = [], []
        self.tl.seekRequested.connect(seeks.append)
        self.tl.markerMoved.connect(lambda mid, t: moves.append((mid, t)))
        x = self.x(2 * S)
        QTest.mouseClick(self.tl, Qt.LeftButton, NONE, QPoint(x, 8))
        self.assertEqual(seeks, [round(2 * self.tl.fps)])
        self.tl.snapping = False
        QTest.mousePress(self.tl, Qt.LeftButton, NONE, QPoint(x, 8))
        QTest.mouseMove(self.tl, QPoint(x + 50, 8))
        QTest.mouseMove(self.tl, QPoint(x + 100, 8))
        QTest.mouseRelease(self.tl, Qt.LeftButton, NONE, QPoint(x + 100, 8))
        self.assertEqual(moves, [(self.m["id"], 3 * S)])                    # 100 px at 100 px/s
        self.assertEqual(self.m["t_us"], 2 * S)                             # (the edit is the window's)

    def test_clips_snap_to_markers(self):
        self.assertIn(2 * S, self.tl._snap_targets(None))


if __name__ == "__main__":
    unittest.main()
