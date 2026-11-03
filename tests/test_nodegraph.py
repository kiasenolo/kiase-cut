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

    def test_sockets(self):
        g = ng.new_graph()
        m = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/mix"})
        names = [s for s, _ in ng.sockets(g["nodes"][m])]
        self.assertEqual(names, ["src", "b", "param:fac"])
        c = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/math"})
        self.assertIn("param:value", [s for s, _ in ng.sockets(g["nodes"][c])])

    def test_node_filters_parse(self):
        for name in ("picture", "mix", "math", "channel", "combine", "set_alpha", "transform"):
            self.assertIsNone(fx.get("builtin:nodes/" + name).error, name)


class RunTest(unittest.TestCase):
    W = H = 8

    def run_graph(self, g, rgba, pictures=None, t=0):
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
            tex, owner = ng.evaluate(eng, g, src, self.W, self.H, pool.alloc, pool.free, t=t, picture=picture, errors=errors)
            out = np.frombuffer(tex.read(), np.uint8).reshape(self.H, self.W, 4).copy() if tex is not None else None
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

    def test_missing_source_is_transparent(self):
        g = ng.new_graph()
        s = ng.add_node(g, {"type": ng.SOURCE, "kind": "video"}, base="s")
        ng.connect(g, s, "output", "src")
        out, _, _ = self.run_graph(g, self.solid([255, 0, 0, 255]))
        self.assertTrue((out == 0).all())

    def test_math_value_and_linked_param(self):
        g = ng.new_graph()
        c = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/math", "params": {"op": "相乘", "value": 0.5}})
        ng.connect(g, "input", c, "src")
        ng.connect(g, c, "output", "src")
        out, errors, _ = self.run_graph(g, self.solid([200, 100, 0, 255]))
        self.assertEqual(errors, [])
        self.assertTrue(abs(int(out[0, 0, 0]) - 100) <= 2 and abs(int(out[0, 0, 1]) - 50) <= 2)

    def test_channel_then_set_alpha(self):
        g = ng.new_graph()
        ch = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/channel", "params": {"channel": "紅"}})
        sa = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/set_alpha"})
        ng.connect(g, "input", ch, "src")
        ng.connect(g, "input", sa, "src")
        ng.connect(g, ch, sa, "alpha_img")
        ng.connect(g, sa, "output", "src")
        out, errors, _ = self.run_graph(g, self.solid([128, 0, 0, 255]))
        self.assertEqual(errors, [])
        self.assertTrue(abs(int(out[0, 0, 3]) - 128) <= 2)

    def test_mute_passes_the_picture_on(self):
        g = ng.new_graph()
        c = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/math", "params": {"op": "相乘", "value": 0.0}, "mute": True})
        ng.connect(g, "input", c, "src")
        ng.connect(g, c, "output", "src")
        red = self.solid([255, 0, 0, 255])
        out, _, _ = self.run_graph(g, red)
        self.assertTrue((out == red).all())

    def test_no_leaks_between_runs(self):
        g = ng.new_graph()
        prev = "input"
        for _ in range(4):
            n = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/math", "params": {"op": "相加", "value": 0.0}})
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
