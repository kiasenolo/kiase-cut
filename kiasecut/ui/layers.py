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

Media dropped on the list (from the media library, the Library tab, 內建素材, the compound
list or the file manager) become new layers where they are dropped; an effect from the VFX
tab dropped on a layer goes onto it (between layers or below them: a filter layer there).
"""
from PySide6.QtCore import QItemSelectionModel, QSize, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu,
                               QPushButton, QVBoxLayout, QWidget)

from .. import assets, edit, project
from .timeline import FX_MIME, MEDIA_MIME

ROLE = Qt.UserRole
TRACK = Qt.UserRole + 1          # (track id, {"hidden", "locked"}) of a layer
PARENT = Qt.UserRole + 2         # the group it is in ("": the level itself)
MATTE = Qt.UserRole + 3          # a group's 最下面的物件當遮罩: on
THUMB_H = 26                     # px: the height of a layer's picture
KINDS = {"image": "▧", "video": "▶", "text": "T", "compound": "▣", "group": "▾", "filter": "✦"}


class LayerList(QListWidget):
    """The layers; dropping one in a new place reports the new order (top first). Drops from
    elsewhere report where they land."""
    reordered = Signal(dict)                     # {group id or "": its layers' ids, top first}
    mediaDropped = Signal(list, list, int)       # media / asset / compound idents, file paths, layers above
    fxDropped = Signal(str, str, int)            # effect ref, the layer it was dropped on ("": between), layers above
    menuRequested = Signal(object)               # global position of a right-click on the selection

    def __init__(self):
        super().__init__()
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSpacing(1)

    @staticmethod
    def _outside(e):
        md = e.mimeData()
        return not isinstance(e.source(), LayerList) and (md.hasFormat(MEDIA_MIME) or md.hasFormat(FX_MIME)
                                                          or md.hasUrls())

    def drop_index(self, pos):
        """How many layers of the level (open groups' layers not counted) are above a drop at
        pos (it goes between two rows: the nearer gap)."""
        it = self.itemAt(pos.toPoint())
        row = self.count() if it is None else \
            self.row(it) + (1 if pos.y() > self.visualItemRect(it).center().y() else 0)
        return sum(1 for i in range(row) if not self.item(i).data(PARENT))

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
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if not self._outside(e):
            super().dropEvent(e)
            self.reordered.emit(self.orders())         # (a layer stays in its own group)
            return
        md, pos = e.mimeData(), e.position()
        at = self.drop_index(pos)
        if md.hasFormat(FX_MIME):
            it = self.itemAt(pos.toPoint())
            self.fxDropped.emit(bytes(md.data(FX_MIME)).decode("utf-8"), it.data(ROLE) if it else "", at)
        elif md.hasFormat(MEDIA_MIME):
            ids = [i for i in bytes(md.data(MEDIA_MIME)).decode("utf-8").split(",") if i]
            self.mediaDropped.emit(ids, [], at)
        else:
            self.mediaDropped.emit([], [u.toLocalFile() for u in md.urls() if u.isLocalFile()], at)
        e.setDropAction(Qt.CopyAction)
        e.accept()

    def contextMenuEvent(self, e):
        it = self.itemAt(e.pos())
        if it is not None and not it.isSelected():
            self.setCurrentItem(it)                 # (a right-click on another layer picks it)
        if not self.selectedItems():
            return
        self.menuRequested.emit(e.globalPos())


class LayerRow(QWidget):
    def __init__(self, c, track, shown, depth=0, thumb=None, opened=None, mask=False):
        """opened: for a group, whether it is open in the list (None: not a group); mask: it is
        its group's mask (the bottom track of a group whose bottom object is a mask)."""
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
        name = c.get("name") or ""
        if c["type"] == "text" and not c.get("named"):
            name = (c["text"].get("content") or "").replace("\n", " ")[:30]
        if c.get("asset"):
            name = name or assets.name_of(c["asset"])
        self.name = QLabel(name or c["type"])
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
            m = QLabel("遮罩")
            m.setToolTip("群組的遮罩：裁切它上面的圖層")
            m.setStyleSheet("color: #c9a0ff; border: 1px solid #6a5090; border-radius: 3px; padding: 0 3px;")
            lay.addWidget(m)
        elif opened is not None and (c.get("matte") or {}).get("on"):
            m = QLabel("◐")
            m.setToolTip("最下面的物件當遮罩")
            m.setStyleSheet("color: #c9a0ff;")
            lay.addWidget(m)
        if c.get("effects"):
            lay.addWidget(QLabel("✦"))
        lay.addStretch(1)


class LayerPanel(QWidget):
    selectionPicked = Signal(object, object)       # {clip ids}, the primary one
    orderChanged = Signal(dict)                    # {group id or "": its layers' ids, top first}
    flagToggled = Signal(str, str, bool)           # track id, "hidden" / "locked", on
    flagsToggled = Signal(list, str, bool)         # the same for several layers' tracks
    renameRequested = Signal(str)                  # clip id
    actionRequested = Signal(str)                  # "text", "copy", "delete", "group", "up", "down"
    shapeRequested = Signal(str)                   # an asset ident (assets.ident): a shape at the top
    mediaDropped = Signal(list, list, int)         # idents, file paths, how many layers are above the drop
    fxDropped = Signal(str, str, int)              # effect ref, layer it landed on or "", layers above

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filling = False
        self.thumb = None               # thumb(clip, level) -> QPixmap or None: a layer's small picture
        self.opened = set()             # groups open in the list
        self._shown = None              # (level, selected ids, primary): what the list shows
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        head = QHBoxLayout()
        title = QLabel("圖層")
        title.setObjectName("title")
        head.addWidget(title)
        self.note = QLabel("靜態複合片段：做一張圖，用圖層排好上下順序")
        self.note.setStyleSheet("color: #8a8a90;")
        head.addWidget(self.note, 1)
        lay.addLayout(head)
        self.list = LayerList()
        self.list.itemSelectionChanged.connect(self._selected)
        self.list.reordered.connect(self.orderChanged)
        self.list.itemDoubleClicked.connect(lambda it: self.renameRequested.emit(it.data(ROLE)))
        self.list.mediaDropped.connect(self.mediaDropped)
        self.list.fxDropped.connect(self.fxDropped)
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

    def _menu(self, where):
        """Right-click on the selected layers: what the buttons do, and rename / hide / lock."""
        items = self.list.selectedItems()
        menu = QMenu(self)
        if len(items) == 1:
            cid = items[0].data(ROLE)
            menu.addAction("重新命名", lambda: self.renameRequested.emit(cid))
        for text, action in (("上移", "up"), ("下移", "down"), ("群組", "group"), ("複製", "copy"),
                             ("刪除", "delete")):
            menu.addAction(text, lambda a=action: self.actionRequested.emit(a))
        mattes = [it.data(MATTE) for it in items if it.data(MATTE) is not None]
        if mattes:                                         # groups: their bottom object cuts the rest
            act = menu.addAction("最下面的物件當遮罩", lambda: self.actionRequested.emit("group_matte"))
            act.setCheckable(True)
            act.setChecked(all(mattes))
        menu.addSeparator()
        tracks = [it.data(TRACK) for it in items]               # (track id, its switches)
        for text, flag in (("隱藏 / 顯示", "hidden"), ("鎖定 / 解鎖", "locked")):
            on = not all(t[1].get(flag) for t in tracks)         # all on: off, else on
            menu.addAction(text, lambda f=flag, on=on: self.flagsToggled.emit([t[0] for t in tracks], f, on))
        menu.exec(where)

    def set_layers(self, level, selected_ids, primary):
        """Show the layers of level (a static compound's content), selection included."""
        self._shown = (level, set(selected_ids), primary)
        self._filling = True
        bar = self.list.verticalScrollBar().value()
        self.list.clear()
        tracks = {c["id"]: t for t in project.all_tracks(level["tracks"]) for c in t["clips"]}

        def add(holder, depth, parent, at_us, locked):
            masked = parent and (holder.get("matte") or {}).get("on")
            bottom = next((t for t in holder["tracks"] if t["kind"] != "audio"), None) if masked else None
            for c in edit.layers(holder):
                t = tracks[c["id"]]
                lock = locked or project.locked(t)
                it = QListWidgetItem()
                it.setData(ROLE, c["id"])
                it.setData(TRACK, (t["id"], {"hidden": bool(t.get("hidden")), "locked": bool(t.get("locked"))}))
                it.setData(PARENT, parent)
                it.setData(MATTE, bool((c.get("matte") or {}).get("on")) if project.is_group(c) else None)
                it.setSizeHint(QSize(200, THUMB_H + 6))
                if lock:
                    it.setFlags(it.flags() & ~Qt.ItemIsSelectable)
                self.list.addItem(it)
                group = project.is_group(c)
                opened = c["id"] in self.opened if group else None
                row = LayerRow(c, t, c["start_us"] <= at_us < c["start_us"] + c["duration_us"], depth,
                               self.thumb(c, level) if self.thumb else None, opened, t is bottom)
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
