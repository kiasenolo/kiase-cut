"""Text alignment (對齊): left, centre, right and justified (齊頭尾) lines; a keyframeable choice."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kiasecut import edit, textlayout  # noqa: E402
from test_edit import S, proj  # noqa: E402


def ink_span(im, row_lo, row_hi):
    """(first, last) column with ink in rows row_lo .. row_hi."""
    a = im.getchannel("A").crop((0, row_lo, im.width, row_hi))
    box = a.getbbox()
    return (box[0], box[2]) if box else None


class TextAlignTests(unittest.TestCase):
    def spec(self, align):
        return {"content": "WWWWWWWW\nii i\nWWWW", "size": 5.0, "align": align}

    def lines(self, align):
        im = textlayout.render(self.spec(align), 1.0)
        h = im.height
        thirds = [(round(h * i / 3) + 2, round(h * (i + 1) / 3) - 2) for i in range(3)]
        return [ink_span(im, a, b) for a, b in thirds]

    def test_alignments(self):
        top, mid, bottom = self.lines("left")
        self.assertLess(abs(mid[0] - top[0]), 4)                     # left edges together
        self.assertLess(abs(bottom[0] - top[0]), 4)
        top, mid, bottom = self.lines("right")
        self.assertLess(abs(mid[1] - top[1]), 4)                     # right edges together
        top, mid, _ = self.lines("center")
        self.assertLess(abs((mid[0] + mid[1]) - (top[0] + top[1])), 6)
        top, mid, bottom = self.lines("justify")
        self.assertLess(abs(mid[0] - top[0]), 4)                     # spread edge to edge
        self.assertLess(abs(mid[1] - top[1]), 6)
        self.assertGreater(top[1] - bottom[1], 20)                   # the last line is not spread

    def test_edit_and_keyframes(self):
        p = proj()
        c = edit.add_text(p, 0, "hello", S)
        edit.set_param(p, c["id"], "text", "align", "right")
        self.assertEqual(c["text"]["align"], "right")
        with self.assertRaises(edit.EditError):
            edit.set_param(p, c["id"], "text", "align", "middle")
        edit.toggle_key(p, c["id"], "text", "align", 0)
        edit.set_param(p, c["id"], "text", "align", "justify", S // 2)
        from kiasecut import curves
        self.assertEqual(curves.value(c["text"]["align"], S // 4), "right")        # held
        self.assertEqual(curves.value(c["text"]["align"], S * 3 // 4), "justify")


if __name__ == "__main__":
    unittest.main()
