"""The texture nodes (nodes/tex_*.glsl): Blender's own sockets, settings and shader code, checked against Blender 5.2."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kiasecut import fx, nodegraph as ng, nodemenu  # noqa: E402

W, H = 64, 40
NAMES = ["brick", "checker", "gabor", "gradient", "magic", "noise", "voronoi", "wave", "white_noise"]
PTS = [(3, 5), (12, 40), (27, 17), (35, 58)]              # (row, column) of the 64 x 40 picture, top down

# What Blender 5.2 renders for the node at these pixels (its settings are the node's defaults unless the case says): [(red, green, blue)]
BLENDER = {
    "checker_color": ("checker", 0, {}, [(204,) * 3, (51,) * 3, (204,) * 3, (204,) * 3]),
    "checker_fac": ("checker", 1, {}, [(255,) * 3, (0,) * 3, (255,) * 3, (255,) * 3]),
    "gradient_radial": ("gradient", 1, {"gtype": "放射"}, [(232,) * 3, (157,) * 3, (19,) * 3, (106,) * 3]),
    "brick": ("brick", 0, {}, [(73,) * 3, (84,) * 3, (124,) * 3, (76,) * 3]),
    "magic": ("magic", 0, {}, [(0, 241, 133), (32, 102, 255), (160, 245, 116), (10, 169, 42)]),
    "white_noise_3d": ("white_noise", 1, {"dims": "3D"}, [(100, 57, 71), (33, 5, 169), (89, 195, 86), (112, 143, 121)]),
    "white_noise_1d": ("white_noise", 0, {"dims": "1D", "w": 1.7}, [(200,) * 3] * 4),
    "wave_distorted": ("wave", 0, {"wave_profile": "鋸齒", "tex_scale": 3, "distortion": 2.2, "detail": 3.5, "detail_scale": 1.5,
                                   "detail_roughness": 0.6, "phase": 1.0}, [(58,) * 3, (177,) * 3, (214,) * 3, (11,) * 3]),
    "gabor_3d": ("gabor", 1, {"gabor_type": "3D", "tex_scale": 4, "anisotropy": 0.7, "orientation_3d": [0, 1, 0]},
                 [(21,) * 3, (100,) * 3, (161,) * 3, (190,) * 3]),
    "noise": ("noise", 0, {}, [(110,) * 3, (86,) * 3, (127,) * 3, (108,) * 3]),
    "noise_ridged_4d": ("noise", 1, {"dims": "4D", "ntype": "脊狀多重分形", "w": 0.7, "tex_scale": 3.3, "detail": 3.5, "roughness": 0.6,
                                     "lacunarity": 2.3, "offset": 0.4, "gain": 1.3, "distortion": 0.5},
                        [(13, 27, 0), (2, 13, 2), (0, 15, 2), (0, 2, 3)]),
    "voronoi": ("voronoi", 0, {}, [(209,) * 3, (100,) * 3, (81,) * 3, (95,) * 3]),
    "voronoi_smooth_3d_colour": ("voronoi", 1, {"dims": "3D", "feature": "平滑 F1", "w": 0.6, "tex_scale": 3.1, "detail": 2.5, "roughness": 0.55,
                                                "lacunarity": 2.2, "smoothness": 0.8, "exponent": 1.5, "randomness": 0.9},
                                 [(255, 255, 129), (242, 255, 255), (150, 137, 181), (255, 243, 190)]),
    "voronoi_f2_4d_position": ("voronoi", 2, {"dims": "4D", "feature": "F2", "w": 0.6, "tex_scale": 3.1, "detail": 2.5, "roughness": 0.55,
                                              "lacunarity": 2.2, "smoothness": 0.8, "exponent": 1.5, "randomness": 0.9},
                               [(0, 126, 21), (58, 60, 0), (0, 0, 11), (206, 0, 9)]),
    "voronoi_radius": ("voronoi", 4, {"feature": "N 球半徑", "w": 0.6, "tex_scale": 3.1, "detail": 2.5, "roughness": 0.55, "lacunarity": 2.2,
                                      "smoothness": 0.8, "exponent": 1.5, "randomness": 0.9}, [(116,) * 3, (98,) * 3, (55,) * 3, (114,) * 3]),
}


def engine():
    try:
        return fx.Engine()
    except fx.FilterError as exc:
        raise unittest.SkipTest(str(exc))


class TextureNodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eng = engine()

    def draw(self, name, output, settings):
        d = fx.get("builtin:nodes/tex_" + name)
        self.assertIsNone(d.error, name)
        vals = {p.name: fx.uniform_value(p, settings.get(p.name), 0) for p in d.params}
        with self.eng.ctx:
            (ta, _), _, _ = self.eng._targets(W, H)
            ta.write(np.zeros((H, W, 4), np.uint8).tobytes())
            return np.frombuffer(self.eng.run_tex(d, vals, ta, W, H, output=output, src_on=False).read(), np.uint8).reshape(H, W, 4)

    def test_every_texture_node_loads_and_is_in_the_menu(self):
        for name in NAMES:
            d = fx.get("builtin:nodes/tex_" + name)
            self.assertIsNone(d.error, name)
            self.assertEqual(d.category, "紋理", name)
        self.assertEqual([i for i in nodemenu.TEXTURE if i.startswith("nodes/")], ["nodes/tex_" + n for n in NAMES])

    def test_the_outputs_are_blenders(self):
        for name, outs in (("checker", ["color", "fac"]), ("noise", ["fac", "color"]), ("white_noise", ["value", "color"]),
                           ("gabor", ["value", "phase", "intensity"]), ("voronoi", ["distance", "color", "position", "wout", "radius"])):
            self.assertEqual([n for n, _ in fx.get("builtin:nodes/tex_" + name).outputs], outs, name)

    def test_pixels_match_blender(self):
        for case, (name, output, settings, want) in BLENDER.items():
            with self.subTest(case=case):
                pic = self.draw(name, output, settings)
                got = [tuple(int(v) for v in pic[y, x, :3]) for y, x in PTS]
                for g, w in zip(got, want):
                    self.assertTrue(all(abs(a - b) <= 1 for a, b in zip(g, w)), f"{got} != {want}")

    def test_default_dimensions_are_blenders(self):
        for name, dims in (("noise", "2D"), ("voronoi", "2D"), ("white_noise", "2D"), ("gabor", "2D")):
            d = fx.get("builtin:nodes/tex_" + name)
            p = next(q for q in d.params if q.name in ("dims", "gabor_type"))
            self.assertEqual(p.items[int(fx.uniform_value(p, None, 0))], dims, name)

    def test_rows_follow_the_settings(self):
        d = fx.get("builtin:nodes/tex_noise")

        def shown(name, **settings):
            vals = {p.name: settings.get(p.name, p.default) for p in d.params}
            return fx.shown(d, name, fx.named(d, vals))
        self.assertFalse(shown("src", dims="1D"))
        self.assertTrue(shown("src", dims="3D"))
        self.assertTrue(shown("w", dims="4D"))
        self.assertFalse(shown("w", dims="3D"))
        self.assertFalse(shown("gain", ntype="fBM"))
        self.assertTrue(shown("gain", ntype="脊狀多重分形"))
        self.assertFalse(shown("gain", ntype="異質地形"))
        self.assertTrue(shown("offset", ntype="異質地形"))

    def test_voronoi_outputs_follow_the_feature(self):
        d = fx.get("builtin:nodes/tex_voronoi")

        def outs(**settings):
            vals = {p.name: settings.get(p.name, p.default) for p in d.params}
            return [n for n, _ in d.outputs if fx.shown(d, n, fx.named(d, vals))]
        self.assertEqual(outs(), ["distance", "color", "position"])
        self.assertEqual(outs(dims="4D"), ["distance", "color", "position", "wout"])
        self.assertEqual(outs(feature="到邊緣距離"), ["distance"])
        self.assertEqual(outs(feature="N 球半徑"), ["radius"])


class LinkedVectorTests(unittest.TestCase):
    def test_a_linked_vector_is_the_texture_s_coordinate(self):
        """Image Coordinates (uniform) into a Gradient's Vector is the gradient it draws unlinked."""
        eng = engine()
        g = ng.new_graph()
        c = ng.add_node(g, {"type": "filter", "ref": "builtin:nodes/coordinate"}, base="c")
        t = ng.add_node(g, {"type": "filter", "ref": "builtin:nodes/tex_gradient"}, base="t")
        ng.connect(g, c, t, "src", "uniform")
        ng.connect(g, t, "output", "src", "fac")
        pool = ng.Pool(eng)
        with eng.ctx:
            src = eng.ctx.texture((W, H), 4, np.zeros((H, W, 4), np.uint8).tobytes())
            tex, owner = ng.evaluate(eng, g, ng.default_params(g), src, W, H, pool.alloc, pool.free)
            linked = ng.read_rgba8(tex).copy()
        row = linked[H // 2, :, 0].astype(int)
        self.assertEqual(row[0], 0)                                         # (x < 0: the linear gradient is 0)
        self.assertGreater(row[-1], 230)                                    # (x near 1)
        self.assertTrue((np.diff(row[W // 2:]) >= 0).all())


if __name__ == "__main__":
    unittest.main()
