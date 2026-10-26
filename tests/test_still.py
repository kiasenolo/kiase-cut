"""截取並匯出當下幀: a frame as a picture file, transparent where the format keeps it, else on
the background colour picked."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import assets, edit, gpu, renderexport  # noqa: E402
from test_edit import S, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


class StillTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.was = gpu.enabled
        gpu.enabled = False
        p = proj()
        p["tracks"][0]["clips"] = p["tracks"][0]["clips"][:1]
        params = assets.make(assets.get("shape.rect"), "#ff0000", "", 1920, 1080)
        edit.replace_media(p, "c1", assets.item(params, "/nowhere.svg"), params)   # a 400 px red square
        self.p = p

    def tearDown(self):
        gpu.enabled = self.was
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_transparent_png(self):
        out = os.path.join(self.dir, "f.png")
        renderexport.still(self.p, 0, (960, 540), out, alpha=True)
        im = QImage(out)
        self.assertEqual((im.width(), im.height()), (960, 540))
        self.assertEqual(im.pixelColor(480, 270).name(), "#ff0000")
        self.assertEqual(im.pixelColor(10, 10).alpha(), 0)

    def test_background_colour(self):
        out = os.path.join(self.dir, "f.png")
        renderexport.still(self.p, 0, (960, 540), out, alpha=False, background=QColor("#336699"))
        im = QImage(out)
        self.assertEqual(im.pixelColor(10, 10).name(), "#336699")
        self.assertEqual(im.pixelColor(10, 10).alpha(), 255)

    def test_jpeg_cannot_be_transparent(self):
        out = os.path.join(self.dir, "f.jpg")
        renderexport.still(self.p, 0, (480, 270), out, alpha=True, background=QColor("white"))
        im = QImage(out)
        self.assertGreater(im.pixelColor(5, 5).lightness(), 240)


if __name__ == "__main__":
    unittest.main()
