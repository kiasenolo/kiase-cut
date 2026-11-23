"""編輯遮罩 (問12): the preview edits a clip's mask only while the 遮罩 tab's toggle is on - not because the tab is open; it
goes off when another clip (or several) is picked, and choosing a new mask shape turns it on."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit  # noqa: E402
from kiasecut.ui.inspector import Inspector  # noqa: E402
from test_edit import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


class MaskEditToggleTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        edit.set_mask(self.p, "c1", "circle")
        self.mp = Inspector(part="mask")
        self.changed = []
        self.mp.maskEditChanged.connect(lambda: self.changed.append(self.mp.mask_edit))
        self.c1, self.c2 = edit.find(self.p, "c1")[1], edit.find(self.p, "c2")[1]

    def test_off_until_asked_and_off_on_another_clip(self):
        self.mp.show_clips([self.c1], 0, 30)
        self.assertFalse(self.mp.mask_edit)
        self.mp.widgets["mask_edit"].setChecked(True)
        self.assertEqual((self.mp.mask_edit, self.changed), (True, [True]))
        self.mp.show_clips([self.c1], 1000, 30)                  # (the same clip at another time: stays on)
        self.assertTrue(self.mp.mask_edit)
        self.mp.show_clips([self.c2], 0, 30)
        self.assertEqual((self.mp.mask_edit, self.changed[-1]), (False, False))

    def test_a_new_shape_turns_it_on(self):
        got = []
        self.mp.maskKindChosen.connect(lambda ids, kind: got.append(kind))
        self.mp.show_clips([self.c2], 0, 30)
        self.assertIn("mask_edit", self.mp.widgets)            # (also before there is a mask: P draws a 路徑 one)
        self.mp._mask_kind_chosen("rectangle")
        self.assertTrue(self.mp.mask_edit)
        self.assertEqual(got, ["rectangle"])


if __name__ == "__main__":
    unittest.main()
