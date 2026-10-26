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
        edit.trim_end(p, "c4", 99 * S)
        self.assertLessEqual(edit.end(c4), g["duration_us"])
        edit.trim_end(p, g["id"], S)                                        # a group never cuts its clips
        self.assertEqual(g["duration_us"], 4 * S)
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
            img = r.render(self.view({"on": True, "show": False}, gx=1.0), 0, 64, 36)   # the group moved right
            self.assertEqual(rgb(img, 12, 18), (0, 0, 0), name)
            self.assertEqual(rgb(img, 40, 18), (255, 0, 0), name)


if __name__ == "__main__":
    unittest.main()
