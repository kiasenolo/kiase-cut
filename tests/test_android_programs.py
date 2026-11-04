"""Where an Android build finds ffmpeg / ffprobe: lib<name>.so in the directory its libraries load from."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from kiasecut import build  # noqa: E402


def maps_of(*paths):
    """/proc/self/maps lines for these library files (and the anonymous ones every process has)."""
    lines = ["7a00000000-7a00001000 r--p 00000000 00:00 0 "]
    lines += [f"7b0000{i:04x}000-7b0000{i:04x}fff r-xp 00000000 fd:00 {i} {p}" for i, p in enumerate(paths)]
    return "\n".join(lines) + "\n"


class AndroidProgramTests(unittest.TestCase):
    def setUp(self):
        build.android_program.cache_clear()
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        for name in ("libffmpeg.so", "libffprobe.so", "libQt6Core_arm64-v8a.so"):
            open(os.path.join(self.dir.name, name), "wb").close()

    def tearDown(self):
        build.android_program.cache_clear()
        build._ffmpeg.clear()

    def test_found_next_to_the_apps_libraries(self):
        maps = maps_of("/system/lib64/libc.so", os.path.join(self.dir.name, "libQt6Core_arm64-v8a.so"))
        with mock.patch.object(sys, "platform", "android"), mock.patch("builtins.open", mock.mock_open(read_data=maps)):
            self.assertEqual(build.android_program("ffmpeg"), os.path.join(self.dir.name, "libffmpeg.so"))
            self.assertEqual(build.find_ffprobe(), os.path.join(self.dir.name, "libffprobe.so"))
            self.assertEqual(build.find_ffmpeg(), os.path.join(self.dir.name, "libffmpeg.so"))

    def test_not_there(self):
        with mock.patch.object(sys, "platform", "android"), \
                mock.patch("builtins.open", mock.mock_open(read_data=maps_of("/system/lib64/libc.so"))):
            self.assertIsNone(build.android_program("ffmpeg"))
            self.assertEqual(build.find_ffprobe(), "ffprobe")           # (falls back to PATH)

    def test_directory_can_be_given(self):
        with mock.patch.object(sys, "platform", "android"), \
                mock.patch.dict(os.environ, {"KIASECUT_BIN_DIR": self.dir.name}), \
                mock.patch("builtins.open", mock.mock_open(read_data="")):
            self.assertEqual(build.android_program("ffprobe"), os.path.join(self.dir.name, "libffprobe.so"))

    def test_other_systems_do_not_look(self):
        with mock.patch.dict(os.environ, {"KIASECUT_BIN_DIR": self.dir.name}):
            self.assertIsNone(build.android_program("ffmpeg"))


if __name__ == "__main__":
    unittest.main()
