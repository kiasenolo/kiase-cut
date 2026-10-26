"""Picking several files at once: 選擇濾鏡檔案 puts every picked filter on the clip in one undo
step, and 匯入素材 hands every picked file to the import."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, library  # noqa: E402
from kiasecut.ui import main_window  # noqa: E402
from kiasecut.ui.main_window import MainWindow  # noqa: E402
from test_edit import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


def dialog(picked):
    """A stand-in for QFileDialog whose multi-select returns `picked`."""
    calls = []

    class Fake:
        @staticmethod
        def getOpenFileNames(*args):
            calls.append(args)
            return list(picked), ""
    return Fake, calls


class FilterFilesTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.h = edit.History(self.p)
        self.win = SimpleNamespace(ulib=None, container=lambda: self.p,
                                   apply=lambda label, fn, *a: self.h.do(label, fn, *a))
        self.win.add_effects_to = lambda ids, refs: MainWindow.add_effects_to(self.win, ids, refs)

    def effects(self):
        return [e["filter"] for e in edit.find(self.p, "c1")[1].get("effects", [])]

    def browse(self, picked):
        fake, calls = dialog(picked)
        with mock.patch.object(main_window, "QFileDialog", fake):
            MainWindow.browse_effect(self.win, ["c1"])
        return calls

    def test_several_files_one_undo_step(self):
        picked = ["C:/f/b.glsl", "C:/f/a.glsl", "C:/f/c.glsl"]
        self.assertEqual(len(self.browse(picked)), 1)
        self.assertEqual(self.effects(), [library.norm(f) for f in picked])   # in the picked order
        self.assertEqual(len(self.h.undo_stack), 1)
        self.h.undo()
        self.assertEqual(self.effects(), [])

    def test_one_file_still_works(self):
        self.browse(["C:/f/a.glsl"])
        self.assertEqual(self.effects(), [library.norm("C:/f/a.glsl")])
        self.assertEqual(len(self.h.undo_stack), 1)

    def test_cancel_changes_nothing(self):
        self.browse([])
        self.assertEqual(self.effects(), [])
        self.assertEqual(self.h.undo_stack, [])

    def test_add_effects_is_all_or_nothing(self):
        with self.assertRaises(edit.EditError):                                # c3 is sound
            self.h.do("新增效果", edit.add_effects, "c3", ["builtin:blur", "builtin:invert"])
        self.assertEqual(self.h.undo_stack, [])


class MediaFilesTests(unittest.TestCase):
    def test_import_media_passes_every_picked_file(self):
        got = []
        win = SimpleNamespace(ensure_project=lambda: True,
                              import_files=lambda files, folder: got.append((files, folder)))
        picked = ["C:/m/a.png", "C:/m/b.mp4", "C:/m/c.mp3"]
        fake, _ = dialog(picked)
        with mock.patch.object(main_window, "QFileDialog", fake):
            MainWindow.import_media(win, "fold")
        self.assertEqual(got, [(picked, "fold")])


if __name__ == "__main__":
    unittest.main()
