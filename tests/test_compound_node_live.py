"""讀取時間 on a compound node of a node effect: a static compound it shows is drawn afresh at the time read, not as a still."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, fx, render  # noqa: E402
from test_compound_mask import HAVE_GL, Scene, W, H, rgb  # noqa: E402
from test_edit import proj  # noqa: E402
from test_vector_nodes import RenderBase  # noqa: E402

APP = QApplication.instance() or QApplication([])


class CompoundNodeLiveTests(RenderBase):
    def view(self, live):
        inner = self.s.pic("m", self.s.red)
        inner["effects"] = [fx.new_effect("builtin:hue_cycle", "e9")]
        view = self.s.view(inner=[inner], static=True)
        p = proj()
        eff = edit.add_effect(p, "c1", fx.GRAPH)
        n = edit.add_graph_node(p, "c1", eff["id"], {"type": "source", "kind": "compound"})
        eff["sources"][n].update(compound_id="k1", cx=0.0, cy=0.0, w=1.0, h=1.0)
        edit.connect_graph(p, "c1", eff["id"], n, "output", "src")
        edit.set_effect_source_live(p, "c1", eff["id"], n, live)
        view["tracks"][0]["clips"][0]["effects"] = [eff]
        return view

    def test_the_compound_is_a_still_unless_it_reads_the_time(self):
        for r in self.renderers[1:]:                                        # (the GPU one: the CPU one cannot run a filter inside a compound inside a node effect)
            r.render(self.view(False), 0, W, H)
            still = [rgb(r.render(self.view(False), f, W, H), W // 2, H // 2) for f in (0, 30)]
            self.assertEqual(still[0], still[1])
            r.render(self.view(True), 0, W, H)
            live = [rgb(r.render(self.view(True), f, W, H), W // 2, H // 2) for f in (0, 30)]
            self.assertNotEqual(live[0], live[1])

    def test_only_a_compound_node_has_it(self):
        p = proj()
        eff = edit.add_effect(p, "c1", fx.GRAPH)
        n = edit.add_graph_node(p, "c1", eff["id"], {"type": "source", "kind": "image"})
        with self.assertRaises(edit.EditError):
            edit.set_effect_source_live(p, "c1", eff["id"], n, True)


if __name__ == "__main__":
    unittest.main()
