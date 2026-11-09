"""LFO (lfo.py): the wave, how fast it goes (Hz or seconds a cycle), how far it swings and about what, where in the
cycle it starts, how long it takes to swing fully, repeating or mirrored - with a picture of the number over the first
few cycles. The wave can be a cubic-bezier or a curve of any number of points, drawn over one cycle."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                               QSpinBox, QVBoxLayout, QWidget)

from .. import lfo, mapping
from . import mapdialog
from .curvefield import CurveField
from .mapdialog import spin
from .tools import BezierField


class WavePreview(QWidget):
    """The number over time: seconds across, the number up; the dashed line is the offset."""

    def __init__(self):
        super().__init__()
        self.s = lfo.make()
        self.setMinimumSize(320, 190)

    def set_spec(self, s):
        self.s = s
        self.update()

    def seconds(self):
        s = self.s
        h = lfo.hz(s) if lfo.check(s) is None else 0.0
        span = 3.0 / h if h > 0 else 4.0
        return max(span, s.get("fade", 0.0) * 1.5, 0.05)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#18181b"))
        area = QRectF(46, 10, self.width() - 58, self.height() - 34)
        p.fillRect(area, QColor("#202024"))
        s = self.s
        if lfo.check(s):
            p.setPen(QColor("#ff7a7a"))
            p.drawText(area, Qt.AlignCenter, "（這個 LFO 算不出來）")
            return
        span = self.seconds()
        pts = lfo.points(s, span, 240)
        ys = [y for _x, y in pts] + [s["offset"]]
        y0, y1 = min(ys), max(ys)
        if y1 - y0 < 1e-9:
            y0, y1 = y0 - 0.5, y1 + 0.5
        pad = (y1 - y0) * 0.08
        y0, y1 = y0 - pad, y1 + pad

        def at(x, y):
            return QPointF(area.left() + x / span * area.width(), area.bottom() - (y - y0) / (y1 - y0) * area.height())
        p.setPen(QPen(QColor("#2c2c31"), 1, Qt.DotLine))
        for f in (0.25, 0.5, 0.75):
            p.drawLine(QPointF(area.left() + f * area.width(), area.top()), QPointF(area.left() + f * area.width(), area.bottom()))
        p.setPen(QPen(QColor("#6a6a72"), 1, Qt.DashLine))
        p.drawLine(at(0, s["offset"]), at(span, s["offset"]))
        path = QPainterPath(at(*pts[0]))
        for x, y in pts[1:]:
            path.lineTo(at(x, y))
        p.setPen(QPen(QColor("#6fb3ff"), 2.5))
        p.drawPath(path)
        p.setPen(QColor("#8e8e94"))
        p.setFont(QFont(p.font().family(), 8))
        p.drawText(QRectF(0, area.top() - 6, 44, 14), Qt.AlignRight | Qt.AlignVCenter, f"{y1:.4g}")
        p.drawText(QRectF(0, area.bottom() - 8, 44, 14), Qt.AlignRight | Qt.AlignVCenter, f"{y0:.4g}")
        p.drawText(QRectF(area.left(), area.bottom() + 3, 80, 16), Qt.AlignLeft, "0 秒")
        p.drawText(QRectF(area.right() - 80, area.bottom() + 3, 80, 16), Qt.AlignRight, f"{span:.3g} 秒")


class LfoDialog(QDialog):
    """Edit one LFO. `clip`: it is for a clip's number (a 疊加在原本的值上 box is offered)."""

    def __init__(self, parent, title, s, note="", clip=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)
        s = lfo.make(**{"wave": s["wave"], "unit": s["unit"], "rate": s["rate"], "amp": s["amp"], "offset": s["offset"],
                        "phase": s["phase"], "fade": s["fade"], "loop": s["loop"], "width": s["width"],
                        "bezier": s["bezier"], "curve": s.get("curve"), "bipolar": s["bipolar"], "rel": s["rel"],
                        "seed": s.get("seed", 0)})
        lay = QVBoxLayout(self)
        if note:
            head = QLabel(note)
            head.setWordWrap(True)
            lay.addWidget(head)
        self.form = QFormLayout()
        self.wave = QComboBox()
        for k, name in lfo.WAVES:
            self.wave.addItem(name, k)
        self.wave.setCurrentIndex(self.wave.findData(s["wave"]))
        self.form.addRow("波形", self.wave)
        self.loop = QComboBox()
        for k, name in lfo.LOOPS:
            self.loop.addItem(name, k)
        self.loop.setCurrentIndex(self.loop.findData(s["loop"]))
        self.loop.setToolTip("重複：每個週期都從波形的開頭再跑一次；鏡像：先正著跑一遍，再倒著跑回來")
        self.form.addRow("週期的接法", self.loop)
        self.unit = QComboBox()
        for k, name in lfo.UNITS:
            self.unit.addItem(name, k)
        self.unit.setCurrentIndex(self.unit.findData(s["unit"]))
        self.rate = spin(s["rate"], 3)
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(self.unit, 1)
        hl.addWidget(self.rate, 1)
        self.form.addRow("速度", row)
        self.amp, self.offset = spin(s["amp"]), spin(s["offset"])
        self.form.addRow("振幅（擺多遠）", self.amp)
        self.form.addRow("偏移（擺動的中心）", self.offset)
        self.bipolar = QCheckBox("雙極（在中心上下擺；取消則只往上擺 0 – 振幅）")
        self.bipolar.setChecked(s["bipolar"])
        self.form.addRow("", self.bipolar)
        self.phase = spin(s["phase"], 1)
        self.phase.setSuffix(" °")
        self.form.addRow("相位（一開始在週期的哪裡）", self.phase)
        self.fade = spin(s["fade"], 2)
        self.fade.setSuffix(" 秒")
        self.fade.setToolTip("從開始起，擺動的幅度花這麼久慢慢長到完整（0：一開始就是完整的）")
        self.form.addRow("漸入", self.fade)
        self.width = spin(s["width"], 2)
        self.width.setRange(0.0, 1.0)
        self.width.setSingleStep(0.05)
        self.form.addRow("脈衝寬度（方波高的部分）", self.width)
        self.seed = QSpinBox()
        self.seed.setRange(0, 99999)
        self.seed.setValue(s.get("seed", 0))
        self.form.addRow("種子（隨機、雜訊）", self.seed)
        self.rel = QCheckBox("疊加在數字原本的值上（關鍵幀照常，LFO 加在它上面）")
        self.rel.setChecked(s["rel"])
        if clip:
            self.form.addRow("", self.rel)
        self.bz = [spin(v, 3) for v in s["bezier"]]
        box = QWidget()
        hl = QHBoxLayout(box)
        hl.setContentsMargins(0, 0, 0, 0)
        for b in self.bz:
            hl.addWidget(b)
        self.presets = QComboBox()
        self.presets.addItem("預設曲線…", None)
        for name, v in mapping.BEZIER_PRESETS:
            self.presets.addItem(name, v)
        for c in mapdialog.saved_curves():
            self.presets.addItem("我的：" + c["name"], tuple(c["value"]))
        self.form.addRow("曲線預設", self.presets)
        self.form.addRow("cubic-bezier (x1, y1, x2, y2)", box)
        self.rows = {"loop": self.loop, "width": self.width, "seed": self.seed, "presets": self.presets, "bezier": box}
        lay.addLayout(self.form)
        self.preview = WavePreview()
        self.field = BezierField()
        self.field.setMinimumSize(220, 300)
        self.field.set_value(s["bezier"])
        self.field.setToolTip("拖曳兩個圓點調整一個週期的波形（y 可以超出 0 – 1）")
        self.cfield = CurveField()
        self.cfield.set_value(s["curve"])
        self.cfield.setMinimumWidth(220)
        self.cfield.setToolTip("一個週期的波形：拖曳點調整曲線，點一下新增點，Delete 刪除（0 – 1 的高度）")
        pic = QHBoxLayout()
        pic.addWidget(self.preview, 2)
        pic.addWidget(self.field, 1)
        pic.addWidget(self.cfield, 1)
        lay.addLayout(pic)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #ff7a7a;")
        lay.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        for w in (self.rate, self.amp, self.offset, self.phase, self.fade, self.width, self.seed, *self.bz):
            w.valueChanged.connect(self._changed)
        for w in (self.wave, self.loop, self.unit):
            w.currentIndexChanged.connect(self._changed)
        for w in (self.bipolar, self.rel):
            w.toggled.connect(self._changed)
        self.presets.activated.connect(self._preset)
        self.field.changed.connect(self._dragged)
        self.cfield.changed.connect(self._changed)
        self._changed()

    def _preset(self, i):
        v = self.presets.itemData(i)
        if v is not None:
            self._dragged(v)

    def _dragged(self, v):
        for b, x in zip(self.bz, v):
            b.blockSignals(True)
            b.setValue(x)
            b.blockSignals(False)
        self._changed()

    def spec(self):
        return {"wave": self.wave.currentData(), "unit": self.unit.currentData(), "rate": self.rate.value(),
                "amp": self.amp.value(), "offset": self.offset.value(), "phase": self.phase.value(),
                "fade": self.fade.value(), "loop": self.loop.currentData(), "width": self.width.value(),
                "bezier": [b.value() for b in self.bz], "curve": [list(k) for k in self.cfield.keys],
                "bipolar": self.bipolar.isChecked(), "rel": self.rel.isChecked(), "seed": self.seed.value()}

    def _changed(self, *_a):
        w = self.wave.currentData()
        show = {"loop": w in lfo.MIRRORABLE, "width": w == "square", "seed": w in ("random", "noise"),
                "presets": w == "bezier", "bezier": w == "bezier"}
        for key, on in show.items():
            self.rows[key].setVisible(on)
            label = self.form.labelForField(self.rows[key])
            if label is not None:
                label.setVisible(on)
        self.field.setVisible(w == "bezier")
        self.cfield.setVisible(w == "curve")
        self.field.set_value([b.value() for b in self.bz])
        s = self.spec()
        why = lfo.check(s)
        self.preview.set_spec(s)
        self.status.setText("✗ " + why if why else "")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(why is None)
        self.layout().activate()
        self.resize(self.size().expandedTo(self.sizeHint()))


def ask_lfo(parent, title, s=None, note="", clip=False):
    """The LFO spec chosen, or None when cancelled."""
    d = LfoDialog(parent, title, s or lfo.make(), note, clip)
    d.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
    return d.spec() if d.exec() == QDialog.Accepted else None
