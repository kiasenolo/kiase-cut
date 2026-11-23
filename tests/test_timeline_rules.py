"""The timeline rules of 2026-11-24: Shift+Q / W ripple, picture / sound tracks only, a drop on a taken spot opens a new
track, clip edges on the project's frames, beat snapping with a BPM timebase."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from kiasecut import edit  # noqa: E402
from test_edit import S, proj  # noqa: E402


def starts(p, tid):
    return [(c["id"], c["start_us"], c["duration_us"]) for c in edit.track_by_id(p, tid)["clips"]]


class RippleTrimTests(unittest.TestCase):
    def test_q_and_w_leave_the_gap(self):
        p = proj()
        edit.trim_to(p, ["c1"], S // 2, "start")
        self.assertEqual(starts(p, "t0"), [("c1", S // 2, 3 * S // 2), ("c2", 5 * S, 2 * S)])

    def test_shift_q_closes_up_from_the_clip_start(self):
        p = proj()
        edit.trim_to(p, ["c1"], S // 2, "start", ripple=True)
        self.assertEqual(starts(p, "t0"), [("c1", 0, 3 * S // 2), ("c2", 9 * S // 2, 2 * S)])

    def test_shift_w_pulls_the_later_clips_in(self):
        p = proj()
        edit.trim_to(p, ["c1"], S, "end", ripple=True)
        self.assertEqual(starts(p, "t0"), [("c1", 0, S), ("c2", 4 * S, 2 * S)])
        self.assertEqual(starts(p, "t2")[0][1], 2 * S)                    # (another track is left alone)


class TakenSpotTests(unittest.TestCase):
    def test_a_clip_dropped_on_another_opens_a_track_above(self):
        p = proj()                                                        # t0: c1 0-2 s, c2 5-7 s
        edit.move_beside(p, "c2", S, "t0")
        holder = next(t for t in p["tracks"] if any(c["id"] == "c2" for c in t["clips"]))
        self.assertEqual(p["tracks"].index(holder), 1)                    # (right above t0)
        self.assertEqual(edit.find(p, "c2")[1]["start_us"], S)            # where it was dropped

    def test_sound_opens_a_track_below(self):
        p = proj()
        p["tracks"][2]["clips"].append({"id": "c4", "type": "audio", "name": "b", "start_us": 7 * S, "duration_us": S,
                                        "source_start_us": 0, "media": {"path": "b.mp3", "duration_us": 9 * S}})
        edit.move_beside(p, "c4", 3 * S, "t2")
        self.assertEqual([t["kind"] for t in p["tracks"]], ["video", "video", "audio", "audio"])
        self.assertEqual(p["tracks"][3]["clips"][0]["id"], "c4")

    def test_several_moved_onto_taken_spots_get_new_tracks(self):
        p = proj()
        edit.move_many(p, ["c2"], -4 * S, 0)                              # c2 onto c1's time
        holder = next(t for t in p["tracks"] if any(c["id"] == "c2" for c in t["clips"]))
        self.assertNotEqual(holder["id"], "t0")
        self.assertEqual(edit.find(p, "c2")[1]["start_us"], S)


class ProjectFrameTests(unittest.TestCase):
    def test_dragged_edges_land_on_the_projects_frames(self):
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtWidgets import QApplication
        from kiasecut.ui.timeline import HEADER_W, Timeline
        _app = QApplication.instance() or QApplication([])
        p = proj()
        tl = Timeline()
        tl.resize(1200, 300)
        tl.set_project(p)
        tl.fps, tl.clip_fps = 120.0, 30.0                                  # a finer 時間線精度 than the project
        tl.snapping = False
        tl.px_per_s, tl.scroll_s = 50.0, 0.0
        moved = []
        tl.moveRequested.connect(lambda cid, start, track: moved.append(start))
        c = edit.find(p, "c1")[1]
        tl.select(c)
        row = next(i for i, t in enumerate(tl.rows) if c in t["clips"])
        tl._grab_begin(c, row)
        tl.drag["x0"] = HEADER_W + 100
        tl.drag.pop("prow0", None)
        e = type("E", (), {"modifiers": lambda s: Qt.NoModifier})()
        tl._mouse_move(e, QPointF(HEADER_W + 100 + 51.3, tl.tops[row] + 5))   # 1.026 s: between frames
        tl._grab_end(True)
        frame = S / 30
        self.assertAlmostEqual(moved[-1] / frame, round(moved[-1] / frame), places=3)
        self.assertAlmostEqual(moved[-1], S, delta=frame)


class BeatGridTests(unittest.TestCase):
    def test_a_bpm_timebase_snaps_to_its_lines(self):
        from PySide6.QtWidgets import QApplication
        from kiasecut.ui.timeline import Timeline, timebase_of
        _app = QApplication.instance() or QApplication([])
        tl = Timeline()
        tl.resize(1200, 300)
        tl.set_project(proj())
        tl.px_per_s, tl.fps = 50.0, 60.0
        self.assertEqual(tl._snap(1.07 * S, None, playhead=False), 1.07 * S)          # (seconds: nothing there)
        tl.timebase = timebase_of({"kind": "bpm", "bpm": 120, "div": 1, "meter": 4})  # a beat every 0.5 s = 25 px
        self.assertEqual(tl._snap(1.07 * S, None, playhead=False), S)                 # 3.5 px from beat 3
        self.assertEqual(tl._snap(1.25 * S, None, playhead=False), 1.25 * S)          # 12.5 px: too far
        tl.px_per_s = 5.0                                                              # out: lines every 2 bars (4 s)
        self.assertEqual(tl._grid_line(7.0 * S), 8 * S)
        tl.snapping = False
        self.assertEqual(tl._snap(1.07 * S, None, playhead=False), 1.07 * S)


class PictureTrackTests(unittest.TestCase):
    def test_text_tracks_load_as_picture_tracks(self):
        from kiasecut import project
        p = proj()
        p["tracks"].insert(1, {"id": "tx", "kind": "text", "name": "字幕", "clips": []})
        p["compounds"] = {"k": {"name": "k", "width": 1920, "height": 1080, "duration_us": S,
                                "tracks": [{"id": "ty", "kind": "text", "name": "t", "clips": []}]}}
        project.normalize(p)
        self.assertEqual(edit.track_by_id(p, "tx")["kind"], "video")
        self.assertEqual(edit.track_by_id(p, "tx")["name"], "字幕")
        self.assertEqual(p["compounds"]["k"]["tracks"][0]["kind"], "video")

    def test_new_text_goes_on_the_topmost_picture_track_with_room(self):
        p = proj()                                                        # t0 (c1 0-2 s, c2 5-7 s), t1 empty, t2 sound
        c = edit.add_text(p, 0)
        self.assertIn(c, edit.track_by_id(p, "t1")["clips"])
        d = edit.add_text(p, 0)                                           # no room on any: a new top picture track
        holder = next(t for t in p["tracks"] if d in t["clips"])
        self.assertEqual(holder["kind"], "video")
        self.assertEqual(p["tracks"].index(holder), 2)                    # (above t1, below the sound)


if __name__ == "__main__":
    unittest.main()
