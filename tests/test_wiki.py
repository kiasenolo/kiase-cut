"""The 說明 Wiki: every page of the tree renders, the legend holds the node editor's own socket colours, and the search finds nodes."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kiasecut import fx, wiki  # noqa: E402


def pages(tree):
    for pid, _, children in tree:
        yield pid
        yield from pages(children)


class WikiTests(unittest.TestCase):
    def test_every_page_renders(self):
        for pid in pages(wiki.tree()):
            with self.subTest(page=pid):
                kind, text = wiki.render(pid)
                self.assertTrue(text.strip())

    def test_every_menu_node_has_a_page(self):
        keys = {e[1] for _, entries in wiki.categories() for e in entries if e[0] == "node"}
        for k in keys:
            with self.subTest(node=k):
                self.assertIn("<h1>", wiki.node_page(k))

    def test_every_builtin_filter_is_in_the_wiki(self):
        listed = {e[1] for _, entries in wiki.categories() for e in entries if e[0] == "node"}
        listed |= {ref for _, items in wiki.effect_categories() for ref, _ in items}
        for ref in wiki.known_refs():
            if ref != "builtin:nodes/picture":
                self.assertIn(ref, listed, ref)

    def test_the_menu_has_no_node_that_is_missing(self):
        for ref in wiki.nodemenu.placed():
            self.assertIn(ref, wiki.known_refs(), ref)

    def test_every_menu_node_says_how_it_is_used(self):
        for _, entries in wiki.categories():
            for e in entries:
                if e[0] == "node" and e[1] != "shapes":
                    with self.subTest(node=e[1]):
                        self.assertIn(e[1].replace("builtin:", "", 1), wiki.wikidata.USAGE)

    def test_usage_is_for_pages_that_exist(self):
        keys = {e[1].replace("builtin:", "", 1) for _, entries in wiki.categories() for e in entries if e[0] == "node"}
        for k in wiki.wikidata.USAGE:
            self.assertIn(k, keys)

    def test_a_node_page_has_its_wiring(self):
        text = wiki.node_page("builtin:nodes/mix")
        for word in ("怎麼用", "接法範例", "怎麼接", "係數（向量）"):
            self.assertIn(word, text)

    def test_legend_colours_are_the_node_editors(self):
        try:
            from kiasecut.ui.node_editor import SOCKET_COLORS
        except ImportError:
            self.skipTest("no Qt")
        for key, _, _ in wiki.TYPES:
            self.assertIn(key, SOCKET_COLORS)
            self.assertIn(SOCKET_COLORS[key].lstrip("#"), wiki.dot(key))

    def test_links_round_trip(self):
        ref = "node:builtin:nodes/mix"
        self.assertEqual(wiki.page_of(wiki.SCHEME + wiki.quote(ref, safe=":")), ref)

    def test_search(self):
        self.assertTrue(any("Vignette" in t for _, t, _ in wiki.search("vignette")))
        self.assertEqual(wiki.search("  "), [])


if __name__ == "__main__":
    unittest.main()
