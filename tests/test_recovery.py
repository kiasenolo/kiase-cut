"""Autosave and recovery (recovery.py): unsaved changes written to the autosave folder, the
newest few kept, and offered back at the next start when the program ended unexpectedly."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from kiasecut import project, recovery, workspace  # noqa: E402


def dead_pid():
    """The id of a process that has ended."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.dir = os.path.join(self.tmp, "auto-save")
        self.proj, self.path = workspace.create(self.tmp, "My Video")

    def session(self, pid, **data):
        os.makedirs(self.dir, exist_ok=True)
        f = os.path.join(self.dir, f"session-{pid}.json")
        with open(f, "w", encoding="utf-8") as fh:
            json.dump(dict({"pid": pid, "project": self.path, "autosave": None}, **data), fh)
        return f

    def test_session_lives_while_running(self):
        recovery.begin(self.dir)
        own = os.path.join(self.dir, f"session-{os.getpid()}.json")
        self.assertTrue(os.path.exists(own))
        save = recovery.autosave(self.dir, self.proj, self.path)
        with open(own, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["autosave"], save)
        self.assertEqual(recovery.crashed(self.dir), [])            # (this one is running)
        recovery.end(self.dir)
        self.assertFalse(os.path.exists(own))
        self.assertTrue(os.path.exists(os.path.join(self.dir, "crash.log")))

    def test_crashed_session_is_offered(self):
        save = recovery.autosave(self.dir, self.proj, self.path)
        gone = self.session(dead_pid(), autosave=save)
        nothing = self.session(dead_pid())                          # saved before it ended
        found = recovery.crashed(self.dir)
        self.assertEqual([f for f, _d in found], [gone])
        self.assertFalse(os.path.exists(nothing))                   # (nothing to bring back: forgotten)

    def test_autosave_opens_from_its_folder(self):
        media = os.path.join(os.path.dirname(self.path), "Media", "a.png")
        self.proj["tracks"] = self.proj["timelines"][0]["tracks"]
        self.proj["library"] = {"items": [{"id": "m1", "path": media, "kind": "image"}], "folders": []}
        save = recovery.autosave(self.dir, self.proj, self.path)
        self.assertTrue(os.path.basename(save).startswith("My Video "))
        back = project.load(save)
        self.assertEqual(back["library"]["items"][0]["path"], media.replace("\\", "/"))

    def test_limit(self):
        kept = recovery.autosave(self.dir, self.proj, self.path)
        os.utime(kept, (time.time() - 5000, time.time() - 5000))     # the oldest,
        self.session(dead_pid(), autosave=kept)                     # but still to be offered: never pruned
        for i in range(5):
            stale = os.path.join(self.dir, f"My Video 2020-01-0{i + 1} 00-00-00.kiasecut.json")
            project.save(self.proj, stale)
            os.utime(stale, (time.time() - 1000 + i, time.time() - 1000 + i))
        recovery.prune(self.dir, 2)
        left = recovery.files(self.dir)
        self.assertEqual(len(left), 3)
        self.assertIn(kept, left)
        self.assertIn(os.path.join(self.dir, "My Video 2020-01-05 00-00-00.kiasecut.json"), left)


class OfferTests(unittest.TestCase):
    def test_recover_opens_it_unsaved(self):
        from PySide6.QtWidgets import QApplication
        from kiasecut.ui import main_window
        QApplication.instance() or QApplication([])
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        where = os.path.join(tmp, "auto-save")
        proj, path = workspace.create(tmp, "Clip")
        proj["duration_us"] = 123
        save = recovery.autosave(where, proj, path)
        os.makedirs(where, exist_ok=True)
        with open(os.path.join(where, f"session-{dead_pid()}.json"), "w", encoding="utf-8") as fh:
            json.dump({"pid": 1, "project": path, "autosave": save}, fh)
        opened = []
        win = SimpleNamespace(autosave_dir=where, path=None, dirty=False, proj=None,
                              open_loaded=lambda p, f: opened.append((p["duration_us"], f)) or True,   # (opened)
                              _update_title=lambda: None, statusBar=lambda: mock.Mock())
        win._session = lambda **kw: main_window.MainWindow._session(win, **kw)

        class Box:                                                 # 回復 is clicked
            Warning, AcceptRole, RejectRole = 0, 0, 1

            def __init__(self, *_a, **_k):
                self.buttons = []

            def addButton(self, text, _role):
                self.buttons.append(text)
                return text

            def setDefaultButton(self, _b):
                pass

            def exec(self):
                pass

            def clickedButton(self):
                return self.buttons[0]
        with mock.patch.object(main_window, "QMessageBox", Box), \
                mock.patch.object(main_window.recovery, "alive", lambda pid: pid == os.getpid()):
            self.assertTrue(main_window.MainWindow.offer_recovery(win))
        self.assertEqual(opened, [(123, path)])
        self.assertTrue(win.dirty)
        self.assertEqual(recovery.crashed(where), [])               # answered: not asked again


if __name__ == "__main__":
    unittest.main()
