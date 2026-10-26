"""套用至背景: a clip's effects work on what is under it, inside its shape (like a frosted
glass panel); 隱藏本體 leaves the clip undrawn - always so for clips that are not shapes."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import assets, edit, fx, glrender, project, render  # noqa: E402
from test_compound_mask import HAVE_GL, Scene, rgb  # noqa: E402
from test_edit import S, clip  # noqa: E402

APP = QApplication.instance() or QApplication([])
W, H = 64, 36


class BackdropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.s = Scene(cls.dir)
        try:
            fx.Engine()
            cls.fx = True
        except Exception:
            cls.fx = False

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def view(self, hide=False, asset=True):
        """Red picture under a half-width shape in the middle with 反相 (invert) applied to the background."""
        bg = self.s.pic("bg", self.s.red)
        top = clip("top", 0, 2 * S)
        if asset:
            a = assets.make(assets.get("shape.rect"), "#00ff00", "", 1920, 1080)
            a.update(w=960, h=1080)
            top["asset"] = a
            top["media"] = {"path": "/none.svg", "width": 960, "height": 1080}
        else:
            top["media"] = {"path": self.s.blue, "width": 160, "height": 90}
            top["transform"]["scale"] = 0.5
        top["effects"] = [{"id": "e1", "filter": "builtin:invert", "params": {}}]
        top["backdrop"] = {"on": True, "hide": hide}
        return {"width": 1920, "height": 1080, "fps": 30, "duration_us": 2 * S, "compounds": {},
                "tracks": [{"id": "t0", "kind": "video", "name": "v", "clips": [bg]},
                           {"id": "t1", "kind": "video", "name": "v", "clips": [top]}]}

    def renderers(self):
        return [render.Renderer()] + ([glrender.GLRenderer()] if HAVE_GL else [])

    def test_rules(self):
        c = {"effects": [{"filter": "builtin:invert"}], "backdrop": {"on": True}}
        self.assertEqual(project.backdrop_of(c), (True, True))                # not a shape: body hidden
        c["asset"] = {"family": "rect"}
        self.assertEqual(project.backdrop_of(c), (True, False))
        c["backdrop"]["hide"] = True
        self.assertEqual(project.backdrop_of(c), (True, True))
        self.assertEqual(project.backdrop_of({"backdrop": {"on": True}}), (False, False))   # no effects
        p = project.new()
        p["tracks"] = [{"id": "t", "kind": "video", "name": "v", "clips": [clip("c", 0, S)]}]
        project.link(p)
        edit.set_backdrop(p, "c", on=True)
        self.assertEqual(edit.find(p, "c")[1]["backdrop"], {"on": True, "hide": False})
        edit.set_backdrop(p, "c", on=False)
        self.assertNotIn("backdrop", edit.find(p, "c")[1])

    def test_shape_over_its_backdrop(self):
        if not self.fx:
            self.skipTest("needs OpenGL for filters")
        for r in self.renderers():
            img = r.render(self.view(hide=True), 0, W, H)
            self.assertEqual(r.errors, [], type(r).__name__)
            self.assertEqual(rgb(img, 32, 18), (0, 255, 255), type(r).__name__)   # inverted red, inside it
            self.assertEqual(rgb(img, 4, 18), (255, 0, 0), type(r).__name__)      # untouched outside it
            img = r.render(self.view(hide=False), 0, W, H)
            self.assertEqual(rgb(img, 32, 18), (0, 255, 0), type(r).__name__)     # the shape drawn on top

    def test_picture_always_hides_itself(self):
        if not self.fx:
            self.skipTest("needs OpenGL for filters")
        for r in self.renderers():
            img = r.render(self.view(asset=False), 0, W, H)
            self.assertEqual(rgb(img, 32, 18), (0, 255, 255), type(r).__name__)   # not blue: hidden
            self.assertEqual(rgb(img, 4, 18), (255, 0, 0), type(r).__name__)


if __name__ == "__main__":
    unittest.main()
