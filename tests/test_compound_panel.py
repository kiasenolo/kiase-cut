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
        self.assertEqual((comp["name"], comp["static"]), ("靜態片段 1", True))
        self.assertTrue(project.is_static(c))

    def test_no_room_makes_a_track(self):
        p = proj()
        p["tracks"][1]["clips"].append(dict(edit.find(p, "c1")[1], id="cx"))    # t1 busy at 0 s too
        n = len(p["tracks"])
        c = edit.new_compound(p, p, 0)
        self.assertEqual(len(p["tracks"]), n + 1)
        self.assertIn(c, next(t for t in p["tracks"] if t["id"] not in ("t0", "t1", "t2"))["clips"])


class OpenByItselfTests(unittest.TestCase):
    def test_add_compound_places_nothing(self):
        p = proj()
        before = [list(t["clips"]) for t in p["tracks"]]
        kid = edit.add_compound(p, static=True)
        self.assertEqual([t["clips"] for t in p["tracks"]], before)
        comp = p["compounds"][kid]
        self.assertEqual((comp["name"], comp["static"], comp["width"]), ("靜態片段 1", True, p["width"]))
        self.assertEqual(project.compound_uses(p)[kid], [])

    def test_walk_path(self):
        from kiasecut.ui.main_window import OPEN_PREFIX, walk_path
        p = proj()
        kid = edit.add_compound(p)
        steps = walk_path(p, [OPEN_PREFIX + kid])
        self.assertEqual(steps, [(None, p["compounds"][kid], kid)])
        inner = edit.new_compound(p, p["compounds"][kid], 0)               # a compound inside it
        steps = walk_path(p, [OPEN_PREFIX + kid, inner["id"]])
        self.assertIs(steps[-1][1], inner["compound"])
        self.assertEqual(steps[-1][2], inner["compound_id"])
        with self.assertRaises(KeyError):
            walk_path(p, [OPEN_PREFIX + "gone"])
        placed = edit.new_compound(p, p, 0)
        with self.assertRaises(edit.EditError):                            # only first
            walk_path(p, [placed["id"], OPEN_PREFIX + kid])

    def test_list_opens_an_unused_compound(self):
        p = proj()
        kid = edit.add_compound(p)
        panel = CompoundPanel()
        panel.set_project(p)
        got = []
        panel.entryRequested.connect(got.append)
        row = next(panel.tree.topLevelItem(i) for i in range(panel.tree.topLevelItemCount())
                   if panel.tree.topLevelItem(i).data(0, 0x0100)[1] == kid)
        panel._double(row, 0)
        self.assertEqual(got, [kid])
        menu = QMenu()
        panel._item_actions(menu, ("def", kid))
        next(a for a in menu.actions() if a.text() == "進入編輯").trigger()
        self.assertEqual(got, [kid, kid])
        panel.set_project(p, ["cmp:" + kid])                               # shown in bold while open
        row = next(panel.tree.topLevelItem(i) for i in range(panel.tree.topLevelItemCount())
                   if panel.tree.topLevelItem(i).data(0, 0x0100)[1] == kid)
        self.assertTrue(row.font(0).bold())


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
