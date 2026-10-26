"""The volume line: with keyframes only a level stretch is dragged (just its points), a
sloping one not at all; Alt drags the whole line."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import curves, edit  # noqa: E402
from kiasecut.ui.timeline import Timeline, level_stretch  # noqa: E402
from test_edit import S, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
NONE, ALT = Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.AltModifier


class VolumeLineTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.c = edit.find(self.p, "c3")[1]                    # sound at 2 - 6 s
        # 1.0 from 0.5 s to 1.5 s, down to 0.5 at 2.5 s, 0.5 to 3.5 s
        self.c["volume"] = {"keys": [[t, v, 0, 0, 0, 0] for t, v in
                                     ((S // 2, 1.0), (3 * S // 2, 1.0), (5 * S // 2, 0.5), (7 * S // 2, 0.5))]}
        self.tl = Timeline()
        self.tl.resize(1000, 400)
        self.tl.set_project(self.p)
        self.tl.px_per_s, self.tl.scroll_s = 100.0, 0.0
        self.tl.set_vzoom(3.0)
        self.row = next(i for i, t in enumerate(self.tl.rows) if self.c in t["clips"])
        self.edits = []
        self.tl.volumeEdited.connect(lambda cid, v: self.edits.append(v))

    def at(self, t):                                           # the line at clip time t
        band = self.tl._vol_band(self.c, self.row)
        return QPoint(round(self.tl._x((self.c["start_us"] + t) / 1e6)),
                      round(self.tl._vol_y(curves.value(self.c["volume"], t), band)))

    def drag(self, t, dy, mods=NONE):
        a = self.at(t)
        QTest.mousePress(self.tl, Qt.LeftButton, mods, a)
        for i in range(1, 6):
            QTest.mouseMove(self.tl, QPoint(a.x(), a.y() + dy * i // 5))
        QTest.mouseRelease(self.tl, Qt.LeftButton, mods, QPoint(a.x(), a.y() + dy))
        return self.edits[-1]["keys"] if self.edits else None

    def test_level_stretch(self):
        keys = self.c["volume"]["keys"]
        self.assertEqual(level_stretch(keys, S), (0, 1))
        self.assertIsNone(level_stretch(keys, 2 * S))          # sloping
        self.assertEqual(level_stretch(keys, 3 * S), (2, 3))
        self.assertEqual(level_stretch(keys, 0), (0,))
        self.assertEqual(level_stretch(keys, 4 * S), (3,))

    def test_a_level_stretch_moves_only_its_points(self):
        keys = self.drag(S, -30)
        self.assertGreater(keys[0][1], 1.0)
        self.assertAlmostEqual(keys[0][1], keys[1][1])
        self.assertEqual((keys[2][1], keys[3][1]), (0.5, 0.5))   # the rest stays

    def test_a_sloping_stretch_is_not_grabbed(self):
        self.drag(2 * S, -30)
        self.assertEqual(self.edits, [])

    def test_alt_moves_everything(self):
        keys = self.drag(2 * S, -30, ALT)
        self.assertTrue(all(k[1] > v for k, v in zip(keys, (1.0, 1.0, 0.5, 0.5))))


if __name__ == "__main__":
    unittest.main()
