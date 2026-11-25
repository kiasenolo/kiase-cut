"""The processed mix: effects on clips, tracks, buses and the master, routing, tails, delay
made up for, and the same sound whatever place it is asked from."""
import os
import tempfile
import unittest
import wave

import numpy as np

from kiasecut import audiomix, dsp, project, renderexport, soundfx, soundgraph

SR, US = 48000, 1_000_000


def write_wav(path, x):
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


def fx(kind, eid, **params):
    e = soundfx.new_effect(kind, eid)
    e["params"].update(params)
    return e


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        t = np.arange(SR) / SR
        cls.low = os.path.join(cls.tmp.name, "low.wav")         # 1 s each, 0.25 full scale
        cls.high = os.path.join(cls.tmp.name, "high.wav")
        for path, f in ((cls.low, 100), (cls.high, 6000)):
            x = 0.25 * np.sin(2 * np.pi * f * t)
            write_wav(path, np.stack([x, x], axis=1))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def clip(self, cid, path, start=0.0, seconds=1.0, **kw):
        return dict({"id": cid, "type": "audio", "name": cid, "start_us": int(start * US),
                     "duration_us": int(seconds * US), "source_start_us": 0,
                     "media": {"path": path, "duration_us": US}}, **kw)

    def view(self, tracks, **mix):
        tracks = [dict({"id": f"t{i + 1}", "kind": "audio", "name": f"A{i + 1}", "clips": t.pop("clips")}, **t)
                  for i, t in enumerate(tracks)]
        return {"fps": 30.0, "tracks": tracks, "buses": mix.get("buses", []), "master": mix.get("master", {}),
                "compounds": {}}

    def mixer(self, view, only=None):
        m = audiomix.Mixer(os.path.join(self.tmp.name, "cache"))
        m.set_view(view, only)
        while m.thread is not None and m.thread.is_alive():
            m.thread.join(0.2)
        return m

    def sound(self, view, seconds=1.0, only=None, mixer=None):
        """The mix from the start, frame by frame, as floats."""
        m = mixer or self.mixer(view, only)
        raw = b"".join(m.mix(f, 30.0) for f in range(int(seconds * 30)))
        return np.frombuffer(raw, np.int16).reshape(-1, 2) / 32768.0


def rms(a, lo=0.2, hi=0.8):
    part = a[int(lo * SR):int(hi * SR)]
    return float(np.sqrt(np.mean(part ** 2)))


REF = 0.25 / np.sqrt(2)


class PlainTests(Base):
    def test_unprocessed_stays_on_the_old_path(self):
        v = self.view([{"clips": [self.clip("a", self.low)]}])
        self.assertFalse(soundfx.used(v))
        self.assertIsNone(self.mixer(v).engine)
        v["tracks"][0]["sound_effects"] = [dict(fx("gain", "e1"), enabled=False)]
        self.assertFalse(soundfx.used(v))

    def test_export_takes_the_renderer(self):
        v = self.view([{"clips": [self.clip("a", self.low)]}])
        v["tracks"][0]["pan"] = 0.5
        v["compounds"] = {}
        self.assertTrue(renderexport.needs_renderer(v))


@unittest.skipUnless(dsp.available(), f"no sound library: {dsp.error()}")
class GraphTests(Base):
    def test_engine_matches_the_plain_mix(self):
        """With effects that change nothing, the engine gives what the plain path gives."""
        v = self.view([{"clips": [self.clip("a", self.low, 0.1, 0.7, volume=0.5)], "gain": 0.8},
                       {"clips": [self.clip("b", self.high, 0.3, 0.5, speed=1.5)]}])
        plain = self.sound(v)
        v["master"] = {"sound_effects": [fx("gain", "m")]}
        m = self.mixer(v)
        self.assertIsNotNone(m.engine)
        np.testing.assert_allclose(self.sound(v, mixer=m), plain, atol=2e-3)

    def test_chain_at_every_place(self):
        half = -6.0206
        for place in ("clip", "track", "bus", "master"):
            v = self.view([{"clips": [self.clip("a", self.low)]}], buses=[{"id": "b1", "name": "B"}])
            entry = [fx("gain", "e1", gain=half)]
            if place == "clip":
                v["tracks"][0]["clips"][0]["sound_effects"] = entry
            elif place == "track":
                v["tracks"][0]["sound_effects"] = entry
            elif place == "bus":
                v["tracks"][0]["output"] = "b1"
                v["buses"][0]["sound_effects"] = entry
            else:
                v["master"] = {"sound_effects": entry}
            self.assertAlmostEqual(rms(self.sound(v)), REF / 2, delta=0.002, msg=place)

    def test_filters_act_per_track(self):
        v = self.view([{"clips": [self.clip("a", self.low)], "sound_effects": [fx("highpass", "e1", f=2000.0)]},
                       {"clips": [self.clip("b", self.high)]}])
        self.assertAlmostEqual(rms(self.sound(v)), REF, delta=0.004)         # only the high one is left

    def test_buses_sends_and_pan(self):
        v = self.view([{"clips": [self.clip("a", self.low)], "output": "b1"}],
                      buses=[{"id": "b1", "gain": 0.5, "output": "b2"}, {"id": "b2", "pan": 1.0}])
        a = self.sound(v)
        self.assertAlmostEqual(rms(a[:, 1:]), REF * 0.5, delta=0.002)
        self.assertAlmostEqual(rms(a[:, :1]), 0.0, delta=1e-4)
        v = self.view([{"clips": [self.clip("a", self.low)], "sends": [{"bus": "b1", "gain": 0.0}]}],
                      buses=[{"id": "b1"}])
        self.assertAlmostEqual(rms(self.sound(v)), REF * 2, delta=0.004)
        v["tracks"][0]["gain"] = 0.0                                          # after the fader: nothing sent
        self.assertLess(rms(self.sound(v)), 1e-4)
        v["tracks"][0]["sends"][0]["pre"] = True                              # before it: still sent
        self.assertAlmostEqual(rms(self.sound(v)), REF, delta=0.002)
        v["tracks"][0]["muted"] = True
        self.assertLess(rms(self.sound(v)), 1e-4)

    def test_mute_and_solo(self):
        v = self.view([{"clips": [self.clip("a", self.low)], "output": "b1", "solo": True},
                       {"clips": [self.clip("b", self.high)]}], buses=[{"id": "b1"}])
        self.assertAlmostEqual(rms(self.sound(v)), REF, delta=0.002)          # the soloed one, through its bus
        v["tracks"][0].pop("solo")
        v["buses"][0]["solo"] = True                                          # a soloed bus: what feeds it
        self.assertAlmostEqual(rms(self.sound(v)), REF, delta=0.002)
        v["buses"][0].pop("solo")
        v["buses"][0]["muted"] = True
        self.assertAlmostEqual(rms(self.sound(v)), REF, delta=0.002)          # the other one only

    def test_tracks_feed_tracks_and_several_places(self):
        # a: into track 2 (which has its own) at half, and nowhere else
        v = self.view([{"clips": [self.clip("a", self.low)], "routes": [{"to": "t2", "gain": -6.0206}]},
                       {"clips": [], "sound_effects": [fx("gain", "e", gain=-6.0206)]}])
        self.assertAlmostEqual(rms(self.sound(v)), REF / 4, delta=0.002)
        v["tracks"][0]["routes"] = [{"to": "t2"}, {"to": "master"}]           # both ways at once
        self.assertAlmostEqual(rms(self.sound(v)), REF * 1.5, delta=0.004)
        v["tracks"][0]["routes"] = []                                          # nowhere
        self.assertLess(rms(self.sound(v)), 1e-4)
        v["tracks"][0]["routes"] = [{"to": "gone"}]                            # lost: the master
        self.assertAlmostEqual(rms(self.sound(v)), REF, delta=0.002)

    def test_solo_hears_what_feeds_it_that_way_only(self):
        v = self.view([{"clips": [self.clip("a", self.low)], "routes": [{"to": "master"}, {"to": "b1"}]},
                       {"clips": [self.clip("b", self.high)]}],
                      buses=[{"id": "b1", "gain": 0.5, "solo": True}])
        self.assertAlmostEqual(rms(self.sound(v)), REF / 2, delta=0.002)       # not a's own way to the master
        v["buses"][0].pop("solo")
        v["tracks"][0]["solo"] = True                                          # a soloed track: all its ways
        self.assertAlmostEqual(rms(self.sound(v)), REF * 1.5, delta=0.004)

    def test_bus_loop_is_cut(self):
        v = self.view([{"clips": [self.clip("a", self.low)], "output": "b1"}],
                      buses=[{"id": "b1", "output": "b2"}, {"id": "b2", "output": "b1"}])
        self.sound(v)                                                         # (it ends, and nothing is raised)

    def test_stem_of_one_track(self):
        v = self.view([{"clips": [self.clip("a", self.low)], "sound_effects": [fx("gain", "e", gain=-6.0206)]},
                       {"clips": [self.clip("b", self.high)]}], master={"sound_effects": [fx("gain", "m", gain=-60.0)]})
        self.assertAlmostEqual(rms(self.sound(v, only=v["tracks"][0])), REF / 2, delta=0.002)

    def test_same_sound_from_the_middle(self):
        v = self.view([{"clips": [self.clip("a", self.low, 0.0, 0.9)], "sound_effects": [fx("lowpass", "e", f=300.0, q=4.0)]}])
        whole = self.sound(v)
        m = self.mixer(v)
        for first in (15, 4):                                                 # forwards, then back
            part = np.frombuffer(b"".join(m.mix(f, 30.0) for f in range(first, first + 6)), np.int16).reshape(-1, 2) / 32768
            np.testing.assert_allclose(part, whole[first * 1600:(first + 6) * 1600], atol=2e-4)

    def test_edit_keeps_the_processors(self):
        v = self.view([{"clips": [self.clip("a", self.low)], "sound_effects": [fx("lowpass", "e")]}])
        m = self.mixer(v)
        before = dict(m.engine.procs)
        v["tracks"][0]["sound_effects"][0]["params"]["f"] = 500.0
        v["tracks"][0]["sound_effects"].append(fx("gain", "g"))
        m.set_view(v)
        self.assertTrue(all(m.engine.procs[k] is p for k, p in before.items()))
        self.assertEqual(len(m.engine.procs), 2)

    def test_automation(self):
        keys = {"keys": [[0, -60.0, 0.0, 0.0, 1.0, 1.0], [US, 0.0, 0.0, 0.0, 1.0, 1.0]]}
        v = self.view([{"clips": [self.clip("a", self.low)]}], master={"sound_effects": [fx("gain", "m", gain=keys)]})
        a = self.sound(v)
        self.assertLess(rms(a, 0.0, 0.2), rms(a, 0.4, 0.6))
        self.assertLess(rms(a, 0.4, 0.6), rms(a, 0.8, 1.0))

    def test_compound_is_mixed_first(self):
        inner = [{"id": "i1", "kind": "audio", "clips": [self.clip("a", self.low)]}]
        comp = {"tracks": inner, "master": {"sound_effects": [fx("gain", "in", gain=-6.0206)]}, "duration_us": US}
        outer = {"id": "c", "type": "compound", "name": "c", "start_us": 0, "duration_us": US, "source_start_us": 0,
                 "compound": comp, "compound_id": "k1", "sound_effects": [fx("gain", "out", gain=-6.0206)]}
        v = self.view([{"clips": [outer]}])
        self.assertTrue(soundfx.used(v))
        self.assertAlmostEqual(rms(self.sound(v)), REF / 4, delta=0.002)

    def test_side_chain_between_tracks(self):
        duck = dict(fx("compressor", "c", thr=-30.0, ratio=20.0, at=1.0), side={"id": "t2"})
        v = self.view([{"clips": [self.clip("a", self.low)], "sound_effects": [duck]},
                       {"clips": [self.clip("b", self.high, 0.5, 0.5)], "pan": 1.0}])
        a = self.sound(v)[:, 0]                                    # the left side: the first track only
        self.assertGreater(rms(a, 0.2, 0.4), REF * 0.5)            # alone: under no threshold of its own tone...
        self.assertLess(rms(a, 0.7, 0.9), rms(a, 0.2, 0.4) * 0.5)  # ...and ducked while the other sounds

    def test_a_limiter_stays_in_time(self):
        v = self.view([{"clips": [self.clip("a", self.high)]}, {"clips": [self.clip("b", self.high)], "gain": 1.0}])
        plain = self.sound(v)
        v["tracks"][0]["sound_effects"] = [fx("limiter", "l", ceil=0.0, lk=15.0)]
        m = self.mixer(v)
        self.assertEqual(m.engine.latency, 719)
        np.testing.assert_allclose(self.sound(v, mixer=m), plain, atol=2e-3)

    def test_delay_is_made_up_for(self):
        """A path that is late (as a limiter's look-ahead makes it) is matched by the others."""

        class Late:
            latency, tail = 700, 0.0

            def __init__(self):
                self.d = soundgraph.Delay(700)

            def set(self, *a):
                pass

            def reset(self):
                self.d.reset()

            def process(self, x, side=None, pos=0):
                return self.d.run(x)

            def meters(self, n=8):
                return np.zeros(n)

        v = self.view([{"clips": [self.clip("a", self.high)]}, {"clips": [self.clip("b", self.high)]}])
        plain = self.sound(v)
        v["tracks"][0]["sound_effects"] = [fx("gain", "e")]
        m = audiomix.Mixer(os.path.join(self.tmp.name, "cache"))
        m.engine = soundgraph.Engine(audiomix.Source_of)
        m.engine.procs = {(("ch", "t1", "e", "gain")): Late()}
        m.set_view(v)
        while m.thread is not None and m.thread.is_alive():
            m.thread.join(0.2)
        self.assertEqual(m.engine.latency, 700)
        np.testing.assert_allclose(self.sound(v, mixer=m), plain, atol=2e-3)


@unittest.skipUnless(dsp.available(), f"no sound library: {dsp.error()}")
class FollowTests(Base):
    def test_a_parameter_follows_the_global_one_through_time(self):
        gain = fx("gain", "e1")
        gain["expr"] = {"gain": "level"}
        mute = fx("gain", "e2")
        v = self.view([{"clips": [self.clip("a", self.low)], "sound_effects": [gain]}], master={"sound_effects": [mute]})
        v["rack"] = [{"id": "r1", "name": "level", "kind": "number",
                      "value": {"keys": [[0, 0.0, 0, 0, 0, 0], [US // 2 - 1000, 0.0, 0, 0, 0, 0],
                                         [US // 2, -24.0, 0, 0, 0, 0]]}}]
        out = self.sound(v)
        self.assertAlmostEqual(rms(out, 0.1, 0.4), REF, delta=0.005)
        self.assertAlmostEqual(rms(out, 0.6, 0.9), REF * 10 ** (-24 / 20), delta=0.003)


if __name__ == "__main__":
    unittest.main()
