"""聲音轉數值: the box of the spectrum as a number along a channel's timeline."""
import copy
import os
import unittest

import numpy as np

from kiasecut import dsp, edit, lfo, mapping, project, rack, soundedit, soundfx, soundmeter
from tests.test_soundgraph import SR, US, Base, fx, write_wav

BOX = {"lo_hz": 40.0, "hi_hz": 200.0, "floor_db": -36.0, "top_db": -12.5, "attack": 0.0, "release": 0.0}   # (the window reads 100 Hz 0.4 dB low)


def make_root(tracks, buses=(), master=None, **extra):
    tracks = [dict({"id": f"t{i + 1}", "kind": "audio", "name": f"A{i + 1}", "clips": t.pop("clips")}, **t)
              for i, t in enumerate(tracks)]
    comp = {"name": "時間線 1", "tracks": tracks, "buses": list(buses), "master": master or {}, "fit": True}
    return dict({"fps": 30.0, "compounds": {"tl1": comp}, "tracks": tracks, "rack": []}, **extra)


class Sounds(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        t = np.arange(2 * SR) / SR                              # "kicks": 100 Hz at 0.25, 0.2 s long, at 0.5 and 1.5 s
        on = ((t >= 0.5) & (t < 0.7)) | ((t >= 1.5) & (t < 1.7))
        x = 0.25 * np.sin(2 * np.pi * 100 * t) * on
        cls.kicks = os.path.join(cls.tmp.name, "kicks.wav")
        write_wav(cls.kicks, np.stack([x, x], axis=1))

    def kick_clip(self, cid="k", start=0.0, **kw):
        c = self.clip(cid, self.kicks, start, 2.0, **kw)
        c["media"]["duration_us"] = 2 * US
        return c

    def curve(self, root, channel="t1", **box):
        snap = soundmeter.snapshot(root, "tl1", channel)
        pcm = soundmeter.tap(snap, os.path.join(self.tmp.name, "cache"), soundmeter.signature(snap))
        spec = dict(BOX, **box)
        return soundmeter.shape(soundmeter.box_db(pcm, spec["lo_hz"], spec["hi_hz"]), spec)

    def read(self, curve, *seconds):
        return [soundmeter.at(curve, s * US) for s in seconds]


@unittest.skipUnless(dsp.available(), f"no sound library: {dsp.error()}")
class MeterTests(Sounds):
    def test_the_box_follows_the_sound(self):
        c = self.curve(make_root([{"clips": [self.kick_clip()]}]))
        quiet, hit, between, again, after = self.read(c, 0.2, 0.6, 1.0, 1.6, 5.0)
        self.assertEqual((quiet, between, after), (0.0, 0.0, 0.0))
        self.assertAlmostEqual(hit, 1.0, delta=0.01)            # (the top edge)
        self.assertAlmostEqual(again, 1.0, delta=0.01)
        half = self.curve(make_root([{"clips": [self.kick_clip()]}]), top_db=12.0)
        self.assertAlmostEqual(self.read(half, 0.6)[0], 0.5, delta=0.02)

    def test_another_part_of_the_spectrum_is_not_heard(self):
        c = self.curve(make_root([{"clips": [self.kick_clip()]}]), lo_hz=2000.0, hi_hz=8000.0)
        self.assertEqual(self.read(c, 0.6)[0], 0.0)

    def test_attack_and_release(self):
        c = self.curve(make_root([{"clips": [self.kick_clip()]}]), attack=0.05, release=0.3)
        self.assertTrue(0.1 < self.read(c, 0.52)[0] < 0.8)
        self.assertTrue(0.2 < self.read(c, 0.9)[0] < 0.8)
        self.assertLess(self.read(c, 1.49)[0], 0.15)

    def test_effects_fader_and_pan_count(self):
        root = make_root([{"clips": [self.kick_clip()], "gain": 0.5}])
        a = self.read(self.curve(root, top_db=12.0), 0.6)[0]
        self.assertAlmostEqual(a, 0.5 - 6.02 / 48, delta=0.02)
        root["tracks"][0]["sound_effects"] = [fx("gain", "e", gain=-6.0206)]
        self.assertAlmostEqual(self.read(self.curve(root, top_db=12.0), 0.6)[0], a - 6.02 / 48, delta=0.02)

    def test_own_mute_and_any_solo_do_not_count(self):
        root = make_root([{"clips": [self.kick_clip()], "muted": True, "reference": True},
                          {"clips": [self.kick_clip("k2")], "solo": True}])
        self.assertAlmostEqual(self.read(self.curve(root), 0.6)[0], 1.0, delta=0.01)

    def test_a_bus_hears_what_is_sent_in_unmuted(self):
        root = make_root([{"clips": [self.kick_clip()], "routes": [{"to": "b1"}]}], buses=[{"id": "b1"}])
        self.assertAlmostEqual(self.read(self.curve(root, "b1"), 0.6)[0], 1.0, delta=0.01)
        self.assertEqual(self.read(self.curve(root, "master"), 0.6)[0] > 0.9, True)
        root["tracks"][0]["muted"] = True
        self.assertEqual(self.read(self.curve(root, "b1"), 0.6)[0], 0.0)
        root["compounds"]["tl1"]["buses"][0]["muted"] = True    # (the bus's own: it is still heard)
        root["tracks"][0]["muted"] = False
        self.assertAlmostEqual(self.read(self.curve(root, "b1"), 0.6)[0], 1.0, delta=0.01)

    def test_master_volume(self):
        root = make_root([{"clips": [self.kick_clip()]}], master_gain=0.5)
        a = self.read(self.curve(root, "master", top_db=12.0), 0.6)[0]
        self.assertAlmostEqual(a, 0.5 - 6.02 / 48, delta=0.02)

    def test_a_late_effect_stays_in_time(self):
        root = make_root([{"clips": [self.kick_clip()], "sound_effects": [fx("limiter", "e", lk=20.0)]}])
        np.testing.assert_allclose(self.read(self.curve(root), 0.45, 0.55, 0.65, 0.75), [0.0, 1.0, 1.0, 0.0], atol=0.02)

    def test_signature_follows_what_feeds_the_channel_only(self):
        root = make_root([{"clips": [self.kick_clip()]}, {"clips": [self.kick_clip("k2")]}])
        key = lambda: soundmeter.signature(soundmeter.snapshot(root, "tl1", "t1"))
        was = key()
        root["tracks"][1]["clips"][0]["volume"] = 0.3           # another track
        root["tracks"][0]["clips"][0]["transform"] = {"x": 3}   # nothing that sounds
        root["tracks"][0]["muted"] = True                       # its own mute
        self.assertEqual(key(), was)
        root["tracks"][0]["clips"][0]["volume"] = 0.3
        self.assertNotEqual(key(), was)
        was = key()
        root["tracks"][0]["sound_effects"] = [{"id": "e", "effect": "compressor", "side": {"id": "t2"},
                                               "params": soundfx.new_effect("compressor", "e")["params"]}]
        self.assertEqual(soundmeter.upstream(root["compounds"]["tl1"], "t1"), {"t1", "t2"})
        self.assertNotEqual(key(), was)

    def test_a_compound_inside(self):
        inner = {"tracks": [{"id": "i1", "kind": "audio", "name": "x", "clips": [self.kick_clip()]}]}
        c = {"id": "cc", "type": "compound", "start_us": US, "duration_us": 2 * US, "source_start_us": 0,
             "compound": inner}
        curve = self.curve(make_root([{"clips": [c]}]))
        np.testing.assert_allclose(self.read(curve, 0.6, 1.6, 2.6), [0.0, 1.0, 1.0], atol=0.02)

    def test_missing_source(self):
        root = make_root([{"clips": [self.kick_clip()]}])
        with self.assertRaises(soundmeter.MeterError):
            soundmeter.snapshot(root, "tl1", "gone")
        with self.assertRaises(soundmeter.MeterError):
            soundmeter.snapshot(root, "gone", "t1")


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(dsp.available(), f"no sound library: {dsp.error()}")
class RackTests(Sounds):
    """A global parameter that follows a meter."""

    def setUp(self):
        soundmeter.forget()
        self.cache = os.path.join(self.tmp.name, "cache")

    def root(self):
        root = make_root([{"clips": [self.kick_clip()], "muted": True},
                          {"clips": [self.clip("a", self.low)]}], buses=[{"id": "b1"}])
        edit.add_rack_param(root, "kick", 0.0)
        edit.set_rack_sound(root, "r1", soundmeter.make("tl1", "t1", **BOX))
        return root

    def at(self, root, seconds, name="kick"):
        return rack.values(root, seconds * US)[name]

    def test_read_after_measuring(self):
        root = self.root()
        self.assertEqual(self.at(root, 0.6), 0.0)
        was = soundmeter.generation()
        self.assertEqual(soundmeter.prepare(root, self.cache), {})
        self.assertGreater(soundmeter.generation(), was)
        self.assertAlmostEqual(self.at(root, 0.6), 1.0, delta=0.01)
        self.assertEqual(self.at(root, 1.0), 0.0)
        self.assertAlmostEqual(self.at(root, 1.6), 1.0, delta=0.01)       # (asked out of order: a table)
        self.assertFalse(soundmeter.plan(root).stale())

    def test_expression_goes_on_top(self):
        root = self.root()
        edit.set_rack_expr(root, "r1", "input * 100 + 1")
        soundmeter.prepare(root, self.cache)
        self.assertAlmostEqual(self.at(root, 0.6), 101.0, delta=1)

    def test_lfo_and_sound_take_each_others_place(self):
        root = self.root()
        p = root["rack"][0]
        edit.set_rack_lfo(root, "r1", lfo.make())
        self.assertNotIn("sound", p)
        edit.set_rack_sound(root, "r1", soundmeter.make("tl1", "t1"))
        self.assertNotIn("lfo", p)
        edit.set_rack_sound(root, "r1", None)
        self.assertNotIn("sound", p)
        soundmeter.prepare(root, self.cache)
        self.assertIsNone(soundmeter.curve("r1"))

    def test_a_sound_may_follow_another_channels_meter(self):
        root = self.root()
        duck = soundfx.new_effect("gain", "g")
        root["tracks"][1]["sound_effects"] = [duck]
        soundedit.bind(root, root["compounds"]["tl1"] | {"tracks": root["tracks"]}, ("track", "t2"), "g", "gain",
                       mapping.make("linear", "kick", (0, 1), (0, -60)))
        edit.add_rack_param(root, "ducked", 0.0)
        edit.set_rack_sound(root, "r2", soundmeter.make("tl1", "t2", **dict(BOX, floor_db=-40.0, top_db=-10.0)))
        todo = soundmeter.plan(root)
        self.assertEqual([j.rid for j in todo.jobs], ["r1", "r2"])
        self.assertEqual(soundmeter.run(todo, self.cache), {})
        self.assertGreater(self.at(root, 0.3, "ducked"), 0.7)             # no kick: as it is
        self.assertEqual(self.at(root, 0.6, "ducked"), 0.0)               # the kick turns it down
        was = todo.keys()["r2"]                                           # what r1 hears changes: r2 is measured again
        edit.set_rack_sound(root, "r1", soundmeter.make("tl1", "t1", **dict(BOX, release=0.4)))
        self.assertNotEqual(soundmeter.plan(root).keys()["r2"], was)

    def test_circles_are_refused_and_cut(self):
        root = self.root()
        level = {"tracks": root["tracks"]}
        root["tracks"][0]["sound_effects"] = [soundfx.new_effect("gain", "g")]
        with self.assertRaisesRegex(edit.EditError, "kick → kick"):
            soundedit.bind(root, level, ("track", "t1"), "g", "gain", "kick * 10")
        del root["tracks"][0]["sound_effects"][0]["expr"]
        # through another parameter's expression, found when the expression is written
        edit.add_rack_param(root, "other", 0.0)
        soundedit.bind(root, level, ("track", "t1"), "g", "gain", "other")
        with self.assertRaisesRegex(edit.EditError, "循環"):
            edit.set_rack_expr(root, "r2", "kick")
        self.assertNotIn("expr", root["rack"][1])
        # made by other means: reads 0 and an export says so
        root["rack"][1]["expr"] = "kick"
        problems = soundmeter.prepare(root, self.cache)
        self.assertIn("循環", problems["r1"])
        self.assertEqual(self.at(root, 0.6), 0.0)
        with self.assertRaisesRegex(RuntimeError, "kick"):
            soundmeter.require(root, self.cache)
        said = []
        soundmeter.require(root, self.cache, allow_errors=True, say=said.append)
        self.assertTrue(said)

    def test_two_channels_in_a_ring(self):
        root = self.root()
        for t in root["tracks"]:
            t["sound_effects"] = [soundfx.new_effect("gain", "g-" + t["id"])]
        edit.add_rack_param(root, "other", 0.0)
        edit.set_rack_sound(root, "r2", soundmeter.make("tl1", "t2"))
        level = {"tracks": root["tracks"]}
        soundedit.bind(root, level, ("track", "t2"), "g-t2", "gain", "kick")
        with self.assertRaisesRegex(edit.EditError, "循環"):
            soundedit.bind(root, level, ("track", "t1"), "g-t1", "gain", "other")

    def test_missing_source_matters_only_when_read(self):
        root = self.root()
        root["rack"][0]["sound"]["channel"] = "gone"
        soundmeter.require(root, self.cache)                              # nothing reads it
        root["tracks"][1]["clips"][0]["expr"] = {"transform.scale": "kick"}
        with self.assertRaisesRegex(RuntimeError, "找不到"):
            soundmeter.require(root, self.cache)

    def test_export_and_import(self):
        root = self.root()
        other = make_root([{"clips": []}])
        edit.import_rack(other, rack.parse_import(rack.export_text(root)))
        self.assertEqual(other["rack"][0]["sound"], root["rack"][0]["sound"])

