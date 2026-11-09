"""The gradient bar (a colour ramp's stops): a click adds a stop, a stop dragged on goes past the others and they stay."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut.ui.gradientbar import GradientBar  # noqa: E402

APP = QApplication.instance() or QApplication([])
STOPS = [[0.0, [0, 0, 0, 1]], [0.3, [1, 0, 0, 1]], [0.6, [0, 1, 0, 1]], [1.0, [1, 1, 1, 1]]]


class GradientBarTests(unittest.TestCase):
    def bar(self):
        b = GradientBar()
        self.addCleanup(b.close)
        b.resize(300, b.height())
        b.show()
        b.set_stops(STOPS)
        return b

    def test_a_stop_dragged_past_another_leaves_it(self):
        b = self.bar()
        y = int(b.bar().bottom() + 12)
        QTest.mousePress(b, Qt.LeftButton, Qt.NoModifier, QPoint(int(b.x_of(0.3)), y))
        for x in range(int(b.x_of(0.3)), int(b.x_of(0.8)), 4):
            QTest.mouseMove(b, QPoint(x, y))
        QTest.mouseRelease(b, Qt.LeftButton, Qt.NoModifier, QPoint(int(b.x_of(0.8)), y))
        self.assertEqual(len(b.stops), 4)
        self.assertEqual([s[1] for s in b.stops][2], [1, 0, 0, 1])                # (the red one is third now)
        self.assertEqual([s[1] for s in b.stops][1], [0, 1, 0, 1])                # (the green one stayed)
        self.assertEqual(b.sel, 2)
        xs = [s[0] for s in b.stops]
        self.assertEqual(xs, sorted(xs))

    def test_a_click_on_the_bar_adds_a_stop(self):
        b = self.bar()
        QTest.mouseClick(b, Qt.LeftButton, Qt.NoModifier, QPoint(int(b.x_of(0.45)), int(b.bar().center().y())))
        self.assertEqual(len(b.stops), 5)


if __name__ == "__main__":
    unittest.main()
