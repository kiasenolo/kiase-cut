"""The browser panels by kind (問17): 本專案 / 我的 Library / 內建 buttons for the sources a kind has, the last one picked kept."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from kiasecut.ui.browsers import CATEGORY_BROWSER, MinePage, SourceBrowser  # noqa: E402

APP = QApplication.instance() or QApplication([])


class BrowserTests(unittest.TestCase):
    def test_buttons_only_for_its_sources_and_the_pick_is_kept(self):
        kept = {}
        store = (lambda k, d: kept.get(k, d), kept.__setitem__)
        pages = {"builtin": QLabel("b"), "mine": QLabel("m")}
        b = SourceBrowser("assets", pages, store, default="builtin")
        self.assertEqual([x.text() for x in b.buttons.values()], ["我的 Library", "內建"])     # (in the usual order)
        self.assertEqual(b.source(), "builtin")
        b.set_source("mine")
        self.assertEqual((b.source(), kept), ("mine", {"browser_source/assets": "mine"}))
        again = SourceBrowser("assets", {"builtin": QLabel("b"), "mine": QLabel("m")}, store, default="builtin")
        self.assertEqual(again.source(), "mine")
        again.set_source("project")                                       # (a source it has not: nothing)
        self.assertEqual(again.source(), "mine")
        one = SourceBrowser("x", {"project": QLabel("p")})
        self.assertTrue(one.row.isHidden())                               # (one source: no buttons row)

    def test_mine_page_tabs_and_every_library_category_has_a_home(self):
        page = MinePage([("videos", ("影片", QLabel("v"))), ("sounds", ("音效", QLabel("s")))], lambda: None)
        page.show_category("sounds")
        self.assertEqual(page.tabs.tabText(page.tabs.currentIndex()), "音效")
        page.set_root("/x/Library")
        self.assertIn("/x/Library", page.head.text())
        from kiasecut import userlib
        self.assertEqual(set(CATEGORY_BROWSER), {k for k, _ in userlib.CATEGORIES})


if __name__ == "__main__":
    unittest.main()
