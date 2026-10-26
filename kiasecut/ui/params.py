"""A component's parameters in the editor (元件, components.py): the 參數 list and the
設為參數 / 解除參數 menu of its clips.

The list sits under the layers of a static component and beside the timeline of a live one.
Click a parameter to select the clips it sets, double-click it to set its default (what
every clip it sets gets), right-click to rename, restack, unbind a clip or delete it.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QVBoxLayout, QWidget

from .. import assets, components

ROLE = Qt.UserRole


def clip_name(c):
    """What a clip (a layer) is called in the lists."""
    name = c.get("name") or ""
    if c["type"] == "text" and not c.get("named"):
        name = (c["text"].get("content") or "").replace("\n", " ")[:30]
    if c.get("asset"):
        name = name or assets.name_of(c["asset"])
    return name or c["type"]


def value_text(p, v):
    """A parameter's value, short."""
    if p["kind"] == "text":
        v = (v or "").replace("\n", " ")
        return f"「{v[:14]}{'…' if len(v) > 14 else ''}」"
    if p["kind"] == "color":
        return assets.hex_of(v)
    if p["kind"] == "image":
        return v.replace("\\", "/").rsplit("/", 1)[-1] if v else "（沒有）"
    return "顯示" if v else "隱藏"


def bound_tip(c, params):
    """The tooltip of the ❖ on a clip that parameters [(param, prop)] set."""
    return "元件參數：" + "、".join(f"{p['name']}（{components.prop_label(c, prop)}）" for p, prop in params)


def param_menu(menu, comp, clips, bind, unbind):
    """設為參數 / 解除參數 of clips of component comp, added to menu: bind(param id or "" for a
    new one, prop, clip ids), unbind([(clip id, prop)])."""
    props = [pr for pr in components.props_of(clips[0]) if all(pr in components.props_of(c) for c in clips)]
    ids = [c["id"] for c in clips]
    sub = menu.addMenu("設為參數")
    sub.setEnabled(bool(props))
    for prop in props:
        label = components.prop_label(clips[0], prop)
        sub.addAction(f"新參數：{label}", lambda pr=prop: bind("", pr, ids))
        for p in components.params(comp):
            if p["kind"] == components.PROPS[prop][0]:
                sub.addAction(f"　交給「{p['name']}」：{label}", lambda pid=p["id"], pr=prop: bind(pid, pr, ids))
    bound = components.bound(comp)
    mine = [(c, p, prop) for c in clips for p, prop in bound.get(c["id"], ())]
    if mine:
        un = menu.addMenu("解除參數")
        for c, p, prop in mine:
            un.addAction(f"「{p['name']}」：{components.prop_label(c, prop)}" +
                         (f"（{clip_name(c)}）" if len(clips) > 1 else ""),
                         lambda b=(c["id"], prop): unbind([b]))
        if len(mine) > 1:
            un.addAction("全部解除", lambda: unbind([(c["id"], prop) for c, _p, prop in mine]))


class ParamList(QWidget):
    selectionPicked = Signal(object, object)       # {clip ids} a parameter sets, the first one
    paramUnbind = Signal(list)                     # [(clip id, prop)] no parameter sets any more
    paramAction = Signal(str, str)                 # "default" / "rename" / "up" / "down" / "delete", parameter id

    def __init__(self, hint="在圖層上按右鍵 > 設為參數；按兩下參數設定預設值", parent=None):
        super().__init__(parent)
        self.comp = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        head = QHBoxLayout()
        title = QLabel("參數")
        title.setObjectName("title")
        head.addWidget(title)
        tip = QLabel(hint)
        tip.setStyleSheet("color: #8a8a90;")
        tip.setWordWrap(True)
        head.addWidget(tip, 1)
        lay.addLayout(head)
        self.list = QListWidget()
        self.list.itemClicked.connect(self._clicked)
        self.list.itemDoubleClicked.connect(lambda it: it.data(ROLE) and self.paramAction.emit("default", it.data(ROLE)))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.list, 1)

    def set_component(self, comp):
        """Show the parameters of comp (a component's content)."""
        self.comp = comp
        cur = self.list.currentItem()
        keep = cur.data(ROLE) if cur is not None else None
        self.list.clear()
        index = components.layer_index(comp)
        for p in components.params(comp):
            n = sum(1 for cid, _prop in p.get("binds") or [] if cid in index)
            it = QListWidgetItem(f"{components.ICON} {p['name']}　{components.KINDS[p['kind']]} · "
                                 f"{n} 個片段 · 預設 {value_text(p, components.default(comp, p, index))}")
            it.setData(ROLE, p["id"])
            if not n:
                it.setForeground(QColor("#6a6a70"))
                it.setToolTip("沒有片段用這個參數：在片段上按右鍵 > 設為參數 > 交給它")
            self.list.addItem(it)
            if p["id"] == keep:
                self.list.setCurrentItem(it)
        if not self.list.count():
            it = QListWidgetItem("還沒有參數：在片段上按右鍵 > 設為參數")
            it.setFlags(Qt.NoItemFlags)
            self.list.addItem(it)

    def _clicked(self, it):
        p = components.param(self.comp, it.data(ROLE))
        if p is None:
            return
        index = components.layer_index(self.comp)
        ids = list(dict.fromkeys(cid for cid, _prop in p.get("binds") or [] if cid in index))
        if ids:
            self.selectionPicked.emit(set(ids), ids[0])

    def _menu(self, pos):
        it = self.list.itemAt(pos)
        p = components.param(self.comp, it.data(ROLE)) if it is not None else None
        if p is None:
            return
        pid = p["id"]
        menu = QMenu(self)
        for text, action in (("設定預設值…", "default"), ("重新命名…", "rename"), (None, None),
                             ("上移", "up"), ("下移", "down"), (None, None), ("刪除參數", "delete")):
            if text is None:
                menu.addSeparator()
            else:
                menu.addAction(text, lambda a=action: self.paramAction.emit(a, pid))
        index = components.layer_index(self.comp)
        binds = [(cid, prop) for cid, prop in p.get("binds") or [] if cid in index]
        if binds:
            un = menu.addMenu("解除片段")
            for cid, prop in binds:
                c = index[cid][1]
                un.addAction(f"{clip_name(c)}：{components.prop_label(c, prop)}",
                             lambda b=(cid, prop): self.paramUnbind.emit([b]))
        menu.exec(self.list.viewport().mapToGlobal(pos))
