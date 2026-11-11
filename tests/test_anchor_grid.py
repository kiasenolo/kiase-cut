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


if __name__ == "__main__":
    unittest.main()
