"""曲線變速's own editor (not the keyframe curves): the clip from its start (left) to its end
(right), the speed up the side in log scale (0.1x - 10x, 1x in the middle). Drag a point (the
first and last only up and down), double-click to add one, right-click one to take it away;
the clip's new length shows under it as the points move, and the edit is made on release."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import project

LO, HI = math.log(project.CURVE_MIN), math.log(project.CURVE_MAX)
GRID = (0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0)


class CurveField(QWidget):
    moved = Signal(list)                        # points while dragging
    committed = Signal(list)                    # points: the edit

    def __init__(self):
        super().__init__()
        self.points = [[0.0, 1.0], [1.0, 1.0]]
        self.drag = None
        self.playhead = None                     # 0 - 1 along the clip, or None
        self.setMinimumHeight(150)
        self.setMouseTracking(True)

    def area(self):
        return QRectF(34, 8, max(10, self.width() - 44), max(10, self.height() - 22))

    def to_px(self, u, s):
        r = self.area()
        return QPointF(r.left() + u * r.width(), r.bottom() - (math.log(s) - LO) / (HI - LO) * r.height())

    def from_px(self, p):
        r = self.area()
        u = min(1.0, max(0.0, (p.x() - r.left()) / r.width()))
        s = math.exp(LO + min(1.0, max(0.0, (r.bottom() - p.y()) / r.height())) * (HI - LO))
        return u, s

    def set_points(self, points):
        if self.drag is None:
            self.points = [list(p) for p in points]
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#18181b"))
        r = self.area()
        p.fillRect(r, QColor("#202024"))
        for s in GRID:
            y = self.to_px(0, s).y()
            p.setPen(QPen(QColor("#4a4a52" if s == 1.0 else "#2c2c31"), 1, Qt.SolidLine if s == 1.0 else Qt.DotLine))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(QColor("#8e8e94"))
            p.drawText(QRectF(0, y - 8, 30, 16), Qt.AlignRight | Qt.AlignVCenter, f"{s:g}x")
        path = QPainterPath()
        for k in range(201):
            u = k / 200
            q = self.to_px(u, project.curve_speed_at(self.points, u))
            path.moveTo(q) if k == 0 else path.lineTo(q)
        p.setPen(QPen(QColor("#6fb3ff"), 2.5))
        p.drawPath(path)
        if self.playhead is not None:
            x = r.left() + self.playhead * r.width()
            p.setPen(QPen(QColor("#e5484d"), 1))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        for i, (u, s) in enumerate(self.points):
            q = self.to_px(u, s)
            p.setPen(QPen(QColor("#ffffff"), 1.5))
            p.setBrush(QColor("#ffb347" if i == self.drag else "#6fb3ff"))
            p.drawEllipse(q, 6, 6)

    def _hit(self, pos):
        best = min(range(len(self.points)), key=lambda i: (self.to_px(*self.points[i]) - pos).manhattanLength())
        return best if (self.to_px(*self.points[best]) - pos).manhattanLength() <= 12 else None

    def mousePressEvent(self, e):
        i = self._hit(e.position())
        if e.button() == Qt.RightButton:
            if i is not None and 0 < i < len(self.points) - 1:
                del self.points[i]
                self.update()
                self.committed.emit([list(p) for p in self.points])
            return
        if e.button() == Qt.LeftButton and i is not None:
            self.drag = i
            self.update()

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.LeftButton or self._hit(e.position()) is not None:
            return
        u, _s = self.from_px(e.position())
        if 0.0 < u < 1.0:
            self.points.append([round(u, 4), round(project.curve_speed_at(self.points, u), 4)])
            self.points.sort()
            self.update()
            self.committed.emit([list(p) for p in self.points])

    def mouseMoveEvent(self, e):
        if self.drag is None:
            i = self._hit(e.position())
            self.setCursor(Qt.SizeAllCursor if i is not None else Qt.ArrowCursor)
            self.setToolTip(f"{self.points[i][1]:.2f}x" if i is not None else "")
            return
        u, s = self.from_px(e.position())
        i = self.drag
        if i == 0 or i == len(self.points) - 1:
            u = self.points[i][0]                          # (the ends stay at the clip's start and end)
        else:
            u = min(self.points[i + 1][0] - 0.01, max(self.points[i - 1][0] + 0.01, u))
        if abs(math.log(s)) < 0.04:                        # (1x snaps)
            s = 1.0
        self.points[i] = [round(u, 4), round(s, 4)]
        self.update()
        self.moved.emit([list(p) for p in self.points])

    def mouseReleaseEvent(self, _e):
        if self.drag is not None:
            self.drag = None
            self.update()
            self.committed.emit([list(p) for p in self.points])


class SpeedCurveEditor(QWidget):
    """The field, the length it gives, and 重設 (flat at 1x)."""
    curveChosen = Signal(list)

    def __init__(self):
        super().__init__()
        self.field = CurveField()
        self.span_us = 0.0                               # the part of the source the clip plays
        self.length = QLabel()
        self.length.setStyleSheet("color: #9a9aa0;")
        reset = QPushButton("重設")
        reset.setToolTip("全部回到 1x")
        reset.clicked.connect(lambda: self.curveChosen.emit([[u, 1.0] for u, _s in self.field.points]))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.length, 1)
        row.addWidget(reset)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.field)
        lay.addLayout(row)
        self.field.moved.connect(self._show_length)
        self.field.committed.connect(self.curveChosen)

    def show_clip(self, c, t_us):
        sc = c.get("speed_curve") or {}
        self.field.set_points(sc.get("points") or [[0.0, 1.0], [1.0, 1.0]])
        self.span_us = c["duration_us"] * project.speed(c)
        self.field.playhead = min(1.0, max(0.0, t_us / max(c["duration_us"], 1)))
        self.field.update()
        self._show_length(self.field.points)

    def _show_length(self, points):
        self.length.setText(f"長度 {self.span_us / project.curve_mean(points) / 1_000_000:.2f} 秒"
                            f"（平均 {project.curve_mean(points):.2f}x）")
