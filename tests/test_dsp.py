"""The sound effects' C library: it builds, loads and the basic effects do what they say."""
import unittest

import numpy as np

from kiasecut import dsp

SR = dsp.RATE


def sine(f, seconds=0.5, amp=0.5):
    x = (amp * np.sin(2 * np.pi * f * np.arange(int(SR * seconds)) / SR)).astype(np.float32)
    return np.stack([x, x], axis=1)


def level_db(a, skip=0.25):
    """Level of a's later part (past the effect settling): the peak of a sine with its RMS, in dB."""
    part = a[int(len(a) * skip):].astype(np.float64)
    return 10 * np.log10(max(1e-18, 2 * np.mean(part ** 2)))


@unittest.skipUnless(dsp.available(), f"no sound library: {dsp.error()}")
class BasicTests(unittest.TestCase):
    def test_kinds_and_defaults(self):
        self.assertIn("gain", dsp.kinds())
        self.assertEqual(dsp.defaults("highpass")["f"], 80.0)
        with self.assertRaises(dsp.DspError):
            dsp.Processor("nothing")

    def test_gain(self):
        fx = dsp.Processor("gain")
        x = sine(440)
        np.testing.assert_allclose(fx.process(x), x, atol=1e-6)
        fx.reset()
        fx.set("gain", -6.0206)
        np.testing.assert_allclose(fx.process(x), x * 0.5, atol=1e-5)
        fx.reset()
        fx.set("gain", -60.0)
        self.assertEqual(np.abs(fx.process(x)).max(), 0.0)

    def test_gain_changes_without_a_step(self):
        fx = dsp.Processor("gain")
        x = np.ones((512, 2), np.float32)
        fx.process(x)
        fx.set("gain", -20.0)
        y = fx.process(x)
        self.assertLess(np.abs(np.diff(y[:, 0])).max(), 0.01)
        self.assertAlmostEqual(float(y[-1, 0]), 0.1, places=5)

    def test_filters(self):
        for kind, f, keeps, cuts in (("highpass", 1000.0, 8000, 100), ("lowpass", 1000.0, 100, 8000)):
            fx = dsp.Processor(kind)
            fx.set("f", f)
            self.assertAlmostEqual(level_db(fx.process(sine(keeps))), -6.0, delta=0.5, msg=kind)
            fx.reset()
            self.assertLess(level_db(fx.process(sine(cuts))), -40.0, msg=kind)
            self.assertGreater(fx.tail, 0.0)

    def test_blocks_do_not_matter(self):
        x = sine(300) + sine(5000)
        whole = dsp.Processor("lowpass").process(x)
        fx = dsp.Processor("lowpass")
        parts = np.concatenate([fx.process(x[i:i + 100], pos=i) for i in range(0, len(x), 100)])
        np.testing.assert_allclose(parts, whole, atol=1e-6)

    def test_in_place_input_is_left_alone(self):
        x = sine(440)
        before = x.copy()
        fx = dsp.Processor("gain")
        fx.set("gain", -12.0)
        fx.process(x)
        np.testing.assert_array_equal(x, before)

    def test_rejects_wrong_shapes(self):
        fx = dsp.Processor("gain")
        with self.assertRaises(ValueError):
            fx.process(np.zeros(100, np.float32))
        with self.assertRaises(ValueError):
            fx.process(np.zeros((100, 2), np.float32), side=np.zeros((50, 2), np.float32))
        self.assertEqual(len(fx.process(np.zeros((0, 2), np.float32))), 0)


@unittest.skipUnless(dsp.available(), f"no sound library: {dsp.error()}")
class EqualiserTests(unittest.TestCase):
    def check_response(self, fx, tones, delta=0.6):
        """What a sine comes out as matches what the effect says it does."""
        said = fx.response(np.array(tones, float))
        for f, want in zip(tones, said):
            fx.reset()
            got = level_db(fx.process(sine(f, 1.0, 0.1)), 0.5) - level_db(sine(f, 1.0, 0.1), 0.5)
            self.assertAlmostEqual(max(got, -70.0), max(want, -70.0), delta=delta if want > -40 else 6.0, msg=f"{fx.kind} {f} Hz")

    def test_flat_at_the_start(self):
        fx = dsp.Processor("eq")
        np.testing.assert_allclose(fx.response([30, 300, 3000, 15000]), 0.0, atol=1e-9)
        x = sine(300) + sine(3000)
        np.testing.assert_allclose(fx.process(x), x, atol=1e-5)

    def test_bands(self):
        fx = dsp.Processor("eq")
        fx.set("g3", 12.0)                                          # a bell at 1 kHz
        self.assertAlmostEqual(fx.response([1000])[0], 12.0, delta=0.05)
        self.assertAlmostEqual(fx.response([1000], part=2)[0], 12.0, delta=0.05)
        self.assertAlmostEqual(fx.response([1000], part=1)[0], 0.0, delta=1e-6)
        self.check_response(fx, [100, 1000, 5000])
        fx.set("out", -6.0)
        self.assertAlmostEqual(fx.response([1000])[0], 6.0, delta=0.05)

    def test_cut_slopes(self):
        for slope in range(4):
            fx = dsp.Processor("eq")
            for i in range(2, 9):
                fx.set(f"o{i}", 0)
            fx.set("t1", 3)
            fx.set("s1", slope)
            fx.set("f1", 1000)
            at, below = fx.response([1000, 125])
            self.assertAlmostEqual(at, -3.01, delta=0.05)           # Butterworth: 3 dB down at the cutoff
            self.assertAlmostEqual(below, -36.1 * (slope + 1), delta=1.5)
            self.check_response(fx, [500, 1000, 4000])

    def test_switching_a_band_does_not_click(self):
        fx = dsp.Processor("eq")
        x = sine(100, 0.5, 0.5)
        a = fx.process(x[:512])
        fx.set("t1", 3)
        fx.set("f1", 2000)
        b = fx.process(x[512:1024], pos=512)
        self.assertLess(np.abs(np.diff(np.concatenate([a, b])[:, 0])).max(), 0.05)

    def test_filter_modes(self):
        for mode in range(13):
            fx = dsp.Processor("filter")
            fx.set("mode", mode)
            self.check_response(fx, [200, 1900, 9000])
        fx = dsp.Processor("filter")
        fx.set("mode", 1)
        fx.set("res", 8.0)
        self.assertGreater(fx.response([2000])[0], 12.0)

    def test_the_analyser_changes_nothing(self):
        fx = dsp.Processor("analyzer")
        x = sine(440)
        np.testing.assert_array_equal(fx.process(x), x)
        self.assertAlmostEqual(float(fx.meters()[0]), 0.5, delta=0.001)


@unittest.skipUnless(dsp.available(), f"no sound library: {dsp.error()}")
class DynamicsTests(unittest.TestCase):
    def settled(self, kind, amp, side=None, **params):
        """The level in and out (dB, peak) of a tone once the effect has settled."""
        fx = dsp.Processor(kind)
        for k, v in params.items():
            fx.set(k, v)
        x = sine(1000, 1.0, amp)
        y = fx.process(x, side=side)
        return 20 * np.log10(amp), 20 * np.log10(max(1e-9, np.abs(y[SR // 2:]).max())), fx

    def test_compressor_follows_its_curve(self):
        for amp in (0.05, 0.25, 0.8):
            level, out, fx = self.settled("compressor", amp, thr=-20.0, ratio=4.0, knee=0.0, at=1.0, rt=200.0)
            self.assertAlmostEqual(out, fx.response([level])[0], delta=1.0, msg=amp)
        self.assertAlmostEqual(fx.response([0.0])[0], -15.0, delta=1e-6)
        self.assertGreater(float(fx.meters()[2]), 10.0)

    def test_side_chain(self):
        loud = sine(200, 1.0, 0.9)
        _, alone, _ = self.settled("compressor", 0.05, thr=-20.0, ratio=10.0)
        _, ducked, _ = self.settled("compressor", 0.05, side=loud, thr=-20.0, ratio=10.0, at=1.0)
        self.assertAlmostEqual(alone, -26.0, delta=0.2)
        self.assertLess(ducked, -38.0)
        _, shut, _ = self.settled("gate", 0.5, side=sine(200, 1.0, 0.001), thr=-30.0, red=40.0)
        self.assertLess(shut, -40.0)

    def test_gate_and_expander(self):
        level, out, _ = self.settled("gate", 0.3, thr=-30.0, red=30.0)
        self.assertAlmostEqual(out, level, delta=0.1)                           # open
        level, out, _ = self.settled("gate", 0.01, thr=-30.0, red=30.0)
        self.assertAlmostEqual(out, level - 30.0, delta=0.5)                    # shut
        level, out, fx = self.settled("expander", 0.01, thr=-30.0, ratio=3.0, knee=0.0)
        self.assertAlmostEqual(out, fx.response([level])[0], delta=1.0)

    def test_limiter_never_passes_its_ceiling(self):
        rng = np.random.default_rng(1)
        x = (rng.standard_normal((SR, 2)) * 0.4).astype(np.float32)
        x[1000] = 8.0
        for extra in ({}, {"alr": 1.0}, {"lk": 0.1, "at": 20.0}, {"lk": 20.0, "at": 0.25, "rt": 0.25}):
            fx = dsp.Processor("limiter")
            fx.set("gain", 12.0)
            fx.set("ceil", -3.0)
            for k, v in extra.items():
                fx.set(k, v)
            y = np.concatenate([fx.process(x[i:i + 512], pos=i) for i in range(0, len(x), 512)])
            self.assertLessEqual(float(np.abs(y).max()), 10 ** (-3 / 20) + 1e-6, msg=extra)
            self.assertGreater(float(np.abs(y[SR // 2:]).max()), 0.5)

    def test_limiter_latency_is_what_it_says(self):
        fx = dsp.Processor("limiter")
        fx.set("lk", 5.0)
        self.assertEqual(fx.latency, 239)
        x = (0.3 * np.random.default_rng(2).standard_normal((4000, 2))).astype(np.float32) * 0.3
        y = fx.process(x)
        np.testing.assert_allclose(y[239:], x[:-239], atol=1e-6)                # under the ceiling: only later

    def test_clip(self):
        fx = dsp.Processor("clip")
        fx.set("ceil", -6.0206)
        np.testing.assert_allclose(fx.process(sine(100, 0.5, 1.0)), np.clip(sine(100, 0.5, 1.0), -0.5, 0.5), atol=1e-5)


if __name__ == "__main__":
    unittest.main()
