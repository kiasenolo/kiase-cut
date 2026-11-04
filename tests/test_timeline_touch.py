"""The timeline by finger: a clip is dragged only once it has been held (white from the hold); a finger that moves first scrolls
the view; empty track space selects time once held."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut.ui import touch  # noqa: E402
from kiasecut.ui.timeline import Timeline  # noqa: E402
from test_tracks import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


class TimelineTouchTests(unittest.TestCase):
    def setUp(self):
        self.tl = Timeline()
        self.tl.resize(900, 400)
        p = proj()
        p["duration_us"] = 60_000_000
        self.tl.set_project(p)
        self.tl.px_per_s, self.tl.scroll_s = 100.0, 0.0
        self.tl.show()
        QTest.qWait(60)
        self.g = self.tl.findChild(touch._Gestures)
        self.dev = QTest.createTouchDevice()
        self.seq = QTest.touchEvent(self.tl, self.dev)
        self.addCleanup(self.tl.close)
        self.moves = []
        self.tl.clipMoving = getattr(self.tl, "clipMoving", None)
        row = self.tl.tops[0]
        self.on_clip = QPoint(round(self.tl._x(1.0)), round(row + 12))
        self.empty = QPoint(round(self.tl._x(30.0)), round(row + 12))

    def test_a_clip_is_only_hit_where_the_finger_holds_it(self):
        self.assertEqual(self.tl._hit(self.on_clip)[1]["id"], "vid")
        self.assertIsNone(self.tl._hit(self.empty)[1])

    def test_held_on_a_clip_it_goes_white_then_a_move_drags_it(self):
        self.seq.press(0, self.on_clip, self.tl).commit()
        self.assertIsNone(self.tl.lit_id)
        self.g._held()
        self.assertEqual(self.tl.lit_id, "vid")
        self.assertIn("vid", self.tl.selected_ids)
        self.seq.move(0, self.on_clip + QPoint(40, 0), self.tl).commit()
        QTest.qWait(10)
        self.assertEqual(self.tl.drag["mode"], "body")
        self.assertTrue(self.tl.drag["moved"])
        self.seq.release(0, self.on_clip + QPoint(40, 0), self.tl).commit()
        self.assertIsNone(self.tl.lit_id)                      # (the light goes out when the finger is lifted)

    def test_a_finger_that_moves_first_drags_no_clip_and_scrolls_the_view(self):
        shot = self.tl.grab().toImage()
        self.seq.press(0, self.on_clip, self.tl).commit()
        for dx in (-30, -60, -90, -120):
            self.seq.move(0, self.on_clip + QPoint(dx, 0), self.tl).commit()
            QTest.qWait(5)
        self.assertIsNone(self.tl.drag)                         # (no clip drag began)
        self.assertIsNone(self.tl.lit_id)
        self.seq.release(0, self.on_clip + QPoint(-120, 0), self.tl).commit()
        self.assertNotEqual(self.tl.scroll_s, 0.0)             # (the view moved)

    def test_held_on_empty_track_space_then_moved_selects_time(self):
        fps = self.tl.fps
        x0 = round(self.tl._x(10.0))
        y = self.empty.y()
        self.seq.press(0, QPoint(x0, y), self.tl).commit()
        self.g._held()
        self.assertIsNone(self.tl.lit_id)                      # (nothing to light)
        self.seq.move(0, QPoint(x0 + 100, y), self.tl).commit()
        self.seq.move(0, QPoint(x0 + 200, y), self.tl).commit()
        QTest.qWait(10)
        self.seq.release(0, QPoint(x0 + 200, y), self.tl).commit()
        self.assertIsNotNone(self.tl.mark_in)
        self.assertGreater(self.tl.mark_out, self.tl.mark_in)

    def test_a_tap_on_a_clip_selects_it(self):
        self.seq.press(0, self.on_clip, self.tl).commit()
        self.seq.release(0, self.on_clip, self.tl).commit()
        self.assertEqual(self.tl.selected_id, "vid")


if __name__ == "__main__":
    unittest.main()
