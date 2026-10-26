"""Media library panel: folders and media, drag into folders or onto the timeline."""
from PySide6.QtCore import QMimeData, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QMenu, QPushButton, QStyle,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import svgimage

MIME = "application/x-kiasecut-media"
ROLE_ID = Qt.UserRole
KIND_NAMES = {"image": "圖片", "video": "影片", "audio": "音訊", "filter": "濾鏡", "textstyle": "文字樣式",
              "compound": "複合片段"}


def svg_pixmap(path, w):
    """A thumbnail of an SVG (an empty pixmap when it cannot be read)."""
    try:
        return QPixmap.fromImage(svgimage.raster(path, w))
    except ValueError:
        return QPixmap()


def glyph_icon(text, color):
    """A small round-cornered tile with a few letters (for items that have no picture)."""
    pm = QPixmap(48, 28)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(0, 0, 48, 28, 5, 5)
    p.setPen(QColor("#ffffff"))
    f = QFont()
    f.setBold(True)
    f.setPixelSize(15)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, text)
    p.end()
    return QIcon(pm)


def fmt_dur(us):
    if not us:
        return ""
    s = us / 1_000_000
    return f"{int(s // 60)}:{s % 60:04.1f}"


def dropped_paths(md):
    """Local file / folder paths in a drag from the file manager."""
    return [u.toLocalFile() for u in md.urls() if u.isLocalFile()] if md.hasUrls() else []


class Tree(QTreeWidget):
    moved = Signal(str, object)        # id, target folder id or None
    filesDropped = Signal(list, object)   # paths from the file manager, target folder id or None

    def __init__(self):
        super().__init__()
        self.setHeaderLabels(["名稱", "類型", "長度"])
        self.setColumnWidth(0, 180)
        self.setIconSize(QSize(40, 24))
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)     # Shift / Ctrl pick several

    def mimeTypes(self):
        return [MIME]

    def mimeData(self, items):
        """The dragged ids, in the order the list shows them (top to bottom)."""
        md = QMimeData()
        md.setData(MIME, ",".join(i.data(0, ROLE_ID) for i in self.in_order(items)).encode())
        return md

    def in_order(self, items):
        rank, stack = {}, [self.topLevelItem(i) for i in reversed(range(self.topLevelItemCount()))]
        while stack:
            n = stack.pop()
            rank[n.data(0, ROLE_ID)] = len(rank)
            stack += [n.child(i) for i in reversed(range(n.childCount()))]
        return sorted(items, key=lambda i: rank.get(i.data(0, ROLE_ID), len(rank)))

    def dragEnterEvent(self, e):
        e.acceptProposedAction() if e.mimeData().hasFormat(MIME) or e.mimeData().hasUrls() else e.ignore()

    def dragMoveEvent(self, e):
        e.acceptProposedAction() if e.mimeData().hasFormat(MIME) or e.mimeData().hasUrls() else e.ignore()

    def _folder_at(self, pos):
        target = self.itemAt(pos)
        if target is None:
            return None
        tid = target.data(0, ROLE_ID)
        return tid if tid.startswith("f") else (target.parent().data(0, ROLE_ID) if target.parent() else None)

    def dropEvent(self, e):
        """The model decides; the tree is rebuilt from it afterwards."""
        folder = self._folder_at(e.position().toPoint())
        if not e.mimeData().hasFormat(MIME):                 # files from the file manager
            paths = dropped_paths(e.mimeData())
            if paths:
                self.filesDropped.emit(paths, folder)
                e.acceptProposedAction()
            else:
                e.ignore()
            return
        for ident in bytes(e.mimeData().data(MIME)).decode().split(","):
            if ident and ident != folder:
                self.moved.emit(ident, folder)
        e.ignore()


class LibraryPanel(QWidget):
    importRequested = Signal(object)          # folder id or None
    newFolderRequested = Signal(object)       # parent folder id or None
    renameRequested = Signal(str)
    deleteRequested = Signal(str)
    moveRequested = Signal(str, object)
    addRequested = Signal(str)                # item id -> add at the playhead
    filesDropped = Signal(list, object)       # paths, folder id or None (dragged in from outside)
    revealRequested = Signal(object)          # item / folder id, or None for the Media folder itself
    collectRequested = Signal()               # copy the media from outside the Media folder into it

    def __init__(self, parent=None, import_label="匯入素材"):
        super().__init__(parent)
        self.extra_menu = None                  # fn(menu, ident or None): more context menu entries
        self.setMinimumWidth(240)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.head = QLabel("")                  # the project folder this library mirrors
        self.head.setStyleSheet("color: #9a9aa0;")
        lay.addWidget(self.head)
        bar = QHBoxLayout()
        for label, fn in ((import_label, lambda: self.importRequested.emit(self.current_folder())),
                          ("新資料夾", lambda: self.newFolderRequested.emit(self.current_folder())),
                          ("開啟資料夾", lambda: self.revealRequested.emit(None))):
            b = QPushButton(label)
            b.clicked.connect(fn)
            bar.addWidget(b)
        lay.addLayout(bar)
        self.bar = bar
        self.bar2 = QHBoxLayout()               # a second row for panels with more buttons
        lay.addLayout(self.bar2)
        self.collect_btn = QPushButton("將不在素材資料夾的素材複製到素材資料夾")
        self.collect_btn.clicked.connect(self.collectRequested)
        self.collect_btn.hide()                 # shown while some media sit elsewhere: set_external()
        lay.addWidget(self.collect_btn)
        self.tree = Tree()
        self.tree.moved.connect(self.moveRequested)
        self.tree.filesDropped.connect(self.filesDropped)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._double(it))
        lay.addWidget(self.tree, 1)
        self.icons = {}

    def set_origin(self, text, tip=""):
        self.head.setText(text)
        self.head.setToolTip(tip)

    def set_external(self, n):
        """n media files used from outside the Media folder: the copy button shows while n > 0."""
        self.collect_btn.setVisible(n > 0)
        self.collect_btn.setToolTip(f"{n} 個素材不在素材資料夾裡（原檔不會被動到）")

    def current_folder(self):
        it = self.tree.currentItem()
        if it is None:
            return None
        ident = it.data(0, ROLE_ID)
        if ident.startswith("f"):
            return ident
        return it.parent().data(0, ROLE_ID) if it.parent() else None

    def _icon(self, it):
        if it["kind"] == "filter":
            return self.icons.setdefault("#filter", glyph_icon("fx", "#8a6f2e"))
        if it["kind"] == "textstyle":
            return self.icons.setdefault("#textstyle", glyph_icon("Aa", "#7c5574"))
        if it["kind"] == "compound":
            return self.icons.setdefault("#compound", glyph_icon("⧉", "#4a6a9a"))
        if it["kind"] == "image":
            if it["path"] not in self.icons:
                pm = svg_pixmap(it["path"], 160) if svgimage.is_svg(it["path"]) else QPixmap(it["path"])
                self.icons[it["path"]] = QIcon(pm.scaled(80, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                                               if not pm.isNull() else QPixmap())
            return self.icons[it["path"]]
        return self.style().standardIcon(QStyle.SP_MediaVolume if it["kind"] == "audio" else QStyle.SP_MediaPlay)

    def set_library(self, lib):
        expanded = {self.tree.topLevelItem(i).data(0, ROLE_ID) for i in range(self.tree.topLevelItemCount())
                    if self.tree.topLevelItem(i).isExpanded()}
        expanded |= self._expanded_ids()
        current = self.tree.currentItem().data(0, ROLE_ID) if self.tree.currentItem() else None
        self.tree.clear()
        nodes = {}
        folders = sorted(lib.get("folders", []), key=lambda f: f["name"])
        pending = list(folders)
        while pending:                               # parents before children
            rest = []
            for f in pending:
                if f["parent"] is None or f["parent"] in nodes:
                    node = QTreeWidgetItem([f["name"], "資料夾", ""])
                    node.setData(0, ROLE_ID, f["id"])
                    node.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
                    (nodes[f["parent"]].addChild(node) if f["parent"] else self.tree.addTopLevelItem(node))
                    nodes[f["id"]] = node
                else:
                    rest.append(f)
            if len(rest) == len(pending):
                break
            pending = rest
        for it in sorted(lib.get("items", []), key=lambda i: i["name"]):
            node = QTreeWidgetItem([it["name"], KIND_NAMES.get(it["kind"], it["kind"]), fmt_dur(it.get("duration_us"))])
            node.setData(0, ROLE_ID, it["id"])
            node.setIcon(0, self._icon(it))
            node.setToolTip(0, it["path"])
            parent = nodes.get(it.get("folder"))
            (parent.addChild(node) if parent else self.tree.addTopLevelItem(node))
            nodes[it["id"]] = node
        for ident, node in nodes.items():
            node.setExpanded(ident in expanded)
            if ident == current:
                self.tree.setCurrentItem(node)

    def _expanded_ids(self):
        out, stack = set(), [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            n = stack.pop()
            if n.isExpanded():
                out.add(n.data(0, ROLE_ID))
            stack += [n.child(i) for i in range(n.childCount())]
        return out

    def _double(self, node):
        ident = node.data(0, ROLE_ID)
        if not ident.startswith("f"):
            self.addRequested.emit(ident)

    def _menu(self, pos):
        node = self.tree.itemAt(pos)
        menu = QMenu(self)
        if node is not None:
            ident = node.data(0, ROLE_ID)
            if not ident.startswith("f"):
                menu.addAction("加到播放頭位置", lambda: self.addRequested.emit(ident))
            menu.addAction("重新命名…", lambda: self.renameRequested.emit(ident))
            menu.addAction("刪除（移到資源回收筒）", lambda: self.deleteRequested.emit(ident))
            menu.addAction("在檔案總管中顯示", lambda: self.revealRequested.emit(ident))
            menu.addSeparator()
        menu.addAction("新資料夾", lambda: self.newFolderRequested.emit(self.current_folder()))
        menu.addAction("匯入素材…", lambda: self.importRequested.emit(self.current_folder()))
        if self.extra_menu:
            menu.addSeparator()
            self.extra_menu(menu, node.data(0, ROLE_ID) if node is not None else None)
        menu.exec(self.tree.viewport().mapToGlobal(pos))
