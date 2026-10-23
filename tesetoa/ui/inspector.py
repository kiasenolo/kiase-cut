"""Inspector: the selected clip's properties, with keyframes and masks (Jianying-style).

Every animatable value has a ◆ button: filled when the playhead sits on one of its
keyframes. Clicking it adds or removes a keyframe there. Changing a value that already
has keyframes edits the keyframe at the playhead, or adds one, as Jianying does.
Edits are reported after a short pause so typing or spinning produces one rebuild.
"""
from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from .. import curves, edit
from .timeline import US, timecode

DEBOUNCE_MS = 350

# group, key, label, min, max, step, decimals, display factor, default
PARAMS = {
    "text": (("size", "字號", 0.5, 200.0, 0.1, 2, 1, 5.0),
             ("letter_spacing", "字距", -0.5, 5.0, 0.01, 2, 1, 0.0),
             ("line_spacing", "行距", -0.5, 5.0, 0.01, 2, 1, 0.0),
             ("italic_deg", "斜體角度", 0.0, 45.0, 1.0, 0, 1, 0.0)),
    "transform": (("x", "位置 X", -10.0, 10.0, 0.01, 3, 1, 0.0),
                  ("y", "位置 Y", -10.0, 10.0, 0.01, 3, 1, 0.0),
                  ("scale", "縮放", 0.01, 50.0, 0.01, 3, 1, 1.0),
                  ("rotation", "旋轉 °", -3600.0, 3600.0, 0.5, 1, 1, 0.0),
                  ("opacity", "不透明度 %", 0.0, 100.0, 1.0, 0, 100, 1.0)),
    "mask": (("cx", "中心 X", -5.0, 5.0, 0.01, 3, 1, 0.0),
             ("cy", "中心 Y", -5.0, 5.0, 0.01, 3, 1, 0.0),
             ("w", "寬", 0.0, 10.0, 0.01, 3, 1, 1.0),
             ("h", "高", 0.0, 10.0, 0.01, 3, 1, 1.0),
             ("rotation", "旋轉 °", -3600.0, 3600.0, 0.5, 1, 1, 0.0),
             ("feather", "羽化", 0.0, 1.0, 0.01, 2, 1, 0.0)),
    "clip": (("volume", "音量 %", 0.0, 1000.0, 1.0, 0, 100, 1.0),),
}
MASK_NAMES = (("無", None), ("線性", "line"), ("鏡面", "mirror"), ("圓形", "circle"), ("矩形", "rectangle"))
EASING_NAMES = (("線性", "linear"), ("緩入", "ease_in"), ("緩出", "ease_out"), ("緩入緩出", "ease_in_out"))
KEY_ON, KEY_OFF = "◆", "◇"


class SpinBox(QDoubleSpinBox):
    """Number input that ignores the mouse wheel, so scrolling the panel never edits."""

    def wheelEvent(self, e):
        e.ignore()


class ComboBox(QComboBox):
    def wheelEvent(self, e):
        e.ignore()


def section(title):
    lbl = QLabel(title)
    lbl.setObjectName("title")
    return lbl


class Inspector(QWidget):
    textEdited = Signal(str, dict)                  # clip id, {field: value}
    paramEdited = Signal(str, str, str, object)     # clip id, group, key, value (number or colour)
    keyToggled = Signal(str, str, str)              # clip id, group, key
    easingChosen = Signal(str, str)                 # clip id, easing name
    maskKindChosen = Signal(str, object)            # clip id, kind or None
    maskInvertChosen = Signal(str, bool)            # clip id, invert
    keyJump = Signal(int)                           # -1 previous keyframe, +1 next

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        lay = QVBoxLayout(self)
        lay.addWidget(section("屬性"))
        self.body = QWidget()
        lay.addWidget(self.body)
        lay.addStretch()
        self.clip_id = None
        self.shape = None                 # what the form was built for
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
        old.hide()                       # deleteLater waits for the event loop; never show both
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
            form.addRow(section("文字"))
            edit_ = QPlainTextEdit()
            edit_.setFixedHeight(80)
            edit_.textChanged.connect(lambda: self._queue("text", "content", edit_.toPlainText()))
            self.widgets["content"] = edit_
            form.addRow("內容", edit_)
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            color = QPushButton()
            color.clicked.connect(self._pick_color)
            self.widgets["color"] = color
            lay.addWidget(color, 1)
            lay.addWidget(self._key_button("text", "color"))
            form.addRow("顏色", row)
            for r in PARAMS["text"]:
                form.addRow(r[1], self._param_row("text", *r))
        if c.get("transform") is not None:
            form.addRow(section("畫面"))
            for row in PARAMS["transform"]:
                form.addRow(row[1], self._param_row("transform", *row))
        if c["type"] in ("image", "video", "compound"):
            form.addRow(section("遮罩"))
            kind = ComboBox()
            for name, k in MASK_NAMES:
                kind.addItem(name, k)
            kind.currentIndexChanged.connect(lambda i: self._emit_now(self.maskKindChosen, kind.itemData(i)))
            self.widgets["mask_kind"] = kind
            form.addRow("類型", kind)
            if c.get("mask"):
                inv = QCheckBox("反轉")
                inv.toggled.connect(lambda on: self._emit_now(self.maskInvertChosen, on))
                self.widgets["mask_invert"] = inv
                form.addRow("", inv)
                for row in PARAMS["mask"]:
                    if c["mask"]["kind"] == "line" and row[0] in ("w", "h"):
                        continue
                    form.addRow(row[1], self._param_row("mask", *row))
        if "volume" in c:
            form.addRow(section("聲音"))
            form.addRow(PARAMS["clip"][0][1], self._param_row("clip", *PARAMS["clip"][0]))
        form.addRow(section("關鍵幀"))
        nav = QHBoxLayout()
        for label, d in (("◀ 上一個", -1), ("下一個 ▶", 1)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, d=d: self.keyJump.emit(d))
            nav.addWidget(b)
        form.addRow(nav)
        ease = ComboBox()
        ease.addItem("—", None)
        for name, k in EASING_NAMES:
            ease.addItem(name, k)
        ease.addItem("自訂", "custom")
        ease.activated.connect(lambda i: ease.itemData(i) not in (None, "custom") and
                               self._emit_now(self.easingChosen, ease.itemData(i)))
        ease.setToolTip("從播放頭上的關鍵幀到下一個關鍵幀之間的速度曲線")
        self.widgets["easing"] = ease
        form.addRow("曲線", ease)

    def _spin(self, key, lo, hi, step, dec, factor=1):
        s = SpinBox()
        s.setRange(lo, hi)
        s.setSingleStep(step)
        s.setDecimals(dec)
        s.setKeyboardTracking(False)
        s.valueChanged.connect(lambda v: self._queue(key[0], key[1], v / factor))
        self.widgets[key] = s
        return s

    def _param_row(self, group, key, _label, lo, hi, step, dec, factor, _default):
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._spin((group, key), lo, hi, step, dec, factor), 1)
        lay.addWidget(self._key_button(group, key))
        return row

    def _key_button(self, group, key):
        b = QPushButton(KEY_OFF)
        b.setFixedWidth(30)
        b.setToolTip("在播放頭新增／刪除關鍵幀")
        b.clicked.connect(lambda: self._emit_now(self.keyToggled, group, key))
        self.widgets[("key", group, key)] = b
        return b

    # -- refresh --------------------------------------------------------------------------------
    def show_clip(self, c, t_us, fps):
        """Show clip c; t_us is the playhead time on the timeline."""
        shape = None if c is None else (c["id"], c["type"], bool(c.get("text")),
                                         (c.get("mask") or {}).get("kind"), "volume" in c)
        if shape != self.shape:
            self._flush()
            self.clip_id = c["id"] if c else None
            self.shape = shape
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
            col = curves.value(tx.get("color", [1, 1, 1]), t)
            r, g, b = (int(round(min(1, max(0, v)) * 255)) for v in col[:3])
            w["color"].setText(f"#{r:02x}{g:02x}{b:02x}")
            w["color"].setStyleSheet(f"background: rgb({r},{g},{b}); color: {'#000' if r + g + b > 380 else '#fff'};")
            on = edit.key_at(tx.get("color"), t) is not None
            kb = w[("key", "text", "color")]
            kb.setText(KEY_ON if on else KEY_OFF)
            kb.setStyleSheet("color: #ffb020;" if on else ("color: #8fd9d3;" if curves.is_animated(tx.get("color")) else ""))
            kb.setEnabled(0 <= t <= c["duration_us"])
        inside = 0 <= t <= c["duration_us"]
        easings = set()
        for group, rows in PARAMS.items():
            holder = c if group == "clip" else c.get(group)
            if holder is None:
                continue
            for key, _l, _lo, _hi, _st, _d, factor, default in rows:
                if (group, key) not in w:
                    continue
                p = holder.get(key, default)
                self._set((group, key), curves.value(p, t) * factor)
                on = edit.key_at(p, t) is not None
                btn = w[("key", group, key)]
                btn.setText(KEY_ON if on else KEY_OFF)
                btn.setStyleSheet("color: #ffb020;" if on else
                                  ("color: #8fd9d3;" if curves.is_animated(p) else ""))
                btn.setEnabled(inside)
                if on:
                    easings.add(edit.easing_at(p, t))
        if "mask_kind" in w:
            kind = (c.get("mask") or {}).get("kind")
            self._set_combo(w["mask_kind"], kind)
        if "mask_invert" in w:
            w["mask_invert"].blockSignals(True)
            w["mask_invert"].setChecked(bool(c["mask"].get("invert")))
            w["mask_invert"].blockSignals(False)
        easings.discard(None)
        ease = w["easing"]
        ease.setEnabled(bool(easings))
        self._set_combo(ease, easings.pop() if len(easings) == 1 else (None if not easings else "custom"))

    @staticmethod
    def _set_combo(combo, data):
        combo.blockSignals(True)
        combo.setCurrentIndex(max(0, combo.findData(data)))
        combo.blockSignals(False)

    def _set(self, key, value):
        s = self.widgets.get(key)
        if s is None or (s.hasFocus() and key in self.pending):
            return
        s.blockSignals(True)
        s.setValue(value)
        s.blockSignals(False)

    # -- edits ----------------------------------------------------------------------------------
    def _queue(self, group, key, value):
        self.pending[(group, key)] = value
        self.timer.start()

    def _emit_now(self, signal, *args):
        self._flush()
        if self.clip_id is not None:
            signal.emit(self.clip_id, *args)

    def _pick_color(self):
        cur = QColor(self.widgets["color"].text())
        col = QColorDialog.getColor(cur, self, "文字顏色")
        if col.isValid():
            self._queue("text*", "color", [col.redF(), col.greenF(), col.blueF()])
            self._flush()

    def _flush(self):
        self.timer.stop()
        if not self.pending or self.clip_id is None:
            self.pending.clear()
            return
        pending, self.pending = self.pending, {}
        if ("text", "content") in pending:                 # the words themselves
            self.textEdited.emit(self.clip_id, {"content": pending.pop(("text", "content"))})
        for (g, k), v in pending.items():                    # everything else can animate
            self.paramEdited.emit(self.clip_id, g.rstrip("*"), k, v)
