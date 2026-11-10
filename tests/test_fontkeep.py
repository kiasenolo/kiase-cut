"""fontkeep: every font a painter is given is held (its newest KEPT), so that what it loaded stays loaded; and appevents'
watchers that go first."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject  # noqa: E402
from PySide6.QtGui import QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from kiasecut.ui import appevents, fontkeep  # noqa: E402

APP = QApplication.instance() or QApplication([])


class FontKeepTests(unittest.TestCase):
    def setUp(self):
        fontkeep.install()
        self.addCleanup(fontkeep.uninstall)
        self.img = QImage(64, 64, QImage.Format_ARGB32_Premultiplied)

    def test_a_painters_fonts_are_kept_once_each(self):
        p = QPainter(self.img)
        for _ in range(3):
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(4, 20, "片段 clip")
        bold = QFont("Segoe UI", 8, QFont.Bold)
        p.setFont(bold)
        self.assertEqual(p.font().weight(), QFont.Bold)                  # (the painter has the font, as ever)
        p.end()
        self.assertEqual(list(fontkeep._kept), [QFont("Segoe UI", 8).key(), bold.key()])

    def test_the_newest_are_kept(self):
        p = QPainter(self.img)
        for size in range(1, fontkeep.KEPT + 6):
            p.setFont(QFont("Segoe UI", size))
        p.setFont(QFont("Segoe UI", 6))                                  # (used again: not the oldest any more)
        p.setFont(QFont("Segoe UI", fontkeep.KEPT + 6))
        p.end()
        self.assertEqual(len(fontkeep._kept), fontkeep.KEPT)
        self.assertIn(QFont("Segoe UI", 6).key(), fontkeep._kept)
        self.assertNotIn(QFont("Segoe UI", 7).key(), fontkeep._kept)

    def test_uninstall_puts_the_painter_back(self):
        fontkeep.uninstall()
        p = QPainter(self.img)
        p.setFont(QFont("Segoe UI", 8))
        p.end()
        self.assertEqual(len(fontkeep._kept), 0)


class FirstWatcherTests(unittest.TestCase):
    def test_those_that_go_first_come_before_newer_ones(self):
        owner, seen = QObject(), []
        late = QObject()
        self.addCleanup(appevents.unwatch, owner)
        self.addCleanup(appevents.unwatch, late)
        appevents.watch(owner, [QEvent.User], lambda o, e: seen.append("first a") and False, first=True)
        appevents.watch(owner, [QEvent.User], lambda o, e: seen.append("plain") and False)
        appevents.watch(owner, [QEvent.User], lambda o, e: seen.append("first b") and False, first=True)
        appevents.watch(late, [QEvent.User], lambda o, e: seen.append("newer plain") and False)
        w = QWidget()
        APP.sendEvent(w, QEvent(QEvent.User))
        self.assertEqual(seen, ["first b", "first a", "newer plain", "plain"])
        appevents.unwatch(owner)
        del seen[:]
        APP.sendEvent(w, QEvent(QEvent.User))
        self.assertEqual(seen, ["newer plain"])


if __name__ == "__main__":
    unittest.main()
