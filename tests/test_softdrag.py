"""softdrag: the program's own drag and drop for a finger (the system's, on Android, takes the finger away from the program)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QListWidget, QWidget  # noqa: E402

from kiasecut.ui import look, softdrag, touch  # noqa: E402

APP = QApplication.instance() or QApplication([])
look.apply(APP)


def setUpModule():
    softdrag.FORCE = True
    softdrag.install()


def tearDownModule():
    softdrag.uninstall()
    softdrag.FORCE = False


_timers = []


def later(ms, fn):
    t = QTimer()
    t.setTimerType(Qt.PreciseTimer)                              # (coarse ones may fire out of order)
    t.setSingleShot(True)
    t.timeout.connect(fn)
    t.start(ms)
    _timers.append(t)


class Target(QLabel):
    def __init__(self, take=True):
        super().__init__("drop here")
        self.setAcceptDrops(True)
        self.take = take
        self.log = []

    def dragEnterEvent(self, e):
        self.log.append("enter")
        if self.take:
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        self.log.append("move")
        if self.take:
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.log.append("leave")

    def dropEvent(self, e):
        self.log.append(("drop", e.mimeData().text(), e.dropAction()))
        e.acceptProposedAction()


class Source(QListWidget):
    def mimeData(self, items):
        md = QMimeData()
        md.setText(",".join(i.text() for i in items))
        return md


class SoftDragTest(unittest.TestCase):
    def setUp(self):
        self.host = QWidget()
        lay = QHBoxLayout(self.host)
        self.src = Source()
        self.src.setDragEnabled(True)
        for i in range(30):
            self.src.addItem(f"item {i}")
        self.tgt = Target()
        lay.addWidget(self.src)
        lay.addWidget(self.tgt)
        self.host.resize(500, 300)
        self.host.show()
        QTest.qWait(80)
        touch.install_scrolling()
        self.host.hide()
        self.host.show()
        QTest.qWait(80)
        self.view = self.src.viewport()
        self.dev = QTest.createTouchDevice()
        self.addCleanup(self.host.close)

    def finger(self, steps, end):
        """Hold a finger on row 2 of the list, move it along `steps` points and lift it at `end` (all driven from timers, as the
        drag blocks the caller while it lasts); returns when it is all over."""
        seq = QTest.touchEvent(self.view, self.dev)
        start = self.src.visualItemRect(self.src.item(2)).center()
        t = 0
        later(t, lambda: seq.press(0, start, self.view).commit())
        t = 700                                                           # (the hold)
        for p in steps:
            later(t, lambda p=p: seq.move(0, p, self.view).commit())
            t += 40
        later(t + 60, lambda: seq.release(0, end, self.view).commit())
        later(t + 300, lambda: APP.exit(0))
        APP.exec()

    def over_target(self):
        return self.view.mapFromGlobal(self.tgt.mapToGlobal(self.tgt.rect().center()))

    def path_to(self, dest, n=10):
        c = self.src.visualItemRect(self.src.item(2)).center()
        return [QPoint(c.x() + (dest.x() - c.x()) * i // n, c.y() + (dest.y() - c.y()) * i // n) for i in range(1, n + 1)]

    def test_an_item_held_then_moved_onto_a_target_is_dropped_there(self):
        dest = self.over_target()
        self.finger(self.path_to(dest), dest)
        drops = [x for x in self.tgt.log if isinstance(x, tuple)]
        self.assertEqual(len(drops), 1)
        self.assertEqual(drops[0][1], "item 2")
        self.assertEqual(drops[0][2], Qt.CopyAction)
        self.assertIn("enter", self.tgt.log)
        self.assertIn("move", self.tgt.log)

    def test_lifted_off_a_target_there_is_no_drop_and_the_picture_is_gone(self):
        dest = self.over_target()
        path = self.path_to(dest) + [QPoint(30, 200)]                      # (the last move is back over the list, which takes no drops)
        self.finger(path, QPoint(30, 200))
        self.assertEqual([x for x in self.tgt.log if isinstance(x, tuple)], [])
        self.assertEqual(self.tgt.log[-1], "leave")
        ghosts = [w for w in self.host.findChildren(QLabel) if w is not self.tgt and w.pixmap() is not None and not w.pixmap().isNull()]
        QTest.qWait(50)
        self.assertEqual([w for w in ghosts if w.isVisible()], [])

    def test_a_target_that_takes_nothing_gets_no_drop(self):
        self.tgt.take = False
        dest = self.over_target()
        self.finger(self.path_to(dest), dest)
        self.assertEqual([x for x in self.tgt.log if isinstance(x, tuple)], [])

    def test_a_swipe_without_a_hold_still_scrolls_and_drags_nothing(self):
        seq = QTest.touchEvent(self.view, self.dev)
        seq.press(0, QPoint(50, 250), self.view).commit()
        for y in (230, 200, 150, 100):
            seq.move(0, QPoint(50, y), self.view).commit()
        seq.release(0, QPoint(50, 100), self.view).commit()
        self.assertGreater(self.src.verticalScrollBar().value(), 50)
        self.assertEqual(self.tgt.log, [])

    def test_the_action_is_the_default_one_when_it_is_allowed(self):
        self.assertEqual(softdrag.proposed(Qt.CopyAction | Qt.MoveAction, Qt.MoveAction), Qt.MoveAction)
        self.assertEqual(softdrag.proposed(Qt.CopyAction | Qt.MoveAction, Qt.LinkAction), Qt.CopyAction)
        self.assertEqual(softdrag.proposed(Qt.MoveAction, Qt.IgnoreAction), Qt.MoveAction)


if __name__ == "__main__":
    unittest.main()
