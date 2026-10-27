"""移入群組: clips put into a group that is already there, the same on the canvas and in time."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kiasecut import edit  # noqa: E402
from test_edit import S, clip  # noqa: E402
from test_groups import scene  # noqa: E402


class IntoGroupTests(unittest.TestCase):
    def setUp(self):
        self.p = scene()                         # t0: c1 0-2, c2 5-7; t1: c4 1-3; t2 audio c3
        self.g = edit.make_group(self.p, self.p, ["c1", "c4"])          # 0-4 s

    def test_keeps_canvas_place_and_time(self):
        self.g["transform"].update(x=0.5, y=-0.2, scale=2.0)
        edit.find(self.p, "c2")[1]["transform"].update(x=0.9, y=0.0, scale=1.0)
        edit.move(self.p, self.g["id"], 1 * S)                          # group 1-5 s
        edit.move_into_group(self.p, self.p, ["c2"], self.g["id"])      # c2 at 5-7 s: the group grows
        self.assertEqual(edit.abs_start(self.p, "c2"), 5 * S)
        self.assertEqual((self.g["start_us"], self.g["duration_us"]), (1 * S, 6 * S))
        tf = edit.find(self.p, "c2")[1]["transform"]
        self.assertAlmostEqual(0.5 + 2.0 * tf["x"], 0.9)                 # the same on the canvas
        self.assertAlmostEqual(-0.2 + 2.0 * tf["y"], 0.0)
        self.assertAlmostEqual(tf["scale"] * 2.0, 1.0)
        self.assertIs(edit.group_of(self.p, edit.find(self.p, "c2")[0]), self.g)

    def test_grows_to_the_left(self):
        self.p["tracks"][1]["clips"].append(clip("c5", 0, S))
        edit.move(self.p, self.g["id"], 2 * S)                          # group 2-6 s
        edit.move_into_group(self.p, self.p, ["c5"], self.g["id"])
        self.assertEqual((self.g["start_us"], self.g["duration_us"]), (0, 6 * S))
        self.assertEqual(edit.abs_start(self.p, "c1"), 2 * S)            # the others stay put
        self.assertEqual(edit.abs_start(self.p, "c5"), 0)

    def test_given_track_and_time(self):
        top = self.g["tracks"][1]
        edit.move_into_group(self.p, self.p, ["c2"], self.g["id"], track_id=top["id"], start_us=4 * S)
        self.assertIn("c2", [k["id"] for k in top["clips"]])
        self.assertEqual(edit.abs_start(self.p, "c2"), 4 * S)               # (right after c4)
        self.assertEqual(self.g["duration_us"], 6 * S)

    def test_new_track_when_no_room(self):
        n = len(self.g["tracks"])
        self.p["tracks"][1]["clips"].append(clip("c5", 0, 2 * S))      # overlaps c1 and c4 in time
        edit.move_into_group(self.p, self.p, ["c5"], self.g["id"])
        self.assertEqual(len(self.g["tracks"]), n + 1)

    def test_refused(self):
        with self.assertRaises(edit.EditError):
            edit.move_into_group(self.p, self.p, ["c3"], self.g["id"])  # sound
        with self.assertRaises(edit.EditError):
            edit.move_into_group(self.p, self.p, [self.g["id"]], self.g["id"])
        with self.assertRaises(edit.EditError):
            edit.move_into_group(self.p, self.p, ["c1"], self.g["id"])  # already in it
        self.g["transform"]["rotation"] = 15.0
        with self.assertRaises(edit.EditError):
            edit.move_into_group(self.p, self.p, ["c2"], self.g["id"])
        self.assertEqual(edit.find(self.p, "c2")[0]["id"], "t0")        # nothing changed

    def test_from_another_group(self):
        h = edit.make_group(self.p, self.p, ["c2"])
        h["transform"].update(x=0.3)
        edit.find(self.p, "c2")[1]["transform"]["x"] = 0.1               # 0.4 on the canvas
        edit.move_into_group(self.p, self.p, ["c2"], self.g["id"])
        self.assertAlmostEqual(edit.find(self.p, "c2")[1]["transform"]["x"], 0.4)
        self.assertEqual(edit.abs_start(self.p, "c2"), 5 * S)

    def test_group_ids(self):
        self.assertEqual([gid for gid, _ in edit.group_ids(self.p)], [self.g["id"]])


if __name__ == "__main__":
    unittest.main()


class IntoGroupUiTests(unittest.TestCase):
    """The ways in: the layer list (dragged in, dropped in), the timeline's lanes, the preview."""

    def setUp(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        self.p = scene()
        self.g = edit.make_group(self.p, self.p, ["c1", "c4"])

    def panel(self):
        from kiasecut.ui.layers import LayerPanel
        panel = LayerPanel()
        panel.resize(300, 400)
        panel.opened.add(self.g["id"])
        panel.set_layers(self.p, set(), None)
        panel.show()
        return panel

    def rows(self, panel):
        from kiasecut.ui.layers import ROLE
        return [panel.list.item(i).data(ROLE) for i in range(panel.list.count())]

    def test_list_drop_targets(self):
        from PySide6.QtCore import QPointF
        panel = self.panel()
        rows = self.rows(panel)                          # g, (c4, c1 inside it), c2
        self.assertEqual(rows, [self.g["id"], "c4", "c1", "c2"])
        lst = panel.list

        def at(row, where):
            r = lst.visualItemRect(lst.item(row))
            return QPointF(r.center().x(), {"top": r.top() + 2, "mid": r.center().y(), "low": r.bottom() - 2}[where])
        self.assertEqual(lst.drop_target(at(0, "mid")), (self.g["id"], 0))      # on the group's row
        self.assertEqual(lst.drop_target(at(0, "low")), (self.g["id"], 0))      # right under it: inside
        self.assertEqual(lst.drop_target(at(1, "low")), (self.g["id"], 1))
        self.assertEqual(lst.drop_target(at(3, "low")), ("", 2))                # after c2: the level
        self.assertEqual(lst.drop_target(at(0, "top")), ("", 0))

    def test_list_drag_onto_group_row(self):
        from PySide6.QtCore import QMimeData, QPointF, Qt
        from PySide6.QtGui import QDropEvent
        panel = self.panel()
        got = []
        panel.movedInto.connect(lambda ids, gid, order: got.append((ids, gid, order)))
        lst = panel.list
        lst.item(3).setSelected(True)                    # c2
        r = lst.visualItemRect(lst.item(0))
        e = QDropEvent(QPointF(r.center()), Qt.MoveAction, QMimeData(), Qt.LeftButton, Qt.NoModifier)
        lst._drop_inside(e)
        self.assertEqual(got, [(["c2"], self.g["id"], ["c2", "c4", "c1"])])

    def test_window_moves_and_stacks(self):
        from types import SimpleNamespace
        from kiasecut.ui.main_window import MainWindow
        h = edit.History(self.p)
        win = SimpleNamespace(proj=self.p, container=lambda *_: self.p,
                              layers=SimpleNamespace(opened=set()), timeline=SimpleNamespace(open_groups=set()),
                              _update_layers=lambda: None)
        win.apply_root = lambda label, fn: h.do(label, lambda root: fn(root))
        MainWindow.layers_into_group(win, ["c2"], self.g["id"], ["c4", "c2", "c1"])
        self.assertEqual([c["id"] for c in edit.layers(self.g)], ["c4", "c2", "c1"])
        self.assertEqual(len(h.undo_stack), 1)
        self.assertIn(self.g["id"], win.layers.opened)

    def test_timeline_lane_drop(self):
        from PySide6.QtCore import QMimeData, QPointF, Qt
        from PySide6.QtGui import QDropEvent
        from kiasecut.ui.timeline import MEDIA_MIME, Timeline
        tl = Timeline()
        tl.resize(900, 400)
        tl.set_project(self.p)
        tl.px_per_s, tl.scroll_s = 100.0, 0.0
        tl.open_groups.add(self.g["id"])
        tl._layout()
        row = next(i for i, t in enumerate(tl.rows) if any(c is self.g for c in t["clips"]))
        ln = tl.lanes(row)[0]
        got = []
        tl.groupDropped.connect(lambda *a: got.append(a))
        md = QMimeData()
        md.setData(MEDIA_MIME, b"m9")
        pos = QPointF(tl._x(1.5), ln["y"] + ln["h"] / 2)
        self.assertIsNotNone(tl._into_lane(pos))
        self.assertIsNone(tl._into_lane(pos, [self.g["id"]]))                # never into itself
        tl.dropEvent(QDropEvent(pos, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
        self.assertEqual(got, [(["m9"], [], self.g["id"], ln["track"]["id"], int(1.5 * S))])

    def test_timeline_lane_trim_past_the_group(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from kiasecut.ui.timeline import Timeline
        tl = Timeline()
        tl.resize(900, 400)
        tl.set_project(self.p)
        tl.px_per_s, tl.scroll_s = 100.0, 0.0
        tl.open_groups.add(self.g["id"])
        tl._layout()
        tl.show()
        row = next(i for i, t in enumerate(tl.rows) if any(c is self.g for c in t["clips"]))
        ln = next(ln for ln in tl.lanes(row) if any(c["id"] == "c4" for c in ln["track"]["clips"]))
        y = round(ln["y"] + ln["h"] / 2)
        at = QPoint(round(tl._x(4.0)) - 2, y)                                # c4's right edge (= the group's)
        QTest.mouseMove(tl, at)
        self.assertEqual(tl.cursor().shape(), Qt.SizeHorCursor)
        got = []
        tl.trimRequested.connect(lambda *a: got.append(a))
        QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, at)
        QTest.mouseMove(tl, at + QPoint(100, 0))
        QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, at + QPoint(100, 0))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][:2], ("c4", "end"))
        self.assertGreater(got[0][2], self.g["duration_us"])                  # past it: the group grows

    def test_preview_drop_on_group(self):
        from PySide6.QtCore import QMimeData, QPointF, Qt
        from PySide6.QtGui import QDropEvent
        from kiasecut.ui.preview import Preview
        from kiasecut.ui.timeline import MEDIA_MIME
        pv = Preview()
        pv.resize(960, 540)
        pv.set_scene(self.p, S // 2, None)
        pv.accept_media = True
        got = []
        pv.mediaDropped.connect(lambda *a: got.append(a))
        md = QMimeData()
        md.setData(MEDIA_MIME, b"m9")
        pv.dropEvent(QDropEvent(QPointF(480, 270), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
        self.assertEqual(got[0][0], ["m9"])
        self.assertEqual(got[0][4], self.g["id"])        # the group covers the middle: into it
