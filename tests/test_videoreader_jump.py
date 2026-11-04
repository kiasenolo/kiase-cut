"""videoreader.Readers.get: a jump gets None (the engine draws that one picture) - except where there is no engine (Android)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kiasecut import videoreader  # noqa: E402

INFO = {"w": 640, "h": 360, "fps": 30.0, "codec": "h264", "matrix": "auto"}


class JumpTest(unittest.TestCase):
    def get(self, engine):
        r = videoreader.Readers()
        with mock.patch.object(videoreader, "info", return_value=INFO), \
                mock.patch.object(videoreader, "find_ffmpeg", return_value="ffmpeg"), \
                mock.patch.object(videoreader, "ENGINE", engine), \
                mock.patch.object(r, "_start", return_value="picture") as start:
            return r.get("a.mp4", 5_000_000, 640, 360), start

    def test_a_jump_is_left_to_the_engine(self):
        img, start = self.get(True)
        self.assertIsNone(img)
        start.assert_not_called()

    def test_without_an_engine_a_jump_starts_a_stream(self):
        img, start = self.get(False)
        self.assertEqual(img, "picture")
        start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
