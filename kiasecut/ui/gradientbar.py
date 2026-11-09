"""A gradient editor like Photoshop's: a bar showing the gradient with a marker under it for each
colour stop. Click on or under the bar to add a stop (it takes the colour the gradient has there), drag a
marker to move it (it goes on past the others, which stay; the stops are in order of place again), double-click it (or 顏色) to change its colour and opacity, Delete or 刪除 removes it
(two stay). 位置 types the selected stop's place; 反轉 flips the gradient.

The value is a list of stops [[position 0 - 1, [r, g, b, a]], ...] in order (assets.stops_of).
"""
import copy

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from .colorpick import pick_color, qcolor, rgba

PAD = 10                           # room left and right of the bar for the end markers
BAR_H = 26
MARK = 11                          # a marker's half width


def _color(c):
    return QColor.fromRgbF(*[min(1.0, max(0.0, x)) for x in c])


def _at(stops, x):
    """The colour [r, g, b, a] of the gradient at x."""
    if x <= stops[0][0]:
        return list(stops[0][1])
    for (x0, c0), (x1, c1) in zip(stops, stops[1:]):
        if x <= x1:
            k = (x - x0) / (x1 - x0) if x1 > x0 else 0.0
            return [a + (b - a) * k for a, b in zip(c0, c1)]
    return list(stops[-1][1])


class GradientBar(QWidget):
    changed = Signal(list)         # the stops, while dragging and when done
    committed = Signal(list)
    selected = Signal()            # another stop is selected, or the selected one changed

    def __init__(self):
        super().__init__()
        self.stops = [[0.0, [1, 1, 1, 1]], [1.0, [0, 0, 0, 1]]]
        self.sel = 0
        self.dragging = False
        self.sampler = None            # (stops, x) -> rgba or None: a node's own interpolation drawn instead of the plain one
        self.setFixedHeight(BAR_H + MARK * 2 + 14)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setMouseTracking(True)

    def set_stops(self, stops):
        if self.dragging or self.stops == [[x, list(c)] for x, c in stops]:
            return                                              # (nothing new: keep the selection and the drag)
        self.stops = copy.deepcopy(stops)
        self.sel = min(self.sel, len(self.stops) - 1)
        self.update()

    # -- geometry -------------------------------------------------------------------------------------
    def bar(self):
        return QRectF(PAD, 4, self.width() - 2 * PAD, BAR_H)

    def x_of(self, pos):
        b = self.bar()
        return b.left() + pos * b.width()

    def pos_of(self, x):
        b = self.bar()
        return min(1.0, max(0.0, (x - b.left()) / max(b.width(), 1)))

    def marker_at(self, pos):
        y0 = self.bar().bottom()
        if not (y0 - 2 <= pos.y() <= y0 + MARK * 2 + 6):
            return None
        best = None
        for i, (p, _c) in enumerate(self.stops):
            d = abs(pos.x() - self.x_of(p))
            if d <= MARK and (best is None or d < best[0] or (d == best[0] and i == self.sel)):
                best = (d, i)
        return None if best is None else best[1]

    # -- painting -------------------------------------------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        b = self.bar()
        n = 6                                                  # (the checkerboard that shows opacity)
        for i in range(int(b.width() // n) + 1):
            for j in range(int(b.height() // n) + 1):
                p.fillRect(QRectF(b.left() + i * n, b.top() + j * n, n, n).intersected(b),
                           QColor("#cfcfcf") if (i + j) % 2 else QColor("#8a8a8a"))
        g = QLinearGradient(b.left(), 0, b.right(), 0)
        if self.sampler is not None and self.sampler(self.stops, 0.0) is not None:
            for i in range(65):
                g.setColorAt(i / 64, _color(self.sampler(self.stops, i / 64)))
        else:
            for x, c in self.stops:
                g.setColorAt(x, _color(c))
        p.fillRect(b, QBrush(g))
        p.setPen(QPen(QColor("#555"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(b)
        for i, (x, c) in enumerate(self.stops):
            cx, top = self.x_of(x), b.bottom() + 2
            tri = QPolygonF([QPointF(cx, top), QPointF(cx - 5, top + 7), QPointF(cx + 5, top + 7)])
            on = i == self.sel
            p.setPen(QPen(QColor("#ffb020") if on else QColor("#9a9aa0"), 1.5))
            p.setBrush(QColor("#232327"))
            p.drawPolygon(tri)
            box = QRectF(cx - 7, top + 7, 14, 14)
            p.setPen(QPen(QColor("#ffb020") if on else QColor("#9a9aa0"), 1.5))
            p.setBrush(_color([c[0], c[1], c[2], 1.0]))
            p.drawRect(box)

    # -- mouse ----------------------------------------------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pos = e.position()
        i = self.marker_at(pos)
        if i is None:
            if pos.y() < self.bar().top() or pos.y() > self.bar().bottom() + MARK * 2 + 6:
                return
            x = self.pos_of(pos.x())                           # a new stop, with the gradient's colour there
            self.stops.append([x, _at(self.stops, x)])
            self.stops.sort(key=lambda s: s[0])
            i = min(range(len(self.stops)), key=lambda k: abs(self.stops[k][0] - x))
            self.sel = i
            self.changed.emit(copy.deepcopy(self.stops))
            self.selected.emit()
        else:
            self.sel = i
            self.selected.emit()
        self.dragging = True
        self.update()

    def mouseMoveEvent(self, e):
        if not self.dragging:
            self.setCursor(Qt.PointingHandCursor if self.marker_at(e.position()) is not None else Qt.ArrowCursor)
            return
        self._place(round(self.pos_of(e.position().x()), 3))
        self.changed.emit(copy.deepcopy(self.stops))
        self.selected.emit()
        self.update()

    def _place(self, x):
        """The selected stop at x (0 - 1): it goes on past the others, which stay; the stops sort by place again."""
        stop = self.stops[self.sel]
        stop[0] = min(max(x, 0.0), 1.0)
        self.stops.sort(key=lambda s: s[0])                    # (a stable sort: a stop at another's place keeps its side)
        self.sel = next(i for i, s in enumerate(self.stops) if s is stop)

    def mouseReleaseEvent(self, _e):
        if self.dragging:
            self.dragging = False
            self.committed.emit(copy.deepcopy(self.stops))

    def mouseDoubleClickEvent(self, e):
        i = self.marker_at(e.position())
        if i is not None:
            self.sel = i
            self.pick()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.remove()
        else:
            super().keyPressEvent(e)

    # -- edits (also the buttons') ----------------------------------------------------------------------
    def remove(self):
        if len(self.stops) <= 2:
            return
        del self.stops[self.sel]
        self.sel = min(self.sel, len(self.stops) - 1)
        self.changed.emit(copy.deepcopy(self.stops))
        self.committed.emit(copy.deepcopy(self.stops))
        self.selected.emit()
        self.update()

    def pick(self, anchor=None):
        col = pick_color(self, qcolor(self._hex()), "漸變色的顏色", anchor=anchor or self)
        if col is not None:
            self.stops[self.sel][1] = rgba(col)
            self.changed.emit(copy.deepcopy(self.stops))
            self.committed.emit(copy.deepcopy(self.stops))
            self.selected.emit()
            self.update()

    def _hex(self):
        r, g, b, a = (round(min(1, max(0, x)) * 255) for x in self.stops[self.sel][1])
        return f"#{r:02x}{g:02x}{b:02x}" + (f"{a:02x}" if a < 255 else "")

    def reverse(self):
        self.stops = [[round(1 - x, 3), c] for x, c in reversed(self.stops)]
        self.sel = len(self.stops) - 1 - self.sel
        self.changed.emit(copy.deepcopy(self.stops))
        self.committed.emit(copy.deepcopy(self.stops))
        self.selected.emit()
        self.update()

    def move_selected(self, pct):
        self._place(pct / 100)
        self.changed.emit(copy.deepcopy(self.stops))
        self.committed.emit(copy.deepcopy(self.stops))
        self.selected.emit()
        self.update()


class GradientEditor(QWidget):
    """The bar with the selected stop's 位置 / 顏色 / 刪除 and 反轉 under it."""
    changed = Signal(list)

    def __init__(self, compact=False):
        """compact: for inside a node - the buttons are marks and the place box is narrow."""
        super().__init__()
        from .inspector import SpinBox                 # (the inspector builds this editor: imported late)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        self.bar = GradientBar()
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        row.setSpacing(3)
        self.place = SpinBox()
        self.place.set_limits(0, 100)
        self.place.setDecimals(1)
        self.place.setSuffix(" %")
        self.place.setKeyboardTracking(False)
        self.place.setToolTip("選取的色標的位置")
        self.color = QPushButton()
        self.color.setToolTip("選取的色標的顏色和透明度")
        remove = QPushButton("✕" if compact else "刪除")
        reverse = QPushButton("⇄" if compact else "反轉")
        if compact:
            self.place.setFixedWidth(62)
            self.color.setMinimumWidth(40)
            for b, tip in ((remove, "刪除選取的色標"), (reverse, "反轉色標的順序")):
                b.setToolTip(tip)
                b.setFixedWidth(26)
                b.setStyleSheet("padding: 4px 0;")
        for w in (self.place, self.color, remove, reverse):
            row.addWidget(w, 1 if w is self.color else 0)
        lay.addLayout(row)
        self.bar.selected.connect(self._show_sel)
        self.bar.changed.connect(self.changed.emit)
        self.bar.committed.connect(self.changed.emit)
        self.place.edited.connect(self._typed)
        self.color.clicked.connect(lambda: self.bar.pick(self.color))
        remove.clicked.connect(self.bar.remove)
        reverse.clicked.connect(self.bar.reverse)
        self._show_sel()

    @property
    def drag(self):
        return self.bar.dragging

    def set_stops(self, stops):
        self.bar.set_stops(stops)
        self._show_sel()

    @property
    def stops(self):
        return self.bar.stops

    def _typed(self, v):
        if abs(self.bar.stops[self.bar.sel][0] * 100 - v) > 0.05:
            self.bar.move_selected(v)

    def _show_sel(self):
        x, c = self.bar.stops[self.bar.sel]
        if not self.place.hasFocus():
            self.place.show_value(round(x * 100, 1))
        hexc = self.bar._hex()
        self.color.setText(hexc)
        self.color.setStyleSheet(f"background: {hexc[:7]}; color: {'#000' if QColor(hexc[:7]).lightness() > 140 else '#fff'};")
