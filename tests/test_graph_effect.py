"""A node graph as an effect of a clip: edit operations, and the picture both renderers draw from it."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, fx, nodegraph as ng, render  # noqa: E402
from test_compound_mask import HAVE_GL, Scene, W, H, rgb  # noqa: E402
from test_edit import S, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
RED, BLUE, WHITE, BLACK = (255, 0, 0), (0, 0, 255), (255, 255, 255), (0, 0, 0)


class GraphEditTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.e = edit.add_effect(self.p, "c1", fx.GRAPH)

    def test_new_effect_has_a_valid_graph(self):
        self.assertEqual(self.e["filter"], fx.GRAPH)
        self.assertIsNone(ng.check(self.e["graph"]))

    def test_filter_node_gets_its_parameters(self):
        nid = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "filter", "ref": "builtin:nodes/math"})
        self.assertEqual(self.e["params"][nid + ".value"], 0.5)
        self.assertTrue(edit.has_param(self.p_clip(), "fx:" + self.e["id"], nid + ".value"))
        edit.remove_graph_node(self.p, "c1", self.e["id"], nid)
        self.assertFalse([k for k in self.e["params"] if k.startswith(nid)])

    def p_clip(self):
        return edit.find(self.p, "c1")[1]

    def test_source_node_is_a_placed_source(self):
        nid = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "source", "kind": "image"})
        self.assertEqual(self.e["sources"][nid]["kind"], "image")
        self.assertTrue(edit.has_param(self.p_clip(), f"fxsrc:{self.e['id']}:{nid}", "cx"))
        edit.remove_graph_node(self.p, "c1", self.e["id"], nid)
        self.assertNotIn("sources", self.e)

    def test_connect_errors_and_output_stays(self):
        a = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "filter", "ref": "builtin:nodes/math"})
        b = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "filter", "ref": "builtin:nodes/mix"})
        edit.connect_graph(self.p, "c1", self.e["id"], a, b, "src")
        with self.assertRaises(edit.EditError):
            edit.connect_graph(self.p, "c1", self.e["id"], b, a, "src")
        with self.assertRaises(edit.EditError):
            edit.remove_graph_node(self.p, "c1", self.e["id"], "output")
        edit.move_graph_nodes(self.p, "c1", self.e["id"], {a: (10, 20)})
        self.assertEqual((self.e["graph"]["nodes"][a]["x"], self.e["graph"]["nodes"][a]["y"]), (10.0, 20.0))
        edit.mute_graph_node(self.p, "c1", self.e["id"], a, True)
        self.assertTrue(self.e["graph"]["nodes"][a]["mute"])

    def test_copied_effect_keeps_its_graph(self):
        nid = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "filter", "ref": "builtin:nodes/math"})
        copy = edit.put_effect(self.p, "c1", self.e)
        self.assertIn(nid, copy["graph"]["nodes"])
        self.assertIn(nid + ".value", copy["params"])
        self.assertIsNot(copy["graph"], self.e["graph"])


class GraphPresetTests(unittest.TestCase):
    def test_saved_as_a_custom_effect_and_applied_again(self):
        from kiasecut import userlib
        p = proj()
        e = edit.add_effect(p, "c1", fx.GRAPH)
        m = edit.add_graph_node(p, "c1", e["id"], {"type": "filter", "ref": "builtin:nodes/mix"}, 30, 40)
        s = edit.add_graph_node(p, "c1", e["id"], {"type": "source", "kind": "image"})
        edit.connect_graph(p, "c1", e["id"], s, m, "b")
        edit.set_param(p, "c1", "fx:" + e["id"], m + ".fac", 0.4)
        with tempfile.TemporaryDirectory() as d:
            path = userlib.save_preset(d, "mine", [e])
            loaded = userlib.load_preset(path)
        self.assertEqual(len(loaded), 1)
        got = loaded[0]
        self.assertEqual(got["graph"], e["graph"])
        self.assertEqual(got["params"][m + ".fac"], 0.4)
        self.assertIn(s, got["sources"])
        copy = edit.put_effect(p, "c2", got)
        self.assertNotEqual(copy["id"], e["id"])
        self.assertIsNone(ng.check(copy["graph"]))


class GraphPanelTests(unittest.TestCase):
    def test_form_has_the_nodes_parameters_and_sources(self):
        from kiasecut.ui.effects_panel import EffectsPanel
        p = proj()
        e = edit.add_effect(p, "c1", fx.GRAPH)
        m = edit.add_graph_node(p, "c1", e["id"], {"type": "filter", "ref": "builtin:nodes/mix"}, 0, 0)
        s = edit.add_graph_node(p, "c1", e["id"], {"type": "source", "kind": "image"}, -100, 0)
        panel = EffectsPanel()
        opened = []
        panel.nodesRequested.connect(opened.append)
        panel.show_clips([edit.find(p, "c1")[1]], 0, 30)
        self.assertIn(("fx:" + e["id"], m + ".fac"), panel.widgets)
        self.assertIn(("source_media", "fx:" + e["id"], s), panel.widgets)
        edit.set_param(p, "c1", "fx:" + e["id"], m + ".fac", 0.25)
        panel.show_clips([edit.find(p, "c1")[1]], 0, 30)
        self.assertEqual(fx.def_of(e).params[1].name, m + ".fac")
        panel.nodesRequested.emit("x")
        self.assertEqual(opened, ["x"])


class GraphRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.s = Scene(cls.dir)
        from kiasecut import glrender
        cls.renderers = [render.Renderer()] + ([glrender.GLRenderer()] if HAVE_GL else [])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def view(self, graph_fn):
        """The scene's red clip with a graph effect that graph_fn(effect) builds."""
        v = self.s.view()
        e = fx.new_effect(fx.GRAPH, "e1")
        graph_fn(e)
        v["tracks"][0]["clips"][0]["effects"] = [e]
        return v

    def source(self, e, nid, path):
        e.setdefault("sources", {})[nid] = {"kind": "image", "image": path, "img_w": 160, "img_h": 90,
                                           "cx": 0.0, "cy": 0.0, "w": 1.0, "h": 1.0, "rotation": 0.0}

    def check(self, view, left, right):
        for r in self.renderers:
            img = r.render(view, 0, W, H)
            self.assertEqual(r.errors, [], type(r).__name__)
            got = (rgb(img, 12, 18), rgb(img, 52, 18))
            for g, want in zip(got, (left, right)):
                self.assertTrue(all(abs(a - b) <= 3 for a, b in zip(g, want)), f"{type(r).__name__}: {got} != {(left, right)}")

    def test_empty_graph_changes_nothing(self):
        self.check(self.view(lambda e: None), RED, RED)

    def test_picture_node_over_the_input(self):
        def build(e):
            g = e["graph"]
            s = ng.add_node(g, {"type": "source", "kind": "image"}, base="s")
            m = ng.add_node(g, {"type": "filter", "ref": "builtin:nodes/mix"})
            ng.connect(g, "input", m, "src")
            ng.connect(g, s, m, "b")
            ng.connect(g, m, "output", "src")
            e["params"].update(ng.default_params(g))
            self.source(e, s, self.s.blue)
        self.check(self.view(build), BLUE, BLUE)

        def half(e):
            build(e)
            self.source(e, "s1", self.s.alpha)              # left half opaque white, right see-through
        self.check(self.view(half), WHITE, RED)

    def test_filter_node_chain_and_mix_amount(self):
        def build(e):
            g = e["graph"]
            n = ng.add_node(g, {"type": "filter", "ref": "builtin:invert"})
            ng.connect(g, "input", n, "src")
            ng.connect(g, n, "output", "src")
            e["params"].update(ng.default_params(g))
        self.check(self.view(build), (0, 255, 255), (0, 255, 255))
        v = self.view(build)
        v["tracks"][0]["clips"][0]["effects"][0]["mix"] = 0.5
        self.check(v, (128, 128, 128), (128, 128, 128))


if __name__ == "__main__":
    unittest.main()
