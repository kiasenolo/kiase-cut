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
