"""全局參數架 (rack.py), the panel after 屬性 and its tabs: the project's named numbers, each with its
value at the playhead (◆: keyframes along the timeline), a ✎ for an expression, and the names to
write in any clip's expression. Right-click a clip's number > 表達式 > 綁定到… uses one."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .. import curves, edit, lfo, rack
from . import icons
from .inspector import KEY_ANIMATED, KEY_ON, SpinBox, key_button
from .menukeys import Menu

EASINGS = (("線性", "linear"), ("緩入", "ease_in"), ("緩出", "ease_out"), ("緩入緩出", "ease_in_out"))


class RackRow(QWidget):
    def __init__(self, window, p):
        super().__init__()
        self.rid = p["id"]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        self.name = QPushButton(p["name"])
        self.name.setFlat(True)
        self.name.setStyleSheet("text-align: left; font-weight: bold;")
        self.name.setFixedWidth(120)
        self.name.setToolTip("在表達式裡直接寫這個名字；按一下重新命名")
        self.name.clicked.connect(lambda: window.action.emit(self.rid, "rename", None))
        self.spin = SpinBox()
        self.spin.set_limits(-100.0, 100.0)
        self.spin.setDecimals(3)
        self.spin.setSingleStep(0.1)
        self.spin.setKeyboardTracking(False)
        self.spin.edited.connect(lambda v: window.action.emit(self.rid, "value", v))
        self.key = key_button(lambda: window.action.emit(self.rid, "key", None))
        self.expr = QPushButton("✎")
        self.expr.setFixedWidth(28)
        self.expr.clicked.connect(lambda: window.action.emit(self.rid, "expr", None))
        self.lfo = QPushButton("∿")
        self.lfo.setFixedWidth(28)
        self.lfo.clicked.connect(lambda: window.action.emit(self.rid, "lfo", None))
        self.result = QLabel()
        self.result.setStyleSheet("color: #e0a030;")
        more = QPushButton("⋯")
        more.setFixedWidth(28)
        more.clicked.connect(lambda: window.row_menu(self.rid, more))
        for w, stretch in ((self.name, 0), (self.spin, 1), (self.key, 0), (self.lfo, 0), (self.expr, 0), (self.result, 1), (more, 0)):
            lay.addWidget(w, stretch)

    def show_param(self, root, p, t_us, now):
        v = curves.value(p.get("value", 0.0), t_us)
        if not self.spin.hasFocus():
            self.spin.show_value(float(v))
        animated = curves.is_animated(p.get("value"))
        on = animated and edit.key_at(p["value"], t_us) is not None
        self.key.setIcon(icons.key_icon("on" if on else "off", KEY_ON if on else KEY_ANIMATED if animated else icons.INK))
        driven = lfo.is_lfo(p.get("lfo"))
        self.lfo.setStyleSheet("color: #6fb3ff;" if driven else "")
        self.lfo.setToolTip(lfo.label(p["lfo"]) if driven else "加上 LFO（低頻振盪器）")
        self.spin.setEnabled(not driven)
        has = bool(p.get("expr"))
        self.expr.setStyleSheet("color: #e0a030;" if has else "")
        self.expr.setToolTip(("表達式：" + p["expr"]) if has else "加上表達式")
        self.result.setText(f"= {now.get(p['name'], 0.0):.4g}　{p['expr']}" if has else "")
        self.result.setToolTip(p.get("expr", ""))


class RackPanel(QWidget):
    action = Signal(str, str, object)        # parameter id, "value" (a number) / "key" / "rename" / "expr" / "lfo" / "lfo_off" / "up" / "down" /
                                             # "delete" / "easing" (a name)
    addRequested = Signal()
    importRequested = Signal()
    exportRequested = Signal()

    def __init__(self):
        super().__init__()
        self.setMinimumWidth(300)
        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        add = QPushButton("＋ 新增參數")
        add.clicked.connect(self.addRequested)
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
        self.t_us = 0

    def fill(self, root, t_us):
        """Show the project's parameters at timeline time t_us (rebuilt only when they changed)."""
        self.t_us = t_us
        ps = rack.params(root)
        shape = tuple((p["id"], p["name"]) for p in ps)
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
        menu = Menu(self)
        menu.addAction("上移", lambda: self.action.emit(rid, "up", None))
        menu.addAction("下移", lambda: self.action.emit(rid, "down", None))
        ease = menu.addMenu("播放頭上關鍵幀的曲線")
        for name, key in EASINGS:
            ease.addAction(name, lambda k=key: self.action.emit(rid, "easing", k))
        menu.addSeparator()
        menu.addAction("取消 LFO", lambda: self.action.emit(rid, "lfo_off", None))
        menu.addAction("刪除參數", lambda: self.action.emit(rid, "delete", None))
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
