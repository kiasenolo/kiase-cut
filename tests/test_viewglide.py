"""viewglide: a view dragged with the middle button goes on a little after the button is let go, as it does after two fingers."""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut.ui import viewglide  # noqa: E402

APP = QApplication.instance() or QApplication([])


def flick(glide, px_per_s=1000.0, n=8, gap=0.01):
    """Samples of a pointer moving right at px_per_s, then released at once."""
    x = 0.0
    for _ in range(n):
        glide.sample(x, 0.0)
        QTest.qWait(int(gap * 1000))
        x += px_per_s * gap
    glide.sample(x, 0.0)


class ViewGlideTest(unittest.TestCase):
    def setUp(self):
        self.owner = QObject()
        self.moved = [0, 0]

    def make(self, scale=1.0):
        def move(dx, dy):
            self.moved[0] += dx
            self.moved[1] += dy
        return viewglide.ViewGlide(self.owner, move, scale=scale)

    def test_a_flick_goes_on_in_its_direction_and_stops(self):
        g = self.make()
        flick(g)
        g.release()
        self.assertTrue(g.running())
        QTest.qWait(1800)
        self.assertFalse(g.running())
        self.assertGreater(self.moved[0], 120)                 # (on past where it was let go)
        self.assertEqual(self.moved[1], 0)

    def test_half_the_scale_is_about_half_the_way(self):
        a = self.make(1.0)
        flick(a)
        a.release()
        QTest.qWait(1800)
        full = self.moved[0]
        self.moved = [0, 0]
        b = self.make(0.5)
        flick(b)
        b.release()
        QTest.qWait(1800)
        self.assertTrue(0.3 * full < self.moved[0] < 0.7 * full, (self.moved[0], full))

    def test_a_pointer_that_stopped_before_the_release_does_not_glide(self):
        g = self.make()
        flick(g)
        QTest.qWait(200)
        g.release()
        self.assertFalse(g.running())

    def test_a_slow_drag_does_not_glide(self):
        g = self.make()
        flick(g, px_per_s=20.0)
        g.release()
        self.assertFalse(g.running())

    def test_stop_ends_it(self):
        g = self.make()
        flick(g)
        g.release()
        QTest.qWait(60)
        g.stop()
        n = self.moved[0]
        QTest.qWait(100)
        self.assertEqual(self.moved[0], n)


class TimelineGlideTest(unittest.TestCase):
    def test_the_timeline_goes_on_after_a_middle_drag_and_by_half_as_much(self):
        from kiasecut.ui.timeline import GLIDE_SCALE, Timeline
        from test_tracks import proj
        self.assertEqual(GLIDE_SCALE, 0.5)
        tl = Timeline()
        tl.resize(900, 400)
        p = proj()
        p["duration_us"] = 600_000_000
        tl.set_project(p)
        tl.px_per_s, tl.scroll_s = 100.0, 100.0
        tl.show()
        QTest.qWait(60)
        QTest.mouseMove(tl, QPoint(500, 200))
        QTest.mousePress(tl, Qt.MiddleButton, Qt.NoModifier, QPoint(500, 200))
        x = 500
        for _ in range(10):
            x -= 12
            QTest.mouseMove(tl, QPoint(x, 200))
            QTest.qWait(10)
        at_release = tl.scroll_s
        QTest.mouseRelease(tl, Qt.MiddleButton, Qt.NoModifier, QPoint(x, 200))
        self.assertTrue(tl.glide.running())
        QTest.qWait(1800)
        self.assertGreater(tl.scroll_s, at_release + 0.5)        # (dragged left: the view goes on to later times)
        tl.close()


if __name__ == "__main__":
    unittest.main()
