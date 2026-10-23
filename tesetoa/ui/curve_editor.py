"""Keyframe curve editor: one parameter's curve over the selected clip's time.

Drag a keyframe to change its time (snapped to frames) and value, drag the round handles
to shape the ease, double-click to add a keyframe, Delete removes the selected one.
The segment from the selected keyframe to the next can be typed as CSS cubic-bezier.
Edits show live in the preview while dragging and become one undo step on release.
"""
import copy
import math

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QComboBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout, QWidget)

from .. import curves
from .inspector import PARAMS, SpinBox

US = 1_000_000
PICK_PX = 8
CHANNEL_COLORS = ("#ff5a5a", "#5ad65a", "#5a8cff")
PRESETS = (("線性", (0.0, 0.0, 1.0, 1.0)), ("緩入", (0.42, 0.0, 1.0, 1.0)), ("緩出", (0.0, 0.0, 0.58, 1.0)),
           ("緩入緩出", (0.42, 0.0, 0.58, 1.0)), ("回彈", (0.34, 1.56, 0.64, 1.0)))


def param_rows(c):
    """(group, key, label, factor, default) of every parameter clip c can animate."""
    out = []
    if c.get("transform") is not None:
        out += [("transform", r[0], r[1], r[6], r[7]) for r in PARAMS["transform"]]
    if c.get("text"):
        out += [("text", r[0], r[1], r[6], r[7]) for r in PARAMS["text"]]
        out.append(("text", "color", "文字顏色", 1, [1.0, 1.0, 1.0]))
    if c.get("mask"):
        out += [("mask", r[0], "遮罩" + r[1], r[6], r[7]) for r in PARAMS["mask"]]
    if "volume" in c:
        out.append(("clip", "volume", "音量 %", 100, 1.0))
    return out


def holder(c, group):
    return c if group == "clip" else (c.get(group) or {})


class CurveCanvas(QWidget):
    keysLive = Signal(list)          # while dragging
    keysCommitted = Signal(list)     # on release / delete / add
    seekRequested = Signal(float)    # clip time, us
    selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.keys = []
        self.static = 0.0
        self.duration = 1
        self.fps = 60.0
        self.factor = 1
        self.color = False
        self.t = 0
        self.sel = None
        self.drag = None
        self.vrange = (0.0, 1.0)

    # -- state ------------------------------------------------------------------------------------
    def set_curve(self, keys, static, duration, fps, factor, t, keep_range=False):
        if self.drag:
            self.t = t
            return
        self.keys = copy.deepcopy(keys)
        self.static = static
        self.duration, self.fps, self.factor, self.t = max(duration, 1), fps, factor, t
        self.color = isinstance(static, list) or bool(keys and isinstance(keys[0][1], list))
        if self.sel is not None and self.sel >= len(self.keys):
            self.sel = None
        if not keep_range:
            self.fit()
        self.update()

    def value_at(self, t):
        return curves.value({"keys": self.keys} if self.keys else self.static, t)

    def fit(self):
        if self.color:
            self.vrange = (-0.05, 1.05)
            return
        vals = [self.value_at(self.duration * i / 200) for i in range(201)]
        vals += [k[1] + k[5] for k in self.keys] + [k[1] + k[3] for k in self.keys]
        lo, hi = min(vals), max(vals)
        if hi - lo < 1e-9:
            pad = max(abs(lo) * 0.5, 0.5 / self.factor)
        else:
            pad = (hi - lo) * 0.12
        self.vrange = (lo - pad, hi + pad)

    # -- geometry ---------------------------------------------------------------------------------
    L, R, T, B = 52, 12, 10, 22

    def x(self, t):
        return self.L + t / self.duration * (self.width() - self.L - self.R)

    def t_of(self, x):
        return (x - self.L) / max(1, self.width() - self.L - self.R) * self.duration

    def y(self, v):
        lo, hi = self.vrange
        return self.T + (hi - v) / (hi - lo) * (self.height() - self.T - self.B)

    def v_of(self, y):
        lo, hi = self.vrange
        return hi - (y - self.T) / max(1, self.height() - self.T - self.B) * (hi - lo)

    def snap_t(self, t):
        step = US / self.fps
        return round(t / step) * step

    # -- painting ---------------------------------------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#18181b"))
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setFont(QFont("Segoe UI", 8))
        area = QRectF(self.L, self.T, w - self.L - self.R, h - self.T - self.B)
        p.fillRect(area, QColor("#1f1f24"))
        # grid: value lines and time ticks
        lo, hi = self.vrange
        step = 10 ** math.floor(math.log10(max((hi - lo) * self.factor / 4, 1e-9)))
        for m in (1, 2, 5):
            if (hi - lo) * self.factor / (step * m) <= 6:
                step *= m
                break
        v = math.floor(lo * self.factor / step) * step
        while v <= hi * self.factor:
            yy = self.y(v / self.factor)
            if self.T <= yy <= h - self.B:
                p.setPen(QColor("#2c2c33"))
                p.drawLine(QPointF(self.L, yy), QPointF(w - self.R, yy))
                p.setPen(QColor("#8a8a90"))
                p.drawText(QRectF(0, yy - 8, self.L - 6, 16), Qt.AlignRight | Qt.AlignVCenter, f"{v:g}")
            v += step
        ts = next(s for s in (0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60) if self.duration / US / s <= 10)
        t = 0.0
        while t * US <= self.duration:
            xx = self.x(t * US)
            p.setPen(QColor("#2c2c33"))
            p.drawLine(QPointF(xx, self.T), QPointF(xx, h - self.B))
            p.setPen(QColor("#8a8a90"))
            p.drawText(QPointF(xx + 2, h - 6), f"{t:g}s")
            t += ts
        # curve(s)
        n = max(2, int(area.width()))
        samples = [self.value_at(self.duration * i / n) for i in range(n + 1)]
        channels = range(3) if self.color else [None]
        for ci in channels:
            path = QPainterPath()
            for i, val in enumerate(samples):
                vv = val[ci] if ci is not None else val
                pt = QPointF(self.x(self.duration * i / n), self.y(vv))
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            p.setPen(QPen(QColor(CHANNEL_COLORS[ci] if ci is not None else "#2fd6c8"), 2))
            p.drawPath(path)
        # handles of the selected key
        if self.sel is not None and self.keys:
            k = self.keys[self.sel]
            for hp in self._handle_points(self.sel):
                kp = QPointF(self.x(k[0]), self.y(self._kv(k)))
                p.setPen(QPen(QColor("#ffb020"), 1))
                p.drawLine(kp, hp[1])
                p.setBrush(QColor("#ffb020"))
                p.drawEllipse(hp[1], 4.5, 4.5)
        # keys
        for i, k in enumerate(self.keys):
            c = QPointF(self.x(k[0]), self.y(self._kv(k)))
            p.setPen(QPen(QColor("#ffffff") if i == self.sel else QColor("#111"), 1.5))
            p.setBrush(QColor("#ffb020") if i == self.sel else QColor("#e6e6e6"))
            r = 6
            p.drawPolygon(QPolygonF([c + QPointF(0, -r), c + QPointF(r, 0), c + QPointF(0, r), c + QPointF(-r, 0)]))
        # playhead
        if 0 <= self.t <= self.duration:
            p.setPen(QPen(QColor("#ff4d4f"), 1.5))
            p.drawLine(QPointF(self.x(self.t), self.T), QPointF(self.x(self.t), h - self.B))
        if not self.keys:
            p.setPen(QColor("#9a9aa0"))
            p.drawText(area, Qt.AlignCenter, "沒有關鍵幀：在曲線上雙擊，或按「在播放頭新增」")

    def _kv(self, k):
        """Value used to place a key vertically (colours sit on their brightness)."""
        return sum(k[1]) / 3 if isinstance(k[1], list) else k[1]

    def _handle_points(self, i):
        """[(side, point)] for key i: 'r' towards the next key, 'l' towards the previous."""
        k = self.keys[i]
        out = []
        dv = lambda d: 0 if self.color else d
        if i + 1 < len(self.keys) and (k[4] or dv(k[5])):       # zero-length handles: linear,
            out.append(("r", QPointF(self.x(k[0] + k[4]), self.y(self._kv(k) + dv(k[5])))))  # not shown
        if i > 0 and (k[2] or dv(k[3])):
            out.append(("l", QPointF(self.x(k[0] + k[2]), self.y(self._kv(k) + dv(k[3])))))
        return out

    # -- mouse ------------------------------------------------------------------------------------
    def _hit(self, pos):
        # keys first: a handle with no length sits on its key and must not steal the drag
        for i, k in enumerate(self.keys):
            if math.hypot(pos.x() - self.x(k[0]), pos.y() - self.y(self._kv(k))) <= PICK_PX:
                return "key", i, None
        if self.sel is not None:
            for side, hp in self._handle_points(self.sel):
                if math.hypot(pos.x() - hp.x(), pos.y() - hp.y()) <= PICK_PX:
                    return "handle", self.sel, side
        return None, None, None

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        kind, i, side = self._hit(e.position())
        if kind is None:
            self.seekRequested.emit(min(max(self.t_of(e.position().x()), 0), self.duration))
            return
        self.sel = i
        self.selected.emit(i)
        self.drag = {"kind": kind, "i": i, "side": side, "moved": False}
        self.update()

    def mouseMoveEvent(self, e):
        d = self.drag
        if d is None:
            kind, _, _ = self._hit(e.position())
            self.setCursor(Qt.SizeAllCursor if kind else Qt.ArrowCursor)
            return
        pos = e.position()
        k = self.keys[d["i"]]
        t = min(max(self.t_of(pos.x()), 0), self.duration)
        v = self.v_of(pos.y())
        if d["kind"] == "key":
            prev_t = self.keys[d["i"] - 1][0] if d["i"] > 0 else -US
            next_t = self.keys[d["i"] + 1][0] if d["i"] + 1 < len(self.keys) else self.duration + US
            frame = US / self.fps
            k[0] = int(min(max(self.snap_t(t), prev_t + frame, 0), next_t - frame, self.duration))
            if not self.color:
                k[1] = v
        else:
            if d["side"] == "r":
                nxt = self.keys[d["i"] + 1][0] - k[0]
                k[4] = min(max(t - k[0], 0), nxt)
                k[5] = 0.0 if self.color else v - k[1]
            else:
                prv = k[0] - self.keys[d["i"] - 1][0]
                k[2] = max(min(t - k[0], 0), -prv)
                k[3] = 0.0 if self.color else v - k[1]
        d["moved"] = True
        self.keysLive.emit(copy.deepcopy(self.keys))
        self.update()

    def mouseReleaseEvent(self, e):
        d, self.drag = self.drag, None
        if d and d["moved"]:
            self.keysCommitted.emit(copy.deepcopy(self.keys))

    def mouseDoubleClickEvent(self, e):
        t = int(self.snap_t(min(max(self.t_of(e.position().x()), 0), self.duration)))
        if any(abs(k[0] - t) < US / self.fps for k in self.keys):
            return
        v = self.value_at(t) if self.color else self.v_of(e.position().y())
        keys = copy.deepcopy(self.keys) or []
        keys.append([t, v, 0.0, 0.0, 0.0, 0.0])
        keys.sort(key=lambda k: k[0])
        self.sel = next(i for i, k in enumerate(keys) if k[0] == t)
        self.keys = keys
        self.keysCommitted.emit(copy.deepcopy(keys))

    def event(self, e):
        # claim Delete before the window's "delete clip" shortcut sees it
        if e.type() == QEvent.ShortcutOverride and e.key() in (Qt.Key_Delete, Qt.Key_Backspace)                 and self.sel is not None and self.keys:
            e.accept()
            return True
        return super().event(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.sel is not None and self.keys:
            keys = copy.deepcopy(self.keys)
            keys.pop(self.sel)
            self.sel = None
            self.keysCommitted.emit(keys)          # an empty list means "no keyframes"
            e.accept()
        else:
            super().keyPressEvent(e)


class CurveEditor(QWidget):
    keysChanged = Signal(str, str, str, list, bool)   # clip id, group, key, keys, final
    removeAll = Signal(str, str, str, object)         # clip id, group, key, value to keep
    seekRequested = Signal(float)                     # clip time, us
    addAtPlayhead = Signal(str, str, str)             # clip id, group, key

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        top = QHBoxLayout()
        self.param = QComboBox()
        self.param.currentIndexChanged.connect(lambda _: self._refresh(fit=True))
        fit = QPushButton("全部顯示")
        fit.clicked.connect(lambda: (self.canvas.fit(), self.canvas.update()))
        top.addWidget(QLabel("參數"))
        top.addWidget(self.param, 1)
        top.addWidget(fit)
        lay.addLayout(top)
        self.canvas = CurveCanvas()
        self.canvas.keysLive.connect(lambda keys: self._emit(keys, False))
        self.canvas.keysCommitted.connect(lambda keys: self._emit(keys, True))
        self.canvas.seekRequested.connect(self.seekRequested)
        self.canvas.selected.connect(lambda _: self._show_key())
        lay.addWidget(self.canvas, 1)

        form = QFormLayout()
        row = QHBoxLayout()
        self.time = SpinBox()
        self.time.setDecimals(3)
        self.time.setSuffix(" s")
        self.time.setRange(0, 1e6)
        self.time.setSingleStep(1 / 60)
        self.value = SpinBox()
        self.value.setDecimals(3)
        self.value.setRange(-1e6, 1e6)
        for s in (self.time, self.value):
            s.setKeyboardTracking(False)
            s.valueChanged.connect(self._fields_changed)
        row.addWidget(self.time)
        row.addWidget(QLabel("數值"))
        row.addWidget(self.value)
        form.addRow("時間", row)
        brow = QHBoxLayout()
        self.bezier = QLineEdit()
        self.bezier.setPlaceholderText("cubic-bezier，例：0.42, 0, 0.58, 1")
        self.bezier.returnPressed.connect(self._apply_bezier)
        apply = QPushButton("套用")
        apply.clicked.connect(self._apply_bezier)
        brow.addWidget(self.bezier, 1)
        brow.addWidget(apply)
        form.addRow("曲線", brow)
        grid = QGridLayout()
        for i, (name, spec) in enumerate(PRESETS):
            b = QPushButton(name)
            b.clicked.connect(lambda _=False, s=spec: self._set_bezier(s))
            grid.addWidget(b, 0, i)
        form.addRow("", grid)
        lay.addLayout(form)
        acts = QHBoxLayout()
        add = QPushButton("在播放頭新增")
        add.clicked.connect(lambda: self.clip and self.addAtPlayhead.emit(self.clip["id"], *self._param()[:2]))
        delete = QPushButton("刪除選取的關鍵幀")
        delete.clicked.connect(self._delete_selected)
        acts.addWidget(add)
        acts.addWidget(delete)
        lay.addLayout(acts)
        self.hint = QLabel("")
        self.hint.setStyleSheet("color: #9a9aa0;")
        lay.addWidget(self.hint)
        self.clip = None
        self.fps = 60.0
        self.t = 0
        self.rows = []
        self.set_clip(None, 0, 60.0)

    # -- state ------------------------------------------------------------------------------------
    def _param(self):
        i = self.param.currentIndex()
        return self.rows[i] if 0 <= i < len(self.rows) else ("transform", "x", "", 1, 0.0)

    def set_clip(self, c, t, fps):
        """Show clip c (or nothing) at clip time t."""
        same = c is not None and self.clip is not None and c["id"] == self.clip["id"]
        self.clip, self.fps, self.t = c, fps, t
        self.setEnabled(c is not None)
        rows = param_rows(c) if c else []
        labels = [("● " if curves.is_animated(holder(c, g).get(k)) else "   ") + lab for g, k, lab, *_ in rows]
        if [r[:2] for r in rows] != [r[:2] for r in self.rows] or not same:
            keep = self._param()[:2]
            self.rows = rows
            self.param.blockSignals(True)
            self.param.clear()
            self.param.addItems(labels)
            idx = next((i for i, r in enumerate(rows) if r[:2] == keep), None)
            if idx is None or not same:
                idx = next((i for i, (g, k, *_x) in enumerate(rows) if curves.is_animated(holder(c, g).get(k))), 0)
            self.param.setCurrentIndex(idx)
            self.param.blockSignals(False)
            self._refresh(fit=True)
            return
        for i, lab in enumerate(labels):
            self.param.setItemText(i, lab)
        self._refresh(fit=False)

    def _refresh(self, fit):
        c = self.clip
        if c is None:
            self.canvas.set_curve([], 0.0, 1, self.fps, 1, 0)
            return
        g, k, _lab, factor, default = self._param()
        p = holder(c, g).get(k, default)
        keys = p["keys"] if curves.is_animated(p) else []
        self.canvas.set_curve(keys, p if not keys else default, c["duration_us"], self.fps, factor,
                              self.t, keep_range=not fit)
        self._show_key()

    def _show_key(self):
        cv = self.canvas
        k = cv.keys[cv.sel] if cv.sel is not None and cv.keys else None
        for wdg in (self.time, self.value):
            wdg.blockSignals(True)
        self.time.setEnabled(k is not None)
        self.value.setEnabled(k is not None and not cv.color)
        if k is not None:
            self.time.setValue(k[0] / US)
            if not cv.color:
                self.value.setValue(k[1] * cv.factor)
            nxt = cv.keys[cv.sel + 1] if cv.sel + 1 < len(cv.keys) else None
            if nxt is not None:
                x1, y1, x2, y2 = curves.segment_bezier(k, nxt)
                self.bezier.setText(f"{x1:.3g}, {y1:.3g}, {x2:.3g}, {y2:.3g}")
                self.hint.setText("曲線作用在選取的關鍵幀到下一個關鍵幀之間")
            else:
                self.bezier.clear()
                self.hint.setText("最後一個關鍵幀之後沒有曲線")
        else:
            self.bezier.clear()
            self.hint.setText("點選關鍵幀來編輯；拖曳圓點調整緩動，雙擊新增，Delete 刪除")
        for wdg in (self.time, self.value):
            wdg.blockSignals(False)

    def select_param(self, group, key):
        """Show this parameter's curve (e.g. after its ◆ was clicked in the inspector)."""
        for i, r in enumerate(self.rows):
            if r[:2] == (group, key):
                self.param.setCurrentIndex(i)
                return

    # -- edits ------------------------------------------------------------------------------------
    def _emit(self, keys, final):
        g, k = self._param()[:2]
        if not self.clip:
            return
        if not keys:
            last = self.canvas.keys[0][1] if self.canvas.keys else self.canvas.static
            self.removeAll.emit(self.clip["id"], g, k, last)
            return
        self.keysChanged.emit(self.clip["id"], g, k, keys, final)
        if final:
            self._show_key()

    def _fields_changed(self):
        cv = self.canvas
        if cv.sel is None or not cv.keys:
            return
        keys = copy.deepcopy(cv.keys)
        keys[cv.sel][0] = int(cv.snap_t(self.time.value() * US))
        if not cv.color:
            keys[cv.sel][1] = self.value.value() / cv.factor
        self._emit(keys, True)

    def _set_bezier(self, spec):
        cv = self.canvas
        if cv.sel is None or cv.sel + 1 >= len(cv.keys):
            self.hint.setText("先選一個後面還有關鍵幀的關鍵幀")
            return
        keys = copy.deepcopy(cv.keys)
        curves.apply_bezier(keys[cv.sel], keys[cv.sel + 1], *spec)
        self._emit(keys, True)

    def _apply_bezier(self):
        try:
            self._set_bezier(curves.parse_bezier(self.bezier.text()))
        except ValueError as exc:
            self.hint.setText(str(exc))

    def _delete_selected(self):
        cv = self.canvas
        if cv.sel is None or not cv.keys:
            return
        keys = copy.deepcopy(cv.keys)
        keys.pop(cv.sel)
        cv.sel = None
        self._emit(keys, True)
