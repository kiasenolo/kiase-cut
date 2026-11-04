"""The workspace saved with the project (工作區狀態): the node editor's zoom and place, its 參數 panel, the selected
clips and the panels' arrangement come back when the project is opened."""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, fx, project  # noqa: E402
from test_edit import proj  # noqa: E402
from test_node_editor import clip_with  # noqa: E402
from kiasecut.ui.node_editor import NodeEditor  # noqa: E402

APP = QApplication.instance() or QApplication([])


class NodeEditorViewTests(unittest.TestCase):
    def make(self):
        ed = NodeEditor()
        ed.resize(1000, 500)
        ed.show()
        ed.show_clip(clip_with())
        APP.processEvents()
        return ed

    def test_zoom_and_centre_come_back(self):
        ed = self.make()
        ed.view.resetTransform()
        ed.view.scale(0.5, 0.5)
        ed.view.centerOn(300, -120)
        st = json.loads(json.dumps(ed.view_state()))
        other = self.make()
        other.set_view_state(st)
        self.assertAlmostEqual(other.view.transform().m11(), 0.5, places=3)
        c = other.view.mapToScene(other.view.viewport().rect().center())
        self.assertLess(abs(c.x() - st["cx"]) + abs(c.y() - st["cy"]), 6)       # (scroll bars move by whole pixels)

    def test_panel_state_comes_back(self):
        ed = self.make()
        ed.set_panel(False)
        st = ed.view_state()
        self.assertFalse(st["panel"])
        other = self.make()
        other.set_view_state(st)
        self.assertFalse(other.panel_btn.isChecked())
        self.assertFalse(other.panel.isVisible())
        other.set_view_state({"panel": True, "panel_w": 250})
        self.assertTrue(other.panel.isVisible())

    def test_a_gone_effect_is_left_out(self):
        ed = self.make()
        before = ed.view.transform().m11()
        ed.set_view_state({"effect": "nope", "zoom": 3.0, "cx": 1, "cy": 1, "panel": True})
        self.assertEqual(ed.view.transform().m11(), before)
        ed.set_view_state("junk")
        ed.set_view_state({"effect": ed.eid, "zoom": "x"})


class WorkspaceRoundTripTests(unittest.TestCase):
    def test_saved_with_the_view_and_restored(self):
        from kiasecut.ui.main_window import MainWindow
        win = MainWindow()
        self.addCleanup(win.close)
        win.show()
        p = proj()
        e = edit.add_effect(p, "c1", fx.GRAPH)
        win.relink = lambda pr: True
        win.set_project(p)
        win.timeline.select(edit.find(win.proj, "c1")[1])
        APP.processEvents()
        self.assertEqual(win.nodes.eid, e["id"])
        win.nodes.view.resetTransform()
        win.nodes.view.scale(0.7, 0.7)
        win.nodes.view.centerOn(50, 60)
        win.nodes.set_panel(False)
        view = json.loads(json.dumps(win.view_state()))           # (what the file holds)
        ws = view["workspace"]
        self.assertEqual(ws["selected"], ["c1"])
        self.assertEqual(ws["nodes"]["effect"], e["id"])
        self.assertIn("state", ws["panels"])
        win.timeline.set_selection(set())
        win.nodes.view.resetTransform()
        win.nodes.set_panel(True)
        APP.processEvents()
        win.restore_workspace(ws)
        APP.processEvents()
        self.assertEqual([c["id"] for c in win.timeline.selected_clips_primary_first()], ["c1"])
        self.assertAlmostEqual(win.nodes.view.transform().m11(), 0.7, places=3)
        self.assertFalse(win.nodes.panel_btn.isChecked())

    def test_junk_is_left_out(self):
        from kiasecut.ui.main_window import MainWindow
        win = MainWindow()
        self.addCleanup(win.close)
        win.restore_workspace(None)
        win.restore_workspace({"layout": 3, "panels": {"state": 4}, "selected": "x", "nodes": []})


if __name__ == "__main__":
    unittest.main()
