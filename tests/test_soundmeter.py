"""聲音轉數值: the box of the spectrum as a number along a channel's timeline."""
import copy
import os
import unittest

import numpy as np

from kiasecut import dsp, project, soundfx, soundmeter
from tests.test_soundgraph import SR, US, Base, fx, write_wav

BOX = {"lo_hz": 40.0, "hi_hz": 200.0, "floor_db": -36.0, "top_db": -12.5, "attack": 0.0, "release": 0.0}   # (the window reads 100 Hz 0.4 dB low)


def make_root(tracks, buses=(), master=None, **extra):
    tracks = [dict({"id": f"t{i + 1}", "kind": "audio", "name": f"A{i + 1}", "clips": t.pop("clips")}, **t)
              for i, t in enumerate(tracks)]
    comp = {"name": "時間線 1", "tracks": tracks, "buses": list(buses), "master": master or {}, "fit": True}
    return dict({"fps": 30.0, "compounds": {"tl1": comp}, "tracks": tracks, "rack": []}, **extra)


@unittest.skipUnless(dsp.available(), f"no sound library: {dsp.error()}")
class MeterTests(Base):
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
