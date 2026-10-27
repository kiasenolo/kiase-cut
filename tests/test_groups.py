"""Groups (群組): clips put together on tracks of their own inside one clip; they keep their
places when the group is made or moved, and come back out where they were."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kiasecut import edit, project  # noqa: E402
from test_edit import S, clip, proj  # noqa: E402


def scene():
    p = proj()                                   # t0: c1 0-2, c2 5-7; t1 empty; t2 audio c3
    p["tracks"][1]["clips"].append(clip("c4", S, 3 * S))
    return p


class GroupTests(unittest.TestCase):
    def test_anchor_keeps_places(self):
        p = scene()
        edit.find(p, "c1")[1]["transform"].update(x=0.5, y=0.2)        # the bottom object
        edit.find(p, "c4")[1]["transform"].update(x=0.1)
        g = edit.make_group(p, p, ["c1", "c4"])
        edit.set_group_anchor(p, g["id"], True)
        c4 = edit.find(p, "c4")[1]
        self.assertEqual((round(c4["transform"]["x"], 6), round(c4["transform"]["y"], 6)), (-0.4, -0.2))
        self.assertEqual(edit.find(p, "c1")[1]["transform"]["x"], 0.5)   # (the bottom one stays as it is)
        edit.set_param(p, "c1", "transform", "x", 0.7)                  # it carries c4 along
        ct = edit.find(p, "c4")[0]
        self.assertEqual(tuple(round(v, 6) for v in project.anchored(g, ct, S)), (0.7, 0.2))
        edit.ungroup(p, p, g["id"])                                       # folded back in
        self.assertEqual(round(c4["transform"]["x"], 6), 0.3)
        self.assertEqual(round(c4["transform"]["y"], 6), 0.0)
        g = edit.make_group(p, p, ["c1", "c4"])
        edit.set_group_anchor(p, g["id"], True)
        edit.set_group_anchor(p, g["id"], False)                          # and off again: the same place
        self.assertEqual(round(c4["transform"]["x"], 6), 0.3)
        edit.set_group_anchor(p, g["id"], True)
        edit.find(p, "c2")[1]["transform"].update(x=0.9)
        edit.move_into_group(p, p, ["c2"], g["id"])                       # in: from the bottom one's centre
        c2t, c2 = edit.find(p, "c2")
        self.assertAlmostEqual(c2["transform"]["x"] + project.anchored(g, c2t, c2["start_us"])[0], 0.9)

    def test_ungroup_many(self):
        p = scene()
        g1 = edit.make_group(p, p, ["c1", "c4"])
        g2 = edit.make_group(p, p, ["c2"])
        outer = edit.make_group(p, p, [g2["id"]])                          # (a group in a group)
        out = edit.ungroup_many(p, p, [g2["id"], outer["id"], g1["id"]])   # (inner one listed first)
        self.assertEqual(sorted(k["id"] for k in out), ["c1", "c2", "c4"])
        self.assertFalse(any(project.is_group(c) for c in project.walk_clips(p["tracks"])))
        self.assertEqual((edit.abs_start(p, "c2"), edit.abs_start(p, "c4")), (5 * S, S))

    def test_starts_in_one_pass(self):
        p = scene()
        g = edit.make_group(p, p, ["c1", "c4"])
        outer = edit.make_group(p, p, [g["id"]])                           # (a group in a group)
        edit.move(p, outer["id"], 10 * S)
        starts = edit.abs_starts(p)
        self.assertEqual(starts, {k: edit.abs_start(p, k) for k in starts})
        self.assertEqual((starts["c1"], starts["c4"], starts["c2"]), (10 * S, 11 * S, 5 * S))
        self.assertEqual([c["id"] for _, c in edit.find_all(p, ["c4", "c2", "c1"])], ["c4", "c2", "c1"])
        self.assertIs(edit.find_all(p, ["c4"])[0][0], edit.find(p, "c4")[0])
        with self.assertRaises(edit.EditError):
            edit.find_all(p, ["c1", "nope"])
        with self.assertRaises(edit.EditError):
            edit.abs_start(p, "nope")

    def test_trim_past_the_group_grows_it(self):
        p = scene()
        g = edit.make_group(p, p, ["c1", "c4"])                          # 0-4, alone on t1
        edit.move(p, g["id"], 2 * S)                                     # 2-6
        edit.trim_end(p, "c4", 6 * S)                                    # c4 1-4 -> 1-6 (group time)
        self.assertEqual((g["start_us"], g["duration_us"]), (2 * S, 6 * S))
        self.assertEqual(edit.find(p, "c4")[1]["duration_us"], 5 * S)
        edit.trim_start(p, "c1", -S)                                     # one second before the group
        self.assertEqual((g["start_us"], g["duration_us"]), (S, 7 * S))
        self.assertEqual((edit.abs_start(p, "c1"), edit.abs_start(p, "c4")), (S, 3 * S))   # c4 stays put
        self.assertEqual(edit.find(p, "c1")[1]["duration_us"], 3 * S)
        p["tracks"][1]["clips"].insert(0, clip("c9", 0, S // 2))         # a neighbour stops the group
        edit.trim_start(p, "c1", -S)
        self.assertEqual(g["start_us"], S // 2)
        self.assertEqual(edit.abs_start(p, "c1"), S // 2)

    def test_make_and_ungroup(self):
        p = scene()
        g = edit.make_group(p, p, ["c1", "c4"])
        self.assertEqual((g["start_us"], g["duration_us"]), (0, 4 * S))
        self.assertEqual([[k["id"] for k in t["clips"]] for t in g["tracks"]], [["c1"], ["c4"]])   # bottom first
        self.assertEqual(edit.find(p, "c4")[1]["start_us"], S)            # (relative to the group: same)
        self.assertEqual(edit.abs_start(p, "c4"), S)
        edit.move(p, g["id"], 10 * S)
        self.assertEqual(edit.abs_start(p, "c4"), 11 * S)                  # moved with it
        self.assertEqual([c["id"] for c in project.walk_clips(p["tracks"])].count("c4"), 1)
        out = edit.ungroup(p, p, g["id"])
        self.assertEqual(sorted(c["id"] for c in out), ["c1", "c4"])
        self.assertEqual(edit.find(p, "c4")[1]["start_us"], 11 * S)
        self.assertEqual(edit.find(p, "c1")[1]["start_us"], 10 * S)
        with self.assertRaises(edit.EditError):
            edit.find(p, g["id"])

    def test_sound_is_refused(self):
        p = scene()
        with self.assertRaises(edit.EditError):
            edit.make_group(p, p, ["c1", "c3"])

    def test_clips_stay_inside(self):
        p = scene()
        g = edit.make_group(p, p, ["c1", "c4"])
        edit.move(p, "c4", 10 * S)                                          # past the group's end
        c4 = edit.find(p, "c4")[1]
        self.assertEqual(edit.end(c4), g["duration_us"])
        edit.trim_end(p, "c4", 6 * S)                                       # (longer: the group grows with it)
        self.assertEqual(edit.end(c4), g["duration_us"])
        self.assertEqual(g["duration_us"], 6 * S)
        edit.trim_end(p, g["id"], S)                                        # a group never cuts its clips
        self.assertEqual(g["duration_us"], 6 * S)
        edit.trim_start(p, g["id"], -3 * S)                                 # longer to the left: clips stay
        self.assertEqual(edit.abs_start(p, "c1"), 0)

    def test_split(self):
        p = scene()
        g = edit.make_group(p, p, ["c1", "c4"])
        right = edit.split(p, g["id"], 1.5 * S)
        self.assertEqual((g["duration_us"], right["start_us"]), (1.5 * S, 1.5 * S))
        left_ids = {k["id"] for t in g["tracks"] for k in t["clips"]}
        right_ids = {k["id"] for t in right["tracks"] for k in t["clips"]}
        self.assertEqual(left_ids, {"c1", "c4"})
        self.assertEqual(len(right_ids), 2)                                 # both were across 1.5 s
        self.assertFalse(left_ids & right_ids)
        self.assertEqual(sorted(edit.abs_start(p, k) for k in right_ids), [int(1.5 * S)] * 2)

    def test_copy_gets_new_ids(self):
        p = scene()
        g = edit.make_group(p, p, ["c1", "c4"])
        new = edit.duplicate_clips(p, p, [g["id"]])
        inner = [k["id"] for t in new[0]["tracks"] for k in t["clips"]]
        self.assertNotIn("c1", inner)
        self.assertEqual(len(set(c["id"] for c in project.walk_clips(p["tracks"]))),
                         len(list(project.walk_clips(p["tracks"]))))

    def test_ungroup_folds_the_transform(self):
        p = scene()
        g = edit.make_group(p, p, ["c1"])
        g["transform"].update(x=0.5, scale=2.0, opacity=0.5)
        edit.find(p, "c1")[1]["transform"].update(x=0.1)
        edit.ungroup(p, p, g["id"])
        tf = edit.find(p, "c1")[1]["transform"]
        self.assertAlmostEqual(tf["x"], 0.7)
        self.assertEqual((tf["scale"], tf["opacity"]), (2.0, 0.5))
        g = edit.make_group(p, p, ["c1"])
        g["transform"]["rotation"] = 10.0
        with self.assertRaises(edit.EditError):
            edit.ungroup(p, p, g["id"])

    def test_saved_and_loaded(self):
        import tempfile
        p = scene()
        p["tracks"][0]["clips"][0]["media"]["path"] = "/x/Media/a.png"
        g = edit.make_group(p, p, ["c1", "c4"])
        d = tempfile.mkdtemp()
        path = os.path.join(d, "g.kiasecut.json")
        project.save(p, path)
        back = project.load(path)
        self.assertEqual(edit.find(back, "c1")[1]["media"]["path"], "/x/Media/a.png")
        self.assertTrue(project.is_group(edit.find(back, g["id"])[1]))


class GroupRenderTests(unittest.TestCase):
    """A group draws its clips as one layer; with its matte on, the bottom clip cuts the rest."""

    @classmethod
    def setUpClass(cls):
        import shutil, tempfile                                             # noqa: E401
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        from test_compound_mask import Scene
        cls.dir = tempfile.mkdtemp()
        cls.s = Scene(cls.dir)
        cls.cleanup = lambda: shutil.rmtree(cls.dir, ignore_errors=True)

    @classmethod
    def tearDownClass(cls):
        cls.cleanup()

    def view(self, matte=None, gx=0.0):
        from test_compound_mask import Scene  # noqa: F401
        bottom = self.s.pic("cut", self.s.alpha)            # left half opaque
        top = self.s.pic("top", self.s.red)
        g = {"id": "g", "type": "group", "name": "g", "start_us": 0, "duration_us": 2 * S, "source_start_us": 0,
             "tracks": [{"id": "a", "kind": "video", "name": "a", "clips": [bottom]},
                        {"id": "b", "kind": "video", "name": "b", "clips": [top]}],
             "matte": matte or {"on": False, "show": False},
             "transform": {"x": gx, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}}
        return {"width": 1920, "height": 1080, "fps": 30, "duration_us": 2 * S, "compounds": {},
                "tracks": [{"id": "t0", "kind": "video", "name": "v", "clips": [g]}]}

    def renderers(self):
        from kiasecut import glrender, render
        from test_compound_mask import HAVE_GL
        return [render.Renderer()] + ([glrender.GLRenderer()] if HAVE_GL else [])

    def test_group_and_matte(self):
        from test_compound_mask import rgb
        for r in self.renderers():
            name = type(r).__name__
            img = r.render(self.view(), 0, 64, 36)
            self.assertEqual(r.errors, [], name)
            self.assertEqual(rgb(img, 52, 18), (255, 0, 0), name)              # the red one on top, all over
            img = r.render(self.view({"on": True, "show": False}), 0, 64, 36)
            self.assertEqual(rgb(img, 12, 18), (255, 0, 0), name)              # red where the cut is opaque
            self.assertEqual(rgb(img, 52, 18), (0, 0, 0), name)                # nothing where it is clear
            img = r.render(self.view({"on": True, "show": False, "invert": True}), 0, 64, 36)   # 反轉遮罩
            self.assertEqual(rgb(img, 12, 18), (0, 0, 0), name)                # cut out where it is opaque
            self.assertEqual(rgb(img, 52, 18), (255, 0, 0), name)              # kept where it is clear
            img = r.render(self.view({"on": True, "show": True, "body": False}), 0, 64, 36)   # 顯示主體 off
            self.assertEqual(rgb(img, 12, 18), (255, 255, 255), name)          # only the (white) mask object
            self.assertEqual(rgb(img, 52, 18), (0, 0, 0), name)
            img = r.render(self.view({"on": True, "show": False}, gx=1.0), 0, 64, 36)   # the group moved right
            self.assertEqual(rgb(img, 12, 18), (0, 0, 0), name)
            self.assertEqual(rgb(img, 40, 18), (255, 0, 0), name)

    def test_anchor_follows_the_bottom_object(self):
        """中心點跟隨最下層物件: the clips above count their x / y from the bottom one's centre."""
        from test_compound_mask import rgb
        for r in self.renderers():
            name = type(r).__name__
            for matte in (None, {"on": True, "show": True}):
                v = self.view(matte)
                g = v["tracks"][0]["clips"][0]
                bottom, top = g["tracks"][0]["clips"][0], g["tracks"][1]["clips"][0]
                bottom["transform"].update(x=0.5, scale=0.3)       # (opaque on its left: under the red)
                top["transform"].update(scale=0.1)
                if matte is None:                                  # (with the mask, cut off there)
                    img = r.render(v, 0, 64, 36)
                    self.assertEqual(rgb(img, 32, 18), (255, 0, 0), name)          # off: the canvas centre
                g["anchor"] = True
                img = r.render(v, 0, 64, 36)
                self.assertEqual(r.errors, [], name)
                self.assertEqual(rgb(img, 46, 18), (255, 0, 0), (name, matte))     # on: by the bottom one's centre
                self.assertNotEqual(rgb(img, 32, 18), (255, 0, 0), (name, matte))

    def test_mask_object_grouped(self):
        """The mask object can be a group: grouping its clips (on two tracks) leaves the bottom
        track empty, and that one does not count."""
        from test_compound_mask import rgb
        for r in self.renderers():
            name = type(r).__name__
            v = self.view({"on": True, "show": False})
            g = v["tracks"][0]["clips"][0]
            g["tracks"].insert(1, {"id": "a2", "kind": "video", "name": "a2", "clips": [self.s.pic("cut2", self.s.alpha)]})
            inner = edit.make_group(v, v, [g["tracks"][0]["clips"][0]["id"], "cut2"])
            self.assertEqual(g["tracks"][0]["clips"], [], name)               # (left empty below it)
            self.assertIs(project.matte_tracks(g["tracks"])[0]["clips"][0], inner, name)
            img = r.render(v, 0, 64, 36)
            self.assertEqual(r.errors, [], name)
            self.assertEqual(rgb(img, 12, 18), (255, 0, 0), name)              # red where the group is opaque
            self.assertEqual(rgb(img, 52, 18), (0, 0, 0), name)

    def test_blend_modes_mix_with_the_shown_mask_object(self):
        """As Photoshop's clipping masks: the clips above are drawn on the shown mask object."""
        from test_compound_mask import rgb
        for r in self.renderers():
            name = type(r).__name__
            for blend, left in (("normal", (255, 0, 0)), ("screen", (255, 255, 255)), ("multiply", (255, 0, 0))):
                v = self.view({"on": True, "show": True})
                v["tracks"][0]["clips"][0]["tracks"][1]["clips"][0]["blend"] = blend
                img = r.render(v, 0, 64, 36)
                self.assertEqual(r.errors, [], name)
                self.assertEqual(rgb(img, 12, 18), left, (name, blend))      # red on the white mask object
                self.assertEqual(rgb(img, 52, 18), (0, 0, 0), (name, blend))  # nothing where it is clear
                v = self.view({"on": True, "show": True, "invert": True})
                v["tracks"][0]["clips"][0]["tracks"][1]["clips"][0]["blend"] = blend
                img = r.render(v, 0, 64, 36)
                self.assertEqual(rgb(img, 12, 18), (255, 255, 255), (name, blend))   # cut out: the mask object
                self.assertEqual(rgb(img, 52, 18), (255, 0, 0), (name, blend))       # kept (nothing under it)
            v = self.view({"on": True, "show": True})
            v["tracks"][0]["clips"][0]["tracks"][1]["clips"][0]["transform"]["opacity"] = 0.5
            img = r.render(v, 0, 64, 36)
            self.assertEqual(rgb(img, 12, 18)[0], 255, name)                  # half red on white
            self.assertAlmostEqual(rgb(img, 12, 18)[1], 128, delta=2)

    def through(self, matte=None, blend="pass_through", opacity=1.0):
        """A group whose red clip is set to screen, over a blue picture."""
        v = self.view(matte)
        g = v["tracks"][0]["clips"][0]
        g["blend"] = blend
        g["transform"]["opacity"] = opacity
        g["tracks"][1]["clips"][0]["blend"] = "screen"
        if not (matte or {}).get("on"):
            g["tracks"] = g["tracks"][1:]                                   # the red one alone
        v["tracks"].insert(0, {"id": "t9", "kind": "video", "name": "bg", "clips": [self.s.pic("bg", self.s.blue)]})
        return v

    def test_pass_through(self):
        """穿透: the group's clips mix with what is under the group, as in Photoshop."""
        from test_compound_mask import rgb
        magenta, blue = (255, 0, 255), (0, 0, 255)
        for r in self.renderers():
            name = type(r).__name__
            img = r.render(self.through(blend="normal"), 0, 64, 36)
            self.assertEqual(r.errors, [], name)
            self.assertEqual(rgb(img, 52, 18), (255, 0, 0), name)             # a group of its own: on nothing
            img = r.render(self.through(), 0, 64, 36)
            self.assertEqual(r.errors, [], name)
            self.assertEqual(rgb(img, 12, 18), magenta, name)                 # red screened on the blue
            self.assertEqual(rgb(img, 52, 18), magenta, name)
            img = r.render(self.through(opacity=0.5), 0, 64, 36)
            self.assertAlmostEqual(rgb(img, 52, 18)[0], 128, delta=2, msg=name)   # halfway from the blue
            self.assertEqual(rgb(img, 52, 18)[2], 255, name)
            img = r.render(self.through({"on": True, "show": True}), 0, 64, 36)
            self.assertEqual(rgb(img, 12, 18), (255, 255, 255), name)         # screened on the white mask object
            self.assertEqual(rgb(img, 52, 18), blue, name)                    # cut away: the blue under it
            img = r.render(self.through({"on": True, "show": False}), 0, 64, 36)
            self.assertEqual(rgb(img, 12, 18), magenta, name)                 # screened on the blue
            self.assertEqual(rgb(img, 52, 18), blue, name)
            img = r.render(self.through({"on": True, "show": False, "invert": True}), 0, 64, 36)
            self.assertEqual(rgb(img, 12, 18), blue, name)
            self.assertEqual(rgb(img, 52, 18), magenta, name)
            v = self.through()
            v["tracks"][1]["clips"][0]["mask"] = {"kind": "rectangle", "invert": False, "cx": -0.5, "cy": 0.0,
                                                  "w": 0.5, "h": 1.0, "rotation": 0.0, "feather": 0.0}
            img = r.render(v, 0, 64, 36)                                       # the group's mask: its left half
            self.assertEqual(rgb(img, 12, 18), magenta, name)
            self.assertEqual(rgb(img, 52, 18), blue, name)

    def test_only_groups_pass_through(self):
        from kiasecut.ui.inspector import Inspector
        v = self.through()
        edit.set_param(v, "g", "clip", "blend", "pass_through")
        with self.assertRaises(edit.EditError):
            edit.set_param(v, "bg", "clip", "blend", "pass_through")
        ins = Inspector()
        ins.show_clips([edit.find(v, "g")[1]], 0, 30)
        self.assertEqual(ins.widgets["blend"].itemData(0), "pass_through")
        self.assertEqual(ins.widgets["blend"].currentData(), "pass_through")
        ins.show_clips([edit.find(v, "bg")[1]], 0, 30)
        self.assertEqual(ins.widgets["blend"].findData("pass_through"), -1)


class RenameTests(unittest.TestCase):
    def test_rename_the_selection(self):
        """重新命名 with several clips selected: all of them get the one name."""
        from types import SimpleNamespace
        from kiasecut.ui import inplace, main_window
        p = scene()
        tl = SimpleNamespace(selected_ids={"c1", "c2"}, clip_label=lambda c: c["name"])
        win = SimpleNamespace(timeline=tl, container=lambda root=None: p, clip_anchor=lambda cid: None,
                              apply_each=lambda label, fn, ids, *a: [fn(p, k, *a) for k in ids])
        ask, inplace.ask_name = inplace.ask_name, lambda *a: ("片頭", True)
        try:
            main_window.MainWindow.on_clip_action(win, "rename", "c1")
            self.assertEqual([edit.find(p, k)[1]["name"] for k in ("c1", "c2", "c4")], ["片頭", "片頭", "c4"])
            main_window.MainWindow.on_clip_action(win, "rename", "c4")       # (not in the selection: only it)
            self.assertEqual([edit.find(p, k)[1]["name"] for k in ("c1", "c4")], ["片頭", "片頭"])
            inplace.ask_name = lambda *a: ("x", False)                        # (cancelled: nothing)
            main_window.MainWindow.on_clip_action(win, "rename", "c2")
            self.assertEqual(edit.find(p, "c2")[1]["name"], "片頭")
        finally:
            inplace.ask_name = ask


class GroupPreviewTests(unittest.TestCase):
    def test_selected_group_is_dragged_from_its_empty_space(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from kiasecut.ui.preview import Preview
        QApplication.instance() or QApplication([])
        p = scene()
        for cid, x in (("c1", -0.6), ("c4", 0.6)):
            edit.find(p, cid)[1]["transform"].update(scale=0.1, x=x)
        g = edit.make_group(p, p, ["c1", "c4"])
        pv = Preview()
        pv.resize(960, 540)
        moved = []
        pv.paramsCommitted.connect(lambda cid, group, vals: moved.append((cid, vals)))
        at = lambda cx, cy: QPoint(round(pv._rect().x() + cx / 2), round(pv._rect().y() + cy / 2))
        pv.set_scene(p, 1500_000, None)
        QTest.mousePress(pv, Qt.LeftButton, Qt.NoModifier, at(960, 540))      # nothing there yet: no group
        QTest.mouseRelease(pv, Qt.LeftButton, Qt.NoModifier, at(960, 540))
        self.assertIsNone(pv.selected_id)
        pv.set_scene(p, 1500_000, g["id"])
        QTest.mousePress(pv, Qt.LeftButton, Qt.NoModifier, at(960, 540))      # between its clips
        for i in range(1, 6):
            QTest.mouseMove(pv, at(960 + 40 * i, 540))
        l0, r0, _, _ = pv._live_box().extents()                             # its clips, not the canvas
        self.assertGreater(r0 - l0, 0)
        self.assertLess(r0 - l0, 1800)
        QTest.mouseRelease(pv, Qt.LeftButton, Qt.NoModifier, at(1160, 540))
        self.assertEqual(moved[-1][0], g["id"])
        self.assertGreater(moved[-1][1]["x"], 0.1)

    def test_dragged_group_box_keeps_to_its_clips(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from kiasecut.ui.preview import Preview
        QApplication.instance() or QApplication([])
        p = scene()
        for cid, x in (("c1", -0.3), ("c4", 0.3)):
            edit.find(p, cid)[1]["transform"].update(scale=0.1, x=x)
        g = edit.make_group(p, p, ["c1", "c4"])
        pv = Preview()
        pv.resize(960, 540)
        at = lambda cx, cy: QPoint(round(pv._rect().x() + cx / 2), round(pv._rect().y() + cy / 2))
        pv.set_scene(p, 1500_000, g["id"])
        l0, r0, t0, b0 = pv._live_box().extents()
        QTest.mousePress(pv, Qt.LeftButton, Qt.NoModifier, at(960, 540))
        for i in range(1, 6):
            QTest.mouseMove(pv, at(960 + 20 * i, 540 + 10 * i))
        l1, r1, t1, b1 = pv._live_box().extents()                           # while dragging
        self.assertAlmostEqual(r1 - l1, r0 - l0, delta=1)
        self.assertAlmostEqual(b1 - t1, b0 - t0, delta=1)
        self.assertGreater(l1, l0)
        QTest.mouseRelease(pv, Qt.LeftButton, Qt.NoModifier, at(1060, 590))


if __name__ == "__main__":
    unittest.main()
