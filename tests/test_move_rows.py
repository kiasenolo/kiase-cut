import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kiasecut import edit  # noqa: E402

US = 1_000_000


def clip(cid, start, dur=US, kind="video"):
    return {"id": cid, "type": kind, "start_us": start, "duration_us": dur}


def project():
    # tracks list: pictures bottom -> top, then sound (the timeline shows pictures reversed)
    return {"tracks": [
        {"id": "v1", "kind": "video", "clips": [clip("a", 0), clip("c", 5 * US)]},
        {"id": "v2", "kind": "video", "clips": [clip("b", 2 * US)]},
        {"id": "v3", "kind": "video", "clips": []},
        {"id": "a1", "kind": "audio", "clips": [clip("s", 0, kind="audio")]},
        {"id": "a2", "kind": "audio", "clips": []},
    ]}


def at(p, cid):
    return next(t["id"] for t in p["tracks"] for c in t["clips"] if c["id"] == cid)


class MoveRowsTest(unittest.TestCase):
    def test_group_up_keeps_row_distance(self):
        p = project()
        edit.move_many(p, ["a", "b"], 0, -1)                 # one row up on screen
        self.assertEqual((at(p, "a"), at(p, "b")), ("v2", "v3"))

    def test_group_down_and_time(self):
        p = project()
        edit.move_many(p, ["a", "b"], 0, -1)
        edit.move_many(p, ["a", "b"], US, 1)
        self.assertEqual((at(p, "a"), at(p, "b")), ("v1", "v2"))
        self.assertEqual(edit.find(p, "a")[1]["start_us"], US)

    def test_edges_and_nothing_changes_on_refusal(self):
        p = project()
        with self.assertRaises(edit.EditError):
            edit.move_many(p, ["a", "b"], US, 1)              # a is already on the bottom row
        self.assertEqual((at(p, "a"), edit.find(p, "a")[1]["start_us"]), ("v1", 0))
        with self.assertRaises(edit.EditError):
            edit.move_many(p, ["b"], 0, -2)                   # no track above v3

    def test_overlap_with_a_clip_that_stays(self):
        p = project()
        p["tracks"][1]["clips"].append(clip("x", 5 * US))
        with self.assertRaises(edit.EditError):
            edit.move_many(p, ["c"], 0, -1)                   # lands on x
        self.assertEqual(at(p, "c"), "v1")

    def test_sound_stays_with_sound(self):
        p = project()
        edit.move_many(p, ["s"], 0, 1)
        self.assertEqual(at(p, "s"), "a2")
        edit.move_many(p, ["s", "b"], 0, 0)
        with self.assertRaises(edit.EditError):
            edit.move_many(p, ["s"], 0, 1)

    def test_default_is_same_row(self):
        p = project()
        edit.move_many(p, ["a", "b"], US)
        self.assertEqual((at(p, "a"), at(p, "b")), ("v1", "v2"))


if __name__ == "__main__":
    unittest.main()
