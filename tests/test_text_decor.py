"""A text's shadow and background: the background's padding on each side."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from kiasecut import components, edit, project, textlayout, userlib  # noqa: E402
from test_edit import S  # noqa: E402


def spec(**kw):
    s = {"content": "HI", "size": 7.95, "color": [1, 1, 1], "bg_on": True, "bg_color": [1, 0, 0, 1], "bg_radius": 0.0,
         "font_path": project.DEFAULT_FONT}
    s.update(kw)
    return s


def red_box(img):
    """(left, top, right, bottom) of the red background's pixels."""
    a = np.asarray(img)
    red = (a[..., 0] > 200) & (a[..., 1] < 60) & (a[..., 3] > 200)
    ys, xs = np.nonzero(red)
    return xs.min(), ys.min(), xs.max(), ys.max()


class PaddingTests(unittest.TestCase):
    def test_each_side_has_its_own(self):
        def size(**pads):
            l, t, r, b = red_box(textlayout.render(spec(**pads), 1.0, 1080))
            return r - l, b - t
        zero = dict(bg_pad_l=0, bg_pad_r=0, bg_pad_t=0, bg_pad_b=0)
        w0, h0 = size(**zero)
        w, h = size(**dict(zero, bg_pad_l=40))
        self.assertAlmostEqual(w - w0, 40, delta=2)                               # only the left grew
        self.assertEqual(h, h0)
        w, h = size(**dict(zero, bg_pad_b=30))
        self.assertAlmostEqual(h - h0, 30, delta=2)
        self.assertEqual(w, w0)
        # and it sits to that side of the text: the red reaches further left than right of the glyphs
        img = textlayout.render(spec(bg_pad_l=60, bg_pad_r=0, bg_pad_t=0, bg_pad_b=0), 1.0, 1080)
        l, t, r, b = red_box(img)
        centre = img.size[0] / 2
        self.assertGreater(centre - l, r - centre + 40)

    def test_an_older_text_with_one_padding(self):
        old = red_box(textlayout.render(spec(bg_pad=20), 1.0, 1080))                # (no sides: bg_pad on every side)
        new = red_box(textlayout.render(spec(bg_pad_l=20, bg_pad_r=20, bg_pad_t=20, bg_pad_b=20), 1.0, 1080))
        self.assertEqual(old, new)
        tx = {"bg_pad": 18.0}
        project.legacy_text_padding(tx)
        self.assertEqual([tx[f"bg_pad_{k}"] for k in "lrtb"], [18.0] * 4)
        self.assertEqual(userlib.style_from_clip({"text": dict(tx)})["text"]["bg_pad_t"], 18.0)

    def test_editing_and_components(self):
        p = project.new()
        c = edit.add_text(p, 0, "字", duration_us=S)
        edit.set_param(p, c["id"], "text", "bg_pad_t", 33.0)
        self.assertEqual(c["text"]["bg_pad_t"], 33.0)
        self.assertIn("text.bg_pad_l", components.number_props_of(c))
        out = components._put(c, "text.bg_pad", 9.0)
        self.assertEqual([out["text"][f"bg_pad_{k}"] for k in "lrtb"], [9.0] * 4)


class InspectorTests(unittest.TestCase):
    def test_rows(self):
        from PySide6.QtWidgets import QApplication
        from kiasecut.ui.inspector import Inspector
        APP = QApplication.instance() or QApplication([])
        p = project.new()
        c = edit.add_text(p, 0, "字", duration_us=S)
        c["text"].update(bg_pad_l=4.0, bg_pad_r=4.0, bg_pad_t=4.0, bg_pad_b=4.0)
        ins = Inspector()
        got = []
        ins.paramEdited.connect(lambda ids, g, k, v: got.append((k, v)))
        ins.show_clips([c], 0, 60)
        self.assertEqual(ins.widgets["bg_pad_all"].value(), 4.0)
        for k in "lrtb":
            self.assertIn(("text", f"bg_pad_{k}"), ins.widgets)
        ins.widgets["bg_pad_all"].edited.emit(10.0)
        ins._flush()
        self.assertEqual(sorted(got), [(f"bg_pad_{k}", 10.0) for k in "blrt"])
        c["text"]["bg_pad_t"] = 20.0
        ins.show_clips([c], 0, 60)
        self.assertTrue(ins.widgets["bg_pad_all"].mixed)


if __name__ == "__main__":
    unittest.main()
