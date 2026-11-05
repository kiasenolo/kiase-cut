"""A press on a title of the menu bar while one of its menus is up: the same title closes the menu, another swaps it."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow  # noqa: E402

from kiasecut.ui import menubartap  # noqa: E402

APP = QApplication.instance() or QApplication([])


def mouse(kind, widget, g):
    return QMouseEvent(kind, QPointF(widget.mapFromGlobal(g)), QPointF(g), Qt.LeftButton,
                       Qt.LeftButton if kind == QEvent.MouseButtonPress else Qt.NoButton, Qt.NoModifier)


class MenuBarTapTests(unittest.TestCase):
    def setUp(self):
        menubartap.FORCE = True
        menubartap.install()
        self.addCleanup(menubartap.uninstall)
        self.addCleanup(setattr, menubartap, "FORCE", False)
        self.w = QMainWindow()
        self.w.resize(500, 300)
        self.bar = self.w.menuBar()
        self.bar.setNativeMenuBar(False)
        self.menus = []
        for n in "ABC":
            m = self.bar.addMenu(n)
            m.addAction(n + "1")
            self.menus.append(m)
        self.w.show()
        self.addCleanup(self.w.close)
        QTest.qWait(60)

    def title(self, i):
        return self.bar.mapToGlobal(self.bar.actionGeometry(self.bar.actions()[i]).center())

    def below(self, i):
        return self.bar.mapToGlobal(self.bar.actionGeometry(self.bar.actions()[i]).bottomLeft())

    def tap(self, i):
        """What a finger does with a menu up: the press goes to the menu with the grab, the release too."""
        up = next((m for m in self.menus if m.isVisible()), None)
        target = up if up is not None else self.bar
        g = self.title(i)
        QApplication.sendEvent(target, mouse(QEvent.MouseButtonPress, target, g))
        QApplication.sendEvent(target, mouse(QEvent.MouseButtonRelease, target, g))
        QTest.qWait(20)

    def shown(self):
        return [m.isVisible() for m in self.menus]

    def test_another_title_swaps_the_menu(self):
        self.menus[0].popup(self.below(0))
        QTest.qWait(20)
        self.tap(1)
        self.assertEqual(self.shown(), [False, True, False])
        self.tap(0)
        self.assertEqual(self.shown(), [True, False, False])
        self.tap(2)
        self.assertEqual(self.shown(), [False, False, True])

    def test_the_same_title_closes_it(self):
        self.menus[1].popup(self.below(1))
        QTest.qWait(20)
        self.tap(1)
        self.assertEqual(self.shown(), [False, False, False])


if __name__ == "__main__":
    unittest.main()
