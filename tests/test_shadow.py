"""陰影: every picture clip has one in its 畫面 (transform shadow_*): the inspector shows and edits it, edit.set_param stores it, and
project.visual_effects(c, True) gives the effect that draws it (the renderers' own test is in test_glrender)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, project  # noqa: E402
from test_edit import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


class Shadow(unittest.TestCase):
    def test_the_effect_is_there_only_when_it_is_on(self):
        p = proj()
        c = edit.find(p, "c1")[1]
        self.assertEqual(project.visual_effects(c, True), [])
        edit.set_param(p, "c1", "transform", "shadow_on", True)
        edit.set_param(p, "c1", "transform", "shadow_x", 12)
        [e] = project.visual_effects(c, True)
        self.assertEqual((e["filter"], e["params"]["x"], e["params"]["on"]), (project.SHADOW, 12.0, True))
        self.assertEqual(project.visual_effects(c), [])                  # (a filter clip or 套用至背景 works on the effects without it)

    def test_the_inspector_shows_and_edits_it(self):
        from kiasecut.ui.inspector import Inspector
        p = proj()
        c = edit.find(p, "c1")[1]
        ins = Inspector()
        got = []
        ins.paramEdited.connect(lambda ids, g, k, v: got.append((g, k, v)))
        ins.show_clips([c], 0, 30)
        self.assertFalse(ins.widgets["shadow_on"].isChecked())
        self.assertEqual(ins.widgets[("transform", "shadow_blur")].value(), 8.0)
        ins.widgets["shadow_on"].click()
        self.assertEqual(got[-1], ("transform", "shadow_on", True))
        edit.set_param(p, "c1", "transform", "shadow_on", True)
        edit.set_param(p, "c1", "transform", "shadow_color", [1.0, 0.0, 0.0])
        ins.show_clips([c], 0, 30)
        self.assertTrue(ins.widgets["shadow_on"].isChecked())
        self.assertEqual(ins.widgets["shadow_color"].text(), "#ff0000")


if __name__ == "__main__":
    unittest.main()
