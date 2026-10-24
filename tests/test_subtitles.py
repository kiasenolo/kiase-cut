"""字幕: the words of several text clips of one track as one line each, edited together."""
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
from kiasecut.ui.subtitle_panel import SubtitlePanel  # noqa: E402
from kiasecut.ui.timeline import Timeline, US  # noqa: E402
from test_edit import S, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


def texts():
    p = proj()
    a = edit.add_text(p, 4 * S, "two")
    b = edit.add_text(p, 0, "one")              # same text track, earlier
    c = edit.add_text(p, 8 * S, "three\nlines")
    return p, [b, a, c]


def track_of(p, cid):
    return edit.find(p, cid)[0]


class LineTests(unittest.TestCase):
    def test_round_trip_keeps_line_breaks(self):
        words = ["one", "two\nlines", ""]
        text = "\n".join(edit.subtitle_line(w) for w in words)
        self.assertEqual(text, "one\ntwo\\nlines\n")
        self.assertEqual(edit.subtitle_lines(text + "\n\n"), ["one", "two\nlines"])

    def test_set_texts(self):
        p, (b, a, c) = texts()
        edit.set_texts(p, {a["id"]: "TWO", c["id"]: "THREE"})
        self.assertEqual([k["text"]["content"] for k in (b, a, c)], ["one", "TWO", "THREE"])
        self.assertEqual(a["name"], "TWO")


class PanelTests(unittest.TestCase):
    def test_lines_in_time_order_and_apply(self):
        p, clips = texts()
        rows = p["tracks"]
        panel = SubtitlePanel()
        got = []
        panel.textsEdited.connect(got.append)
        panel.show_selection(rows, {k["id"] for k in clips})
        self.assertFalse(panel.body.isHidden())
        self.assertEqual(panel.editor.toPlainText(), "one\ntwo\nthree\\nlines")
        panel.editor.setPlainText("一\ntwo\n三\\n行\n")
        self.assertTrue(panel.apply_btn.isEnabled())
        panel.apply()
        self.assertEqual(got, [{clips[0]["id"]: "一", clips[2]["id"]: "三\n行"}])

    def test_line_count_must_match(self):
        p, clips = texts()
        panel = SubtitlePanel()
        panel.show_selection(p["tracks"], {k["id"] for k in clips})
        panel.editor.setPlainText("a\nb")
        self.assertFalse(panel.apply_btn.isEnabled())
        self.assertIn("3", panel.count.text())

    def test_unapplied_changes_survive_refresh_until_selection_changes(self):
        p, clips = texts()
        ids = {k["id"] for k in clips}
        panel = SubtitlePanel()
        panel.show_selection(p["tracks"], ids)
        panel.editor.setPlainText("x\ny\nz")
        panel.show_selection(p["tracks"], ids)              # a frame later
        self.assertEqual(panel.editor.toPlainText(), "x\ny\nz")
        panel.show_selection(p["tracks"], ids - {clips[0]["id"]})
        self.assertEqual(panel.editor.toPlainText(), "two\nthree\\nlines")
        clips[1]["text"]["content"] = "undone"              # an undo, with nothing typed
        panel.show_selection(p["tracks"], ids - {clips[0]["id"]})
        self.assertEqual(panel.editor.toPlainText(), "undone\nthree\\nlines")

    def test_only_text_clips_of_one_track(self):
        p, clips = texts()
        panel = SubtitlePanel()
        panel.show_selection(p["tracks"], {clips[0]["id"], "c1"})   # c1: a picture on another track
        self.assertTrue(panel.body.isHidden())
        panel.show_selection(p["tracks"], set())
        self.assertTrue(panel.body.isHidden())


CTRL = Qt.ControlModifier


class CtrlDragTests(unittest.TestCase):
    """Ctrl + press on a clip and drag on: the clips the box reaches follow the first one."""
    def setUp(self):
        self.p, self.clips = texts()
        self.tl = Timeline()
        self.tl.resize(1400, 300)
        self.tl.set_project(self.p)
        self.tl.px_per_s, self.tl.scroll_s = 100.0, 0.0
        self.tl._layout()
        self.row = next(i for i, t in enumerate(self.tl.rows) if t["kind"] == "text")

    def at(self, c):
        return QPoint(round(self.tl._x((c["start_us"] + c["duration_us"] / 2) / US)),
                      round(self.tl.tops[self.row] + self.tl.row_h(self.row) / 2))

    def sweep(self, first, last):
        tl = self.tl
        QTest.mousePress(tl, Qt.LeftButton, CTRL, self.at(first))
        QTest.mouseMove(tl, (self.at(first) + self.at(last)) / 2)
        QTest.mouseMove(tl, self.at(last))
        QTest.mouseRelease(tl, Qt.LeftButton, CTRL, self.at(last))

    def test_first_unselected_selects_the_rest(self):
        a, b, c = self.clips
        self.tl.set_selection({b["id"]}, b["id"])
        self.sweep(a, c)
        self.assertEqual(self.tl.selected_ids, {a["id"], b["id"], c["id"]})

    def test_first_selected_deselects_the_rest(self):
        a, b, c = self.clips
        self.tl.set_selection({a["id"], c["id"]}, a["id"])
        self.sweep(a, c)
        self.assertEqual(self.tl.selected_ids, set())       # b was not selected: it stays out

    def test_ctrl_click_still_toggles(self):
        a, b, _ = self.clips
        self.tl.set_selection({a["id"]}, a["id"])
        QTest.mouseClick(self.tl, Qt.LeftButton, CTRL, self.at(b))
        self.assertEqual(self.tl.selected_ids, {a["id"], b["id"]})
        QTest.mouseClick(self.tl, Qt.LeftButton, CTRL, self.at(a))
        self.assertEqual(self.tl.selected_ids, {b["id"]})


if __name__ == "__main__":
    unittest.main()
