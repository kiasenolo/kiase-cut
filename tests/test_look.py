"""The look is the program's own on every platform: started under another style and light
colours (as on Windows), an effect's box still has no white border."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QPalette  # noqa: E402
from PySide6.QtWidgets import (QApplication, QFrame, QLabel, QScrollArea, QStyle,  # noqa: E402
                               QVBoxLayout, QWidget)

from kiasecut.ui import look  # noqa: E402

APP = QApplication.instance() or QApplication([])


class LookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        APP.setStyle("windows")
        APP.setPalette(APP.style().standardPalette())    # light, like Windows'
        look.apply(APP)

    def test_breeze_sizes_and_dark_colours(self):
        self.assertEqual(APP.style().pixelMetric(QStyle.PM_LayoutLeftMargin), 6)   # Breeze's, not Windows'
        self.assertEqual(APP.palette().color(QPalette.Window).name(), look.COLOURS["Window"])

    def test_effect_box_has_no_border(self):
        root = QWidget()
        lay = QVBoxLayout(root)
        box = QFrame()
        box.setFrameShape(QFrame.StyledPanel)
        QVBoxLayout(box).addWidget(QLabel("模糊"))
        lay.addWidget(box)
        scroll = QScrollArea()
        lay.addWidget(scroll)
        root.resize(200, 200)
        root.show()
        APP.processEvents()
        self.assertEqual(box.frameWidth(), 0)
        self.assertEqual(scroll.frameWidth(), 2)
        img = root.grab().toImage()
        g = box.geometry()
        for x, y in ((g.left(), g.center().y()), (g.right(), g.center().y()), (g.center().x(), g.top())):
            self.assertEqual(img.pixelColor(x, y).name(), "#111111")
        edge = img.pixelColor(scroll.geometry().left(), scroll.geometry().center().y())
        self.assertEqual(edge.name(), QColor(look.FRAME).name())
        root.close()

    def test_the_accent_is_the_systems(self):
        p = APP.palette()
        p.setColor(QPalette.Accent, QColor("#0078d4"))          # as Windows' platform gives it
        APP.setPalette(p)
        look.apply(APP)
        self.assertEqual(APP.palette().color(QPalette.Highlight).name(), "#0078d4")
        self.assertIn("border-color: #0078d4", APP.styleSheet())
        self.assertEqual(APP.palette().color(QPalette.Window).name(), look.COLOURS["Window"])

    def test_standard_icons_are_breeze(self):
        for sp in (QStyle.SP_DialogOkButton, QStyle.SP_MessageBoxWarning, QStyle.SP_DirIcon):
            self.assertFalse(APP.style().standardIcon(sp).pixmap(16).isNull())


if __name__ == "__main__":
    unittest.main()
