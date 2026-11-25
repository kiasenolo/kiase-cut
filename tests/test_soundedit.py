"""Edits of the sound processing: chains, keyframes, buses, routes - and that they undo and
survive saving."""
import json
import unittest

from kiasecut import edit, project, soundedit, soundfx

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
        soundedit.set_output(p, ("bus", a), b)
        self.assertEqual(soundedit.destinations(p, ("bus", b)), [])
        with self.assertRaises(edit.EditError):
            soundedit.set_output(p, ("bus", b), a)
        with self.assertRaises(edit.EditError):
            soundedit.add_send(p, ("bus", b), a)

    def test_removing_a_bus_lets_go_of_it(self):
        p = make()
        a = soundedit.add_bus(p, "混響")
        soundedit.set_output(p, ("track", "t0"), a)
        soundedit.add_send(p, ("track", "t1"), a)
        e = soundedit.add_effect(p, ("clip", "c1"), "gain")
        soundedit.set_side(p, ("clip", "c1"), e, a)
        soundedit.remove_bus(p, a)
        self.assertNotIn("output", p["tracks"][0])
        self.assertNotIn("sends", p["tracks"][1])
        self.assertNotIn("side", edit.find(p, "c1")[1]["sound_effects"][0])
        self.assertEqual(soundedit.buses(p), [])

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


if __name__ == "__main__":
    unittest.main()
