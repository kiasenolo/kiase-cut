"""Image masks (遮罩 → 圖片): a picture file's alpha or brightness cuts a clip, as a compound
mask does; video masks (遮罩 → 影片) the same with a video's frame at clip time + t_off; and
編輯區域: a live compound mask, or a video mask, plays from another moment (t_off)."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage  # noqa: E402
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


class VideoMaskTests(unittest.TestCase):
    """The video's frames come from the renderer's video_frame (here: the left half until 1 s
    into the video, all of it after)."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.s = Scene(cls.dir)
        cls.asked = []

        def frame(path, us, w, h):
            cls.asked.append((path, us))
            return QImage(cls.s.alpha if us < S else cls.s.blue)
        from kiasecut import glrender
        cls.renderers = [render.Renderer(frame)] + ([glrender.GLRenderer(frame)] if HAVE_GL else [])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def view(self, **mask):
        v = self.s.view({})
        v["tracks"][0]["clips"][0]["mask"] = dict({"kind": "video", "video": "/v.mp4", "vid_w": 160, "vid_h": 90,
                                                   "vid_dur": 3 * S, "matte": "alpha", "invert": False, "cx": 0.0,
                                                   "cy": 0.0, "w": 1.0, "h": 1.0, "rotation": 0.0}, **mask)
        return v

    def test_frames_follow_the_clip(self):
        red, black = (255, 0, 0), (0, 0, 0)
        for r in self.renderers:
            name = type(r).__name__
            for view, frame, want in ((self.view(), 0, (red, black)), (self.view(), 45, (red, red)),       # 1.5 s
                                      (self.view(t_off=S), 0, (red, red)),                                  # 1 s in
                                      (self.view(invert=True), 0, (black, red))):
                self.asked.clear()
                img = r.render(view, frame, W, H)
                self.assertEqual(r.errors, [], name)
                self.assertEqual((rgb(img, 12, 18), rgb(img, 52, 18)), want, f"{name} {frame} {view['tracks']}")
                self.assertTrue(self.asked and self.asked[0][0] == "/v.mp4", name)
        self.asked.clear()
        self.renderers[0].render(self.view(t_off=10 * S), 0, W, H)          # past its end: its last frame
        self.assertEqual(self.asked[0][1], 3 * S - S / 30)

    def test_no_video_cuts_nothing(self):
        red = (255, 0, 0)
        img = render.Renderer().render(self.view(), 0, W, H)                # (no frames to be had)
        self.assertEqual((rgb(img, 12, 18), rgb(img, 52, 18)), (red, red))
        img = self.renderers[0].render(self.view(video=None), 0, W, H)
        self.assertEqual((rgb(img, 12, 18), rgb(img, 52, 18)), (red, red))

    def test_edits(self):
        p = proj()
        edit.set_mask(p, "c1", "video")
        c = edit.find(p, "c1")[1]
        edit.set_mask_video(p, "c1", "/a/wide.mp4", 1920, 1080, 4 * S)
        m = c["mask"]
        self.assertEqual((m["video"], m["vid_w"], m["vid_h"], m["vid_dur"], m["w"], m["h"]),
                         ("/a/wide.mp4", 1920, 1080, 4 * S, 1.0, 1.0))
        edit.set_mask_offset(p, "c1", S)
        self.assertEqual(m["t_off"], S)
        self.assertTrue(renderexport.needs_renderer(p))
        edit.set_mask(p, "c1", "image")                                      # the video's settings go
        self.assertNotIn("video", c["mask"])
        edit.set_mask(p, "c1", "video")
        self.assertNotIn("video", c["mask"])
        with self.assertRaises(edit.EditError):
            edit.set_mask_video(p, "c2", "/a.mp4", 10, 10, S)               # c2 has no video mask

    def test_path_saved_relative(self):
        p = proj()
        edit.set_mask(p, "c1", "video")
        folder = tempfile.mkdtemp()
        try:
            edit.set_mask_video(p, "c1", folder + "/Media/m.mp4", 10, 10, S)
            path = os.path.join(folder, "x.kiasecut.json")
            project.save(p, path)
            with open(path, encoding="utf-8") as fh:
                self.assertIn('"video": "Media/m.mp4"', fh.read())
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class VideoMaskPanelTests(unittest.TestCase):
    def test_picker_and_region(self):
        from kiasecut.ui.inspector import Inspector
        p = proj()
        edit.set_mask(p, "c1", "video")
        mp = Inspector(part="mask")
        mp.set_videos([("/a.mp4", "a"), ("/b.mp4", "b")])
        got = []
        mp.maskVideoChosen.connect(lambda ids, path: got.append((ids, path)))
        mp.show_clips([edit.find(p, "c1")[1]], 0, 30)
        pick = mp.widgets["mask_video"]
        self.assertEqual([pick.itemData(i) for i in range(pick.count())], ["/a.mp4", "/b.mp4", ""])
        self.assertNotIn("matte_region", mp.widgets)                        # (no video yet)
        pick.activated.emit(1)
        self.assertEqual(got, [(["c1"], "/b.mp4")])
        edit.set_mask_video(p, "c1", "/b.mp4", 1920, 1080, S)
        mp.show_clips([edit.find(p, "c1")[1]], 0, 30)
        self.assertEqual(mp.widgets["mask_video"].currentData(), "/b.mp4")
        self.assertIn("matte_region", mp.widgets)
        self.assertIn("mask_matte", mp.widgets)
        self.assertNotIn(("mask", "feather"), mp.widgets)                    # (a picture has no feather)


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
