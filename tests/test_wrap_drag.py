"""Endless drags (無邊界): the pointer reaching an edge jumps to the other one and the drag goes
on - number fields, the timeline (whose view follows) and the curve editor. The pointer is not
really moved here: the jump is played by sending the next moves where it was sent."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

from kiasecut.ui import wrapdrag  # noqa: E402
from kiasecut.ui.curve_editor import CurveCanvas  # noqa: E402
from kiasecut.ui.inspector import SpinBox  # noqa: E402
from kiasecut.ui.preview import Preview  # noqa: E402
from kiasecut.ui.timeline import RULER_H, Timeline  # noqa: E402
from test_edit import proj as edit_proj  # noqa: E402
from test_tracks import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
NONE = Qt.KeyboardModifier.NoModifier


class Cursor:
    """Stands in for QCursor: remembers where the pointer was sent (or refuses to move it)."""
    sent = []

    @classmethod
    def setPos(cls, p):
        cls.sent.append(QPoint(p))


def send(w, kind, g, button=Qt.LeftButton):
    """A mouse event at global point g, to widget w."""
    g = QPointF(g)
    buttons = Qt.NoButton if kind == QEvent.MouseButtonRelease else button
    ev = QMouseEvent(kind, w.mapFromGlobal(g), g, Qt.NoButton if kind == QEvent.MouseMove else button,
                     buttons, NONE)
    QApplication.sendEvent(w, ev)


class Hand:
    """Moves the pointer by steps, jumping where the drag sends it (as the system would)."""

    def __init__(self, w, start, button=Qt.LeftButton):
        self.w, self.g, self.button = w, QPointF(start), button
        Cursor.sent = []
        send(w, QEvent.MouseButtonPress, self.g, button)

    def move(self, dx, dy, steps=1):
        for _ in range(steps):
            self.g += QPointF(dx, dy)
            send(self.w, QEvent.MouseMove, self.g, self.button)
            if Cursor.sent:
                self.g = QPointF(Cursor.sent.pop())             # the jump arrives

    def release(self):
        send(self.w, QEvent.MouseButtonRelease, self.g, self.button)
        if Cursor.sent:
            self.g = QPointF(Cursor.sent.pop())             # put back where the drag ended up


def hidden():
    c = QGuiApplication.overrideCursor()
    return c is not None and c.shape() == Qt.BlankCursor


class WrapTests(unittest.TestCase):
    def setUp(self):
        self.real = wrapdrag.QCursor
        wrapdrag.QCursor = Cursor
        Cursor.sent = []

    def tearDown(self):
        wrapdrag.QCursor = self.real

    def test_goes_on_past_the_edge(self):
        w = QWidget()
        w.resize(300, 200)
        wd = wrapdrag.WrapDrag(w, axes="x")
        wd.start()
        g0 = w.mapToGlobal(QPointF(150, 100))
        xs = []
        g = QPointF(g0)
        for _ in range(60):                                     # 600 px right in a 300 px window
            g += QPointF(10, 0)
            xs.append(wd.pos(QMouseEvent(QEvent.MouseMove, w.mapFromGlobal(g), g, Qt.NoButton,
                                         Qt.LeftButton, NONE)).x())
            if Cursor.sent:
                g = QPointF(Cursor.sent.pop())
        self.assertTrue(wd.wrapped)
        self.assertEqual(xs, [150 + 10 * (i + 1) for i in range(60)])

    def test_moves_from_before_the_jump(self):
        """A move Qt had queued before the jump still reads where it was."""
        w = QWidget()
        w.resize(300, 200)
        wd = wrapdrag.WrapDrag(w, axes="x")
        wd.start()
        ev = lambda x: QMouseEvent(QEvent.MouseMove, QPointF(x, 50), w.mapToGlobal(QPointF(x, 50)), Qt.NoButton,
                                   Qt.LeftButton, NONE)
        Cursor.sent = []
        self.assertEqual(wd.pos(ev(299)).x(), 299)             # the edge: sent left
        to = w.mapFromGlobal(QPointF(Cursor.sent.pop())).x()
        self.assertLess(to, 10)
        self.assertEqual(wd.pos(ev(300)).x(), 300)             # (queued before it)
        self.assertEqual(wd.pos(ev(to + 2)).x(), 299 - to + to + 2)   # arrived: counts on from 299

    def test_a_pointer_that_cannot_move_stops_at_the_edge(self):
        w = QWidget()
        w.resize(300, 200)
        wd = wrapdrag.WrapDrag(w, axes="x")
        wd.start()
        ev = lambda x: QMouseEvent(QEvent.MouseMove, QPointF(x, 50), w.mapToGlobal(QPointF(x, 50)), Qt.NoButton,
                                   Qt.LeftButton, NONE)
        for _ in range(wrapdrag.PATIENCE + 3):
            self.assertEqual(wd.pos(ev(299)).x(), 299)
        self.assertTrue(wd.stuck)
        self.assertFalse(wd.wrapped)

    def test_number_field(self):
        win = QWidget()
        win.resize(200, 120)
        s = SpinBox()
        s.set_limits(-1000.0, 1000.0)
        s.setSingleStep(1.0)
        s.setDecimals(0)
        QVBoxLayout(win).addWidget(s)
        win.show()
        s.show_value(0)
        le = s.lineEdit()
        hand = Hand(le, le.mapToGlobal(QPointF(le.width() / 2, le.height() / 2)))
        start = QPointF(hand.g)
        hand.move(0, -4, 100)                                   # 400 px up in a 120 px window
        self.assertTrue(hidden())
        hand.release()
        self.assertFalse(hidden())
        self.assertEqual(s.value(), 200)                        # (a step per 2 px)
        self.assertEqual(hand.g, start)                         # the pointer back on the field

    def test_timeline_seek_and_view_follow(self):
        tl = Timeline()
        tl.resize(900, 300)
        p = proj()
        p["duration_us"] = 600 * 1_000_000
        tl.set_project(p)
        tl.px_per_s, tl.scroll_s = 100.0, 0.0
        frames = []
        tl.seekRequested.connect(frames.append)
        hand = Hand(tl, tl.mapToGlobal(QPointF(400, RULER_H / 2)))        # the ruler
        hand.move(20, 0, 100)                                   # 2000 px right: 20 s on
        hand.release()
        self.assertAlmostEqual(frames[-1] / tl.fps, tl._sec(400) - tl.scroll_s + 20, delta=0.1)
        self.assertGreater(tl.scroll_s, 10)                      # the view went along
        self.assertLess(tl._x(frames[-1] / tl.fps), tl.width() + 1)   # the playhead in sight
        self.assertFalse(tl.wrap.on)
        self.assertFalse(hidden())
        at = tl.mapFromGlobal(hand.g)                            # the pointer back at the playhead
        self.assertAlmostEqual(tl._sec(at.x()), frames[-1] / tl.fps, delta=0.1)

    def test_timeline_pan_is_endless(self):
        tl = Timeline()
        tl.resize(900, 300)
        tl.set_project(proj())
        tl.px_per_s, tl.scroll_s = 100.0, 50.0
        hand = Hand(tl, tl.mapToGlobal(QPointF(500, 150)), Qt.MiddleButton)
        hand.move(20, 0, 100)                                   # 2000 px: 20 s back
        hand.release()
        self.assertAlmostEqual(tl.scroll_s, 30.0, places=6)

    def test_curve_key_keeps_in_view(self):
        """A keyframe dragged up past the plot: the value goes on, the view follows it."""
        S = 1_000_000
        cv = CurveCanvas()
        cv.resize(800, 400)
        cv.normalize = False
        keys = [[0, 0.0, 0, 0, 0, 0], [2 * S, 100.0, 0, 0, 0, 0]]
        cv.set_curves([{"label": "x", "factor": 1.0, "keys": keys, "static": 0.0}], 2 * S, 30.0, 0)
        got = []
        cv.keysCommitted.connect(got.append)
        hand = Hand(cv, cv.mapToGlobal(cv.key_point(0, 1)))
        lo, hi = cv.vrange
        hand.move(0, -10, 200)                                  # 2000 px up in a 400 px canvas
        hand.release()
        per_px = (hi - lo) / (cv.height() - cv.T - cv.B)
        self.assertAlmostEqual(got[-1][0][1][1][1], 100.0 + 2000 * per_px, delta=per_px * 2)
        p = cv.key_point(0, 1)
        self.assertTrue(cv.T - 1 <= p.y() <= cv.height() - cv.B + 1)

    def test_preview_move_goes_on_and_view_follows(self):
        pv = Preview()
        pv.resize(960, 540)                                    # the 1920 x 1080 canvas at half size
        pv.set_scene(edit_proj(), 500_000, "c1")
        got = []
        pv.movesCommitted.connect(lambda v: got.append(("moves", v)))
        pv.paramsCommitted.connect(lambda cid, g, v: got.append((g, v)))
        hand = Hand(pv, pv.mapToGlobal(QPointF(480, 270)))     # the clip's middle
        hand.move(20, 0, 100)                                  # 2000 screen px right: 4000 canvas px
        hand.release()
        vals = got[-1][1]
        x = vals["c1"]["x"] if got[-1][0] == "moves" else vals["x"]
        self.assertAlmostEqual(x, 4000 / 960, delta=0.05)      # (x: half canvas widths from the middle)
        self.assertLess(pv.pan.x(), -1500)                     # the view went along
        self.assertFalse(pv.wrap.on)

    def test_preview_pan_is_endless(self):
        pv = Preview()
        pv.resize(960, 540)
        pv.set_scene(edit_proj(), 500_000, "c1")
        hand = Hand(pv, pv.mapToGlobal(QPointF(480, 270)), Qt.MiddleButton)
        hand.move(0, 15, 100)                                  # 1500 px down in a 540 px preview
        hand.release()
        self.assertAlmostEqual(pv.pan.y(), 1500, places=6)

    def test_shown_again_when_a_drag_is_dropped(self):
        """A drag its widget dropped without stop(): the pointer shows at the next release."""
        w = QWidget()
        w.resize(300, 200)
        wd = wrapdrag.WrapDrag(w)
        wd.start()
        g = w.mapToGlobal(QPointF(100, 100))
        wd.pos(QMouseEvent(QEvent.MouseMove, QPointF(100, 100), g, Qt.NoButton, Qt.LeftButton, NONE))
        self.assertTrue(hidden())
        send(w, QEvent.MouseButtonRelease, g)
        self.assertFalse(hidden())

    def test_a_click_does_not_hide(self):
        s = SpinBox()
        s.show()
        le = s.lineEdit()
        g = le.mapToGlobal(QPointF(5, 5))
        send(le, QEvent.MouseButtonPress, g)
        self.assertFalse(hidden())
        send(le, QEvent.MouseButtonRelease, g)
        self.assertFalse(hidden())


if __name__ == "__main__":
    unittest.main()
