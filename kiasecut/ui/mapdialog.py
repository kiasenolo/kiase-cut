"""映射 (mapping.py) when a number is bound to a parameter: how the parameter's value becomes the number
- as it is, along a straight line between a minimum and a maximum, along a cubic-bezier curve, along a curve of
any number of points (which a JavaScript expression reads as curve(x) too), or by a JavaScript expression - with a
picture of the curve it makes."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QInputDialog,
                               QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from .. import mapping
from .curvefield import CurveField
from .tools import BezierField


saved_curves = lambda: []                     # () -> [{name, value}]: the curves kept in 工具 > cubic-bezier 編輯器
save_curve = lambda name, value: None         # (name, [x1, y1, x2, y2]): keeps one there (both set by the main window)


def spin(value, decimals=3):
    s = QDoubleSpinBox()
    s.setRange(-1e9, 1e9)
    s.setDecimals(decimals)
    s.setSingleStep(0.1)
    s.setKeyboardTracking(False)
    s.setValue(value)
    return s


class CurvePreview(QWidget):
    """The mapping's curve: the parameter's value across, the number up, with the value it has now marked."""

    def __init__(self):
        super().__init__()
        self.m = mapping.make()
        self.current = None                   # the parameter's value now (a dot on the curve)
        self.env = {}
        self.setMinimumSize(300, 190)

    def set_mapping(self, m):
        self.m = m
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#18181b"))
        area = QRectF(46, 10, self.width() - 58, self.height() - 34)
        p.fillRect(area, QColor("#202024"))
        m = self.m
        if mapping.check(m):
            p.setPen(QColor("#ff7a7a"))
            p.drawText(area, Qt.AlignCenter, "（這個映射算不出來）")
            return
        lo, hi = (m["in"] if m["mode"] != "direct" else (0.0, 1.0))
        pts = [(lo + (hi - lo) * i / 96, mapping.apply(m, lo + (hi - lo) * i / 96, self.env)) for i in range(97)]
        ys = [y for _x, y in pts]
        y0, y1 = min(ys), max(ys)
        if y1 - y0 < 1e-9:
            y0, y1 = y0 - 0.5, y1 + 0.5
        pad = (y1 - y0) * 0.08
        y0, y1 = y0 - pad, y1 + pad
        span = (hi - lo) or 1.0

        def at(x, y):
            return QPointF(area.left() + (x - lo) / span * area.width(), area.bottom() - (y - y0) / (y1 - y0) * area.height())
        p.setPen(QPen(QColor("#2c2c31"), 1, Qt.DotLine))
        for f in (0.25, 0.5, 0.75):
            p.drawLine(QPointF(area.left() + f * area.width(), area.top()), QPointF(area.left() + f * area.width(), area.bottom()))
            p.drawLine(QPointF(area.left(), area.top() + f * area.height()), QPointF(area.right(), area.top() + f * area.height()))
        path = QPainterPath(at(*pts[0]))
        for x, y in pts[1:]:
            path.lineTo(at(x, y))
        p.setPen(QPen(QColor("#6fb3ff"), 2.5))
        p.drawPath(path)
        if self.current is not None:
            cx = min(max(self.current, min(lo, hi)), max(lo, hi))
            q = at(cx, mapping.apply(m, self.current, self.env))
            p.setPen(QPen(QColor("#ffffff"), 1.5))
            p.setBrush(QColor("#ffb347"))
            p.drawEllipse(q, 5, 5)
        p.setPen(QColor("#8e8e94"))
        p.setFont(QFont(p.font().family(), 8))
        p.drawText(QRectF(0, area.top() - 6, 44, 14), Qt.AlignRight | Qt.AlignVCenter, f"{y1:.4g}")
        p.drawText(QRectF(0, area.bottom() - 8, 44, 14), Qt.AlignRight | Qt.AlignVCenter, f"{y0:.4g}")
        p.drawText(QRectF(area.left(), area.bottom() + 3, 80, 16), Qt.AlignLeft, f"{lo:.4g}")
        p.drawText(QRectF(area.right() - 80, area.bottom() + 3, 80, 16), Qt.AlignRight, f"{hi:.4g}")


class MapDialog(QDialog):
    """Edit one mapping. src_label names what is bound ("全局參數「speed」"); current is its value now (or None);
    env the rack's values (for an expression that reads other parameters)."""

    def __init__(self, parent, title, m, src_label, current=None, env=None, out_hint=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        m = mapping.make(**{k: v for k, v in {"mode": m["mode"], "src": m.get("src", ""), "in_": m["in"], "out": m["out"],
                                             "bezier": m["bezier"], "curve": m.get("curve"), "js": m.get("js") or mapping.DEFAULT_JS}.items()})
        self.src = m["src"]
        lay = QVBoxLayout(self)
        head = QLabel(f"數字跟著{src_label}走。選它的值怎麼變成這個數字：")
        head.setWordWrap(True)
        lay.addWidget(head)
        self.form = QFormLayout()
        self.mode = QComboBox()
        for k, name in mapping.MODES:
            self.mode.addItem(name, k)
        self.mode.setCurrentIndex(self.mode.findData(m["mode"]))
        self.form.addRow("映射方式", self.mode)
        self.in_lo, self.in_hi = spin(m["in"][0]), spin(m["in"][1])
        self.out_lo, self.out_hi = spin(m["out"][0]), spin(m["out"][1])
        if out_hint is not None and m["mode"] == "direct":
            self.out_lo.setValue(out_hint[0])
            self.out_hi.setValue(out_hint[1])
        self.rows = {}
        for key, label, (a, b) in (("in", f"{src_label}的最小值 | 最大值", (self.in_lo, self.in_hi)),
                                   ("out", "數字的最小值 | 最大值", (self.out_lo, self.out_hi))):
            box = QWidget()
            hl = QHBoxLayout(box)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.addWidget(a)
            hl.addWidget(b)
            self.form.addRow(label, box)
            self.rows[key] = (box, self.form.labelForField(box))
        self.bz = [spin(v, 3) for v in m["bezier"]]
        box = QWidget()
        hl = QHBoxLayout(box)
        hl.setContentsMargins(0, 0, 0, 0)
        for s in self.bz:
            hl.addWidget(s)
        self.presets = QComboBox()
        self.presets.addItem("預設曲線…", None)
        for name, v in mapping.BEZIER_PRESETS:
            self.presets.addItem(name, v)
        self.fill_saved()
        keep = QPushButton("存成我的曲線…")
        keep.setToolTip("把現在這條曲線存進 工具 > cubic-bezier 編輯器 的「我的曲線」")
        keep.clicked.connect(self._keep)
        row = QWidget()
        pl = QHBoxLayout(row)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(self.presets, 1)
        pl.addWidget(keep)
        self.form.addRow("曲線預設", row)
        self.form.addRow("cubic-bezier (x1, y1, x2, y2)", box)
        self.rows["bezier"] = (box, self.form.labelForField(box))
        self.rows["presets"] = (row, self.form.labelForField(row))
        self.js = QPlainTextEdit(m["js"])
        self.js.setFont(QFont("monospace"))
        self.js.setFixedHeight(70)
        self.form.addRow("JavaScript", self.js)
        self.rows["js"] = (self.js, self.form.labelForField(self.js))
        lay.addLayout(self.form)
        self.preview = CurvePreview()
        self.preview.current, self.preview.env = current, dict(env or {})
        self.field = BezierField()                         # (the curve's own editor: drag its two handles)
        self.field.setMinimumSize(240, 380)
        self.field.set_value(m["bezier"])
        self.field.setToolTip("拖曳兩個圓點調整曲線（y 可以超出 0 - 1，會有回彈）")
        self.cfield = CurveField()                         # (a curve of any number of points: its own mode, and what curve(x) reads)
        self.cfield.set_value(m["curve"])
        self.cfield.setMinimumWidth(240)
        self.cfield.setToolTip("拖曳點調整曲線，點一下新增點，Delete 刪除；點可以拖過其他的點，其他的點會留著")
        pic = QHBoxLayout()
        pic.addWidget(self.preview, 1)
        pic.addWidget(self.field, 1)
        pic.addWidget(self.cfield, 1)
        lay.addLayout(pic)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        for w in (self.in_lo, self.in_hi, self.out_lo, self.out_hi, *self.bz):
            w.valueChanged.connect(self._changed)
        self.mode.currentIndexChanged.connect(self._changed)
        self.js.textChanged.connect(self._changed)
        self.presets.activated.connect(self._preset)
        self.field.changed.connect(self._dragged)
        self.cfield.changed.connect(self._changed)
        self._changed()

    def fill_saved(self):
        """The curves of 我的曲線 after the built-in ones."""
        for i in range(self.presets.count() - 1, 0, -1):
            if self.presets.itemText(i).startswith("我的："):
                self.presets.removeItem(i)
        for c in saved_curves():
            self.presets.addItem("我的：" + c["name"], tuple(c["value"]))

    def _keep(self):
        name, ok = QInputDialog.getText(self, "存成我的曲線", "曲線的名字：")
        if ok and name.strip():
            save_curve(name.strip(), [s.value() for s in self.bz])
            self.fill_saved()

    def _preset(self, i):
        v = self.presets.itemData(i)
        if v is not None:
            for s, x in zip(self.bz, v):
                s.blockSignals(True)
                s.setValue(x)
                s.blockSignals(False)
            self._changed()

    def _dragged(self, v):
        """The curve's handles were dragged: the four numbers follow."""
        for s, x in zip(self.bz, v):
            s.blockSignals(True)
            s.setValue(x)
            s.blockSignals(False)
        self._changed()

    def mapping(self):
        return {"mode": self.mode.currentData(), "src": self.src, "in": [self.in_lo.value(), self.in_hi.value()],
                "out": [self.out_lo.value(), self.out_hi.value()], "bezier": [s.value() for s in self.bz],
                "curve": [list(k) for k in self.cfield.keys], "js": self.js.toPlainText().strip() or mapping.DEFAULT_JS}

    def _changed(self, *_a):
        mode = self.mode.currentData()
        show = {"in": mode != "direct", "out": mode != "direct", "bezier": mode == "bezier",
                "presets": mode == "bezier", "js": mode == "js"}
        for key, on in show.items():
            for w in self.rows[key]:
                if w is not None:
                    w.setVisible(on)
        self.field.setVisible(mode == "bezier")
        self.cfield.setVisible(mode in ("curve", "js"))
        self.field.set_value([s.value() for s in self.bz])
        m = self.mapping()
        why = mapping.check(m)
        self.preview.set_mapping(m)
        self.status.setText("✗ " + why if why else "")
        self.status.setStyleSheet("color: #ff7a7a;")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(why is None)
        self.layout().activate()
        self.resize(self.size().expandedTo(self.sizeHint()))                  # (a curve editor beside the preview needs the room)


def ask_mapping(parent, title, m, src_label, current=None, env=None, out_hint=None):
    """The mapping chosen, or None when cancelled."""
    d = MapDialog(parent, title, m, src_label, current, env, out_hint)
    d.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
    return d.mapping() if d.exec() == QDialog.Accepted else None
