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
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QInputDialog, QMessageBox, QScrollArea, QSlider, QSplitter, QVBoxLayout, QWidget)

from .. import curves, dsp, edit, project, rack, soundedit, soundfx, soundnodes, userlib
from . import icons, inplace, linkmark, sound_follow
from .sound_node_editor import SoundNodeEditor
from .sound_visuals import BAND_COLORS, Dynamics, Response, Spectrum
from .inspector import SpinBox
from .menukeys import Menu
from .meter import FADER_HI, FADER_LO, Bars, Fader, to_db

US = 1_000_000
RATE = 48000
STRIP_W = 104
KIND_COLOR = {"track": "#3f8a5a", "bus": "#3f6fa8", "master": "#a8473f", "clip": "#b3702f"}
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
        self.name = QPushButton("")
        self.name.setFocusPolicy(Qt.NoFocus)
        self.name.clicked.connect(lambda: page.select(target))
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
        self.output = self.pan = None
        self.send_spins = {}
        if self.kind != "master":
            sends = QWidget()
            self.sends = QVBoxLayout(sends)
            self.sends.setContentsMargins(0, 0, 0, 0)
            self.sends.setSpacing(1)
            lay.addWidget(sends)
            self.output = QPushButton("")
            self.output.setFocusPolicy(Qt.NoFocus)
            self.output.setToolTip("輸出到哪裡")
            self.output.clicked.connect(self.output_menu)
            lay.addWidget(self.output)
            self.pan = SpinBox()
            self.pan.setDecimals(0)
            self.pan.set_limits(-100, 100, -100, 100)
            self.pan.setPrefix("聲像 ")
            self.pan.edited.connect(lambda v: page.edit_target(target, "聲像", soundedit.set_pan, v / 100,
                                                               merge=("pan", self.channel)))
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
                b.clicked.connect(lambda on, flag=flag, label=label: page.edit_target(
                    target, label if on else "取消" + label, soundedit.set_flag, flag, on))
                row.addWidget(b)
            lay.addLayout(row)

    # -- the fader ------------------------------------------------------------------------------------
    def fader_moved(self, v):
        db = v / 10
        self.db.setText(db_text(db) + " dB")
        if self.kind == "master":
            self.page.win.on_master(db_lin(db), not self.fader.isSliderDown())
        elif self.fader.isSliderDown():
            self.page.live_target(self.target, soundedit.set_gain, db_lin(db))
        else:
            self.fader_done()

    def fader_done(self):
        db = self.fader.value() / 10
        if self.kind == "master":
            self.page.win.on_master(db_lin(db), True)
        else:
            self.page.edit_target(self.target, "音量", soundedit.set_gain, db_lin(db), merge=("fader", self.channel))

    # -- menus ----------------------------------------------------------------------------------------
    def name_menu(self, at):
        menu = Menu(self)
        if self.kind == "bus":
            menu.addAction("重新命名…", self.rename)
            menu.addAction("刪除 bus", lambda: self.page.remove_bus(self.target[1]))
        if self.kind != "master":
            menu.addAction("新增傳送…", lambda: self.send_menu())
        if not menu.isEmpty():
            menu.exec(self.name.mapToGlobal(at))

    def rename(self):
        old = self.name.text()
        name, ok = inplace.ask_name(self, old, (self.name, self.name.rect()))
        if ok and name.strip() and name != old:
            self.page.win.apply("重新命名 bus", soundedit.rename_bus, self.target[1], name)

    def output_menu(self):
        level = self.page.level()
        now = soundedit.holder(level, self.target).get("output")
        menu = Menu(self)
        for ident, label in [(None, "Master")] + [(b["id"], b.get("name") or b["id"])
                                                 for b in soundedit.destinations(level, self.target)]:
            a = menu.addAction(label, lambda ident=ident: self.page.edit_target(
                self.target, "輸出目的地", soundedit.set_output, ident))
            a.setCheckable(True)
            a.setChecked(ident == now)
        menu.addSeparator()
        menu.addAction("新增 bus 並接過去", lambda: self.page.add_bus(self.target))
        menu.exec(self.output.mapToGlobal(self.output.rect().bottomLeft()))

    def send_menu(self):
        level = self.page.level()
        there = {s["bus"] for s in soundedit.holder(level, self.target).get("sends") or ()}
        menu = Menu(self)
        for b in soundedit.destinations(level, self.target):
            if b["id"] not in there:
                menu.addAction(b.get("name") or b["id"], lambda ident=b["id"]: self.page.edit_target(
                    self.target, "新增傳送", soundedit.add_send, ident))
        if menu.isEmpty():
            menu.addAction("（沒有可以傳送的 bus）").setEnabled(False)
        menu.exec(self.name.mapToGlobal(self.name.rect().bottomLeft()))

    def one_send_menu(self, widget, at, send):
        menu = Menu(self)
        a = menu.addAction("推桿前傳送", lambda: self.page.edit_target(
            self.target, "傳送位置", soundedit.set_send, send["bus"], None, not send.get("pre")))
        a.setCheckable(True)
        a.setChecked(bool(send.get("pre")))
        menu.addAction("移除傳送", lambda: self.page.edit_target(self.target, "移除傳送", soundedit.remove_send, send["bus"]))
        menu.exec(widget.mapToGlobal(at))

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
        selected = self.page.target == self.target
        self.name.setStyleSheet(f"QPushButton {{ background: {KIND_COLOR[self.kind]}; color: #ffffff; padding: 3px; "
                                f"border: 2px solid {'#ffffff' if selected else 'transparent'}; }}")
        chain = holder.get("sound_effects") or []
        names = {b["id"]: b.get("name") or b["id"] for b in soundedit.buses(level)}
        sends = holder.get("sends") or []
        shape = (tuple((e["id"], e.get("effect"), e.get("enabled", True)) for e in chain),
                 tuple((s["bus"], names.get(s["bus"]), bool(s.get("pre"))) for s in sends))
        if shape != self.shape:
            self.shape = shape
            self.build_slots(chain)
            if self.kind != "master":
                self.build_sends(sends, names)
        if self.kind != "master":
            self.output.setText("→ " + names.get(holder.get("output"), "Master"))
            if not self.pan.editing:
                self.pan.show_value(curves.value(holder.get("pan", 0.0), 0) * 100)
            self.mute.setChecked(bool(holder.get("muted")))
            self.solo.setChecked(bool(holder.get("solo")))
            for s in sends:
                spin = self.send_spins.get(s["bus"])
                if spin is not None and not spin.editing:
                    spin.show_value(curves.value(s.get("gain", 0.0), self.page.level_time()))
        if not self.fader.isSliderDown():
            gain = (self.page.win.proj.get("master_gain", 1.0) if self.kind == "master" else holder.get("gain", 1.0))
            db = lin_db(gain)
            self.fader.blockSignals(True)
            self.fader.setValue(round(db * 10))
            self.fader.blockSignals(False)
            self.db.setText(db_text(db) + " dB")

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

    def build_sends(self, sends, names):
        clear_layout(self.sends)
        self.send_spins = {}
        for s in sends:
            spin = SpinBox()
            spin.setDecimals(1)
            spin.set_limits(soundfx.SEND_OFF_DB, 12.0, soundfx.SEND_OFF_DB, 12.0)
            spin.setPrefix(f"{(names.get(s['bus']) or '?')[:6]}{'（前）' if s.get('pre') else ''} ")
            spin.setToolTip(f"傳送到 {names.get(s['bus'])}（dB；-60 是不送）。右鍵：推桿前傳送、移除")
            spin.edited.connect(lambda v, bus=s["bus"]: self.page.edit_target(
                self.target, "傳送量", soundedit.set_send, bus, v, None, self.page.level_time(),
                merge=("send", self.channel, bus)))
            spin.lineEdit().setContextMenuPolicy(Qt.CustomContextMenu)
            spin.lineEdit().customContextMenuRequested.connect(
                lambda at, w=spin.lineEdit(), s=dict(s): self.one_send_menu(w, at, s))
            self.send_spins[s["bus"]] = spin
            self.sends.addWidget(spin)
        add = small_button("＋傳送", "把聲音另外送一份到某個 bus", width=0)
        add.clicked.connect(self.send_menu)
        self.sends.addWidget(add)


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
            from PySide6.QtGui import QPixmap
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

        mixer = QWidget()
        row = QHBoxLayout(mixer)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        strips = QWidget()
        self.strip_row = QHBoxLayout(strips)
        self.strip_row.setContentsMargins(4, 4, 4, 4)
        self.strip_row.setSpacing(3)
        self.strip_row.setAlignment(Qt.AlignLeft)
        self.strip_area = QScrollArea()
        self.strip_area.setWidget(strips)
        self.strip_area.setWidgetResizable(True)
        row.addWidget(self.strip_area, 1)
        self.master_slot = QHBoxLayout()
        self.master_slot.setContentsMargins(3, 4, 3, 4)
        row.addLayout(self.master_slot)
        self.spectrum = Spectrum()
        row.addWidget(self.spectrum)
        mixer.setMinimumHeight(330)
        self.vsplit.addWidget(mixer)
        self.vsplit.setStretchFactor(0, 1)
        self.vsplit.setSizes([460, 400])
        lay.addWidget(self.vsplit, 1)
        self.setStyleSheet("QWidget#audiopage { background: #0d0d0d; } QFrame#strip { background: #161618; }")
        for key, split in (("audio/vsplit", self.vsplit), ("audio/hsplit", self.hsplit), ("audio/right", self.right)):
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
            self.target = ("clip", clip["id"])
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
        sounding = lambda t: t["kind"] == "audio" or any(soundedit.sounding(c) for c in t["clips"]) or soundfx.routed(t)
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

    def target_name(self, target):
        if not target:
            return "選一個片段或混音台的一條"
        if target[0] == "master":
            return "Master 的效果"
        h = soundedit.holder(self.level(), target)
        kind = {"clip": "片段", "track": "軌道", "bus": "Bus"}[target[0]]
        return f"{kind}：{h.get('name') or target[1]}"

    def _valid(self, target):
        if not target:
            return False
        try:
            soundedit.holder(self.level(), target)
        except edit.EditError:
            return False
        return True

    def select(self, target, effect_id=None):
        self.target = target
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
        target = target or self.target
        if not target:
            return
        self.target = target
        made = self.edit_target(target, "新增聲音效果", soundedit.add_effect, kind)
        if made and kind == soundfx.GRAPH:
            self.refresh()
            self.open_graph(made)

    def add_bus(self, route_from=None):
        def fn(level):
            ident = soundedit.add_bus(level)
            if route_from:
                soundedit.set_output(level, route_from, ident)
            return ident
        self.win.apply("新增 bus", fn)

    def remove_bus(self, bus_id):
        if self.target == ("bus", bus_id):
            self.target = None
        self.win.apply("刪除 bus", soundedit.remove_bus, bus_id)

    # -- showing ------------------------------------------------------------------------------------------
    def refresh(self):
        """After an edit, an undo, a level change or a new project."""
        if not self.isVisible():
            return
        if not self.win.proj:
            self.target = None
            self.close_graph()
            self._build_strips([])
            self.chain.shape = None
            clear_layout(self.chain.list)
            self.chain.add.setEnabled(False)
            return
        level = self.level()
        if not self._valid(self.target):
            self.target = None
        targets = [("track", t["id"]) for t in self.tracks()] + [("bus", b["id"]) for b in soundedit.buses(level)]
        self._build_strips(targets)
        for strip in self.strips.values():
            strip.show_channel(level)
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
