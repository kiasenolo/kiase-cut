import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from kiasecut import edit, library, project, workspace  # noqa: E402


def png(path, size=(32, 18)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", size, "red").save(path)
    return path.replace("\\", "/")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = os.path.realpath(self.tmp.name)
        self.proj, self.path = workspace.create(self.d, "My Video", 1280, 720, 30)
        self.root = workspace.root_of(self.path)

    def sync(self):
        res = library.scan(self.root, library.known_paths(self.proj))
        return library.apply_scan(self.proj, self.root, res)

    def import_(self, *names, folder=None):
        src = [png(os.path.join(self.d, "outside", n)) for n in names]
        got = library.import_copy(self.root, src, library.folder_dir(self.proj, self.root, folder))
        self.sync()
        return [library.norm(g) for g in got.values()]


class Layout(Base):
    def test_create(self):
        for d in (workspace.MEDIA, workspace.CACHE, workspace.EXPORTS, workspace.BACKUP):
            self.assertTrue(os.path.isdir(os.path.join(self.root, d)))
        self.assertTrue(self.path.endswith("My Video.kiasecut.json"))
        i = self.proj["info"]
        self.assertEqual((i["title"], i["time_spent_s"], i["opens"]), ("My Video", 0, 1))
        self.assertTrue(workspace.parse_time(i["created"]))
        with self.assertRaises(FileExistsError):
            workspace.create(self.d, "My Video")             # not an empty folder

    def test_paths_are_relative_on_disk_and_absolute_in_memory(self):
        (path,) = self.import_("a.png")
        library.add_files(self.proj, [], None)
        clip = library.clip_from(library.item(self.proj, library.lib(self.proj)["items"][0]["id"]), 0)
        self.proj["tracks"].append({"id": "t0", "kind": "video", "name": "v", "clips": [clip]})
        workspace.save(self.proj, self.path)
        raw = json.load(open(self.path, encoding="utf-8"))
        self.assertEqual(raw["library"]["items"][0]["path"], "Media/a.png")
        self.assertEqual(raw["timelines"][0]["tracks"][0]["clips"][0]["media"]["path"], "Media/a.png")
        back = project.load(self.path)
        self.assertEqual(library.lib(back)["items"][0]["path"], path)
        self.assertEqual(back["tracks"][0]["clips"][0]["media"]["path"], path)
        self.assertIsNotNone(back["info"]["last_saved"])

    def test_moving_the_folder_keeps_the_media(self):
        self.import_("a.png")
        workspace.save(self.proj, self.path)
        import shutil
        new = os.path.join(self.d, "moved")
        shutil.copytree(self.root, new)
        back = project.load(os.path.join(new, "My Video.kiasecut.json"))
        p = library.lib(back)["items"][0]["path"]
        self.assertTrue(p.startswith(new.replace("\\", "/")) and os.path.exists(p))

    def test_backup_on_second_save_and_autosave(self):
        workspace.save(self.proj, self.path)
        workspace.save(self.proj, self.path)
        b = os.listdir(os.path.join(self.root, workspace.BACKUP))
        self.assertEqual(len(b), 1)
        self.assertIsNotNone(workspace.make_backup(self.path, tag="x"))
        workspace.autosave(self.proj, self.path)
        self.assertIn("My Video autosave.kiasecut.json", os.listdir(os.path.join(self.root, workspace.BACKUP)))

    def test_old_project_gets_info(self):
        old = project.new()
        project.save(old, self.path)
        p = project.load(self.path)
        self.assertNotIn("info", p)
        workspace.opened(p, self.path)
        self.assertEqual(p["info"]["opens"], 2)
        self.assertTrue(workspace.parse_time(p["info"]["created"]))


class Undo(Base):
    def test_undo_does_not_touch_the_library(self):
        self.import_("a.png")
        h = edit.History(self.proj)
        h.do("track", lambda p: p["tracks"].append({"id": "t9", "kind": "video", "name": "x", "clips": []}))
        self.import_("b.png")
        self.assertEqual(len(library.lib(self.proj)["items"]), 2)
        h.undo()
        self.assertEqual(len(library.lib(self.proj)["items"]), 2)
        self.assertEqual(self.proj["tracks"], [])
        self.proj["info"]["author"] = "me"
        h.redo()
        self.assertEqual(self.proj["info"]["author"], "me")


class Sync(Base):
    def test_import_copies_and_mirrors(self):
        (p,) = self.import_("a.png")
        self.assertEqual(p, library.norm(os.path.join(self.root, "Media", "a.png")))
        it = library.lib(self.proj)["items"]
        self.assertEqual((len(it), it[0]["name"], it[0]["folder"], it[0]["kind"]), (1, "a.png", None, "image"))
        again = self.import_("a.png")                          # the same file again: reused
        self.assertEqual(again, [p])
        self.assertEqual(len(library.lib(self.proj)["items"]), 1)
        self.assertFalse(self.sync())                          # nothing new: no change

    def test_unique_names(self):
        a = png(os.path.join(self.d, "one", "x.png"), (10, 10))
        b = png(os.path.join(self.d, "two", "x.png"), (20, 20))
        got = library.import_copy(self.root, [a, b], os.path.join(self.root, "Media"))
        self.assertEqual(sorted(os.path.basename(v) for v in got.values()), ["x (2).png", "x.png"])

    def test_disk_changes_show_up(self):
        png(os.path.join(self.root, "Media", "Sub", "deep", "z.png"))
        png(os.path.join(self.root, "Media", "top.png"))
        self.assertTrue(self.sync())
        L = library.lib(self.proj)
        self.assertEqual(sorted(f["name"] for f in L["folders"]), ["Sub", "deep"])
        z = next(i for i in L["items"] if i["name"] == "z.png")
        self.assertEqual(library.folder(self.proj, z["folder"])["name"], "deep")
        self.assertEqual(library.folder_rel(self.proj, z["folder"]), "Sub/deep")
        os.remove(z["path"])
        self.sync()
        self.assertEqual([i["name"] for i in L["items"]], ["top.png"])

    def test_folder_ops_touch_the_disk(self):
        f = library.make_folder(self.proj, self.root, "圖片")
        self.assertTrue(os.path.isdir(os.path.join(self.root, "Media", "圖片")))
        f2 = library.make_folder(self.proj, self.root, "圖片")
        self.assertEqual(f2["name"], "圖片 (2)")
        (p,) = self.import_("a.png", folder=f["id"])
        self.assertTrue(os.path.exists(p))
        mid = library.lib(self.proj)["items"][0]["id"]
        library.move_on_disk(self.proj, self.root, mid, f2["id"])
        moved = library.item(self.proj, mid)["path"]
        self.assertTrue(moved.endswith("圖片 (2)/a.png") and os.path.exists(moved) and not os.path.exists(p))
        self.assertFalse(self.sync())                          # the mirror agrees with the disk
        library.rename_on_disk(self.proj, self.root, mid, "b")
        self.assertEqual(library.item(self.proj, mid)["name"], "b.png")
        with self.assertRaises(edit.EditError):
            library.rename_on_disk(self.proj, self.root, mid, "a/b")
        library.rename_on_disk(self.proj, self.root, f2["id"], "新名字")
        self.assertTrue(library.item(self.proj, mid)["path"].endswith("新名字/b.png"))
        self.assertTrue(os.path.exists(library.item(self.proj, mid)["path"]))
        self.assertFalse(self.sync())
        library.move_on_disk(self.proj, self.root, f2["id"], f["id"])        # folder into folder
        self.assertTrue(library.item(self.proj, mid)["path"].endswith("圖片/新名字/b.png"))
        with self.assertRaises(edit.EditError):
            library.move_on_disk(self.proj, self.root, f["id"], f2["id"])
        library.delete_on_disk(self.proj, self.root, f["id"])
        self.assertEqual(library.lib(self.proj)["items"], [])
        self.assertNotIn("圖片", os.listdir(os.path.join(self.root, "Media")))

    def test_clips_and_undo_follow_a_rename(self):
        (p,) = self.import_("a.png")
        mid = library.lib(self.proj)["items"][0]["id"]
        h = edit.History(self.proj)
        h.do("place", lambda r: library.place(r, r, mid, None, 0))
        h.do("again", lambda r: library.place(r, r, mid, None, 10_000_000))
        pairs = library.rename_on_disk(self.proj, self.root, mid, "renamed.png")
        h.rewrite(lambda t: library.retarget_text(t, *pairs[0][:2], pairs[0][2]))
        new = library.item(self.proj, mid)["path"]
        self.assertTrue(all(c["media"]["path"] == new for c in project.all_clips(self.proj)))
        h.undo()
        h.undo()
        h.redo()
        self.assertTrue(all(c["media"]["path"] == new for c in project.all_clips(self.proj)))

    def test_collect_external_media(self):
        ext = png(os.path.join(self.d, "elsewhere", "e.png"))
        ext2 = png(os.path.join(self.d, "elsewhere2", "e.png"), (50, 50))
        F = library.add_folder(self.proj, "素材")
        library.add_files(self.proj, [ext], F["id"])
        c = library.clip_from(library.item(self.proj, library.lib(self.proj)["items"][0]["id"]), 0)
        c2 = {"id": "x2", "type": "image", "name": "e2", "start_us": 0, "duration_us": 1, "media": {"path": ext2}}
        self.proj["tracks"].append({"id": "t0", "kind": "video", "name": "v", "clips": [c, c2]})
        plan = library.external_media(self.proj, self.root)
        self.assertEqual(len(plan), 2)
        self.assertEqual(sorted(os.path.relpath(v, self.root + "/Media").replace("\\", "/") for v in plan.values()),
                         ["匯入的素材/e.png", "素材/e.png"])
        done = library.collect(plan)
        for src, dst in done.items():
            library.retarget(self.proj, src, dst)
        self.sync()
        self.assertEqual(library.external_media(self.proj, self.root), {})
        self.assertTrue(all(os.path.exists(k["media"]["path"]) for k in project.all_clips(self.proj)))
        names = sorted(f["name"] for f in library.lib(self.proj)["folders"])
        self.assertEqual(names, ["匯入的素材", "素材"])
        self.assertEqual(len(library.lib(self.proj)["items"]), 2)     # both are in the mirror now


if __name__ == "__main__":
    unittest.main()
