"""motion.Fader: a button is white at once under the mouse and fades back; its icon and text go black with it."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSize, Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton, QToolButton, QWidget, QHBoxLayout  # noqa: E402

from kiasecut.ui import icons, look, motion  # noqa: E402

APP = QApplication.instance() or QApplication([])
look.apply(APP)


def shown():
    host = QWidget()
    lay = QHBoxLayout(host)
    push = QPushButton("匯入素材")
    tool = QToolButton()
    tool.setIcon(icons.key_icon("off"))
    tool.setIconSize(QSize(16, 16))
    tool.setAutoRaise(True)
    lay.addWidget(push)
    lay.addWidget(tool)
    host.resize(300, 80)
    host.show()
    QTest.qWait(60)
    QTest.mouseMove(host, QPoint(299, 79))            # (the offscreen mouse is where an earlier test left it)
    QTest.qWait(30)
    return host, push, tool


class FaderTest(unittest.TestCase):
    def test_a_button_is_white_at_once_under_the_mouse_and_fades_back_when_it_leaves(self):
        host, push, tool = shown()
        f = motion.of(push)
        self.assertEqual(f.bg, motion.REST)
        QTest.mouseMove(push, QPoint(10, 10))
        QTest.qWait(30)
        self.assertEqual((f.bg, f.ink), (motion.WHITE, motion.BLACK))
        QTest.mouseMove(host, QPoint(150, 70))
        QTest.qWait(40)
        self.assertNotEqual(f.bg, motion.WHITE)                 # (on its way, not there)
        self.assertGreater(f.bg.red(), motion.REST.red())
        QTest.qWait(motion.FADE_MS + 200)
        self.assertEqual(f.bg, motion.REST)
        host.close()

    def test_the_fade_is_quick_at_first_and_has_a_long_tail(self):
        host, push, _ = shown()
        f = motion.of(push)
        QTest.mouseMove(push, QPoint(10, 10))
        QTest.qWait(30)
        QTest.mouseMove(host, QPoint(150, 70))
        QTest.qWait(150)
        early = f.bg.red()
        self.assertLess(early, 255 - (255 - 38) * 0.5)          # (more than half way back after 0.15 s of 0.5)
        host.close()

    def test_pressing_makes_it_grey(self):
        host, push, _ = shown()
        f = motion.of(push)
        QTest.mouseMove(push, QPoint(10, 10))
        QTest.mousePress(push, Qt.LeftButton, Qt.NoModifier, QPoint(10, 10))
        QTest.qWait(30)
        self.assertEqual(f.dst[0], motion.GREY)                   # (on its way to grey: pressed)
        QTest.mouseRelease(push, Qt.LeftButton, Qt.NoModifier, QPoint(10, 10))
        host.close()

    def test_checked_buttons_rest_grey(self):
        host, push, _ = shown()
        push.setCheckable(True)
        push.setChecked(True)
        QTest.qWait(motion.FADE_MS + 100)
        self.assertEqual(motion.of(push).bg, motion.GREY)
        host.close()

    def test_icons_are_drawn_black_on_a_white_button_and_left_alone_otherwise(self):
        host, _, tool = shown()
        f = motion.of(tool)
        self.assertFalse(look.Style._dark_ink(f))                 # (at rest: the icon as it is)
        QTest.mouseMove(tool, QPoint(8, 8))
        QTest.qWait(30)
        self.assertTrue(look.Style._dark_ink(f))
        pm = look.Style._tinted(tool.icon(), QSize(16, 16), f.ink)
        img = pm.toImage()
        opaque = [img.pixelColor(x, y) for x in range(img.width()) for y in range(img.height()) if img.pixelColor(x, y).alpha() > 200]
        self.assertTrue(opaque)
        self.assertTrue(all(c.red() < 10 and c.green() < 10 and c.blue() < 10 for c in opaque))
        host.close()

    def test_a_disabled_button_is_faint(self):
        host, push, _ = shown()
        push.setEnabled(False)
        QTest.qWait(motion.FADE_MS + 100)
        self.assertEqual(motion.of(push).bg, motion.FAINT)
        host.close()


if __name__ == "__main__":
    unittest.main()
