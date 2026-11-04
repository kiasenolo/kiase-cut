"""ui/androidfiles.py: Qt's own file dialog in place of the system's chooser (which gives content:// addresses)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from kiasecut.ui import androidfiles  # noqa: E402

APP = QApplication.instance() or QApplication([])


class StartTest(unittest.TestCase):
    def test_folder_file_and_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(androidfiles._start(d), (d, ""))
            self.assertEqual(androidfiles._start(os.path.join(d, "out.mp4")), (d, "out.mp4"))
        folder, name = androidfiles._start("")
        self.assertTrue(os.path.isdir(folder))
        self.assertEqual(name, "")

    def test_dialog_is_not_the_native_one_and_takes_the_filter(self):
        with tempfile.TemporaryDirectory() as d:
            dlg = androidfiles._dialog(None, "匯入素材", d, "影片 (*.mp4 *.mov);;All files (*)", QFileDialog.ExistingFiles)
            self.assertTrue(dlg.testOption(QFileDialog.DontUseNativeDialog))
            self.assertEqual(dlg.fileMode(), QFileDialog.ExistingFiles)
            self.assertEqual(dlg.nameFilters(), ["影片 (*.mp4 *.mov)", "All files (*)"])
            save = androidfiles._dialog(None, "匯出", os.path.join(d, "a.mp4"), "MP4 (*.mp4)", QFileDialog.AnyFile, save=True)
            self.assertEqual(save.acceptMode(), QFileDialog.AcceptSave)
            self.assertEqual(os.path.basename(save.selectedFiles()[0]), "a.mp4")

    def test_install_replaces_the_four_static_functions(self):
        saved = {n: getattr(QFileDialog, n) for n in ("getOpenFileName", "getOpenFileNames", "getSaveFileName", "getExistingDirectory")}
        try:
            androidfiles.install()
            self.assertIs(QFileDialog.getOpenFileNames.__func__ if hasattr(QFileDialog.getOpenFileNames, "__func__")
                          else QFileDialog.getOpenFileNames, androidfiles.open_files)
        finally:
            for n, f in saved.items():
                setattr(QFileDialog, n, f)


if __name__ == "__main__":
    unittest.main()
