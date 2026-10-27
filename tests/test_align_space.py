"""Align (left ... bottom: with each other, or one clip with the canvas) and even spacing,
including a typed gap that is negative (overlapping)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, project  # noqa: E402
from kiasecut.ui.preview import Box, Preview  # noqa: E402
from test_edit import S, clip  # noqa: E402

APP = QApplication.instance() or QApplication([])


def scene(*places):
    """Clips 192 x 108 px (scale 0.1 of a 1920 x 1080 picture) centred at the given canvas px."""
    p = project.new()
    clips = []
    for i, (x, y) in enumerate(places):
        c = clip(f"k{i}", 0, S)
        c["transform"].update(scale=0.1, x=(x - 960) / 960, y=(540 - y) / 540)
        clips.append(c)
    p["tracks"] = [{"id": f"t{i}", "kind": "video", "name": "v", "clips": [c]} for i, c in enumerate(clips)]
    project.refresh_duration(p)
    p = project.link(p)
    pv = Preview()
    pv.set_scene(p, 0, "k0", {c["id"] for c in clips})
    return p, pv


def apply(p, moves):
    for cid, vals in moves.items():
        for k, v in vals.items():
            edit.set_param(p, cid, "transform", k, v)


def ext(p, cid):
    return Box(edit.find(p, cid)[1], 1920, 1080, 0).extents()


class AlignTests(unittest.TestCase):
    def test_align_to_each_other(self):
        p, pv = scene((300, 200), (700, 500), (1000, 300))
        apply(p, pv.align_moves("left"))
        self.assertTrue(all(abs(ext(p, f"k{i}")[0] - (300 - 96)) < 0.5 for i in range(3)))
        apply(p, pv.align_moves("bottom"))
        self.assertTrue(all(abs(ext(p, f"k{i}")[3] - (500 + 54)) < 0.5 for i in range(3)))
        apply(p, pv.align_moves("hcenter"))
        mids = [(ext(p, f"k{i}")[0] + ext(p, f"k{i}")[1]) / 2 for i in range(3)]
        self.assertTrue(max(mids) - min(mids) < 0.5)

    def test_one_clip_in_a_group_to_the_group(self):
        p, pv = scene((300, 200), (700, 500), (1500, 900))
        g = edit.make_group(p, p, ["k0", "k1"])
        for moved in (False, True):
            if moved:                                    # (a moved group: still its own clips' box)
                edit.set_param(p, g["id"], "transform", "x", 0.3)
            pv.set_scene(p, 0, "k0", {"k0"})
            apply(p, pv.align_moves("right"))
            self.assertAlmostEqual(ext(p, "k0")[1], 700 + 96, 1)
            apply(p, pv.align_moves("top"))
            self.assertAlmostEqual(ext(p, "k0")[2], 200 - 54, 1)
            apply(p, pv.align_moves("left"))
            self.assertAlmostEqual(ext(p, "k0")[0], 700 - 96, 1)    # (k1's left: k0 is right over it now)
            apply(p, pv.align_moves("hcenter"))
            self.assertAlmostEqual(ext(p, "k0")[0], 700 - 96, 1)

    def test_in_an_anchored_group(self):
        p, pv = scene((300, 200), (700, 500))
        g = edit.make_group(p, p, ["k0", "k1"])
        edit.set_group_anchor(p, g["id"], True)                  # (k1 counts from k0's centre)
        pv.set_scene(p, 0, "k1", {"k1"})
        apply(p, pv.align_moves("left"))
        pv.set_scene(p, 0, "k1", {"k1"})
        k1 = pv._kid_boxes()["k1"][0]
        self.assertAlmostEqual(k1.extents()[0], 300 - 96, 1)     # where it shows: on k0's left edge
        self.assertAlmostEqual(k1.extents()[2], 500 - 54, 1)

    def test_one_clip_to_the_canvas(self):
        p, pv = scene((300, 200))
        apply(p, pv.align_moves("right"))
        self.assertAlmostEqual(ext(p, "k0")[1], 1920, 1)
        apply(p, pv.align_moves("vcenter"))
        self.assertAlmostEqual(edit.find(p, "k0")[1]["transform"]["y"], 0.0, 4)

    def test_even_and_typed_spacing(self):
        p, pv = scene((200, 500), (500, 500), (1200, 500))   # gaps 108 and 508
        axis, gaps = pv.spacing()
        self.assertEqual(axis, "x")
        self.assertEqual([round(g) for g in gaps], [108, 508])
        apply(p, pv.space_moves())
        pv.set_scene(p, 0, "k0", {"k0", "k1", "k2"})
        self.assertEqual([round(g) for g in pv.spacing()[1]], [308, 308])
        self.assertAlmostEqual(ext(p, "k0")[0], 200 - 96, 1)      # the first one stays
        apply(p, pv.space_moves(-40))                              # overlapping
        pv.set_scene(p, 0, "k0", {"k0", "k1", "k2"})
        self.assertEqual([round(g) for g in pv.spacing()[1]], [-40, -40])
        apply(p, pv.space_moves(20))                               # and apart again
        pv.set_scene(p, 0, "k0", {"k0", "k1", "k2"})
        self.assertEqual([round(g) for g in pv.spacing()[1]], [20, 20])

    def test_vertical_spread(self):
        p, pv = scene((500, 100), (520, 400), (480, 1000))
        self.assertEqual(pv.spacing()[0], "y")


if __name__ == "__main__":
    unittest.main()
