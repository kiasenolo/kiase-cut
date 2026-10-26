"""Number fields with Blender's soft and hard limits: dragging keeps inside the soft limits,
dragging with Alt or typing goes on to the hard ones (or has none)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut.ui.inspector import PARAMS, SpinBox, hard_limits  # noqa: E402

APP = QApplication.instance() or QApplication([])
NONE, ALT = Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.AltModifier


class LimitTests(unittest.TestCase):
    def spin(self, v=0.0, hard=(None, None)):
        s = SpinBox()
        s.set_limits(0.0, 10.0, *hard)
        s.setSingleStep(1.0)
        s.setDecimals(1)
        s.show_value(v)
        s.show()
        return s

    def drag(self, s, dy, mods=NONE):
        le = s.lineEdit()
        start = QPoint(le.width() // 2, le.height() // 2)
        QTest.mousePress(le, Qt.LeftButton, NONE, start)
        for i in range(1, 11):                               # in small steps, as a hand would
            QTest.mouseMove(le, QPoint(start.x(), start.y() - dy * i // 10))
            if mods != NONE:                                 # (QTest.mouseMove takes no modifiers)
                from PySide6.QtGui import QMouseEvent
                pos = QPoint(start.x(), start.y() - dy * i // 10)
                ev = QMouseEvent(QMouseEvent.MouseMove, pos, le.mapToGlobal(pos), Qt.NoButton, Qt.LeftButton, mods)
                QApplication.sendEvent(le, ev)
        QTest.mouseRelease(le, Qt.LeftButton, NONE, QPoint(start.x(), start.y() - dy))
        return s.value()

    def test_drag_stops_at_the_soft_limit(self):
        self.assertEqual(self.drag(self.spin(5.0), 200), 10.0)
        self.assertEqual(self.drag(self.spin(5.0), -200), 0.0)

    def test_alt_drag_passes_it(self):
        self.assertGreater(self.drag(self.spin(5.0), 200, ALT), 10.0)
        self.assertEqual(self.drag(self.spin(5.0, (0.0, 20.0)), 400, ALT), 20.0)     # up to the hard one

    def test_typing_passes_it(self):
        s = self.spin(5.0)
        s.lineEdit().setText("250")
        s.interpretText()
        self.assertEqual(s.value(), 250.0)
        s = self.spin(5.0, (0.0, 100.0))
        s.lineEdit().setText("250")
        s.interpretText()
        self.assertEqual(s.value(), 100.0)

    def test_a_value_beyond_the_soft_limit_drags_from_there(self):
        s = self.spin(50.0)
        self.assertEqual(self.drag(s, -10), 45.0)          # (not snapped back to 10)

    def test_known_hard_limits(self):
        self.assertEqual(hard_limits("transform", "opacity"), (0.0, 1.0))
        self.assertEqual(hard_limits("transform", "x"), (None, None))
        self.assertEqual(hard_limits("asset", "stroke"), (0, None))
        self.assertEqual(hard_limits("asset", "arc_sweep"), (0, 100))

    def test_scale_and_font_size_reach_zero(self):
        for group, key in (("transform", "scale"), ("transform", "scale_y"), ("text", "size")):
            self.assertEqual(hard_limits(group, key)[0], 0.0)
            soft_lo = next(f[2] for f in PARAMS[group] if f[0] == key)
            self.assertEqual(soft_lo, 0.0)                   # plain dragging gets there too


if __name__ == "__main__":
    unittest.main()
