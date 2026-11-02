"""A curve a filter parameter holds (fx's `curve` type), edited as the keyframe curve editor does:
keys on a plot from x = 0 to 1, each with bezier handles (drag a key or its handles, double-click
to add a key, Delete to remove the selected, the wheel zooms). The 緩動 buttons shape the segments
after the selected keys (all of them when none is selected) like the keyframe editor's presets.
"""
import copy

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from .. import curves, fx
from .curve_editor import PRESETS, US, CurveCanvas

FPS = 1000.0                       # (x snaps to 0.001)


class UnitCanvas(CurveCanvas):
    """The keyframe canvas with a plain 0 - 1 ruler and no playhead."""

    def x_label(self, t):
        return f"{t:.3g}"

    def mouseDoubleClickEvent(self, e):
        super().mouseDoubleClickEvent(e)


class CurveField(QWidget):
    changed = Signal(list)         # the keys (fx.curve_keys), while dragging and when done

    def __init__(self):
        super().__init__()
        self.keys = fx.curve_keys(None)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        self.canvas = UnitCanvas()
        self.canvas.setMinimumHeight(240)
        self.canvas.set_normalize(False)
        lay.addWidget(self.canvas)
        row = QHBoxLayout()
        row.setSpacing(3)
        for name, spec in PRESETS:
            b = QPushButton(name)
            b.clicked.connect(lambda _=False, s=spec: self._shape(s))
            row.addWidget(b)
        reset = QPushButton("重設")
        reset.clicked.connect(lambda: self._send(fx.curve_keys(None)))
        row.addWidget(reset)
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
        if final:
            self._show()

    def _send(self, keys):
        self.keys = keys
        self.changed.emit(copy.deepcopy(keys))
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
        self._show()
