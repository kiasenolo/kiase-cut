"""Image masks (遮罩 → 圖片): a picture file's alpha or brightness cuts a clip, as a compound
mask does; and 編輯區域: a live compound mask plays from another moment (t_off)."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, project, render, renderexport  # noqa: E402
from test_compound_mask import HAVE_GL, Scene, W, H, rgb  # noqa: E402
from test_edit import S, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


class ImageMaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.s = Scene(cls.dir)
        from kiasecut import glrender
        cls.renderers = [render.Renderer()] + ([glrender.GLRenderer()] if HAVE_GL else [])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def view(self, **mask):
        v = self.s.view({})
        v["tracks"][0]["clips"][0]["mask"] = dict({"kind": "image", "image": self.s.alpha, "img_w": 160,
                                                   "img_h": 90, "matte": "alpha", "invert": False, "cx": 0.0,
                                                   "cy": 0.0, "w": 1.0, "h": 1.0, "rotation": 0.0}, **mask)
        return v

    def halves(self, view, left, right, frame=0):
        for r in self.renderers:
            img = r.render(view, frame, W, H)
            self.assertEqual(r.errors, [], type(r).__name__)
            self.assertEqual(rgb(img, 12, 18), left, type(r).__name__)
            self.assertEqual(rgb(img, 52, 18), right, type(r).__name__)

    def test_alpha_luma_invert(self):
        red, black = (255, 0, 0), (0, 0, 0)
        self.halves(self.view(), red, black)
        self.halves(self.view(invert=True), black, red)
        self.halves(self.view(image=self.s.luma, matte="luma"), red, black)
        self.halves(self.view(cx=1.0), black, red)                          # moved right by half the clip

    def test_no_picture_cuts_nothing(self):
        red = (255, 0, 0)
        self.halves(self.view(image=None), red, red)

    def test_edits(self):
        p = proj()
        edit.set_mask(p, "c1", "image")
        c = edit.find(p, "c1")[1]
        self.assertEqual(c["mask"]["kind"], "image")
        edit.set_mask_image(p, "c1", "/a/tall.png", 100, 400)                # taller than the 16:9 clip
        self.assertEqual((c["mask"]["image"], c["mask"]["w"], c["mask"]["h"]), ("/a/tall.png", round(0.25 * 9 / 16, 4), 1.0))
        edit.set_mask_compound(p, "c1", matte="luma")
        self.assertEqual(c["mask"]["matte"], "luma")
        self.assertTrue(renderexport.needs_renderer(p))
        with self.assertRaises(edit.EditError):
            edit.set_mask_offset(p, "c1", S)                                 # an image has no time

    def test_path_saved_relative(self):
        p = proj()
        edit.set_mask(p, "c1", "image")
        folder = tempfile.mkdtemp()
        try:
            edit.set_mask_image(p, "c1", folder + "/Media/m.png", 10, 10)
            path = os.path.join(folder, "x.kiasecut.json")
            project.save(p, path)
            with open(path, encoding="utf-8") as fh:
                self.assertIn('"image": "Media/m.png"', fh.read())
            back = project.load(path)
            self.assertEqual(edit.find(back, "c1")[1]["mask"]["image"], folder.replace("\\", "/") + "/Media/m.png")
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class RegionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.s = Scene(cls.dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_offset_picks_another_moment(self):
        inner = [self.s.pic("m", self.s.alpha, 0, S), self.s.pic("n", self.s.blue, S, S)]   # all opaque from 1 s
        r = render.Renderer()
        red, black = (255, 0, 0), (0, 0, 0)
        img = r.render(self.s.view({}, inner), 0, W, H)
        self.assertEqual((rgb(img, 12, 18), rgb(img, 52, 18)), (red, black))
        img = r.render(self.s.view({"t_off": S}, inner), 0, W, H)                         # starts 1 s in
        self.assertEqual((rgb(img, 12, 18), rgb(img, 52, 18)), (red, red))

    def test_edit(self):
        p = proj()
        edit.set_mask(p, "c1", "compound")
        edit.set_mask_offset(p, "c1", 1.5 * S)
        self.assertEqual(edit.find(p, "c1")[1]["mask"]["t_off"], int(1.5 * S))
        edit.set_mask_offset(p, "c1", 0)
        self.assertNotIn("t_off", edit.find(p, "c1")[1]["mask"])


if __name__ == "__main__":
    unittest.main()
