"""Expressions on a clip's numbers: they replace the number in what is drawn, in both renderers."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import assets, components, edit, project, propexpr, render, renderexport  # noqa: E402
from test_edit import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


class PropExprTests(unittest.TestCase):
    def setUp(self):
        p = proj()
        p["tracks"][0]["clips"] = p["tracks"][0]["clips"][:1]
        a = assets.make(assets.get("shape.rect"), "#ff0000", "#000000", 192, 108)
        a.update(w=40, h=40)
        edit.replace_media(p, "c1", assets.item(a, "/nowhere.svg"), a)
        self.p = p
        self.c = edit.find(p, "c1")[1]

    def test_the_number_follows_the_expression(self):
        edit.set_prop_expr(self.p, "c1", "transform.x", "value + time")
        got = propexpr.at(self.c, 500_000)["transform"]["x"]
        self.assertAlmostEqual(got, 0.5)
        self.assertEqual(self.c["transform"].get("x", 0.0), 0.0)             # (the clip itself is not touched)

    def test_value_is_the_keyframed_number_in_the_shown_units(self):
        edit.set_prop_expr(self.p, "c1", "transform.opacity", "value / 2")
        self.assertAlmostEqual(propexpr.at(self.c, 0)["transform"]["opacity"], 0.5)      # (100 % / 2 = 50 %)

    def test_cleared_and_checked(self):
        edit.set_prop_expr(self.p, "c1", "transform.x", "time")
        edit.set_prop_expr(self.p, "c1", "transform.x", "")
        self.assertNotIn("expr", self.c)
        with self.assertRaises(edit.EditError):
            edit.set_prop_expr(self.p, "c1", "transform.x", "time +")
        with self.assertRaises(edit.EditError):
            edit.set_prop_expr(self.p, "c1", "text.size", "1")                 # (no text here)

    def test_broken_one_leaves_the_number(self):
        edit.set_prop_expr(self.p, "c1", "transform.x", "nothing_here")
        self.assertEqual(propexpr.at(self.c, 0).get("transform", {}).get("x", 0.0), 0.0)

    def test_names_come_from_the_renderer(self):
        edit.set_prop_expr(self.p, "c1", "transform.x", "gain * 2")
        self.assertAlmostEqual(propexpr.at(self.c, 0, {"gain": 0.25})["transform"]["x"], 0.5)

    def test_drawn_where_the_expression_says(self):
        edit.set_prop_expr(self.p, "c1", "transform.x", "time < 1 ? -0.5 : 0.5")
        view = dict(self.p)
        im = render.Renderer().render(view, 0, 192, 108)
        self.assertEqual(im.pixelColor(48, 54).red(), 255)                    # (left of the middle)
        self.assertEqual(im.pixelColor(144, 54).red(), 0)
        im = render.Renderer().render(view, int(1.5 * view["fps"]), 192, 108)
        self.assertEqual(im.pixelColor(144, 54).red(), 255)

    def test_the_gpu_renderer_does_the_same(self):
        from kiasecut import glrender
        try:
            gl = glrender.GLRenderer()
        except Exception:
            self.skipTest("no OpenGL 3.3 here")
        edit.set_prop_expr(self.p, "c1", "transform.x", "time < 1 ? -0.5 : 0.5")
        im = gl.render(dict(self.p), 0, 192, 108)
        self.assertEqual(im.pixelColor(48, 54).red(), 255)
        self.assertEqual(im.pixelColor(144, 54).red(), 0)

    def test_inspector_marks_the_number(self):
        from kiasecut.ui.inspector import Inspector
        edit.set_prop_expr(self.p, "c1", "transform.x", "time * 2")
        ins = Inspector()
        asked = []
        ins.exprRequested.connect(lambda ids, prop: asked.append((ids, prop)))
        ins.show_clips([self.c], 0, 60)
        self.assertIn("time * 2", ins.widgets[("transform", "x")].toolTip())
        self.assertEqual(ins.widgets[("transform", "y")].toolTip(), "")
        self.assertEqual(ins.expr_texts, {"transform.x": "time * 2"})

    def test_needs_the_programs_renderer(self):
        self.assertFalse(renderexport.needs_renderer(self.p))
        edit.set_prop_expr(self.p, "c1", "transform.x", "time")
        self.assertTrue(renderexport.needs_renderer(self.p))


if __name__ == "__main__":
    unittest.main()
