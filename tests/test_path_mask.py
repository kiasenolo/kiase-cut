"""路徑 masks: a pen path of the clip's own cuts it (both renderers), feathered and inverted like the shapes, its parts
keyframed (they blend node by node); drawn and edited with the pen in mask mode."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF  # noqa: E402

from kiasecut import curves, edit, glrender, masks, project, render, renderexport  # noqa: E402
from test_edit import S  # noqa: E402
from test_track_source import APP, clip, pic  # noqa: E402,F401


def scene():
    p = project.new(1920, 1080, 30)
    p["tracks"] = [{"id": "top", "kind": "video", "name": "上", "clips": [clip("red", pic("#ff0000"), dur=2 * S)]}]
    project.link(p)
    project.refresh_duration(p)
    return p


def reds(img, xs, y=54):
    return [img.pixelColor(x, y).red() for x in xs]


class PathMaskTests(unittest.TestCase):
    def test_default_path_cuts_both_renderers_alike(self):
        p = scene()
        edit.set_mask(p, "red", masks.PATH)
        m = edit.find(p, "red")[1]["mask"]
        self.assertEqual((m["w"], m["h"], len(m["paths"][0]["nodes"])), (1.0, 1.0, 4))
        self.assertTrue(renderexport.needs_renderer(p))
        for r in (render.Renderer(None), glrender.GLRenderer(None)):
            got = reds(r.render(p, 10, 192, 108), (20, 46, 50, 96, 140, 150))
            self.assertEqual(got, [0, 0, 255, 255, 255, 0])       # the middle half (48 - 144) is kept
            self.assertEqual(reds(r.render(p, 10, 192, 108), (96,), y=10), [0])
        edit.set_param(p, "red", "mask", "invert", True)
        for r in (render.Renderer(None), glrender.GLRenderer(None)):
            self.assertEqual(reds(r.render(p, 10, 192, 108), (20, 96)), [255, 0])

    def test_feather_softens_the_edge(self):
        p = scene()
        edit.set_mask(p, "red", masks.PATH)
        edit.set_param(p, "red", "mask", "feather", 0.3)
        for r in (render.Renderer(None), glrender.GLRenderer(None)):
            a, b, c = reds(r.render(p, 10, 192, 108), (40, 48, 56))
            self.assertTrue(0 < a < b < c, (a, b, c))

    def test_keyframed_path_blends_node_by_node(self):
        p = scene()
        edit.set_mask(p, "red", masks.PATH)
        c = edit.find(p, "red")[1]
        edit.toggle_key(p, "red", "mask", "paths", 0)
        moved = [{"nodes": [[n[0] + 0.2] + n[1:] for n in c["mask"]["paths"]["keys"][0][1][0]["nodes"]], "closed": True}]
        edit.set_param(p, "red", "mask", "paths", moved, S)
        self.assertAlmostEqual(curves.value(c["mask"]["paths"], S // 2)[0]["nodes"][0][0], 0.35, places=6)
        self.assertAlmostEqual(curves.value(c["mask"]["paths"], 2 * S)[0]["nodes"][0][0], 0.45, places=6)
        other = [{"nodes": [[0.1, 0.1, 0, 0, 0, 0], [0.9, 0.1, 0, 0, 0, 0], [0.5, 0.9, 0, 0, 0, 0]], "closed": True}]
        self.assertEqual(curves.blend(moved, other, 0.5), moved)          # (three nodes against four: held)
        self.assertEqual(curves.value({"keys": [[0, [1.0, 0.0, 0.0], 0, 0, 0, 0], [10, [0.0, 0.0, 1.0], 0, 0, 0, 0]]}, 5),
                         [0.5, 0.0, 0.5])                                  # (colours blend as before)

    def test_set_mask_path_takes_the_drawn_parts(self):
        p = scene()
        tri = [{"nodes": [[0.1, 0.1, 0, 0, 0, 0], [0.9, 0.1, 0, 0, 0, 0], [0.5, 0.9, 0, 0, 0, 0]], "closed": True}]
        edit.set_mask_path(p, "red", tri)
        m = edit.find(p, "red")[1]["mask"]
        self.assertEqual((m["kind"], m["paths"]), (masks.PATH, tri))
        with self.assertRaises(edit.EditError):
            edit.set_mask_path(p, "red", [{"nodes": [[0, 0, 0, 0, 0, 0]], "closed": False}])


class PenOnMaskTests(unittest.TestCase):
    def setUp(self):
        from test_align_space import scene as pv_scene
        self.p, self.pv = pv_scene((960, 540))
        self.pv.resize(1000, 600)
        self.pv.set_scene(self.p, 0, "k0", {"k0"})
        self.pv.set_mask_mode(True, "mask")
        self.got, self.drawn = [], []
        self.pv.paramsCommitted.connect(lambda cid, g, v: self.got.append((cid, g, v)))
        self.pv.maskPathDrawn.connect(lambda cid, paths: self.drawn.append((cid, paths)))

    def test_drawn_path_becomes_the_mask_and_edits_round_trip(self):
        from test_pen_tool import mouse
        from PySide6.QtCore import Qt
        pv = self.pv
        box = pv.selected_box()
        corners = [box.xf().map(QPointF(x * box.bw, y * box.bh)) for x, y in ((-0.25, -0.25), (0.25, -0.25), (0.0, 0.25))]
        self.assertTrue(pv.pen_begin(mask_for="k0"))
        for pt in corners + [corners[0]]:                                 # three corners, then the first: closed
            mouse(pv, "press", (pt.x(), pt.y()))
            mouse(pv, "release", (pt.x(), pt.y()))
        self.assertIsNone(pv.pen)
        cid, paths = self.drawn[0]
        self.assertEqual(cid, "k0")
        nodes = paths[0]["nodes"]
        self.assertTrue(paths[0]["closed"])
        for n, want in zip(nodes, ((0.25, 0.25), (0.75, 0.25), (0.5, 0.75))):
            self.assertAlmostEqual(n[0], want[0], delta=0.01)
            self.assertAlmostEqual(n[1], want[1], delta=0.01)
        edit.set_mask_path(self.p, "k0", paths)
        pv.set_scene(self.p, 0, "k0", {"k0"})
        self.assertTrue(pv.pen_edit_mask())
        pv._pen_commit()                                                  # unchanged nodes go back as they came
        cid, group, values = self.got[-1]
        self.assertEqual((cid, group), ("k0", "mask"))
        for a, b in zip(values["paths"][0]["nodes"], nodes):
            for u, v in zip(a[:6], b[:6]):
                self.assertAlmostEqual(u, v, places=6)
        pv.set_mask_mode(False)
        self.assertIsNone(pv.pen)                                         # (leaving mask mode ends it)
        _ = Qt


if __name__ == "__main__":
    unittest.main()
