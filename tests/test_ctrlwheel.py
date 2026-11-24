"""Ctrl + the wheel over a number box, a check box or a combo box changes it (ui/ctrlwheel.py)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt  # noqa: E402
QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, tempfile.mkdtemp())
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QSpinBox, QVBoxLayout, QWidget  # noqa: E402

from kiasecut.ui import ctrlwheel  # noqa: E402
from kiasecut.ui.inspector import SpinBox  # noqa: E402

APP = QApplication.instance() or QApplication([])


def spin(w, delta, mods=Qt.ControlModifier):
    at = QPointF(w.width() / 2, w.height() / 2)
    ev = QWheelEvent(at, w.mapToGlobal(at.toPoint()), QPoint(0, 0), QPoint(0, delta), Qt.NoButton, mods, Qt.NoScrollPhase, False)
    QApplication.sendEvent(w, ev)


class CtrlWheelTests(unittest.TestCase):
    def setUp(self):
        ctrlwheel.install()
        self.host = QWidget()
        lay = QVBoxLayout(self.host)
        self.dbl, self.inspect, self.num, self.tick, self.combo = QDoubleSpinBox(), SpinBox(), QSpinBox(), QCheckBox("x"), QComboBox()
        self.dbl.setDecimals(3)
        self.inspect.setDecimals(3)
        self.inspect.setRange(-10, 10)
        self.dbl.setRange(-10, 10)
        self.combo.addItems(["a", "b", "c"])
        for w in (self.dbl, self.inspect, self.num, self.tick, self.combo):
            lay.addWidget(w)
        self.host.show()
        APP.processEvents()

    def tearDown(self):
        self.host.close()

    def test_a_number_goes_by_a_hundredth_a_notch_and_a_whole_number_by_one(self):
        for w in (self.dbl, self.inspect):
            spin(w, 120)
            self.assertAlmostEqual(w.value(), 0.01)
            spin(w, -240)
            self.assertAlmostEqual(w.value(), -0.01)
        spin(self.num, 120)
        self.assertEqual(self.num.value(), 1)

    def test_it_stops_at_the_limits(self):
        self.dbl.setValue(9.995)
        spin(self.dbl, 240)
        self.assertEqual(self.dbl.value(), 10)

    def test_without_ctrl_the_wheel_edits_nothing(self):
        spin(self.inspect, 120, Qt.NoModifier)
        self.assertEqual(self.inspect.value(), 0)

    def test_a_check_box_is_ticked_by_up_and_cleared_by_down(self):
        spin(self.tick, 120)
        self.assertTrue(self.tick.isChecked())
        spin(self.tick, 120)
        self.assertTrue(self.tick.isChecked())
        spin(self.tick, -120)
        self.assertFalse(self.tick.isChecked())

    def test_a_combo_box_goes_to_the_previous_and_next_choice(self):
        got = []
        self.combo.activated.connect(got.append)
        spin(self.combo, -120)
        self.assertEqual(self.combo.currentText(), "b")
        spin(self.combo, -120)
        spin(self.combo, -120)
        self.assertEqual(self.combo.currentText(), "c")
        spin(self.combo, 120)
        self.assertEqual(self.combo.currentText(), "b")
        self.assertEqual(got, [1, 2, 1])


if __name__ == "__main__":
    unittest.main()
