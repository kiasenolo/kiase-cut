"""Rulers, reference lines (dragged out of the rulers, moved, taken back) and the grid snap."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402

from kiasecut.ui.preview import RULER_PX  # noqa: E402
from test_align_space import APP, scene  # noqa: E402,F401


def mouse(pv, kind, pt, mods=Qt.NoModifier):
    t = {"press": QEvent.MouseButtonPress, "move": QEvent.MouseMove, "release": QEvent.MouseButtonRelease}[kind]
    e = QMouseEvent(t, QPointF(*pt), QPointF(*pt), Qt.LeftButton, Qt.LeftButton, mods)
    {"press": pv.mousePressEvent, "move": pv.mouseMoveEvent, "release": pv.mouseReleaseEvent}[kind](e)


def to_screen(pv, cx, cy):
    r = pv._rect()
    return r.x() + cx / pv.W * r.width(), r.y() + cy / pv.H * r.height()


class Guides(unittest.TestCase):
    def setUp(self):
        self.p, self.pv = scene((300, 200))
        self.pv.resize(1000, 600)
        self.pv.set_rulers(True)
        self.got = []
        self.pv.guidesCommitted.connect(self.got.append)

    def test_drag_out_of_the_left_ruler_makes_an_upright_line(self):
        sx, sy = to_screen(self.pv, 700, 400)
        mouse(self.pv, "press", (RULER_PX / 2, sy))
        mouse(self.pv, "move", (sx, sy))
        mouse(self.pv, "release", (sx, sy))
        self.assertEqual(len(self.got), 1)
        self.assertEqual(self.got[0]["y"], [])
        self.assertAlmostEqual(self.got[0]["x"][0], 700, delta=3)

    def test_let_go_on_the_ruler_makes_none(self):
        sx, sy = to_screen(self.pv, 700, 400)
        mouse(self.pv, "press", (sx, RULER_PX / 2))
        mouse(self.pv, "move", (sx, 200))
        mouse(self.pv, "move", (sx, RULER_PX / 2))
        mouse(self.pv, "release", (sx, RULER_PX / 2))
        self.assertEqual(self.got[-1], {"x": [], "y": []})

    def test_clips_settle_on_a_guide_and_on_the_grid(self):
        self.pv.view["guides"] = {"x": [613], "y": []}
        dx, dy, g = self.pv._snap((200, 400, 100, 200), 410, 3, [], 6)
        self.assertAlmostEqual(200 + dx, 613, delta=0.01)           # its left edge
        self.pv.view["guides"] = None
        self.pv.set_grid(snap=True, size=50)
        dx, dy, g = self.pv._snap((203, 403, 101, 201), 0, 0, [], 6)
        self.assertAlmostEqual((203 + dx) % 50, 0, delta=0.01)


if __name__ == "__main__":
    unittest.main()
