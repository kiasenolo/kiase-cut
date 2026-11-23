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


if __name__ == "__main__":
    unittest.main()
