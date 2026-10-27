"""混合程度: an effect's result mixed with the picture it was given (0 - 100 %, keyframed like
any value), the same in both renderers; edited through the "fxmix:<effect id>" group."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, fx, glrender, render  # noqa: E402
from kiasecut.ui.effects_panel import EffectsPanel  # noqa: E402
from kiasecut.ui.main_window import same_group  # noqa: E402
from test_compound_mask import HAVE_GL  # noqa: E402
from test_edit import S, clip, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
WHITE = """// @filter white
vec4 effect(vec2 uv) { return vec4(1.0); }
"""


class MixRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.white = os.path.join(cls.dir, "white.glsl")
        with open(cls.white, "w", encoding="utf-8") as f:
            f.write(WHITE)
        im = QImage(160, 90, QImage.Format_ARGB32_Premultiplied)
        im.fill(QColor("#ff0000"))
        cls.red = os.path.join(cls.dir, "red.png")
        im.save(cls.red)
        try:
            fx.Engine()
            cls.fx = True
        except Exception:
            cls.fx = False

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        if not self.fx:
            self.skipTest("no OpenGL for filters")

    def view(self, mix):
        c = clip("c", 0, 2 * S)
        c["media"] = {"path": self.red, "width": 160, "height": 90}
        c["effects"] = [{"id": "e0", "filter": self.white, "params": {}}]
        if mix is not None:
            c["effects"][0]["mix"] = mix
        return {"width": 160, "height": 90, "fps": 30, "duration_us": 2 * S, "compounds": {},
                "tracks": [{"id": "t0", "kind": "video", "name": "v", "clips": [c]}]}

    def renderers(self):
        return [render.Renderer()] + ([glrender.GLRenderer()] if HAVE_GL else [])

    def green(self, r, view, frame=0):
        img = r.render(view, frame, 160, 90)
        return QColor(img.pixel(80, 45)).green()

    def test_amounts(self):
        for r in self.renderers():
            with self.subTest(renderer=type(r).__name__):
                self.assertGreater(self.green(r, self.view(None)), 250)       # (none: all of it)
                self.assertLess(self.green(r, self.view(0.0)), 5)              # the picture as it was
                self.assertAlmostEqual(self.green(r, self.view(0.5)), 128, delta=3)
                self.assertGreater(self.green(r, self.view(3.0)), 250)       # (held to 0 - 1)

    def test_keyframed(self):
        mix = {"keys": [[0, 0.0, 0, 0, 0, 0], [2 * S, 1.0, 0, 0, 0, 0]]}
        for r in self.renderers():
            with self.subTest(renderer=type(r).__name__):
                self.assertAlmostEqual(self.green(r, self.view(mix), 30), 128, delta=4)     # 1 s: half


class MixEditTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.e = edit.put_effect(self.p, "c1", "builtin:vignette")
        self.g = "fxmix:" + self.e["id"]

    def test_set_and_key(self):
        edit.set_param(self.p, "c1", self.g, "mix", 0.25, 0)
        self.assertEqual(self.e["mix"], 0.25)
        self.assertNotIn("mix", self.e["params"])                  # (never mistaken for a filter's own)
        edit.toggle_key(self.p, "c1", self.g, "mix", S)
        self.assertEqual(self.e["mix"]["keys"][0][:2], [S, 0.25])
        self.assertIn(S, edit.key_times(edit.find(self.p, "c1")[1]))
        self.assertTrue(edit.has_param(edit.find(self.p, "c1")[1], self.g, "mix"))
        self.assertFalse(edit.has_param(edit.find(self.p, "c1")[1], self.g, "strength"))

    def test_new_key_starts_full(self):
        edit.toggle_key(self.p, "c1", self.g, "mix", 0)
        self.assertEqual(self.e["mix"]["keys"][0][1], 1.0)

    def test_same_group(self):
        other = edit.put_effect(self.p, "c2", "builtin:vignette")
        c1, c2 = edit.find(self.p, "c1")[1], edit.find(self.p, "c2")[1]
        self.assertEqual(same_group(c1, c2, self.g), "fxmix:" + other["id"])

    def test_swap_keeps_mix(self):
        edit.set_param(self.p, "c1", self.g, "mix", 0.4, 0)
        edit.swap_filter(self.p, "c1", self.e["id"], "builtin:grayscale")
        self.assertEqual(self.e["mix"], 0.4)


class MixPanelTests(unittest.TestCase):
    def test_row(self):
        p = proj()
        e = edit.put_effect(p, "c1", "builtin:vignette")
        e["mix"] = 0.3
        panel = EffectsPanel()
        panel.show_clips([edit.find(p, "c1")[1]], 0, 30)
        s = panel.widgets[("fxmix:" + e["id"], "mix")]
        self.assertEqual(s.value(), 30)
        got = []
        panel.paramEdited.connect(lambda *a: got.append(a))
        s.setValue(75)
        panel._flush()
        self.assertEqual(got, [(["c1"], "fxmix:" + e["id"], "mix", 0.75)])
        s.setValue(500)                                         # (typed past 100 %: held there)
        self.assertEqual(s.value(), 100)


if __name__ == "__main__":
    unittest.main()
