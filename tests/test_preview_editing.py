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
from test_edit import S, clip, proj  # noqa: E402

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


class SpacingSnapTests(unittest.TestCase):
    def test_centred_between_neighbours(self):
        pv = Preview()
        others = [(100, 300, 400, 600), (900, 1100, 400, 600)]
        dx, dy, guides = pv._snap((495, 695, 400, 600), 0, 0, others, 7)
        self.assertEqual(dx, 5)                                         # 200 px on each side
        self.assertEqual([g[0] for g in guides if g[0] == "gap"], ["gap", "gap"])

    def test_as_far_as_two_other_clips(self):
        pv = Preview()
        others = [(100, 300, 400, 600), (400, 600, 400, 600)]           # 100 px apart
        dx, _, guides = pv._snap((703, 903, 400, 600), 0, 0, others, 7)
        self.assertEqual(dx, -3)
        self.assertIn("gap", [g[0] for g in guides])
        _, dy, _ = pv._snap((400, 600, 704, 904), 0, 0, [(400, 600, 100, 300), (400, 600, 400, 600)], 7)
        self.assertEqual(dy, -4)                                        # the same up and down

    def test_not_side_by_side(self):
        pv = Preview()
        others = [(100, 300, 0, 100), (400, 600, 0, 100)]               # far above it
        dx, _, _ = pv._snap((703, 903, 400, 600), 0, 0, others, 7)
        self.assertEqual(dx, 0)


class MultiSelectTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        c1 = edit.find(self.p, "c1")[1]
        c1["transform"].update(scale=0.2, x=-0.5)                       # on screen around (240, 270)
        c4 = clip("c4", 0, 2 * S)
        c4["transform"].update(scale=0.2, x=0.5)                        # around (720, 270)
        self.p["tracks"][1]["clips"].append(c4)
        self.pv = preview(self.p, "c1")
        self.picked = []
        self.pv.selectionPicked.connect(lambda ids, primary: self.picked.append((ids, primary)))

    def drag(self, a, b, mods=NONE):
        QTest.mousePress(self.pv, Qt.LeftButton, mods, a)
        QTest.mouseMove(self.pv, (a + b) / 2)
        QTest.mouseMove(self.pv, b)
        QTest.mouseRelease(self.pv, Qt.LeftButton, mods, b)

    def test_shift_click_adds_and_removes(self):
        QTest.mouseClick(self.pv, Qt.LeftButton, Qt.ShiftModifier, QPoint(720, 270))
        self.assertEqual(self.picked[-1], ({"c1", "c4"}, "c4"))
        QTest.mouseClick(self.pv, Qt.LeftButton, Qt.ControlModifier, QPoint(240, 270))
        self.assertEqual(self.picked[-1], ({"c4"}, "c4"))

    def test_selected_clips_move_together(self):
        self.pv.set_scene(self.p, S // 2, "c1", {"c1", "c4"})
        got = []
        self.pv.movesCommitted.connect(got.append)
        self.drag(QPoint(240, 270), QPoint(290, 300))
        self.assertEqual(len(got), 1)
        moves = got[0]
        self.assertEqual(set(moves), {"c1", "c4"})
        self.assertAlmostEqual(moves["c1"]["x"] + 0.5, moves["c4"]["x"] - 0.5, 5)
        self.assertAlmostEqual(moves["c1"]["y"], moves["c4"]["y"], 5)
        self.assertGreater(moves["c1"]["x"], -0.5)

    def test_box_selects_what_it_touches(self):
        self.drag(QPoint(480, 30), QPoint(700, 300))
        self.assertEqual(self.picked[-1], ({"c4"}, "c4"))
        self.drag(QPoint(480, 30), QPoint(100, 300), Qt.ShiftModifier)     # added
        self.assertEqual(self.picked[-1][0], {"c1", "c4"})

    def test_click_on_nothing_selects_nothing(self):
        QTest.mouseClick(self.pv, Qt.LeftButton, NONE, QPoint(480, 30))
        self.assertEqual(self.picked[-1], (set(), None))


class GapHandleTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        edit.find(self.p, "c1")[1]["transform"].update(scale=0.1, x=-0.6)      # 192 px wide
        for cid, x in (("c4", 0.0), ("c5", 0.4)):                              # gaps 384 and 192 px
            c = clip(cid, 0, 2 * S)
            c["transform"].update(scale=0.1, x=x)
            self.p["tracks"][1]["clips"].append(c)
        self.pv = preview(self.p, "c1")
        self.pv.set_scene(self.p, S // 2, "c1", {"c1", "c4", "c5"})

    def gaps(self):
        return self.pv._gaps(self.pv._live_boxes(), self.pv._k())

    def drag_bar(self, bar, by):
        got = []
        self.pv.movesCommitted.connect(got.append)
        mid = (bar[0] + bar[1]) / 2
        a = QPoint(round(mid.x() / 2), round(mid.y() / 2))                     # canvas -> widget (half size)
        QTest.mousePress(self.pv, Qt.LeftButton, NONE, a)
        QTest.mouseMove(self.pv, a + by / 2)
        QTest.mouseMove(self.pv, a + by)
        QTest.mouseRelease(self.pv, Qt.LeftButton, NONE, a + by)
        return got[0]

    def test_a_bar_in_each_gap(self):
        gaps = self.gaps()
        self.assertEqual([(g[0], round(g[4])) for g in gaps], [("x", 384), ("x", 192)])
        self.assertEqual(self.pv._gap_at(gaps[0][2][0][0], self.pv._k())[:2], ("x", 0))

    def test_dragging_a_bar_evens_the_gaps(self):
        moves = self.drag_bar(self.gaps()[1][2][0], QPoint(24, 0))            # the second gap, +48 canvas px
        self.assertEqual(set(moves["c1"]), {"x"})                              # only along the row
        self.assertAlmostEqual(moves["c1"]["x"], -0.6, 5)                      # the first stays
        # 240 px apart: c1 ends at 480, so c4 spans 720..912 and c5 1152..1344
        self.assertAlmostEqual(moves["c4"]["x"], (816 - 960) / 960, 4)
        self.assertAlmostEqual(moves["c5"]["x"], (1248 - 960) / 960, 4)

    def test_overlapping_clips_have_no_bars(self):
        for cid, x in (("c1", -0.05), ("c5", 0.05)):                           # all on top of each other
            edit.find(self.p, cid)[1]["transform"]["x"] = x
        self.pv.set_scene(self.p, S // 2, "c1", {"c1", "c4", "c5"})
        self.assertEqual(self.gaps(), [])

    def test_grid(self):
        # 2 x 2: c1 c4 on top, c5 c6 below (192 x 108 each, 192 px between columns, 108 between rows)
        for cid, x, y in (("c1", -0.2, 0.2), ("c4", 0.2, 0.2), ("c5", -0.2, -0.2), ("c6", 0.2, -0.2)):
            if cid == "c6":
                c = clip("c6", 0, 2 * S)
                c["transform"]["scale"] = 0.1
                self.p["tracks"][1]["clips"].append(c)
            edit.find(self.p, cid)[1]["transform"].update(x=x, y=y)
        self.pv.set_scene(self.p, S // 2, "c1", {"c1", "c4", "c5", "c6"})
        gaps = self.gaps()
        self.assertEqual([(g[0], round(g[4]), len(g[2])) for g in gaps], [("x", 192, 1), ("y", 108, 2)])
        moves = self.drag_bar(gaps[1][2][1], QPoint(0, 20))                    # a row bar, +40 canvas px
        self.assertEqual({cid: set(v) for cid, v in moves.items()}, {c: {"y"} for c in ("c1", "c4", "c5", "c6")})
        self.assertAlmostEqual(moves["c1"]["y"], 0.2, 5)                       # the top row stays
        self.assertAlmostEqual(moves["c6"]["y"], moves["c5"]["y"], 5)
        self.assertAlmostEqual(moves["c5"]["y"], -0.2 - 40 / 540, 4)          # 148 px below it


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

    def test_a_click_elsewhere_finishes(self):
        tb = self.pv.text_box
        tb.setPlainText("bye")
        QTest.mouseClick(tb.viewport(), Qt.LeftButton, NONE, QPoint(5, 5))      # inside: still typing
        self.assertIs(self.pv.text_box, tb)
        QTest.mouseClick(self.pv, Qt.LeftButton, NONE, QPoint(5, 5))           # the preview never takes the focus
        self.assertIsNone(self.pv.text_box)
        self.assertEqual(self.got, [(self.t["id"], "bye")])

    def test_a_click_on_another_part_finishes(self):
        from PySide6.QtWidgets import QPushButton
        other = QPushButton("x")
        other.setFocusPolicy(Qt.NoFocus)                                         # (as the timeline's tools)
        other.show()
        self.addCleanup(other.close)
        self.pv.text_box.setPlainText("done")
        QTest.mouseClick(other, Qt.LeftButton)
        self.assertIsNone(self.pv.text_box)
        self.assertEqual(self.got, [(self.t["id"], "done")])

    def test_double_click_elsewhere_does_nothing(self):
        self.pv.close_text_box()
        self.pv.set_scene(self.p, S // 2, "c1")
        QTest.mouseDClick(self.pv, Qt.LeftButton, NONE, QPoint(10, 10))   # on the picture c1, no text there
        self.assertIsNone(self.pv.text_box)


if __name__ == "__main__":
    unittest.main()
