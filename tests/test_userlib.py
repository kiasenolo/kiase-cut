import json
import shutil
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from kiasecut import edit, fx, library, project, userlib  # noqa: E402


def png(path, size=(32, 18)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", size, "red").save(path)
    return path.replace("\\", "/")


class UserLibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = library.norm(os.path.realpath(self.tmp.name) + "/Library")
        userlib.ensure_layout(self.root)
        self.old = project.LIBRARY_ROOT
        project.LIBRARY_ROOT = self.root
        self.addCleanup(lambda: setattr(project, "LIBRARY_ROOT", self.old))

    def test_layout_and_categories(self):
        for key, _ in userlib.CATEGORIES:
            self.assertTrue(os.path.isdir(userlib.category_dir(self.root, key)))
        self.assertTrue(os.path.exists(self.root + "/filters/FORMAT.md"))
        self.assertTrue(os.path.exists(self.root + "/filters/Example.glsl.txt"))
        self.assertFalse(os.path.exists(self.root + "/filters/Example.glsl"))
        self.assertEqual(userlib.category_of(self.root + "/images/a/b.png", self.root), "images")
        self.assertEqual(userlib.category_of(self.root + "/x.png", self.root), "")
        self.assertIsNone(userlib.category_of("/elsewhere/x.png", self.root))
        self.assertEqual(userlib.category_for("a.GLSL"), "filters")
        self.assertEqual(userlib.category_for("a.json"), None)
        self.assertEqual(userlib.category_for("a.json", prefer="textstyles"), "textstyles")

    def test_old_example_filter_removed_only_when_untouched(self):
        old = self.root + "/filters/Example.glsl"
        shutil.copyfile(fx.TEMPLATE_PATH, old)
        userlib.ensure_layout(self.root)
        self.assertFalse(os.path.exists(old))
        with open(old, "w", encoding="utf-8") as fh:
            fh.write("// @filter Mine\n")
        userlib.ensure_layout(self.root)
        self.assertTrue(os.path.exists(old))

    def test_scan_finds_hand_dropped_files(self):
        png(self.root + "/images/Logos/a.png")
        ul = userlib.UserLibrary(self.root)
        res = ul.scan("images")
        self.assertTrue(ul.apply("images", res))
        self.assertEqual([i["name"] for i in ul.lib("images")["items"]], ["a.png"])
        self.assertEqual([f["name"] for f in ul.lib("images")["folders"]], ["Logos"])
        self.assertFalse(ul.apply("images", ul.scan("images")))        # nothing new

    def test_library_files_are_stored_relative_and_not_collected(self):
        p = png(self.root + "/images/a.png")
        proj = project.new(640, 360, 30)
        clip = library.clip_from({"id": "m1", "name": "a", "path": p, "kind": "image", "width": 32, "height": 18}, 0)
        project.timeline(proj)["tracks"].append({"id": "t0", "kind": "video", "name": "v", "clips": [clip]})
        pdir = os.path.join(self.tmp.name, "proj")
        os.makedirs(pdir)
        project.save(proj, os.path.join(pdir, "p.kiasecut.json"))
        with open(os.path.join(pdir, "p.kiasecut.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        stored = data["timelines"][0]["tracks"][-1]["clips"][0]["media"]["path"]
        self.assertEqual(stored, "@library/images/a.png")
        self.assertTrue(library.in_user_library(p))
        self.assertFalse(library.in_user_library("/elsewhere/a.png"))
        self.assertEqual(library.external_media(proj, pdir), {})

    def test_retarget_follows_filter_files(self):
        proj = project.new(640, 360, 30)
        f = self.root + "/filters/mine.glsl"
        clip = {"id": "c1", "type": "filter", "start_us": 0, "duration_us": 1000000,
                "effects": [{"id": "e1", "filter": f, "params": {}}]}
        project.timeline(proj)["tracks"].append({"id": "t0", "kind": "video", "name": "v", "clips": [clip]})
        library.retarget(proj, f, self.root + "/filters/renamed.glsl")
        self.assertEqual(clip["effects"][0]["filter"], self.root + "/filters/renamed.glsl")

    def test_text_style_roundtrip(self):
        proj = project.new(640, 360, 30)
        tr = {"id": "t0", "kind": "text", "name": "t", "clips": []}
        proj["tracks"].append(tr)
        c = edit.add_text(proj, 0)
        edit.set_text(proj, c["id"], size=12.0, font_path="/x/y.ttf")
        path = userlib.save_style(self.root + "/textstyles", "Big", c)
        style = userlib.load_style(path)
        other = edit.add_text(proj, 5_000_000)
        edit.apply_text_style(proj, other["id"], style)
        self.assertEqual(other["text"]["size"], 12.0)
        self.assertEqual(other["text"]["font_path"], "/x/y.ttf")
        self.assertEqual(other["text"]["content"], "輸入文字")                # the words stay


class FilterFileTest(unittest.TestCase):
    def test_header_parsing(self):
        d = fx.parse("// @filter Demo\n// @param amount float 0.5 0 1 \"強度\"\n// @param on bool true\n"
                     "// @param tint color #ff8800\n// @passes 2\nvec4 effect(vec2 uv){return src(uv);}\n", "x")
        self.assertIsNone(d.error)
        self.assertEqual((d.name, d.passes), ("Demo", 2))
        self.assertEqual([(p.name, p.type) for p in d.params], [("amount", "float"), ("on", "bool"), ("tint", "color")])
        self.assertEqual(d.params[0].label, "強度")

    def test_bad_header_is_reported_not_raised(self):
        d = fx.parse("// @param bad wrongtype 1\nvec4 effect(vec2 uv){return src(uv);}\n", "x")
        self.assertTrue(d.error)
        d = fx.parse("// @filter NoEffect\n", "x")
        self.assertTrue(d.error)

    def test_builtin_filters_parse(self):
        refs = fx.builtin_refs()
        self.assertGreaterEqual(len(refs), 10)
        for r in refs:
            self.assertIsNone(fx.get(r).error, r)

    def test_effect_ops(self):
        proj = project.new(640, 360, 30)
        proj["tracks"].append({"id": "t0", "kind": "video", "name": "v", "clips": [
            {"id": "c1", "type": "image", "start_us": 0, "duration_us": 1000000, "media": {"path": "x.png"},
             "transform": {"x": 0, "y": 0, "scale": 1, "rotation": 0, "opacity": 1}}]})
        a = edit.add_effect(proj, "c1", "builtin:blur")
        b = edit.add_effect(proj, "c1", "builtin:invert")
        edit.move_effect(proj, "c1", b["id"], -1)
        self.assertEqual([e["id"] for e in proj["tracks"][0]["clips"][0]["effects"]], [b["id"], a["id"]])
        edit.set_effect_mask(proj, "c1", a["id"], "circle")
        self.assertEqual(a["mask"]["kind"], "circle")
        edit.remove_effect(proj, "c1", a["id"])
        edit.remove_effect(proj, "c1", b["id"])
        self.assertNotIn("effects", proj["tracks"][0]["clips"][0])


if __name__ == "__main__":
    unittest.main()


class LibraryCompoundTests(unittest.TestCase):
    """複合片段 in the Library: saved with what they show and the files they use, then used in
    another project (once per version of the file)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = library.norm(os.path.realpath(self.tmp.name))
        self.root = base + "/Library"
        userlib.ensure_layout(self.root)
        self.old = project.LIBRARY_ROOT
        project.LIBRARY_ROOT = self.root
        self.addCleanup(lambda: setattr(project, "LIBRARY_ROOT", self.old))
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from test_edit import S, clip, proj
        self.S = S
        self.outside = png(base + "/Project A/Media/wipe.png")
        self.mine = png(self.root + "/images/logo.png")
        p = proj()
        p["tracks"][0]["clips"][0]["media"] = {"path": self.outside, "width": 32, "height": 18}
        p["tracks"][1]["clips"].append(clip("c4", 0, S, media={"path": self.mine, "width": 32, "height": 18}))
        inner = edit.make_compound(p, p, ["c4"])                       # a compound inside the one saved
        self.kid = edit.make_compound(p, p, ["c1", inner["id"]])["compound_id"]
        p["compounds"][self.kid]["name"] = "轉場"
        self.p = p
        self.folder = userlib.category_dir(self.root, "compounds")

    def test_save_and_use(self):
        path = userlib.save_compound(self.root, self.folder, "轉場", self.p, self.kid)
        self.assertTrue(path.endswith("轉場.kccomp"))
        self.assertEqual(userlib.category_for(path), "compounds")
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        self.assertIn("@library/images/logo.png", raw)                  # Library files stay where they are
        self.assertIn("@library/compounds/.media/", raw)                # others are copied in
        self.assertEqual(len(json.loads(raw)["compounds"]), 2)          # with the compound inside it
        shutil.rmtree(os.path.dirname(os.path.dirname(self.outside)))   # (the first project is gone)

        from test_edit import proj
        q = proj()
        pack = userlib.load_compound(path)
        kid = edit.add_library_compound(q, pack)
        comp = q["compounds"][kid]
        self.assertEqual(comp["name"], "轉場")
        paths = [c["media"]["path"] for c in project.walk_clips(comp["tracks"]) if c.get("media")]
        self.assertIn(self.mine, paths)
        copied = next(x for x in paths if "/.media/" in x)
        self.assertTrue(os.path.exists(copied))
        nested = next(c for c in project.walk_clips(comp["tracks"]) if c.get("compound_id"))
        self.assertIn(nested["compound_id"], q["compounds"])
        self.assertIs(nested["compound"], q["compounds"][nested["compound_id"]])      # linked
        clip_ids = [c["id"] for c in project.all_clips(q)]
        self.assertEqual(len(clip_ids), len(set(clip_ids)))
        self.assertNotIn("c4", clip_ids)                                 # new ids
        c = edit.place_compound(q, q, kid, None, 3 * self.S)
        self.assertEqual(c["compound_id"], kid)
        self.assertEqual(edit.add_library_compound(q, userlib.load_compound(path)), kid)   # used again
        self.assertEqual(len(q["compounds"]), 2)

    def test_timelines_are_refused(self):
        self.p["compounds"][self.kid]["tracks"][0]["clips"][0]["timeline_id"] = "tl1"
        self.p["compounds"][self.kid]["tracks"][0]["clips"][0].pop("compound_id", None)
        with self.assertRaises(ValueError):
            userlib.compound_deps(self.p, self.kid)
