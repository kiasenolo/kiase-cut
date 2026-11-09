"""中鍵拖拽: the middle button drags anything that scrolls - the content follows the pointer, a
box with nothing to scroll hands the drag to the area it sits in, and the timeline keeps its own.
The drag is endless (無邊界): past the view's edge the pointer jumps to the other side and it goes on."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget  # noqa: E402

from kiasecut.ui import middledrag, wrapdrag  # noqa: E402
from kiasecut.ui.timeline import Timeline  # noqa: E402
from test_wrap_drag import Cursor, Hand, hidden  # noqa: E402

APP = QApplication.instance() or QApplication([])
NONE = Qt.KeyboardModifier.NoModifier


def drag(w, a, b, button=Qt.MiddleButton):
    QTest.mousePress(w, button, NONE, a)
    QTest.mouseMove(w, b)
    QTest.mouseRelease(w, button, NONE, b)


class _Count(QObject):
    def __init__(self, parent, got):
        super().__init__(parent)
        self.got = got

    def eventFilter(self, obj, e):
        if e.type() == QEvent.MouseButtonPress:
            self.got.append(e)
        return False


class MiddleDragTests(unittest.TestCase):
    def setUp(self):
        middledrag.install()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        self.box = QPlainTextEdit("short")
        self.box.setFixedHeight(80)
        lay.addWidget(self.box)
        self.label = QLabel("tall")
        self.label.setFixedHeight(2000)
        lay.addWidget(self.label)
        self.scroll.setWidget(inner)
        self.scroll.resize(300, 400)
        self.scroll.show()
        QTest.qWaitForWindowExposed(self.scroll)
        self.bar = self.scroll.verticalScrollBar()
        self.bar.setValue(500)

    def tearDown(self):
        self.scroll.close()

    def test_drag_up_scrolls_down(self):
        drag(self.label, QPoint(100, 600), QPoint(100, 480))
        self.assertEqual(self.bar.value(), 620)
        drag(self.label, QPoint(100, 600), QPoint(100, 650))
        self.assertEqual(self.bar.value(), 570)
        self.assertIsNone(QApplication.overrideCursor())

    def test_wheel_while_dragging_adds_to_the_drag(self):
        from PySide6.QtGui import QWheelEvent
        vp = self.scroll.viewport()                               # (the content moves under the pointer: use the view's own points)
        QTest.mousePress(vp, Qt.MiddleButton, NONE, QPoint(150, 250))
        QTest.mouseMove(vp, QPoint(150, 230))                     # +20
        elsewhere = QPointF(5, 5)                                 # (the pointer is not over the content)
        ev = QWheelEvent(elsewhere, vp.mapToGlobal(elsewhere), QPoint(0, 0), QPoint(0, -120),
                         Qt.NoButton, NONE, Qt.NoScrollPhase, False)
        APP.sendEvent(vp, ev)                                     # one notch down: 3 steps
        QTest.mouseMove(vp, QPoint(150, 220))                     # +10 more, on top of the wheel
        QTest.mouseRelease(vp, Qt.MiddleButton, NONE, QPoint(150, 220))
        self.assertEqual(self.bar.value(), 500 + 20 + 3 * self.bar.singleStep() + 10)

    def test_a_drag_that_lost_its_release_ends_and_keeps_the_next_press(self):
        vp = self.scroll.viewport()
        QTest.mousePress(vp, Qt.MiddleButton, NONE, QPoint(150, 250))
        QTest.mouseMove(vp, QPoint(150, 230))
        self.assertIsNotNone(QApplication.overrideCursor())
        got = []
        self.label.installEventFilter(_Count(self.label, got))
        QTest.mousePress(self.label, Qt.LeftButton, NONE, QPoint(10, 10))      # (the release never came)
        QTest.mouseRelease(self.label, Qt.LeftButton, NONE, QPoint(10, 10))
        self.assertIsNone(QApplication.overrideCursor())
        self.assertTrue(got)                                                   # (the press reached its widget)

    def test_box_without_scroll_hands_it_on(self):
        self.bar.setValue(0)
        drag(self.box.viewport(), QPoint(50, 40), QPoint(50, 10))
        self.assertEqual(self.bar.value(), 30)

    def test_box_that_scrolls_takes_it(self):
        self.box.setPlainText("\n".join(str(i) for i in range(200)))
        line = self.box.fontMetrics().lineSpacing()
        drag(self.box.viewport(), QPoint(50, 70), QPoint(50, 70 - 5 * line))
        self.assertEqual(self.box.verticalScrollBar().value(), 5)
        self.assertEqual(self.bar.value(), 500)

    def test_left_button_does_not_scroll(self):
        drag(self.label, QPoint(100, 600), QPoint(100, 480), Qt.LeftButton)
        self.assertEqual(self.bar.value(), 500)

    def test_endless(self):
        real, wrapdrag.QCursor = wrapdrag.QCursor, Cursor          # (the jumps are played, not made)
        try:
            self.bar.setValue(0)
            hand = Hand(self.label, self.label.mapToGlobal(QPointF(100, 300)), Qt.MiddleButton)
            hand.move(0, -20, 50)                                  # 1000 px up: past the view's top
            self.assertTrue(hidden())
            y = self.scroll.viewport().mapFromGlobal(hand.g).y()
            self.assertTrue(0 <= y <= self.scroll.viewport().height(), y)     # (it jumped, staying in the view)
            hand.release()
        finally:
            wrapdrag.QCursor = real
        self.assertEqual(self.bar.value(), 1000)
        self.assertFalse(hidden())
        self.assertIsNone(QApplication.overrideCursor())

    def test_timeline_keeps_its_middle_button(self):
        self.assertIsNone(middledrag._area_at(Timeline()))


class GlideTests(unittest.TestCase):
    """The content goes on a little after the middle button is let go, slowing down; a pause before the release, or a touch, stops it."""

    def setUp(self):
        middledrag.install()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.label = QLabel("tall")
        self.label.setFixedHeight(5000)
        self.scroll.setWidget(self.label)
        self.scroll.resize(300, 400)
        self.scroll.show()
        QTest.qWaitForWindowExposed(self.scroll)
        self.bar = self.scroll.verticalScrollBar()
        self.bar.setValue(1000)

    def tearDown(self):
        self.scroll.close()

    def flick(self, still=0):
        y0 = self.bar.value() + 300                                # (a point in the middle of the view, in the label's coordinates)
        QTest.mousePress(self.label, Qt.MiddleButton, NONE, QPoint(100, y0))
        for i in range(1, 7):
            QTest.qWait(15)
            QTest.mouseMove(self.label, QPoint(100, y0 - i * 20))
        if still:
            QTest.qWait(still)
        QTest.mouseRelease(self.label, Qt.MiddleButton, NONE, QPoint(100, y0 - 120))

    def test_it_goes_on_a_while_and_comes_to_rest(self):
        self.flick()
        at_release = self.bar.value()
        QTest.qWait(60)
        mid = self.bar.value()
        self.assertGreater(mid, at_release)                        # (going on, the way it was going)
        QTest.qWait(1500)
        end = self.bar.value()
        self.assertGreater(end, mid)
        QTest.qWait(200)
        self.assertEqual(self.bar.value(), end)                    # (and it stopped)
        self.assertLess(end - at_release, 600)                     # (a short glide)

    def test_a_pause_before_letting_go_gives_none(self):
        self.flick(still=150)
        at = self.bar.value()
        QTest.qWait(200)
        self.assertEqual(self.bar.value(), at)

    def test_the_wheel_stops_it(self):
        from PySide6.QtGui import QWheelEvent
        self.flick()
        QTest.qWait(40)
        e = QWheelEvent(QPointF(50, 50), QPointF(50, 50), QPoint(0, 0), QPoint(0, 0), Qt.NoButton, Qt.ShiftModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(self.scroll.viewport(), e)
        at = self.bar.value()
        QTest.qWait(200)
        self.assertEqual(self.bar.value(), at)

    def test_a_drag_at_the_end_of_the_content_does_not_run_past_it(self):
        self.bar.setValue(self.bar.maximum() - 30)
        self.flick()
        QTest.qWait(800)
        self.assertEqual(self.bar.value(), self.bar.maximum())


if __name__ == "__main__":
    unittest.main()
