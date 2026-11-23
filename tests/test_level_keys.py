"""Ctrl+D (the clip selection, else the in / out range) and Tab (into the selected compound, a group opens or folds, else
back up), as MainWindow.do_deselect / tab_level do them on the timeline."""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, project  # noqa: E402
from kiasecut.ui.main_window import MainWindow  # noqa: E402
from kiasecut.ui.timeline import Timeline  # noqa: E402
from test_tracks import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


class LevelKeyTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.tl = Timeline()
        self.tl.resize(900, 300)
        self.tl.set_project(self.p)
        self.done = []
        win = types.SimpleNamespace(timeline=self.tl, path_ids=[])
        win.set_mark = lambda which: (setattr(self.tl, "mark_in", None), setattr(self.tl, "mark_out", None),
                                      self.done.append(("mark", which)))
        win.on_clip_action = lambda action, cid: self.done.append((action, cid))
        win.leave_compound = lambda: self.done.append(("leave",))
        self.win = win

    def test_ctrl_d_clears_the_clips_first_then_the_range(self):
        self.tl.mark_in, self.tl.mark_out = 10, 40
        self.tl.set_selection({"vid"}, "vid")
        MainWindow.do_deselect(self.win)
        self.assertEqual(self.tl.selected_ids, set())
        self.assertEqual((self.tl.mark_in, self.tl.mark_out), (10, 40))     # (the range stays this time)
        MainWindow.do_deselect(self.win)
        self.assertEqual(self.done, [("mark", None)])
        MainWindow.do_deselect(self.win)                                     # nothing left: nothing happens
        self.assertEqual(self.done, [("mark", None)])

    def test_tab_enters_a_compound_folds_a_group_else_goes_up(self):
        g = edit.make_group(self.p, self.p, ["vid"])
        self.tl.set_project(self.p)
        self.tl.set_selection({g["id"]}, g["id"])
        was = self.tl.is_open(g)
        MainWindow.tab_level(self.win)
        self.assertNotEqual(self.tl.is_open(g), was)                         # a group: opens / folds in place
        c = {"id": "cc", "type": "compound", "name": "c", "start_us": 3_000_000, "duration_us": 1_000_000,
             "source_start_us": 0, "transform": {"x": 0.0, "y": 0.0}}
        self.p["tracks"][0]["clips"].append(c)
        self.tl.set_project(self.p)
        self.tl.set_selection({"cc"}, "cc")
        MainWindow.tab_level(self.win)
        self.assertEqual(self.done[-1], ("enter", "cc"))
        self.tl.set_selection(set())
        MainWindow.tab_level(self.win)                                       # nothing picked, at the top: nothing
        self.assertEqual(len(self.done), 1)
        self.win.path_ids = ["cc"]
        MainWindow.tab_level(self.win)
        self.assertEqual(self.done[-1], ("leave",))


if __name__ == "__main__":
    unittest.main()
