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


class LayerStackTests(unittest.TestCase):
    def test_second_effect_on_top_stacks_in_the_filter_layer(self):
        p = proj()
        first = edit.add_filter_clip(p, "builtin:blur", 0)
        calls = []
        host = types.SimpleNamespace(container=lambda *_: p, on_filter_dropped=lambda *a: calls.append(("stack",) + a),
                                     add_filter_clip=lambda *a: calls.append(("new",) + a), layer_drop_at=None)
        top = edit.layers(p)[0]
        self.assertEqual(top["id"], first["id"])
        MainWindow.layer_fx_drop(host, "builtin:invert", "", 0)
        self.assertEqual(calls, [("stack", "builtin:invert", first["id"], "", 0)])
        calls.clear()
        MainWindow.layer_fx_drop(host, "builtin:invert", "", 2)               # (between layers lower down: a layer of its own)
        self.assertEqual(calls[0][0], "new")


class StaticFilterLayerTests(unittest.TestCase):
    def test_every_filter_layer_is_at_time_zero_on_its_own_track(self):
        p = proj()
        a = edit.add_filter_clip(p, "builtin:blur", 0, own_track=True)
        b = edit.add_filter_clip(p, "builtin:invert", 0, own_track=True)
        self.assertEqual((a["start_us"], b["start_us"]), (0, 0))              # (a still is drawn at 0: later ones never worked)
        tracks = [t for t in p["tracks"] if a in t["clips"] or b in t["clips"]]
        self.assertEqual(len(tracks), 2)
        c = edit.add_filter_clip(p, "builtin:blur", 0)                         # (on a timeline they still share a track)
        d = edit.add_filter_clip(p, "builtin:invert", 0)
        self.assertGreater(d["start_us"], c["start_us"])


class PivotUnitsTests(unittest.TestCase):
    def test_pivot_shown_in_object_widths(self):
        from kiasecut.ui.inspector import Inspector
        p = proj()
        c = edit.find(p, "c1")[1]
        ins = Inspector()
        ins.resize(400, 900)
        ins.show()
        got = []
        ins.paramEdited.connect(lambda ids, g, k, v: got.append((g, k, v)))
        ins.pivot_units = lambda clip, t: (960 / 200, 540 / 100)               # a 200 x 100 object on a 1920 x 1080 canvas
        c["transform"]["pivot_x"] = 100 / 960                                  # (stored: half-canvas units)
        ins.show_clips([c], 0, 30)
        box = ins.widgets[("transform", "pivot_x")]
        self.assertAlmostEqual(box.value(), 0.5)                               # its right edge
        box.edited.emit(-0.5)                                                  # its left edge
        ins._flush()
        self.assertAlmostEqual(got[-1][2], -100 / 960)
        ins.close()
        ins.deleteLater()


if __name__ == "__main__":
    unittest.main()
