"""menuanim: a menu opens from big, blurred and see-through to what it is, then the effect is gone."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QWidget  # noqa: E402

from kiasecut.ui import look, menuanim  # noqa: E402

APP = QApplication.instance() or QApplication([])
look.apply(APP)
menuanim.install()


def opened():
    host = QWidget()
    host.resize(200, 100)
    host.show()
    m = QMenu(host)
    m.addAction("復原")
    m.addAction("重做")
    m.popup(host.mapToGlobal(QPoint(10, 10)))
    return host, m


class MenuAnimTest(unittest.TestCase):
    def test_a_menu_is_translucent_and_starts_clear_of_the_effect_when_done(self):
        host, m = opened()
        self.assertTrue(m.testAttribute(Qt.WA_TranslucentBackground))
        self.assertIsInstance(m.graphicsEffect(), menuanim.Pop)
        self.assertEqual(m.graphicsEffect().t, 0.0)
        QTest.qWait(menuanim.DURATION_MS + 150)
        self.assertIsNone(m.graphicsEffect())
        m.close()
        host.close()

    def test_it_is_nearly_invisible_at_first_and_whole_at_the_end(self):
        host, m = opened()
        first = m.grab().toImage()
        QTest.qWait(menuanim.DURATION_MS + 150)
        last = m.grab().toImage()

        def alpha(img):
            return sum(img.pixelColor(x, y).alpha() for x in range(0, img.width(), 4) for y in range(0, img.height(), 4))
        self.assertLess(alpha(first), alpha(last) * 0.1)
        m.close()
        host.close()

    def test_the_curve_is_bezier_1_0_0_1(self):
        c = menuanim.curve()
        self.assertLess(c.valueForProgress(0.1), 0.05)      # (almost nothing at first)
        self.assertAlmostEqual(c.valueForProgress(0.5), 0.5, places=1)
        self.assertGreater(c.valueForProgress(0.9), 0.95)

    def test_opening_again_starts_over(self):
        host, m = opened()
        QTest.qWait(100)
        m.close()
        m.popup(host.mapToGlobal(QPoint(10, 10)))
        self.assertEqual(m.graphicsEffect().t, 0.0)
        QTest.qWait(menuanim.DURATION_MS + 150)
        self.assertIsNone(m.graphicsEffect())
        m.close()
        host.close()


if __name__ == "__main__":
    unittest.main()
