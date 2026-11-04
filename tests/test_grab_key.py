"""G / R / S: Blender's grab, rotate and scale of the selected clip on the canvas, and G on the timeline."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut.ui.preview import Preview  # noqa: E402
from kiasecut.ui.timeline import HEADER_W, Timeline  # noqa: E402
from test_edit import S, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


def key(widget, k, text=""):
    e = QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier, text)
    return widget.eventFilter(widget, e)


class PreviewGrab(unittest.TestCase):
    def setUp(self):
        self.pv = Preview()
        self.pv.resize(960, 540)
        self.pv.set_scene(proj(), 0, "c1", {"c1"})
        self.live, self.kept, self.back = [], [], []
        self.pv.paramsLive.connect(lambda cid, g, v: self.live.append((g, v)))
        self.pv.paramsCommitted.connect(lambda cid, g, v: self.kept.append((g, v)))
        self.pv.grabCancelled.connect(lambda: self.back.append(1))

    def grab(self, kind, to):
        self.assertTrue(self.pv._can_grab(kind))
        self.pv._grab_begin(kind)
        m0 = self.pv.drag["m0"]
        self.pv.drag["m"] = QPointF(m0.x() + to[0], m0.y() + to[1])
        self.pv._grab_update()

    def test_g_moves_by_how_far_the_pointer_went_and_a_click_keeps_it(self):
        self.grab("move", (100, 0))
        self.assertEqual(self.live[-1][0], "transform")
        self.assertGreater(self.live[-1][1]["x"], 0)
        self.pv._grab_end(True)
        self.assertEqual(self.kept[-1][1], self.live[-1][1])
        self.assertIsNone(self.pv.drag)

    def test_x_y_and_typed_numbers(self):
        self.grab("move", (100, 80))
        self.assertNotEqual(self.live[-1][1]["y"], 0)
        self.pv.drag["axis"] = "x"
        self.pv._grab_update()
        self.assertEqual(self.live[-1][1]["y"], 0)
        self.assertTrue(self.pv._grab_key(QKeyEvent(QEvent.KeyPress, Qt.Key_Y, Qt.NoModifier, "y"), True))
        self.assertEqual(self.pv.drag["axis"], "y")
        for k, t in ((Qt.Key_2, "2"), (Qt.Key_0, "0"), (Qt.Key_0, "0")):
            self.pv._grab_key(QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier, t), True)
        self.assertEqual(self.pv.drag["num"], "200")
        self.assertEqual(self.live[-1][1]["x"], 0)
        self.assertAlmostEqual(self.live[-1][1]["y"], -200 / 540, places=2)

    def test_esc_puts_it_back(self):
        self.grab("move", (100, 0))
        self.assertTrue(self.pv._grab_key(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier), True))
        self.assertEqual((self.kept, self.back), ([], [1]))
        self.assertIsNone(self.pv.drag)

    def test_r_turns_and_s_scales(self):
        self.pv._grab_begin("rotate")
        d = self.pv.drag
        d["m"] = QPointF(d["m0"].x() + 200, d["m0"].y() + 200)
        d["num"] = "30"
        self.pv._grab_update()
        self.assertAlmostEqual(self.live[-1][1]["rotation"], 30.0)
        self.pv._grab_end(False)
        self.pv._grab_begin("gscale")
        self.pv.drag["num"] = "2"
        self.pv._grab_update()
        self.assertAlmostEqual(self.live[-1][1]["scale"], 2 * self.pv.selected_box().s, places=3)
        self.pv._grab_end(True)
        self.assertEqual(self.kept[-1][1]["scale"], self.live[-1][1]["scale"])

    def test_the_keys_start_it_only_with_a_clip_selected(self):
        self.assertIsNotNone(self.pv.selected_box())
        self.pv.set_scene(proj(), 0, None, None)
        self.assertFalse(self.pv._can_grab("move"))


class TimelineGrab(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.tl = Timeline()
        self.tl.resize(1200, 300)
        self.tl.set_project(self.p)
        self.tl.px_per_s, self.tl.scroll_s = 50.0, 0.0
        self.moved, self.back = [], []
        self.tl.moveRequested.connect(lambda cid, start, track: self.moved.append((cid, start, track)))
        self.tl.grabCancelled.connect(lambda: self.back.append(1))
        self.tl.select(self.tl.selected_clips()[0] if self.tl.selected_clips() else next(c for t in self.tl.rows for c in t["clips"]))

    def start(self):
        c = self.tl.selected
        row = next(i for i, t in enumerate(self.tl.rows) if any(k["id"] == c["id"] for k in t["clips"]))
        self.tl._grab_begin(c, row)
        self.tl.drag["x0"] = HEADER_W + 100
        self.tl.drag.pop("prow0", None)

    def drag_by(self, dx):
        e = type("E", (), {"modifiers": lambda s: Qt.NoModifier})()
        self.tl._mouse_move(e, QPointF(HEADER_W + 100 + dx, self.tl.tops[self.tl.drag["row0"]] + 5))

    def test_g_moves_the_clip_along_time_and_a_click_keeps_it(self):
        self.start()
        self.drag_by(100)                                           # 2 s later
        self.assertTrue(self.tl.drag["moved"])
        self.tl._grab_end(True)
        cid, start, _track = self.moved[-1]
        self.assertEqual(cid, "c1")
        self.assertAlmostEqual(start, 2 * S, delta=S // 10)

    def test_esc_leaves_it_and_says_so(self):
        self.start()
        self.drag_by(100)
        self.tl._grab_end(False)
        self.assertEqual((self.moved, self.back), ([], [1]))
        self.assertIsNone(self.tl.drag)


if __name__ == "__main__":
    unittest.main()
