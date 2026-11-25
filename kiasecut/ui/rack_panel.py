"""全局參數架 (rack.py), the panel after 屬性 and its tabs: the project's named values, each with its
kind, its value at the playhead (◆: keyframes along the timeline), for a number or a whole number a ✎
for an expression and a ∿ for an LFO, for a number a ♪ for a sound to follow (soundmeter.py), and the names to write in any clip's expression. Right-click a
clip's number > 綁定全局參數 uses one; so does right-clicking its words, font, a colour, a switch, a
menu or a vector (racklinks.py)."""
import os

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from .. import curves, edit, lfo, rack, soundmeter
from . import icons, look
from .colorpick import hex_of, pick_color, qcolor, rgba
from .inspector import KEY_ANIMATED, KEY_ON, ComboBox, SpinBox, key_button
from .menukeys import Menu

EASINGS = (("線性", "linear"), ("緩入", "ease_in"), ("緩出", "ease_out"), ("緩入緩出", "ease_in_out"))
BROWSE = "__browse__"


def heard_label(root, spec):
    """What a meter spec listens to, for a tooltip."""
    comp = (root.get("compounds") or {}).get(spec.get("level")) or {}
    channel = next((name for ident, _kind, name in soundmeter.channels(comp) if ident == spec.get("channel")), "？")
    return f"{comp.get('name') or '？'} ▸ {channel}　{spec['lo_hz']:.0f}–{spec['hi_hz']:.0f} Hz"


class RackRow(QWidget):
    def __init__(self, window, p):
        super().__init__()
        self.rid = p["id"]
        self.kind = kind = rack.kind_of(p)
        self.window_ = window
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        self.name = QPushButton(p["name"])
        self.name.setFlat(True)
        self.name.setStyleSheet("text-align: left; font-weight: bold;")
        self.name.setFixedWidth(120)
        self.name.setToolTip("在表達式裡直接寫這個名字；按一下重新命名")
        self.name.clicked.connect(lambda: self.send("rename"))
        tag = QLabel(rack.KINDS.get(kind, kind))
        tag.setStyleSheet("color: #8e8e94;")
        tag.setFixedWidth(56)
        lay.addWidget(self.name)
        lay.addWidget(tag)
        editor = QWidget()
        box = QHBoxLayout(editor)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(3)
        self.spin = self.check = self.combo = self.color = self.words = None
        self.spins = []
        if kind in rack.DRIVEN:
            self.spin = self._number(box, 0 if kind == "int" else 3, 1 if kind == "int" else 0.1)
            self.spin.edited.connect(lambda v: self.send("value", int(round(v)) if self.kind == "int" else v))
        elif kind in rack.SIZES:
            for i in range(rack.SIZES[kind]):
                s = self._number(box, 3, 0.1)
                s.setToolTip(f"表達式裡寫 {p['name']}[{i}]")
                s.edited.connect(lambda v, i=i: self._vector(i, v))
                self.spins.append(s)
        elif kind == "bool":
            self.check = QCheckBox("開")
            self.check.clicked.connect(lambda on: self.send("value", bool(on)))
            box.addWidget(self.check)
            box.addStretch()
        elif kind == "menu":
            self.combo = ComboBox()
            self.combo.addItems(p.get("items") or [])
            self.combo.activated.connect(lambda i: self.send("value", self.combo.itemText(i)))
            box.addWidget(self.combo, 1)
        elif kind == "color":
            self.color = QPushButton()
            self.color.clicked.connect(self._pick_color)
            box.addWidget(self.color, 1)
        elif kind == "text":
            self.words = QPlainTextEdit()
            self.words.setFixedHeight(48)
            self.words.setTabChangesFocus(True)
            self.words.textChanged.connect(lambda: self.send("value", self.words.toPlainText()))
            box.addWidget(self.words, 1)
        elif kind == "font":
            self.combo = ComboBox()
            self.combo.setMaxVisibleItems(20)
            self.combo.setMinimumWidth(60)
            self.combo.setSizeAdjustPolicy(ComboBox.AdjustToMinimumContentsLengthWithIcon)
            for f in window.fonts:
                self.combo.addItem(f["name"], f["path"])
            self.combo.addItem("瀏覽字型檔…", BROWSE)
            self.combo.activated.connect(self._font_chosen)
            box.addWidget(self.combo, 1)
        lay.addWidget(editor, 1)
        self.key = key_button(lambda: self.send("key"))
        lay.addWidget(self.key)
        self.lfo = self.expr = self.sound = self.result = None
        if kind in rack.DRIVEN:
            self.expr = QPushButton("✎")
            self.expr.setFixedWidth(28)
            self.expr.clicked.connect(lambda: self.send("expr"))
            self.lfo = QPushButton("∿")
            self.lfo.setFixedWidth(28)
            self.lfo.clicked.connect(lambda: self.send("lfo"))
            self.result = QLabel()
            self.result.setStyleSheet("color: #e0a030;")
            if kind == "number":
                self.sound = QPushButton("♪")
                self.sound.setFixedWidth(28)
                self.sound.clicked.connect(lambda: self.send("sound"))
                lay.addWidget(self.sound)
            lay.addWidget(self.lfo)
            lay.addWidget(self.expr)
            lay.addWidget(self.result, 1)
        more = QPushButton("⋯")
        more.setFixedWidth(28)
        more.clicked.connect(lambda: window.row_menu(self.rid, more))
        lay.addWidget(more)
        self.vector = []
        self.current = None

    def send(self, action, arg=None):
        self.window_.action.emit(self.rid, action, arg)

    def _number(self, box, decimals, step):
        s = SpinBox()
        s.set_limits(-100.0, 100.0)
        s.setDecimals(decimals)
        s.setSingleStep(step)
        s.setKeyboardTracking(False)
        box.addWidget(s, 1)
        return s

    def _vector(self, i, v):
        out = list(self.vector)
        out[i] = v
        self.vector = out
        self.send("value", list(out))

    def _pick_color(self):
        got = pick_color(self, qcolor(self.current), self.name.text())
        if got is not None:
            self.send("value", rgba(got))

    def _font_chosen(self, i):
        path = self.combo.itemData(i)
        if path == BROWSE:
            path, _ = QFileDialog.getOpenFileName(self, "選擇字型檔", "", "字型 (*.ttf *.otf *.ttc *.otc)")
            if not path:
                self._show_font(self.current)
                return
            path = path.replace("\\", "/")
        self.send("value", path)

    def _show_font(self, path):
        self.combo.blockSignals(True)
        i = self.combo.findData(path) if path else -1
        if path and i < 0:                                     # a font that is not in the list: its file name
            self.combo.insertItem(0, os.path.splitext(os.path.basename(path))[0], path)
            i = 0
        self.combo.setCurrentIndex(i)
        self.combo.blockSignals(False)

    def show_value(self, v):
        """Show the parameter's own value at the playhead (a field being typed in is left alone)."""
        if self.kind in rack.DRIVEN:
            if not self.spin.hasFocus():
                self.spin.show_value(float(v))
        elif self.kind in rack.SIZES:
            self.vector = list(v)
            for s, x in zip(self.spins, v):
                if not s.hasFocus():
                    s.show_value(float(x))
        elif self.kind == "bool":
            self.check.setChecked(bool(v))
        elif self.kind == "menu":
            self.combo.setCurrentIndex(self.combo.findText(v))
        elif self.kind == "color":
            self.current = text = hex_of(QColor.fromRgbF(*v))
            solid = qcolor(text)
            self.color.setText(text)
            look.set_sheet(self.color, f"QPushButton {{ background: {solid.name()}; "
                                       f"color: {'#000' if solid.lightness() > 140 else '#fff'}; }}")
        elif self.kind == "text":
            if not self.words.hasFocus() and self.words.toPlainText() != v:
                self.words.blockSignals(True)
                self.words.setPlainText(v)
                self.words.blockSignals(False)
        elif self.kind == "font":
            self.current = v
            self._show_font(v)

    def show_param(self, root, p, t_us, now):
        self.show_value(rack.value_at(p, t_us))
        animated = curves.is_animated(p.get("value"))
        on = animated and edit.key_at(p["value"], t_us) is not None
        self.key.setIcon(icons.key_icon("on" if on else "off", KEY_ON if on else KEY_ANIMATED if animated else icons.INK))
        if self.kind not in rack.DRIVEN:
            return
        driven = lfo.is_lfo(p.get("lfo"))
        look.set_sheet(self.lfo, "color: #6fb3ff;" if driven else "")
        self.lfo.setToolTip(lfo.label(p["lfo"]) if driven else "加上 LFO（低頻振盪器）")
        heard = self.sound is not None and soundmeter.is_spec(p.get("sound"))
        problem = self.window_.problems.get(p["id"]) if heard else None
        if self.sound is not None:
            look.set_sheet(self.sound, "color: #ff6b6b;" if problem else "color: #52ffae;" if heard else "")
            self.sound.setToolTip(problem or (heard_label(root, p["sound"]) if heard else "跟著聲音（peak to value）"))
        self.spin.setEnabled(not driven and not heard)
        has = bool(p.get("expr"))
        look.set_sheet(self.expr, "color: #e0a030;" if has else "")
        self.expr.setToolTip(("表達式：" + p["expr"]) if has else "加上表達式")
        shown = f"= {now.get(p['name'], 0.0):.4g}　{p.get('expr', '')}" if has or heard else ""
        self.result.setText(problem or shown)
        self.result.setToolTip(problem or p.get("expr", ""))


class RackPanel(QWidget):
    action = Signal(str, str, object)        # parameter id, "value" (a value of its kind) / "key" / "rename" / "expr" / "lfo" / "lfo_off" / "sound" / "sound_off" /
                                             # "items" / "up" / "down" / "delete" / "easing" (a name)
    addRequested = Signal(str)               # kind (rack.KINDS)
    importRequested = Signal()
    exportRequested = Signal()

    def __init__(self):
        super().__init__()
        self.setMinimumWidth(300)
        self.fonts = []                       # the installed fonts, [{"name", "path"}] (set_fonts)
        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        add = QPushButton("＋ 新增參數")
        self.add_menu = Menu(add)
        for kind, text in rack.KINDS.items():
            self.add_menu.addAction(text, lambda k=kind: self.addRequested.emit(k))
        add.clicked.connect(lambda: self.add_menu.exec(add.mapToGlobal(add.rect().bottomLeft())))
        imp, exp = QPushButton("匯入…"), QPushButton("匯出…")
        imp.clicked.connect(self.importRequested)
        exp.clicked.connect(self.exportRequested)
        head.addWidget(add)
        head.addWidget(imp)
        head.addWidget(exp)
        head.addStretch()
        lay.addLayout(head)
        self.body = QWidget()
        self.rows_lay = QVBoxLayout(self.body)
        self.rows_lay.setContentsMargins(0, 0, 0, 0)
        self.rows_lay.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.body)
        lay.addWidget(scroll, 1)
        self.rows = {}
        self.shape = None
        self.root = None
        self.t_us = 0
        self.problems = {}                    # parameter id -> why its sound cannot be measured

    def set_fonts(self, fonts):
        """The installed fonts arrived (or changed): the rows are built again with them."""
        self.fonts = list(fonts)
        self.shape = None
        if self.root is not None:
            self.fill(self.root, self.t_us)

    def fill(self, root, t_us):
        """Show the project's parameters at timeline time t_us (rebuilt only when they changed)."""
        self.root, self.t_us = root, t_us
        ps = rack.params(root)
        shape = tuple((p["id"], p["name"], rack.kind_of(p), tuple(p.get("items") or ())) for p in ps)
        if shape != self.shape:
            self.shape = shape
            for r in self.rows.values():
                r.setParent(None)
                r.deleteLater()
            self.rows = {}
            for i, p in enumerate(ps):
                self.rows[p["id"]] = r = RackRow(self, p)
                self.rows_lay.insertWidget(i, r)
        now = rack.values(root, t_us)
        for p in ps:
            self.rows[p["id"]].show_param(root, p, t_us, now)

    def row_menu(self, rid, button):
        kind = self.rows[rid].kind
        menu = Menu(self)
        menu.addAction("上移", lambda: self.action.emit(rid, "up", None))
        menu.addAction("下移", lambda: self.action.emit(rid, "down", None))
        if kind in rack.BLENDING:
            ease = menu.addMenu("播放頭上關鍵幀的曲線")
            for name, key in EASINGS:
                ease.addAction(name, lambda k=key: self.action.emit(rid, "easing", k))
        menu.addSeparator()
        if kind == "menu":
            menu.addAction("編輯選項…", lambda: self.action.emit(rid, "items", None))
        if kind in rack.DRIVEN:
            menu.addAction("取消 LFO", lambda: self.action.emit(rid, "lfo_off", None))
        if kind == "number":
            menu.addAction("取消聲音來源", lambda: self.action.emit(rid, "sound_off", None))
        menu.addAction("刪除參數", lambda: self.action.emit(rid, "delete", None))
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
