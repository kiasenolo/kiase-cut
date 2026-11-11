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


class NodeEditorSelectionTests(unittest.TestCase):
    def test_the_node_editor_follows_a_selection_that_shares_one_vfx_node(self):
        from kiasecut.ui.main_window import MainWindow
        mk = lambda *vfx: {"effects": [{"filter": fx.GRAPH, "vfx": v} for v in vfx]}
        shared = MainWindow._nodes_shared
        self.assertTrue(shared([mk("a")]))
        self.assertTrue(shared([mk("a"), mk("a"), mk("b", "a")]))
        self.assertFalse(shared([mk("a"), mk("b")]))                    # (different graphs: nothing to show for both)
        self.assertFalse(shared([mk(None), mk(None)]))                  # (their own graphs, not shared)
        self.assertFalse(shared([]))



class VfxStartValuesTests(unittest.TestCase):
    def setUp(self):
        from test_edit import proj
        self.p = proj()
        self.e = edit.add_effect(self.p, "c1", fx.GRAPH)
        math = edit.add_graph_node(self.p, "c1", self.e["id"], {"type": "filter", "ref": "builtin:nodes/math"})
        self.math = math
        self.e["params"].update(ng.default_params(self.e["graph"]))
        self.vid = edit.vfx_from_effect(self.p, "c1", self.e["id"])

    def test_a_new_use_starts_with_what_the_nodes_inside_were_set_to(self):
        key = ng.param_key(self.math, "op")
        self.e["params"][key] = "相除"                                      # (set after the VFX Node was made, on this use)
        self.e["params"][ng.expose_key("alpha")] = 50.0                    # (the use's own value: not carried)
        project.sync_vfx(self.p, [self.e])                                 # (what History.do does after the edit)
        c2 = edit.find(self.p, "c2")[1] if any(c["id"] == "c2" for c in project.all_clips(self.p)) else None
        if c2 is None:
            self.skipTest("the test project has one clip")
        used = edit.add_vfx_effect(self.p, "c2", self.vid)
        self.assertEqual(used["params"][key], "相除")
        self.assertNotIn(ng.expose_key("alpha"), used["params"])

    def test_a_node_made_before_it_kept_its_settings_borrows_a_use(self):
        key = ng.param_key(self.math, "op")
        self.p["vfx_nodes"][self.vid]["params"] = {}
        self.e["params"][key] = "相除"
        c2 = next((c for c in project.all_clips(self.p) if c["id"] == "c2"), None)
        if c2 is None:
            self.skipTest("the test project has one clip")
        self.assertEqual(edit.add_vfx_effect(self.p, "c2", self.vid)["params"][key], "相除")

    def test_what_the_nodes_inside_were_set_to_goes_to_every_use_but_exposed_values_stay(self):
        key, alpha = ng.param_key(self.math, "op"), ng.expose_key("alpha")
        two = edit.add_vfx_effect(self.p, "c2", self.vid)
        two["params"][alpha] = 10.0
        self.e["params"][key] = "相除"
        self.e["params"][alpha] = 50.0
        project.sync_vfx(self.p, [self.e])
        self.assertEqual(two["params"][key], "相除")
        self.assertEqual((self.e["params"][alpha], two["params"].get(alpha)), (50.0, 10.0))


class NodeEffectPanelTests(unittest.TestCase):
    def test_a_node_effect_shows_only_its_exposed_parameters(self):
        from PySide6.QtWidgets import QApplication
        from test_edit import proj
        from kiasecut import components
        from kiasecut.ui.effects_panel import EffectsPanel
        app = QApplication.instance() or QApplication([])
        p = proj()
        e = edit.add_effect(p, "c1", fx.GRAPH)
        math = edit.add_graph_node(p, "c1", e["id"], {"type": "filter", "ref": "builtin:nodes/math"})
        e["params"].update(ng.default_params(e["graph"]))
        name = ng.add_exposed(e["graph"], e["params"], "float", "透明度")
        panel = EffectsPanel()
        panel.resize(360, 900)
        panel.show()
        panel.show_clips([edit.find(p, "c1")[1]], 0, 30)
        app.processEvents()
        self.assertIn((f"fx:{e['id']}", ng.expose_key(name)), panel.widgets)
        self.assertNotIn((f"fx:{e['id']}", ng.param_key(math, "op")), panel.widgets)
        props = components.number_props_of(edit.find(p, "c1")[1])
        self.assertIn(f"fx:{e['id']}.{ng.expose_key(name)}", props)
        self.assertFalse([q for q in props if q.startswith(f"fx:{e['id']}.{math}.")])


class ColourButtonMenuTests(unittest.TestCase):
    def test_a_colour_buttons_background_does_not_reach_its_menu(self):
        """The right-click menu of a component's colour field came up as a white board (the button's sheet went to the child menu)."""
        from PySide6.QtWidgets import QApplication, QMenu, QPushButton, QWidget
        from kiasecut.ui import look
        app = QApplication.instance() or QApplication([])
        look.apply(app)
        host = QWidget()
        host.show()
        button = QPushButton(host)
        look.set_sheet(button, "QPushButton { background: #ffffff; color: #000; }")      # (as the inspector sets it)
        menu = QMenu(host)
        menu.addAction("x")
        menu.show()
        img = menu.grab().toImage()
        self.assertNotEqual(img.pixelColor(img.width() // 2, 4).name(), "#ffffff")
        menu.close()
