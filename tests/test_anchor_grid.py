"""The 錨點 9-grid: the anchor goes to a corner / edge / centre of the clip and the clip itself stays where it is."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from kiasecut import edit  # noqa: E402
from kiasecut.ui.preview import Box  # noqa: E402
from test_align_space import APP, scene  # noqa: E402,F401


class AnchorGrid(unittest.TestCase):
    def check(self, **tf):
        p, pv = scene((700, 400))
        edit.find(p, "k0")[1]["transform"].update(tf)
        for gx, gy in ((-1, -1), (1, 0), (0, 1), (0, 0), (1, 1)):
            box = Box(edit.find(p, "k0")[1], 1920, 1080, 0)
            before = [(c.x(), c.y()) for c in box.corners()]
            vals = box.anchor_to(gx, gy)
            for k, v in vals.items():
                edit.set_param(p, "k0", "transform", k, v)
            box = Box(edit.find(p, "k0")[1], 1920, 1080, 0)
            for c, b in zip(box.corners(), before):
                self.assertAlmostEqual(c.x(), b[0], delta=0.05, msg=(gx, gy))
                self.assertAlmostEqual(c.y(), b[1], delta=0.05, msg=(gx, gy))
            g = box.xf().map(__import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(gx * box.bw / 2, gy * box.bh / 2))
            self.assertAlmostEqual(box.anchor_pt().x(), g.x(), delta=0.01)       # 位置 now places that point
            self.assertAlmostEqual(box.anchor_pt().y(), g.y(), delta=0.01)

    def test_plain(self):
        self.check()

    def test_turned_scaled_and_flipped(self):
        self.check(rotation=30.0, scale_y=0.2, flip_h=True)

    def test_with_a_pivot(self):
        self.check(rotation=20.0, pivot_x=0.3, pivot_y=-0.2)


class CornerHandles(unittest.TestCase):
    def test_drag_sets_the_radius_and_shift_sets_all(self):
        from PySide6.QtCore import QPointF, Qt
        p, pv = scene((960, 540))
        edit.find(p, "k0")[1]["transform"].update(scale=1.0)
        pv.resize(1920, 1080)
        pv.set_scene(p, 0, "k0", {"k0"})
        box = pv.selected_box()
        self.assertTrue(pv._has_radius_handles(box))
        key, pt = pv.radius_handles(box, pv._k())[0]
        self.assertEqual(key, "radius_tl")
        d = {"corner": "radius_tl"}
        tl = box.corners()[0]
        got = pv._radius_values(box, d, QPointF(tl.x() + 30, tl.y() + 30), Qt.NoModifier)
        self.assertEqual(got, {"radius_tl": 30.0})
        every = pv._radius_values(box, d, QPointF(tl.x() + 30, tl.y() + 30), Qt.ShiftModifier)
        self.assertEqual(set(every), {"radius_tl", "radius_tr", "radius_br", "radius_bl"})
        edit.set_param(p, "k0", "transform", "radius_tl", 30.0)
        pv.set_scene(p, 0, "k0", {"k0"})
        _, pt = pv.radius_handles(pv.selected_box(), pv._k())[0]
        self.assertAlmostEqual(pt.x(), tl.x() + 30, delta=0.01)

    def test_overlapping_handles_pick_the_nearest_and_double_click_types_a_number(self):
        from unittest import mock
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        p, pv = scene((960, 540))
        edit.find(p, "k0")[1]["transform"].update(scale=1.0, radius_tl=2000.0, radius_tr=2000.0, radius_br=2000.0, radius_bl=2000.0)
        pv.resize(1920, 1080)
        pv.set_scene(p, 0, "k0", {"k0"})
        box = pv.selected_box()
        k = pv._k()
        hs = dict(pv.radius_handles(box, k))
        pt = hs["radius_br"] + QPointF(1, 1)               # (the four meet in the middle: the one under the pointer, not the first)
        self.assertEqual(pv._radius_hit(box, pt, k), "radius_br")
        got = []
        pv.paramsCommitted.connect(lambda cid, g, vals: got.append((cid, g, vals)))
        with mock.patch("kiasecut.ui.preview.QInputDialog.getDouble", return_value=(12.0, True)):
            pv._ask_radius(box, "radius_tr", False)
            pv._ask_radius(box, "radius_tr", True)
        self.assertEqual(got[0], ("k0", "transform", {"radius_tr": 12.0}))
        self.assertEqual(set(got[1][2]), {"radius_tl", "radius_tr", "radius_br", "radius_bl"})

    def test_linked_corners_change_together(self):
        from PySide6.QtCore import QPointF, Qt
        p, pv = scene((960, 540))
        edit.find(p, "k0")[1]["transform"].update(scale=1.0)
        pv.resize(1920, 1080)
        edit.set_param(p, "k0", "transform", "radius_tl", 10.0)
        edit.set_param(p, "k0", "transform", "radius_link", True)
        edit.set_param(p, "k0", "transform", "radius_br", 25.0)
        tf = edit.find(p, "k0")[1]["transform"]
        self.assertEqual([tf[k] for k in ("radius_tl", "radius_tr", "radius_br", "radius_bl")], [25.0] * 4)
        pv.set_scene(p, 0, "k0", {"k0"})
        box = pv.selected_box()
        got = pv._radius_values(box, {"corner": "radius_tr"}, QPointF(box.corners()[1].x() - 40, box.corners()[1].y() + 40), Qt.NoModifier)
        self.assertEqual(len(got), 4)                                      # (no Shift needed)
        edit.set_param(p, "k0", "transform", "radius_link", False)
        edit.set_param(p, "k0", "transform", "radius_tl", 3.0)
        self.assertEqual(edit.find(p, "k0")[1]["transform"]["radius_tr"], 25.0)


if __name__ == "__main__":
    unittest.main()
