"""Keyframed choices (font, mask shape, invert, blend mode) and blend modes."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kiasecut import curves, edit, project, renderexport  # noqa: E402
from test_edit import S, clip, proj  # noqa: E402


class HoldTests(unittest.TestCase):
    def test_choices_hold_until_the_next_key(self):
        p = {"keys": [[0, "a.ttf", 0, 0, 0, 0], [S, "b.ttf", 0, 0, 0, 0], [2 * S, "c.ttf", 0, 0, 0, 0]]}
        self.assertEqual(curves.value(p, -5), "a.ttf")
        self.assertEqual(curves.value(p, S - 1), "a.ttf")
        self.assertEqual(curves.value(p, S), "b.ttf")
        self.assertEqual(curves.value(p, 1.5 * S), "b.ttf")
        self.assertEqual(curves.value(p, 3 * S), "c.ttf")
        on = {"keys": [[0, False, 0, 0, 0, 0], [S, True, 0, 0, 0, 0]]}
        self.assertIs(curves.value(on, S / 2), False)
        self.assertIs(curves.value(on, S), True)

    def test_numbers_still_blend(self):
        p = {"keys": [[0, 0.0, 0, 0, 0, 0], [S, 1.0, 0, 0, 0, 0]]}
        self.assertAlmostEqual(curves.value(p, S / 2), 0.5, places=6)


class ChoiceEditTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.text = edit.add_text(self.p, 0)

    def test_font_keyframes(self):
        cid = self.text["id"]
        edit.set_param(self.p, cid, "text", "font_path", "a.ttf", 0)
        edit.toggle_key(self.p, cid, "text", "font_path", 0)
        edit.set_param(self.p, cid, "text", "font_path", "b.ttf", S)          # a second key at 1 s
        f = self.text["text"]["font_path"]
        self.assertEqual([k[1] for k in f["keys"]], ["a.ttf", "b.ttf"])
        self.assertEqual(curves.value(f, S // 2), "a.ttf")
        self.assertEqual(curves.value(f, 2 * S), "b.ttf")
        with self.assertRaises(edit.EditError):                                # choices have no curve
            edit.set_easing(self.p, cid, "text", "font_path", 0, "ease_in")
        self.assertIsNone(edit.easing_at(f, 0))
        self.assertIn(S, edit.key_times(self.text))
        edit.toggle_key(self.p, cid, "text", "font_path", S)
        edit.toggle_key(self.p, cid, "text", "font_path", 0)
        self.assertEqual(self.text["text"]["font_path"], "a.ttf")             # last key removed: its value stays

    def test_blend_mode(self):
        edit.set_param(self.p, "c1", "clip", "blend", "screen")
        c = edit.find(self.p, "c1")[1]
        self.assertEqual(c["blend"], "screen")
        edit.toggle_key(self.p, "c1", "clip", "blend", 0)
        edit.set_param(self.p, "c1", "clip", "blend", "multiply", S)
        self.assertEqual(curves.value(c["blend"], S // 2), "screen")
        self.assertEqual(curves.value(c["blend"], S), "multiply")
        with self.assertRaises(edit.EditError):
            edit.set_param(self.p, "c1", "clip", "blend", "nonsense")
        with self.assertRaises(edit.EditError):                                # sound has no picture
            edit.set_param(self.p, "c3", "clip", "blend", "screen")
        edit.shift_keys(c, S // 2)                                             # trims move them too
        self.assertEqual(c["blend"]["keys"][1][0], S // 2)

    def test_mask_shape_and_invert_keyframes(self):
        edit.set_mask(self.p, "c1", "circle")
        edit.toggle_key(self.p, "c1", "mask", "kind", 0)
        edit.set_mask(self.p, "c1", "rectangle", S)                           # keyframed: a key at 1 s
        m = edit.find(self.p, "c1")[1]["mask"]
        self.assertEqual(curves.value(m["kind"], S // 2), "circle")
        self.assertEqual(curves.value(m["kind"], S), "rectangle")
        edit.toggle_key(self.p, "c1", "mask", "invert", 0)
        edit.set_mask_invert(self.p, "c1", True, S)
        self.assertIs(curves.value(m["invert"], 0), False)
        self.assertIs(curves.value(m["invert"], S), True)
        edit.set_mask_invert(self.p, "c1", False, 0)                          # edits the key at 0
        self.assertEqual([k[1] for k in m["invert"]["keys"]], [False, True])

    def test_effect_bool_param_and_mask_shape(self):
        e = edit.add_effect(self.p, "c1", "builtin:invert")
        edit.set_effect_mask(self.p, "c1", e["id"], "circle")
        edit.toggle_key(self.p, "c1", "fxmask:" + e["id"], "kind", 0)
        edit.set_effect_mask(self.p, "c1", e["id"], "rectangle", S)
        self.assertEqual(curves.value(e["mask"]["kind"], S), "rectangle")
        edit.set_effect_mask_invert(self.p, "c1", e["id"], True, S)
        self.assertIs(e["mask"]["invert"], True)                               # not keyframed: set outright

    def test_effect_menu_param(self):
        path = os.path.join(self.tmp(), "menu.glsl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('// @param mode menu 平滑 "線性|平滑|銳利" "模式"\nvec4 effect(vec2 uv) { return src(uv); }\n')
        e = edit.add_effect(self.p, "c1", path)
        g = "fx:" + e["id"]
        self.assertEqual(e["params"]["mode"], "平滑")
        edit.toggle_key(self.p, "c1", g, "mode", 0)
        edit.set_param(self.p, "c1", g, "mode", "銳利", S)
        self.assertEqual(curves.value(e["params"]["mode"], S - 1), "平滑")    # a choice holds until its key
        self.assertEqual(curves.value(e["params"]["mode"], S), "銳利")
        with self.assertRaises(edit.EditError):
            edit.set_param(self.p, "c1", g, "mode", "模糊", S)

    def tmp(self):
        import shutil
        import tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def test_export_route(self):
        self.assertFalse(renderexport.needs_renderer(self.p))
        edit.set_param(self.p, "c1", "clip", "blend", "screen")
        self.assertTrue(renderexport.needs_renderer(self.p))
        edit.set_param(self.p, "c1", "clip", "blend", "normal")
        self.assertFalse(renderexport.needs_renderer(self.p))
        edit.toggle_key(self.p, self.text["id"], "text", "font_path", 0)
        self.assertFalse(renderexport.needs_renderer(self.p))                 # MLT draws keyframed fonts
        edit.set_mask(self.p, "c1", "circle")
        self.assertFalse(renderexport.needs_renderer(self.p))
        edit.toggle_key(self.p, "c1", "mask", "kind", 0)
        self.assertTrue(renderexport.needs_renderer(self.p))


class BlendRenderTests(unittest.TestCase):
    """Blend modes in the live renderer (the preview and the filter export)."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtGui import QColor, QGuiApplication, QImage
        cls.app = QGuiApplication.instance() or QGuiApplication([])
        cls.dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_choices")
        os.makedirs(cls.dir, exist_ok=True)
        cls.paths = {}
        for name, rgb in (("grey", (128, 128, 128)), ("red", (255, 0, 0))):
            im = QImage(16, 9, QImage.Format_RGB32)
            im.fill(QColor(*rgb))
            cls.paths[name] = os.path.join(cls.dir, name + ".png")
            im.save(cls.paths[name])

    @classmethod
    def tearDownClass(cls):
        for path in cls.paths.values():
            os.remove(path)
        os.rmdir(cls.dir)

    def frame(self, blend, t=0):
        from kiasecut import render
        media = lambda n: {"path": self.paths[n], "width": 16, "height": 9}
        top = clip("b", 0, 2 * S, media=media("red"))
        top["blend"] = blend
        view = {"width": 160, "height": 90, "fps": 30, "duration_us": 2 * S, "tracks": [
            {"id": "t0", "kind": "video", "name": "v1", "clips": [clip("a", 0, 2 * S, media=media("grey"))]},
            {"id": "t1", "kind": "video", "name": "v2", "clips": [top]}]}
        img = render.Renderer().render(view, round(t * 30 / S), 160, 90)
        c = img.pixelColor(80, 45)
        return c.red(), c.green(), c.blue()

    def test_modes(self):
        self.assertEqual(self.frame("normal"), (255, 0, 0))
        r, g, b = self.frame("multiply")
        self.assertTrue(abs(r - 128) <= 1 and g == 0 and b == 0)
        r, g, b = self.frame("screen")
        self.assertTrue(r == 255 and abs(g - 128) <= 1 and abs(b - 128) <= 1)
        keyed = {"keys": [[0, "normal", 0, 0, 0, 0], [S, "multiply", 0, 0, 0, 0]]}
        self.assertEqual(self.frame(keyed, 0), (255, 0, 0))
        self.assertLessEqual(abs(self.frame(keyed, S + S // 10)[0] - 128), 1)


if __name__ == "__main__":
    unittest.main()
