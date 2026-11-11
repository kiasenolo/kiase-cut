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
        self.assertEqual(a["beat"], {"on": False, "bpm": 95.5, "offset_us": S, "div": 1, "meter": 4})
        self.assertEqual(edit.beat_times(a), [])
        edit.set_beat(p, "a1", on=True)
        self.assertEqual(a["beat"]["bpm"], 95.5)
        edit.clear_beat(p, "a1")
        self.assertNotIn("beat", a)
        with self.assertRaises(edit.EditError):
            edit.set_beat(p, "v1", on=True)                          # pictures have no beat

    def test_subdivisions(self):
        p = proj()
        edit.set_beat(p, "a1", on=True, bpm=60, offset_us=2 * S, div=4)   # beats at 10, 11, ... s
        _, a = edit.find(p, "a1")
        grid = edit.beat_grid(a, 10 * S, 11 * S)
        self.assertEqual([round(t) for t, _ in grid], [10 * S, 10.25 * S, 10.5 * S, 10.75 * S, 11 * S])
        self.assertEqual([d for _, d in grid], [1, 4, 2, 4, 1])
        edit.set_beat(p, "a1", div=6)
        self.assertEqual([d for _, d in edit.beat_grid(a, 10 * S, 11 * S)], [1, 6, 3, 2, 3, 6, 1])
        edit.set_beat(p, "a1", div=3)
        self.assertEqual([d for _, d in edit.beat_grid(a, 10 * S, 11 * S)], [1, 3, 3, 1])
        with self.assertRaises(edit.EditError):
            edit.set_beat(p, "a1", div=5)

    def test_bars(self):
        """拍號: with bars, a bar's first beat is 0 (every meter beats from beat 0)."""
        p = proj()
        edit.set_beat(p, "a1", on=True, bpm=60, offset_us=2 * S, div=2)   # beat 0 at 10 s: bars at 10, 14, 18 s
        _, a = edit.find(p, "a1")
        self.assertEqual(a["beat"]["meter"], 4)
        self.assertEqual([d for _, d in edit.beat_grid(a, 13 * S, 15 * S, bars=True)], [1, 2, 0, 2, 1])
        self.assertEqual([d for _, d in edit.beat_grid(a, 13 * S, 15 * S)], [1, 2, 1, 2, 1])      # (snapping)
        edit.set_beat(p, "a1", meter=3)                              # bars at 10, 13, 16 s
        self.assertEqual([d for _, d in edit.beat_grid(a, 13 * S, 14 * S, bars=True)], [0, 2, 1])
        edit.set_beat(p, "a1", meter=0)
        self.assertNotIn(0, [d for _, d in edit.beat_grid(a, bars=True)])
        edit.set_beat(p, "a1", div=0.5, meter=4)                     # a line every 2 beats: 10 (bar), 12, 14 (bar)
        self.assertEqual([d for _, d in edit.beat_grid(a, 10 * S, 14 * S, bars=True)], [0, 1, 0])
        with self.assertRaises(edit.EditError):
            edit.set_beat(p, "a1", meter=8)

    def test_bpm_divided_in_the_list(self):
        p = proj()
        edit.set_beat(p, "a1", on=True, bpm=180, offset_us=0.3 * S, div=0.5)   # 180 -> 90
        _, a = edit.find(p, "a1")
        self.assertEqual(a["beat"]["bpm"], 180.0)                    # the BPM typed in stays
        beats = edit.beat_times(a)
        self.assertAlmostEqual(beats[1] - beats[0], 60 / 90 * S)
        self.assertAlmostEqual(beats[0], 10.3 * S)                   # beat 0 at 8.3 s, every 2nd beat after it
        self.assertEqual({d for _, d in edit.beat_grid(a)}, {1})
        edit.set_beat(p, "a1", div=0.25)
        beats = edit.beat_times(a)
        self.assertAlmostEqual(beats[1] - beats[0], 60 / 45 * S)

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

    def test_dense_lines_drop_out(self):
        edit.set_beat(self.p, "a1", on=True, bpm=120, offset_us=0, div=4)   # a beat every 0.5 s
        _, a = edit.find(self.p, "a1")
        self.tl.px_per_s = 50.0                                      # quarters 6.25 px apart: all show
        self.assertEqual({d for _, d in self.tl._beat_lines(a)}, {1, 2, 4})
        self.tl.px_per_s = 15.0                                      # quarters 1.9 px, halves 3.75 px
        self.assertEqual({d for _, d in self.tl._beat_lines(a)}, {1})
        self.tl.px_per_s = 30.0                                      # halves 7.5 px
        self.assertEqual({d for _, d in self.tl._beat_lines(a)}, {1, 2})
        edit.set_beat(self.p, "a1", div=0.5)                         # a line every beat pair: 1 s
        self.tl.px_per_s = 6.0
        self.assertTrue(self.tl._beat_lines(a))
        self.tl.px_per_s = 4.0
        self.assertEqual(self.tl._beat_lines(a), [])

    def test_view_state_round_trip(self):
        self.tl.px_per_s, self.tl.scroll_s = 123.0, 4.5
        self.tl.heights = {"t1": 90}
        v = self.tl.view_state()
        other = Timeline()
        other.resize(1200, 300)
        other.set_project(proj())
        other.set_view_state(v)
        self.assertEqual((other.px_per_s, other.scroll_s, other.heights), (123.0, 4.5, {"t1": 90}))


class AdvancedEntry(unittest.TestCase):
    def test_panel_button_asks_for_the_editor(self):
        from kiasecut.ui.beat_panel import BeatPanel
        pn, got = BeatPanel(), []
        pn.advancedRequested.connect(got.append)
        pn.show_clips([edit.find(proj(), "a1")[1]])
        pn.advanced.click()
        self.assertEqual(got, ["a1"])

    def test_dialog_follows_its_clip(self):
        from kiasecut.ui.beat_dialog import BeatDialog
        p = proj()
        dlg = BeatDialog("a1")
        self.assertTrue(dlg.show_clip(p))
        self.assertFalse(BeatDialog("v1").show_clip(p))              # no sound
        self.assertFalse(BeatDialog("nope").show_clip(p))

    def test_alt_b_switches_all_to_the_opposite_of_the_first(self):
        from types import SimpleNamespace
        from kiasecut.ui.main_window import MainWindow
        p = proj()
        _, a1 = edit.find(p, "a1")
        p["tracks"][1]["clips"].append(dict(a1, id="a2", start_us=30 * S))
        edit.set_beat(p, "a2", on=True)
        applied = []
        sel = [edit.find(p, "a1")[1], edit.find(p, "a2")[1], edit.find(p, "v1")[1]]
        win = SimpleNamespace(proj=p, timeline=SimpleNamespace(selected_clips_primary_first=lambda: sel),
                              statusBar=lambda: None,
                              apply=lambda label, fn: (applied.append(label), fn(p)))
        MainWindow.do_toggle_beat(win)                              # first (a1) is off -> all on
        self.assertEqual(applied, ["啟用 BPM 對齊"])
        self.assertTrue(all(edit.find(p, i)[1]["beat"]["on"] for i in ("a1", "a2")))
        self.assertNotIn("beat", edit.find(p, "v1")[1])
        MainWindow.do_toggle_beat(win)
        self.assertFalse(any(edit.find(p, i)[1]["beat"]["on"] for i in ("a1", "a2")))


class SourceGridAndWave(unittest.TestCase):
    def test_source_grid_is_beat_grid_in_the_sounds_time(self):
        p = proj()
        _, a = edit.find(p, "a1")
        for div, meter in ((1, 4), (2, 3), (3, 0), (0.5, 4), (4, 7)):
            edit.set_beat(p, "a1", on=True, bpm=133, offset_us=0.37 * S, div=div, meter=meter)
            lo, hi = a["source_start_us"], a["source_start_us"] + a["duration_us"]
            mine = [(round(t - lo), d) for t, d in edit.source_grid(a["beat"], lo, hi, bars=True)]
            theirs = [(round(t - a["start_us"]), d) for t, d in edit.beat_grid(a, bars=True)]
            self.assertEqual([d for _, d in mine], [d for _, d in theirs])
            self.assertTrue(all(abs(x - y) <= 1 for (x, _), (y, _) in zip(mine, theirs)))

    def test_wave_view_draws_and_moves(self):
        import numpy as np
        from kiasecut.ui.beat_wave import WaveView
        p = proj()
        edit.set_beat(p, "a1", on=True, bpm=120, offset_us=0)
        _, a = edit.find(p, "a1")

        class Peaks:
            def get(self, path, stream=0):
                n = 60_000
                sig = np.sin(np.arange(n) / 40.0).astype(np.float32) * 0.6
                return np.stack([sig, -sig], 1), 0.0
        v = WaveView()
        v.resize(800, 300)
        v.set_clip(a, Peaks())
        self.assertAlmostEqual(v.t0, 2 * S - 0.04 * 8 * S, delta=2)          # focused on the clip's stretch
        self.assertFalse(v.grab().isNull())
        w = v.t1 - v.t0
        v.zoom(0.5, 400)
        self.assertAlmostEqual(v.t1 - v.t0, w / 2, delta=2)
        t0 = v.t0
        v.pan(1000)
        self.assertEqual(v.t0, t0 + 1000)
        v.fit()
        self.assertAlmostEqual(v.t0, 2 * S - 0.04 * 8 * S, delta=2)

    def test_overview_moves_the_big_view(self):
        import numpy as np
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QEvent
        from kiasecut.ui.beat_wave import Overview, WaveView
        p = proj()
        _, a = edit.find(p, "a1")

        class Peaks:
            def get(self, path, stream=0):
                return np.full((60_000, 2), [0.5, -0.5], np.float32), 0.0
        v = WaveView()
        v.resize(800, 300)
        v.set_clip(a, Peaks())
        o = Overview(v)
        o.resize(600, 64)
        self.assertFalse(o.grab().isNull())
        span = v.t1 - v.t0

        def mouse(kind, x):
            return QMouseEvent(kind, QPointF(x, 10), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        o.mousePressEvent(mouse(QEvent.MouseButtonPress, o.x_of(40 * S)))     # outside the frame: centred there
        self.assertAlmostEqual((v.t0 + v.t1) / 2, 40 * S, delta=S / 50)
        self.assertAlmostEqual(v.t1 - v.t0, span, delta=2)
        o.mouseMoveEvent(mouse(QEvent.MouseMove, o.x_of(20 * S)))
        self.assertAlmostEqual((v.t0 + v.t1) / 2, 20 * S, delta=S / 50)
        o.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease, 0))
        self.assertIsNone(o.drag)

    def test_preview_plays_only_the_stretch_and_loops(self):
        import shutil
        import subprocess
        import tempfile
        import time
        from kiasecut.build import find_ffmpeg
        from kiasecut.ui import beat_preview
        self.assertEqual(beat_preview.tempo_filter(1.0), "atempo=1.000000")
        self.assertEqual(beat_preview.tempo_filter(4.0).count("atempo"), 2)
        self.assertEqual(beat_preview.tempo_filter(0.25).count("atempo"), 2)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "tone.wav")
            subprocess.run([find_ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", path], check=True)
            pv = beat_preview.Preview()
            pos, states = [], []
            pv.positionChanged.connect(pos.append)
            pv.playingChanged.connect(states.append)
            pv.set_source(path, 0, 1 * S, 2 * S, 1.0)                # the second second of the file
            pv.play(1.5 * S)
            end = time.monotonic() + 5
            while pv.pcm is None and time.monotonic() < end:
                APP.processEvents()
                time.sleep(0.01)
            self.assertAlmostEqual(len(pv.pcm) / 4 / 44100, 1.0, delta=0.05)       # 1 s of stereo 44.1 kHz
            end = time.monotonic() + 0.4
            while time.monotonic() < end:
                APP.processEvents()
            pv.pause()
            self.assertTrue(pos and all(1 * S <= t <= 2 * S for t in pos))
            self.assertGreater(max(pos), 1.5 * S)
            self.assertEqual(states, [True, False])
            pv.loop = False                                          # plays to the out point and stops there
            pv.play(1.9 * S)
            end = time.monotonic() + 1.5
            while pv.playing and time.monotonic() < end:
                APP.processEvents()
                time.sleep(0.01)
            self.assertFalse(pv.playing)
            self.assertEqual(pv.pos, 2 * S)


if __name__ == "__main__":
    unittest.main()
