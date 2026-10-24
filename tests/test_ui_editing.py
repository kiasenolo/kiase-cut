"""Scaling on the preview (anchored / about the centre, linked / unlinked X Y), the editor's
own frame rate (時間線精度) in the player and the timeline, grabbing the playhead line."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut.ui.main_window import edit_rate  # noqa: E402
from kiasecut.ui.player import Worker  # noqa: E402
from kiasecut.ui.preview import Box, Preview  # noqa: E402
from kiasecut.ui.timeline import HEADER_W, RULER_H, Timeline  # noqa: E402
from test_edit import S, clip, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
NONE = Qt.KeyboardModifier.NoModifier


def picture(**tf):
    c = clip("c", 0, S)                         # 1920 x 1080 picture: fills the canvas at scale 1
    c["transform"].update(scale=0.5, **tf)       # 960 x 540, centred
    return c


class ScaleDragTests(unittest.TestCase):
    def drag(self, c, side, to, mods=NONE):
        pv = Preview()
        box = Box(c, 1920, 1080, 0)
        handle = next(pt for sx, sy, pt in box.handles() if (sx, sy) == side)
        d = {"side": side, "m0": handle}
        out = pv._scale_values(box, d, QPointF(handle.x() + to[0], handle.y() + to[1]), mods)
        return out, Box(dict(c, transform=dict(c["transform"], **out)), 1920, 1080, 0)

    def test_corner_keeps_the_opposite_corner(self):
        c = picture()
        before = Box(c, 1920, 1080, 0).corners()[0]           # top left
        out, after = self.drag(c, (1, 1), (96, 54))            # bottom right, outwards
        self.assertAlmostEqual(out["scale"], 0.55, 3)
        self.assertAlmostEqual(out["scale_y"], 0.55, 3)
        tl = after.corners()[0]
        self.assertAlmostEqual(tl.x(), before.x(), 1)
        self.assertAlmostEqual(tl.y(), before.y(), 1)

    def test_alt_scales_about_the_centre(self):
        out, after = self.drag(picture(), (1, 1), (96, 54), Qt.KeyboardModifier.AltModifier)
        self.assertNotIn("x", out)
        self.assertAlmostEqual(out["scale"], 0.6, 3)            # both sides move
        self.assertAlmostEqual(after.cx, 960, 3)

    def test_linked_edge_keeps_the_ratio(self):
        out, after = self.drag(picture(), (1, 0), (96, 0))     # right edge
        self.assertAlmostEqual(out["scale"], 0.55, 3)
        self.assertAlmostEqual(out["scale_y"], 0.55, 3)
        self.assertAlmostEqual(after.extents()[0], 480, 1)     # the left edge stays

    def test_unlinked_edge_and_corner(self):
        out, after = self.drag(picture(scale_link=False), (1, 0), (96, 0))
        self.assertAlmostEqual(out["scale"], 0.55, 3)
        self.assertAlmostEqual(out["scale_y"], 0.5, 3)          # only its own axis
        out, _ = self.drag(picture(scale_link=False), (1, 1), (96, 0))
        self.assertAlmostEqual(out["scale"], 0.55, 3)
        self.assertAlmostEqual(out["scale_y"], 0.5, 3)          # a corner sets each freely
        out, _ = self.drag(picture(scale_link=False), (1, 1), (96, 0), Qt.KeyboardModifier.ShiftModifier)
        self.assertAlmostEqual(out["scale"], out["scale_y"], 4)  # Shift keeps the ratio

    def test_rotated_anchor(self):
        c = picture(rotation=30.0)
        before = Box(c, 1920, 1080, 0).corners()[3]           # bottom left stays for the top right
        _, after = self.drag(c, (1, -1), (40, -70))
        self.assertAlmostEqual(after.corners()[3].x(), before.x(), 1)
        self.assertAlmostEqual(after.corners()[3].y(), before.y(), 1)


class EditRateTests(unittest.TestCase):
    def test_edit_rate(self):
        p = proj()
        self.assertEqual(edit_rate(p), p["fps"])
        p["view"] = {"edit_fps": 240}
        self.assertEqual(edit_rate(p), 240)
        p["view"] = {"edit_fps": "junk"}
        self.assertEqual(edit_rate(p), p["fps"])

    def test_player_steps(self):
        w = Worker()
        w.view = {"fps": 240.0, "play_fps": 60.0}
        self.assertEqual(w.step(), 4)                          # a picture every 4 frames of the editor
        w.view = {"fps": 30.0, "play_fps": 30.0}
        self.assertEqual(w.step(), 1)
        w.view = {"fps": 24.0, "play_fps": 60.0}               # coarser than the project: every frame
        self.assertEqual(w.step(), 1)
        w.loop = (10, 19)
        self.assertEqual(w._next(18, 4), 12)                   # wraps inside the time selection

    def test_timeline(self):
        tl = Timeline()
        tl.resize(1000, 400)
        tl.edit_fps = 240.0
        tl.set_project(proj())
        self.assertEqual(tl.fps, 240.0)
        self.assertEqual(tl.max_zoom(), 9600.0)
        tl.px_per_s, tl.scroll_s = 100.0, 0.0
        tl.set_position(240, follow=False)                      # 1 s
        x = HEADER_W + 100
        self.assertTrue(tl._on_playhead(QPointF(x + 2, RULER_H + 50)))
        self.assertFalse(tl._on_playhead(QPointF(x + 12, RULER_H + 50)))
        self.assertFalse(tl._on_playhead(QPointF(x, RULER_H - 5)))     # the ruler seeks anyway
        tl.edit_fps = None
        tl.set_project(proj())
        self.assertEqual(tl.fps, proj()["fps"])


if __name__ == "__main__":
    unittest.main()
