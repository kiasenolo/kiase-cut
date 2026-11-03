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

    def test_edge_fade_goes_inward_on_every_basic_shape(self):
        from kiasecut import render
        r = render.Renderer()
        for key in ("shape.rect", "shape.circle", "shape.hexagon", "shape.star", "shape.heart", "shape.arrow", "shape.parallelogram"):
            a = assets.get(key)
            self.assertIsNotNone(a, key)
            p = assets.at(assets.make(a, "#ffffff", "#000000", 200, 200), 0)
            self.assertIn("fade", assets.fields_of(p["family"]), key)
            p["fade"] = 40
            self.assertEqual(assets.overflow(p), 0.0, key)                    # (inward: the frame stays the same)
            self.assertNotIn("Blur", assets.svg(p, part="fill"), key)          # (no filter: those cost speed)
            im = r.asset(p, 200, 200)
            self.assertGreater(im.pixelColor(im.width() // 2, im.height() // 2).alpha(), 200, key)
        p = assets.at(assets.make(assets.get("shape.rect"), "#ffffff", "#000000", 200, 200), 0)
        p["fade"] = 40
        im = r.asset(p, 200, 200)
        row = [im.pixelColor(x, im.height() // 2).alpha() for x in range(0, im.width() // 2)]
        self.assertGreater(row[-1], 250)                                       # solid in the middle
        self.assertLess(row[0], 30)                                            # clear at the edge
        self.assertEqual(row, sorted(row))                                     # a steady rise between
        self.assertLessEqual(max(b - a for a, b in zip(row, row[1:])), 10)      # in small steps (no bands)
        p["stroke_on"], p["stroke"], p["stroke_color"] = True, 10, "#ff0000"
        im = r.asset(p, 200, 200)
        self.assertGreater(im.pixelColor(im.width() // 2, 2).alpha(), 250)     # the outline stays whole

    def test_every_preset_is_a_picture(self):
        for a in assets.ASSETS:
            p = assets.make(a, "#3366ff", "#ff336680", 1920, 1080)
            path = assets.store(self.dir, p)
            info = library.probe(path)
            self.assertEqual(info["kind"], "image", a.key)
            self.assertEqual((info["width"], info["height"]), (p["w"], p["h"]), a.key)
            if a.cat not in ("shape", "empty"):             # fills the canvas
                self.assertEqual((p["w"], p["h"]), (1920, 1080), a.key)
            img = svgimage.raster(path, 64)
            if a.cat == "empty":                            # nothing to see in the file
                self.assertEqual(sum(img.pixelColor(x, y).alpha() for x in range(0, 64, 4) for y in range(0, img.height(), 2)), 0)
                continue
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
                    points=999, w=-5, color="nope", radius=3)
        self.assertEqual((p["points"], p["w"], p["color"]), (100, 1, [1.0, 1.0, 1.0, 1.0]))
        self.assertEqual(p["radius"], 3)                  # stars' corners are rounded
        heart = changed(assets.make(assets.get("shape.heart"), "#fff", "", 1920, 1080), radius=3)
        self.assertNotIn("radius", heart)                 # hearts have no corners
        self.assertEqual(assets.at(p, 0)["color"], "#ffffff")
        self.assertEqual(assets.to_rgba("#ff000080")[3], 128 / 255)
        self.assertEqual(assets.hex_of([1, 0, 0, 0.5]), "#ff000080")

    def test_star_round_corners(self):
        """A star's corners rounded by radius px: its tips pulled in, its middle still filled."""
        star = changed(assets.make(assets.get("shape.star"), "#ffffff", "", 1080, 1080), w=200, h=200)
        sharp, round_ = assets.store(self.dir, star), assets.store(self.dir, changed(star, radius=10))
        self.assertEqual(pixel(sharp, 100, 12, 200).alpha(), 255)          # the top tip
        self.assertEqual(pixel(round_, 100, 12, 200).alpha(), 0)
        self.assertEqual(pixel(round_, 100, 110, 200).alpha(), 255)
        self.assertIn(" A10 10 ", assets.outline_d(assets.at(changed(star, radius=10), 0), 200, 200))
        huge = assets.outline_d(assets.at(changed(star, radius=100000), 0), 200, 200)
        self.assertNotIn("nan", huge)                                     # (no more than the sides allow)

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

    def test_grid_lines_and_cells(self):
        p = assets.make(assets.get("shape.grid"), "#ffffff", "", 1080, 1080)
        self.assertEqual((p["gcols"], p["grows"]), (16, 9))
        path = assets.store(self.dir, changed(p, w=400, h=400, gcols=4, grows=4, gline=8, gleft=True, gright=True, gtop=True, gbottom=True))
        self.assertEqual(pixel(path, 50, 50, 400).alpha(), 0)         # inside a cell: nothing
        self.assertGreater(pixel(path, 100, 200, 400).alpha(), 200)   # on the middle line
        self.assertGreater(pixel(path, 2, 50, 400).alpha(), 200)      # the outer edge
        path = assets.store(self.dir, changed(p, w=400, h=400, gcols=4, grows=4, gline=8, gleft=False))
        self.assertEqual(pixel(path, 2, 50, 400).alpha(), 0)                # no left edge,
        self.assertGreater(pixel(path, 397, 50, 400).alpha(), 200)          # the right one stays
        path = assets.store(self.dir, assets.normalize(dict(p, w=400, h=400, gcols=4, grows=4, gline=8, gborder=False)))
        self.assertEqual(pixel(path, 397, 50, 400).alpha(), 0)              # (the old single switch: all four)
        path = assets.store(self.dir, changed(p, w=400, h=400, gcols=2, grows=1, gline=8, gratio=1.0))
        self.assertEqual(pixel(path, 200, 5, 400).alpha(), 0)         # square cells: two of 200, centred (above them: empty)
        self.assertGreater(pixel(path, 200, 100, 400).alpha(), 200)

    def test_arc_ring_and_parallelogram(self):
        e = changed(assets.make(assets.get("shape.circle"), "#ffffff", "", 1080, 1080), w=100, h=100)
        ring = changed(e, ratio=50)
        self.assertEqual(pixel(assets.store(self.dir, ring), 50, 50, 100).alpha(), 0)
        self.assertEqual(pixel(assets.store(self.dir, ring), 50, 10, 100).alpha(), 255)
        whole = changed(e, ratio=100, stroke_on=True, stroke=4, stroke_align="center")
        self.assertEqual(whole["ratio"], 100)                    # all the way: only the outline is left
        self.assertEqual(pixel(assets.store(self.dir, whole), 50, 20, 100).alpha(), 0)
        self.assertEqual(pixel(assets.store(self.dir, whole), 50, 7, 100).alpha(), 255)    # (the box has a margin)
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
        edit.set_param(p, "c1", "asset", "radius", 99999, 0)                 # typed past the soft limit
        self.assertEqual(c["asset"]["radius"], 99999)
        edit.set_param(p, "c1", "asset", "radius", -5, 0)                    # never below the hard one
        self.assertEqual(c["asset"]["radius"], 0)
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

    def test_empties_show_only_while_editing(self):
        from kiasecut import render
        keys = [a.key for a in assets.ASSETS if a.cat == "empty"]
        self.assertGreaterEqual(len(keys), 3)
        full = assets.make(assets.get("empty.full"), "", "", 1920, 1080)
        self.assertEqual((full["w"], full["h"]), (1920, 1080))
        small = assets.make(assets.get("empty.small"), "", "", 1920, 1080)
        self.assertEqual((small["w"], small["h"]), (100, 100))
        p = proj()
        p["tracks"][0]["clips"] = p["tracks"][0]["clips"][:1]
        edit.replace_media(p, "c1", assets.item(full, "/nowhere.svg"), full)
        r = render.Renderer()
        dark = r.render(p, 0, 64, 36).pixelColor(32, 18)
        self.assertEqual((dark.red(), dark.green(), dark.blue()), (0, 0, 0))     # nothing in the output
        p["editing"] = True
        seen = r.render(p, 0, 64, 36)
        self.assertGreater(max(seen.pixelColor(x, y).red() for x in range(64) for y in range(36)), 40)   # its frame in the preview
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
        from kiasecut.ui.inspector import Inspector
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
        rows = ins._asset_rows
        self.assertFalse(ins._asset_form.isRowVisible(rows["fill_color2"]))       # (a plain colour: nothing more)
        self.assertFalse(ins._asset_form.isRowVisible(rows["fill_image"]))
        editor = ins.widgets[("asset", "fill_stops")]                  # the gradient bar: not shown for a colour
        self.assertFalse(ins._asset_form.isRowVisible(editor))
        editor.changed.emit([[0, [1, 0, 0, 1]], [0.3, [0, 1, 0, 1]], [1, [0, 0, 1, 1]]])
        ins._flush()
        self.assertEqual(got[-1][:3], (["c1"], "asset", "fill_stops"))
        self.assertEqual(len(got[-1][3]), 3)
        got.clear()
        ins.widgets[("asset", "w")].setValue(640)
        ins._flush()
        self.assertEqual(got, [(["c1"], "asset", "w", 640.0)])
        ins.widgets[("key", "asset", "points")].click()
        self.assertEqual(keys, [("asset", "points")])
        edit.toggle_key(p, "c1", "asset", "points", 0)
        ins.show_clips([c], 0, 30)
        self.assertEqual(ins.widgets[("key", "asset", "points")].property("key"), "on")
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


class UnsavedProjectTests(unittest.TestCase):
    def test_shapes_drawn_outside_the_project_come_back_into_its_built_in_folder(self):
        from kiasecut import library
        d = tempfile.mkdtemp()
        try:
            cache, root = os.path.join(d, "cache"), os.path.join(d, "Project")
            os.makedirs(root)
            p = proj()
            a = assets.make(assets.get("shape.rect"), "#ff0000", "#000000", 192, 108)
            path = assets.store(os.path.join(cache, "media"), a)               # (a project with no folder yet)
            edit.replace_media(p, "c1", assets.item(a, path), a)
            plan = library.external_media(p, root)
            self.assertIn(path, plan)
            self.assertIn("/Media/" + assets.FOLDER + "/", plan[path])         # (not 匯入的素材)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class PanelDragTests(unittest.TestCase):
    def test_shapes_can_be_dragged_in_the_grid_and_in_the_list(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QAbstractItemView
        from kiasecut.ui import viewmode
        from kiasecut.ui.assets_panel import AssetsPanel
        was = viewmode.remembered("assets", "grid")
        try:
            for mode in ("grid", "list", "grid"):
                viewmode.remember("assets", mode)
                panel = AssetsPanel()
                for lst in panel.lists.values():
                    self.assertTrue(lst.dragEnabled(), mode)
                    self.assertEqual(lst.dragDropMode(), QAbstractItemView.DragOnly)
                panel.view_row.itemAt(panel.view_row.count() - 1).widget().click()      # (the other view)
                for lst in panel.lists.values():
                    self.assertTrue(lst.dragEnabled(), mode)
                md = panel.lists["shape"].mimeData([panel.lists["shape"].item(0)])
                self.assertTrue(bytes(md.data("application/x-kiasecut-media")).startswith(b"asset:") or md.formats())
        finally:
            viewmode.remember("assets", was)


class PaintTests(unittest.TestCase):
    """A shape's fill and outline can be a gradient or a picture, not only a colour."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        from PySide6.QtGui import QColor, QImage
        im = QImage(8, 8, QImage.Format_ARGB32)
        im.fill(QColor("#00ff00"))
        self.pic = os.path.join(self.dir, "green.png")
        im.save(self.pic)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def shape(self, **fields):
        p = assets.make(assets.get("shape.rect"), "#ff0000", "#0000ff", 1920, 1080)
        p.update(w=200, h=100)
        return assets.at(changed(p, **fields), 0)

    def render(self, q, w=200):
        from PySide6.QtCore import QByteArray
        from PySide6.QtGui import QColor, QImage, QPainter
        from PySide6.QtSvg import QSvgRenderer
        text = assets.svg(q)
        r = QSvgRenderer(QByteArray(text.encode("utf-8")))
        self.assertTrue(r.isValid())
        im = QImage(w + 2 * int(assets.overflow(q)), 100 + 2 * int(assets.overflow(q)), QImage.Format_ARGB32_Premultiplied)
        im.fill(QColor(0, 0, 0, 0))
        pt = QPainter(im)
        r.render(pt)
        pt.end()
        return im

    def test_gradient_fill(self):
        im = self.render(self.shape(fill_type="gradient", color="#ff0000", fill_color2="#0000ff", fill_angle=0))
        self.assertGreater(im.pixelColor(10, 50).red(), 200)
        self.assertGreater(im.pixelColor(190, 50).blue(), 200)

    def test_picture_fill_and_outline(self):
        q = self.shape(fill_type="image", fill_image=self.pic, stroke_on=True, stroke=20, stroke_type="gradient",
                       stroke_color="#ffffff", stroke_color2="#000000", stroke_angle=90)
        im = self.render(q)
        c = im.pixelColor(100, 50)
        self.assertEqual((c.red(), c.green(), c.blue()), (0, 255, 0))           # the picture inside
        self.assertGreater(im.pixelColor(100, 2).red(), 150)                     # the outline's white top
        self.assertLess(im.pixelColor(100, 97).red(), 100)                       # ... fading to black

    def test_picture_outline_and_missing_file(self):
        im = self.render(self.shape(stroke_on=True, stroke=20, stroke_type="image", stroke_image=self.pic))
        self.assertEqual(im.pixelColor(100, 3).green(), 255)
        self.assertEqual(im.pixelColor(100, 50).red(), 255)                      # the fill is still red
        q = self.shape(fill_type="image", fill_image=os.path.join(self.dir, "none.png"))
        self.assertEqual(self.render(q).pixelColor(100, 50).red(), 255)          # unreadable: the colour

    def test_blender_texture_fill_and_outline(self):
        from kiasecut import textures
        for kind in textures.KINDS:
            q = self.shape(fill_type=kind, fill_color2="#ffffff", color="#000000", stroke_on=True, stroke=20,
                           stroke_type=kind, stroke_scale=3)
            im = self.render(q)
            self.assertGreater(im.pixelColor(100, 50).alpha(), 250, kind)
            self.assertGreater(im.pixelColor(100, 3).alpha(), 250, kind)
        q = self.shape(fill_type="checker", color="#000000", fill_color2="#ffffff")
        im = self.render(q)
        self.assertGreater(len({im.pixelColor(x, 50).red() for x in range(0, 200, 5)}), 1)    # not one colour

    def test_gradient_with_several_stops(self):
        stops = [[0, [1, 0, 0, 1]], [0.5, [0, 1, 0, 1]], [1, [0, 0, 1, 1]]]
        im = self.render(self.shape(fill_type="gradient", fill_stops=stops))
        self.assertGreater(im.pixelColor(2, 50).red(), 200)
        self.assertGreater(im.pixelColor(100, 50).green(), 200)       # the middle stop
        self.assertGreater(im.pixelColor(197, 50).blue(), 200)
        g = changed(assets.make(assets.get("gradient.custom.0"), "#ff0000", "#0000ff", 200, 100), stops=stops)
        self.assertEqual(len(assets.at(g, 0)["stops"]), 3)
        self.assertIn('offset="0.5"', assets.svg(assets.at(g, 0)))
        self.assertEqual(assets.clean("stops", [[0, [1, 1, 1, 1]]]), [])      # (one stop: none of its own)
        self.assertEqual(len(assets.stops_of(assets.at(g, 0))), 3)
        self.assertEqual(len(assets.stops_of(assets.at(assets.make(assets.get("gradient.0"), "", "", 20, 10), 0))), 2)

    def test_stops_and_curve_keys_go_through_set_param(self):
        p = proj()
        params = assets.make(assets.get("shape.rect"), "#ff0000", "#0000ff", 1920, 1080)
        edit.replace_media(p, "c1", assets.item(params, "/a.svg"), params)
        stops = [[0, [1, 0, 0, 1]], [0.5, [0, 1, 0, 0.5]], [1, [0, 0, 1, 1]]]
        edit.set_param(p, "c1", "asset", "fill_stops", stops)
        self.assertEqual(len(edit.find(p, "c1")[1]["asset"]["fill_stops"]), 3)
        e = edit.put_effect(p, "c1", "builtin:duotone")
        keys = [[0, 0, 0, 0, 0.3, 0], [1, 1, -0.3, 0, 0, 0]]
        edit.set_param(p, "c1", "fx:" + e["id"], "ease", keys)
        self.assertEqual(edit.find(p, "c1")[1]["effects"][0]["params"]["ease"], keys)

    def test_the_editor_is_not_pulled_back_while_it_is_used(self):
        from kiasecut.ui.gradientbar import GradientEditor
        ed = GradientEditor()
        ed.set_stops([[0, [1, 0, 0, 1]], [1, [0, 0, 1, 1]]])
        ed.bar.sel = 1
        ed.set_stops([[0, [1, 0, 0, 1]], [1, [0, 0, 1, 1]]])          # (the same: nothing is reset)
        self.assertEqual(ed.bar.sel, 1)
        ed.bar.dragging = True
        ed.bar.stops[1][0] = 0.6
        ed.set_stops([[0, [1, 0, 0, 1]], [1, [0, 0, 1, 1]]])          # (a refresh with the old value, mid-drag)
        self.assertEqual(ed.bar.stops[1][0], 0.6)

    def test_old_parameters_still_load(self):
        p = changed(assets.make(assets.get("shape.star"), "#fff", "#000", 1920, 1080))
        self.assertEqual(p["fill_type"], "solid")
        self.assertEqual(assets.normalize({k: v for k, v in p.items() if "type" not in k})["stroke_type"], "solid")


class VisualizerAssetTests(unittest.TestCase):
    def test_the_four_visualizers_are_in_the_tab(self):
        from kiasecut import viz
        from kiasecut.ui.assets_panel import AssetsPanel
        panel = AssetsPanel()
        lst = panel.lists["viz"]
        self.assertEqual([lst.item(i).text() for i in range(lst.count())], list(viz.KINDS.values()))
        self.assertTrue(lst.dragEnabled())
        self.assertFalse(lst.item(0).icon().isNull())
        got = []
        panel.addRequested.connect(got.append)
        lst.itemDoubleClicked.emit(lst.item(2))
        self.assertEqual(got, ["viz:scope"])
        md = lst.mimeData([lst.item(1)])
        self.assertEqual(bytes(md.data("application/x-kiasecut-media")).decode(), "viz:wave")
        panel.refresh()                                             # (the colours of the panel do not touch them)


if __name__ == "__main__":
    unittest.main()
