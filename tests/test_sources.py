"""SVG pictures, replacing a clip's source, and static clips (靜態片段)."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication  # noqa: E402

from kiasecut import audiomix, curves, edit, library, project, render, renderexport, svgimage  # noqa: E402
from test_edit import S, clip, proj  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])
SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 200 100">
<rect width="200" height="100" fill="#ff0000"/><circle cx="150" cy="50" r="40" fill="#0000ff"/></svg>"""


class SvgTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.path = os.path.join(cls.dir, "pic.svg")
        with open(cls.path, "w", encoding="utf-8") as fh:
            fh.write(SVG)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_probe_and_files(self):
        self.assertEqual(library.probe(self.path), {"kind": "image", "width": 200, "height": 100})
        self.assertEqual(library.media_files([self.dir]), [self.path])
        bad = os.path.join(self.dir, "bad.svg")
        with open(bad, "w") as fh:
            fh.write("not svg")
        try:
            with self.assertRaises(edit.EditError):
                library.probe(bad)
        finally:
            os.remove(bad)

    def test_sharp_at_any_size(self):
        big = svgimage.raster(self.path, 2000)
        self.assertEqual((big.width(), big.height()), (2000, 1000))
        self.assertEqual(big.pixelColor(1500, 500).name(), "#0000ff")
        self.assertEqual(big.pixelColor(100, 500).name(), "#ff0000")
        r = render.Renderer()
        self.assertGreaterEqual(r.image(self.path, 900, 450).width(), 900)     # drawn at the size shown

    def test_in_a_frame(self):
        c = clip("s", 0, 2 * S, media={"path": self.path, "width": 200, "height": 100})
        view = {"width": 160, "height": 90, "fps": 30, "duration_us": 2 * S,
                "tracks": [{"id": "t", "kind": "video", "name": "v", "clips": [c]}]}
        img = render.Renderer().render(view, 0, 160, 90)
        self.assertEqual(img.pixelColor(20, 45).name(), "#ff0000")
        self.assertEqual(img.pixelColor(140, 45).name(), "#0000ff")


class ReplaceTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()

    def test_picture_by_video_keeps_look(self):
        c = edit.find(self.p, "c1")[1]
        c["transform"]["scale"] = 2.0
        edit.toggle_key(self.p, "c1", "transform", "x", S // 2)
        edit.set_mask(self.p, "c1", "circle")
        it = {"kind": "video", "path": "v.mp4", "name": "v.mp4", "width": 1280, "height": 720,
              "duration_us": S}                                      # shorter than the 2 s clip
        edit.replace_media(self.p, "c1", it)
        self.assertEqual(c["type"], "video")
        self.assertEqual(c["media"]["path"], "v.mp4")
        self.assertEqual((c["start_us"], c["duration_us"], c["source_start_us"]), (0, S, 0))
        self.assertEqual(c["transform"]["scale"], 2.0)
        self.assertIn("keys", c["transform"]["x"])
        self.assertEqual(c["mask"]["kind"], "circle")
        self.assertEqual(c["volume"], 1.0)
        self.assertEqual(c["name"], "v.mp4")

    def test_video_by_picture_and_wrong_kinds(self):
        edit.replace_media(self.p, "c1", {"kind": "video", "path": "v.mp4", "name": "v", "width": 10, "height": 10,
                                          "duration_us": 10 * S})
        c = edit.find(self.p, "c1")[1]
        self.assertEqual(c["duration_us"], 2 * S)                    # a long enough source keeps the length
        edit.replace_media(self.p, "c1", {"kind": "image", "path": "i.png", "name": "i", "width": 4, "height": 3})
        self.assertEqual(c["type"], "image")
        self.assertNotIn("volume", c)
        with self.assertRaises(edit.EditError):
            edit.replace_media(self.p, "c1", {"kind": "audio", "path": "a.mp3", "name": "a", "duration_us": S})
        with self.assertRaises(edit.EditError):
            edit.replace_media(self.p, "c3", {"kind": "image", "path": "i.png", "name": "i", "width": 4, "height": 3})
        edit.replace_media(self.p, "c3", {"kind": "audio", "path": "b.mp3", "name": "b", "duration_us": 20 * S})
        a = edit.find(self.p, "c3")[1]
        self.assertEqual((a["media"]["path"], a["source_start_us"], a["duration_us"]), ("b.mp3", S, 4 * S))
        text = edit.add_text(self.p, 0)
        with self.assertRaises(edit.EditError):
            edit.replace_media(self.p, text["id"], {"kind": "image", "path": "i.png", "name": "i", "width": 4,
                                                    "height": 3})

    def test_by_compound(self):
        st = edit.make_compound(self.p, self.p, ["c2"], 5 * S + S // 2, static=True)
        kid = st["compound_id"]
        c = edit.replace_with_compound(self.p, self.p, "c1", kid)
        self.assertEqual((c["type"], c["compound_id"], c["duration_us"]), ("compound", kid, 2 * S))
        self.assertNotIn("media", c)
        with self.assertRaises(edit.EditError):                      # a compound cannot show itself
            edit.replace_with_compound(self.p, self.p["compounds"][kid], st["compound"]["tracks"][0]["clips"][0]["id"],
                                       kid)


class StaticTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()

    def test_make_static_from_selection(self):
        st = edit.make_compound(self.p, self.p, ["c1", "c2"], int(1.5 * S), static=True)
        comp = st["compound"]
        self.assertTrue(project.is_static(st))
        self.assertEqual((st["start_us"], st["duration_us"]), (0, 7 * S))
        self.assertNotIn("still_us", comp)
        inner = [c["id"] for t in comp["tracks"] for c in t["clips"]]
        self.assertEqual(sorted(inner), ["c1", "c2"])
        # the playhead moment (1.5 s) is its first frame: c1 starts there, c2 follows
        c1 = edit.find(comp, "c1")[1]
        self.assertEqual((c1["start_us"], c1["duration_us"], c1["source_start_us"]), (0, S // 2, int(1.5 * S)))
        self.assertEqual(edit.find(comp, "c2")[1]["start_us"], int(3.5 * S))
        with self.assertRaises(edit.EditError):                      # gone from the timeline
            edit.find(self.p, "c1")
        with self.assertRaises(edit.EditError):                      # sound is not a picture
            edit.make_compound(self.p, self.p, ["c3"], 0, static=True)
        # like a picture: any length, no sound
        edit.trim_end(self.p, st["id"], 30 * S)
        self.assertEqual(st["duration_us"], 30 * S)
        edit.trim_start(self.p, st["id"], -5 * S)
        self.assertEqual(st["start_us"], 0)
        self.assertIsNone(edit.source_length(st))
        self.assertTrue(renderexport.needs_renderer(self.p))
        back = project.link(project.normalize(__import__("json").loads(project.dumps(self.p))))
        self.assertTrue(project.is_static(next(c for c in project.all_clips(back) if c["id"] == st["id"])))

    def test_static_shows_one_moment(self):
        d = tempfile.mkdtemp()
        try:
            from PySide6.QtGui import QColor, QImage
            paths = []
            for name, col in (("red", "#ff0000"), ("green", "#00ff00")):
                im = QImage(16, 9, QImage.Format_RGB32)
                im.fill(QColor(col))
                paths.append(os.path.join(d, name + ".png"))
                im.save(paths[-1])
            m = lambda i: {"path": paths[i], "width": 16, "height": 9}
            p = project.new(160, 90, 30.0)
            p["tracks"].append({"id": "t0", "kind": "video", "name": "v",
                                "clips": [clip("r", 0, S, media=m(0)), clip("g", S, S, media=m(1))]})
            project.link(p)
            st = edit.make_compound(p, p, ["r", "g"], int(1.5 * S), static=True)   # the green moment
            edit.trim_end(p, st["id"], 10 * S)
            r = render.Renderer()
            for t in (0, 5 * S, 9 * S):
                img = r.render(p, round(t * 30 / S), 160, 90)
                self.assertEqual(img.pixelColor(80, 45).name(), "#00ff00", t)
            self.assertEqual(len(r.stills), 1)                       # drawn once
            self.assertEqual(audiomix.sources(p["tracks"]), [])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_freeze_at_keeps_the_look(self):
        a = clip("a", 0, 3 * S)
        a["transform"]["x"] = {"keys": [[0, 0.0, 0, 0, 0, 0], [2 * S, 1.0, 0, 0, 0, 0]]}
        tracks = [{"id": "t", "kind": "video", "name": "v",
                   "clips": [clip("gone", 0, S), a, clip("later", 4 * S, S)]}]
        edit.freeze_at(tracks, S)
        cl = tracks[0]["clips"]
        self.assertEqual([c["id"] for c in cl], ["a", "later"])        # what ended by then can never show
        self.assertEqual((cl[0]["start_us"], cl[0]["duration_us"], cl[0]["source_start_us"]), (0, 2 * S, S))
        self.assertAlmostEqual(curves.value(cl[0]["transform"]["x"], 0), 0.5)   # as it looked at 1 s
        self.assertEqual(cl[1]["start_us"], 3 * S)

    def test_old_still_moment_becomes_the_first_frame(self):
        p = proj()
        st = edit.make_compound(p, p, ["c1"], 0, static=True)
        data = __import__("json").loads(project.dumps(p))
        comp = data["compounds"][st["compound_id"]]
        comp["still_us"] = S // 2                                          # saved by an older version
        back = project.normalize(data)
        comp = back["compounds"][st["compound_id"]]
        self.assertNotIn("still_us", comp)
        c1 = comp["tracks"][0]["clips"][0]
        self.assertEqual((c1["start_us"], c1["source_start_us"]), (0, S // 2))

    def test_new_empty_static(self):
        st = edit.new_static(self.p, self.p, 3 * S, "t1")
        self.assertTrue(project.is_static(st))
        self.assertEqual(st["duration_us"], edit.STILL_DEFAULT_US)
        self.assertEqual(edit.find(self.p, st["id"])[0]["id"], "t1")

    def test_plain_compound(self):
        c = edit.make_compound(self.p, self.p, ["c1"], None)
        self.assertFalse(project.is_static(c))
        self.assertEqual(edit.source_length(c), 2 * S)


if __name__ == "__main__":
    unittest.main()
