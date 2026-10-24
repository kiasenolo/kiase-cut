"""Inspector: the selected clip's properties, with keyframes and masks (Jianying-style).

Every animatable value has a ◆ button: filled when the playhead sits on one of its
keyframes. Clicking it adds or removes a keyframe there. Changing a value that already
has keyframes edits the keyframe at the playhead, or adds one, as Jianying does. Choices
(font, blend mode, mask shape, invert) have ◆ too: their keyframes hold until the next one.
Edits are reported after a short pause so typing or spinning produces one rebuild.

Scale has an X and a Y value with a link button between them: linked (the default), changing
one changes the other in proportion and keyframes go on both. Built-in assets (assets.py)
add a 素材參數 section: size in canvas pixels, colours and the shape's own settings, each
with its ◆ like any other value.

One class serves two tabs: part="main" (type, text, picture, sound) and part="mask" (the
mask: on / off, shape, invert and its values), each with its own keyframe controls.

With several clips selected the form shows what they have in common: a value they share
is shown, one that differs shows "--", and typing a value sets it on all of them.
"""
from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor
import os

from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from .. import assets, curves, edit, project
from . import icons
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
                  ("scale", "縮放 X", 0.01, 50.0, 0.01, 3, 1, 1.0),
                  ("scale_y", "縮放 Y", 0.01, 50.0, 0.01, 3, 1, 1.0),
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
BLEND_NAMES = (("正常", "normal"), ("正片疊底", "multiply"), ("濾色", "screen"), ("疊加", "overlay"),
               ("變暗", "darken"), ("變亮", "lighten"), ("顏色減淡", "color_dodge"), ("顏色加深", "color_burn"),
               ("強光", "hard_light"), ("柔光", "soft_light"), ("差值", "difference"), ("排除", "exclusion"),
               ("相加", "add"))
KEY_ON, KEY_OFF = "◆", "◇"


class SpinBox(QDoubleSpinBox):
    """Number input that ignores the mouse wheel, so scrolling the panel never edits.

    Press and drag up / down to change the value (a step per 2 px; Shift for tenths, Ctrl
    for tens of steps); a click without dragging starts typing. It can show "--" (values
    that differ across a selection); `edited` fires for the user's changes, including
    typing the very number that was hidden behind "--"."""
    edited = Signal(float)
    SCRUB_PX = 3

    def __init__(self, *a):
        super().__init__(*a)
        self.mixed = False
        self._typed = False              # the user typed over "--" and has not finished yet
        self._scrub = None               # press position / value while dragging the number
        self.editing = False             # typing (after a click), until Enter / leaving
        self.valueChanged.connect(self._changed)
        self.lineEdit().textEdited.connect(self._typing)
        self.editingFinished.connect(self._finished)
        self.lineEdit().installEventFilter(self)
        self.lineEdit().setCursor(Qt.SizeVerCursor)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setButtonSymbols(QDoubleSpinBox.NoButtons)    # dragging replaces the arrows

    def eventFilter(self, obj, e):
        t = e.type()
        if obj is not self.lineEdit() or not self.isEnabled():
            return False
        if t == QEvent.FocusOut:
            self.editing = False
            return False
        if self.editing:                                 # typing: the field behaves normally
            return False
        if t == QEvent.MouseButtonPress and e.button() == Qt.LeftButton:
            self._scrub = {"y": e.globalPosition().y(), "v": self.value(), "moved": False}
            return True
        if t == QEvent.MouseMove and self._scrub is not None:
            dy = self._scrub["y"] - e.globalPosition().y()
            if not self._scrub["moved"] and abs(dy) < self.SCRUB_PX:
                return True
            self._scrub["moved"] = True
            k = 0.1 if e.modifiers() & Qt.ShiftModifier else 10 if e.modifiers() & Qt.ControlModifier else 1
            v = self._scrub["v"] + round(dy / 2) * self.singleStep() * k
            v = min(max(v, self.minimum()), self.maximum())
            if abs(v - self.value()) > 1e-12 or self.mixed:
                self.mixed = False
                self.setValue(v)
            return True
        if t == QEvent.MouseButtonRelease and self._scrub is not None:
            moved, self._scrub = self._scrub["moved"], None
            if not moved:                                # a click: edit the number
                self.editing = True
                self.lineEdit().setFocus(Qt.MouseFocusReason)
                QTimer.singleShot(0, self.lineEdit().selectAll)    # after Qt's own focus handling
            else:
                self.lineEdit().clearFocus()             # (Qt focused it on the press)
            return True
        return False

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
        self.editing = False
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
    liveEdited = Signal(list, str, str, object)     # clip ids, group, key, value: before the edit is made

    def __init__(self, parent=None, part="main"):
        super().__init__(parent)
        self.part = part
        self.groups = ["mask"] if part == "mask" else ["transform", "text", "clip", "asset"]
        self.setMinimumWidth(300)
        lay = QVBoxLayout(self)
        lay.addWidget(section("遮罩" if part == "mask" else "屬性"))
        self.body = QWidget()
        lay.addWidget(self.body)
        lay.addStretch()
        self._last_font = None
        self.fonts = []                   # [{path, name}] installed fonts (fonts.py), for the picker
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
            font = ComboBox()
            font.setPlaceholderText("--")
            font.setMaxVisibleItems(20)
            font.activated.connect(self._font_chosen)
            self.widgets["font"] = font
            self._fill_fonts()
            form.addRow("字體", self._with_key(font, "text", "font_path"))
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
            if c["type"] == "filter":                     # a filter has no place of its own: only how strongly it works
                form.addRow(section("濾鏡"))
                rows = [("opacity", "強度 %") + r[2:] for r in PARAMS["transform"] if r[0] == "opacity"]
                self._rows(form, "transform", rows, ())
            else:
                if c.get("asset"):
                    self._build_asset(form, c["asset"]["family"])
                form.addRow(section("畫面"))
                self._rows(form, "transform", PARAMS["transform"], (("x", "y", "位置"), ("scale", "scale_y", "縮放")))
                blend = ComboBox()
                blend.setPlaceholderText("--")
                for name, k in BLEND_NAMES:
                    blend.addItem(name, k)
                blend.setToolTip("這個片段和下面的畫面怎麼混合")
                blend.activated.connect(lambda i: self._emit_now(self.paramEdited, "clip", "blend", blend.itemData(i)))
                self.widgets["blend"] = blend
                form.addRow("混合模式", self._with_key(blend, "clip", "blend"))
        if "volume" in c:
            form.addRow(section("聲音"))
            form.addRow(PARAMS["clip"][0][1], self._param_row("clip", *PARAMS["clip"][0]))
        self._key_section(form)

    BROWSE = "__browse__"

    def set_fonts(self, fonts):
        """The installed fonts arrived (or changed)."""
        self.fonts = list(fonts)
        self._fill_fonts()
        self.shape = None                 # rebuild shows the current clip's font in the list

    def _fill_fonts(self):
        box = self.widgets.get("font")
        if box is None:
            return
        box.blockSignals(True)
        box.clear()
        for f in self.fonts:
            box.addItem(f["name"], f["path"])
        box.addItem("瀏覽字型檔…", self.BROWSE)
        box.setCurrentIndex(-1)
        box.blockSignals(False)

    def _font_chosen(self, i):
        box = self.widgets["font"]
        path = box.itemData(i)
        if path == self.BROWSE:
            path, _ = QFileDialog.getOpenFileName(self, "選擇字型檔", "", "字型 (*.ttf *.otf *.ttc *.otc)")
            if not path:
                self._show_font(self._last_font)
                return
            path = path.replace("\\", "/")
        self._emit_now(self.paramEdited, "text", "font_path", path)      # keyframed fonts get a key here

    def _show_font(self, path):
        """Show the font of the clip(s): `path`, "--" when they differ."""
        box = self.widgets.get("font")
        if box is None:
            return
        self._last_font = path
        box.blockSignals(True)
        i = box.findData(path) if path != "--" else -1
        if i < 0 and path not in (None, "--"):          # a font that is not in the list: show its file name
            box.insertItem(0, os.path.splitext(os.path.basename(path))[0], path)
            i = 0
        box.setCurrentIndex(i)
        box.blockSignals(False)

    def _build_mask(self, form, c):
        if c["type"] not in ("image", "video", "compound", "filter"):
            note = QLabel("只有圖片、影片、複合片段和濾鏡片段可以加遮罩")
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
            row.addWidget(self._key_button("mask", "kind"))
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
        form.addRow("", self._with_key(inv, "mask", "invert"))
        rows = [r for r in PARAMS["mask"] if not (kind_tag(c["mask"]) == "line" and r[0] in ("w", "h"))]
        self._rows(form, "mask", rows, (("cx", "cy", "中心"), ("w", "h", "大小")))
        hint = QLabel("在預覽上拖曳：中間移動、方塊調大小、圓點旋轉、箭頭羽化")
        hint.setStyleSheet("color: #9a9aa0;")
        hint.setWordWrap(True)
        form.addRow(hint)
        self._key_section(form)

    def _key_section(self, form):
        form.addRow(section("關鍵幀"))                  # (previous / next: in the curve editor)
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

    def _rows(self, form, group, rows, pairs):
        """Form rows for PARAMS rows; each (a, b, label) of pairs shares one row (X | Y)."""
        by_key = {r[0]: r for r in rows}
        paired = {a: (b, lab) for a, b, lab in pairs if a in by_key and b in by_key}
        skip = {b for b, _ in paired.values()}
        for r in rows:
            if r[0] in skip:
                continue
            if r[0] in paired:
                b, lab = paired[r[0]]
                row = QWidget()
                lay = QHBoxLayout(row)
                lay.setContentsMargins(0, 0, 0, 0)
                lay.setSpacing(3)
                for rr in (r, by_key[b]):
                    if rr is not r and (group, r[0]) == ("transform", "scale"):
                        lay.addWidget(self._link_button())
                    tag = QLabel(rr[1].split()[-1])                  # "位置 X" -> "X"
                    tag.setStyleSheet("color: #8e8e94;")
                    lay.addWidget(tag)
                    lay.addWidget(self._spin((group, rr[0]), *rr[2:7]), 1)
                    lay.addWidget(self._key_button(group, rr[0]))
                form.addRow(lab, row)
            else:
                form.addRow(r[1], self._param_row(group, *r))

    def _param_row(self, group, key, _label, lo, hi, step, dec, factor, _default):
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._spin((group, key), lo, hi, step, dec, factor), 1)
        lay.addWidget(self._key_button(group, key))
        return row

    def _with_key(self, widget, group, key):
        """A row of widget and its ◆ button."""
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(widget, 1)
        lay.addWidget(self._key_button(group, key))
        return row

    def _link_button(self):
        b = QPushButton()
        b.setIcon(icons.icon("link", 16))
        b.setCheckable(True)
        b.setFixedWidth(26)
        b.setToolTip("X / Y 縮放連動：開＝一起調整（保持比例），關＝分開調整")
        b.clicked.connect(lambda on: self._emit_now(self.paramEdited, "transform", "scale_link", on))
        self.widgets["scale_link"] = b
        return b

    def _build_asset(self, form, family):
        """素材參數: size, colours and the family's own fields (assets.FIELDS), each with ◆."""
        form.addRow(section("素材參數"))
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        for f in ("w", "h"):
            info = assets.FIELD_INFO[f]
            t = QLabel(info[0])
            t.setStyleSheet("color: #8e8e94;")
            lay.addWidget(t)
            lay.addWidget(self._spin(("asset", f), *info[2:6]), 1)
            lay.addWidget(self._key_button("asset", f))
        form.addRow("大小 px", row)
        for f in ("color",) + assets.FIELDS[family]:
            info = assets.FIELD_INFO[f]
            if info[1] == "color":
                b = QPushButton()
                b.clicked.connect(lambda _=False, f=f: self._pick_asset_color(f))
                self.widgets[("asset", f)] = b
                form.addRow(info[0], self._with_key(b, "asset", f))
            elif info[1] == "choice":
                box = ComboBox()
                box.setPlaceholderText("--")
                for i, (name, _v) in enumerate(info[2]):
                    box.addItem(name, i)
                box.activated.connect(lambda i, f=f: self._emit_now(self.paramEdited, "asset", f,
                                                                    assets.FIELD_INFO[f][2][i][1]))
                self.widgets[("asset", f)] = box
                form.addRow(info[0], self._with_key(box, "asset", f))
            else:
                form.addRow(info[0], self._param_row("asset", f, info[0], *info[2:6], 1, None))

    def _show_asset(self, clips, ts, easings):
        """The asset fields at the playhead (each clip at its own time), their ◆ states;
        adds the easings of keys at the playhead to `easings`."""
        for (_g, f), wid in [(k, v) for k, v in self.widgets.items()
                                if isinstance(k, tuple) and len(k) == 2 and k[0] == "asset"]:
            ps = [k["asset"].get(f) for k in clips]
            kind = assets.FIELD_INFO[f][1]
            vals = []
            for p, t in zip(ps, ts):
                v = assets.clean(f, curves.value(p, t) if p is not None else None)
                vals.append(assets.hex_of(v) if kind == "color" else
                            round(v, assets.FIELD_INFO[f][5]) if kind == "number" else v)
                if edit.key_at(p, t) is not None:
                    easings.add(edit.easing_at(p, t))
            v = vals[0] if len(set(map(str, vals))) == 1 else None
            if kind == "color":
                if v is None:
                    wid.setText("--")
                    wid.setStyleSheet("")
                else:
                    rgb = QColor(v[:7])
                    wid.setText(v)
                    wid.setStyleSheet(f"background: {v[:7]}; color: {'#000' if rgb.lightness() > 140 else '#fff'};")
            elif kind == "choice":
                opts = [x for _n, x in assets.FIELD_INFO[f][2]]
                self._set_combo(wid, opts.index(v) if v in opts else "--")
            else:
                self._set(("asset", f), v)
            self._key_state(self.widgets[("key", "asset", f)], ps, clips, ts)

    def _pick_asset_color(self, f):
        cur = self.widgets[("asset", f)].text()
        col = QColorDialog.getColor(QColor(cur[:7]) if cur.startswith("#") else QColor("white"), self, "顏色",
                                    QColorDialog.ShowAlphaChannel)
        if col.isValid():
            self._queue("asset", f, [col.redF(), col.greenF(), col.blueF(), col.alphaF()])
            self._flush()

    def _key_button(self, group, key):
        b = QPushButton(KEY_OFF)
        b.setFixedWidth(26)
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
                                         kind_tag(c.get("mask")), "volume" in c, (c.get("asset") or {}).get("family"))
        if shape != self.shape:
            self._flush()
            self.clip_ids = [k["id"] for k in clips]
            self.shape = shape
            self._build(c)
        if c is None:
            return
        w = self.widgets
        ts = [t_us - k["start_us"] for k in clips]
        names = {"image": "圖片", "video": "影片", "audio": "音訊", "text": "文字", "compound": "複合片段",
                 "filter": "濾鏡片段"}
        kinds = sorted({"靜態片段" if project.is_static(k) else names.get(k["type"], k["type"]) for k in clips})
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
            fonts = {curves.value(k["text"].get("font_path"), t) for k, t in zip(clips, ts)}
            self._show_font(fonts.pop() if len(fonts) == 1 else "--")
            self._key_state(w[("key", "text", "font_path")], [k["text"].get("font_path") for k in clips], clips, ts)
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
                hs = [k if group == "clip" else k[group] for k in clips]
                if (group, key) == ("transform", "scale_y"):            # absent: follows X
                    ps = [h.get("scale_y", h.get("scale", default)) for h in hs]
                else:
                    ps = [h.get(key, default) for h in hs]
                vals = [round(curves.value(p, t) * factor, dec) for p, t in zip(ps, ts)]
                self._set((group, key), vals[0] if same(vals) else None)
                for p, t in zip(ps, ts):
                    if edit.key_at(p, t) is not None:
                        easings.add(edit.easing_at(p, t))
                self._key_state(w[("key", group, key)], ps, clips, ts)
        if "scale_link" in w:
            w["scale_link"].blockSignals(True)
            w["scale_link"].setChecked(all(edit.linked(k["transform"]) for k in clips))
            w["scale_link"].blockSignals(False)
        if ("asset", "w") in w:
            self._show_asset(clips, ts, easings)
        if "mask_on" in w:
            on = {bool(project.active_mask(k)) for k in clips}
            w["mask_on"].blockSignals(True)
            w["mask_on"].setTristate(len(on) > 1)
            w["mask_on"].setCheckState(Qt.PartiallyChecked if len(on) > 1 else
                                       (Qt.Checked if on.pop() else Qt.Unchecked))
            w["mask_on"].blockSignals(False)
        if "blend" in w:
            modes = {curves.value(k.get("blend", "normal"), t) for k, t in zip(clips, ts)}
            self._set_combo(w["blend"], modes.pop() if len(modes) == 1 else "--")
            self._key_state(w[("key", "clip", "blend")], [k.get("blend", "normal") for k in clips], clips, ts)
        if "mask_kind" in w:
            kinds = {curves.value((k.get("mask") or {}).get("kind"), t) for k, t in zip(clips, ts)}
            self._set_combo(w["mask_kind"], kinds.pop() if len(kinds) == 1 else "--")
            if ("key", "mask", "kind") in w:
                self._key_state(w[("key", "mask", "kind")], [k["mask"].get("kind") for k in clips], clips, ts)
        if "mask_invert" in w:
            inv = {bool(curves.value(k["mask"].get("invert", False), t)) for k, t in zip(clips, ts)}
            w["mask_invert"].blockSignals(True)
            w["mask_invert"].setCheckState(Qt.PartiallyChecked if len(inv) > 1 else
                                           (Qt.Checked if inv.pop() else Qt.Unchecked))
            w["mask_invert"].blockSignals(False)
            self._key_state(w[("key", "mask", "invert")], [k["mask"].get("invert", False) for k in clips], clips, ts)
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
        if self.clip_ids and (group, key) != ("text", "content"):
            self.liveEdited.emit(list(self.clip_ids), group.rstrip("*"), key, value)   # shown in the preview now

    def show_live(self, clip_id, group, values):
        """The numbers of a drag on the canvas, while it goes on (not an edit yet)."""
        if self.clip_ids != [clip_id] or group not in self.groups:
            return
        if group == "asset":                             # (dragging an asset's size)
            rows = {f: (f, None, None, None, None, i[5], 1) for f, i in assets.FIELD_INFO.items() if i[1] == "number"}
        else:
            rows = {r[0]: r for r in PARAMS.get(group, ())}
        for key, v in values.items():
            r = rows.get(key)
            s = self.widgets.get((group, key))
            if r is not None and s is not None and not s.hasFocus():
                s.show_value(round(v * r[6], r[5]))

    def show_live_time(self, clip_id, start_us, duration_us, fps):
        """Start / length of a clip being dragged or trimmed on the timeline."""
        w = self.widgets
        if self.clip_ids == [clip_id] and "開始" in w:
            w["開始"].setText(timecode(start_us, fps))
            w["長度"].setText(f"{duration_us / US:.2f} 秒")

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


def kind_tag(mask):
    """A mask's shape for comparing forms: its kind, "keys" when the shape has keyframes,
    None without a mask."""
    if not mask:
        return None
    return "keys" if curves.is_animated(mask.get("kind")) else mask.get("kind")


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
    if all(k["type"] in ("image", "video", "compound", "filter") for k in clips):
        out["type"] = out["type"] if out["type"] != "mixed" else "video"     # can take masks
        kinds = {kind_tag(k.get("mask")) for k in clips}
        if len(kinds) == 1 and None not in kinds:
            out["mask"] = first["mask"]
    if all("volume" in k for k in clips):
        out["volume"] = first["volume"]
    if all(k.get("asset") for k in clips) and len({k["asset"]["family"] for k in clips}) == 1:
        out["asset"] = first["asset"]
    return out
