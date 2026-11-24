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

    def test_confetti(self):
        if self.eng is None:
            self.skipTest("no OpenGL for filters")
        d = fx.get("builtin:confetti")
        self.assertIsNone(d.error)
        pic = np.zeros((90, 160, 4), np.uint8)
        for over in ({"time_offset": 6.0}, {"time_offset": 6.0, "shape": 1}, {"mode": 1}):
            vals = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
            vals.update(over)
            out = self.eng.run(d, vals, pic, time=0.5, unit=90 / 1080)
            self.assertGreater(int(out[..., 3].sum()), 0, over)
            self.assertTrue((self.eng.run(d, vals, pic, time=0.5, unit=90 / 1080) == out).all(), over)

    def test_bokeh(self):
        if self.eng is None:
            self.skipTest("no OpenGL for filters")
        d = fx.get("builtin:bokeh_lights")
        self.assertIsNone(d.error)
        pic = np.zeros((90, 160, 4), np.uint8)
        for over in ({"time_offset": 9.0}, {"time_offset": 9.0, "blades": 6}):
            vals = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
            vals.update(over)
            out = self.eng.run(d, vals, pic, time=0.5, unit=90 / 1080)
            self.assertGreater(int(out[..., :3].sum()), 0, over)
            self.assertTrue((self.eng.run(d, vals, pic, time=0.5, unit=90 / 1080) == out).all(), over)

    def test_shatter(self):
        if self.eng is None:
            self.skipTest("no OpenGL for filters")
        d = fx.get("builtin:shatter")
        self.assertIsNone(d.error)
        pic = np.full((90, 160, 4), 255, np.uint8)
        vals = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
        unit = 90 / 1080
        whole = self.eng.run(d, vals, pic, time=0.1, unit=unit)               # before the start: the picture as it is
        self.assertTrue((whole == pic).all())
        broken = self.eng.run(d, vals, pic, time=1.2, unit=unit)
        self.assertTrue(0 < int(broken[..., 3].astype(int).sum()) < int(pic[..., 3].astype(int).sum()))
        self.assertTrue((self.eng.run(d, vals, pic, time=1.2, unit=unit) == broken).all())
        self.assertEqual(int(self.eng.run(d, vals, pic, time=20.0, unit=unit)[..., 3].sum()), 0)     # all gone
        vals["reverse"] = True                                                # played backwards: back in one piece at the end
        end = vals["start"] + vals["spread"] + vals["life"]
        self.assertTrue((self.eng.run(d, vals, pic, time=end + 0.1, unit=unit) == pic).all())

    def test_particle_system(self):
        if self.eng is None:
            self.skipTest("no OpenGL for filters")
        d = fx.get("builtin:particle_system")
        self.assertIsNone(d.error)
        self.assertEqual((d.particles, d.particle_param, d.particle_copies, d.particle_children), (200000, "count", "trail", "sub"))
        pic = np.zeros((90, 160, 4), np.uint8)
        unit = 90 / 1080
        base = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
        self.assertEqual(fx.particle_count(d, dict(base, count=10, trail=3)), 40)
        for over in ({}, {"emitter": 1}, {"emitter": 2}, {"emitter": 3}, {"look": 2}, {"look": 3}, {"look": 4}, {"look": 5},
                     {"trail": 4, "mode": 1}, {"floor_on": True, "drag": 0.0}, {"turb": 80.0}, {"rotmode": 3}):
            vals = dict(base, **over)
            out = self.eng.run(d, vals, pic, time=1.0, unit=unit)
            self.assertGreater(int(out[..., :3].sum()), 0, over)
            self.assertTrue((self.eng.run(d, vals, pic, time=1.0, unit=unit) == out).all(), over)
        self.assertEqual(fx.particle_count(d, dict(base, count=10, trail=3, sub=5)), 90)      # parents and their trails, then the children
        for mode in range(3):                                                     # sub-particles: at some moment of the parent's life, or where it dies, or where it is born
            vals = dict(base, sub=4, sub_mode=mode, count=20, trail=2)
            out = self.eng.run(d, vals, pic, time=1.5, unit=unit)
            self.assertGreater(int(out[..., :3].sum()), 0, mode)
            self.assertTrue((self.eng.run(d, vals, pic, time=1.5, unit=unit) == out).all(), mode)
        only = dict(base, count=20, sub=0, mode=1, period=3.0)
        kids = dict(base, count=20, sub=6, mode=1, period=3.0, sub_mode=2, sub_life=2.0, life=0.3, life_var=0.0)      # (children outlive their parents)
        self.assertGreater(int(self.eng.run(d, kids, pic, time=0.9, unit=unit)[..., :3].sum()), 0)
        self.assertEqual(int(self.eng.run(d, dict(only, life=0.3, life_var=0.0), pic, time=0.9, unit=unit)[..., :3].sum()), 0)
        solid = np.zeros((90, 160, 4), np.uint8)                                 # from a picture: only where it is
        solid[:, :40] = 255
        out = self.eng.run(d, dict(base, emitter=4, speed=0.0, gravity=0.0, count=2000, hide_src=True), solid, time=1.0, unit=unit)
        self.assertGreater(int(out[:, :48, :3].sum()), 0)
        self.assertEqual(int(out[:, 60:, :3].sum()), 0)

    def test_depth_makes_particles_smaller_the_farther_they_are(self):
        if self.eng is None:
            self.skipTest("no OpenGL for filters")
        d = fx.get("builtin:particle_system")
        pic = np.zeros((180, 320, 4), np.uint8)
        unit = 180 / 1080
        base = dict({p.name: fx.uniform_value(p, None, 0) for p in d.params}, count=1, speed=0.0, gravity=0.0, drag=0.0, life=30.0, life_var=0.0,
                    size=200.0, size_var=0.0, size_end=1.0, fade_in=0.0, fade_out=0.0, look=1, glow=0.0, origin_x=0.5, origin_y=0.5)
        area = lambda vals: int((self.eng.run(d, vals, pic, time=1.0, unit=unit)[..., 3] > 128).sum())
        flat = area(base)
        self.assertGreater(flat, 0)
        self.assertEqual(area(dict(base, origin_z=800.0)), flat)                   # (3D off: no depth, nothing changes)
        on = dict(base, depth_on=True)
        self.assertAlmostEqual(area(on) / flat, 1.0, delta=0.05)                   # (at z = 0 as big as flat)
        far, near = area(dict(on, origin_z=600.0)), area(dict(on, origin_z=-300.0))
        self.assertLess(far, flat * 0.6)
        self.assertGreater(near, flat * 1.4)
        self.assertEqual(area(dict(on, origin_z=-5000.0)), 0)                      # (behind the viewer)
        moving = dict(on, speed_z=300.0)                                           # (going away: smaller as time goes by)
        a1 = int((self.eng.run(d, moving, pic, time=0.5, unit=unit)[..., 3] > 128).sum())
        a2 = int((self.eng.run(d, moving, pic, time=2.0, unit=unit)[..., 3] > 128).sum())
        self.assertLess(a2, a1)

    def test_a_ball_emitter_spreads_in_all_three_directions(self):
        if self.eng is None:
            self.skipTest("no OpenGL for filters")
        d = fx.get("builtin:particle_system")
        pic = np.zeros((180, 320, 4), np.uint8)
        unit = 180 / 1080
        base = dict({p.name: fx.uniform_value(p, None, 0) for p in d.params}, count=200, speed=0.0, gravity=0.0, drag=0.0, life=30.0, life_var=0.0,
                    size=20.0, size_var=0.0, size_end=1.0, fade_in=0.0, fade_out=0.0, look=1, glow=0.0, origin_x=0.5, origin_y=0.5,
                    emitter=5, ewidth=800.0, depth_on=True)
        img = self.eng.run(d, base, pic, time=25.0, unit=unit)[..., 3] > 128
        ys, xs = np.nonzero(img)
        self.assertGreater(len(xs), 100)
        self.assertGreater(xs.max() - xs.min(), 100)                                 # (it fills a round part of the picture)
        self.assertGreater(ys.max() - ys.min(), 50)
        small = [int((self.eng.run(d, dict(base, origin_z=z), pic, time=25.0, unit=unit)[..., 3] > 128).sum()) for z in (-300.0, 600.0)]
        self.assertGreater(small[0], small[1])                                       # (the ball farther away is smaller)

    def test_sprite_picture(self):
        if self.eng is None:
            self.skipTest("no OpenGL for filters")
        text = SIMPLE.replace("// @param n int", "// @sprite pic\n// @param pic color #ffffff \"p\"\n// @param n int").replace(
            "p.data = vec4(0.0);", "p.data = vec4(0.0);\n    p.size = vec2(10.0);") + """
vec4 sprite(vec2 q, vec4 color, vec4 data) { return has_sprite_picture() ? sprite_picture(q) : vec4(0.0, 0.0, 1.0, 1.0); }
"""
        d = fx.parse(text, "t")
        self.assertIsNone(d.error)
        self.assertEqual(d.sprite, "pic")
        self.assertIn("@sprite", fx.parse(text.replace("@sprite pic", "@sprite n"), "t").error)
        pic = np.zeros((60, 100, 4), np.uint8)
        none = self.eng.run(d, {"n": 1, "pic": [1, 1, 1, 1]}, pic, time=0.0, unit=1.0)
        self.assertEqual(none[30, 20].tolist(), [0, 0, 255, 255])                # (no picture: the stand-in)
        red = np.zeros((8, 8, 4), np.uint8)
        red[...] = (255, 0, 0, 255)
        got = self.eng.run(d, {"n": 1, "pic": [1, 1, 1, 1]}, pic, time=0.0, unit=1.0, sources={"pic": (red, (1, 0, 0, 0, 1, 0, 0, 0, 1))})
        self.assertEqual(got[30, 20].tolist(), [255, 0, 0, 255])                 # (the picture)


if __name__ == "__main__":
    unittest.main()
