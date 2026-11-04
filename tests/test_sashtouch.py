"""sashtouch: the line between panels by finger - held first (it goes white), then dragged; a swipe or a tap moves nothing."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDockWidget, QLabel, QMainWindow, QSplitter  # noqa: E402

from kiasecut.ui import look, sashtouch  # noqa: E402

APP = QApplication.instance() or QApplication([])
look.apply(APP)


def setUpModule():
    sashtouch.FORCE = True
    sashtouch.install()


def tearDownModule():
    sashtouch.uninstall()
    sashtouch.FORCE = False


class DockLineTests(unittest.TestCase):
    def setUp(self):
        self.w = QMainWindow()
        self.w.resize(800, 400)
        self.w.setCentralWidget(QLabel("centre"))
        self.dock = QDockWidget("left")
        self.dock.setWidget(QLabel("L"))
        self.dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.w.addDockWidget(Qt.LeftDockWidgetArea, self.dock)
        self.w.show()
        QTest.qWait(80)
        self.dev = QTest.createTouchDevice()
        self.x, self.y = self.dock.geometry().right() + 3, 200
        self.addCleanup(self.w.close)

    def finger(self, hold, dx):
        seq = QTest.touchEvent(self.w, self.dev)
        seq.press(0, QPoint(self.x, self.y), self.w).commit()
        if hold:
            QTest.qWait(sashtouch.HOLD_MS + 150)
        lit = []
        for i in (1, 2, 3, 4):
            seq.move(0, QPoint(self.x + dx * i // 4, self.y), self.w).commit()
            QTest.qWait(10)
            lit.append(sashtouch._watch.light is not None)
        seq.release(0, QPoint(self.x + dx, self.y), self.w).commit()
        QTest.qWait(30)
        return lit

    def test_the_line_is_found_between_the_panels(self):
        r = sashtouch.gap_rect(self.w, QPoint(self.x, self.y))
        self.assertIsNotNone(r)
        self.assertLessEqual(r.width(), sashtouch.THIN)
        self.assertEqual(r.height(), self.w.rect().height())

    def test_a_swipe_that_starts_on_the_line_moves_nothing(self):
        before = self.dock.width()
        lit = self.finger(False, 80)
        self.assertEqual(self.dock.width(), before)
        self.assertFalse(any(lit))

    def test_held_it_goes_white_and_is_then_dragged(self):
        before = self.dock.width()
        lit = self.finger(True, 80)
        self.assertTrue(all(lit))
        self.assertGreater(self.dock.width(), before + 40)
        self.assertIsNone(sashtouch._watch.light)                       # (the light goes out when the finger is lifted)

    def test_a_tap_moves_nothing_and_lights_nothing(self):
        before = self.dock.width()
        seq = QTest.touchEvent(self.w, self.dev)
        seq.press(0, QPoint(self.x, self.y), self.w).commit()
        seq.release(0, QPoint(self.x, self.y), self.w).commit()
        QTest.qWait(sashtouch.HOLD_MS + 100)
        self.assertEqual(self.dock.width(), before)
        self.assertIsNone(sashtouch._watch.light)

    def test_a_real_mouse_is_not_watched(self):
        QTest.mouseMove(self.w, QPoint(self.x, self.y))
        QTest.mousePress(self.w, Qt.LeftButton, Qt.NoModifier, QPoint(self.x, self.y))
        self.assertIsNone(sashtouch._watch.obj)                         # (no hold is waited for: a mouse is at once, as ever)
        QTest.mouseRelease(self.w, Qt.LeftButton, Qt.NoModifier, QPoint(self.x, self.y))


class SplitterTests(unittest.TestCase):
    def setUp(self):
        self.sp = QSplitter(Qt.Horizontal)
        self.sp.addWidget(QLabel("a"))
        self.sp.addWidget(QLabel("b"))
        self.sp.resize(600, 200)
        self.sp.show()
        QTest.qWait(80)
        self.handle = self.sp.handle(1)
        self.dev = QTest.createTouchDevice()
        self.addCleanup(self.sp.close)

    def finger(self, hold, dx):
        seq = QTest.touchEvent(self.handle, self.dev)
        c = self.handle.rect().center()
        seq.press(0, c, self.handle).commit()
        if hold:
            QTest.qWait(sashtouch.HOLD_MS + 150)
        for i in (1, 2, 3, 4):
            seq.move(0, c + QPoint(dx * i // 4, 0), self.handle).commit()
            QTest.qWait(10)
        seq.release(0, c + QPoint(dx, 0), self.handle).commit()
        QTest.qWait(30)

    def test_a_splitters_handle_is_held_first_too(self):
        w0 = self.sp.sizes()[0]
        self.finger(False, 80)
        self.assertEqual(self.sp.sizes()[0], w0)
        self.finger(True, 80)
        self.assertGreater(self.sp.sizes()[0], w0 + 40)


if __name__ == "__main__":
    unittest.main()
