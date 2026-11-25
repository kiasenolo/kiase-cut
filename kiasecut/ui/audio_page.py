"""The 聲音 page: the whole window given to the sound, with the mixer at its heart.

    [ transport                                                    ]
    [ timeline (waveforms)              | small preview            ]
    [                                   | the chain of what is     ]
    [                                   | selected, its settings   ]
    [ strip | strip | ... bus | ... + | Master | spectrum          ]

It lies over the editor's panels (they stay as they were underneath) and borrows the editor's
timeline while it is open. What it edits goes through the editor's undo history
(soundedit.py); a value being dragged is heard at once and written when it is let go.
"""
import math
import os

import numpy as np
from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QApplication, QColorDialog, QInputDialog, QMessageBox, QScrollArea, QSlider, QSplitter,
                               QVBoxLayout, QWidget)

from .. import curves, dsp, edit, project, rack, soundedit, soundfx, soundnodes, userlib
from . import icons, inplace, linkmark, sound_follow
from .mixer_routing import BAND, Cables, Knob
from .sound_node_editor import SoundNodeEditor
from .sound_visuals import BAND_COLORS, Dynamics, Response, Spectrum
from .inspector import SpinBox
from .menukeys import Menu
from .meter import FADER_HI, FADER_LO, Bars, Fader, to_db

US = 1_000_000
RATE = 48000
STRIP_W = 104
KIND_COLOR = {"track": "#3f8a5a", "bus": "#3f6fa8", "master": "#a8473f", "clip": "#b3702f"}
STRIP_COLORS = (("紅", "#b5433c"), ("橙", "#c2762c"), ("黃", "#c9b23a"), ("綠", "#3f8a5a"), ("青", "#2f8f95"),
                ("藍", "#3f6fa8"), ("紫", "#7255a8"), ("粉紅", "#a84f83"), ("灰", "#66666e"))
SLIDER_STEPS = 1000


def lin_db(g):
    return max(FADER_LO, min(FADER_HI, to_db(g)))


def db_lin(db):
    return 0.0 if db <= FADER_LO else 10 ** (db / 20)


def db_text(db):
    return "-∞" if db <= FADER_LO else f"{db:+.1f}"


def slider_pos(p, v):
    """Where value v of parameter p sits on its slider (0 ... SLIDER_STEPS)."""
    lo, hi = p["min"], p["max"]
    if p.get("log") and lo > 0:
        f = math.log(max(v, lo) / lo) / math.log(hi / lo)
    else:
        f = (v - lo) / (hi - lo)
    return round(min(1.0, max(0.0, f)) * SLIDER_STEPS)


def slider_value(p, pos):
    lo, hi, f = p["min"], p["max"], pos / SLIDER_STEPS
    if p.get("log") and lo > 0:
        return lo * (hi / lo) ** f
    return lo + (hi - lo) * f


def decimals(p):
    span = p["max"] - p["min"]
    return 0 if span >= 1000 else 1 if span >= 50 else 2


class ParamSlider(QSlider):
    """The wheel never moves it; a double click puts the default back."""

    def __init__(self, reset):
        super().__init__(Qt.Horizontal)
        self.reset = reset
        self.setFocusPolicy(Qt.NoFocus)

    def wheelEvent(self, e):
        e.ignore()

    def mouseDoubleClickEvent(self, e):
        self.reset()


def small_button(text, tip="", checkable=False, width=22):
    b = QPushButton(text)
    b.setToolTip(tip)
    b.setCheckable(checkable)
    b.setFocusPolicy(Qt.NoFocus)
    if width:
        b.setFixedWidth(width)
    b.setStyleSheet("QPushButton { padding: 1px 3px; }")
    return b


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.hide()
            w.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def effect_menu(parent, chosen):
    """新增效果's menu, by category; chosen(kind)."""
    menu = Menu(parent)
    menu.addAction(soundfx.GRAPH_TITLE + "（用節點組合）", lambda: chosen(soundfx.GRAPH))
    menu.addSeparator()
    for title, kinds in soundfx.CATEGORIES:
        sub = menu.addMenu(title)
        for kind in kinds:
            sub.addAction(soundfx.EFFECTS[kind]["title"], lambda kind=kind: chosen(kind))
    return menu


# -- one effect in the chain panel ----------------------------------------------------------------
class EffectBox(QFrame):
    def __init__(self, page, effect, index, count):
        super().__init__()
        self.page, self.eid, self.kind = page, effect["id"], effect["effect"]
        self.spec = soundfx.EFFECTS.get(self.kind)
        self.rows = {}                          # param name -> (spin, slider, key button)
        self.choices = {}                       # param name -> its check box or combo
        self.visual = None                      # what is drawn above the parameters
        self.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(3)
        head = QHBoxLayout()
        head.setSpacing(2)
        self.on = QCheckBox()
        self.on.setFocusPolicy(Qt.NoFocus)
        self.on.setToolTip("啟用")
        self.on.clicked.connect(lambda on: page.edit("啟用聲音效果" if on else "停用聲音效果",
                                                     soundedit.set_enabled, self.eid, on))
        head.addWidget(self.on)
        self.title = QPushButton(("▾ " if self.eid not in page.folded else "▸ ") + soundfx.title(effect))
        self.title.setStyleSheet("QPushButton { text-align: left; border: none; background: transparent; font-weight: 600; }")
        self.title.setFocusPolicy(Qt.NoFocus)
        self.title.clicked.connect(lambda: page.fold(self.eid))
        head.addWidget(self.title, 1)
        for text, tip, to, ok in (("↑", "往前移", index - 1, index > 0), ("↓", "往後移", index + 1, index < count - 1)):
            b = small_button(text, tip)
            b.setEnabled(ok)
            b.clicked.connect(lambda _c=False, to=to: page.edit("調整聲音效果順序", soundedit.move_effect, self.eid, to))
            head.addWidget(b)
        x = small_button("✕", "移除")
        x.clicked.connect(lambda: page.edit("移除聲音效果", soundedit.remove_effect, self.eid))
        head.addWidget(x)
        lay.addLayout(head)
        if self.kind == soundfx.GRAPH:
            if self.eid not in page.folded:
                b = QPushButton("編輯節點圖")
                b.setFocusPolicy(Qt.NoFocus)
                b.clicked.connect(lambda: page.open_graph(self.eid))
                lay.addWidget(b)
            return
        if self.spec is None:
            lay.addWidget(QLabel("這個版本沒有這個效果"))
            return
        if self.eid in page.folded:
            return
        visual = self.spec.get("visual")
        if visual in ("eq", "response"):
            self.visual = Response(self.kind, 210 if visual == "eq" else 130)
            self.visual.band = page.bands.get(self.eid, 1)
            self.visual.live.connect(lambda values: page.live(soundedit.set_params, self.eid, values, page.time()))
            self.visual.done.connect(lambda values: page.edit("調整聲音效果", soundedit.set_params, self.eid, values,
                                                              page.time()))
            self.visual.bandPicked.connect(lambda i: page.pick_band(self.eid, i))
            lay.addWidget(self.visual)
        elif visual == "dynamics":
            self.visual = Dynamics(self.kind)
            self.visual.live.connect(lambda values: page.live(soundedit.set_params, self.eid, values, page.time()))
            self.visual.done.connect(lambda values: page.edit("調整聲音效果", soundedit.set_params, self.eid, values,
                                                              page.time()))
            lay.addWidget(self.visual)
        elif visual == "spectrum":
            self.visual = Spectrum(150)
            lay.addWidget(self.visual)
        if visual == "eq":
            bands = QHBoxLayout()
            bands.setSpacing(2)
            self.band_buttons = []
            for i in range(1, soundfx.EQ_BANDS + 1):
                b = small_button(str(i), f"頻段 {i}", width=0)
                b.clicked.connect(lambda _c=False, i=i: page.pick_band(self.eid, i))
                bands.addWidget(b)
                self.band_buttons.append(b)
            lay.addLayout(bands)
        self.side = None
        if self.spec.get("side"):
            row = QHBoxLayout()
            row.addWidget(QLabel("側鏈來源"))
            self.side = QComboBox()
            self.side.setFocusPolicy(Qt.NoFocus)
            self.side.setToolTip("偵測哪裡的音量（例如：選人聲，讓這裡在人聲出現時壓低）")
            self.side.activated.connect(lambda i: page.edit("側鏈來源", soundedit.set_side, self.eid,
                                                            self.side.itemData(i)))
            row.addWidget(self.side, 1)
            lay.addLayout(row)
        grid = QGridLayout()
        grid.setHorizontalSpacing(5)
        grid.setVerticalSpacing(2)
        for r, p in enumerate(page.visible_params(effect)):
            name = p["name"]
            label = QLabel(p["label"])
            grid.addWidget(label, r, 0)
            if p.get("choices"):
                if p["choices"] == ["關", "開"]:
                    box = QCheckBox()
                    box.clicked.connect(lambda on, name=name: self.choose(name, int(on)))
                else:
                    box = QComboBox()
                    box.addItems(p["choices"])
                    box.activated.connect(lambda i, name=name: self.choose(name, i))
                box.setFocusPolicy(Qt.NoFocus)
                grid.addWidget(box, r, 1, 1, 2)
                self.choices[name] = box
                continue
            slider = ParamSlider(lambda name=name: page.edit("重設參數", soundedit.reset_param, self.eid, name))
            slider.setRange(0, SLIDER_STEPS)
            slider.sliderMoved.connect(lambda v, p=p: self.dragged(p, slider_value(p, v)))
            slider.sliderReleased.connect(lambda p=p, s=slider: self.write(p, slider_value(p, s.value())))
            grid.addWidget(slider, r, 1)
            spin = SpinBox()
            spin.setDecimals(decimals(p))
            spin.setSingleStep(10 ** -decimals(p) if decimals(p) else max(1.0, (p["max"] - p["min"]) / 1000))
            spin.set_limits(p["min"], p["max"], p["min"], p["max"])
            if p["unit"]:
                spin.setSuffix(" " + p["unit"])
            spin.setFixedWidth(92)
            spin.edited.connect(lambda v, p=p: self.write(p, v))
            grid.addWidget(spin, r, 2)
            key = small_button("◇", "在播放頭加上 / 移除關鍵幀")
            key.clicked.connect(lambda _c=False, name=name: self.toggle_key(name))
            grid.addWidget(key, r, 3)
            self.rows[name] = (spin, slider, key)
            for w in (label, slider, spin, spin.lineEdit()):
                w.setContextMenuPolicy(Qt.CustomContextMenu)
                w.customContextMenuRequested.connect(lambda at, w=w, p=p: self.param_menu(p, w.mapToGlobal(at)))
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)

    def param_menu(self, p, at):
        menu = Menu(self)
        page = self.page
        menu.addAction("重設為預設值", lambda: page.edit("重設參數", soundedit.reset_param, self.eid, p["name"]))
        if page.time() is not None:
            menu.addAction("加上 / 移除關鍵幀", lambda: self.toggle_key(p["name"]))
        sound_follow.add_items(menu, page, page.target, self.eid, p, page.time())
        menu.exec(at)

    def choose(self, name, value):
        self.page.edit("調整聲音效果", soundedit.set_param, self.eid, name, value, self.page.time())

    def spec_of(self, name):
        return next(p for p in self.spec["params"] if p["name"] == name)

    def toggle_key(self, name):
        t = self.page.time()
        if t is None:
            return
        self.page.edit("聲音參數關鍵幀", soundedit.toggle_key, self.eid, name, t)

    def dragged(self, p, v):
        spin = self.rows[p["name"]][0]
        spin.show_value(v)
        self.page.live(soundedit.set_param, self.eid, p["name"], v, self.page.time())

    def write(self, p, v):
        self.page.edit("調整聲音效果", soundedit.set_param, self.eid, p["name"], v, self.page.time(),
                       merge=("sfx", self.eid, p["name"]))

    def show_effect(self, effect):
        self.on.setChecked(effect.get("enabled", True))
        if self.spec is None or any(slider.isSliderDown() for _, slider, _ in self.rows.values()):
            return
        t = self.page.time()
        names = rack.values(self.page.win.view(), self.page.level_time()) if effect.get("expr") else None
        values = soundfx.values(effect, t or 0, names) if self.spec["params"] else {}
        if isinstance(self.visual, (Response, Dynamics)):
            self.visual.set_values(values)
        if getattr(self, "side", None) is not None:
            entries = [("", "自己")] + soundedit.side_sources(self.page.level(), self.page.target)
            if [self.side.itemData(i) for i in range(self.side.count())] != [i for i, _ in entries] or \
                    [self.side.itemText(i) for i in range(self.side.count())] != [n for _, n in entries]:
                self.side.clear()
                for ident, name in entries:
                    self.side.addItem(name, ident)
            chosen = (effect.get("side") or {}).get("id") or ""
            self.side.setCurrentIndex(max(0, self.side.findData(chosen)))
        if self.spec.get("visual") == "eq" and self.eid not in self.page.folded:
            band = self.page.bands.get(self.eid, 1)
            for i, b in enumerate(self.band_buttons, 1):
                b.setStyleSheet(f"QPushButton {{ padding: 1px; border: 2px solid {'#ffffff' if i == band else 'transparent'}; "
                                f"background: {BAND_COLORS[i - 1] if values[f'o{i}'] > 0.5 else '#222226'}; "
                                f"color: {'#000000' if values[f'o{i}'] > 0.5 else '#8e8e94'}; }}")
        for name, box in self.choices.items():
            if isinstance(box, QCheckBox):
                box.setChecked(values[name] > 0.5)
            else:
                box.setCurrentIndex(int(round(values[name])))
        for name, (spin, slider, key) in self.rows.items():
            p = self.spec_of(name)
            held = (effect.get("params") or {}).get(name, p["default"])
            v = curves.value(held, t or 0)
            if not spin.editing:
                spin.show_value(v)
            slider.blockSignals(True)
            slider.setValue(slider_pos(p, v))
            slider.blockSignals(False)
            animated = curves.is_animated(held)
            bound = (effect.get("expr") or {}).get(name)
            linkmark.mark(spin, sound_follow.said(bound) if bound else "")
            key.setText("◆" if animated and edit.key_at(held, t or 0) is not None else "◈" if animated else "◇")


# -- the chain of what is selected ----------------------------------------------------------------
class ChainPanel(QWidget):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.boxes = {}
        self.shape = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(8, 4, 8, 4)
        self.title = QLabel("")
        self.title.setObjectName("crumb")
        head.addWidget(self.title, 1)
        self.add = QPushButton("＋ 新增效果")
        self.add.setFocusPolicy(Qt.NoFocus)
        self.add.clicked.connect(lambda: effect_menu(self, page.add_effect).exec(
            self.add.mapToGlobal(self.add.rect().bottomLeft())))
        self.presets = QPushButton("預設")
        self.presets.setFocusPolicy(Qt.NoFocus)
        self.presets.clicked.connect(lambda: page.preset_menu(self.presets.mapToGlobal(self.presets.rect().bottomLeft())))
        head.addWidget(self.presets)
        head.addWidget(self.add)
        lay.addLayout(head)
        self.warning = QLabel("")
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("color: #e0a03a; padding: 2px 8px;")
        self.warning.hide()
        lay.addWidget(self.warning)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        self.list = QVBoxLayout(inner)
        self.list.setContentsMargins(6, 2, 6, 6)
        self.list.setSpacing(4)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

    def refresh(self):
        page = self.page
        target = page.target
        level = page.level()
        entries = soundedit.chain(level, target) if target else []
        self.add.setEnabled(target is not None)
        self.presets.setEnabled(target is not None)
        self.title.setText(page.target_name(target))
        why = dsp.error()
        self.warning.setVisible(bool(why))
        if why:
            self.warning.setText("聲音效果函式庫無法使用，效果不會作用：" + why.splitlines()[0])
        shape = (target, tuple((e["id"], e.get("effect"), e["id"] in page.folded,
                                tuple(p["name"] for p in page.visible_params(e))) for e in entries))
        dragging = any(getattr(b.visual, "drag", None) is not None for b in self.boxes.values())
        if shape != self.shape and not dragging:   # (rebuilt only when it changes shape: a value being dragged keeps its widget)
            self.shape = shape
            clear_layout(self.list)
            self.boxes = {}
            for i, e in enumerate(entries):
                self.boxes[e["id"]] = box = EffectBox(page, e, i, len(entries))
                self.list.addWidget(box)
            if target and not entries:
                note = QLabel("沒有效果")
                note.setObjectName("viewer")
                note.setAlignment(Qt.AlignCenter)
                self.list.addWidget(note)
            self.list.addStretch()
        for e in entries:
            if e["id"] in self.boxes:
                self.boxes[e["id"]].show_effect(e)

    def drawn(self):
        """The boxes that draw their effect's sound: {effect id: widget}."""
        return {i: b.visual for i, b in self.boxes.items() if b.visual is not None}


# -- one channel of the mixer ------------------------------------------------------------------------
class NameButton(QPushButton):
    """A strip's name: a click selects the strip (Ctrl, Shift: more of them), a drag moves it."""

    def __init__(self, strip):
        super().__init__("")
        self.strip = strip
        self.at = None
        self.dragging = False
        self.setFocusPolicy(Qt.NoFocus)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        self.at, self.dragging = e.globalPosition().toPoint(), False
        page, target = self.strip.page, self.strip.target
        self.later = target in page.picked and not e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)
        if not self.later:                  # (one of several selected: they stay until it is clear it is no drag)
            page.pick(target, e.modifiers())

    def mouseMoveEvent(self, e):
        if self.at is None or self.strip.kind == "master":
            return
        if not self.dragging and abs(e.globalPosition().toPoint().x() - self.at.x()) < QApplication.startDragDistance():
            return
        self.dragging = True
        self.strip.page.drag_strips(self.strip.target, e.globalPosition().toPoint())

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self.at is None:
            return
        self.at = None
        if self.dragging:
            self.dragging = False
            self.strip.page.drop_strips(self.strip.target, e.globalPosition().toPoint())
        elif self.later:
            self.strip.page.pick(self.strip.target, Qt.NoModifier)


class Strip(QFrame):
    def __init__(self, page, target):
        super().__init__()
        self.page, self.target = page, target
        self.kind = target[0]
        self.channel = target[1] or soundfx.MASTER
        self.shape = None
        self.setFixedWidth(STRIP_W)
        self.setObjectName("strip")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        self.name = NameButton(self)
        self.name.setContextMenuPolicy(Qt.CustomContextMenu)
        self.name.customContextMenuRequested.connect(self.name_menu)
        lay.addWidget(self.name)
        slots = QWidget()
        self.slots = QVBoxLayout(slots)
        self.slots.setContentsMargins(0, 0, 0, 0)
        self.slots.setSpacing(1)
        self.slots.setAlignment(Qt.AlignTop)
        area = QScrollArea()
        area.setWidget(slots)
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setFixedHeight(92)
        lay.addWidget(area)
        self.pan = None
        if self.kind != "master":
            self.pan = SpinBox()
            self.pan.setDecimals(0)
            self.pan.set_limits(-100, 100, -100, 100)
            self.pan.setPrefix("聲像 ")
            self.pan.edited.connect(self.pan_set)
            lay.addWidget(self.pan)
        row = QHBoxLayout()
        row.setSpacing(3)
        self.bars = Bars()
        self.fader = Fader(Qt.Vertical)
        self.fader.setRange(round(FADER_LO * 10), round(FADER_HI * 10))
        self.fader.setFocusPolicy(Qt.NoFocus)
        self.fader.setToolTip("音量；按兩下回到 0 dB")
        self.fader.valueChanged.connect(self.fader_moved)
        self.fader.sliderReleased.connect(lambda: self.fader_done())
        row.addWidget(self.bars, 1)
        row.addWidget(self.fader)
        lay.addLayout(row, 1)
        self.db = QLabel("")
        self.db.setAlignment(Qt.AlignCenter)
        self.db.setStyleSheet("font-family: Consolas, monospace;")
        lay.addWidget(self.db)
        self.mute = self.solo = None
        if self.kind != "master":
            row = QHBoxLayout()
            row.setSpacing(3)
            self.mute = small_button("M", "靜音", True, 0)
            self.solo = small_button("S", "獨奏", True, 0)
            for b, flag, label, colour in ((self.mute, "muted", "靜音", "#c0504a"), (self.solo, "solo", "獨奏", "#c9a63a")):
                b.setStyleSheet("QPushButton { background: #222226; color: #8e8e94; border: none; padding: 3px; }"
                                f"QPushButton:checked {{ background: {colour}; color: #000000; }}")
                b.clicked.connect(lambda on, flag=flag, label=label: page.edit_many(
                    self.group(), label if on else "取消" + label, soundedit.set_flags, flag, on))
                row.addWidget(b)
            lay.addLayout(row)
        # -- the line from what is selected to this one
        foot = QWidget()
        foot.setFixedHeight(26)
        row = QHBoxLayout(foot)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        row.addStretch()
        self.wire = QPushButton("▲")
        self.wire.setFocusPolicy(Qt.NoFocus)
        self.wire.setFixedSize(34, 22)
        self.wire.clicked.connect(lambda: page.toggle_wire(target))
        self.wire.setContextMenuPolicy(Qt.CustomContextMenu)
        self.wire.customContextMenuRequested.connect(lambda at: self.wire_menu(self.wire.mapToGlobal(at)))
        row.addWidget(self.wire)
        self.knob = Knob()
        self.knob.live.connect(lambda db: page.turn_wire(target, db, False))
        self.knob.done.connect(lambda db: page.turn_wire(target, db, True))
        self.knob.menu_asked.connect(self.wire_menu)
        row.addWidget(self.knob)
        row.addStretch()
        lay.addWidget(foot)
        self.wire.hide()
        self.knob.hide()

    def group(self):
        """The strips what is done to this one is done to: all that are selected, if it is."""
        picked = self.page.picked
        return list(picked) if self.target in picked else [self.target]

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.page.pick(self.target, e.modifiers())

    # -- the fader and pan: of all that are selected, each from where it is -----------------------------
    def stored_db(self, target):
        return soundedit.gain_db(soundedit.holder(self.page.level(), target).get("gain", 1.0))

    def fader_moved(self, v):
        db = v / 10
        self.db.setText(db_text(db) + " dB")
        if self.kind == "master":
            self.page.win.on_master(db_lin(db), not self.fader.isSliderDown())
        elif self.fader.isSliderDown():
            delta = db - self.stored_db(self.target)
            targets = [t for t in self.group() if t[0] != "master"]
            for t in targets:
                other = self.page.strips.get(t)
                if other is not None and other is not self:
                    other.show_gain(soundedit.db_gain(self.stored_db(t) + delta))
            self.page.live_many(targets, soundedit.nudge_gain, delta)
        else:
            self.fader_done()

    def fader_done(self):
        db = self.fader.value() / 10
        if self.kind == "master":
            self.page.win.on_master(db_lin(db), True)
            return
        delta = db - self.stored_db(self.target)
        if abs(delta) > 1e-3:
            targets = self.group()
            self.page.edit_many(targets, "音量", soundedit.nudge_gain, delta, merge=("fader", tuple(targets)))

    def pan_set(self, v):
        delta = v / 100 - soundedit.holder(self.page.level(), self.target).get("pan", 0.0)
        targets = self.group()
        self.page.edit_many(targets, "聲像", soundedit.nudge_pan, delta, merge=("pan", tuple(targets)))

    def show_gain(self, gain):
        db = lin_db(gain)
        self.fader.blockSignals(True)
        self.fader.setValue(round(db * 10))
        self.fader.blockSignals(False)
        self.db.setText(db_text(db) + " dB")

    # -- menus ----------------------------------------------------------------------------------------
    def name_menu(self, at):
        page = self.page
        if self.target not in page.picked:
            page.select(self.target)
        group = self.group()
        buses = [t[1] for t in group if t[0] == "bus"]
        channels = [t for t in group if t[0] != "master"]
        menu = Menu(self)
        if self.kind != "master" and len(group) == 1:
            menu.addAction("重新命名…", self.rename)
        colours = menu.addMenu("顏色")
        for label, colour in STRIP_COLORS:
            pix = QPixmap(14, 14)
            pix.fill(QColor(colour))
            colours.addAction(QIcon(pix), label, lambda colour=colour: page.color_strips(group, colour))
        colours.addSeparator()
        colours.addAction("自訂…", lambda: page.ask_color(group))
        colours.addAction("預設顏色", lambda: page.color_strips(group, None))
        if channels:
            menu.addAction("改送到新的 bus", lambda: page.to_new_bus(channels))
        if buses:
            menu.addAction("刪除 bus" if len(buses) == 1 else f"刪除 {len(buses)} 條 bus", lambda: page.remove_buses(buses))
        menu.exec(self.name.mapToGlobal(at))

    def wire_menu(self, at):
        page = self.page
        dest = self.target[1] or soundfx.MASTER
        sources = page.sources()
        level = page.level()
        found = [(s, soundedit.route_to(level, s, dest)) for s in sources]
        found = [(s, r) for s, r in found if r is not None]
        menu = Menu(self)
        only = menu.addAction("只接到這條", lambda: page.edit_many(sources, "只接到這條", soundedit.route_only, dest))
        only.setEnabled(any(soundedit.can_route(level, s, dest) for s in sources))
        if found:
            first, route = found[0]
            pre = menu.addAction("推桿前送出", lambda: page.wire_each([s for s, _ in found], "送出位置",
                                                                  dest, None, not route.get("pre")))
            pre.setCheckable(True)
            pre.setChecked(bool(route.get("pre")))
            menu.addAction("送出量回到 0 dB", lambda: page.wire_each([s for s, _ in found], "送出量", dest, 0.0))
            keyed = curves.is_animated(route.get("gain"))
            here = keyed and edit.key_at(route["gain"], page.level_time()) is not None
            menu.addAction("移除這裡的關鍵幀" if here else "在播放頭加關鍵幀", lambda: page.edit_target(
                first, "送出量關鍵幀", soundedit.toggle_route_key, dest, page.level_time()))
        menu.exec(at)

    def rename(self):
        old = self.name.toolTip()
        name, ok = inplace.ask_name(self, old, (self.name, self.name.rect()))
        if ok and name.strip() and name != old:
            if self.kind == "bus":
                self.page.win.apply("重新命名 bus", soundedit.rename_bus, self.target[1], name)
            else:
                self.page.win.apply("重新命名軌道", edit.rename_track, self.target[1], name)

    def slot_menu(self, widget, at, effect_id):
        menu = Menu(self)
        menu.addAction("移除", lambda: self.page.edit_target(self.target, "移除聲音效果", soundedit.remove_effect, effect_id))
        menu.exec(widget.mapToGlobal(at))

    # -- showing --------------------------------------------------------------------------------------
    def show_channel(self, level):
        holder = soundedit.holder(level, self.target)
        if self.kind == "master":
            name = "Master"
        else:
            name = holder.get("name") or self.target[1]
        self.name.setText(self.name.fontMetrics().elidedText(name, Qt.ElideRight, STRIP_W - 18))
        self.name.setToolTip(name)
        self.show_selected()
        chain = holder.get("sound_effects") or []
        shape = tuple((e["id"], e.get("effect"), e.get("enabled", True)) for e in chain)
        if shape != self.shape:
            self.shape = shape
            self.build_slots(chain)
        if self.kind != "master":
            if not self.pan.editing:
                self.pan.show_value(curves.value(holder.get("pan", 0.0), 0) * 100)
            self.mute.setChecked(bool(holder.get("muted")))
            self.solo.setChecked(bool(holder.get("solo")))
        if not self.fader.isSliderDown():
            self.show_gain(self.page.win.proj.get("master_gain", 1.0) if self.kind == "master" else holder.get("gain", 1.0))

    def colour(self):
        return soundedit.holder(self.page.level(), self.target).get("mix_color") or KIND_COLOR[self.kind]

    def show_selected(self):
        page = self.page
        edge = "#ffffff" if page.target == self.target else "#8fb8ff" if self.target in page.picked else "transparent"
        colour = self.colour()
        ink = "#000000" if QColor(colour).lightnessF() > 0.62 else "#ffffff"
        self.name.setStyleSheet(f"QPushButton {{ background: {colour}; color: {ink}; padding: 3px; "
                                f"border: 2px solid {edge}; }}")
        picked = self.target in page.picked
        self.setStyleSheet(f"QFrame#strip {{ background: {'#222228' if picked else '#161618'}; }}")

    def show_wire(self, level):
        """The button (and knob) for the line from the selected strips to this one."""
        dest = self.target[1] or soundfx.MASTER
        sources = self.page.sources()
        shown = bool(sources) and self.target not in sources
        found = [r for r in (soundedit.route_to(level, s, dest) for s in sources) if r is not None] if shown else []
        able = shown and (bool(found) or any(soundedit.can_route(level, s, dest) for s in sources))
        self.wire.setVisible(shown)
        self.knob.setVisible(bool(found))
        if not shown:
            return
        self.wire.setEnabled(able)
        colour = QColor(self.page.strip_colour(sources[0])).lighter(150).name()
        if found and len(found) == len(sources):
            look = f"background: {colour}; color: #000000; border: 1px solid {colour};"
        elif found:                                       # (only some of the selected are connected)
            look = f"background: #222226; color: {colour}; border: 1px dashed {colour};"
        else:
            look = "background: #222226; color: %s; border: 1px solid #3a3a40;" % ("#c8c8ce" if able else "#4a4a50")
        self.wire.setStyleSheet(f"QPushButton {{ {look} padding: 0; }}")
        self.wire.setToolTip(("拔掉接到這條的線" if found and len(found) == len(sources) else "接到這條")
                             if able else "會接成迴圈")
        if found:
            gain = found[0].get("gain", 0.0)
            self.knob.show_value(curves.value(gain, self.page.level_time()), curves.is_animated(gain))

    def build_slots(self, chain):
        clear_layout(self.slots)
        for e in chain:
            b = small_button(soundfx.title(e), soundfx.title(e), width=0)
            b.setStyleSheet("QPushButton { padding: 1px 2px; background: #222226; text-align: left; %s}"
                            % ("" if e.get("enabled", True) else "color: #6a6a72; "))
            b.setMinimumWidth(1)
            b.clicked.connect(lambda _c=False, eid=e["id"]: self.page.select(self.target, eid))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda at, b=b, eid=e["id"]: self.slot_menu(b, at, eid))
            self.slots.addWidget(b)
        plus = small_button("＋", "新增效果", width=0)
        plus.clicked.connect(lambda: effect_menu(self, lambda kind: self.page.add_effect(kind, self.target)).exec(
            plus.mapToGlobal(plus.rect().bottomLeft())))
        self.slots.addWidget(plus)


class SmallPreview(QLabel):
    def __init__(self):
        super().__init__()
        self.image = None
        self.setMinimumHeight(90)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background: #000000;")

    def show_image(self, img):
        self.image = img
        self._fit()

    def _fit(self):
        if self.image is not None and not self.image.isNull() and self.width() > 4 and self.height() > 4:
            self.setPixmap(QPixmap.fromImage(self.image.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def sizeHint(self):
        return QSize(320, 180)


# -- the page -----------------------------------------------------------------------------------------
class AudioPage(QWidget):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.target = None                      # (kind, id) whose chain the panel shows
        self.picked = []                        # the mixer strips selected (target among them, when it is a strip)
        self.folded = set()                     # effect ids folded shut in the panel
        self.bands = {}                         # EQ effect id -> the band whose parameters show
        self.strips = {}                        # target -> Strip
        self.setObjectName("audiopage")
        self.setAutoFillBackground(True)
        self.setAttribute(Qt.WA_StyledBackground)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        bar = QWidget()
        bar.setObjectName("bar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 3, 8, 3)
        self.time_label = QLabel("")
        self.time_label.setObjectName("time")
        row.addWidget(self.time_label)
        row.addStretch()
        self.play_btn = None
        for name, tip, fn in (("start", "到開頭（Home）", lambda: win.seek(0)), ("prev", "上一幀（←）", lambda: win.step(-1)),
                              ("play", "播放 / 暫停（空白鍵）", win.toggle_play), ("next", "下一幀（→）", lambda: win.step(1)),
                              ("end", "到結尾（End）", lambda: win.seek(win.length - 1))):
            b = win.tool(name, tip, fn)
            b.setFocusPolicy(Qt.NoFocus)
            row.addWidget(b)
            if name == "play":
                self.play_btn = b
        row.addStretch()
        self.preview_btn = QPushButton("預覽畫面")
        self.preview_btn.setCheckable(True)
        self.preview_btn.setFocusPolicy(Qt.NoFocus)
        self.preview_btn.setChecked(str(win.settings().value("audio/preview", "true")).lower() not in ("false", "0"))
        self.preview_btn.toggled.connect(self.show_preview)
        row.addWidget(self.preview_btn)
        lay.addWidget(bar)

        self.vsplit = QSplitter(Qt.Vertical)
        self.vsplit.setChildrenCollapsible(False)
        self.hsplit = QSplitter(Qt.Horizontal)
        self.hsplit.setChildrenCollapsible(False)
        slot = QWidget()
        self.timeline_slot = QVBoxLayout(slot)          # (the editor's timeline, while the page is open)
        self.timeline_slot.setContentsMargins(0, 0, 0, 0)
        self.hsplit.addWidget(slot)
        self.right = QSplitter(Qt.Vertical)
        self.picture = SmallPreview()
        self.picture.setVisible(self.preview_btn.isChecked())
        self.right.addWidget(self.picture)
        self.chain = ChainPanel(self)
        self.right.addWidget(self.chain)
        self.nodes = SoundNodeEditor(self)              # a 聲音節點效果 opened (below the chain, or over the page)
        self.nodes.hide()
        self.right.addWidget(self.nodes)
        self.enlarged = False
        self._narrow = None                             # hsplit's sizes before a graph widened the right side
        self.right.setStretchFactor(0, 0)
        self.right.setStretchFactor(1, 1)
        self.right.setSizes([190, 520])
        self.right.setMinimumWidth(300)
        self.hsplit.addWidget(self.right)
        self.hsplit.setStretchFactor(0, 1)
        self.hsplit.setSizes([900, 420])
        self.vsplit.addWidget(self.hsplit)

        self.mixer_box = mixer = QWidget()
        row = QHBoxLayout(mixer)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        strips = QWidget()
        self.strip_row = QHBoxLayout(strips)
        self.strip_row.setContentsMargins(4, 4, 4, BAND)
        self.strip_row.setSpacing(3)
        self.strip_row.setAlignment(Qt.AlignLeft)
        self.strip_area = QScrollArea()
        self.strip_area.setWidget(strips)
        self.strip_area.setWidgetResizable(True)
        row.addWidget(self.strip_area, 1)
        self.master_slot = QHBoxLayout()
        self.master_slot.setContentsMargins(3, 4, 3, BAND)
        row.addLayout(self.master_slot)
        self.wires = Cables(self, mixer)
        bar_ = self.strip_area.horizontalScrollBar()
        bar_.valueChanged.connect(lambda _v: self.wires.update())
        bar_.rangeChanged.connect(lambda *_a: QTimer.singleShot(0, self._level_master))
        mixer.setMinimumHeight(370)
        mixer.setMinimumWidth(320)
        self.mixsplit = QSplitter(Qt.Horizontal)        # the mixer | the output's spectrum: as wide as it is dragged
        self.mixsplit.setChildrenCollapsible(False)
        self.mixsplit.addWidget(mixer)
        self.spectrum = Spectrum()
        self.mixsplit.addWidget(self.spectrum)
        self.mixsplit.setStretchFactor(0, 1)            # (a wider window: the mixer takes it)
        self.mixsplit.setStretchFactor(1, 0)
        self.mixsplit.setSizes([1100, 260])
        self.vsplit.addWidget(self.mixsplit)
        self.vsplit.setStretchFactor(0, 1)
        self.vsplit.setSizes([460, 400])
        lay.addWidget(self.vsplit, 1)
        self.setStyleSheet("QWidget#audiopage { background: #0d0d0d; }")
        for key, split in (("audio/vsplit", self.vsplit), ("audio/hsplit", self.hsplit), ("audio/right", self.right),
                           ("audio/mixsplit", self.mixsplit)):
            state = win.settings().value(key)
            if state is not None:
                split.restoreState(state)
            split.splitterMoved.connect(lambda *_a, k=key, sp=split: win.settings().setValue(k, sp.saveState()))

        self.tick = QTimer(self, interval=33)
        self.tick.timeout.connect(self.update_meters)
        win.installEventFilter(self)
        win.timeline.clipSelected.connect(self.clip_selected)
        self._strip_shape = None
        self.hide()

    # -- where it lies ----------------------------------------------------------------------------------
    def place(self):
        win = self.win
        top = win.menuBar().height() if win.menuBar().isVisible() else 0
        bottom = win.statusBar().height() if win.statusBar().isVisible() else 0
        self.setGeometry(0, top, win.width(), max(0, win.height() - top - bottom))

    def eventFilter(self, obj, e):
        if obj is self.win and e.type() == QEvent.Resize and self.isVisible():
            self.place()
            if self.enlarged:
                QTimer.singleShot(0, self._cover)
        return False

    def open(self):
        self.place()
        self.show()
        self.raise_()
        self.tick.start()
        clip = self.win.timeline.selected
        if clip is not None and soundedit.sounding(clip):
            self.target, self.picked = ("clip", clip["id"]), []
        self.refresh()

    def close_page(self):
        self.tick.stop()
        self.hide()

    # -- what is edited ---------------------------------------------------------------------------------
    def level(self):
        """The open level, to read from (a project, or an open compound's content)."""
        return self.win.container()

    def tracks(self):
        """The level's tracks that can sound, in the timeline's order top to bottom for pictures
        and then the sound tracks."""
        ts = self.level()["tracks"]
        fed = soundedit.fed_channels(self.level())
        sounding = lambda t: t["kind"] == "audio" or t["id"] in fed or soundfx.routed(t) or \
            any(soundedit.sounding(c) for c in t["clips"])
        return [t for t in ts if t["kind"] == "audio" and sounding(t)] + \
            [t for t in ts if t["kind"] != "audio" and sounding(t)]

    def level_time(self):
        return int(self.win.playhead_us())

    def time(self):
        """The time the selected chain's keyframes are counted in."""
        if not self.target:
            return None
        if self.target[0] == "clip":
            return int(self.win.clip_time(self.target[1]))
        return self.level_time()

    # -- the strips selected -------------------------------------------------------------------------
    def strip_order(self):
        """The strips' targets, left to right (the master last)."""
        return list(self.strips)

    def sources(self):
        """The selected strips that send sound on."""
        return [t for t in self.picked if t[0] != "master"]

    def pick(self, target, modifiers):
        """A click on a strip: Ctrl adds or takes away, Shift selects up to it."""
        picked = list(self.picked)
        if modifiers & Qt.ShiftModifier and picked and self.target in self.strips:
            order = self.strip_order()
            a, b = sorted((order.index(self.target), order.index(target)))
            picked += [t for t in order[a:b + 1] if t not in picked]
        elif modifiers & Qt.ControlModifier:
            if target in picked and len(picked) > 1:
                picked.remove(target)
                if self.target == target:
                    self.target = picked[-1]
                self.picked = picked
                self.refresh()
                return
            if target not in picked:
                picked.append(target)
        else:
            picked = [target]
        self.target, self.picked = target, picked
        self.refresh()

    def acting_on(self, target):
        """What adding an effect to target adds it to."""
        return list(self.picked) if target in self.picked and len(self.picked) > 1 else [target]

    # -- the lines -------------------------------------------------------------------------------------
    def strip_colour(self, target):
        strip = self.strips.get(target)
        try:
            return strip.colour() if strip is not None else KIND_COLOR[target[0]]
        except edit.EditError:
            return KIND_COLOR[target[0]]

    def cables(self):
        """(sources, [(source, destination)], {source: colour}) of the lines to be shown."""
        sources = [t for t in self.sources() if t in self.strips]
        if not sources or not self.win.proj:
            return [], [], {}
        level = self.level()
        kinds = {t[1]: t for t in self.strips if t[0] != "master"}
        kinds[soundfx.MASTER] = ("master", "")
        try:
            found = [(s, kinds[r["to"]]) for s in sources for r in soundedit.routes(level, s) if r["to"] in kinds]
        except edit.EditError:
            return [], [], {}
        return sources, found, {s: self.strip_colour(s) for s in sources}

    def toggle_wire(self, target):
        dest = target[1] or soundfx.MASTER
        sources = self.sources()
        level = self.level()
        on = not all(soundedit.route_to(level, s, dest) for s in sources)
        self.edit_many(sources, "接線" if on else "拔掉接線", soundedit.set_routes, dest, on)

    def turn_wire(self, target, db, final):
        """The knob of the lines to target: they move together, each from where it is."""
        dest = target[1] or soundfx.MASTER
        level, t = self.level(), self.level_time()
        wired = [s for s in self.sources() if soundedit.route_to(level, s, dest)]
        if not wired:
            return
        delta = db - float(curves.value(soundedit.route_to(level, wired[0], dest).get("gain", 0.0), t))
        if final:
            if len(wired) == 1:
                self.edit_target(wired[0], "送出量", soundedit.set_route_level, dest, db, None, t)
            else:
                self.edit_many(wired, "送出量", soundedit.nudge_route_level, dest, delta, t)
        else:
            self.live_many(wired, soundedit.nudge_route_level, dest, delta, t)

    def wire_each(self, sources, label, dest, gain=None, pre=None):
        def fn(level):
            for s in sources:
                soundedit.set_route_level(level, s, dest, gain, pre, self.level_time())
        self.win.apply(label, fn)

    def _level_master(self):
        """The master's strip ends where the others do (a scroll bar takes room under them)."""
        bar = self.strip_area.horizontalScrollBar()
        self.master_slot.setContentsMargins(3, 4, 3, BAND + (bar.sizeHint().height() if bar.maximum() > 0 else 0))
        QTimer.singleShot(0, self.wires.update)

    # -- order, colours, buses -----------------------------------------------------------------------
    def _drop_before(self, at):
        """(the strip id dragged ones would go before at global position at, the x of that place)."""
        strips = [(t, s) for t, s in self.strips.items() if t[0] != "master"]
        x = at.x()
        for t, s in strips:
            left = s.mapToGlobal(s.rect().topLeft()).x()
            if x < left + s.width() / 2:
                return t[1], self.wires.mapFromGlobal(s.mapToGlobal(s.rect().topLeft())).x() - 2
        last = strips[-1][1]
        return None, self.wires.mapFromGlobal(last.mapToGlobal(last.rect().topRight())).x() + 2

    def drag_strips(self, target, at):
        _, x = self._drop_before(at)
        self.wires.drop = x
        self.wires.update()

    def drop_strips(self, target, at):
        before, _ = self._drop_before(at)
        self.wires.drop = None
        self.wires.update()
        moving = [t[1] for t in (self.picked if target in self.picked else [target]) if t[0] != "master"]
        ids = [t[1] for t in self.strips if t[0] != "master"]
        trial = {"buses": [], "tracks": []}
        soundedit.move_strips(trial, ids, moving, before)
        if trial["mixer_order"] != ids:
            self.win.apply("調整混音台順序", soundedit.move_strips, ids, moving, before)

    def color_strips(self, targets, color):
        self.edit_many(targets, "混音台顏色", soundedit.set_color, color)

    def ask_color(self, targets):
        color = QColorDialog.getColor(QColor(self.strip_colour(targets[0])), self.win, "顏色")
        if color.isValid():
            self.color_strips(targets, color.name())

    def to_new_bus(self, targets):
        made = self.win.apply("改送到新的 bus", soundedit.to_new_bus, targets)
        if made:
            self.select(("bus", made))

    def remove_buses(self, ids):
        gone = {("bus", i) for i in ids}
        self.picked = [t for t in self.picked if t not in gone]
        if self.target in gone:
            self.target = self.picked[-1] if self.picked else None
        self.win.apply("刪除 bus", soundedit.remove_buses, ids)

    def target_name(self, target):
        if not target:
            return "選一個片段或混音台的一條"
        if target[0] == "master":
            return "Master 的效果"
        h = soundedit.holder(self.level(), target)
        kind = {"clip": "片段", "track": "軌道", "bus": "Bus"}[target[0]]
        more = len(self.picked) - 1 if target in self.picked else 0
        return f"{kind}：{h.get('name') or target[1]}" + (f"　（共選 {more + 1} 條）" if more else "")

    def _valid(self, target):
        if not target:
            return False
        try:
            soundedit.holder(self.level(), target)
        except edit.EditError:
            return False
        return True

    def select(self, target, effect_id=None):
        """Show target's chain; a strip: selected alone."""
        self.target = target
        self.picked = [target] if target and target[0] != "clip" else []
        if effect_id:
            self.folded.discard(effect_id)
        self.refresh()
        if effect_id and any(e["id"] == effect_id and e.get("effect") == soundfx.GRAPH
                             for e in soundedit.chain(self.level(), target)):
            self.open_graph(effect_id)

    # -- a 聲音節點效果 opened -------------------------------------------------------------------------
    def open_graph(self, effect_id):
        # (what it shows first: a refresh arriving while it is laid out must find it set)
        self.nodes.target, self.nodes.eid = self.target, effect_id
        if self.nodes.isHidden():
            self._narrow = self.hsplit.sizes()
            total = sum(self._narrow)
            self.hsplit.setSizes([total * 2 // 5, total - total * 2 // 5])
            self.nodes.show()
            tall = max(1, self.right.height())
            picture = 150 if self.picture.isVisibleTo(self) else 0
            self.right.setSizes([picture, (tall - picture) // 4, tall - picture - (tall - picture) // 4])
        self.nodes.eid = None
        self.nodes.open(self.target, effect_id)
        QTimer.singleShot(0, lambda: self.nodes.eid == effect_id and effect_id not in self.nodes.views
                          and self.nodes.view.show_all())           # (once it is laid out)

    def close_graph(self):
        if self.nodes.isHidden():
            return
        if self.enlarged:
            self.enlarge_graph()
        self.nodes.keep_view()
        self.nodes.eid = self.nodes.target = None
        self.nodes.hide()
        if self._narrow:
            self.hsplit.setSizes(self._narrow)

    def _cover(self):
        top = self.nodes_top()
        self.nodes.setGeometry(0, top, self.width(), self.height() - top)

    def nodes_top(self):
        return self.vsplit.y()

    def enlarge_graph(self):
        """The node graph over the whole page (below the transport), and back."""
        self.enlarged = not self.enlarged
        if self.enlarged:
            self.nodes.setParent(self)
            self._cover()
            self.nodes.show()
            self.nodes.raise_()
        else:
            self.right.addWidget(self.nodes)
            self.nodes.show()
        self.nodes.big_btn.setText("縮回" if self.enlarged else "放大")

    def clip_selected(self, clip):
        if not self.isVisible():
            return
        if clip is not None and soundedit.sounding(clip):
            self.select(("clip", clip["id"]))
        elif self.target and self.target[0] == "clip":
            self.select(None)

    def visible_params(self, effect):
        """The parameters of an effect that have a row now: of an equaliser those of the band
        picked (and the ones of no band), and only those that count with its settings."""
        spec = soundfx.EFFECTS.get(effect.get("effect"))
        if spec is None:
            return []
        values = soundfx.values(effect, self.time() or 0)
        band = self.bands.get(effect["id"], 1)
        return [p for p in spec["params"]
                if p.get("band") in (None, band) and ("when" not in p or p["when"](values))]

    def pick_band(self, effect_id, band):
        self.bands[effect_id] = band
        box = self.chain.boxes.get(effect_id)
        if box is not None and isinstance(box.visual, Response):
            box.visual.band = band
            box.visual.update()
        QTimer.singleShot(0, self.chain.refresh)        # (not while the curve that asked is being pressed)

    def fold(self, effect_id):
        self.folded ^= {effect_id}
        self.chain.refresh()

    # -- edits ------------------------------------------------------------------------------------------
    def edit_target(self, target, label, fn, *args, merge=None):
        """fn(level, target, *args) as one undo step."""
        return self.win.apply(label, fn, target, *args, merge=merge)

    def edit_many(self, targets, label, fn, *args, merge=None):
        """fn(level, targets, *args) as one undo step."""
        return self.win.apply(label, fn, list(targets), *args, merge=merge)

    def live_many(self, targets, fn, *args):
        self.live_target(list(targets), fn, *args)

    def edit(self, label, fn, *args, merge=None):
        """The same on the selected target."""
        if self.target:
            return self.edit_target(self.target, label, fn, *args, merge=merge)

    def live_target(self, target, fn, *args):
        """Hear fn's change without making it yet (a value being dragged)."""
        view = self.win.snapshot()
        try:
            fn(view, target, *args)
        except edit.EditError:
            return
        self.win.player.worker.set_view(view, self.win.cache_dir())

    def live(self, fn, *args):
        if self.target:
            self.live_target(self.target, fn, *args)

    def add_effect(self, kind, target=None):
        """Add an effect to target (the one shown) - and, one each, to the others selected with it."""
        target = target or self.target
        if not target:
            return
        targets = self.acting_on(target)
        if target not in self.picked:
            self.target, self.picked = target, [] if target[0] == "clip" else [target]
        else:
            self.target = target
        made = self.edit_many(targets, "新增聲音效果", soundedit.add_effects, kind)
        if made and kind == soundfx.GRAPH:
            self.refresh()
            self.open_graph(made[target])

    # -- presets of a whole chain (in the Library) -------------------------------------------------------
    def preset_menu(self, at):
        menu = Menu(self)
        root = self.win.ulib.root if self.win.ulib else self.win.library_root()
        saved = userlib.sound_presets(root)
        for name, path in saved:
            menu.addAction(name, lambda path=path: self.apply_preset(path))
        if saved:
            menu.addSeparator()
        save = menu.addAction("把這條效果鏈存成預設…", lambda: self.save_preset(root))
        save.setEnabled(bool(self.target and soundedit.chain(self.level(), self.target)))
        if saved:
            gone = menu.addMenu("刪除預設")
            for name, path in saved:
                gone.addAction(name, lambda name=name, path=path: self.delete_preset(name, path))
        menu.exec(at)

    def apply_preset(self, path):
        try:
            saved = userlib.load_sound_preset(path)
        except (OSError, ValueError) as exc:
            self.win.statusBar().showMessage(f"讀不了這個預設：{exc}", 6000)
            return
        if self.target:
            self.edit_many(self.acting_on(self.target), "套用聲音效果預設", soundedit.add_presets, saved)

    def save_preset(self, root, name=None):
        if name is None:
            name, ok = QInputDialog.getText(self.win, "存成預設", "名稱：")
            if not ok or not name.strip():
                return
        name = name.strip()
        try:
            if os.path.exists(userlib.sound_preset_path(root, name)) and QMessageBox.question(
                    self.win, "存成預設", f"已經有「{name}」，要取代它嗎？") != QMessageBox.Yes:
                return
            userlib.save_sound_preset(root, name, soundedit.preset_entries(soundedit.chain(self.level(), self.target)))
        except (OSError, ValueError) as exc:
            self.win.statusBar().showMessage(f"存不了預設：{exc}", 6000)

    def delete_preset(self, name, path):
        if QMessageBox.question(self.win, "刪除預設", f"刪除「{name}」？") == QMessageBox.Yes:
            try:
                os.remove(path)
            except OSError as exc:
                self.win.statusBar().showMessage(f"刪不掉：{exc}", 6000)

    def add_bus(self):
        self.win.apply("新增 bus", soundedit.add_bus)

    # -- showing ------------------------------------------------------------------------------------------
    def refresh(self):
        """After an edit, an undo, a level change or a new project."""
        if not self.isVisible():
            return
        if not self.win.proj:
            self.target, self.picked = None, []
            self.close_graph()
            self._build_strips([])
            self.chain.shape = None
            clear_layout(self.chain.list)
            self.chain.add.setEnabled(False)
            return
        level = self.level()
        self.picked = [t for t in self.picked if self._valid(t)]
        if not self._valid(self.target):
            self.target = self.picked[-1] if self.picked else None
        found = {t["id"]: ("track", t["id"]) for t in self.tracks()}
        found.update({b["id"]: ("bus", b["id"]) for b in soundedit.buses(level)})
        targets = [found[i] for i in soundedit.ordered(level, list(found))]
        self._build_strips(targets)
        for strip in self.strips.values():
            strip.show_channel(level)
        for strip in self.strips.values():                    # (after every strip knows its colour)
            strip.show_wire(level)
        self.wires.raise_()
        QTimer.singleShot(0, self.wires.update)               # (once the strips are where they will be)
        self.chain.refresh()
        if not self.nodes.isHidden() and (self.nodes.target != self.target or not self.nodes.refresh()):
            self.close_graph()
        self.show_time()

    def _build_strips(self, targets):
        shape = (tuple(targets), bool(self.win.proj), self.win.level_key() if self.win.proj else None)
        if shape == self._strip_shape:
            return
        self._strip_shape = shape
        clear_layout(self.strip_row)
        clear_layout(self.master_slot)
        self.strips = {}
        if not self.win.proj:
            return
        for t in targets:
            self.strips[t] = Strip(self, t)
            self.strip_row.addWidget(self.strips[t])
        add = QPushButton("＋\nBus")
        add.setFocusPolicy(Qt.NoFocus)
        add.setFixedSize(40, 60)
        add.setToolTip("新增一條 bus")
        add.clicked.connect(lambda: self.add_bus())
        self.strip_row.addWidget(add, 0, Qt.AlignTop)
        self.strip_row.addStretch()
        master = ("master", "")
        self.strips[master] = Strip(self, master)
        self.master_slot.addWidget(self.strips[master])

    def show_time(self):
        self.time_label.setText(self.win.time_lbl.text())

    def set_playing(self, playing):
        self.play_btn.setIcon(icons.icon("pause" if playing else "play"))

    def show_preview(self, on):
        self.picture.setVisible(on)
        self.win.settings().setValue("audio/preview", "true" if on else "false")
        if on and self.win.proj:
            self.win.seek(self.win.pos)

    def wants_picture(self):
        return self.isVisible() and self.picture.isVisible()

    def after_frame(self, img):
        """The player showed a frame."""
        self.show_time()
        if img is not None and self.wants_picture():
            self.picture.show_image(img)
        if not self.nodes.isHidden() and any(curves.is_animated(v) for n in self._graph_params() for v in n.values()):
            self.nodes.refresh()
        if self.target:
            level = self.level()
            if self._valid(self.target) and any(curves.is_animated(v) for e in soundedit.chain(level, self.target)
                                                for v in (e.get("params") or {}).values()):
                self.chain.refresh()                # (keyframed values follow the playhead)

    def _graph_params(self):
        try:
            return soundnodes.param_dicts(self.nodes.graph())
        except (edit.EditError, KeyError):
            return []

    def update_meters(self):
        player = getattr(self.win, "player", None)
        mixer = player.worker.mixer if player else None
        engine = mixer.engine if mixer is not None else None
        playing = bool(getattr(self.win, "playing", False))
        sample = int(self.win.playhead_us() * RATE / US) if self.win.proj else 0
        for (kind, ident), strip in self.strips.items():
            if engine is not None and playing:
                left, right = engine.level_at(ident or soundfx.MASTER, sample)
                if kind == "master":
                    left, right = left * mixer.master, right * mixer.master
                strip.bars.feed(left, right)
        n = Spectrum.N
        quiet = np.zeros(n, np.float32)
        self.spectrum.feed(engine.output_before(sample + n // 2, n) * mixer.master
                           if engine is not None and playing else quiet)
        drawn = self.chain.drawn()
        if not self.nodes.isHidden():
            drawn.update(self.nodes.drawn())
        if engine is not None:
            engine.watched = frozenset(i for i, w in drawn.items() if not isinstance(w, Dynamics))     # (what the next blocks keep)
        for effect_id, widget in drawn.items():
            if isinstance(widget, Dynamics):
                widget.feed_meters(engine.meters_at(effect_id, sample) if engine is not None and playing else None)
                continue
            widget.feed(engine.output_before(sample + n // 2, n, effect_id) if engine is not None and playing else quiet)
