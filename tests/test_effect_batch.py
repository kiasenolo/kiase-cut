"""新增效果 with several clips selected (批量): the filter goes on each picture clip of the
selection, from the menu, the file picker or a drop in the effects panel."""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit  # noqa: E402
from kiasecut.ui.effects_panel import EffectsPanel  # noqa: E402
from kiasecut.ui.main_window import MainWindow  # noqa: E402
from kiasecut.ui.vfx_panel import FX_MIME, effect_mime  # noqa: E402
from test_edit import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


def chain(p, cid):
    return [e["filter"] for e in edit.find(p, cid)[1].get("effects") or []]


class EffectBatchTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.names = []

    def host(self):
        p = self.p
        h = types.SimpleNamespace(apply=lambda name, fn, *a: (self.names.append(name), fn(p, *a)))
        h.add_effects_to = lambda ids, refs: MainWindow.add_effects_to(h, ids, refs)
        return h

    def clips(self, *ids):
        return [edit.find(self.p, cid)[1] for cid in ids]

    def test_panel_offers_add_for_a_multi_selection(self):
        panel = EffectsPanel()
        got = []
        panel.addRequested.connect(lambda ids, ref: got.append((ids, ref)))
        panel.show_clips(self.clips("c1", "c2", "c3"), 0, 30)              # c3 is a sound
        self.assertTrue(panel.add_btn.isEnabled())
        self.assertEqual(panel.targets(), ["c1", "c2"])
        panel._add("builtin:blur")
        self.assertEqual(got, [(["c1", "c2"], "builtin:blur")])
        panel.show_clips(self.clips("c3"), 0, 30)
        self.assertFalse(panel.add_btn.isEnabled())
        panel.show_clips(self.clips("c1"), 0, 30)                          # one clip: as before
        self.assertEqual(panel.targets(), ["c1"])
        panel._add("builtin:invert")
        self.assertEqual(got[-1], (["c1"], "builtin:invert"))

    def test_added_to_each_in_one_step(self):
        host = self.host()
        MainWindow.add_effects_to(host, ["c1", "c2"], ["builtin:blur", "builtin:invert"])
        self.assertEqual(chain(self.p, "c1"), ["builtin:blur", "builtin:invert"])
        self.assertEqual(chain(self.p, "c2"), ["builtin:blur", "builtin:invert"])
        self.assertEqual(self.names, ["新增效果（2 個片段）"])
        a, b = (edit.find(self.p, c)[1]["effects"][0]["id"] for c in ("c1", "c2"))
        self.assertNotEqual(a, b)                                           # each its own effect

    def test_dropped_in_the_panel(self):
        edit.add_effect(self.p, "c1", "builtin:blur")
        blur = edit.find(self.p, "c1")[1]["effects"][0]
        edit.set_param(self.p, "c1", "fx:" + blur["id"], "radius", 42.0)
        panel = EffectsPanel()
        panel.resize(360, 600)
        panel.show()
        panel.show_clips(self.clips("c1", "c2"), 0, 30)
        APP.processEvents()
        got = []
        panel.effectsDropped.connect(lambda ids, payload: got.append((ids, payload)))
        md = effect_mime(blur, "c1")
        pos = QPointF(20, 60)
        enter = QDragEnterEvent(pos.toPoint(), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(panel, enter)
        self.assertTrue(enter.isAccepted())
        QApplication.sendEvent(panel, QDropEvent(pos, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
        self.assertEqual(got[0][0], ["c1", "c2"])
        MainWindow.effects_dropped(self.host(), *got[0])
        self.assertEqual(chain(self.p, "c1"), ["builtin:blur", "builtin:blur"])
        self.assertEqual(edit.find(self.p, "c2")[1]["effects"][0]["params"]["radius"], 42.0)
        self.assertEqual(self.names, ["複製效果（2 個片段）"])
        panel.hide()


if __name__ == "__main__":
    unittest.main()
