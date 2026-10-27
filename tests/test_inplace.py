"""Renaming and colour picking in place: the name field over the item's name, the colour popup
under what is coloured; Enter / a click elsewhere keeps, Esc does not."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QListWidget, QPushButton, QVBoxLayout, QWidget  # noqa: E402

from kiasecut.ui import inplace  # noqa: E402
from kiasecut.ui.colorpick import pick_color  # noqa: E402

APP = QApplication.instance() or QApplication([])


def glob(w):
    return QRect(w.mapToGlobal(QPoint(0, 0)), w.size())


class InPlaceTests(unittest.TestCase):
    def setUp(self):
        self.win = QWidget()
        lay = QVBoxLayout(self.win)
        self.list = QListWidget()
        self.list.addItems(["aa", "bb", "cc"])
        self.btn = QPushButton("color")
        lay.addWidget(self.list)
        lay.addWidget(self.btn)
        self.win.resize(400, 400)
        self.win.show()
        QTest.qWaitForWindowExposed(self.win)

    def tearDown(self):
        self.win.close()

    def later(self, fn):
        QTimer.singleShot(30, fn)

    def overlay(self, name):
        return next(w for w in self.win.findChildren(QWidget) if w.objectName() == name and w.isVisible())

    def test_name_field_over_the_item(self):
        seen = {}

        def type_it():
            seen["at"] = glob(self.overlay("inplace"))
            f = QApplication.focusWidget()
            QTest.keyClicks(f, "Zq")
            QTest.keyClick(f, Qt.Key_Return)
        self.later(type_it)
        inplace.item_hint(self.list, self.list.item(1))
        self.assertEqual(inplace.ask_name(self.win, "bb"), ("Zq", True))
        row = self.list.visualItemRect(self.list.item(1))
        row = QRect(self.list.viewport().mapToGlobal(row.topLeft()), row.size())
        self.assertTrue(seen["at"].contains(row.center()))

    def test_escape_and_unchanged_keep_the_name(self):
        self.later(lambda: QTest.keyClick(QApplication.focusWidget(), Qt.Key_Escape))
        self.assertFalse(inplace.ask_name(self.win, "bb")[1])
        self.later(lambda: QTest.keyClick(QApplication.focusWidget(), Qt.Key_Return))
        self.assertFalse(inplace.ask_name(self.win, "bb")[1])

    def test_click_elsewhere_keeps_and_goes_nowhere(self):
        clicked = []
        self.btn.clicked.connect(lambda: clicked.append(1))

        def click():
            QTest.keyClicks(QApplication.focusWidget(), "x")
            QTest.mouseClick(self.btn, Qt.LeftButton)
        self.later(click)
        self.assertEqual(inplace.ask_name(self.win, "aa"), ("x", True))
        self.assertEqual(clicked, [])

    def test_colour_under_its_button_live_and_kept(self):
        seen, at = [], {}

        def pick():
            pop = self.overlay("colorpop")
            at["pop"] = glob(pop)
            QTest.keyClicks(pop.hex, "ff0000")
            QTest.keyClick(pop.hex, Qt.Key_Return)
        self.later(pick)
        col = pick_color(self.win, QColor("#00ff00"), "顏色", live=seen.append, anchor=self.btn)
        self.assertEqual(col.name(), "#ff0000")
        self.assertEqual([c.name() for c in seen], ["#ff0000"])
        b = glob(self.btn)                       # (no room under it: just above, starting where it does)
        self.assertEqual((at["pop"].bottom() + 1 + 4, at["pop"].left()), (b.top(), b.left()))

    def test_colour_escape_cancels_untouched_picks_nothing(self):
        cancelled = []

        def try_then_escape():
            pop = self.overlay("colorpop")
            QTest.mouseClick(pop.sv, Qt.LeftButton, pos=QPoint(10, 10))
            QTest.keyClick(pop.hex, Qt.Key_Escape)
        self.later(try_then_escape)
        self.assertIsNone(pick_color(self.win, QColor("#00ff00"), "顏色", cancel=lambda: cancelled.append(1),
                                     anchor=self.btn))
        self.assertEqual(cancelled, [1])
        self.later(lambda: QTest.keyClick(QApplication.focusWidget(), Qt.Key_Return))
        self.assertIsNone(pick_color(self.win, QColor("#00ff00"), "顏色", anchor=self.btn))


if __name__ == "__main__":
    unittest.main()
