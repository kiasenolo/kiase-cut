"""時間線軌道 as a picture source: a mask (or an effect's colour) reading what a track of the same
level shows at that moment."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import assets, edit, glrender, project, render, renderexport  # noqa: E402
from test_edit import S  # noqa: E402

APP = QApplication.instance() or QApplication([])


def pic(col, w=64, h=36):
    path = os.path.join(tempfile.mkdtemp(), "p.png")
    im = QImage(w, h, QImage.Format_RGB32)
    im.fill(QColor(col))
    im.save(path)
    return path


def clip(cid, path, x=0.0, scale=1.0, start=0, dur=2 * S):
    return {"id": cid, "type": "image", "name": cid, "start_us": start, "duration_us": dur, "source_start_us": 0,
            "media": {"path": path, "width": 64, "height": 36},
            "transform": {"x": x, "y": 0.0, "scale": scale, "rotation": 0.0, "opacity": 1.0}}


class TrackSourceTests(unittest.TestCase):
    def scene(self):
        p = project.new(1920, 1080, 30)
        p["tracks"] = [
            {"id": "shape", "kind": "video", "name": "形狀", "hidden": False,
             "clips": [clip("left", pic("#ffffff"), x=-0.5, scale=0.5, dur=S)]},       # white, left half, first second
            {"id": "top", "kind": "video", "name": "上", "clips": [clip("red", pic("#ff0000"))]},
        ]
        project.link(p)
        edit.set_mask(p, "red", "track")
        edit.set_mask_track(p, "red", "shape", (1920, 1080))
        project.refresh_duration(p)
        return p

    def red_at(self, p, frame, x, renderer=None):
        img = (renderer or render.Renderer(None)).render(p, frame, 192, 108)
        c = img.pixelColor(x, 54)
        return c.red() > 200 and c.green() < 60

    def test_shape_mask_hides_only_the_shape(self):
        """用路徑當遮罩: the red clip is cut by the white shape alone; the shape is not drawn, and a blue clip later on the
        shape's track still shows - in the editor's preview and in an export (no editing level) alike."""
        p = self.scene()
        shape = p["tracks"][0]["clips"][0]                       # a white rectangle over the left half
        shape["asset"] = dict(assets.make(assets.get("shape.rect"), "#ffffff", "#000000", 1920, 1080), w=960, h=1080)
        shape["transform"]["scale"] = 1.0
        p["tracks"][0]["clips"].append(clip("blue", pic("#0000ff"), x=0.5, scale=0.5, start=S, dur=S))
        p["tracks"][1]["clips"][0]["mask"] = None
        edit.mask_by_shape(p, "left", ["red"], (1920, 1080))
        self.assertFalse(p["tracks"][0].get("reference"))
        self.assertTrue(renderexport.needs_renderer(p))
        for r in (render.Renderer(None), glrender.GLRenderer(None)):
            self.assertTrue(self.red_at(p, 10, 48, r))          # where the shape is: the red clip
            self.assertFalse(self.red_at(p, 10, 150, r))        # elsewhere cut away
            img = r.render(p, 10, 192, 108)
            self.assertLess(img.pixelColor(150, 54).red(), 60)   # (and the white shape is not drawn there either)
            img = r.render(p, 45, 192, 108)
            c = img.pixelColor(150, 54)
            self.assertTrue(c.blue() > 200 and c.red() < 60)    # the shape's track still shows its other clip

    def test_reference_track_still_cuts_in_an_export(self):
        p = self.scene()
        p["tracks"][0]["reference"] = True
        for r in (render.Renderer(None), glrender.GLRenderer(None)):
            self.assertTrue(self.red_at(p, 10, 48, r))
            self.assertFalse(self.red_at(p, 10, 150, r))

    def test_mask_follows_the_track(self):
        p = self.scene()
        for r in (render.Renderer(None), glrender.GLRenderer(None)):
            self.assertTrue(self.red_at(p, 10, 48, r))          # where the track shows white: the red clip
            self.assertFalse(self.red_at(p, 10, 150, r))        # elsewhere cut away
            self.assertFalse(self.red_at(p, 45, 48, r))         # after its clip ends: nothing to let through
        self.assertTrue(renderexport.needs_renderer(p))

    def test_effect_colour_from_a_track(self):
        """單色填滿 fed from the track: the red clip takes the track's colours where it shows."""
        p = self.scene()
        edit.set_mask(p, "red", None)
        with self.assertRaises(edit.EditError):
            edit.set_mask_track(p, "red", "shape", (1920, 1080))       # (no 軌道 mask any more)
        e = edit.add_effect(p, "red", "builtin:replace_color")
        e["params"]["IN_Color_c"] = [0.0, 0.0, 1.0, 1.0]               # blue where the track has nothing
        edit.set_effect_source(p, "red", e["id"], "IN_Color_c", "track")
        edit.set_effect_source_media(p, "red", e["id"], "IN_Color_c", track=("shape", (1920, 1080)))
        img = render.Renderer(None).render(p, 10, 192, 108)
        left, right = img.pixelColor(48, 54), img.pixelColor(150, 54)
        self.assertGreater(left.green(), 200)                           # white from the track
        self.assertEqual((right.red() < 60, right.blue() > 200), (True, True))


if __name__ == "__main__":
    unittest.main()
