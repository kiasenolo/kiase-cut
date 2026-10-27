"""取消匯出 and the export's extra information: an export stops when asked (between frames
and while the sound is mixed), says what stage it is at, the dialog counts the frames and
warns about a huge size, and the progress window waits for the export to wind down.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import gpu, project, renderexport, sysmem  # noqa: E402
from kiasecut.build import find_ffmpeg  # noqa: E402
from kiasecut.ui.export_dialog import ExportDialog, ExportProgress  # noqa: E402

APP = QApplication.instance() or QApplication([])
S = 1_000_000
W, H, FPS = 160, 90, 10
FFMPEG = find_ffmpeg()


@unittest.skipUnless(FFMPEG, "no ffmpeg")
class CancelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.tone = os.path.join(cls.dir, "tone.wav")
        subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                        cls.tone], check=True)
        cls.gpu = gpu.enabled
        gpu.enabled = False

    @classmethod
    def tearDownClass(cls):
        gpu.enabled = cls.gpu
        shutil.rmtree(cls.dir, ignore_errors=True)

    def proj(self):
        p = project.new(W, H, FPS)
        p["tracks"] = [{"id": "t1", "kind": "audio", "name": "聲音", "clips": [
            {"id": "a1", "type": "audio", "name": "a1", "start_us": 0, "duration_us": 3 * S, "source_start_us": 0,
             "media": {"path": self.tone, "duration_us": 3 * S}, "volume": 1.0}]}]
        project.refresh_duration(p)
        return project.link(p)

    def run_export(self, name, cancelled, spec=None):
        stages, out = [], os.path.join(self.dir, name)
        renderexport.export(self.proj(), out, (W, H), FPS, 0, 3 * FPS - 1, {"crf": 20, "preset": "fast"},
                            cache_dir=os.path.join(self.dir, "cache"), cancelled=cancelled, spec=spec,
                            on_stage=stages.append)
        return out, stages

    def test_stages(self):
        _, stages = self.run_export("staged.mp4", lambda: False, {"format": "mp4_h265"})
        self.assertEqual(stages, ["混音", "繪製與編碼畫面"])

    def test_cancel_between_frames(self):
        asked = []

        def cancelled():               # no from the sound, yes once the pictures have begun
            asked.append(1)
            return len(asked) > 3
        with self.assertRaisesRegex(RuntimeError, "已取消"):
            self.run_export("stopped.mp4", cancelled, {"format": "mp4_h265"})

    def test_cancel_while_mixing(self):
        with self.assertRaisesRegex(RuntimeError, "已取消"):
            self.run_export("stopped.wav", lambda: True, {"format": "wav"})


class DialogTests(unittest.TestCase):
    def made(self, w):
        """w, deleted when the test ends: a window without a parent still there when Python
        quits (kept by a lambda of its own) crashed PySide 6.12's clean-up."""
        self.addCleanup(shiboken6.delete, w)
        return w

    def test_frames_and_warning(self):
        dlg = self.made(ExportDialog(None, os.path.join(tempfile.gettempdir(), "x.mp4"), 30, 90, None, None,
                                     1920, 1080, out_fps=30))
        self.assertEqual(dlg.frames(), (0, 89))
        self.assertIn("90 幀", dlg.info_lbl.text())
        self.assertNotIn("⚠", dlg.info_lbl.text())
        dlg.scale_box.setCurrentIndex(dlg.scale_box.count() - 1)         # 自訂
        dlg.scale_custom.setValue(8.0)
        dlg._update()
        self.assertIn("⚠", dlg.info_lbl.text())                          # 15360×8640: past 8K

    def test_progress_waits_for_the_export(self):
        stopped = []
        prog = self.made(ExportProgress(None, "/tmp/x.mp4", "MP4", 100, stopped.append))
        prog.show()
        prog.set_progress(0.25)
        prog._tick()
        self.assertEqual(prog.frames_lbl.text(), "25 / 100")
        prog.close()                                       # the window's X: stop, but stay open
        prog.cancel()
        self.assertEqual(stopped, [None])                  # by the user: no reason
        self.assertTrue(prog.isVisible())
        self.assertFalse(prog.cancel_btn.isEnabled())
        prog.finish()
        self.assertFalse(prog.isVisible())

    def test_stops_itself_when_memory_runs_low(self):
        stopped = []
        prog = self.made(ExportProgress(None, "/tmp/x.mp4", "MP4", 100, stopped.append))
        prog.guard.low = lambda: (300 * 2 ** 20, 16 * 2 ** 30)
        prog._tick()
        self.assertEqual(len(stopped), 1)
        self.assertIn("300 MB", stopped[0])
        self.assertIn("記憶體", prog.stage.text())
        prog._tick()                                       # once only
        self.assertEqual(len(stopped), 1)
        prog.finish()

    def test_guard_floor(self):
        real = sysmem.available
        try:
            sysmem.available = lambda: (8 * 2 ** 30, 16 * 2 ** 30)
            g = sysmem.Guard()
            self.assertAlmostEqual(g.floor, 16 * 2 ** 30 * 0.05)         # 5%: 819 MB
            self.assertIsNone(g.low())
            sysmem.available = lambda: (700 * 2 ** 20, 16 * 2 ** 30)
            self.assertIsNotNone(g.low())
            sysmem.available = lambda: (600 * 2 ** 20, 4 * 2 ** 30)       # already low at the start:
            g = sysmem.Guard()                                            # half of what was free
            self.assertEqual(g.floor, 300 * 2 ** 20)
            self.assertIsNone(g.low())
            sysmem.available = lambda: None
            self.assertIsNone(sysmem.Guard().low())
        finally:
            sysmem.available = real

    def test_memory_numbers(self):
        if sys.platform.startswith("linux") or sys.platform == "win32":
            self.assertGreater(sysmem.used(), 0)
            free, total = sysmem.available()
            self.assertTrue(0 < free <= total)
        self.assertEqual(sysmem.gb(512 * 2 ** 20), "512 MB")
        self.assertEqual(sysmem.gb(3 * 2 ** 30), "3.0 GB")


if __name__ == "__main__":
    unittest.main()
