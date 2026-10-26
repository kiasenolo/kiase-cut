"""Built-in assets (內建素材): every preset makes a valid SVG of its size, parameters can be
edited and keyframed, asset clips are drawn at their own size from their parameters; X / Y
scale, linked and not."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import assets, curves, edit, library, project, svgimage  # noqa: E402
from test_edit import S, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


def changed(p, **fields):
    """Asset parameters p with some fields set (as the inspector would)."""
    return assets.normalize(dict(p, **fields))


def pixel(path, x, y, w):
    return svgimage.raster(path, w).pixelColor(x, y)


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_every_preset_is_a_picture(self):
        for a in assets.ASSETS:
            p = assets.make(a, "#3366ff", "#ff336680", 1920, 1080)
            path = assets.store(self.dir, p)
            info = library.probe(path)
            self.assertEqual(info["kind"], "image", a.key)
            self.assertEqual((info["width"], info["height"]), (p["w"], p["h"]), a.key)
            if a.cat != "shape":                            # fills the canvas
                self.assertEqual((p["w"], p["h"]), (1920, 1080), a.key)
            img = svgimage.raster(path, 64)
            self.assertGreater(sum(img.pixelColor(x, y).alpha() for x in range(0, 64, 4)
                                   for y in range(0, img.height(), 2)), 0, a.key)
            for fill, align in ((True, "inside"), (False, "inside"), (True, "outside")):     # outlines too
                if "fill" in p:
                    q = changed(p, fill=fill, stroke_on=True, stroke=30, stroke_align=align, join="round", w=300, h=120)
                    pad = 30 if align == "outside" else 0      # (an outline outside makes the picture larger)
                    self.assertEqual(svgimage.size(assets.store(self.dir, q)), (300 + 2 * pad, 120 + 2 * pad), a.key)

    def test_colours_and_parameters(self):
        p = assets.make(assets.get("solid.custom"), "#ff0000", "#000000", 16, 9)
        self.assertEqual(pixel(assets.store(self.dir, p), 8, 4, 16).name(), "#ff0000")
        red = assets.make(assets.get("solid.3"), "#00ff00", "#000000", 16, 9)   # a preset keeps its colour
        self.assertEqual(pixel(assets.store(self.dir, red), 8, 4, 16).name(), "#e53935")
        g = assets.make(assets.get("gradient.custom.0"), "#000000", "#ffffff", 100, 10)
        self.assertLess(pixel(assets.store(self.dir, g), 2, 5, 100).red(), 30)
        self.assertGreater(pixel(assets.store(self.dir, g), 97, 5, 100).red(), 225)
        flipped = changed(g, angle=180)
        self.assertGreater(pixel(assets.store(self.dir, flipped), 2, 5, 100).red(), 225)
        ring = changed(assets.make(assets.get("shape.circle"), "#ffffff", "", 1920, 1080),
                       w=100, h=100, fill=False, stroke_on=True, stroke=10)
        self.assertEqual(pixel(assets.store(self.dir, ring), 50, 50, 100).alpha(), 0)    # hollow
        self.assertEqual(pixel(assets.store(self.dir, ring), 50, 3, 100).alpha(), 255)
        disc = changed(ring, fill=True, stroke_on=False)
        self.assertEqual(pixel(assets.store(self.dir, disc), 50, 50, 100).alpha(), 255)

    def test_normalize(self):
        p = changed(assets.make(assets.get("shape.star"), "#fff", "", 1920, 1080),
                    points=99, w=-5, color="nope", radius=3)
        self.assertEqual((p["points"], p["w"], p["color"]), (24, 1, [1.0, 1.0, 1.0, 1.0]))
        self.assertNotIn("radius", p)                     # stars have no corners
        self.assertEqual(assets.at(p, 0)["color"], "#ffffff")
        self.assertEqual(assets.to_rgba("#ff000080")[3], 128 / 255)
        self.assertEqual(assets.hex_of([1, 0, 0, 0.5]), "#ff000080")

    def test_fill_and_outline(self):
        """Fill and outline together, the outline inside / on / outside the edge, none at 0 px."""
        base = changed(assets.make(assets.get("shape.rect"), "#ff0000", "#0000ff", 1080, 1080), w=100, h=100,
                       stroke_on=True, stroke=10)

        def at(p, x, y):                                 # (x, y) in the frame's own px
            q = assets.at(p, 0)
            pad = assets.overflow(q)
            img = svgimage.raster_text(assets.svg(q), q["w"] + 2 * pad, q["h"] + 2 * pad)
            return img.pixelColor(round(x + pad), round(y + pad))
        for align, inside, outside in (("inside", "#0000ff", None), ("center", "#0000ff", "#0000ff"),
                                       ("outside", "#ff0000", "#0000ff")):
            p = changed(base, stroke_align=align)
            self.assertEqual(at(p, 50, 50).name(), "#ff0000", align)      # the fill
            self.assertEqual(at(p, 2, 50).name(), inside, align)
            if outside:
                self.assertEqual(at(p, -3, 50).name(), outside, align)
        self.assertEqual(assets.overflow(assets.at(changed(base, stroke_align="outside", join="miter"), 0)),
                         10 * assets.MITER_LIMIT)
        none = changed(base, fill=False, stroke=0)
        self.assertEqual(at(none, 2, 50).alpha(), 0)

    def test_arc_ring_and_parallelogram(self):
        e = changed(assets.make(assets.get("shape.circle"), "#ffffff", "", 1080, 1080), w=100, h=100)
        ring = changed(e, ratio=50)
        self.assertEqual(pixel(assets.store(self.dir, ring), 50, 50, 100).alpha(), 0)
        self.assertEqual(pixel(assets.store(self.dir, ring), 50, 10, 100).alpha(), 255)
        quarter = changed(e, arc_start=0, arc_sweep=25)          # 3 to 6 o'clock
        self.assertEqual(pixel(assets.store(self.dir, quarter), 70, 70, 100).alpha(), 255)
        self.assertEqual(pixel(assets.store(self.dir, quarter), 30, 30, 100).alpha(), 0)
        para = changed(assets.make(assets.get("shape.parallelogram"), "#ffffff", "", 1080, 1080),
                       w=200, h=100, skew=30)
        self.assertEqual(pixel(assets.store(self.dir, para), 3, 3, 200).alpha(), 0)
        self.assertEqual(pixel(assets.store(self.dir, para), 3, 97, 200).alpha(), 255)

    def test_older_outlines(self):
        old = {"key": "shape.ring", "family": "ellipse", "w": 100, "h": 100, "color": "#00ff00",
               "outline": True, "stroke": 10}
        p = assets.normalize(old)
        self.assertEqual((p["fill"], p["stroke_on"], p["stroke_color"]), (False, True, [0.0, 1.0, 0.0, 1.0]))
        self.assertNotIn("outline", p)
        self.assertEqual(pixel(assets.store(self.dir, p), 50, 50, 100).alpha(), 0)

    def test_store_reuses(self):
        p = assets.make(assets.get("shape.circle"), "#ffffff", "#000000", 1920, 1080)
        a, b = assets.store(self.dir, p), assets.store(self.dir, dict(p))
        self.assertEqual(a, b)
        self.assertNotEqual(a, assets.store(self.dir, changed(p, w=401)))
        self.assertEqual(len(os.listdir(os.path.join(self.dir, assets.FOLDER))), 2)

    def test_restore(self):
        p = assets.make(assets.get("shape.heart"), "#ff0000", "", 1920, 1080)
        c = {"id": "c", "asset": p, "media": {"path": "/gone/heart.svg", "width": 1, "height": 1}}
        moved = assets.restore([c], self.dir)
        self.assertEqual(moved[0][0], "/gone/heart.svg")
        self.assertTrue(os.path.exists(c["media"]["path"]))
        self.assertEqual((c["media"]["width"], c["media"]["height"]), (400, 400))
        self.assertEqual(assets.restore([c], self.dir), [])

    def test_ident(self):
        a, c1, c2 = assets.parse(assets.ident("shape.star", "#AABBCC", "#11223344"))
        self.assertEqual((a.key, c1, c2), ("shape.star", "#aabbcc", "#11223344"))
        self.assertEqual(assets.parse("asset:shape.star:junk")[1:], ("#ffffff", "#000000"))
        self.assertIsNone(assets.parse("asset:nope"))
        self.assertIsNone(assets.parse("mabc"))

    def test_asset_clip_edits(self):
        p = proj()
        params = assets.make(assets.get("shape.rect"), "#ffffff", "", 1920, 1080)
        c = edit.find(p, "c1")[1]
        edit.replace_media(p, "c1", assets.item(params, "/a.svg"), params)
        self.assertEqual(c["asset"]["family"], "rect")
        self.assertEqual(project.picture_size(c, 1920, 1080), (400, 400))      # own size, not fitted
        self.assertEqual(project.picture_size(c, 1920, 1080, 2.0), (800, 800))
        edit.set_param(p, "c1", "asset", "w", 600, 0)
        self.assertEqual(project.picture_size(c, 1920, 1080), (600, 400))
        edit.set_param(p, "c1", "asset", "radius", 99999, 0)                 # kept in range
        self.assertEqual(c["asset"]["radius"], assets.FIELD_INFO["radius"][3])
        edit.set_param(p, "c1", "asset", "color", "#00ff00", 0)
        self.assertEqual(c["asset"]["color"], [0.0, 1.0, 0.0, 1.0])
        with self.assertRaises(edit.EditError):
            edit.set_param(p, "c1", "asset", "points", 5, 0)                 # a rectangle has none
        edit.replace_media(p, "c1", {"kind": "image", "path": "/x.png", "width": 100, "height": 50})
        self.assertNotIn("asset", c)
        self.assertEqual(project.picture_size(c, 1920, 1080), (1920, 960))
        with self.assertRaises(edit.EditError):
            edit.set_param(p, "c1", "asset", "w", 600, 0)

    def test_keyframes(self):
        from kiasecut import renderexport
        p = proj()
        params = assets.make(assets.get("shape.rect"), "#ff0000", "", 1920, 1080)
        edit.replace_media(p, "c1", assets.item(params, "/a.svg"), params)
        c = edit.find(p, "c1")[1]
        self.assertFalse(renderexport.needs_renderer(p))
        for g, k in (("asset", "w"), ("asset", "color")):
            edit.toggle_key(p, "c1", g, k, 0)
        edit.set_param(p, "c1", "asset", "w", 800, S)                     # a second key at 1 s
        edit.set_param(p, "c1", "asset", "color", [0, 0, 1, 1], S)
        self.assertEqual(project.picture_size(c, 1920, 1080, t=S // 2), (600, 400))
        self.assertEqual(assets.at(c["asset"], S)["color"], "#0000ff")
        self.assertEqual(edit.key_times(c), [0, S])                       # shown on the timeline
        self.assertTrue(renderexport.needs_renderer(p))                    # MLT cannot animate it
        for t in (S, 0):                                                   # the last key goes: a value again
            edit.toggle_key(p, "c1", "asset", "color", t)
        self.assertEqual(c["asset"]["color"], [1.0, 0.0, 0.0, 1.0])
        right = edit.split(p, "c1", S // 2)                                # keys follow a split
        self.assertEqual(project.picture_size(right, 1920, 1080), (600, 400))

    def test_outline_outside_is_drawn(self):
        """An outline outside the edge shows past the shape's frame; it goes to the own renderer."""
        from kiasecut import render, renderexport
        p = proj()
        p["tracks"][0]["clips"] = p["tracks"][0]["clips"][:1]
        params = changed(assets.make(assets.get("shape.rect"), "#ff0000", "#0000ff", 1920, 1080),
                         w=400, h=400, stroke_on=True, stroke=40, stroke_align="outside", join="round")
        edit.replace_media(p, "c1", assets.item(params, "/nowhere.svg"), params)
        self.assertTrue(renderexport.needs_renderer(p))
        img = render.Renderer().render(p, 0, 1920, 1080)
        self.assertEqual(img.pixelColor(960, 540).name(), "#ff0000")              # the fill
        self.assertEqual(img.pixelColor(960 - 200 - 20, 540).name(), "#0000ff")   # 20 px outside the frame
        self.assertEqual(img.pixelColor(960 - 200 - 60, 540).name(), "#000000")   # past the outline

    def test_drawn_from_parameters(self):
        from kiasecut import render
        p = proj()
        p["tracks"][0]["clips"] = p["tracks"][0]["clips"][:1]
        params = assets.make(assets.get("solid.custom"), "#ff0000", "", 1920, 1080)
        edit.replace_media(p, "c1", assets.item(params, "/nowhere.svg"), params)   # no file needed
        edit.toggle_key(p, "c1", "asset", "color", 0)
        edit.set_param(p, "c1", "asset", "color", [0, 0, 1, 1], S)
        r = render.Renderer()
        fps = p["fps"]
        a = r.render(p, 0, 64, 36).pixelColor(32, 18)
        b = r.render(p, round(fps), 64, 36).pixelColor(32, 18)
        self.assertEqual((a.red(), a.blue()), (255, 0))
        self.assertEqual((b.red(), b.blue()), (0, 255))
        self.assertFalse(r.errors)

    def test_export_static_asset(self):
        from kiasecut import build
        p = proj()
        params = assets.make(assets.get("shape.star"), "#ff0000", "", 1920, 1080)
        edit.replace_media(p, "c1", assets.item(params, "/nowhere.svg"), params)
        doc = build.Builder(p, self.dir).document()                       # drawn from the parameters
        self.assertIn(".png", doc)

    def test_panel(self):
        from kiasecut.ui.assets_panel import AssetsPanel
        from kiasecut.ui.timeline import MEDIA_MIME
        panel = AssetsPanel()
        got = []
        panel.addRequested.connect(got.append)
        lst = panel.lists["shape"]
        self.assertEqual(lst.count(), sum(a.cat == "shape" for a in assets.ASSETS))
        md = lst.mimeData([lst.item(0)])
        self.assertEqual(bytes(md.data(MEDIA_MIME)).decode(), "asset:shape.rect:#ffffff:#000000")
        panel.colors = ["#ff0000", "#00ff00"]
        panel.refresh()
        lst.itemDoubleClicked.emit(lst.item(0))
        self.assertEqual(got, ["asset:shape.rect:#ff0000:#00ff00"])

    def test_inspector(self):
        from kiasecut.ui.inspector import KEY_ON, Inspector
        p = proj()
        params = assets.make(assets.get("shape.star"), "#ff0000", "", 1920, 1080)
        edit.replace_media(p, "c1", assets.item(params, "/a.svg"), params)
        ins = Inspector()
        got, keys = [], []
        ins.paramEdited.connect(lambda ids, g, k, v: got.append((ids, g, k, v)))
        ins.keyToggled.connect(lambda ids, g, k: keys.append((g, k)))
        c = edit.find(p, "c1")[1]
        ins.show_clips([c], 0, 30)
        self.assertEqual(ins.widgets[("asset", "points")].value(), 5)
        self.assertEqual(ins.widgets[("asset", "color")].text(), "#ff0000")
        self.assertTrue(ins.widgets["scale_link"].isChecked())
        ins.widgets[("asset", "w")].setValue(640)
        ins._flush()
        self.assertEqual(got, [(["c1"], "asset", "w", 640.0)])
        ins.widgets[("key", "asset", "points")].click()
        self.assertEqual(keys, [("asset", "points")])
        edit.toggle_key(p, "c1", "asset", "points", 0)
        ins.show_clips([c], 0, 30)
        self.assertEqual(ins.widgets[("key", "asset", "points")].text(), KEY_ON)
        ins.show_clips([edit.find(p, "c2")[1]], 0, 30)     # a plain picture: no asset section
        self.assertNotIn(("asset", "w"), ins.widgets)


class ScaleTests(unittest.TestCase):
    def tf(self, p, cid="c1"):
        return edit.find(p, cid)[1]["transform"]

    def test_linked_without_y(self):
        p = proj()
        edit.set_param(p, "c1", "transform", "scale", 2.0, 0)
        self.assertNotIn("scale_y", self.tf(p))           # Y follows X
        edit.set_param(p, "c1", "transform", "scale_y", 3.0, 0)
        self.assertEqual(self.tf(p)["scale"], 3.0)
        self.assertNotIn("scale_y", self.tf(p))

    def test_linked_keeps_ratio(self):
        p = proj()
        self.tf(p)["scale_y"] = 0.5
        edit.set_param(p, "c1", "transform", "scale", 2.0, 0)
        self.assertEqual((self.tf(p)["scale"], self.tf(p)["scale_y"]), (2.0, 1.0))
        edit.set_param(p, "c1", "transform", "scale_y", 3.0, 0)
        self.assertEqual((self.tf(p)["scale"], self.tf(p)["scale_y"]), (6.0, 3.0))

    def test_unlinked(self):
        p = proj()
        edit.set_param(p, "c1", "transform", "scale_link", False)
        edit.set_param(p, "c1", "transform", "scale", 2.0, 0)
        self.assertEqual((self.tf(p)["scale"], self.tf(p)["scale_y"]), (2.0, 1.0))
        edit.set_param(p, "c1", "transform", "scale_y", 0.25, 0)
        self.assertEqual((self.tf(p)["scale"], self.tf(p)["scale_y"]), (2.0, 0.25))
        edit.set_param(p, "c1", "transform", "scale_link", True)
        edit.set_param(p, "c1", "transform", "scale", 4.0, 0)
        self.assertEqual((self.tf(p)["scale"], self.tf(p)["scale_y"]), (4.0, 0.5))

    def test_keys(self):
        p = proj()
        self.tf(p)["scale_y"] = 0.5
        edit.toggle_key(p, "c1", "transform", "scale", S // 2)      # linked: both get a key
        self.assertTrue(curves.is_animated(self.tf(p)["scale"]))
        self.assertTrue(curves.is_animated(self.tf(p)["scale_y"]))
        edit.set_param(p, "c1", "transform", "scale", 2.0, S // 2)
        self.assertAlmostEqual(curves.value(self.tf(p)["scale_y"], S // 2), 1.0)
        edit.toggle_key(p, "c1", "transform", "scale_y", S // 2)    # and lose it together
        self.assertFalse(curves.is_animated(self.tf(p)["scale"]))
        self.assertFalse(curves.is_animated(self.tf(p)["scale_y"]))
        edit.set_param(p, "c1", "transform", "scale_link", False)
        edit.toggle_key(p, "c1", "transform", "scale", S // 2)      # unlinked: only X
        self.assertTrue(curves.is_animated(self.tf(p)["scale"]))
        self.assertFalse(curves.is_animated(self.tf(p)["scale_y"]))

    def test_live_values(self):
        h = {"scale": 2.0, "scale_y": 1.0}
        self.assertEqual(edit.with_linked_scale(h, {"scale": 4.0}, 0), {"scale": 4.0, "scale_y": 2.0})
        h["scale_link"] = False
        self.assertEqual(edit.with_linked_scale(h, {"scale": 4.0}, 0), {"scale": 4.0})
        self.assertEqual(edit.with_linked_scale({"scale": 2.0, "scale_link": False}, {"scale": 3.0}, 0),
                         {"scale": 3.0, "scale_y": 2.0})


if __name__ == "__main__":
    unittest.main()
