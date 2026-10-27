"""設定 > 緩存位置 (in the project, the user's cache folder, or a folder picked) and
檔案 > 清除專案緩存."""
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox  # noqa: E402

from kiasecut import workspace  # noqa: E402
from kiasecut.ui import main_window  # noqa: E402
from kiasecut.ui.settings_dialog import SettingsDialog  # noqa: E402

APP = QApplication.instance() or QApplication([])
MW = main_window.MainWindow


def fill(folder, name="a.npy", size=100):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), "wb") as fh:
        fh.write(b"x" * size)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = os.path.realpath(tmp.name)
        self.proj, self.path = workspace.create(os.path.join(self.d, "projects"), "My Video")
        self.root = workspace.root_of(self.path)
        self.base = os.path.join(self.d, "cache").replace("\\", "/")


class Places(Base):
    def test_in_the_project_or_outside(self):
        self.assertEqual(workspace.cache_dir(self.root), self.root + "/Cache")
        ident = workspace.cache_id(self.proj, self.root)
        self.assertEqual(workspace.cache_dir(self.root, self.base, ident), self.base + "/" + ident)

    def test_the_outside_cache_stays_when_the_project_moves(self):
        ident = workspace.cache_id(self.proj, self.root)
        os.makedirs(os.path.join(self.d, "elsewhere"))
        moved = workspace.move_project(self.path, os.path.join(self.d, "elsewhere"))
        self.assertEqual(workspace.cache_id(workspace.project.load(moved), workspace.root_of(moved)), ident)

    def test_projects_have_their_own(self):
        other, path = workspace.create(os.path.join(self.d, "projects"), "Other")
        other["info"]["created"] = "2020-01-01T00:00:00+00:00"
        self.assertNotEqual(workspace.cache_id(self.proj, self.root),
                            workspace.cache_id(other, workspace.root_of(path)))

    def test_no_cache_folder_until_something_is_cached(self):
        self.assertFalse(os.path.exists(workspace.cache_dir(self.root)))

    def test_clear_everywhere(self):
        ident = workspace.cache_id(self.proj, self.root)
        fill(workspace.cache_dir(self.root) + "/peaks", size=100)
        fill(workspace.cache_dir(self.root, self.base, ident) + "/text", size=50)
        fill(self.base + "/someone-else", size=10)
        freed = workspace.clear_cache(workspace.cache_dirs(self.root, ident, [self.base, ""]))
        self.assertEqual(freed, 150)
        self.assertFalse(os.path.exists(workspace.cache_dir(self.root)))
        self.assertFalse(os.path.exists(workspace.cache_dir(self.root, self.base, ident)))
        self.assertTrue(os.path.exists(self.base + "/someone-else/a.npy"))     # other projects' kept
        self.assertTrue(os.path.isdir(workspace.media_dir(self.root)))


def window(base, proj=None, root=None, mode=workspace.CACHE_DEFAULT, custom=""):
    w = SimpleNamespace(proj=proj, root=root, cache_base=base, messages=[])
    w.statusBar = lambda: SimpleNamespace(showMessage=lambda m, *_a: w.messages.append(m))
    w.default_cache_base = lambda: base
    w.cache_mode = lambda: mode
    w.cache_custom = lambda: custom
    w.cache_dir = lambda: MW.cache_dir(w)
    return w


class Window(Base):
    def test_choice_to_folder(self):
        w = window(self.base)
        self.assertIsNone(MW.cache_base_of(w, workspace.CACHE_PROJECT, "/x"))
        self.assertEqual(MW.cache_base_of(w, workspace.CACHE_DEFAULT, "/x"), self.base)
        self.assertEqual(MW.cache_base_of(w, workspace.CACHE_CUSTOM, "/x"), "/x")
        self.assertEqual(MW.cache_base_of(w, workspace.CACHE_CUSTOM, ""), self.base)    # none picked yet

    def test_cache_dir_follows_the_setting(self):
        w = window(self.base, self.proj, self.root)
        self.assertTrue(MW.cache_dir(w).startswith(self.base + "/"))
        w.cache_base = None
        self.assertEqual(MW.cache_dir(w), self.root + "/Cache")

    def test_clear_asks_then_deletes(self):
        custom = os.path.join(self.d, "custom").replace("\\", "/")
        w = window(self.base, self.proj, self.root, workspace.CACHE_CUSTOM, custom)
        ident = workspace.cache_id(self.proj, self.root)
        for d in (self.root + "/Cache", f"{self.base}/{ident}", f"{custom}/{ident}"):
            fill(d)
        with mock.patch.object(main_window.QMessageBox, "question", return_value=QMessageBox.No):
            MW.clear_project_cache(w)
        self.assertTrue(os.path.exists(self.root + "/Cache"))
        with mock.patch.object(main_window.QMessageBox, "question", return_value=QMessageBox.Yes):
            MW.clear_project_cache(w)
        for d in (self.root + "/Cache", f"{self.base}/{ident}", f"{custom}/{ident}"):
            self.assertFalse(os.path.exists(d))
        self.assertIn("300 B", w.messages[-1])
        MW.clear_project_cache(w)
        self.assertEqual(w.messages[-1], "這個專案沒有緩存")

    def test_changing_the_place_moves_the_waveforms_and_sound(self):
        peaks = SimpleNamespace(dir="old")
        w = window(self.base, self.proj, self.root)
        w.timeline = SimpleNamespace(peaks=peaks)
        w.rebuild = mock.Mock()
        MW.set_cache_base(w, None)
        self.assertEqual(peaks.dir, os.path.join(self.root + "/Cache", "peaks"))
        w.rebuild.assert_called_once()


class Dialog(unittest.TestCase):
    def dialog(self, mode, custom=""):
        dlg = SettingsDialog(None, "/tmp/lib", "/tmp/lib", "/tmp/p", 5, cache_mode=mode, cache_custom=custom,
                             default_cache="/home/u/.cache/KiaseCut/projects")
        self.addCleanup(shiboken6.delete, dlg)           # (left for Python's exit, it crashed PySide's clean-up)
        return dlg

    def test_custom_needs_a_folder(self):
        dlg = self.dialog(workspace.CACHE_CUSTOM)
        ok = dlg.buttons.button(QDialogButtonBox.Ok)
        self.assertFalse(ok.isEnabled())
        dlg.cache_custom.setText("/tmp/c")
        self.assertTrue(ok.isEnabled())
        self.assertEqual((dlg.values()["cache_mode"], dlg.values()["cache_custom"]), ("custom", "/tmp/c"))

    def test_folder_field_only_for_custom(self):
        dlg = self.dialog(workspace.CACHE_PROJECT)
        self.assertTrue(dlg.cache_custom.isHidden())
        self.assertTrue(dlg.buttons.button(QDialogButtonBox.Ok).isEnabled())
        self.assertIn("Cache", dlg.cache_note.text())
        dlg.cache_mode.setCurrentIndex(dlg.cache_mode.findData(workspace.CACHE_DEFAULT))
        self.assertIn("/home/u/.cache/KiaseCut/projects", dlg.cache_note.text())
        self.assertEqual(dlg.values()["cache_mode"], "default")


if __name__ == "__main__":
    unittest.main()
