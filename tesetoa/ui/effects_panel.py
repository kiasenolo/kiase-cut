"""Effects: the filters on the selected clip (or the filter of a filter clip).

Each effect has its switch, name, order buttons, its parameters (every number can be
keyframed with ◆, like the clip's own) and an optional mask that limits where it works.
The parameters come from the filter file's `// @param` lines (see filters/FORMAT.md), so
the form of a user's filter is built the same way as a built-in one.
"""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton,
                               QToolButton, QVBoxLayout, QWidget)

from .. import curves, edit, fx
from .inspector import MASK_NAMES, PARAMS, ComboBox, Inspector, SpinBox, section

DEBOUNCE_MS = 350


def step_for(p):
    span = p.hi - p.lo
    if p.type == "int":
        return 1.0
    return 0.01 if span <= 10 else 0.1 if span <= 100 else 1.0


class EffectsPanel(QWidget):
    addRequested = Signal(str, str)                 # clip id, filter ref
    browseRequested = Signal(str)                   # clip id: pick a filter file
    removeRequested = Signal(str, str)              # clip id, effect id
    enabledChosen = Signal(str, str, bool)
    moveRequested = Signal(str, str, int)           # clip id, effect id, -1 / +1
    maskKindChosen = Signal(str, str, object)       # clip id, effect id, kind or None
    maskInvertChosen = Signal(str, str, bool)
    paramEdited = Signal(list, str, str, object)    # clip ids, group, key, value
    keyToggled = Signal(list, str, str)
    liveEdited = Signal(list, str, str, object)
    docRequested = Signal()
    revealFilter = Signal(str)                      # filter ref: show its file

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.user_filters = []                      # [(name, path)] from the user's Library
        self.clip_id = None
        self.shape = None
        self.widgets = {}
        self.pending = {}
        self.timer = QTimer(self, singleShot=True, interval=DEBOUNCE_MS)
        self.timer.timeout.connect(self._flush)
        lay = QVBoxLayout(self)
        lay.addWidget(section("效果"))
        bar = QHBoxLayout()
        self.add_btn = QToolButton()
        self.add_btn.setText("＋ 新增效果")
        self.add_btn.setPopupMode(QToolButton.InstantPopup)
        self.add_btn.setMenu(QMenu(self.add_btn))
        self.add_btn.menu().aboutToShow.connect(self._fill_menu)
        doc = QPushButton("濾鏡寫法說明")
        doc.setToolTip("自己用 GLSL 寫濾鏡的格式、參數與範例")
        doc.clicked.connect(self.docRequested)
        bar.addWidget(self.add_btn)
        bar.addStretch(1)
        bar.addWidget(doc)
        lay.addLayout(bar)
        self.body = QWidget()
        lay.addWidget(self.body)
        lay.addStretch(1)
        self._build(None)

    # -- the menu of filters ----------------------------------------------------------------------
    def set_user_filters(self, filters):
        self.user_filters = list(filters)

    def _fill_menu(self):
        menu = self.add_btn.menu()
        menu.clear()
        cats = {}
        for ref in fx.builtin_refs():
            d = fx.get(ref)
            cats.setdefault(d.category or "其他", []).append((d.name, ref))
        for cat, items in cats.items():
            sub = menu.addMenu(cat)
            for name, ref in items:
                sub.addAction(name, lambda _=False, ref=ref: self._add(ref))
        menu.addSeparator()
        mine = menu.addMenu("我的濾鏡（Library）")
        for name, path in self.user_filters:
            mine.addAction(name, lambda _=False, path=path: self._add(path))
        if not self.user_filters:
            mine.addAction("（Library 的「濾鏡」分頁還沒有檔案）").setEnabled(False)
        menu.addAction("選擇濾鏡檔案…", lambda: self.clip_id and self.browseRequested.emit(self.clip_id))

    def _add(self, ref):
        if self.clip_id:
            self.add_btn.menu().hide()
            self.addRequested.emit(self.clip_id, ref)

    # -- the form ---------------------------------------------------------------------------------
    def _build(self, c):
        old = self.body
        self.body = QWidget()
        self.layout().replaceWidget(old, self.body)
        old.hide()
        old.deleteLater()
        self.widgets = {}
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(0, 0, 0, 0)
        self.add_btn.setEnabled(c is not None and c["type"] in edit.VISUAL)
        if c is None:
            lay.addWidget(self._note("在時間軸上選一個片段（只選一個）"))
            return
        if c["type"] not in edit.VISUAL:
            lay.addWidget(self._note("聲音片段不能加濾鏡"))
            return
        effects = c.get("effects") or []
        if not effects:
            lay.addWidget(self._note("沒有效果。按「新增效果」加一個；\n"
                                     "也可以在 Library 的「濾鏡」頁雙擊，放成獨立的濾鏡片段，"
                                     "它會作用在下面所有的軌道。" if c["type"] != "filter"
                                     else "這個濾鏡片段沒有效果了，按「新增效果」加一個。"))
        for i, e in enumerate(effects):
            lay.addWidget(self._effect_box(c, e, i, len(effects)))

    @staticmethod
    def _note(text):
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setStyleSheet("color: #9a9aa0;")
        return lab

    def _effect_box(self, c, e, index, count):
        d = fx.get(e["filter"])
        box = QFrame()
        box.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(box)
        head = QHBoxLayout()
        on = QCheckBox(d.name)
        on.setChecked(not e.get("disabled"))
        on.setToolTip(d.description or "開／關這個效果")
        on.toggled.connect(lambda v, eid=e["id"]: self._now(self.enabledChosen, eid, v))
        head.addWidget(on, 1)
        for text, tip, fn in (("↑", "往前（先套用）", lambda _=False, eid=e["id"]: self._now(self.moveRequested, eid, -1)),
                              ("↓", "往後", lambda _=False, eid=e["id"]: self._now(self.moveRequested, eid, 1)),
                              ("✕", "移除這個效果", lambda _=False, eid=e["id"]: self._now(self.removeRequested, eid))):
            b = QPushButton(text)
            b.setFixedWidth(28)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            head.addWidget(b)
        b_up, b_down = head.itemAt(1).widget(), head.itemAt(2).widget()
        b_up.setEnabled(index > 0)
        b_down.setEnabled(index < count - 1)
        lay.addLayout(head)
        if d.error:
            err = QLabel("⚠ " + d.error)
            err.setWordWrap(True)
            err.setStyleSheet("color: #e0605a;")
            lay.addWidget(err)
        if not e["filter"].startswith(fx.BUILTIN):
            where = QPushButton("在檔案總管中顯示濾鏡檔")
            where.clicked.connect(lambda _=False, ref=e["filter"]: self.revealFilter.emit(ref))
            lay.addWidget(where)
        group = "fx:" + e["id"]
        for p in d.params:
            lay.addLayout(self._param_row(group, p))
        # where the effect works
        row = QHBoxLayout()
        row.addWidget(QLabel("範圍"))
        kind = ComboBox()
        kind.addItem("整個畫面", None)
        for name, k in MASK_NAMES:
            if k is not None:
                kind.addItem(name + "遮罩", k)
        kind.setCurrentIndex(max(0, kind.findData((e.get("mask") or {}).get("kind"))))
        kind.activated.connect(lambda i, eid=e["id"], cb=kind: self._now(self.maskKindChosen, eid, cb.itemData(i)))
        row.addWidget(kind, 1)
        lay.addLayout(row)
        if e.get("mask"):
            inv = QCheckBox("反轉（效果作用在遮罩之外）")
            inv.setChecked(bool(e["mask"].get("invert")))
            inv.toggled.connect(lambda v, eid=e["id"]: self._now(self.maskInvertChosen, eid, v))
            lay.addWidget(inv)
            mgroup = "fxmask:" + e["id"]
            for r in PARAMS["mask"]:
                if e["mask"]["kind"] == "line" and r[0] in ("w", "h"):
                    continue
                lay.addLayout(self._number_row(mgroup, r[0], r[1], r[2], r[3], r[4], r[5], r[6]))
        return box

    def _number_row(self, group, key, label, lo, hi, step, dec, factor):
        row = QHBoxLayout()
        lab = QLabel(label)
        lab.setMinimumWidth(70)
        row.addWidget(lab)
        s = SpinBox()
        s.setRange(lo, hi)
        s.setSingleStep(step)
        s.setDecimals(dec)
        s.setKeyboardTracking(False)
        s.edited.connect(lambda v, g=group, k=key, f=factor: self._queue(g, k, v / f))
        self.widgets[(group, key)] = s
        row.addWidget(s, 1)
        row.addWidget(self._key_button(group, key))
        return row

    def _key_button(self, group, key):
        b = QPushButton("◇")
        b.setFixedWidth(26)
        b.setToolTip("在播放頭新增／刪除關鍵幀")
        b.clicked.connect(lambda: self._now(self.keyToggled, group, key))
        self.widgets[("key", group, key)] = b
        return b

    def _param_row(self, group, p):
        if p.type in ("float", "int"):
            dec = 0 if p.type == "int" else 2 if (p.hi - p.lo) <= 100 else 1
            return self._number_row(group, p.name, p.label, p.lo, p.hi, step_for(p), dec, 1)
        row = QHBoxLayout()
        lab = QLabel(p.label)
        lab.setMinimumWidth(70)
        row.addWidget(lab)
        if p.type == "bool":
            cb = QCheckBox()
            cb.toggled.connect(lambda v, g=group, k=p.name: (self._queue(g, k, 1.0 if v else 0.0), self._flush()))
            self.widgets[(group, p.name)] = cb
            row.addWidget(cb, 1)
        elif p.type == "color":
            btn = QPushButton()
            btn.clicked.connect(lambda _=False, g=group, k=p.name: self._pick_color(g, k))
            self.widgets[(group, p.name)] = btn
            row.addWidget(btn, 1)
            row.addWidget(self._key_button(group, p.name))
        else:                                                   # vec2
            sx, sy = SpinBox(), SpinBox()
            for s in (sx, sy):
                s.setRange(p.lo, p.hi)
                s.setSingleStep(step_for(p))
                s.setDecimals(3)
                s.setKeyboardTracking(False)
            sx.edited.connect(lambda v, g=group, k=p.name: self._queue_vec(g, k, 0, v))
            sy.edited.connect(lambda v, g=group, k=p.name: self._queue_vec(g, k, 1, v))
            self.widgets[(group, p.name, 0)], self.widgets[(group, p.name, 1)] = sx, sy
            row.addWidget(sx, 1)
            row.addWidget(sy, 1)
            row.addWidget(self._key_button(group, p.name))
        return row

    # -- showing values ---------------------------------------------------------------------------
    def show_clips(self, clips, t_us, fps):
        c = clips[0] if len(clips) == 1 else None
        shape = None
        if c is not None:
            shape = (c["id"], c["type"], tuple((e["id"], e["filter"], bool(e.get("disabled")),
                                                (e.get("mask") or {}).get("kind"), fx.get(e["filter"]).key(),
                                                fx.get(e["filter"]).error) for e in c.get("effects") or []))
        if shape != self.shape:
            self._flush()
            self.shape = shape
            self.clip_id = c["id"] if c else None
            self._build(c)
        if c is None or c["type"] not in edit.VISUAL:
            return
        t = t_us - c["start_us"]
        w = self.widgets
        for e in c.get("effects") or []:
            d = fx.get(e["filter"])
            group = "fx:" + e["id"]
            for p in d.params:
                stored = e["params"].get(p.name, p.default)
                v = curves.value(stored, t)
                self._show(group, p, v)
                kb = w.get(("key", group, p.name))
                if kb is not None:
                    Inspector._key_state(kb, [stored], [c], [t])
            if e.get("mask"):
                mgroup = "fxmask:" + e["id"]
                for r in PARAMS["mask"]:
                    s = w.get((mgroup, r[0]))
                    if s is None:
                        continue
                    stored = e["mask"].get(r[0], r[7])
                    if not (s.hasFocus() and (mgroup, r[0]) in self.pending):
                        s.show_value(round(curves.value(stored, t) * r[6], r[5]))
                    Inspector._key_state(w[("key", mgroup, r[0])], [stored], [c], [t])

    def _show(self, group, p, v):
        w = self.widgets
        if p.type in ("float", "int"):
            s = w.get((group, p.name))
            if s is not None and not (s.hasFocus() and (group, p.name) in self.pending):
                s.show_value(round(float(v), 0 if p.type == "int" else 3))
        elif p.type == "bool":
            cb = w.get((group, p.name))
            if cb is not None:
                cb.blockSignals(True)
                cb.setChecked(bool(round(float(v))))
                cb.blockSignals(False)
        elif p.type == "color":
            btn = w.get((group, p.name))
            if btn is not None:
                r, g, b = (int(round(min(1, max(0, x)) * 255)) for x in list(v)[:3])
                btn.setText(f"#{r:02x}{g:02x}{b:02x}")
                btn.setStyleSheet(f"background: rgb({r},{g},{b}); color: {'#000' if r + g + b > 380 else '#fff'};")
        else:
            for i in (0, 1):
                s = w.get((group, p.name, i))
                if s is not None and not s.hasFocus():
                    s.show_value(round(float(v[i]), 3))

    # -- edits ------------------------------------------------------------------------------------
    def _queue(self, group, key, value):
        self.pending[(group, key)] = value
        self.timer.start()
        if self.clip_id:
            self.liveEdited.emit([self.clip_id], group, key, value)

    def _queue_vec(self, group, key, index, value):
        cur = self.pending.get((group, key))
        if cur is None:
            cur = [self.widgets[(group, key, i)].value() for i in (0, 1)]
        cur = list(cur)
        cur[index] = value
        self._queue(group, key, cur)

    def _pick_color(self, group, key):
        btn = self.widgets[(group, key)]
        col = QColorDialog.getColor(QColor(btn.text()), self, "顏色")
        if col.isValid():
            self._queue(group, key, [col.redF(), col.greenF(), col.blueF(), 1.0])
            self._flush()

    def _now(self, signal, *args):
        self._flush()
        if self.clip_id:
            if signal in (self.keyToggled,):
                signal.emit([self.clip_id], *args)
            else:
                signal.emit(self.clip_id, *args)

    def _flush(self):
        self.timer.stop()
        if not self.pending or not self.clip_id:
            self.pending.clear()
            return
        pending, self.pending = self.pending, {}
        for (g, k), v in pending.items():
            self.paramEdited.emit([self.clip_id], g, k, v)
