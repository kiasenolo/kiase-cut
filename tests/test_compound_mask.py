"""Compound masks (遮罩 → 複合片段): a compound's alpha or brightness cuts a clip, a live one
plays at clip time, a static one is its still; picking one fits its proportions; the
preview shows it over the clip; a compound corner keeps its proportions; export goes through
the renderer."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, glrender, render, renderexport  # noqa: E402
from kiasecut.ui.preview import Box, MaskGeo, Preview  # noqa: E402
from test_edit import S, clip, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
NONE = Qt.KeyboardModifier.NoModifier
W, H = 64, 36

try:
    glrender.GL().ctx.release()
    HAVE_GL = True
except Exception:
    HAVE_GL = False


def rgb(img, x, y):
    c = img.pixelColor(x, y)
    return c.red(), c.green(), c.blue()


class Scene:
    """A red picture over black, masked by compound k1 (a picture of its own: 'half')."""

    def __init__(self, folder):
        def save(name, paint):
            im = QImage(160, 90, QImage.Format_ARGB32_Premultiplied)
            im.fill(Qt.transparent)
            p = QPainter(im)
            paint(p)
            p.end()
            path = os.path.join(folder, name)
            im.save(path)
            return path

        self.red = save("red.png", lambda p: p.fillRect(QRectF(0, 0, 160, 90), QColor("#ff0000")))
        # left half: opaque white; right half: see-through (alpha) / opaque black (luma)
        self.alpha = save("alpha.png", lambda p: p.fillRect(QRectF(0, 0, 80, 90), QColor("white")))
        self.luma = save("luma.png", lambda p: (p.fillRect(QRectF(0, 0, 160, 90), QColor("black")),
                                                 p.fillRect(QRectF(0, 0, 80, 90), QColor("white"))))
        self.blue = save("blue.png", lambda p: p.fillRect(QRectF(0, 0, 160, 90), QColor("#0000ff")))

    def pic(self, cid, path, start=0, dur=2 * S):
        c = clip(cid, start, dur)
        c["media"] = {"path": path, "width": 160, "height": 90}
        return c

    def view(self, mask=None, inner=None, static=False, **extra):
        top = self.pic("top", self.red)
        if mask is not None:
            top["mask"] = dict({"kind": "compound", "compound_id": "k1", "matte": "alpha", "invert": False,
                                "cx": 0.0, "cy": 0.0, "w": 1.0, "h": 1.0, "rotation": 0.0, "feather": 0.0}, **mask)
        comp = {"name": "half", "width": 1920, "height": 1080, "duration_us": 2 * S,
                "tracks": [{"id": "i0", "kind": "video", "name": "v", "clips": inner or [self.pic("m", self.alpha)]}]}
        if static:
            comp["static"] = True
        v = {"width": 1920, "height": 1080, "fps": 30, "duration_us": 2 * S, "compounds": {"k1": comp},
             "tracks": [{"id": "t0", "kind": "video", "name": "v", "clips": [top]}]}
        v.update(extra)
        return v


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.s = Scene(cls.dir)
        cls.renderers = [render.Renderer()] + ([glrender.GLRenderer()] if HAVE_GL else [])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def frame(self, view, frame=0):
        out = []
        for r in self.renderers:
            img = r.render(view, frame, W, H)
            self.assertEqual(r.errors, [], type(r).__name__)
            out.append(img)
        return out

    def halves(self, view, left, right, frame=0):
        for img in self.frame(view, frame):
            self.assertEqual(rgb(img, 12, 18), left)
            self.assertEqual(rgb(img, 52, 18), right)

    def test_alpha_and_luma(self):
        red, black = (255, 0, 0), (0, 0, 0)
        self.halves(self.s.view({}), red, black)                                   # alpha: the opaque half
        self.halves(self.s.view({"invert": True}), black, red)
        self.halves(self.s.view({"matte": "luma"}, [self.s.pic("m", self.s.luma)]), red, black)
        self.halves(self.s.view({"matte": "alpha"}, [self.s.pic("m", self.s.luma)]), red, red)   # all opaque

    def test_static_and_moved(self):
        self.halves(self.s.view({}, static=True), (255, 0, 0), (0, 0, 0))
        self.halves(self.s.view({"cx": 1.0}), (0, 0, 0), (255, 0, 0))             # moved right by half the clip

    def test_live_compound_plays_at_clip_time(self):
        inner = [self.s.pic("m", self.s.alpha, 0, S), self.s.pic("n", self.s.blue, S, S)]     # all opaque from 1 s
        red = (255, 0, 0)
        self.halves(self.s.view({}, inner), red, (0, 0, 0), frame=0)
        self.halves(self.s.view({}, inner), red, red, frame=45)
        self.halves(self.s.view({}, inner, static=True), red, (0, 0, 0), frame=45)   # a still stays

    def test_no_compound_cuts_nothing(self):
        red = (255, 0, 0)
        self.halves(self.s.view({"compound_id": None}), red, red)
        self.halves(self.s.view({"compound_id": "gone"}), red, red)

    def test_compound_cannot_cut_itself(self):
        v = self.s.view({})
        inner = self.s.pic("m", self.s.alpha)
        inner["mask"] = dict(v["tracks"][0]["clips"][0]["mask"])             # its own content masked by itself
        v["compounds"]["k1"]["tracks"][0]["clips"] = [inner]
        self.frame(v)                                                         # (no endless drawing)

    def test_shown_over_the_clip(self):
        v = self.s.view({}, matte_preview={"clip": "top", "opacity": 1.0})
        self.halves(v, (255, 255, 255), (0, 0, 0))                           # the compound's white half on top
        v = self.s.view({"matte": "luma"}, [self.s.pic("m", self.s.luma)], matte_preview={"clip": "top", "opacity": 1.0})
        self.halves(v, (255, 255, 255), (0, 0, 0))


class EditTests(unittest.TestCase):
    def test_pick_a_compound(self):
        p = proj()
        edit.set_mask(p, "c1", "rectangle")
        edit.set_mask(p, "c1", "compound")
        m = edit.find(p, "c1")[1]["mask"]
        self.assertEqual((m["kind"], m["compound_id"], m["matte"]), ("compound", None, "alpha"))
        edit.set_mask_compound(p, "c1", "k9", {"width": 1080, "height": 1080})   # square into 16:9
        self.assertEqual((m["compound_id"], m["w"], m["h"]), ("k9", round(9 / 16, 4), 1.0))
        edit.set_mask_compound(p, "c1", matte="luma")
        self.assertEqual(m["matte"], "luma")
        with self.assertRaises(edit.EditError):
            edit.set_mask_compound(p, "c1", matte="red")
        edit.set_mask(p, "c1", "circle")                                     # back to a shape
        m = edit.find(p, "c1")[1]["mask"]
        self.assertNotIn("compound_id", m)
        with self.assertRaises(edit.EditError):
            edit.set_mask_compound(p, "c1", matte="luma")

    def test_keyframed_shape_becomes_compound(self):
        p = proj()
        edit.set_mask(p, "c1", "rectangle")
        edit.find(p, "c1")[1]["mask"]["kind"] = {"keys": [[0, "rectangle"], [S, "circle"]]}
        edit.set_mask(p, "c1", "compound", 0)
        self.assertEqual(edit.find(p, "c1")[1]["mask"]["kind"], "compound")

    def test_export_through_the_renderer(self):
        p = proj()
        self.assertFalse(renderexport.needs_renderer(p))
        edit.set_mask(p, "c1", "compound")
        self.assertTrue(renderexport.needs_renderer(p))


class PreviewTests(unittest.TestCase):
    def test_corner_keeps_the_proportions(self):
        p = proj()
        edit.set_mask(p, "c1", "compound")
        edit.set_mask_compound(p, "c1", "k9", {"width": 1080, "height": 1080})
        pv = Preview()
        pv.resize(960, 540)
        pv.set_scene(p, S // 2, "c1")
        pv.set_mask_mode(True)
        box = pv.selected_box()
        g = MaskGeo(box)
        self.assertEqual([n for n, _ in g.handles(pv._k())], ["w", "h", "wh", "rot"])    # no feather
        corner = dict(g.handles(pv._k()))["wh"]
        pv.drag = {"kind": "wh", "box": box, "geo": g, "m0": corner, "moved": True}

        class Ev:
            def modifiers(self):
                return NONE
        group, vals = pv._values(Ev(), QPointF(corner.x() - 200, corner.y() + 40))
        self.assertEqual(group, "mask")
        self.assertAlmostEqual(vals["h"] / vals["w"], 1.0 / round(9 / 16, 4), 2)
        self.assertLess(vals["w"], round(9 / 16, 4))


if __name__ == "__main__":
    unittest.main()
