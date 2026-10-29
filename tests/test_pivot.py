"""中心點 (transform pivot_x / pivot_y): a clip turns and scales about its pivot - in both
renderers' placement (project.centre_px, render.clip_world), in groups folded in and out, and
on the preview (the ring dragged stays put and the clip moves the other way; a turn keeps the pivot put)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, project, render  # noqa: E402
from kiasecut.ui.preview import Preview  # noqa: E402
from test_edit import S, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
NONE = Qt.KeyboardModifier.NoModifier
W, H = 1920, 1080


def near(a, b, tol=1e-6):
    return abs(a.x() - b.x()) < tol and abs(a.y() - b.y()) < tol


class PlacementTests(unittest.TestCase):
    def test_no_pivot_no_shift(self):
        self.assertEqual(project.pivot_shift({"rotation": 30.0, "scale": 2.0}, 0, W, H), (0.0, 0.0))

    def test_pivot_stays_put_whatever_the_turn_and_scale(self):
        base = {"x": 0.2, "y": -0.1, "pivot_x": 0.5, "pivot_y": 0.25}
        piv = QPointF(0.5 * W / 2, -0.25 * H / 2)                     # in the clip's own frame
        rest = render.clip_world({"transform": base}, 0, W, H).map(piv)
        for extra in ({"rotation": 90.0}, {"rotation": -37.0, "scale": 2.5}, {"scale": 0.5, "scale_y": 3.0},
                      {"rotation": 180.0, "flip_h": True}):
            c = {"transform": dict(base, **extra)}
            self.assertTrue(near(render.clip_world(c, 0, W, H).map(piv), rest, 1e-6), extra)

    def test_unturned_unscaled_is_where_it_was(self):
        c = {"transform": {"x": 0.3, "y": 0.4, "pivot_x": 0.7, "pivot_y": -0.2}}
        self.assertEqual(project.centre_px(c["transform"], 0, W, H), (W / 2 + 0.3 * W / 2, H / 2 - 0.4 * H / 2))

    def test_half_turn_about_the_right_edge(self):
        dx, dy = project.pivot_shift({"pivot_x": 1.0, "rotation": 180.0}, 0, 200, 100)
        self.assertAlmostEqual(dx, 200.0)
        self.assertAlmostEqual(dy, 0.0)


class GroupTests(unittest.TestCase):
    def world(self, p, cid, group=None):
        """Clip cid's frame -> the level's canvas (through its group when it is in one)."""
        _, c = edit.find(p, cid)
        xf = render.clip_world(c, 0, W, H)
        if group is not None:
            xf = xf * QTransform.fromTranslate(-W / 2, -H / 2) * render.clip_world(group, 0, W, H)
        return xf

    def test_ungroup_keeps_them_in_place(self):
        p = proj()
        edit.find(p, "c1")[1]["transform"].update(x=0.1, rotation=30.0, pivot_x=0.4, pivot_y=0.3)
        g = edit.make_group(p, p, ["c1"])
        g["transform"].update(scale=2.0, x=-0.2, pivot_x=-0.5, pivot_y=0.2)
        pts = [QPointF(0, 0), QPointF(300, -100), QPointF(-50, 220)]
        before = [self.world(p, "c1", g).map(q) for q in pts]
        edit.ungroup(p, p, g["id"])
        after = [self.world(p, "c1").map(q) for q in pts]
        for a, b in zip(before, after):
            self.assertTrue(near(a, b, 1e-3), (a, b))

    def test_move_into_group_keeps_them_in_place(self):
        p = proj()
        g = edit.make_group(p, p, ["c2"])
        g["transform"].update(scale=0.5, y=0.3, pivot_x=0.6, pivot_y=-0.4)
        edit.find(p, "c1")[1]["transform"].update(x=0.25, rotation=-20.0, scale=1.5, pivot_x=-0.3, pivot_y=0.1)
        pts = [QPointF(0, 0), QPointF(200, 80)]
        before = [self.world(p, "c1").map(q) for q in pts]
        edit.move_into_group(p, p, ["c1"], g["id"])
        after = [self.world(p, "c1", g).map(q) for q in pts]
        for a, b in zip(before, after):
            self.assertTrue(near(a, b, 1e-3), (a, b))


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.c = edit.find(self.p, "c1")[1]

    def drag(self, a, b, mods=NONE):
        pv = Preview()
        pv.resize(960, 540)                              # the 1920 x 1080 canvas at half size
        pv.set_scene(self.p, S // 2, "c1")
        got = []
        pv.paramsCommitted.connect(lambda *args: got.append(args))
        QTest.mousePress(pv, Qt.LeftButton, mods, a)
        QTest.mouseMove(pv, (a + b) / 2)
        QTest.mouseMove(pv, b)
        QTest.mouseRelease(pv, Qt.LeftButton, mods, b)
        return got

    def test_dragging_the_ring_keeps_the_ring_put_and_moves_the_clip(self):
        self.c["transform"]["rotation"] = 40.0
        before = render.clip_world(self.c, 0, W, H)
        ring = before.map(QPointF(0, 0))                                      # (the pivot is at the centre)
        got = self.drag(QPoint(480, 270), QPoint(540, 250),
                        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(len(got), 1)
        cid, group, vals = got[0]
        self.assertEqual((cid, group), ("c1", "transform"))
        self.assertTrue(vals["pivot_x"] or vals["pivot_y"])
        for k, v in vals.items():
            edit.set_param(self.p, cid, group, k, v, 0)
        after = render.clip_world(self.c, 0, W, H)
        piv = QPointF(vals["pivot_x"] * W / 2, -vals["pivot_y"] * H / 2)
        self.assertTrue(near(after.map(piv), ring, 0.05))                     # the ring did not move
        self.assertFalse(near(before.map(QPointF(0, 0)), after.map(QPointF(0, 0)), 5.0))   # the clip did

    def test_ring_snaps_to_a_corner(self):
        got = self.drag(QPoint(480, 270), QPoint(958, 538), Qt.KeyboardModifier.ControlModifier)   # (at the centre: Ctrl)
        vals = got[0][2]
        self.assertEqual((vals["pivot_x"], vals["pivot_y"]), (1.0, -1.0))
        self.assertAlmostEqual(vals["x"], -1.0, 5)       # (the ring stays: the clip moves the other way)

    def test_plain_drag_at_the_centre_moves_the_clip(self):
        got = self.drag(QPoint(480, 270), QPoint(530, 270))
        self.assertNotIn("pivot_x", got[0][2])
        self.assertGreater(got[0][2]["x"], 0.05)

    def test_moved_ring_is_dragged_without_ctrl(self):
        self.c["transform"].update(pivot_x=0.5, pivot_y=0.0)                  # at (720, 270) on screen
        got = self.drag(QPoint(720, 270), QPoint(720, 400), Qt.KeyboardModifier.ShiftModifier)
        self.assertIn("pivot_x", got[0][2])


class FieldTests(unittest.TestCase):
    def test_set_and_keyframe(self):
        p = proj()
        edit.set_transform(p, "c1", "pivot_x", 0.5)
        self.assertEqual(edit.find(p, "c1")[1]["transform"]["pivot_x"], 0.5)


if __name__ == "__main__":
    unittest.main()
