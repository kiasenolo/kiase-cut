"""The preview by finger: a clip is picked and dragged only once it has been held (white from the hold); a finger that moves first
moves the view; a tap still clicks."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut.ui import touch  # noqa: E402
from kiasecut.ui.preview import Preview  # noqa: E402
from test_edit import S, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


class PreviewTouchTests(unittest.TestCase):
    def setUp(self):
        self.pv = Preview()
        self.pv.resize(960, 540)
        self.pv.set_scene(proj(), S // 2, None)
        self.pv.show()
        QTest.qWait(40)
        self.addCleanup(self.pv.close)
        self.g = self.pv.findChild(touch._Gestures)
        self.dev = QTest.createTouchDevice()
        self.seq = QTest.touchEvent(self.pv, self.dev)
        box = self.pv.visible_boxes()[0]
        self.cid = box.clip["id"]
        c = box.corners()
        mid = (c[0] + c[2]) / 2
        r = self.pv._rect()
        self.on = QPoint(round(r.x() + mid.x() / self.pv.W * r.width()), round(r.y() + mid.y() / self.pv.H * r.height()))

    def test_held_on_a_clip_it_goes_white_picks_and_a_move_drags_it(self):
        self.seq.press(0, self.on, self.pv).commit()
        self.assertIsNone(self.pv.lit_id)
        self.assertIsNone(self.pv.selected_id)
        self.g._held()
        self.assertEqual(self.pv.lit_id, self.cid)
        self.assertEqual(self.pv.selected_id, self.cid)
        self.seq.move(0, self.on + QPoint(40, 0), self.pv).commit()
        QTest.qWait(10)
        self.assertEqual(self.pv.drag["kind"], "move")
        self.seq.release(0, self.on + QPoint(40, 0), self.pv).commit()
        self.assertIsNone(self.pv.lit_id)

    def test_a_finger_that_moves_first_picks_nothing_and_moves_the_view(self):
        self.seq.press(0, self.on, self.pv).commit()
        pan = QPointF(self.pv.pan)
        self.seq.move(0, self.on + QPoint(60, 30), self.pv).commit()
        QTest.qWait(10)
        self.seq.release(0, self.on + QPoint(60, 30), self.pv).commit()
        self.assertIsNone(self.pv.selected_id)
        self.assertIsNone(self.pv.drag)
        self.assertNotEqual(self.pv.pan, pan)

    def test_a_handle_is_taken_at_once_without_a_hold(self):
        self.pv.selected_id, self.pv.selected_ids = self.cid, {self.cid}
        box = self.pv.selected_box()
        r, k = self.pv._rect(), self.pv._k()
        pt = box.rot_handle(k)
        at = QPoint(round(r.x() + pt.x() / self.pv.W * r.width()), round(r.y() + pt.y() / self.pv.H * r.height()))
        self.assertFalse(self.g.hold_left(at))
        self.assertTrue(self.g.hold_left(self.on))

    def test_a_tap_still_picks(self):
        self.seq.press(0, self.on, self.pv).commit()
        self.seq.release(0, self.on, self.pv).commit()
        QTest.qWait(20)
        self.assertEqual(self.pv.selected_id, self.cid)

    def test_the_fullscreen_canvas_is_not_gated(self):
        pv = Preview(interactive=False)
        self.addCleanup(pv.close)
        g = pv.findChild(touch._Gestures)
        self.assertIsNone(g.hold_left)


if __name__ == "__main__":
    unittest.main()
