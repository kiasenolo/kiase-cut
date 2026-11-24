"""@particles: a filter that draws instanced particles over its picture (fx.py), stateless in time."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kiasecut import fx  # noqa: E402

SIMPLE = """// @filter t
// @particles 50 n
// @param n int 10 1 50 "n"
bool particle(int i, out Particle p) {
    p.pos = vec2(20.0 + float(i) * 8.0, 30.0);
    p.size = vec2(4.0);
    p.rot = 0.0;
    p.color = vec4(1.0, 0.5, 0.0, 1.0);
    p.data = vec4(0.0);
    return true;
}
"""


class ParticleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.eng = fx.Engine()
        except fx.FilterError:
            cls.eng = None

    def test_header(self):
        d = fx.parse(SIMPLE, "t")
        self.assertIsNone(d.error)
        self.assertEqual((d.particles, d.particle_param), (50, "n"))
        self.assertEqual(fx.particle_count(d, {"n": 7}), 7)
        self.assertEqual(fx.particle_count(d, {"n": 500}), 50)
        for bad, word in ((SIMPLE.replace("50 n", "0"), "@particles"), (SIMPLE.replace("50 n", "50 nope"), "nope"),
                          (SIMPLE.replace("bool particle(", "bool other("), "particle()")):
            self.assertIn(word, fx.parse(bad, "t").error)

    def test_draws_and_is_stateless(self):
        if self.eng is None:
            self.skipTest("no OpenGL for filters")
        d = fx.parse(SIMPLE, "t")
        pic = np.zeros((60, 100, 4), np.uint8)
        few = self.eng.run(d, {"n": 3}, pic, time=0.0, unit=1.0)
        many = self.eng.run(d, {"n": 10}, pic, time=0.0, unit=1.0)
        self.assertGreater(int(few[..., 3].sum()), 0)
        self.assertGreater(int(many[..., 3].sum()), int(few[..., 3].sum()))
        r, g, b, a = few[30, 20].tolist()                                 # the first particle's middle: premultiplied, nearly opaque
        self.assertGreater(a, 200)
        self.assertEqual((r, b), (a, 0))
        self.assertAlmostEqual(g / a, 0.5, delta=0.02)
        again = self.eng.run(d, {"n": 10}, pic, time=0.0, unit=1.0)
        self.assertTrue((many == again).all())

    def test_sparks(self):
        if self.eng is None:
            self.skipTest("no OpenGL for filters")
        d = fx.get("builtin:sparks")
        self.assertIsNone(d.error)
        pic = np.zeros((90, 160, 4), np.uint8)
        vals = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
        early = self.eng.run(d, vals, pic, time=0.4, unit=90 / 1080)
        later = self.eng.run(d, vals, pic, time=1.2, unit=90 / 1080)
        self.assertGreater(int(early[..., :3].sum()), 0)
        self.assertFalse((early == later).all())
        # any frame on its own: jumping back gives what the first visit gave
        self.assertTrue((self.eng.run(d, vals, pic, time=0.4, unit=90 / 1080) == early).all())
        vals["mode"] = 1                                                  # a burst is over once the sparks are
        vals["period"] = 30.0
        self.assertEqual(int(self.eng.run(d, vals, pic, time=20.0, unit=90 / 1080)[..., :3].sum()), 0)


if __name__ == "__main__":
    unittest.main()
