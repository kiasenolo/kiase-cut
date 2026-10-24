"""vec3 filter parameters, and (when the `bpy` module is installed) filters exported from Blender with
tools/converters/compositor_to_hyprshade.py in the KiaseCut format."""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tesetoa import fx  # noqa: E402

try:
    import bpy  # noqa: E402
except ImportError:
    bpy = None


def engine():
    try:
        return fx.Engine()
    except fx.FilterError as exc:
        raise unittest.SkipTest(str(exc))


FILTER = """// @filter V3
// @param tint vec3 0.1,0.2,0.3 -1 2 "Tint"
vec4 effect(vec2 uv) {
    vec4 c = src(uv);
    return vec4(clamp(c.rgb + tint * c.a, 0.0, 1.0), c.a);
}
"""


class Vec3Test(unittest.TestCase):
    def test_parse(self):
        d = fx.parse(FILTER, "t")
        self.assertIsNone(d.error)
        p = d.params[0]
        self.assertEqual((p.type, p.default, p.lo, p.hi, p.label), ("vec3", [0.1, 0.2, 0.3], -1.0, 2.0, "Tint"))
        self.assertIn("uniform vec3 tint;", fx.shader_source(d))

    def test_bad_default(self):
        self.assertIn("vec3", fx.parse(FILTER.replace("0.1,0.2,0.3", "0.1,0.2"), "t").error)

    def test_uniform_value_and_animation(self):
        p = fx.parse(FILTER, "t").params[0]
        self.assertEqual(fx.uniform_value(p, None, 0), (0.1, 0.2, 0.3))
        anim = {"keys": [[0, [0.0, 0.0, 0.0], 0, 0, 0, 0], [1_000_000, [1.0, 0.5, 0.0], 0, 0, 0, 0]]}
        v = fx.uniform_value(p, anim, 500_000)
        self.assertEqual(len(v), 3)
        self.assertAlmostEqual(v[0], 0.5, places=3)
        self.assertAlmostEqual(v[1], 0.25, places=3)

    def test_render(self):
        eng = engine()
        d = fx.parse(FILTER, "t")
        rgba = np.full((8, 8, 4), 255, np.uint8)
        rgba[..., :3] = 0
        out = eng.run(d, {"tint": (0.5, 0.0, 1.0)}, rgba)
        self.assertEqual(tuple(out[4, 4]), (128, 0, 255, 255))


@unittest.skipIf(bpy is None, "needs the bpy module")
class AddonExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "tools", "converters"))
        import compositor_to_hyprshade as addon
        cls.addon = addon

    def group(self):
        g = bpy.data.node_groups.new("Exported", "CompositorNodeTree")
        it = g.interface
        it.new_socket("Image", in_out="INPUT", socket_type="NodeSocketColor")
        s = it.new_socket("Strength", in_out="INPUT", socket_type="NodeSocketFloat")
        s.default_value, s.min_value, s.max_value = 0.5, 0.0, 2.0
        s = it.new_socket("Steps", in_out="INPUT", socket_type="NodeSocketInt")
        s.default_value, s.min_value, s.max_value = 3, 1, 9
        s = it.new_socket("Flip", in_out="INPUT", socket_type="NodeSocketBool")
        s = it.new_socket("Tint", in_out="INPUT", socket_type="NodeSocketColor")
        s.default_value = (0.8, 0.2, 0.1, 1.0)
        s = it.new_socket("Offset", in_out="INPUT", socket_type="NodeSocketVector")
        s.default_value = (0.1, 0.2, 0.3)
        it.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        gi, go = g.nodes.new("NodeGroupInput"), g.nodes.new("NodeGroupOutput")
        exp = g.nodes.new("CompositorNodeExposure")
        g.links.new(gi.outputs[0], exp.inputs[0])
        g.links.new(gi.outputs["Strength"], exp.inputs[1])
        g.links.new(exp.outputs[0], go.inputs[0])
        return g

    def test_kiasecut_export_compiles_and_has_params(self):
        eng = engine()
        code, _ = self.addon.convert_tree(self.group(), {"linearize": False}, "KIASECUT")
        d = fx.parse(code, "x")
        self.assertIsNone(d.error)
        self.assertEqual({p.name: p.type for p in d.params},
                         {"IN_Strength": "float", "IN_Steps_i": "int", "IN_Flip_b": "bool", "IN_Tint_c": "color",
                          "IN_Offset": "vec3"})
        strength = next(p for p in d.params if p.name == "IN_Strength")
        self.assertEqual((strength.default, strength.lo, strength.hi), (0.5, 0.0, 2.0))
        rgba = np.full((6, 6, 4), (100, 50, 20, 255), np.uint8)
        vals = {p.name: fx.uniform_value(p, 1.0 if p.name == "IN_Strength" else None, 0)
                for p in d.params}
        out = eng.run(d, vals, rgba)
        self.assertEqual(tuple(out[3, 3]), (200, 100, 40, 255))        # exposure +1 stop

    def test_every_format_still_works(self):
        g = self.group()
        for fmt in ("HYPRSHADE", "HLSL", "SHADERGLASS", "KIASECUT"):
            code, _ = self.addon.convert_tree(g, None, fmt)
            self.assertTrue(code.strip())


if __name__ == "__main__":
    unittest.main()
