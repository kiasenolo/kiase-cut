"""The node editor widget (ui/node_editor.py): it shows a node effect's graph and turns mouse and keys into requests."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402

from kiasecut import fx, nodegraph as ng  # noqa: E402
from kiasecut.ui.node_editor import NodeEditor  # noqa: E402

APP = QApplication.instance() or QApplication([])


def clip_with(graph_fn=None):
    e = fx.new_effect(fx.GRAPH, "e1")
    if graph_fn:
        graph_fn(e)
    return {"id": "c1", "type": "image", "effects": [e]}


def fx_ghost():
    from kiasecut.ui.node_editor import GHOST
    return GHOST


NEW_SOCKET = "\0newsocket"


class NodeEditorTests(unittest.TestCase):
    def make(self, graph_fn=None):
        ed = NodeEditor()
        ed.resize(900, 500)
        ed.show()
        ed.show_clip(clip_with(graph_fn))
        APP.processEvents()
        return ed

    def test_a_words_box_is_as_tall_as_it_was_dragged_to_and_shows_a_line_each(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.STRING, "value": "one\ntwo\nthree"}, 0, 150, base="s")
            nid = ng.add_node(e["graph"], {"type": ng.SOURCE, "kind": "text"}, 0, 400, base="x")
            e.setdefault("sources", {})[nid] = {"kind": "text", "content": "a\nb\nc\nd", "cx": 0.0, "cy": 0.0, "w": 1.0, "h": 1.0, "rotation": 0.0}
            e["params"].update(ng.default_params(e["graph"]))
        ed = self.make(build)
        row = lambda nid, kind: next(r for r in ed.view.items_by_id[nid].rows if r["kind"] == kind)
        self.assertEqual(row("s1", "string")["h"], 22.0)                         # (one line tall: the lines after a ⏎)
        self.assertEqual(row("x1", "text")["h"], 22.0)
        self.assertFalse([r for r in ed.view.items_by_id["s1"].rows if r["kind"] == "panel"])
        got = []
        ed.linesEdited.connect(lambda *a: got.append(a))
        it = ed.view.items_by_id["s1"]
        r = row("s1", "string")
        box = it.field_rect(r)
        grip = it.mapToScene(box.right() - 4, box.bottom() - 4)
        v = ed.view
        QTest.mousePress(v.viewport(), Qt.LeftButton, Qt.NoModifier, v.mapFromScene(grip))
        QTest.mouseMove(v.viewport(), v.mapFromScene(grip + QPointF(0, 2.2 * 22)))
        self.assertEqual(row("s1", "string")["h"], 66.0)                         # (it follows the drag, a line at a time)
        QTest.mouseRelease(v.viewport(), Qt.LeftButton, Qt.NoModifier, v.mapFromScene(grip + QPointF(0, 2.2 * 22)))
        self.assertEqual(got, [("e1", "s1", 3)])
        ed.graph["nodes"]["x1"]["lines"] = 4                                      # (as a node that was saved so)
        ed.rebuild()
        APP.processEvents()
        self.assertEqual(row("x1", "text")["h"], 88.0)
        self.assertGreater(ed.view.items_by_id["x1"].field_rect(row("x1", "text")).height(), 80)

    def test_words_are_typed_right_in_the_node(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.STRING, "value": "hello"}, 0, 150, base="s")
        ed = self.make(build)
        got = []
        ed.stringEdited.connect(lambda *a: got.append(a))
        it = ed.view.items_by_id["s1"]
        r = next(r for r in it.rows if r["kind"] == "string")
        ed.field_clicked(it, r, 0, QPointF(0, 0))
        self.assertIsNotNone(ed.edit_proxy)                                       # (a box in the node, not a window)
        box = ed.edit_proxy.widget()
        self.assertEqual(box.toPlainText(), "hello")
        box.setPlainText("你好\n世界")
        QTest.keyClick(box, Qt.Key_Return)
        self.assertEqual(got, [("e1", "s1", "你好\n世界")])
        self.assertIsNone(ed.edit_proxy)
        ed.field_clicked(it, r, 0, QPointF(0, 0))
        ed.edit_proxy.widget().setPlainText("nope")
        QTest.keyClick(ed.edit_proxy.widget(), Qt.Key_Escape)
        self.assertEqual(len(got), 1)                                             # (Esc: not kept)

    def test_a_font_is_picked_from_a_list_in_the_node(self):
        from PySide6.QtWidgets import QComboBox
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FONT, "value": ""}, 0, 150, base="f")
        ed = self.make(build)
        ed.fonts = [{"name": "甲", "path": "/a.ttf"}, {"name": "乙", "path": "/b.ttf"}]
        got = []
        ed.fontEdited.connect(lambda *a: got.append(a))
        it = ed.view.items_by_id["f1"]
        r = next(r for r in it.rows if r["kind"] == "fontvalue")
        ed.field_clicked(it, r, 0, QPointF(0, 0))
        combo = ed.edit_proxy.widget()
        self.assertIsInstance(combo, QComboBox)
        self.assertEqual([combo.itemText(i) for i in range(combo.count())][:2], ["甲", "乙"])
        combo.textActivated.emit("乙")
        self.assertEqual(got, [("e1", "f1", "/b.ttf")])

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

    def test_a_dragged_link_jumps_onto_a_near_socket_and_is_thicker_than_the_placed_ones(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/mix"}, 0, 150)
        ed = self.make(build)
        v = ed.view
        got = []
        ed.connectRequested.connect(lambda *a: got.append(a))
        mix = v.items_by_id["mix1"]
        target = mix.input_pos("b")
        near = target + QPointF(-20 / v.transform().m11(), 0)                 # (beyond the socket's own size, within the snap range)
        self.assertIsNone(v.socket_at(near))
        pa, pb = v.mapFromScene(v.items_by_id["input"].output_pos()), v.mapFromScene(near)
        QTest.mousePress(v.viewport(), Qt.LeftButton, Qt.NoModifier, pa)
        QTest.mouseMove(v.viewport(), pb)
        ln = v.rubber[0]
        self.assertGreater(ln.pen().widthF(), v.link_items[0][0].pen().widthF())
        self.assertAlmostEqual((ln.path().currentPosition() - target).manhattanLength(), 0, delta=0.5)   # (its end is on the socket)
        self.assertIsNotNone(v.snap_ring)
        QTest.mouseRelease(v.viewport(), Qt.LeftButton, Qt.NoModifier, pb)
        self.assertEqual(got, [("e1", "input", "mix1", "b", "")])
        self.assertIsNone(v.snap_ring)
        ed.add_menu = lambda *a, **k: None                                   # (let go in the empty it asks for a node: not here)
        self.drag(ed, v.items_by_id["input"].output_pos(), target + QPointF(-200, 0))   # (far from every socket: no link)
        self.assertEqual(len(got), 1)

    def test_a_picked_up_link_is_the_one_dragged_not_a_second_beside_it(self):
        ed = self.make()
        v = ed.view
        out = v.items_by_id["output"]
        placed = [l for l, _a, b, sk, _o in v.link_items if (b, sk) == ("output", "src")]
        self.assertTrue(placed and all(l.isVisible() for l in placed))
        a = out.input_pos("src")
        QTest.mousePress(v.viewport(), Qt.LeftButton, Qt.NoModifier, v.mapFromScene(a))
        QTest.mouseMove(v.viewport(), v.mapFromScene(a + QPointF(-60, 80)))
        self.assertFalse(any(l.isVisible() for l in placed))                   # (it left the socket)
        ed.add_menu = lambda *a, **k: None
        QTest.mouseRelease(v.viewport(), Qt.LeftButton, Qt.NoModifier, v.mapFromScene(a))   # (back on its own socket: it stays)
        self.assertTrue(all(l.isVisible() for l in placed))

    def test_links_are_coloured_by_their_sockets_with_a_gradient_between_types(self):
        from kiasecut.ui import node_editor as ne
        def build(e):
            m = ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/math"}, 300, 150)
            r = ng.add_node(e["graph"], {"type": ng.REROUTE}, 150, 150)
            ng.connect(e["graph"], "input", r, "src")
            ng.connect(e["graph"], r, m, "b")
        ed = self.make(build)
        v = ed.view
        r = next(i for i in v.items_by_id.values() if isinstance(i, ne.RerouteItem))
        self.assertEqual(r.colour, ne.SOCKET_COLORS["image"])                    # (a reroute takes what feeds it)
        cols = {(a, b): ln.cols for ln, a, b, sock, out in v.link_items}
        self.assertEqual(cols[("input", r.nid)], (ne.SOCKET_COLORS["image"],) * 2)
        self.assertEqual(cols[(r.nid, "math1")], (ne.SOCKET_COLORS["image"], ne.SOCKET_COLORS["float"]))   # (a picture into a number: from one to the other)
        ln = next(ln for ln, a, b, *_ in v.link_items if b == "math1")
        brush = ln.pen().brush()
        self.assertEqual(brush.style(), Qt.LinearGradientPattern)
        self.assertEqual(brush.gradient().stops()[0][1].name(), ne.SOCKET_COLORS["image"])
        self.assertEqual(brush.gradient().stops()[-1][1].name(), ne.SOCKET_COLORS["float"])

    def test_each_kind_of_value_has_its_own_socket_colour(self):
        from kiasecut.ui import node_editor as ne
        kinds = ("float", "int", "bool", "color", "vec3", "menu", "curve")
        colours = [ne.type_color(t) for t in kinds]
        self.assertEqual(len(set(colours)), len(kinds))
        self.assertEqual(ne.type_color("vec2"), ne.type_color("vec3"))
        self.assertNotIn(ne.type_color("bool"), (ne.SOCKET_COLORS["image"], ne.SOCKET_COLORS["string"], ne.SOCKET_COLORS["font"]))

    def test_nodes_that_carry_values_say_so_in_their_sockets(self):
        from kiasecut import fx
        from kiasecut.ui import node_editor as ne
        for ref in ne.node_refs():
            d = fx.get(ref)
            self.assertIsNone(d.error, ref)
            for (way, name), kind in d.socket_types.items():
                self.assertIn(kind, fx.SOCKET_TYPES, ref)
                known = ["src"] + [n for n, _ in d.inputs] if way == "in" else [""] + [n for n, _ in d.outputs]
                self.assertIn(name, known, f"{ref}: @socket {way} {name}")
                if way == "out" and d.outputs:
                    self.assertNotEqual(name, "", ref)
        sep, comb = fx.get("builtin:nodes/separate_xyz"), fx.get("builtin:nodes/combine_xyz")
        self.assertEqual(sep.socket_type("in", "src"), "vector")
        self.assertEqual(sep.src_label, "向量")                                  # (not 圖像)
        self.assertEqual([sep.socket_type("out", n) for n in "xyz"], ["float"] * 3)
        self.assertEqual((comb.socket_type("out", ""), comb.out_label), ("vector", "向量"))
        self.assertEqual(fx.get("builtin:nodes/value").out_label, "數值")
        self.assertEqual(fx.get("builtin:mix").socket_type("out", ""), "image")    # (a picture stays one)

    def test_the_feeding_menu_starts_with_the_constant_that_fits_with_its_value(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/math"}, 0, 150)
        ed = self.make(build)
        shown = []
        ed.popup = lambda menu, pos: shown.append([x.text() for x in menu.actions()])
        ed.add_menu(QPointF(0, 0), QPoint(0, 0), feed=("math1", "b"))
        self.assertEqual(shown[-1][1], "常數（保留目前的值）")                    # (after the search box)

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

    def test_dragged_nodes_snap_to_the_grid(self):
        from kiasecut.ui import node_editor
        ed = self.make()
        got = []
        ed.moveRequested.connect(lambda *a: got.append(a))
        v = ed.view
        it = v.items_by_id["input"]
        start = v.mapFromScene(it.mapToScene(40, 12))
        QTest.mousePress(v.viewport(), Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(v.viewport(), start + QPoint(33, 47))
        QTest.mouseRelease(v.viewport(), Qt.LeftButton, Qt.NoModifier, start + QPoint(33, 47))
        x, y = got[-1][1]["input"]
        self.assertEqual((x % node_editor.GRID, y % node_editor.GRID), (0, 0))
        v.snap = False
        start = v.mapFromScene(it.mapToScene(40, 12))
        QTest.mousePress(v.viewport(), Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(v.viewport(), start + QPoint(7, 3))
        QTest.mouseRelease(v.viewport(), Qt.LeftButton, Qt.NoModifier, start + QPoint(7, 3))
        self.assertNotEqual(got[-1][1]["input"][0] % node_editor.GRID, 0)

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
        got, live = [], []
        ed.paramEdited.connect(lambda *a: got.append(a))
        ed.paramLive.connect(lambda *a: live.append(a))
        at = self.row_pos(ed, "math1", "value")
        self.drag(ed, at, at + QPointF(40, 0))
        self.assertTrue(live)                                           # (the preview followed the drag...)
        self.assertEqual(len(got), 1)                                   # ...and one edit came when it was let go
        self.assertEqual(got[0][2], live[-1][3])
        self.assertTrue(got)
        eid, key, value = got[-1]
        self.assertEqual((eid, key), ("e1", "math1.value"))
        self.assertGreater(value, 0.5)                                  # (dragged right: more)
        it = ed.view.items_by_id["math1"]
        row = next(r for r in it.rows if r["kind"] == "param" and r["p"].name == "value")
        self.assertTrue(it.has_field(row))
        it.linked.add("b")                                                 # (B is one socket: its number box and its picture)
        self.assertFalse(it.has_field(row))

    def test_wheel_zooms_ctrl_and_shift_scroll(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QWheelEvent
        ed = self.make()
        v = ed.view
        pos = QPointF(100, 100)

        def wheel(delta, mods):
            v.wheelEvent(QWheelEvent(pos, v.mapToGlobal(pos.toPoint()), QPoint(0, 0), QPoint(0, delta), Qt.NoButton, mods, Qt.NoScrollPhase, False))
            glide = getattr(v, "_zoom_glide", None)
            while glide is not None and glide.left:       # (the wheel's zoom glides: let it end)
                glide.last -= 1.0
                glide.step()
        k0, under = v.transform().m11(), v.mapToScene(pos.toPoint())
        wheel(120, Qt.NoModifier)
        self.assertGreater(v.transform().m11(), k0)                     # up: zoom in
        moved = v.mapToScene(pos.toPoint()) - under
        self.assertLess(abs(moved.x()) + abs(moved.y()), 2.0)           # (the point under the pointer stays)
        wheel(-120, Qt.NoModifier)
        self.assertAlmostEqual(v.transform().m11(), k0, places=3)
        h0, v0 = v.horizontalScrollBar().value(), v.verticalScrollBar().value()
        wheel(-120, Qt.ShiftModifier)
        self.assertGreaterEqual(v.verticalScrollBar().value(), v0)
        self.assertEqual(v.horizontalScrollBar().value(), h0)
        self.assertEqual(v.transform().m11(), k0)
        wheel(-120, Qt.ControlModifier)
        self.assertEqual(v.transform().m11(), k0)                       # Ctrl: sideways, not zoom

    def test_pressing_elsewhere_closes_the_number_box_keeping_the_text(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/math"}, 0, 150)
            e["params"].update(ng.default_params(e["graph"]))
        ed = self.make(build)
        got = []
        ed.paramEdited.connect(lambda *a: got.append(a))
        it = ed.view.items_by_id["math1"]
        row = next(r for r in it.rows if r["kind"] == "param" and r["p"].name == "value")
        ed.field_clicked(it, row, 0, QPointF(0, 0))                     # the box opens
        self.assertIsNotNone(ed.edit_proxy)
        ed.edit_proxy.widget().setText("0.9")
        self.click(ed, QPointF(-400, -400))                             # an empty place
        self.assertIsNone(ed.edit_proxy)
        self.assertEqual(got[-1], ("e1", "math1.value", 0.9))

    def test_number_field_scrubs_up_and_down(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/math"}, 0, 150)
            e["params"].update(ng.default_params(e["graph"]))
        ed = self.make(build)
        got = []
        ed.paramEdited.connect(lambda *a: got.append(a))
        at = self.row_pos(ed, "math1", "value")
        self.drag(ed, at, at + QPointF(0, -20))                         # up: more, a step per 2 px
        self.assertAlmostEqual(got[-1][2], 0.5 + 10 * 1.0, 4)           # (a range of 2000: a step is 1)
        self.drag(ed, at, at + QPointF(0, 20))                          # down: less
        self.assertAlmostEqual(got[-1][2], 0.5, 4)

    def test_a_number_hops_up_as_it_grows_and_down_as_it_shrinks_inside_its_box(self):
        from kiasecut.ui import motion
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/math"}, 0, 150)
            e["params"].update(ng.default_params(e["graph"]))
        ed = self.make(build)
        at = self.row_pos(ed, "math1", "value")
        it = ed.view.items_by_id["math1"]
        row = next(r for r in it.rows if r["kind"] == "param" and r["p"].name == "value")
        v = ed.view
        pa = v.mapFromScene(at)
        QTest.mousePress(v.viewport(), Qt.LeftButton, Qt.NoModifier, pa)
        QTest.mouseMove(v.viewport(), v.mapFromScene(at + QPointF(0, -20)))
        hop = it.hops[(row["y"], 0)]
        self.assertEqual(hop.off, motion.HOP_PX)                        # (up: more, the number is lifted)
        box = it.field_rect(row)
        self.assertEqual(it.hopped(box, row).top(), box.top() - motion.HOP_PX)
        QTest.mouseMove(v.viewport(), v.mapFromScene(at + QPointF(0, 20)))
        self.assertEqual(hop.off, -motion.HOP_PX)
        QTest.mouseRelease(v.viewport(), Qt.LeftButton, Qt.NoModifier, v.mapFromScene(at + QPointF(0, 20)))
        QTest.qWait(motion.HOP_MS + 100)
        self.assertEqual(hop.off, 0.0)
        self.assertEqual(it.hopped(box, row), box)

    def test_number_scrub_is_endless_and_gives_the_pointer_back(self):
        from kiasecut.ui import wrapdrag
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/math"}, 0, 150)
            e["params"].update(ng.default_params(e["graph"]))
        ed = self.make(build)
        at = self.row_pos(ed, "math1", "value")
        it = ed.view.items_by_id["math1"]
        v = ed.view
        pa, pb = v.mapFromScene(at), v.mapFromScene(at + QPointF(0, -20))
        QTest.mousePress(v.viewport(), Qt.LeftButton, Qt.NoModifier, pa)
        self.assertIsNotNone(it.drag["wrap"])                           # (the drag goes by wrapdrag.py: no edge stops it)
        QTest.mouseMove(v.viewport(), pb)
        self.assertTrue(it.drag["wrap"].on)
        self.assertTrue(wrapdrag.hider().hidden)                        # (the pointer hidden while the number moves)
        QTest.mouseRelease(v.viewport(), Qt.LeftButton, Qt.NoModifier, pb)
        self.assertFalse(wrapdrag.hider().hidden)

    def test_a_link_dragged_out_of_an_input_and_let_go_in_the_empty_asks_for_a_node(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/math"}, 0, 150)
            e["params"].update(ng.default_params(e["graph"]))
        ed = self.make(build)
        asked = []
        ed.add_menu = lambda pos, gpos, link=None, feed=None: asked.append(feed)
        it = ed.view.items_by_id["math1"]
        a = it.input_pos("b")
        self.assertEqual(ed.view.socket_at(a), ("in", "math1", "b"))
        self.drag(ed, a, a + QPointF(-250, 120))                          # (the empty)
        self.assertEqual(asked, [("math1", "b")])

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
        self.assertEqual(got[-1][2], 1e6)                                  # (typing has no range, only a sane end)
        ed.set_number("builtin_bulge1", r, 0, 1e9, final=False)             # dragging: the field's own range
        self.assertEqual(ed._scrub[3], r["p"].hi)

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

    def test_input_node_has_an_empty_socket_that_makes_a_parameter(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/math"}, 300, 150)
            e["params"].update(ng.default_params(e["graph"]))
        ed = self.make(build)
        got, links = [], []
        ed.exposeRequested.connect(lambda *a: got.append(a))
        ed.connectRequested.connect(lambda *a: links.append(a))
        inp = ed.view.items_by_id["input"]
        self.assertEqual([o for o, _ in inp.outputs()], ["", "\0ghost"])             # the picture, then the empty one
        ghost = next(at for out, at in inp.outputs() if out == "\0ghost")
        self.drag(ed, ghost, ed.view.items_by_id["math1"].input_pos("param:value"))
        self.assertEqual(got, [("e1", "input", "math1", "param:value")])
        self.drag(ed, inp.output_pos(""), ed.view.items_by_id["math1"].input_pos("src"))       # (the picture still links)
        self.assertEqual(links, [("e1", "input", "math1", "src", "")])

    def test_menu_switch_empty_socket_makes_an_option_and_the_menu_edits_them(self):
        from kiasecut.ui import node_editor
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/menu_switch"}, 300, 150)
            e["params"].update(ng.default_params(e["graph"]))
        ed = self.make(build)
        v = ed.view
        got = []
        ed.itemRequested.connect(lambda *a: got.append(a))
        it = v.items_by_id["menu_switch1"]
        self.assertEqual([r["label"] for r in it.rows if r["kind"] == "image"],
                         ["選項 1", "選項 2", "選項 3", "（拉一條線進來新增選項）"])
        self.drag(ed, v.items_by_id["input"].output_pos(""), it.input_pos(node_editor.GHOST_ITEM))
        self.assertEqual(got, [("e1", "menu_switch1", "add", "", "", "input", "")])
        self.assertEqual(v.option_at(it.mapToScene(30, next(r["y"] for r in it.rows if r["socket"] == "i2") + 5)),
                         ("menu_switch1", "i2"))
        self.assertIsNone(v.option_at(it.mapToScene(30, next(r["y"] for r in it.rows if r["socket"] == node_editor.GHOST_ITEM) + 5)))
        ed.popup = lambda menu, pos: popped.append([a.text() for a in menu.actions() if a.text()])
        popped = []
        ed.option_menu("menu_switch1", "i2", QPoint(0, 0))
        self.assertEqual(popped, [["重新命名選項…", "往上移", "往下移", "刪除選項"]])
        ed.graph["nodes"]["menu_switch1"]["ref"] = "builtin:nodes/index_switch"            # (an Index Switch's are only numbered)
        popped.clear()
        ed.option_menu("menu_switch1", "i2", QPoint(0, 0))
        self.assertEqual(popped, [["往上移", "往下移", "刪除選項"]])

    def test_free_input_dragged_to_an_output_links_and_makes_a_parameter(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/math"}, 300, 150)
            ng.add_node(e["graph"], {"type": ng.PARAMS}, -300, 150)
            e["params"].update(ng.default_params(e["graph"]))
        ed = self.make(build)
        got, made = [], []
        ed.connectRequested.connect(lambda *a: got.append(a))
        ed.exposeRequested.connect(lambda *a: made.append(a))
        math = ed.view.items_by_id["math1"]
        self.drag(ed, math.input_pos("src"), ed.view.items_by_id["input"].output_pos(""))        # input -> output
        self.assertEqual(got, [("e1", "input", "math1", "src", "")])
        ghost = next(at for out, at in ed.view.items_by_id["params1"].outputs() if out == "\0ghost")
        self.drag(ed, math.input_pos("param:value"), ghost)                                     # input -> the ghost: a new parameter
        self.assertEqual(made, [("e1", "params1", "math1", "param:value")])

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

    def test_media_dragged_in_is_requested_as_source_nodes(self):
        from kiasecut.ui.timeline import MEDIA_MIME
        ed = self.make()
        got = []
        ed.mediaDropped.connect(lambda *a: got.append(a))
        v = ed.view
        md = QMimeData()
        md.setData(MEDIA_MIME, b"m1,cmp:k1")
        at = QPointF(v.mapFromScene(QPointF(50, 60)))
        v.dropEvent(QDropEvent(at, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
        self.assertEqual(len(got), 1)
        eid, ids, paths, x, y = got[0]
        self.assertEqual((eid, ids, paths), ("e1", ["m1", "cmp:k1"], []))
        self.assertAlmostEqual(x, 50, delta=2)
        self.assertAlmostEqual(y, 60, delta=2)

    def test_blender_mark_is_not_shown_in_the_node_editor(self):
        self.assertEqual(ng.short_name("[Blender] Color Ramp"), "Color Ramp")
        self.assertEqual(ng.short_name("模糊"), "模糊")
        self.assertEqual(ng.title({"type": ng.FILTER, "ref": "builtin:blender_color_ramp"}), "Color Ramp")
        ed = self.make()
        menus = []
        ed.popup = lambda menu, pos: menus.append(menu)
        ed.add_menu(QPointF(0, 0), QPoint(0, 0))

        def names(menu):
            for a in menu.actions():
                yield a.text()
                if a.menu():
                    yield from names(a.menu())
        self.assertFalse([n for n in names(menus[0]) if "[Blender]" in n])

    def test_add_menu_follows_blenders_order(self):
        ed = self.make()
        menus = []
        ed.popup = lambda menu, pos: menus.append(menu)
        ed.add_menu(QPointF(0, 0), QPoint(0, 0))

        def tree(menu):
            return {a.text(): (tree(a.menu()) if a.menu() else None) for a in menu.actions() if a.text()}
        top = tree(menus[0])
        self.assertEqual([k for k in top if k != "搜尋節點…"][:12],
                         ["輸入", "輸出", "色彩", "創意", "濾鏡", "去背", "遮罩", "紋理", "變換", "工具", "KiaseCut 效果", "佈局"][:12])
        self.assertEqual(list(top["輸入"])[:2], ["常數", "輸入（片段的畫面）"])
        self.assertEqual(list(top["輸入"]["常數"]), ["布林", "顏色", "字體", "整數", "整數向量", "選單", "字串", "數值", "向量"])
        self.assertEqual(list(top["色彩"])[0], "調整")
        self.assertEqual(list(top["濾鏡"])[:3], ["模糊", "擴張／侵蝕", "濾鏡"])
        self.assertEqual(list(top["工具"])[:3], ["數學", "向量", "正規化"])
        self.assertEqual(list(top["工具"]["向量"]), ["合併 XYZ", "映射範圍", "混合", "分離 XYZ", "向量曲線", "向量數學", "向量旋轉"])
        self.assertIn("場景", top["輸入"])
        self.assertIn("混合", top["色彩"])
        self.assertNotIn("混合", top["KiaseCut 效果"])
        self.assertTrue(any("模糊" in k for sub in top["KiaseCut 效果"].values() for k in sub))
        self.assertNotIn("圖片來源", {k for sub in top.values() if sub for k in sub})
        menus[0].search.setText("向量數學")
        self.assertTrue(any("向量" in a.text() for a in menus[0].found))

    def test_every_tool_node_has_a_place_in_the_menu(self):
        from kiasecut import nodemenu
        from kiasecut.ui.node_editor import node_refs
        for ref in node_refs():
            self.assertIn(ref, nodemenu.placed(), ref)
        for ref in nodemenu.placed():
            self.assertIn(ref, set(fx.builtin_refs()) | set(node_refs()), ref)

    def test_add_menu_searches(self):
        ed = self.make()
        asked = []
        ed.addRequested.connect(lambda *a: asked.append(a[1]))
        menus = []
        ed.popup = lambda menu, pos: menus.append(menu)
        ed.add_menu(QPointF(5, 6), QPoint(0, 0))
        menu = menus[0]
        menu.search.setText("blur")
        self.assertTrue(menu.found and all(a.isEnabled() for a in menu.found))
        menu.search.setText("zzzzqq")
        self.assertFalse(menu.found[0].isEnabled())
        menu.search.setText("圓")
        menu.search.returnPressed.emit()
        self.assertEqual(asked[-1]["kind"], "shape")

    def test_frame_carries_nodes_and_is_sized(self):
        def add(e):
            g = e["graph"]
            ng.add_node(g, {"type": ng.FRAME, "w": 300.0, "h": 200.0, "label": "框", "text": "", "color": "gray"}, -300, -300)
            g["nodes"]["input"]["x"], g["nodes"]["input"]["y"] = -250.0, -250.0
        ed = self.make(add)
        fid = next(i for i, n in ed.graph["nodes"].items() if n["type"] == ng.FRAME)
        moves, edits = [], []
        ed.moveRequested.connect(lambda eid, m: moves.append(m))
        ed.frameEdited.connect(lambda *a: edits.append(a[1:]))
        v = ed.view
        a = v.mapFromScene(QPointF(-290, -200))                    # empty part of the frame, not on the node
        QTest.mousePress(v.viewport(), Qt.LeftButton, Qt.NoModifier, a)
        QTest.mouseMove(v.viewport(), a + QPoint(30, 20))
        QTest.mouseRelease(v.viewport(), Qt.LeftButton, Qt.NoModifier, a + QPoint(30, 20))
        self.assertIn(fid, moves[-1])
        self.assertIn("input", moves[-1])                         # the node inside went along
        self.assertNotIn("output", moves[-1])
        g = v.mapFromScene(v.items_by_id[fid].mapToScene(QPointF(295, 195)))
        QTest.mousePress(v.viewport(), Qt.LeftButton, Qt.NoModifier, g)
        QTest.mouseMove(v.viewport(), g + QPoint(40, 30))
        QTest.mouseRelease(v.viewport(), Qt.LeftButton, Qt.NoModifier, g + QPoint(40, 30))
        self.assertEqual(edits[-1][0], fid)
        self.assertGreater(edits[-1][1]["w"], 300)

    def test_align_and_arrange(self):
        def add(e):
            g = e["graph"]
            made.append(ng.add_node(g, {"type": "reroute"}, 100, 60))
            g["nodes"]["input"]["x"], g["nodes"]["input"]["y"] = 0.0, 0.0
        made = []
        ed = self.make(add)
        rid = made[0]
        moves = []
        ed.moveRequested.connect(lambda eid, m: moves.append(m))
        ed.select("input")
        ed.view.items_by_id[rid].setSelected(True)
        ed.align("left")
        self.assertAlmostEqual(moves[-1][rid][0], 0.0, delta=0.5)
        ed.arrange()
        xs = [moves[-1][i][0] for i in moves[-1]]
        self.assertTrue(xs)
        self.assertEqual(ng.depths(ed.graph)["output"], 1)

    def test_copy_paste(self):
        ed = self.make()
        got = []
        ed.pasteRequested.connect(lambda *a: got.append(a))
        ed.select("input")
        ed.copy_selected()
        ed.paste_here(QPointF(10, 20))
        eid, pack, x, y = got[0]
        self.assertEqual(list(pack["nodes"]), ["input"])
        self.assertEqual((x, y), (10, 20))

    def test_ctrl_shift_click_steps_the_preview_along_the_outputs(self):
        def add(e):
            made.append(ng.add_node(e["graph"], {"type": "filter", "ref": "builtin:nodes/separate_color"}, 200, 40))
            e["params"].update(ng.default_params(e["graph"]))
        made = []
        ed = self.make(add)
        sep = made[0]
        asked = []
        ed.viewerRequested.connect(lambda *a: asked.append(a[1:]))
        self.assertEqual([o for o, _ in ng.outputs(ed.graph["nodes"][sep])], ["c1", "c2", "c3", "a"])
        it = ed.view.items_by_id[sep]
        self.assertEqual([o for o, _ in it.outputs()], ["c1", "c2", "c3", "a"])
        at = ed.view.mapFromScene(it.mapToScene(QPointF(60, 60)))
        mods = Qt.ControlModifier | Qt.ShiftModifier
        QTest.mouseClick(ed.view.viewport(), Qt.LeftButton, mods, at)
        self.assertEqual(asked[-1], (sep, "c1"))
        ed.graph["nodes"]["v"] = {"type": ng.VIEWER, "x": 0.0, "y": 0.0}
        ed.graph["links"].append({"from": sep, "to": "v", "socket": "src", "out": "c3"})
        QTest.mouseClick(ed.view.viewport(), Qt.LeftButton, mods, at)
        self.assertEqual(asked[-1], (sep, "a"))
        ed.graph["links"][-1]["out"] = "a"
        QTest.mouseClick(ed.view.viewport(), Qt.LeftButton, mods, at)
        self.assertEqual(asked[-1], ("", ""))

    def test_link_from_a_named_output_keeps_its_name(self):
        def add(e):
            made.append(ng.add_node(e["graph"], {"type": "filter", "ref": "builtin:nodes/separate_color"}, 200, 40))
            ng.connect(e["graph"], made[0], "output", "src", "c3")
            e["params"].update(ng.default_params(e["graph"]))
        made = []
        ed = self.make(add)
        self.assertEqual([l[4] for l in ed.view.link_items if l[1] == made[0]], ["c3"])

    def test_curve_and_gradient_fields_are_drawn_and_edited_in_the_node(self):
        import tempfile
        d = tempfile.mkdtemp()
        path = os.path.join(d, "curvy.glsl")
        with open(path, "w", encoding="utf-8") as f:
            f.write("// @filter 曲線測試\n// @param c curve 0,0,1,1 \"曲線\"\n// @param g gradient 0:#000000,1:#ffffff \"漸層\"\n"
                    "vec4 effect(vec2 uv) { return src(uv) * curve_ease(c, uv.x); }\n")
        made = []

        def add(e):
            made.append(ng.add_node(e["graph"], {"type": "filter", "ref": path}, 300, 40))
            e["params"].update(ng.default_params(e["graph"]))
        ed = self.make(add)
        nid = made[0]
        it = ed.view.items_by_id[nid]
        plots = [r for r in it.rows if r["kind"] == "plot"]
        self.assertEqual([r["p"].type for r in plots], ["curve", "gradient"])
        self.assertGreater(plots[0]["h"], plots[1]["h"])
        got = []
        ed.paramEdited.connect(lambda *a: got.append(a))
        self.assertEqual([q.name for q, _w in it.inline], ["c", "g"])             # (both are edited right in the node)
        grad = dict((q.name, w) for q, w in it.inline)["g"]
        grad.bar.committed.emit([[0.0, [1, 0, 0, 1]], [1.0, [0, 0, 1, 1]]])
        self.assertEqual(got[-1][1], nid + ".g")

    def test_what_a_ramp_in_a_node_opens_is_not_cut_by_the_node(self):
        from kiasecut.ui import inplace
        made = []

        def add(e):
            made.append(ng.add_node(e["graph"], {"type": "filter", "ref": "builtin:blender_color_ramp"}, 300, 40))
            e["params"].update(ng.default_params(e["graph"]))
        ed = self.make(add)
        it = ed.view.items_by_id[made[0]]
        w, = [w for q, w in it.inline if q.type == "gradient"]
        self.assertIs(inplace.real_window(w), ed.window())
        ed.view.centerOn(it)
        r = inplace.window_rect(w.color, w.color.rect())
        win = ed.window().rect()
        self.assertTrue(win.contains(r.center()))
        self.assertIs(inplace.real_window(ed), ed.window())

    def test_ramp_drag_is_live_and_its_end_is_the_edit(self):
        from kiasecut.ui.gradientbar import GradientEditor
        made = []

        def add(e):
            made.append(ng.add_node(e["graph"], {"type": "filter", "ref": "builtin:blender_color_ramp"}, 300, 40))
            e["params"].update(ng.default_params(e["graph"]))
        ed = self.make(add)
        nid = made[0]
        it = ed.view.items_by_id[nid]
        live, done = [], []
        ed.paramLive.connect(lambda *a: live.append(a))
        ed.paramEdited.connect(lambda *a: done.append(a))
        w, = [w for q, w in it.inline if q.type == "gradient"]
        self.assertIsInstance(w, GradientEditor)
        stops = [[0.0, [1, 0, 0, 1]], [0.4, [0, 1, 0, 1]], [1.0, [0, 0, 1, 1]]]
        w.bar.changed.emit(stops)                                    # (dragging)
        self.assertEqual((len(live), len(done)), (1, 0))
        self.assertEqual(live[-1][2], nid + ".ramp")
        self.assertEqual(ed.params[nid + ".ramp"], stops)           # (the node's own picture follows)
        w.bar.committed.emit(stops)                                  # (let go)
        self.assertEqual(len(done), 1)

    def test_thumbnails_row_per_output(self):
        def add(e):
            made.append(ng.add_node(e["graph"], {"type": "filter", "ref": "builtin:nodes/separate_color"}, 200, 40))
            e["params"].update(ng.default_params(e["graph"]))
        made = []
        ed = self.make(add)
        asked = []
        ed.thumbsToggled.connect(asked.append)
        before = ed.view.items_by_id[made[0]].h
        ed.set_show_thumbs(True)
        self.assertEqual(asked, [True])
        it = ed.view.items_by_id[made[0]]
        self.assertEqual([r["p"] for r in it.rows if r["kind"] == "thumb"], ["c1", "c2", "c3", "a"])
        self.assertGreater(it.h, before)
        self.assertEqual([r for r in ed.view.items_by_id["output"].rows if r["kind"] == "thumb"], [])
        ed.set_thumbs({"e1": {made[0]: {"c1": (2, 2, bytes([255]) * 16)}}})
        self.assertEqual(ed.thumb_image(made[0], "c1").width(), 2)
        self.assertIsNone(ed.thumb_image(made[0], "a"))

    def grouped(self):
        made = {}

        def add(e):
            g = e["graph"]
            made["a"] = ng.add_node(g, {"type": "filter", "ref": "builtin:nodes/math"}, 100, 0)
            ng.connect(g, "input", made["a"], "src")
            ng.connect(g, made["a"], "output", "src")
            made["g"] = ng.make_group(g, [made["a"]])
            e["params"].update(ng.default_params(g))
        return self.make(add), made

    def test_group_is_a_box_and_tab_goes_inside(self):
        ed, m = self.grouped()
        self.assertEqual(set(ed.view.items_by_id), {"input", "output", m["g"]})
        box = ed.view.items_by_id[m["g"]]
        self.assertEqual([r["socket"] for r in box.rows if r["kind"] == "image"], ["in1"])
        self.assertEqual([o for o, _ in box.outputs()], ["out1"])
        self.assertEqual(len(ed.view.link_items), 2)
        ed.select(m["g"])
        ed.tab()
        self.assertEqual(ed.level, m["g"])
        self.assertEqual(set(ed.view.items_by_id), {m["a"], "\0gin", "\0gout"})
        self.assertEqual({(a, b) for _ln, a, b, _s, _o in ed.view.link_items}, {("\0gin", m["a"]), (m["a"], "\0gout")})
        ed.tab()                                                      # nothing selected: out again
        self.assertEqual(ed.level, "")

    def test_links_to_a_groups_own_sockets_ask_for_group_ports(self):
        ed, m = self.grouped()
        asked, unplugged = [], []
        ed.groupPortRequested.connect(lambda *a: asked.append(a[1:]))
        ed.groupUnplugRequested.connect(lambda *a: unplugged.append(a[1:]))
        ed.enter(m["g"])
        v = ed.view
        # a new group input: drag out of the empty socket of 群組輸入 onto the member's main picture socket
        ghost = v.items_by_id["\0gin"].output_pos(fx_ghost())
        ed.drop_link("\0gin", fx_ghost(), None, ("in", m["a"], "src"), ghost, QPoint(0, 0))
        self.assertEqual(asked[-1], (m["g"], m["a"], "src", None, "", "", ""))
        # a member's output onto the empty socket of 群組輸出: a new group output
        ed.drop_link(m["a"], "", None, ("in", "\0gout", NEW_SOCKET), ghost, QPoint(0, 0))
        self.assertEqual(asked[-1], (m["g"], m["a"], "", "", "", "", ""))
        # onto an existing one: that output
        ed.drop_link(m["a"], "", None, ("in", "\0gout", "out1"), ghost, QPoint(0, 0))
        self.assertEqual(asked[-1][4], "out1")
        # a link of the group's input let go in the empty: unplugged
        ed.drop_link("\0gin", "in1", (m["a"], "src"), None, ghost, QPoint(0, 0))
        self.assertEqual(unplugged[-1], (m["g"], m["a"], "src", None))

    def test_ctrl_g_and_ctrl_alt_g(self):
        ed = self.make()
        asked = []
        ed.groupRequested.connect(lambda *a: asked.append(("g",) + a[1:]))
        ed.ungroupRequested.connect(lambda *a: asked.append(("u",) + a[1:]))
        ed.select("input")
        QTest.keyClick(ed.view, Qt.Key_G, Qt.ControlModifier)
        self.assertEqual(asked[-1], ("g", ["input"]))
        ed2, m = self.grouped()
        ung = []
        ed2.ungroupRequested.connect(lambda *a: ung.append(a[1:]))
        ed2.select(m["g"])
        QTest.keyClick(ed2.view, Qt.Key_G, Qt.ControlModifier | Qt.AltModifier)
        self.assertEqual(ung, [(m["g"],)])
        self.assertTrue(ed.view.claims(Qt.Key_Tab, Qt.NoModifier))
        self.assertTrue(ed.view.claims(Qt.Key_G, Qt.ControlModifier))

    def test_shift_right_drag_puts_bends_in_links(self):
        ed = self.make()
        got = []
        ed.rerouteRequested.connect(lambda *a: got.append(a))
        a = ed.view.items_by_id["input"].output_pos()
        b = ed.view.items_by_id["output"].input_pos("src")
        mid = (a + b) / 2
        v = ed.view
        p0, p1 = v.mapFromScene(mid + QPointF(0, -40)), v.mapFromScene(mid + QPointF(0, 40))
        QTest.mousePress(v.viewport(), Qt.RightButton, Qt.ShiftModifier, p0)
        QTest.mouseMove(v.viewport(), v.mapFromScene(mid))
        QTest.mouseMove(v.viewport(), p1)
        QTest.mouseRelease(v.viewport(), Qt.RightButton, Qt.ShiftModifier, p1)
        self.assertEqual(len(got), 1)
        (x, y, src, dst, sock, out), = got[0][1]
        self.assertEqual((src, dst, sock, out), ("input", "output", "src", ""))
        self.assertAlmostEqual(x + 15, mid.x(), delta=6)

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

    def test_window_shortcuts_do_not_take_the_editors_keys(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        ed = self.make()
        for key, mods in ((Qt.Key_X, Qt.ControlModifier), (Qt.Key_X, Qt.NoModifier), (Qt.Key_Delete, Qt.NoModifier),
                          (Qt.Key_M, Qt.NoModifier), (Qt.Key_Home, Qt.NoModifier), (Qt.Key_A, Qt.ShiftModifier),
                          (Qt.Key_D, Qt.ShiftModifier), (Qt.Key_A, Qt.NoModifier), (Qt.Key_D, Qt.ControlModifier)):
            e = QKeyEvent(QEvent.ShortcutOverride, key, mods)
            e.ignore()
            ed.view.event(e)
            self.assertTrue(e.isAccepted(), (key, mods))
        e = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_Z, Qt.ControlModifier)       # (undo stays the window's)
        e.ignore()
        ed.view.event(e)
        self.assertFalse(e.isAccepted())

    def test_ctrl_d_deselects_the_nodes(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        ed = self.make()
        QTest.keyClick(ed.view, Qt.Key_A)
        self.assertTrue(ed.selected())
        QTest.keyClick(ed.view, Qt.Key_D, Qt.ControlModifier)
        self.assertEqual(ed.selected(), [])

    def test_edge_widens_a_node(self):
        ed = self.make()
        got = []
        ed.widthEdited.connect(lambda eid, nid, w: got.append((nid, w)))
        it = ed.view.items_by_id["output"]
        w0 = it.w
        v = ed.view
        v.snap = False
        a = it.mapToScene(QPointF(w0 - 3, 40))
        self.drag(ed, a, a + QPointF(60, 0))
        self.assertEqual(len(got), 1)
        self.assertAlmostEqual(it.w, w0 + 60, delta=3)           # (the view's zoom rounds the drag)
        self.assertEqual(got[0], ("output", it.w))
        b = it.mapToScene(QPointF(it.w - 3, 40))
        self.drag(ed, b, b - QPointF(500, 0))
        self.assertEqual(it.w, 140.0)                            # (narrowest)

    def test_widening_snaps_the_right_edge_to_the_grid(self):
        from kiasecut.ui import node_editor
        ed = self.make()
        got = []
        ed.widthEdited.connect(lambda eid, nid, w: got.append((nid, w)))
        it = ed.view.items_by_id["output"]
        a = it.mapToScene(QPointF(it.w - 3, 40))
        self.drag(ed, a, a + QPointF(37, 0))
        self.assertEqual((it.pos().x() + it.w) % node_editor.GRID, 0)
        self.assertEqual(got[-1], ("output", it.w))

    def test_new_nodes_stick_to_the_pointer_till_a_click(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/math"}, 300, 150)
        ed = self.make(build)
        v = ed.view
        moved, gone = [], []
        ed.moveRequested.connect(lambda eid, m: moved.append(m))
        ed.removeRequested.connect(lambda eid, ids: gone.append(ids))
        ed.carry(["math1"])
        self.assertIsNotNone(v.carrying)
        at = v.items_by_id["math1"].pos()
        v._carry_to(QPointF(500, 400), False)                        # (the pointer moves, no button: the nodes follow)
        self.assertNotEqual(v.items_by_id["math1"].pos(), at)
        self.assertEqual(v.items_by_id["math1"].pos().x() % 20, 0)   # (and snap to the grid)
        QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(200, 160))
        self.assertIsNone(v.carrying)
        self.assertEqual(list(moved[-1]), ["math1"])                 # (put down: one move)
        ed.carry(["math1"])                                          # Esc takes an added node back
        QTest.keyClick(v, Qt.Key_Escape)
        self.assertEqual(gone, [["math1"]])
        ed.carry(["math1"], remove=False)                            # (a duplicate stays where it was made)
        QTest.keyClick(v, Qt.Key_Escape)
        self.assertEqual(gone, [["math1"]])
        self.assertIsNone(v.carrying)

    def test_g_grabs_the_selected_nodes_by_how_far_the_pointer_goes(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/math"}, 300, 160)
        ed = self.make(build)
        v = ed.view
        moved, gone = [], []
        ed.moveRequested.connect(lambda eid, m: moved.append(m))
        ed.removeRequested.connect(lambda eid, ids: gone.append(ids))
        ed.select("math1")
        QTest.keyClick(v, Qt.Key_G)
        self.assertIsNotNone(v.carrying)
        self.assertTrue(v.wrap.on)                                   # (endless: the pointer wraps at the edges)
        it = v.items_by_id["math1"]
        at = it.pos()
        here = v.mapToScene(v.mapFromGlobal(v.cursor().pos()))
        v._carry_to(here, False)                                     # (the pointer has not moved: nothing jumps)
        self.assertEqual(it.pos().x() % 20, 0)
        self.assertLess((it.pos() - at).manhattanLength(), 20)
        v._carry_to(here + QPointF(100, 60), False)
        self.assertGreater(it.pos().x(), at.x() + 60)
        QTest.keyClick(v, Qt.Key_Return)                             # Enter keeps it where it is
        self.assertIsNone(v.carrying)
        self.assertFalse(v.wrap.on)
        self.assertEqual(list(moved[-1]), ["math1"])
        QTest.keyClick(v, Qt.Key_G)
        v._carry_to(here + QPointF(400, 200), False)
        QTest.keyClick(v, Qt.Key_Escape)                             # Esc puts it back, and it was not taken away
        self.assertEqual(gone, [])
        self.assertEqual(it.pos(), QPointF(*moved[-1]["math1"]))

    def test_n_opens_the_parameter_panel_and_its_fields_send_edits(self):
        def build(e):
            m = ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/math"}, 300, 160)
            n = ng.add_node(e["graph"], {"type": ng.PARAMS}, 0, 160)
            ng.expose(e["graph"], e["params"], n, m, "param:value")
        ed = self.make(build)
        self.assertTrue(ed.panel.isVisible())                        # (open by default)
        QTest.keyClick(ed.view, Qt.Key_N)
        self.assertFalse(ed.panel.isVisible())
        QTest.keyClick(ed.view, Qt.Key_N)
        self.assertTrue(ed.panel.isVisible())
        self.assertTrue(ed.panel_btn.isChecked())
        edited, moved, gone = [], [], []
        ed.exposedEdited.connect(lambda eid, name, f: edited.append((name, f)))
        ed.exposedMoved.connect(lambda eid, name, d: moved.append((name, d)))
        ed.removeExposedRequested.connect(lambda eid, name: gone.append(name))
        name = ng.exposed(ed.graph)[0]["name"]
        boxes = ed.panel.findChildren(QLineEdit)
        boxes[0].setText("力度")
        boxes[0].editingFinished.emit()
        self.assertEqual(edited[-1], (name, {"label": "力度"}))
        from PySide6.QtWidgets import QDoubleSpinBox, QPushButton
        spins = ed.panel.findChildren(QDoubleSpinBox)
        self.assertEqual(len(spins), 3)                              # (最小 / 最大 / 預設)
        spins[1].setValue(5)
        spins[1].editingFinished.emit()
        self.assertEqual(edited[-1], (name, {"hi": 5.0}))
        buttons = {b.text(): b for b in ed.panel.findChildren(QPushButton)}
        buttons["✕"].click()
        self.assertEqual(gone, [name])
        QTest.keyClick(ed.view, Qt.Key_N)
        self.assertFalse(ed.panel.isVisible())

    def test_a_node_dragged_by_its_body_is_an_endless_drag(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/math"}, 300, 160)
        ed = self.make(build)
        v = ed.view
        moved = []
        ed.moveRequested.connect(lambda eid, m: moved.append(m))
        it = v.items_by_id["math1"]
        at = it.mapToScene(QPointF(it.w / 2, 4))                      # (its head)
        pa = v.mapFromScene(at)
        QTest.mousePress(v.viewport(), Qt.LeftButton, Qt.NoModifier, pa)
        QTest.mouseMove(v.viewport(), pa + QPoint(60, 40))
        self.assertTrue(v.wrap.on)
        QTest.mouseRelease(v.viewport(), Qt.LeftButton, Qt.NoModifier, pa + QPoint(60, 40))
        self.assertFalse(v.wrap.on)
        self.assertEqual(list(moved[-1]), ["math1"])

    def test_the_head_widens_a_node_from_its_right_edge_too(self):
        ed = self.make()
        it = ed.view.items_by_id["output"]
        self.assertTrue(it.edge_at(QPointF(it.w - 2, 4)))
        self.assertFalse(it.edge_at(QPointF(it.w / 2, 4)))

    def test_width_is_kept(self):
        def g(e):
            e["graph"]["nodes"]["output"]["width"] = 300.0
        ed = self.make(g)
        self.assertEqual(ed.view.items_by_id["output"].w, 300.0)

    def test_typing_goes_past_the_range_dragging_does_not(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:blender_glare"}, 0, 150)
            e["params"].update(ng.default_params(e["graph"]))
        ed = self.make(build)
        it = ed.view.items_by_id["builtin_blender_glare1"]
        row = next(r for r in it.rows if r["socket"] == "param:sun_position")
        ed.set_number("builtin_blender_glare1", row, 0, -1.0)                     # typed: no limit
        self.assertEqual(ed.params["builtin_blender_glare1.sun_position"][0], -1.0)
        ed.set_number("builtin_blender_glare1", row, 1, 5.0, final=False)         # dragged: the soft range
        self.assertEqual(ed.params["builtin_blender_glare1.sun_position"][1], 1.0)

    def test_media_nodes_choose_their_picture_inside_the_node(self):
        ed = self.make()
        nid = ng.add_node(ed.graph, {"type": ng.SOURCE, "kind": "image"}, 0, 100)
        kid = ng.add_node(ed.graph, {"type": ng.SOURCE, "kind": "compound"}, 0, 300)
        ed.sources[nid] = {"kind": "image"}
        ed.sources[kid] = {"kind": "compound"}
        ed.set_media([("/m/a.png", "貓")], [], [("k1", "片頭")])
        ed.rebuild()
        item = ed.view.items_by_id[nid]
        row = next(r for r in item.rows if r["kind"] == "media")
        self.assertEqual((row["label"], ed.media_name("image", ed.sources[nid])), ("圖片", ""))
        ed.sources[nid]["image"] = "/m/a.png"
        ed.sources[kid]["compound_id"] = "k1"
        self.assertEqual((ed.media_name("image", ed.sources[nid]), ed.media_name("compound", ed.sources[kid])), ("貓", "片頭"))
        ed.sources[nid]["image"] = "/gone/b.png"
        self.assertEqual(ed.media_name("image", ed.sources[nid]), "b.png")
        menus, got = [], []
        ed.popup = lambda menu, pos: menus.append(menu)
        ed.mediaChosen.connect(lambda *a: got.append(a))
        ed.field_clicked(item, row, 0, QPoint(0, 0))
        self.assertEqual([a.text() for a in menus[0].actions() if a.text()], ["貓", "瀏覽圖片檔…"])
        menus[0].actions()[0].trigger()
        self.assertEqual(got, [(ed.eid, nid, "/m/a.png")])

    def test_shape_ratio_field_is_its_own(self):
        ed = self.make()
        nid = ng.add_node(ed.graph, {"type": ng.SOURCE, "kind": "shape", "asset": {"key": "ring", "family": "ellipse"}}, 0, 100)
        ed.params.update(ng.default_params(ed.graph))
        ed.sources[nid] = {"kind": "shape", "cx": 0.0, "cy": 0.0, "w": 1.0, "h": 1.0, "rotation": 0.0, "fit": 0.0}
        names = [p.name for p in ng.asset_def(ed.graph["nodes"][nid]).params + ng.place_params()]
        self.assertEqual(len(names), len(set(names)))                      # (no field shares a name with where it sits)
        self.assertIn("ratio", names)
        self.assertIn("fit", names)

    def test_gradient_picture_follows_the_ramps_choices(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:blender_color_ramp"}, 0, 150)
            e["params"].update(ng.default_params(e["graph"]))
        ed = self.make(build)
        key = "builtin_blender_color_ramp1."
        vals = ed.node_values("builtin_blender_color_ramp1")
        self.assertEqual(ed.view.items_by_id["builtin_blender_color_ramp1"].ramp_options(vals), (2, 0, 0))
        ed.params[key + "interp"] = "固定"
        ed.params[key + "mode"] = "HSV"
        opts = ed.view.items_by_id["builtin_blender_color_ramp1"].ramp_options(ed.node_values("builtin_blender_color_ramp1"))
        self.assertEqual(opts, (4, 1, 0))                                 # constant (the shader's 4), HSV (1)
        stops = [[0.0, [1, 0, 0, 1]], [1.0, [0, 0, 1, 1]]]
        self.assertEqual(fx.gradient_color(stops, 0.5, 4), [1, 0, 0, 1])    # constant: holds the left stop
        mid = fx.gradient_color(stops, 0.5, 2)
        self.assertAlmostEqual(mid[0], 0.5)

    def test_rows_follow_the_operation(self):
        def build(e):
            ng.add_node(e["graph"], {"type": ng.FILTER, "ref": "builtin:nodes/math"}, 0, 150)
            e["params"].update(ng.default_params(e["graph"]))
        ed = self.make(build)

        def sockets():
            return [r["socket"] for r in ed.view.items_by_id["math1"].rows if r["socket"]]
        self.assertIn("b", sockets())                                  # (相加: A and B)
        self.assertNotIn("c", sockets())
        self.assertNotIn("param:value3", sockets())
        ed.params["math1.op"] = 4                                      # 乘加: C too
        ed.show_clip(clip_with(lambda e: None) | {"effects": [{"id": ed.eid, "filter": fx.GRAPH, "params": ed.params, "graph": ed.graph}]})
        self.assertIn("c", sockets())
        ed.params["math1.op"] = 9                                      # 絕對值: A alone
        ed.show_clip({"id": "c1", "type": "image", "effects": [{"id": ed.eid, "filter": fx.GRAPH, "params": ed.params, "graph": ed.graph}]})
        self.assertNotIn("b", sockets())
        self.assertNotIn("param:value", sockets())

    def test_a_selects_all(self):
        ed = self.make()
        QTest.keyClick(ed.view, Qt.Key_A)
        self.assertEqual(set(ed.selected()), {"input", "output"})

    def test_redraws_only_when_the_graph_changed(self):
        ed = self.make()
        item = ed.view.items_by_id["input"]
        ed.show_clip(clip_with())
        self.assertIs(ed.view.items_by_id["input"], item)


if __name__ == "__main__":
    unittest.main()
