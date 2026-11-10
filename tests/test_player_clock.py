"""Playing when the pictures are slow to draw (a tablet): the sound is queued without waiting for the output, the clock
the pictures follow is put back to the sound when the sound is behind it, and the sound's lead grows with what a picture
takes - the pictures come as fast as they can be drawn. They used to come slower and slower: each one waited for room
in an output that stayed full once the sound had fallen behind (2 pictures a second where 9 could be drawn)."""
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

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import gpu  # noqa: E402
from kiasecut.audiomix import CHANNELS, RATE  # noqa: E402
from kiasecut.ui import player  # noqa: E402
from test_player_output import Device, wait_for  # noqa: E402

APP = QApplication.instance() or QApplication([])
BYTES_S = RATE * CHANNELS * 2


class Draining:
    """A sound output that plays what it holds at the real speed, and has room for no more than its buffer."""
    made = []

    def __init__(self, _device, _fmt):
        self.size, self.held, self.at, self.written, self.empty_s = 0, 0.0, None, 0, 0.0
        Draining.made.append(self)

    def setBufferSize(self, n):
        self.size = n

    def bufferSize(self):
        return self.size

    def start(self):
        self.at = time.monotonic()
        return self

    def _play(self):
        now = time.monotonic()
        due = (now - self.at) * BYTES_S
        if due > self.held:
            self.empty_s += (due - self.held) / BYTES_S        # (it ran empty that long)
        self.held, self.at = max(0.0, self.held - due), now

    def bytesFree(self):
        self._play()
        return int(self.size - self.held)

    def write(self, data):
        n = min(len(data), self.bytesFree())
        self.held += n
        self.written += n
        return n

    def stop(self):
        pass


class SlowPictureTests(unittest.TestCase):
    def setUp(self):
        Draining.made = []
        self.cache = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cache, True)
        devices = mock.Mock()
        devices.defaultAudioOutput = lambda: Device("speakers")
        for patch in (mock.patch.object(player, "QAudioSink", Draining), mock.patch.object(player, "QMediaDevices", devices),
                      mock.patch.object(gpu, "enabled", False)):
            patch.start()
            self.addCleanup(patch.stop)
        self.w = player.Worker()
        self.shown = []
        real = self.w._show

        def slow(pos):
            if self.w.playing:
                time.sleep(self.takes)
                self.shown.append((time.monotonic(), pos))
            real(pos)
        self.w._show = slow
        self.takes = 0.12
        self.th = threading.Thread(target=self.w.run, daemon=True)
        self.th.start()
        self.addCleanup(self._end)
        self.w.set_view({"width": 64, "height": 36, "fps": 60.0, "duration_us": 60_000_000, "tracks": []}, self.cache)
        self.assertTrue(wait_for(lambda: self.w.length > 0))

    def _end(self):
        self.w.stop()
        self.th.join(5)

    def test_pictures_come_as_fast_as_they_are_drawn(self):
        self.w.set_playing(True)
        time.sleep(3.0)
        self.w.set_playing(False)
        self.assertTrue(wait_for(lambda: not self.w.playing))
        late = [(t, pos) for t, pos in self.shown if t > self.shown[0][0] + 1.5]      # (once it has settled)
        gaps = [b[0] - a[0] for a, b in zip(late, late[1:])]
        self.assertGreater(len(late), 8)                                 # (1.5 s of pictures of 0.12 s: 12; it was 3)
        self.assertLess(max(gaps), 0.3)                                  # none waited for the output
        # the pictures keep to the clock: as far on in the project as the time that passed
        (t0, p0), (t1, p1) = late[0], late[-1]
        self.assertAlmostEqual((p1 - p0) / 60.0, t1 - t0, delta=0.15)

    def test_the_sound_leads_by_what_a_picture_takes(self):
        self.w.set_playing(True)
        time.sleep(2.5)
        sink = Draining.made[-1]
        before = sink.empty_s
        time.sleep(1.0)
        self.w.set_playing(False)
        self.assertGreater(self.w._lead(), 0.2 * 60)                     # more than the 6 frames a quick picture needs
        self.assertLess(sink.empty_s - before, 0.05)                     # and the output did not run empty for it

    def test_the_clock_is_put_back_to_a_sound_that_is_behind(self):
        w = player.Worker()
        w.view = {"fps": 60.0}
        w.sink_bytes = BYTES_S // 2
        sink = mock.Mock()
        sink.bytesFree = lambda: 0                                       # full: half a second still to be heard
        w.audio_n = 60                                                   # a second of sound queued: half a second heard
        w.t0 = time.monotonic() - 0.8                                    # the clock says 0.8 s
        w._follow_sound(sink)
        self.assertAlmostEqual(time.monotonic() - w.t0, 0.5, delta=0.02)
        w._follow_sound(sink)                                            # (in step now: left alone)
        self.assertAlmostEqual(time.monotonic() - w.t0, 0.5, delta=0.02)
        w.t0 = time.monotonic() - 0.2                                    # the sound ahead of the clock: nothing to do
        w._follow_sound(sink)
        self.assertAlmostEqual(time.monotonic() - w.t0, 0.2, delta=0.02)


class DragPictureTests(unittest.TestCase):
    """On a tablet the stopped pictures of a drag are drawn smaller when one at its size is slow, and the last one again
    at its size when the drag rests."""

    def setUp(self):
        self.cache = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cache, True)
        for patch in (mock.patch.object(gpu, "enabled", False), mock.patch.object(player, "PLAY_SCALES", (1.0, 0.5))):
            patch.start()
            self.addCleanup(patch.stop)
        self.w = player.Worker()
        self.drawn = []                                                  # (frame, width) of each picture
        self.takes = 0.08
        self.th = threading.Thread(target=self.w.run, daemon=True)
        self.th.start()
        self.addCleanup(self._end)
        self.assertTrue(wait_for(lambda: hasattr(self.w, "renderer")))
        real = self.w.renderer.render

        def render(view, pos, w, h, *a, **k):
            time.sleep(self.takes)
            self.drawn.append((pos, w))
            return real(view, pos, w, h, *a, **k)
        self.w.renderer.render = render
        self.w.set_view({"width": 640, "height": 360, "fps": 30.0, "duration_us": 20_000_000, "tracks": []}, self.cache)
        self.assertTrue(wait_for(lambda: len(self.drawn) == 1))

    def _end(self):
        self.w.stop()
        self.th.join(5)

    def seek(self, pos):
        n = len(self.drawn)
        self.w.request_seek(pos)
        self.assertTrue(wait_for(lambda: len(self.drawn) > n))

    def test_a_drags_pictures_are_smaller_and_the_last_is_drawn_again_at_its_size(self):
        time.sleep(0.4)
        self.seek(10)                                                    # a jump by itself: at its size
        self.assertEqual(self.drawn[-1], (10, 640))
        for pos in (11, 12, 13):                                         # one after the other: a drag
            self.seek(pos)
            self.assertEqual(self.drawn[-1], (pos, 320))
        self.assertTrue(wait_for(lambda: self.drawn[-1] == (13, 640)))   # it rests there
        n = len(self.drawn)
        time.sleep(0.4)
        self.assertEqual(len(self.drawn), n)                             # (once)

    def test_quick_pictures_stay_at_their_size(self):
        self.takes = 0.0
        time.sleep(0.4)
        for pos in (10, 11, 12, 13):
            self.seek(pos)
            self.assertEqual(self.drawn[-1], (pos, 640))

    def test_a_chosen_quality_is_kept(self):
        self.w.set_quality(0.5)
        self.assertTrue(wait_for(lambda: self.drawn[-1][1] == 320))
        time.sleep(0.4)
        for pos in (10, 11, 12):
            self.seek(pos)
            self.assertEqual(self.drawn[-1], (pos, 320))
        n = len(self.drawn)
        time.sleep(0.4)
        self.assertEqual(len(self.drawn), n)                             # (nothing to draw again)


if __name__ == "__main__":
    unittest.main()
