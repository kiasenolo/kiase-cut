"""touch.py: one finger is the mouse, two fingers pinch and scroll, a held finger is a right click."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from kiasecut.ui import touch, wheel  # noqa: E402

APP = QApplication.instance() or QApplication([])


class Probe(QWidget):
    def __init__(self):
        super().__init__()
        self.resize(400, 300)
        self.log = []

    def event(self, e):
        t = e.type()
        if t in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            self.log.append(("press" if t == QEvent.MouseButtonPress else "release", e.button()))
        elif t == QEvent.ContextMenu:
            self.log.append(("menu",))
        elif t == QEvent.Wheel:
            self.log.append(("wheel", e.pixelDelta().x(), e.pixelDelta().y(), wheel.touchpad(e)))
        elif wheel.pinch(e) is not None:
            self.log.append(("pinch", round(wheel.pinch(e), 2)))
        elif t == QEvent.MouseMove:
            self.log.append(("move", e.position().x(), e.position().y()))
        return super().event(e)


class TouchTest(unittest.TestCase):
    def setUp(self):
        self.w = Probe()
        self.w.show()
        self.g = touch.enable(self.w)
        self.dev = QTest.createTouchDevice()

    def seq(self):
        return QTest.touchEvent(self.w, self.dev)

    def test_two_fingers_apart_pinch_out_and_together_scroll(self):
        s = self.seq()
        s.press(0, QPoint(100, 100), self.w).press(1, QPoint(200, 100), self.w).commit()
        s.move(0, QPoint(80, 100), self.w).move(1, QPoint(220, 100), self.w).commit()        # 100 px -> 140 px: 1.4x
        pinches = [x for x in self.w.log if x[0] == "pinch"]
        self.assertEqual(len(pinches), 1)
        self.assertAlmostEqual(pinches[0][1], 1.4, places=1)
        self.w.log.clear()
        s.move(0, QPoint(80, 130), self.w).move(1, QPoint(220, 130), self.w).commit()        # both fingers 30 px down
        scrolls = [x for x in self.w.log if x[0] == "wheel"]
        self.assertEqual(scrolls, [("wheel", 0, 30, True)])
        self.assertEqual([x for x in self.w.log if x[0] == "pinch"], [])
        s.release(0, QPoint(80, 130), self.w).release(1, QPoint(220, 130), self.w).commit()
        self.assertEqual(self.g.mode, "idle")

    def test_second_finger_ends_the_first_ones_mouse_press(self):
        s = self.seq()
        s.press(0, QPoint(100, 100), self.w).commit()
        s.press(1, QPoint(200, 100), self.w).commit()
        self.assertIn(("release", Qt.LeftButton), self.w.log)
        self.assertEqual(self.g.mode, "multi")

    def test_one_finger_is_press_move_release(self):
        s = self.seq()
        s.press(0, QPoint(100, 100), self.w).commit()
        s.move(0, QPoint(130, 105), self.w).commit()
        s.release(0, QPoint(130, 105), self.w).commit()
        self.assertEqual([x for x in self.w.log if x[0] in ("press", "release", "move")],
                         [("press", Qt.LeftButton), ("move", 130.0, 105.0), ("release", Qt.LeftButton)])
        self.assertEqual(self.g.mode, "idle")

    def test_a_finger_held_still_is_a_right_click(self):
        s = self.seq()
        s.press(0, QPoint(100, 100), self.w).commit()
        self.g._held()                                          # (the timer's work, without waiting for it)
        kinds = [x for x in self.w.log if x[0] in ("press", "release", "menu")]
        self.assertEqual(kinds[-3:], [("press", Qt.RightButton), ("menu",), ("release", Qt.RightButton)])
        self.assertEqual(self.g.mode, "hold")
        s.release(0, QPoint(100, 100), self.w).commit()
        self.assertEqual(self.g.mode, "idle")

    def test_moving_finger_is_not_a_hold(self):
        s = self.seq()
        s.press(0, QPoint(100, 100), self.w).commit()
        s.move(0, QPoint(140, 100), self.w).commit()
        self.assertFalse(self.g.timer.isActive())
        self.g._held()
        self.assertEqual(self.g.mode, "one")


class OnTheViews(unittest.TestCase):
    """The real views read what the helper sends."""

    def test_pinch_zooms_the_preview_and_two_fingers_move_it(self):
        from kiasecut.ui.preview import Preview
        pv = Preview()
        pv.resize(640, 360)
        pv.show()
        dev = QTest.createTouchDevice()
        s = QTest.touchEvent(pv, dev)
        z0 = pv.zoom
        s.press(0, QPoint(250, 180), pv).press(1, QPoint(350, 180), pv).commit()
        s.move(0, QPoint(200, 180), pv).move(1, QPoint(400, 180), pv).commit()               # twice as far apart
        self.assertAlmostEqual(pv.zoom / z0, 2.0, places=1)
        pan = QPointF(pv.pan)                                                                  # (+= changes a QPointF in place)
        s.move(0, QPoint(200, 230), pv).move(1, QPoint(400, 230), pv).commit()               # 50 px down
        self.assertEqual(pv.pan.y() - pan.y(), 50)
        s.release(0, QPoint(200, 230), pv).release(1, QPoint(400, 230), pv).commit()


if __name__ == "__main__":
    unittest.main()
