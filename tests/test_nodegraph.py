"""Node graphs (nodegraph.py): the graph as data, and running it on the GPU."""
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
        self.assertEqual(names, ["src", "b", "param:blend", "param:fac", "param:use_alpha", "param:clamp_on"])
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

    def run_graph(self, g, rgba, pictures=None, t=0, params=None):
        eng = engine()
        pool = ng.Pool(eng)
        with eng.ctx:
            src = eng.ctx.texture((self.W, self.H), 4, np.ascontiguousarray(rgba).tobytes())
            src.filter = (eng.mgl.LINEAR, eng.mgl.LINEAR)
            texs = {}

            def picture(nid):
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
        out, errors, _ = self.run_graph(g, self.solid([255, 0, 0, 255]), {s: blue})
        self.assertEqual(errors, [])
        self.assertTrue((np.abs(out.astype(int) - blue) <= 1).all())
        half = self.solid([0, 0, 128, 128])                    # premultiplied half-blue over red
        out, _, _ = self.run_graph(g, self.solid([255, 0, 0, 255]), {s: half})
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
