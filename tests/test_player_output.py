"""Preview sound output: opened anew on the default device each time playing starts, again
when the sound devices change while playing (headphones out or back in), and none at all -
playing silently - when there is no device."""
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import gpu  # noqa: E402
from kiasecut.ui import player  # noqa: E402

APP = QApplication.instance() or QApplication([])


class Device:
    def __init__(self, name):
        self.name = name

    def isNull(self):
        return self.name is None


class Out:
    def write(self, data):
        return len(data)


class Sink:
    made = []

    def __init__(self, device, _fmt):
        self.device, self.stopped = device.name, False
        Sink.made.append(self)

    def setBufferSize(self, _n):
        pass

    def start(self):
        return Out()

    def bytesFree(self):
        return 1 << 20

    def stop(self):
        self.stopped = True


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class OutputTests(unittest.TestCase):
    def setUp(self):
        Sink.made = []
        self.default = Device("speakers")
        self.cache = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cache, True)
        devices = mock.Mock()
        devices.defaultAudioOutput = lambda: self.default
        for patch in (mock.patch.object(player, "QAudioSink", Sink), mock.patch.object(player, "QMediaDevices", devices),
                      mock.patch.object(gpu, "enabled", False)):
            patch.start()
            self.addCleanup(patch.stop)
        self.w = player.Worker()
        self.th = threading.Thread(target=self.w.run, daemon=True)
        self.th.start()
        self.addCleanup(self._end)
        self.w.set_view({"width": 64, "height": 36, "fps": 30.0, "duration_us": 20_000_000, "tracks": []},
                        self.cache)
        self.assertTrue(wait_for(lambda: self.w.length > 0))          # (playing waits for a project)

    def _end(self):
        self.w.stop()
        self.th.join(5)

    def test_follows_the_default_device(self):
        self.w.set_playing(True)
        self.assertTrue(wait_for(lambda: len(Sink.made) == 1))
        self.default = Device("headphones")                     # plugged in while playing
        self.w.outputs_changed()
        self.assertTrue(wait_for(lambda: len(Sink.made) == 2))
        self.assertTrue(Sink.made[0].stopped)
        self.assertEqual(Sink.made[1].device, "headphones")
        self.w.set_playing(False)
        self.assertTrue(wait_for(lambda: Sink.made[1].stopped))
        self.default = Device("speakers")                       # out while stopped: the next play uses the new one
        self.w.set_playing(True)
        self.assertTrue(wait_for(lambda: len(Sink.made) == 3))
        self.assertEqual(Sink.made[2].device, "speakers")

    def test_plays_silently_without_a_device(self):
        self.default = Device(None)
        self.w.set_playing(True)
        self.assertTrue(wait_for(lambda: self.w.pos > 3))      # the picture still moves on
        self.assertEqual(Sink.made, [])


if __name__ == "__main__":
    unittest.main()
