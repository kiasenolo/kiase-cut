"""Alt+drag: copies of clips, the originals staying put - on the timeline (later / other rows)
and on the canvas (on top of the original, at the dragged position)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit  # noqa: E402
from kiasecut.ui.preview import Box, Preview  # noqa: E402
from test_edit import S, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


class DuplicateTests(unittest.TestCase):
    def test_timeline_copy_later(self):
        p = proj()
        new = edit.duplicate_moved(p, p, ["c1"], 2 * S + S // 2, 0)       # c1 0-2 s: copy at 2.5 s
        self.assertEqual(len(new), 1)
        self.assertEqual(edit.find(p, "c1")[1]["start_us"], 0)           # the original stays
        t, c = edit.find(p, new[0]["id"])
        self.assertEqual((t["id"], c["start_us"]), ("t0", 2 * S + S // 2))

    def test_timeline_copy_to_another_row(self):
        p = proj()
        new = edit.duplicate_moved(p, p, ["c1"], 0, 1)                    # one row down: t0 -> ... the row below
        pictures, _ = edit.display_groups(p)
        row_of = lambda cid: next(i for i, t in enumerate(pictures) if any(c["id"] == cid for c in t["clips"]))
        self.assertNotEqual(row_of(new[0]["id"]), row_of("c1"))

    def test_canvas_copy_on_top(self):
        p = proj()
        new = edit.duplicate_moved(p, p, ["c1"], moves={"c1": {"x": 0.5, "y": -0.25}}, t_of=lambda cid: 0)
        tracks = p["tracks"]
        idx = lambda cid: next(i for i, t in enumerate(tracks) if any(c["id"] == cid for c in t["clips"]))
        self.assertGreater(idx(new[0]["id"]), idx("c1"))                 # a higher layer: drawn over it
        c = edit.find(p, new[0]["id"])[1]
        self.assertEqual((c["transform"]["x"], c["transform"]["y"]), (0.5, -0.25))
        self.assertEqual(edit.find(p, "c1")[1]["transform"]["x"], 0.0)
        self.assertEqual(c["start_us"], 0)

    def test_preview_alt_drag_reports_copies(self):
        p = proj()
        pv = Preview()
        pv.resize(960, 540)
        pv.set_scene(p, 0, "c1", {"c1"})
        got = {}
        pv.dupCommitted.connect(lambda m: got.update(m))
        moved = []
        pv.movesCommitted.connect(moved.append)
        pv.paramsCommitted.connect(lambda *a: moved.append(a))
        box = Box(edit.find(p, "c1")[1], 1920, 1080, 0)
        pv.drag = {"kind": "move", "box": box, "boxes": [box], "x0": 960, "y0": 540, "moved": False, "others": []}

        class Ev:                                                         # (a mouse event's modifiers)
            def __init__(self, mods):
                self._m = mods

            def modifiers(self):
                return self._m
        group, vals = pv._values(Ev(Qt.KeyboardModifier.AltModifier), QPointF(1200, 540))
        self.assertEqual(group, "moves")
        self.assertTrue(pv.drag["dup"])
        pv.drag["moved"] = True
        pv.live = (group, vals)
        pv.mouseReleaseEvent(None)
        self.assertIn("c1", got)
        self.assertEqual(moved, [])

    def test_ctrl_moves_freely(self):
        p = proj()
        pv = Preview()
        pv.set_scene(p, 0, "c1", {"c1"})
        box = Box(edit.find(p, "c1")[1], 1920, 1080, 0)
        others = [Box(edit.find(p, "c2")[1], 1920, 1080, 0)]
        pv.drag = {"kind": "move", "box": box, "boxes": [box], "x0": 960, "y0": 540, "moved": True, "others": []}

        class Ev:
            def __init__(self, mods):
                self._m = mods

            def modifiers(self):
                return self._m
        _, free = pv._values(Ev(Qt.KeyboardModifier.ControlModifier), QPointF(963, 540))     # 3 px off centre
        self.assertNotEqual(free["x"], 0.0)
        _, snapped = pv._values(Ev(Qt.KeyboardModifier.NoModifier), QPointF(963, 540))
        self.assertEqual(snapped["x"], 0.0)
        del others


if __name__ == "__main__":
    unittest.main()
