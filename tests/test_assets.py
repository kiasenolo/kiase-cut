"""Built-in assets (內建素材): every one makes a valid SVG of the right size, idents round-trip,
writing reuses an identical file."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import assets, library, svgimage  # noqa: E402

APP = QApplication.instance() or QApplication([])


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_every_asset_is_a_picture(self):
        for a in assets.ASSETS:
            path = assets.write(self.dir, a, "#3366ff", "#ff336680", 1920, 1080)
            info = library.probe(path)
            self.assertEqual(info["kind"], "image", a.key)
            if a.cat != "shape":                            # fills the canvas
                self.assertEqual((info["width"], info["height"]), (1920, 1080), a.key)
            img = svgimage.raster(path, 64)
            self.assertGreater(sum(img.pixelColor(x, y).alpha() for x in range(0, 64, 4)
                                   for y in range(0, img.height(), 2)), 0, a.key)

    def test_colours(self):
        a = assets.get("solid.custom")
        img = svgimage.raster(assets.write(self.dir, a, "#ff0000", "#000000", 16, 9), 16)
        self.assertEqual(img.pixelColor(8, 4).name(), "#ff0000")
        red = assets.get("solid.3")                         # a preset keeps its own colour
        img = svgimage.raster(assets.write(self.dir, red, "#00ff00", "#000000", 16, 9), 16)
        self.assertEqual(img.pixelColor(8, 4).name(), "#e53935")
        g = assets.get("gradient.custom.h")
        img = svgimage.raster(assets.write(self.dir, g, "#000000", "#ffffff", 100, 10), 100)
        self.assertLess(img.pixelColor(2, 5).red(), 30)
        self.assertGreater(img.pixelColor(97, 5).red(), 225)

    def test_ident(self):
        a, c1, c2 = assets.parse(assets.ident("shape.star", "#AABBCC", "#11223344"))
        self.assertEqual((a.key, c1, c2), ("shape.star", "#aabbcc", "#11223344"))
        self.assertEqual(assets.parse("asset:shape.star:junk")[1:], ("#ffffff", "#000000"))
        self.assertIsNone(assets.parse("asset:nope"))
        self.assertIsNone(assets.parse("mabc"))

    def test_write_reuses(self):
        a = assets.get("shape.circle")
        p1 = assets.write(self.dir, a, "#ffffff", "#000000", 1920, 1080)
        p2 = assets.write(self.dir, a, "#ffffff", "#000000", 1280, 720)     # shapes do not depend on the canvas
        self.assertEqual(p1, p2)
        with open(p1, "w", encoding="utf-8") as fh:
            fh.write("changed")
        p3 = assets.write(self.dir, a, "#ffffff", "#000000", 1920, 1080)
        self.assertNotEqual(p1, p3)
        self.assertEqual(len(os.listdir(self.dir)), 2)
        s = assets.get("solid.0")
        self.assertNotEqual(assets.write(self.dir, s, "", "", 1920, 1080),
                            assets.write(self.dir, s, "", "", 1080, 1920))

    def test_panel(self):
        from kiasecut.ui.assets_panel import AssetsPanel
        from kiasecut.ui.timeline import MEDIA_MIME
        panel = AssetsPanel()
        got = []
        panel.addRequested.connect(got.append)
        lst = panel.lists["shape"]
        self.assertEqual(lst.count(), sum(a.cat == "shape" for a in assets.ASSETS))
        md = lst.mimeData([lst.item(0)])
        self.assertEqual(bytes(md.data(MEDIA_MIME)).decode(), "asset:shape.rect:#ffffff:#000000")
        panel.colors = ["#ff0000", "#00ff00"]
        panel.refresh()
        lst.itemDoubleClicked.emit(lst.item(0))
        self.assertEqual(got, ["asset:shape.rect:#ff0000:#00ff00"])


if __name__ == "__main__":
    unittest.main()
