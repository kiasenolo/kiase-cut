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

from kiasecut import edit, fx, nodegraph as ng, project, render  # noqa: E402
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

    def test_shape_node_edits(self):
        nid = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "source", "kind": "shape", "shape": "star"})
        self.assertEqual(self.e["sources"][nid]["shape"], "star")
        edit.set_effect_shape(self.p, "c1", self.e["id"], nid, "heart", [1, 0, 0, 1])
        self.assertEqual((self.e["sources"][nid]["shape"], self.e["sources"][nid]["color"]), ("heart", [1.0, 0.0, 0.0, 1.0]))
        with self.assertRaises(edit.EditError):
            edit.set_effect_shape(self.p, "c1", self.e["id"], nid, "blob")
        self.assertTrue(edit.has_param(self.p_clip(), f"fxsrc:{self.e['id']}:{nid}", "cx"))

    def test_text_node_edits(self):
        nid = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "source", "kind": "text"})
        node = self.e["graph"]["nodes"][nid]
        self.assertTrue(ng.is_text(node))
        self.assertEqual(self.e["sources"][nid]["content"], ng.TEXT_CONTENT)
        names = [q.name for q in ng.text_def(node).params]
        for name in ("size", "color", "stroke", "box_w", "shadow_blur", "bg_radius", "align", "italic_deg"):    # (what the text tool has)
            self.assertIn(name, names)
            self.assertIn(nid + "." + name, self.e["params"])
        self.assertIn(("param:size", "字號"), ng.sockets(node))
        edit.set_effect_text(self.p, "c1", self.e["id"], nid, content="你好\nworld", font_path="/x/y.ttf")
        self.assertEqual((self.e["sources"][nid]["content"], self.e["sources"][nid]["font_path"]), ("你好\nworld", "/x/y.ttf"))
        edit.set_effect_text(self.p, "c1", self.e["id"], nid, content="again")
        self.assertEqual(self.e["sources"][nid]["font_path"], "/x/y.ttf")
        spec = ng.text_of(node, nid, self.e["params"], 0, None, self.e["sources"][nid])
        self.assertEqual((spec["content"], spec["align"], spec["stroke_align"], spec["valign"]), ("again", "center", "inside", "top"))
        with self.assertRaises(edit.EditError):
            edit.set_effect_text(self.p, "c1", self.e["id"], "output", content="x")
        other = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "filter", "ref": "builtin:nodes/math"})
        with self.assertRaises(ng.GraphError):                                 # (a value is fed by the effect's own parameters only)
            ng.connect(self.e["graph"], other, nid, "param:size")
        edit.remove_graph_node(self.p, "c1", self.e["id"], nid)
        self.assertFalse([k for k in self.e["params"] if k.startswith(nid + ".")])

    def test_string_node_feeds_a_text_node(self):
        t = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "source", "kind": "text"})
        a = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "string", "value": "多個文字"})
        b = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "string"})
        g = self.e["graph"]
        self.assertEqual((g["nodes"][a]["value"], g["nodes"][b]["value"], ng.title(g["nodes"][a])), ("多個文字", "文字", "字串"))
        self.assertEqual(ng.outputs(g["nodes"][a]), [("", "字串")])
        self.assertIn(("content", "文字"), ng.sockets(g["nodes"][t]))
        edit.connect_graph(self.p, "c1", self.e["id"], a, t, "content")
        spec = lambda: ng.text_of(g["nodes"][t], t, self.e["params"], 0, None, self.e["sources"][t], g)
        self.assertEqual(spec()["content"], "多個文字")
        edit.connect_graph(self.p, "c1", self.e["id"], b, t, "content")                 # (a socket takes one link: the new one replaces it)
        self.assertEqual([l["from"] for l in g["links"] if l["to"] == t], [b])
        edit.set_graph_string(self.p, "c1", self.e["id"], b, "line 1\nline 2")
        self.assertEqual(spec()["content"], "line 1\nline 2")
        edit.remove_graph_node(self.p, "c1", self.e["id"], b)
        self.assertEqual(spec()["content"], ng.TEXT_CONTENT)                            # (unlinked: the node's own words again)
        with self.assertRaises(edit.EditError):                                        # (words are no picture, a picture no words)
            edit.connect_graph(self.p, "c1", self.e["id"], a, "output", "src")
        math = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "filter", "ref": "builtin:nodes/math"})
        with self.assertRaises(edit.EditError):
            edit.connect_graph(self.p, "c1", self.e["id"], math, t, "content")
        with self.assertRaises(edit.EditError):
            edit.set_graph_string(self.p, "c1", self.e["id"], math, "x")

    def test_font_node_feeds_a_text_node(self):
        t = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "source", "kind": "text"})
        f = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "font", "value": "/x/a.ttf"})
        d = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "font"})
        s = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "string"})
        g = self.e["graph"]
        self.assertEqual((g["nodes"][f]["value"], g["nodes"][d]["value"], ng.title(g["nodes"][f])), ("/x/a.ttf", project.DEFAULT_FONT, "字體"))
        self.assertEqual(ng.outputs(g["nodes"][f]), [("", "字體")])
        self.assertIn(("font", "字體"), ng.sockets(g["nodes"][t]))
        edit.set_effect_text(self.p, "c1", self.e["id"], t, font_path="/x/own.ttf")
        spec = lambda: ng.text_of(g["nodes"][t], t, self.e["params"], 0, None, self.e["sources"][t], g)
        self.assertEqual(spec()["font_path"], "/x/own.ttf")
        edit.connect_graph(self.p, "c1", self.e["id"], f, t, "font")
        self.assertEqual(spec()["font_path"], "/x/a.ttf")
        edit.set_graph_font(self.p, "c1", self.e["id"], f, "/x/b.ttf")
        self.assertEqual(spec()["font_path"], "/x/b.ttf")
        edit.connect_graph(self.p, "c1", self.e["id"], s, t, "content")                 # (both constants at once)
        self.assertEqual((spec()["content"], spec()["font_path"]), ("文字", "/x/b.ttf"))
        for src, socket in ((f, "content"), (s, "font"), (f, "src")):                    # (each goes to its own socket only)
            with self.assertRaises(edit.EditError):
                edit.connect_graph(self.p, "c1", self.e["id"], src, t if socket != "src" else "output", socket)
        with self.assertRaises(edit.EditError):
            edit.set_graph_font(self.p, "c1", self.e["id"], s, "/x")
        edit.remove_graph_node(self.p, "c1", self.e["id"], f)
        self.assertEqual(spec()["font_path"], "/x/own.ttf")

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

    def test_saved_and_opened_again(self):
        """A node effect is not a filter file: its ref must not be made a path of the project folder."""
        p = proj()
        e = edit.add_effect(p, "c1", fx.GRAPH)
        edit.add_graph_node(p, "c1", e["id"] if isinstance(e, dict) else e, {"type": "filter", "ref": "builtin:nodes/math"}, 10, 20)
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, "x.kiasecut.json")
        project.save(p, path)
        _, c = edit.find(project.load(path), "c1")
        got = [x for x in c["effects"] if x["filter"] == fx.GRAPH]
        self.assertEqual(len(got), 1)
        self.assertIn("math1", got[0]["graph"]["nodes"])

    def test_built_in_shape_node_edits(self):
        nid = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "source", "kind": "shape", "asset": {"key": "shape.arrow"}})
        self.assertTrue(ng.is_asset(self.e["graph"]["nodes"][nid]))
        self.assertIn(nid + ".stroke", self.e["params"])
        src = self.e["sources"][nid]
        self.assertAlmostEqual(src["h"] / src["w"], 300 / 480, 3)               # the preset's proportions
        with self.assertRaises(edit.EditError):
            edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "source", "kind": "shape", "asset": {"key": "solid.0"}})
        edit.remove_graph_node(self.p, "c1", self.e["id"], nid)
        self.assertFalse([k for k in self.e["params"] if k.startswith(nid + ".")])

    def test_dropped_built_in_shape(self):
        """A shape dragged from the 內建素材 tab into the node editor becomes a shape node with its colours."""
        import types
        from kiasecut import assets
        from kiasecut.ui.main_window import MainWindow
        p, eid = self.p, self.e["id"]
        picked = []
        h = types.SimpleNamespace(node_clip=lambda: "c1", apply=lambda _n, fn: fn(p) or True, proj=p,
                                  nodes=types.SimpleNamespace(level=None, select=picked.append),
                                  statusBar=lambda: types.SimpleNamespace(showMessage=lambda *a: None))
        MainWindow.on_node_media(h, eid, [assets.ident("shape.star", "#ff8800", "#00ff00"), assets.ident("solid.0", "#fff", "#000")],
                                 [], 10, 20)
        self.assertEqual(len(picked), 1)                                          # (a solid is no shape)
        nid = picked[0]
        self.assertEqual(self.e["graph"]["nodes"][nid]["asset"]["key"], "shape.star")
        self.assertEqual(self.e["params"][nid + ".color"], list(assets.to_rgba("#ff8800")))
        self.assertEqual(self.e["params"][nid + ".stroke_color"], list(assets.to_rgba("#00ff00")))
        self.assertEqual(self.e["params"][nid + ".points"], 5.0)

    def test_new_pasted_and_duplicated_nodes_are_carried(self):
        """The handlers hand what they made to the editor to stick to the pointer (apply returns None for these, as the real one)."""
        import types
        from kiasecut.ui.main_window import MainWindow
        p, eid = self.p, self.e["id"]
        carried = []
        h = types.SimpleNamespace(node_clip=lambda: "c1", apply=lambda _n, fn: (fn(p), None)[1], proj=p,
                                  nodes=types.SimpleNamespace(level=None, carry=lambda ids, remove=True: carried.append((list(ids), remove))))
        MainWindow.on_node_add(h, eid, {"type": "filter", "ref": "builtin:nodes/math"}, 10.0, 20.0)
        nid = carried[-1][0][0]
        self.assertEqual((carried[-1][1], nid in self.e["graph"]["nodes"]), (True, True))
        MainWindow.on_node_duplicate(h, eid, [nid])
        self.assertEqual((len(carried[-1][0]), carried[-1][1]), (1, False))                 # (a duplicate is not taken back)
        MainWindow.on_node_paste(h, eid, ng.pack(self.e["graph"], [nid]), 5.0, 5.0)
        self.assertEqual(len(carried), 3)

    def test_node_item_edits(self):
        m = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "filter", "ref": "builtin:nodes/menu_switch"})
        sock = edit.node_item(self.p, "c1", self.e["id"], m, "add", name="貓", src="input")
        g = self.e["graph"]
        self.assertEqual([i["name"] for i in g["nodes"][m]["items"]], ["選項 1", "選項 2", "選項 3", "貓"])
        self.assertTrue(any(l["to"] == m and l["socket"] == sock for l in g["links"]))
        edit.node_item(self.p, "c1", self.e["id"], m, "rename", sock, "狗")
        self.assertEqual(g["nodes"][m]["items"][-1]["name"], "狗")
        edit.node_item(self.p, "c1", self.e["id"], m, "remove", sock)
        self.assertFalse(any(l["to"] == m and l["socket"] == sock for l in g["links"]))
        with self.assertRaises(edit.EditError):
            edit.node_item(self.p, "c1", self.e["id"], m, "nonsense")

    def test_copied_effect_keeps_its_graph(self):
        nid = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "filter", "ref": "builtin:nodes/math"})
        copy = edit.put_effect(self.p, "c1", self.e)
        self.assertIn(nid, copy["graph"]["nodes"])
        self.assertIn(nid + ".value", copy["params"])
        self.assertIsNot(copy["graph"], self.e["graph"])


class ExposedParamTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.e = edit.add_effect(self.p, "c1", fx.GRAPH)
        self.eid = self.e["id"]
        self.m = edit.add_graph_node(self.p, "c1", self.eid, {"type": "filter", "ref": "builtin:nodes/math"})
        self.n = edit.add_graph_node(self.p, "c1", self.eid, {"type": "params"})

    def test_dragging_from_the_empty_socket_makes_a_parameter(self):
        edit.set_param(self.p, "c1", "fx:" + self.eid, self.m + ".value", 0.8)
        name = edit.expose_graph_param(self.p, "c1", self.eid, self.n, self.m, "param:value")
        x = self.e["graph"]["exposed"][0]
        self.assertEqual((x["name"], x["type"], x["label"]), (name, "float", "B 的數值"))
        self.assertEqual(self.e["params"]["expose." + name], 0.8)             # (it starts at what the parameter had)
        self.assertNotIn(self.m + ".value", self.e["params"])
        names = [q.name for q in fx.def_of(self.e).params]
        self.assertIn("expose." + name, names)
        self.assertNotIn(self.m + ".value", names)                            # (the bound one is not a row of its own)
        self.assertEqual(ng.binds(self.e["graph"]), {(self.m, "param:value"): name})
        self.assertTrue(edit.has_param(edit.find(self.p, "c1")[1], "fx:" + self.eid, "expose." + name))

    def test_any_kind_of_parameter_can_be_exposed_and_a_second_one_gets_another_name(self):
        a = edit.expose_graph_param(self.p, "c1", self.eid, self.n, self.m, "param:value")
        m2 = edit.add_graph_node(self.p, "c1", self.eid, {"type": "filter", "ref": "builtin:nodes/math"})
        b = edit.expose_graph_param(self.p, "c1", self.eid, self.n, m2, "param:value")
        self.assertNotEqual(a, b)
        c = edit.expose_graph_param(self.p, "c1", self.eid, self.n, self.m, "param:clamp_on")     # a tick
        d = edit.expose_graph_param(self.p, "c1", self.eid, self.n, self.m, "param:op")           # a menu
        kinds = {x["name"]: x["type"] for x in self.e["graph"]["exposed"]}
        self.assertEqual((kinds[c], kinds[d]), ("bool", "menu"))

    def test_the_input_node_can_hold_the_parameters_too(self):
        a = edit.expose_graph_param(self.p, "c1", self.eid, "input", self.m, "param:value")
        g = self.e["graph"]
        self.assertEqual(ng.binds(g), {(self.m, "param:value"): a})
        self.assertEqual(ng.viewed(g), None)
        self.assertTrue(any(l["from"] == "input" and l.get("out") == a for l in g["links"]))

    def test_existing_parameter_to_another_node_of_the_same_kind_only(self):
        a = edit.expose_graph_param(self.p, "c1", self.eid, self.n, self.m, "param:value")
        m2 = edit.add_graph_node(self.p, "c1", self.eid, {"type": "filter", "ref": "builtin:nodes/math"})
        edit.connect_graph(self.p, "c1", self.eid, self.n, m2, "param:value", a)
        with self.assertRaises(edit.EditError):
            edit.connect_graph(self.p, "c1", self.eid, self.n, m2, "param:clamp_on", a)    # (a number into a tick)
        with self.assertRaises(edit.EditError):
            edit.connect_graph(self.p, "c1", self.eid, self.n, m2, "src", a)               # (a parameter is no picture)

    def test_a_picture_feeds_a_tick_or_a_menu_as_a_number_but_not_a_curve(self):
        edit.connect_graph(self.p, "c1", self.eid, "input", self.m, "param:clamp_on")       # (read as a number: above 0.5 is true)
        edit.connect_graph(self.p, "c1", self.eid, "input", self.m, "param:op")             # (and as the index of a menu's choice)
        h = edit.add_graph_node(self.p, "c1", self.eid, {"type": "filter", "ref": "builtin:blender_color_ramp"})
        with self.assertRaises(edit.EditError):
            edit.connect_graph(self.p, "c1", self.eid, "input", h, "param:ramp")             # (a gradient takes none)

    def test_removing_a_parameter_unbinds_it(self):
        a = edit.expose_graph_param(self.p, "c1", self.eid, self.n, self.m, "param:value")
        edit.remove_exposed_param(self.p, "c1", self.eid, a)
        self.assertEqual(ng.binds(self.e["graph"]), {})
        self.assertNotIn("expose." + a, self.e["params"])
        self.assertIn(self.m + ".value", [q.name for q in fx.def_of(self.e).params])

    def test_bound_value_drives_the_picture(self):
        if not HAVE_GL:
            self.skipTest("needs OpenGL 3.3")
        from kiasecut import glrender
        edit.connect_graph(self.p, "c1", self.eid, "input", self.m, "src")
        edit.connect_graph(self.p, "c1", self.eid, self.m, "output", "src")
        edit.set_param(self.p, "c1", "fx:" + self.eid, self.m + ".op", "相乘")
        a = edit.expose_graph_param(self.p, "c1", self.eid, self.n, self.m, "param:value")
        edit.set_param(self.p, "c1", "fx:" + self.eid, "expose." + a, 0.0)
        s = Scene(tempfile.mkdtemp())
        v = s.view()
        v["tracks"][0]["clips"][0]["effects"] = [self.e]
        for r in (render.Renderer(), glrender.GLRenderer()):
            self.assertEqual(rgb(r.render(v, 0, W, H), 12, 18), BLACK, type(r).__name__)      # red x 0 (a float: its brightness)
        self.e["params"]["expose." + a] = 1.0
        for r in (render.Renderer(), glrender.GLRenderer()):
            got = rgb(r.render(v, 0, W, H), 12, 18)
            self.assertTrue(all(abs(c - 54) <= 2 for c in got), f"{type(r).__name__}: {got}")    # red x 1: its brightness, grey

    def test_reroute_keeps_the_picture_going(self):
        edit.connect_graph(self.p, "c1", self.eid, "input", "output", "src")
        edit.add_graph_reroutes(self.p, "c1", self.eid, [(10, 10, "input", "output", "src", "")])
        kinds = [n["type"] for n in self.e["graph"]["nodes"].values()]
        self.assertEqual(kinds.count("reroute"), 1)
        self.assertIsNone(ng.check(self.e["graph"]))
        if HAVE_GL:
            from kiasecut import glrender
            s = Scene(tempfile.mkdtemp())
            v = s.view()
            v["tracks"][0]["clips"][0]["effects"] = [self.e]
            for r in (render.Renderer(), glrender.GLRenderer()):
                self.assertEqual(rgb(r.render(v, 0, W, H), 12, 18), RED, type(r).__name__)

    def test_frame_is_a_note_that_changes_nothing(self):
        edit.connect_graph(self.p, "c1", self.eid, "input", "output", "src")
        fid = edit.add_graph_node(self.p, "c1", self.eid, {"type": "frame", "w": 100, "h": 80}, 5, 6)
        edit.set_graph_frame(self.p, "c1", self.eid, fid, label="註", text="x", color="red", w=10)
        n = self.e["graph"]["nodes"][fid]
        self.assertEqual((n["label"], n["text"], n["color"], n["w"], n["h"]), ("註", "x", "red", 60.0, 80.0))
        self.assertIsNone(ng.check(self.e["graph"]))
        if HAVE_GL:
            from kiasecut import glrender
            s = Scene(tempfile.mkdtemp())
            v = s.view()
            v["tracks"][0]["clips"][0]["effects"] = [self.e]
            for r in (render.Renderer(), glrender.GLRenderer()):
                self.assertEqual(rgb(r.render(v, 0, W, H), 12, 18), RED, type(r).__name__)

    def test_paste_into_another_effect(self):
        m = edit.add_graph_node(self.p, "c1", self.eid, {"type": "filter", "ref": "builtin:nodes/math"}, 100, 50)
        key = [k for k in self.e["params"] if k.startswith(m + ".")][0]
        self.e["params"][key] = 0.25
        pack = ng.pack(self.e["graph"], [m, "output"], self.e["params"], self.e.get("sources"))
        self.assertEqual(list(pack["nodes"]), [m])
        other = edit.add_effect(self.p, "c1", fx.GRAPH)
        made = edit.paste_graph_nodes(self.p, "c1", other["id"], pack, 7, 9)
        self.assertEqual(len(made), 1)
        self.assertEqual(other["params"][made[0] + key[len(m):]], 0.25)
        self.assertEqual((other["graph"]["nodes"][made[0]]["x"], other["graph"]["nodes"][made[0]]["y"]), (7.0, 9.0))

    def test_group_edits(self):
        before = set(self.e["graph"]["nodes"])
        a = edit.add_graph_node(self.p, "c1", self.eid, {"type": "filter", "ref": "builtin:nodes/math"}, 100, 0)
        edit.connect_graph(self.p, "c1", self.eid, "input", a, "src")
        edit.connect_graph(self.p, "c1", self.eid, a, "output", "src")
        gid = edit.group_graph_nodes(self.p, "c1", self.eid, [a], "我的群組")
        self.assertEqual(self.e["graph"]["nodes"][gid]["label"], "我的群組")
        b = edit.add_graph_node(self.p, "c1", self.eid, {"type": "filter", "ref": "builtin:nodes/mix", "group": gid}, 150, 0)
        self.assertEqual(self.e["graph"]["nodes"][b]["group"], gid)
        name = edit.group_port(self.p, "c1", self.eid, gid, b, socket="b")
        out = edit.group_port(self.p, "c1", self.eid, gid, b, out="")
        edit.connect_graph(self.p, "c1", self.eid, "input", gid, name)
        self.assertIsNone(ng.check(self.e["graph"]))
        edit.group_unplug(self.p, "c1", self.eid, gid, output=out)
        edit.remove_graph_node(self.p, "c1", self.eid, gid)           # members and their settings go too
        self.assertEqual(set(self.e["graph"]["nodes"]), before)
        self.assertFalse([k for k in self.e["params"] if k.startswith(a + ".")])
        gid = edit.group_graph_nodes(self.p, "c1", self.eid, ["input"])
        edit.ungroup_graph(self.p, "c1", self.eid, gid)
        self.assertNotIn(gid, self.e["graph"]["nodes"])

    def test_viewer_edit(self):
        sep = edit.add_graph_node(self.p, "c1", self.eid, {"type": "filter", "ref": "builtin:nodes/separate_color"})
        edit.set_graph_viewer(self.p, "c1", self.eid, sep, "a")
        self.assertEqual(ng.viewed(self.e["graph"]), (sep, "a"))             # (a 預覽 node was made and linked)
        vid = next(i for i, n in self.e["graph"]["nodes"].items() if n["type"] == ng.VIEWER)
        edit.set_graph_viewer(self.p, "c1", self.eid, sep, "c2")
        self.assertEqual(ng.viewed(self.e["graph"]), (sep, "c2"))            # (the same node, linked again)
        self.assertEqual([i for i, n in self.e["graph"]["nodes"].items() if n["type"] == ng.VIEWER], [vid])
        with self.assertRaises(edit.EditError):
            edit.set_graph_viewer(self.p, "c1", self.eid, sep, "nope")
        self.assertIsNone(ng.check(self.e["graph"]))
        edit.remove_graph_node(self.p, "c1", self.eid, sep)
        self.assertIsNone(ng.viewed(self.e["graph"]))
        edit.set_graph_viewer(self.p, "c1", self.eid, "input", "")
        edit.set_graph_viewer(self.p, "c1", self.eid, None)
        self.assertIsNone(ng.viewed(self.e["graph"]))

    def test_insert_dissolve_duplicate(self):
        edit.connect_graph(self.p, "c1", self.eid, "input", "output", "src")
        edit.insert_graph_node(self.p, "c1", self.eid, self.m, "input", "output", "src")
        links = {(l["from"], l["to"], l["socket"]) for l in self.e["graph"]["links"]}
        self.assertEqual(links, {("input", self.m, "src"), (self.m, "output", "src")})
        copy_ids = edit.duplicate_graph_nodes(self.p, "c1", self.eid, [self.m])
        self.assertIn(copy_ids[0] + ".value", self.e["params"])
        edit.dissolve_graph_node(self.p, "c1", self.eid, self.m)
        self.assertEqual({(l["from"], l["to"], l["socket"]) for l in self.e["graph"]["links"]}, {("input", "output", "src")})
        self.assertNotIn(self.m + ".value", self.e["params"])


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
        sh = edit.add_graph_node(p, "c1", e["id"], {"type": "source", "kind": "shape", "shape": "star"})
        panel = EffectsPanel()
        opened = []
        panel.nodesRequested.connect(opened.append)
        picked = []
        panel.shapeChosen.connect(lambda *a: picked.append(a))
        panel.show_clips([edit.find(p, "c1")[1]], 0, 30)
        box = panel.widgets[("shape_pick", "fx:" + e["id"], sh)]
        self.assertEqual(box.currentData(), "star")
        box.activated.emit(box.findData("heart"))
        self.assertEqual(picked[-1][1:], (e["id"], sh, "heart", None))
        self.assertIn(("fx:" + e["id"], m + ".fac"), panel.widgets)
        self.assertIn(("source_media", "fx:" + e["id"], s), panel.widgets)
        edit.set_param(p, "c1", "fx:" + e["id"], m + ".fac", 0.25)
        panel.show_clips([edit.find(p, "c1")[1]], 0, 30)
        self.assertIn(m + ".fac", [q.name for q in fx.def_of(e).params])
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

    def test_separate_color_gives_a_picture_per_output(self):
        def build(out):
            def f(e):
                g = e["graph"]
                sep = ng.add_node(g, {"type": "filter", "ref": "builtin:nodes/separate_color"}, base="sep")
                ng.connect(g, "input", sep, "src")
                ng.connect(g, sep, "output", "src", out)
                e["params"].update(ng.default_params(g))
            return f
        self.check(self.view(build("c1")), WHITE, WHITE)       # the red channel of a red clip
        self.check(self.view(build("c2")), BLACK, BLACK)       # its green
        self.check(self.view(build("a")), WHITE, WHITE)        # its alpha

    def test_built_in_shape_node_draws_with_its_parameters(self):
        def f(e):
            e["params"].update(ng.default_params(e["graph"]))
        proj_ = proj()
        eff = edit.add_effect(proj_, "c1", fx.GRAPH)
        nid = edit.add_graph_node(proj_, "c1", eff["id"], {"type": "source", "kind": "shape",
                                                           "asset": {"key": "shape.rect", "colors": ("#0000ff", "#000000")}}, 0, 0)
        edit.connect_graph(proj_, "c1", eff["id"], nid, "output", "src")
        self.assertEqual(eff["params"][nid + ".color"], [0.0, 0.0, 1.0, 1.0])
        self.assertIn(nid + ".radius", [q.name for q in fx.def_of(eff).params])
        eff["sources"][nid].update(w=0.5, h=1.0)
        view = self.s.view()
        view["tracks"][0]["clips"][0]["effects"] = [eff]
        self.check(view, BLACK, BLACK)                       # (both test pixels are outside the half-width frame)
        eff["sources"][nid].update(w=1.0, h=1.0)
        self.check(view, BLUE, BLUE)
        edit.set_param(proj_, "c1", "fx:" + eff["id"], nid + ".color", [1.0, 0.0, 0.0, 1.0])
        self.check(view, RED, RED)
        edit.set_param(proj_, "c1", "fx:" + eff["id"], nid + ".fill_type", "漸變")
        for r in self.renderers:
            r.render(view, 0, W, H)
            self.assertEqual(r.errors, [], type(r).__name__)

    def text_view(self, **params):
        """The scene's clip with a text node (big white words in the middle) as the effect's output."""
        proj_ = proj()
        eff = edit.add_effect(proj_, "c1", fx.GRAPH)
        nid = edit.add_graph_node(proj_, "c1", eff["id"], {"type": "source", "kind": "text"}, 0, 0)
        edit.connect_graph(proj_, "c1", eff["id"], nid, "output", "src")
        eff["sources"][nid]["content"] = "█"
        eff["params"][nid + ".size"] = 12.0
        for k, v in params.items():
            eff["params"][nid + "." + k] = v
        view = self.s.view()
        view["tracks"][0]["clips"][0]["effects"] = [eff]
        return view, eff, nid

    def test_text_node_draws_its_words(self):
        view, eff, nid = self.text_view()
        for r in self.renderers:
            img = r.render(view, 0, W, H)
            self.assertEqual(r.errors, [], type(r).__name__)
            self.assertEqual(rgb(img, W // 2, H // 2), WHITE, type(r).__name__)           # the block fills the middle
            self.assertEqual(rgb(img, 2, 2), BLACK, type(r).__name__)                      # the rest is clear (the clip under it is gone)
        eff["params"][nid + ".color"] = [0.0, 0.0, 1.0, 1.0]
        for r in self.renderers:
            self.assertEqual(rgb(r.render(view, 0, W, H), W // 2, H // 2), BLUE, type(r).__name__)
        eff["params"][nid + ".color"] = [1.0, 1.0, 1.0, 1.0]
        eff["sources"][nid].update(cx=2.0)                                                  # (moved out of the picture)
        for r in self.renderers:
            self.assertEqual(rgb(r.render(view, 0, W, H), W // 2, H // 2), BLACK, type(r).__name__)

    def test_a_string_node_gives_the_text_node_its_words(self):
        view, eff, nid = self.text_view()
        g = eff["graph"]
        eff["sources"][nid]["content"] = " "                                                # (nothing to see of its own words)
        for r in self.renderers:
            self.assertEqual(rgb(r.render(view, 0, W, H), W // 2, H // 2), BLACK, type(r).__name__)
        sid = ng.add_node(g, {"type": ng.STRING, "value": "█"}, 0, 0)
        ng.connect(g, sid, nid, ng.TEXT_SOCKET)
        for r in self.renderers:
            img = r.render(view, 0, W, H)
            self.assertEqual(r.errors, [], type(r).__name__)
            self.assertEqual(rgb(img, W // 2, H // 2), WHITE, type(r).__name__)

    def test_text_node_with_shadow_background_and_outline_renders(self):
        view, eff, nid = self.text_view(shadow_on=True, bg_on=True, bg_color=[1.0, 0.0, 0.0, 1.0], stroke_on=True,
                                        stroke_color=[0.0, 1.0, 0.0, 1.0], stroke=3.0, align="靠右", box_w=300.0)
        for r in self.renderers:
            img = r.render(view, 0, W, H)
            self.assertEqual(r.errors, [], type(r).__name__)

    def shape_view(self, **params):
        """The scene's clip with a half-size rectangle shape node (white, no outline) as the effect's output."""
        proj_ = proj()
        eff = edit.add_effect(proj_, "c1", fx.GRAPH)
        nid = edit.add_graph_node(proj_, "c1", eff["id"], {"type": "source", "kind": "shape", "asset": {"key": "shape.rect"}}, 0, 0)
        edit.connect_graph(proj_, "c1", eff["id"], nid, "output", "src")
        eff["sources"][nid].update(w=0.5, h=0.5)
        for k, v in params.items():
            eff["params"][nid + "." + k] = v
        view = self.s.view()
        view["tracks"][0]["clips"][0]["effects"] = [eff]
        return view, eff, nid

    def pixels(self, view, *spots):
        for r in self.renderers:
            img = r.render(view, 0, W, H)
            self.assertEqual(r.errors, [], type(r).__name__)
            yield type(r).__name__, [rgb(img, x, y) for x, y in spots]

    def test_outline_outside_the_frame_is_drawn(self):
        for align, want in (("外側", RED), ("內側", BLACK)):
            view, _e, _n = self.shape_view(stroke_on=True, stroke=200.0, stroke_align=align, stroke_color=[1.0, 0.0, 0.0, 1.0], fill=False)
            for name, (got,) in self.pixels(view, (12, 18)):                     # (just left of the frame's edge)
                self.assertTrue(all(abs(a - b) <= 3 for a, b in zip(got, want)), f"{name} {align}: {got}")

    def test_shape_values_are_sockets_fed_by_effect_parameters(self):
        view, eff, nid = self.shape_view()
        eff["sources"][nid].update(w=1.0, h=1.0)
        proj_ = proj()
        g = eff["graph"]
        pn = ng.add_node(g, {"type": "params"}, base="params")
        self.assertIn(("param:color", "顏色"), ng.sockets(g["nodes"][nid]))
        self.assertIn(("param:cx", "位置 X"), ng.sockets(g["nodes"][nid]))
        with self.assertRaises(ng.GraphError):                                    # (a picture is no number)
            ng.connect(g, "input", nid, "param:radius")
        colour = ng.expose(g, eff["params"], pn, nid, "param:color")
        shift = ng.expose(g, eff["params"], pn, nid, "param:cx", eff["sources"])
        eff["params"]["expose." + colour] = [0.0, 0.0, 1.0, 1.0]
        for name, (a_, b_) in self.pixels(view, (12, 18), (52, 18)):
            self.assertTrue(all(abs(x - y) <= 3 for x, y in zip(a_, BLUE)), f"{name}: {a_}")
        eff["params"]["expose." + shift] = 2.0                                    # (moved out of the picture)
        for name, (a_, b_) in self.pixels(view, (12, 18), (52, 18)):
            self.assertEqual(a_, BLACK, name)
        self.assertNotIn("expose." + colour, [q.name for q in fx.def_of(eff).params if q.name == nid + ".color"])

    def test_ratio_keeps_the_shape_in_proportion(self):
        view, eff, nid = self.shape_view()
        eff["sources"][nid].update(w=1.0, h=1.0)
        for name, (edge, mid) in self.pixels(view, (4, 18), (32, 18)):
            self.assertEqual((edge, mid), (WHITE, WHITE), name)                  # 0: stretched over the frame
        eff["sources"][nid]["fit"] = 1.0                                       # a square in the 64 x 36 frame
        for name, (edge, mid) in self.pixels(view, (4, 18), (32, 18)):
            self.assertEqual((edge, mid), (BLACK, WHITE), name)

    def test_a_picture_paints_the_fill(self):
        view, eff, nid = self.shape_view()
        ng.connect(eff["graph"], "input", nid, "fill_image")                    # (the clip's red picture)
        for name, (out, mid) in self.pixels(view, (12, 18), (32, 18)):
            self.assertEqual(out, BLACK, name)                                   # outside the shape
            self.assertTrue(all(abs(a - b) <= 3 for a, b in zip(mid, RED)), f"{name}: {mid}")      # the picture, inside it

    def test_a_picture_paints_the_outline_only(self):
        view, eff, nid = self.shape_view(stroke_on=True, stroke=200.0, stroke_align="外側")
        ng.connect(eff["graph"], "input", nid, "stroke_image")
        for name, (ring, mid) in self.pixels(view, (12, 18), (32, 18)):
            self.assertTrue(all(abs(a - b) <= 3 for a, b in zip(ring, RED)), f"{name}: {ring}")
            self.assertTrue(all(abs(a - b) <= 3 for a, b in zip(mid, WHITE)), f"{name}: {mid}")     # (its own fill)

    def test_viewer_shows_a_node_in_the_editor_only(self):
        def f(e):
            g = e["graph"]
            sep = ng.add_node(g, {"type": "filter", "ref": "builtin:nodes/separate_color"}, base="sep")
            ng.connect(g, "input", sep, "src")
            ng.connect(g, "input", "output", "src")
            v = ng.add_node(g, {"type": ng.VIEWER}, base="viewer")
            ng.connect(g, sep, v, "src", "c2")
            e["params"].update(ng.default_params(g))
        v = self.view(f)
        self.check(v, RED, RED)                                # an export: the output
        v["editing"] = True
        self.check(v, BLACK, BLACK)                            # the editor's preview: the green channel picture

    def test_coordinate_node_is_a_gradient(self):
        def build(mode):
            def f(e):
                g = e["graph"]
                c = ng.add_node(g, {"type": "filter", "ref": "builtin:nodes/coordinate"}, base="c")
                ng.connect(g, c, "output", "src", "normalized")
                e["params"].update(ng.default_params(g))
            return f
        for r in self.renderers:
            img = r.render(self.view(build(1)), 0, W, H)
            left, right = rgb(img, 12, 18), rgb(img, 52, 18)
            self.assertLess(left[0], 90, type(r).__name__)                # X: 0 at the left, 1 at the right
            self.assertGreater(right[0], 165, type(r).__name__)
            self.assertAlmostEqual(left[1], 128, delta=12, msg=type(r).__name__)    # Y: up, 0.5 in the middle row

    def test_time_node_follows_the_clip(self):
        def f(e):
            g = e["graph"]
            c = ng.add_node(g, {"type": "filter", "ref": "builtin:nodes/time"}, base="t")
            ng.connect(g, c, "output", "src", "progress")
            e["params"].update(ng.default_params(g))
        v = self.view(f)
        for r in self.renderers:
            first = rgb(r.render(v, 0, W, H), 12, 18)[0]
            later = rgb(r.render(v, 45, W, H), 12, 18)[0]
            self.assertLess(first, 20, type(r).__name__)
            self.assertGreater(later, first + 20, type(r).__name__)

    def test_thumbnails_come_back_for_every_node(self):
        def f(e):
            g = e["graph"]
            sep = ng.add_node(g, {"type": "filter", "ref": "builtin:nodes/separate_color"}, base="sep")
            ng.connect(g, "input", sep, "src")
            ng.connect(g, sep, "output", "src", "c1")
            e["params"].update(ng.default_params(g))
        v = self.view(f)
        v["editing"], v["thumbs"] = True, ["e1"]
        for r in self.renderers:
            r.render(v, 0, W, H)
            got = r.thumbs["e1"]
            self.assertIn("", got["input"])
            w, h, data = got["sep1"]["c1"]
            self.assertEqual(len(data), w * h * 4)
            self.assertEqual(data[:3], bytes(WHITE), type(r).__name__)
        v["editing"] = False
        for r in self.renderers:
            r.render(v, 0, W, H)
            self.assertEqual(r.thumbs, {})

    def test_a_group_renders_as_what_is_inside(self):
        def f(e):
            g = e["graph"]
            sep = ng.add_node(g, {"type": "filter", "ref": "builtin:nodes/separate_color"}, base="sep")
            ng.connect(g, "input", sep, "src")
            ng.connect(g, sep, "output", "src", "c1")
            gid = ng.make_group(g, [sep])
            self.assertIn(gid, g["nodes"])
            e["params"].update(ng.default_params(g))
        self.check(self.view(f), WHITE, WHITE)

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
            e["params"][ng.param_key(m, "use_alpha")] = True     # (B laid over the input by its alpha)
            self.source(e, s, self.s.blue)
        self.check(self.view(build), BLUE, BLUE)

        def half(e):
            build(e)
            self.source(e, "s1", self.s.alpha)              # left half opaque white, right see-through
        self.check(self.view(half), WHITE, RED)

    def test_shape_node(self):
        def build(e, shape="rectangle"):
            g = e["graph"]
            n = ng.add_node(g, {"type": "source", "kind": "shape"}, base="shape")
            m = ng.add_node(g, {"type": "filter", "ref": "builtin:nodes/mix"})
            ng.connect(g, "input", m, "src")
            ng.connect(g, n, m, "b")
            ng.connect(g, m, "output", "src")
            e["params"].update(ng.default_params(g))
            e["params"][ng.param_key(m, "use_alpha")] = True     # (B laid over the input by its alpha)
            e.setdefault("sources", {})[n] = {"kind": "shape", "shape": shape, "color": [0, 0, 1, 1],
                                              "cx": 0.0, "cy": 0.0, "w": 0.5, "h": 0.5, "rotation": 0.0}
        for shape, corner in (("rectangle", True), ("ellipse", False)):
            v = self.view(lambda e, s=shape: build(e, s))
            for r in self.renderers:
                img = r.render(v, 0, W, H)
                self.assertEqual(r.errors, [])
                self.assertEqual(rgb(img, W // 2, H // 2), BLUE, shape)
                self.assertEqual(rgb(img, 2, 2), RED, shape)                 # outside it: the clip
                x, y = int(W * 0.27), int(H * 0.27)                          # just inside the box's corner
                self.assertEqual(rgb(img, x, y), BLUE if corner else RED, shape)

    def test_costly_nodes_keep_their_pictures_between_frames(self):
        """On the GPU a node that does not read the clip (here the blur of a shape) is drawn once while its settings and the
        shape stay the same - frames of any time, the same picture - and again when one changes."""
        if not HAVE_GL:
            self.skipTest("no OpenGL")
        from kiasecut import glrender
        r = glrender.GLRenderer()
        ran = []
        real = r.gl.fx.run_outputs

        def counted(d, *a, **k):
            ran.append(d.name)
            return real(d, *a, **k)
        r.gl.fx.run_outputs = counted

        def build(e, color):
            g = e["graph"]
            n = ng.add_node(g, {"type": "source", "kind": "shape"}, base="shape")
            b = ng.add_node(g, {"type": "filter", "ref": "builtin:blur"})
            m = ng.add_node(g, {"type": "filter", "ref": "builtin:nodes/mix"})
            ng.connect(g, n, b, "src")
            ng.connect(g, "input", m, "src")
            ng.connect(g, b, m, "b")
            ng.connect(g, m, "output", "src")
            e["params"].update(ng.default_params(g))
            e.setdefault("sources", {})[n] = {"kind": "shape", "shape": "rectangle", "color": color,
                                              "cx": 0.0, "cy": 0.0, "w": 0.5, "h": 0.5, "rotation": 0.0}
            return e
        v = self.view(lambda e: build(e, [0, 1, 0, 1]))
        first = r.render(v, 0, W, H)
        self.assertEqual(r.errors, [])
        self.assertEqual(ran.count("模糊"), 1, ran)
        for frame in (0, 20, 40):
            self.assertEqual(r.render(v, frame, W, H), first)
        self.assertEqual(ran.count("模糊"), 1, ran)                              # (the other frames drew no blur)
        self.assertGreater(rgb(first, W // 2, H // 2)[1], 200)
        e = v["tracks"][0]["clips"][0]["effects"][0]
        src = next(iter(e["sources"].values()))
        src["color"] = [0, 0, 1, 1]                                            # (the shape's colour changes: the blur is drawn again)
        changed = r.render(v, 0, W, H)
        self.assertEqual(rgb(changed, W // 2, H // 2)[:2], (0, 0))
        self.assertGreater(rgb(changed, W // 2, H // 2)[2], 200)
        self.assertEqual(ran.count("模糊"), 2, ran)

    def test_nodes_that_read_the_clip_are_kept_while_its_picture_is_the_same(self):
        """On the GPU the blur of the clip itself is drawn once while the clip's picture, its place and the settings stay the same -
        frames of any time - and again when one changes; a video's frame (it may change without a new picture) and a picture that
        another effect made are never kept."""
        if not HAVE_GL:
            self.skipTest("no OpenGL")
        from PySide6.QtGui import QImage
        from kiasecut import glrender
        frame = QImage(160, 90, QImage.Format_ARGB32_Premultiplied)
        frame.fill(0xFFFF0000)

        def counting(r):
            ran = []
            real = r.gl.fx.run_outputs

            def counted(d, *a, **k):
                ran.append(d.name)
                return real(d, *a, **k)
            r.gl.fx.run_outputs = counted
            return ran

        def build(e):
            g = e["graph"]
            b = ng.add_node(g, {"type": "filter", "ref": "builtin:blur"})
            ng.connect(g, "input", b, "src")
            ng.connect(g, b, "output", "src")
            e["params"].update(ng.default_params(g))

        r = glrender.GLRenderer()
        ran = counting(r)
        v = self.view(build)
        clip = v["tracks"][0]["clips"][0]
        first = r.render(v, 0, W, H)
        self.assertEqual(r.errors, [])
        self.assertEqual(ran.count("模糊"), 1, ran)
        for t in (0, 20, 40):
            self.assertEqual(r.render(v, t, W, H), first)
        self.assertEqual(ran.count("模糊"), 1, ran)                              # (the other frames drew no blur)
        clip["media"]["path"] = self.s.blue                                    # (another picture)
        blue = r.render(v, 0, W, H)
        self.assertEqual(ran.count("模糊"), 2, ran)
        self.assertGreater(rgb(blue, W // 2, H // 2)[2], 200)
        self.assertEqual(rgb(blue, W // 2, H // 2)[0], 0)
        clip["transform"]["scale"] = 0.5                                       # (placed another way)
        r.render(v, 0, W, H)
        self.assertEqual(ran.count("模糊"), 3, ran)
        r.render(v, 20, W, H)
        self.assertEqual(ran.count("模糊"), 3, ran)

        clip["type"] = "video"                                                 # a video: its frames are never said to be the same
        r = glrender.GLRenderer(video_frame=lambda path, us, w, h: frame)
        ran = counting(r)
        for t in (0, 0, 20):
            r.render(v, t, W, H)
        self.assertEqual(r.errors, [])
        self.assertEqual(ran.count("模糊"), 3, ran)

        clip["type"] = "image"
        v["tracks"][0]["clips"][0]["effects"].insert(0, fx.new_effect("builtin:invert", "e0"))      # after another effect: not the clip's picture
        r = glrender.GLRenderer()
        ran = counting(r)
        for t in (0, 0, 20):
            r.render(v, t, W, H)
        self.assertEqual(r.errors, [])
        self.assertEqual(ran.count("模糊"), 3, ran)

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


class GraphMediaDropTests(unittest.TestCase):
    def test_files_dropped_in_become_source_nodes(self):
        import types
        from PIL import Image
        from kiasecut.ui.main_window import MainWindow
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        png = os.path.join(d, "a.png")
        Image.new("RGB", (40, 20), (255, 0, 0)).save(png)
        p = proj()
        e = edit.add_effect(p, "c1", fx.GRAPH)
        host = types.SimpleNamespace(proj=p, node_clip=lambda: "c1", nodes=types.SimpleNamespace(select=lambda n: None, level=""),
                                     statusBar=lambda: types.SimpleNamespace(showMessage=lambda *a: None),
                                     apply=lambda _n, fn, *a: fn(p, *a) or True)
        host._node_media = MainWindow._node_media
        MainWindow.on_node_media(host, e["id"], [], [png], 10.0, 20.0)
        srcs = [(n, v) for n, v in e["graph"]["nodes"].items() if v["type"] == "source"]
        self.assertEqual(len(srcs), 1)
        nid, node = srcs[0]
        self.assertEqual((node["x"], node["y"]), (10.0, 20.0))
        self.assertEqual(e["sources"][nid]["image"], png)
        self.assertEqual(e["sources"][nid]["img_w"], 40)
