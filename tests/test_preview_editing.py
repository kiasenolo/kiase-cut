"""On the preview: an effect's 範圍 mask dragged like the clip's own (編輯遮罩 in the 效果 tab),
and a text clip's words typed in by double-clicking it."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit  # noqa: E402
from kiasecut.ui.effects_panel import EffectsPanel  # noqa: E402
from kiasecut.ui.preview import Preview  # noqa: E402
from test_edit import S, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
NONE = Qt.KeyboardModifier.NoModifier


def preview(p, selected, t=S // 2):
    pv = Preview()
    pv.resize(960, 540)                              # the 1920 x 1080 canvas at half size
    pv.set_scene(p, t, selected)
    return pv


class EffectMaskTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.e = edit.add_effect(self.p, "c1", "builtin:blur")
        edit.set_effect_mask(self.p, "c1", self.e["id"], "rectangle")

    def drag(self, pv, a, b):
        got = []
        pv.paramsCommitted.connect(lambda *args: got.append(args))
        QTest.mousePress(pv, Qt.LeftButton, NONE, a)
        QTest.mouseMove(pv, (a + b) / 2)
        QTest.mouseMove(pv, b)
        QTest.mouseRelease(pv, Qt.LeftButton, NONE, b)
        return got

    def test_drag_moves_the_effects_mask(self):
        pv = preview(self.p, "c1")
        pv.set_mask_mode(True, "fxmask:" + self.e["id"])
        got = self.drag(pv, QPoint(480, 270), QPoint(580, 270))
        self.assertEqual(len(got), 1)
        cid, group, vals = got[0]
        self.assertEqual((cid, group), ("c1", "fxmask:" + self.e["id"]))
        self.assertGreater(vals["cx"], 0.1)
        edit.set_param(self.p, cid, group, "cx", vals["cx"], 0)          # and it is a valid edit
        self.assertEqual(self.e["mask"]["cx"], vals["cx"])

    def test_clip_without_that_mask_is_left_alone(self):
        pv = preview(self.p, "c1")
        pv.set_mask_mode(True, "mask")                                  # c1 has no mask of its own
        self.assertFalse(pv.masking(pv.selected_box()))
        self.assertEqual(self.drag(pv, QPoint(480, 270), QPoint(580, 270)), [])
        self.assertEqual(edit.find(self.p, "c1")[1]["transform"]["x"], 0.0)

    def test_panel_toggle(self):
        panel = EffectsPanel()
        c1 = edit.find(self.p, "c1")[1]
        changes = []
        panel.maskEditChanged.connect(lambda: changes.append(panel.mask_edit))
        panel.show_clips([c1], 0, 30)
        btn = panel.widgets[("mask_edit", self.e["id"])]
        btn.click()
        self.assertEqual(panel.mask_edit, self.e["id"])
        edit.set_effect_mask(self.p, "c1", self.e["id"], None)          # the range removed
        panel.show_clips([c1], 0, 30)
        self.assertIsNone(panel.mask_edit)
        self.assertEqual(changes[-1], None)
        panel._kind_chosen(self.e["id"], "circle")                      # picking a shape switches it on
        self.assertEqual(panel.mask_edit, self.e["id"])


class TextOnPreviewTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.t = edit.add_text(self.p, 0, "hello")
        self.pv = preview(self.p, self.t["id"])
        self.pv.show()
        self.got = []
        self.pv.textEdited.connect(lambda cid, words: self.got.append((cid, words)))
        QTest.mouseDClick(self.pv, Qt.LeftButton, NONE, QPoint(480, 270))   # the text is centred

    def test_double_click_opens_a_box_with_the_words(self):
        tb = self.pv.text_box
        self.assertIsNotNone(tb)
        self.assertEqual(tb.toPlainText(), "hello")
        tb.setPlainText("你好\n世界")
        QTest.keyClick(tb, Qt.Key_Return, Qt.ControlModifier)
        self.assertIsNone(self.pv.text_box)
        self.assertEqual(self.got, [(self.t["id"], "你好\n世界")])

    def test_esc_puts_the_words_back(self):
        tb = self.pv.text_box
        tb.setPlainText("oops")
        tb.flush()                                                      # (typing paused: sent)
        QTest.keyClick(tb, Qt.Key_Escape)
        self.assertIsNone(self.pv.text_box)
        self.assertEqual(self.got[-1], (self.t["id"], "hello"))

    def test_double_click_elsewhere_does_nothing(self):
        self.pv.close_text_box()
        self.pv.set_scene(self.p, S // 2, "c1")
        QTest.mouseDClick(self.pv, Qt.LeftButton, NONE, QPoint(10, 10))   # on the picture c1, no text there
        self.assertIsNone(self.pv.text_box)


if __name__ == "__main__":
    unittest.main()
