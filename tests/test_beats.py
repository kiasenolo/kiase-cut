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


def old_grid(c, lo=None, hi=None, bars=False, beyond=False):
    """beat_grid as it was before change points existed (the reference for projects without them)."""
    import math
    beat = c.get("beat")
    if not beat or not beat.get("on") or not beat.get("bpm"):
        return []
    div = beat.get("div", 1) if beat.get("div", 1) in edit.BEAT_DIVS else 1
    k = project.speed(c)
    period = 60 * S / beat["bpm"] / div / k
    zero = c["start_us"] + (beat.get("offset_us", 0) - c.get("source_start_us", 0)) / k
    a, b = c["start_us"], edit.end(c)
    if beyond:
        a, b = a - period, b + period
    if lo is not None:
        a = max(a, lo)
    if hi is not None:
        b = min(b, hi)
    if b < a:
        return []
    k0, k1 = math.ceil((a - zero) / period - 1e-9), math.floor((b - zero) / period + 1e-9)
    meter = int(beat.get("meter", edit.BEAT_DEFAULT["meter"]) or 0) if bars else 0
    if div < 1:
        step = round(1 / div)
        return [(zero + i * period, 0 if meter and (i * step) % meter == 0 else 1) for i in range(k0, k1 + 1)]
    out = []
    for i in range(k0, k1 + 1):
        d = div // math.gcd(i % div, div)
        out.append((zero + i * period, 0 if meter and d == 1 and (i // div) % meter == 0 else d))
    return out


class ChangePoints(unittest.TestCase):
    def clip(self, **beat):
        p = proj()
        edit.set_beat(p, "a1", on=True, **beat)
        return p, edit.find(p, "a1")[1]

    def test_without_points_nothing_changes(self):
        for kw in (dict(bpm=120), dict(bpm=133.3, offset_us=0.37 * S, div=3, meter=7), dict(bpm=90, div=0.5, meter=4),
                   dict(bpm=200, div=6, meter=0)):
            for speed in (None, 1.5):
                p, c = self.clip(**kw)
                if speed:
                    c["speed"] = speed
                for args in (dict(), dict(bars=True), dict(beyond=True), dict(bars=True, beyond=True, lo=11 * S, hi=15 * S)):
                    self.assertEqual(edit.beat_grid(c, **args), old_grid(c, **args))
                c["beat"]["points"] = []                             # an empty list is none
                self.assertEqual(edit.beat_grid(c, bars=True), old_grid(c, bars=True))

    def test_old_file_round_trips_unchanged(self):
        import json
        p, c = self.clip(bpm=120)
        self.assertNotIn("points", c["beat"])
        text = project.dumps(p)
        self.assertNotIn("points", text)
        self.assertEqual(json.loads(project.dumps(project.link(json.loads(text)))), json.loads(text))

    def test_tempo_change_cuts_the_grid(self):
        # beats 0.5 s apart; at 4 s of the sound it goes to 60 BPM (1 s apart) and the beats begin again there
        p, c = self.clip(bpm=120, offset_us=0)
        edit.add_beat_point(p, "a1", 4 * S, bpm=60)
        src = [t for t, _ in edit.source_grid(c["beat"], 2 * S, 8 * S)]
        self.assertEqual(src, [2 * S, 2.5 * S, 3 * S, 3.5 * S, 4 * S, 5 * S, 6 * S, 7 * S, 8 * S])
        # on the timeline the clip shows source 2 s.. at 10 s
        self.assertEqual([round(t) for t in edit.beat_times(c)][:6], [10 * S, 10.5 * S, 11 * S, 11.5 * S, 12 * S, 13 * S])

    def test_beats_begin_again_at_the_point_not_on_the_old_phase(self):
        p, c = self.clip(bpm=120, offset_us=0)
        edit.add_beat_point(p, "a1", 3.2 * S, bpm=120)               # same tempo, but beat 0 moves to 3.2 s
        src = [t for t, _ in edit.source_grid(c["beat"], 3 * S, 4.2 * S)]
        self.assertEqual(src, [3 * S, 3.2 * S, 3.7 * S, 4.2 * S])

    def test_meter_change_restarts_the_bars(self):
        p, c = self.clip(bpm=120, offset_us=0, meter=4)
        edit.add_beat_point(p, "a1", 4 * S, meter=3)
        grid = edit.source_grid(c["beat"], 0, 8 * S, bars=True)
        firsts = [t / S for t, d in grid if d == 0]
        self.assertEqual(firsts, [0.0, 2.0, 4.0, 5.5, 7.0])          # bars of 4 beats, then of 3 from the point
        self.assertEqual(edit.beat_at(c["beat"], 5 * S), (120.0, 3))
        self.assertEqual(edit.beat_at(c["beat"], 1 * S), (120.0, 4))

    def test_both_at_once_and_several_points(self):
        p, c = self.clip(bpm=120, offset_us=0, meter=7)
        edit.add_beat_point(p, "a1", 6 * S, bpm=90, meter=4)
        edit.add_beat_point(p, "a1", 3 * S, bpm=60)
        self.assertEqual([x["time_us"] for x in c["beat"]["points"]], [3 * S, 6 * S])    # in time order
        self.assertEqual(edit.beat_at(c["beat"], 7 * S), (90.0, 4))
        self.assertEqual(edit.beat_at(c["beat"], 4 * S), (60.0, 7))                      # the meter goes on

    def test_snapping_follows_the_points(self):
        p, c = self.clip(bpm=120, offset_us=0)
        edit.add_beat_point(p, "a1", 4 * S, bpm=60)
        beats = edit.level_beats(p)
        self.assertIn(round(12 * S), beats)                          # source 4 s: the point itself
        self.assertIn(round(13 * S), beats)                          # a second later, not half a second
        self.assertNotIn(round(12.5 * S), beats)
        _, a = edit.find(p, "a1")
        # a clip edge near 12.45 s goes to 12 s or 13 s, never to the old 12.5 s line
        a["duration_us"] = round(2.45 * S)
        edit.snap_to_beats(p, ["a1"])
        self.assertIn(round(edit.end(a)), (12 * S, 13 * S))

    def test_point_edits(self):
        p, c = self.clip(bpm=120)
        i = edit.add_beat_point(p, "a1", 5 * S, bpm=90)
        self.assertEqual(i, 0)
        with self.assertRaises(edit.EditError):
            edit.add_beat_point(p, "a1", 5 * S + 10, bpm=80)         # too near the first
        with self.assertRaises(edit.EditError):
            edit.add_beat_point(p, "a1", 6 * S)                      # sets nothing
        edit.add_beat_point(p, "a1", 8 * S, meter=3)
        edit.move_beat_point(p, "a1", 0, 9 * S)                      # cannot go past its neighbour
        self.assertEqual([x["time_us"] for x in c["beat"]["points"]], [8 * S - 1000, 8 * S])
        edit.set_beat_point(p, "a1", 0, meter=5)                     # replaces what it sets
        self.assertEqual(c["beat"]["points"][0], {"time_us": 8 * S - 1000, "meter": 5})
        edit.remove_beat_point(p, "a1", 0)
        edit.remove_beat_point(p, "a1", 0)
        self.assertNotIn("points", c["beat"])
        edit.add_beat_point(p, "a1", 5 * S, bpm=90)
        edit.clear_beat(p, "a1")
        self.assertNotIn("beat", c)
        with self.assertRaises(edit.EditError):
            edit.set_beat(p, "a1", points=[])                        # only through the point edits

    def test_points_survive_save_and_load(self):
        import json
        p, c = self.clip(bpm=120)
        edit.add_beat_point(p, "a1", 5 * S, bpm=90, meter=3)
        q = project.link(json.loads(project.dumps(p)))
        self.assertEqual(edit.find(q, "a1")[1]["beat"]["points"], [{"time_us": 5 * S, "bpm": 90.0, "meter": 3}])
        self.assertEqual(edit.beat_times(edit.find(q, "a1")[1]), edit.beat_times(c))


    def test_wave_view_change_points(self):
        import numpy as np
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QKeyEvent, QMouseEvent
        from kiasecut.ui.beat_wave import WaveView
        p = proj()
        edit.set_beat(p, "a1", on=True, bpm=120, offset_us=0)
        edit.add_beat_point(p, "a1", 5 * S, bpm=90)
        edit.add_beat_point(p, "a1", 7 * S, meter=3)
        _, a = edit.find(p, "a1")

        class Peaks:
            def get(self, path, stream=0):
                return np.full((60_000, 2), [0.5, -0.5], np.float32), 0.0
        v = WaveView()
        v.resize(800, 300)
        v.set_clip(a, Peaks())
        self.assertFalse(v.grab().isNull())
        got = []
        v.pointAdd.connect(lambda t: got.append(("add", t)))
        v.pointMove.connect(lambda i, t: got.append(("move", i, t)))
        v.pointSelected.connect(lambda i: got.append(("select", i)))
        v.pointRemove.connect(lambda i: got.append(("remove", i)))

        def mouse(kind, x, mods=Qt.NoModifier):
            return QMouseEvent(kind, QPointF(x, 100), QPointF(x, 100), Qt.LeftButton, Qt.LeftButton, mods)
        x5 = v.x_of(5 * S)
        self.assertEqual(v.point_at(x5 + 3), 0)
        self.assertEqual(v.point_at(v.x_of(7 * S)), 1)
        self.assertIsNone(v.point_at(v.x_of(6 * S)))
        v.mouseDoubleClickEvent(mouse(QEvent.MouseButtonDblClick, x5 + 2))      # on a point: nothing new
        self.assertEqual(got, [])
        v.mouseDoubleClickEvent(mouse(QEvent.MouseButtonDblClick, v.x_of(6.3 * S)))
        kind, t = got.pop()
        self.assertEqual(kind, "add")
        self.assertAlmostEqual(t, 5 * S + 4 * S / 3, delta=2)                # snapped to the 90 BPM grid after 5 s (0.667 s apart)
        v.mousePressEvent(mouse(QEvent.MouseButtonPress, x5))                  # drag the first point, no snapping (Alt)
        self.assertEqual(v.sel_point, 0)
        self.assertEqual(got.pop(), ("select", 0))
        v.mouseMoveEvent(mouse(QEvent.MouseMove, v.x_of(5.3 * S), Qt.AltModifier))
        self.assertEqual(got[-1][:2], ("move", 0))
        self.assertAlmostEqual(got[-1][2], 5.3 * S, delta=S / 200)
        v.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease, v.x_of(5.3 * S)))
        v.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier))
        self.assertEqual(got[-1], ("remove", 0))


    def test_point_bar_edits_the_picked_point_in_place(self):
        import numpy as np
        from kiasecut.ui.beat_dialog import BeatDialog
        p = proj()
        edit.set_beat(p, "a1", on=True, bpm=120, offset_us=0)

        class Peaks:
            def get(self, path, stream=0):
                return np.full((60_000, 2), [0.5, -0.5], np.float32), 0.0
        dlg = BeatDialog("a1")
        dlg.show_clip(p, Peaks())

        def on_point(cid, op, args):                              # (what the main window does)
            {"add": edit.add_beat_point, "move": edit.move_beat_point, "set": edit.set_beat_point,
             "remove": edit.remove_beat_point}[op](p, cid, **args)
            self.assertTrue(dlg.show_clip(p))
        dlg.pointEdited.connect(on_point)
        self.assertFalse(dlg.pt_bpm.isEnabled())                  # nothing picked
        dlg.add_at(6 * S)
        pts = edit.find(p, "a1")[1]["beat"]["points"]
        self.assertEqual(pts, [{"time_us": 6 * S, "bpm": 120.0}])
        self.assertEqual(dlg.wave.sel_point, 0)                   # picked, its numbers in the bar
        self.assertTrue(dlg.pt_bpm.isEnabled() and dlg.pt_use_bpm.isChecked() and not dlg.pt_use_meter.isChecked())
        dlg._point_set(bpm=100)
        dlg.pt_use_meter.setChecked(True)                         # the bar's own check box
        dlg._point_set(meter=3)
        self.assertEqual(pts[0], {"time_us": 6 * S, "bpm": 100.0, "meter": 3})
        dlg.pt_use_bpm.setChecked(False)
        self.assertEqual(pts[0], {"time_us": 6 * S, "meter": 3})
        self.assertFalse(dlg.pt_use_meter.isEnabled())            # the last thing it sets cannot be switched off
        dlg.pt_delete.click()
        self.assertNotIn("points", edit.find(p, "a1")[1]["beat"])
        self.assertIsNone(dlg.wave.sel_point)
        self.assertFalse(dlg.pt_bpm.isEnabled())

    def test_wheel_zoom_glides_like_the_timelines(self):
        import numpy as np
        import time
        from kiasecut.ui import inertia
        from kiasecut.ui.beat_wave import WaveView
        p = proj()
        _, a = edit.find(p, "a1")

        class Peaks:
            def get(self, path, stream=0):
                return np.full((60_000, 2), [0.5, -0.5], np.float32), 0.0
        v = WaveView()
        v.resize(800, 300)
        v.set_clip(a, Peaks())
        span = v.t1 - v.t0
        v._wheel_queue, v._wheel_x, v._wheel_last = {"zoom": 2.0}, 400.0, time.monotonic()
        v._wheel_timer.start()
        v._wheel_step()
        first = v.t1 - v.t0
        self.assertTrue(span > first > span / 1.25 ** 2)          # a part of the way, not all at once
        end = time.monotonic() + 3
        while v._wheel_queue and time.monotonic() < end:
            time.sleep(0.01)
            v._wheel_step()
        self.assertAlmostEqual(v.t1 - v.t0, span / 1.25 ** 2, delta=span * 1e-3)    # the whole of it in the end
        self.assertFalse(v._wheel_timer.isActive())


    def test_follow_scrolls_continuously_and_a_drag_turns_it_off(self):
        import numpy as np
        from kiasecut.ui.beat_dialog import BeatDialog
        from kiasecut.ui.beat_wave import WaveView
        p = proj()
        _, a = edit.find(p, "a1")

        class Peaks:
            def get(self, path, stream=0):
                return np.full((60_000, 2), [0.5, -0.5], np.float32), 0.0
        v = WaveView()
        v.resize(800, 300)
        v.set_clip(a, Peaks())
        span = v.t1 - v.t0
        v.set_playhead(v.t0 + 0.2 * span, True)                      # before the pin: the view stays
        self.assertAlmostEqual(v.t1 - v.t0, span, delta=1)
        t0 = v.t0
        v.set_playhead(t0 + 0.2 * span, True)
        self.assertEqual(v.t0, t0)
        for f in (0.35, 0.5, 0.9, 1.3):                              # past it (and outside the view): pinned at 30 %
            v.set_playhead(v.t0 + f * span, True)
            self.assertAlmostEqual((v.playhead - v.t0) / span, 0.3, places=6)
        before = v.t0
        v.set_playhead(v.playhead + 0.1 * span, False)               # not following: the view stays
        self.assertEqual(v.t0, before)
        dlg = BeatDialog("a1")
        dlg.show_clip(p, Peaks())
        self.assertTrue(dlg.follow.isCheckable() and dlg.follow.isChecked())
        dlg.wave.userMoved.emit()                                    # not playing: stays on
        self.assertTrue(dlg.follow.isChecked())
        dlg.preview.playing = True
        dlg.wave.userMoved.emit()                                    # playing: a drag turns it off
        self.assertFalse(dlg.follow.isChecked())


    def test_timeline_follow_is_continuous_and_can_be_off(self):
        tl = Timeline()
        tl.resize(1200, 300)
        tl.set_project(proj())
        tl.px_per_s, tl.scroll_s = 100.0, 0.0
        pin = tl.header_w + (tl.width() - tl.header_w) * tl.FOLLOW_AT
        tl.set_position(round(2 * tl.fps), follow=True, playing=True)       # before the pin: the view stays
        self.assertEqual(tl.scroll_s, 0.0)
        for sec in (6.0, 7.0, 9.5):                                          # past it: held there, the view moves
            tl.set_position(round(sec * tl.fps), follow=True, playing=True)
            self.assertAlmostEqual(tl._x(sec), pin, delta=1)
        was = tl.scroll_s
        tl.follow_play = False                                               # off: the view stays while playing
        tl.set_position(round(20 * tl.fps), follow=True, playing=True)
        self.assertEqual(tl.scroll_s, was)
        got = []
        tl.viewMovedByHand.connect(lambda: got.append(1))
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        tl.wheelEvent(QWheelEvent(QPointF(300, 100), QPointF(300, 100), tl.rect().topLeft(), __import__("PySide6.QtCore").QtCore.QPoint(120, 0),
                                  Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
        self.assertEqual(got, [1])                                           # a sideways scroll is by hand


if __name__ == "__main__":
    unittest.main()
