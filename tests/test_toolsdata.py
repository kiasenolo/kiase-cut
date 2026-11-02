"""The extra tools' data (toolsdata.py): my cubic-bezier curves, colour cards with Info, and a
card's colours exported / imported as a JSON string[]."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from kiasecut import toolsdata  # noqa: E402


class ToolsDataTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_curves(self):
        self.assertEqual(toolsdata.load_curves(self.root), [])
        toolsdata.save_curves(self.root, [{"name": "彈跳", "value": [0.34, 1.56, 0.64, 1]}])
        self.assertTrue(toolsdata.curves_file(self.root).endswith(os.path.join("tools", "cubic-bezier-tools", "curves.json")))
        self.assertEqual(toolsdata.load_curves(self.root), [{"name": "彈跳", "value": [0.34, 1.56, 0.64, 1.0]}])
        self.assertEqual(toolsdata.bezier_text([0.34, 1.56, 0.64, 1.0]), "cubic-bezier(0.34, 1.56, 0.64, 1)")

    def test_cards(self):
        path = toolsdata.save_card(self.root, {"name": "海邊", "info": "夏天", "colors": ["#1E90FF", "nope", "#ffd70080"]})
        self.assertEqual(os.path.dirname(path), toolsdata.palette_dir(self.root))
        card, = toolsdata.load_cards(self.root)
        self.assertEqual((card["name"], card["info"], card["colors"]), ("海邊", "夏天", ["#1e90ff", "#ffd70080"]))
        out = os.path.join(self.root, "x.json")
        toolsdata.export_colors(card, out)
        with open(out, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), ["#1e90ff", "#ffd70080"])
        self.assertEqual(toolsdata.import_colors(out), ["#1e90ff", "#ffd70080"])
        toolsdata.save_card(self.root, {"name": "海邊", "info": "", "colors": []})       # a second of the same name
        self.assertEqual(len(toolsdata.load_cards(self.root)), 2)
        with open(out, "w") as fh:
            json.dump([1, 2], fh)
        with self.assertRaises(ValueError):
            toolsdata.import_colors(out)


class BezierPlayTests(unittest.TestCase):
    def test_nothing_moves_until_play_is_pressed(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from kiasecut.ui.tools import BezierTool
        APP = QApplication.instance() or QApplication([])
        tool = BezierTool(lambda: tempfile.mkdtemp())
        pv = tool.preview
        self.assertFalse(pv.timer.isActive())                       # (at rest at the start, no timer running)
        self.assertEqual((pv.k, pv.playing()), (0.0, False))
        QTest.qWait(60)
        self.assertEqual(pv.k, 0.0)
        tool.seconds.setValue(0.2)
        self.assertEqual(pv.seconds, 0.2)
        done = []
        pv.finished.connect(lambda: done.append(1))
        tool.play_btn.click()
        self.assertTrue(pv.playing())
        QTest.qWait(80)
        self.assertTrue(0.0 < pv.k < 1.0)                           # (on its way)
        QTest.qWait(400)
        self.assertEqual((pv.k, pv.playing(), done, pv.timer.isActive()), (1.0, False, [1], False))
        tool.play_btn.click()                                       # (again from the start)
        self.assertLess(pv.k, 0.5)
        pv.reset()
        self.assertEqual((pv.k, pv.timer.isActive()), (0.0, False))
        tool.close()


class BezierDragTests(unittest.TestCase):
    def test_shift_keeps_a_handle_to_one_direction(self):
        from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from kiasecut.ui.tools import BezierField
        APP = QApplication.instance() or QApplication([])
        f = BezierField()
        f.resize(300, 600)
        f.set_value([0.42, 0.0, 0.58, 1.0])
        start = f.at(0.42, 0.0).toPoint()

        def move(to, mods=Qt.NoModifier):
            f.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(to), f.mapToGlobal(QPointF(to)), Qt.NoButton,
                                         Qt.LeftButton, mods))
        QTest.mousePress(f, Qt.LeftButton, Qt.NoModifier, start)
        move(start + QPoint(30, -10), Qt.ShiftModifier)                    # mostly across: the height stays
        self.assertGreater(f.v[0], 0.42)
        self.assertEqual(f.v[1], 0.0)
        move(start + QPoint(5, -60), Qt.ShiftModifier)                     # mostly up: the place across stays
        self.assertEqual(f.v[0], 0.42)
        self.assertGreater(f.v[1], 0.0)
        move(start + QPoint(30, -60))                                      # no Shift: free
        self.assertGreater(f.v[0], 0.42)
        self.assertGreater(f.v[1], 0.0)
        QTest.mouseRelease(f, Qt.LeftButton, Qt.NoModifier, start)
        self.assertEqual(f.v[2:], [0.58, 1.0])                             # (the other handle did not move)


if __name__ == "__main__":
    unittest.main()
