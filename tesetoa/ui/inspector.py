"""Inspector: the selected clip's properties, with keyframes and masks (Jianying-style).

Every animatable value has a ◆ button: filled when the playhead sits on one of its
keyframes. Clicking it adds or removes a keyframe there. Changing a value that already
has keyframes edits the keyframe at the playhead, or adds one, as Jianying does.
Edits are reported after a short pause so typing or spinning produces one rebuild.

One class serves two tabs: part="main" (type, text, picture, sound) and part="mask" (the
mask: on / off, shape, invert and its values), each with its own keyframe controls.

With several clips selected the form shows what they have in common: a value they share
is shown, one that differs shows "--", and typing a value sets it on all of them.
"""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from .. import curves, edit, project
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
    """Number input that ignores the mouse wheel, so scrolling the panel never edits.
    It can show "--" (values that differ across a selection); `edited` fires for the user's
    changes, including typing the very number that was hidden behind "--"."""
    edited = Signal(float)

    def __init__(self, *a):
        super().__init__(*a)
        self.mixed = False
        self._typed = False              # the user typed over "--" and has not finished yet
        self.valueChanged.connect(self._changed)
        self.lineEdit().textEdited.connect(self._typing)
        self.editingFinished.connect(self._finished)

    def wheelEvent(self, e):
        e.ignore()

    def show_value(self, v):
        self.blockSignals(True)
        self.mixed = self._typed = False
        self.setValue(v)
        self.blockSignals(False)
        self.lineEdit().setText(self.textFromValue(self.value()))

    def show_mixed(self):
        self.mixed, self._typed = True, False
        self.lineEdit().setText("--")

    def textFromValue(self, v):
        return "--" if self.mixed else super().textFromValue(v)

    def _typing(self, _text):
        if self.mixed:
            self.mixed, self._typed = False, True

    def _changed(self, v):
        self.mixed = self._typed = False
        self.edited.emit(v)

    def _finished(self):
        # typing the very number hidden behind "--" changes no value, so valueChanged is
        # silent: report it here
        if self._typed:
            self._typed = False
            self.edited.emit(self.value())


class ComboBox(QComboBox):
    def wheelEvent(self, e):
        e.ignore()


def section(title):
    lbl = QLabel(title)
    lbl.setObjectName("title")
    return lbl


class Inspector(QWidget):
    # every edit names the clips it applies to (the whole selection)
    textEdited = Signal(list, dict)                 # clip ids, {field: value}
    paramEdited = Signal(list, str, str, object)    # clip ids, group, key, value (number or colour)
    keyToggled = Signal(list, str, str)             # clip ids, group, key
    easingChosen = Signal(list, str, list)          # clip ids, easing name, parameter groups
    maskKindChosen = Signal(list, object)           # clip ids, kind or None
    maskInvertChosen = Signal(list, bool)           # clip ids, invert
    maskEnabledChosen = Signal(list, bool)          # clip ids, on
    keyJump = Signal(int)                           # -1 previous keyframe, +1 next

    def __init__(self, parent=None, part="main"):
        super().__init__(parent)
        self.part = part
        self.groups = ["mask"] if part == "mask" else ["transform", "text", "clip"]
        self.setMinimumWidth(300)
        lay = QVBoxLayout(self)
        lay.addWidget(section("遮罩" if part == "mask" else "屬性"))
        self.body = QWidget()
        lay.addWidget(self.body)
        lay.addStretch()
        self.clip_ids = []
        self.shape = None                 # what the form was built for
        self.widgets = {}
        self.pending = {}
        self.timer = QTimer(self, singleShot=True, interval=DEBOUNCE_MS)
        self.timer.timeout.connect(self._flush)
        self._build(None)

    # -- form -----------------------------------------------------------------------------------
    @property
    def clip_id(self):
        return self.clip_ids[0] if self.clip_ids else None

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
        if self.part == "mask":
            self._build_mask(form, c)
            return
        for key in ("類型", "開始", "長度"):
            self.widgets[key] = QLabel()
            form.addRow(key, self.widgets[key])
        if c.get("text"):
            form.addRow(section("文字"))
            edit_ = QPlainTextEdit()
            edit_.setFixedHeight(80)
            edit_.setPlaceholderText("--")
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
        if "volume" in c:
            form.addRow(section("聲音"))
            form.addRow(PARAMS["clip"][0][1], self._param_row("clip", *PARAMS["clip"][0]))
        self._key_section(form)

    def _build_mask(self, form, c):
        if c["type"] not in ("image", "video", "compound"):
            note = QLabel("只有圖片、影片和複合片段可以加遮罩")
            note.setStyleSheet("color: #9a9aa0;")
            form.addRow(note)
            return
        on = QCheckBox("啟用遮罩")
        on.setToolTip("關掉時保留遮罩的設定，只是不裁切")
        on.toggled.connect(lambda v: self._emit_now(self.maskEnabledChosen, v))
        self.widgets["mask_on"] = on
        form.addRow(on)
        row = QHBoxLayout()
        kind = ComboBox()
        kind.setPlaceholderText("選擇形狀…")
        for name, k in MASK_NAMES:
            if k is not None:
                kind.addItem(name, k)
        kind.activated.connect(lambda i: self._emit_now(self.maskKindChosen, kind.itemData(i)))
        self.widgets["mask_kind"] = kind
        row.addWidget(kind, 1)
        if c.get("mask"):
            drop = QPushButton("移除")
            drop.setToolTip("刪除遮罩和它的設定")
            drop.clicked.connect(lambda: self._emit_now(self.maskKindChosen, None))
            row.addWidget(drop)
        form.addRow("形狀", row)
        if not c.get("mask"):
            hint = QLabel("選一個形狀，或勾選「啟用遮罩」加上矩形遮罩")
            hint.setStyleSheet("color: #9a9aa0;")
            hint.setWordWrap(True)
            form.addRow(hint)
            return
        inv = QCheckBox("反轉")
        inv.setTristate(False)
        inv.toggled.connect(lambda v: self._emit_now(self.maskInvertChosen, v))
        self.widgets["mask_invert"] = inv
        form.addRow("", inv)
        for r in PARAMS["mask"]:
            if c["mask"]["kind"] == "line" and r[0] in ("w", "h"):
                continue
            form.addRow(r[1], self._param_row("mask", *r))
        hint = QLabel("在預覽上拖曳：中間移動、方塊調大小、圓點旋轉、箭頭羽化")
        hint.setStyleSheet("color: #9a9aa0;")
        hint.setWordWrap(True)
        form.addRow(hint)
        self._key_section(form)

    def _key_section(self, form):
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
                               self._emit_now(self.easingChosen, ease.itemData(i), list(self.groups)))
        ease.setToolTip("從播放頭上的關鍵幀到下一個關鍵幀之間的速度曲線")
        self.widgets["easing"] = ease
        form.addRow("曲線", ease)

    def _spin(self, key, lo, hi, step, dec, factor=1):
        s = SpinBox()
        s.setRange(lo, hi)
        s.setSingleStep(step)
        s.setDecimals(dec)
        s.setKeyboardTracking(False)
        s.edited.connect(lambda v: self._queue(key[0], key[1], v / factor))
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
        self.show_clips([c] if c else [], t_us, fps)

    def show_clips(self, clips, t_us, fps):
        """Show the selected clips (the first is the primary one); t_us is the playhead time."""
        c = common(clips)
        shape = None if c is None else (tuple(k["id"] for k in clips), c["type"], bool(c.get("text")),
                                         (c.get("mask") or {}).get("kind"), "volume" in c)
        if shape != self.shape:
            self._flush()
            self.clip_ids = [k["id"] for k in clips]
            self.shape = shape
            self._build(c)
        if c is None:
            return
        w = self.widgets
        ts = [t_us - k["start_us"] for k in clips]
        names = {"image": "圖片", "video": "影片", "audio": "音訊", "text": "文字", "compound": "複合片段"}
        kinds = sorted({names.get(k["type"], k["type"]) for k in clips})
        same = lambda vals: len(set(vals)) == 1
        if "類型" in w:
            w["類型"].setText(kinds[0] if len(clips) == 1 else f"{len(clips)} 個片段（{'、'.join(kinds)}）")
            starts = [timecode(k["start_us"], fps) for k in clips]
            w["開始"].setText(starts[0] if same(starts) else "--")
            lens = [f"{k['duration_us'] / US:.2f} 秒" for k in clips]
            w["長度"].setText(lens[0] if same(lens) else "--")
        if "content" in w:
            contents = [k["text"]["content"] for k in clips]
            text = contents[0] if same(contents) else ""
            if w["content"].toPlainText() != text and not w["content"].hasFocus():
                w["content"].blockSignals(True)
                w["content"].setPlainText(text)
                w["content"].blockSignals(False)
            cols = []
            for k, t in zip(clips, ts):
                col = curves.value(k["text"].get("color", [1, 1, 1]), t)
                cols.append(tuple(int(round(min(1, max(0, v)) * 255)) for v in col[:3]))
            if same(cols):
                r, g, b = cols[0]
                w["color"].setText(f"#{r:02x}{g:02x}{b:02x}")
                w["color"].setStyleSheet(f"background: rgb({r},{g},{b}); color: {'#000' if r + g + b > 380 else '#fff'};")
            else:
                w["color"].setText("--")
                w["color"].setStyleSheet("")
            self._key_state(w[("key", "text", "color")], [k["text"].get("color") for k in clips], clips, ts)
        easings = set()
        for group, rows in PARAMS.items():
            if group not in self.groups or (c if group == "clip" else c.get(group)) is None:
                continue
            for key, _l, _lo, _hi, _st, dec, factor, default in rows:
                if (group, key) not in w:
                    continue
                ps = [(k if group == "clip" else k[group]).get(key, default) for k in clips]
                vals = [round(curves.value(p, t) * factor, dec) for p, t in zip(ps, ts)]
                self._set((group, key), vals[0] if same(vals) else None)
                for p, t in zip(ps, ts):
                    if edit.key_at(p, t) is not None:
                        easings.add(edit.easing_at(p, t))
                self._key_state(w[("key", group, key)], ps, clips, ts)
        if "mask_on" in w:
            on = {bool(project.active_mask(k)) for k in clips}
            w["mask_on"].blockSignals(True)
            w["mask_on"].setTristate(len(on) > 1)
            w["mask_on"].setCheckState(Qt.PartiallyChecked if len(on) > 1 else
                                       (Qt.Checked if on.pop() else Qt.Unchecked))
            w["mask_on"].blockSignals(False)
        if "mask_kind" in w:
            kinds = {(k.get("mask") or {}).get("kind") for k in clips}
            self._set_combo(w["mask_kind"], kinds.pop() if len(kinds) == 1 else "--")
        if "mask_invert" in w:
            inv = {bool(k["mask"].get("invert")) for k in clips}
            w["mask_invert"].blockSignals(True)
            w["mask_invert"].setCheckState(Qt.PartiallyChecked if len(inv) > 1 else
                                           (Qt.Checked if inv.pop() else Qt.Unchecked))
            w["mask_invert"].blockSignals(False)
        easings.discard(None)
        if "easing" not in w:
            return
        ease = w["easing"]
        ease.setEnabled(bool(easings))
        self._set_combo(ease, easings.pop() if len(easings) == 1 else (None if not easings else "custom"))

    @staticmethod
    def _key_state(btn, ps, clips, ts):
        """◆ when every clip has a keyframe at the playhead, ◈ when some do."""
        on = [edit.key_at(p, t) is not None for p, t in zip(ps, ts)]
        btn.setText(KEY_ON if all(on) else ("◈" if any(on) else KEY_OFF))
        btn.setStyleSheet("color: #ffb020;" if any(on) else
                          ("color: #c9933a;" if any(curves.is_animated(p) for p in ps) else ""))
        btn.setEnabled(any(0 <= t <= k["duration_us"] for k, t in zip(clips, ts)))

    @staticmethod
    def _set_combo(combo, data):
        combo.blockSignals(True)
        i = combo.findData(data)
        combo.setCurrentIndex(-1 if data == "--" or i < 0 else i)   # -1 shows the placeholder
        combo.blockSignals(False)

    def _set(self, key, value):
        s = self.widgets.get(key)
        if s is None or (s.hasFocus() and key in self.pending):
            return
        if s.hasFocus() and s.mixed and value is None:
            return                                       # the user may be typing over "--"
        s.show_mixed() if value is None else s.show_value(value)

    # -- edits ----------------------------------------------------------------------------------
    def _queue(self, group, key, value):
        self.pending[(group, key)] = value
        self.timer.start()

    def _emit_now(self, signal, *args):
        self._flush()
        if self.clip_ids:
            signal.emit(list(self.clip_ids), *args)

    def _pick_color(self):
        cur = QColor(self.widgets["color"].text()) if self.widgets["color"].text() != "--" else QColor("white")
        col = QColorDialog.getColor(cur, self, "文字顏色")
        if col.isValid():
            self._queue("text*", "color", [col.redF(), col.greenF(), col.blueF()])
            self._flush()

    def _flush(self):
        self.timer.stop()
        if not self.pending or not self.clip_ids:
            self.pending.clear()
            return
        pending, self.pending = self.pending, {}
        ids = list(self.clip_ids)
        if ("text", "content") in pending:                 # the words themselves
            self.textEdited.emit(ids, {"content": pending.pop(("text", "content"))})
        for (g, k), v in pending.items():                    # everything else can animate
            self.paramEdited.emit(ids, g.rstrip("*"), k, v)


def common(clips):
    """A clip-like dict holding only what every clip has (for the form layout), or None."""
    if not clips:
        return None
    if len(clips) == 1:
        return clips[0]
    first = clips[0]
    out = {"id": first["id"], "type": first["type"] if len({k["type"] for k in clips}) == 1 else "mixed"}
    if all(k.get("text") for k in clips):
        out["text"] = first["text"]
    if all(k.get("transform") is not None for k in clips):
        out["transform"] = first["transform"]
    if all(k["type"] in ("image", "video", "compound") for k in clips):
        out["type"] = out["type"] if out["type"] != "mixed" else "video"     # can take masks
        kinds = {(k.get("mask") or {}).get("kind") for k in clips}
        if len(kinds) == 1 and None not in kinds:
            out["mask"] = first["mask"]
    if all("volume" in k for k in clips):
        out["volume"] = first["volume"]
    return out
