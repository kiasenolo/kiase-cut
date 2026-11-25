"""聲音節點效果: the graph's edits, and what it sounds like."""
import unittest

import numpy as np

from kiasecut import dsp, edit, soundedit, soundfx, soundnodes
from tests.test_soundedit import make
from tests.test_soundgraph import REF, Base, fx, rms


class GraphEditTests(unittest.TestCase):
    def test_wiring(self):
        g = soundnodes.new_graph()
        a = soundnodes.add(g, soundnodes.new_node("gain"))
        b = soundnodes.add(g, soundnodes.new_node("compressor"))
        soundnodes.connect(g, "in", 0, a, 0)
        soundnodes.connect(g, a, 0, b, 0)
        soundnodes.connect(g, b, 0, "out", 0)
        self.assertEqual(len(g["links"]), 3)                    # (in -> out was replaced: one link per input)
        self.assertFalse(soundnodes.can_link(g, b, 0, a, 0))    # a loop
        self.assertFalse(soundnodes.can_link(g, a, 1, b, 1))    # no such output
        self.assertEqual([k for _, k in soundnodes.inputs(g["nodes"][b])], ["stereo", "stereo"])   # its side-chain
        soundnodes.remove(g, [a, "in"], keep_links=True)
        self.assertIn("in", g["nodes"])
        self.assertIn(["in", 0, b, 0], g["links"])

    def test_a_mixer_grows(self):
        g = soundnodes.new_graph()
        m = soundnodes.add(g, soundnodes.new_node("mix"))
        soundnodes.connect(g, "in", 0, m, 2)
        self.assertEqual(g["nodes"][m]["inputs"], 3)
        self.assertIn("g3", g["nodes"][m]["params"])
        with self.assertRaises(ValueError):
            soundnodes.connect(g, "in", 0, m, 9)

    def test_insert_and_copy(self):
        g = soundnodes.new_graph()
        a = soundnodes.add(g, soundnodes.new_node("gain"))
        soundnodes.insert_on_link(g, a, ["in", 0, "out", 0])
        self.assertEqual(sorted(g["links"]), sorted([["in", 0, a, 0], [a, 0, "out", 0]]))
        new = soundnodes.paste(g, soundnodes.copy_nodes(g, [a, "out"]), 10, 10)
        self.assertEqual(len(new), 1)
        self.assertEqual(g["nodes"][new[0]]["effect"], "gain")

    def test_through_a_level(self):
        p = make()
        target = ("clip", "c1")
        e = soundedit.add_effect(p, target, soundfx.GRAPH)
        nid = soundedit.add_node(p, target, e, "gain", 100.0, 0.0, None, None, ["in", 0, "out", 0])
        soundedit.toggle_key(p, target, f"{e}/{nid}", "gain", 1_000_000)
        c = edit.find(p, "c1")[1]
        self.assertEqual(edit.key_times(c), [1_000_000])        # a node's keys are the clip's keys
        edit.shift_keys(c, 500_000)
        self.assertEqual(edit.key_times(c), [500_000])
        with self.assertRaises(edit.EditError):
            soundedit.connect_nodes(p, target, e, nid, 0, nid, 0)
        bus = soundedit.add_bus(p)
        ext = soundedit.add_node(p, target, e, "ext", 0.0, 100.0)
        soundedit.set_node(p, target, e, ext, {"channel": bus})
        soundedit.remove_bus(p, bus)
        self.assertEqual(soundedit.graph(p, target, e)["nodes"][ext]["channel"], "")


@unittest.skipUnless(dsp.available(), f"no sound library: {dsp.error()}")
class GraphSoundTests(Base):
    def graph(self, build):
        g = soundnodes.new_graph()
        build(g)
        return {"id": "g1", "effect": soundfx.GRAPH, "graph": g}

    def add(self, g, kind, **params):
        node = soundnodes.new_node(kind)
        node.setdefault("params", {}).update(params)
        return soundnodes.add(g, node)

    def run_track(self, entry, **mix):
        v = self.view([{"clips": [self.clip("a", self.low)], "sound_effects": [entry]},
                       {"clips": [self.clip("b", self.high)], "gain": 1.0}], **mix)
        v["tracks"][1]["pan"] = 1.0                          # the second one: the right side only
        return self.sound(v)[:, 0]                           # the left side: the graph's track alone

    def test_a_new_graph_changes_nothing(self):
        self.assertAlmostEqual(rms(self.run_track(self.graph(lambda g: None))), REF, delta=0.002)

    def test_nothing_into_the_output_is_silence(self):
        self.assertLess(rms(self.run_track(self.graph(lambda g: g["links"].clear()))), 1e-4)

    def test_parallel_paths_are_added(self):
        def build(g):
            m = self.add(g, "mix", g1=-6.0206, g2=-6.0206)
            a = self.add(g, "gain", gain=-6.0206)
            soundnodes.connect(g, "in", 0, m, 0)
            soundnodes.connect(g, "in", 0, a, 0)
            soundnodes.connect(g, a, 0, m, 1)
            soundnodes.connect(g, m, 0, "out", 0)
        self.assertAlmostEqual(rms(self.run_track(self.graph(build))), REF * 0.75, delta=0.003)

    def test_split_merge_and_mute(self):
        def build(g):
            s, m = self.add(g, "split"), self.add(g, "merge")
            quiet = self.add(g, "gain", gain=-60.0)
            soundnodes.connect(g, "in", 0, s, 0)
            soundnodes.connect(g, s, 1, quiet, 0)
            soundnodes.connect(g, quiet, 0, m, 0)            # left: the right side, silenced
            soundnodes.connect(g, s, 0, m, 1)
            soundnodes.connect(g, m, 0, "out", 0)
        entry = self.graph(build)
        self.assertLess(rms(self.run_track(entry)), 1e-4)
        next(n for n in entry["graph"]["nodes"].values() if n.get("effect") == "gain")["mute"] = True
        self.assertAlmostEqual(rms(self.run_track(entry)), REF, delta=0.002)

    def test_delay_inside_a_graph_is_made_up_for(self):
        def build(g):
            lim = self.add(g, "limiter", ceil=0.0, lk=15.0)
            m = self.add(g, "mix", g1=-6.0206, g2=-6.0206)
            soundnodes.connect(g, "in", 0, lim, 0)
            soundnodes.connect(g, lim, 0, m, 0)
            soundnodes.connect(g, "in", 0, m, 1)
            soundnodes.connect(g, m, 0, "out", 0)
        v = self.view([{"clips": [self.clip("a", self.high)]}])
        plain = self.sound(v)
        v["tracks"][0]["sound_effects"] = [self.graph(build)]
        m = self.mixer(v)
        self.assertEqual(m.engine.latency, 719)
        np.testing.assert_allclose(self.sound(v, mixer=m), plain, atol=3e-3)      # no comb filtering

    def test_external_input_takes_a_bus_apart(self):
        def build(g):
            e = self.add(g, "ext")
            g["nodes"][e]["channel"] = "t2"
            soundnodes.connect(g, e, 0, "out", 0)
        v = self.view([{"clips": [self.clip("a", self.low)], "output": "b1"},
                       {"clips": [self.clip("b", self.high)], "gain": 0.5}],
                      buses=[{"id": "b1", "sound_effects": [self.graph(build)]}])
        v["tracks"][1]["output"] = "b1"
        self.assertAlmostEqual(rms(self.sound(v)), REF * 0.5, delta=0.003)      # only what the second one sends

    def test_external_input_that_would_loop_is_silent(self):
        def build(g):
            e = self.add(g, "ext")
            g["nodes"][e]["channel"] = "b1"
            soundnodes.connect(g, e, 0, "out", 0)
        v = self.view([{"clips": [self.clip("a", self.low)], "output": "b1", "sound_effects": [self.graph(build)]}],
                      buses=[{"id": "b1"}])
        self.sound(v)

    def test_side_chain_socket_on_a_clip(self):
        def build(g):
            c = self.add(g, "compressor", thr=-30.0, ratio=20.0, at=1.0)
            e = self.add(g, "ext")
            g["nodes"][e]["channel"] = "t2"
            soundnodes.connect(g, "in", 0, c, 0)
            soundnodes.connect(g, e, 0, c, 1)
            soundnodes.connect(g, c, 0, "out", 0)
        v = self.view([{"clips": [self.clip("a", self.low, sound_effects=[self.graph(build)])]},
                       {"clips": [self.clip("b", self.high, 0.5, 0.5)], "pan": 1.0}])
        a = self.sound(v)[:, 0]
        self.assertLess(rms(a, 0.7, 0.9), rms(a, 0.2, 0.4) * 0.5)


if __name__ == "__main__":
    unittest.main()
