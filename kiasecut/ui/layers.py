"""The static compound editor (靜態複合片段 = a picture made in the editor): a layer list, as in
Photoshop, takes the timeline's place while a static compound is open.

Each picture clip is a layer, the top one first (edit.layers), with a small picture of it (at
the picture's moment). A group's ▸ opens it in the list: its layers show indented under it,
selected, hidden, locked and restacked inside it like the others. Click a layer to select it
(Ctrl / Shift for several: they are the timeline's selection, so the preview, the inspector
and every edit work on them as usual), drag layers up and down to restack them (one per
track: edit.set_layer_order), the eye hides a layer and the padlock locks it (its track's
switches), double-click its name to rename it. The buttons add a text or a shape at the top,
copy, delete, group and restack the selection; right-click a layer for the same. A layer that
does not cover the picture's moment (time 0 - a static compound shows only that) is listed
dimmed.

Layers dragged in under an open group's row, among its layers, or onto a group's row go into
that group (移入群組, as the menu's 移入群組 does), the same on the canvas. Media dropped on
the list (from the media library, the Library tab, 內建素材, the compound list or the file
manager) become new layers where they are dropped (inside an open group there, or on a
group's row: in that group); an effect from the VFX
tab dropped on a layer goes onto it (between layers or below them: a filter layer there).
With Alt held, media dropped on a picture layer replace its source (替換素材); dropped on one of
several selected layers, every selected picture layer gets them (批量替換), one undo step.

A static component (靜態元件, components.py) is edited the same way, with its parameters listed
beside the layers (params.ParamList): right-click layers > 設為參數 makes a new parameter of one
of their properties (文字內容, 文字顏色, a shape's colours, 圖片, 顯示), or hands it to a
parameter that is there (one parameter can set several layers), 解除參數 lets it go; a layer a
parameter sets is marked ❖. A plain static compound has 轉為元件 at the top.
"""
from PySide6.QtCore import QItemSelectionModel, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu,
                               QPushButton, QVBoxLayout, QWidget)

from .. import assets, components, edit, project
from .params import ParamList, bound_tip, clip_name, param_menu
from .timeline import FX_MIME, MEDIA_MIME, group_menu
from . import inplace
from .menukeys import Menu

ROLE = Qt.UserRole
TRACK = Qt.UserRole + 1          # (track id, {"hidden", "locked"}) of a layer
PARENT = Qt.UserRole + 2         # the group it is in ("": the level itself)
MATTE = Qt.UserRole + 3          # a group's 遮罩: {on, invert}
KIND = Qt.UserRole + 4           # the clip's type
THUMB_H = 26                     # px: the height of a layer's picture
KINDS = {"image": "▧", "video": "▶", "text": "T", "compound": "▣", "group": "▾", "filter": "✦"}


class LayerList(QListWidget):
    """The layers; dropping one in a new place reports the new order (top first). Drops from
    elsewhere report where they land."""
    reordered = Signal(dict)                     # {group id or "": its layers' ids, top first}
    movedInto = Signal(list, str, list)          # layer ids, the group they go into, its layers' ids then (top first)
    mediaDropped = Signal(list, list, int, str)  # idents, file paths, layers above, group id or ""
    fxDropped = Signal(str, str, int)            # effect ref, the layer it was dropped on ("": between), layers above
    menuRequested = Signal(object)               # global position of a right-click on the selection
    replaceDropped = Signal(str, str)            # media ident, layer it was Alt-dropped on: 替換素材

    def __init__(self):
        super().__init__()
        self.replacing = []             # rows an Alt-drag would give its media to (lit while dragging)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSpacing(1)

    @staticmethod
    def _outside(e):
        md = e.mimeData()
        return not isinstance(e.source(), LayerList) and (md.hasFormat(MEDIA_MIME) or md.hasFormat(FX_MIME)
                                                          or md.hasUrls())

    def _opened(self, it):
        """Whether the row is a group open in the list (its layers follow it)."""
        gid = it.data(ROLE)
        return it.data(KIND) == "group" and any(self.item(i).data(PARENT) == gid for i in range(self.count()))

    def _parent_below(self, above):
        """The group a layer put right under row `above` (None: at the top) is in."""
        if above is None:
            return ""
        return above.data(ROLE) if self._opened(above) else (above.data(PARENT) or "")

    def _on_group(self, pos):
        """The group row in the middle of which pos is (a drop there goes into it), or None."""
        it = self.itemAt(pos.toPoint())
        if it is None or it.data(KIND) != "group":
            return None
        r = self.visualItemRect(it)
        return it if abs(pos.y() - r.center().y()) < r.height() / 4 else None

    def drop_target(self, pos):
        """(group id or "", how many of its layers are above) for a drop at pos: between two rows
        (the nearer gap), in the group whose layers are there; on a group's row: at its top."""
        g = self._on_group(pos)
        if g is not None:
            return g.data(ROLE), 0
        it = self.itemAt(pos.toPoint())
        row = self.count() if it is None else \
            self.row(it) + (1 if pos.y() > self.visualItemRect(it).center().y() else 0)
        parent = self._parent_below(self.item(row - 1) if row > 0 else None)
        return parent, sum(1 for i in range(row) if (self.item(i).data(PARENT) or "") == parent)

    def drop_index(self, pos):
        """How many layers of the level (open groups' layers not counted) are above a drop at pos."""
        parent, above = self.drop_target(pos)
        return above if not parent else 0

    def orders(self):
        """{group id or "": its layers' ids in the order the list shows them}."""
        out = {}
        for i in range(self.count()):
            it = self.item(i)
            out.setdefault(it.data(PARENT) or "", []).append(it.data(ROLE))
        return out

    def dragEnterEvent(self, e):
        if self._outside(e):
            e.setDropAction(Qt.CopyAction)
            e.accept()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if self._outside(e):
            e.setDropAction(Qt.CopyAction)
            e.accept()
            lit = self._replace_rows(e)
            if lit != self.replacing:
                self.replacing = lit
                self.viewport().update()
        else:
            super().dragMoveEvent(e)

    def dragLeaveEvent(self, e):
        self.replacing = []
        self.viewport().update()
        super().dragLeaveEvent(e)

    def _replace_rows(self, e):
        """With Alt held, media over a picture layer replaces its source: that row, and the
        other selected picture layers when it is selected (批量替換)."""
        alt = (e.modifiers() | QApplication.queryKeyboardModifiers()) & Qt.AltModifier
        it = self.itemAt(e.position().toPoint())
        if not alt or it is None or not e.mimeData().hasFormat(MEDIA_MIME) or it.data(KIND) not in edit.REPLACEABLE:
            return []
        if not it.isSelected():
            return [it]
        return [it] + [x for x in self.selectedItems() if x is not it and x.data(KIND) in edit.REPLACEABLE]

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self.replacing:
            return
        p = QPainter(self.viewport())
        for i, it in enumerate(self.replacing):
            r = self.visualItemRect(it).adjusted(1, 1, -2, -2)
            p.setPen(QPen(QColor("#ffb020"), 2))
            p.fillRect(r, QColor(255, 176, 32, 40))
            p.drawRect(r)
            if i == 0:
                p.setPen(QColor("#ffd34d"))
                n = len(self.replacing)
                p.drawText(r.adjusted(0, 0, -8, 0), Qt.AlignVCenter | Qt.AlignRight,
                           "替換素材" + (f"（{n} 個）" if n > 1 else ""))
    def dropEvent(self, e):
        if not self._outside(e):
            self._drop_inside(e)
            return
        md, pos = e.mimeData(), e.position()
        group, at = self.drop_target(pos)
        lit, self.replacing = self._replace_rows(e), []
        self.viewport().update()
        if lit:                                         # Alt: the layer's (layers') source
            ident = bytes(md.data(MEDIA_MIME)).decode("utf-8").split(",")[0]
            self.replaceDropped.emit(ident, lit[0].data(ROLE))
        elif md.hasFormat(FX_MIME):
            it = self.itemAt(pos.toPoint())
            self.fxDropped.emit(bytes(md.data(FX_MIME)).decode("utf-8"), it.data(ROLE) if it else "", at)
        elif md.hasFormat(MEDIA_MIME):
            ids = [i for i in bytes(md.data(MEDIA_MIME)).decode("utf-8").split(",") if i]
            self.mediaDropped.emit(ids, [], at, group)
        else:
            self.mediaDropped.emit([], [u.toLocalFile() for u in md.urls() if u.isLocalFile()], at, group)
        e.setDropAction(Qt.CopyAction)
        e.accept()

    def _drop_inside(self, e):
        """Layers dragged within the list: restacked in their own groups, or into another group
        (under an open group's row or among its layers, or on a group's row)."""
        moving = self.selectedItems()
        ids = [it.data(ROLE) for it in moving]
        onto = self._on_group(e.position())
        if onto is not None and onto.data(ROLE) not in ids:          # on a group's row: into it, on top
            gid = onto.data(ROLE)
            inner = [self.item(i).data(ROLE) for i in range(self.count())
                     if self.item(i).data(PARENT) == gid and self.item(i).data(ROLE) not in ids]
            e.ignore()
            self.movedInto.emit(ids, gid, ids + inner)
            return
        super().dropEvent(e)
        if moving:
            r = min(self.row(it) for it in moving)
            above = next((self.item(i) for i in range(r - 1, -1, -1) if not self.item(i).isSelected()), None)
            parent = self._parent_below(above)
            into = [it for it in moving if (it.data(PARENT) or "") != parent]
            if parent and into and not any(it.data(ROLE) == parent for it in moving):
                order = [self.item(i).data(ROLE) for i in range(self.count())
                         if (self.item(i).data(PARENT) or "") == parent or self.item(i) in into]
                self.movedInto.emit([it.data(ROLE) for it in into], parent, order)
                return
        self.reordered.emit(self.orders())         # (a layer stays in its own group)

    def contextMenuEvent(self, e):
        it = self.itemAt(e.pos())
        if it is not None and not it.isSelected():
            self.setCurrentItem(it)                 # (a right-click on another layer picks it)
        if not self.selectedItems():
            return
        self.menuRequested.emit(e.globalPos())


class LayerRow(QWidget):
    def __init__(self, c, track, shown, depth=0, thumb=None, opened=None, mask=None, params=()):
        """opened: for a group, whether it is open in the list (None: not a group); mask: when it
        is its group's mask (the bottom track of a group whose bottom object is a mask), that
        group's matte; params: [(param, prop)] of a component that set this layer."""
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 1, 4, 1)
        lay.setSpacing(4)
        self.eye = QPushButton("●" if not track.get("hidden") else "○")
        self.eye.setObjectName("tool")
        self.eye.setFixedSize(22, 22)
        self.eye.setToolTip("顯示 / 隱藏這個圖層")
        self.lock = QPushButton("🔒" if track.get("locked") else "·")
        self.lock.setObjectName("tool")
        self.lock.setFixedSize(22, 22)
        self.lock.setToolTip("鎖定這個圖層（不能被選取或移動）")
        kind = "static" if project.is_static(c) else c["type"]
        tag = QLabel("◧" if kind == "static" else KINDS.get(c["type"], "·"))
        tag.setFixedWidth(16)
        tag.setAlignment(Qt.AlignCenter)
        self.name = QLabel(clip_name(c))
        dim = track.get("hidden") or not shown
        self.name.setStyleSheet("color: #6a6a70;" if dim else "")
        if not shown:
            self.name.setToolTip("這個圖層不在畫面的那一格（時間 0），所以看不到")
        lay.addWidget(self.eye)
        lay.addWidget(self.lock)
        lay.addSpacing(18 * depth)
        self.arrow = None
        if opened is not None:
            self.arrow = QPushButton("▾" if opened else "▸")
            self.arrow.setObjectName("tool")
            self.arrow.setFixedSize(18, 22)
            self.arrow.setToolTip("收合群組" if opened else "展開群組：在清單裡顯示它的圖層")
            lay.addWidget(self.arrow)
        else:
            lay.addSpacing(18)
        pic = QLabel()
        pic.setFixedSize(round(THUMB_H * 16 / 9) + 2, THUMB_H + 2)
        pic.setAlignment(Qt.AlignCenter)
        pic.setStyleSheet("background: #1b1b1f; border: 1px solid #2c2c32;")
        if thumb is not None:
            pic.setPixmap(thumb)
        lay.addWidget(pic)
        lay.addWidget(tag)
        lay.addWidget(self.name)
        if mask:
            m = QLabel("反轉遮罩" if mask.get("invert") else "遮罩")
            m.setToolTip("群組的遮罩：在它上面的圖層挖掉它的形狀" if mask.get("invert")
                         else "群組的遮罩：裁切它上面的圖層")
            m.setStyleSheet("color: #c9a0ff; border: 1px solid #6a5090; border-radius: 3px; padding: 0 3px;")
            lay.addWidget(m)
        elif opened is not None and (c.get("matte") or {}).get("on"):
            m = QLabel("◐")
            m.setToolTip("最下面的物件當遮罩")
            m.setStyleSheet("color: #c9a0ff;")
            lay.addWidget(m)
        if c.get("effects"):
            lay.addWidget(QLabel("✦"))
        if params:
            m = QLabel(components.ICON)
            m.setToolTip(bound_tip(c, params))
            m.setStyleSheet("color: #8fa8ff;")
            lay.addWidget(m)
        lay.addStretch(1)


class LayerPanel(QWidget):
    selectionPicked = Signal(object, object)       # {clip ids}, the primary one
    orderChanged = Signal(dict)                    # {group id or "": its layers' ids, top first}
    flagToggled = Signal(str, str, bool)           # track id, "hidden" / "locked", on
    flagsToggled = Signal(list, str, bool)         # the same for several layers' tracks
    renameRequested = Signal(str)                  # clip id
    actionRequested = Signal(str)                  # "text", "copy", "delete", "group", "up", "down"
    shapeRequested = Signal(str)                   # an asset ident (assets.ident): a shape at the top
    mediaDropped = Signal(list, list, int, str)    # idents, file paths, layers above the drop, group id or ""
    movedInto = Signal(list, str, list)            # layer ids, group id, that group's layers then (top first)
    fxDropped = Signal(str, str, int)              # effect ref, layer it landed on or "", layers above
    replaceDropped = Signal(str, str)              # media ident, layer it was Alt-dropped on (替換素材)
    paramBind = Signal(str, str, list)             # parameter id ("": a new one), prop, layer ids
    paramUnbind = Signal(list)                     # [(layer id, prop)] no parameter sets any more
    paramAction = Signal(str, str)                 # "default" / "rename" / "up" / "down" / "delete", parameter id
    defaultDropped = Signal(str, str)              # parameter id, a picture dropped on it
    componentRequested = Signal()                  # 轉為元件: the open static compound becomes a component

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filling = False
        self.thumb = None               # thumb(clip, level) -> QPixmap or None: a layer's small picture
        self.opened = set()             # groups open in the list
        self._shown = None              # (level, selected ids, primary): what the list shows
        outer = QHBoxLayout(self)                   # the layers, and a component's parameters beside them
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(12)
        lay = QVBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(lay, 3)
        head = QHBoxLayout()
        title = QLabel("圖層")
        title.setObjectName("title")
        head.addWidget(title)
        self.note = QLabel("靜態複合片段：做一張圖，用圖層排好上下順序")
        self.note.setStyleSheet("color: #8a8a90;")
        head.addWidget(self.note, 1)
        self.to_component = QPushButton("轉為元件")
        self.to_component.setToolTip("變成元件：圖層的文字、顏色、圖片和顯示開關可以設成參數，"
                                     "每個使用它的片段在屬性裡設定自己的")
        self.to_component.clicked.connect(self.componentRequested)
        head.addWidget(self.to_component)
        lay.addLayout(head)
        self.list = LayerList()
        self.list.itemSelectionChanged.connect(self._selected)
        self.list.reordered.connect(self.orderChanged)
        self.list.itemDoubleClicked.connect(self._rename)
        self.list.mediaDropped.connect(self.mediaDropped)
        self.list.movedInto.connect(self.movedInto)
        self.list.fxDropped.connect(self.fxDropped)
        self.list.replaceDropped.connect(self.replaceDropped)
        self.list.menuRequested.connect(self._menu)
        lay.addWidget(self.list, 1)
        bar = QHBoxLayout()
        bar.setSpacing(3)

        def button(text, tip, action):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda: self.actionRequested.emit(action))
            bar.addWidget(b)
            return b
        button("文字", "在最上面加一個文字圖層", "text")
        shapes = QPushButton("形狀 ▾")
        shapes.setToolTip("在最上面加一個形狀（顏色用「內建素材」分頁的兩個顏色）")
        menu = QMenu(shapes)
        for a in assets.ASSETS:
            if a.cat == "shape":
                menu.addAction(a.name, lambda k=a.key: self.shapeRequested.emit(k))
        shapes.setMenu(menu)
        bar.addWidget(shapes)
        bar.addSpacing(8)
        button("上移", "選取的圖層往上一層", "up")
        button("下移", "選取的圖層往下一層", "down")
        button("群組", "把選取的圖層放進一個群組（Ctrl+G）", "group")
        button("複製", "複製選取的圖層", "copy")
        button("刪除", "刪除選取的圖層", "delete")
        bar.addStretch(1)
        lay.addLayout(bar)
        self.params_box = ParamList()               # a component's parameters (to the right)
        self.params_box.layout().setContentsMargins(0, 0, 0, 0)      # its title level with 圖層
        self.params_box.selectionPicked.connect(self.selectionPicked)
        self.params_box.paramUnbind.connect(self.paramUnbind)
        self.params_box.paramAction.connect(self.paramAction)
        self.params_box.defaultDropped.connect(self.defaultDropped)
        self.params = self.params_box.list
        outer.addWidget(self.params_box, 2)

    def rename_current(self):
        """F2: rename the one selected layer; False otherwise."""
        items = self.list.selectedItems()
        if len(items) != 1:
            return False
        self._rename(items[0])
        return True

    def _rename(self, it):
        """Rename a layer, the name field over its name in the row."""
        row = self.list.itemWidget(it)
        if isinstance(row, LayerRow):
            inplace.hint(row.name)
        self.renameRequested.emit(it.data(ROLE))

    def _menu(self, where):
        """Right-click on the selected layers: what the buttons do, and rename / hide / lock."""
        items = self.list.selectedItems()
        menu = Menu(self)
        if items:                                          # (several: all get the one name)
            menu.addAction("重新命名" if len(items) == 1 else f"全部重新命名（{len(items)} 個）",
                           lambda it=items[0]: self._rename(it))
        for text, action in (("上移", "up"), ("下移", "down"), ("建立群組", "group"), ("複製", "copy"),
                             ("刪除", "delete")):
            menu.addAction(text, lambda a=action: self.actionRequested.emit(a))
        level = self._shown[0] if self._shown else None
        if level is not None:                               # 移入群組: one of the picture's groups
            ids = {it.data(ROLE) for it in items}
            skip = set(ids)
            for cid in ids:
                c = edit.find(level, cid)[1]
                if project.is_group(c):
                    skip |= {k["id"] for k in project.walk_clips(c["tracks"])}
            group_menu(menu, level, skip, lambda g: self.actionRequested.emit("into:" + g), (0, 1))
        if level is not None and components.is_component(level):
            menu.addSeparator()
            param_menu(menu, level, [edit.find(level, it.data(ROLE))[1] for it in items],
                       self.paramBind.emit, self.paramUnbind.emit)
            menu.addSeparator()
        mattes = [it.data(MATTE) for it in items if it.data(MATTE) is not None]
        if mattes:                                         # groups: their bottom object cuts the rest
            act = menu.addAction("最下面的物件當遮罩", lambda: self.actionRequested.emit("group_matte"))
            act.setCheckable(True)
            act.setChecked(all(m["on"] for m in mattes))
            if all(m["on"] for m in mattes):
                act = menu.addAction("反轉遮罩", lambda: self.actionRequested.emit("group_invert"))
                act.setCheckable(True)
                act.setChecked(all(m["invert"] for m in mattes))
        menu.addSeparator()
        tracks = [it.data(TRACK) for it in items]               # (track id, its switches)
        for text, flag in (("隱藏 / 顯示", "hidden"), ("鎖定 / 解鎖", "locked")):
            on = not all(t[1].get(flag) for t in tracks)         # all on: off, else on
            menu.addAction(text, lambda f=flag, on=on: self.flagsToggled.emit([t[0] for t in tracks], f, on))
        menu.exec(where)

    def set_layers(self, level, selected_ids, primary):
        """Show the layers of level (a static compound's content), selection included."""
        self._shown = (level, set(selected_ids), primary)
        comp = components.is_component(level)
        self.note.setText("元件：圖層的屬性可以設成參數，每個使用它的片段自己設定" if comp
                          else "靜態複合片段：做一張圖，用圖層排好上下順序")
        self.to_component.setVisible(bool(level.get("static")) and not comp)
        self.params_box.setVisible(comp)
        bound = components.bound(level) if comp else {}
        if comp:
            self.params_box.set_component(level)
        self._filling = True
        bar = self.list.verticalScrollBar().value()
        self.list.clear()
        tracks = {c["id"]: t for t in project.all_tracks(level["tracks"]) for c in t["clips"]}

        def add(holder, depth, parent, at_us, locked):
            masked = parent and (holder.get("matte") or {}).get("on")
            bottom = next(iter(project.matte_tracks(holder["tracks"])), None) if masked else None
            for c in edit.layers(holder):
                t = tracks[c["id"]]
                lock = locked or project.locked(t)
                it = QListWidgetItem()
                it.setData(ROLE, c["id"])
                it.setData(TRACK, (t["id"], {"hidden": bool(t.get("hidden")), "locked": bool(t.get("locked"))}))
                it.setData(PARENT, parent)
                it.setData(KIND, c["type"])
                it.setData(MATTE, {k: bool((c.get("matte") or {}).get(k)) for k in ("on", "invert")}
                           if project.is_group(c) else None)
                it.setSizeHint(QSize(200, THUMB_H + 6))
                if lock:
                    it.setFlags(it.flags() & ~Qt.ItemIsSelectable)
                self.list.addItem(it)
                group = project.is_group(c)
                opened = c["id"] in self.opened if group else None
                row = LayerRow(c, t, c["start_us"] <= at_us < c["start_us"] + c["duration_us"], depth,
                               self.thumb(c, level) if self.thumb else None, opened,
                               holder["matte"] if t is bottom else None, bound.get(c["id"], ()))
                row.eye.clicked.connect(lambda _=False, t=t: self.flagToggled.emit(t["id"], "hidden", not t.get("hidden")))
                row.lock.clicked.connect(lambda _=False, t=t: self.flagToggled.emit(t["id"], "locked", not t.get("locked")))
                if row.arrow is not None:
                    row.arrow.clicked.connect(lambda _=False, g=c["id"]: self.toggle_group(g))
                self.list.setItemWidget(it, row)
                it.setSelected(c["id"] in selected_ids)
                if c["id"] == primary:
                    self.list.setCurrentItem(it, QItemSelectionModel.NoUpdate)
                if opened:                                  # (its clips' times are its own)
                    add(c, depth + 1, c["id"], at_us - c["start_us"], lock)
        add(level, 0, "", 0, False)
        self.list.verticalScrollBar().setValue(bar)
        self._filling = False

    def toggle_group(self, gid):
        """Open or close a group in the list."""
        self.opened ^= {gid}
        if self._shown:
            cur = self.list.currentItem()
            self.set_layers(self._shown[0], {it.data(ROLE) for it in self.list.selectedItems()},
                            cur.data(ROLE) if cur is not None else None)

    def _selected(self):
        if self._filling:
            return
        ids = {it.data(ROLE) for it in self.list.selectedItems()}
        cur = self.list.currentItem()
        primary = cur.data(ROLE) if cur is not None and cur.data(ROLE) in ids else next(iter(ids), None)
        self.selectionPicked.emit(ids, primary)
