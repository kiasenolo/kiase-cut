"""BPM alignment (節拍) and the playhead's snapping."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, project  # noqa: E402
from kiasecut.ui.timeline import HEADER_W, Timeline  # noqa: E402

APP = QApplication.instance() or QApplication([])
S = 1_000_000


def proj():
    p = project.new(fps=30.0)
    p["tracks"] = [
        {"id": "t0", "kind": "video", "name": "v", "clips": [
            {"id": "v1", "type": "image", "name": "v1", "start_us": 3 * S, "duration_us": 2 * S, "source_start_us": 0,
             "media": {"path": "x.png", "width": 64, "height": 64},
             "transform": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}}]},
        {"id": "t1", "kind": "audio", "name": "a", "clips": [
            {"id": "a1", "type": "audio", "name": "a", "start_us": 10 * S, "duration_us": 8 * S,
             "source_start_us": 2 * S, "media": {"path": "a.mp3", "duration_us": 60 * S}, "volume": 1.0}]},
    ]
    project.refresh_duration(p)
    return project.link(p)


class BeatEdits(unittest.TestCase):
    def test_grid_follows_the_sound(self):
        p = proj()
        _, a = edit.find(p, "a1")
        self.assertEqual(edit.beat_times(a), [])                     # none until switched on
        edit.set_beat(p, "a1", on=True, bpm=120, offset_us=0.25 * S)
        # beat 0 at source 0.25 s; the clip shows source 2 s.. at timeline 10 s
        beats = edit.beat_times(a)
        self.assertAlmostEqual(beats[0], 10.25 * S)
        self.assertAlmostEqual(beats[1] - beats[0], 0.5 * S)
        self.assertTrue(all(10 * S <= b <= 18 * S for b in beats))
        self.assertEqual(len(beats), 16)
        edit.trim_start(p, "a1", 11 * S)                        # trimming keeps beats on the music
        self.assertAlmostEqual(edit.beat_times(a)[0], 11.25 * S)
        self.assertEqual(edit.beat_times(a, 12 * S, 13 * S), [12.25 * S, 12.75 * S])

    def test_off_keeps_reset_removes(self):
        p = proj()
        edit.set_beat(p, "a1", on=True, bpm=95.5, offset_us=S)
        edit.set_beat(p, "a1", on=False)
        _, a = edit.find(p, "a1")
        self.assertEqual(a["beat"], {"on": False, "bpm": 95.5, "offset_us": S})
        self.assertEqual(edit.beat_times(a), [])
        edit.set_beat(p, "a1", on=True)
        self.assertEqual(a["beat"]["bpm"], 95.5)
        edit.clear_beat(p, "a1")
        self.assertNotIn("beat", a)
        with self.assertRaises(edit.EditError):
            edit.set_beat(p, "v1", on=True)                          # pictures have no beat

    def test_undo_and_view_stay_apart(self):
        p = proj()
        h = edit.History(p)
        p["view"] = {"vzoom": 1.5}
        h.do("on", edit.set_beat, "a1", on=True)
        p["view"] = {"vzoom": 2.0}
        h.undo()
        self.assertNotIn("beat", edit.find(p, "a1")[1])
        self.assertEqual(p["view"], {"vzoom": 2.0})                  # undo leaves the view alone


class TimelineSnaps(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.tl = Timeline()
        self.tl.resize(1200, 300)
        self.tl.set_project(self.p)
        self.tl.px_per_s, self.tl.scroll_s = 50.0, 0.0
        self.seeks = []
        self.tl.seekRequested.connect(self.seeks.append)

    def x(self, sec):
        return HEADER_W + sec * self.tl.px_per_s

    def test_playhead_snaps_to_clip_edges(self):
        self.tl.drag = {"clip": None, "mode": "seek", "moved": False}
        self.tl._seek_to(self.x(5.1))                                # near v1's end (5 s)
        self.assertEqual(self.seeks[-1], 150)
        self.assertEqual(self.tl._snap_guides(), [5 * S])
        self.tl._seek_to(self.x(7.0))                                # nothing near
        self.assertEqual(self.seeks[-1], 210)
        self.assertEqual(self.tl._snap_guides(), [])
        self.tl.snapping = False
        self.tl._seek_to(self.x(5.1))
        self.assertEqual(self.seeks[-1], 153)

    def test_beats_are_targets(self):
        edit.set_beat(self.p, "a1", on=True, bpm=60, offset_us=2.5 * S)   # beats at 10.5, 11.5, ...
        self.tl.drag = {"clip": None, "mode": "seek", "moved": False}
        self.tl._seek_to(self.x(11.55))
        self.assertEqual(self.seeks[-1], round(11.5 * 30))
        # a moved picture clip lands its start on a beat; its own beats never pull the sound clip
        _, v = edit.find(self.p, "v1")
        self.assertAlmostEqual(self.tl._snap_span(12.45 * S, 2 * S, v), 12.5 * S)
        _, a = edit.find(self.p, "a1")
        self.assertNotIn(10.5 * S, self.tl._snap_targets(a))
        edit.set_beat(self.p, "a1", on=False)
        self.assertNotIn(10.5 * S, self.tl._snap_targets(None))

    def test_view_state_round_trip(self):
        self.tl.px_per_s, self.tl.scroll_s = 123.0, 4.5
        self.tl.heights = {"t1": 90}
        v = self.tl.view_state()
        other = Timeline()
        other.resize(1200, 300)
        other.set_project(proj())
        other.set_view_state(v)
        self.assertEqual((other.px_per_s, other.scroll_s, other.heights), (123.0, 4.5, {"t1": 90}))


if __name__ == "__main__":
    unittest.main()
