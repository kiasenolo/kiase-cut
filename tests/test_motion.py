"""motion.Fader: a button is white at once under the mouse and fades back; its icon and text go black with it."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSize, Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QMenuBar, QComboBox, QDoubleSpinBox, QHBoxLayout, QLineEdit, QPushButton, QRadioButton, QScrollBar, QTabBar, QToolButton, QWidget  # noqa: E402

from kiasecut.ui import icons, look, motion  # noqa: E402

APP = QApplication.instance() or QApplication([])
look.apply(APP)


def setUpModule():
    for w in QApplication.topLevelWidgets():              # (windows other test files left up, at the same corner, would take the mouse)
        if w.isVisible():
            w.hide()


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
        self.assertEqual(motion.of(push).bg, motion.ACTIVE)
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

    def test_a_hop_goes_straight_back_with_no_overshoot(self):
        host, sp = self.make()
        hop = sp._hop
        seen = []
        hop.kick(1)
        for _ in range(20):
            seen.append(hop.off)
            QTest.qWait(30)
        self.assertEqual(seen[0], motion.HOP_PX)
        self.assertTrue(all(x >= -1e-9 for x in seen))                 # (never past where it was)
        self.assertTrue(all(b <= a + 1e-9 for a, b in zip(seen, seen[1:])))
        self.assertEqual(hop.off, 0.0)
        host.close()

    def test_a_hop_that_has_just_begun_is_not_restarted_by_the_next_step_the_same_way(self):
        host, sp = self.make()
        hop = sp._hop
        hop.kick(1)
        QTest.qWait(int(motion.HOP_MS * 0.3) + 80)                   # (past the first third)
        late = hop.off
        hop.kick(1)                                          # (past the first third: a new hop)
        self.assertEqual(hop.off, motion.HOP_PX)
        hop.kick(1)
        QTest.qWait(50)
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


class ToggleTest(unittest.TestCase):
    def make(self):
        host = QWidget()
        lay = QHBoxLayout(host)
        cb, rb = QCheckBox("勾"), QRadioButton("選")
        lay.addWidget(cb)
        lay.addWidget(rb)
        host.resize(240, 60)
        host.show()
        QTest.qWait(60)
        QTest.mouseMove(host, QPoint(239, 59))
        QTest.qWait(30)
        return host, cb, rb

    def test_ticking_a_box_moves_it_to_white_in_a_moment_and_unticking_moves_it_back(self):
        host, cb, rb = self.make()
        t = cb.property("kcToggle")
        self.assertEqual(t.on, 0.0)
        cb.setChecked(True)
        QTest.qWait(60)
        self.assertTrue(0.0 < t.on < 1.0)                         # (on its way)
        QTest.qWait(motion.ON_MS + 100)
        self.assertAlmostEqual(t.on, 1.0, places=2)
        cb.setChecked(False)
        QTest.qWait(motion.FADE_MS + 100)
        self.assertAlmostEqual(t.on, 0.0, places=2)
        host.close()

    def test_a_radio_button_and_a_half_ticked_box_count_as_on(self):
        host, cb, rb = self.make()
        rb.setChecked(True)
        cb.setTristate(True)
        cb.setCheckState(Qt.PartiallyChecked)
        QTest.qWait(motion.ON_MS + 100)
        self.assertAlmostEqual(rb.property("kcToggle").on, 1.0, places=2)
        self.assertAlmostEqual(cb.property("kcToggle").on, 1.0, places=2)
        host.close()

    def test_the_outline_brightens_under_the_mouse_over_the_label_too(self):
        if sys.platform == "win32" and QApplication.platformName() == "offscreen":
            self.skipTest("Qt's offscreen platform on Windows tells no widget that the mouse came in")
        host, cb, rb = self.make()
        t = cb.property("kcToggle")
        QTest.mouseMove(cb, QPoint(cb.width() - 3, 8))              # (on the text, not the box)
        QTest.qWait(motion.ON_MS + 100)
        self.assertAlmostEqual(t.hover, 1.0, places=2)
        QTest.mouseMove(host, QPoint(239, 59))
        QTest.qWait(motion.FADE_MS + 100)
        self.assertAlmostEqual(t.hover, 0.0, places=2)
        host.close()

    def test_a_ticked_box_is_drawn_white_with_a_black_tick(self):
        host, cb, _ = self.make()
        cb.setChecked(True)
        QTest.qWait(motion.ON_MS + 100)
        img = cb.grab().toImage()
        colours = {img.pixelColor(x, y).name() for x in range(img.width()) for y in range(img.height())}
        self.assertIn("#ffffff", colours)
        self.assertIn("#000000", colours)
        host.close()


class TabsTest(unittest.TestCase):
    def make(self, name=""):
        bar = QTabBar()
        bar.setObjectName(name)
        for t in ("素材庫", "效果", "屬性"):
            bar.addTab(t)
        bar.setCurrentIndex(1)
        bar.resize(240, 40)
        bar.show()
        QTest.qWait(60)
        QTest.mouseMove(bar, QPoint(239, 39))
        QTest.qWait(40)
        return bar

    def test_the_open_tab_has_its_numbers_at_one_and_the_others_at_zero(self):
        bar = self.make()
        f = bar.property("kcTabs")
        self.assertEqual([f.get(i)[1] for i in range(3)], [0.0, 1.0, 0.0])
        bar.close()

    def test_a_tab_lights_under_the_mouse_and_fades_back(self):
        bar = self.make()
        f = bar.property("kcTabs")
        QTest.mouseMove(bar, QPoint(bar.tabRect(0).center().x(), 10))
        QTest.qWait(motion.ON_MS + 120)
        self.assertAlmostEqual(f.get(0)[0], 1.0, places=2)
        self.assertEqual(f.get(2)[0], 0.0)
        QTest.mouseMove(bar, QPoint(bar.tabRect(2).center().x(), 10))
        QTest.qWait(motion.FADE_MS + 120)
        self.assertAlmostEqual(f.get(0)[0], 0.0, places=2)
        self.assertAlmostEqual(f.get(2)[0], 1.0, places=2)
        bar.close()

    def test_choosing_a_tab_moves_the_line_over_to_it_in_a_moment(self):
        bar = self.make()
        f = bar.property("kcTabs")
        bar.setCurrentIndex(2)
        QTest.qWait(60)
        self.assertTrue(0.0 < f.get(2)[1] < 1.0)
        QTest.qWait(motion.FADE_MS + 120)
        self.assertEqual([round(f.get(i)[1], 2) for i in range(3)], [0.0, 0.0, 1.0])
        bar.close()

    def test_tabs_are_as_big_as_they_were_in_the_style_sheet(self):
        for name, pad in (("", 14), ("layouts", 8), ("timelines", 10)):         # (31, 25 and 27 px with a font 17 px tall)
            bar = self.make(name)
            self.assertEqual(bar.tabRect(0).height(), bar.fontMetrics().height() + pad)
            bar.close()

    def test_the_open_tab_is_drawn_with_a_white_line_along_its_foot(self):
        bar = self.make()
        QTest.qWait(motion.FADE_MS + 100)
        img = bar.grab().toImage()
        r = bar.tabRect(1)
        self.assertEqual(img.pixelColor(r.center().x(), r.bottom()).name(), "#ffffff")
        self.assertNotEqual(img.pixelColor(bar.tabRect(0).center().x(), bar.tabRect(0).bottom()).name(), "#ffffff")
        bar.close()


class ScrollBarTest(unittest.TestCase):
    def make(self):
        host = QWidget()
        lay = QHBoxLayout(host)
        bar = QScrollBar(Qt.Vertical)
        bar.setRange(0, 100)
        bar.setPageStep(50)
        lay.addWidget(bar)
        host.resize(60, 200)
        host.show()
        QTest.qWait(60)
        QTest.mouseMove(host, QPoint(0, 199))
        QTest.qWait(30)
        t = bar.property("kcThumb")                                 # (the offscreen mouse of an earlier test may be on the new bar: start at rest)
        t.anim.stop()
        t.over = t.held = False
        t.colour = t.goal = t.start = motion.BAR_REST
        return host, bar

    def thumb_at(self, bar, y):
        return bar.property("kcThumb").grab().toImage().pixelColor(bar.width() // 2, y).name()

    def test_the_thumb_is_light_grey_at_rest_and_follows_the_value(self):
        host, bar = self.make()
        r = bar.property("kcThumb").rect_of_thumb()
        self.assertGreater(r.height(), 30)
        mid = r.center().y()
        self.assertEqual(self.thumb_at(bar, mid), motion.BAR_REST.name())
        self.assertNotEqual(bar.property("kcThumb").grab().toImage().pixelColor(1, mid).name(), motion.BAR_REST.name())   # (only 5 px of the 15 are thumb)
        bar.setValue(100)
        QTest.qWait(30)
        self.assertGreater(bar.property("kcThumb").rect_of_thumb().y(), r.y())
        host.close()

    def test_the_thumb_goes_white_under_the_mouse_and_fades_back(self):
        host, bar = self.make()
        t = bar.property("kcThumb")
        mid = t.rect_of_thumb().center()
        QTest.mouseMove(bar, QPoint(0, 0))                          # (the offscreen mouse may be where we want it: send a move)
        QTest.mouseMove(bar, mid)
        QTest.qWait(40)
        self.assertEqual(t.colour, motion.BAR_HOT)
        QTest.mouseMove(host, QPoint(0, 199))
        QTest.qWait(60)
        self.assertNotEqual(t.colour, motion.BAR_HOT)
        QTest.qWait(motion.FADE_MS + 150)
        self.assertEqual(t.colour, motion.BAR_REST)
        host.close()

    def test_the_thumb_is_dark_grey_while_held(self):
        host, bar = self.make()
        t = bar.property("kcThumb")
        mid = t.rect_of_thumb().center()
        QTest.mouseMove(bar, mid)
        QTest.qWait(30)
        QTest.mousePress(bar, Qt.LeftButton, Qt.NoModifier, mid)
        QTest.qWait(motion.PRESS_MS + 100)
        self.assertEqual(t.colour, motion.BAR_HELD)
        QTest.mouseRelease(bar, Qt.LeftButton, Qt.NoModifier, mid)
        QTest.qWait(40)
        self.assertEqual(t.colour, motion.BAR_HOT)
        host.close()


class CatchUpTest(unittest.TestCase):
    def test_a_button_checked_with_its_signals_blocked_still_shows_it(self):
        host = QWidget()
        lay = QHBoxLayout(host)
        a, b = QPushButton("自動寬度"), QPushButton("自動高度")
        for x in (a, b):
            x.setCheckable(True)
            lay.addWidget(x)
        host.resize(300, 60)
        host.show()
        QTest.qWait(60)
        QTest.mouseMove(host, QPoint(299, 59))
        QTest.qWait(30)
        a.setChecked(True)
        QTest.qWait(motion.FADE_MS + 100)
        a.blockSignals(True)                                  # (a panel showing another value: one goes off, the other on, silently)
        b.blockSignals(True)
        a.setChecked(False)
        b.setChecked(True)
        a.blockSignals(False)
        b.blockSignals(False)
        QTest.qWait(motion.FADE_MS + 200)
        self.assertEqual(motion.of(a).bg, motion.REST)
        self.assertEqual(motion.of(b).bg, motion.ACTIVE)
        host.close()

    def test_a_box_ticked_with_its_signals_blocked_still_shows_it(self):
        host = QWidget()
        lay = QHBoxLayout(host)
        cb = QCheckBox("勾")
        lay.addWidget(cb)
        host.resize(120, 60)
        host.show()
        QTest.qWait(60)
        cb.blockSignals(True)
        cb.setChecked(True)
        cb.blockSignals(False)
        QTest.qWait(motion.ON_MS + 200)
        self.assertAlmostEqual(cb.property("kcToggle").on, 1.0, places=2)
        host.close()


class SwatchTest(unittest.TestCase):
    def test_a_colour_button_shows_its_colour_and_keeps_it_under_the_mouse(self):
        host = QWidget()
        lay = QHBoxLayout(host)
        a, b = QPushButton("#336699"), QPushButton("x")
        a.setStyleSheet("background: #336699; color: #fff;")
        b.setStyleSheet("background: rgb(200,100,50); color: #000;")
        lay.addWidget(a)
        lay.addWidget(b)
        host.resize(300, 60)
        host.show()
        QTest.qWait(60)
        QTest.mouseMove(host, QPoint(299, 59))
        QTest.qWait(30)
        img = a.grab().toImage()
        self.assertEqual(img.pixelColor(a.width() // 2, 6).name(), "#336699")
        self.assertEqual(b.grab().toImage().pixelColor(b.width() // 2, 6).name(), "#c86432")
        QTest.mouseMove(a, QPoint(a.width() // 2, a.height() // 2))
        QTest.qWait(40)
        img = a.grab().toImage()
        self.assertEqual(img.pixelColor(a.width() // 2, 6).name(), "#336699")             # (still its colour)
        self.assertEqual(img.pixelColor(a.width() // 2, 0).name(), "#ffffff")              # (in a frame that went white)
        host.close()


class MenuBarTest(unittest.TestCase):
    def make(self):
        bar = QMenuBar()
        for t in ("檔案(&F)", "編輯(&E)", "檢視(&V)"):
            bar.addMenu(t).addAction("項目")
        bar.resize(300, 40)
        bar.show()
        QTest.qWait(60)
        return bar

    def choose(self, bar, action):
        """As the mouse does: over the title, and it is the active one."""
        QTest.mouseMove(bar, bar.actionGeometry(action).center())
        bar.setActiveAction(action)

    def test_the_chosen_title_is_a_white_slanted_tab_and_the_first_is_flat_on_the_left(self):
        bar = self.make()
        first, second = bar.actions()[0], bar.actions()[1]
        self.choose(bar, first)
        QTest.qWait(60)
        img = bar.grab().toImage()
        r = bar.actionGeometry(first)
        lean = motion.menu_slant(bar)
        self.assertGreater(img.pixelColor(r.left() + 1, r.top() + 1).lightness(), 230)                # (flat: white to the very corner)
        self.assertGreater(img.pixelColor(r.left() + 1, r.bottom() - 1).lightness(), 230)
        self.assertGreater(img.pixelColor(r.right() + lean - 3, r.top() + 1).lightness(), 230)        # (the right side leans: wide at the top...)
        self.assertLess(img.pixelColor(r.right() + lean - 3, r.bottom() - 1).lightness(), 100)        # (...and cut at the foot)
        self.choose(bar, second)
        QTest.qWait(60)
        img = bar.grab().toImage()
        r = bar.actionGeometry(second)
        self.assertLess(img.pixelColor(r.left() + 1, r.top() + 1).lightness(), 100)                   # (the top starts a lean in from the box...)
        self.assertGreater(img.pixelColor(r.left() + lean + 2, r.top() + 1).lightness(), 230)
        self.assertGreater(img.pixelColor(r.left() + 2, r.bottom() - 1).lightness(), 230)             # (...and the foot is at the box's left: where the menu is)
        self.assertLess(img.pixelColor(r.left() - 3, r.bottom() - 1).lightness(), 100)
        bar.close()

    def test_the_foot_of_a_tab_is_where_its_menu_opens(self):
        bar = self.make()
        a = bar.actions()[2]
        self.choose(bar, a)
        QTest.qWait(60)
        img = bar.grab().toImage()
        r = bar.actionGeometry(a)
        row = [x for x in range(r.left() - 30, r.right() + 30) if img.pixelColor(x, r.bottom() - 1).lightness() > 200]
        self.assertLessEqual(abs(min(row) - r.left()), 1)                      # (the left of the white at the foot is the left of the box, the menu's left)
        bar.close()

    def test_two_titles_side_by_side_leave_no_space_between_them(self):
        bar = self.make()
        f = bar.property("kcMenuBar")
        f.go = lambda key, target: 1.0                                   # (both white, as in the middle of a sweep of the mouse)
        f.strip.update()
        QTest.qWait(30)
        img = bar.grab().toImage()
        r = bar.actionGeometry(bar.actions()[1])
        lean = motion.menu_slant(bar)
        for y in range(r.top() + 1, r.bottom()):
            joint = round(r.left() + lean - lean * (y - r.top()) / r.height())         # (the shared edge, leaning "/" as it goes down)
            row = [img.pixelColor(x, y).lightness() for x in range(joint - 4, joint + 5)]
            self.assertTrue(all(v > 230 for v in row), (y, row))              # (white across the joint on every row: no seam, no space)
        bar.close()

    def test_a_title_goes_white_at_once_and_back_in_half_a_second(self):
        bar = self.make()
        f = bar.property("kcMenuBar")
        a = bar.actions()[1]
        self.choose(bar, a)
        QTest.qWait(30)
        self.assertEqual(f.v["編輯(&E)"], 1.0)
        QTest.mouseMove(bar, QPoint(299, 39))
        bar.setActiveAction(None)
        QTest.qWait(60)
        self.assertTrue(0.0 < f.v["編輯(&E)"] < 1.0)
        QTest.qWait(motion.FADE_MS + 150)
        self.assertAlmostEqual(f.v["編輯(&E)"], 0.0, places=2)
        bar.close()

    def test_the_text_of_the_chosen_title_is_black_and_has_room_round_it(self):
        bar = self.make()
        self.choose(bar, bar.actions()[1])
        QTest.qWait(60)
        img = bar.grab().toImage()
        r = bar.actionGeometry(bar.actions()[1])
        lean = motion.menu_slant(bar)
        left, right = r.left() + lean // 2, r.right() + lean // 2                  # (the tab at the middle of its height)
        mid = r.center().y()
        dark = [x for x in range(left + 4, right - 4) for y in range(mid - 4, mid + 5) if img.pixelColor(x, y).lightness() < 60]
        self.assertTrue(dark)
        self.assertGreater(min(dark) - left, 10)                                   # (room at the left)
        self.assertGreater(right - max(dark), 10)                                  # (and at the right)
        bar.close()

    def test_a_title_left_lit_when_the_mouse_went_is_put_out(self):
        bar = self.make()
        a, calls = bar.actions()[1], []
        QTest.mouseMove(bar, QPoint(299, 39))
        bar.activeAction = lambda: a                                          # (Qt says it is lit, as it does after a Leave that never came; no menu open)
        bar.setActiveAction = lambda x: calls.append(x)
        QTest.qWait(400)
        self.assertEqual(calls, [None] * len(calls))
        self.assertTrue(calls)
        bar.close()

    def test_a_title_stays_lit_while_the_mouse_is_on_it_or_its_menu_is_open(self):
        bar = self.make()
        a = bar.actions()[1]
        self.choose(bar, a)
        QTest.qWait(400)
        self.assertIs(bar.activeAction(), a)
        QTest.mouseMove(bar, QPoint(299, 39))
        a.menu().popup(bar.mapToGlobal(QPoint(100, 40)))
        QTest.qWait(400)
        self.assertIs(bar.activeAction(), a)
        a.menu().hide()
        bar.close()


class ArrowButtonTest(unittest.TestCase):
    def test_a_tool_button_with_an_arrow_type_draws_its_chevron_and_it_goes_black_on_the_white(self):
        host = QWidget()
        lay = QHBoxLayout(host)
        b = QToolButton()
        b.setAutoRaise(True)
        b.setArrowType(Qt.DownArrow)
        lay.addWidget(b)
        host.resize(120, 60)
        host.show()
        QTest.qWait(60)
        QTest.mouseMove(host, QPoint(119, 59))
        QTest.qWait(30)
        img = b.grab().toImage()
        lit = [(x, y) for x in range(img.width()) for y in range(img.height()) if img.pixelColor(x, y).lightness() > 120]
        self.assertTrue(lit)                                          # (at rest: a light chevron on the panel, not nothing)
        QTest.mouseMove(b, QPoint(b.width() // 2, b.height() // 2))
        QTest.qWait(40)
        img = b.grab().toImage()
        white = sum(1 for x in range(img.width()) for y in range(img.height()) if img.pixelColor(x, y).lightness() > 230)
        dark = [(x, y) for x in range(img.width()) for y in range(img.height()) if img.pixelColor(x, y).lightness() < 60]
        self.assertGreater(white, img.width() * img.height() // 2)    # (white under the mouse)
        self.assertTrue(dark)                                         # (and the chevron is black on it)
        QTest.mouseMove(host, QPoint(119, 59))                        # (the offscreen mouse stays where it was left: give it back)
        QTest.qWait(40)
        host.close()


if __name__ == "__main__":
    unittest.main()
