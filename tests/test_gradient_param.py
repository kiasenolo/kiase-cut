"""The `gradient` filter parameter (colour stops, the gradient editor in the effect panel) and the
[Blender] Color Ramp filter built on it."""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kiasecut import fx  # noqa: E402


def engine():
    try:
        return fx.Engine()
    except fx.FilterError as exc:
        raise unittest.SkipTest(str(exc))


class GradientParamTest(unittest.TestCase):
    def test_parse_and_value(self):
        d = fx.parse("// @filter G\n// @param g gradient 0.5:#ff0000,0:#0000ff80 \"G\"\nvec4 effect(vec2 uv) { return src(uv); }\n", "t")
        self.assertIsNone(d.error)
        p = d.params[0]
        self.assertEqual([s[0] for s in p.default], [0.0, 0.5])          # (in order)
        pos, col, n = fx.uniform_value(p, None, 0)
        self.assertEqual((len(pos), len(col), n), (fx.GRADIENT_N, fx.GRADIENT_N * 4, 2))
        self.assertAlmostEqual(col[3], 128 / 255, places=3)
        self.assertIn("uniform vec4 g_c[32];", fx.shader_source(d))

    def test_bad_default(self):
        self.assertIn("gradient", fx.parse("// @filter G\n// @param g gradient 0:#ff0000\nvec4 effect(vec2 uv) { return src(uv); }\n", "t").error)

    def test_color_ramp_filter(self):
        d = fx.get("builtin:blender_color_ramp")
        self.assertIsNone(d.error)
        img = np.zeros((1, 2, 4), np.uint8)
        img[0, 0] = (0, 0, 0, 255)
        img[0, 1] = (255, 255, 255, 255)
        ramp = [[0.0, [1.0, 0.0, 0.0, 1.0]], [1.0, [0.0, 0.0, 1.0, 1.0]]]
        vals = {p.name: fx.uniform_value(p, ramp if p.name == "ramp" else None, 0) for p in d.params}
        out = engine().run(d, vals, img)
        self.assertEqual(tuple(out[0, 0]), (255, 0, 0, 255))
        self.assertEqual(tuple(out[0, 1]), (0, 0, 255, 255))

    def test_panel_shows_the_editor_and_keeps_edits(self):
        from PySide6.QtWidgets import QApplication
        from kiasecut import edit
        from kiasecut.ui.effects_panel import EffectsPanel
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from test_edit import proj
        APP = QApplication.instance() or QApplication([])
        p = proj()
        e = edit.put_effect(p, "c1", "builtin:blender_color_ramp")
        panel = EffectsPanel()
        c = edit.find(p, "c1")[1]
        panel.show_clips([c], 0, 30)
        ed = panel.widgets[("fx:" + e["id"], "ramp")]
        self.assertEqual(len(ed.stops), 2)
        got = []
        panel.paramEdited.connect(lambda ids, g, k, v: got.append((k, v)))
        ed.bar.sel = 0
        ed.bar.stops[0][1] = [1.0, 0.0, 0.0, 1.0]
        ed.bar.changed.emit(ed.bar.stops)
        panel._flush()
        self.assertEqual(got[-1][0], "ramp")
        e["params"]["ramp"] = got[-1][1]                      # (what the edit stores)
        c = edit.find(p, "c1")[1]
        panel.show_clips([c], 0, 30)
        self.assertEqual(ed.stops[0][1], [1.0, 0.0, 0.0, 1.0])


if __name__ == "__main__":
    unittest.main()
