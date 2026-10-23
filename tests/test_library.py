import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tesetoa import edit, library, project  # noqa: E402

S = 1_000_000


def proj():
    p = project.new()
    p["tracks"] = [{"id": "t0", "kind": "video", "name": "v", "clips": []},
                   {"id": "t1", "kind": "audio", "name": "a", "clips": []}]
    L = library.lib(p)
    L["items"] += [
        {"id": "mimg", "name": "a.png", "path": "a.png", "kind": "image", "width": 3840, "height": 2160, "folder": None},
        {"id": "mvid", "name": "b.mp4", "path": "b.mp4", "kind": "video", "width": 1920, "height": 1080,
         "duration_us": 8 * S, "folder": None},
        {"id": "maud", "name": "c.mp3", "path": "c.mp3", "kind": "audio", "duration_us": 30 * S, "folder": None},
    ]
    return p


class LibraryTests(unittest.TestCase):
    def test_folders(self):
        p = proj()
        a = library.add_folder(p, "素材")
        b = library.add_folder(p, "子資料夾", a["id"])
        library.move(p, "mimg", b["id"])
        self.assertEqual(library.item(p, "mimg")["folder"], b["id"])
        with self.assertRaises(edit.EditError):
            library.move(p, a["id"], b["id"])             # into its own child
        library.delete(p, b["id"])                          # contents move up
        self.assertEqual(library.item(p, "mimg")["folder"], a["id"])
        library.rename(p, a["id"], "圖片")
        self.assertEqual(library.folder(p, a["id"])["name"], "圖片")

    def test_place_on_matching_track_and_new_tracks(self):
        p = proj()
        c = library.place(p, p, "mvid", "t0", 2 * S)
        self.assertIn(c, p["tracks"][0]["clips"])
        self.assertEqual((c["start_us"], c["duration_us"]), (2 * S, 8 * S))
        c2 = library.place(p, p, "mimg", "t0", 3 * S)      # overlaps: nearest gap is after
        self.assertEqual(c2["start_us"], 10 * S)
        a = library.place(p, p, "maud", "t0", 0)             # audio onto a picture track
        self.assertTrue(any(a in t["clips"] for t in p["tracks"] if t["kind"] == "audio"))
        n = len(p["tracks"])
        library.place(p, p, "mimg", None, 0)                 # no track: a new picture track
        self.assertEqual(len(p["tracks"]), n + 1)
        self.assertNotEqual([t["kind"] for t in p["tracks"]][-1], "video")   # audio stays last


if __name__ == "__main__":
    unittest.main()
