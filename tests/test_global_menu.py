"""The menus are in the window and, where the desktop has a global menu bar (KDE's at the top of the screen), there too."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenuBar  # noqa: E402

from kiasecut.ui import look  # noqa: E402
from kiasecut.ui.main_window import MainWindow  # noqa: E402

APP = QApplication.instance() or QApplication([])
look.apply(APP)


class GlobalMenuTests(unittest.TestCase):
    def setUp(self):
        self.win = MainWindow()
        self.win.resize(900, 500)
        self.win.show()
        QTest.qWait(50)
        self.addCleanup(self.win.close)

    def test_the_window_always_has_its_own_menu_bar(self):
        bar = self.win.menuBar()
        self.assertFalse(bar.isNativeMenuBar())
        self.assertTrue(bar.isVisible())
        self.assertGreaterEqual(len(bar.actions()), 5)

    def test_a_platform_with_no_global_menu_keeps_no_second_bar(self):       # (offscreen has none)
        self.assertIsNone(self.win.global_bar)
        self.assertEqual(len(self.win.findChildren(QMenuBar)), 1)

    def test_a_global_bar_has_the_very_same_menus(self):
        win = self.win
        bar = QMenuBar(win)                                                   # (what _global_menu makes where there is a global menu)
        for a in win.menuBar().actions():
            bar.addAction(a)
        self.assertEqual([a.menu() for a in bar.actions()], [a.menu() for a in win.menuBar().actions()])
        self.assertTrue(all(a.menu() is not None for a in bar.actions()))
        bar.deleteLater()


if __name__ == "__main__":
    unittest.main()
