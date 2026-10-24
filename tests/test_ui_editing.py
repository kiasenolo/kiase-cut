"""Scaling on the preview (anchored / about the centre, linked / unlinked X Y), the editor's
own frame rate (時間線精度) in the player and the timeline, grabbing the playhead line, the
ruler never grabbing clips scrolled under it, clip colours (per track, see-through fill)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import assets, edit  # noqa: E402
from kiasecut.ui.main_window import edit_rate  # noqa: E402
from kiasecut.ui.player import Worker  # noqa: E402
from kiasecut.ui.preview import Box, Preview  # noqa: E402
from kiasecut.ui.timeline import COLORS, FILL_ALPHA, HEADER_W, RULER_H, ROW_BG, Timeline, clip_color, row_color  # noqa: E402
from test_edit import S, clip, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
NONE = Qt.KeyboardModifier.NoModifier


def picture(**tf):
    c = clip("c", 0, S)                         # 1920 x 1080 picture: fills the canvas at scale 1
    c["transform"].update(scale=0.5, **tf)       # 960 x 540, centred
    return c


class ScaleDragTests(unittest.TestCase):
    def drag(self, c, side, to, mods=NONE):
        pv = Preview()
        box = Box(c, 1920, 1080, 0)
        handle = next(pt for sx, sy, pt in box.handles() if (sx, sy) == side)
        d = {"side": side, "m0": handle}
        group, out = pv._scale_values(box, d, QPointF(handle.x() + to[0], handle.y() + to[1]), mods)
        if group == "multi":                                    # a built-in asset: its size
            moved = dict(c, transform=dict(c["transform"], **out.get("transform", {})),
                         asset=dict(c["asset"], **out["asset"]))
            return out, Box(moved, 1920, 1080, 0)
        return out, Box(dict(c, transform=dict(c["transform"], **out)), 1920, 1080, 0)

    def test_corner_keeps_the_opposite_corner(self):
        c = picture()
        before = Box(c, 1920, 1080, 0).corners()[0]           # top left
        out, after = self.drag(c, (1, 1), (96, 54))            # bottom right, outwards
        self.assertAlmostEqual(out["scale"], 0.55, 3)
        self.assertAlmostEqual(out["scale_y"], 0.55, 3)
        tl = after.corners()[0]
        self.assertAlmostEqual(tl.x(), before.x(), 1)
        self.assertAlmostEqual(tl.y(), before.y(), 1)

    def test_alt_scales_about_the_centre(self):
        out, after = self.drag(picture(), (1, 1), (96, 54), Qt.KeyboardModifier.AltModifier)
        self.assertNotIn("x", out)
        self.assertAlmostEqual(out["scale"], 0.6, 3)            # both sides move
        self.assertAlmostEqual(after.cx, 960, 3)

    def test_linked_edge_keeps_the_ratio(self):
        out, after = self.drag(picture(), (1, 0), (96, 0))     # right edge
        self.assertAlmostEqual(out["scale"], 0.55, 3)
        self.assertAlmostEqual(out["scale_y"], 0.55, 3)
        self.assertAlmostEqual(after.extents()[0], 480, 1)     # the left edge stays

    def test_unlinked_edge_and_corner(self):
        out, after = self.drag(picture(scale_link=False), (1, 0), (96, 0))
        self.assertAlmostEqual(out["scale"], 0.55, 3)
        self.assertAlmostEqual(out["scale_y"], 0.5, 3)          # only its own axis
        out, _ = self.drag(picture(scale_link=False), (1, 1), (96, 0))
        self.assertAlmostEqual(out["scale"], 0.55, 3)
        self.assertAlmostEqual(out["scale_y"], 0.5, 3)          # a corner sets each freely
        out, _ = self.drag(picture(scale_link=False), (1, 1), (96, 0), Qt.KeyboardModifier.ShiftModifier)
        self.assertAlmostEqual(out["scale"], out["scale_y"], 4)  # Shift keeps the ratio

    def test_asset_changes_its_size(self):
        c = clip("c", 0, S)
        c["asset"] = assets.make(assets.get("shape.rect"), "#ffffff", "", 1920, 1080)
        c["transform"]["scale"] = 0.5                          # shown 200 x 200
        before = Box(c, 1920, 1080, 0)
        out, after = self.drag(c, (1, 0), (50, 0))             # right edge: 100 px of the clip's own
        self.assertEqual(out["asset"], {"w": 500.0, "h": 400.0})
        self.assertNotIn("scale", out["transform"])            # the scale stays
        self.assertAlmostEqual(after.extents()[0], before.extents()[0], 1)
        out, _ = self.drag(c, (1, 1), (50, 0))                 # corner: each side freely
        self.assertEqual(out["asset"], {"w": 500.0, "h": 400.0})
        out, _ = self.drag(c, (1, 1), (50, 0), Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(out["asset"]["w"], out["asset"]["h"])
        out, _ = self.drag(c, (1, 0), (50, 0), Qt.KeyboardModifier.AltModifier)
        self.assertEqual(out["asset"]["w"], 600.0)              # about the centre: both sides
        self.assertNotIn("transform", out)

    def test_rotated_anchor(self):
        c = picture(rotation=30.0)
        before = Box(c, 1920, 1080, 0).corners()[3]           # bottom left stays for the top right
        _, after = self.drag(c, (1, -1), (40, -70))
        self.assertAlmostEqual(after.corners()[3].x(), before.x(), 1)
        self.assertAlmostEqual(after.corners()[3].y(), before.y(), 1)


class EditRateTests(unittest.TestCase):
    def test_edit_rate(self):
        p = proj()
        self.assertEqual(edit_rate(p), p["fps"])
        p["view"] = {"edit_fps": 240}
        self.assertEqual(edit_rate(p), 240)
        p["view"] = {"edit_fps": "junk"}
        self.assertEqual(edit_rate(p), p["fps"])

    def test_player_steps(self):
        w = Worker()
        w.view = {"fps": 240.0, "play_fps": 60.0}
        self.assertEqual(w.step(), 4)                          # a picture every 4 frames of the editor
        w.view = {"fps": 30.0, "play_fps": 30.0}
        self.assertEqual(w.step(), 1)
        w.view = {"fps": 24.0, "play_fps": 60.0}               # coarser than the project: every frame
        self.assertEqual(w.step(), 1)
        w.loop = (10, 19)
        self.assertEqual(w._next(18, 4), 12)                   # wraps inside the time selection

    def test_timeline(self):
        tl = Timeline()
        tl.resize(1000, 400)
        tl.edit_fps = 240.0
        tl.set_project(proj())
        self.assertEqual(tl.fps, 240.0)
        self.assertEqual(tl.max_zoom(), 9600.0)
        tl.px_per_s, tl.scroll_s = 100.0, 0.0
        tl.set_position(240, follow=False)                      # 1 s
        x = HEADER_W + 100
        self.assertTrue(tl._on_playhead(QPointF(x + 2, RULER_H + 50)))
        self.assertFalse(tl._on_playhead(QPointF(x + 12, RULER_H + 50)))
        self.assertFalse(tl._on_playhead(QPointF(x, RULER_H - 5)))     # the ruler seeks anyway
        tl.edit_fps = None
        tl.set_project(proj())
        self.assertEqual(tl.fps, proj()["fps"])


class TimelineClipTests(unittest.TestCase):
    def timeline(self, p, h=300):
        tl = Timeline()
        tl.resize(900, h)
        tl.set_project(p)
        tl.px_per_s, tl.scroll_s = 100.0, 0.0
        return tl

    def test_ruler_does_not_grab_clips_under_it(self):
        p = proj()
        for _ in range(6):                                  # enough tracks to scroll
            edit.add_track(p, "video")
        tl = self.timeline(p, h=150)
        top_row = 0                                         # the top row gets c1
        src = next(t for t in p["tracks"] if any(c["id"] == "c1" for c in t["clips"]))
        c1 = next(c for c in src["clips"] if c["id"] == "c1")
        src["clips"].remove(c1)
        tl.rows[top_row]["clips"].append(c1)
        tl.scroll_y = tl.row_h(top_row) // 2                # its row half under the ruler
        tl._layout()
        self.assertLess(tl.tops[top_row], RULER_H)
        y = RULER_H - 5                                     # on the ruler, over clip c1 (0 - 2 s)
        x = HEADER_W + 100
        self.assertIsNone(tl._row_at(y))
        self.assertEqual(tl._hit(QPointF(x, y))[1], None)
        seeks = []
        tl.seekRequested.connect(seeks.append)
        QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
        QTest.mouseMove(tl, QPoint(x + 50, y))
        self.assertEqual(tl.drag["mode"], "seek")           # the playhead, not the clip
        QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x + 50, y))
        self.assertTrue(seeks)
        self.assertEqual(edit.find(p, "c1")[1]["start_us"], 0)
        below = tl.tops[top_row] + tl.row_h(top_row) - 6    # its part below the ruler still works
        self.assertEqual(tl._hit(QPointF(x, below))[1]["id"], "c1")

    def test_track_clip_colours(self):
        p = proj()
        edit.set_track_clip_colors(p, "t0", "#ff8800")
        self.assertEqual({c.get("color") for c in p["tracks"][0]["clips"]}, {"#ff8800"})
        self.assertNotIn("color", p["tracks"][2]["clips"][0])          # other tracks stay
        edit.set_track_clip_colors(p, "t0", None)
        self.assertFalse(any("color" in c for c in p["tracks"][0]["clips"]))

    def test_clip_takes_its_tracks_colour(self):
        c = clip("c", 0, S)
        self.assertEqual(clip_color(c, {"color": "#ff8a65"}).name(), "#ff8a65")       # default: the track's
        self.assertEqual(clip_color(c, {}).name(), COLORS["image"])
        c["color"] = "#00ff00"                                                        # its own wins
        self.assertEqual(clip_color(c, {"color": "#ff8a65"}).name(), "#00ff00")

    def test_row_is_a_deep_shade(self):
        self.assertEqual(row_color({}), ROW_BG)
        row = row_color({"color": "#ff8a65"})
        self.assertLess(row.value(), 100)                                            # dark
        self.assertGreater(row.red() - row.blue(), 30)                               # still orange

    def test_see_through_fill_and_coloured_outline(self):
        p = proj()
        p["tracks"][0]["clips"][0]["color"] = "#ffff00"      # a light colour
        tl = self.timeline(p)
        img = QImage(tl.size(), QImage.Format_ARGB32)
        tl.render(img)
        row = next(i for i, r in enumerate(tl.rows) if r["id"] == "t0")
        y = round(tl.tops[row] + tl.row_h(row) / 2)
        inside = img.pixelColor(HEADER_W + 150, y)          # a tint, far darker than the colour
        outline = max((img.pixelColor(HEADER_W + i, y) for i in range(5)), key=lambda q: q.green())   # left edge
        self.assertLess(inside.red(), 150)
        self.assertGreater(outline.red(), 200)
        self.assertGreater(outline.green(), 200)
        self.assertEqual(FILL_ALPHA, 0x50)


if __name__ == "__main__":
    unittest.main()
