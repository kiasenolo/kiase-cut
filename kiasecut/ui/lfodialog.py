"""LFO (lfo.py): the wave, how fast it goes (Hz or seconds a cycle), how far it swings and about what, where in the
cycle it starts, how long it takes to swing fully, how long the speed takes to grow from slow, repeating or mirrored - with a picture of the number over the first
few cycles. The wave can be a cubic-bezier or a curve of any number of points, drawn over one cycle."""
import copy
import time

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
                               QLabel, QSpinBox, QVBoxLayout, QWidget)

from .. import lfo, mapping
from . import mapdialog
from . import inertia, viewglide, wheel
from .curvefield import CurveField
from .mapdialog import spin
from .tools import BezierField
from .wrapdrag import WrapDrag


class WavePreview(QWidget):
    """The number over time: seconds across, the number up; the dashed line is the offset. The time moves and zooms as the
    timeline's does (the same inertia settings): the wheel scrolls it, Ctrl + wheel, a pinch or Ctrl + the middle button zooms it
    about the pointer, the middle (or left) button drags it with a little glide after; a double click goes back to the first few cycles."""
    MIN_SPAN, MAX_SPAN = 0.01, 36000.0
    WHEEL_CHANNEL = {"dx": "timeline_scroll", "zoom": "timeline_zoom"}      # (inertia.py: the timeline's settings)

    def __init__(self):
        super().__init__()
        self.s = lfo.make()
        self.view = None                    # (first second, last second) once zoomed or moved, else the first few cycles
        self.drag = None
        self._wheel_queue = {}
        self._wheel_x = 0.0
        self._wheel_last = 0.0
        self._wheel_timer = QTimer(self, interval=8)
        self._wheel_timer.timeout.connect(self._wheel_step)
        self.glide = viewglide.ViewGlide(self, self._glide_pan)
        self.wrap = WrapDrag(self, lambda: QRectF(0, 0, self.width(), self.height()), axes="x")
        self.setMinimumSize(320, 190)
        self.setToolTip("滾輪左右移動時間，Ctrl + 滾輪（或 Ctrl + 中鍵拖曳）縮放，中鍵拖曳移動，按兩下回到預設")

    def set_spec(self, s):
        self.s = s
        self.update()

    def auto_seconds(self):
        s = self.s
        h = lfo.hz(s) if lfo.check(s) is None else 0.0
        span = 3.0 / h if h > 0 else 4.0
        ramp = s.get("ramp", 0.0)
        if ramp > 0 and h > 0:                      # (a ramp from slow: its 3 cycles at full speed come after it)
            span = ramp + span
        return max(span, s.get("fade", 0.0) * 1.5, 0.05)

    def window(self):
        """(first second, seconds shown)."""
        if self.view is None:
            return 0.0, self.auto_seconds()
        return self.view[0], self.view[1] - self.view[0]

    def area(self):
        return QRectF(46, 10, self.width() - 58, self.height() - 34)

    def _set_view(self, t0, span):
        span = min(max(span, self.MIN_SPAN), self.MAX_SPAN)
        t0 = max(0.0, t0)
        self.view = (t0, t0 + span)
        self.update()

    def pan(self, dt):
        t0, span = self.window()
        self._set_view(t0 + dt, span)

    def zoom(self, f, x):
        """Zoom time by f (below 1: in) about the pixel x."""
        t0, span = self.window()
        area = self.area()
        k = min(1.0, max(0.0, (x - area.left()) / max(1.0, area.width())))
        new = min(max(span * f, self.MIN_SPAN), self.MAX_SPAN)
        self._set_view(t0 + (span - new) * k, new)

    def _glide_pan(self, dx, _dy):
        self.pan(-dx / max(1.0, self.area().width()) * self.window()[1])

    def wheelEvent(self, e):
        """As the timeline's wheel: a notch scrolls a tenth of the view, Ctrl + a notch zooms 1.25 times about the pointer; the
        motion is queued and let out as the glide setting says (a touchpad's own motion is applied as it comes)."""
        if e.modifiers() & Qt.ControlModifier:
            part = {"zoom": wheel.notch(e)}
            self._wheel_x = e.position().x()
        else:
            dx, dy = wheel.pixels(e, self.width() / 10, self.width() / 10)
            part = {"dx": -(dx if abs(dx) > abs(dy) else dy)}
        glide = {k: v for k, v in part.items() if not wheel.touchpad(e) and inertia.percent(self.WHEEL_CHANNEL[k])}
        self._wheel_apply({k: v for k, v in part.items() if k not in glide})
        if glide:
            for k, v in glide.items():
                self._wheel_queue[k] = self._wheel_queue.get(k, 0.0) + v
            if not self._wheel_timer.isActive():
                self._wheel_last = time.monotonic()
                self._wheel_timer.start()
        e.accept()

    def _wheel_step(self):
        now = time.monotonic()
        dt = (now - self._wheel_last) * 1000.0
        self._wheel_last = now
        part = {}
        for key, left in list(self._wheel_queue.items()):
            k = 1.0 - 0.5 ** (dt / max(inertia.half_life_ms(self.WHEEL_CHANNEL[key]), 1.0))
            small = 0.5 if key == "dx" else 0.01
            take = left if abs(left) * (1 - k) < small else left * k
            part[key] = take
            if take == left:
                del self._wheel_queue[key]
            else:
                self._wheel_queue[key] = left - take
        if not self._wheel_queue:
            self._wheel_timer.stop()
        self._wheel_apply(part)

    def _wheel_apply(self, part):
        if "zoom" in part:
            self.zoom(1.25 ** -part["zoom"], self._wheel_x)
        if "dx" in part:
            self.pan(part["dx"] / max(1.0, self.area().width()) * self.window()[1])

    def event(self, e):
        f = wheel.pinch(e)
        if f is not None:
            self.zoom(1 / f, e.position().x())
            return True
        return super().event(e)

    def mousePressEvent(self, e):
        self.glide.stop()
        if e.button() in (Qt.MiddleButton, Qt.LeftButton):
            t0, span = self.window()
            zoom = e.button() == Qt.MiddleButton and bool(e.modifiers() & Qt.ControlModifier)
            self.drag = {"kind": "zoom" if zoom else "pan", "x0": e.position().x(), "t0": t0, "span": span, "x": e.position().x()}

    def mouseMoveEvent(self, e):
        d = self.drag
        if d is None:
            return
        if not d.get("wrap"):
            d["wrap"] = True
            self.wrap.start()
        x = self.wrap.pos(e).x()
        area = self.area()
        if d["kind"] == "pan":
            self._set_view(d["t0"] - (x - d["x0"]) / max(1.0, area.width()) * d["span"], d["span"])
            self.glide.sample(x, 0.0)
        else:                                                # about the press; right: in
            k = min(1.0, max(0.0, (d["x"] - area.left()) / max(1.0, area.width())))
            at = d["t0"] + d["span"] * k
            span = min(max(d["span"] * 2 ** (-(x - d["x0"]) / 200), self.MIN_SPAN), self.MAX_SPAN)
            self._set_view(at - span * k, span)

    def mouseReleaseEvent(self, _e):
        d, self.drag = self.drag, None
        if d is not None:
            self.wrap.stop()
            if d["kind"] == "pan":
                self.glide.release()

    def mouseDoubleClickEvent(self, _e):
        self.glide.stop()
        self._wheel_queue.clear()
        self.view = None
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#18181b"))
        area = self.area()
        p.fillRect(area, QColor("#202024"))
        s = self.s
        if lfo.check(s):
            p.setPen(QColor("#ff7a7a"))
            p.drawText(area, Qt.AlignCenter, "（這個 LFO 算不出來）")
            return
        t0, span = self.window()
        pts = lfo.points(s, span, max(240, min(4000, int(area.width() * 2))), t0)
        ys = [y for _x, y in pts] + [s["offset"]]
        y0, y1 = min(ys), max(ys)
        if y1 - y0 < 1e-9:
            y0, y1 = y0 - 0.5, y1 + 0.5
        pad = (y1 - y0) * 0.08
        y0, y1 = y0 - pad, y1 + pad

        def at(x, y):
            return QPointF(area.left() + (x - t0) / span * area.width(), area.bottom() - (y - y0) / (y1 - y0) * area.height())
        p.setPen(QPen(QColor("#2c2c31"), 1, Qt.DotLine))
        for f in (0.25, 0.5, 0.75):
            p.drawLine(QPointF(area.left() + f * area.width(), area.top()), QPointF(area.left() + f * area.width(), area.bottom()))
        p.setPen(QPen(QColor("#6a6a72"), 1, Qt.DashLine))
        p.drawLine(at(t0, s["offset"]), at(t0 + span, s["offset"]))
        path = QPainterPath(at(*pts[0]))
        for x, y in pts[1:]:
            path.lineTo(at(x, y))
        p.setPen(QPen(QColor("#6fb3ff"), 2.5))
        p.drawPath(path)
        p.setPen(QColor("#8e8e94"))
        p.setFont(QFont(p.font().family(), 8))
        p.drawText(QRectF(0, area.top() - 6, 44, 14), Qt.AlignRight | Qt.AlignVCenter, f"{y1:.4g}")
        p.drawText(QRectF(0, area.bottom() - 8, 44, 14), Qt.AlignRight | Qt.AlignVCenter, f"{y0:.4g}")
        p.drawText(QRectF(area.left(), area.bottom() + 3, 80, 16), Qt.AlignLeft, f"{t0:.3g} 秒")
        p.drawText(QRectF(area.right() - 80, area.bottom() + 3, 80, 16), Qt.AlignRight, f"{t0 + span:.3g} 秒")


KEYS = ("wave", "unit", "rate", "amp", "offset", "phase", "fade", "fade_out", "ramp", "ramp_out", "ramp_from", "loop", "width", "seed", "bipolar", "rel", "bezier",
        "curve")


class MixSpin(QDoubleSpinBox):
    """A number showing "--" while the LFOs being edited do not agree on it (until it is typed or stepped)."""

    def __init__(self, value, decimals=3, key=None, owner=None):
        self.mixed, self.key, self.owner = False, key, owner
        super().__init__()
        self.setRange(-1e9, 1e9)
        self.setDecimals(decimals)
        self.setSingleStep(0.1)
        self.setKeyboardTracking(False)
        self.setValue(value)
        self.lineEdit().textEdited.connect(self._touch)
        self.valueChanged.connect(self._touch)

    def show_mixed(self):
        self.mixed = True
        self.lineEdit().setText("--")

    def textFromValue(self, v):
        return "--" if self.mixed else super().textFromValue(v)

    def _touch(self, *_a):
        self.mixed = False
        if self.owner is not None:
            self.owner.touch(self.key)


class LfoDialog(QDialog):
    """Edit one LFO. `clip`: it is for a clip's number (a 疊加在原本的值上 box is offered). specs: the LFOs of
    several clips - a field they do not agree on shows "--" and is only written to them once it is changed."""

    def __init__(self, parent, title, s, note="", clip=False, specs=None):
        super().__init__(parent)
        specs = specs or [s]
        self.touched = set()
        self.base = lfo.make(**specs[0])
        self.mixed = {k for k in KEYS if any(sp.get(k) != specs[0].get(k) for sp in specs[1:])}
        self.setWindowTitle(title)
        self.setMinimumWidth(480)
        s = lfo.make(**{"wave": s["wave"], "unit": s["unit"], "rate": s["rate"], "amp": s["amp"], "offset": s["offset"],
                        "phase": s["phase"], "fade": s["fade"], "fade_out": s.get("fade_out", 0.0), "ramp": s.get("ramp", 0.0), "ramp_out": s.get("ramp_out", 0.0), "ramp_from": s.get("ramp_from", 0.2), "loop": s["loop"], "width": s["width"],
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
        self.rate = self.mix("rate", s["rate"], 3)
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(self.unit, 1)
        hl.addWidget(self.rate, 1)
        self.form.addRow("速度", row)
        self.amp, self.offset = self.mix("amp", s["amp"]), self.mix("offset", s["offset"])
        self.form.addRow("振幅（擺多遠）", self.amp)
        self.form.addRow("偏移（擺動的中心）", self.offset)
        self.bipolar = QCheckBox("雙極（在中心上下擺；取消則只往上擺 0 – 振幅）")
        self.bipolar.setChecked(s["bipolar"])
        self.form.addRow("", self.bipolar)
        self.phase = self.mix("phase", s["phase"], 1)
        self.phase.setSuffix(" °")
        self.form.addRow("相位（一開始在週期的哪裡）", self.phase)
        self.fade = self.mix("fade", s["fade"], 2)
        self.fade.setSuffix(" 秒")
        self.fade.setToolTip("從開始起，擺動的幅度花這麼久慢慢長到完整（0：一開始就是完整的）")
        self.form.addRow("漸入", self.fade)
        self.fade_out = self.mix("fade_out", s["fade_out"], 2)
        self.fade_out.setSuffix(" 秒")
        self.fade_out.setToolTip("到片段結尾前，擺動的幅度花這麼久慢慢收到 0（0：不淡出）")
        if clip:
            self.form.addRow("淡出", self.fade_out)
        self.ramp = self.mix("ramp", s["ramp"], 2)
        self.ramp.setSuffix(" 秒")
        self.ramp.setToolTip("從開始起，速度花這麼久從慢慢加快到完整的速度（0：一開始就是完整的速度）")
        self.form.addRow("時間漸入（由慢到快）", self.ramp)
        self.ramp_out = self.mix("ramp_out", s["ramp_out"], 2)
        self.ramp_out.setSuffix(" 秒")
        self.ramp_out.setToolTip("到片段結尾前，速度花這麼久從完整的速度慢慢降到起始速度（0：不減速）")
        if clip:
            self.form.addRow("時間淡出（由快到慢）", self.ramp_out)
        self.ramp_from = self.mix("ramp_from", s["ramp_from"] * 100, 0)
        self.ramp_from.setRange(0, 100)
        self.ramp_from.setSingleStep(5)
        self.ramp_from.setSuffix(" %")
        self.ramp_from.setToolTip("一開始的速度是完整速度的幾 %")
        self.form.addRow("　起始速度", self.ramp_from)
        self.pulse = self.mix("width", s["width"], 2)
        self.pulse.setRange(0.0, 1.0)
        self.pulse.setSingleStep(0.05)
        self.form.addRow("脈衝寬度（方波高的部分）", self.pulse)
        self.seed = QSpinBox()
        self.seed.setRange(0, 99999)
        self.seed.setValue(s.get("seed", 0))
        self.seed.valueChanged.connect(lambda *_: self.touch("seed"))
        self.form.addRow("種子（隨機、雜訊）", self.seed)
        self.rel = QCheckBox("疊加在數字原本的值上（關鍵幀照常，LFO 加在它上面）")
        self.rel.setChecked(s["rel"])
        if clip:
            self.form.addRow("", self.rel)
        self.bz = [self.mix("bezier", v, 3) for v in s["bezier"]]
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
        self.rows = {"loop": self.loop, "width": self.pulse, "seed": self.seed, "presets": self.presets, "bezier": box}
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
        for w in (self.rate, self.amp, self.offset, self.phase, self.fade, self.fade_out, self.ramp, self.ramp_out, self.ramp_from, self.pulse, self.seed, *self.bz):
            w.valueChanged.connect(self._changed)
        for w in (self.wave, self.loop, self.unit):
            w.currentIndexChanged.connect(self._changed)
        for w in (self.bipolar, self.rel):
            w.toggled.connect(self._changed)
        self.presets.activated.connect(self._preset)
        self.field.changed.connect(self._dragged)
        self.cfield.changed.connect(lambda *_: self.touch("curve"))
        self.cfield.changed.connect(self._changed)
        for key, w in (("wave", self.wave), ("loop", self.loop), ("unit", self.unit)):
            w.activated.connect(lambda *_, k=key: self.touch(k))
            if key in self.mixed:
                w.setCurrentIndex(-1)
        for key, w in (("bipolar", self.bipolar), ("rel", self.rel)):
            w.clicked.connect(lambda *_, k=key, w=w: (w.setTristate(False), self.touch(k)))
            if key in self.mixed:
                w.setTristate(True)
                w.setCheckState(Qt.PartiallyChecked)
        self._changed()

    def mix(self, key, value, decimals=3):
        sp = MixSpin(value, decimals, key, self)
        if key in self.mixed:
            sp.show_mixed()
        return sp

    def touch(self, key):
        """The user changed this field: it is written to every clip now."""
        if key == "bezier":
            for b in self.bz:
                b.mixed = False
                b.lineEdit().setText(b.textFromValue(b.value()))
        self.touched.add(key)

    def _preset(self, i):
        v = self.presets.itemData(i)
        if v is not None:
            self._dragged(v)

    def _dragged(self, v):
        self.touch("bezier")
        for b, x in zip(self.bz, v):
            b.blockSignals(True)
            b.setValue(x)
            b.blockSignals(False)
        self._changed()

    def spec(self):
        s = self._read()
        for k in self.mixed - self.touched:
            s[k] = self.base[k]
        return s

    def _read(self):
        return {"wave": self.wave.currentData(), "unit": self.unit.currentData(), "rate": self.rate.value(),
                "amp": self.amp.value(), "offset": self.offset.value(), "phase": self.phase.value(),
                "fade": self.fade.value(), "fade_out": self.fade_out.value(), "ramp": self.ramp.value(), "ramp_out": self.ramp_out.value(), "ramp_from": self.ramp_from.value() / 100, "loop": self.loop.currentData(), "width": self.pulse.value(),
                "bezier": [b.value() for b in self.bz], "curve": [list(k) for k in self.cfield.keys],
                "bipolar": self.bipolar.isChecked(), "rel": self.rel.isChecked(), "seed": self.seed.value()}

    def _changed(self, *_a):
        s = self.spec()
        w = s["wave"]
        self.ramp_from.setEnabled(s["ramp"] > 0 or s["ramp_out"] > 0)
        show = {"loop": w in lfo.MIRRORABLE, "width": w == "square", "seed": w in ("random", "noise"),
                "presets": w == "bezier", "bezier": w == "bezier"}
        for key, on in show.items():
            self.rows[key].setVisible(on)
            label = self.form.labelForField(self.rows[key])
            if label is not None:
                label.setVisible(on)
        self.field.setVisible(w == "bezier")
        self.cfield.setVisible(w == "curve")
        self.field.set_value(s["bezier"])
        why = lfo.check(s)
        self.preview.set_spec(s)
        self.status.setText("✗ " + why if why else "")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(why is None)
        self.layout().activate()
        self.resize(self.size().expandedTo(self.sizeHint()))


def ask_lfo_each(parent, title, specs, note="", clip=False):
    """One LFO spec per given spec (the LFOs of several clips), or None when cancelled: each keeps its own values
    except the fields the user changed in the dialog."""
    d = LfoDialog(parent, title, specs[0], note, clip, specs)
    d.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
    if d.exec() != QDialog.Accepted:
        return None
    new = d.spec()
    out = []
    for sp in specs:
        sp = lfo.make(**sp)
        for k in d.touched:
            sp[k] = copy.deepcopy(new[k])
        out.append(sp)
    return out


def ask_lfo(parent, title, s=None, note="", clip=False):
    """The LFO spec chosen, or None when cancelled."""
    d = LfoDialog(parent, title, s or lfo.make(), note, clip)
    d.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
    return d.spec() if d.exec() == QDialog.Accepted else None
