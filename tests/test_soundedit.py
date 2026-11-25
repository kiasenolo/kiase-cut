"""Edits of the sound processing: chains, keyframes, buses, routes - and that they undo and
survive saving."""
import json
import tempfile
import unittest

from kiasecut import edit, project, rack, soundedit, soundfx, soundnodes, userlib

S = 1_000_000


def make():
    clip = {"id": "c1", "type": "audio", "name": "a", "start_us": 0, "duration_us": 4 * S, "source_start_us": 0,
            "media": {"path": "/nowhere.wav", "duration_us": 4 * S}}
    pic = {"id": "p1", "type": "image", "name": "p", "start_us": 0, "duration_us": S, "source_start_us": 0,
           "media": {"path": "/nowhere.png", "width": 4, "height": 4}}
    p = project.new(640, 360, 30.0)
    p["tracks"][:] = [{"id": "t0", "kind": "audio", "name": "A1", "clips": [clip]},
                      {"id": "t1", "kind": "video", "name": "V1", "clips": [pic]}]
    return project.link(p)


class ChainTests(unittest.TestCase):
    def test_add_move_remove_on_every_target(self):
        p = make()
        bus = soundedit.add_bus(p)
        for target in (("clip", "c1"), ("track", "t0"), ("bus", bus), ("master", "")):
            a = soundedit.add_effect(p, target, "gain")
            b = soundedit.add_effect(p, target, "highpass")
            soundedit.move_effect(p, target, b, 0)
            self.assertEqual([e["id"] for e in soundedit.chain(p, target)], [b, a])
            soundedit.set_enabled(p, target, a, False)
            self.assertFalse(soundedit.effect(p, target, a)["enabled"])
            soundedit.set_param(p, target, a, "gain", 99.0)                 # held to its range
            self.assertEqual(soundedit.effect(p, target, a)["params"]["gain"], 24.0)
            soundedit.remove_effect(p, target, a)
            soundedit.remove_effect(p, target, b)
            self.assertEqual(soundedit.chain(p, target), [])
        self.assertNotIn("master", soundedit.mix_holder(p))                   # nothing left behind
        self.assertNotIn("sound_effects", p["tracks"][0])

    def test_a_picture_takes_no_sound_effect(self):
        with self.assertRaises(edit.EditError):
            soundedit.add_effect(make(), ("clip", "p1"), "gain")

    def test_keyframes_follow_trim_and_split(self):
        p = make()
        e = soundedit.add_effect(p, ("clip", "c1"), "gain")
        soundedit.toggle_key(p, ("clip", "c1"), e, "gain", S)
        soundedit.set_param(p, ("clip", "c1"), e, "gain", -12.0, 3 * S)
        c = edit.find(p, "c1")[1]
        self.assertEqual([k[0] for k in c["sound_effects"][0]["params"]["gain"]["keys"]], [S, 3 * S])
        self.assertEqual(edit.key_times(c), [S, 3 * S])
        edit.shift_keys(c, S)
        self.assertEqual(edit.key_times(c), [0, 2 * S])
        soundedit.toggle_key(p, ("clip", "c1"), e, "gain", 0)
        soundedit.toggle_key(p, ("clip", "c1"), e, "gain", 2 * S)
        self.assertEqual(c["sound_effects"][0]["params"]["gain"], -12.0)


class BusTests(unittest.TestCase):
    def test_routes_make_no_loop(self):
        p = make()
        a, b = soundedit.add_bus(p), soundedit.add_bus(p)
        soundedit.set_route(p, ("bus", a), b, True)
        self.assertEqual(soundedit.destinations(p, ("bus", b)), ["t0", "t1", "master"])
        with self.assertRaises(edit.EditError):
            soundedit.set_route(p, ("bus", b), a, True)
        soundedit.set_route(p, ("track", "t0"), a, True)                       # a -> b, so b may not reach t0
        self.assertFalse(soundedit.can_route(p, ("bus", b), "t0"))
        self.assertFalse(soundedit.can_route(p, ("bus", b), b))
        self.assertTrue(soundedit.can_route(p, ("track", "t1"), "t0"))         # a track may feed a track

    def test_lines_as_in_fl(self):
        p = make()
        t = ("track", "t0")
        a = soundedit.add_bus(p)
        self.assertEqual(soundedit.routes(p, t), [{"to": "master"}])
        soundedit.set_route(p, t, a, True)                                    # another line, the master's stays
        self.assertEqual([r["to"] for r in soundedit.routes(p, t)], ["master", a])
        soundedit.set_route_level(p, t, a, gain=-12.0, pre=True)
        self.assertEqual(soundedit.route_to(p, t, a), {"to": a, "gain": -12.0, "pre": True})
        soundedit.nudge_route_level(p, [t, ("track", "t1")], a, 3.0)          # only who has the line
        self.assertEqual(soundedit.route_to(p, t, a)["gain"], -9.0)
        self.assertIsNone(soundedit.route_to(p, ("track", "t1"), a))
        soundedit.route_only(p, [t], a)
        self.assertEqual([r["to"] for r in soundedit.routes(p, t)], [a])
        soundedit.set_route(p, t, a, False)                                   # nowhere at all is allowed
        self.assertEqual(soundedit.routes(p, t), [])
        self.assertTrue(soundfx.routed(p["tracks"][0]))
        soundedit.set_route(p, t, "master", True)
        self.assertNotIn("routes", p["tracks"][0])                            # as it was: nothing written

    def test_several_at_once(self):
        p = make()
        both = [("track", "t0"), ("track", "t1")]
        soundedit.set_gain(p, both[1], 0.5)
        soundedit.nudge_gain(p, both + [("master", "")], -6.0206)
        self.assertAlmostEqual(p["tracks"][0]["gain"], 0.5, delta=1e-3)
        self.assertAlmostEqual(p["tracks"][1]["gain"], 0.25, delta=1e-3)
        soundedit.nudge_pan(p, both, 0.4)
        soundedit.set_flags(p, both, "muted", True)
        self.assertTrue(all(t["muted"] and t["pan"] == 0.4 for t in p["tracks"]))
        bus = soundedit.to_new_bus(p, both)
        self.assertEqual([[r["to"] for r in soundedit.routes(p, t)] for t in both], [[bus], [bus]])
        soundedit.set_routes(p, both + [("bus", bus)], "master", True)         # the bus has it already
        made = soundedit.add_effects(p, [both[0], ("bus", bus), ("master", "")], "gain")
        self.assertEqual(len(set(made.values())), 3)
        soundedit.set_color(p, both, "#112233")
        self.assertEqual(p["tracks"][1]["mix_color"], "#112233")
        soundedit.set_color(p, both, None)
        self.assertNotIn("mix_color", p["tracks"][1])

    def test_strip_order(self):
        p = make()
        a, b = soundedit.add_bus(p), soundedit.add_bus(p)
        ids = ["t0", "t1", a, b]
        self.assertEqual(soundedit.ordered(p, ids), ids)
        soundedit.move_strips(p, ids, [b, "t1"], "t0")
        self.assertEqual(soundedit.ordered(p, ids), ["t1", b, "t0", a])
        self.assertEqual(soundedit.ordered(p, ids + ["new"]), ["t1", b, "new", "t0", a])    # next to what it follows
        self.assertEqual([t["id"] for t in p["tracks"]], ["t0", "t1"])        # the timeline's are left
        soundedit.move_strips(p, soundedit.ordered(p, ids), ["t1"], None)
        self.assertEqual(soundedit.ordered(p, ids), [b, "t0", a, "t1"])

    def test_removing_a_bus_lets_go_of_it(self):
        p = make()
        a, other = soundedit.add_bus(p, "混響"), soundedit.add_bus(p)
        soundedit.route_only(p, [("track", "t0")], a)
        soundedit.set_route(p, ("track", "t1"), a, True)
        soundedit.set_route(p, ("track", "t1"), "master", False)
        soundedit.set_route(p, ("track", "t1"), other, True)
        e = soundedit.add_effect(p, ("clip", "c1"), "gain")
        soundedit.set_side(p, ("clip", "c1"), e, a)
        soundedit.remove_buses(p, [a])
        self.assertNotIn("routes", p["tracks"][0])                            # had only that one: the master again
        self.assertEqual(p["tracks"][1]["routes"], [{"to": other}])
        self.assertNotIn("side", edit.find(p, "c1")[1]["sound_effects"][0])
        self.assertEqual([b["id"] for b in soundedit.buses(p)], [other])

    def test_saved_and_undone(self):
        p = make()
        history = edit.History(p)
        history.do("bus", soundedit.add_bus)
        history.do("fx", soundedit.add_effect, ("master", ""), "gain")
        history.do("pan", soundedit.set_pan, ("track", "t0"), -0.5)
        again = project.normalize(json.loads(project.dumps(p)))
        self.assertEqual(soundedit.buses(again)[0]["id"], "bus1")
        self.assertEqual(soundedit.chain(again, ("master", ""))[0]["effect"], "gain")
        self.assertTrue(soundfx.used(again))
        for _ in range(3):
            history.undo()
        self.assertFalse(soundfx.used(history.proj))

    def test_a_compounds_own_mix(self):
        p = make()
        kid = edit.add_compound(p)
        comp = p["compounds"][kid]
        comp["tracks"][0]["clips"] = []
        soundedit.add_bus(comp)
        self.assertEqual(len(comp["buses"]), 1)
        self.assertEqual(soundedit.buses(p), [])


class CurveAndFollowTests(unittest.TestCase):
    def test_curve_editor_rows_and_keys(self):
        p = make()
        t = ("clip", "c1")
        gain = soundedit.add_effect(p, t, "gain")
        graph = soundedit.add_effect(p, t, "graph")
        soundedit.add_effect(p, t, "reverb")
        c = edit.find(p, "c1")[1]
        g = soundedit.graph(p, t, graph)
        mix = soundnodes.new_node("mix")
        g["nodes"]["n9"] = mix
        rows = soundfx.clip_rows(c["sound_effects"])
        groups = {r[0] for r in rows}
        self.assertIn("sfx:" + gain, groups)
        self.assertIn(f"sfx:{graph}/n9", groups)
        self.assertEqual(len({r[:2] for r in rows}), len(rows))
        for group, key, *_ in rows:
            self.assertTrue(edit.has_param(c, group, key), (group, key))
        edit.set_keys(p, "c1", "sfx:" + gain, "gain", [[0, -6.0, 0, 0, 0, 0], [S, 0.0, 0, 0, 0, 0]])
        self.assertEqual(edit.key_times(c), [0, S])
        edit.toggle_key(p, "c1", f"sfx:{graph}/n9", "g2", 2 * S)
        self.assertEqual(edit.key_times(c), [0, S, 2 * S])
        edit.clear_keys(p, "c1", "sfx:" + gain, "gain", -3.0)
        self.assertEqual(c["sound_effects"][0]["params"]["gain"], -3.0)

    def test_following_a_global_parameter(self):
        p = make()
        edit.add_rack_param(p, "loud", 6.0)
        t = ("track", "t0")
        e = soundedit.add_effect(p, t, "gain")
        soundedit.set_expr(p, t, e, "gain", "loud * 2")
        entry = soundedit.effect(p, t, e)
        names = rack.values(p, 0)
        self.assertEqual(soundfx.values(entry, 0, names)["gain"], 12.0)
        self.assertEqual(rack.users(p, "loud"), 1)
        edit.rename_rack_param(p, rack.params(p)[0]["id"], "level")
        self.assertEqual(entry["expr"]["gain"], "level * 2")
        soundedit.set_expr(p, t, e, "gain", "level * 100")                   # held to the parameter's range
        self.assertEqual(soundfx.values(entry, 0, rack.values(p, 0))["gain"], 24.0)
        soundedit.set_expr(p, t, e, "gain", "")
        self.assertNotIn("expr", entry)
        with self.assertRaises(edit.EditError):
            soundedit.set_expr(p, t, e, "gain", "((")


class PresetTests(unittest.TestCase):
    def test_a_chain_kept_and_put_on_another(self):
        p = make()
        t = ("clip", "c1")
        gain = soundedit.add_effect(p, t, "gain")
        graph = soundedit.add_effect(p, t, "graph")
        g = soundedit.graph(p, t, graph)
        g["nodes"]["n9"] = soundnodes.new_node("ext", channel="t1")
        soundedit.toggle_key(p, t, gain, "gain", S)
        soundedit.set_expr(p, t, gain, "gain", "value * 2")
        saved = soundedit.preset_entries(soundedit.chain(p, t))
        self.assertNotIn("id", saved[0])
        self.assertNotIn("expr", saved[0])
        self.assertEqual(saved[0]["params"]["gain"], 0.0)
        self.assertEqual(saved[1]["graph"]["nodes"]["n9"]["channel"], "")
        self.assertIn("expr", soundedit.effect(p, t, gain))                  # the chain itself is left alone
        with tempfile.TemporaryDirectory() as root:
            userlib.save_sound_preset(root, "voice / 1", saved)
            (name, path), = userlib.sound_presets(root)
            self.assertEqual(name, "voice _ 1")
            made = soundedit.add_preset(p, ("track", "t0"), userlib.load_sound_preset(path) + [{"effect": "unknown"}])
        self.assertEqual(len(made), 2)
        self.assertNotIn(gain, made)
        self.assertEqual([e["id"] for e in soundedit.chain(p, ("track", "t0"))], made)
        with self.assertRaises(edit.EditError):
            soundedit.add_preset(p, ("clip", "p1"), saved)


if __name__ == "__main__":
    unittest.main()
