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
        self.drag(ed, ed.view.items_by_id["input"].output_pos(), mix.input_pos(1))
        self.assertEqual(got, [("e1", "input", "mix1", "b")])

    def test_picking_up_a_link_and_dropping_it_nowhere_unlinks(self):
        ed = self.make()
        got = []
        ed.disconnectRequested.connect(lambda *a: got.append(a))
        out = ed.view.items_by_id["output"]
        self.drag(ed, out.input_pos(0), out.input_pos(0) + QPointF(-30, 200))
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

    def test_redraws_only_when_the_graph_changed(self):
        ed = self.make()
        item = ed.view.items_by_id["input"]
        ed.show_clip(clip_with())
        self.assertIs(ed.view.items_by_id["input"], item)


if __name__ == "__main__":
    unittest.main()
