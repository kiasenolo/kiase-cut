"""Menus and lists with many entries (ui/bigcombo.py, ui/searchbox.py): a search box over a list with a scroll bar of its own."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox, QMenu  # noqa: E402

from kiasecut import fx, menugroups  # noqa: E402
from kiasecut.ui import bigcombo, searchbox  # noqa: E402
from kiasecut.ui.groupmenu import GroupMenu  # noqa: E402

APP = QApplication.instance() or QApplication([])


def combo(n):
    c = QComboBox()
    c.addItems([f"Font {i}" for i in range(n)])
    c.resize(200, 26)
    c.show()
    bigcombo.watch(c)
    return c


class BigComboTests(unittest.TestCase):
    def test_a_big_combo_opens_a_searchable_list(self):
        c = combo(300)
        got = []
        c.activated.connect(got.append)
        QTest.mouseClick(c, Qt.LeftButton)
        pop = c.popup
        self.assertEqual(pop.list.count(), 300)
        self.assertLess(pop.height(), 600)                                   # (a list that scrolls, not 300 rows)
        pop.search.setText("font 12")
        self.assertEqual([pop.list.item(i).text() for i in range(pop.list.count())][:2], ["Font 12", "Font 120"])
        QTest.keyClick(pop.search, Qt.Key_Down)
        pop.search.returnPressed.emit()
        self.assertEqual((got, c.currentText()), ([120], "Font 120"))

    def test_a_small_combo_keeps_qts_list(self):
        c = combo(10)
        QTest.mouseClick(c, Qt.LeftButton)
        self.assertFalse(hasattr(c, "popup"))
        c.hidePopup()

    def test_a_menu_search_lists_the_matches_and_picks(self):
        menu = QMenu()
        picked = []
        box = searchbox.install(menu, picked.append, "搜尋…")
        menu.addAction("x")
        for i in range(100):
            box.add("cat", f"Item {i}", f"builtin:item{i}")
        searchbox.finish(box)
        menu.show()
        box.search.setText("item 5")
        self.assertEqual(box.results.count(), 11)
        self.assertFalse(menu.actions()[2].isVisible())                      # (the categories are hidden while searching)
        box.search.returnPressed.emit()
        self.assertEqual(picked, ["builtin:item5"])
        box.search.setText("zzz")
        self.assertFalse(box.results.item(0).flags() & Qt.ItemIsEnabled)


class GroupTests(unittest.TestCase):
    def test_the_long_node_menus_have_groups_that_hold_every_choice_once(self):
        for ref, name in (("builtin:nodes/math", "op"), ("builtin:nodes/mix", "blend"), ("builtin:nodes/vector_math", "op")):
            q = next(p for p in fx.get(ref).params if p.name == name)
            groups = menugroups.of(q.items)
            self.assertIsNotNone(groups, ref)
            flat = [n for _t, g in groups for n in g]
            self.assertEqual(sorted(flat), sorted(q.items), ref)
        self.assertIsNone(menugroups.of(["a", "b"]))

    def test_a_clip_s_blend_modes_are_grouped_and_a_click_picks(self):
        c = QComboBox()
        names = ["正常", "正片疊底", "濾色", "疊加", "變暗", "變亮", "顏色減淡", "顏色加深", "強光", "柔光", "差值", "排除", "相加"]
        c.addItems(names)
        c.setProperty("kcGroups", menugroups.of(names))
        c.show()
        bigcombo.watch(c)
        got = []
        c.activated.connect(got.append)
        QTest.mouseClick(c, Qt.LeftButton)
        pop = c.popup
        self.assertIsInstance(pop, GroupMenu)
        lst = pop.lists[1]
        lst.itemClicked.emit(lst.item(1))
        self.assertEqual((c.currentText(), got), ("正片疊底", [c.currentIndex()]))


if __name__ == "__main__":
    unittest.main()
