"""Inspector: the selected clip's properties, editable where they are not keyframed.

Edits are reported through signals after a short pause, so typing or spinning a value
produces one rebuild instead of one per keystroke. The form is rebuilt only when the
selection changes; otherwise values are refreshed in place without firing edits.
"""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QColorDialog, QDoubleSpinBox, QFormLayout, QLabel, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from .. import curves
from .timeline import US, timecode

DEBOUNCE_MS = 350

TEXT_SPINS = (  # key, label, min, max, step, decimals
    ("size", "字號", 0.5, 200.0, 0.1, 2),
    ("letter_spacing", "字距", -0.5, 5.0, 0.01, 2),
    ("line_spacing", "行距", -0.5, 5.0, 0.01, 2),
    ("italic_deg", "斜體角度", 0.0, 45.0, 1.0, 0),
)
TRANSFORM_SPINS = (  # key, label, min, max, step, decimals, display factor
    ("x", "位置 X", -10.0, 10.0, 0.01, 3, 1),
    ("y", "位置 Y", -10.0, 10.0, 0.01, 3, 1),
    ("scale", "縮放", 0.01, 50.0, 0.01, 3, 1),
    ("rotation", "旋轉 °", -3600.0, 3600.0, 0.5, 1, 1),
    ("opacity", "不透明度 %", 0.0, 100.0, 1.0, 0, 100),
)


class Inspector(QWidget):
    textEdited = Signal(str, dict)            # clip id, {field: value}
    transformEdited = Signal(str, str, float)  # clip id, field, value

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(280)
        lay = QVBoxLayout(self)
        title = QLabel("屬性")
        title.setObjectName("title")
        lay.addWidget(title)
        self.body = QWidget()
        lay.addWidget(self.body)
        lay.addStretch()
        self.clip_id = None
        self.widgets = {}
        self.pending = {}
        self.timer = QTimer(self, singleShot=True, interval=DEBOUNCE_MS)
        self.timer.timeout.connect(self._flush)
        self._build(None)

    # -- form -----------------------------------------------------------------------------------
    def _build(self, c):
        old = self.body
        self.body = QWidget()
        self.layout().replaceWidget(old, self.body)
        old.deleteLater()
        form = QFormLayout(self.body)
        self.widgets = {}
        if c is None:
            form.addRow(QLabel("在時間軸上選一個片段"))
            return
        for key in ("類型", "開始", "長度"):
            self.widgets[key] = QLabel()
            form.addRow(key, self.widgets[key])
        if c.get("text"):
            edit = QPlainTextEdit()
            edit.setFixedHeight(80)
            edit.textChanged.connect(lambda: self._queue("text", "content", edit.toPlainText()))
            self.widgets["content"] = edit
            form.addRow("文字", edit)
            color = QPushButton()
            color.clicked.connect(self._pick_color)
            self.widgets["color"] = color
            form.addRow("顏色", color)
            for key, label, lo, hi, step, dec in TEXT_SPINS:
                form.addRow(label, self._spin(("text", key), lo, hi, step, dec))
        if c.get("transform") is not None:
            for key, label, lo, hi, step, dec, k in TRANSFORM_SPINS:
                form.addRow(label, self._spin(("transform", key), lo, hi, step, dec, k))
        for key in ("遮罩", "音量", "關鍵幀"):
            self.widgets[key] = QLabel()
            form.addRow(key, self.widgets[key])

    def _spin(self, key, lo, hi, step, dec, factor=1):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setSingleStep(step)
        s.setDecimals(dec)
        s.setKeyboardTracking(False)
        s.valueChanged.connect(lambda v: self._queue(key[0], key[1], v / factor))
        self.widgets[key] = s
        return s

    # -- refresh --------------------------------------------------------------------------------
    def show_clip(self, c, t_us, fps):
        """Show clip c; t_us is the playhead time on the timeline."""
        if c is None or c["id"] != self.clip_id:
            self._flush()
            self.clip_id = c["id"] if c else None
            self._build(c)
        if c is None:
            return
        t = t_us - c["start_us"]
        w = self.widgets
        w["類型"].setText({"image": "圖片", "video": "影片", "audio": "音訊", "text": "文字",
                          "compound": "複合片段"}.get(c["type"], c["type"]))
        w["開始"].setText(timecode(c["start_us"], fps))
        w["長度"].setText(f"{c['duration_us'] / US:.2f} 秒")
        if c.get("text"):
            tx = c["text"]
            if w["content"].toPlainText() != tx["content"] and not w["content"].hasFocus():
                w["content"].blockSignals(True)
                w["content"].setPlainText(tx["content"])
                w["content"].blockSignals(False)
            r, g, b = (int(round(v * 255)) for v in tx.get("color", [1, 1, 1])[:3])
            w["color"].setText(f"#{r:02x}{g:02x}{b:02x}")
            w["color"].setStyleSheet(f"background: rgb({r},{g},{b}); color: {'#000' if r + g + b > 380 else '#fff'};")
            for key, *_ in TEXT_SPINS:
                self._set(("text", key), tx.get(key, 0.0), False)
        keyed = []
        if c.get("transform") is not None:
            tf = c["transform"]
            for key, _l, _lo, _hi, _st, _d, k in TRANSFORM_SPINS:
                default = 1.0 if key in ("scale", "opacity") else 0.0
                anim = curves.is_animated(tf.get(key))
                if anim:
                    keyed.append(key)
                self._set(("transform", key), curves.value(tf.get(key, default), t) * k, anim)
        w["遮罩"].setText((c["mask"]["kind"] + ("（反轉）" if c["mask"].get("invert") else ""))
                          if c.get("mask") else "—")
        w["音量"].setText(f"{curves.value(c['volume'], t):.2f}" if "volume" in c else "—")
        w["關鍵幀"].setText("、".join(keyed) if keyed else "—")

    def _set(self, key, value, locked):
        s = self.widgets.get(key)
        if s is None or (s.hasFocus() and key not in self.pending):
            return
        s.blockSignals(True)
        s.setValue(value)
        s.blockSignals(False)
        s.setEnabled(not locked)
        s.setToolTip("有關鍵幀：數值隨時間變化，目前不能直接修改" if locked else "")

    # -- edits ----------------------------------------------------------------------------------
    def _queue(self, group, key, value):
        self.pending[(group, key)] = value
        self.timer.start()

    def _pick_color(self):
        cur = QColor(self.widgets["color"].text())
        col = QColorDialog.getColor(cur, self, "文字顏色")
        if col.isValid():
            self._queue("text", "color", [col.redF(), col.greenF(), col.blueF()])
            self._flush()

    def _flush(self):
        self.timer.stop()
        if not self.pending or self.clip_id is None:
            self.pending.clear()
            return
        pending, self.pending = self.pending, {}
        text = {k: v for (g, k), v in pending.items() if g == "text"}
        if text:
            self.textEdited.emit(self.clip_id, text)
        for (g, k), v in pending.items():
            if g == "transform":
                self.transformEdited.emit(self.clip_id, k, float(v))
