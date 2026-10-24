"""Streaming video reader and GPU switches (skipped without ffmpeg)."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication  # noqa: E402

from kiasecut import gpu, videoreader  # noqa: E402
from kiasecut.build import find_ffmpeg  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])
S = 1_000_000


class SizeTests(unittest.TestCase):
    def test_stream_size_halves(self):
        self.assertEqual(videoreader.stream_size(3840, 2160, 960, 540), (960, 540))
        self.assertEqual(videoreader.stream_size(3840, 2160, 961, 540), (1920, 1080))
        self.assertEqual(videoreader.stream_size(3840, 2160, 5000, 3000), (3840, 2160))   # never above the source
        self.assertEqual(videoreader.stream_size(1080, 1920, 300, 500), (540, 960))

    def test_encoder_choice(self):
        was = gpu.enabled
        try:
            gpu.enabled = False
            self.assertIn("libx264", gpu.ffmpeg_video_args({"crf": 20}, (1920, 1080)))
            self.assertIsNone(gpu.mlt_video_opts({"crf": 20}, (1920, 1080)))
            gpu.enabled = True
            if gpu.nvenc():
                self.assertIn("h264_nvenc", gpu.ffmpeg_video_args({"crf": 20}, (1920, 1080)))
                self.assertEqual(gpu.mlt_video_opts({"crf": 20}, (1920, 1080))["cq"], 22)
            self.assertIn("libx264", gpu.ffmpeg_video_args({"crf": 20}, (7680, 4320)))     # past NVENC's limit
        finally:
            gpu.enabled = was


@unittest.skipUnless(find_ffmpeg(), "needs ffmpeg")
class ReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.path = os.path.join(cls.dir, "count.mp4").replace("\\", "/")
        # every frame a different grey: frame n has video level 16 + 8n, which shows as 8n * 255 / 219
        subprocess.run([find_ffmpeg(), "-v", "error", "-f", "lavfi", "-i",
                        "color=c=black:s=64x36:r=30:d=1,geq=lum='16+8*N':cb=128:cr=128", "-c:v", "libx264",
                        "-qp", "0", "-pix_fmt", "yuv444p", cls.path], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def level(self, img):
        return img.pixelColor(img.width() // 2, img.height() // 2).red()

    def test_info(self):
        inf = videoreader.info(self.path)
        self.assertEqual((inf["w"], inf["h"], round(inf["fps"])), (64, 36, 30))

    def test_follows_on_and_jumps(self):
        r = videoreader.Readers()
        try:
            self.assertIsNone(r.get(self.path, 0, 64, 36))           # a first picture: the engine's job
            levels = [self.level(r.get(self.path, n * S / 30, 64, 36)) for n in range(1, 12)]
            self.assertEqual(len(r.streams), 1)
            for n, lv in enumerate(levels, 1):                      # frame n, read in order
                self.assertLessEqual(abs(lv - 8 * n * 255 / 219), 3, (n, levels))
            self.assertLessEqual(abs(self.level(r.get(self.path, 15 * S / 30, 64, 36)) - 120 * 255 / 219), 3)   # skips on
            self.assertEqual(len(r.streams), 1)
            self.assertIsNone(r.get(self.path, 2 * S / 30, 64, 36))  # backwards: a jump
        finally:
            r.close()


if __name__ == "__main__":
    unittest.main()
