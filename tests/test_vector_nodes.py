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


class VectorRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.s = Scene(cls.dir)
        from kiasecut import glrender
        cls.renderers = [render.Renderer()] + ([glrender.GLRenderer()] if HAVE_GL else [])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

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
