"""vec3 and menu filter parameters, and (when the `bpy` module is installed, e.g. run inside Blender) filters
exported from Blender with tools/converters/compositor_to_hyprshade.py in the KiaseCut format."""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kiasecut import fx  # noqa: E402

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


MENU = """// @param mode menu Red "Keep|Red|Blue" "Mode"
vec4 effect(vec2 uv) {
    vec4 c = src(uv);
    if (mode == 1) return vec4(1.0, 0.0, 0.0, 1.0);
    if (mode == 2) return vec4(0.0, 0.0, 1.0, 1.0);
    return c;
}
"""


class MenuParamTest(unittest.TestCase):
    def test_parse(self):
        d = fx.parse(MENU, "t")
        self.assertIsNone(d.error)
        p = d.params[0]
        self.assertEqual((p.type, p.default, p.items, p.label), ("menu", "Red", ["Keep", "Red", "Blue"], "Mode"))
        self.assertIn("uniform int mode;", fx.shader_source(d))
        self.assertEqual(fx.parse(MENU.replace("menu Red", "menu 2"), "t").params[0].default, "Blue")

    def test_bad_menus(self):
        for bad in ("menu Green", "menu 5", 'menu Red "" "Mode"', 'menu Red "Red|Red" "Mode"'):
            self.assertIsNotNone(fx.parse(MENU.replace('menu Red "Keep|Red|Blue" "Mode"', bad), "t").error, bad)
        self.assertIsNotNone(fx.parse("// @param mode menu Red\nvec4 effect(vec2 uv) { return src(uv); }", "t").error)

    def test_uniform_value(self):
        p = fx.parse(MENU, "t").params[0]
        self.assertEqual(fx.uniform_value(p, None, 0), 1)
        self.assertEqual(fx.uniform_value(p, "Blue", 0), 2)
        self.assertEqual(fx.uniform_value(p, "gone", 0), 1)              # a choice no longer there: the default
        anim = {"keys": [[0, "Keep", 0, 0, 0, 0], [1_000_000, "Blue", 0, 0, 0, 0]]}
        self.assertEqual([fx.uniform_value(p, anim, t) for t in (0, 999_999, 1_000_000)], [0, 0, 2])

    def test_render(self):
        eng = engine()
        d = fx.parse(MENU, "t")
        rgba = np.full((4, 4, 4), (10, 20, 30, 255), np.uint8)
        self.assertEqual([tuple(eng.run(d, {"mode": i}, rgba)[2, 2]) for i in range(3)],
                         [(10, 20, 30, 255), (255, 0, 0, 255), (0, 0, 255, 255)])


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
        for g in (self.group(), self.menu_group()):
            for fmt in ("HYPRSHADE", "HLSL", "SHADERGLASS", "KIASECUT"):
                code, _ = self.addon.convert_tree(g, None, fmt)
                self.assertTrue(code.strip())

    def menu_group(self, nested=False):
        """Menu input 'Mode' picking a Menu Switch: Keep (the picture) / Red / Brighter (exposure +1);
        nested: the Menu Switch sits in a group inside, picked through that group's own menu input."""
        def switch_tree(name):
            g = bpy.data.node_groups.new(name, "CompositorNodeTree")
            it = g.interface
            it.new_socket("Image", in_out="INPUT", socket_type="NodeSocketColor")
            it.new_socket("Mode", in_out="INPUT", socket_type="NodeSocketMenu")
            it.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
            return g, it, g.nodes.new("NodeGroupInput"), g.nodes.new("NodeGroupOutput")

        inner, _, gi, go = switch_tree("MenuInner")
        ms = inner.nodes.new("GeometryNodeMenuSwitch")
        ms.data_type = "RGBA"
        ms.enum_items[0].name, ms.enum_items[1].name = "Keep", "Red"
        ms.enum_items.new("Brighter")
        exp = inner.nodes.new("CompositorNodeExposure")
        exp.inputs[1].default_value = 1.0
        inner.links.new(gi.outputs[0], exp.inputs[0])
        inner.links.new(gi.outputs[0], ms.inputs[1])
        ms.inputs[2].default_value = (1.0, 0.0, 0.0, 1.0)
        inner.links.new(exp.outputs[0], ms.inputs[3])
        inner.links.new(gi.outputs["Mode"], ms.inputs[0])
        inner.links.new(ms.outputs[0], go.inputs[0])
        if not nested:
            inner.interface.items_tree["Mode"].default_value = "Red"
            return inner
        outer, it, gi, go = switch_tree("MenuOuter")
        node = outer.nodes.new("CompositorNodeGroup")
        node.node_tree = inner
        outer.links.new(gi.outputs[0], node.inputs[0])
        outer.links.new(gi.outputs["Mode"], node.inputs["Mode"])
        outer.links.new(node.outputs[0], go.inputs[0])
        it.items_tree["Mode"].default_value = "Red"
        return outer

    def test_menu_input_becomes_a_menu_parameter(self):
        for nested in (False, True):
            code, _ = self.addon.convert_tree(self.menu_group(nested), {"linearize": False}, "KIASECUT")
            d = fx.parse(code, "x")
            self.assertIsNone(d.error)
            p = next(p for p in d.params if p.name == "IN_Mode_m")
            self.assertEqual((p.type, p.items, p.default), ("menu", ["Keep", "Red", "Brighter"], "Red"))
            eng = engine()
            rgba = np.full((6, 6, 4), (100, 50, 20, 255), np.uint8)
            got = [tuple(eng.run(d, {"IN_Mode_m": fx.uniform_value(p, choice, 0)}, rgba)[3, 3])
                   for choice in p.items]
            self.assertEqual(got, [(100, 50, 20, 255), (255, 0, 0, 255), (200, 100, 40, 255)])

    def test_menu_fixed_in_other_formats(self):
        code, _ = self.addon.convert_tree(self.menu_group(), None, "HYPRSHADE")
        self.assertIn("const float IN_Mode = 1.000000;", code)

    def test_menu_into_a_nodes_own_menu_is_fixed_with_a_warning(self):
        g = bpy.data.node_groups.new("BlurKind", "CompositorNodeTree")   # (Blender does not let one menu
        it = g.interface                                                  # input pick both: links conflict)
        it.new_socket("Image", in_out="INPUT", socket_type="NodeSocketColor")
        it.new_socket("Kind", in_out="INPUT", socket_type="NodeSocketMenu")
        it.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        gi, go = g.nodes.new("NodeGroupInput"), g.nodes.new("NodeGroupOutput")
        blur = g.nodes.new("CompositorNodeBlur")
        kind = next((s for s in blur.inputs if s.type == "MENU"), None)
        if kind is None:
            self.skipTest("Blur has no menu socket in this Blender")
        g.links.new(gi.outputs["Kind"], kind)
        g.links.new(gi.outputs[0], blur.inputs[0])
        g.links.new(blur.outputs[0], go.inputs[0])
        code, warns = self.addon.convert_tree(g, None, "KIASECUT")
        self.assertTrue(any("only a Menu Switch follows" in w for w in warns), warns)
        self.assertEqual(fx.parse(code, "x").params, [])                 # no parameter for it


if __name__ == "__main__":
    unittest.main()
