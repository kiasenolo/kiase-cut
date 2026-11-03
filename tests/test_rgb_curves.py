"""The RGB Curves node (nodes/rgb_curves.glsl) against Blender 5.2's: levels, the combined curve then each colour's, film-like."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kiasecut import fx, nodemenu  # noqa: E402

PIXELS = [(29, 100, 132), (95, 23, 168), (46, 190, 192)]


def poly(*pts):
    return [[x, y, 0, 0, 0, 0] for x, y in pts]


COMBINED = poly((0, 0), (0.5, 0.8), (1, 1))
# name: (settings, what Blender 5.2 gives for PIXELS)
CASES = {
    "identity": ({}, PIXELS),
    "combined": ({"curve_c": COMBINED}, [(46, 160, 206), (153, 37, 220), (74, 229, 230)]),
    "green and blue": ({"curve_g": poly((0, 0), (0.6, 0.2), (1, 1)), "curve_b": poly((0, 0.3), (1, 0.6))}, [(29, 33, 116), (95, 8, 127), (46, 126, 134)]),
    "combined then each": ({"curve_c": COMBINED, "curve_r": poly((0, 0.1), (1, 0.9)), "curve_b": poly((0, 0.5), (1, 0.5))},
                           [(63, 160, 128), (148, 37, 128), (84, 229, 128)]),
    "levels": ({"curve_c": COMBINED, "black_level": (0.1, 0.2, 0.0, 1.0), "white_level": (0.9, 0.8, 1.0, 1.0)}, [(7, 130, 206), (140, 0, 220), (41, 246, 230)]),
    "factor": ({"fac": 0.4, "curve_c": poly((0, 0.3), (0.5, 0.2), (1, 1))}, [(46, 82, 102), (80, 43, 148), (55, 175, 177)]),
    "film like": ({"tone": "類似底片", "curve_c": COMBINED}, [(46, 156, 206), (128, 37, 220), (74, 228, 230)]),
    "film like, levels and factor": ({"tone": "類似底片", "white_level": (0.6, 0.6, 0.6, 1.0), "black_level": (0.05, 0.05, 0.05, 1.0), "fac": 0.7,
                                      "curve_c": poly((0, 0.2), (0.5, 0.4), (1, 0.9))}, [(53, 136, 173), (139, 48, 231), (66, 255, 255)]),
    "beyond the ends": ({"white_level": (0.5, 0.6, 0.7, 1.0), "black_level": (0.0, 0.0, 0.1, 1.0), "curve_c": poly((0, 0.2), (1, 0.8)),
                         "curve_g": poly((0, 0.1), (0.5, 0.5), (1, 0.7))}, [(86, 137, 157), (165, 85, 194), (106, 173, 217)]),
}


class RgbCurvesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.eng = fx.Engine()
        except fx.FilterError as exc:
            raise unittest.SkipTest(str(exc))

    def test_matches_blender(self):
        d = fx.get("builtin:nodes/rgb_curves")
        self.assertIsNone(d.error)
        img = np.array([[(*p, 255) for p in PIXELS]], np.uint8)
        for name, (settings, want) in CASES.items():
            with self.subTest(case=name):
                vals = {p.name: fx.uniform_value(p, settings.get(p.name), 0) for p in d.params}
                out = self.eng.run(d, vals, img)
                got = [tuple(int(v) for v in px[:3]) for px in out[0]]
                for g, w in zip(got, want):
                    self.assertTrue(all(abs(a - b) <= 2 for a, b in zip(g, w)), f"{got} != {want}")

    def test_semi_transparent_pixels_are_worked_on_as_straight_colours(self):
        d = fx.get("builtin:nodes/rgb_curves")
        vals = {p.name: fx.uniform_value(p, {"curve_c": COMBINED}.get(p.name), 0) for p in d.params}
        img = np.array([[(60, 80, 100, 128)]], np.uint8)                          # (straight 120, 160, 200 at one half)
        out = self.eng.run(d, vals, img)[0, 0].astype(float)
        straight = [min(255, v * 255 / out[3]) for v in out[:3]]
        self.assertEqual(int(out[3]), 128)
        want = [np.interp(v / 255, [0, 0.5, 1], [0, 0.8, 1]) * 255 for v in (120, 160, 200)]
        self.assertTrue(all(abs(a - b) < 4 for a, b in zip(straight, want)), (straight, want))

    def test_rows_follow_the_channel_and_the_tone(self):
        d = fx.get("builtin:nodes/rgb_curves")

        def shown(name, **settings):
            vals = {p.name: settings.get(p.name, p.default) for p in d.params}
            return fx.shown(d, name, fx.named(d, vals))
        self.assertTrue(shown("curve_c"))
        self.assertFalse(shown("curve_r"))
        self.assertTrue(shown("curve_r", tab="紅"))
        self.assertFalse(shown("curve_c", tab="藍"))
        self.assertFalse(shown("curve_r", tab="紅", tone="類似底片"))
        self.assertFalse(shown("tab", tone="類似底片"))

    def test_is_in_the_color_menu(self):
        adjust = next(m for m in nodemenu.COLOR if isinstance(m, tuple) and m[1] == "調整")
        self.assertIn("nodes/rgb_curves", adjust[2])


if __name__ == "__main__":
    unittest.main()
