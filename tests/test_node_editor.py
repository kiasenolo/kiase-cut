"""The node editor widget (ui/node_editor.py): it shows a node effect's graph and turns mouse and keys into requests."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import fx, nodegraph as ng  # noqa: E402
from kiasecut.ui.node_editor import NodeEditor  # noqa: E402

APP = QApplication.instance() or QApplication([])


def clip_with(graph_fn=None):
    e = fx.new_effect(fx.GRAPH, "e1")
    if graph_fn:
        graph_fn(e)
    return {"id": "c1", "type": "image", "effects": [e]}


class NodeEditorTests(unittest.TestCase):
    def make(self, graph_fn=None):
        ed = NodeEditor()
        ed.resize(900, 500)
        ed.show()
        ed.show_clip(clip_with(graph_fn))
        APP.processEvents()
        return ed

    def test_shows_nothing_without_a_node_effect(self):
        ed = NodeEditor()
        ed.show_clip({"id": "c", "type": "image", "effects": []})
        self.assertTrue(ed.view.isHidden())
        self.assertIsNone(ed.eid)

    def test_draws_nodes_and_links(self):
        ed = self.make()
        self.assertEqual(set(ed.view.items_by_id), {"input", "output"})
        self.assertEqual(len(ed.view.link_items), 1)

    def drag(self, ed, a, b):
        v = ed.view
        pa = v.mapFromScene(a)
        pb = v.mapFromScene(b)
        QTest.mousePress(v.viewport(), Qt.LeftButton, Qt.NoModifier, pa)
        QTest.mouseMove(v.viewport(), pb)
        QTest.mouseRelease(v.viewport(), Qt.LeftButton, Qt.NoModifier, pb)

    def test_drag_between_sockets_connects(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/mix"}, 0, 150)
        ed = self.make(build)
        got = []
        ed.connectRequested.connect(lambda *a: got.append(a))
        mix = ed.view.items_by_id["mix1"]
        self.drag(ed, ed.view.items_by_id["input"].output_pos(), mix.input_pos("b"))
        self.assertEqual(got, [("e1", "input", "mix1", "b", "")])

    def test_picking_up_a_link_and_dropping_it_nowhere_unlinks(self):
        ed = self.make()
        got = []
        ed.disconnectRequested.connect(lambda *a: got.append(a))
        out = ed.view.items_by_id["output"]
        self.drag(ed, out.input_pos("src"), out.input_pos("src") + QPointF(-30, 200))
        self.assertEqual(got, [("e1", "output", "src")])

    def test_moving_a_node_asks_for_the_move(self):
        ed = self.make()
        got = []
        ed.moveRequested.connect(lambda *a: got.append(a))
        it = ed.view.items_by_id["input"]
        v = ed.view
        start = v.mapFromScene(it.mapToScene(40, 12))
        QTest.mousePress(v.viewport(), Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(v.viewport(), start + QPoint(30, 40))
        QTest.mouseRelease(v.viewport(), Qt.LeftButton, Qt.NoModifier, start + QPoint(30, 40))
        self.assertEqual(len(got), 1)
        self.assertEqual(list(got[0][1]), ["input"])

    def test_delete_and_mute_keys(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/math"}, 0, 150)
        ed = self.make(build)
        removed, muted, picked = [], [], []
        ed.removeRequested.connect(lambda *a: removed.append(a))
        ed.muteRequested.connect(lambda *a: muted.append(a))
        ed.nodeSelected.connect(lambda *a: picked.append(a))
        ed.select("math1")
        self.assertEqual(picked[-1], ("e1", "math1"))
        QTest.keyClick(ed.view, Qt.Key_M)
        QTest.keyClick(ed.view, Qt.Key_X)
        self.assertEqual(muted, [("e1", ["math1"], True)])
        self.assertEqual(removed, [("e1", ["math1"])])
        ed.select("output")
        QTest.keyClick(ed.view, Qt.Key_X)
        self.assertEqual(len(removed), 1)                       # (the output stays)

    def row_pos(self, ed, nid, name):
        """Scene point of the middle of the field of parameter name of node nid."""
        it = ed.view.items_by_id[nid]
        r = next(r for r in it.rows if r["kind"] == "param" and r["p"].name == name)
        return it.mapToScene(it.field_rect(r).center())

    def test_number_field_scrubs_and_is_hidden_when_linked(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/math"}, 0, 150)
            e["params"].update(ng.default_params(e["graph"]))
        ed = self.make(build)
        got = []
        ed.paramEdited.connect(lambda *a: got.append(a))
        at = self.row_pos(ed, "math1", "value")
        self.drag(ed, at, at + QPointF(40, 0))
        self.assertTrue(got)
        eid, key, value = got[-1]
        self.assertEqual((eid, key), ("e1", "math1.value"))
        self.assertGreater(value, 0.5)                                  # (dragged right: more)
        it = ed.view.items_by_id["math1"]
        row = next(r for r in it.rows if r["socket"] == "param:value")
        self.assertTrue(it.has_field(row))
        it.linked.add("param:value")
        self.assertFalse(it.has_field(row))

    def test_tick_flips_and_menu_choices_are_asked_for(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/math"}, 0, 150)
            e["params"].update(ng.default_params(e["graph"]))
        ed = self.make(build)
        got = []
        ed.paramEdited.connect(lambda *a: got.append(a))
        it = ed.view.items_by_id["math1"]
        r = next(r for r in it.rows if r["kind"] == "param" and r["p"].name == "clamp_on")
        ed.field_clicked(it, r, 0, QPointF(0, 0))
        self.assertEqual(got, [("e1", "math1.clamp_on", True)])
        self.assertEqual(ed.field_number("math1", r, 0), None)

    def test_typed_number_and_clamp(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:bulge"}, 0, 150)
            e["params"].update(ng.default_params(e["graph"]))
        ed = self.make(build)
        got = []
        ed.paramEdited.connect(lambda *a: got.append(a))
        it = ed.view.items_by_id["builtin_bulge1"]
        r = next(r for r in it.rows if r["kind"] == "param" and r["p"].type == "float")
        ed.set_number("builtin_bulge1", r, 0, 1e9)
        self.assertEqual(got[-1][2], r["p"].hi)

    def test_values_follow_the_effect_without_redrawing(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/math"}, 0, 150)
            e["params"].update(ng.default_params(e["graph"]))
        ed = self.make(build)
        item = ed.view.items_by_id["math1"]
        c = clip_with(build)
        c["effects"][0]["params"]["math1.value"] = 0.9
        c["effects"][0]["graph"] = ed.graph
        ed.show_clip(c)
        self.assertIs(ed.view.items_by_id["math1"], item)
        self.assertEqual(ed.node_values("math1").get("value"), 0.9)

    def click(self, ed, scene_pos):
        v = ed.view
        pt = v.mapFromScene(scene_pos)
        QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, pt)

    def with_math(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/math"}, 0, 150)
            e["params"].update(ng.default_params(e["graph"]))
        return self.make(build)

    def test_a_real_click_on_a_tick_menu_and_number(self):
        ed = self.with_math()
        got = []
        ed.paramEdited.connect(lambda *a: got.append(a))
        it = ed.view.items_by_id["math1"]

        def field(name):
            r = next(r for r in it.rows if r["kind"] == "param" and r["p"].name == name)
            return it.mapToScene(it.field_rect(r).center())
        self.click(ed, field("clamp_on"))
        self.assertEqual(got[-1], ("e1", "math1.clamp_on", True))
        shown = []
        ed.popup = lambda menu, pos: shown.append([x.text() for x in menu.actions()])
        self.click(ed, field("op"))
        self.assertEqual(len(shown), 1)
        self.assertIn("相乘", shown[0])
        self.click(ed, field("value"))                                  # (a click: a box to type in)
        self.assertIsNotNone(ed.edit_proxy)
        ed.edit_proxy.widget().setText("2.5")
        ed.edit_proxy.widget().returnPressed.emit()
        self.assertEqual(got[-1], ("e1", "math1.value", 2.5))

    def test_ghost_socket_drag_makes_a_parameter(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/math"}, 300, 150)
            ng.add_node(e["graph"], {"type": ng.PARAMS}, -300, 150)
            e["params"].update(ng.default_params(e["graph"]))
        ed = self.make(build)
        got = []
        ed.exposeRequested.connect(lambda *a: got.append(a))
        ghost = next(at for out, at in ed.view.items_by_id["params1"].outputs() if out == "\0ghost")
        self.drag(ed, ghost, ed.view.items_by_id["math1"].input_pos("param:value"))
        self.assertEqual(got, [("e1", "params1", "math1", "param:value")])

    def test_existing_parameter_output_links_with_its_name(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/math"}, 300, 150)
            n = ng.add_node(e["graph"], {"type": ng.PARAMS}, -300, 150)
            e["graph"]["exposed"] = [{"name": "k", "label": "強度", "type": "float", "default": 0.5, "lo": 0, "hi": 1, "items": []}]
            e["params"]["expose.k"] = 0.5
        ed = self.make(build)
        got = []
        ed.connectRequested.connect(lambda *a: got.append(a))
        at = next(at for out, at in ed.view.items_by_id["params1"].outputs() if out == "k")
        self.drag(ed, at, ed.view.items_by_id["math1"].input_pos("param:value"))
        self.assertEqual(got, [("e1", "params1", "math1", "param:value", "k")])

    def test_ctrl_right_drag_cuts_links(self):
        ed = self.make()
        got = []
        ed.disconnectManyRequested.connect(lambda *a: got.append(a))
        a = ed.view.items_by_id["input"].output_pos()
        b = ed.view.items_by_id["output"].input_pos("src")
        mid = (a + b) / 2
        v = ed.view
        p0, p1 = v.mapFromScene(mid + QPointF(0, -40)), v.mapFromScene(mid + QPointF(0, 40))
        QTest.mousePress(v.viewport(), Qt.RightButton, Qt.ControlModifier, p0)
        QTest.mouseMove(v.viewport(), v.mapFromScene(mid))
        QTest.mouseMove(v.viewport(), p1)
        QTest.mouseRelease(v.viewport(), Qt.RightButton, Qt.ControlModifier, p1)
        self.assertEqual(got, [("e1", [("output", "src")])])

    def test_node_dropped_on_a_link_is_inserted(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/math"}, -60, 160)
        ed = self.make(build)
        got, moved = [], []
        ed.insertRequested.connect(lambda *a: got.append(a))
        ed.moveRequested.connect(lambda *a: moved.append(a))
        a = ed.view.items_by_id["input"].output_pos()
        b = ed.view.items_by_id["output"].input_pos("src")
        it = ed.view.items_by_id["math1"]
        grab = it.mapToScene(40, 12)
        new_pos = (a + b) / 2 - QPointF(105, 30)                        # (the node's box across the middle of the link)
        target = grab + (new_pos - it.pos())
        self.drag(ed, grab, target)
        self.assertEqual(len(got), 1, got)
        self.assertEqual(got[0][0:2] + got[0][4:], ("e1", "math1", "input", "output", "src", ""))
        self.assertEqual(moved, [])

    def test_link_let_go_in_the_empty_asks_for_a_node(self):
        ed = self.make()
        asked = []
        ed.add_menu = lambda pos, gpos, link=None: asked.append(link)
        out = ed.view.items_by_id["input"].output_pos()
        self.drag(ed, out, out + QPointF(40, 220))
        self.assertEqual(asked, [("input", "")])

    def test_redraws_only_when_the_graph_changed(self):
        ed = self.make()
        item = ed.view.items_by_id["input"]
        ed.show_clip(clip_with())
        self.assertIs(ed.view.items_by_id["input"], item)


if __name__ == "__main__":
    unittest.main()
