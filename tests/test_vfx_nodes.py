"""VFX Nodes: node effects shared by link - one graph, many clips, parameter values of their own."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from kiasecut import edit, fx, nodegraph as ng, project  # noqa: E402
from kiasecut.ui.effects_panel import EffectsPanel  # noqa: E402
from kiasecut.ui.vfxnodes import VfxNodePanel  # noqa: E402
from test_edit import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


def two_uses():
    p = proj()
    h = edit.History(p)
    vid = h.do("new", edit.new_vfx_node, "光暈")
    a = h.do("a", edit.add_vfx_effect, "c1", vid)
    b = h.do("b", edit.add_vfx_effect, "c2", vid)
    return p, h, vid, a, b


class VfxNodes(unittest.TestCase):
    def test_uses_share_one_graph_and_keep_their_own_values(self):
        p, h, vid, a, b = two_uses()
        self.assertIs(a["graph"], b["graph"])
        self.assertIs(a["graph"], p["vfx_nodes"][vid]["graph"])
        m = h.do("node", edit.add_graph_node, "c1", a["id"], {"type": "filter", "ref": "builtin:nodes/math"})
        self.assertIn(m, b["graph"]["nodes"])                           # (added through clip 1, there on clip 2)
        self.assertIn(m + ".value", b["params"])                         # (and its values start at their defaults)
        edit.set_param(p, "c1", "fx:" + a["id"], m + ".value", 0.25)
        self.assertNotEqual(a["params"][m + ".value"], b["params"][m + ".value"])

    def test_it_survives_saving_undo_and_a_copy_of_the_effect(self):
        p, h, vid, a, b = two_uses()
        m = h.do("node", edit.add_graph_node, "c2", b["id"], {"type": "filter", "ref": "builtin:nodes/math"})
        text = project.dumps(p)
        stored = json.loads(text)
        self.assertNotIn("graph", stored["timelines"][0]["tracks"][0]["clips"][0]["effects"][0])      # (the clip keeps only the link)
        self.assertIn(m, stored["vfx_nodes"][vid]["graph"]["nodes"])
        q = project.link(project.normalize(json.loads(text)))
        e1 = edit.find(q, "c1")[1]["effects"][0]
        e2 = edit.find(q, "c2")[1]["effects"][0]
        self.assertIs(e1["graph"], e2["graph"])
        self.assertIn(m, e1["graph"]["nodes"])
        h.undo()                                                         # (the node's addition is undone for both)
        a2, b2 = edit.find(p, "c1")[1]["effects"][0], edit.find(p, "c2")[1]["effects"][0]
        self.assertNotIn(m, a2["graph"]["nodes"])
        self.assertIs(a2["graph"], b2["graph"])
        copied = h.do("copy", edit.put_effect, "c1", a2)                 # (copying the effect is another use)
        self.assertIs(copied["graph"], a2["graph"])

    def test_unsharing_and_deleting_leave_copies(self):
        p, h, vid, a, b = two_uses()
        h.do("own", edit.unshare_vfx, "c2", b["id"])
        b = edit.find(p, "c2")[1]["effects"][0]
        self.assertNotIn("vfx", b)
        self.assertIsNot(a["graph"], b["graph"])
        self.assertEqual(a["graph"], b["graph"])
        h.do("gone", edit.delete_vfx_node, vid)
        self.assertEqual(p["vfx_nodes"], {})
        a = edit.find(p, "c1")[1]["effects"][0]
        self.assertNotIn("vfx", a)
        self.assertTrue(a["graph"]["nodes"])

    def test_a_node_effect_becomes_a_vfx_node_and_a_node_can_be_renamed(self):
        p = proj()
        h = edit.History(p)
        e = h.do("add", edit.add_effect, "c1", fx.GRAPH)
        vid = h.do("share", edit.vfx_from_effect, "c1", e["id"], "我的特效")
        self.assertEqual(p["vfx_nodes"][vid]["name"], "我的特效")
        use = h.do("use", edit.add_vfx_effect, "c2", vid)
        self.assertIs(use["graph"], e["graph"])
        h.do("rename", edit.rename_vfx_node, vid, " 新名字 ")
        self.assertEqual(p["vfx_nodes"][vid]["name"], "新名字")
        with self.assertRaises(edit.EditError):
            edit.vfx_from_effect(p, "c1", e["id"])
        self.assertEqual({k: len(v) for k, v in project.vfx_uses(p).items()}, {vid: 2})

    def test_a_compound_kept_in_the_library_carries_its_nodes(self):
        p, h, vid, a, b = two_uses()
        stored = json.loads(project.dumps(p))
        fake = {"k1": {"tracks": stored["timelines"][0]["tracks"]}}
        project.inline_vfx(fake, p)
        e = fake["k1"]["tracks"][0]["clips"][0]["effects"][0]
        self.assertNotIn("vfx", e)
        self.assertIn("graph", e)


class VfxPanels(unittest.TestCase):
    def test_the_list_says_how_many_clips_use_each(self):
        p, h, vid, a, b = two_uses()
        panel = VfxNodePanel()
        panel.set_project(p, project.vfx_uses(p))
        self.assertEqual([panel.list.item(i).text() for i in range(panel.list.count())], ["光暈  ×2"])
        got = []
        panel.applyRequested.connect(got.append)
        panel.list.setCurrentRow(0)
        next(b for b in panel.findChildren(QPushButton) if b.text() == "套用到選取的片段").click()
        self.assertEqual(got, [vid])

    def test_new_effect_menu_lists_the_nodes_or_goes_straight_to_a_new_one(self):
        p = proj()
        panel = EffectsPanel()
        panel.show_clips([edit.find(p, "c1")[1]], 0, 30)
        got = []
        panel.vfxRequested.connect(lambda ids, vid: got.append((ids, vid)))
        panel._fill_menu()
        direct = [a for a in panel.add_btn.menu().actions() if a.text().startswith("節點效果")]
        self.assertEqual(len(direct), 1)
        self.assertIsNone(direct[0].menu())                    # (none yet: a plain item, a new one)
        direct[0].trigger()
        self.assertEqual(got, [(["c1"], "")])
        panel.set_vfx_nodes([("vn1", "光暈")])
        panel._fill_menu()
        sub = next(a for a in panel.add_btn.menu().actions() if a.text().startswith("節點效果")).menu()
        self.assertEqual([a.text() for a in sub.actions() if a.text()], ["光暈", "新增…"])
        sub.actions()[0].trigger()
        self.assertEqual(got[-1], (["c1"], "vn1"))


if __name__ == "__main__":
    unittest.main()
