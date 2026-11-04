"""The fullscreen preview as a widget over the window (Android: a second window of the program is a poor thing there)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from kiasecut.ui import look  # noqa: E402
from kiasecut.ui.preview import FullscreenPreview  # noqa: E402

APP = QApplication.instance() or QApplication([])
look.apply(APP)


class CoverTest(unittest.TestCase):
    def setUp(self):
        self.win = QWidget()
        self.win.resize(600, 400)
        self.win.show()
        QTest.qWait(40)
        self.fs = FullscreenPreview(self.win)
        self.addCleanup(self.win.close)

    def test_it_covers_the_window_as_a_widget_of_it_and_goes_on_covering(self):
        self.fs.present()
        self.assertFalse(self.fs.isWindow())
        self.assertEqual(self.fs.geometry(), self.win.rect())
        self.win.resize(800, 500)
        QTest.qWait(20)
        self.assertEqual(self.fs.geometry(), self.win.rect())

    def test_a_double_click_closes_it_and_it_can_be_deleted_a_turn_later(self):
        got = []
        self.fs.closed.connect(lambda: got.append(1))
        self.fs.present()
        QTest.mouseDClick(self.fs.canvas, Qt.LeftButton, Qt.NoModifier, QPoint(20, 20))
        self.assertEqual(got, [1])
        self.assertFalse(self.fs.isVisible())
        self.fs.deleteLater()
        QTest.qWait(30)

    def test_escape_closes_it(self):
        self.fs.present()
        QTest.keyClick(self.fs, Qt.Key_Escape)
        self.assertFalse(self.fs.isVisible())


if __name__ == "__main__":
    unittest.main()
