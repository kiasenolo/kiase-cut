"""錨點 of a node effect's source (shape, text, picture): 位置 places it, and the object turns and is sized about it."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, nodegraph as ng  # noqa: E402
from test_compound_mask import HAVE_GL, Scene, W, H  # noqa: E402
from test_edit import S, proj  # noqa: E402
from test_graph_effect import BLACK, WHITE, GraphRenderTests  # noqa: E402
from test_preview_editing import NONE, preview  # noqa: E402

APP = QApplication.instance() or QApplication([])


class AnchorMathTests(unittest.TestCase):
    def test_the_anchor_is_what_cx_cy_place_and_what_it_turns_about(self):
        disp = (200.0, 100.0)
        src = {"cx": 0.0, "cy": 0.0, "anchor_x": -0.5, "anchor_y": 0.0, "rotation": 0.0}
        got = ng.centred(src, 40.0, 20.0, disp, 0)                    # its left edge in the middle: the centre 20 px right
        self.assertAlmostEqual(got["cx"], 0.2)
        self.assertAlmostEqual(got["cy"], 0.0)
        got = ng.centred(dict(src, rotation=90.0), 40.0, 20.0, disp, 0)    # turned clockwise: the centre 20 px below the anchor
        self.assertAlmostEqual(got["cx"], 0.0)
        self.assertAlmostEqual(got["cy"], -0.4)
        top = ng.centred(dict(src, anchor_x=0.0, anchor_y=0.5), 40.0, 20.0, disp, 0)
        self.assertAlmostEqual(top["cy"], -0.2)                        # (y up: the top edge)
        plain = {"cx": 0.3}
        self.assertIs(ng.centred(plain, 40.0, 20.0, disp, 0), plain)

    def test_nodes_have_the_anchor_as_sockets_and_keyframes(self):
        p = proj()
        e = edit.add_effect(p, "c1", "nodes:graph")
        for spec in ({"kind": "text"}, {"kind": "shape", "asset": {"key": "shape.rect"}}):
            nid = edit.add_graph_node(p, "c1", e["id"], dict(spec, type="source"))
            node = e["graph"]["nodes"][nid]
            self.assertIn(("param:anchor_x", "錨點 X"), ng.sockets(node))
            self.assertIn(("param:anchor_y", "錨點 Y"), ng.sockets(node))
        group = f"fxsrc:{e['id']}:{nid}"
        edit.set_param(p, "c1", group, "anchor_x", -0.5, 0)
        edit.set_effect_source(p, "c1", e["id"], nid, "shape")
        self.assertEqual(e["sources"][nid]["anchor_x"], -0.5)         # (kept when the shape is chosen again)


@unittest.skipUnless(HAVE_GL, "no OpenGL")
class AnchorRenderTests(GraphRenderTests):
    def test_a_shape_with_its_anchor_on_the_left_edge_starts_at_its_place(self):
        view, eff, nid = self.shape_view()
        eff["sources"][nid].update(anchor_x=-0.5)                     # half as wide as the picture: from the middle rightwards
        for name, got in self.pixels(view, (W // 2 - 4, H // 2), (W // 2 + 4, H // 2), (W - 4, H // 2)):
            self.assertEqual(got, [BLACK, WHITE, WHITE], name)
        eff["sources"][nid]["rotation"] = 180.0                       # half a turn about that edge: leftwards
        for name, got in self.pixels(view, (W // 2 - 4, H // 2), (W // 2 + 4, H // 2)):
            self.assertEqual(got, [WHITE, BLACK], name)

    def test_a_picture_node_with_its_anchor_on_the_top_edge_hangs_from_its_place(self):
        p_ = proj()
        eff = edit.add_effect(p_, "c1", "nodes:graph")
        nid = edit.add_graph_node(p_, "c1", eff["id"], {"type": "source", "kind": "image"})
        edit.set_effect_source_media(p_, "c1", eff["id"], nid, image=(self.s.blue, 160, 90))
        edit.connect_graph(p_, "c1", eff["id"], nid, "output", "src")
        eff["sources"][nid].update(w=0.5, h=0.5, anchor_y=0.5)         # from the middle downwards
        view = self.s.view()
        view["tracks"][0]["clips"][0]["effects"] = [eff]
        for name, got in self.pixels(view, (W // 2, H // 2 - 3), (W // 2, H // 2 + 3), (W // 2, H - 3)):
            self.assertEqual(got, [BLACK, (0, 0, 255), (0, 0, 255)], name)

    def test_a_text_with_its_anchor_on_the_right_edge_ends_at_its_place(self):
        view, eff, nid = self.text_view()
        eff["sources"][nid].update(anchor_x=0.5)
        for name, got in self.pixels(view, (W // 2 - 4, H // 2), (W // 2 + 4, H // 2)):
            self.assertEqual(got, [WHITE, BLACK], name)

    def test_a_shape_in_a_vector_node_keeps_its_anchor(self):
        view, eff, nid = self.shape_view()
        eff["sources"][nid].update(anchor_x=-0.5)
        v = ng.add_node(eff["graph"], {"type": "source", "kind": ng.VECTOR, "op": "add"})
        eff["sources"][v] = {"kind": ng.VECTOR, "cx": 0.0, "cy": 0.0, "w": 1.0, "h": 1.0, "rotation": 0.0}
        ng.connect(eff["graph"], nid, v, "v1")
        ng.connect(eff["graph"], v, "output", "src")
        for name, got in self.pixels(view, (W // 2 - 4, H // 2), (W // 2 + 4, H // 2), (W - 4, H // 2)):
            self.assertEqual(got, [BLACK, WHITE, WHITE], name)


for _name in [n for n in dir(GraphRenderTests) if n.startswith("test_") and n not in AnchorRenderTests.__dict__]:
    setattr(AnchorRenderTests, _name, None)                           # (only the fixtures of the render tests are wanted)
del GraphRenderTests


class AnchorOnPreviewTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.e = edit.add_effect(self.p, "c1", "nodes:graph")
        self.nid = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "source", "kind": "shape", "asset": {"key": "shape.rect"}})
        self.e["sources"][self.nid].update(w=0.5, h=0.5)
        self.group = f"fxsrc:{self.e['id']}:{self.nid}"
        self.pv = preview(self.p, "c1")
        self.pv.set_mask_mode(True, self.group)
        self.pv.resize(960, 540)
        self.pv.show()
        self.addCleanup(self.pv.close)

    def geo(self):
        from kiasecut.ui.preview import MaskGeo
        box = self.pv.selected_box()
        return MaskGeo(box, self.pv.mask_of(box.clip))

    def drag(self, a, b, mods=NONE):
        got = []
        self.pv.paramsCommitted.connect(lambda *args: got.append(args))
        QTest.mousePress(self.pv, Qt.LeftButton, mods, a)
        QTest.mouseMove(self.pv, (a + b) / 2)
        QTest.mouseMove(self.pv, b)
        QTest.mouseRelease(self.pv, Qt.LeftButton, mods, b)
        self.pv.paramsCommitted.disconnect()
        return got[-1][1], got[-1][2]

    @staticmethod
    def px(pt):                                                     # (the canvas at half size)
        return QPoint(round(pt.x() / 2), round(pt.y() / 2))

    def apply(self, vals):
        for k, v in vals.items():
            edit.set_param(self.p, "c1", self.group, k, v, 0)
        self.pv.set_scene(self.p, S // 2, "c1")
        self.pv.set_mask_mode(True, self.group)

    def test_alt_drag_moves_the_anchor_and_not_the_object(self):
        g = self.geo()
        before, left = g.centre(), g.xf.map(QPointF(-g.hw, 0))
        group, vals = self.drag(self.px(g.anchor_pt()), self.px(left) + QPoint(2, 1), Qt.AltModifier)
        self.assertEqual(group, self.group)
        self.assertEqual((vals["anchor_x"], vals["anchor_y"]), (-0.5, 0.0))        # (it settles on the edge)
        self.apply(vals)
        g = self.geo()
        self.assertAlmostEqual(g.centre().x(), before.x(), delta=0.1)
        self.assertAlmostEqual(g.centre().y(), before.y(), delta=0.1)
        self.assertAlmostEqual(g.anchor_pt().x(), left.x(), delta=0.1)

        # sized by the right edge: the left one, where the anchor is, stays
        edge = max((pt for n, pt in g.handles(1.0) if n == "w"), key=lambda p: p.x())
        _group, vals = self.drag(self.px(edge), self.px(edge) + QPoint(60, 0))
        self.assertAlmostEqual(vals["w"], 0.5 * (edge.x() - left.x() + 120) / (edge.x() - left.x()), delta=0.003)
        self.apply(vals)
        g = self.geo()
        self.assertAlmostEqual(g.anchor_pt().x(), left.x(), delta=0.1)
        self.assertAlmostEqual(g.xf.map(QPointF(g.hw, 0)).x(), edge.x() + 120, delta=2)

        # turned: about the anchor
        rot = next(pt for n, pt in g.handles(2.0) if n == "rot")     # (2 canvas px to a widget px)
        _group, vals = self.drag(self.px(rot), self.px(rot) + QPoint(120, 60))
        self.apply(vals)
        h = self.geo()
        self.assertNotEqual(h.rot, 0.0)
        self.assertAlmostEqual(h.anchor_pt().x(), left.x(), delta=0.1)
        self.assertAlmostEqual(h.anchor_pt().y(), left.y(), delta=0.1)

    def test_half_is_the_edge_of_a_text_nodes_frame(self):
        nid = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "source", "kind": "text"})
        self.group = f"fxsrc:{self.e['id']}:{nid}"
        self.apply({"anchor_x": -0.5, "cx": -0.5})
        g = self.geo()
        left = g.xf.map(QPointF(-g.hw, 0))
        self.assertAlmostEqual(g.anchor_pt().x(), left.x(), delta=0.1)
        self.assertAlmostEqual(left.x(), 480.0, delta=0.1)              # (位置 X -0.5 on the 1920 px canvas)
        from kiasecut import render                                    # (and the words are drawn from that frame)
        r = render.Renderer()
        r.canvas_h = 1080
        src = self.e["sources"][nid]
        _pic, placed = r.text_source(self.e, nid, src, 0, (g.dw, g.dh), 1.0, 30.0)
        self.assertAlmostEqual(placed["cx"] * g.dw / 2, g.centre().x() - 960, delta=0.1)

    def test_moving_it_keeps_the_anchor_and_snaps_by_the_centre(self):
        self.apply({"anchor_x": -0.5, "cx": -0.5})                  # its centre in the middle of the picture
        g = self.geo()
        c = g.centre()
        _group, vals = self.drag(self.px(c) + QPoint(30, 30), self.px(c) + QPoint(24, 28))
        self.assertEqual((vals["cx"], vals["cy"]), (-0.5, 0.0))       # (2 px off: back on the middle)
        self.assertNotIn("anchor_x", vals)


if __name__ == "__main__":
    unittest.main()
