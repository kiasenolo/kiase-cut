"""Locked tracks (鎖定): their clips cannot be selected anywhere (timeline clicks, selection
boxes, 全選, the preview) and nothing is moved or dropped onto them."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, project  # noqa: E402
from kiasecut.ui.preview import Preview  # noqa: E402
from kiasecut.ui.timeline import HEADER_W, US, Timeline  # noqa: E402
from test_edit import S, clip, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
NONE = Qt.KeyboardModifier.NoModifier


def locked_proj():
    p = proj()
    p["tracks"][1]["clips"].append(clip("c4", 0, 2 * S))                 # on t1, which stays unlocked
    edit.set_track_flag(p, "t0", "locked", True)                          # c1, c2 are on t0
    return p


class EditTests(unittest.TestCase):
    def test_flag_and_moves(self):
        p = locked_proj()
        self.assertTrue(project.locked(edit.track_by_id(p, "t0")))
        with self.assertRaises(edit.EditError):                           # nothing moves onto it
            edit.move(p, "c4", 3 * S, "t0")
        edit.move(p, "c4", 3 * S)                                         # along its own track: fine
        c = edit.new_compound(p, p, 3 * S + 3 * S)                        # t1 is busy there? no: free
        self.assertNotIn(c, edit.track_by_id(p, "t0")["clips"])
        placed = edit.place_compound(p, p, c["compound_id"], "t0", 8 * S)  # dropped on it: a new track
        self.assertNotIn(placed, edit.track_by_id(p, "t0")["clips"])
        edit.set_track_flag(p, "t0", "locked", False)
        self.assertFalse(project.locked(edit.track_by_id(p, "t0")))


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.tl = Timeline()
        self.tl.resize(1000, 400)
        self.p = locked_proj()
        self.tl.set_project(self.p)
        self.tl.px_per_s, self.tl.scroll_s = 100.0, 0.0
        self.row = next(i for i, t in enumerate(self.tl.rows) if t["id"] == "t0")

    def at(self, cid):
        row, c = next((i, c) for i, t in enumerate(self.tl.rows) for c in t["clips"] if c["id"] == cid)
        return QPointF(self.tl._x((c["start_us"] + c["duration_us"] / 2) / US), self.tl.tops[row] + 10)

    def test_cannot_be_selected(self):
        tl = self.tl
        self.assertEqual(tl._hit(self.at("c1"))[1], None)                 # a click finds no clip there
        self.assertEqual(tl._hit(self.at("c4"))[1]["id"], "c4")
        tl.select(edit.find(self.p, "c1")[1])
        self.assertIsNone(tl.selected_id)
        tl.set_selection({"c1", "c2", "c4"}, "c1")
        self.assertEqual((tl.selected_ids, tl.selected_id), ({"c4"}, "c4"))
        tl.select_all()
        self.assertEqual(tl.selected_ids, {"c3", "c4"})                   # everything but the locked track

    def test_click_and_box(self):
        tl = self.tl
        tl.select(None)
        QTest.mouseClick(tl, Qt.LeftButton, NONE, self.at("c1").toPoint())
        self.assertIsNone(tl.selected_id)
        ys = sorted((self.at("c1").y(), self.at("c4").y()))
        start = QPoint(HEADER_W + 350, int(ys[0]))                        # empty space at 3.5 s, top row
        end = QPoint(HEADER_W + 50, int(ys[1]))                           # back over c4 and c1
        QTest.mousePress(tl, Qt.LeftButton, NONE, start)
        QTest.mouseMove(tl, (start + end) / 2)
        QTest.mouseMove(tl, end)
        QTest.mouseRelease(tl, Qt.LeftButton, NONE, end)
        self.assertEqual(tl.selected_ids, {"c4"})                         # the box skips the locked track

    def test_padlock_button(self):
        flags = [f for f, _ in self.tl.header_buttons(self.row)]
        self.assertEqual(flags[0], "locked")
        got = []
        self.tl.trackAction.connect(lambda action, tid: got.append((action, tid)))
        r = dict(self.tl.header_buttons(self.row))["locked"]
        QTest.mouseClick(self.tl, Qt.LeftButton, NONE, r.center().toPoint())
        self.assertEqual(got, [("toggle:locked", "t0")])

    def test_no_drop_onto_it(self):
        self.assertIsNone(self.tl._drop_row(self.tl.tops[self.row] + 10))


class PreviewTests(unittest.TestCase):
    def test_locked_clip_not_picked(self):
        p = locked_proj()
        edit.find(p, "c1")[1]["transform"].update(scale=0.3, x=-0.5)     # left; c4 on the right
        edit.find(p, "c4")[1]["transform"].update(scale=0.3, x=0.5)
        pv = Preview()
        pv.resize(960, 540)
        pv.set_scene(p, S // 2, None)
        picked = []
        pv.clipPicked.connect(lambda c: picked.append(c["id"]))
        pv.selectionPicked.connect(lambda ids, primary: picked.append(sorted(ids)))
        QTest.mouseClick(pv, Qt.LeftButton, NONE, QPoint(240, 270))       # on c1
        self.assertNotIn("c1", picked)
        QTest.mouseClick(pv, Qt.LeftButton, NONE, QPoint(720, 270))       # on c4
        self.assertIn("c4", picked)
        self.assertEqual(sorted(b.clip["id"] for b in pv.visible_boxes()), ["c1", "c4"])     # both still show
        self.assertEqual([b.clip["id"] for b in pv._marquee_hits(QRectF(0, 0, 1920, 1080))], ["c4"])   # a box: c4 only


if __name__ == "__main__":
    unittest.main()
