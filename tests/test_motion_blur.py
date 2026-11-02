"""動態模糊 (an effect): the whole clip drawn over the shutter's moments and averaged, so whatever
moves in its picture smears - its place, an expression, a text's animation, the clips inside a
compound - and nothing changes when nothing moves."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, project, render, renderexport  # noqa: E402
from test_edit import S  # noqa: E402

APP = QApplication.instance() or QApplication([])
MOVE = {"keys": [[0, -1.0, 0, 0, 0, 0], [S // 2, 1.0, 0, 0, 0, 0]]}     # across the canvas in half a second


def gl_renderer():
    try:
        from kiasecut import glrender
        return glrender.GLRenderer()
    except Exception:
        return None


class MotionBlurTests(unittest.TestCase):
    def setUp(self):
        pic = os.path.join(tempfile.mkdtemp(), "red.png")
        im = QImage(64, 36, QImage.Format_RGB32)
        im.fill(QColor("#ff0000"))
        im.save(pic)
        self.p = project.new(1920, 1080, 30)
        self.c = {"id": "a", "type": "image", "name": "x", "start_us": 0, "duration_us": 2 * S, "source_start_us": 0,
                  "media": {"path": pic, "width": 64, "height": 36},
                  "transform": {"x": dict(MOVE), "y": 0.0, "scale": 0.2, "rotation": 0.0, "opacity": 1.0}}
        self.p["tracks"] = [{"id": "t", "kind": "video", "name": "v", "clips": [self.c]}]
        project.link(self.p)
        project.refresh_duration(self.p)

    def row(self, frame, renderer=None):
        """(how many px of the middle row are lit, the brightest red there)"""
        img = (renderer or render.Renderer(None)).render(self.p, frame, 480, 270)
        reds = [img.pixelColor(x, 135).red() for x in range(480)]
        return sum(1 for r in reds if r > 20), max(reds)

    def blur(self, clip_id="a"):
        return edit.add_effect(self.p, clip_id, project.MOTION_BLUR_FILTER)

    def test_smears_along_the_move(self):
        sharp = self.row(7)[0]
        e = self.blur()
        self.assertEqual(e["params"], {"shutter": 180.0, "samples": 16})
        self.assertEqual(project.visual_effects(self.c), [])      # (not run as a filter on the picture)
        self.assertGreater(self.row(7)[0], sharp + 10)            # wider along x (half a frame of 32 px)
        self.assertTrue(renderexport.needs_renderer(self.p))

    def test_still_clip_is_as_it_was(self):
        sharp = render.Renderer(None).render(self.p, 45, 480, 270)
        self.blur()
        self.assertEqual(render.Renderer(None).render(self.p, 45, 480, 270), sharp)    # (stopped at 0.5 s)

    def test_switched_off(self):
        sharp = self.row(7)
        e = self.blur()
        edit.set_effect_enabled(self.p, "a", e["id"], False)
        self.assertIsNone(project.shutter_times(self.c, S // 4, 30))
        self.assertEqual(self.row(7), sharp)

    def test_shutter_and_samples(self):
        e = self.blur()
        e["params"].update(shutter=360.0, samples=5)
        times = project.shutter_times(self.c, S // 4, 30)
        self.assertEqual(len(times), 5)
        self.assertAlmostEqual(times[-1] - times[0], S / 30 * 4 / 5)    # 360°: a whole frame, sample midpoints
        self.assertEqual(min(project.shutter_times(self.c, 0, 30)), 0)  # (not before the clip starts)

    def test_an_expression_moves_it(self):
        self.c["transform"]["x"] = 0.0
        edit.set_prop_expr(self.p, "a", "transform.x", "time * 4 - 1")
        sharp = self.row(7)[0]
        self.blur()
        self.assertGreater(self.row(7)[0], sharp + 10)

    def test_a_text_that_spreads(self):
        c = edit.add_text(self.p, 0, "IIII", duration_us=S)
        c["text"]["letter_spacing"] = {"keys": [[0, 0.0, 0, 0, 0, 0], [S // 2, 3.0, 0, 0, 0, 0]]}
        self.c["transform"]["opacity"] = 0.0
        frame = lambda f: render.Renderer(None).render(self.p, f, 480, 270)
        sharp, still = frame(7), frame(45)
        self.blur(c["id"])
        self.assertNotEqual(frame(7), sharp)                      # the letters drawn apart at each moment
        self.assertEqual(frame(45), still)                        # (stopped spreading at 0.5 s)

    def test_the_inside_of_a_compound(self):
        self.c["transform"]["scale"] = 0.2
        comp = edit.make_compound(self.p, self.p, ["a"])
        outer = comp if isinstance(comp, dict) and "start_us" in comp else \
            next(c for c in project.all_clips(self.p) if c.get("compound_id"))
        self.assertFalse(project.curves.is_animated((outer.get("transform") or {}).get("x")))
        sharp = self.row(7)[0]
        self.blur(outer["id"])
        self.assertGreater(self.row(7)[0], sharp + 10)

    def test_gpu_draws_it_too(self):
        gl = gl_renderer()
        if gl is None:
            self.skipTest("no OpenGL")
        sharp = self.row(7, gl)
        self.blur()
        cpu, gpu = self.row(7), self.row(7, gl)
        self.assertGreater(gpu[0], sharp[0] + 10)
        self.assertLessEqual(abs(gpu[0] - cpu[0]), 4)
        self.assertLessEqual(abs(gpu[1] - cpu[1]), 6)

    def test_old_clip_setting_becomes_the_effect(self):
        self.c["motion_blur"] = {"shutter": 90.0, "samples": 12}
        project.normalize(self.p)
        self.assertNotIn("motion_blur", self.c)
        e = self.c["effects"][0]
        self.assertEqual((e["filter"], e["params"]), (project.MOTION_BLUR_FILTER, {"shutter": 90.0, "samples": 12}))


if __name__ == "__main__":
    unittest.main()
