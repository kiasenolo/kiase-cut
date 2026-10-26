"""Keyframe curve editor: the selected clip's parameter curves over its time.

Any number of parameters can be shown at once (tick them in the list); each gets its own
colour. "正規化" stretches every curve to the same height so position, scale and rotation
can be compared; without it they share one axis in the inspector's units.

Click a keyframe to select it; Ctrl / Shift + click adds or removes keyframes, dragging on
empty space draws a selection box, Ctrl+A selects all. Dragging a selected keyframe moves
the whole selection (time snaps to frames; hold Shift to keep to one axis). The round
handles shape the ease of a selected keyframe. Double-click adds a keyframe to the nearest
curve, Delete removes the selection, Ctrl+D clears it. The wheel moves the view up and
down, Shift+wheel left and right, Ctrl+wheel zooms time around the mouse, Alt+wheel zooms
values (a touchpad's two-finger scroll moves both ways at once, its pinch zooms time), the middle button drags the view and Ctrl+middle-drag zooms it around where the drag
started (as in Blender's graph editor: sideways zooms time, up and down values; right / up:
in); "全部顯示" fits everything again. A click on the time ruler (or empty space) moves the
playhead.

The segment after each selected keyframe takes a typed CSS cubic-bezier or a preset. Edits
show live in the preview while dragging and become one undo step on release.

批量: with more clips selected, the keyframes of theirs alike the shown clip's (keybatch.py)
are ringed and change with them while "一起修改" is ticked.
"""
import copy
import math

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from .. import assets, curves, edit, fx
from . import wheel
from .inspector import PARAMS, SpinBox

US = 1_000_000
PICK_PX = 8
CHANNEL_COLORS = ("#ff5a5a", "#5ad65a", "#5a8cff")
CURVE_COLORS = ("#2fd6c8", "#ff9f43", "#c38bff", "#7bd65a", "#ff6b9a", "#f4d35e", "#5aa9ff", "#e0e0e0")
PRESETS = (("線性", (0.0, 0.0, 1.0, 1.0)), ("緩入", (0.42, 0.0, 1.0, 1.0)), ("緩出", (0.0, 0.0, 0.58, 1.0)),
           ("緩入緩出", (0.42, 0.0, 0.58, 1.0)), ("回彈", (0.34, 1.56, 0.64, 1.0)))
MAX_HANDLES = 16                  # handles are drawn for at most this many selected keys


def param_rows(c):
    """(group, key, label, factor, default) of every parameter clip c can animate."""
    out = []
    if c.get("transform") is not None:
        out += [("transform", r[0], r[1], r[6], r[7]) for r in PARAMS["transform"]
                if r[0] != "scale_y" or "scale_y" in c["transform"]]       # (absent: Y follows X)
    if c.get("asset"):                                  # a built-in asset's numbers (assets.py)
        out += [("asset", f, "素材" + assets.FIELD_INFO[f][0], 1, assets.clean(f, None))
                for f in assets.fields_of(c["asset"].get("family")) if assets.FIELD_INFO[f][1] == "number"]
    if c.get("text"):
        out += [("text", r[0], r[1], r[6], r[7]) for r in PARAMS["text"]]
        out.append(("text", "color", "文字顏色", 1, [1.0, 1.0, 1.0]))
    if c.get("mask"):
        out += [("mask", r[0], "遮罩" + r[1], r[6], r[7]) for r in PARAMS["mask"]]
    if "volume" in c:
        out.append(("clip", "volume", "音量 %", 100, 1.0))
    for e in c.get("effects") or []:                    # the numbers of the clip's filters and their masks
        d = fx.get(e["filter"])
        name = d.name if len(c["effects"]) == 1 else f"{d.name} #{c['effects'].index(e) + 1}"
        for p in d.params:
            if p.type in ("float", "int"):
                out.append(("fx:" + e["id"], p.name, f"{name}·{p.label}", 1, p.default))
        if e.get("mask"):
            out += [("fxmask:" + e["id"], r[0], f"{name}·遮罩{r[1]}", r[6], r[7]) for r in PARAMS["mask"]]
    return out


def holder(c, group):
    if group.startswith(("fx:", "fxmask:")):
        try:
            return edit.holder(c, group)
        except edit.EditError:
            return {}
    return c if group == "clip" else (c.get(group) or {})


class CurveCanvas(QWidget):
    keysLive = Signal(list)          # [(curve index, keys)] while dragging
    keysCommitted = Signal(list)     # the same on release / delete / add
    seekRequested = Signal(float)    # clip time, us
    selectionChanged = Signal()

    L, R, T, B = 52, 12, 10, 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.curves = []             # [{label, factor, color(bool), keys, static, pen}]
        self.duration = 1
        self.fps = 60.0
        self.t = 0
        self.sel = set()             # {(curve index, key index)}
        self.drag = None
        self.band = None
        self.normalize = True
        self.t0, self.t1 = 0.0, 1.0  # visible time (us)
        self.vrange = (0.0, 1.0)     # visible plot values
        self.ranges = []             # per curve (lo, hi) for normalising
        self._paths = None           # cached curve paths for the current view
        self.linked = {}             # {curve index: {key index: other clips with an alike key}} (批量)

    # -- state ------------------------------------------------------------------------------------
    def set_curves(self, specs, duration, fps, t, keep_view=False):
        """specs: [{label, factor, keys, static}] in display order."""
        if self.drag:
            self.t = t
            self.update()
            return
        old = [(c["label"], len(c["keys"])) for c in self.curves]
        self.curves = []
        for i, s in enumerate(specs):
            keys = copy.deepcopy(s["keys"])
            color = isinstance(s["static"], list) or bool(keys and isinstance(keys[0][1], list))
            self.curves.append({"label": s["label"], "factor": s["factor"], "keys": keys,
                                "static": s["static"], "color": color,
                                "pen": CURVE_COLORS[s.get("slot", i) % len(CURVE_COLORS)]})
        if [(c["label"], len(c["keys"])) for c in self.curves] != old:
            self.sel = {(ci, i) for ci, i in self.sel
                        if ci < len(self.curves) and i < len(self.curves[ci]["keys"])} if keep_view else set()
        self.duration, self.fps, self.t = max(duration, 1), fps, t
        if keep_view and len(self.ranges) == len(self.curves):
            self._paths = None
        else:
            self.fit()
        self.update()

    def value_at(self, ci, t):
        c = self.curves[ci]
        return curves.value({"keys": c["keys"]} if c["keys"] else c["static"], t)

    def _samples(self, ci, n=200):
        return [self.value_at(ci, self.duration * i / n) for i in range(n + 1)]

    def fit(self):
        """Show the whole clip and every curve."""
        pad = self.duration * 0.02                   # keys at the very ends stay whole
        self.t0, self.t1 = -pad, self.duration + pad
        self.ranges = []
        for ci, c in enumerate(self.curves):
            if c["color"]:
                self.ranges.append((0.0, 1.0))
                continue
            vals = self._samples(ci)
            vals += [k[1] + k[5] for k in c["keys"]] + [k[1] + k[3] for k in c["keys"]]
            lo, hi = min(vals), max(vals)
            if hi - lo < 1e-9:
                s = max(abs(lo), 1.0 / c["factor"], 1e-3)
                lo, hi = lo - s / 2, hi + s / 2
            self.ranges.append((lo, hi))
        if self.normalize or not self.curves:
            self.vrange = (-0.12, 1.12)
        else:
            vals = [self.pv(ci, v) for ci in range(len(self.curves)) for v in self.ranges[ci]]
            lo, hi = min(vals), max(vals)
            pad = (hi - lo) * 0.12 or 0.5
            self.vrange = (lo - pad, hi + pad)
        self._paths = None
        self.update()

    def set_normalize(self, on):
        self.normalize = on
        self.fit()

    # -- value <-> plot ---------------------------------------------------------------------------
    def pv(self, ci, v):
        """Plot value of curve ci's value v."""
        if self.normalize:
            lo, hi = self.ranges[ci]
            return (v - lo) / (hi - lo)
        return v * self.curves[ci]["factor"]

    def vv(self, ci, p):
        if self.normalize:
            lo, hi = self.ranges[ci]
            return lo + p * (hi - lo)
        return p / self.curves[ci]["factor"]

    # -- geometry ---------------------------------------------------------------------------------
    def x(self, t):
        return self.L + (t - self.t0) / max(self.t1 - self.t0, 1) * (self.width() - self.L - self.R)

    def t_of(self, x):
        return self.t0 + (x - self.L) / max(1, self.width() - self.L - self.R) * (self.t1 - self.t0)

    def y(self, p):
        lo, hi = self.vrange
        return self.T + (hi - p) / (hi - lo) * (self.height() - self.T - self.B)

    def p_of(self, y):
        lo, hi = self.vrange
        return hi - (y - self.T) / max(1, self.height() - self.T - self.B) * (hi - lo)

    def snap_t(self, t):
        step = US / self.fps
        return round(t / step) * step

    def _kv(self, k):
        """Value used to place a key vertically (colours sit on their brightness)."""
        return sum(k[1]) / 3 if isinstance(k[1], list) else k[1]

    def key_point(self, ci, i):
        k = self.curves[ci]["keys"][i]
        return QPointF(self.x(k[0]), self.y(self.pv(ci, self._kv(k))))

    def _handle_points(self, ci, i):
        """[(side, point)] for key i of curve ci: 'r' towards the next key, 'l' the previous."""
        c = self.curves[ci]
        keys, k = c["keys"], c["keys"][i]
        out = []
        dv = (lambda d: 0) if c["color"] else (lambda d: d)
        base = self._kv(k)
        if i + 1 < len(keys) and (k[4] or dv(k[5])):            # zero-length handles: linear, not shown
            out.append(("r", QPointF(self.x(k[0] + k[4]), self.y(self.pv(ci, base + dv(k[5]))))))
        if i > 0 and (k[2] or dv(k[3])):
            out.append(("l", QPointF(self.x(k[0] + k[2]), self.y(self.pv(ci, base + dv(k[3]))))))
        return out

    def _shown_handles(self):
        return sorted(self.sel)[:MAX_HANDLES]

    # -- painting ---------------------------------------------------------------------------------
    def _curve_paths(self):
        if self._paths is not None:
            return self._paths
        area_w = max(2, self.width() - self.L - self.R)
        a = max(0.0, self.t0)
        b = min(float(self.duration), self.t1)
        n = max(2, int((self.x(b) - self.x(a)) / 2)) if b > a else 0
        out = []
        for ci, c in enumerate(self.curves):
            paths = []
            if n:
                vals = [self.value_at(ci, a + (b - a) * i / n) for i in range(n + 1)]
                xs = [self.x(a + (b - a) * i / n) for i in range(n + 1)]
                chans = range(3) if c["color"] else [None]
                for ch in chans:
                    path = QPainterPath()
                    for i, (xx, val) in enumerate(zip(xs, vals)):
                        pt = QPointF(xx, self.y(self.pv(ci, val[ch] if ch is not None else val)))
                        path.moveTo(pt) if i == 0 else path.lineTo(pt)
                    paths.append((ch, path))
            out.append(paths)
        self._paths = (area_w, self.height(), out)
        return self._paths

    def resizeEvent(self, e):
        self._paths = None
        super().resizeEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#18181b"))
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setFont(QFont("Segoe UI", 8))
        area = QRectF(self.L, self.T, w - self.L - self.R, h - self.T - self.B)
        p.fillRect(area, QColor("#1f1f24"))
        # outside the clip
        for a, b in ((self.t0, 0), (self.duration, self.t1)):
            if b > a:
                xa, xb = max(self.x(a), self.L), min(self.x(b), w - self.R)
                if xb > xa:
                    p.fillRect(QRectF(xa, self.T, xb - xa, area.height()), QColor("#141417"))
        # value grid
        lo, hi = self.vrange
        if self.normalize:
            grid = [(v / 4, f"{v * 25}%") for v in range(-1, 6)]
        else:
            step = 10 ** math.floor(math.log10(max((hi - lo) / 4, 1e-9)))
            for m in (1, 2, 5, 10):
                if (hi - lo) / (step * m) <= 6:
                    step *= m
                    break
            v0 = math.floor(lo / step) * step
            grid = [(v0 + i * step, f"{v0 + i * step:g}") for i in range(int((hi - lo) / step) + 2)]
        for v, label in grid:
            yy = self.y(v)
            if self.T <= yy <= h - self.B:
                p.setPen(QColor("#2c2c33"))
                p.drawLine(QPointF(self.L, yy), QPointF(w - self.R, yy))
                p.setPen(QColor("#8a8a90"))
                p.drawText(QRectF(0, yy - 8, self.L - 6, 16), Qt.AlignRight | Qt.AlignVCenter, label)
        # time ruler
        span = (self.t1 - self.t0) / US
        ts = next((s for s in (1 / 60, 1 / 30, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 300)
                   if span / s <= 8), 600)
        t = math.ceil(self.t0 / US / ts) * ts
        while t * US <= self.t1:
            xx = self.x(t * US)
            p.setPen(QColor("#2c2c33"))
            p.drawLine(QPointF(xx, self.T), QPointF(xx, h - self.B))
            p.setPen(QColor("#8a8a90"))
            p.drawText(QPointF(xx + 2, h - 6), f"{t:.3g}s")
            t += ts
        p.save()
        p.setClipRect(area)
        # curves
        for ci, paths in enumerate(self._curve_paths()[2]):
            for ch, path in paths:
                col = CHANNEL_COLORS[ch] if ch is not None else self.curves[ci]["pen"]
                p.setPen(QPen(QColor(col), 2 if ch is None else 1.5))
                p.drawPath(path)
        # handles of selected keys
        for ci, i in self._shown_handles():
            kp = self.key_point(ci, i)
            for _side, hp in self._handle_points(ci, i):
                p.setPen(QPen(QColor("#ffb020"), 1))
                p.drawLine(kp, hp)
                p.setBrush(QColor("#ffb020"))
                p.drawEllipse(hp, 4.5, 4.5)
        # keys
        r = 6
        for ci, c in enumerate(self.curves):
            for i in range(len(c["keys"])):
                pt = self.key_point(ci, i)
                on = (ci, i) in self.sel
                p.setPen(QPen(QColor("#ffffff") if on else QColor(c["pen"]), 1.5))
                p.setBrush(QColor("#ffb020") if on else QColor("#26262b"))
                p.drawPolygon(QPolygonF([pt + QPointF(0, -r), pt + QPointF(r, 0), pt + QPointF(0, r), pt + QPointF(-r, 0)]))
                if i in self.linked.get(ci, ()):            # changes with other clips' keys (批量)
                    q = r + 4
                    p.setPen(QPen(QColor("#5ad6ff"), 1.5))
                    p.setBrush(Qt.NoBrush)
                    p.drawPolygon(QPolygonF([pt + QPointF(0, -q), pt + QPointF(q, 0), pt + QPointF(0, q),
                                             pt + QPointF(-q, 0)]))
        if self.band is not None:
            p.setPen(QPen(QColor("#e6e6e6"), 1, Qt.DashLine))
            p.setBrush(QColor(255, 255, 255, 35))
            p.drawRect(self.band)
        # playhead
        if self.t0 <= self.t <= self.t1:
            p.setPen(QPen(QColor("#ff4d4f"), 1.5))
            p.drawLine(QPointF(self.x(self.t), self.T), QPointF(self.x(self.t), h - self.B))
        p.restore()
        if not self.curves:
            p.setPen(QColor("#9a9aa0"))
            p.drawText(area, Qt.AlignCenter, "在上方勾選要顯示的參數")
        elif not any(c["keys"] for c in self.curves):
            p.setPen(QColor("#9a9aa0"))
            p.drawText(area, Qt.AlignCenter, "沒有關鍵幀：在曲線區雙擊，或按「在播放頭新增」")

    # -- mouse ------------------------------------------------------------------------------------
    def _hit(self, pos):
        # keys first: a handle with no length sits on its key and must not steal the drag
        for ci in reversed(range(len(self.curves))):
            for i in range(len(self.curves[ci]["keys"])):
                kp = self.key_point(ci, i)
                if math.hypot(pos.x() - kp.x(), pos.y() - kp.y()) <= PICK_PX:
                    return "key", (ci, i), None
        for ci, i in self._shown_handles():
            for side, hp in self._handle_points(ci, i):
                if math.hypot(pos.x() - hp.x(), pos.y() - hp.y()) <= PICK_PX:
                    return "handle", (ci, i), side
        return None, None, None

    def _set_sel(self, sel):
        self.sel = set(sel)
        self.selectionChanged.emit()
        self.update()

    def _bounds(self):
        """How far (us) the selection may move without passing an unselected key or the clip."""
        frame = US / self.fps
        lo, hi = -math.inf, math.inf
        for ci, i in self.sel:
            keys = self.curves[ci]["keys"]
            t = keys[i][0]
            if i == 0:
                lo = max(lo, -t)
            elif (ci, i - 1) not in self.sel:
                lo = max(lo, keys[i - 1][0] + frame - t)
            if i + 1 == len(keys):
                hi = min(hi, self.duration - t)
            elif (ci, i + 1) not in self.sel:
                hi = min(hi, keys[i + 1][0] - frame - t)
        return lo, hi

    def mousePressEvent(self, e):
        pos = e.position()
        if e.button() == Qt.MiddleButton:                    # Ctrl: zoom, else move the view
            zoom = bool(e.modifiers() & Qt.ControlModifier)
            self.drag = {"kind": "zoom" if zoom else "pan", "pos": pos, "t0": self.t0, "t1": self.t1,
                         "v": self.vrange, "at": (self.t_of(pos.x()), self.p_of(pos.y()))}
            return
        if e.button() != Qt.LeftButton:
            return
        adding = bool(e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier))
        kind, ref, side = self._hit(pos)
        if kind == "handle":
            self.drag = {"kind": "handle", "ref": ref, "side": side, "moved": False}
            return
        if kind == "key":
            if adding:
                self._set_sel(self.sel ^ {ref})
                if ref not in self.sel:
                    return
            elif ref not in self.sel:
                self._set_sel({ref})
            self.drag = {"kind": "keys", "pos": pos, "moved": False, "bounds": self._bounds(),
                         "orig": {ci: copy.deepcopy(self.curves[ci]["keys"]) for ci, _ in self.sel},
                         "ref": ref}
            return
        if pos.y() > self.height() - self.B:               # the time ruler: scrub
            self.drag = {"kind": "seek"}
            self.seekRequested.emit(min(max(self.t_of(pos.x()), 0), self.duration))
            return
        self.drag = {"kind": "band", "pos": pos, "moved": False, "base": set(self.sel) if adding else set()}

    def mouseMoveEvent(self, e):
        d = self.drag
        pos = e.position()
        if d is None:
            kind, _, _ = self._hit(pos)
            self.setCursor(Qt.SizeAllCursor if kind else Qt.ArrowCursor)
            return
        if d["kind"] == "pan":
            dt = (pos.x() - d["pos"].x()) / max(1, self.width() - self.L - self.R) * (d["t1"] - d["t0"])
            lo, hi = d["v"]
            dv = (pos.y() - d["pos"].y()) / max(1, self.height() - self.T - self.B) * (hi - lo)
            self.t0, self.t1 = d["t0"] - dt, d["t1"] - dt
            self.vrange = (lo + dv, hi + dv)
            self._paths = None
            self.update()
            return
        if d["kind"] == "zoom":                              # around the press; right / up: in
            a, b = d["at"]
            span = (d["t1"] - d["t0"]) * 2 ** (-(pos.x() - d["pos"].x()) / 200)
            span = min(max(span, 4 * US / self.fps), max(self.duration, US) * 20)
            k = (a - d["t0"]) / max(d["t1"] - d["t0"], 1)
            self.t0, self.t1 = a - span * k, a - span * k + span
            f = 2 ** ((pos.y() - d["pos"].y()) / 200)
            lo, hi = d["v"]
            self.vrange = (b - (b - lo) * f, b + (hi - b) * f)
            self._paths = None
            self.update()
            return
        if d["kind"] == "seek":
            self.seekRequested.emit(min(max(self.t_of(pos.x()), 0), self.duration))
            return
        if d["kind"] == "band":
            if not d["moved"] and (pos - d["pos"]).manhattanLength() < 4:
                return
            d["moved"] = True
            self.band = QRectF(d["pos"], pos).normalized()
            hit = {(ci, i) for ci, c in enumerate(self.curves) for i in range(len(c["keys"]))
                   if self.band.contains(self.key_point(ci, i))}
            self._set_sel(d["base"] | hit)
            return
        if d["kind"] == "keys":
            if not d["moved"] and (pos - d["pos"]).manhattanLength() < 3:
                return
            d["moved"] = True
            frame = US / self.fps
            dt = round((self.t_of(pos.x()) - self.t_of(d["pos"].x())) / frame) * frame
            lo, hi = d["bounds"]
            dt = min(max(dt, lo), hi)
            dp = self.p_of(pos.y()) - self.p_of(d["pos"].y())
            if e.modifiers() & Qt.ShiftModifier:           # keep to the main direction
                if abs(pos.x() - d["pos"].x()) >= abs(pos.y() - d["pos"].y()):
                    dp = 0.0
                else:
                    dt = 0
            for ci, i in self.sel:
                o = d["orig"][ci][i]
                k = self.curves[ci]["keys"][i]
                k[0] = int(round(o[0] + dt))
                if not self.curves[ci]["color"]:
                    k[1] = self.vv(ci, self.pv(ci, o[1]) + dp)
            self._paths = None
            self.keysLive.emit(self._changes(d["orig"].keys()))
            self.update()
            return
        if d["kind"] == "handle":
            ci, i = d["ref"]
            c = self.curves[ci]
            keys, k = c["keys"], c["keys"][d["ref"][1]]
            t = min(max(self.t_of(pos.x()), 0), self.duration)
            v = self.vv(ci, self.p_of(pos.y()))
            if d["side"] == "r":
                k[4] = min(max(t - k[0], 0), keys[i + 1][0] - k[0])
                k[5] = 0.0 if c["color"] else v - k[1]
            else:
                k[2] = max(min(t - k[0], 0), -(k[0] - keys[i - 1][0]))
                k[3] = 0.0 if c["color"] else v - k[1]
            d["moved"] = True
            self._paths = None
            self.keysLive.emit(self._changes([ci]))
            self.update()

    def _changes(self, cis):
        return [(ci, copy.deepcopy(self.curves[ci]["keys"])) for ci in sorted(set(cis))]

    def mouseReleaseEvent(self, e):
        d, self.drag = self.drag, None
        if d is None:
            return
        if d["kind"] == "band":
            self.band = None
            if not d["moved"]:
                if not d["base"]:
                    self._set_sel(set())
                self.seekRequested.emit(min(max(self.t_of(e.position().x()), 0), self.duration))
            self.update()
        elif d["kind"] == "keys" and d["moved"]:
            self.keysCommitted.emit(self._changes(d["orig"].keys()))
        elif d["kind"] == "keys":
            if not (e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)):
                self._set_sel({d["ref"]})                  # a plain click picks one of a selection
        elif d["kind"] == "handle" and d["moved"]:
            self.keysCommitted.emit(self._changes([d["ref"][0]]))

    def mouseDoubleClickEvent(self, e):
        if not self.curves or e.button() != Qt.LeftButton:
            return
        pos = e.position()
        t = int(self.snap_t(min(max(self.t_of(pos.x()), 0), self.duration)))
        # the curve passing closest to the click
        ci = min(range(len(self.curves)),
                 key=lambda j: abs(self.y(self.pv(j, self._kv([0, self.value_at(j, t)]))) - pos.y()))
        c = self.curves[ci]
        if any(abs(k[0] - t) < US / self.fps for k in c["keys"]):
            return
        v = self.value_at(ci, t) if c["color"] else self.vv(ci, self.p_of(pos.y()))
        keys = copy.deepcopy(c["keys"])
        keys.append([t, v, 0.0, 0.0, 0.0, 0.0])
        keys.sort(key=lambda k: k[0])
        c["keys"] = keys
        self.sel = {(ci, next(i for i, k in enumerate(keys) if k[0] == t))}
        self.selectionChanged.emit()
        self.keysCommitted.emit(self._changes([ci]))

    def wheelEvent(self, e):
        pos = e.position()
        mods = e.modifiers()
        if mods & (Qt.AltModifier | Qt.ControlModifier):
            f = 0.8 ** wheel.notch(e)
            if mods & Qt.AltModifier:                        # zoom values around the mouse
                a = self.p_of(pos.y())
                lo, hi = self.vrange
                self.vrange = (a - (a - lo) * f, a + (hi - a) * f)
            else:                                            # Ctrl: zoom time around the mouse
                self.zoom_time(f, pos.x())
        else:                                                # a notch: a tenth of the view
            pw, ph = max(1, self.width() - self.L - self.R), max(1, self.height() - self.T - self.B)
            shift = mods & Qt.ShiftModifier
            dx, dy = wheel.pixels(e, pw / 10, (pw if shift else ph) / 10)
            if shift:                                        # left / right
                dx, dy = dy if abs(dy) >= abs(dx) else dx, 0.0
            dt = -dx / pw * (self.t1 - self.t0)              # (a touchpad moves both ways at once)
            self.t0, self.t1 = self.t0 + dt, self.t1 + dt
            lo, hi = self.vrange
            dv = dy / ph * (hi - lo)
            self.vrange = (lo + dv, hi + dv)
        self._paths = None
        self.update()
        e.accept()

    def zoom_time(self, f, x):
        """Zoom time by f (below 1: in) around x."""
        a = self.t_of(x)
        span = min(max((self.t1 - self.t0) * f, 4 * US / self.fps), max(self.duration, US) * 20)
        k = (a - self.t0) / max(self.t1 - self.t0, 1)
        self.t0, self.t1 = a - span * k, a - span * k + span

    def event(self, e):
        f = wheel.pinch(e)
        if f is not None:                                    # a touchpad's pinch zooms time
            self.zoom_time(1 / f, e.position().x())
            self._paths = None
            self.update()
            return True
        # claim Delete and Ctrl+A before the window's clip shortcuts see them
        if e.type() == QEvent.ShortcutOverride:
            if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.sel:
                e.accept()
                return True
            if e.modifiers() & Qt.ControlModifier and (e.key() == Qt.Key_A or e.key() == Qt.Key_D and self.sel):
                e.accept()
                return True
        return super().event(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.sel:
            self.delete_selected()
            e.accept()
        elif e.key() == Qt.Key_D and e.modifiers() & Qt.ControlModifier:
            self._set_sel(set())
            e.accept()
        elif e.key() == Qt.Key_A and e.modifiers() & Qt.ControlModifier:
            self._set_sel({(ci, i) for ci, c in enumerate(self.curves) for i in range(len(c["keys"]))})
            e.accept()
        else:
            super().keyPressEvent(e)

    def delete_selected(self):
        if not self.sel:
            return
        touched = {ci for ci, _ in self.sel}
        changes = []
        for ci in sorted(touched):
            gone = {i for cj, i in self.sel if cj == ci}
            changes.append((ci, [copy.deepcopy(k) for i, k in enumerate(self.curves[ci]["keys"]) if i not in gone]))
        self._set_sel(set())
        self.keysCommitted.emit(changes)               # an empty list means "no keyframes"


class CurveEditor(QWidget):
    keysChanged = Signal(str, list, bool)          # clip id, [(group, key, keys, value if none)], final
    seekRequested = Signal(float)                  # clip time, us
    addAtPlayhead = Signal(str, list)              # clip id, [(group, key)]
    keyJump = Signal(int)                          # -1 previous keyframe, +1 next (playhead)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.params = QListWidget()
        self.params.setMaximumHeight(118)
        self.params.itemChanged.connect(self._ticked)
        lay.addWidget(self.params)
        top = QHBoxLayout()
        self.norm = QCheckBox("正規化")
        self.norm.setToolTip("每條曲線拉到同樣高度；取消則共用一個數值軸")
        self.norm.setChecked(True)
        self.norm.toggled.connect(lambda on: self.canvas.set_normalize(on))
        only = QPushButton("只看有關鍵幀的")
        only.clicked.connect(self._only_animated)
        fit = QPushButton("全部顯示")
        fit.clicked.connect(lambda: self.canvas.fit())
        top.addWidget(self.norm)
        self.batch = QCheckBox("一起修改")
        self.batch.setChecked(True)
        self.batch.setStyleSheet("QCheckBox { color: #5ad6ff; }")
        self.batch.toggled.connect(lambda _on: self._show_links())
        self.batch.hide()
        top.addWidget(self.batch)
        top.addStretch()
        top.addWidget(only)
        top.addWidget(fit)
        lay.addLayout(top)
        self.canvas = CurveCanvas()
        self.canvas.keysLive.connect(lambda ch: self._emit(ch, False))
        self.canvas.keysCommitted.connect(lambda ch: self._emit(ch, True))
        self.canvas.seekRequested.connect(self.seekRequested)
        self.canvas.selectionChanged.connect(self._show_key)
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
        self.time.edited.connect(self._time_typed)
        self.value.edited.connect(self._value_typed)
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
        for text, d, tip in (("◀", -1, "上一個關鍵幀"), ("▶", 1, "下一個關鍵幀")):
            b = QPushButton(text)
            b.setFixedWidth(30)
            b.setToolTip(tip + "（播放頭跳過去）")
            b.clicked.connect(lambda _=False, d=d: self.keyJump.emit(d))
            acts.addWidget(b)
        add = QPushButton("在播放頭新增")
        add.setToolTip("替勾選的每個參數在播放頭加一個關鍵幀")
        add.clicked.connect(lambda: self.clip and self.addAtPlayhead.emit(
            self.clip["id"], [(g, k) for g, k, *_ in self.shown]))
        delete = QPushButton("刪除選取的關鍵幀")
        delete.clicked.connect(self.canvas.delete_selected)
        acts.addWidget(add)
        acts.addWidget(delete)
        lay.addLayout(acts)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #9a9aa0;")
        lay.addWidget(self.hint)
        self.clip = None
        self.fps = 60.0
        self.t = 0
        self.rows = []               # every parameter of the clip
        self.checked = set()         # (group, key) ticked; kept from clip to clip
        self.shown = []              # rows ticked, in list order
        self.links = (0, 0, {})      # (other clips selected, those with alike keys, {(group, key): {key index: n}})
        self.set_clip(None, 0, 60.0)

    # -- state ------------------------------------------------------------------------------------
    def set_clip(self, c, t, fps):
        """Show clip c (or nothing) at clip time t."""
        same = c is not None and self.clip is not None and c["id"] == self.clip["id"]
        self.clip, self.fps, self.t = c, fps, t
        self.setEnabled(c is not None)
        rows = param_rows(c) if c else []
        if [r[:2] for r in rows] != [r[:2] for r in self.rows] or not same:
            self.rows = rows
            names = {r[:2] for r in rows}
            if not same and not (self.checked & names):
                animated = {(g, k) for g, k, *_ in rows if curves.is_animated(holder(c, g).get(k))}
                self.checked |= animated or ({rows[0][:2]} if rows else set())
            self._fill_list()
            self._refresh(fit=True)
            return
        self._label_list()
        self._refresh(fit=False)

    def set_time(self, c, t):
        """Playhead moved: only the red line moves unless the clip changed."""
        if c is None or self.clip is None or c["id"] != self.clip["id"]:
            self.set_clip(c, t, self.fps)
            return
        self.t = t
        self.canvas.t = t
        self.canvas.update()

    def _fill_list(self):
        self.params.blockSignals(True)
        self.params.clear()
        for g, k, lab, *_ in self.rows:
            it = QListWidgetItem(lab)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if (g, k) in self.checked else Qt.Unchecked)
            it.setData(Qt.UserRole, (g, k))
            self.params.addItem(it)
        self.params.blockSignals(False)
        self._label_list()

    def _label_list(self):
        """● marks animated parameters; ticked ones take their curve's colour."""
        self.params.blockSignals(True)
        slot = 0
        for i, (g, k, lab, *_) in enumerate(self.rows):
            it = self.params.item(i)
            anim = curves.is_animated(holder(self.clip, g).get(k)) if self.clip else False
            it.setText(("● " if anim else "    ") + lab)
            if (g, k) in self.checked:
                it.setForeground(QColor(CURVE_COLORS[slot % len(CURVE_COLORS)]))
                slot += 1
            else:
                it.setForeground(QColor("#c8c8cc"))
        self.params.blockSignals(False)

    def _ticked(self, it):
        gk = tuple(it.data(Qt.UserRole))
        if it.checkState() == Qt.Checked:
            self.checked.add(gk)
        else:
            self.checked.discard(gk)
        self._label_list()
        self._refresh(fit=True)

    def _only_animated(self):
        if not self.clip:
            return
        anim = {(g, k) for g, k, *_ in self.rows if curves.is_animated(holder(self.clip, g).get(k))}
        if not anim:
            self.hint.setText("這個片段沒有關鍵幀")
            return
        self.checked -= {r[:2] for r in self.rows}
        self.checked |= anim
        self._fill_list()
        self._refresh(fit=True)

    def _refresh(self, fit):
        c = self.clip
        self.shown = [r for r in self.rows if r[:2] in self.checked] if c else []
        specs = []
        for slot, (g, k, lab, factor, default) in enumerate(self.shown):
            p = holder(c, g).get(k, default)
            keys = p["keys"] if curves.is_animated(p) else []
            specs.append({"label": lab, "factor": factor, "keys": keys, "slot": slot,
                          "static": p if not keys else default})
        self.canvas.set_curves(specs, c["duration_us"] if c else 1, self.fps, self.t, keep_view=not fit)
        self._show_links()
        self._show_key()

    def set_links(self, others, linked, links):
        """批量: others other clips are selected, linked of them have keyframes alike this
        clip's; links {(group, key): {key index: how many clips}} (keybatch.match)."""
        self.links = (others, linked, links)
        self._show_links()

    def batch_on(self):
        return self.links[1] > 0 and self.batch.isChecked()

    def _show_links(self):
        others, linked, links = self.links
        self.batch.setVisible(others > 0)
        self.batch.setEnabled(linked > 0)
        self.batch.setText(f"一起修改另外 {linked} 個片段" if linked else "其他選取的片段沒有相近的關鍵幀")
        self.batch.setToolTip("多選時，其他片段在同一參數、相差一幀內、數值相差 1% 內的關鍵幀（藍框）會跟著一起改："
                              "移動、改數值、改曲線、刪除、新增")
        on = linked > 0 and self.batch.isChecked()
        self.canvas.linked = {ci: links.get(r[:2], {}) for ci, r in enumerate(self.shown)} if on else {}
        self.canvas.update()

    def _single(self):
        cv = self.canvas
        if len(cv.sel) != 1:
            return None
        ci, i = next(iter(cv.sel))
        return ci, i

    def _show_key(self):
        """Time / value fields: a selection's shared value, or "--" where they differ (typing
        sets every selected keyframe)."""
        cv = self.canvas
        sel = sorted(cv.sel)
        one = self._single()
        keys = [cv.curves[ci]["keys"][i] for ci, i in sel]
        numeric = [(ci, i) for ci, i in sel if not cv.curves[ci]["color"]]
        one_per_curve = len({ci for ci, _ in sel}) == len(sel)
        self.time.setEnabled(bool(sel) and one_per_curve)
        self.value.setEnabled(bool(numeric))
        if sel:
            times = {round(k[0] / US, 3) for k in keys}
            self.time.show_value(times.pop()) if len(times) == 1 else self.time.show_mixed()
            vals = {round(cv.curves[ci]["keys"][i][1] * cv.curves[ci]["factor"], 3) for ci, i in numeric}
            if vals:
                self.value.show_value(vals.pop()) if len(vals) == 1 else self.value.show_mixed()
        if one is not None:
            ci, i = one
            ks = cv.curves[ci]["keys"]
            if i + 1 < len(ks):
                x1, y1, x2, y2 = curves.segment_bezier(ks[i], ks[i + 1])
                self.bezier.setText(f"{x1:.3g}, {y1:.3g}, {x2:.3g}, {y2:.3g}")
                self.hint.setText(f"{cv.curves[ci]['label']}：曲線作用在選取的關鍵幀到下一個關鍵幀之間")
            else:
                self.bezier.clear()
                self.hint.setText(f"{cv.curves[ci]['label']}：最後一個關鍵幀之後沒有曲線")
        elif sel:
            segs = {curves.segment_bezier(cv.curves[ci]["keys"][i], cv.curves[ci]["keys"][i + 1])
                    for ci, i in sel if i + 1 < len(cv.curves[ci]["keys"])}
            if len(segs) == 1:
                x1, y1, x2, y2 = segs.pop()
                self.bezier.setText(f"{x1:.3g}, {y1:.3g}, {x2:.3g}, {y2:.3g}")
            else:
                self.bezier.setText("--" if segs else "")
            self.hint.setText("")
        else:
            self.bezier.clear()
            self.hint.setText("")

    def select_param(self, group, key):
        """Show this parameter's curve too (e.g. after its ◆ was clicked in the inspector)."""
        if (group, key) in self.checked or (group, key) not in {r[:2] for r in self.rows}:
            return
        self.checked.add((group, key))
        self._fill_list()
        self._refresh(fit=True)

    # -- edits ------------------------------------------------------------------------------------
    def _emit(self, changes, final):
        """changes: [(curve index, keys)] from the canvas."""
        if not self.clip:
            return
        out = []
        for ci, keys in changes:
            g, k = self.shown[ci][:2]
            old = self.canvas.curves[ci]
            keep = old["keys"][0][1] if old["keys"] else old["static"]
            if not keys and final:
                # the value the last keyframe had, so deleting it does not jump
                cur = holder(self.clip, g).get(k)
                keep = cur["keys"][0][1] if curves.is_animated(cur) else keep
            out.append((g, k, keys, keep))
        self.keysChanged.emit(self.clip["id"], out, final)
        if final:
            self._show_key()

    def _typed(self, change):
        """Apply change(curve, key) to every selected keyframe, as one edit."""
        cv = self.canvas
        if not cv.sel:
            return
        changed = {}
        for ci, i in sorted(cv.sel):
            keys = changed.setdefault(ci, copy.deepcopy(cv.curves[ci]["keys"]))
            change(cv.curves[ci], keys[i])
        self._emit(sorted(changed.items()), True)

    def _time_typed(self, v):
        t = int(self.canvas.snap_t(v * US))
        self._typed(lambda c, k: k.__setitem__(0, t))

    def _value_typed(self, v):
        self._typed(lambda c, k: None if c["color"] else k.__setitem__(1, v / c["factor"]))

    def _set_bezier(self, spec):
        cv = self.canvas
        targets = [(ci, i) for ci, i in sorted(cv.sel) if i + 1 < len(cv.curves[ci]["keys"])]
        if not targets:
            self.hint.setText("先選一個後面還有關鍵幀的關鍵幀")
            return
        changed = {}
        for ci, i in targets:
            keys = changed.setdefault(ci, copy.deepcopy(cv.curves[ci]["keys"]))
            curves.apply_bezier(keys[i], keys[i + 1], *spec)
        self._emit(sorted(changed.items()), True)

    def _apply_bezier(self):
        if self.bezier.text().strip() == "--":
            return
        try:
            self._set_bezier(curves.parse_bezier(self.bezier.text()))
        except ValueError as exc:
            self.hint.setText(str(exc))
