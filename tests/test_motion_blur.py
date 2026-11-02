"""動態模糊 (an effect): a clip's picture averaged over the shutter's moments while its place
moves - none when it is off or nothing of its place is animated."""
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


class MotionBlurTests(unittest.TestCase):
    def setUp(self):
        pic = os.path.join(tempfile.mkdtemp(), "red.png")
        im = QImage(64, 36, QImage.Format_RGB32)
        im.fill(QColor("#ff0000"))
        im.save(pic)
        self.p = project.new(1920, 1080, 30)
        self.c = {"id": "a", "type": "image", "name": "x", "start_us": 0, "duration_us": 2 * S, "source_start_us": 0,
                  "media": {"path": pic, "width": 64, "height": 36},
                  "transform": {"x": {"keys": [[0, -1.0, 0, 0, 0, 0], [S // 2, 1.0, 0, 0, 0, 0]]}, "y": 0.0,
                                "scale": 0.2, "rotation": 0.0, "opacity": 1.0}}
        self.p["tracks"] = [{"id": "t", "kind": "video", "name": "v", "clips": [self.c]}]
        project.link(self.p)
        project.refresh_duration(self.p)

    def lit(self, frame):
        img = render.Renderer(None).render(self.p, frame, 480, 270)
        return sum(1 for x in range(480) if img.pixelColor(x, 135).red() > 20)

    def test_smears_along_the_move(self):
        sharp = self.lit(7)
        e = edit.add_effect(self.p, "a", project.MOTION_BLUR_FILTER)
        self.assertEqual(e["params"], {"shutter": 180.0, "samples": 8})
        self.assertEqual(project.visual_effects(self.c), [])      # (not run as a filter on the picture)
        self.assertGreater(self.lit(7), sharp + 10)               # wider along x (half a frame of 32 px)
        self.assertTrue(renderexport.needs_renderer(self.p))

    def test_still_clip_is_not_blurred(self):
        e = edit.add_effect(self.p, "a", project.MOTION_BLUR_FILTER)
        self.assertIsNotNone(project.blur_times(self.c, S // 4, 30))
        self.assertIsNone(project.blur_times(self.c, S, 30))      # (it stopped moving at 0.5 s)
        edit.set_effect_enabled(self.p, "a", e["id"], False)
        self.assertIsNone(project.blur_times(self.c, S // 4, 30))

    def test_shutter_and_samples(self):
        e = edit.add_effect(self.p, "a", project.MOTION_BLUR_FILTER)
        e["params"].update(shutter=360.0, samples=5)
        times = project.blur_times(self.c, S // 4, 30)
        self.assertEqual(len(times), 5)
        self.assertAlmostEqual(times[-1] - times[0], S / 30)     # 360°: a whole frame

    def test_old_clip_setting_becomes_the_effect(self):
        self.c["motion_blur"] = {"shutter": 90.0, "samples": 12}
        project.normalize(self.p)
        self.assertNotIn("motion_blur", self.c)
        e = self.c["effects"][0]
        self.assertEqual((e["filter"], e["params"]), (project.MOTION_BLUR_FILTER, {"shutter": 90.0, "samples": 12}))


if __name__ == "__main__":
    unittest.main()
