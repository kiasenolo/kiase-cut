"""路徑跟隨: clips move along a shape / pen path clip, by progress, as the path clip is placed."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import assets, edit, pathfollow, project  # noqa: E402
from test_edit import S, clip  # noqa: E402

APP = QApplication.instance() or QApplication([])
US = 1_000_000


def scene():
    """A horizontal line path from canvas (460, 540) to (1460, 540) (a 1000 px wide pen path at the centre-left) and a follower."""
    p = project.new()
    path = clip("path", 0, 5 * US)
    params, (cx, cy) = assets.path_params([{"nodes": [[0, 0, 0, 0, 0, 0], [1000, 0, 0, 0, 0, 0]], "closed": False}])
    path["asset"] = params
    path["transform"].update(scale=1.0, x=(960 - 960) / 960, y=0.0)
    follower = clip("fol", 0, 5 * US)
    p["tracks"] = [{"id": "t1", "kind": "video", "name": "v", "clips": [follower]}, {"id": "t2", "kind": "video", "name": "v", "clips": [path]}]
    return project.link(p), follower, path


class Follow(unittest.TestCase):
    def test_progress_places_the_clip_on_the_path(self):
        p, f, path = scene()
        edit.set_path_follow(p, "fol", "path")
        self.assertEqual((f["transform"]["x"], f["transform"]["y"]), (0.0, 0.0))
        for prog, want in ((0.0, 460), (0.5, 960), (1.0, 1460)):
            f["transform"]["path_progress"] = prog
            view = pathfollow.resolved(p)
            x = view["tracks"][0]["clips"][0]["transform"]["x"]
            self.assertAlmostEqual(960 + x * 960, want, delta=0.5)
        self.assertEqual(f["transform"]["path_id"], "path")          # (the project itself is not touched)

    def test_keyframed_progress_and_a_moving_path(self):
        p, f, path = scene()
        edit.set_path_follow(p, "fol", "path")
        f["transform"]["path_progress"] = {"keys": [[0, 0.0, 0.0, 0.0, 0.0, 0.0], [4 * US, 1.0, 0.0, 0.0, 0.0, 0.0]]}
        path["transform"]["y"] = 0.5
        view = pathfollow.resolved(p)
        tf = view["tracks"][0]["clips"][0]["transform"]
        self.assertTrue(isinstance(tf["x"], dict) and len(tf["x"]["keys"]) > 10)
        from kiasecut import curves
        self.assertAlmostEqual(960 + curves.value(tf["x"], 2 * US) * 960, 960, delta=3)
        self.assertAlmostEqual(curves.value(tf["y"], 0), 0.5, delta=0.01)

    def test_stop_and_bad_targets(self):
        p, f, path = scene()
        edit.set_path_follow(p, "fol", "path")
        edit.set_path_follow(p, "fol", None)
        self.assertNotIn("path_id", f["transform"])
        with self.assertRaises(edit.EditError):
            edit.set_path_follow(p, "path", "path")
        self.assertFalse(pathfollow.has_followers(p))

    def test_resolve_is_for_copies_and_runs_once(self):
        p, f, path = scene()
        edit.set_path_follow(p, "fol", "path")
        f["transform"]["x"] = 0.1                                    # an offset from the path
        import copy
        q = copy.deepcopy(p)
        self.assertTrue(pathfollow.resolve(q))
        x = q["tracks"][0]["clips"][0]["transform"]["x"]
        self.assertFalse(pathfollow.resolve(q))
        self.assertEqual(q["tracks"][0]["clips"][0]["transform"]["x"], x)
        self.assertAlmostEqual(x, (460 - 960) / 960 + 0.1, delta=0.001)


class TextOnPath(unittest.TestCase):
    def test_text_gets_the_polyline_and_the_middle(self):
        p, f, path = scene()
        t = clip("txt", 0, 5 * US)
        t["type"] = "text"
        t["text"] = {"content": "Hello", "size": 5.0}
        p["tracks"][0]["clips"].append(t)
        edit.set_text_path(p, "txt", "path")
        self.assertEqual(t["text"]["on_path"], "path")
        view = pathfollow.resolved(p)
        c = view["tracks"][0]["clips"][1]
        pts = c["text"]["path_pts"]
        self.assertAlmostEqual(pts[0][0], -500, delta=0.5)           # (the line is 1000 px wide, its middle at the centre)
        self.assertAlmostEqual(pts[-1][0], 500, delta=0.5)
        self.assertAlmostEqual(c["transform"]["x"], 0.0, delta=0.001)
        from kiasecut import textlayout
        im = textlayout.render(dict(c["text"], font_path=None) if False else c["text"], 1.0, 1080)
        self.assertGreater(im.width, 1000)
        edit.set_text_path(p, "txt", None)
        self.assertFalse(pathfollow.has_followers(p))


if __name__ == "__main__":
    unittest.main()
