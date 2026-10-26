"""The static compound editor (靜態複合片段 = a picture made in the editor): a layer list, as in
Photoshop, takes the timeline's place while a static compound is open.

Each picture clip is a layer, the top one first (edit.layers). Click a layer to select it
(Ctrl / Shift for several: they are the timeline's selection, so the preview, the inspector
and every edit work on them as usual), drag layers up and down to restack them (one per
track: edit.set_layer_order), the eye hides a layer and the padlock locks it (its track's
switches), double-click its name to rename it. The buttons add a text or a shape at the top,
copy, delete, group and restack the selection. A layer that does not cover the picture's
moment (time 0 - a static compound shows only that) is listed dimmed.
"""
from PySide6.QtCore import QItemSelectionModel, QSize, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu,
                               QPushButton, QVBoxLayout, QWidget)

from .. import assets, edit, project

ROLE = Qt.UserRole
KINDS = {"image": "▧", "video": "▶", "text": "T", "compound": "▣", "group": "▾", "filter": "✦"}


class LayerList(QListWidget):
    """The layers; dropping one in a new place reports the new order (top first)."""
    reordered = Signal(list)

    def __init__(self):
        super().__init__()
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSpacing(1)

    def dropEvent(self, e):
        super().dropEvent(e)
        self.reordered.emit([self.item(i).data(ROLE) for i in range(self.count())])


class LayerRow(QWidget):
    def __init__(self, c, track, shown):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
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
        lay.addWidget(tag)
        lay.addWidget(self.name, 1)
        if c.get("effects"):
            lay.addWidget(QLabel("✦"))


class LayerPanel(QWidget):
    selectionPicked = Signal(object, object)       # {clip ids}, the primary one
    orderChanged = Signal(list)                    # clip ids, top first
    flagToggled = Signal(str, str, bool)           # track id, "hidden" / "locked", on
    renameRequested = Signal(str)                  # clip id
    actionRequested = Signal(str)                  # "text", "copy", "delete", "group", "up", "down"
    shapeRequested = Signal(str)                   # an asset ident (assets.ident): a shape at the top

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filling = False
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

    def set_layers(self, level, selected_ids, primary):
        """Show the layers of level (a static compound's content), selection included."""
        self._filling = True
        self.list.clear()
        tracks = {c["id"]: t for t in level["tracks"] for c in t["clips"]}
        for c in edit.layers(level):
            t = tracks[c["id"]]
            it = QListWidgetItem()
            it.setData(ROLE, c["id"])
            it.setSizeHint(QSize(200, 28))
            if project.locked(t):
                it.setFlags(it.flags() & ~Qt.ItemIsSelectable)
            self.list.addItem(it)
            row = LayerRow(c, t, c["start_us"] <= 0 < c["start_us"] + c["duration_us"])
            row.eye.clicked.connect(lambda _=False, t=t: self.flagToggled.emit(t["id"], "hidden", not t.get("hidden")))
            row.lock.clicked.connect(lambda _=False, t=t: self.flagToggled.emit(t["id"], "locked", not t.get("locked")))
            self.list.setItemWidget(it, row)
            it.setSelected(c["id"] in selected_ids)
            if c["id"] == primary:
                self.list.setCurrentItem(it, QItemSelectionModel.NoUpdate)
        self._filling = False

    def _selected(self):
        if self._filling:
            return
        ids = {it.data(ROLE) for it in self.list.selectedItems()}
        cur = self.list.currentItem()
        primary = cur.data(ROLE) if cur is not None and cur.data(ROLE) in ids else next(iter(ids), None)
        self.selectionPicked.emit(ids, primary)
