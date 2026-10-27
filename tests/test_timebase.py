"""時基: the BPM timebase counts bars, beats and parts; the ruler and the readout show it."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import project  # noqa: E402
from kiasecut.ui.timebase import clip_zero  # noqa: E402
from kiasecut.ui.timeline import Timeline, beat_code, on_frames, time_text, timebase_of  # noqa: E402

APP = QApplication.instance() or QApplication([])
S = 1_000_000


def tb(**kw):
    return timebase_of(dict(kind="bpm", **kw))


class Codes(unittest.TestCase):
    def test_bars_beats_parts(self):
        t = tb(bpm=120, div=4, meter=4, offset_us=1 * S)       # a beat every 0.5 s from 1 s
        self.assertEqual(beat_code(1 * S, t), "1.1.1")
        self.assertEqual(beat_code(1.125 * S, t), "1.1.2")
        self.assertEqual(beat_code(1.5 * S, t), "1.2.1")
        self.assertEqual(beat_code(3 * S, t), "2.1.1")
        self.assertEqual(beat_code(3 * S - 1, t), "1.4.4")     # just before a line: the part before
        self.assertEqual(beat_code(0.5 * S, t), "0.4.1")       # before the offset: bar 0
        self.assertEqual(beat_code(-1 * S, t), "0.1.1")
        self.assertEqual(beat_code(-1 * S - 1, t), "-1.4.4")

    def test_without_parts_or_bars(self):
        self.assertEqual(beat_code(3 * S, tb(bpm=60, div=1, meter=4)), "1.4")
        self.assertEqual(beat_code(3.5 * S, tb(bpm=60, div=2, meter=0)), "4.2")
        self.assertEqual(beat_code(7 * S, tb(bpm=60, div=1, meter=3)), "3.2")

    def test_time_kind_shows_seconds(self):
        self.assertEqual(time_text(61.5 * S, 30, timebase_of({"kind": "time", "bpm": 90})), "01:01.15")
        self.assertEqual(time_text(61.5 * S, 30, None), "01:01.15")

    def test_beats_fall_on_frames(self):
        t = tb(bpm=120, div=4, meter=4, offset_us=1.03 * S)    # 16 frames a second: 8 a beat
        self.assertEqual(on_frames(t, 16)["offset_us"], 1 * S)
        self.assertEqual(t["offset_us"], 1.03 * S)             # (what was typed stays)
        codes = [time_text(f / 16 * S, 16, t) for f in range(16, 26)]
        self.assertEqual(codes, ["1.1.1", "1.1.1", "1.1.2", "1.1.2", "1.1.3", "1.1.3", "1.1.4", "1.1.4",
                                 "1.2.1", "1.2.1"])

    def test_bad_saved_values(self):
        self.assertEqual(timebase_of("x")["kind"], "time")
        t = timebase_of({"kind": "bpm", "bpm": 0, "div": 5, "meter": 8})
        self.assertEqual((t["bpm"], t["div"], t["meter"]), (1.0, 4, 4))
        self.assertEqual(timebase_of({"kind": "bpm", "bpm": "?"})["kind"], "time")

    def test_clip_beats_on_the_timeline(self):
        c = {"start_us": 10 * S, "source_start_us": 2 * S, "beat": {"on": True, "bpm": 100, "offset_us": 0.25 * S}}
        self.assertEqual(clip_zero(c), (100, 8.25 * S))
        self.assertEqual(clip_zero(dict(c, speed=2.0)), (200, 9.125 * S))
        self.assertIsNone(clip_zero({"start_us": 0}))


class Ruler(unittest.TestCase):
    def test_paints_at_every_zoom(self):
        tl = Timeline()
        tl.resize(900, 300)
        tl.set_project(project.link(project.new(fps=30.0)))
        for meter in (0, 4):
            for div in (1, 3, 4):
                tl.timebase = tb(bpm=128, div=div, meter=meter, offset_us=-0.3 * S)
                for px in (0.5, 5, 40, 400, 1200):
                    tl.px_per_s = px
                    img = QImage(tl.size(), QImage.Format_ARGB32)
                    tl.render(img)


if __name__ == "__main__":
    unittest.main()
