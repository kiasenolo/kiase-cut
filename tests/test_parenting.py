"""parenting.py: 父子綁定 - a clip goes where its parent goes, and binding, letting go and deleting never make it jump."""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import curves, edit, parenting, pathfollow  # noqa: E402

APP = QApplication.instance() or QApplication([])
S, W, H = 1_000_000, 1920, 1080


def keys(*pairs):
    return {"keys": [[t, v, 0.0, 0.0, 0.0, 0.0] for t, v in pairs]}


def clip(cid, start=0, dur=4 * S, **tf):
    t = {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}
    t.update(tf)
    return {"id": cid, "type": "text", "name": cid, "start_us": start, "duration_us": dur, "source_start_us": 0, "transform": t,
            "text": {"content": cid, "size": 8.0}}


def level(*clips):
    return {"width": W, "height": H, "fps": 30, "tracks": [{"id": f"t{i}", "kind": "video", "name": "v", "clips": [c]} for i, c in enumerate(clips)]}


def seen(lv, cid, T):
    return parenting.seen(lv["tracks"], cid, T, W, H)


def baked(lv, cid, T):
    """The numbers the renderer's copy has for clip cid at level time T."""
    view = copy.deepcopy(lv)
    pathfollow.resolve(view)
    c = edit.find(view, cid)[1]
    return parenting.read(c["transform"], T - c["start_us"])


class Parenting(unittest.TestCase):
    def same(self, a, b, places=3, note=""):
        for k in parenting.KEYS:
            self.assertAlmostEqual(a[k], b[k], places, f"{note} {k}: {a} / {b}")

    def test_a_child_moves_turns_and_grows_with_its_parent(self):
        lv = level(clip("p", x=0.5, rotation=90.0, scale=2.0), dict(clip("c", x=0.25), parent="p"))
        got = seen(lv, "c", 0)
        # (0.25 of half the width = 240 px to the right, twice as far and a quarter turn clockwise: 480 px below the parent)
        self.assertAlmostEqual(got["x"], 0.5, 6)
        self.assertAlmostEqual(got["y"], -480 / 540, 6)
        self.assertEqual((got["rotation"], got["scale"]), (90.0, 2.0))
        self.same(baked(lv, "c", 0), got)
        view = copy.deepcopy(lv)
        self.assertTrue(pathfollow.has_followers(view))
        pathfollow.resolve(view)
        self.assertNotIn("parent", edit.find(view, "c")[1])
        self.assertFalse(pathfollow.resolve(view))                              # (a second pass leaves it alone)

    def test_a_moving_parent_takes_it_along_frame_by_frame_at_the_same_time_of_the_timeline(self):
        lv = level(clip("p", x=keys((0, 0.0), (2 * S, 1.0))), dict(clip("c", start=S, y=0.5), parent="p"))
        for T in (S, int(1.5 * S), 3 * S):
            got = baked(lv, "c", T)
            self.assertAlmostEqual(got["x"], min(T / (2 * S), 1.0), 3)           # (the parent's time, not the child's)
            self.assertAlmostEqual(got["y"], 0.5, 6)

    def test_binding_and_letting_go_leave_it_where_it_is(self):
        for parent in (clip("p", x=0.3, y=-0.2, rotation=30.0, scale=1.5),
                       clip("p", x=0.3, z=0.4, rot_x=20.0, rot_y=-35.0, rotation=10.0, scale=0.7),
                       clip("p", x=-0.4, pivot_x=0.3, rotation=45.0, scale=2.0),
                       dict(clip("p", x=0.2, rotation=15.0), transform={"x": 0.2, "y": 0.0, "scale": 1.0, "rotation": 15.0, "flip_h": True})):
            lv = level(parent, clip("c", x=-0.5, y=0.4, rotation=20.0, scale=0.8))
            before = seen(lv, "c", S)
            edit.set_parent(lv, "c", "p", S)
            c = edit.find(lv, "c")[1]
            self.assertEqual(c["parent"], "p")
            self.same(seen(lv, "c", S), before, 4, "bound")
            self.assertEqual((seen(lv, "c", S)["flip_h"], seen(lv, "c", S)["flip_v"]), (False, False))
            edit.set_parent(lv, "c", None, S)
            self.assertNotIn("parent", c)
            self.same(seen(lv, "c", S), before, 4, "let go")

    def test_keyframes_keep_their_path_when_bound(self):
        eased = {"keys": [[0, 0.0, 0.0, 0.0, 500000, 0.0], [2 * S, 1.0, -500000, 0.0, 0.0, 0.0]]}
        for turn in (0.0, 40.0):
            lv = level(clip("p", x=0.2, y=0.1, scale=2.0, rotation=turn), clip("c", x=copy.deepcopy(eased), rotation=keys((0, 0.0), (2 * S, 90.0))))
            before = [seen(lv, "c", T) for T in (0, S // 2, 2 * S)]
            edit.set_parent(lv, "c", "p", 0)
            c = edit.find(lv, "c")[1]
            for T, was in zip((0, S // 2, 2 * S), before):
                if turn == 0.0 or T in (0, 2 * S):                              # (a turn mixes x and y: straight between the keys)
                    self.same(seen(lv, "c", T), was, 3, f"turn {turn} at {T}")
            self.assertTrue(curves.is_animated(c["transform"]["x"]))
            if turn == 0.0:
                self.assertEqual(c["transform"]["x"]["keys"][0][4], 500000)     # (the easing stays)
                self.assertNotIn("scale_y", c["transform"])                     # (still linked)

    def test_a_chain_and_no_ring(self):
        lv = level(clip("a", x=0.1), dict(clip("b", x=0.2), parent="a"), dict(clip("c", x=0.3), parent="b"), clip("d"))
        self.assertAlmostEqual(seen(lv, "c", 0)["x"], 0.6, 6)
        self.assertEqual([k for k, _c in parenting.candidates(lv["tracks"], "a")], ["d"])
        with self.assertRaises(edit.EditError):
            edit.set_parent(lv, "a", "c", 0)
        edit.find(lv, "a")[1]["parent"] = "c"                                   # (a ring in a broken file: no hang)
        seen(lv, "c", 0)
        pathfollow.resolve(copy.deepcopy(lv))

    def test_what_is_dragged_on_the_canvas_becomes_the_childs_own_numbers(self):
        for parent in (clip("p", x=0.3, rotation=30.0, scale=2.0), clip("p", rot_y=40.0, z=0.2)):
            lv = level(parent, dict(clip("c", x=0.1, y=0.1), parent="p"))
            wanted = {"x": -0.25, "y": 0.5}
            own = parenting.to_local(lv["tracks"], "c", 0, wanted, W, H)
            edit.find(lv, "c")[1]["transform"].update(own)
            got = seen(lv, "c", 0)
            self.assertAlmostEqual(got["x"], -0.25, 5)
            self.assertAlmostEqual(got["y"], 0.5, 5)
        lv = level(clip("p", scale=2.0), dict(clip("c"), parent="p"))
        own = parenting.to_local(lv["tracks"], "c", 0, {"scale": 3.0}, W, H)
        self.assertEqual(own, {"scale": 1.5})
        lone = level(clip("a"))
        wanted = {"x": 0.5}
        self.assertIs(parenting.to_local(lone["tracks"], "a", 0, wanted, W, H), wanted)

    def test_deleting_the_parent_leaves_the_child_where_it_is(self):
        for remove in (lambda lv: edit.delete(lv, "p"), lambda lv: edit.delete_many(lv, ["p"]), lambda lv: edit.ripple_delete(lv, ["p"])):
            lv = level(clip("p", x=0.5, rotation=90.0, scale=2.0), dict(clip("c", x=0.25), parent="p"))
            before = seen(lv, "c", 0)
            remove(lv)
            c = edit.find(lv, "c")[1]
            self.assertNotIn("parent", c)
            self.same(seen(lv, "c", 0), before, 4)

    def test_copies_of_both_are_bound_to_each_other_and_copies_of_one_to_the_original_parent(self):
        lv = level(clip("p"), dict(clip("c", x=0.25), parent="p"))
        root = {"tracks": lv["tracks"], "compounds": {}, "timelines": [], "width": W, "height": H}
        both = edit.paste_clips(root, lv, edit.copy_clips(lv, ["p", "c"]), 5 * S)
        by = {c["name"]: c for c in both}
        self.assertEqual(by["c"]["parent"], by["p"]["id"])
        (one,) = edit.paste_clips(root, lv, edit.copy_clips(lv, ["c"]), 10 * S)
        self.assertEqual(one["parent"], "p")

    def test_the_inspector_picks_a_parent_and_the_window_turns_a_drag_into_the_childs_numbers(self):
        import types
        from kiasecut.ui.inspector import Inspector
        from kiasecut.ui.main_window import MainWindow
        lv = level(clip("p", x=0.5, scale=2.0), dict(clip("c", x=0.1), parent="p"))
        child = edit.find(lv, "c")[1]
        inspector = Inspector()
        inspector.set_parent_choices([("p", "爸爸")])
        picked = []
        inspector.parentChosen.connect(lambda ids, pid: picked.append((ids, pid)))
        inspector.show_clip(child, 0, 30)
        box = inspector.widgets["parent"]
        self.assertEqual((box.currentData(), [box.itemData(i) for i in range(box.count())]), ("p", [None, "p"]))
        box.activated.emit(0)
        self.assertEqual(picked, [(["c"], None)])
        h = types.SimpleNamespace(proj={"width": W, "height": H}, level_names=lambda level_, cid: {})
        own = MainWindow.own_numbers(h, lv, "c", 0, {"x": 0.9})                  # (seen 0.4 right of the parent, twice as big: 0.2)
        self.assertAlmostEqual(own["x"], 0.2, 6)
        self.assertEqual(set(own), {"x"})


if __name__ == "__main__":
    unittest.main()
