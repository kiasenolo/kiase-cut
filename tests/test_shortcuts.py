"""Common shortcuts: Q / W trim to the playhead, Shift+Delete ripple delete, ↑ / ↓ to the edit
points (but not out of a focused number field), the timeline zoom keys."""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QSpinBox  # noqa: E402

from kiasecut import edit  # noqa: E402
from kiasecut.ui.main_window import MainWindow  # noqa: E402
from kiasecut.ui.timeline import Timeline  # noqa: E402
from test_edit import S, clip, proj  # noqa: E402
from test_groups import scene  # noqa: E402

APP = QApplication.instance() or QApplication([])


def span(p, cid):
    c = edit.find(p, cid)[1]
    return c["start_us"], c["start_us"] + c["duration_us"]


class TrimToTests(unittest.TestCase):
    def test_left_and_right(self):
        p = proj()                                       # c1 0-2 s, c2 5-7 s, c3 (sound) 2-6 s
        edit.trim_to(p, ["c1", "c2", "c3"], 1 * S, "start")
        self.assertEqual(span(p, "c1"), (1 * S, 2 * S))
        self.assertEqual(span(p, "c2"), (5 * S, 7 * S))     # the playhead is not inside it
        edit.trim_to(p, ["c2", "c3"], 6 * S, "end")
        self.assertEqual(span(p, "c2"), (5 * S, 6 * S))
        self.assertEqual(span(p, "c3"), (2 * S, 6 * S))     # (ends right there: nothing to cut)

    def test_content_stays_in_place(self):
        p = proj()
        edit.trim_to(p, ["c3"], 3 * S, "start")
        c3 = edit.find(p, "c3")[1]
        self.assertEqual((c3["start_us"], c3["source_start_us"]), (3 * S, 2 * S))

    def test_nothing_under_the_playhead(self):
        p = proj()
        with self.assertRaises(edit.EditError):
            edit.trim_to(p, ["c1", "c2"], 3 * S, "end")
        self.assertEqual(span(p, "c1"), (0, 2 * S))

    def test_group_clip_in_level_time(self):
        p = scene()
        g = edit.make_group(p, p, ["c1", "c4"])
        edit.move(p, g["id"], 1 * S)                     # c1 at 1-3 s on the timeline
        edit.trim_to(p, ["c1"], 2 * S, "end")
        self.assertEqual(edit.abs_start(p, "c1"), 1 * S)
        self.assertEqual(edit.find(p, "c1")[1]["duration_us"], 1 * S)


class RippleDeleteTests(unittest.TestCase):
    def test_later_clips_close_up(self):
        p = proj()
        p["tracks"][0]["clips"].append(clip("c5", 8 * S, S))
        p["tracks"][1]["clips"].append(clip("c6", 6 * S, S))
        edit.ripple_delete(p, ["c1", "c2"])
        self.assertEqual(span(p, "c5"), (4 * S, 5 * S))     # 8 s - c1's 2 s - c2's 2 s
        self.assertEqual(span(p, "c6"), (6 * S, 7 * S))     # another track: stays
        self.assertEqual(span(p, "c3"), (2 * S, 6 * S))

    def test_only_what_was_after(self):
        p = proj()
        edit.ripple_delete(p, ["c2"])
        self.assertEqual(span(p, "c1"), (0, 2 * S))
        with self.assertRaises(edit.EditError):
            edit.find(p, "c2")


class EditPointTests(unittest.TestCase):
    def win(self, pos):
        p = proj()
        tl = Timeline()
        tl.set_project(p)
        seen = []
        w = SimpleNamespace(proj=p, timeline=tl, fps=30.0, pos=pos, length=7 * 30,
                            placed=lambda c: c, seek=seen.append,
                            statusBar=lambda: SimpleNamespace(showMessage=lambda *a: seen.append(a[0])))
        return w, seen

    def test_next_and_previous(self):
        w, seen = self.win(70)                           # 2.33 s
        MainWindow.jump_edit(w, 1)
        MainWindow.jump_edit(w, -1)
        self.assertEqual(seen, [150, 60])                # c2's start (5 s), c1's end / c3's start (2 s)

    def test_last_point_is_the_last_frame(self):
        w, seen = self.win(200)
        MainWindow.jump_edit(w, 1)
        self.assertEqual(seen, [209])
        w.pos = 209
        MainWindow.jump_edit(w, 1)
        self.assertEqual(seen[-1], "沒有更多剪輯點")


class ArrowFocusTests(unittest.TestCase):
    def override(self, widget, key=Qt.Key_Up, mods=Qt.NoModifier):
        widget.show()
        widget.setFocus()
        QTest.qWaitForWindowExposed(widget)
        e = QKeyEvent(QEvent.ShortcutOverride, key, mods)
        e.ignore()
        MainWindow.eventFilter(None, widget, e)
        widget.close()
        return e.isAccepted()

    def test_number_field_keeps_up_down(self):
        self.assertTrue(self.override(QSpinBox()))
        self.assertFalse(self.override(QSpinBox(), mods=Qt.AltModifier))
        self.assertFalse(self.override(QLineEdit()))          # no use for them: 剪輯點


class ZoomTests(unittest.TestCase):
    def test_zoom_keeps_the_playhead_and_fit(self):
        tl = Timeline()
        tl.resize(1000, 300)
        tl.set_project(proj())
        tl.scroll_s, tl.px_per_s = 0.0, 100.0
        x = tl._x(3.0)
        tl.zoom_by(2.0, 3.0)
        self.assertEqual(tl.px_per_s, 200.0)
        self.assertAlmostEqual(tl._x(3.0), x)
        tl.zoom_fit()
        self.assertEqual(tl.scroll_s, 0)
        self.assertAlmostEqual(tl._x(tl.proj["duration_us"] / S), tl.width() - 20)


if __name__ == "__main__":
    unittest.main()
