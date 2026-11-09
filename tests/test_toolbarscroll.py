"""ToolbarScroll: a row of buttons wider than its panel scrolls sideways; it no longer makes the panel (the window) wider."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton  # noqa: E402

from kiasecut.ui.toolbarscroll import ToolbarScroll  # noqa: E402

APP = QApplication.instance() or QApplication([])


class ToolbarScrollTests(unittest.TestCase):
    def test_narrow(self):
        row = QHBoxLayout()
        for i in range(20):
            row.addWidget(QPushButton(f"button number {i}"))
        bar = ToolbarScroll(row, "bar")
        self.assertGreater(bar.sizeHint().width(), 1000)            # (what the buttons want)
        self.assertLess(bar.minimumSizeHint().width(), 200)         # (what the window has to give)
        self.assertEqual(bar.inner.objectName(), "bar")
        bar.resize(300, bar.sizeHint().height())
        bar.show()
        APP.processEvents()
        h = bar.horizontalScrollBar()
        self.assertGreater(h.maximum(), 0)                          # (scrolls)
        self.assertEqual(bar.height(), bar.sizeHint().height())


if __name__ == "__main__":
    unittest.main()
