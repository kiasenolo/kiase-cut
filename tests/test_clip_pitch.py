"""A clip's 保持音高 and 目標長度: played twice as fast its 440 Hz stays 440 Hz (off: 880 Hz, as a
tape), and a length asked for sets the speed that gives it."""
import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kiasecut import audiomix, build, edit, project, stretch  # noqa: E402
from test_edit import S  # noqa: E402

FFMPEG = build.find_ffmpeg()


def pitch(pcm):
    a = pcm.astype(np.float32).mean(axis=1)
    f = np.abs(np.fft.rfft(a * np.hanning(len(a))))
    return np.argmax(f) * audiomix.RATE / len(a)


class StretchTests(unittest.TestCase):
    def test_all_at_once(self):
        t = np.arange(audiomix.RATE) / audiomix.RATE
        tone = (np.sin(2 * np.pi * 440 * t) * 10000).astype(np.int16)
        a = np.stack([tone, tone], axis=1)
        out = stretch.stretch_all(a, 2.0)
        self.assertEqual(len(out), audiomix.RATE // 2)
        self.assertAlmostEqual(pitch(out[2000:-2000]), 440, delta=8)


@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class ClipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.path = os.path.join(cls.dir, "a440.wav")
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                        "-ac", "2", "-c:a", "pcm_s16le", cls.path], check=True)

    def proj(self):
        c = {"id": "s", "type": "audio", "name": "x", "start_us": 0, "duration_us": 4 * S, "source_start_us": 0,
             "media": {"path": self.path, "duration_us": 4 * S}, "volume": 1.0}
        return project.link(dict(project.new(), tracks=[{"id": "a", "kind": "audio", "name": "a", "clips": [c]}]))

    def mixed(self, p):
        mix = audiomix.Mixer(self.dir)
        mix.set_view(p)
        mix.thread.join()
        return np.frombuffer(b"".join(mix.mix(f, 30) for f in range(5, 35)), np.int16).reshape(-1, 2)

    def test_keep_pitch(self):
        p = self.proj()
        edit.set_speed(p, "s", 2.0)
        self.assertAlmostEqual(pitch(self.mixed(p)), 880, delta=10)          # a tape
        edit.set_keep_pitch(p, "s", True)
        self.assertAlmostEqual(pitch(self.mixed(p)), 440, delta=10)          # its own pitch

    def test_target_length(self):
        p = self.proj()
        c = edit.set_duration_by_speed(p, "s", 1 * S)
        self.assertEqual((round(project.speed(c), 3), c["duration_us"]), (4.0, S))
        c = edit.set_duration_by_speed(p, "s", 2 * S)
        self.assertEqual((round(project.speed(c), 3), c["duration_us"]), (2.0, 2 * S))


class SpeedCurveTests(unittest.TestCase):
    def clip(self):
        c = {"id": "v", "type": "video", "name": "x", "start_us": 0, "duration_us": 4 * S, "source_start_us": S,
             "media": {"path": "x.mp4", "duration_us": 20 * S, "width": 10, "height": 10}, "transform": {},
             "volume": 1.0, "fade_in_us": S}
        p = project.new()
        p["tracks"] = [{"id": "t", "kind": "video", "name": "v", "clips": [c]}]
        project.link(p)
        return p, c

    def test_same_source_new_length(self):
        p, c = self.clip()
        edit.set_speed_curve(p, "v", [[0, 1], [0.5, 4], [1, 1]])
        self.assertAlmostEqual(project.source_time(c, 0), S)
        self.assertAlmostEqual(project.source_time(c, c["duration_us"]), 5 * S, delta=5)    # the same 4 s of it
        self.assertLess(c["duration_us"], 2 * S)                                             # mean above 2x
        self.assertAlmostEqual(project.speed(c), 4 * S / c["duration_us"], delta=1e-3)
        mid = project.source_time(c, c["duration_us"] / 2) - S
        self.assertAlmostEqual(mid, 2 * S, delta=S * 0.01)                                   # (symmetric)
        early = project.source_time(c, c["duration_us"] * 0.1) - S
        self.assertLess(early / (c["duration_us"] * 0.1), project.speed(c))                  # slow at the start
        self.assertLess(c["fade_in_us"], S)                                                  # stretched with it
        edit.set_speed_curve(p, "v", False)
        self.assertNotIn("speed_curve", c)
        self.assertAlmostEqual(project.speed(c), 4 * S / c["duration_us"], delta=1e-3)       # its mean, plain

    def test_points_cleaned(self):
        p, c = self.clip()
        edit.set_speed_curve(p, "v", [[0.2, 50], [0.6, 0.01]])
        self.assertEqual(c["speed_curve"]["points"], [[0.0, 10.0], [1.0, 0.1]])
        with self.assertRaises(edit.EditError):
            edit.set_speed_curve(p, "v", [[0.5, 1]])
        edit.set_speed(p, "v", 2.0)                                                          # a plain speed: off
        self.assertNotIn("speed_curve", c)


@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class SpeedCurveSoundTests(ClipTests):
    def test_pitch_follows_the_curve(self):
        p = self.proj()
        edit.set_speed_curve(p, "s", [[0, 2], [1, 2]])                                       # flat 2x: a tape at 880
        self.assertAlmostEqual(pitch(self.mixed(p)), 880, delta=10)

    test_keep_pitch = test_target_length = None


if __name__ == "__main__":
    unittest.main()
