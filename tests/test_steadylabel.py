"""SteadyLabel (the playhead's time): words that differ only in their digits ask for no layout and paint nothing but the
label; other words are another size, asked for once."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget  # noqa: E402

from kiasecut.ui import look  # noqa: E402
from kiasecut.ui.steadylabel import SteadyLabel  # noqa: E402

APP = QApplication.instance() or QApplication([])


class Seen(QObject):
    def __init__(self):
        super().__init__()
        self.events = []
        APP.installEventFilter(self)

    def eventFilter(self, obj, e):
        if e.type() in (QEvent.Paint, QEvent.LayoutRequest) and isinstance(obj, QWidget):
            self.events.append(("paint" if e.type() == QEvent.Paint else "layout", obj.objectName()))
        return False

    def take(self):
        APP.processEvents()
        got, self.events = self.events, []
        return got


class SteadyLabelTests(unittest.TestCase):
    def setUp(self):
        was = APP.styleSheet()
        APP.setStyleSheet(look.style_sheet())
        self.addCleanup(APP.setStyleSheet, was)
        self.top = QWidget()
        self.top.setObjectName("top")
        box = QVBoxLayout(self.top)
        self.bar = QWidget()
        self.bar.setObjectName("bar")
        row = QHBoxLayout(self.bar)
        box.addWidget(self.bar)
        self.lab = SteadyLabel("00:00.00", look.BAR)
        self.lab.setObjectName("time")
        self.plain = QLabel("00:00.00")
        self.plain.setObjectName("plain")
        row.addWidget(self.lab)
        row.addWidget(self.plain)
        self.top.resize(400, 120)
        self.top.show()
        self.addCleanup(self.top.close)
        self.seen = Seen()
        self.addCleanup(APP.removeEventFilter, self.seen)
        for _ in range(3):                                               # (what showing it asked for is over)
            self.seen.take()

    def test_other_digits_ask_for_nothing_and_paint_the_label_alone(self):
        size = self.lab.size()
        self.lab.setText("00:01.23")
        self.assertEqual(self.seen.take(), [("paint", "time")])
        self.assertEqual((self.lab.text(), self.lab.size()), ("00:01.23", size))
        self.plain.setText("00:01.23")                                   # (what a QLabel does)
        got = self.seen.take()
        self.assertIn(("layout", "bar"), got)
        self.assertIn(("paint", "top"), got)

    def test_it_fills_itself_with_the_bars_colour_under_a_style_sheet(self):
        self.assertTrue(self.lab.testAttribute(Qt.WA_OpaquePaintEvent))
        APP.setStyleSheet(look.style_sheet())                            # (polished again: the sheet takes the attribute back)
        APP.processEvents()
        self.assertTrue(self.lab.testAttribute(Qt.WA_OpaquePaintEvent))
        at = self.lab.mapTo(self.top, self.lab.rect().topLeft())
        self.assertEqual(self.top.grab().toImage().pixelColor(at.x() + 1, at.y() + 1).name(), look.BAR)

    def test_other_words_are_another_size(self):
        wide = self.lab.width()
        self.lab.setText("1.2.3")
        self.assertIn(("layout", "bar"), self.seen.take() + self.seen.take() + self.seen.take())     # (and the layouts above it, in their turn)
        self.assertLess(self.lab.width(), wide)
        self.lab.setText("7.8.9")
        self.assertEqual(self.seen.take(), [("paint", "time")])
        self.lab.setText("")
        self.assertEqual(self.lab.text(), "")


if __name__ == "__main__":
    unittest.main()
