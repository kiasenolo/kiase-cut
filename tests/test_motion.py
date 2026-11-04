"""motion.Fader: a button is white at once under the mouse and fades back; its icon and text go black with it."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSize, Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox, QDoubleSpinBox, QHBoxLayout, QLineEdit, QPushButton, QToolButton, QWidget  # noqa: E402

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
        self.assertFalse(f.dark())                 # (at rest: the icon as it is)
        QTest.mouseMove(tool, QPoint(8, 8))
        QTest.qWait(30)
        self.assertTrue(f.dark())
        pm = motion.tinted(tool.icon(), QSize(16, 16), f.ink)
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


def fields():
    host = QWidget()
    lay = QHBoxLayout(host)
    line, spin, combo = QLineEdit("abc"), QDoubleSpinBox(), QComboBox()
    combo.addItems(["一", "二"])
    for w in (line, spin, combo):
        lay.addWidget(w)
    host.resize(420, 80)
    host.show()
    QTest.qWait(60)
    QTest.mouseMove(host, QPoint(419, 79))
    QTest.qWait(30)
    return host, line, spin, combo


class FieldTest(unittest.TestCase):
    def test_every_kind_of_field_has_one_frame_and_the_line_edit_inside_a_spin_box_has_none(self):
        host, line, spin, combo = fields()
        for w in (line, spin, combo):
            self.assertIsNotNone(w.property("kcField"))
            self.assertEqual(w.property("kcField").frame.geometry(), w.rect())
        self.assertIsNone(spin.lineEdit().property("kcField"))
        host.close()

    def test_the_outline_brightens_under_the_mouse_and_fades_back(self):
        host, line, spin, _ = fields()
        fr = line.property("kcField").frame
        self.assertEqual(fr.hover, 0.0)
        QTest.mouseMove(line, QPoint(10, 8))
        QTest.qWait(motion.IN_MS + 150)
        self.assertAlmostEqual(fr.hover, 1.0, places=2)
        QTest.mouseMove(host, QPoint(419, 79))
        QTest.qWait(motion.FADE_MS + 150)
        self.assertAlmostEqual(fr.hover, 0.0, places=2)
        QTest.mouseMove(spin.lineEdit(), QPoint(10, 8))             # (the mouse is on the line edit inside: the spin box is under it too)
        QTest.qWait(motion.IN_MS + 150)
        self.assertAlmostEqual(spin.property("kcField").frame.hover, 1.0, places=2)
        host.close()

    def test_typing_in_a_field_takes_the_outline_for_a_line_underneath(self):
        host, line, spin, _ = fields()
        fr = line.property("kcField").frame
        line.setFocus()
        QTest.qWait(motion.IN_MS + 150)
        self.assertAlmostEqual(fr.focus, 1.0, places=2)
        spin.lineEdit().setFocus()
        QTest.qWait(motion.FADE_MS + 150)
        self.assertAlmostEqual(fr.focus, 0.0, places=2)
        self.assertAlmostEqual(spin.property("kcField").frame.focus, 1.0, places=2)
        host.close()

    def test_a_disabled_field_does_not_light_up(self):
        host, line, _, _ = fields()
        line.setEnabled(False)
        QTest.qWait(60)
        QTest.mouseMove(line, QPoint(10, 8))
        QTest.qWait(motion.IN_MS + 100)
        self.assertEqual(line.property("kcField").frame.hover, 0.0)
        host.close()


class HopTest(unittest.TestCase):
    def make(self):
        from kiasecut.ui.inspector import SpinBox
        host = QWidget()
        lay = QHBoxLayout(host)
        sp = SpinBox()
        sp.setRange(0, 100)
        sp.setValue(42)
        lay.addWidget(sp)
        host.resize(120, 50)
        host.show()
        QTest.qWait(60)
        return host, sp

    def test_a_number_that_grows_hops_up_and_one_that_shrinks_hops_down_and_both_come_to_rest(self):
        host, sp = self.make()
        hop = sp._hop
        hop.kick(1)
        self.assertEqual(hop.off, motion.HOP_PX)
        m = sp.lineEdit().textMargins()
        self.assertGreater(m.bottom(), 0)
        self.assertEqual(m.top(), 0)
        QTest.qWait(motion.HOP_MS + 100)
        self.assertEqual(sp.lineEdit().textMargins().bottom(), 0)
        hop.kick(-1)
        self.assertEqual(hop.off, -motion.HOP_PX)
        self.assertGreater(sp.lineEdit().textMargins().top(), 0)
        QTest.qWait(motion.HOP_MS + 100)
        self.assertEqual((sp.lineEdit().textMargins().top(), sp.lineEdit().textMargins().bottom()), (0, 0))
        host.close()

    def test_a_hop_that_has_just_begun_is_not_restarted_by_the_next_step_the_same_way(self):
        host, sp = self.make()
        hop = sp._hop
        hop.kick(1)
        QTest.qWait(150)
        late = hop.off
        hop.kick(1)                                          # (past the first third: a new hop)
        self.assertEqual(hop.off, motion.HOP_PX)
        hop.kick(1)
        QTest.qWait(10)
        self.assertLess(hop.off, motion.HOP_PX)              # (the one that began just now runs on)
        hop.kick(-1)                                         # (the other way: at once)
        self.assertEqual(hop.off, -motion.HOP_PX)
        host.close()

    def test_dragging_the_number_kicks_it_the_way_the_value_goes(self):
        host, sp = self.make()
        QTest.mousePress(sp.lineEdit(), Qt.LeftButton, Qt.NoModifier, QPoint(20, 10))
        sp._hop.kick = lambda d: seen.append(d)
        seen = []
        QTest.mouseMove(sp.lineEdit(), QPoint(20, 2))
        QTest.mouseMove(sp.lineEdit(), QPoint(20, 14))
        QTest.mouseRelease(sp.lineEdit(), Qt.LeftButton, Qt.NoModifier, QPoint(20, 14))
        self.assertIn(1, seen)
        self.assertIn(-1, seen)
        host.close()


if __name__ == "__main__":
    unittest.main()
