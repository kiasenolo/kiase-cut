"""How the mixer shows where sound goes, as FL Studio's does: with strips selected, lines run
under the strips from each of them to where it is sent; every other strip has a button at its
foot that makes or takes away the line to it, and beside a line's button a knob for its level."""
import math

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QToolTip, QWidget

from .. import soundfx

BAND = 30                       # the room under the strips the lines run in
LANE = 5                        # between the lines of two sources
LANES = 4
SHADES = (150, 195, 115, 175)   # lighter() of each source's colour: two of one colour still tell apart
KNOB_DB = (soundfx.SEND_OFF_DB, 12.0)


class Knob(QWidget):
    """A line's level: drag up and down (Shift: finely), double-click for 0 dB."""
    live = Signal(float)                    # dB, while dragging
    done = Signal(float)
    menu_asked = Signal(QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self.value = 0.0
        self.keyed = False
        self.drag = None                    # (y it was pressed at, value then)
        self.setCursor(Qt.SizeVerCursor)

    @staticmethod
    def text(db):
        return "不送" if db <= KNOB_DB[0] else f"{db:+.1f} dB"

    @staticmethod
    def _turn(db):
        """0 ... 1 round the dial: 0 dB three quarters of the way."""
        lo, hi = KNOB_DB
        return 0.75 * (db - lo) / -lo if db < 0 else 0.75 + 0.25 * db / hi

    def show_value(self, db, keyed=False):
        if self.drag is None:
            self.value = min(KNOB_DB[1], max(KNOB_DB[0], float(db)))
        self.keyed = keyed
        self.setToolTip("送出量 " + self.text(self.value))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(3, 3, 18, 18)
        p.setPen(QPen(QColor("#3a3a40"), 3, Qt.SolidLine, Qt.FlatCap))
        p.drawArc(r, 225 * 16, -270 * 16)
        turn = self._turn(self.value)
        p.setPen(QPen(QColor("#e0a030" if self.keyed else "#e8e8ea"), 3, Qt.SolidLine, Qt.FlatCap))
        p.drawArc(r, 225 * 16, int(-270 * 16 * turn))
        angle = math.radians(225 - 270 * turn)
        centre = r.center()
        p.setPen(QPen(QColor("#e8e8ea"), 2))
        p.drawLine(centre, centre + QPointF(math.cos(angle) * 6, -math.sin(angle) * 6))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.drag = (e.globalPosition().y(), self.value)
        e.accept()

    def mouseMoveEvent(self, e):
        if self.drag is None:
            return
        fine = 0.1 if e.modifiers() & Qt.ShiftModifier else 0.5
        v = self.drag[1] + (self.drag[0] - e.globalPosition().y()) * fine
        v = min(KNOB_DB[1], max(KNOB_DB[0], round(v, 1)))
        if v != self.value:
            self.value = v
            self.setToolTip("送出量 " + self.text(v))
            QToolTip.showText(e.globalPosition().toPoint(), self.text(v), self)
            self.update()
            self.live.emit(v)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.drag is not None:
            was, self.drag = self.drag[1], None
            if self.value != was:
                self.done.emit(self.value)

    def mouseDoubleClickEvent(self, e):
        self.drag = None
        self.value = 0.0
        self.update()
        self.done.emit(0.0)

    def wheelEvent(self, e):
        e.ignore()

    def contextMenuEvent(self, e):
        self.menu_asked.emit(e.globalPos())


class Cables(QWidget):
    """Laid over the mixer; clicks go through it. page.cables() says what to draw."""

    def __init__(self, page, mixer):
        super().__init__(mixer)
        self.page = page
        self.drop = None                    # x of the line shown where dragged strips would go
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        mixer.installEventFilter(self)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Resize:
            self.setGeometry(obj.rect())
        return False

    def _foot(self, strip):
        """The middle of a strip's bottom edge, here."""
        return self.mapFromGlobal(strip.mapToGlobal(QPoint(strip.width() // 2, strip.height())))

    def lines(self):
        """[(source target, destination target, colour, source x, destination x, lane y)] as
        they are drawn."""
        out = []
        sources, found, colours = self.page.cables()
        strips = self.page.strips
        if not found:
            return out
        base = max(self._foot(s).y() for s in strips.values())
        view = self.page.strip_area.viewport()
        left = self.mapFromGlobal(view.mapToGlobal(QPoint(0, 0))).x()
        right = left + view.width()

        def x_of(target):
            x = self._foot(strips[target]).x()
            return x if target[0] == "master" else min(right - 3, max(left + 3, x))    # (scrolled away: at the edge)
        for source, dest in found:
            if source not in strips or dest not in strips:
                continue
            i = sources.index(source)
            spread = ((i % LANES) - (min(len(sources), LANES) - 1) / 2) * 7
            out.append((source, dest, colours[source], x_of(source) + spread, x_of(dest) + spread,
                        base + 7 + LANE * (i % LANES)))
        return out

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        strips = self.page.strips
        for source, dest, colour, x1, x2, y in self.lines():
            c = QColor(colour).lighter(SHADES[self.page.sources().index(source) % len(SHADES)])
            p.setPen(QPen(c, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            a, b = self._foot(strips[source]).y(), self._foot(strips[dest]).y()
            p.drawPolyline(QPolygonF([QPointF(x1, a + 1), QPointF(x1, y), QPointF(x2, y), QPointF(x2, b + 6)]))
            p.setBrush(c)
            p.setPen(Qt.NoPen)
            p.drawPolygon(QPolygonF([QPointF(x2, b + 1), QPointF(x2 - 4.5, b + 8), QPointF(x2 + 4.5, b + 8)]))
            p.setBrush(Qt.NoBrush)
        if self.drop is not None:
            p.setPen(QPen(QColor("#ffffff"), 3))
            p.drawLine(QPointF(self.drop, 4), QPointF(self.drop, self.height() - BAND))
