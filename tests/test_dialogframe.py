"""dialogframe: a dialog gets a title bar (✕ closes, dragging moves) and its contents sit below it."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox, QVBoxLayout  # noqa: E402

from kiasecut.ui import dialogframe  # noqa: E402

APP = QApplication.instance() or QApplication([])
dialogframe.install()


def made():
    d = QDialog()
    d.setWindowTitle("刪除剪輯")
    lay = QVBoxLayout(d)
    label = QLabel("確定？")
    lay.addWidget(label)
    d.resize(300, 200)
    d.show()
    QTest.qWait(30)
    return d, label


class FrameTest(unittest.TestCase):
    def test_a_dialog_gets_a_bar_and_its_contents_sit_below_it(self):
        d, label = made()
        bar = d.findChild(dialogframe.Bar)
        self.assertIsNotNone(bar)
        self.assertTrue(d.windowFlags() & Qt.FramelessWindowHint)
        self.assertGreaterEqual(label.mapTo(d, QPoint(0, 0)).y(), dialogframe.BAR_H)
        self.assertEqual(bar.width(), d.width() - 2 * dialogframe.OUTLINE)
        d.close()

    def test_it_is_framed_once_and_popups_and_frameless_dialogs_are_left_alone(self):
        d, _ = made()
        self.assertEqual(len(d.findChildren(dialogframe.Bar)), 1)
        d.close()
        d2 = QDialog()
        d2.setWindowFlag(Qt.FramelessWindowHint)
        d2.show()
        self.assertIsNone(d2.findChild(dialogframe.Bar))
        d2.close()
        p = QDialog()
        p.setWindowFlags(Qt.Popup)
        p.show()
        self.assertIsNone(p.findChild(dialogframe.Bar))
        p.close()

    def test_the_close_mark_rejects(self):
        d, _ = made()
        bar = d.findChild(dialogframe.Bar)
        done = []
        d.rejected.connect(lambda: done.append(1))
        QTest.mouseClick(bar, Qt.LeftButton, Qt.NoModifier, QPoint(bar.width() - 20, bar.height() // 2))
        self.assertEqual(done, [1])

    def test_dragging_the_bar_moves_the_dialog(self):
        d, _ = made()
        bar = d.findChild(dialogframe.Bar)
        before = d.pos()
        QTest.mousePress(bar, Qt.LeftButton, Qt.NoModifier, QPoint(40, 20))
        QTest.mouseMove(bar, QPoint(90, 60))
        QTest.mouseRelease(bar, Qt.LeftButton, Qt.NoModifier, QPoint(90, 60))
        self.assertNotEqual(d.pos(), before)
        self.assertTrue(d.isVisible())
        d.close()

    def test_a_message_box_is_framed_too(self):
        box = QMessageBox(QMessageBox.Question, "刪除", "確定要刪除這個剪輯嗎？", QMessageBox.Yes | QMessageBox.No)
        box.show()
        QTest.qWait(30)
        bar = box.findChild(dialogframe.Bar)
        self.assertIsNotNone(bar)
        yes = box.button(QMessageBox.Yes)
        self.assertGreaterEqual(yes.mapTo(box, QPoint(0, 0)).y(), dialogframe.BAR_H)
        box.close()


if __name__ == "__main__":
    unittest.main()
