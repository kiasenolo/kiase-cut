"""Effect parameters of a node effect that are words, a font, a curve or a gradient (the 輸入 node's empty socket let go on
a text node's 文字 / 字體, or on a curve's or gradient's row)."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("KIASECUT_PREVIEW_GL", "0")
os.environ.setdefault("KIASECUT_NODE_GL", "0")
from PySide6.QtCore import QSettings  # noqa: E402

QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, tempfile.mkdtemp())      # (the tests must not change the user's own settings)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())

from PySide6.QtWidgets import QApplication, QComboBox, QPlainTextEdit  # noqa: E402

from kiasecut import edit, fonts, fx, nodegraph as ng, project  # noqa: E402
from kiasecut.ui.effects_panel import EffectsPanel  # noqa: E402
from kiasecut.ui.node_editor import NodeEditor, WordsEdit, type_color, SOCKET_COLORS  # noqa: E402
from test_compound_mask import W, H, rgb  # noqa: E402
from test_edit import proj  # noqa: E402
import test_graph_effect as graph_tests  # noqa: E402

APP = QApplication.instance() or QApplication([])


class WordParamTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.e = edit.add_effect(self.p, "c1", fx.GRAPH)
        self.g = self.e["graph"]
        self.t = self.add({"type": "source", "kind": "text"})
        edit.set_effect_text(self.p, "c1", self.e["id"], self.t, content="自己的字", font_path="/x/own.ttf")

    def add(self, node):
        return edit.add_graph_node(self.p, "c1", self.e["id"], node)

    def expose(self, dst, socket, src="input"):
        return edit.expose_graph_param(self.p, "c1", self.e["id"], src, dst, socket)

    def spec(self, t=None, at=0):
        t = t or self.t
        return ng.text_of(self.g["nodes"][t], t, self.e["params"], at, ng.binds(self.g), self.e["sources"][t], self.g)

    def test_the_inputs_empty_socket_makes_words_and_font_parameters(self):
        a, b = self.expose(self.t, "content"), self.expose(self.t, "font")
        self.assertEqual([(x["name"], x["type"], x["label"], x["default"]) for x in ng.exposed(self.g)],
                         [("text", "string", "文字", "自己的字"), ("font", "font", "字體", "/x/own.ttf")])
        self.assertEqual((self.e["params"]["expose." + a], self.e["params"]["expose." + b]), ("自己的字", "/x/own.ttf"))
        self.assertIsNone(ng.check(self.g))
        self.e["params"]["expose." + a], self.e["params"]["expose." + b] = "改過", "/x/other.ttf"
        self.assertEqual((self.spec()["content"], self.spec()["font_path"]), ("改過", "/x/other.ttf"))
        self.assertTrue(ng.words_given(self.g, self.t, ng.TEXT_SOCKET))
        d = fx.def_of(self.e)                                                  # (the 效果 panel's rows)
        self.assertEqual([(q.type, q.label) for q in d.params[:2]], [("string", "文字"), ("font", "字體")])
        edit.remove_exposed_param(self.p, "c1", self.e["id"], a)                # (unbound: the node's own again)
        self.assertEqual(self.spec()["content"], "自己的字")
        self.assertFalse(ng.words_given(self.g, self.t, ng.TEXT_SOCKET))

    def test_one_parameter_feeds_several_texts_and_each_new_one_has_a_name_of_its_own(self):
        other = self.add({"type": "source", "kind": "text"})
        a = self.expose(self.t, "content")
        edit.connect_graph(self.p, "c1", self.e["id"], "input", other, "content", a)
        self.e["params"]["expose." + a] = "一起換"
        self.assertEqual((self.spec()["content"], self.spec(other)["content"]), ("一起換", "一起換"))
        b = self.expose(other, "content")
        self.assertEqual((a, b), ("text", "text2"))
        self.assertEqual([x["label"] for x in ng.exposed(self.g)], ["文字", "文字 2"])
        self.assertEqual(self.spec(other)["content"], "一起換")                  # (it starts as what the node showed)

    def test_it_starts_as_a_linked_string_node_says_and_takes_its_place(self):
        s = self.add({"type": "string", "value": "節點的字"})
        edit.connect_graph(self.p, "c1", self.e["id"], s, self.t, "content")
        a = self.expose(self.t, "content")
        self.assertEqual(self.e["params"]["expose." + a], "節點的字")
        self.assertEqual([l["from"] for l in self.g["links"] if l["to"] == self.t], ["input"])
        edit.connect_graph(self.p, "c1", self.e["id"], s, self.t, "content")    # (and a string node takes it back)
        self.assertEqual(self.spec()["content"], "節點的字")
        self.assertEqual(ng.binds(self.g), {})

    def test_the_params_node_and_a_link_dragged_out_of_the_socket(self):
        n = edit.add_graph_node_feeding(self.p, "c1", self.e["id"], {"type": ng.PARAMS}, 0, 0, self.t, "content")
        self.assertEqual(ng.binds(self.g), {(self.t, "content"): "text"})
        self.assertTrue(any(l["from"] == n for l in self.g["links"]))

    def test_parameters_made_by_hand_and_what_does_not_fit(self):
        s = edit.add_exposed_param(self.p, "c1", self.e["id"], "string")
        f = edit.add_exposed_param(self.p, "c1", self.e["id"], "font")
        c = edit.add_exposed_param(self.p, "c1", self.e["id"], "color")
        self.assertEqual((self.e["params"]["expose." + s], self.e["params"]["expose." + f]), ("文字", project.DEFAULT_FONT))
        connect = lambda name, sock, dst=None: edit.connect_graph(self.p, "c1", self.e["id"], "input", dst or self.t, sock, name)
        connect(s, "content")
        connect(f, "font")
        self.assertEqual((self.spec()["content"], self.spec()["font_path"]), ("文字", project.DEFAULT_FONT))
        math = self.add({"type": "filter", "ref": "builtin:nodes/math"})
        for name, sock, dst in ((s, "font", None), (f, "content", None), (c, "content", None), (s, "param:size", None),
                                (s, "src", "output"), (s, "param:value", math)):
            with self.assertRaises(edit.EditError, msg=(name, sock)):
                connect(name, sock, dst)

    def test_words_hold_keyframes(self):
        a = self.expose(self.t, "content")
        self.e["params"]["expose." + a] = {"keys": [[0, "前"], [1_000_000, "後"]]}
        self.assertEqual((self.spec(at=0)["content"], self.spec(at=999_999)["content"], self.spec(at=1_000_000)["content"]),
                         ("前", "前", "後"))

    def test_set_from_the_effects_panel_saved_and_opened_again(self):
        a = self.expose(self.t, "content")
        edit.set_param(self.p, "c1", "fx:" + self.e["id"], "expose." + a, "面板打的字", 0)
        self.assertEqual(self.e["params"]["expose." + a], "面板打的字")
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, "x.kiasecut.json")
        project.save(self.p, path)
        _, c = edit.find(project.load(path), "c1")
        got = next(x for x in c["effects"] if x["filter"] == fx.GRAPH)
        self.assertEqual(got["params"]["expose." + a], "面板打的字")
        self.assertEqual(ng.binds(got["graph"]), {(self.t, "content"): a})

    def test_the_fonts_of_parameters_are_the_projects_and_can_be_swapped(self):
        a = self.expose(self.t, "font")
        self.e["params"]["expose." + a] = {"keys": [[0, "/x/k0.ttf"], [10, "/x/k1.ttf"]]}
        self.assertTrue({"/x/k0.ttf", "/x/k1.ttf", "/x/own.ttf"} <= fonts.used(self.p))
        edit.replace_fonts(self.p, {"/x/k1.ttf": "/y/new.ttf", "/x/own.ttf": "/y/o.ttf"})
        self.assertEqual([k[1] for k in self.e["params"]["expose." + a]["keys"]], ["/x/k0.ttf", "/y/new.ttf"])
        self.assertEqual(ng.exposed(self.g)[0]["default"], "/y/o.ttf")

    def test_curves_and_gradients_can_be_parameters_but_take_no_picture(self):
        curve = self.add({"type": "filter", "ref": "builtin:nodes/float_curve"})
        ramp = self.add({"type": "filter", "ref": "builtin:blender_color_ramp"})
        value = self.add({"type": "filter", "ref": "builtin:nodes/value"})
        for nid, kind in ((curve, "curve"), (ramp, "gradient")):
            q = next(q for q in fx.for_node(self.g["nodes"][nid]).params if q.type == kind)
            self.assertIn(("param:" + q.name, q.label), ng.sockets(self.g["nodes"][nid]))
            self.assertFalse(ng.takes_picture(self.g, nid, "param:" + q.name))
            with self.assertRaises(edit.EditError):
                edit.connect_graph(self.p, "c1", self.e["id"], value, nid, "param:" + q.name)
            before = self.e["params"][nid + "." + q.name]
            name = self.expose(nid, "param:" + q.name)
            self.assertEqual(self.e["params"]["expose." + name], before)
            self.assertIn(kind, [x.type for x in fx.def_of(self.e).params])


class WordParamPictureTests(graph_tests.GraphRenderTests):
    """On both renderers: the parameter's words are what is drawn."""

    def test_a_string_parameter_gives_the_text_node_its_words(self):
        view, eff, nid = self.text_view()
        g = eff["graph"]
        eff["sources"][nid]["content"] = " "                                                # (nothing to see of its own words)
        for r in self.renderers:
            self.assertEqual(rgb(r.render(view, 0, W, H), W // 2, H // 2), graph_tests.BLACK, type(r).__name__)
        name = ng.expose(g, eff["params"], "input", nid, ng.TEXT_SOCKET, eff["sources"])
        for words, want in (("█", graph_tests.WHITE), (" ", graph_tests.BLACK), ("█", graph_tests.WHITE)):    # (a change is drawn: nothing stale is kept)
            eff["params"]["expose." + name] = words
            for r in self.renderers:
                img = r.render(view, 0, W, H)
                self.assertEqual(r.errors, [], type(r).__name__)
                self.assertEqual(rgb(img, W // 2, H // 2), want, (type(r).__name__, words))

    def test_a_bound_curve_changes_the_picture(self):
        view, eff, nid = self.text_view(color=[0.5, 0.5, 0.5, 1.0])
        g = eff["graph"]
        c = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/rgb_curves"}, 0, 0)
        eff["params"].update({k: v for k, v in ng.default_params(g).items() if k.startswith(c + ".")})
        ng.connect(g, nid, c, "src")
        ng.connect(g, c, "output", "src")
        q = next(q for q in fx.for_node(g["nodes"][c]).params if q.type == "curve")
        name = ng.expose(g, eff["params"], "input", c, "param:" + q.name, eff["sources"])
        before = [rgb(r.render(view, 0, W, H), W // 2, H // 2) for r in self.renderers]
        eff["params"]["expose." + name] = [1.0, 0.0, 1.0, 0.0]                            # (the curve bent down: grey gets darker)
        for r, was in zip(self.renderers, before):
            img = r.render(view, 0, W, H)
            self.assertEqual(r.errors, [], type(r).__name__)
            self.assertNotEqual(rgb(img, W // 2, H // 2), was, type(r).__name__)


for _name in [n for n in dir(graph_tests.GraphRenderTests) if n.startswith("test_")]:     # (only the new ones here)
    setattr(WordParamPictureTests, _name, None) if _name not in WordParamPictureTests.__dict__ else None


class WordParamWidgetTests(unittest.TestCase):
    def clip(self):
        p = proj()
        e = edit.add_effect(p, "c1", fx.GRAPH)
        t = edit.add_graph_node(p, "c1", e["id"], {"type": "source", "kind": "text"}, 0, 200)
        a = edit.expose_graph_param(p, "c1", e["id"], "input", t, "content")
        b = edit.expose_graph_param(p, "c1", e["id"], "input", t, "font")
        return p, e, t, a, b

    def test_the_effects_panel_edits_them(self):
        p, e, t, a, b = self.clip()
        panel = EffectsPanel()
        self.addCleanup(panel.deleteLater)
        panel.set_fonts([{"name": "甲", "path": "/a.ttf"}, {"name": "乙", "path": "/b.ttf"}])
        got = []
        panel.paramEdited.connect(lambda ids, group, key, v: got.append((group, key, v)))
        c = edit.find(p, "c1")[1]
        panel.show_clips([c], 0, 30)
        words = panel.widgets[("fx:" + e["id"], "expose." + a)]
        self.assertIsInstance(words, QPlainTextEdit)
        self.assertEqual(words.toPlainText(), ng.TEXT_CONTENT)
        words.setPlainText("hi\nthere")
        panel._flush()
        self.assertEqual(got, [("fx:" + e["id"], "expose." + a, "hi\nthere")])
        font = panel.widgets[("fx:" + e["id"], "expose." + b)]
        self.assertIsInstance(font, QComboBox)
        self.assertEqual(font.currentData(), project.DEFAULT_FONT)
        i = font.findData("/b.ttf")
        font.setCurrentIndex(i)
        font.activated.emit(i)
        self.assertEqual(got[-1], ("fx:" + e["id"], "expose." + b, "/b.ttf"))

    def test_the_node_editor_shows_the_links_and_the_panels_defaults(self):
        p, e, t, a, b = self.clip()
        ed = NodeEditor()
        self.addCleanup(ed.deleteLater)
        ed.fonts = [{"name": "甲", "path": "/a.ttf"}]
        ed.resize(900, 500)
        ed.show()
        ed.show_clip(edit.find(p, "c1")[1])
        ed.set_panel(True)
        APP.processEvents()
        item = ed.view.items_by_id[t]
        for kind in ("text", "font"):
            row = next(r for r in item.rows if r["kind"] == kind)
            self.assertFalse(item.has_field(row))                    # (the parameter gives it: no box in the node)
        inp = ed.view.items_by_id["input"]
        self.assertEqual(inp.out_colour(a), SOCKET_COLORS["string"])
        self.assertEqual(inp.out_colour(b), SOCKET_COLORS["font"])
        self.assertEqual(type_color("string"), SOCKET_COLORS["string"])
        words = ed.panel.findChild(WordsEdit)
        edited = []
        ed.panel.edited.connect(lambda name, f: edited.append((name, f)))
        words.setPlainText("新預設")
        words.confirmed.emit()
        words.lost.emit()                                            # (asked once)
        self.assertEqual(edited, [(a, {"default": "新預設"})])

    def test_a_bound_curve_has_no_plot_in_the_node(self):
        p = proj()
        e = edit.add_effect(p, "c1", fx.GRAPH)
        c = edit.add_graph_node(p, "c1", e["id"], {"type": "filter", "ref": "builtin:nodes/float_curve"}, 0, 200)
        q = next(q for q in fx.for_node(e["graph"]["nodes"][c]).params if q.type == "curve")
        edit.expose_graph_param(p, "c1", e["id"], "input", c, "param:" + q.name)
        ed = NodeEditor()
        self.addCleanup(ed.deleteLater)
        ed.show()
        ed.show_clip(edit.find(p, "c1")[1])
        APP.processEvents()
        self.assertFalse([r for r in ed.view.items_by_id[c].rows if r["kind"] == "plot"])


if __name__ == "__main__":
    unittest.main()
