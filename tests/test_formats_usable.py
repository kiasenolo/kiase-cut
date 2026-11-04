"""formats.usable: a format whose encoder this ffmpeg lacks (Android's has no x265) is left out of the export dialog."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kiasecut import formats  # noqa: E402


class UsableTest(unittest.TestCase):
    def test_missing_encoder_makes_a_format_unusable(self):
        with mock.patch.object(formats, "encoders", return_value={"libx264", "aac", "prores_ks"}):
            self.assertFalse(formats.usable(formats.get("mp4_h265")))
            self.assertFalse(formats.usable(formats.get("webm_vp9")))
            self.assertTrue(formats.usable(formats.get("mp4_h264")))
            self.assertTrue(formats.usable(formats.get("mov_prores")))

    def test_any_of_the_encoders_will_do_and_unknown_means_usable(self):
        with mock.patch.object(formats, "encoders", return_value={"hevc_nvenc"}):
            self.assertTrue(formats.usable(formats.get("mp4_h265")))
        with mock.patch.object(formats, "encoders", return_value=None):
            self.assertTrue(formats.usable(formats.get("mp4_h265")))


if __name__ == "__main__":
    unittest.main()
