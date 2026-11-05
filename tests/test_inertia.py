"""慣性設定: global or separate amounts; 0 = no glide."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut.ui import inertia  # noqa: E402
from kiasecut.ui.zoomglide import ZoomGlide  # noqa: E402

APP = QApplication.instance() or QApplication([])


class InertiaTests(unittest.TestCase):
    def setUp(self):
        self.was = dict(inertia.state)

    def tearDown(self):
        inertia.state.update(self.was)

    def test_global_and_separate(self):
        inertia.state.update(separate=False, all=50, preview_zoom=200)
        self.assertEqual(inertia.percent("preview_zoom"), 50)
        self.assertAlmostEqual(inertia.half_life_ms("preview_zoom"), 27.5)
        inertia.state["separate"] = True
        self.assertEqual(inertia.percent("preview_zoom"), 200)

    def test_save_and_load(self):
        path = os.path.join(os.environ.get("TMPDIR", "/tmp"), "kc_inertia_test.ini")
        s = QSettings(path, QSettings.IniFormat)
        inertia.state.update(separate=True, all=30, scroll=0, drag=250)
        inertia.save(s)
        inertia.state.update(separate=False, all=100, scroll=100, drag=100)
        inertia.load(s)
        self.assertEqual((inertia.state["separate"], inertia.state["all"], inertia.state["scroll"], inertia.state["drag"]),
                         (True, 30, 0, 250))
        os.remove(path)

    def test_zero_zooms_at_once(self):
        got = []
        g = ZoomGlide(None, lambda k, at: got.append(k), "node_zoom")
        inertia.state.update(separate=True, node_zoom=0)
        g.add(2.0, None)
        self.assertEqual(got, [2.0])
        self.assertFalse(g.timer.isActive())


if __name__ == "__main__":
    unittest.main()
