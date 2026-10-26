"""The static compound editor's layers: listed top first, restacked one per track, each
keeping its own track's switches; sound stays below."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kiasecut import edit  # noqa: E402
from test_edit import S, clip, proj  # noqa: E402


class LayerTests(unittest.TestCase):
    def test_order(self):
        p = proj()                                             # t0: c1, c2; t1 empty; audio
        p["tracks"][1]["clips"].append(clip("c4", 0, S))
        p["tracks"][1]["hidden"] = True
        tracks = p["tracks"]
        self.assertEqual([c["id"] for c in edit.layers(p)], ["c4", "c1", "c2"])
        edit.set_layer_order(p, ["c2", "c4", "c1"])
        self.assertIs(p["tracks"], tracks)                      # (the same list: the timeline's)
        self.assertEqual([c["id"] for c in edit.layers(p)], ["c2", "c4", "c1"])
        self.assertTrue(all(len(t["clips"]) == 1 for t in p["tracks"]))
        self.assertTrue(next(t for t in p["tracks"] if t["clips"][0]["id"] == "c4").get("hidden"))
        self.assertEqual(p["tracks"][-1]["kind"], "audio")
        self.assertEqual(len({t["id"] for t in p["tracks"]}), len(p["tracks"]))
        with self.assertRaises(edit.EditError):
            edit.set_layer_order(p, ["c2", "c4"])               # every layer, or none


if __name__ == "__main__":
    unittest.main()
