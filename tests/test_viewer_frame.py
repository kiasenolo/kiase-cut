"""A 預覽 node on a picture node: while the node editor is in front, the preview draws the clip moved and scaled so that picture fills the
canvas (in the view only), however the clip is placed."""
import copy
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, fx, nodegraph as ng  # noqa: E402
from kiasecut.ui.main_window import MainWindow  # noqa: E402
from test_edit import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


class ViewerFrame(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.e = edit.add_effect(self.p, "c1", fx.GRAPH)
        self.nid = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "source", "kind": "image"})
        edit.set_effect_source_media(self.p, "c1", self.e["id"], self.nid, image=("/a/b.png", 100, 100))
        edit.set_param(self.p, "c1", "transform", "x", 7.0)
        self.src = self.e["sources"][self.nid]

    def framed(self, active=True):
        v = {"width": 1920, "height": 1080, "tracks": copy.deepcopy(self.p["tracks"])}
        me = types.SimpleNamespace(panels=types.SimpleNamespace(is_active=lambda k: active), node_clip=lambda: "c1")
        MainWindow._frame_viewed(me, v)
        return next(c for t in v["tracks"] for c in t["clips"] if c["id"] == "c1")["transform"]

    def test_only_with_a_viewer_on_the_picture(self):
        self.assertEqual(self.framed()["x"], 7.0)                                   # (no 預覽 node: as it is)
        g = self.e["graph"]
        v = ng.add_node(g, {"type": "viewer"}, base="viewer")
        ng.connect(g, self.nid, v, "src")
        self.src.update(w=0.5, h=0.5, cx=0.5, cy=0.0)
        tf = self.framed()
        self.assertAlmostEqual(tf["scale"], 2.0 * min(1.0, 1.0) * 1.0, places=3)      # (a half-size picture fills the canvas at twice the size)
        self.assertAlmostEqual(tf["x"], -1.0, places=3)                              # (and its middle, right of the clip's, is brought to the canvas's)
        self.assertEqual(self.framed(active=False)["x"], 7.0)                       # (the node editor not in front: not touched)
        self.assertEqual(next(c for t in self.p["tracks"] for c in t["clips"] if c["id"] == "c1")["transform"]["x"], 7.0)   # (the project itself never)


if __name__ == "__main__":
    unittest.main()
