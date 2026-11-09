"""A curve a filter parameter holds (fx's `curve` type), edited as the keyframe curve editor does:
keys on a plot from x = 0 to 1, each with bezier handles (drag a key or its handles, double-click
to add a key, Delete to remove the selected, the wheel zooms). The 緩動 buttons shape the segments
after the selected keys (all of them when none is selected) like the keyframe editor's presets.
"""
import copy
import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .. import curves, fx
from .curve_editor import PRESETS, US, CurveCanvas

FPS = 1000.0                       # (x snaps to 0.001)


class UnitCanvas(CurveCanvas):
    """The keyframe canvas with a plain 0 - 1 ruler and no playhead. A key dragged along x goes on past the others (the
    keys are in the order of their x again, none is lost), where the keyframe editor keeps every key between its neighbours."""

    def x_label(self, t):
        return f"{t:.3g}"

    def _bounds(self):
        lo, hi = -math.inf, math.inf
        for ci, i in self.sel:
            t = self.curves[ci]["keys"][i][0]
            lo, hi = max(lo, -t), min(hi, self.duration - t)
        return lo, hi

    def _move_keys(self, d, dt, dp):
        if len(d["orig"]) != 1 or any(ci != 0 for ci, _ in d["sel"]):
            return super()._move_keys(d, dt, dp)
        orig = d["orig"][0]
        chosen = sorted(i for _ci, i in d["sel"])
        keys = [copy.deepcopy(k) for k in orig]
        for i in chosen:
            keys[i][0] = int(round(orig[i][0] + dt))
            keys[i][1] = self.vv(0, self.pv(0, orig[i][1]) + dp)
        ref_i = d.setdefault("ref0", d["ref"][1])                  # (the key under the pointer, as the press numbered it)
        rows = sorted(((keys[j], j in chosen, j == ref_i) for j in range(len(orig))), key=lambda r: (r[0][0], r[1]))
        out = [r[0] for r in rows]
        for n in range(1, len(out)):                             # (no two keys at one x: the one being dragged steps aside)
            if out[n][0] <= out[n - 1][0]:
                if rows[n][1] or not rows[n - 1][1]:
                    out[n][0] = out[n - 1][0] + 1
                else:
                    out[n - 1][0] = out[n][0] - 1
        for n, k in enumerate(out):                              # (a handle does not reach past the next key)
            if n + 1 < len(out):
                k[4] = min(k[4], out[n + 1][0] - k[0])
            if n > 0:
                k[2] = max(k[2], -(k[0] - out[n - 1][0]))
        self.curves[0]["keys"] = out
        self.sel = {(0, n) for n, r in enumerate(rows) if r[1]}
        d["ref"] = (0, next(n for n, r in enumerate(rows) if r[2]))

    def mouseDoubleClickEvent(self, e):
        super().mouseDoubleClickEvent(e)


class CurveField(QWidget):
    changed = Signal(list)         # the keys (fx.curve_keys), while dragging and when done
    live = Signal(list)            # the keys while a drag is on (the same as `changed` then)
    finished = Signal(list)        # the keys when an edit is done (a drag let go, a key added or removed, a button)

    def __init__(self, compact=False):
        """compact: the field a node holds in itself - no endless drags (the view scales it), a shorter plot, the buttons in two rows."""
        super().__init__()
        self.keys = fx.curve_keys(None)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        self.canvas = UnitCanvas()
        self.canvas.setMinimumHeight(120 if compact else 240)
        if compact:
            self.canvas.wrapping = False
            self.canvas.L, self.canvas.R, self.canvas.T, self.canvas.B = 32, 14, 8, 18
        self.canvas.set_normalize(False)
        lay.addWidget(self.canvas)
        row = QGridLayout() if compact else QHBoxLayout()
        row.setSpacing(3)
        buttons = []
        for name, spec in PRESETS:
            b = QPushButton(name)
            b.clicked.connect(lambda _=False, s=spec: self._shape(s))
            buttons.append(b)
        reset = QPushButton("重設")
        reset.clicked.connect(lambda: self._send(fx.curve_keys(None)))
        buttons.append(reset)
        for n, b in enumerate(buttons):
            if compact:
                b.setFocusPolicy(Qt.NoFocus)
                b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)         # (the node's width is what it is: the buttons share it)
                b.setFixedHeight(22)
                b.setStyleSheet("padding: 0px; font-size: 11px;")
                row.addWidget(b, n // 3, n % 3)
            else:
                row.addWidget(b)
        lay.addLayout(row)
        self.canvas.keysLive.connect(lambda ch: self._take(ch, False))
        self.canvas.keysCommitted.connect(lambda ch: self._take(ch, True))
        self.canvas.set_normalize(False)
        self._show()

    @property
    def drag(self):
        return self.canvas.drag

    # -- value <-> the canvas (x in microseconds there, 1 s = the whole 0 - 1) -------------------------
    def set_value(self, v):
        keys = fx.curve_keys(v)
        if self.canvas.drag is not None or keys == self.keys:
            return                                              # (nothing new: keep the selection and the drag)
        self.keys = keys
        self._show()

    def _show(self):
        keys = [[k[0] * US, k[1], k[2] * US, k[3], k[4] * US, k[5]] for k in self.keys]
        cv = self.canvas
        cv.set_curves([{"label": "過渡曲線", "factor": 1.0, "keys": keys, "static": 0.0}], US, FPS, -10 ** 12,
                      keep_view=True)
        if not cv.drag:
            cv.vrange = (-0.25, 1.25)
            cv._paths = None
            cv.update()

    def _take(self, changes, final):
        keys = changes[0][1] if changes else []
        out = [[k[0] / US, k[1], k[2] / US, k[3], k[4] / US, k[5]] for k in keys] or fx.curve_keys(None)
        self.keys = out
        self.changed.emit(copy.deepcopy(out))
        (self.finished if final else self.live).emit(copy.deepcopy(out))
        if final:
            self._show()

    def _send(self, keys):
        self.keys = keys
        self.changed.emit(copy.deepcopy(keys))
        self.finished.emit(copy.deepcopy(keys))
        self.canvas.sel = set()
        self.canvas.fit()
        self._show()

    def _shape(self, spec):
        keys = copy.deepcopy(self.keys)
        sel = {i for _ci, i in self.canvas.sel}
        for i in range(len(keys) - 1):
            if not sel or i in sel:
                curves.apply_bezier(keys[i], keys[i + 1], *spec)
        self._send_keep(keys)

    def _send_keep(self, keys):
        self.keys = keys
        self.changed.emit(copy.deepcopy(keys))
        self.finished.emit(copy.deepcopy(keys))
        self._show()
