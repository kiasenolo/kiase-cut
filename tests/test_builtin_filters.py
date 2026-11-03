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

    def test_glare_gives_the_light_and_the_highlights_alone(self):
        import numpy as np
        try:
            eng = fx.Engine()
        except fx.FilterError as exc:
            self.skipTest(str(exc))
        d = fx.get("builtin:blender_glare")
        self.assertEqual([n for n, _ in d.outputs], ["image", "glare", "highlights"])
        vals = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
        h, w = 64, 128
        rgba = np.zeros((h, w, 4), np.uint8)
        rgba[..., 3] = 255
        rgba[20:30, 50:60, :3] = 255
        with eng.ctx:
            (ta, _), _, _ = eng._targets(w, h)
            ta.write(rgba.tobytes())
            outs = [np.frombuffer(eng.run_tex(d, vals, ta, w, h, output=i).read(), np.uint8).reshape(h, w, 4) for i in range(3)]
        image, glare, high = outs
        self.assertEqual(tuple(glare[5, 5]), (0, 0, 0, 0))                # (no light far away: clear)
        self.assertGreater(glare[25, 55, 3], 0)
        self.assertGreater(glare[25, 70, 3], 0)                           # (the light spreads past the bright square)
        self.assertGreater(high[25, 55, 3], 0)
        self.assertEqual(high[25, 70, 3], 0)                              # (the highlights stay on it)
        self.assertGreater(image[25, 70, 0], 0)

    def test_textures_give_fac_and_colour_outputs(self):
        import numpy as np
        try:
            eng = fx.Engine()
        except fx.FilterError as exc:
            self.skipTest(str(exc))
        h, w = 36, 64
        rgba = np.zeros((h, w, 4), np.uint8)
        for name, outs in (("noise", ["fac", "color"]), ("gradient", ["color", "fac"]), ("wave", ["color", "fac"]),
                           ("magic", ["color", "fac"]), ("voronoi", ["distance", "color"]), ("checker", ["color", "fac"]),
                           ("brick", ["color", "fac"])):
            d = fx.get("builtin:blender_tex_" + name)
            self.assertIsNone(d.error, name)
            self.assertEqual([n for n, _ in d.outputs], outs, name)
            self.assertFalse([p.name for p in d.params if p.name == "amount"], name)
            vals = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
            with eng.ctx:
                (ta, _), _, _ = eng._targets(w, h)
                ta.write(rgba.tobytes())
                pics = [np.frombuffer(eng.run_tex(d, vals, ta, w, h, output=i).read(), np.uint8).reshape(h, w, 4) for i in range(2)]
            for pic in pics:
                self.assertTrue((pic[..., 3] == 255).all(), name)              # (opaque, whatever it is put on)
                self.assertGreater(pic[..., :3].std(), 3, name)                # (and a pattern)

    def test_noise_w_moves_the_4d_noise_only(self):
        import numpy as np
        try:
            eng = fx.Engine()
        except fx.FilterError as exc:
            self.skipTest(str(exc))
        d = fx.get("builtin:blender_tex_noise")
        vals = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
        rgba = np.full((48, 64, 4), 255, np.uint8)
        vals["w"] = 0.0
        flat = eng.run(d, vals, rgba)
        vals["w"] = 2.5
        self.assertTrue((eng.run(d, vals, rgba) == flat).all())                  # (3D: W does nothing)
        vals["dims"] = 1
        moved = eng.run(d, vals, rgba)
        vals["w"] = 0.0
        self.assertFalse((moved == eng.run(d, vals, rgba)).all())                # (4D: another W, another picture)
        self.assertFalse(fx.shown(d, "w", {"dims": "3D"}))
        self.assertTrue(fx.shown(d, "w", {"dims": "4D"}))

    def test_value_and_rgb_nodes_are_constants(self):
        import numpy as np
        try:
            eng = fx.Engine()
        except fx.FilterError as exc:
            self.skipTest(str(exc))
        rgba = np.zeros((8, 8, 4), np.uint8)
        d = fx.get("builtin:nodes/value")
        vals = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
        vals["value"] = 0.5
        out = eng.run(d, vals, rgba)
        self.assertTrue((out[..., 3] == 255).all())
        self.assertTrue(abs(int(out[0, 0, 0]) - 128) <= 1 and (out[..., 0] == out[0, 0, 0]).all())
        d = fx.get("builtin:nodes/rgb")
        vals = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
        vals["color"] = [1.0, 0.0, 0.0, 1.0]
        out = eng.run(d, vals, rgba)
        self.assertEqual(tuple(out[3, 3]), (255, 0, 0, 255))

    def test_exposure_node_doubles_per_stop(self):
        import numpy as np
        try:
            eng = fx.Engine()
        except fx.FilterError as exc:
            self.skipTest(str(exc))
        d = fx.get("builtin:nodes/exposure")
        vals = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
        rgba = np.zeros((4, 4, 4), np.uint8)
        rgba[...] = (50, 40, 20, 200)
        vals["exposure"] = 0.0
        self.assertTrue(np.abs(eng.run(d, vals, rgba).astype(int) - rgba).max() <= 1)      # (0: as it was)
        vals["exposure"] = 1.0
        out = eng.run(d, vals, rgba)
        self.assertEqual(int(out[0, 0, 3]), 200)                                           # (alpha stays)
        self.assertAlmostEqual(int(out[0, 0, 0]), 100, delta=2)                            # (one stop: twice)
        vals["exposure"] = -1.0
        self.assertAlmostEqual(int(eng.run(d, vals, rgba)[0, 0, 0]), 25, delta=2)

    def test_white_noise_is_random_per_point(self):
        import numpy as np
        try:
            eng = fx.Engine()
        except fx.FilterError as exc:
            self.skipTest(str(exc))
        d = fx.get("builtin:blender_tex_white_noise")
        self.assertEqual([n for n, _ in d.outputs], ["value", "color"])
        vals = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
        rgba = np.full((64, 128, 4), 255, np.uint8)
        out = eng.run(d, vals, rgba)
        r = out[..., 0].astype(float)
        self.assertTrue((out[..., 0] == out[..., 1]).all())              # (the value output: grey)
        self.assertGreater(r.std(), 60)                                   # (even over 0..255: ~74)
        self.assertAlmostEqual(r.mean(), 127.5, delta=8)
        vals["z"] = 3.0
        self.assertFalse((eng.run(d, vals, rgba)[..., 0] == out[..., 0]).all())     # (another Z, another picture)

    def test_memory_pull_garbles_what_is_under_it(self):
        import numpy as np
        try:
            eng = fx.Engine()
        except fx.FilterError as exc:
            self.skipTest(str(exc))
        d = fx.get("builtin:memory_pull")
        vals = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
        vals.update(amount=1.0, spread=False, page=512.0)
        y, x = np.mgrid[0:64, 0:128]
        rgba = np.zeros((64, 128, 4), np.uint8)
        rgba[..., 0], rgba[..., 1], rgba[..., 2], rgba[..., 3] = x * 2, y * 4, 90, 255
        out = eng.run(d, vals, rgba, time=1.0)
        self.assertTrue((out[..., 3] == 255).all())                      # (garbage, not nothing: the picture stays there)
        self.assertGreater(float((out != rgba).any(axis=2).mean()), 0.8)
        for look, want in ((1, 0), (2, 255)):                              # (the old looks: nothing / black)
            vals["null_look"] = look
            out = eng.run(d, vals, rgba, time=1.0)
            self.assertTrue((out[..., 3] == want).all(), look)
        self.assertEqual(d.params[[p.name for p in d.params].index("null_look")].items[0], "花屏")
        rate = by_name = next(q for q in d.params if q.name == "rate")
        self.assertEqual((rate.default, rate.lo, rate.hi), (60.0, 0.0, 240.0))            # (a new picture every frame at 60 fps)
        vals["null_look"] = 0
        calm = eng.run(d, dict(vals, chaos=0.0), rgba, time=1.0).astype(int)
        mad = eng.run(d, dict(vals, chaos=1.0), rgba, time=1.0).astype(int)
        self.assertGreater(int(np.abs(calm - mad).sum()), 0)                  # (madder: not the same picture)
        by = {p.name: p for p in d.params}
        self.assertFalse(fx.enabled(by["chaos"], fx.named(d, {"null_look": "透明"})))   # (癲狂程度 is for 花屏 only)
        self.assertTrue(fx.enabled(by["chaos"], fx.named(d, {"null_look": "花屏"})))

    def test_memory_blocks_breaks_into_blocks(self):
        import numpy as np
        try:
            eng = fx.Engine()
        except fx.FilterError as exc:
            self.skipTest(str(exc))
        d = fx.get("builtin:memory_blocks")
        self.assertIsNone(d.error)
        vals = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
        y, x = np.mgrid[0:128, 0:256]
        rgba = np.zeros((128, 256, 4), np.uint8)
        rgba[..., 0], rgba[..., 1], rgba[..., 2], rgba[..., 3] = x, y * 2, 90, 255
        vals.update(spread=False, amount=0.0)
        self.assertTrue((eng.run(d, vals, rgba, time=1.0) == rgba).all())       # (nothing failed: as it was)
        for k in [q.name for q in d.params if q.name.startswith("w_")]:
            vals[k] = 0.0
        vals.update(amount=1.0, w_gone=1.0)
        self.assertTrue((eng.run(d, vals, rgba, time=1.0)[..., :3] == 0).all())   # (all gone: black)
        vals.update(gone_look=1)
        self.assertTrue((eng.run(d, vals, rgba, time=1.0)[..., 3] == 0).all())    # (or transparent)
        vals.update(gone_look=0, w_color=1.0, w_gone=0.0, blk=32.0, aspect=1.0, split=0.0)
        out = eng.run(d, vals, rgba, time=1.0)
        self.assertEqual(len(np.unique(out[:32, :32].reshape(-1, 4), axis=0)), 1)   # (only a colour: one block, one colour)
        vals.update(w_color=0.0, w_vx=1.0)                                          # (only X: a block's columns are all the same down)
        out = eng.run(d, vals, rgba, time=1.0)
        self.assertTrue((out[:32, :32] == out[:1, :32]).all())

    def test_options_that_do_nothing_are_half_faded(self):
        from PySide6.QtWidgets import QApplication
        from kiasecut import edit
        from kiasecut.ui.effects_panel import EffectsPanel
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from test_edit import proj
        APP = QApplication.instance() or QApplication([])
        p = proj()
        e = edit.put_effect(p, "c1", "builtin:blender_glare")
        e["params"]["type"] = "Streaks"
        panel = EffectsPanel()
        c = edit.find(p, "c1")[1]
        panel.show_clips([c], 0, 30)
        row = lambda name: panel.param_rows[(e["id"], name)]
        self.assertEqual(row("streaks").graphicsEffect().opacity(), 1.0)          # (Streaks uses these)
        self.assertTrue(row("streaks").isEnabled())
        self.assertEqual(row("sun_position").graphicsEffect().opacity(), 0.5)     # (Sun Beams' only)
        self.assertFalse(row("sun_position").isEnabled())
        e["params"]["type"] = "Sun Beams"
        panel.show_clips([c], 0, 30)
        self.assertEqual(row("sun_position").graphicsEffect().opacity(), 1.0)
        self.assertEqual(row("streaks").graphicsEffect().opacity(), 0.5)

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

    def test_outputs_share_the_passes_before_the_last(self):
        """@shared: every output asked at once is drawn by the last pass alone, the passes before it once for all;
        an @alone output skips those; @skip leaves passes out while its condition holds."""
        try:
            eng = fx.Engine()
        except fx.FilterError as exc:
            self.skipTest(str(exc))
        d = fx.parse('// @passes 3\n// @shared\n// @output a\n// @output b\n// @output c\n// @alone c\n'
                     '// @param mode menu on "on|off"\n// @skip 1 mode == off\n'
                     'vec4 effect(vec2 uv) {\n'
                     '  if (pass_index == 0) return vec4(0.25, 0.0, 0.0, 1.0);\n'
                     '  if (pass_index == 1) return vec4(src(uv).r + 0.25, 0.0, 0.0, 1.0);\n'
                     '  if (output_index == 0) return vec4(src(uv).r, 0.0, 0.0, 1.0);\n'
                     '  if (output_index == 1) return vec4(src(uv).r, 1.0, 0.0, 1.0);\n'
                     '  return vec4(0.0, 0.0, 1.0, 1.0);\n}', "t")
        self.assertIsNone(d.error)
        self.assertEqual((d.shared, d.alone, d.skips), (True, ["c"], [(1, 1, [("mode", False, ["off"])])]))
        draws = []
        real = eng._program

        def counted(*a, **k):
            prog, vao = real(*a, **k)
            return prog, type("V", (), {"render": lambda _s, mode: (draws.append(1), vao.render(mode))})()
        eng._program = counted

        def targets(n):
            out = []
            for _ in range(n):
                tex = eng.ctx.texture((8, 8), 4)
                out.append((tex, eng.ctx.framebuffer(color_attachments=[tex])))
            return out
        src = eng.ctx.texture((8, 8), 4, bytes(8 * 8 * 4))

        def run(values, which):
            dests = targets(len(which))
            draws.clear()
            res = eng.run_outputs(d, values, src, 8, 8, list(zip(which, dests)))
            return [tuple(np.frombuffer(t.read(), np.uint8)[:4]) for t in res], len(draws)
        got, n = run({"mode": 0}, [0, 1, 2])
        self.assertEqual((got[0], got[1], got[2]), ((128, 0, 0, 255), (128, 255, 0, 255), (0, 0, 255, 255)))
        self.assertEqual(n, 5)                                    # (2 shared + one last pass each; 9 drawn one by one)
        self.assertEqual(run({"mode": 0}, [2])[1], 1)             # (c alone: the last pass only)
        got, n = run({"mode": 1}, [0, 1])                         # (pass 1 left out: the last reads pass 0's 0.25)
        self.assertEqual((got[0], n), ((64, 0, 0, 255), 3))

    def test_sun_beams_skip_blocks_without_light_and_change_nothing(self):
        """The gather leaves out runs of steps in blocks of the highlights with no light: the picture is the one every step
        read gives (the same shader with the skipping taken out), whatever the sun, size, quality and scale."""
        try:
            eng = fx.Engine()
        except fx.FilterError as exc:
            self.skipTest(str(exc))
        d = fx.get("builtin:blender_glare")
        every = fx.parse(d.code.replace("if (!lit)\n            continue;", ""), "t")
        self.assertNotEqual(every.code, d.code)
        rng = np.random.default_rng(3)
        for (w, h), unit, quality, sun in [((96, 54), 1.0, 0, (0.5, 0.5)), ((101, 61), 0.5, 1, (0.5, -0.05)),
                                           ((96, 54), 0.37, 2, (1.4, 0.9)), ((101, 61), 1.0, 0, (0.2, 0.7))]:
            img = np.zeros((h, w, 4), np.uint8)
            img[..., 3] = 255
            for _ in range(4):                                        # (a few bright specks: most blocks hold no light)
                x, y = rng.integers(0, w - 6), rng.integers(0, h - 6)
                img[y:y + rng.integers(1, 6), x:x + rng.integers(1, 6), :3] = 255
            vals = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
            vals.update({"type": 5, "quality": quality, "sun_position": sun, "size": 0.3 if unit == 0.37 else 1.0, "threshold": 0.4,
                         "smoothness": 0.0, "strength": 1.0})
            got = eng.run(d, vals, img, unit=unit)
            self.assertTrue(got[..., :3].max() > 0)
            self.assertTrue(np.array_equal(got, eng.run(every, vals, img, unit=unit)), (w, h, unit, quality, sun))

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

    def lens(self, rgba, **kw):
        import numpy as np
        try:
            eng = fx.Engine()
        except fx.FilterError as exc:
            self.skipTest(str(exc))
        d = fx.get("builtin:blender_lens_distortion")
        vals = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
        vals.update(kw)
        return eng.run(d, vals, rgba).astype(int)

    def test_lens_distortion_is_blenders(self):
        """Blender 5.2's Lens Distortion node (Distortion 0.4, Dispersion 0.6) on a small picture: the rows below
        are its render, in sRGB. Pixels the lens shows nothing of stay empty (the corners), the rest agrees to
        the 8-bit rounding."""
        import numpy as np
        h, w = 16, 24
        y, x = np.mgrid[0:h, 0:w]
        rgba = np.zeros((h, w, 4), np.uint8)
        rgba[..., 3] = 255
        rgba[..., 0], rgba[..., 1], rgba[..., 2] = 40 + 8 * x, 60 + 8 * y, 200 - 6 * x
        rgba[:, 15] = 255
        rgba[5, :, :3] = (255, 40, 40)
        out = self.lens(rgba, mode=0, distortion=0.4, dispersion=0.6)
        row8 = [[52, 123, 183], [65, 123, 177], [75, 123, 172], [83, 123, 167], [90, 123, 162], [96, 123, 157], [102, 123, 153],
                [108, 123, 149], [114, 123, 145], [119, 123, 141], [124, 123, 137], [129, 123, 133], [135, 123, 129],
                [140, 123, 125], [145, 123, 121], [150, 123, 117], [211, 200, 196], [240, 238, 239], [171, 139, 135],
                [174, 123, 100], [181, 123, 96], [189, 123, 90], [199, 123, 85], [212, 123, 79]]
        row2 = [[0, 0, 0], [0, 0, 0], [0, 0, 0], [71, 84, 170], [83, 86, 165], [91, 87, 160], [98, 87, 155], [105, 88, 150],
                [111, 88, 146], [117, 89, 142], [123, 89, 137], [129, 89, 133], [135, 89, 129], [141, 89, 125], [147, 89, 121],
                [164, 104, 116], [245, 232, 224], [197, 181, 204], [173, 87, 103], [182, 86, 97], [193, 84, 92], [0, 0, 0],
                [0, 0, 0], [0, 0, 0]]
        alpha0 = [0, 0, 0, 0, 0, 0, 223, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 223, 0, 0, 0, 0, 0, 0]
        # (the colour is premultiplied here: straight in the rows above, which are opaque or empty)
        self.assertLessEqual(int(np.abs(out[8, :, :3] - np.array(row8)).max()), 3)
        self.assertLessEqual(int(np.abs(out[2, :, :3] - np.array(row2)).max()), 3)
        self.assertLessEqual(int(np.abs(out[0, :, 3] - np.array(alpha0)).max()), 2)

    def test_lens_distortion_leaves_what_the_lens_cannot_show_empty(self):
        import numpy as np
        out = self.lens(np.full((40, 60, 4), 255, np.uint8), mode=0, distortion=1.0)
        self.assertEqual(tuple(out[0, 0]), (0, 0, 0, 0))                    # (past the lens: not even the picture's edge)
        self.assertEqual(tuple(out[20, 30]), (255, 255, 255, 255))
        # a pincushion (negative distortion) fills the corners from further out, so the picture's edge stays in
        out = self.lens(np.full((40, 60, 4), 255, np.uint8), mode=0, distortion=-0.5)
        self.assertEqual(tuple(out[20, 30]), (255, 255, 255, 255))
        self.assertEqual(out[0, 0, 3], 255)

    def test_lens_distortion_disperses_red_in_and_blue_out(self):
        """A bright vertical line right of the centre: with a barrel (positive) distortion red lands nearer the
        centre and blue further out (green between), and the jitter changes nothing about where."""
        import numpy as np
        rgba = np.zeros((40, 200, 4), np.uint8)
        rgba[..., 3] = 255
        rgba[:, 150:152, :3] = 255
        for jitter in (False, True):
            out = self.lens(rgba, mode=0, distortion=0.3, dispersion=1.0, jitter=jitter)
            peak = [int(np.argmax(out[20, 100:, c])) for c in range(3)]
            self.assertLess(peak[0], peak[2], peak)

    def test_lens_distortion_horizontal_shifts_red_left_and_blue_right(self):
        """水平: 5 px per unit of dispersion, the alpha the average of the three taps (where one reads past the edge)."""
        import numpy as np
        rgba = np.zeros((10, 40, 4), np.uint8)
        rgba[..., 3] = 255
        rgba[:, 20] = 255
        out = self.lens(rgba, mode=1, dispersion=1.0)
        self.assertEqual([tuple(out[5, x, :3]) for x in (15, 20, 25)], [(255, 0, 0), (0, 255, 0), (0, 0, 255)])
        self.assertEqual(int(out[5, 14:26, :3].astype(bool).sum()), 3)
        self.assertEqual(int(out[5, 0, 3]), 170)                              # (2/3: the blue tap is outside)
        self.assertEqual(int(out[5, 20, 3]), 255)

    def test_transform_filters_are_available(self):
        names = {fx.get(ref).name for ref in fx.builtin_refs()}
        self.assertTrue({"Transform", "Scale", "Translate"}.issubset(names))

    def test_blur_kernel_is_blenders(self):
        """A white line blurred: tent weights (size - distance) / size^2 across it, a flat box, a radial kernel when not
        separable (as Blender 5.2's Blur node)."""
        if self.eng is None:
            self.skipTest("no OpenGL for filters")
        d = fx.get("builtin:blur")
        base = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
        line = np.zeros((41, 41, 4), np.uint8)
        line[..., 3] = 255
        line[20, :, :3] = 255
        tent = {**base, "radius": 10.0, "link_xy": True, "kind": 1, "separable": True}
        col = self.eng.run(d, tent, line)[20:31, 20, 0] / 255.0
        self.assertTrue(np.allclose(col, [(10 - i) / 100 for i in range(11)], atol=1.5 / 255), col)
        dot = np.zeros((41, 41, 4), np.uint8)
        dot[..., 3] = 255
        dot[20, 20, :3] = 255
        flat = self.eng.run(d, {**tent, "radius": 3.0, "kind": 0}, dot)[..., 0].astype(float)
        self.assertTrue((flat[17:24, 17:24] == flat[20, 20]).all())                   # 7 x 7, all the same
        self.assertEqual(flat[16, 20], 0.0)
        disc = self.eng.run(d, {**tent, "radius": 4.0, "kind": 0, "separable": False}, dot)[..., 0]
        self.assertGreater(disc[20, 24], 0)                                            # a radial kernel: on the radius ...
        self.assertEqual(disc[24, 24], 0)                                              # ... but not in the corner of the box

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
