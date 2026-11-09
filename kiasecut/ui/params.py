"""A component's parameters in the editor (元件, components.py): the 參數 list and the
設為參數 / 解除參數 menu of its clips.

The list sits under the layers of a static component and beside the timeline of a live one.
Click a parameter to select the clips it sets, double-click it to set its default (what
every clip it sets gets; a picture parameter's: drop a picture on it too), right-click to
rename, restack, unbind a clip or delete it.
"""
from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from .. import assets, components, mapping
from .library import PictureDrop
from . import inplace
from .menukeys import Menu

ROLE = Qt.UserRole
PARAM_MIME = "application/x-kiase-component-param"       # a parameter dragged onto a property (拖曳綁定)


class DragList(QListWidget):
    """The 參數 list: a parameter can be dragged onto a number in the properties to set it."""

    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setDefaultDropAction(Qt.CopyAction)

    def mimeData(self, items):
        md = QMimeData()
        if items:
            md.setData(PARAM_MIME, str(items[0].data(ROLE)).encode("utf-8"))
        return md

    def supportedDropActions(self):
        return Qt.CopyAction


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
    if p["kind"] == "number":
        return f"{float(v):.4g}"
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
    numbers = None
    for prop in props:
        label = components.prop_label(clips[0], prop)
        kind = components.prop_kind(prop)
        at = sub
        if kind == "number":                              # (many: in a menu of their own, one each)
            numbers = numbers or sub.addMenu("數字")
            at = numbers.addMenu(label)
            at.addAction("新參數", lambda pr=prop: bind("", pr, ids))
        else:
            at.addAction(f"新參數：{label}", lambda pr=prop: bind("", pr, ids))
        for p in components.params(comp):
            if p["kind"] == kind:
                at.addAction(f"　交給「{p['name']}」" + ("" if kind == "number" else f"：{label}"),
                             lambda pid=p["id"], pr=prop: bind(pid, pr, ids))
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
    paramExpr = Signal(str, str, str)              # parameter id, clip id, prop: edit the expression it sets that through
    defaultDropped = Signal(str, str)              # parameter id, the picture dropped on it (its new default)
    paramAdd = Signal(str)                         # kind (components.KINDS): a parameter to make by hand

    def __init__(self, hint="", parent=None):
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
        tip.setVisible(bool(hint))
        head.addWidget(tip, 1)
        add = QPushButton("＋ 新增參數")
        add.setToolTip("自己新增一個參數並選它的種類（文字、數字、顏色、圖片、顯示）；之後在圖層上按右鍵 > 設為參數 > 交給它")
        menu = Menu(add)
        for kind, text in components.KINDS.items():
            menu.addAction(text, lambda k=kind: self.paramAdd.emit(k))
        add.setMenu(menu)
        head.addWidget(add)
        lay.addLayout(head)
        self.list = DragList()
        self.list.itemClicked.connect(self._clicked)
        self.list.itemDoubleClicked.connect(lambda it: it.data(ROLE) and self.paramAction.emit("default", it.data(ROLE)))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.list, 1)
        self.picture_of = lambda md: None           # the picture a drag carries
        self.list.setAcceptDrops(True)
        PictureDrop(self.list.viewport(), lambda md: self.picture_of(md), self.defaultDropped.emit, self._image_param_at)

    def _image_param_at(self, pos):
        """The id of the picture parameter at pos in the list, or None."""
        it = self.list.itemAt(pos)
        p = components.param(self.comp, it.data(ROLE)) if it is not None and self.comp else None
        return p["id"] if p and p["kind"] == "image" else None

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

    def _clicked(self, it):
        p = components.param(self.comp, it.data(ROLE))
        if p is None:
            return
        index = components.layer_index(self.comp)
        ids = list(dict.fromkeys(cid for cid, _prop in p.get("binds") or [] if cid in index))
        if ids:
            self.selectionPicked.emit(set(ids), ids[0])

    def rename_current(self):
        """F2: rename the current parameter; False when there is none."""
        it = self.list.currentItem()
        if it is None or not it.isSelected() or components.param(self.comp, it.data(ROLE)) is None:
            return False
        inplace.item_hint(self.list, it)
        self.paramAction.emit("rename", it.data(ROLE))
        return True

    def _menu(self, pos):
        it = self.list.itemAt(pos)
        p = components.param(self.comp, it.data(ROLE)) if it is not None else None
        if p is None:
            return
        pid = p["id"]
        menu = Menu(self)
        if not p.get("binds"):                         # (a parameter that sets no layer takes the kind it is given)
            kinds = menu.addMenu("改種類")
            for kind, text in components.KINDS.items():
                if kind != p["kind"]:
                    kinds.addAction(text, lambda k=kind: self.paramAction.emit("kind:" + k, pid))
            menu.addSeparator()
        for text, action in (("設定預設值…", "default"), ("重新命名…", "rename"), (None, None),
                             ("上移", "up"), ("下移", "down"), (None, None), ("刪除參數", "delete")):
            if text is None:
                menu.addSeparator()
            else:
                menu.addAction(text, lambda a=action: (inplace.item_hint(self.list, it), self.paramAction.emit(a, pid)))
        index = components.layer_index(self.comp)
        binds = [(cid, prop) for cid, prop in p.get("binds") or [] if cid in index]
        if binds and p["kind"] == "number":
            ex = menu.addMenu("映射")
            for cid, prop in binds:
                c = index[cid][1]
                text = components.expr_of(p, cid, prop)
                text = mapping.label(text) if mapping.is_mapping(text) else text
                ex.addAction(f"{clip_name(c)}：{components.prop_label(c, prop)}　{text if len(text) < 24 else text[:22] + '…'}",
                             lambda b=(cid, prop): self.paramExpr.emit(pid, *b))
        if binds:
            un = menu.addMenu("解除片段")
            for cid, prop in binds:
                c = index[cid][1]
                un.addAction(f"{clip_name(c)}：{components.prop_label(c, prop)}",
                             lambda b=(cid, prop): self.paramUnbind.emit([b]))
        menu.exec(self.list.viewport().mapToGlobal(pos))
