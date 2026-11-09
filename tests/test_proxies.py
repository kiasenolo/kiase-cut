"""Preview proxies (proxies.py): a long-GOP video gets a small short-GOP copy for the preview's jumps; exports read the file itself."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from kiasecut import proxies, videoreader  # noqa: E402
from kiasecut.build import find_ffmpeg  # noqa: E402


@unittest.skipUnless(find_ffmpeg(), "needs ffmpeg")
class ProxyTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.src = os.path.join(self.dir, "long.mp4")
        subprocess.run([find_ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25:duration=12",
                        "-c:v", "libx264", "-g", "100", "-pix_fmt", "yuv420p", self.src], check=True)       # a key frame every 4 s
        videoreader._info.clear()
        proxies._wanted.clear()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def wait(self):
        end = time.time() + 60
        while proxies.busy() and time.time() < end:
            time.sleep(0.1)

    def test_made_in_the_background_and_used_for_a_small_picture(self):
        readers = videoreader.Readers(os.path.join(self.dir, "proxy"))
        readers.get(self.src, 1_000_000, 640, 360)                      # asks for it
        self.wait()
        img = readers.get(self.src, 7_000_000, 640, 360)
        self.assertEqual((img.width(), img.height()), (960, 540))      # (the proxy's own size)
        made = os.listdir(os.path.join(self.dir, "proxy"))
        self.assertEqual(len(made), 1)
        self.assertTrue(made[0].endswith(".mp4"))
        self.assertTrue(any(s.path.endswith(made[0]) for s in readers.streams))
        gap = proxies.key_frame_gap(os.path.join(self.dir, "proxy", made[0]))
        self.assertLessEqual(gap, 0.5)

    def test_a_picture_bigger_than_the_proxy_reads_the_file(self):
        readers = videoreader.Readers(os.path.join(self.dir, "proxy"))
        readers.get(self.src, 1_000_000, 640, 360)
        self.wait()
        readers.get(self.src, 8_000_000, 1280, 720)
        self.assertTrue(all(s.path == self.src for s in readers.streams if s.w == 1280))

    def test_exports_read_without_proxies(self):
        readers = videoreader.Readers()
        readers.get(self.src, 1_000_000, 640, 360)
        self.assertEqual(proxies._queue, [])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "proxy")))

    def test_short_gop_files_and_the_switch(self):
        short = os.path.join(self.dir, "short.mp4")
        subprocess.run([find_ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25:duration=4",
                        "-c:v", "libx264", "-g", "10", "-pix_fmt", "yuv420p", short], check=True)
        self.assertFalse(proxies.worth(videoreader.info(short), short))
        self.assertTrue(proxies.worth(videoreader.info(self.src), self.src))
        proxies.enabled = False
        try:
            self.assertIsNone(proxies.request(os.path.join(self.dir, "proxy"), self.src, videoreader.info(self.src)))
            self.assertFalse(proxies.busy())
        finally:
            proxies.enabled = True


if __name__ == "__main__":
    unittest.main()
