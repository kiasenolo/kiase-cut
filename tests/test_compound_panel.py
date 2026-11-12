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


class PanelRefreshTests(unittest.TestCase):
    """Every edit hands the project to the list again: it is filled again only when what it shows has changed."""

    def test_the_list_is_left_alone_by_edits_that_change_nothing_in_it(self):
        p = proj()
        a = edit.new_compound(p, p, 3 * S)
        inner = edit.place_compound(p, p["compounds"][a["compound_id"]], edit.add_compound(p), None, 0)   # one in the other
        project.refresh_duration(p)
        panel = CompoundPanel()
        panel.set_project(p, [])
        first = panel.tree.topLevelItem(1)
        self.assertEqual(panel.uses, project.compound_uses(p))
        edit.set_param(p, "c1", "transform", "x", 0.5)                 # nothing of the list
        edit.move(p, "c2", 4 * S)                                       # (the timeline is as long as before)
        h = edit.History(p)
        h.do("x", edit.set_param, "c1", "transform", "y", 0.5)
        h.undo()                                                        # (the project's dicts are new ones now)
        panel.set_project(p, [])
        self.assertIs(panel.tree.topLevelItem(1), first)                # the very rows
        self.assertIs(panel.comps, p["compounds"])
        self.assertEqual({k: [(tl, path, c["id"]) for tl, path, c in v] for k, v in panel.uses.items()},
                         {k: [(tl, path, c["id"]) for tl, path, c in v] for k, v in project.compound_uses(p).items()})
        self.assertIs(panel.uses[a["compound_id"]][0][2], edit.find(p, a["id"])[1])   # (and the project's own clips)
        for change in (lambda: edit.move(p, a["id"], 9 * S), lambda: edit.rename_compound(p, a["compound_id"], "新名字"),
                       lambda: edit.delete(p, a["id"]), lambda: edit.delete(p["compounds"][a["compound_id"]], inner["id"])):
            change()
            was = panel.tree.topLevelItem(1)
            panel.set_project(p, [])
            self.assertIsNot(panel.tree.topLevelItem(1), was)
        panel.set_project(p, ["cmp:" + a["compound_id"]])                # another one open (bold): shown anew too
        self.assertTrue(any(panel.tree.topLevelItem(i).font(0).bold() for i in range(panel.tree.topLevelItemCount())))

    def test_holders_of_is_contains(self):
        p = proj()
        a = edit.new_compound(p, p, 3 * S)
        ka = a["compound_id"]
        kb = edit.add_compound(p)
        kc = edit.add_compound(p)
        edit.place_compound(p, p["compounds"][ka], kb, None, 0)         # tl1 > a > b; c alone
        ids = [t["id"] for t in p["timelines"]] + list(p["compounds"])
        for inner in ids:
            self.assertEqual(project.holders_of(p, inner), {o for o in ids if project.contains(p, o, inner)}, inner)
        self.assertEqual(project.holders_of(p, kb), {"tl1", ka, kb})
        self.assertEqual(project.holders_of(p, kc), {kc})


class PanelMenuTests(unittest.TestCase):
    def test_menu_offers_them_all(self):
        panel = CompoundPanel()
        panel.set_project(proj())
        got = []
        panel.createRequested.connect(got.append)
        menu = QMenu()
        panel._create_actions(menu)
        acts = [a for a in menu.actions() if not a.isSeparator()]
        self.assertEqual([a.text() for a in acts], ["新增時間線", "新增複合片段", "新增靜態複合片段", "新增元件", "新增靜態元件"])
        for a in acts:
            a.trigger()
        self.assertEqual(got, ["timeline", "compound", "static", "component", "static_component"])


class ToStaticTests(unittest.TestCase):
    """轉為靜態複合片段: a compound whose clips all start at 0 and are as long as each other."""
    def steady_proj(self):
        p = proj()
        p["tracks"][1]["clips"].append(dict(edit.find(p, "c1")[1], id="c4"))    # 0-2 s, as c1
        c = edit.make_compound(p, p, ["c1", "c4"])
        return p, c["compound_id"]

    def test_steady_one_turns_static(self):
        p, kid = self.steady_proj()
        self.assertTrue(edit.steady(p["compounds"][kid]))
        edit.to_static(p, kid)
        self.assertTrue(p["compounds"][kid]["static"])
        c = next(c for _tl, _p, c in project.compound_uses(p)[kid])
        self.assertTrue(project.is_static(c))
        self.assertEqual(c["duration_us"], 2 * S)              # the clips showing it keep their length
        with self.assertRaises(edit.EditError):                 # (already is)
            edit.to_static(p, kid)

    def test_not_when_lengths_differ_or_sound(self):
        p = proj()
        kid = edit.make_compound(p, p, ["c1", "c2"])["compound_id"]     # 0-2 s and 5-7 s
        self.assertFalse(edit.steady(p["compounds"][kid]))
        with self.assertRaises(edit.EditError):
            edit.to_static(p, kid)
        self.assertFalse(p["compounds"][kid].get("static"))
        p = proj()
        edit.find(p, "c3")[1].update(start_us=0, duration_us=2 * S)
        kid = edit.make_compound(p, p, ["c1", "c3"])["compound_id"]     # same span, but sound
        self.assertFalse(edit.steady(p["compounds"][kid]))

    def test_group_clips_must_last_the_group(self):
        p, kid = self.steady_proj()
        comp = p["compounds"][kid]
        edit.make_group(p, comp, [c["id"] for t in comp["tracks"] for c in t["clips"]])
        self.assertTrue(edit.steady(comp))
        g = next(c for t in comp["tracks"] for c in t["clips"] if project.is_group(c))
        g["tracks"][0]["clips"][0]["duration_us"] = S
        self.assertFalse(edit.steady(comp))

    def test_panel_menu_offers_it_only_when_steady(self):
        p, kid = self.steady_proj()
        other = edit.make_compound(p, p, ["c2"])["compound_id"]
        edit.find(p["compounds"][other], "c2")[1]["start_us"] = S         # starts late
        panel = CompoundPanel()
        panel.set_project(p)
        got = []
        panel.staticRequested.connect(got.append)
        for k, want in ((kid, True), (other, False)):
            menu = QMenu()
            panel._item_actions(menu, ("def", k))
            acts = {a.text(): a for a in menu.actions()}
            self.assertEqual("轉為靜態複合片段" in acts, want)
            if want:
                acts["轉為靜態複合片段"].trigger()
        self.assertEqual(got, [kid])


class FolderTests(unittest.TestCase):
    def test_folders_hold_compounds_and_folders(self):
        p = proj()
        a, b = edit.add_compound(p), edit.add_compound(p)
        outer = edit.add_compound_folder(p, "外")
        inner = edit.add_compound_folder(p, "內", outer)
        edit.move_to_compound_folder(p, a, inner)
        panel = CompoundPanel()
        panel.set_project(p)
        tops = [panel.tree.topLevelItem(i).data(0, 0x0100) for i in range(panel.tree.topLevelItemCount())]
        self.assertEqual([d for d in tops if d[0] == "folder"], [("folder", outer)])
        self.assertIn(("def", b), tops)                                      # (b is outside every folder)
        self.assertNotIn(("def", a), tops)
        folder_row = panel.tree.topLevelItem(next(i for i, d in enumerate(tops) if d[0] == "folder"))
        self.assertEqual(folder_row.child(0).data(0, 0x0100), ("folder", inner))
        self.assertEqual(folder_row.child(0).child(0).data(0, 0x0100), ("def", a))
        with self.assertRaises(edit.EditError):                               # not into itself
            edit.move_to_compound_folder(p, outer, inner)
        edit.rename_compound_folder(p, inner, "新名")
        edit.delete_compound_folder(p, inner)                                 # a moves up into 外
        self.assertEqual(p["compounds"][a]["folder"], outer)
        edit.delete_compound_folder(p, outer)
        self.assertNotIn("folder", p["compounds"][a])
        self.assertNotIn("compound_folders", p)

    def test_menu_and_drop(self):
        p = proj()
        a = edit.add_compound(p)
        f = edit.add_compound_folder(p, "夾")
        panel = CompoundPanel()
        panel.set_project(p)
        got = []
        panel.moveRequested.connect(lambda i, to: got.append((i, to)))
        menu = QMenu()
        panel._item_actions(menu, ("def", a))
        sub = next(x for x in menu.actions() if x.text() == "移到資料夾").menu()
        next(x for x in sub.actions() if "夾" in x.text()).trigger()
        self.assertEqual(got, [(a, f)])


if __name__ == "__main__":
    unittest.main()
