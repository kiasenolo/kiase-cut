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


class ToolCoverTest(unittest.TestCase):
    def test_a_tool_is_a_widget_of_a_cover_over_the_whole_window_with_a_close_button(self):
        from PySide6.QtWidgets import QLabel
        from kiasecut.ui.tools import ToolCover
        win = QWidget()
        win.resize(500, 300)
        win.show()
        tool = QWidget(None, Qt.Window)
        tool.setWindowTitle("調色盤")
        tool.resize(200, 100)
        QLabel("x", tool)
        cover = ToolCover(win, tool)
        self.assertFalse(cover.isVisible())
        cover.present()
        self.assertFalse(tool.isWindow())
        self.assertEqual(cover.geometry(), win.rect())
        win.resize(700, 400)
        QTest.qWait(20)
        self.assertEqual(cover.geometry(), win.rect())
        cover.close_btn.click()
        self.assertFalse(cover.isVisible())
        cover.present()                                     # (and again)
        self.assertTrue(tool.isVisible())
        QTest.keyClick(cover, Qt.Key_Escape)
        self.assertFalse(cover.isVisible())
        win.close()
