"""Node graphs (nodegraph.py): the graph as data, and running it on the GPU."""
import math
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kiasecut import fx, nodegraph as ng  # noqa: E402


def engine():
    try:
        return fx.Engine()
    except fx.FilterError as exc:
        raise unittest.SkipTest(str(exc))


class DataTest(unittest.TestCase):
    def test_default_params(self):
        g = ng.new_graph()
        m = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/math"})
        self.assertEqual(ng.default_params(g)[m + ".value"], 0.5)

    def test_socket_shapes_circle_for_one_value_diamond_for_every_pixel(self):
        g = ng.new_graph()
        v = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/value"})
        sw = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/switch"})
        m = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/math"})
        a = ng.add_node(g, {"type": ng.SOURCE, "kind": "image"}, base="a")
        self.assertEqual(ng.output_shape(g, v), "single")          # a Value node: one number
        self.assertEqual(ng.output_shape(g, a), "field")           # a picture
        self.assertEqual(ng.output_shape(g, m), "field")           # a Math node's result is made per pixel
        self.assertEqual(ng.input_shape(g, sw, "param:use_true"), "single")   # a tick: read once
        self.assertEqual(ng.input_shape(g, m, "param:value"), "either")       # a number: one value or a picture
        self.assertEqual(ng.input_shape(g, sw, "yes"), "field")               # a picture input

    def test_parameters_made_by_hand_have_a_type_the_user_defines(self):
        g, params = ng.new_graph(), {}
        a = ng.add_exposed(g, params, "color", "主色")
        b = ng.add_exposed(g, params, "float")
        self.assertEqual((params["expose." + a], [x["type"] for x in ng.exposed(g)]), ([1.0, 1.0, 1.0, 1.0], ["color", "float"]))
        ng.edit_exposed(g, params, b, {"type": "vec3"})                     # any type, while nothing is linked to it
        self.assertEqual(params["expose." + b], [0.0, 0.0, 0.0])
        ng.edit_exposed(g, params, b, {"type": "int"})
        self.assertEqual([x["type"] for x in ng.exposed(g)], ["color", "int"])
        g["links"].append({"from": "x", "to": "y", "socket": "param:k", "out": b})
        with self.assertRaises(ng.GraphError):
            ng.edit_exposed(g, params, b, {"type": "bool"})
        with self.assertRaises(ng.GraphError):
            ng.add_exposed(g, params, "menu")

    def test_new_graph_is_valid(self):
        g = ng.new_graph()
        self.assertIsNone(ng.check(g))
        self.assertEqual(ng.new_effect("e1")["filter"], fx.GRAPH)

    def test_connect_replaces_and_refuses_loops(self):
        g = ng.new_graph()
        a = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/math"}, 0, 0)
        b = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/mix"}, 0, 0)
        ng.connect(g, a, b, "src")
        with self.assertRaises(ng.GraphError):
            ng.connect(g, b, a, "src")
        with self.assertRaises(ng.GraphError):
            ng.connect(g, a, a, "src")
        with self.assertRaises(ng.GraphError):
            ng.connect(g, a, b, "nothing")
        ng.connect(g, "input", b, "src")
        self.assertEqual([l["from"] for l in g["links"] if l["to"] == b and l["socket"] == "src"], ["input"])
        ng.remove_node(g, b)
        self.assertFalse([l for l in g["links"] if b in (l["from"], l["to"])])

    def test_one_output(self):
        with self.assertRaises(ng.GraphError):
            ng.add_node(ng.new_graph(), {"type": ng.OUTPUT})

    def test_a_link_without_an_output_leaves_the_first_one(self):
        """Made before the filter had @output pictures (Glare's), a link names none: it is the first output."""
        g = ng.new_graph()
        n = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:blender_glare"})
        ng.connect(g, "input", n, "src")
        g["links"].append({"from": n, "to": "output", "socket": "src"})
        g["links"].append({"from": n, "to": "output", "socket": "x", "out": "gone"})
        ng.migrate(g)
        self.assertEqual([l.get("out") for l in g["links"] if l["from"] == n], ["image", "image"])
        ng.connect(g, n, "output", "src", "highlights")
        ng.migrate(g)
        self.assertEqual([l["out"] for l in g["links"] if l["from"] == n and l["to"] == "output"][-1], "highlights")

    def test_sockets(self):
        g = ng.new_graph()
        m = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/mix"})
        names = [s for s, _ in ng.sockets(g["nodes"][m])]
        self.assertEqual(names, ["src", "b", "facv", "param:data_type", "param:factor_mode", "param:blend", "param:fac", "param:clamp_fac",
                                 "param:use_alpha", "param:clamp_on"])
        c = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/math"})
        self.assertIn("param:value", [s for s, _ in ng.sockets(g["nodes"][c])])

    def test_node_filters_parse(self):
        import glob
        names = [os.path.splitext(os.path.basename(f))[0] for f in glob.glob(os.path.join(fx.PKG, "nodes", "*.glsl"))]
        self.assertTrue({"mix", "math", "vector_math", "map_range", "alpha_over"} <= set(names))
        for name in names:
            self.assertIsNone(fx.get("builtin:nodes/" + name).error, name)


class RunTest(unittest.TestCase):
    W = H = 8

    def run_graph(self, g, rgba, pictures=None, t=0, params=None, watch=None):
        eng = engine()
        pool = ng.Pool(eng)
        with eng.ctx:
            src = eng.ctx.texture((self.W, self.H), 4, np.ascontiguousarray(rgba).tobytes())
            src.filter = (eng.mgl.LINEAR, eng.mgl.LINEAR)
            texs = {}

            def picture(nid, *_more):
                if watch:
                    watch(nid, params)
                arr = (pictures or {}).get(nid)
                if arr is None:
                    return None
                tex = texs[nid] = eng.ctx.texture((arr.shape[1], arr.shape[0]), 4, np.ascontiguousarray(arr).tobytes())
                return tex, ng.IDENTITY, None
            errors = []
            tex, owner = ng.evaluate(eng, g, params or {}, src, self.W, self.H, pool.alloc, pool.free, t=t, picture=picture, errors=errors)
            out = ng.read_rgba8(tex).copy() if tex is not None else None
            if owner is not None:
                pool.free(owner)
            self.assertEqual(len(pool.spare) + 0, len(pool.spare))
        return out, errors, pool

    def solid(self, rgba):
        return np.tile(np.array(rgba, np.uint8), (self.H, self.W, 1))

    def test_passthrough(self):
        red = self.solid([255, 0, 0, 255])
        out, errors, _ = self.run_graph(ng.new_graph(), red)
        self.assertEqual(errors, [])
        self.assertTrue((out == red).all())

    def test_mix_over_and_source(self):
        g = ng.new_graph()
        s = ng.add_node(g, {"type": ng.SOURCE, "kind": "image"}, base="s")
        m = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/mix"})
        ng.connect(g, "input", m, "src")
        ng.connect(g, s, m, "b")
        ng.connect(g, m, "output", "src")
        blue = self.solid([0, 0, 255, 255])
        over = {ng.param_key(m, "use_alpha"): True}            # (off is Blender's Mix; on lays B over A by B's alpha)
        out, errors, _ = self.run_graph(g, self.solid([255, 0, 0, 255]), {s: blue}, params=over)
        self.assertEqual(errors, [])
        self.assertTrue((np.abs(out.astype(int) - blue) <= 1).all())
        half = self.solid([0, 0, 128, 128])                    # premultiplied half-blue over red
        out, _, _ = self.run_graph(g, self.solid([255, 0, 0, 255]), {s: half}, params=over)
        self.assertTrue(abs(int(out[0, 0, 0]) - 127) <= 2 and abs(int(out[0, 0, 2]) - 128) <= 2 and out[0, 0, 3] == 255)

    def test_switch_and_menu_switch_pick_one_and_leave_the_rest_unworked(self):
        asked = []

        class Seen(dict):
            def get(self, k, d=None):
                asked.append(k)
                return dict.get(self, k, d)
        g = ng.new_graph()
        a = ng.add_node(g, {"type": ng.SOURCE, "kind": "image"}, base="a")
        b = ng.add_node(g, {"type": ng.SOURCE, "kind": "image"}, base="b")
        sw = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/switch"})
        ng.connect(g, "input", sw, "src")
        ng.connect(g, b, sw, "yes")
        ng.connect(g, sw, "output", "src")
        blue = self.solid([0, 0, 255, 255])
        red = self.solid([255, 0, 0, 255])
        out, errors, _ = self.run_graph(g, self.solid([0, 255, 0, 255]), Seen({b: blue}), params={sw + ".use_true": False})
        self.assertEqual(errors, [])
        self.close(out, (0, 255, 0, 255))                          # (false: the picture in)
        self.assertNotIn(b, asked)                                 # (and the other one is not even looked at)
        out, _, _ = self.run_graph(g, self.solid([0, 255, 0, 255]), {b: blue}, params={sw + ".use_true": True})
        self.close(out, (0, 0, 255, 255))
        g = ng.new_graph()
        a = ng.add_node(g, {"type": ng.SOURCE, "kind": "image"}, base="a")
        b = ng.add_node(g, {"type": ng.SOURCE, "kind": "image"}, base="b")
        m = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/menu_switch"})
        ng.connect(g, "input", m, "src")
        ng.connect(g, a, m, "i2")
        ng.connect(g, b, m, "i3")
        ng.connect(g, m, "output", "src")
        pics = {a: red, b: blue}
        for choice, want in (("選項 1", (0, 255, 0, 255)), ("選項 2", (255, 0, 0, 255)), ("選項 3", (0, 0, 255, 255))):
            out, errors, _ = self.run_graph(g, self.solid([0, 255, 0, 255]), pics, params={m + ".choice": choice})
            self.assertEqual(errors, [], choice)
            self.close(out, want)

    def test_a_number_node_can_feed_a_shape_and_leaves_the_params_as_they_were(self):
        g = ng.new_graph()
        v = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/value"})
        c = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/rgb"})
        s = ng.add_node(g, {"type": ng.SOURCE, "kind": "shape", "asset": {"key": "ring", "family": "ellipse"}}, base="s")
        ng.connect(g, v, s, "param:ratio")                         # a Value node into a shape's number
        ng.connect(g, c, s, "param:stroke_color")                  # a colour into its colour
        with self.assertRaises(ng.GraphError):
            ng.connect(g, v, s, "param:cx")                        # where it sits: the effect's parameters only
        self.assertEqual(ng.input_shape(g, s, "param:ratio"), "single")
        ng.connect(g, s, "output", "src")
        params = {v + ".value": 0.25, c + ".color": [0.0, 1.0, 0.0, 1.0]}
        seen = {}
        self.run_graph(g, self.solid([0, 0, 0, 255]), params=dict(params),
                       watch=lambda nid, ps: seen.update(ratio=ps.get(s + ".ratio"), colour=ps.get(s + ".stroke_color")))
        self.assertAlmostEqual(seen["ratio"], 0.25, 3)
        self.assertAlmostEqual(seen["colour"][1], 1.0, 2)
        mine = dict(params)
        self.run_graph(g, self.solid([0, 0, 0, 255]), params=mine)
        self.assertEqual(mine, params)                             # (put back: nothing left of the linked values)

    def test_a_number_can_set_a_tick_and_choose_a_menu_option(self):
        g = ng.new_graph()
        v = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/value"})
        a = ng.add_node(g, {"type": ng.SOURCE, "kind": "image"}, base="a")
        sw = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/switch"})
        ng.connect(g, "input", sw, "src")
        ng.connect(g, a, sw, "yes")
        ng.connect(g, v, sw, "param:use_true")                    # a number into a tick
        ng.connect(g, sw, "output", "src")
        red = self.solid([255, 0, 0, 255])
        green = self.solid([0, 255, 0, 255])
        out, errors, _ = self.run_graph(g, green, {a: red}, params={v + ".value": 1.0})
        self.assertEqual(errors, [])
        self.close(out, (255, 0, 0, 255))                          # (1: true)
        out, _, _ = self.run_graph(g, green, {a: red}, params={v + ".value": 0.0})
        self.close(out, (0, 255, 0, 255))                          # (0: false)
        g = ng.new_graph()
        v = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/value"})
        a = ng.add_node(g, {"type": ng.SOURCE, "kind": "image"}, base="a")
        m = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/menu_switch"})
        ng.connect(g, "input", m, "src")
        ng.connect(g, a, m, "i2")
        ng.connect(g, v, m, "param:choice")                        # a number into a menu: its index
        ng.connect(g, m, "output", "src")
        out, _, _ = self.run_graph(g, green, {a: red}, params={v + ".value": 1.0})
        self.close(out, (255, 0, 0, 255))
        out, _, _ = self.run_graph(g, green, {a: red}, params={v + ".value": 0.0})
        self.close(out, (0, 255, 0, 255))

    def test_index_switch_picks_the_numbered_input_and_a_number_can_be_its_index(self):
        g = ng.new_graph()
        v = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/value"})
        a = ng.add_node(g, {"type": ng.SOURCE, "kind": "image"}, base="a")
        b = ng.add_node(g, {"type": ng.SOURCE, "kind": "image"}, base="b")
        m = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/index_switch"})
        params = ng.default_params(g)
        ng.connect(g, "input", m, "src")
        ng.connect(g, a, m, "i2")
        s3 = ng.add_item(g, params, m)
        ng.connect(g, b, m, s3)
        ng.connect(g, m, "output", "src")
        self.assertEqual([lab for s, lab in ng.sockets(g["nodes"][m]) if not s.startswith("param")], ["0", "1", "2"])
        red, blue, green = self.solid([255, 0, 0, 255]), self.solid([0, 0, 255, 255]), self.solid([0, 255, 0, 255])
        for index, want in ((0, (0, 255, 0, 255)), (1, (255, 0, 0, 255)), (2, (0, 0, 255, 255)), (3, (0, 0, 0, 0))):
            out, errors, _ = self.run_graph(g, green, {a: red, b: blue}, params={m + ".index": index})
            self.assertEqual(errors, [], index)
            self.close(out, want)
        ng.connect(g, v, m, "param:index")                         # a number: the index
        out, _, _ = self.run_graph(g, green, {a: red, b: blue}, params={v + ".value": 2.0})
        self.close(out, (0, 0, 255, 255))

    def test_menu_switch_has_options_of_its_own(self):
        g = ng.new_graph()
        a = ng.add_node(g, {"type": ng.SOURCE, "kind": "image"}, base="a")
        b = ng.add_node(g, {"type": ng.SOURCE, "kind": "image"}, base="b")
        m = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/menu_switch"})
        params = ng.default_params(g)
        ng.connect(g, "input", m, "src")
        ng.connect(g, m, "output", "src")
        sock = ng.add_item(g, params, m, "貓")                      # a fourth option, named
        ng.add_item(g, params, m, "狗")
        ng.connect(g, a, m, sock)
        names = [n for _s, n in ng.sockets(g["nodes"][m]) if n not in ("選單",)]
        self.assertEqual(names, ["選項 1", "選項 2", "選項 3", "貓", "狗"])
        red = self.solid([255, 0, 0, 255])
        out, errors, _ = self.run_graph(g, self.solid([0, 255, 0, 255]), {a: red}, params={m + ".choice": "貓"})
        self.assertEqual(errors, [])
        self.close(out, (255, 0, 0, 255))
        ng.rename_item(g, params, m, sock, "鳥")                    # a new name: the link and a stored choice go with it
        params[m + ".choice"] = "鳥"
        out, _, _ = self.run_graph(g, self.solid([0, 255, 0, 255]), {a: red}, params=params)
        self.close(out, (255, 0, 0, 255))
        ng.move_item(g, params, m, sock, -3)
        ng.move_item(g, params, m, sock, -1)                        # (first now: the main socket, the link kept)
        self.assertEqual(g["nodes"][m]["items"][0]["name"], "鳥")
        out, _, _ = self.run_graph(g, self.solid([0, 255, 0, 255]), {a: red}, params=params)
        self.close(out, (255, 0, 0, 255))
        ng.remove_item(g, params, m, next(i["sock"] for i in g["nodes"][m]["items"] if i["name"] == "鳥"))
        self.assertEqual(params[m + ".choice"], g["nodes"][m]["items"][0]["name"])   # (the choice of a removed option: the first)
        while len(g["nodes"][m]["items"]) > 2:
            ng.remove_item(g, params, m, g["nodes"][m]["items"][-1]["sock"])
        with self.assertRaises(ng.GraphError):
            ng.remove_item(g, params, m, "src")                     # (never fewer than two)


    def test_menu_switch_tells_which_option_is_chosen(self):
        g = ng.new_graph()
        m = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/menu_switch"})
        params = ng.default_params(g)
        self.assertEqual([lab for _o, lab in ng.outputs(g["nodes"][m])], ["輸出", "選項 1", "選項 2", "選項 3"])
        ng.connect(g, m, "output", "src", "sel_i2")                 # the boolean of the second option
        green = self.solid([0, 255, 0, 255])
        for choice, want in (("選項 2", (255, 255, 255, 255)), ("選項 1", (0, 0, 0, 255)), ("選項 3", (0, 0, 0, 255))):
            out, errors, _ = self.run_graph(g, green, params={m + ".choice": choice})
            self.assertEqual(errors, [], choice)
            self.close(out, want)
        ng.move_item(g, params, m, "i2", -1)                        # first now (the socket "src"): the link goes with the option
        out, _, _ = self.run_graph(g, green, params={m + ".choice": "選項 2"})
        self.assertEqual(next(l for l in g["links"] if l["from"] == m)["out"], "sel_src")
        self.close(out, (255, 255, 255, 255))
        ng.remove_item(g, params, m, "src")                         # the option goes: so does the link from its boolean
        self.assertFalse(any(l["from"] == m for l in g["links"]))

    def test_mix_data_types_are_blenders(self):
        """Mix as Blender 5.2 gives it: A (0.8, 0.4, 0.2, 0.5) with B (0.2, 0.6, 0.9, 0.8), the four channels as stored."""
        g = ng.new_graph()
        b = ng.add_node(g, {"type": ng.SOURCE, "kind": "image"}, base="b")
        fv = ng.add_node(g, {"type": ng.SOURCE, "kind": "image"}, base="fv")
        m = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/mix"})
        ng.connect(g, "input", m, "src")
        ng.connect(g, b, m, "b")
        ng.connect(g, m, "output", "src")
        pic_a = self.solid([204, 102, 51, 128])
        pic_b = self.solid([51, 153, 230, 204])
        facv = self.solid([0, 128, 255, 255])

        def run(**kw):
            params = ng.default_params(g)
            params.update({m + "." + k: v for k, v in kw.items()})
            out, errors, _ = self.run_graph(g, pic_a, {b: pic_b, fv: facv}, params=params)
            self.assertEqual(errors, [], kw)
            return out[4, 4] / 255.0

        def near(got, want, tol=0.012):
            self.assertTrue(np.allclose(got, want, atol=tol), (got, want))
        near(run(use_alpha=False, fac=0.5), (0.5, 0.5, 0.55, 0.65))                   # (colour: alpha mixes too)
        near(run(use_alpha=False, fac=0.5, blend="相乘"), (0.48, 0.32, 0.19, 0.5))     # (other modes keep A's alpha)
        near(run(use_alpha=False, fac=-0.5, clamp_fac=False), (1.0, 0.3, 0.0, 0.35))   # (factor past 0 - 1: pushed out)
        near(run(use_alpha=False, fac=-0.5), (0.8, 0.4, 0.2, 0.5))                     # (clamped: A)
        near(run(data_type="浮點", fac=0.25), (0.487, 0.487, 0.487, 1.0))               # (brightness of A and B)
        near(run(data_type="向量", fac=0.25), (0.65, 0.45, 0.375, 1.0))
        ng.connect(g, fv, m, "facv")
        near(run(data_type="向量", factor_mode="非統一"), (0.8, 0.5, 0.9, 1.0))         # (a factor for every axis)

    def test_vector_math_new_operations_and_vector_map_range(self):
        """Power, Sign and Round of Vector Math, and Map Range on a vector (every axis its own range), as Blender 5.2 gives them."""
        g = ng.new_graph()
        v = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/vector_math"})
        ng.connect(g, "input", v, "src")
        ng.connect(g, v, "output", "src")
        pic = self.solid([64, 128, 191, 255])                      # (0.25, 0.5, 0.75)

        def run(node_params):
            params = ng.default_params(g)
            params.update(node_params)
            out, errors, _ = self.run_graph(g, pic, params=params)
            self.assertEqual(errors, [])
            return out[4, 4] / 255.0
        want = lambda got, w: self.assertTrue(np.allclose(got, w, atol=0.012), (got, w))
        want(run({v + ".op": "四捨五入"}), (0, 1, 1, 1))              # (floor(x + 0.5): Blender rounds a half up)
        want(run({v + ".op": "正負號"}), (1, 1, 1, 1))
        want(run({v + ".op": "次方", v + ".vector_b": (0.5, 2.0, 0.0)}), (0.5, 0.25, 1, 1))
        m = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/map_range"})
        ng.connect(g, "input", m, "src")
        ng.connect(g, m, "output", "src")
        p = {m + ".data_type": "向量", m + ".from_max_v": (1.0, 0.5, 1.0), m + ".to_min_v": (0.1, 0.0, 0.2), m + ".to_max_v": (0.9, 1.0, 0.6)}
        want(run(p), (0.1 + 0.25 * 0.8, 1.0, 0.2 + 0.75 * 0.4, 1))   # (the green axis runs 0 - 0.5: clamped at the end)
        want(run({**p, m + ".mode": "階梯", m + ".steps_v": (4.0, 2.0, 3.0)}), (0.1 + 0.25 * 0.8, 1.0, 0.2 + 2 / 3 * 0.4, 1))

    def test_missing_source_is_transparent(self):
        g = ng.new_graph()
        s = ng.add_node(g, {"type": ng.SOURCE, "kind": "video"}, base="s")
        ng.connect(g, s, "output", "src")
        out, _, _ = self.run_graph(g, self.solid([255, 0, 0, 255]))
        self.assertTrue((out == 0).all())

    def test_math_value_and_linked_param(self):
        g = ng.new_graph()
        c = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/math"})
        ng.connect(g, "input", c, "src")
        ng.connect(g, c, "output", "src")
        out, errors, _ = self.run_graph(g, self.solid([200, 100, 0, 255]), params={c + ".op": "相乘", c + ".value": 0.5})
        self.assertEqual(errors, [])
        self.close(out, (57, 57, 57, 255))                    # a float node: the brightness (0.447) x 0.5, as a grey

    def node(self, ref, **vals):
        g = ng.new_graph()
        n = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/" + ref})
        ng.connect(g, "input", n, "src")
        ng.connect(g, n, "output", "src")
        return g, n, {n + "." + k: v for k, v in vals.items()}

    def close(self, out, want, tol=2):
        self.assertTrue(all(abs(int(a) - int(b)) <= tol for a, b in zip(out[0, 0], want)), f"{tuple(out[0, 0])} != {want}")

    def test_nodes_keep_values_outside_0_1_between_them(self):
        g = ng.new_graph()
        a = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/math"}, base="a")
        b = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/math"}, base="b")
        ng.connect(g, "input", a, "src")
        ng.connect(g, a, b, "src")
        ng.connect(g, b, "output", "src")
        out, errors, _ = self.run_graph(g, self.solid([128, 64, 0, 255]),
                                        params={a + ".op": "相減", a + ".value": 1.0, b + ".op": "相加", b + ".value": 1.0})
        self.assertEqual(errors, [])
        self.close(out, (73, 73, 73, 255))                    # 0.286 - 1 = -0.714 and back: an 8-bit step would have lost it

    def test_a_linked_number_input_ignores_its_box(self):
        g = ng.new_graph()
        c = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/math"})
        ng.connect(g, "input", c, "src")
        ng.connect(g, c, "output", "src")
        clear = self.solid([0, 0, 0, 0])
        out, _, _ = self.run_graph(g, clear, params={c + ".op": "相加", c + ".value": 0.5})
        self.close(out, (128, 128, 128, 255))                    # B not linked: its box (0.5)
        ng.connect(g, "input", c, "b")
        out, _, _ = self.run_graph(g, clear, params={c + ".op": "相加", c + ".value": 0.5})
        self.close(out, (0, 0, 0, 255))                          # linked: the clear picture is 0, not the box

    def test_math_a_is_a_number_too(self):
        g = ng.new_graph()
        c = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/math"})
        ng.connect(g, c, "output", "src")
        out, errors, _ = self.run_graph(g, self.solid([0, 0, 0, 0]), params={c + ".op": "相加", c + ".value_a": 0.25, c + ".value": 0.25})
        self.assertEqual(errors, [])
        self.close(out, (128, 128, 128, 255))                    # nothing linked: 0.25 + 0.25 from the boxes

    def test_math_operations(self):
        for op, value, want in (("次方", 2.0, (21,) * 3), ("平方根", 0.0, (136,) * 3), ("大於", 0.2, (255,) * 3),
                                ("四捨五入", 0.0, (0,) * 3), ("相除", 2.0, (36,) * 3), ("最大", 0.6, (153,) * 3),
                                ("迴繞", 0.25, (9,) * 3)):             # (the input's brightness is 0.286)
            g, n, p = self.node("math", op=op, value=value)
            if op == "迴繞":
                p[n + ".value3"] = 0.0                           # wrap(a, max = 0.25, min = 0)
            out, errors, _ = self.run_graph(g, self.solid([128, 64, 0, 255]), params={n + "." + k.split(".")[1]: v for k, v in p.items()})
            self.assertEqual(errors, [], op)
            self.close(out, want + (255,), 4)

    def test_vector_math_two_outputs(self):
        g = ng.new_graph()
        n = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/vector_math"})
        ng.connect(g, "input", n, "src")
        ng.connect(g, n, "output", "src", "value")
        out, errors, _ = self.run_graph(g, self.solid([51, 51, 51, 255]), params={n + ".op": "長度"})
        self.assertEqual(errors, [])
        self.close(out, (88, 88, 88, 255))                       # length of (0.2, 0.2, 0.2)
        ng.connect(g, n, "output", "src", "vector")
        out, _, _ = self.run_graph(g, self.solid([51, 102, 0, 255]), params={n + ".op": "相加", n + ".vector_b": [0.2, 0.0, 0.5]})
        self.close(out, (102, 102, 128, 255))
        out, _, _ = self.run_graph(g, self.solid([255, 0, 0, 255]), params={n + ".op": "外積", n + ".vector_b": [0.0, 1.0, 0.0]})
        self.close(out, (0, 0, 255, 255))                        # X cross Y = Z

    def test_xyz_nodes_and_vector_rotate(self):
        """Separate / Combine XYZ and Vector Rotate (the formulas checked against Blender 5.2: Rodrigues, Euler XYZ = Rz Ry Rx, invert = the inverse)."""
        g = ng.new_graph()
        n = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/separate_xyz"})
        ng.connect(g, "input", n, "src")
        ng.connect(g, n, "output", "src", "y")
        out, errors, _ = self.run_graph(g, self.solid([51, 102, 0, 255]))
        self.assertEqual(errors, [])
        self.close(out, (102, 102, 102, 255))
        g = ng.new_graph()
        n = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/combine_xyz"})
        ng.connect(g, n, "output", "src")
        out, errors, _ = self.run_graph(g, self.solid([0, 0, 0, 0]), params={n + ".x": 0.2, n + ".y": 0.4, n + ".z": 0.6})
        self.assertEqual(errors, [])
        self.close(out, (51, 102, 153, 255))
        g = ng.new_graph()
        n = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/vector_rotate"})
        ng.connect(g, "input", n, "src")
        ng.connect(g, n, "output", "src")
        red = self.solid([255, 0, 0, 255])

        def run(**p):
            out, errors, _ = self.run_graph(g, red, params={n + "." + k: v for k, v in p.items()})
            self.assertEqual(errors, [])
            return out
        self.close(run(kind="Z 軸", angle=90.0), (0, 255, 0, 255))                 # X turned 90 degrees about Z is Y
        self.close(run(kind="Z 軸", angle=90.0, invert=True), (0, 0, 0, 255))      # ... and the other way is -Y (clamped)
        self.close(run(kind="Z 軸", angle=90.0, vec_center=(0.5, 0.5, 0.5)), (255, 255, 0, 255))
        self.close(run(kind="軸與角度", vec_axis=(0.0, 0.0, 5.0), angle=90.0), (0, 255, 0, 255))
        self.close(run(kind="歐拉 XYZ", vec_rotation=(0.0, 0.0, 90.0)), (0, 255, 0, 255))
        self.close(run(kind="歐拉 XYZ", vec_rotation=(0.0, 0.0, 90.0), invert=True), (0, 0, 0, 255))

    def test_constant_input_nodes(self):
        """The input nodes Vector, Boolean, Integer, Integer Vector and Menu: a constant picture each."""
        def run(ref, **vals):
            g = ng.new_graph()
            n = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/" + ref})
            ng.connect(g, n, "output", "src")
            out, errors, _ = self.run_graph(g, self.solid([0, 0, 0, 0]), params={n + "." + k: v for k, v in vals.items()})
            self.assertEqual(errors, [])
            return out
        self.close(run("vector", vector=(0.2, 0.4, 1.0)), (51, 102, 255, 255))
        self.close(run("boolean", value=True), (255, 255, 255, 255))
        self.close(run("boolean", value=False), (0, 0, 0, 255))
        self.close(run("integer", value=1), (255, 255, 255, 255))             # (a picture holds 0 - 1: bigger numbers are clamped in the 8-bit view)
        self.close(run("integer_vector", x=1, y=0, z=1), (255, 0, 255, 255))
        self.close(run("menu", choice="選項 1"), (0, 0, 0, 255))
        self.close(run("menu", choice="選項 2"), (255, 255, 255, 255))
        for ref, par, val in (("integer", "value", 2), ("menu", "choice", "選項 3")):      # the input nodes drive the switches by their number
            g = ng.new_graph()
            v = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/" + ref})
            a = ng.add_node(g, {"type": ng.SOURCE, "kind": "image"}, base="a")
            m = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/index_switch"})
            ng.connect(g, "input", m, "src")
            ng.connect(g, a, m, "i2")
            s3 = ng.add_item(g, ng.default_params(g), m)
            ng.connect(g, a, m, s3)
            ng.connect(g, v, m, "param:index")
            ng.connect(g, m, "output", "src")
            out, errors, _ = self.run_graph(g, self.solid([0, 255, 0, 255]), {a: self.solid([255, 0, 0, 255])}, params={v + "." + par: val})
            self.assertEqual(errors, [], ref)
            self.close(out, (255, 0, 0, 255))

    def test_blackbody_normalize_and_image_info(self):
        """Blackbody (Blender's fit, values from Blender 5.2), Normalize ((v - min) / (max - min) of the luminance, over a picture whose
        size is not a power of two) and Image Info (the size as a vector)."""
        self.W, self.H = 37, 23
        g = ng.new_graph()
        b = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/blackbody"})
        m = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/vector_math"})
        ng.connect(g, b, m, "src")
        ng.connect(g, m, "output", "src")
        blank = self.solid([0, 0, 0, 0])
        for temp, want in ((500, (5.41329, 0, 0)), (900, (4.98396, 0, 0)), (1500, (3.26431, 0.43405, 0)), (2500, (2.06763, 0.76932, 0.13943)),
                           (6500, (1.04255, 0.98405, 1.03527)), (10000, (0.87138, 0.99492, 1.43051)), (20000, (0.8263, 0.99451, 1.56631))):
            out, errors, _ = self.run_graph(g, blank, params={b + ".temperature": float(temp), m + ".op": "縮放", m + ".vec_scale": 0.1})
            self.assertEqual(errors, [], temp)
            self.close(out, tuple(int(round(c * 25.5)) for c in want) + (255,), 2)
        g = ng.new_graph()
        n = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/normalize"})
        ng.connect(g, "input", n, "src")
        ng.connect(g, n, "output", "src")
        rng = np.random.default_rng(5)
        rgba = np.dstack([rng.integers(0, 256, (self.H, self.W, 3)), np.full((self.H, self.W), 255)]).astype(np.uint8)
        out, errors, _ = self.run_graph(g, rgba)
        self.assertEqual(errors, [])
        lum = rgba[..., :3].astype(float) @ [0.2126, 0.7152, 0.0722]
        want = (lum - lum.min()) / (lum.max() - lum.min()) * 255
        self.assertLess(np.abs(out[..., 0].astype(float) - want).max(), 2.5)
        out, _, _ = self.run_graph(g, self.solid([100, 100, 100, 255]))
        self.close(out, (0, 0, 0, 255))                                      # (nothing to stretch: 0)
        for k, (name, want) in enumerate((("dimensions", (37, 23, 0)), ("resolution", (37, 23, 0)), ("location", (0, 0, 0)),
                                          ("rotation", (0, 0, 0)), ("scale", (1, 1, 0)))):
            g = ng.new_graph()
            n = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/image_info"})
            m = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/vector_math"})
            ng.connect(g, "input", n, "src")
            ng.connect(g, n, m, "src", name)
            ng.connect(g, m, "output", "src")
            out, errors, _ = self.run_graph(g, blank, params={m + ".op": "縮放", m + ".vec_scale": 0.005})
            self.assertEqual(errors, [], name)
            self.close(out, tuple(int(round(c * 1.275)) for c in want) + (255,), 2)

    def test_filter_node_kernels(self):
        """The Filter node against the kernels of Blender 5.2 (the reference here is numpy, the same kernels Blender gave on random pictures)."""
        rng = np.random.default_rng(11)
        rgba = rng.integers(0, 256, (self.H, self.W, 4)).astype(np.uint8)
        rgba[..., :3] = np.minimum(rgba[..., :3], rgba[..., 3:])                    # (premultiplied: colour never above the alpha)
        a = rgba.astype(float) / 255.0

        def conv(k):
            p = np.pad(a, ((1, 1), (1, 1), (0, 0)), mode="edge")
            return sum(k[j][i] * p[j:j + self.H, i:i + self.W] for j in range(3) for i in range(3))
        k = np.array
        lap = k([[-1, -1, -1], [-1, 8, -1], [-1, -1, -1]]) / 8.0

        def edge(k1, k2):
            r = np.sqrt(conv(k1) ** 2 + conv(k2) ** 2)
            r[..., 3] = a[..., 3]
            return r
        sob, pre = k([[1, 2, 1], [0, 0, 0], [-1, -2, -1]]), k([[1, 1, 1], [0, 0, 0], [-1, -1, -1]])
        kir = k([[2, 2, 2], [3, 3, 3], [-5, -5, -5]])
        want = {"柔化": conv(k([[1, 2, 1], [2, 4, 2], [1, 2, 1]]) / 16.0), "方塊銳利化": conv(k([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])),
                "菱形銳利化": conv(k([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])), "拉普拉斯": edge(lap, lap), "索伯": edge(sob, sob.T),
                "普魯伊特": edge(pre, pre.T), "基爾希": edge(kir, k([[-5, 3, 2]] * 3)), "陰影": conv(k([[-1, -2, -1], [0, 1, 0], [1, 2, 1]]))}
        g = ng.new_graph()
        n = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/filter"})
        ng.connect(g, "input", n, "src")
        ng.connect(g, n, "output", "src")
        for kind, ref in want.items():
            out, errors, _ = self.run_graph(g, rgba, params={n + ".kind": kind})
            self.assertEqual(errors, [], kind)
            self.assertLess(np.abs(out.astype(float) - np.clip(np.maximum(ref, 0), 0, 1) * 255).max(), 2.5, kind)
        out, _, _ = self.run_graph(g, rgba, params={n + ".kind": "方塊銳利化", n + ".fac": 0.5})
        mixed = np.clip(np.maximum(0.5 * a + 0.5 * want["方塊銳利化"], 0), 0, 1) * 255
        self.assertLess(np.abs(out.astype(float) - mixed).max(), 2.5)

    def test_dilate_erode_types(self):
        """Dilate / Erode against Blender 5.2: steps (square window), distance (round window), threshold (nearest edge, falloff) and feather
        (every curve; the numbers are Blender's results on a single pixel / a single hole)."""
        self.W, self.H = 32, 32
        g = ng.new_graph()
        n = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/dilate_erode"})
        ng.connect(g, "input", n, "src")
        ng.connect(g, n, "output", "src")

        def go(mask, **p):
            v = (mask * 255 + 0.5).astype(np.uint8)
            out, errors, _ = self.run_graph(g, np.dstack([v, v, v, np.full_like(v, 255)]), params={n + "." + k: x for k, x in p.items()})
            self.assertEqual(errors, [], p)
            return out[..., 0].astype(float) / 255
        dot = np.zeros((32, 32))
        dot[16, 16] = 1.0
        hole = 1.0 - dot
        block = np.zeros((32, 32))
        block[8:13, 8:13] = 1.0
        near = lambda got, want, tol=0.01: self.assertLess(np.abs(np.asarray(got) - np.asarray(want)).max(), tol, (got, want))
        want = np.zeros((32, 32))
        want[6:15, 6:15] = 1.0
        near(go(block, size=2, kind="步驟"), want)                                  # (a 5 x 5 block grows to 9 x 9)
        near(go(block, size=-1, kind="步驟")[8:13, 8:13], np.pad(np.ones((3, 3)), 1))
        near(go(block, size=0, kind="羽化"), block)                                 # (size 0: as it was)
        yy, xx = np.mgrid[-16:16, -16:16]
        near(go(dot, size=3, kind="距離"), (xx * xx + yy * yy <= 9).astype(float))
        near(go(dot, size=4, kind="閾值")[16, 16:22], [1, 1, 1, 1, 0, 0])             # (distance below the size)
        near(go(dot, size=4, kind="閾值", falloff_size=3.0)[range(16, 19), range(16, 19)], [1, (4 - 2 ** 0.5) / 3, (4 - 8 ** 0.5) / 3])
        near(go(hole, size=-4, kind="閾值", falloff_size=3.0)[16, 16:23], [0, 0, 0, 0, 0, 1 / 3, 2 / 3])
        for fall, dilated, eroded in (("平滑", [1, 0.7472, 0.2986, 0.0445, 0], [0, 0.2528, 0.7014, 0.9555, 1]),
                                      ("球形", [1, 0.9447, 0.763, 0.4456, 0], [0, 0.0553, 0.237, 0.5544, 1]),
                                      ("平方根", [1, 0.7803, 0.5285, 0.2619, 0], [0, 0.2197, 0.4715, 0.7381, 1]),
                                      ("反平方", [1, 0.893, 0.5868, 0.2048, 0], [0, 0.107, 0.4132, 0.7952, 1]),
                                      ("銳利", [1, 0.4153, 0.1354, 0.0262, 0], [0, 0.5847, 0.8646, 0.9738, 1]),
                                      ("線性", [1, 0.619, 0.2986, 0.0804, 0], [0, 0.381, 0.7014, 0.9196, 1])):
            near(go(dot, size=4, kind="羽化", falloff=fall)[16, 16:21], dilated, 0.006)
            near(go(hole, size=-4, kind="羽化", falloff=fall)[16, 16:21], eroded, 0.006)
        both = go(dot, size=4, kind="羽化", falloff="平滑")                          # (the two axes multiply)
        near(both[17, 17], 0.7472 ** 2, 0.006)
        self.W, self.H = 37, 23                                                     # (a picture that is not square)
        rng = np.random.default_rng(2)
        mask = (rng.random((23, 37)) > 0.93).astype(float)
        got = go(mask, size=3, kind="距離")
        want = np.zeros((23, 37))
        for y in range(23):
            for x in range(37):
                want[y, x] = max(mask[y + j, x + i] for j in range(-3, 4) for i in range(-3, 4)
                                 if i * i + j * j <= 9 and 0 <= y + j < 23 and 0 <= x + i < 37)
        near(got, want)

    def test_float_curve_and_vector_curves(self):
        """Float Curve / Vector Curves: a straight line leaves the values alone (also beyond 0 - 1 / -1 - 1, the ends' slope goes on), a
        curve moves them, the factor mixes."""
        g = ng.new_graph()
        f = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/float_curve"})
        ng.connect(g, "input", f, "src")
        ng.connect(g, f, "output", "src")
        grey = lambda v: self.solid([v, v, v, 255])
        for v in (0, 64, 128, 255):
            out, errors, _ = self.run_graph(g, grey(v))
            self.assertEqual(errors, [])
            self.close(out, (v, v, v, 255), 2)
        flat = {f + ".curve": [[0.0, 0.5, 0.0, 0.0, 0.0, 0.0], [1.0, 0.5, 0.0, 0.0, 0.0, 0.0]]}         # (two keys at y = 0.5)
        out, _, _ = self.run_graph(g, grey(51), params=flat)
        self.close(out, (128, 128, 128, 255), 2)
        out, _, _ = self.run_graph(g, grey(51), params={**flat, f + ".fac": 0.5})
        self.close(out, (90, 90, 90, 255), 2)                                       # (halfway between 0.2 and 0.5)
        g = ng.new_graph()
        v = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/vector_curves"})
        ng.connect(g, "input", v, "src")
        ng.connect(g, v, "output", "src")
        out, errors, _ = self.run_graph(g, self.solid([64, 128, 192, 255]))
        self.assertEqual(errors, [])
        self.close(out, (64, 128, 192, 255), 2)
        mid = [[0.0, 0.5, 0.0, 0.0, 0.0, 0.0], [1.0, 0.5, 0.0, 0.0, 0.0, 0.0]]                           # (every x gives 0.5 = 0 on the -1 - 1 side)
        out, _, _ = self.run_graph(g, self.solid([64, 128, 192, 255]), params={v + ".curve_y": mid})
        self.close(out, (64, 0, 192, 255), 2)

    def test_mask_outputs_and_rounded_square_mask(self):
        """Vignette's Mask output, Color Ramp's Alpha output and the Rounded Square Mask node (the last one checked against the node group of Blender 5.2)."""
        self.W, self.H = 40, 24
        g = ng.new_graph()
        v = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:blender_vignette"})
        ng.connect(g, "input", v, "src")
        ng.connect(g, v, "output", "src", "mask")
        out, errors, _ = self.run_graph(g, self.solid([200, 100, 50, 255]), params={v + ".factor": 0.0})
        self.assertEqual(errors, [])
        self.assertEqual(out[12, 20, 0], 0)                                         # (Blender's Mask: 0 in the middle, 1 at the edge; the strength does not touch it)
        self.assertGreater(out[0, 0, 0], 215)
        self.assertEqual(out[12, 20, 0], out[12, 20, 2])
        ng.connect(g, v, "output", "src")                                          # (the first output is still the picture)
        out, _, _ = self.run_graph(g, self.solid([200, 100, 50, 255]), params={v + ".factor": 0.0})
        self.close(out, (200, 100, 50, 255), 2)
        g = ng.new_graph()
        r = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:blender_color_ramp"})
        ng.connect(g, "input", r, "src")
        ng.connect(g, r, "output", "src", "alpha")
        out, errors, _ = self.run_graph(g, self.solid([128, 128, 128, 255]))
        self.assertEqual(errors, [])
        self.assertEqual(out[0, 0, 0], out[0, 0, 1])                                # (grey)
        g = ng.new_graph()
        m = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/rounded_square_mask"})
        ng.connect(g, "input", m, "src")
        ng.connect(g, m, "output", "src")
        out, errors, _ = self.run_graph(g, self.solid([0, 0, 0, 255]), params={m + ".size": (0.5, 0.5), m + ".angle": 0.0})
        self.assertEqual(errors, [])
        self.assertEqual(out[12, 20, 0], 255)
        self.assertEqual(out[0, 0, 0], 0)
        out, _, _ = self.run_graph(g, self.solid([0, 0, 0, 255]), params={m + ".size": (1.2, 0.6), m + ".roundness": 1.0, m + ".feather": 0.8,
                                                                           m + ".offset": (-0.3, 0.1), m + ".angle": math.degrees(0.5)})
        for (y, x), want in {(2, 5): 0.935, (6, 30): 0.422, (12, 20): 0.981, (18, 10): 0.551, (20, 35): 0.685, (22, 3): 0.116}.items():
            self.assertLess(abs(out[y, x, 0] / 255.0 - want), 0.012, (y, x))        # (values from Blender's Rounded Square Mask group)

    def test_mix_blend_modes(self):
        g = ng.new_graph()
        s = ng.add_node(g, {"type": ng.SOURCE, "kind": "image"}, base="s")
        m = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/mix"})
        ng.connect(g, "input", m, "src")
        ng.connect(g, s, m, "b")
        ng.connect(g, m, "output", "src")
        b = self.solid([128, 128, 128, 255])
        for blend, want in (("相乘", (64, 32, 0)), ("濾色", (192, 160, 128)), ("相加", (255, 192, 128)), ("差異", (0, 64, 128)),
                            ("變暗", (128, 64, 0)), ("變亮", (128, 128, 128)), ("相減", (0, 0, 0))):
            out, errors, _ = self.run_graph(g, self.solid([128, 64, 0, 255]), {s: b}, params={m + ".blend": blend})
            self.assertEqual(errors, [], blend)
            self.close(out, want + (255,), 3)
        out, _, _ = self.run_graph(g, self.solid([128, 64, 0, 255]), {s: b}, params={m + ".blend": "相乘", m + ".fac": 0.5})
        self.close(out, (96, 48, 0, 255), 3)                     # a * (1 - fac + fac * b)

    def test_map_range_and_gamma(self):
        g, n, p = self.node("map_range", from_max=2.0, to_max=4.0)
        out, _, _ = self.run_graph(g, self.solid([128, 64, 0, 255]), params={n + ".to_max": 1.0, n + ".from_max": 0.5})
        self.close(out, (146, 146, 146, 255), 2)                # the brightness 0.286 of 0 - 0.5 -> 0.572 (a float node: grey)
        g, n, p = self.node("gamma")
        out, _, _ = self.run_graph(g, self.solid([64, 64, 64, 255]), params={n + ".gamma": 2.0})
        self.close(out, (16, 16, 16, 255), 2)                    # 0.25 ** 2

    def test_channel_then_set_alpha(self):
        g = ng.new_graph()
        ch = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/separate_color"})
        sa = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/set_alpha"})
        ng.connect(g, "input", ch, "src")
        ng.connect(g, "input", sa, "src")
        ng.connect(g, ch, sa, "alpha_img", "c1")
        ng.connect(g, sa, "output", "src")
        out, errors, _ = self.run_graph(g, self.solid([128, 0, 0, 255]))
        self.assertEqual(errors, [])
        self.assertTrue(abs(int(out[0, 0, 3]) - 128) <= 2)

    def test_separate_then_combine_gives_the_picture_back(self):
        for mode, ycc in (("RGB", None), ("HSV", None), ("HSL", None), ("YCC", "ITU 601"), ("YCC", "ITU 709"), ("YCC", "JPEG"), ("YUV", None)):
            g = ng.new_graph()
            sp = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/separate_color"}, base="sp")
            cb = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/combine"}, base="cb")
            ng.connect(g, "input", sp, "src")
            for out, socket in (("c1", "src"), ("c2", "g"), ("c3", "b"), ("a", "a")):
                ng.connect(g, sp, cb, socket, out)
            ng.connect(g, cb, "output", "src")
            params = {sp + ".mode": mode, cb + ".mode": mode}
            if ycc:
                params.update({sp + ".ycc_mode": ycc, cb + ".ycc_mode": ycc})
            out, errors, _ = self.run_graph(g, self.solid([200, 90, 30, 255]), params=params)
            self.assertEqual(errors, [], mode)
            self.close(out, (200, 90, 30, 255), 4)

    def test_combine_takes_its_boxes_when_not_linked(self):
        g = ng.new_graph()
        cb = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/combine"})
        ng.connect(g, cb, "output", "src")
        out, errors, _ = self.run_graph(g, self.solid([0, 0, 0, 0]), params={cb + ".v1": 1.0, cb + ".v2": 0.5, cb + ".v3": 0.0})
        self.assertEqual(errors, [])
        self.close(out, (255, 128, 0, 255), 3)                   # not linked: the numbers of the boxes

    def test_set_alpha_types_and_its_box(self):
        g = ng.new_graph()
        sa = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/set_alpha"})
        ng.connect(g, "input", sa, "src")
        ng.connect(g, sa, "output", "src")
        src = self.solid([200, 100, 0, 128])
        out, _, _ = self.run_graph(g, src, params={sa + ".type": "套用遮罩", sa + ".alpha": 0.5})
        self.assertTrue(abs(int(out[0, 0, 3]) - 64) <= 2)                  # applied: 0.5 x 0.5
        out, _, _ = self.run_graph(g, src, params={sa + ".type": "取代透明度", sa + ".alpha": 1.0})
        self.assertEqual(int(out[0, 0, 3]), 255)                          # replaced

    def test_transform_samples_and_moves(self):
        for interp in ("最近點", "雙線性", "雙三次"):
            g, n, p = self.node("transform", pos_x=0.0)
            out, errors, _ = self.run_graph(g, self.solid([128, 64, 0, 255]), params={n + ".interp": interp})
            self.assertEqual(errors, [], interp)
            self.close(out, (128, 64, 0, 255), 3)
        g, n, p = self.node("transform")
        out, _, _ = self.run_graph(g, self.solid([128, 64, 0, 255]), params={n + ".pos_x": 100000.0})
        self.assertEqual(int(out[0, 0, 3]), 0)                            # moved out of the picture: clear

    def test_mute_passes_the_picture_on(self):
        g = ng.new_graph()
        c = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/math", "mute": True})
        ng.connect(g, "input", c, "src")
        ng.connect(g, c, "output", "src")
        red = self.solid([255, 0, 0, 255])
        out, _, _ = self.run_graph(g, red)
        self.assertTrue((out == red).all())

    def test_thumbnails_are_shrunk_on_the_card_before_they_are_read(self):
        eng = engine()
        with eng.ctx:
            for dtype, raw in (("f1", bytes([255, 0, 0, 255]) * (400 * 200)),
                               ("f2", np.tile(np.array([1.0, 0.0, 0.0, 1.0], np.float16), 400 * 200).tobytes())):
                tex = eng.ctx.texture((400, 200), 4, raw, dtype=dtype)
                w, h, data = ng.small_rgba8(tex, 96)
                self.assertEqual((w, h, len(data)), (100, 50, 100 * 50 * 4), dtype)        # (400 / 4: two levels down)
                self.assertEqual(data[:4], bytes([255, 0, 0, 255]), dtype)
                self.assertEqual(ng.small_rgba8(tex, 500)[:2], (400, 200))                  # (small enough: as it is)
                tex.release()

    def test_no_leaks_between_runs(self):
        g = ng.new_graph()
        prev = "input"
        for _ in range(4):
            n = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/math"})
            ng.connect(g, prev, n, "src")
            prev = n
        ng.connect(g, prev, "output", "src")
        _out, _e, pool = self.run_graph(g, self.solid([1, 2, 3, 255]))
        self.assertLessEqual(len(pool.spare), 3)               # chain of 4: at most two live + the result

    def test_loop_is_an_error(self):
        g = ng.new_graph()
        a = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/math"})
        b = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/math"})
        g["links"] += [{"from": a, "to": b, "socket": "src"}, {"from": b, "to": a, "socket": "src"},
                       {"from": b, "to": "output", "socket": "src"}]
        self.assertIsNotNone(ng.check(g))
        with self.assertRaises(ng.GraphError):
            self.run_graph(g, self.solid([0, 0, 0, 255]))


if __name__ == "__main__":
    unittest.main()


class GroupTests(unittest.TestCase):
    def build(self):
        g = ng.new_graph()
        a = ng.add_node(g, {"type": "filter", "ref": "builtin:nodes/math"}, 100, 0)
        b = ng.add_node(g, {"type": "filter", "ref": "builtin:nodes/math"}, 200, 0)
        ng.connect(g, "input", a, "src")
        ng.connect(g, a, b, "src")
        ng.connect(g, b, "output", "src")
        return g, a, b

    def test_make_group_rewires_the_border(self):
        g, a, b = self.build()
        gid = ng.make_group(g, [a, b])
        grp = g["nodes"][gid]
        self.assertEqual(ng.members(g, gid), [a, b])
        self.assertEqual([i["to"] for i in grp["inputs"]], [[[a, "src"]]])
        self.assertEqual([(o["from"], o["out"]) for o in grp["outputs"]], [(b, "")])
        self.assertEqual({(l["from"], l["to"]) for l in g["links"]},
                         {("input", gid), (gid, "output"), (a, b)})
        flat = ng.flatten(g)
        self.assertNotIn(gid, flat["nodes"])
        self.assertEqual({(l["from"], l["to"], l["socket"]) for l in flat["links"]},
                         {("input", a, "src"), (a, b, "src"), (b, "output", "src")})
        self.assertIsNone(ng.check(g))

    def test_ungroup_gives_the_same_graph_back(self):
        g, a, b = self.build()
        before = {(l["from"], l["to"], l["socket"]) for l in g["links"]}
        gid = ng.make_group(g, [a, b])
        ng.ungroup(g, gid)
        self.assertEqual({(l["from"], l["to"], l["socket"]) for l in g["links"]}, before)
        self.assertNotIn("group", g["nodes"][a])
        self.assertNotIn(gid, g["nodes"])

    def test_group_sockets_can_be_added_and_taken_away(self):
        g, a, b = self.build()
        c = ng.add_node(g, {"type": "filter", "ref": "builtin:nodes/mix"}, 150, 80)
        gid = ng.make_group(g, [a, b, c])
        name = ng.group_input(g, gid, c, "b")
        self.assertIn((name, "圖像"), [(s, l) for s, l in ng.sockets(g["nodes"][gid])] + [(name, "圖像")])
        ng.connect(g, "input", gid, name)
        flat = ng.flatten(g)
        self.assertIn(("input", c, "b"), {(l["from"], l["to"], l["socket"]) for l in flat["links"]})
        ng.group_unplug(g, gid, c, "b")
        self.assertNotIn(name, [s for s, _ in ng.sockets(g["nodes"][gid])])
        self.assertFalse([l for l in g["links"] if l["to"] == gid and l["socket"] == name])

    def test_removing_a_group_removes_its_members(self):
        g, a, b = self.build()
        gid = ng.make_group(g, [a, b])
        ng.remove_node(g, gid)
        self.assertEqual(set(g["nodes"]), {"input", "output"})

    def test_groups_inside_groups(self):
        g, a, b = self.build()
        inner = ng.make_group(g, [a])
        outer = ng.make_group(g, [inner, b])
        self.assertEqual(g["nodes"][inner]["group"], outer)
        flat = ng.flatten(g)
        self.assertEqual({(l["from"], l["to"]) for l in flat["links"]}, {("input", a), (a, b), (b, "output")})


class SunPositionTests(unittest.TestCase):
    def test_projects_saved_with_y_down_are_turned_over_when_opened(self):
        from kiasecut import project
        g = ng.new_graph()
        n = ng.add_node(g, {"type": "filter", "ref": "builtin:blender_glare"})
        graph_fx = {"id": "e2", "filter": "nodes:graph", "enabled": True, "graph": g,
                    "params": {n + ".sun_position": [0.5, -0.05]}}
        plain = {"id": "e1", "filter": "builtin:blender_glare", "enabled": True,
                 "params": {"sun_position": [0.25, {"keys": [[0, 0.2, 0, 0, 5, 0.1], [100, 0.7, -5, -0.1, 0, 0]]}], "type": "Sun Beams"}}
        clip = {"id": "c1", "type": "image", "name": "c", "start_us": 0, "duration_us": 10, "source_start_us": 0,
                "media": {"path": "x.png", "width": 1, "height": 1}, "effects": [plain, graph_fx]}
        old = {"format": project.FORMAT, "version": 4, "width": 16, "height": 9, "fps": 30, "duration_us": 10, "compounds": {},
               "tracks": [{"id": "t0", "kind": "video", "name": "v", "clips": [clip]}]}
        p = project.normalize(old)
        self.assertEqual(p["version"], project.VERSION)
        self.assertEqual(graph_fx["params"][n + ".sun_position"], [0.5, 1.05])
        y = plain["params"]["sun_position"][1]
        self.assertEqual((plain["params"]["sun_position"][0], y["keys"][0][1], y["keys"][1][1]), (0.25, 0.8, 0.30000000000000004))
        self.assertEqual((y["keys"][0][3], y["keys"][0][5], y["keys"][1][3]), (0, -0.1, 0.1))     # (handles turn over too)
        project.normalize(p)                                                   # (once only)
        self.assertEqual(graph_fx["params"][n + ".sun_position"], [0.5, 1.05])
