"""Text alignment (對齊): left, centre, right and justified (齊頭尾) lines; a keyframeable choice.
The 文字框 (Lunacy's text frame): auto width (the default), auto height (wraps), fixed size with
top / middle / bottom; switching keeps the text where it is; the preview's handles resize it."""
import os
import sys
import unittest
import numpy as np
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kiasecut import edit, textlayout  # noqa: E402
from test_edit import S, proj  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])


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

    def test_fill_outline_and_keyframes(self):
        p = proj()
        c = edit.add_text(p, 0, "O")
        spec = dict(c["text"], stroke_on=True, stroke_color=[1.0, 0.0, 0.0], stroke=5.0, fill=False)
        outlined = textlayout.render(spec, 1.0)
        filled = textlayout.render(dict(spec, fill=True), 1.0)
        outline_alpha = np.frombuffer(outlined.getchannel("A").tobytes(), dtype=np.uint8)
        fill_alpha = np.frombuffer(filled.getchannel("A").tobytes(), dtype=np.uint8)
        self.assertGreater(int(outline_alpha.sum()), 0)
        self.assertLess(int(outline_alpha.sum()), int(fill_alpha.sum()))
        pixels = outlined.load()
        self.assertTrue(any(pixels[x, y][0] > pixels[x, y][1] * 1.5
                            for y in range(outlined.height) for x in range(outlined.width)
                            if pixels[x, y][3]))

        edit.toggle_key(p, c["id"], "text", "stroke_on", 0)
        edit.set_param(p, c["id"], "text", "stroke_on", True, S // 2)
        from kiasecut import curves
        self.assertFalse(curves.value(c["text"]["stroke_on"], S // 4))
        self.assertTrue(curves.value(c["text"]["stroke_on"], 3 * S // 4))

        c["text"].pop("fill")
        edit.toggle_key(p, c["id"], "text", "fill", 0)
        self.assertTrue(curves.value(c["text"]["fill"], 0))

    def test_outline_alignment_changes_its_bounds_and_is_keyframeable(self):
        p = proj()
        c = edit.add_text(p, 0, "O")
        base = dict(c["text"], stroke_on=True, fill=False, stroke=5.0)
        bounds = {}
        for align in ("inside", "center", "outside"):
            alpha = textlayout.render(dict(base, stroke_align=align), 1.0).getchannel("A")
            bounds[align] = alpha.getbbox()
        widths = {align: box[2] - box[0] for align, box in bounds.items()}
        self.assertLess(widths["inside"], widths["center"])
        self.assertLess(widths["center"], widths["outside"])
        edit.set_param(p, c["id"], "text", "stroke_align", "outside")
        edit.toggle_key(p, c["id"], "text", "stroke_align", 0)
        edit.set_param(p, c["id"], "text", "stroke_align", "center", S // 2)
        from kiasecut import curves
        self.assertEqual(curves.value(c["text"]["stroke_align"], S // 4), "outside")
        self.assertEqual(curves.value(c["text"]["stroke_align"], 3 * S // 4), "center")
        with self.assertRaises(edit.EditError):
            edit.set_param(p, c["id"], "text", "stroke_align", "invalid")

    def test_inspector_exposes_fill_and_outline_controls(self):
        from kiasecut.ui.inspector import Inspector
        ins = Inspector()
        c = edit.add_text(proj(), 0, "文字")
        ins.show_clips([c], 0, 30)
        got = []
        ins.paramEdited.connect(lambda ids, group, key, value: got.append((group, key, value)))
        ins.widgets["fill"].click()
        ins.widgets["stroke_on"].click()
        self.assertIn(("text", "fill", False), got)
        self.assertIn(("text", "stroke_on", True), got)
        self.assertIn("stroke_color", ins.widgets)
        self.assertIn(("text", "stroke"), ins.widgets)
        self.assertIn("stroke_align", ins.widgets)


LONG = "The quick brown fox jumps over 敏捷的棕色狐狸跳過懶狗"


def lines_of(spec):
    return ["".join(g[1] for g in glyphs) for glyphs, _w in textlayout._layout(spec, 1.0, 1080)["lines"]]


class TextBoxTests(unittest.TestCase):
    def test_wraps_in_its_width(self):
        spec = {"content": LONG, "size": 5.0, "box_w": 300}
        lines = lines_of(spec)
        self.assertGreater(len(lines), 2)
        for ln in lines:
            self.assertNotIn(ln.strip(), ("Th", "qui", "bro"))           # Latin words go down whole
        self.assertEqual(" ".join(lines).replace("  ", " ").count("quick"), 1)
        lay = textlayout._layout(spec, 1.0, 1080)
        self.assertTrue(all(w <= 300.5 or len(g) == 1 for g, w in lay["lines"]))
        self.assertEqual(lines_of({"content": LONG, "size": 5.0}), [LONG])  # no box: one line
        self.assertEqual(textlayout.frame_size(spec)[0], 300)
        # the same layout at another scale / canvas: px of a 1080-high canvas at scale 1
        self.assertEqual(["".join(g[1] for g in gs) for gs, _ in textlayout._layout(spec, 2.0, 720)["lines"]], lines)

    def test_vertical_alignment(self):
        spec = {"content": "AB", "size": 5.0, "box_w": 400, "box_h": 600}
        tops = {}
        for v in ("top", "middle", "bottom"):
            im = textlayout.render(dict(spec, valign=v), 1.0)
            self.assertGreaterEqual(im.height, 600)
            box = im.getchannel("A").getbbox()
            tops[v] = (box[1] - im.height / 2, box[3] - im.height / 2)   # from the frame's centre
        self.assertLess(tops["top"][0], -250)                            # near the frame's top
        self.assertLess(abs(tops["middle"][0] + tops["middle"][1]), 12)  # about its centre
        self.assertGreater(tops["bottom"][1], 250)
        same = {k: textlayout.render(dict(spec, box_h=0, valign=k), 1.0).tobytes() for k in ("top", "bottom")}
        self.assertEqual(same["top"], same["bottom"])                    # auto height: nothing to align in

    def test_modes_keep_the_text_in_place(self):
        p = proj()
        c = edit.add_text(p, 0, "hello\nworld", S)
        self.assertEqual(edit.text_box_mode(c["text"]), "auto")
        before = textlayout.frame_size(c["text"])
        edit.set_param(p, c["id"], "text", "box_mode", "fixed", 0)
        self.assertEqual(edit.text_box_mode(c["text"]), "fixed")
        w, h = textlayout.frame_size(c["text"])
        self.assertAlmostEqual(w, before[0], delta=0.2)
        self.assertAlmostEqual(h, before[1], delta=0.2)
        self.assertEqual(lines_of(c["text"]), ["hello", "world"])        # nothing wrapped
        edit.set_param(p, c["id"], "text", "box_mode", "auto_h", 0)
        self.assertNotIn("box_h", c["text"])
        self.assertIn("box_w", c["text"])
        edit.set_param(p, c["id"], "text", "box_mode", "auto", 0)
        self.assertNotIn("box_w", c["text"])
        edit.set_param(p, c["id"], "text", "valign", "bottom")
        with self.assertRaises(edit.EditError):
            edit.set_param(p, c["id"], "text", "valign", "center")
        with self.assertRaises(edit.EditError):
            edit.set_param(p, c["id"], "text", "box_mode", "huge")
        edit.set_param(p, c["id"], "text", "box_w", -5)
        self.assertEqual(c["text"]["box_w"], 0.0)

    def test_preview_resizes_the_frame(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtWidgets import QApplication
        from kiasecut.ui.preview import Box, Preview
        QApplication.instance() or QApplication([])
        p = proj()
        c = edit.add_text(p, 0, LONG, S)
        before = Box(c, 1920, 1080, 0)
        pv = Preview()
        handle = next(pt for sx, sy, pt in before.handles() if (sx, sy) == (1, 0))
        group, out = pv._scale_values(before, {"side": (1, 0), "m0": handle}, QPointF(handle.x() + 50, handle.y()),
                                      Qt.KeyboardModifier.NoModifier)
        self.assertEqual(group, "transform")                             # as big as its words: it scales
        edit.set_param(p, c["id"], "text", "box_mode", "auto_h", 0)
        box = Box(c, 1920, 1080, 0)
        w0 = c["text"]["box_w"]
        self.assertAlmostEqual(box.bw, w0, delta=0.5)
        handle = next(pt for sx, sy, pt in box.handles() if (sx, sy) == (1, 0))
        group, out = pv._scale_values(box, {"side": (1, 0), "m0": handle}, QPointF(handle.x() - 400, handle.y()),
                                      Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(group, "multi")
        self.assertEqual(set(out["text"]), {"box_w"})                    # an edge: its own side
        self.assertAlmostEqual(out["text"]["box_w"], w0 - 400, delta=0.5)
        self.assertLess(out["transform"]["x"], 0)                        # the left edge stays
        handle = next(pt for sx, sy, pt in box.handles() if (sx, sy) == (1, 1))
        group, out = pv._scale_values(box, {"side": (1, 1), "m0": handle}, QPointF(handle.x() - 400, handle.y() + 30),
                                      Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(set(out["text"]), {"box_w", "box_h"})           # a corner: fixed size


if __name__ == "__main__":
    unittest.main()
