"""Arrow keys nudge the selected clips by a canvas pixel (Shift: ten)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit  # noqa: E402
from test_align_space import APP, apply, ext, scene  # noqa: E402,F401


class Nudge(unittest.TestCase):
    def test_pixels_and_direction(self):
        p, pv = scene((300, 200), (700, 500))
        self.assertTrue(pv._can_nudge())
        before = [ext(p, f"k{i}") for i in range(2)]
        apply(p, pv.nudge_moves(10, -1))
        for i in range(2):
            e = ext(p, f"k{i}")
            self.assertAlmostEqual(e[0] - before[i][0], 10, delta=0.01)
            self.assertAlmostEqual(e[2] - before[i][2], -1, delta=0.01)

    def test_signal(self):
        p, pv = scene((300, 200))
        got = []
        pv.movesCommitted.connect(got.append)
        pv.nudge(1, 0)
        self.assertEqual(list(got[0]), ["k0"])

    def test_flip_toggles_and_applies(self):
        p, pv = scene((300, 200))
        got = []
        pv.paramsCommitted.connect(lambda cid, g, v: got.append((cid, g, v)))
        pv.flip("flip_h")
        self.assertEqual(got, [("k0", "transform", {"flip_h": True})])
        edit.set_param(p, "k0", "transform", "flip_h", True)
        pv.set_scene(p, 0, "k0", {"k0"})
        pv.flip("flip_h")
        self.assertEqual(got[-1][2], {"flip_h": False})


if __name__ == "__main__":
    unittest.main()
