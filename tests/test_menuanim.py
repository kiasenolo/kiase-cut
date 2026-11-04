"""menuanim: a menu (or a combo box's list) is unrolled from its top down, then the effect is gone; closing is at once."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox, QMenu, QWidget  # noqa: E402

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

    def test_it_shows_nothing_at_first_then_unrolls_from_the_top_to_the_whole_menu(self):
        host, m = opened()
        first = m.grab().toImage()
        QTest.qWait(80)
        mid = m.grab().toImage()
        QTest.qWait(menuanim.DURATION_MS + 150)
        last = m.grab().toImage()

        def rows(img):                                       # the rows (from the top) that have something in them
            return [y for y in range(img.height()) if any(img.pixelColor(x, y).alpha() > 0 for x in range(0, img.width(), 4))]
        self.assertLess(len(rows(first)), 4)
        got = rows(mid)
        self.assertTrue(0 < len(got) < len(rows(last)))
        self.assertEqual(got, list(range(got[0], got[-1] + 1)))     # (a block from the top, no more)
        self.assertEqual(got[0], rows(last)[0])
        m.close()
        host.close()

    def test_the_curve_is_bezier_0_point5_0_1(self):
        c = menuanim.curve()
        self.assertGreater(c.valueForProgress(0.1), 0.35)   # (most of it at once)
        self.assertLess(c.valueForProgress(0.1), 0.8)
        self.assertGreater(c.valueForProgress(0.5), 0.85)
        self.assertGreater(c.valueForProgress(0.95), 0.98)

    def test_a_combo_boxs_list_unrolls_too(self):
        host = QWidget()
        box = QComboBox(host)
        box.addItems(["一", "二", "三"])
        host.resize(200, 100)
        host.show()
        QTest.qWait(40)
        box.showPopup()
        QTest.qWait(20)
        container = box.view().window()
        self.assertIsInstance(container.graphicsEffect(), menuanim.Pop)
        QTest.qWait(menuanim.DURATION_MS + 150)
        self.assertIsNone(container.graphicsEffect())
        box.hidePopup()
        host.close()

    def test_closing_is_at_once_with_no_fade_effect_on_it(self):
        host, m = opened()
        QTest.qWait(menuanim.DURATION_MS + 150)
        m.close()
        self.assertFalse(m.isVisible())
        self.assertIsNone(m.graphicsEffect())
        host.close()

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
