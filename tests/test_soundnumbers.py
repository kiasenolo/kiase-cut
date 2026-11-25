"""Numbers wired between sound nodes: what the number nodes work out, how they wire, and what
the wired effect sounds like."""
import os
import re
import unittest

from kiasecut import dsp, edit, rack, soundedit, soundfx, soundmeter, soundnodes, soundnumbers
from tests.test_soundedit import make
from tests.test_soundgraph import REF, US, Base, rms
from tests.test_soundmeter import BOX, Sounds, make_root

HALF = -6.0206


def graph(*kinds, **params):
    """A graph with a node of each kind; returns (graph, their ids)."""
    g = soundnodes.new_graph()
    return g, [soundnodes.add(g, soundnodes.new_node(k)) for k in kinds]


def number(kind, **values):
    node = soundnodes.new_node(kind)
    for name, v in values.items():
        if name == "op":
            v = soundnumbers.MATH_OPS.index(v)
        if name == "mode":
            v = (soundnumbers.MAP_MODES if kind == "maprange" else soundnumbers.CLAMP_MODES).index(v)
        node["params"][name] = v
    return soundnumbers.Numbers({"n": node}, {}, 0).of("n")


class CalcTests(unittest.TestCase):
    def test_the_operations_are_the_picture_nodes(self):
        path = os.path.join(os.path.dirname(soundnumbers.__file__), "filters", "nodes", "math.glsl")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        ops = re.search(r'@param op menu \S+ "([^"]+)"', text).group(1).split("|")
        self.assertEqual(ops, soundnumbers.MATH_OPS)
        shown = lambda name: re.search(rf"@show {name} op (\S+) (\S+)", text).group(2).split("|")
        self.assertEqual(sorted(shown("value")), sorted(soundnumbers.ONE_INPUT))
        self.assertEqual(sorted(shown("value3")), sorted(soundnumbers.THREE_INPUTS))
        self.assertEqual(sorted(soundnumbers._MATH), sorted(ops))

    def test_math(self):
        for op, a, b, c, want in (
                ("相加", 2, 3, 0, 5), ("相除", 1, 0, 0, 0), ("乘加", 2, 3, 4, 10), ("次方", -2, 2, 0, 4),
                ("次方", -2, 3, 0, -8), ("次方", -2, 0.5, 0, 0), ("次方", 0, -1, 0, 0), ("對數", 8, 2, 0, 3),
                ("對數", 8, 1, 0, 0), ("平方根", -4, 0, 0, 0), ("四捨五入", -1.5, 0, 0, -1), ("截斷", -1.7, 0, 0, -1),
                ("小數部分", -1.25, 0, 0, 0.75), ("截斷取餘", -7, 3, 0, -1), ("向下取餘", -7, 3, 0, 2),
                ("迴繞", 5, 3, 1, 1), ("迴繞", -1, 4, 0, 3), ("對齊", 7, 3, 0, 6), ("來回", 2.5, 2, 0, 1.5),
                ("比較", 1.0, 1.05, 0.1, 1), ("平滑最小", 1, 5, 0, 1), ("反正弦", 2, 0, 0, 1.5707963),
                ("指數", 1e9, 0, 0, 0)):
            self.assertAlmostEqual(number("math", op=op, a=a, b=b, c=c), want, places=5, msg=(op, a, b, c))
        self.assertEqual(number("math", op="相加", a=2, b=3, clamp=1), 1.0)

    def test_map_range_and_clamp(self):
        m = lambda **kw: number("maprange", **kw)
        self.assertAlmostEqual(m(x=0.5, to_min=10, to_max=20), 15)
        self.assertAlmostEqual(m(x=2.0, to_min=10, to_max=20), 20)
        self.assertAlmostEqual(m(x=2.0, to_min=10, to_max=20, clamp=0), 30)
        self.assertAlmostEqual(m(x=0.5, to_min=100, to_max=10000, mode="對數"), 1000)
        self.assertAlmostEqual(m(x=0.5, to_min=-1, to_max=1, mode="對數"), 0)       # (no ratio there: a straight line)
        self.assertAlmostEqual(m(x=0.25, mode="平滑"), 0.15625)
        self.assertAlmostEqual(m(x=0.6, steps=1, mode="階梯"), 1.0)
        self.assertAlmostEqual(m(x=5, from_min=3, from_max=3), 0)
        self.assertEqual(number("clamp", x=5, lo=1, hi=0), 0)
        self.assertEqual(number("clamp", x=5, lo=1, hi=0, mode="範圍"), 1)


class WiringTests(unittest.TestCase):
    def test_numbers_and_sound_never_join(self):
        g, (v, m, gain) = graph("value", "math", "gain")
        self.assertTrue(soundnodes.can_link(g, v, 0, gain, "param:gain"))
        self.assertTrue(soundnodes.can_link(g, v, 0, m, "param:a"))
        self.assertTrue(soundnodes.can_link(g, v, 0, m, "param:op"))
        self.assertFalse(soundnodes.can_link(g, v, 0, gain, 0))
        self.assertFalse(soundnodes.can_link(g, v, 0, "out", 0))
        self.assertFalse(soundnodes.can_link(g, "in", 0, gain, "param:gain"))
        self.assertFalse(soundnodes.can_link(g, v, 0, gain, "param:nothing"))
        self.assertFalse(soundnodes.can_link(g, m, 0, v, "param:value"))
        soundnodes.connect(g, v, 0, m, "param:a")
        soundnodes.connect(g, m, 0, gain, "param:gain")
        self.assertFalse(soundnodes.can_link(g, m, 0, m, "param:b"))
        g2, (a, b) = graph("math", "math")
        soundnodes.connect(g2, a, 0, b, "param:a")
        self.assertFalse(soundnodes.can_link(g2, b, 0, a, "param:a"))         # a loop

    def test_a_looked_ahead_time_cannot_be_wired(self):
        g, (v, lim) = graph("value", "limiter")
        self.assertFalse(soundnodes.can_link(g, v, 0, lim, "param:lk"))

    def test_insert_remove_copy(self):
        g, (v, m, gain) = graph("value", "math", "gain")
        soundnodes.connect(g, v, 0, m, "param:a")
        soundnodes.connect(g, m, 0, gain, "param:gain")
        with self.assertRaises(ValueError):
            soundnodes.insert_on_link(g, m, [m, 0, gain, "param:gain"])
        copied = soundnodes.paste(g, soundnodes.copy_nodes(g, [v, m]))
        self.assertIn([copied[0], 0, copied[1], "param:a"], g["links"])
        soundnodes.remove(g, [m], keep_links=True)
        self.assertIn([v, 0, gain, "param:gain"], g["links"])

    def test_a_chain_of_many_is_worked_out_once_each(self):
        g, ids = graph(*["math"] * 30)
        for a, b in zip(ids, ids[1:]):
            soundnodes.connect(g, a, 0, b, "param:a")
            soundnodes.connect(g, a, 0, b, "param:b")
        self.assertEqual(soundnodes.numbers(g, 0).of(ids[-1]), 2.0 ** 29)

    def test_new_nodes_are_wired_by_kind(self):
        p = make()
        target = ("clip", "c1")
        e = soundedit.add_effect(p, target, soundfx.GRAPH)
        gain = soundedit.add_node(p, target, e, "gain", 0, 0)
        math_ = soundedit.add_node(p, target, e, "math", 0, 0, None, (gain, "param:gain"))
        other = soundedit.add_node(p, target, e, "clamp", 0, 0, (math_, 0))
        links = soundedit.graph(p, target, e)["links"]
        self.assertIn([math_, 0, gain, "param:gain"], links)
        self.assertIn([math_, 0, other, "param:x"], links)

    def test_curve_editor_rows_and_keys(self):
        p = make()
        target = ("clip", "c1")
        e = soundedit.add_effect(p, target, soundfx.GRAPH)
        v = soundedit.add_node(p, target, e, "value", 0, 0)
        soundedit.toggle_key(p, target, f"{e}/{v}", "value", 0)
        soundedit.set_param(p, target, f"{e}/{v}", "value", 5000.0, US)
        rows = soundfx.clip_rows(soundedit.chain(p, target))
        self.assertIn((f"sfx:{e}/{v}", "value"), [r[:2] for r in rows])


@unittest.skipUnless(dsp.available(), f"no sound library: {dsp.error()}")
class SoundTests(Base):
    def run_graph(self, build):
        v = self.view([{"clips": [self.clip("a", self.low)]}])
        g = soundnodes.new_graph()
        build(g, v)
        v["tracks"][0]["sound_effects"] = [{"id": "e", "effect": "graph", "graph": g}]
        return self.sound(v)

    def gain_graph(self, g, source):
        n = soundnodes.add(g, soundnodes.new_node("gain"))
        soundnodes.connect(g, "in", 0, n, 0)
        soundnodes.connect(g, n, 0, "out", 0)
        soundnodes.connect(g, source, 0, n, "param:gain")
        return n

    def test_a_wired_number_is_the_parameter(self):
        def build(g, _v):
            src = soundnodes.add(g, soundnodes.new_node("value"))
            g["nodes"][src]["params"]["value"] = HALF
            n = self.gain_graph(g, src)
            g["nodes"][n]["params"]["gain"] = 12.0                  # (the wire is over it)
        self.assertAlmostEqual(rms(self.run_graph(build)), REF / 2, delta=0.002)

    def test_held_to_the_limits_and_muted(self):
        def build(g, _v, mute=False):
            src = soundnodes.add(g, soundnodes.new_node("value"))
            g["nodes"][src]["params"]["value"] = -1000.0
            if mute:
                g["nodes"][src]["mute"] = True
            self.gain_graph(g, src)
        self.assertAlmostEqual(rms(self.run_graph(build)), REF * 0.001, delta=0.0002)        # -60 dB
        self.assertAlmostEqual(rms(self.run_graph(lambda g, v: build(g, v, True))), REF, delta=0.002)

    def test_math_follows_a_global_parameter_over_time(self):
        def build(g, v):
            v["rack"] = [{"id": "r1", "name": "k", "value": {"keys": [[0, 0.0, 0, 0, 0, 0], [US // 2, 0.0, 0, 0, 0, 0],
                                                                     [US // 2 + 1, 1.0, 0, 0, 0, 0]]}}]
            src = soundnodes.add(g, soundnodes.new_node("global"))
            g["nodes"][src]["expr"] = {"value": "k"}
            m = soundnodes.add(g, soundnodes.new_node("math"))
            g["nodes"][m]["params"].update(op=soundnumbers.MATH_OPS.index("相乘"), b=HALF)
            soundnodes.connect(g, src, 0, m, "param:a")
            self.gain_graph(g, m)
        a = self.run_graph(build)
        self.assertAlmostEqual(rms(a, 0.1, 0.4), REF, delta=0.003)
        self.assertAlmostEqual(rms(a, 0.6, 0.9), REF / 2, delta=0.003)

    def test_a_wired_mixer_level(self):
        def build(g, _v):
            mix = soundnodes.add(g, soundnodes.new_node("mix"))
            src = soundnodes.add(g, soundnodes.new_node("value"))
            g["nodes"][src]["params"]["value"] = HALF
            soundnodes.connect(g, "in", 0, mix, 0)
            soundnodes.connect(g, mix, 0, "out", 0)
            soundnodes.connect(g, src, 0, mix, "param:g1")
        self.assertAlmostEqual(rms(self.run_graph(build)), REF / 2, delta=0.002)


@unittest.skipUnless(dsp.available(), f"no sound library: {dsp.error()}")
class MeterTests(Sounds):
    """A 全局參數 node reads what a binding would: 聲音轉數值 sees it."""

    def test_the_node_counts_as_a_reader(self):
        root = make_root([{"clips": [self.kick_clip()]}, {"clips": [self.clip("a", self.low)]}])
        edit.add_rack_param(root, "kick", 0.0)
        edit.set_rack_sound(root, "r1", soundmeter.make("tl1", "t1", **BOX))
        level = {"tracks": root["tracks"]}
        e = soundedit.add_effect(level, ("track", "t1"), soundfx.GRAPH)
        n = soundedit.add_node(level, ("track", "t1"), e, "global", 0, 0)
        with self.assertRaisesRegex(edit.EditError, "循環"):       # the kick's own track may not hear itself
            soundedit.bind(root, level, ("track", "t1"), f"{e}/{n}", "value", "kick")
        e2 = soundedit.add_effect(level, ("track", "t2"), soundfx.GRAPH)
        n2 = soundedit.add_node(level, ("track", "t2"), e2, "global", 0, 0)
        del root["tracks"][0]["sound_effects"][0]["graph"]["nodes"][n]["expr"]
        soundedit.bind(root, level, ("track", "t2"), f"{e2}/{n2}", "value", "kick")
        self.assertEqual(rack.users(root, "kick"), 1)
        self.assertEqual(soundmeter.snapshot(root, "tl1", "t2").reads(), {"kick"})
        edit.rename_rack_param(root, "r1", "boom")
        self.assertEqual(soundedit.effect(level, ("track", "t2"), f"{e2}/{n2}")["expr"], {"value": "boom"})


if __name__ == "__main__":
    unittest.main()
