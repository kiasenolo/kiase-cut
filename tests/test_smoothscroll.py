"""平滑捲動: a wheel notch glides the content to where it always went, notches in a row run together, and only areas that scroll as Qt does take part."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QGraphicsView, QLabel, QScrollArea  # noqa: E402

from kiasecut.ui import look  # noqa: E402

APP = QApplication.instance() or QApplication([])
look.apply(APP)


def wheel(w, dy, mods=Qt.NoModifier, phase=Qt.NoScrollPhase, pixel=QPoint(0, 0)):
    e = QWheelEvent(QPointF(50, 50), QPointF(50, 50), pixel, QPoint(0, dy), Qt.NoButton, mods, phase, False)
    APP.sendEvent(w.viewport(), e)
    return e.isAccepted()


def area(height=3000):
    sa = QScrollArea()
    lab = QLabel("x")
    lab.setFixedHeight(height)
    sa.setWidget(lab)
    sa.resize(300, 300)
    sa.show()
    QTest.qWait(50)
    return sa


class SmoothScrollTests(unittest.TestCase):
    def test_a_notch_takes_a_moment_and_arrives_where_the_wheel_always_took_it(self):
        sa = area()
        bar = sa.verticalScrollBar()
        goal = bar.singleStep() * APP.wheelScrollLines()
        self.assertTrue(wheel(sa, -120))
        self.assertLess(bar.value(), goal)                         # (not there at once)
        QTest.qWait(40)
        self.assertTrue(0 < bar.value() < goal)
        QTest.qWait(500)
        self.assertEqual(bar.value(), goal)
        sa.close()

    def test_notches_in_a_row_add_up(self):
        sa = area()
        bar = sa.verticalScrollBar()
        goal = bar.singleStep() * APP.wheelScrollLines()
        for _ in range(3):
            wheel(sa, -120)
            QTest.qWait(20)
        QTest.qWait(600)
        self.assertEqual(bar.value(), 3 * goal)
        wheel(sa, 120)
        QTest.qWait(600)
        self.assertEqual(bar.value(), 2 * goal)
        sa.close()

    def test_at_the_end_the_event_is_left_for_the_area_around(self):
        sa = area()
        self.assertFalse(wheel(sa, 120))                           # (already at the top)
        sa.verticalScrollBar().setValue(sa.verticalScrollBar().maximum())
        self.assertFalse(wheel(sa, -120))
        sa.close()

    def test_an_area_with_nothing_to_scroll_does_not_take_it(self):
        sa = area(height=50)
        self.assertFalse(wheel(sa, -120))
        sa.close()

    def test_a_touchpad_and_a_held_key_are_left_alone(self):
        sa = area()
        glide = sa.property("kcGlide")
        wheel(sa, -120, phase=Qt.ScrollUpdate, pixel=QPoint(0, -30))
        self.assertFalse(glide.timer.isActive())                   # (its own pixels move the content, as Qt does)
        sa.verticalScrollBar().setValue(0)
        wheel(sa, -120, mods=Qt.ControlModifier)
        self.assertFalse(glide.timer.isActive())
        sa.close()

    def test_an_area_that_handles_the_wheel_itself_is_not_taken_over(self):
        class Own(QGraphicsView):
            def wheelEvent(self, e):
                e.accept()
        own, plain = Own(), QGraphicsView()
        for v in (own, plain):
            v.show()
        QTest.qWait(30)
        self.assertIsNone(own.property("kcGlide"))
        self.assertIsNotNone(plain.property("kcGlide"))
        own.close()
        plain.close()

    def test_moving_the_bar_by_hand_in_the_middle_of_a_glide_wins(self):
        sa = area()
        bar = sa.verticalScrollBar()
        wheel(sa, -120)
        QTest.qWait(30)
        bar.setValue(500)
        QTest.qWait(300)
        self.assertEqual(bar.value(), 500)
        sa.close()


if __name__ == "__main__":
    unittest.main()
