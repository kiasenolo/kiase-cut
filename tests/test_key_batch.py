"""批量編輯關鍵幀: keyframes of other clips alike the edited curve's (a frame apart, whatever
their values; the closer value first) are paired, and a move, a new value or ease, a removal
or an added key is done to them too, each keeping its own difference (a typed value: set)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import keybatch  # noqa: E402
from kiasecut.ui.curve_editor import CurveEditor  # noqa: E402
from kiasecut.ui.main_window import same_group  # noqa: E402

APP = QApplication.instance() or QApplication([])
S = 1_000_000
FPS = 30
FRAME = S // FPS


def k(t, v, *h):
    return [t, v, *(list(h) or [0.0, 0.0, 0.0, 0.0])]


class MatchTests(unittest.TestCase):
    def test_same_and_close_keys_pair(self):
        a = [k(0, 0.0), k(S, 0.5), k(2 * S, 1.0)]
        b = [k(0, 0.0), k(S + FRAME, 0.505), k(2 * S, 1.0)]          # a frame later, 1% off
        self.assertEqual(keybatch.match(a, b, FPS), {0: 0, 1: 1, 2: 2})

    def test_far_keys_do_not(self):
        a = [k(0, 0.0), k(S, 0.5)]
        self.assertEqual(keybatch.match(a, [k(0, 0.0), k(S + 2 * FRAME, 0.5)], FPS), {0: 0})   # two frames

    def test_different_values_at_the_same_time_pair(self):
        a = [k(0, 0.0), k(S, 0.5)]
        self.assertEqual(keybatch.match(a, [k(0, 0.3), k(S, 6.0)], FPS), {0: 0, 1: 1})
        self.assertEqual(keybatch.match([k(0, [1.0, 0.5, 0.0])], [k(0, [0.2, 0.9, 0.4])], FPS), {0: 0})
        self.assertEqual(keybatch.match([k(0, "circle")], [k(0, "line")], FPS), {0: 0})

    def test_the_closer_value_wins_a_tie(self):
        other = [k(0, 9.0), k(20_000, 1.0)]                             # as near: 10 ms each way
        self.assertEqual(keybatch.match([k(10_000, 1.0)], other, FPS), {0: 1})
        self.assertEqual(keybatch.match([k(0, 1.0)], other, FPS), {0: 0})   # nearer in time first

    def test_each_key_pairs_once(self):
        self.assertEqual(keybatch.match([k(0, 1.0), k(FRAME, 1.0)], [k(0, 1.0)], FPS), {0: 0})


class CarryTests(unittest.TestCase):
    def carry(self, old, new, other):
        return keybatch.carry(old, new, other, FPS, 5 * S, S // 120)

    def test_move_keeps_each_ones_difference(self):
        old = [k(0, 0.0), k(S, 0.5)]
        new = [k(0, 0.0), k(S + 3 * FRAME, 0.8)]
        other = [k(0, 0.0), k(S + FRAME, 0.502), k(3 * S, 9.0)]       # (the last one is not alike)
        keys, keep = self.carry(old, new, other)
        self.assertEqual(keys[1][0], S + 4 * FRAME)
        self.assertAlmostEqual(keys[1][1], 0.802)
        self.assertEqual(keys[2], k(3 * S, 9.0))
        self.assertIsNone(keep)

    def test_new_ease(self):
        old = [k(0, 0.0), k(S, 1.0)]
        new = [k(0, 0.0, 0.0, 0.0, 400_000, 0.0), k(S, 1.0)]
        keys, _ = self.carry(old, new, [k(0, 0.0), k(S, 1.0)])
        self.assertEqual(keys[0], k(0, 0.0, 0.0, 0.0, 400_000, 0.0))

    def test_remove_and_remove_all(self):
        old = [k(0, 0.0), k(S, 0.5), k(2 * S, 1.0)]
        keys, _ = self.carry(old, [old[0], old[2]], [k(0, 0.0), k(S, 0.5), k(2 * S, 1.0)])
        self.assertEqual([x[0] for x in keys], [0, 2 * S])
        keys, keep = self.carry(old, [], [k(0, 0.005), k(S, 0.5), k(2 * S, 1.0)])
        self.assertEqual((keys, keep), ([], 0.005))                   # (its own first value stays)
        keys, _ = self.carry(old, [], [k(0, 0.2), k(S, 0.5), k(2 * S, 1.0), k(3 * S, 4.0)])
        self.assertEqual(keys, [k(3 * S, 4.0)])                        # (at no time of the edited curve: kept)

    def test_added_key_follows_the_others_curve(self):
        old = [k(0, 0.0), k(2 * S, 1.0)]
        new = [k(0, 0.0), k(S, 0.9), k(2 * S, 1.0)]                     # 0.4 above the line
        keys, _ = self.carry(old, new, [k(0, 0.0), k(2 * S, 1.005)])
        self.assertEqual(keys[1][0], S)
        self.assertAlmostEqual(keys[1][1], 0.5025 + 0.4, 3)

    def test_different_values_move_by_as_much_or_take_a_typed_one(self):
        old = [k(0, 0.0), k(S, 0.5)]
        new = [k(0, 0.0), k(S, 0.8)]
        other = [k(0, 2.0), k(S, 5.0)]
        keys, _ = self.carry(old, new, other)
        self.assertAlmostEqual(keys[1][1], 5.3)
        self.assertEqual(keys[0], k(0, 2.0))                           # (left alone)
        keys, _ = keybatch.carry(old, new, other, FPS, 5 * S, S // 120, absolute=True)
        self.assertEqual([x[1] for x in keys], [2.0, 0.8])

    def test_nothing_alike_or_a_clash(self):
        self.assertIsNone(self.carry([k(0, 0.0)], [k(FRAME, 0.0)], [k(2 * FRAME, 5.0)]))
        old = [k(0, 0.0), k(S, 0.5)]
        other = [k(0, 0.0), k(S, 0.5), k(S + 2 * FRAME, 7.0)]            # moved onto a key of its own
        self.assertIsNone(self.carry(old, [k(0, 0.0), k(S + 2 * FRAME, 0.5)], other))


class EditorTests(unittest.TestCase):
    def test_toggle_and_rings(self):
        ed = CurveEditor()
        c = {"id": "c", "type": "image", "start_us": 0, "duration_us": 2 * S,
             "transform": {"x": {"keys": [k(0, 0.0), k(S, 0.5)]}, "y": 0.0, "scale": 1.0, "rotation": 0.0,
                           "opacity": 1.0}}
        ed.set_clip(c, 0, FPS)
        ed.set_links(2, 0, {})
        self.assertFalse(ed.batch_on())
        self.assertIn("沒有同時間", ed.batch.text())
        ed.set_links(2, 2, {("transform", "x"): {0: 2, 1: 1}})
        self.assertTrue(ed.batch_on())
        ci = [r[:2] for r in ed.shown].index(("transform", "x"))
        self.assertEqual(ed.canvas.linked[ci], {0: 2, 1: 1})
        ed.batch.setChecked(False)
        self.assertFalse(ed.batch_on())
        self.assertEqual(ed.canvas.linked, {})

    def test_filters_pair_by_kind_and_place(self):
        a = {"effects": [{"id": "e1", "filter": "blur"}, {"id": "e2", "filter": "glow"}, {"id": "e3", "filter": "glow"}]}
        b = {"effects": [{"id": "f1", "filter": "glow"}, {"id": "f2", "filter": "glow"}]}
        self.assertEqual(same_group(a, b, "fx:e3"), "fx:f2")
        self.assertEqual(same_group(a, b, "fxmask:e2"), "fxmask:f1")
        self.assertIsNone(same_group(a, b, "fx:e1"))
        self.assertEqual(same_group(a, b, "transform"), "transform")


if __name__ == "__main__":
    unittest.main()
