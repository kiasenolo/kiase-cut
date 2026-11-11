"""Vector nodes: 相加 and 布林 over shapes, texts and SVG files (vector.py, nodegraph.py, render.py)."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QPainterPath  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, fx, nodegraph as ng, render, vector  # noqa: E402
from test_compound_mask import HAVE_GL, Scene, W, H, rgb  # noqa: E402
from test_edit import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
WHITE, BLACK = (255, 255, 255), (0, 0, 0)


def rect(x, y, w, h):
    p = QPainterPath()
    p.addRect(QRectF(x, y, w, h))
    return vector.Layer(p)


class VectorTests(unittest.TestCase):
    def test_path_data_has_every_command(self):
        p = vector.parse_d("M10 10 h20 v20 H10 Z m5 5 l10 0 0 10 z M0 0 C 1 1 2 2 3 3 S 5 5 6 6 Q 1 2 3 4 T 5 6 A 5 5 0 0 1 10 0")
        self.assertGreater(p.elementCount(), 10)
        arc = vector.parse_d("M0 0 A 10 10 0 0 1 20 0")
        self.assertAlmostEqual(arc.boundingRect().height(), 10, delta=0.5)         # (a half circle of radius 10)
        self.assertAlmostEqual(arc.boundingRect().width(), 20, delta=0.01)
        self.assertTrue(vector.parse_d("garbage").isEmpty())

    def test_boolean_operations(self):
        a, b = [rect(0, 0, 10, 10)], [rect(5, 0, 10, 10)]
        box = lambda op: vector.combine(op, [a, b])[0].path.boundingRect()
        self.assertEqual((box("union").width(), box("union").height()), (15, 10))
        self.assertEqual((box("subtract").x(), box("subtract").width()), (0, 5))
        self.assertEqual((box("intersect").x(), box("intersect").width()), (5, 5))
        xor = vector.combine("xor", [a, b])[0].path
        self.assertFalse(xor.contains(vector.QPointF(7, 5)))
        self.assertTrue(xor.contains(vector.QPointF(2, 5)) and xor.contains(vector.QPointF(12, 5)))
        self.assertEqual(len(vector.add([a, b])), 2)
        self.assertEqual(vector.combine("union", [a]), a)

    def test_boolean_is_painted_as_the_first_input(self):
        red = rect(0, 0, 10, 10)
        red.fill = (1.0, 0.0, 0.0, 1.0)
        out = vector.combine("union", [[red], [rect(5, 0, 10, 10)]])[0]
        self.assertEqual(out.fill, (1.0, 0.0, 0.0, 1.0))

    def test_svg_file_is_read(self):
        d = tempfile.mkdtemp()
        try:
            f = os.path.join(d, "a.svg")
            with open(f, "w") as fh:
                fh.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"><g transform="translate(10 0)">'
                         '<rect width="20" height="10" fill="#ff0000"/><circle cx="50" cy="25" r="5" style="fill:blue;stroke:#000;stroke-width:2"/>'
                         '<path d="M0 0L5 0L5 5Z" fill="none"/></g></svg>')
            layers, box = vector.load_svg(f)
            self.assertEqual((box.width(), box.height()), (100, 50))
            self.assertEqual(len(layers), 3)
            self.assertEqual(layers[0].fill, (1.0, 0.0, 0.0, 1.0))
            self.assertEqual(layers[0].path.boundingRect().x(), 10)
            self.assertEqual(layers[1].width, 2)
            self.assertIsNone(layers[2].fill)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class VectorPaintTests(unittest.TestCase):
    def test_gradient_and_picture_fills_are_kept_and_follow_the_outline(self):
        q = {"color": "#ff0000", "fill_type": "gradient", "fill_color2": "#0000ff", "fill_gtype": "linear", "fill_angle": 0}
        brush = vector.paint_of(q, "fill", 100, 100)
        path = QPainterPath()
        path.addRect(QRectF(-50, -50, 100, 100))
        layer = vector.Layer(path, brush).mapped(vector.QTransform().translate(100, 0))
        img = vector.render([layer], 300, 100, 1.0)
        left, right = img.pixelColor(210, 50), img.pixelColor(290, 50)        # (the shape is 200..300 in the picture: its colours go red to blue)
        self.assertGreater(left.red(), left.blue())
        self.assertGreater(right.blue(), right.red())
        self.assertNotEqual(vector.signature([layer]), vector.signature([vector.Layer(path, (1.0, 0.0, 0.0, 1.0))]))
        d = tempfile.mkdtemp()
        try:
            f = os.path.join(d, "g.png")
            im = vector.QImage(8, 8, vector.QImage.Format_ARGB32)
            im.fill(vector.QColor(0, 255, 0))
            im.save(f)
            green = vector.paint_of({"color": "#fff", "fill_type": "image", "fill_image": f}, "fill", 100, 100)
            out = vector.render([vector.Layer(path, green)], 100, 100, 1.0).pixelColor(50, 50)
            self.assertEqual((out.red(), out.green(), out.blue()), (0, 255, 0))
            plain = vector.paint_of({"color": "#00ff00", "fill_type": "image", "fill_image": "/nope.png"}, "fill", 100, 100)
            self.assertEqual(plain, (0.0, 1.0, 0.0, 1.0))                                   # (a picture that cannot be read: the colour)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class VectorGraphTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.e = edit.add_effect(self.p, "c1", fx.GRAPH)

    def add(self, **node):
        return edit.add_graph_node(self.p, "c1", self.e["id"], node)

    def test_vector_nodes_take_many_outlines(self):
        a = self.add(type="source", kind="shape", asset={"key": "shape.rect"})
        b = self.add(type="source", kind="shape", asset={"key": "shape.arrow"})
        v = self.add(type="source", kind="vector", op="add")
        g = self.e["graph"]
        self.assertEqual(ng.vecop_sockets(g["nodes"][v]), ["v1", "v2"])
        edit.connect_graph(self.p, "c1", self.e["id"], a, v, "v1")
        edit.connect_graph(self.p, "c1", self.e["id"], b, v, "v2")
        s3 = edit.node_item(self.p, "c1", self.e["id"], v, "add", src=a)
        self.assertEqual(s3, "v3")
        self.assertEqual(len([l for l in g["links"] if l["to"] == v]), 3)
        edit.node_item(self.p, "c1", self.e["id"], v, "remove", "v3")
        self.assertEqual(ng.vecop_sockets(g["nodes"][v]), ["v1", "v2"])
        with self.assertRaises(edit.EditError):
            edit.node_item(self.p, "c1", self.e["id"], v, "remove", "v2")
        self.assertEqual(self.e["sources"][v]["kind"], "vector")

    def test_only_outlines_go_into_a_vector_node(self):
        blur = self.add(type="filter", ref="builtin:blur")
        v = self.add(type="source", kind="vector", op="boolean")
        with self.assertRaises(edit.EditError):
            edit.connect_graph(self.p, "c1", self.e["id"], blur, v, "v1")
        with self.assertRaises(edit.EditError):
            edit.connect_graph(self.p, "c1", self.e["id"], "input", v, "v1")
        t = self.add(type="source", kind="text")
        edit.connect_graph(self.p, "c1", self.e["id"], t, v, "v1")
        w = self.add(type="source", kind="vector", op="add")
        edit.connect_graph(self.p, "c1", self.e["id"], v, w, "v1")               # (a vector node into another)
        edit.connect_graph(self.p, "c1", self.e["id"], v, "output", "src")        # (and its picture goes on like any)

    def test_boolean_has_its_operation(self):
        v = self.add(type="source", kind="vector", op="boolean")
        k = ng.param_key(v, "operation")
        self.assertEqual(self.e["params"][k], "聯集")
        self.assertEqual(ng.vecop_of(self.e["graph"]["nodes"][v], v, self.e["params"], 0), "union")
        self.e["params"][k] = "差集"
        self.assertEqual(ng.vecop_of(self.e["graph"]["nodes"][v], v, self.e["params"], 0), "subtract")
        add = self.add(type="source", kind="vector", op="add")
        self.assertEqual(ng.vecop_of(self.e["graph"]["nodes"][add], add, self.e["params"], 0), "add")


_SHARED = {}


class RenderBase(unittest.TestCase):
    """The scene and the renderers, made once (a second GL context in the same process can make the first one fail)."""
    @classmethod
    def setUpClass(cls):
        if not _SHARED:
            _SHARED["dir"] = tempfile.mkdtemp()
            _SHARED["scene"] = Scene(_SHARED["dir"])
            from kiasecut import glrender
            _SHARED["renderers"] = [render.Renderer()] + ([glrender.GLRenderer()] if HAVE_GL else [])
        cls.dir, cls.s, cls.renderers = _SHARED["dir"], _SHARED["scene"], _SHARED["renderers"]


class VectorRenderTests(RenderBase):
    def build(self, op, sizes):
        """A graph effect: a boolean of rectangles (x, w in clip fractions; all as tall as the clip), white, into the output."""
        p = proj()
        eff = edit.add_effect(p, "c1", fx.GRAPH)
        v = edit.add_graph_node(p, "c1", eff["id"], {"type": "source", "kind": "vector", "op": "boolean" if op != "add" else "add"})
        if op != "add":
            eff["params"][ng.param_key(v, "operation")] = op
        for i, (cx, w) in enumerate(sizes):
            n = edit.add_graph_node(p, "c1", eff["id"], {"type": "source", "kind": "shape", "asset": {"key": "shape.rect", "colors": ("#ffffff", "#000000")}})
            eff["sources"][n].update(cx=cx, w=w, h=1.0)
            edit.connect_graph(p, "c1", eff["id"], n, v, "v1" if i == 0 else "v2" if i == 1 else edit.node_item(p, "c1", eff["id"], v, "add"))
        edit.connect_graph(p, "c1", eff["id"], v, "output", "src")
        view = self.s.view()
        view["tracks"][0]["clips"][0]["effects"] = [eff]
        return view

    def pixels(self, view):
        out = []
        for r in self.renderers:
            img = r.render(view, 0, W, H)
            self.assertEqual(r.errors, [], type(r).__name__)
            out.append([rgb(img, x, H // 2) for x in (8, 24, 40, 56)])      # (a quarter of the clip each)
        return out

    def test_rotate_turns_a_vector_and_feeds_a_boolean(self):
        p = proj()
        eff = edit.add_effect(p, "c1", fx.GRAPH)
        rot = edit.add_graph_node(p, "c1", eff["id"], {"type": "source", "kind": "vector", "op": "rotate"})
        n = edit.add_graph_node(p, "c1", eff["id"], {"type": "source", "kind": "shape", "asset": {"key": "shape.rect", "colors": ("#ffffff", "#000000")}})
        eff["sources"][n].update(cx=0.0, w=1.0, h=0.25)                       # (a wide bar over the middle of the clip)
        edit.connect_graph(p, "c1", eff["id"], n, rot, "v1")
        edit.connect_graph(p, "c1", eff["id"], rot, "output", "src")
        with self.assertRaises(edit.EditError):
            edit.node_item(p, "c1", eff["id"], rot, "add")
        eff["params"][ng.param_key(rot, "angle")] = 90.0
        view = self.s.view()
        view["tracks"][0]["clips"][0]["effects"] = [eff]
        for r in self.renderers:
            img = r.render(view, 0, W, H)
            self.assertEqual(r.errors, [], type(r).__name__)
            self.assertEqual(rgb(img, W // 2, 2), WHITE, type(r).__name__)           # (now a tall bar: the top middle is covered)
            self.assertEqual(rgb(img, 3, H // 2), BLACK, type(r).__name__)

    def single(self, op, **params):
        p = proj()
        eff = edit.add_effect(p, "c1", fx.GRAPH)
        node = edit.add_graph_node(p, "c1", eff["id"], {"type": "source", "kind": "vector", "op": op})
        n = edit.add_graph_node(p, "c1", eff["id"], {"type": "source", "kind": "shape", "asset": {"key": "shape.rect", "colors": ("#ffffff", "#000000")}})
        eff["sources"][n].update(cx=0.0, w=0.25, h=1.0)                       # (a bar a quarter of the clip wide, in the middle)
        edit.connect_graph(p, "c1", eff["id"], n, node, "v1")
        edit.connect_graph(p, "c1", eff["id"], node, "output", "src")
        for k, v in params.items():
            eff["params"][ng.param_key(node, k)] = v
        view = self.s.view()
        view["tracks"][0]["clips"][0]["effects"] = [eff]
        return view, eff, node

    def test_move_and_scale_a_vector(self):
        view, eff, node = self.single("move", offset=[720.0, 0.0])           # (canvas px: the 1920 px canvas is 64 px here)
        for r in self.renderers:
            img = r.render(view, 0, W, H)
            self.assertEqual(r.errors, [], type(r).__name__)
            self.assertEqual((rgb(img, 12, 18), rgb(img, 52, 18)), (BLACK, WHITE), type(r).__name__)      # (the bar is on the right now)
        view, _, _ = self.single("scale", factor=[4.0, 1.0])
        for r in self.renderers:
            img = r.render(view, 0, W, H)
            self.assertEqual((rgb(img, 12, 18), rgb(img, 52, 18)), (WHITE, WHITE), type(r).__name__)
        view, _, _ = self.single("scale", factor=[0.5, 1.0], about="畫面中心")
        for r in self.renderers:
            self.assertEqual(rgb(r.render(view, 0, W, H), 12, 18), BLACK, type(r).__name__)

    def test_a_number_node_linked_into_scale_or_move_gives_x_and_y(self):
        p = proj()
        eff = edit.add_effect(p, "c1", fx.GRAPH)
        node = edit.add_graph_node(p, "c1", eff["id"], {"type": "source", "kind": "vector", "op": "scale"})
        n = edit.add_graph_node(p, "c1", eff["id"], {"type": "source", "kind": "shape", "asset": {"key": "shape.rect", "colors": ("#ffffff", "#000000")}})
        eff["sources"][n].update(cx=0.0, w=0.25, h=0.25)
        val = edit.add_graph_node(p, "c1", eff["id"], {"type": "filter", "ref": "builtin:nodes/value"})
        eff["params"][ng.param_key(val, "value")] = 4.0
        edit.connect_graph(p, "c1", eff["id"], n, node, "v1")
        edit.connect_graph(p, "c1", eff["id"], val, node, ng.PARAM + "factor")
        edit.connect_graph(p, "c1", eff["id"], node, "output", "src")
        view = self.s.view()
        view["tracks"][0]["clips"][0]["effects"] = [eff]
        for r in self.renderers:
            img = r.render(view, 0, W, H)
            self.assertEqual(r.errors, [], type(r).__name__)
            self.assertEqual((rgb(img, 12, 18), rgb(img, 32, 4)), (WHITE, WHITE), type(r).__name__)      # (4 times as wide and as tall)

    def test_union_subtract_intersect_xor(self):
        a, b = (-0.25, 0.75), (0.25, 0.75)         # (cx in half-frame units, w as a fraction: A covers the left 3/4 of the clip, B the right 3/4)
        want = {"聯集": [WHITE] * 4, "差集": [WHITE, BLACK, BLACK, BLACK], "交集": [BLACK, WHITE, WHITE, BLACK],
                "排除": [WHITE, BLACK, BLACK, WHITE]}
        for op, expected in want.items():
            for got in self.pixels(self.build(op, [a, b])):
                self.assertEqual(got, expected, op)

    def test_add_puts_them_together_and_three_inputs_work(self):
        for got in self.pixels(self.build("add", [(-0.75, 0.25), (-0.25, 0.25), (0.75, 0.25)])):
            self.assertEqual(got, [WHITE, WHITE, BLACK, WHITE])


class VectorTextAndSvgTests(RenderBase):
    def test_a_text_gives_its_glyph_outlines_where_the_text_node_draws_them(self):
        p = proj()
        eff = edit.add_effect(p, "c1", fx.GRAPH)
        v = edit.add_graph_node(p, "c1", eff["id"], {"type": "source", "kind": "vector", "op": "add"})
        t = edit.add_graph_node(p, "c1", eff["id"], {"type": "source", "kind": "text"})
        eff["sources"][t]["content"] = "█"
        eff["params"][ng.param_key(t, "size")] = 12.0
        edit.connect_graph(p, "c1", eff["id"], t, v, "v1")
        edit.connect_graph(p, "c1", eff["id"], v, "output", "src")
        view = self.s.view()
        view["tracks"][0]["clips"][0]["effects"] = [eff]
        for r in self.renderers:
            img = r.render(view, 0, W, H)
            self.assertEqual(r.errors, [], type(r).__name__)
            self.assertEqual(rgb(img, W // 2, H // 2), WHITE, type(r).__name__)
            self.assertEqual(rgb(img, 2, 2), BLACK, type(r).__name__)

    def test_an_svg_node_is_offered_svg_files_only(self):
        pr = proj()
        eff = edit.add_effect(pr, "c1", fx.GRAPH)
        n = edit.add_graph_node(pr, "c1", eff["id"], {"type": "source", "kind": "image", "svg": True})
        self.assertTrue(eff["graph"]["nodes"][n]["svg"])
        plain = edit.add_graph_node(pr, "c1", eff["id"], {"type": "source", "kind": "image"})
        self.assertNotIn("svg", eff["graph"]["nodes"][plain])


class OverscanTests(RenderBase):
    def graph(self, ref, params, overscan=None):
        p = proj()
        eff = edit.add_effect(p, "c1", fx.GRAPH)
        n = edit.add_graph_node(p, "c1", eff["id"], {"type": "source", "kind": "shape", "asset": {"key": "shape.rect", "colors": ("#ffffff", "#000000")}})
        eff["sources"][n].update(cx=0.0, w=4.0, h=4.0)                       # (four times the frame: most of it is outside)
        t = edit.add_graph_node(p, "c1", eff["id"], {"type": "filter", "ref": ref})
        for k, v in params.items():
            eff["params"][ng.param_key(t, k)] = v
        edit.connect_graph(p, "c1", eff["id"], n, t, "src")
        edit.connect_graph(p, "c1", eff["id"], t, "output", "src")
        if overscan is not None:
            eff["overscan"] = overscan
        view = self.s.view()
        view["tracks"][0]["clips"][0]["effects"] = [eff]
        return view

    def pixels_of(self, view):
        out = []
        for r in self.renderers:
            img = r.render(view, 0, W, H)
            self.assertEqual(r.errors, [], type(r).__name__)
            out.append((rgb(img, 12, 18), rgb(img, 52, 18)))
        return out

    def test_what_a_transform_shrinks_back_into_the_frame_comes_from_outside_it(self):
        for ref, params in (("builtin:nodes/transform", {"zoom": 0.5}), ("builtin:transform", {"factor": [0.5, 0.5]}),
                            ("builtin:scale", {"factor": [0.5, 0.5]})):
            view = self.graph(ref, params)
            for got in self.pixels_of(view):
                self.assertEqual(got, (WHITE, WHITE), ref)                    # (auto: a margin)
            for got in self.pixels_of(self.graph(ref, params, 0)):
                self.assertEqual(got, (BLACK, BLACK), ref)                    # (no margin: the shape was cut at the frame first)

    def test_a_rotate_node_keeps_the_corners(self):
        view = self.graph("builtin:nodes/rotate", {"angle": 45.0})
        for got in self.pixels_of(view):
            self.assertEqual(got, (WHITE, WHITE))
        self.assertEqual(ng.overscan_fraction(self.graph("builtin:blur", {})["tracks"][0]["clips"][0]["effects"][0]["graph"]), 0.0)

    def test_the_setting_is_kept_and_checked(self):
        p = proj()
        eff = edit.add_effect(p, "c1", fx.GRAPH)
        edit.set_effect_overscan(p, "c1", eff["id"], 100)
        self.assertEqual(eff["overscan"], 100)
        edit.set_effect_overscan(p, "c1", eff["id"], "auto")
        self.assertNotIn("overscan", eff)
        with self.assertRaises(edit.EditError):
            edit.set_effect_overscan(p, "c1", eff["id"], 7)
        g = self.graph("builtin:nodes/transform", {"zoom": 0.5})["tracks"][0]["clips"][0]["effects"][0]["graph"]
        self.assertEqual((ng.overscan_fraction(g), ng.overscan_fraction(g, 0), ng.overscan_fraction(g, 25)), (0.5, 0.0, 0.25))
        g["nodes"]["glare"] = {"type": "filter", "ref": "builtin:blender_glare"}            # (a node that reads pixels by their place on the card: no margin on its own)
        self.assertEqual(ng.overscan_fraction(g), 0.0)
