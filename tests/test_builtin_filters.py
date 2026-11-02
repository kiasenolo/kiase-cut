"""Every built-in filter reads, compiles and runs at its defaults (and at every menu choice)."""
import os
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kiasecut import fx  # noqa: E402


class BuiltinFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.eng = fx.Engine()
        except fx.FilterError:
            cls.eng = None

    def test_all_run(self):
        if self.eng is None:
            self.skipTest("no OpenGL for filters")
        pic = np.zeros((54, 96, 4), np.uint8)
        pic[10:40, 20:70] = (250, 240, 200, 255)
        for ref in fx.builtin_refs():
            d = fx.get(ref)
            with self.subTest(filter=ref):
                self.assertIsNone(d.error)
                vals = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
                menus = [p for p in d.params if p.type == "menu"]
                for p in menus or [None]:
                    for k in range(len(p.items) if p else 1):
                        if p:
                            vals[p.name] = k
                        out = self.eng.run(d, vals, pic, time=0.5, progress=0.5, frame=3, unit=54 / 1080)
                        self.assertEqual(out.shape, pic.shape)
                    if p:
                        vals[p.name] = fx.uniform_value(p, None, 0)

    def test_panels_and_enable(self):
        d = fx.parse('// @param mode menu A "A|B|C"\n// @param on bool false\n// @panel 面板 closed\n'
                     '// @param x float 1\n// @param y float 1\n// @enable x mode == B|C\n// @enable y !on\n'
                     '// @panel -\n// @param z float 1\nvec4 effect(vec2 uv) { return src(uv); }', "t")
        self.assertIsNone(d.error)
        self.assertEqual(d.panels, [("面板", True)])
        by = {p.name: p for p in d.params}
        self.assertEqual((by["x"].panel, by["z"].panel), ("面板", None))
        self.assertFalse(fx.enabled(by["x"], fx.named(d, {"mode": "A"})))
        self.assertTrue(fx.enabled(by["x"], fx.named(d, {"mode": 2})))          # (a menu stored as its number)
        self.assertFalse(fx.enabled(by["y"], {"on": True}))
        self.assertTrue(fx.enabled(by["z"], {}))
        bad = fx.parse("// @param x float 1\n// @enable x nothing == 1\nvec4 effect(vec2 uv) { return src(uv); }", "t")
        self.assertIn("nothing", bad.error)

    def test_blender_ones_named(self):
        names = {fx.get(ref).name for ref in fx.builtin_refs()}
        for n in ("Glare", "Lens Distortion", "Vignette", "Sensor Noise"):
            self.assertIn("[Blender] " + n, names)

    def test_levels_and_extras(self):
        d = fx.parse('// @passes 3\n// @param quality menu a "a|b"\n// @levels 0f 1 2 quality\n// @extras - - 0\n'
                     'vec4 effect(vec2 uv) { return src(uv); }', "t")
        self.assertIsNone(d.error)
        self.assertEqual((d.levels, d.fixed, d.level_param, d.extras), ([0, 1, 2], [True, False, False], "quality", [None, None, 0]))
        self.assertEqual(fx.Engine.level_size(d, 0, {"quality": 1}, 100, 60, (100, 60)), (100, 60))     # (f: kept)
        self.assertEqual(fx.Engine.level_size(d, 2, {"quality": 1}, 100, 60, (100, 60)), (12, 7))       # (2 + 1 halvings)
        self.assertEqual(fx.Engine.level_size(d, 1, {"quality": 0}, 50, 30, (400, 240)), (50, 30))      # (never bigger than the picture)
        for bad in ('// @passes 2\n// @levels 0 1 2\n', '// @passes 2\n// @extras - 1\n', '// @passes 2\n// @levels 0 nothing\n'):
            self.assertIsNotNone(fx.parse(bad + 'vec4 effect(vec2 uv) { return src(uv); }', "t").error, bad)

    def test_a_chain_of_smaller_passes_reaches_the_last_one(self):
        """Pass 0 draws a lit pixel, pass 1 reads it at half size, the last one reads pass 0 again with extra()."""
        import numpy as np
        try:
            eng = fx.Engine()
        except fx.FilterError as exc:
            self.skipTest(str(exc))
        d = fx.parse('// @passes 3\n// @precision float\n// @levels 0 2\n// @extras - - 0\n'
                     'vec4 effect(vec2 uv) {\n'
                     '  if (pass_index == 0) return vec4(1.0, 0.0, 0.0, 1.0);\n'
                     '  if (pass_index == 1) return vec4(pass_px / 100.0, src_px.x / 100.0, 1.0);\n'
                     '  return vec4(src(uv).rg, extra(uv).r * 0.5, 1.0);\n}',
                     "t")
        self.assertIsNone(d.error)
        out = eng.run(d, {}, np.zeros((40, 80, 4), np.uint8))
        self.assertEqual(tuple(out[20, 40]), (51, 25, 128, 255))         # (pass 1 was 80 / 4 = 20 x 40 / 4 = 10 px; pass 0 gave 1.0 / 2)

    def test_bloom_is_blenders_chain(self):
        """Bloom normalised by the chain's length: a lit square on black glows evenly all round, and a bigger Size reaches further."""
        import numpy as np
        try:
            eng = fx.Engine()
        except fx.FilterError as exc:
            self.skipTest(str(exc))
        d = fx.get("builtin:blender_glare")
        vals = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
        vals.update(type=0, threshold=0.2, strength=4.0, quality=0)
        rgba = np.zeros((128, 128, 4), np.uint8)
        rgba[60:68, 60:68] = 255
        reach = []
        for size in (0.1, 0.5):
            vals["size"] = size
            out = eng.run(d, vals, rgba)
            self.assertAlmostEqual(int(out[64, 80, 0]), int(out[80, 64, 0]), delta=3)       # (the same all round)
            reach.append(int(out[64, 110, 0]))
        self.assertGreater(reach[1], reach[0])

    def test_glare_spreads_over_what_was_clear(self):
        """A bright spot on a transparent picture: the glow has alpha where the picture had none."""
        import numpy as np
        try:
            eng = fx.Engine()
        except fx.FilterError as exc:
            self.skipTest(str(exc))
        d = fx.get("builtin:blender_glare")
        vals = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
        vals.update(type=0, threshold=0.2, size=0.5, strength=4.0, quality=0)         # (Bloom)
        rgba = np.zeros((96, 96, 4), np.uint8)
        rgba[44:52, 44:52] = (255, 255, 255, 255)
        out = eng.run(d, vals, rgba)
        self.assertEqual(out[48, 48, 3], 255)
        for x in (54, 58):                                                           # (a few pixels from the spot)
            self.assertGreater(int(out[48, x, 3]), 0)
            self.assertGreater(int(out[48, x, :3].max()), 0)
            self.assertLessEqual(int(out[48, x, :3].max()), int(out[48, x, 3]))      # (still a valid premultiplied pixel)
        self.assertGreater(int(out[48, 54, 3]), int(out[48, 58, 3]))                 # (and fading away)

    def test_transform_filters_are_available(self):
        names = {fx.get(ref).name for ref in fx.builtin_refs()}
        self.assertTrue({"Transform", "Scale", "Translate"}.issubset(names))

    def test_seed_uses_subsecond_timestamp(self):
        ref = "builtin:light_leak"
        with patch("kiasecut.fx.time.time_ns", side_effect=(1_234_567_890_123, 1_234_567_890_456)):
            first = fx.new_effect(ref, "e1")["params"]["seed"]
            second = fx.new_effect(ref, "e2")["params"]["seed"]
        self.assertNotEqual(first, second)
        self.assertGreaterEqual(first, 0)
        self.assertLessEqual(first, 100)


if __name__ == "__main__":
    unittest.main()
