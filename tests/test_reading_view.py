"""A page to read (a QTextBrowser: the wiki, the filter document) does not get the outline / wash an input field has; a field still does."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit, QTextBrowser, QTextEdit  # noqa: E402

from kiasecut.ui import look, motion  # noqa: E402


class ReadingViewTests(unittest.TestCase):
    def test_browser_is_not_a_field(self):
        QApplication.instance() or QApplication([])
        browser, edit, line = QTextBrowser(), QTextEdit(), QLineEdit()
        for w in (browser, edit, line):
            motion.attach_field(w)
        self.assertIsNone(browser.property("kcField"))
        self.assertIsNotNone(edit.property("kcField"))
        self.assertIsNotNone(line.property("kcField"))


if __name__ == "__main__":
    unittest.main()
