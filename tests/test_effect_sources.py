"""Effect colour sources: a filter's colour parameter fed by a picture, a video or a compound
(effect["sources"]), placed on the clip as a mask is - the colour at each pixel is the
source's there, over the parameter's own colour where the source does not reach. A number
parameter (使用遮罩) is its number times the source's brightness there, its own number where
the source does not reach or is see-through."""
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

from kiasecut import edit, project, render  # noqa: E402
from test_compound_mask import HAVE_GL, Scene, W, H, rgb  # noqa: E402
from test_edit import S, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
WHITE, BLUE, RED = (255, 255, 255), (0, 0, 255), (255, 0, 0)
FILL = """// @filter 填色
// @param tint color #0000ff "顏色"
vec4 effect(vec2 uv) { return premultiply(tint); }
"""


LEVEL = """// @filter 灰階
// @param amount float 1 0 1 "數值"
vec4 effect(vec2 uv) { return vec4(vec3(amount), 1.0); }
"""
GREY = (128, 128, 128)
BLACK = (0, 0, 0)


class SourceRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.s = Scene(cls.dir)
        cls.fill = os.path.join(cls.dir, "fill.glsl")
        with open(cls.fill, "w", encoding="utf-8") as fh:
            fh.write(FILL)
        cls.level = os.path.join(cls.dir, "level.glsl")
        with open(cls.level, "w", encoding="utf-8") as fh:
            fh.write(LEVEL)
        cls.asked = []

        def frame(path, us, w, h):
            cls.asked.append((path, us))
            return QImage(cls.s.alpha if us < S else cls.s.red)
        from kiasecut import glrender
        cls.renderers = [render.Renderer(frame)] + ([glrender.GLRenderer(frame)] if HAVE_GL else [])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def view(self, **src):
        v = self.s.view()
        source = dict({"kind": "image", "image": self.s.alpha, "img_w": 160, "img_h": 90,
                       "cx": 0.0, "cy": 0.0, "w": 1.0, "h": 1.0, "rotation": 0.0}, **src)
        v["tracks"][0]["clips"][0]["effects"] = [{"id": "e1", "filter": self.fill, "params": {"tint": [0, 0, 1, 1]},
                                                  "sources": {"tint": source}}]
        return v

    def number_view(self, amount, image):
        v = self.s.view()
        source = {"kind": "image", "image": image, "img_w": 160, "img_h": 90,
                  "cx": 0.0, "cy": 0.0, "w": 1.0, "h": 1.0, "rotation": 0.0}
        v["tracks"][0]["clips"][0]["effects"] = [{"id": "e1", "filter": self.level, "params": {"amount": amount},
                                                  "sources": {"amount": source}}]
        return v

    def test_number_times_brightness(self):
        self.halves(self.number_view(1.0, self.s.luma), WHITE, BLACK)          # white x 1, black x 1
        self.halves(self.number_view(0.5, self.s.luma), GREY, BLACK)
        self.halves(self.number_view(0.5, self.s.alpha), GREY, GREY)          # see-through: its own number

    def halves(self, view, left, right, frame=0):
        for r in self.renderers:
            img = r.render(view, frame, W, H)
            self.assertEqual(r.errors, [], type(r).__name__)
            self.assertEqual((rgb(img, 12, 18), rgb(img, 52, 18)), (left, right), type(r).__name__)

    def test_picture_over_the_colour(self):
        self.halves(self.view(), WHITE, BLUE)
        self.halves(self.view(cx=1.0), BLUE, WHITE)                       # moved right by half the clip
        self.halves(self.view(rotation=180.0), BLUE, WHITE)               # turned about its centre
        self.halves(self.view(w=0.25, h=0.25), BLUE, BLUE)                # small, in the middle

    def test_no_picture_is_the_colour(self):
        self.halves(self.view(image=None), BLUE, BLUE)

    def test_video_plays_and_compound(self):
        self.halves(self.view(kind="video", video="/v.mp4", vid_w=160, vid_h=90, vid_dur=3 * S), WHITE, BLUE)
        self.halves(self.view(kind="video", video="/v.mp4", vid_w=160, vid_h=90, vid_dur=3 * S, t_off=S), RED, RED)
        self.halves(self.view(kind="compound", compound_id="k1"), WHITE, BLUE)   # (k1: the half picture)


class SourceEditTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.e = edit.add_effect(self.p, "c1", "builtin:glow")              # (its 光的顏色 is "tint")
        self.g = f"fxsrc:{self.e['id']}:tint"

    def src(self):
        return (self.e.get("sources") or {}).get("tint")

    def test_set_place_and_remove(self):
        edit.set_effect_source(self.p, "c1", self.e["id"], "tint", "image")
        self.assertEqual(self.src()["kind"], "image")
        edit.set_effect_source_media(self.p, "c1", self.e["id"], "tint", image=("/a/tall.png", 100, 400))
        self.assertEqual((self.src()["image"], self.src()["w"], self.src()["h"]), ("/a/tall.png", round(0.25 * 9 / 16, 4), 1.0))
        edit.set_param(self.p, "c1", self.g, "cx", 0.5, 0)                  # placed like a mask, keyframes too
        edit.toggle_key(self.p, "c1", self.g, "rotation", 0)
        edit.set_param(self.p, "c1", self.g, "rotation", 90.0, S)
        self.assertIn(S, edit.key_times(edit.find(self.p, "c1")[1]))
        with self.assertRaises(edit.EditError):
            edit.set_effect_source_offset(self.p, "c1", self.e["id"], "tint", S)   # a picture has no time
        edit.set_effect_source(self.p, "c1", self.e["id"], "tint", "video")
        self.assertNotIn("image", self.src())                                # (another kind: chosen anew)
        self.assertEqual(self.src()["cx"], 0.5)                              # (its place stays)
        edit.set_effect_source_media(self.p, "c1", self.e["id"], "tint", video=("/v.mp4", 1920, 1080, 3 * S))
        edit.set_effect_source_offset(self.p, "c1", self.e["id"], "tint", S)
        self.assertEqual(self.src()["t_off"], S)
        edit.set_effect_source(self.p, "c1", self.e["id"], "tint", None)
        self.assertNotIn("sources", self.e)
        with self.assertRaises(edit.EditError):
            edit.set_effect_source(self.p, "c1", self.e["id"], "nothing", "image")   # no such parameter

    def test_numbers_take_one_too(self):
        edit.set_effect_source(self.p, "c1", self.e["id"], "radius", "image")   # (a float: 使用遮罩)
        self.assertEqual(self.e["sources"]["radius"]["kind"], "image")
        for name in ("mode", "glow_only"):                                 # a menu, a switch: not numbers
            with self.assertRaises(edit.EditError):
                edit.set_effect_source(self.p, "c1", self.e["id"], name, "image")

    def test_paths_saved_relative_and_swap(self):
        edit.set_effect_source(self.p, "c1", self.e["id"], "tint", "image")
        folder = tempfile.mkdtemp()
        try:
            edit.set_effect_source_media(self.p, "c1", self.e["id"], "tint", image=(folder + "/Media/m.png", 10, 10))
            path = os.path.join(folder, "x.kiasecut.json")
            project.save(self.p, path)
            with open(path, encoding="utf-8") as fh:
                self.assertIn('"image": "Media/m.png"', fh.read())
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        edit.swap_filter(self.p, "c1", self.e["id"], "builtin:invert")      # no colour there: it goes
        self.assertNotIn("sources", self.e)


class SourceUiTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.e = edit.add_effect(self.p, "c1", "builtin:glow")
        self.c1 = edit.find(self.p, "c1")[1]

    def test_panel(self):
        from kiasecut.ui.effects_panel import EffectsPanel
        panel = EffectsPanel()
        panel.set_media([("/a.png", "a"), ("/b.png", "b")], [("/v.mp4", "v")], [("k1", "合")])
        kinds, media, modes = [], [], []
        panel.sourceKindChosen.connect(lambda *a: kinds.append(a))
        panel.sourceMediaChosen.connect(lambda *a: media.append(a))
        panel.maskEditChanged.connect(lambda: modes.append(panel.source_edit))
        panel.show_clips([self.c1], 0, 30)
        box = panel.widgets[("source", "fx:" + self.e["id"], "tint")]
        self.assertEqual(box.currentData(), None)                           # 顏色
        box.activated.emit(box.findData("image"))
        self.assertEqual(kinds, [(["c1"], self.e["id"], "tint", "image")])
        self.assertEqual(panel.source_edit, (self.e["id"], "tint"))          # straight to placing it
        edit.set_effect_source(self.p, "c1", self.e["id"], "tint", "image")
        edit.set_effect_source_media(self.p, "c1", self.e["id"], "tint", image=("/b.png", 16, 9))
        panel.show_clips([self.c1], 0, 30)
        pick = panel.widgets[("source_media", "fx:" + self.e["id"], "tint")]
        self.assertEqual(pick.currentData(), "/b.png")
        self.assertEqual([pick.itemData(i) for i in range(pick.count())], ["/a.png", "/b.png", ""])
        self.assertTrue(panel.widgets[("source_edit", self.e["id"], "tint")].isChecked())
        self.assertNotIn(("source_region", self.e["id"], "tint"), panel.widgets)   # (a picture has no time)
        pick.activated.emit(0)
        self.assertEqual(media, [(["c1"], self.e["id"], "tint", "/a.png")])
        panel.widgets[("source_edit", self.e["id"], "tint")].click()        # off
        self.assertIsNone(panel.source_edit)
        edit.set_effect_source(self.p, "c1", self.e["id"], "tint", "video")
        panel.show_clips([self.c1], 0, 30)
        self.assertIn(("source_region", self.e["id"], "tint"), panel.widgets)

    def test_number_button(self):
        from kiasecut.ui.effects_panel import EffectsPanel
        panel = EffectsPanel()
        kinds = []
        panel.sourceKindChosen.connect(lambda *a: kinds.append(a))
        panel.show_clips([self.c1], 0, 30)
        key = ("source_btn", "fx:" + self.e["id"], "radius")
        self.assertIn(key, panel.widgets)
        self.assertNotIn(("source_btn", "fx:" + self.e["id"], "tint"), panel.widgets)      # (colours have their menu)
        self.assertFalse(panel.widgets[key].isChecked())
        edit.set_effect_source(self.p, "c1", self.e["id"], "radius", "image")
        panel.show_clips([self.c1], 0, 30)
        self.assertTrue(panel.widgets[key].isChecked())
        self.assertIn(("source_media", "fx:" + self.e["id"], "radius"), panel.widgets)    # which picture
        panel.widgets[key].click()                                           # again: stop reading it
        self.assertEqual(kinds, [(["c1"], self.e["id"], "radius", None)])

    def test_preview_drag_places_it(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from kiasecut.ui.preview import Preview
        edit.set_effect_source(self.p, "c1", self.e["id"], "tint", "image")
        g = f"fxsrc:{self.e['id']}:tint"
        pv = Preview()
        pv.resize(960, 540)
        pv.set_scene(self.p, S // 2, "c1")
        pv.set_mask_mode(True, g)
        self.assertTrue(pv.masking(pv.selected_box()))
        got = []
        pv.paramsCommitted.connect(lambda *a: got.append(a))
        a, b = QPoint(480, 270), QPoint(580, 270)
        QTest.mousePress(pv, Qt.LeftButton, Qt.NoModifier, a)
        QTest.mouseMove(pv, QPoint(530, 270))
        QTest.mouseMove(pv, b)
        QTest.mouseRelease(pv, Qt.LeftButton, Qt.NoModifier, b)
        self.assertEqual(len(got), 1)
        cid, group, vals = got[0]
        self.assertEqual((cid, group), ("c1", g))
        self.assertAlmostEqual(vals["cx"], 200 / 960, places=3)
        for k, v in vals.items():
            edit.set_param(self.p, cid, group, k, v, S // 2)
        self.assertAlmostEqual(self.e["sources"]["tint"]["cx"], 200 / 960, places=3)


if __name__ == "__main__":
    unittest.main()
