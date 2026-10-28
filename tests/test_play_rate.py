"""播放速度: the preview plays slower or faster - its clock runs at that rate, and the sound is
made to fit (pieces add up to exactly that much shorter or longer): at its own pitch with
保持音高 (stretch.py), else resampled like a tape (speed_pcm)."""
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import gpu, stretch  # noqa: E402
from kiasecut.audiomix import CHANNELS  # noqa: E402
from kiasecut.ui import player  # noqa: E402
from test_player_output import Device, wait_for  # noqa: E402

APP = QApplication.instance() or QApplication([])


def pcm(n):
    a = np.zeros((n, CHANNELS), np.int16)
    a[:, 0] = np.arange(n)                              # a ramp: resampling keeps it one
    return a.tobytes()


class SpeedPcmTests(unittest.TestCase):
    def samples(self, b):
        return len(b) // (2 * CHANNELS)

    def test_one_is_untouched(self):
        self.assertEqual(player.speed_pcm(pcm(800), 1.0), (pcm(800), 0.0))

    def test_faster_is_shorter_slower_longer(self):
        out, carry = player.speed_pcm(pcm(800), 2.0)
        self.assertEqual((self.samples(out), carry), (400, 0.0))
        out, _ = player.speed_pcm(pcm(800), 0.5)
        self.assertEqual(self.samples(out), 1600)
        ramp = np.frombuffer(out, np.int16).reshape(-1, CHANNELS)[:, 0]
        self.assertTrue((np.diff(ramp.astype(int)) >= 0).all())

    def test_pieces_add_up(self):
        total, carry = 0, 0.0
        for _ in range(30):                              # 1470 samples a picture at 0.75x: 1960 each
            out, carry = player.speed_pcm(pcm(1470), 0.75, carry)
            total += self.samples(out)
        self.assertEqual(total, round(30 * 1470 / 0.75))


def tone(hz, seconds, rate=48000):
    t = np.arange(round(rate * seconds)) / rate
    a = (np.sin(2 * np.pi * hz * t) * 10000).astype(np.int16)
    return np.stack([a] * CHANNELS, axis=1).tobytes()


def pitch(b, rate=48000):
    a = np.frombuffer(b, np.int16).reshape(-1, CHANNELS)[:, 0].astype(float)
    a = a[len(a) // 4: 3 * len(a) // 4]                 # (past the start's few ms of silence)
    return np.argmax(np.abs(np.fft.rfft(a * np.hanning(len(a))))) * rate / len(a)


class KeepPitchTests(unittest.TestCase):
    def stretched(self, rate, src, piece=1600):
        s, carry, out = stretch.Stretch(rate, CHANNELS), 0.0, []
        for i in range(0, len(src), piece * 2 * CHANNELS):
            b, carry = s.feed(src[i:i + piece * 2 * CHANNELS], carry)
            out.append(b)
        return b"".join(out)

    def test_same_pitch_and_length(self):
        src = tone(440, 2.0)
        for rate in (0.5, 0.75, 1.5, 2.0, 4.0):
            out = self.stretched(rate, src)
            self.assertEqual(len(out) // (2 * CHANNELS), round(96000 / rate), rate)
            self.assertAlmostEqual(pitch(out), 440, delta=3)
            self.assertAlmostEqual(pitch(player.speed_pcm(src, rate)[0]), 440 * rate, delta=3 * rate)   # (tape)

    def test_steady_loudness(self):
        out = np.frombuffer(self.stretched(1.5, tone(300, 2.0)), np.int16).reshape(-1, CHANNELS)[:, 0].astype(float)
        rms = [np.sqrt((w ** 2).mean()) for w in np.split(out[4800:4800 + 48000], 20)]     # 50 ms windows
        self.assertLess(max(rms) / min(rms), 1.15)


class ClockTests(unittest.TestCase):
    def setUp(self):
        self.cache = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cache, True)
        devices = mock.Mock()
        devices.defaultAudioOutput = lambda: Device(None)          # (silent: the clock alone)
        for patch in (mock.patch.object(player, "QMediaDevices", devices), mock.patch.object(gpu, "enabled", False)):
            patch.start()
            self.addCleanup(patch.stop)
        self.w = player.Worker()
        self.th = threading.Thread(target=self.w.run, daemon=True)
        self.th.start()
        self.addCleanup(self._end)
        self.w.set_view({"width": 64, "height": 36, "fps": 30.0, "duration_us": 60_000_000, "tracks": []}, self.cache)
        self.assertTrue(wait_for(lambda: self.w.length > 0))

    def _end(self):
        self.w.stop()
        self.th.join(5)

    def frames_in(self, seconds):
        start = self.w.pos
        self.w.set_playing(True)
        time.sleep(seconds)
        self.w.set_playing(False)
        return self.w.pos - start

    def test_double_and_half_speed(self):
        self.w.set_rate(2.0)
        fast = self.frames_in(1.0)
        self.assertGreater(fast, 45)                    # ~60 frames of 30 fps in a second
        self.assertLess(fast, 72)
        self.w.set_rate(0.5)
        slow = self.frames_in(1.0)
        self.assertGreater(slow, 9)                     # ~15
        self.assertLess(slow, 21)

    def test_either_pitch_keeps_time(self):
        for keep in (True, False):
            self.w.set_keep_pitch(keep)
            self.w.set_rate(2.0)
            fast = self.frames_in(0.5)
            self.assertGreater(fast, 20, keep)          # ~30
            self.assertLess(fast, 38, keep)


if __name__ == "__main__":
    unittest.main()
