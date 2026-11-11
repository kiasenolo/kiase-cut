"""The pen tool: path assets (nodes stored across their box), drawing a path, editing its nodes."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402

from kiasecut import assets, edit  # noqa: E402
from kiasecut.ui import pentool  # noqa: E402
from kiasecut.ui.preview import Box  # noqa: E402
from test_align_space import APP, scene  # noqa: E402,F401


def mouse(pv, kind, canvas_pt, button=Qt.LeftButton, mods=Qt.NoModifier):
    r = pv._rect()
    pt = QPointF(r.x() + canvas_pt[0] / pv.W * r.width(), r.y() + canvas_pt[1] / pv.H * r.height())
    t = {"press": QEvent.MouseButtonPress, "move": QEvent.MouseMove, "release": QEvent.MouseButtonRelease}[kind]
    e = QMouseEvent(t, pt, pt, button, button if kind != "move" else Qt.NoButton, mods)
    {"press": pv.mousePressEvent, "move": pv.mouseMoveEvent, "release": pv.mouseReleaseEvent}[kind](e)


class PathAsset(unittest.TestCase):
    NODES = [[100, 100, 0, 0, 50, 0], [300, 200, -50, 0, 0, 0], [200, 300, 0, 0, 0, 0]]

    def test_params_and_outline(self):
        p, (cx, cy) = assets.path_params([{"nodes": [list(n) for n in self.NODES], "closed": False}])
        self.assertEqual(p["family"], "path")
        self.assertFalse(p["fill"])
        self.assertTrue(p["stroke_on"])
        self.assertAlmostEqual(p["w"], 200, delta=0.01)
        self.assertAlmostEqual(cx, 200, delta=0.01)
        q = assets.at(p, 0)
        d = assets.outline_d(q, q["w"], q["h"])
        self.assertTrue(d.startswith("M0 0 C") and " L" in d and not d.endswith("Z"))
        self.assertIn("<path", assets.svg(q))

    def test_closed_is_filled(self):
        p, _ = assets.path_params([{"nodes": [list(n) for n in self.NODES], "closed": True}])
        self.assertTrue(p["fill"] and p["paths"][0]["closed"] and not p["stroke_on"])
        self.assertTrue(assets.outline_d(assets.at(p, 0), p["w"], p["h"]).endswith("Z"))

    def test_several_parts_and_the_old_nodes_field(self):
        sq = lambda x: {"nodes": [[x, 0, 0, 0, 0, 0], [x + 50, 0, 0, 0, 0, 0], [x + 50, 50, 0, 0, 0, 0]], "closed": True}
        p, _ = assets.path_params([sq(0), sq(200)])
        self.assertEqual(assets.outline_d(assets.at(p, 0), p["w"], p["h"]).count("M"), 2)
        old = {"key": "path.pen", "family": "path", "nodes": [[0, 0, 0, 0, 0, 0], [1, 1, 0, 0, 0, 0]], "closed": False, "w": 10, "h": 10}
        self.assertEqual(len(assets.normalize(old)["paths"]), 1)

    def test_split_keeps_the_curve_and_smooth_toggles(self):
        nodes = [list(n) for n in self.NODES]
        a = assets.bezier_points(nodes[0], nodes[1], 8)[4]
        new, at = pentool.split(nodes, False, 0, 0.5)
        self.assertEqual(at, 1)
        self.assertAlmostEqual(new[1][0], a[0], delta=0.01)
        self.assertAlmostEqual(new[1][1], a[1], delta=0.01)
        self.assertTrue(pentool.is_smooth(new[1]))
        pentool.toggle_smooth(new, False, 1)
        self.assertEqual(new[1][2:], [0, 0, 0, 0])
        pentool.toggle_smooth(new, False, 1)
        self.assertTrue(pentool.is_smooth(new[1]))


class Draw(unittest.TestCase):
    def setUp(self):
        self.p, self.pv = scene((100, 100))
        self.pv.resize(1000, 600)
        self.done, self.toggles = [], []
        self.pv.penFinished.connect(lambda paths: self.done.append(paths))
        self.pv.penToggled.connect(self.toggles.append)

    def test_click_drag_and_finish(self):
        pv = self.pv
        self.assertTrue(pv.pen_begin())
        mouse(pv, "press", (300, 300))
        mouse(pv, "release", (300, 300))
        mouse(pv, "press", (900, 400))
        mouse(pv, "move", (1100, 400))
        mouse(pv, "release", (1100, 400))                # a smooth point: handles out of the click
        pv.pen_key(type("K", (), {"key": lambda s: Qt.Key_Return, "modifiers": lambda s: Qt.NoModifier})())()
        self.assertEqual(self.toggles, [True, False])
        self.assertEqual(len(self.done[0]), 1)
        nodes, closed = self.done[0][0]["nodes"], self.done[0][0]["closed"]
        self.assertFalse(closed)
        self.assertEqual(len(nodes), 2)
        self.assertEqual(nodes[0][2:], [0.0, 0.0, 0.0, 0.0])
        self.assertAlmostEqual(nodes[1][4], 200, delta=2)
        self.assertAlmostEqual(nodes[1][2], -200, delta=2)

    def test_close_on_the_first_point(self):
        pv = self.pv
        pv.pen_begin()
        for pt in ((300, 300), (900, 300), (600, 800)):
            mouse(pv, "press", pt)
            mouse(pv, "release", pt)
        mouse(pv, "press", (300, 300))
        self.assertTrue(self.done[0][0]["closed"])
        self.assertEqual(len(self.done[0][0]["nodes"]), 3)

    def test_escape_drops_the_path(self):
        pv = self.pv
        pv.pen_begin()
        mouse(pv, "press", (300, 300))
        mouse(pv, "release", (300, 300))
        pv.pen_key(type("K", (), {"key": lambda s: Qt.Key_Escape, "modifiers": lambda s: Qt.NoModifier})())()
        self.assertIsNone(pv.pen)
        self.assertEqual(self.done, [])


class EditPath(unittest.TestCase):
    def test_drag_a_node_keeps_the_others_where_they_are(self):
        params, (cx, cy) = assets.path_params([{"nodes": [[600, 300, 0, 0, 100, 0], [1000, 500, -100, 0, 0, 0], [800, 800, 0, 0, 0, 0]], "closed": False}])
        p, pv = scene((960, 540))
        c = edit.find(p, "k0")[1]
        c["asset"] = params
        c["transform"].update(scale=1.0, x=(cx - 960) / 960, y=(540 - cy) / 540)
        pv.resize(1000, 600)
        pv.set_scene(p, 0, "k0", {"k0"})
        before = [(n[0], n[1]) for n in pv_nodes(pv, p)]
        self.assertAlmostEqual(before[0][0], 600, delta=0.1)
        got = []
        pv.paramsCommitted.connect(lambda cid, g, v: got.append((cid, g, v)))
        self.assertTrue(pv.pen_can_edit())
        self.assertTrue(pv.pen_edit())
        mouse(pv, "press", (800, 800))
        mouse(pv, "move", (850, 850))
        mouse(pv, "release", (850, 850))
        self.assertEqual(got[0][1], "multi")
        for g, vals in got[0][2].items():
            for k, v in vals.items():
                edit.set_param(p, "k0", g, k, v)
        after = pv_nodes(pv, p)
        self.assertAlmostEqual(after[0][0], 600, delta=0.2)
        self.assertAlmostEqual(after[0][1], 300, delta=0.2)
        self.assertAlmostEqual(after[1][0], 1000, delta=0.2)
        self.assertAlmostEqual(after[2][0], 850, delta=0.5)
        self.assertAlmostEqual(after[2][1], 850, delta=0.5)


class MultiSelect(unittest.TestCase):
    def setUp(self):
        params, (cx, cy) = assets.path_params([{"nodes": [[400, 300, 0, 0, 0, 0], [800, 300, 0, 0, 0, 0], [800, 600, 0, 0, 0, 0],
                                                          [400, 600, 0, 0, 0, 0]], "closed": False}])
        self.p, self.pv = scene((960, 540))
        c = edit.find(self.p, "k0")[1]
        c["asset"] = params
        c["transform"].update(scale=1.0, x=(cx - 960) / 960, y=(540 - cy) / 540)
        self.pv.resize(1000, 600)
        self.pv.set_scene(self.p, 0, "k0", {"k0"})
        self.got = []
        self.pv.paramsCommitted.connect(lambda cid, g, v: self.got.append((g, v)))
        self.pv.pen_edit()

    def apply(self):
        for g, vals in self.got[-1][1].items():
            for k, v in vals.items():
                edit.set_param(self.p, "k0", g, k, v)
        self.pv.set_scene(self.p, 0, "k0", {"k0"})

    def test_marquee_selects_and_arrows_move_them_together(self):
        pv = self.pv
        mouse(pv, "press", (300, 200))
        mouse(pv, "move", (900, 450))
        mouse(pv, "release", (900, 450))
        self.assertEqual(pv.pen["sel"], {(0, 0), (0, 1)})
        pv.pen_key(type("K", (), {"key": lambda s: Qt.Key_Right, "modifiers": lambda s: Qt.ShiftModifier})())()
        self.apply()
        pts = [(n[0], n[1]) for n in pv_nodes(pv, self.p)]
        self.assertAlmostEqual(pts[0][0], 410, delta=0.3)
        self.assertAlmostEqual(pts[1][0], 810, delta=0.3)
        self.assertAlmostEqual(pts[2][0], 800, delta=0.3)

    def test_delete_selected_and_click_empty_clears(self):
        pv = self.pv
        pv.pen["sel"] = {(0, 0)}
        pv._pen_delete_selected()
        self.apply()
        self.assertEqual(len(pv_nodes(pv, self.p)), 3)
        pv.pen["sel"] = {(0, 0)}
        mouse(pv, "press", (50, 50))
        mouse(pv, "release", (50, 50))
        self.assertEqual(pv.pen["sel"], set())
        self.assertIsNotNone(pv.pen)
        mouse(pv, "press", (50, 50))
        mouse(pv, "release", (50, 50))
        self.assertIsNone(pv.pen)

    def test_continue_from_an_end_and_shift_click_starts_a_part(self):
        pv = self.pv
        mouse(pv, "press", (400, 600), mods=Qt.ControlModifier)
        mouse(pv, "release", (400, 600))
        self.assertEqual(pv.pen["cur"], 0)
        mouse(pv, "press", (300, 700))
        mouse(pv, "release", (300, 700))
        pv._pen_finish()
        self.apply()
        self.assertEqual(len(pv_nodes(pv, self.p)), 5)
        pv.pen_edit()
        mouse(pv, "press", (1500, 200), mods=Qt.ShiftModifier)
        mouse(pv, "release", (1500, 200))
        mouse(pv, "press", (1700, 400))
        mouse(pv, "release", (1700, 400))
        pv._pen_finish()
        self.apply()
        self.assertEqual(len(edit.find(self.p, "k0")[1]["asset"]["paths"]), 2)


class Booleans(unittest.TestCase):
    def test_union_subtract_and_back_to_paths(self):
        sq = lambda x0, y0, x1, y1: {"nodes": [[x0, y0, 0, 0, 0, 0], [x1, y0, 0, 0, 0, 0], [x1, y1, 0, 0, 0, 0], [x0, y1, 0, 0, 0, 0]],
                                     "closed": True}
        a, b = pentool.qpath_of_paths([sq(0, 0, 100, 100)]), pentool.qpath_of_paths([sq(50, 0, 150, 100)])
        area = lambda q: sum(abs(s["nodes"][0][0]) * 0 for s in []) or q.boundingRect().width() * q.boundingRect().height()
        u = pentool.combine("union", [a, b])
        self.assertAlmostEqual(u.boundingRect().width(), 150, delta=0.01)
        d = pentool.combine("subtract", [a, b])
        self.assertAlmostEqual(d.boundingRect().width(), 50, delta=0.01)
        paths = pentool.paths_of_qpath(d)
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0]["closed"])
        self.assertEqual(len(paths[0]["nodes"]), 4)
        self.assertEqual(pentool.paths_of_qpath(pentool.combine("intersect", [a, pentool.qpath_of_paths([sq(500, 500, 600, 600)])])), [])


class PathMask(unittest.TestCase):
    def test_path_cuts_the_other_clips_and_its_track_is_reference(self):
        from test_edit import S, clip
        from kiasecut import project
        p = project.new()
        a, b = clip("a", 0, S), clip("b", 0, S)
        b["asset"] = assets.path_params([{"nodes": [[0, 0, 0, 0, 0, 0], [100, 0, 0, 0, 0, 0], [50, 80, 0, 0, 0, 0]], "closed": True}])[0]
        p["tracks"] = [{"id": "t1", "kind": "video", "name": "v", "clips": [a]}, {"id": "t2", "kind": "video", "name": "v", "clips": [b]}]
        p = project.link(p)
        out = edit.mask_by_shape(p, "b", ["a", "b"], (1920, 1080))
        self.assertEqual([c["id"] for c in out], ["a"])
        self.assertEqual((a["mask"]["kind"], a["mask"]["track_id"]), ("track", "t2"))
        self.assertTrue(p["tracks"][1]["reference"])


def pv_nodes(pv, p):
    """The nodes of clip k0 in canvas px as the tool reads them."""
    box = Box(edit.find(p, "k0")[1], 1920, 1080, 0)
    keep, pv.pen = pv.pen, {"paths": [], "cur": None, "edit": "k0", "box": box, "sel": set(), "drag": None, "hover": None}
    pv._pen_load(box)
    out = [n for sub in pv.pen["paths"] for n in sub["nodes"]]
    pv.pen = keep
    return out


if __name__ == "__main__":
    unittest.main()
