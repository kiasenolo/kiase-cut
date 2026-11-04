"""Icons (ui/icons.py): a checked tool button has a dark background, so its icon is drawn light there."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut.ui import icons  # noqa: E402

APP = QApplication.instance() or QApplication([])


def brightest(ic, state):
    img = ic.pixmap(24, 24, QIcon.Normal, state).toImage()
    return max((img.pixelColor(x, y).lightness() for x in range(img.width()) for y in range(img.height())
                if img.pixelColor(x, y).alpha() > 128), default=0)


class IconTests(unittest.TestCase):
    def test_checked_icon_is_light_by_default(self):
        self.assertGreater(brightest(icons.icon("height"), QIcon.On), 150)

    def test_light_background_asks_for_dark_ink(self):
        self.assertLess(brightest(icons.icon("link", 16, icons.DARK), QIcon.On), 60)


if __name__ == "__main__":
    unittest.main()
