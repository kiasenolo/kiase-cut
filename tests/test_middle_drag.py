"""中鍵拖拽: the middle button drags anything that scrolls - the content follows the pointer, a
box with nothing to scroll hands the drag to the area it sits in, and the timeline keeps its own."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget  # noqa: E402

from kiasecut.ui import middledrag  # noqa: E402
from kiasecut.ui.timeline import Timeline  # noqa: E402

APP = QApplication.instance() or QApplication([])
NONE = Qt.KeyboardModifier.NoModifier


def drag(w, a, b, button=Qt.MiddleButton):
    QTest.mousePress(w, button, NONE, a)
    QTest.mouseMove(w, b)
    QTest.mouseRelease(w, button, NONE, b)


class MiddleDragTests(unittest.TestCase):
    def setUp(self):
        middledrag.install()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        self.box = QPlainTextEdit("short")
        self.box.setFixedHeight(80)
        lay.addWidget(self.box)
        self.label = QLabel("tall")
        self.label.setFixedHeight(2000)
        lay.addWidget(self.label)
        self.scroll.setWidget(inner)
        self.scroll.resize(300, 400)
        self.scroll.show()
        QTest.qWaitForWindowExposed(self.scroll)
        self.bar = self.scroll.verticalScrollBar()
        self.bar.setValue(500)

    def tearDown(self):
        self.scroll.close()

    def test_drag_up_scrolls_down(self):
        drag(self.label, QPoint(100, 600), QPoint(100, 480))
        self.assertEqual(self.bar.value(), 620)
        drag(self.label, QPoint(100, 600), QPoint(100, 650))
        self.assertEqual(self.bar.value(), 570)
        self.assertIsNone(QApplication.overrideCursor())

    def test_box_without_scroll_hands_it_on(self):
        self.bar.setValue(0)
        drag(self.box.viewport(), QPoint(50, 40), QPoint(50, 10))
        self.assertEqual(self.bar.value(), 30)

    def test_box_that_scrolls_takes_it(self):
        self.box.setPlainText("\n".join(str(i) for i in range(200)))
        line = self.box.fontMetrics().lineSpacing()
        drag(self.box.viewport(), QPoint(50, 70), QPoint(50, 70 - 5 * line))
        self.assertEqual(self.box.verticalScrollBar().value(), 5)
        self.assertEqual(self.bar.value(), 500)

    def test_left_button_does_not_scroll(self):
        drag(self.label, QPoint(100, 600), QPoint(100, 480), Qt.LeftButton)
        self.assertEqual(self.bar.value(), 500)

    def test_timeline_keeps_its_middle_button(self):
        self.assertIsNone(middledrag._area_at(Timeline()))


if __name__ == "__main__":
    unittest.main()
