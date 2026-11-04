"""escapekey: Esc takes the focus out of a field; the Back key (Android) is an Esc."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (QApplication, QDialog, QDoubleSpinBox, QLineEdit, QPlainTextEdit, QPushButton,  # noqa: E402
                               QVBoxLayout, QWidget)

from kiasecut.ui import escapekey  # noqa: E402

APP = QApplication.instance() or QApplication([])
escapekey.install()


class Host(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        self.line = QLineEdit("abc")
        self.spin = QDoubleSpinBox()
        self.text = QPlainTextEdit()
        self.ro = QLineEdit("read only")
        self.ro.setReadOnly(True)
        self.btn = QPushButton("b")
        for w in (self.line, self.spin, self.text, self.ro, self.btn):
            lay.addWidget(w)
        self.keys = []

    def keyPressEvent(self, e):
        self.keys.append(e.key())
        super().keyPressEvent(e)


class EscTest(unittest.TestCase):
    def setUp(self):
        self.host = Host()
        self.host.show()
        self.host.activateWindow()
        QTest.qWait(60)
        self.addCleanup(self.host.close)

    def focus(self, w):
        w.setFocus()
        QTest.qWait(20)
        self.assertIs(QApplication.focusWidget(), w)

    def test_esc_takes_the_focus_out_of_a_line_a_number_and_a_text_box(self):
        for w in (self.host.line, self.host.spin, self.host.text):
            self.focus(w)
            QTest.keyClick(w, Qt.Key_Escape)
            QTest.qWait(20)
            self.assertIsNot(QApplication.focusWidget(), w)

    def test_the_text_typed_is_kept(self):
        self.focus(self.host.line)
        QTest.keyClicks(self.host.line, "xyz")
        QTest.keyClick(self.host.line, Qt.Key_Escape)
        QTest.qWait(20)
        self.assertEqual(self.host.line.text(), "abcxyz")

    def test_esc_on_a_button_or_a_read_only_field_is_left_alone(self):
        self.focus(self.host.btn)
        QTest.keyClick(self.host.btn, Qt.Key_Escape)
        QTest.qWait(20)
        self.assertIs(QApplication.focusWidget(), self.host.btn)
        self.assertFalse(escapekey.is_field(self.host.ro))

    def test_esc_still_reaches_the_window_around_the_field(self):
        self.focus(self.host.line)
        QTest.keyClick(self.host.line, Qt.Key_Escape)
        QTest.qWait(20)
        self.assertIn(Qt.Key_Escape, self.host.keys)

    def test_a_dialog_asked_to_close_by_esc_still_closes(self):
        d = QDialog()
        lay = QVBoxLayout(d)
        line = QLineEdit()
        lay.addWidget(line)
        d.show()
        QTest.qWait(40)
        line.setFocus()
        QTest.keyClick(line, Qt.Key_Escape)
        QTest.qWait(30)
        self.assertFalse(d.isVisible())

    def test_back_is_esc_where_it_is_asked_to_be(self):
        escapekey.FORCE = True
        try:
            self.focus(self.host.line)
            self.host.keys.clear()
            QTest.keyClick(self.host.line, Qt.Key_Back)
            QTest.qWait(30)
            self.assertIn(Qt.Key_Escape, self.host.keys)
            self.assertNotIn(Qt.Key_Back, self.host.keys)
            self.assertIsNot(QApplication.focusWidget(), self.host.line)       # (and it left the field)
        finally:
            escapekey.FORCE = False

    def test_back_is_left_alone_on_a_desktop(self):
        self.focus(self.host.btn)
        self.host.keys.clear()
        QTest.keyClick(self.host.btn, Qt.Key_Back)
        self.assertIn(Qt.Key_Back, self.host.keys)


if __name__ == "__main__":
    unittest.main()
