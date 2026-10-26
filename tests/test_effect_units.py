"""A filter's pixel lengths are canvas px: the same effect looks the same in a small preview,
full screen and the export (the filter is told the canvas size, and the picture it works on
is scaled by preview / canvas)."""
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

from kiasecut import fx, glrender, render  # noqa: E402
from test_compound_mask import HAVE_GL  # noqa: E402
from test_edit import S, clip  # noqa: E402

APP = QApplication.instance() or QApplication([])
SHIFT = 120                   # canvas px the filter moves the picture to the right

# written as a filter made outside the program would be: a length in px over resolution
SHIFT_FILTER = """// @filter shift
// @param amount float %d 0 1000 "px"
vec4 effect(vec2 uv) { return src(uv - vec2(amount, 0.0) / resolution); }
""" % SHIFT


def edge(img):
    """x (0..1 of the width) where the middle row turns from black to red."""
    y = img.height() // 2
    for x in range(img.width()):
        if QColor(img.pixel(x, y)).red() > 128:
            return x / img.width()
    return None


class EffectUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.shift = os.path.join(cls.dir, "shift.glsl")
        with open(cls.shift, "w", encoding="utf-8") as f:
            f.write(SHIFT_FILTER)
        im = QImage(160, 90, QImage.Format_ARGB32_Premultiplied)
        im.fill(Qt.transparent)
        p = QPainter(im)
        p.fillRect(QRectF(80, 0, 80, 90), QColor("#ff0000"))       # right half red
        p.end()
        cls.half = os.path.join(cls.dir, "half.png")
        im.save(cls.half)
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

    def pic(self, cid, effects=()):
        c = clip(cid, 0, 2 * S)
        c["media"] = {"path": self.half, "width": 160, "height": 90}
        c["effects"] = [{"id": f"e{i}", "filter": ref, "params": {}} for i, ref in enumerate(effects)]
        return c

    def view(self, cw, ch, top):
        return {"width": cw, "height": ch, "fps": 30, "duration_us": 2 * S, "compounds": {},
                "tracks": [{"id": "t0", "kind": "video", "name": "v", "clips": [top]}]}

    def renderers(self):
        return [render.Renderer()] + ([glrender.GLRenderer()] if HAVE_GL else [])

    def test_same_at_any_preview_size(self):
        for cw, ch in ((1920, 1080), (3840, 2160), (1080, 1920)):
            view = self.view(cw, ch, self.pic("c", [self.shift]))
            want = 0.5 + SHIFT / cw
            for r in self.renderers():
                for w in (cw // 8, cw // 4, cw // 2):
                    with self.subTest(canvas=(cw, ch), renderer=type(r).__name__, width=w):
                        img = r.render(view, 0, w, round(w * ch / cw))
                        self.assertAlmostEqual(edge(img), want, delta=1.5 / w)

    def test_filter_clip(self):
        f = clip("f", 0, 2 * S, type="filter")
        f["effects"] = [{"id": "e0", "filter": self.shift, "params": {}}]
        view = self.view(1920, 1080, self.pic("c"))
        view["tracks"].append({"id": "t1", "kind": "video", "name": "v", "clips": [f]})
        for r in self.renderers():
            for w in (240, 960):
                with self.subTest(renderer=type(r).__name__, width=w):
                    self.assertAlmostEqual(edge(r.render(view, 0, w, w * 9 // 16)), 0.5 + SHIFT / 1920, delta=1.5 / w)

    def test_inside_compound(self):
        """In a compound the lengths are the compound's canvas px (they shrink with it)."""
        comp = {"name": "k", "width": 1920, "height": 1080, "duration_us": 2 * S,
                "tracks": [{"id": "i0", "kind": "video", "name": "v", "clips": [self.pic("m", [self.shift])]}]}
        top = clip("k", 0, 2 * S, type="compound", compound_id="k1", compound=comp)
        top["transform"]["scale"] = 0.5
        view = self.view(1920, 1080, top)
        view["compounds"] = {"k1": comp}
        for r in self.renderers():
            for w in (240, 960):
                with self.subTest(renderer=type(r).__name__, width=w):
                    self.assertAlmostEqual(edge(r.render(view, 0, w, w * 9 // 16)), 0.5 + SHIFT / 1920 / 2,
                                           delta=1.5 / w)

    def test_builtin_lengths_are_canvas_px(self):
        """RGB 色差 by 100 px on a 4K canvas: red moves left 100 of its 3840 px, whatever the preview."""
        e = {"id": "e0", "filter": "builtin:rgb_shift", "params": {"amount": 100.0, "angle": 0.0}}
        c = self.pic("c")
        c["effects"] = [e]
        view = self.view(3840, 2160, c)
        for r in self.renderers():
            for w in (480, 1920):
                with self.subTest(renderer=type(r).__name__, width=w):
                    img = r.render(view, 0, w, w * 9 // 16)
                    y = img.height() // 2
                    xs = [x for x in range(img.width()) if QColor(img.pixel(x, y)).red() > 128]
                    self.assertAlmostEqual(xs[0] / w, 0.5 - 100 / 3840, delta=1.5 / w)


if __name__ == "__main__":
    unittest.main()
