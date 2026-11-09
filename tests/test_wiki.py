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

    def test_guides_link_to_pages_that_exist(self):
        known = set(pages(wiki.tree())) | {"types", "rules", "nodes", "fx", "format", "home"} | set(wiki.wikidata.SECTIONS)
        known |= {"node:" + e[1] for _, entries in wiki.categories() for e in entries if e[0] == "node"}
        known |= {"node:" + ref for _, items in wiki.effect_categories() for ref, _ in items}
        for pid, (title, body) in wiki.wikidata.GUIDES.items():
            for target, _ in wiki.LINK.findall(body):
                if target.startswith("node:") and not target.startswith(("node:builtin:", "node:special:")):
                    target = "node:builtin:" + target[5:]
                with self.subTest(guide=pid, link=target):
                    self.assertIn(target, known)
        self.assertNotIn("[[", wiki.render("guide:first")[1])

    def test_the_diagrams_of_the_guides_are_drawn(self):
        import re
        for pid, (_, body) in wiki.wikidata.GUIDES.items():
            for name in re.findall(r'src="diagram:(\w+)"', body):
                self.assertIn(name, wiki.wikidata.DIAGRAMS)
                w, h, nodes, links = wiki.wikidata.DIAGRAMS[name]
                for a, o, b, i in links:
                    self.assertEqual(nodes[a][5][o][0], "out")
                    self.assertEqual(nodes[b][5][i][0], "in")

    def test_every_guide_is_in_a_section(self):
        listed = set(pages(wiki.tree()))
        for pid in wiki.wikidata.GUIDES:
            self.assertIn(pid, listed, pid)
        for sec, (_, _, ids) in wiki.wikidata.SECTIONS.items():
            kind, text = wiki.render(sec)
            for pid in ids:
                self.assertIn(pid, listed)
                self.assertIn(wiki.quote(pid, safe=":"), text)

    def test_search_finds_guides(self):
        self.assertTrue(any(p.startswith("guide:") for p, _, _ in wiki.search("節點效果")))

    def test_filter_format_names_every_header(self):
        import re
        with open(fx.__file__, encoding="utf-8") as fh:
            src = fh.read()
        body = src[src.index("def parse("):src.index("_cache = {}")]
        keys = set(re.findall(r'key == "(\w+)"', body))
        for group in re.findall(r"key in \(([^)]*)\)", body):
            keys |= set(re.findall(r'"(\w+)"', group))
        self.assertTrue({"passes", "socket", "bake", "enable", "param"} <= keys)
        doc = wiki.format_page()
        for key in keys:
            with self.subTest(header=key):
                self.assertIn("// @" + key, doc)

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
