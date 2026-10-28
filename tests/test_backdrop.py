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

from PySide6.QtCore import Qt  # noqa: E402
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

    def view(self, hide=False, asset=True, color="#00ff00"):
        """Red picture under a half-width shape in the middle with 反相 (invert) applied to the background."""
        bg = self.s.pic("bg", self.s.red)
        top = clip("top", 0, 2 * S)
        if asset:
            a = assets.make(assets.get("shape.rect"), color, "", 1920, 1080)
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

    def test_a_see_through_shape_still_covers(self):
        """A shape's 套用至背景 works where the shape is, not by its colour's alpha."""
        if not self.fx:
            self.skipTest("needs OpenGL for filters")
        for r in self.renderers():
            img = r.render(self.view(color="#00ff0000"), 0, W, H)               # filled, all see-through
            self.assertEqual(r.errors, [], type(r).__name__)
            self.assertEqual(rgb(img, 32, 18), (0, 255, 255), type(r).__name__)
            self.assertEqual(rgb(img, 4, 18), (255, 0, 0), type(r).__name__)
            img = r.render(self.view(color="#00ff0080"), 0, W, H)               # half: the effect in full
            self.assertEqual(rgb(img, 4, 18), (255, 0, 0), type(r).__name__)
            px = rgb(img, 32, 18)
            self.assertTrue(px[0] < 8 and px[2] > 100, (type(r).__name__, px))  # green over cyan

    def test_opacity_only_fades_the_shape(self):
        if not self.fx:
            self.skipTest("needs OpenGL for filters")
        for r in self.renderers():
            for op in (0.0, 0.5):
                view = self.view()
                view["tracks"][1]["clips"][0]["transform"]["opacity"] = op
                img = r.render(view, 0, W, H)
                px = rgb(img, 32, 18)
                if op == 0:
                    self.assertEqual(px, (0, 255, 255), type(r).__name__)               # the effect in full
                else:
                    self.assertTrue(px[0] < 8 and 100 < px[2] < 160, (type(r).__name__, px))  # green half over cyan
                self.assertEqual(rgb(img, 4, 18), (255, 0, 0), type(r).__name__)

    def test_cover(self):
        q = assets.at(dict(assets.make(assets.get("shape.circleframe"), "#ff000000", "#00000000", 1920, 1080),
                           stroke_color=[0, 0, 0, 0]), 0)
        c = assets.cover(q)
        self.assertEqual((c["stroke_color"], c["fill"], c["stroke_on"]), ("#ffffff", False, True))   # its outline
        q.update(stroke_on=False)
        self.assertTrue(assets.cover(q)["fill"])                                # nothing drawn: its fill
        g = assets.at(assets.make(assets.get("gradient.8"), "", "", 1920, 1080), 0)   # 暗角
        self.assertEqual((assets.cover(g)["color"], assets.cover(g)["color2"]), ("#ffffff", "#ffffff"))

    def test_picture_always_hides_itself(self):
        if not self.fx:
            self.skipTest("needs OpenGL for filters")
        for r in self.renderers():
            img = r.render(self.view(asset=False), 0, W, H)
            self.assertEqual(rgb(img, 32, 18), (0, 255, 255), type(r).__name__)   # not blue: hidden
            self.assertEqual(rgb(img, 4, 18), (255, 0, 0), type(r).__name__)



class ThroughTests(unittest.TestCase):
    """效果穿透: a compound clip lets the 套用至背景 and filter clips inside work on what is
    under it too, inside its frame."""

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

    def view(self, inner="filter", on=True, scale=1.0, opacity=1.0, static=False):
        """A red picture under a compound clip holding a 反相 filter clip, or a half-width
        shape with 反相 套用至背景 over a blue picture's left half."""
        bg = self.s.pic("bg", self.s.red)
        inv = [{"id": "e1", "filter": "builtin:invert", "params": {}}]
        if inner == "filter":
            clips = [clip("f", 0, 2 * S, type="filter", effects=inv)]
        else:
            top = clip("sh", 0, 2 * S)
            a = assets.make(assets.get("shape.rect"), "#00ff00", "", 1920, 1080)
            a.update(w=960, h=1080)
            top.update(asset=a, media={"path": "/none.svg", "width": 960, "height": 1080}, effects=inv,
                       backdrop={"on": True, "hide": True})
            clips = [top]
        blue = self.s.pic("blue", self.s.blue)
        blue["transform"].update(scale=0.5, x=-0.5)
        comp = {"name": "k", "width": 1920, "height": 1080, "duration_us": 2 * S,
                "tracks": [{"id": "i0", "kind": "video", "name": "v", "clips": [blue]},
                           {"id": "i1", "kind": "video", "name": "v", "clips": clips}]}
        if static:
            comp["static"] = True
        cc = clip("cc", 0, 2 * S, type="compound", compound_id="k2", compound=comp)
        cc["transform"].update(scale=scale, opacity=opacity)
        if on:
            cc["fx_through"] = True
        return {"width": 1920, "height": 1080, "fps": 30, "duration_us": 2 * S, "compounds": {"k2": comp},
                "tracks": [{"id": "t0", "kind": "video", "name": "v", "clips": [bg]},
                           {"id": "t1", "kind": "video", "name": "v", "clips": [cc]}]}

    def renderers(self):
        return [render.Renderer()] + ([glrender.GLRenderer()] if HAVE_GL else [])

    def test_rules(self):
        v = self.view()
        cc = v["tracks"][1]["clips"][0]
        self.assertTrue(project.passes_through(cc))
        inner = cc["compound"]["tracks"][1]
        inner["hidden"] = True
        self.assertFalse(project.passes_through(cc))                  # nothing inside that shows
        inner["hidden"] = False
        self.assertTrue(project.passes_through(self.view("shape")["tracks"][1]["clips"][0]))
        self.assertFalse(project.passes_through(self.view(on=False)["tracks"][1]["clips"][0]))
        outer = clip("o", 0, 2 * S, type="compound", compound={"tracks": [{"id": "x", "kind": "video", "clips": [cc]}]},
                     fx_through=True)
        self.assertTrue(project.passes_through(outer))                # through one that passes its own
        cc.pop("fx_through")
        self.assertFalse(project.passes_through(outer))
        edit.set_fx_through(v, "cc", True)
        self.assertTrue(cc["fx_through"])
        edit.set_fx_through(v, "cc", False)
        self.assertNotIn("fx_through", cc)
        with self.assertRaises(edit.EditError):
            edit.set_fx_through(v, "bg", True)

    def test_inspector_row(self):
        from kiasecut.ui.inspector import Inspector
        ins = Inspector()
        v = self.view()
        ins.show_clips([v["tracks"][1]["clips"][0]], 0, 30)
        self.assertEqual(ins.widgets["fx_through"].checkState(), Qt.Checked)
        v["tracks"][1]["clips"][0]["compound"]["tracks"].pop()             # nothing inside to pass
        v["tracks"][1]["clips"][0].pop("fx_through")
        ins.show_clips([v["tracks"][1]["clips"][0]], 0, 30)
        self.assertNotIn("fx_through", ins.widgets)
        ins.deleteLater()

    def test_filter_clip(self):
        if not self.fx:
            self.skipTest("needs OpenGL for filters")
        cyan, red = (0, 255, 255), (255, 0, 0)
        for r in self.renderers():
            name = type(r).__name__
            img = r.render(self.view(on=False), 0, W, H)
            self.assertEqual(r.errors, [], name)
            self.assertEqual(rgb(img, 48, 18), red, name)                   # off: only what is inside
            self.assertEqual(rgb(img, 16, 18), (255, 255, 0), name)          # (the blue inverted)
            for static in (False, True):
                img = r.render(self.view(static=static), 0, W, H)
                self.assertEqual(r.errors, [], name)
                self.assertEqual(rgb(img, 48, 18), cyan, (name, static))    # the red under it inverted
                self.assertEqual(rgb(img, 16, 18), (255, 255, 0), (name, static))
            img = r.render(self.view(scale=0.5), 0, W, H)
            self.assertEqual(rgb(img, 40, 18), cyan, name)
            self.assertEqual(rgb(img, 4, 4), red, name)                     # outside its frame: untouched
            px = rgb(r.render(self.view(opacity=0.5), 0, W, H), 48, 18)
            self.assertTrue(abs(px[0] - 128) <= 3 and px[2] > 120, (name, px))   # halfway

    def test_backdrop_shape(self):
        if not self.fx:
            self.skipTest("needs OpenGL for filters")
        for r in self.renderers():
            name = type(r).__name__
            img = r.render(self.view("shape", on=False), 0, W, H)
            self.assertEqual(r.errors, [], name)
            self.assertEqual(rgb(img, 36, 18), (255, 0, 0), name)
            img = r.render(self.view("shape"), 0, W, H)
            self.assertEqual(r.errors, [], name)
            self.assertEqual(rgb(img, 36, 18), (0, 255, 255), name)          # inside the shape: inverted red
            self.assertEqual(rgb(img, 28, 18), (255, 255, 0), name)          # and the blue in it
            self.assertEqual(rgb(img, 56, 18), (255, 0, 0), name)            # outside it: as it was
            self.assertEqual(rgb(img, 4, 18), (0, 0, 255), name)


if __name__ == "__main__":
    unittest.main()
