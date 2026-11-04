"""touch.py: one finger is the mouse, two fingers pinch and scroll, a held finger lifted in place is a right click."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt  # noqa: E402
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

    def tearDown(self):
        self.g.glide.stop()
        self.w.removeEventFilter(self.g)
        self.w.close()
        self.w.deleteLater()

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

    def test_a_second_finger_soon_after_the_first_clicks_nothing(self):
        s = self.seq()
        s.press(0, QPoint(100, 100), self.w).commit()
        s.press(1, QPoint(200, 100), self.w).commit()
        self.assertEqual([x for x in self.w.log if x[0] in ("press", "release")], [])
        self.assertEqual(self.g.mode, "multi")

    def test_a_second_finger_ends_the_first_ones_mouse_press(self):
        s = self.seq()
        s.press(0, QPoint(100, 100), self.w).commit()
        self.g._press()                                         # (the timer's work: the press was due)
        s.press(1, QPoint(200, 100), self.w).commit()
        self.assertEqual([x for x in self.w.log if x[0] in ("press", "release")],
                         [("press", Qt.LeftButton), ("release", Qt.LeftButton)])
        self.assertEqual(self.g.mode, "multi")

    def test_a_tremble_moves_nothing_but_a_tap_is_a_click(self):
        s = self.seq()
        s.press(0, QPoint(100, 100), self.w).commit()
        s.move(0, QPoint(103, 102), self.w).commit()
        s.release(0, QPoint(103, 102), self.w).commit()
        self.assertEqual([x[0] for x in self.w.log if x[0] in ("press", "release", "move")], ["press", "release"])

    def test_two_taps_are_a_double_click(self):
        s = self.seq()
        kinds = []
        orig = self.w.event

        def watch(e):
            if e.type() == QEvent.MouseButtonDblClick:
                kinds.append("dbl")
            return orig(e)
        self.w.event = watch
        for _ in range(2):
            s.press(0, QPoint(100, 100), self.w).commit()
            s.release(0, QPoint(100, 100), self.w).commit()
        self.assertEqual(kinds, ["dbl"])
        s.press(0, QPoint(100, 100), self.w).commit()           # (a third tap starts over)
        s.release(0, QPoint(100, 100), self.w).commit()
        self.assertEqual(kinds, ["dbl"])

    def test_taps_far_apart_are_not_a_double_click(self):
        s = self.seq()
        s.press(0, QPoint(100, 100), self.w).commit()
        s.release(0, QPoint(100, 100), self.w).commit()
        s.press(0, QPoint(300, 200), self.w).commit()
        self.assertFalse(self.g.double)

    def test_two_and_three_finger_taps_call_what_was_set(self):
        got = []
        touch.on_tap(2, lambda: got.append(2))
        touch.on_tap(3, lambda: got.append(3))
        try:
            s = self.seq()
            s.press(0, QPoint(100, 100), self.w).press(1, QPoint(200, 100), self.w).commit()
            s.release(0, QPoint(100, 100), self.w).release(1, QPoint(200, 100), self.w).commit()
            s.press(0, QPoint(100, 100), self.w).press(1, QPoint(200, 100), self.w).press(2, QPoint(150, 150), self.w).commit()
            s.release(0, QPoint(100, 100), self.w).release(1, QPoint(200, 100), self.w).release(2, QPoint(150, 150), self.w).commit()
            self.assertEqual(got, [2, 3])
            s.press(0, QPoint(100, 100), self.w).press(1, QPoint(200, 100), self.w).commit()      # fingers that moved are no tap
            s.move(0, QPoint(100, 140), self.w).move(1, QPoint(200, 140), self.w).commit()
            s.release(0, QPoint(100, 140), self.w).release(1, QPoint(200, 140), self.w).commit()
            self.assertEqual(got, [2, 3])
        finally:
            touch._taps.clear()

    def test_a_scroll_that_ends_moving_glides_and_dies_away(self):
        s = self.seq()
        s.press(0, QPoint(100, 100), self.w).press(1, QPoint(200, 100), self.w).commit()
        for y in (130, 160, 190, 220):
            s.move(0, QPoint(100, y), self.w).move(1, QPoint(200, y), self.w).commit()
        s.release(0, QPoint(100, 220), self.w).release(1, QPoint(200, 220), self.w).commit()
        self.assertTrue(self.g.glide.isActive())
        self.w.log.clear()
        for _ in range(400):
            if not self.g.glide.isActive():
                break
            QTest.qWait(16)
        self.assertFalse(self.g.glide.isActive())
        moved = [x for x in self.w.log if x[0] == "wheel" and x[2] > 0]
        self.assertTrue(moved)

    def test_fingers_make_the_targets_bigger_and_a_mouse_makes_them_small_again(self):
        s = self.seq()
        s.press(0, QPoint(100, 100), self.w).commit()
        self.assertEqual(touch.scale(), touch.FINGER_SCALE)
        s.release(0, QPoint(100, 100), self.w).commit()
        QTest.mouseMove(self.w, QPoint(50, 50))
        QTest.mousePress(self.w, Qt.LeftButton, Qt.NoModifier, QPoint(50, 50))
        QTest.mouseRelease(self.w, Qt.LeftButton, Qt.NoModifier, QPoint(50, 50))
        self.assertEqual(touch.scale(), 1.0)

    def test_one_finger_is_press_move_release(self):
        s = self.seq()
        s.press(0, QPoint(100, 100), self.w).commit()
        s.move(0, QPoint(130, 105), self.w).commit()
        s.release(0, QPoint(130, 105), self.w).commit()
        self.assertEqual([x for x in self.w.log if x[0] in ("press", "release", "move")],
                         [("press", Qt.LeftButton), ("move", 130.0, 105.0), ("release", Qt.LeftButton)])
        self.assertEqual(self.g.mode, "idle")

    def test_a_finger_held_still_and_lifted_is_a_right_click(self):
        s = self.seq()
        s.press(0, QPoint(100, 100), self.w).commit()
        self.g._held()                                          # (the timer's work, without waiting for it)
        self.assertNotIn(("menu",), self.w.log)                 # (nothing yet: the finger is still down)
        s.move(0, QPoint(104, 101), self.w).commit()            # (a tremble is not a drag)
        self.assertEqual([x for x in self.w.log if x[0] == "move"], [])
        s.release(0, QPoint(104, 101), self.w).commit()
        kinds = [x for x in self.w.log if x[0] in ("press", "release", "menu")]
        self.assertEqual(kinds[-3:], [("press", Qt.RightButton), ("menu",), ("release", Qt.RightButton)])
        self.assertEqual(self.g.mode, "idle")

    def test_a_finger_held_and_moved_is_a_drag(self):
        s = self.seq()
        s.press(0, QPoint(100, 100), self.w).commit()
        self.g._held()
        s.move(0, QPoint(160, 100), self.w).commit()
        s.move(0, QPoint(180, 100), self.w).commit()
        s.release(0, QPoint(180, 100), self.w).commit()
        self.assertEqual([x[0] for x in self.w.log if x[0] in ("press", "move", "release", "menu")],
                         ["press", "move", "move", "release"])
        self.assertNotIn(("menu",), self.w.log)

    def test_moving_finger_is_not_a_hold(self):
        s = self.seq()
        s.press(0, QPoint(100, 100), self.w).commit()
        s.move(0, QPoint(140, 100), self.w).commit()
        self.assertFalse(self.g.hold.isActive())
        self.g._held()
        self.assertFalse(self.g.held)


class ScrollAreaTest(unittest.TestCase):
    """A list: one finger swipes it; held first, it drags (the press is made at the hold)."""

    def setUp(self):
        from PySide6.QtWidgets import QListWidget
        self.list = QListWidget()
        for i in range(200):
            self.list.addItem(f"item {i}")
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)       # (as wheel.Style makes every list)
        self.list.resize(200, 300)
        self.list.show()
        self.view = self.list.viewport()
        self.g = touch.enable(self.view, scroll=True)
        self.dev = QTest.createTouchDevice()
        self.log = []
        log = self.log

        class Watch(QObject):
            def eventFilter(self, obj, e):
                if e.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseMove, QEvent.ContextMenu):
                    log.append(e.type())
                return False
        self.watch = Watch(self.view)
        self.view.installEventFilter(self.watch)

    def tearDown(self):
        self.g.glide.stop()
        self.view.removeEventFilter(self.g)
        self.list.close()
        self.list.deleteLater()

    def seq(self):
        return QTest.touchEvent(self.view, self.dev)

    def test_a_swipe_scrolls_and_presses_nothing(self):
        s = self.seq()
        bar = self.list.verticalScrollBar()
        s.press(0, QPoint(100, 250), self.view).commit()
        for y in (230, 200, 150, 100):
            s.move(0, QPoint(100, y), self.view).commit()
        s.release(0, QPoint(100, 100), self.view).commit()
        self.assertGreater(bar.value(), 100)
        self.assertEqual(self.log, [])

    def test_a_tap_is_a_click(self):
        s = self.seq()
        s.press(0, QPoint(100, 50), self.view).commit()
        s.release(0, QPoint(100, 50), self.view).commit()
        self.assertEqual(self.log, [QEvent.MouseButtonPress, QEvent.MouseButtonRelease])
        self.assertEqual(self.list.currentRow(), 2)

    def test_hold_then_move_is_a_drag_not_a_scroll(self):
        s = self.seq()
        bar = self.list.verticalScrollBar()
        s.press(0, QPoint(100, 250), self.view).commit()
        self.g._held()                                          # (the timer's work)
        s.move(0, QPoint(100, 200), self.view).commit()
        s.move(0, QPoint(100, 150), self.view).commit()
        self.assertEqual(bar.value(), 0)
        self.assertEqual(self.log[0], QEvent.MouseButtonPress)
        self.assertIn(QEvent.MouseMove, self.log)

    def test_hold_then_lift_is_a_right_click(self):
        s = self.seq()
        s.press(0, QPoint(100, 50), self.view).commit()
        self.g._held()
        s.release(0, QPoint(100, 50), self.view).commit()
        self.assertEqual(self.log, [QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonPress,
                                    QEvent.ContextMenu, QEvent.MouseButtonRelease])

    def test_a_flick_glides(self):
        s = self.seq()
        bar = self.list.verticalScrollBar()
        s.press(0, QPoint(100, 280), self.view).commit()
        for y in (250, 220, 190, 160, 130):
            s.move(0, QPoint(100, y), self.view).commit()
        s.release(0, QPoint(100, 130), self.view).commit()
        at_lift = bar.value()
        self.assertTrue(self.g.glide.isActive())
        for _ in range(400):
            if not self.g.glide.isActive():
                break
            QTest.qWait(16)
        self.assertGreater(bar.value(), at_lift)

    def test_a_list_that_cannot_scroll_leaves_it_to_the_area_around_it(self):
        from PySide6.QtWidgets import QListWidget, QScrollArea, QVBoxLayout, QWidget
        outer = QScrollArea()
        outer.setWidgetResizable(True)
        body = QWidget()
        lay = QVBoxLayout(body)
        inner = QListWidget()
        for i in range(30):
            inner.addItem(f"item {i}")
        inner.setFixedHeight(900)                               # (as tall as its items: it has nothing to scroll)
        inner.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lay.addWidget(inner)
        outer.setWidget(body)
        outer.resize(300, 300)
        outer.show()
        g = touch.enable(inner.viewport(), scroll=True)
        view = inner.viewport()
        s = QTest.touchEvent(view, self.dev)
        s.press(0, QPoint(100, 250), view).commit()
        for y in (230, 200, 150, 100):
            s.move(0, QPoint(100, y), view).commit()
        s.release(0, QPoint(100, 100), view).commit()
        g.glide.stop()
        self.assertGreater(outer.verticalScrollBar().value(), 100)
        view.removeEventFilter(g)
        outer.close()

    def test_install_scrolling_covers_lists_shown_later_but_not_popups(self):
        from PySide6.QtWidgets import QListWidget
        touch.install_scrolling()
        late = QListWidget()
        late.show()
        self.assertTrue(late.viewport().property("kcTouch"))
        popup = QListWidget()
        popup.setWindowFlags(Qt.Popup)
        popup.show()
        self.assertFalse(popup.viewport().property("kcTouch"))
        late.close()
        popup.close()


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
