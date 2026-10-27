"""Effects: the filters on the selected clip (or the filter of a filter clip).
With several clips selected (批量) the picture ones are edited together: when their effects are
the same filters in the same order the form is the main clip's and every change goes to all of
them (a value they do not share shows as --); when not, only 新增效果 is offered, and it (or a
filter dropped in the panel) replaces all their effects with the new one.

Each effect has its switch, name, order buttons, its 混合程度 (how much of its result shows over
the picture it was given, 0 - 100 %), its parameters (every value can be
keyframed with ◆, like the clip's own; on / off, menus and shapes hold until their next keyframe)
and an optional mask that limits where it works. Its ⠿ grip drags it: to another place in the
list, or onto a clip (timeline, layers) to copy it there with its settings, or onto an empty spot
of the timeline for a filter clip of it; filters of the VFX tab can be dropped in the list too.
Dropped onto an effect with Alt held, a filter (or an effect) takes that effect's place instead,
keeping its values when the parameters line up (edit.swap_filter): a filter whose file is gone
swapped for its built-in version, say.
The parameters come from the filter file's `// @param` lines (see filters/FORMAT.md), so
the form of a user's filter is built the same way as a built-in one.

Selecting other clips whose effects make the same form keeps the form: its widgets are keyed by
the shown clip's effect ids again, and what its buttons hold (the ids of the clip it was built
for) is put through _real on its way in.
"""
import json

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDrag
from PySide6.QtWidgets import (QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton,
                               QToolButton, QVBoxLayout, QWidget)

from .. import curves, edit, fx
from .colorpick import pick_color, qcolor, rgba
from .inspector import (MASK_NAMES, PARAMS, ComboBox, Inspector, SpinBox, hard_limits, key_button, kind_tag,
                        section)
from .vfx_panel import FX_MIME, effect_mime

DEBOUNCE_MS = 350


def step_for(p):
    span = p.hi - p.lo
    if p.type == "int":
        return 1.0
    return 0.01 if span <= 10 else 0.1 if span <= 100 else 1.0


MIXED = object()                                # the clips' values are not the same


def alike(values):
    """The value every clip has (numbers within a hair), else MIXED."""
    def same(a, b):
        if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
            return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return abs(a - b) < 1e-9
        return a == b
    return values[0] if all(same(values[0], v) for v in values[1:]) else MIXED


def set_checks(cb, states):
    """A checkbox showing states of several clips: half checked when they are not the same
    (a click then turns them all on)."""
    mixed = len(set(states)) > 1
    cb.setTristate(mixed)
    cb.setCheckState(Qt.PartiallyChecked if mixed else Qt.Checked if states and states[0] else Qt.Unchecked)


class Grip(QLabel):
    """⠿ on an effect's title row: drags what mime() gives (the effect, its box as the picture)."""

    def __init__(self, mime):
        super().__init__("⠿")
        self.mime = mime
        self.press = None
        self.setCursor(Qt.OpenHandCursor)
        self.setStyleSheet("font-size: 16px; padding: 0 2px; color: #9a9aa0;")
        self.setToolTip("拖曳：在清單裡調整順序；拖到時間軸或圖層上的片段＝把這個效果（連同設定）複製過去；"
                        "拖到時間軸的空白處＝做成濾鏡片段")

    def mousePressEvent(self, e):
        self.press = e.position().toPoint() if e.button() == Qt.LeftButton else None

    def mouseReleaseEvent(self, e):
        self.press = None

    def mouseMoveEvent(self, e):
        if self.press is None or (e.position().toPoint() - self.press).manhattanLength() < QApplication.startDragDistance():
            return
        self.press = None
        md = self.mime()
        if md is None:
            return
        drag = QDrag(self)
        drag.setMimeData(md)
        pic = self.parentWidget().grab()
        if pic.height() > 60:
            pic = pic.copy(0, 0, pic.width(), 40)
        drag.setPixmap(pic)
        drag.setHotSpot(self.mapTo(self.parentWidget(), e.position().toPoint()))
        drag.exec(Qt.CopyAction | Qt.MoveAction, Qt.CopyAction)


class EffectsPanel(QWidget):
    addRequested = Signal(list, str)                # clip ids, filter ref
    browseRequested = Signal(list)                  # clip ids: pick a filter file
    # the effect edits name the clips they apply to and the main clip's effect id (the others'
    # are the same filter at the same place)
    removeRequested = Signal(list, str)             # clip ids, effect id
    enabledChosen = Signal(list, str, bool)
    moveRequested = Signal(list, str, int)          # clip ids, effect id, -1 / +1
    maskKindChosen = Signal(list, str, object)      # clip ids, effect id, kind or None
    maskInvertChosen = Signal(list, str, bool)
    maskEditChanged = Signal()                      # 編輯遮罩 switched: self.mask_edit
    paramEdited = Signal(list, str, str, object)    # clip ids, group, key, value
    keyToggled = Signal(list, str, str)
    liveEdited = Signal(list, str, str, object)
    liveCancelled = Signal()                 # a colour being picked was given up: show what is there
    backdropChosen = Signal(list, object, object)   # clip ids, 套用至背景 (or None), 隱藏本體 (or None)
    docRequested = Signal()
    revealFilter = Signal(str)                      # filter ref: show its file
    effectDropped = Signal(list, str, int)          # clip ids, what FX_MIME carries, place in the chain
    effectsDropped = Signal(list, str)              # clip ids whose effects are not alike, what FX_MIME carries
    effectSwapped = Signal(list, str, str)          # clip ids, effect id, what FX_MIME carries (Alt-drop on it)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.user_filters = []                      # [(name, path)] from the user's Library
        self.clip_id = None
        self.clip = None                            # the main clip of the form as last shown (what a drag copies)
        self.clips = []                             # the clips the form edits, the main one first
        self.ids = []                               # the picture clips of the selection
        self.boxes = []                             # the effects' boxes, in order
        self.mask_edit = None                       # effect id whose mask the preview edits (編輯遮罩)
        self.shape = None
        self.built = []                             # the effect ids the form was built with
        self.alias = {}                             # those -> the shown clip's effect ids
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
        self.drop_line = QFrame(self)               # where a dragged effect would go
        self.drop_line.setStyleSheet("background: #6fb3ff;")
        self.drop_line.setFixedHeight(3)
        self.drop_line.hide()
        self.swap_frame = QFrame(self)              # the effect an Alt-drop would replace
        self.swap_frame.setStyleSheet("border: 2px solid #6fb3ff; background: transparent;")
        self.swap_frame.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.swap_frame.hide()
        self.setAcceptDrops(True)
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
        menu.addAction("選擇濾鏡檔案…", lambda: self.targets() and self.browseRequested.emit(self.targets()))

    def targets(self):
        """The clips 新增效果 adds to: each picture clip of the selection."""
        return list(self.ids)

    def _add(self, ref):
        if self.targets():
            self.add_btn.menu().hide()
            self.addRequested.emit(self.targets(), ref)

    # -- the form ---------------------------------------------------------------------------------
    def _build(self, c, count=0):
        """The form of main clip c (and self.clips alike, 批量) of a selection of count clips;
        None: no form, just a note."""
        old = self.body
        self.body = QWidget()
        self.layout().replaceWidget(old, self.body)
        old.hide()
        old.deleteLater()
        self.widgets = {}
        self.boxes = []
        self.built = [e["id"] for e in (c.get("effects") or [])] if c else []
        self.alias = {}
        self.many_note = None
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(0, 0, 0, 0)
        self.add_btn.setEnabled(bool(self.ids))
        n = len(self.ids)
        if not count:
            lay.addWidget(self._note("在時間軸上選一個片段"))
            return
        if not n:
            lay.addWidget(self._note("聲音片段不能加濾鏡" if count == 1 else "選取的都是聲音片段，不能加濾鏡"))
            return
        if c is None:
            lay.addWidget(self._note(f"選了 {count} 個片段，它們的效果（或順序）不一樣：按「新增效果」或把濾鏡拖到這裡，"
                                     f"會清掉這 {n} 個畫面片段原本的效果，只留新加的這一個。"))
            return
        if count > 1:
            self.many_note = self._note("")
            self._many_text(count)
            lay.addWidget(self.many_note)
        effects = c.get("effects") or []
        if effects and fx.missing():
            err = QLabel("⚠ " + fx.missing())
            err.setWordWrap(True)
            err.setTextInteractionFlags(Qt.TextSelectableByMouse)
            err.setStyleSheet("color: #e0605a;")
            lay.addWidget(err)
        if not effects:
            lay.addWidget(self._note("沒有效果。按「新增效果」加一個；\n"
                                     "也可以在 Library 的「濾鏡」頁雙擊，放成獨立的濾鏡片段，"
                                     "它會作用在下面所有的軌道。" if c["type"] != "filter"
                                     else "這個濾鏡片段沒有效果了，按「新增效果」加一個。"))
        if effects and any(k["type"] != "filter" for k in self.clips):
            lay.addWidget(self._backdrop_row())
        for i, e in enumerate(effects):
            box = self._effect_box(c, e, i, len(effects))
            self.boxes.append(box)
            lay.addWidget(box)

    def _many_text(self, count):
        n = len(self.ids)
        self.many_note.setText(f"一起調整 {n} 個片段的效果" + ("（聲音片段除外）" if n < count else "")
                               + "；各片段不一樣的數值顯示為 --")

    def _backdrop_row(self):
        """套用至背景 and 隱藏本體 (a built-in asset's choice; any other clip hides itself)."""
        clips = [k for k in self.clips if k["type"] != "filter"]
        bs = [k.get("backdrop") or {} for k in clips]
        own = all(k.get("asset") for k in clips)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 4)
        on = QCheckBox("套用至背景")
        set_checks(on, [bool(b.get("on")) for b in bs])
        on.setToolTip("效果作用在片段下面的畫面上（只在片段的形狀範圍內），像毛玻璃；不一定要用模糊")
        on.clicked.connect(lambda _=False: self._now(self.backdropChosen, on.checkState() == Qt.Checked, None))
        rl.addWidget(on)
        hide = QCheckBox("隱藏本體")
        set_checks(hide, [bool(b.get("hide")) or not k.get("asset") for b, k in zip(bs, clips)])
        hide.setEnabled(own and all(b.get("on") for b in bs))
        hide.setToolTip("不畫出片段本身，只留下背景的效果" if own else "圖片、影片、文字和複合片段套用至背景時一定會隱藏本體")
        hide.clicked.connect(lambda _=False: self._now(self.backdropChosen, None, hide.checkState() == Qt.Checked))
        rl.addWidget(hide)
        rl.addStretch(1)
        self.widgets["backdrop"] = (on, hide)
        return row

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
        head.addWidget(Grip(lambda eid=e["id"]: self._drag_mime(eid)))
        es = [k["effects"][index] for k in self.clips]           # this effect of each clip
        on = QCheckBox(d.name)
        set_checks(on, [not x.get("disabled") for x in es])
        on.setToolTip(d.description or "開／關這個效果")
        on.clicked.connect(lambda _=False, eid=e["id"]: self._now(self.enabledChosen, eid, on.checkState() == Qt.Checked))
        head.addWidget(on, 1)
        for text, tip, fn in (("↑", "往前（先套用）", lambda _=False, eid=e["id"]: self._now(self.moveRequested, eid, -1)),
                              ("↓", "往後", lambda _=False, eid=e["id"]: self._now(self.moveRequested, eid, 1)),
                              ("✕", "移除這個效果", lambda _=False, eid=e["id"]: self._now(self.removeRequested, eid))):
            b = QPushButton(text)
            b.setFixedWidth(28)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            head.addWidget(b)
        b_up, b_down = head.itemAt(2).widget(), head.itemAt(3).widget()
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
        lay.addLayout(self._number_row("fxmix:" + e["id"], "mix", "混合程度 %", 0.0, 100.0, 1.0, 0, 100))
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
        kinds = {kind_tag(x.get("mask")) for x in es}
        kind.setCurrentIndex(max(0, kind.findData(kinds.pop())) if len(kinds) == 1 else -1)
        kind.activated.connect(lambda i, eid=e["id"], cb=kind: self._kind_chosen(eid, cb.itemData(i)))
        row.addWidget(kind, 1)
        mgroup = "fxmask:" + e["id"]
        self.widgets[(mgroup, "kind")] = kind
        masked = all(x.get("mask") for x in es)                 # (the rows: when every clip has one)
        if masked and len(self.clips) == 1:                     # (the preview drags one clip's)
            ed = QPushButton("編輯遮罩")
            ed.setCheckable(True)
            ed.setChecked(self.mask_edit == e["id"])
            ed.setToolTip("在預覽畫面上拖曳這個遮罩：移動、縮放、旋轉、羽化")
            ed.toggled.connect(lambda v, eid=e["id"]: self.set_mask_edit(eid if v else None))
            self.widgets[("mask_edit", e["id"])] = ed
            row.addWidget(ed)
        if masked:
            row.addWidget(self._key_button(mgroup, "kind"))
        lay.addLayout(row)
        if masked:
            irow = QHBoxLayout()
            inv = QCheckBox("反轉（效果作用在遮罩之外）")
            inv.clicked.connect(lambda _=False, eid=e["id"]: self._now(self.maskInvertChosen, eid, inv.checkState() == Qt.Checked))
            self.widgets[(mgroup, "invert")] = inv
            irow.addWidget(inv, 1)
            irow.addWidget(self._key_button(mgroup, "invert"))
            lay.addLayout(irow)
            for r in PARAMS["mask"]:
                if all(kind_tag(x["mask"]) == "line" for x in es) and r[0] in ("w", "h"):
                    continue
                lay.addLayout(self._number_row(mgroup, r[0], r[1], r[2], r[3], r[4], r[5], r[6]))
        return box

    def _number_row(self, group, key, label, lo, hi, step, dec, factor):
        row = QHBoxLayout()
        lab = QLabel(label)
        lab.setMinimumWidth(70)
        row.addWidget(lab)
        s = SpinBox()
        if group.startswith("fx:"):                  # a filter's own numbers: typing goes past its range
            s.set_limits(lo, hi)
        else:
            g = group.split(":", 1)[0] if group.startswith(("fxmask:", "fxmix:")) else group
            g = "mask" if g == "fxmask" else g
            s.set_limits(lo, hi, *[None if v is None else v * factor for v in hard_limits(g, key)])
        s.setSingleStep(step)
        s.setDecimals(dec)
        s.setKeyboardTracking(False)
        s.edited.connect(lambda v, g=group, k=key, f=factor: self._queue(g, k, v / f))
        self.widgets[(group, key)] = s
        row.addWidget(s, 1)
        row.addWidget(self._key_button(group, key))
        return row

    def _key_button(self, group, key):
        b = key_button(lambda: self._now(self.keyToggled, group, key))
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
            cb.clicked.connect(lambda _=False, g=group, k=p.name, cb=cb: (self._queue(g, k, cb.checkState() == Qt.Checked),
                                                                         self._flush()))
            self.widgets[(group, p.name)] = cb
            row.addWidget(cb, 1)
            row.addWidget(self._key_button(group, p.name))
        elif p.type == "menu":
            box = ComboBox()
            box.addItems(p.items)
            box.activated.connect(lambda i, g=group, k=p.name, items=p.items: (self._queue(g, k, items[i]), self._flush()))
            self.widgets[(group, p.name)] = box
            row.addWidget(box, 1)
            row.addWidget(self._key_button(group, p.name))
        elif p.type == "color":
            btn = QPushButton()
            btn.clicked.connect(lambda _=False, g=group, k=p.name: self._pick_color(g, k))
            self.widgets[(group, p.name)] = btn
            row.addWidget(btn, 1)
            row.addWidget(self._key_button(group, p.name))
        else:                                                   # vec2 / vec3
            n = 3 if p.type == "vec3" else 2
            for i in range(n):
                s = SpinBox()
                s.set_limits(p.lo, p.hi)
                s.setSingleStep(step_for(p))
                s.setDecimals(3)
                s.setKeyboardTracking(False)
                s.edited.connect(lambda v, g=group, k=p.name, i=i, n=n: self._queue_vec(g, k, i, v, n))
                self.widgets[(group, p.name, i)] = s
                row.addWidget(s, 1)
            row.addWidget(self._key_button(group, p.name))
        return row

    def _retarget(self, c):
        """The form kept for clip c (alike the one it was built for): its widgets keyed by c's
        effect ids, the ids its buttons hold mapped to them."""
        f = QApplication.focusWidget()
        if f is not None and self.body.isAncestorOf(f):
            f.clearFocus()                          # (a field typed in shows the new clips' value)
        now = [e["id"] for e in (c.get("effects") or [])] if c else []
        before = self.alias
        self.alias = {b: n for b, n in zip(self.built, now) if b != n}
        step = {before.get(b, b): self.alias.get(b, b) for b in self.built}    # shown before -> now

        def moved(x):
            head, sep, eid = x.rpartition(":")
            return head + sep + step.get(eid, eid)
        self.widgets = {tuple(moved(x) if isinstance(x, str) else x for x in key) if isinstance(key, tuple) else key: w
                        for key, w in self.widgets.items()}
        for key, b in self.widgets.items():
            if isinstance(key, tuple) and key[0] == "mask_edit":
                b.blockSignals(True)
                b.setChecked(key[1] == self.mask_edit)
                b.blockSignals(False)

    def _real(self, x):
        """An effect id, or a group of one ("fx:<id>", "fxmix:<id>", "fxmask:<id>"), as the
        shown clip's: the form may have been built for another clip alike it."""
        if not self.alias or x is None:
            return x
        head, sep, eid = x.rpartition(":")
        return head + sep + self.alias.get(eid, eid)

    # -- showing values ---------------------------------------------------------------------------
    def _kind_chosen(self, eid, kind):
        eid = self._real(eid)
        if kind is not None and len(self.clips) == 1:   # a new range: straight to dragging it on the preview
            self.mask_edit = eid
        self._now(self.maskKindChosen, eid, kind)

    def set_mask_edit(self, eid):
        """Edit the mask of effect eid on the preview (None: none)."""
        eid = self._real(eid)
        if eid == self.mask_edit:
            return
        self.mask_edit = eid
        for key, b in self.widgets.items():
            if key[0] == "mask_edit":
                b.blockSignals(True)
                b.setChecked(key[1] == eid)
                b.blockSignals(False)
        self.maskEditChanged.emit()

    def show_live(self, clip_id, group, values):
        """The numbers of an effect mask being dragged on the preview (not an edit yet)."""
        if clip_id != self.clip_id or not group.startswith("fxmask:"):
            return
        for r in PARAMS["mask"]:
            s = self.widgets.get((group, r[0]))
            if r[0] in values and s is not None and not s.hasFocus():
                s.show_value(round(values[r[0]] * r[6], r[5]))

    def _drag_mime(self, eid):
        """A drag of effect eid of the clip shown (its settings as they are now)."""
        eid = self._real(eid)
        self._flush()
        e = next((e for e in (self.clip or {}).get("effects") or [] if e["id"] == eid), None)
        return effect_mime(e, self.clip_id) if e is not None else None

    # -- dropping effects in the list -------------------------------------------------------------
    def _takes(self, e):
        return bool(self.ids) and e.mimeData().hasFormat(FX_MIME)

    def _drop_index(self, y):
        """(place in the chain, the line's y) for a drop at y (panel coordinates)."""
        tops = [(b.mapTo(self, QPoint(0, 0)).y(), b.height()) for b in self.boxes]
        for i, (top, h) in enumerate(tops):
            if y < top + h / 2:
                return i, top - 3
        if tops:
            return len(tops), tops[-1][0] + tops[-1][1] + 1
        return 0, self.body.mapTo(self, QPoint(0, 0)).y()

    def _swap_box(self, e):
        """With Alt held: the index of the effect box under the drop (one of the form's), else None."""
        if self.clip is None or not e.modifiers() & Qt.AltModifier:
            return None
        y = e.position().y()
        for i, b in enumerate(self.boxes):
            top = b.mapTo(self, QPoint(0, 0)).y()
            if top <= y < top + b.height():
                return i
        return None

    def _accept(self, e):
        e.setDropAction(Qt.CopyAction)           # (Alt may propose a link, which the drags do not offer)
        e.accept()

    def dragEnterEvent(self, e):
        if not self._takes(e):
            e.ignore()
            return
        self._accept(e)
        self.dragMoveEvent(e)

    def dragMoveEvent(self, e):
        if not self._takes(e):
            e.ignore()
            return
        k = self._swap_box(e)
        if k is not None:
            b = self.boxes[k]
            self.drop_line.hide()
            self.swap_frame.setGeometry(QRect(b.mapTo(self, QPoint(0, 0)), b.size()))
            self.swap_frame.show()
            self.swap_frame.raise_()
        else:
            _i, y = self._drop_index(e.position().y())
            self.swap_frame.hide()
            self.drop_line.setGeometry(self.body.mapTo(self, QPoint(0, 0)).x(), max(0, y), self.body.width(), 3)
            self.drop_line.show()
            self.drop_line.raise_()
        self._accept(e)

    def dragLeaveEvent(self, e):
        self.drop_line.hide()
        self.swap_frame.hide()

    def dropEvent(self, e):
        self.drop_line.hide()
        self.swap_frame.hide()
        if not self._takes(e):
            e.ignore()
            return
        i, _y = self._drop_index(e.position().y())
        k = self._swap_box(e)
        self._accept(e)
        self._flush()
        payload = bytes(e.mimeData().data(FX_MIME)).decode("utf-8")
        if k is not None:
            self.effectSwapped.emit(list(self.ids), self.clip["effects"][k]["id"], payload)
        elif self.clip is None:                       # clips with effects not alike: replacing them all
            self.effectsDropped.emit(list(self.ids), payload)
        else:
            self.effectDropped.emit(list(self.ids), payload, i)

    def show_clips(self, clips, t_us, fps):
        pics = [k for k in clips if k["type"] in edit.VISUAL]
        chains = {tuple(e["filter"] for e in k.get("effects") or []) for k in pics}
        c = pics[0] if len(chains) == 1 else None               # alike (or one clip): a form
        # what the form is built from - not which clips, nor how many when it is the same form
        # (the switches show what the clips have, so which kinds of clip there are): it is kept
        if c is None:                               # for alike ones
            shape = (len(clips), len(pics))
        else:
            shape = (len(clips) > 1, len(pics) > 1, len(pics) < len(clips),
                     tuple((fx.get(e["filter"]).key(), fx.get(e["filter"]).error) for e in c.get("effects") or []),
                     frozenset((k["type"] == "filter", bool(k.get("asset")),
                                tuple((e["filter"], bool(e.get("disabled")), kind_tag(e.get("mask")))
                                      for e in k.get("effects") or [])) for k in pics),
                     frozenset(json.dumps(k.get("backdrop"), sort_keys=True) for k in pics))
        ids = [k["id"] for k in pics]
        if shape != self.shape or ids != self.ids:
            self._flush()                           # (to the clips it was typed for)
        moved = ids != self.ids or (c or {}).get("id") != self.clip_id
        self.ids = ids
        self.clips = pics if c else []
        self.clip = c
        if shape != self.shape or moved:
            self.clip_id = c["id"] if c else None
            if self.mask_edit and (len(pics) > 1 or not any(e["id"] == self.mask_edit and e.get("mask")
                                                            for e in (c.get("effects") or [] if c else []))):
                self.mask_edit = None               # that effect or its mask is gone (or several clips)
        if shape != self.shape:
            self.shape = shape
            self._build(c, len(clips))
            self.maskEditChanged.emit()
        elif moved:
            self._retarget(c)
            if self.many_note is not None:
                self._many_text(len(clips))
            self.maskEditChanged.emit()
        if c is None:
            return
        ts = [edit.time_in(t_us, k["start_us"], fps) for k in pics]
        w = self.widgets
        for i, e in enumerate(c.get("effects") or []):
            es = [k["effects"][i] for k in pics]
            d = fx.get(e["filter"])
            xgroup = "fxmix:" + e["id"]
            stored = [x.get("mix", 1.0) for x in es]
            s = w.get((xgroup, "mix"))
            v = alike([curves.value(m, t) for m, t in zip(stored, ts)])
            if s is None or s.hasFocus() and ((xgroup, "mix") in self.pending or s.mixed and v is MIXED):
                pass                                # (being typed)
            elif v is MIXED:
                s.show_mixed()
            else:
                s.show_value(round(float(v) * 100))
            if ("key", xgroup, "mix") in w:
                Inspector._key_state(w[("key", xgroup, "mix")], stored, pics, ts)
            group = "fx:" + e["id"]
            for p in d.params:
                stored = [x["params"].get(p.name, p.default) for x in es]
                self._show(group, p, alike([curves.value(v, t) for v, t in zip(stored, ts)]))
                kb = w.get(("key", group, p.name))
                if kb is not None:
                    Inspector._key_state(kb, stored, pics, ts)
            mgroup = "fxmask:" + e["id"]
            if ("key", mgroup, "kind") not in w:
                continue                            # (not every clip has a range)
            for key, default in (("kind", "rectangle"), ("invert", False)):
                stored = [x["mask"].get(key, default) for x in es]
                v = alike([curves.value(m, t) for m, t in zip(stored, ts)])
                box = w[(mgroup, key)]
                box.blockSignals(True)
                if key == "kind":
                    box.setCurrentIndex(-1 if v is MIXED else max(0, box.findData(v)))
                else:
                    set_checks(box, [bool(curves.value(m, t)) for m, t in zip(stored, ts)])
                box.blockSignals(False)
                Inspector._key_state(w[("key", mgroup, key)], stored, pics, ts)
            for r in PARAMS["mask"]:
                s = w.get((mgroup, r[0]))
                if s is None:
                    continue
                stored = [x["mask"].get(r[0], r[7]) for x in es]
                v = alike([curves.value(m, t) for m, t in zip(stored, ts)])
                if s.hasFocus() and ((mgroup, r[0]) in self.pending or s.mixed and v is MIXED):
                    pass                            # (being typed)
                elif v is MIXED:
                    s.show_mixed()
                else:
                    s.show_value(round(v * r[6], r[5]))
                Inspector._key_state(w[("key", mgroup, r[0])], stored, pics, ts)

    def _show(self, group, p, v):
        """Parameter p of effect group showing value v (MIXED: the clips' are not the same)."""
        w = self.widgets
        if p.type in ("float", "int"):
            s = w.get((group, p.name))
            if s is None or s.hasFocus() and ((group, p.name) in self.pending or s.mixed and v is MIXED):
                return
            s.show_mixed() if v is MIXED else s.show_value(round(float(v), 0 if p.type == "int" else 3))
        elif p.type == "bool":
            cb = w.get((group, p.name))
            if cb is not None:
                cb.blockSignals(True)
                set_checks(cb, [True, False] if v is MIXED else [bool(round(float(v)))])
                cb.blockSignals(False)
        elif p.type == "menu":
            box = w.get((group, p.name))
            if box is not None:
                box.blockSignals(True)
                box.setCurrentIndex(-1 if v is MIXED else fx.menu_index(p, v))
                box.blockSignals(False)
        elif p.type == "color":
            btn = w.get((group, p.name))
            if btn is not None and v is MIXED:
                btn.setText("--")
                btn.setStyleSheet("")
            elif btn is not None:
                r, g, b, a = (int(round(min(1, max(0, x)) * 255)) for x in (list(v) + [1.0] * 4)[:4])
                btn.setText(f"#{r:02x}{g:02x}{b:02x}" + (f"{a:02x}" if a < 255 else ""))
                btn.setStyleSheet(f"background: rgb({r},{g},{b}); color: {'#000' if r + g + b > 380 else '#fff'};")
        else:
            for i in range(3 if p.type == "vec3" else 2):
                s = w.get((group, p.name, i))
                if s is not None and not s.hasFocus():
                    s.show_mixed() if v is MIXED else s.show_value(round(float(v[i]), 3))

    # -- edits ------------------------------------------------------------------------------------
    def _queue(self, group, key, value):
        group = self._real(group)
        self.pending[(group, key)] = value
        self.timer.start()
        if self.clip_id:
            self.liveEdited.emit(list(self.ids), group, key, value)

    def _queue_vec(self, group, key, index, value, n=2):
        group = self._real(group)
        cur = self.pending.get((group, key))
        if cur is None:
            cur = [self.widgets[(group, key, i)].value() for i in range(n)]
        cur = list(cur)
        cur[index] = value
        self._queue(group, key, cur)

    def _pick_color(self, group, key):
        group = self._real(group)
        btn = self.widgets[(group, key)]
        ids = list(self.ids) if self.clip_id else []
        col = pick_color(self, qcolor(btn.text() if btn.text() != "--" else "#ffffff"), "顏色",
                         live=lambda c: ids and self.liveEdited.emit(ids, group, key, rgba(c)),
                         cancel=self.liveCancelled.emit, anchor=btn)
        if col is not None:
            self._queue(group, key, rgba(col))
            self._flush()

    def _now(self, signal, *args):
        """signal for the clips of the form (◆: for the main one; the others alike follow it)."""
        if args and isinstance(args[0], str):
            args = (self._real(args[0]),) + args[1:]    # (an effect id or a group)
        self._flush()
        if self.clip_id:
            signal.emit([self.clip_id] if signal is self.keyToggled else list(self.ids), *args)

    def _flush(self):
        self.timer.stop()
        if not self.pending or not self.clip_id:
            self.pending.clear()
            return
        pending, self.pending = self.pending, {}
        for (g, k), v in pending.items():
            self.paramEdited.emit(list(self.ids), g, k, v)
