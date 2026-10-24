"""The GPU compositor (glrender.py) draws what the CPU renderer (render.py) draws.

Every scene is rendered by both and compared: on average within a couple of levels, and
with only a sliver of pixels (anti-aliased edges, feathers) further apart. Skipped when this
computer has no OpenGL 3.3.
"""
import copy
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QRadialGradient  # noqa: E402

from kiasecut import fx, glrender, project, render  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])
S = 1_000_000
W, H = 320, 180

try:
    glrender.GL().ctx.release()
    HAVE_GL = True
except Exception:                                    # no OpenGL 3.3 / moderngl here
    HAVE_GL = False


def pixels(img):
    im = img.convertToFormat(QImage.Format_RGBA8888)
    return np.frombuffer(bytes(im.constBits()), np.uint8).reshape(im.height(), im.width(), 4)[..., :3].astype(int)


def tf(**kw):
    t = {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}
    t.update(kw)
    return t


@unittest.skipUnless(HAVE_GL, "needs OpenGL 3.3")
class GpuMatchesCpu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        grad = QImage(400, 225, QImage.Format_ARGB32_Premultiplied)
        p = QPainter(grad)
        g = QLinearGradient(0, 0, 400, 225)
        g.setColorAt(0, QColor("#1d4fd8"))
        g.setColorAt(0.5, QColor("#f5f5f5"))
        g.setColorAt(1, QColor("#e8590c"))
        p.fillRect(grad.rect(), g)
        p.setBrush(QColor("#2b8a3e"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(120, 110), 60, 60)
        p.end()
        cls.grad = os.path.join(cls.dir, "grad.png")
        grad.save(cls.grad)
        spot = QImage(200, 200, QImage.Format_ARGB32_Premultiplied)    # see-through edges
        spot.fill(Qt.transparent)
        p = QPainter(spot)
        r = QRadialGradient(QPointF(100, 100), 100)
        r.setColorAt(0, QColor(255, 220, 40, 255))
        r.setColorAt(1, QColor(255, 220, 40, 0))
        p.fillRect(spot.rect(), r)
        p.end()
        cls.spot = os.path.join(cls.dir, "spot.png")
        spot.save(cls.spot)
        cls.svg = os.path.join(cls.dir, "s.svg")
        with open(cls.svg, "w", encoding="utf-8") as fh:
            fh.write('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect x="10" y="10" '
                     'width="80" height="80" rx="20" fill="#7048e8"/></svg>')
        cls.cpu, cls.gpu = render.Renderer(), glrender.GLRenderer()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def pic(self, cid, path, w, h, **kw):
        c = {"id": cid, "type": "image", "name": cid, "start_us": 0, "duration_us": 2 * S, "source_start_us": 0,
             "media": {"path": path, "width": w, "height": h}, "transform": tf()}
        c.update(kw)
        return c

    def bg(self, **kw):
        return self.pic("bg", self.grad, 400, 225, **kw)

    def top(self, **kw):
        return self.pic("top", self.spot, 200, 200, **kw)

    def view(self, *layers, t=0):
        tracks = [{"id": f"t{i}", "kind": "video", "name": f"v{i}", "clips": list(cl)} for i, cl in enumerate(layers)]
        return {"width": 640, "height": 360, "fps": 30, "duration_us": 2 * S, "tracks": tracks}

    def check(self, name, view, frame=0, mean_max=2.0, far_max=0.01):
        a = pixels(self.cpu.render(copy.deepcopy(view), frame, W, H))
        b = pixels(self.gpu.render(copy.deepcopy(view), frame, W, H))
        d = np.abs(a - b).max(axis=2)
        mean, far = float(np.abs(a - b).mean()), float((d > 48).mean())
        self.assertEqual(self.cpu.errors + self.gpu.errors, [], name)
        self.assertLessEqual(mean, mean_max, f"{name}: mean difference {mean:.2f}")
        self.assertLessEqual(far, far_max, f"{name}: {far:.2%} of pixels differ a lot")
        return mean, far

    def test_pictures_and_transforms(self):
        self.check("plain", self.view([self.bg()]))
        self.check("moved", self.view([self.bg(transform=tf(x=0.3, y=-0.2, scale=0.6, rotation=33, opacity=0.7))]))
        self.check("flipped", self.view([self.bg(transform=dict(tf(scale=0.8, rotation=-20), flip_h=True))]))
        self.check("stretched", self.view([self.bg(transform=dict(tf(scale=0.5), scale_y=1.2))]))
        self.check("see-through", self.view([self.bg()], [self.top(transform=tf(scale=0.7, x=-0.3, opacity=0.8))]))
        self.check("svg", self.view([self.bg()], [self.pic("s", self.svg, 100, 100, transform=tf(scale=0.5))]))

    def test_blend_modes(self):
        for mode in glrender.BLEND_INDEX:
            self.check(f"blend {mode}", self.view([self.bg()], [self.top(blend=mode, transform=tf(scale=0.9))]))

    def test_masks(self):
        for kind in ("line", "mirror", "circle", "rectangle"):
            for feather, invert, rot in ((0.0, False, 0.0), (0.3, True, 25.0)):
                mask = {"kind": kind, "invert": invert, "cx": 0.2, "cy": -0.1, "w": 0.6, "h": 0.5,
                        "rotation": rot, "feather": feather}
                self.check(f"mask {kind} {feather} {invert}",
                           self.view([self.top(transform=tf(scale=1.2))], [self.bg(mask=mask, transform=tf(rotation=10))]))

    def test_text(self):
        if not project.DEFAULT_FONT:
            self.skipTest("no default font")
        text = {"id": "tx", "type": "text", "name": "tx", "start_us": 0, "duration_us": 2 * S, "source_start_us": 0,
                "text": {"content": "KiaseCut 剪輯", "font_path": project.DEFAULT_FONT, "size": 12.0,
                         "color": [1.0, 0.9, 0.2], "letter_spacing": 0.0, "line_spacing": 0.0, "italic_deg": 0},
                "transform": tf(y=0.3, rotation=-8)}
        self.check("text", self.view([self.bg()], [text]), mean_max=2.5, far_max=0.02)

    def compound(self, static=False):
        comp = {"name": "k", "width": 640, "height": 360, "duration_us": 2 * S,
                "tracks": [{"id": "i0", "kind": "video", "name": "v", "clips": [self.bg(transform=tf(scale=0.7))]},
                           {"id": "i1", "kind": "video", "name": "v", "clips": [self.top(transform=tf(x=0.4))]}]}
        if static:
            comp.update(static=True, still_us=0)
        return {"id": "k", "type": "compound", "name": "k", "start_us": 0, "duration_us": 2 * S, "source_start_us": 0,
                "compound_id": "k1", "compound": comp, "transform": tf(scale=1.4, rotation=12, x=0.1, opacity=0.9)}

    def test_compounds(self):
        self.check("compound", self.view([self.top()], [self.compound()]))
        self.check("static", self.view([self.top()], [self.compound(static=True)]))

    def test_effects(self):
        e = fx.new_effect("builtin:invert", "e1")
        e["mask"] = {"kind": "circle", "invert": False, "cx": 0.0, "cy": 0.0, "w": 0.5, "h": 0.8, "rotation": 0.0,
                     "feather": 0.2}
        self.check("effect with mask", self.view([self.top()], [self.bg(effects=[e], transform=tf(scale=0.8, rotation=15),
                                                                         blend="screen")]))
        blur = fx.new_effect("builtin:blur", "e2")
        self.check("two effects", self.view([self.bg(effects=[blur, fx.new_effect("builtin:invert", "e3")],
                                                     transform=tf(scale=0.7, opacity=0.6))]))
        clip = {"id": "f", "type": "filter", "name": "f", "start_us": 0, "duration_us": 2 * S, "source_start_us": 0,
                "transform": tf(opacity=0.5, rotation=20), "effects": [fx.new_effect("builtin:invert", "e4")],
                "mask": {"kind": "rectangle", "invert": False, "cx": 0.1, "cy": 0.0, "w": 0.5, "h": 0.5,
                         "rotation": 0.0, "feather": 0.1}}
        self.check("filter clip", self.view([self.bg()], [clip]))


@unittest.skipUnless(HAVE_GL, "needs OpenGL 3.3")
class BuiltinFilters(unittest.TestCase):
    def test_every_builtin_compiles_and_runs(self):
        eng = fx.Engine()
        rgba = np.zeros((36, 64, 4), np.uint8)
        rgba[..., 1], rgba[..., 3] = 200, 255
        for ref in fx.builtin_refs():
            self.assertIsNone(fx.check(ref), ref)
            d = fx.get(ref)
            out = eng.run(d, {p.name: fx.uniform_value(p, None, 0) for p in d.params}, rgba, 0.5, 0.5, 15)
            self.assertEqual(out.shape, rgba.shape, ref)
            self.assertTrue((out[..., :3] <= out[..., 3:4]).all(), f"{ref}: not premultiplied")


if __name__ == "__main__":
    unittest.main()
