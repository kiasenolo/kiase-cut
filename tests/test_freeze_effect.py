"""凍結 (a time effect): on a clip it holds the clip at its first frame; as a filter clip the
tracks under it hold the picture of the moment it begins. 降低幀數 steps a filter clip's tracks
below the same way."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, project, render  # noqa: E402
from test_edit import S  # noqa: E402

APP = QApplication.instance() or QApplication([])


class FreezeTests(unittest.TestCase):
    def scene(self, on_clip, ref="builtin:freeze"):
        pic = os.path.join(tempfile.mkdtemp(), "red.png")
        im = QImage(64, 36, QImage.Format_RGB32)
        im.fill(QColor("#ff0000"))
        im.save(pic)
        p = project.new(1920, 1080, 30)
        c = {"id": "a", "type": "image", "name": "x", "start_us": 0, "duration_us": 4 * S, "source_start_us": 0,
             "media": {"path": pic, "width": 64, "height": 36},
             "transform": {"x": {"keys": [[0, -0.8, 0, 0, 0, 0], [4 * S, 0.8, 0, 0, 0, 0]]}, "y": 0.0, "scale": 0.2,
                           "rotation": 0.0, "opacity": 1.0}}           # moving left to right
        p["tracks"] = [{"id": "t", "kind": "video", "name": "v", "clips": [c]},
                       {"id": "f", "kind": "video", "name": "fx", "clips": []}]
        project.link(p)
        if on_clip:
            edit.add_effect(p, "a", ref)
        else:
            edit.add_filter_clip(p, ref, 2 * S, track_id="f")
        project.refresh_duration(p)
        return p

    def x(self, p, frame):
        img = render.Renderer(None).render(p, frame, 480, 270)
        xs = [x for x in range(480) if img.pixelColor(x, 135).red() > 200 and img.pixelColor(x, 135).green() < 60]
        return sum(xs) // len(xs)

    def test_on_a_clip(self):
        p = self.scene(True)
        self.assertEqual({self.x(p, f) for f in (0, 30, 90)}, {self.x(p, 0)})

    def test_as_a_filter_clip(self):
        p = self.scene(False)
        before, at, later = self.x(p, 30), self.x(p, 60), self.x(p, 100)
        self.assertLess(before, at)                    # still moving before it begins
        self.assertEqual(at, later)                    # held from 2 s on

    def test_frame_rate_filter_clip_steps(self):
        p = self.scene(False, "builtin:frame_rate")
        edit.find(p, p["tracks"][1]["clips"][0]["id"])[1]["effects"][0]["params"]["fps"] = 1.0
        self.assertEqual(self.x(p, 61), self.x(p, 80))     # one step a second under it
        self.assertLess(self.x(p, 80), self.x(p, 92))


if __name__ == "__main__":
    unittest.main()
