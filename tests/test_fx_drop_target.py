"""A filter dropped on a clip goes onto that clip - the one that was lit while dragging, also a clip on an open
group's lane, and also a selected layer the timeline has no row for (a layer inside a group of a static compound)."""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit  # noqa: E402
from kiasecut.ui.main_window import MainWindow  # noqa: E402
from kiasecut.ui.timeline import FX_MIME, Timeline  # noqa: E402
from test_edit import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


def mime():
    md = QMimeData()
    md.setData(FX_MIME, b"builtin:blur")
    return md


class FxDropTargetTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.tl = Timeline()
        self.tl.resize(1200, 400)
        self.tl.set_project(self.p)
        self.tl.show()
        APP.processEvents()
        self.got = []
        self.tl.filterDropped.connect(lambda ref, cid, tid, t: self.got.append(cid))

    def tearDown(self):
        self.tl.close()
        self.tl.deleteLater()
        APP.processEvents()

    def spot(self, c):
        row = next(i for i, r in enumerate(self.tl.rows) if c in r["clips"])
        x = self.tl._x((c["start_us"] + c["duration_us"] / 2) / 1e6)
        return QPointF(x, self.tl.tops[row] + 8)

    def drop(self, at):
        self.md = mime()                                                        # (the event does not own it)
        self.tl.dropEvent(QDropEvent(at, Qt.CopyAction, self.md, Qt.LeftButton, Qt.NoModifier))

    def test_on_a_clip_and_between(self):
        c = self.p["tracks"][0]["clips"][0]
        self.drop(self.spot(c))
        self.assertEqual(self.got, [c["id"]])
        self.drop(QPointF(self.tl.width() - 5, self.tl.tops[0] + 8))           # (empty spot: a filter clip)
        self.assertEqual(self.got[-1], "")

    def test_the_lit_clip_wins_over_where_it_was_let_go(self):
        c = self.p["tracks"][0]["clips"][0]
        self.tl.drop_clip = c                                                   # (lit by the last move)
        self.drop(QPointF(self.tl.width() - 5, self.tl.tops[0] + 8))
        self.assertEqual(self.got, [c["id"]])
        self.assertIsNone(self.tl.drop_clip)

    def test_clip_on_a_group_lane(self):
        g = edit.make_group(self.p, self.p, ["c1"])
        self.tl.open_groups.add(g["id"])
        self.tl.set_project(self.p)
        APP.processEvents()
        inner = edit.find(self.p, "c1")[1]
        for row in range(len(self.tl.rows)):
            for ln in self.tl.lanes(row):
                if inner in ln["track"]["clips"]:
                    x = self.tl._x((ln["abs0"] + inner["start_us"] + inner["duration_us"] / 2) / 1e6)
                    self.drop(QPointF(x, ln["y"] + 3))
                    self.assertEqual(self.got, ["c1"])
                    return
        self.fail("no lane for the clip")

    def test_selected_layer_outside_the_rows(self):
        p = proj()
        applied = []
        host = types.SimpleNamespace(
            timeline=types.SimpleNamespace(selected_ids={"inner"}, selected_clips_primary_first=lambda: []),
            apply=lambda name, fn, *a: applied.append(name), panels=types.SimpleNamespace(show=lambda n: None),
            add_filter_clip=lambda *a: applied.append("filter clip"))
        MainWindow.on_filter_dropped(host, "builtin:blur", "inner", "", 0)
        self.assertEqual(applied, ["新增效果"])                                   # not nothing, not a filter clip


if __name__ == "__main__":
    unittest.main()
