"""Version 6 (container merge): timelines are compounds with fit; old projects are converted when they load, one way."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from kiasecut import edit, project  # noqa: E402

S = 1_000_000


def old_project():
    """A version 5 project: two timelines, the second shown inside the first by a nested timeline clip."""
    pic = {"id": "c1", "type": "image", "name": "c1", "start_us": 0, "duration_us": 2 * S, "source_start_us": 0,
           "media": {"path": "/x/a.png", "width": 64, "height": 36}, "transform": {"x": 0.0, "y": 0.0}}
    nest = {"id": "n1", "type": "compound", "name": "B", "start_us": 2 * S, "duration_us": S, "source_start_us": 0,
            "timeline_id": "tl2", "transform": {"x": 0.0, "y": 0.0}}
    return {"format": "kiasecut", "version": 5, "width": 1280, "height": 720, "fps": 30.0, "compounds": {},
            "active_timeline": "tl1",
            "timelines": [{"id": "tl1", "name": "A", "tracks": [{"id": "t0", "kind": "video", "name": "v", "clips": [pic, nest]}],
                           "markers": [{"id": "m1", "t_us": S, "name": "here"}]},
                          {"id": "tl2", "name": "B", "tracks": [{"id": "t0", "kind": "text", "name": "字", "clips": []}]}]}


class LoadOldTests(unittest.TestCase):
    def load(self, data):
        path = os.path.join(tempfile.mkdtemp(), "old.kiasecut.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return project.load(path)

    def test_timelines_become_fit_compounds(self):
        p = self.load(old_project())
        self.assertNotIn("timelines", p)
        self.assertEqual(sorted(p["compounds"]), ["tl1", "tl2"])
        a, b = p["compounds"]["tl1"], p["compounds"]["tl2"]
        self.assertTrue(a["fit"] and b["fit"])
        self.assertEqual((a["name"], a["width"], a["height"]), ("A", 1280, 720))
        self.assertIs(p["tracks"], a["tracks"])
        self.assertEqual(a["markers"][0]["name"], "here")
        nest = a["tracks"][0]["clips"][1]
        self.assertEqual(nest["compound_id"], "tl2")
        self.assertNotIn("timeline_id", nest)
        self.assertIs(nest["compound"], b)
        self.assertEqual(b["tracks"][0]["kind"], "video")                 # (文字 tracks were picture tracks)
        self.assertEqual(project.compound_uses(p)["tl2"][0][0], "tl1")

    def test_saved_as_version_6_and_back(self):
        p = self.load(old_project())
        path = os.path.join(tempfile.mkdtemp(), "new.kiasecut.json")
        project.save(p, path)
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        self.assertEqual(raw.get("version", project.VERSION), project.VERSION)
        self.assertNotIn("timelines", raw)
        self.assertNotIn("tracks", raw)
        q = project.load(path)
        self.assertEqual([c["id"] for c in q["tracks"][0]["clips"]], ["c1", "n1"])

    def test_new_project_and_timelines(self):
        p = project.new()
        self.assertEqual([k for k, _ in project.timelines(p)], ["tl1"])
        tl = edit.add_timeline(p)
        self.assertEqual(p["active_timeline"], tl["id"])
        self.assertTrue(p["compounds"][tl["id"]]["fit"])
        edit.open_timeline(p, "tl1")
        kid = edit.add_compound(p)
        with self.assertRaises(edit.EditError):
            edit.open_timeline(p, kid)                                    # (not a fit one: it opens in a tab of its own)
        edit.delete_timeline(p, tl["id"])
        self.assertEqual([k for k, _ in project.timelines(p)], ["tl1"])


if __name__ == "__main__":
    unittest.main()
