"""Panel layouts: the panels as docks (built-in arrangements, side panels leaving their tabs
when the selection has no use for them, the side panel in use) and layout files in
KiaseCut/preset/layout."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QTabBar  # noqa: E402

from kiasecut import layouts  # noqa: E402
from kiasecut.ui.docks import ORDER, SIDE, Panels  # noqa: E402

APP = QApplication.instance() or QApplication([])


class FileTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.where = layouts.folder(self.dir)

    def test_folder(self):
        self.assertEqual(self.where, os.path.join(self.dir, "KiaseCut", "preset", "layout"))

    def test_names(self):
        self.assertEqual(layouts.clean_name("  a/b:c  "), "a_b_c")
        for bad in ("", "  ", "製圖", "一般剪片", "..."):
            with self.assertRaises(ValueError):
                layouts.clean_name(bad)

    def test_write_read_rename_remove(self):
        self.assertEqual(layouts.list_user(self.where), [])          # (no folder yet)
        layouts.write(self.where, "B", b"\x00\x01state", ["curves"])
        layouts.write(self.where, "a", b"x", [])
        self.assertEqual(layouts.list_user(self.where), ["a", "B"])
        self.assertEqual(layouts.read(self.where, "B"), (b"\x00\x01state", ["curves"]))
        layouts.rename(self.where, "B", "c")
        self.assertEqual(layouts.list_user(self.where), ["a", "c"])
        with self.assertRaises(ValueError):
            layouts.rename(self.where, "a", "c")
        layouts.remove(self.where, "a")
        self.assertEqual(layouts.list_user(self.where), ["c"])

    def test_not_a_layout(self):
        os.makedirs(self.where)
        with open(os.path.join(self.where, "x.json"), "w") as fh:
            fh.write('{"something": 1}')
        with self.assertRaises(ValueError):
            layouts.read(self.where, "x")

    def test_keys(self):
        self.assertEqual(layouts.title(layouts.builtin_key("design")), "製圖")
        self.assertEqual(layouts.title(layouts.user_key("我的")), "我的")


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.win = QMainWindow()
        self.win.resize(1400, 900)
        self.pn = Panels(self.win, {k: QLabel(k) for k in ORDER})
        self.pn.arrange("edit")
        self.win.show()
        QApplication.processEvents()

    def tearDown(self):
        self.win.close()

    def test_edit_layout_tabs(self):
        tabs = {d.key for d in self.win.tabifiedDockWidgets(self.pn["library"])}
        self.assertEqual(tabs, {"assets", "userlib", "vfx", "compounds"})
        self.assertEqual(self.win.dockWidgetArea(self.pn["timeline"]), Qt.BottomDockWidgetArea)
        self.assertFalse(self.pn["library"].isFloating())
        self.assertIs(self.pn["preview"].titleBarWidget(), self.pn["preview"].title)   # on its own: a title
        self.assertIs(self.pn["library"].titleBarWidget(), self.pn["library"].blank)  # in tabs: none

    def test_design_layout_closes_some(self):
        self.pn.arrange("design")
        self.assertEqual(sorted(self.pn.closed()), ["beats", "curves", "subtitles"])
        self.assertFalse(self.pn["curves"].isVisible())
        self.assertTrue(self.pn["compounds"].isVisible())

    def test_unusable_side_panel_leaves_its_tabs_and_comes_back(self):
        mask = self.pn["mask"]
        self.pn.set_usable("mask", False)
        self.assertTrue(mask.isHidden() and mask.auto_hidden and not mask.user_closed)
        self.pn.set_usable("mask", True)
        self.assertFalse(mask.isHidden())
        self.assertIn(self.pn["inspector"], self.win.tabifiedDockWidgets(mask))      # back in its tabs

    def test_unusable_panel_on_its_own_says_so(self):
        mask = self.pn["mask"]
        mask.setFloating(True)
        self.pn.set_usable("mask", False)
        self.assertFalse(mask.isHidden())
        self.assertEqual(mask.stack.currentIndex(), 1)

    def test_closed_on_purpose_stays_closed(self):
        self.pn["beats"].close()
        self.assertTrue(self.pn["beats"].user_closed)
        self.pn.set_usable("beats", True)
        self.assertTrue(self.pn["beats"].isHidden())
        self.pn.show("beats")
        self.assertFalse(self.pn["beats"].isHidden() or self.pn["beats"].user_closed)

    def test_state_round_trip(self):
        self.pn["curves"].setFloating(True)
        self.pn["subtitles"].close()
        self.pn.set_usable("mask", False)                # hidden for the selection: not saved as closed
        state, closed = self.pn.state(), self.pn.closed()
        self.assertEqual(closed, ["subtitles"])
        self.pn.arrange("design")
        self.assertTrue(self.pn.restore(state, closed))
        QApplication.processEvents()
        self.assertTrue(self.pn["curves"].isFloating())
        self.assertTrue(self.pn["subtitles"].isHidden() and self.pn["subtitles"].user_closed)
        self.assertFalse(self.pn["mask"].isHidden())     # back: the selection decides again
        self.assertFalse(self.pn["beats"].user_closed)
        self.assertFalse(self.pn.restore(b"nonsense", []))

    def test_side_panel_in_use(self):
        got = []
        self.pn.activeChanged.connect(got.append)
        self.pn["mask"].raise_()                         # its tab picked
        QApplication.processEvents()
        self.assertEqual(self.pn.active, "mask")
        self.assertTrue(self.pn.is_active("mask"))
        self.pn["inspector"].setFloating(True)           # side by side: a click picks it
        QApplication.processEvents()
        w = self.pn["inspector"].widget()
        QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, QPoint(5, 5))
        self.assertEqual(self.pn.active, "inspector")
        self.assertIn("mask", got)

    def test_tabs_dragged_as_one_from_their_bar(self):
        ins, lib = self.pn["inspector"], self.pn["library"]
        bar = next(b for b in self.win.findChildren(QTabBar) if b.metaObject().className() == "QMainWindowTabBar"
                   and "屬性" in [b.tabText(i) for i in range(b.count())])
        empty = QPoint(bar.width() - 3, bar.height() // 2)
        self.assertLess(bar.tabAt(empty), 0)
        QTest.mousePress(bar, Qt.LeftButton, Qt.NoModifier, empty)
        QTest.mouseMove(bar, empty + QPoint(-30, 20))
        self.assertIs(self.pn["effects"].parentWidget(), ins.parentWidget())     # dragged together
        to = ins.mapFromGlobal(lib.mapToGlobal(QPoint(5, lib.height() // 2)))  # left of the library
        QTest.mouseMove(ins, to)
        QTest.mouseRelease(ins, Qt.LeftButton, Qt.NoModifier, to)
        QTest.qWait(400)                                 # (the docking animation)
        self.assertLess(ins.x(), lib.x())
        self.assertFalse(ins.isFloating())
        self.assertEqual({d.key for d in self.win.tabifiedDockWidgets(ins)}, set(SIDE[1:]))

    def test_lone_panel_dragged_with_the_tabs_that_left_for_the_selection(self):
        ins, lib = self.pn["inspector"], self.pn["library"]
        for k in SIDE[1:]:                               # nothing selected: only 屬性 is left
            self.pn.set_usable(k, False)
        QTest.qWait(20)
        self.assertIs(ins.titleBarWidget(), ins.title)   # looks like one on its own
        QTest.mousePress(ins.title, Qt.LeftButton, Qt.NoModifier, QPoint(40, 8))
        QTest.mouseMove(ins.title, QPoint(70, 28))
        self.assertTrue(all(self.pn[k].parentWidget() is ins.parentWidget() for k in SIDE[1:]))
        to = ins.mapFromGlobal(lib.mapToGlobal(QPoint(5, lib.height() // 2)))
        QTest.mouseMove(ins, to)
        QTest.mouseRelease(ins, Qt.LeftButton, Qt.NoModifier, to)
        QTest.qWait(400)
        self.assertLess(ins.x(), lib.x())
        self.assertTrue(all(self.pn[k].isHidden() and self.pn[k].auto_hidden for k in SIDE[1:]))   # away again
        for k in SIDE[1:]:
            self.pn.set_usable(k, True)
        self.assertEqual({d.key for d in self.win.tabifiedDockWidgets(ins)}, set(SIDE[1:]))   # back with it

    def test_tabs_floated_together_have_a_title_bar_to_bring_them_back(self):
        ins, lib = self.pn["inspector"], self.pn["library"]
        bar = next(b for b in self.win.findChildren(QTabBar) if b.metaObject().className() == "QMainWindowTabBar"
                   and "屬性" in [b.tabText(i) for i in range(b.count())])
        empty = QPoint(bar.width() - 3, bar.height() // 2)
        QTest.mousePress(bar, Qt.LeftButton, Qt.NoModifier, empty)
        QTest.mouseMove(bar, empty + QPoint(-30, 20))
        out = ins.mapFromGlobal(self.win.mapToGlobal(QPoint(self.win.width() + 300, 300)))   # off the window
        QTest.mouseMove(ins, out)
        QTest.mouseRelease(ins, Qt.LeftButton, Qt.NoModifier, out)
        QTest.qWait(50)
        self.assertTrue(ins.in_floating_tabs() and ins.parentWidget().isWindow())
        self.assertIs(ins.titleBarWidget(), ins.title)   # the window's frame
        self.assertFalse(ins.title.buttons["float"].isVisible())
        QTest.mousePress(ins.title, Qt.LeftButton, Qt.NoModifier, QPoint(40, 8))
        QTest.mouseMove(ins.title, QPoint(80, 30))
        to = ins.mapFromGlobal(lib.mapToGlobal(QPoint(5, lib.height() // 2)))
        QTest.mouseMove(ins, to)
        QTest.mouseRelease(ins, Qt.LeftButton, Qt.NoModifier, to)
        QTest.qWait(400)
        self.assertFalse(ins.in_floating_tabs())         # back in the main window, all of them
        self.assertLess(ins.x(), lib.x())
        self.assertEqual({d.key for d in self.win.tabifiedDockWidgets(ins)}, set(SIDE[1:]))
        self.assertIs(ins.titleBarWidget(), ins.blank)


if __name__ == "__main__":
    unittest.main()
