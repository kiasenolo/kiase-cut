"""The project manager: every project (the projects folder and the recent list) with its
thumbnail; thumbnails from a saved frame or a static compound named _thumbnail."""
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, project, thumbnail, workspace  # noqa: E402
from kiasecut.ui.project_manager import ProjectManager, label  # noqa: E402
from test_edit import S, clip  # noqa: E402

APP = QApplication.instance() or QApplication([])


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.home = os.path.join(self.dir, "KiaseCut")
        os.makedirs(self.home)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def make(self, name, where=None):
        return workspace.create(where or self.home, name)


class FindTests(Base):
    def test_folder_and_recent(self):
        _, a = self.make("A")
        time.sleep(0.02)
        _, b = self.make("B")
        _, far = self.make("Far", self.dir)                       # outside the folder: only from recent
        os.makedirs(os.path.join(self.home, "not a project"))
        found = workspace.find_projects(self.home, [far, a, os.path.join(self.dir, "gone.kiasecut.json")])
        names = [workspace.project_name(p) for p in found]
        self.assertEqual(sorted(names), ["A", "B", "Far"])        # each once, missing ones left out
        self.assertEqual(names.index("B") < names.index("A"), True)      # newest first
        self.assertEqual(workspace.find_projects(os.path.join(self.dir, "nowhere")), [])


class ThumbnailTests(Base):
    def red(self):
        im = QImage(16, 9, QImage.Format_RGB32)
        im.fill(QColor("#ff0000"))
        path = os.path.join(self.dir, "red.png")
        im.save(path)
        return clip("r", 0, S, media={"path": path, "width": 16, "height": 9})

    def test_from_a_frame(self):
        _, path = self.make("A")
        self.assertIsNone(thumbnail.load(path))                  # none at first
        im = QImage(1280, 720, QImage.Format_RGB32)
        im.fill(QColor("#00ff00"))
        thumbnail.save_image(im, path)
        got = thumbnail.load(path)
        self.assertEqual((got.width(), got.pixelColor(10, 10).name()), (thumbnail.WIDTH, "#00ff00"))
        thumbnail.remove(path)
        self.assertIsNone(thumbnail.load(path))

    def test_from_a_static_compound(self):
        proj, path = self.make("A")
        proj["tracks"].append({"id": "t0", "kind": "video", "name": "v", "clips": [self.red()]})
        project.link(proj)
        self.assertIsNone(thumbnail.update(proj, path))           # no _thumbnail: nothing to do
        plain = edit.make_compound(proj, proj, ["r"], None)
        with self.assertRaises(edit.EditError):                   # only a static one may be _thumbnail
            edit.rename_compound(proj, plain["compound_id"], "_thumbnail")
        proj["compounds"][plain["compound_id"]]["name"] = "_thumbnail"           # (an older file, say)
        self.assertIsNone(project.thumbnail_compound(proj))
        self.assertEqual(thumbnail.update(proj, path), "not static")
        self.assertIsNone(thumbnail.load(path))
        proj["compounds"][plain["compound_id"]]["name"] = "plain"
        st = edit.make_compound(proj, proj, [plain["id"]], 0, static=True)
        edit.rename_compound(proj, st["compound_id"], "_thumbnail")
        self.assertIs(project.thumbnail_compound(proj), st["compound"])
        self.assertEqual(thumbnail.update(proj, path), "compound")
        got = thumbnail.load(path)
        self.assertEqual(got.pixelColor(got.width() // 2, got.height() // 2).name(), "#ff0000")


class LabelTests(Base):
    def test_title_folder_time(self):
        proj, path = self.make("Folder A")
        proj["info"]["title"] = "我的影片"
        project.save(proj, path)
        lines = label(path).split("\n")
        self.assertEqual(lines[:2], ["我的影片", "Folder A"])
        self.assertRegex(lines[2], r"^\d{4}-\d\d-\d\d \d\d:\d\d$")
        proj["info"]["title"] = "  "                                         # no title: folder and time
        project.save(proj, path)
        self.assertEqual(label(path).split("\n")[0], "Folder A")
        self.assertEqual(len(label(path).split("\n")), 2)
        del proj["info"]
        project.save(proj, path)
        self.assertEqual(len(label(path).split("\n")), 2)
        with open(path, "w", encoding="utf-8") as fh:                        # unreadable: the same
            fh.write("{broken")
        self.assertEqual(label(path).split("\n")[0], "Folder A")


class DialogTests(Base):
    def test_cards_and_choices(self):
        _, a = self.make("Alpha")
        _, b = self.make("Beta")
        im = QImage(320, 180, QImage.Format_RGB32)
        im.fill(QColor("#3366ff"))
        thumbnail.save_image(im, a)
        dlg = ProjectManager(None, self.home, [])
        self.assertEqual(sorted(workspace.project_name(p) for p in dlg.paths()), ["Alpha", "Beta"])
        dlg.search.setText("alp")
        shown = [dlg.list.item(i).data(Qt.UserRole) for i in range(dlg.list.count()) if not dlg.list.item(i).isHidden()]
        self.assertEqual([workspace.project_name(p) for p in shown], ["Alpha"])
        item = next(dlg.list.item(i) for i in range(dlg.list.count()) if dlg.list.item(i).data(Qt.UserRole) == a)
        dlg.list.itemActivated.emit(item)
        self.assertEqual(dlg.choice, ("open", a))
        empty = ProjectManager(None, os.path.join(self.dir, "none"), [])
        self.assertTrue(empty.list.isHidden() and not empty.empty.isHidden())


class FolderTests(Base):
    """The manager as a small file manager: folders, rename, move, copy, delete."""

    def test_browse_folders_and_projects(self):
        _, a = self.make("A")
        group = workspace.new_folder(self.home, "客戶")
        _, b = self.make("B", group)
        folders, projects = workspace.browse(self.home)
        self.assertEqual([os.path.basename(f) for f in folders], ["客戶"])        # B's folder is not a project
        self.assertEqual([workspace.project_name(p) for p in projects], ["A"])
        self.assertEqual([workspace.project_name(p) for p in workspace.browse(group)[1]], ["B"])
        self.assertEqual(sorted(workspace.project_name(p) for p in workspace.find_all(self.home)), ["A", "B"])

    def test_rename_move_copy_delete(self):
        _, a = self.make("A")
        im = QImage(32, 18, QImage.Format_RGB32)
        im.fill(QColor("#ff0000"))
        thumbnail.save_image(im, a)
        b = workspace.rename_project(a, "Bee")
        self.assertTrue(b.endswith("/Bee/Bee.kiasecut.json") and os.path.exists(b))
        self.assertFalse(os.path.exists(a))
        self.assertIsNotNone(thumbnail.load(b))                                  # the thumbnail followed
        group = workspace.new_folder(self.home, "G")
        moved = workspace.move_project(b, group)
        self.assertEqual(os.path.dirname(os.path.dirname(moved)), group)
        copy = workspace.copy_project(moved)
        self.assertTrue(os.path.exists(copy))
        self.assertIn("副本", workspace.project_name(copy))
        self.assertEqual(project.load(copy)["format"], "kiasecut")
        gone = []
        workspace.remove_project(copy, lambda p: (gone.append(p), shutil.rmtree(p)))
        self.assertEqual(gone, [workspace.root_of(copy)])                         # its whole folder
        self.assertTrue(os.path.exists(moved))
        with self.assertRaises(ValueError):
            workspace.move_folder(group, os.path.join(group, "x"))               # not into itself

    def test_shared_folder_is_not_moved(self):
        proj, a = self.make("A")
        other = os.path.join(workspace.root_of(a), "Other" + workspace.EXT)
        project.save(proj, other)
        self.assertFalse(workspace.owns_folder(a))
        with self.assertRaises(ValueError):
            workspace.move_project(a, self.dir)
        gone = []
        workspace.remove_project(a, lambda p: (gone.append(p), os.remove(p)))
        self.assertEqual(gone, [a])                                               # just the file
        self.assertTrue(os.path.exists(other))

    def test_dialog_folders(self):
        _, a = self.make("A")
        group = workspace.new_folder(self.home, "G")
        _, b = self.make("B", group)
        dlg = ProjectManager(None, self.home, [], current=a)
        kinds = [dlg.list.item(i).data(Qt.UserRole + 1) for i in range(dlg.list.count())]
        self.assertEqual(kinds, ["folder", "project"])
        folder_item = next(dlg.list.item(i) for i in range(dlg.list.count()) if kinds[i] == "folder")
        dlg.list.itemActivated.emit(folder_item)                                 # go in
        self.assertEqual(dlg.paths(), [b])
        self.assertEqual(dlg.list.item(0).data(Qt.UserRole + 1), "up")
        dlg.list.moveRequested.emit(b, self.home)                                # dragged onto 上一層
        self.assertEqual(dlg.paths(), [])
        dlg.go_up()
        self.assertEqual(sorted(workspace.project_name(p) for p in dlg.paths()), ["A", "B"])
        self.assertTrue(dlg.moved)
        from unittest import mock
        with mock.patch("kiasecut.ui.project_manager.QMessageBox.information") as told:
            dlg.list.moveRequested.emit(a, group)                                # the open one stays
        self.assertTrue(told.called)
        self.assertTrue(os.path.exists(a))
        dlg.search.setText("b")                                                   # search sees every folder
        self.assertEqual([workspace.project_name(p) for p in dlg.paths()], ["B"])


if __name__ == "__main__":
    unittest.main()
