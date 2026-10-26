"""File > 專案資訊 (F11): what is typed is kept however the window closes - Esc too."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import workspace  # noqa: E402
from kiasecut.ui import main_window  # noqa: E402
from test_edit import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


class ProjectInfoTests(unittest.TestCase):
    def test_escape_keeps_the_text(self):
        p = proj()
        p["timelines"] = [{"id": "tl1", "name": "時間線 1", "tracks": p["tracks"]}]
        p.setdefault("duration_us", 0)
        win = SimpleNamespace(proj=p, path=None, root=None, dirty=False, _tick=lambda: None,
                              _update_title=lambda: None, reveal=lambda _i: None)

        def typed_then_escape(dlg):
            dlg.title.setText("我的影片")
            dlg.comments.setPlainText("記得換配樂")
            QTest.keyClick(dlg, Qt.Key_Escape)
            return 0

        real_init = main_window.ProjectInfoDialog.__init__

        def init(dlg, _parent, *a):                       # (no main window to sit on)
            real_init(dlg, None, *a)
        with mock.patch.object(main_window.ProjectInfoDialog, "exec", typed_then_escape), \
                mock.patch.object(main_window.ProjectInfoDialog, "__init__", init), \
                mock.patch.object(main_window.library, "lib", lambda _p: {"items": []}):
            main_window.MainWindow.show_project_info(win)
        info = workspace.info(p)
        self.assertEqual(info["title"], "我的影片")
        self.assertEqual(info["comments"], "記得換配樂")
        self.assertTrue(win.dirty)


if __name__ == "__main__":
    unittest.main()
