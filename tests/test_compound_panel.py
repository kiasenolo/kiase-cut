"""The 複合片段 tab's right-click menu: 新增時間線 / 新增複合片段 / 新增靜態複合片段, and
edit.new_compound behind the last two (an empty compound with a clip at the playhead)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from kiasecut import edit, project  # noqa: E402
from kiasecut.ui.compounds import CompoundPanel  # noqa: E402
from test_edit import S, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


class NewCompoundTests(unittest.TestCase):
    def test_empty_compound_at_the_playhead(self):
        p = proj()
        c = edit.new_compound(p, p, 3 * S)
        comp = p["compounds"][c["compound_id"]]
        self.assertEqual((comp["name"], comp.get("static")), ("複合片段 1", None))
        self.assertEqual([t["clips"] for t in comp["tracks"]], [[]])
        self.assertEqual((c["start_us"], c["duration_us"]), (3 * S, edit.STILL_DEFAULT_US))
        self.assertIs(c["compound"], comp)
        track = next(t for t in p["tracks"] if c in t["clips"])
        self.assertEqual(track["id"], "t1")                    # the topmost picture track with room

    def test_static_one(self):
        p = proj()
        c = edit.new_compound(p, p, 0, static=True)
        comp = p["compounds"][c["compound_id"]]
        self.assertEqual((comp["name"], comp["static"], comp["still_us"]), ("靜態片段 1", True, 0))
        self.assertTrue(project.is_static(c))

    def test_no_room_makes_a_track(self):
        p = proj()
        p["tracks"][1]["clips"].append(dict(edit.find(p, "c1")[1], id="cx"))    # t1 busy at 0 s too
        n = len(p["tracks"])
        c = edit.new_compound(p, p, 0)
        self.assertEqual(len(p["tracks"]), n + 1)
        self.assertIn(c, next(t for t in p["tracks"] if t["id"] not in ("t0", "t1", "t2"))["clips"])


class PanelMenuTests(unittest.TestCase):
    def test_menu_offers_the_three(self):
        panel = CompoundPanel()
        panel.set_project(proj())
        got = []
        panel.createRequested.connect(got.append)
        menu = QMenu()
        panel._create_actions(menu)
        acts = [a for a in menu.actions() if not a.isSeparator()]
        self.assertEqual([a.text() for a in acts], ["新增時間線", "新增複合片段", "新增靜態複合片段"])
        for a in acts:
            a.trigger()
        self.assertEqual(got, ["timeline", "compound", "static"])


if __name__ == "__main__":
    unittest.main()
