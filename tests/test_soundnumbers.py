"""Numbers wired between sound nodes: what the number nodes work out, how they wire, and what
the wired effect sounds like."""
import os
import re
import unittest

import numpy as np

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


def one(kind, t_us=0, length=0, output=0, mute=False, names=None, curve=None, **values):
    node = soundnodes.new_node(kind)
    node["params"].update(values) if values else None
    node.update({k: v for k, v in (("mute", mute), ("names", names), ("curve", curve)) if v})
    return soundnumbers.Numbers({"n": node}, {}, t_us, length=length).of("n", output)


class SecondBatchTests(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(one("integer", value=2.6), 3)
        self.assertEqual(one("boolean", value=1), 1)
        self.assertEqual(one("menu", value=5), 5)
        for kind in soundnumbers.CONSTANTS:
            self.assertEqual(soundnodes.wire_specs(soundnodes.new_node(kind)), [], kind)
            self.assertIsNone(one(kind, mute=True))

    def test_scene_time(self):
        self.assertEqual(one("scenetime", 3 * US, 12 * US), 3.0)
        self.assertEqual(one("scenetime", 3 * US, 12 * US, output=1), 0.25)
        self.assertEqual(one("scenetime", 30 * US, 12 * US, output=1), 1.0)
        self.assertEqual(one("scenetime", 3 * US, 0, output=1), 0.0)
        g, (st, gain) = graph("scenetime", "gain")
        soundnodes.connect(g, st, 1, gain, "param:gain")
        soundnodes.connect(g, st, 0, gain, "param:gain")      # (in the other's place)
        soundnodes.connect(g, st, 1, gain, "param:gain")
        got = soundnodes.numbers(g, 3 * US, length=12 * US).into(gain, soundnodes.wire_specs(g["nodes"][gain]))
        self.assertEqual(got, {"gain": 0.25})

    def test_float_curve(self):
        for x in (-0.5, 0.0, 0.3, 1.0, 1.5):                  # (a straight line, extended)
            self.assertAlmostEqual(one("floatcurve", value=x), x, places=6)
        flip = [[0, 1, 0, 0, 0, 0], [1, 0, 0, 0, 0, 0]]
        self.assertAlmostEqual(one("floatcurve", value=0.25, curve=flip), 0.75, places=6)
        self.assertAlmostEqual(one("floatcurve", value=2.0, curve=flip), -1.0, places=6)
        self.assertAlmostEqual(one("floatcurve", value=0.25, fac=0.5, curve=flip), 0.5, places=6)
        self.assertEqual(one("floatcurve", value=0.25, curve=flip, mute=True), 0.25)

    def test_mix_and_switches(self):
        self.assertEqual(one("valmix", a=10, b=20, fac=0.25), 12.5)
        self.assertEqual(one("valmix", a=10, b=20, fac=2), 20)
        self.assertEqual(one("valmix", a=10, b=20, fac=2, clamp_fac=0), 30)
        self.assertEqual(one("switch", a=3, b=4), 3)
        self.assertEqual(one("switch", a=3, b=4, use=1), 4)
        v = {"v0": 5, "v1": 6, "v2": 7}
        self.assertEqual(one("indexswitch", index=1, **v), 6)
        self.assertEqual(one("indexswitch", index=2, **v), 0)           # (only two of them)
        self.assertEqual(one("indexswitch", index=2, count=3, **v), 7)
        self.assertEqual(one("indexswitch", index=-1, **v), 0)
        self.assertEqual(one("menuswitch", choice=2, **v), 7)
        self.assertEqual(one("menuswitch", choice=2, count=2, **v), 6)  # (held to the options there are)
        self.assertEqual(one("menuswitch", choice=2, mute=True, **v), 5)

    def test_option_names(self):
        node = soundnodes.new_node("menuswitch")
        node["names"] = {"v1": "副歌"}
        self.assertEqual(soundnumbers.spec(node, "choice")["choices"], ["選項 1", "副歌", "選項 3"])
        self.assertEqual(soundnumbers.spec(node, "v1")["label"], "副歌")
        self.assertEqual(soundfx.spec(node, "v1")["label"], "副歌")
        shown = [p["name"] for p in soundnumbers.specs(node) if p["name"] != "choice"]
        self.assertNotIn("count", [r[1] for r in soundfx.clip_rows(
            [{"id": "e", "effect": "graph", "graph": {"nodes": {"n1": node}, "links": []}}])])
        self.assertIn("v7", shown)

    def test_wired_through_two_switches(self):
        g, (menu, ms, sw, gain) = graph("menu", "menuswitch", "switch", "gain")
        g["nodes"][menu]["params"]["value"] = 1
        g["nodes"][ms]["params"]["v1"] = -3.0
        soundnodes.connect(g, menu, 0, ms, "param:choice")
        soundnodes.connect(g, ms, 0, sw, "param:b")
        soundnodes.connect(g, sw, 0, gain, "param:gain")
        g["nodes"][sw]["params"]["use"] = 1
        into = lambda: soundnodes.numbers(g, 0).into(gain, soundnodes.wire_specs(g["nodes"][gain]))
        self.assertEqual(into(), {"gain": -3.0})
        soundnodes.remove(g, [sw], keep_links=True)           # (what fed its A goes on: nothing here)
        self.assertEqual(into(), {})


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


@unittest.skipUnless(dsp.available(), f"no sound library: {dsp.error()}")
class SceneTimeSoundTests(Base):
    def chain(self):
        """A gain halved once 場景時間's 進度 is past a half."""
        g = soundnodes.new_graph()
        st = soundnodes.add(g, soundnodes.new_node("scenetime"))
        past = soundnodes.add(g, soundnodes.new_node("math"))
        g["nodes"][past]["params"].update(op=soundnumbers.MATH_OPS.index("大於"), b=0.5)
        to = soundnodes.add(g, soundnodes.new_node("valmix"))
        g["nodes"][to]["params"].update(a=0.0, b=HALF)
        gain = soundnodes.add(g, soundnodes.new_node("gain"))
        soundnodes.connect(g, st, 1, past, "param:a")
        soundnodes.connect(g, past, 0, to, "param:fac")
        soundnodes.connect(g, to, 0, gain, "param:gain")
        soundnodes.connect(g, "in", 0, gain, 0)
        soundnodes.connect(g, gain, 0, "out", 0)
        return [{"id": "e", "effect": "graph", "graph": g}]

    def check(self, view, first, second):
        a = self.sound(view)
        self.assertAlmostEqual(rms(a, 0.15, 0.4), first, delta=0.003)
        self.assertAlmostEqual(rms(a, 0.65, 0.9), second, delta=0.003)

    def test_on_a_clip_it_is_the_clips_time(self):
        c = self.clip("a", self.low, sound_effects=self.chain())
        longer = {"clips": [self.clip("b", self.high, 5.0)]}
        self.check(self.view([{"clips": [c]}, longer]), REF, REF / 2)

    def test_on_a_track_it_is_the_timelines(self):
        v = self.view([{"clips": [self.clip("a", self.low)], "sound_effects": self.chain()}])
        self.check(v, REF, REF / 2)
        v["tracks"].append({"id": "t2", "kind": "audio", "name": "A2", "clips": [self.clip("b", self.high, 5.0)]})
        self.check(v, REF, REF)

    def test_a_meter_counts_what_its_copy_leaves_out(self):
        root = make_root([{"clips": [self.clip("a", self.low)], "sound_effects": self.chain()},
                          {"clips": [self.clip("b", self.high, 5.0)]}])
        snap = soundmeter.snapshot(root, "tl1", "t1")
        self.assertEqual(snap.view["tracks"][1]["clips"], [])       # (not heard, but it makes the timeline longer)
        self.assertEqual(snap.view["length_us"], 6 * US)
        plain = make_root([{"clips": [self.clip("a", self.low)]}])
        self.assertNotIn("length_us", soundmeter.snapshot(plain, "tl1", "t1").view)


if __name__ == "__main__":
    unittest.main()


LEVEL = dict(lo_hz=40.0, hi_hz=200.0, floor_db=-36.0, top_db=-12.5, attack=0.0, release=0.0)


def level_graph(effect="gain", param="gain", to=(0.0, -60.0), **box):
    """A graph whose `effect` has `param` follow how loud the kicks wired into 電平 are."""
    g = soundnodes.new_graph()
    lv = soundnodes.add(g, soundnodes.new_node("level"))
    g["nodes"][lv]["params"].update(LEVEL, **box)
    m = soundnodes.add(g, soundnodes.new_node("maprange"))
    g["nodes"][m]["params"].update(to_min=to[0], to_max=to[1])
    n = soundnodes.add(g, soundnodes.new_node(effect))
    soundnodes.connect(g, lv, 0, m, "param:x")
    soundnodes.connect(g, m, 0, n, "param:" + param)
    soundnodes.connect(g, n, 0, "out", 0)
    return g, lv, n


class LevelWiringTests(unittest.TestCase):
    def test_sound_in_a_number_out(self):
        g, (lv, gain, m) = graph("level", "gain", "math")
        self.assertTrue(soundnodes.can_link(g, "in", 0, lv, 0))
        self.assertTrue(soundnodes.can_link(g, lv, 0, gain, "param:gain"))
        self.assertFalse(soundnodes.can_link(g, lv, 0, "out", 0))
        soundnodes.connect(g, "in", 0, lv, 0)
        soundnodes.connect(g, lv, 0, m, "param:a")
        with self.assertRaises(ValueError):                         # not into a wire of sound
            soundnodes.insert_on_link(g, soundnodes.add(g, soundnodes.new_node("level")), ["in", 0, "out", 0])
        self.assertIn(["in", 0, "out", 0], g["links"])              # (nothing was undone by trying)
        soundnodes.remove(g, [lv], keep_links=True)
        self.assertEqual([l for l in g["links"] if l[2] == m], [])

    def test_a_loop_through_a_number_is_refused(self):
        g, (lv, gain) = graph("level", "gain")
        soundnodes.connect(g, gain, 0, lv, 0)
        self.assertFalse(soundnodes.can_link(g, lv, 0, gain, "param:gain"))

    def test_nothing_heard_leaves_the_parameter_as_it_is(self):
        g, lv, n = level_graph()
        self.assertIsNone(soundnodes.numbers(g, 0).of(lv))
        self.assertEqual(soundnodes.numbers(g, 0, heard=lambda i: 1.0).into(n, soundnodes.wire_specs(g["nodes"][n])),
                         {"gain": -60.0})


@unittest.skipUnless(dsp.available(), f"no sound library: {dsp.error()}")
class LevelSoundTests(Sounds):
    """The kicks (0.5 - 0.7 s and 1.5 - 1.7 s) on track 2 turn down the steady tone on track 1."""

    def view_of(self, g):
        low = self.clip("a", self.low)
        v = self.view([{"clips": [low, dict(low, id="a2", start_us=US)], "sound_effects": [
            {"id": "e", "effect": "graph", "graph": g}]}, {"clips": [self.kick_clip()], "muted": False,
                                                           "routes": []}])
        return v

    def ducked(self, **box):
        g, lv, n = level_graph(**box)
        ext = soundnodes.add(g, soundnodes.new_node("ext"))
        g["nodes"][ext]["channel"] = "t2"
        soundnodes.connect(g, ext, 0, lv, 0)
        soundnodes.connect(g, "in", 0, n, 0)
        return g

    def test_a_side_chain_made_of_nodes(self):
        a = self.sound(self.view_of(self.ducked()), 2.0)
        self.assertAlmostEqual(rms(a, 0.2, 0.45), REF, delta=0.003)
        self.assertLess(rms(a, 0.56, 0.68), REF * 0.01)
        self.assertAlmostEqual(rms(a, 0.85, 1.4), REF, delta=0.003)
        self.assertLess(rms(a, 1.56, 1.68), REF * 0.01)

    def test_from_the_middle_as_from_the_start(self):
        v = self.view_of(self.ducked(release=400.0))
        whole = self.sound(v, 2.0)
        m = self.mixer(v)
        for first in (24, 17):                                        # while the release of the first kick is falling
            part = np.frombuffer(b"".join(m.mix(f, 30.0) for f in range(first, first + 6)), np.int16)
            np.testing.assert_allclose(part.reshape(-1, 2) / 32768, whole[first * 1600:(first + 6) * 1600], atol=2e-3)

    def test_as_the_rack_measures_only_a_little_later(self):
        sound = np.concatenate([np.zeros(48000 // 2), 0.25 * np.sin(2 * np.pi * 100 * np.arange(48000) / 48000),
                                np.zeros(48000 // 2)]).astype(np.float32)
        follower = soundmeter.Follower()
        live = [follower.feed(sound[i:i + 512], 40, 200, -36, -12.5, 0.02, 0.2) for i in range(0, 48000 * 2, 512)]
        spec = dict(BOX, attack=0.02, release=0.2)
        curve = soundmeter.shape(soundmeter.box_db(sound, 40, 200), spec)
        # the block that ends at e hears the window centred on e - N / 2
        shift = soundmeter.N // 2 // soundmeter.HOP - 1
        np.testing.assert_allclose(live[8:150], curve[8 - shift:150 - shift], atol=0.02)

    def test_a_number_from_late_sound_waits_for_it(self):
        """The level hears the sound after a look-ahead limiter (20 ms late): the gain it drives
        must still act at the same place of the sound."""
        def make_graph(limit):
            g, lv, n = level_graph(top_db=-20.0, floor_db=-21.0)
            first = "in"
            if limit:
                lim = soundnodes.add(g, soundnodes.new_node("limiter"))
                g["nodes"][lim]["params"].update(lk=20.0, ceil=0.0)
                soundnodes.connect(g, "in", 0, lim, 0)
                first = lim
            soundnodes.connect(g, first, 0, lv, 0)
            soundnodes.connect(g, "in", 0, n, 0)
            return g

        def onset(g):
            v = self.view([{"clips": [self.kick_clip()], "sound_effects": [{"id": "e", "effect": "graph", "graph": g}]}])
            a = np.abs(self.sound(v, 1.0)[:, 0])
            heard = np.nonzero(a[int(0.45 * 48000):] > 0.02)[0]
            return int(heard[-1]) if len(heard) else 0          # how much of the kick gets through before it is shut

        self.assertAlmostEqual(onset(make_graph(True)), onset(make_graph(False)), delta=600)
