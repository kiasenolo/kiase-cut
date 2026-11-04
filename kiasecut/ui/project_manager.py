"""Project manager: every project, as cards with their thumbnails (thumbnail.py), in folders.

Shown when the program starts without a project (and from 檔案 > 專案管理器…). It works like a
file manager over the projects folder (the 新專案 location): the folders on the left as a tree
(with 最近的專案 above it: the recent projects wherever they live, kept apart from the folders),
the folder's path above as buttons that go back to any level, and on the right folders that
group projects as cards first (double-click to go in, or 上一層), then the projects there, newest
first - a project folder shows as its project. It opens in the folder it was left in. Typing in
the search box looks through every folder. Under each card: the project's title (檔案 > 專案資訊), its folder's name
and when it was last saved - without a title, just the folder and the time.
Double-click (or 開啟) opens one; 新增專案… makes one in the folder shown, 新增資料夾 a folder,
開啟其他專案… does what the 檔案 menu does. Right-click a card to rename it, copy it (建立副本),
move it to another folder (or drag it onto a folder card / 上一層), delete it (to the recycle
bin: a project that owns its folder goes with the whole folder), open its folder or take its
thumbnail away. The open project cannot be deleted, moved or renamed here.
排序 orders the folders and the projects (each among their own) by name, the time they were last
changed or their size (a project that owns its folder: the whole folder), either way round; it is
remembered. The ✎ beside the path picks another projects folder (設定's 新專案預設位置), left in
`new_location`.
The choice is left in `choice`: ("open", project file), ("new", folder) or ("browse",);
`moved` lists (old, new) project files and `removed` the deleted ones (for the recent list).
"""
import datetime
import os

from PySide6.QtCore import QFile, QSettings, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListView, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSizePolicy, QSplitter,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import thumbnail, workspace
from . import ask, inplace
from .viewmode import list_toggle

SETTINGS = ("KiaseCut", "KiaseCut")
SORTS = (("最近修改", "time_desc"), ("最早修改", "time_asc"), ("名稱 A→Z", "name_asc"), ("名稱 Z→A", "name_desc"),
         ("大小（大→小）", "size_desc"), ("大小（小→大）", "size_asc"))


def size_of(path, project=False):
    """Bytes a folder (or a project: its folder when it owns one, else its file) takes up."""
    if project and not workspace.owns_folder(path):
        return os.path.getsize(path) if os.path.exists(path) else 0
    top = workspace.root_of(path) if project else path
    total = 0
    for d, _dirs, files in os.walk(top):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(d, f))
            except OSError:
                pass
    return total


def order(paths, how, projects=False):
    """paths in 排序's order (how: SORTS's keys)."""
    field, way = (how or "time_desc").rsplit("_", 1)
    if field == "name":
        key = lambda p: (label(p).split("\n")[0] if projects else os.path.basename(p)).lower()
    elif field == "size":
        key = lambda p: size_of(p, projects)
    else:
        key = lambda p: os.path.getmtime(p) if os.path.exists(p) else 0
    return sorted(paths, key=key, reverse=way == "desc")
from .menukeys import Menu

CARD = QSize(240, 135)
KIND = Qt.UserRole + 1          # "project", "folder" or "up" (the folder above)


def card(path):
    """The picture of a project's card: its thumbnail fitted in, or a blank one."""
    pix = QPixmap(CARD)
    pix.fill(QColor("#26262a"))
    p = QPainter(pix)
    img = thumbnail.load(path)
    if img is not None:
        img = img.scaled(CARD, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p.drawImage((CARD.width() - img.width()) // 2, (CARD.height() - img.height()) // 2, img)
    else:
        p.setPen(QColor("#6a6a72"))
        p.drawText(pix.rect(), Qt.AlignCenter, "沒有縮圖")
    p.end()
    return pix


def label(path):
    """A card's text: the project's title, its folder's name and when it was last saved, one
    per line (no title: just the folder and the time)."""
    when = datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
    folder = os.path.basename(workspace.root_of(path))
    title = workspace.stored_title(path)
    return "\n".join(([title] if title else []) + [folder, when])


def folder_card(up=False):
    """The picture of a folder card (up: the way back to the folder above)."""
    pix = QPixmap(CARD)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    w, h = CARD.width(), CARD.height()
    p.setBrush(QColor("#3a3a40" if up else "#c9a227"))
    p.drawRoundedRect(w * 0.28, h * 0.18, w * 0.2, h * 0.16, 6, 6)          # the tab
    p.setBrush(QColor("#2e2e33" if up else "#e0b93a"))
    p.drawRoundedRect(w * 0.28, h * 0.26, w * 0.44, h * 0.56, 8, 8)
    if up:
        p.setPen(QColor("#c0c0c4"))
        f = p.font()
        f.setPixelSize(34)
        p.setFont(f)
        p.drawText(pix.rect().adjusted(0, h * 0.1, 0, 0), Qt.AlignCenter, "↑")
    p.end()
    return pix


class Cards(QListWidget):
    """The cards; a card dragged onto a folder card (or 上一層) asks to go into that folder."""
    moveRequested = Signal(str, str)        # dragged project file or folder, folder to go into

    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)

    def _target(self, pos):
        it = self.itemAt(pos)
        return it if it is not None and it.data(KIND) in ("folder", "up") else None

    def dragMoveEvent(self, e):
        if e.source() is self and self._target(e.position().toPoint()) is not None:
            e.setDropAction(Qt.MoveAction)
            e.accept()
        else:
            e.ignore()

    def dropEvent(self, e):
        target = self._target(e.position().toPoint())
        moving = self.currentItem()
        e.ignore()                          # (never let the view move the items itself)
        if target is not None and moving is not None and moving is not target and moving.data(KIND) != "up":
            self.moveRequested.emit(moving.data(Qt.UserRole), target.data(Qt.UserRole))


class ProjectManager(QDialog):
    def __init__(self, parent, location, recent=(), current=None):
        """current: the project open in the editor (it is not deleted, moved or renamed here)."""
        super().__init__(parent)
        self.setWindowTitle("專案管理器")
        self.resize(900, 620)
        self.location, self.recent = location, list(recent)
        self.folder = location
        self.show_recent = False                    # the 最近的專案 node is picked (not a folder)
        last = str(QSettings(*SETTINGS).value("pm_folder") or "")
        if last and os.path.isdir(last) and self.inside(last):
            self.folder = last
        self.current = os.path.abspath(current) if current else None
        self.choice = None
        self.moved, self.removed = [], []
        self.new_location = None                    # ✎: another projects folder was picked
        top = QHBoxLayout()
        self.up_btn = QPushButton("上一層")
        self.up_btn.clicked.connect(self.go_up)
        self.where = QWidget()                      # the path as buttons, one for each level
        self.crumbs = QHBoxLayout(self.where)
        self.crumbs.setContentsMargins(0, 0, 0, 0)
        self.crumbs.setSpacing(2)
        self.where.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)     # a long path gives way
        self.search = QLineEdit()
        self.search.setMinimumWidth(220)
        self.search.setPlaceholderText("搜尋所有資料夾的專案…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self.fill())
        pen = QPushButton("✎")
        pen.setFixedWidth(30)
        pen.setToolTip("換一個專案資料夾（新專案預設存放的地方）")
        pen.clicked.connect(self.pick_location)
        self.sort = QComboBox()
        for text, key in SORTS:
            self.sort.addItem(text, key)
        s = QSettings(*SETTINGS)
        self.sort.setCurrentIndex(max(0, self.sort.findData(s.value("pm_sort", "time_desc"))))
        self.sort.setToolTip("排序（資料夾和專案各自排）")
        self.sort.currentIndexChanged.connect(lambda _i: (QSettings(*SETTINGS).setValue("pm_sort", self.sort.currentData()),
                                                          self.fill()))
        top.addWidget(self.up_btn)
        top.addWidget(self.where, 1)
        top.addWidget(pen)
        top.addWidget(self.sort)
        top.addWidget(self.search)
        self.view_top = top                         # (網格 / 列表: added once the list exists)
        self.list = Cards()
        self.list.setViewMode(QListView.IconMode)
        self.list.setIconSize(CARD)
        self.list.setGridSize(QSize(CARD.width() + 24, CARD.height() + 72))       # (three lines under it)
        self.list.setResizeMode(QListView.Adjust)
        self.list.setMovement(QListView.Snap)
        self.list.setWordWrap(True)
        self.list.setUniformItemSizes(True)
        self.list.itemActivated.connect(self._activated)
        self.list.currentItemChanged.connect(
            lambda cur, _old: self.open_btn.setEnabled(cur is not None and cur.data(KIND) == "project"))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.view_top.addWidget(list_toggle("projects", self.list, CARD, QSize(CARD.width() + 24, CARD.height() + 72),
                                            QSize(48, 27)))
        self.list.moveRequested.connect(self._move_into)
        for key, fn in (("F2", self.rename), ("Delete", self.delete)):      # the current card
            QShortcut(QKeySequence(key), self.list, lambda fn=fn: self._on_current(fn), context=Qt.WidgetShortcut)
        self.empty = QLabel("還沒有專案：按「新增專案…」開始")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("color: #777;")
        bottom = QHBoxLayout()
        new = QPushButton("新增專案…")
        new.clicked.connect(lambda: self._done(("new", self.folder)))
        folder = QPushButton("新增資料夾")
        folder.clicked.connect(self.make_folder)
        browse = QPushButton("開啟其他專案…")
        browse.clicked.connect(lambda: self._done(("browse",)))
        self.open_btn = QPushButton("開啟")
        self.open_btn.setDefault(True)
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(lambda: self.list.currentItem() and self._activated(self.list.currentItem()))
        close = QPushButton("關閉")
        close.clicked.connect(self.reject)
        for b in (new, folder, browse):
            bottom.addWidget(b)
        bottom.addStretch(1)
        bottom.addWidget(self.open_btn)
        bottom.addWidget(close)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(150)
        self.tree.itemExpanded.connect(self._expanded)
        self.tree.itemClicked.connect(self._tree_clicked)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.list, 1)
        rl.addWidget(self.empty, 1)
        self.split = QSplitter(Qt.Horizontal)
        self.split.addWidget(self.tree)
        self.split.addWidget(right)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([200, 700])
        self.split.setChildrenCollapsible(False)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.split, 1)
        lay.addLayout(bottom)
        self.build_tree()
        self.fill()

    def done(self, r):
        QSettings(*SETTINGS).setValue("pm_folder", self.folder)         # (it opens here next time)
        super().done(r)

    # -- the folder tree --------------------------------------------------------------------------
    def inside(self, folder):
        a, b = os.path.abspath(folder), os.path.abspath(self.location)
        return a == b or a.startswith(b.rstrip(os.sep) + os.sep)

    def build_tree(self):
        """The tree again: 最近的專案, then the projects folder with the folders open on the way to the one shown."""
        self.tree.blockSignals(True)
        self.tree.clear()
        rec = QTreeWidgetItem(["最近的專案"])
        rec.setData(0, Qt.UserRole, None)
        self.tree.addTopLevelItem(rec)
        root = QTreeWidgetItem([os.path.basename(self.location.rstrip("/\\")) or self.location])
        root.setData(0, Qt.UserRole, self.location)
        root.setToolTip(0, self.location)
        self.tree.addTopLevelItem(root)
        self._load(root)
        root.setExpanded(True)
        self.tree.blockSignals(False)
        self.sync_tree()

    def _load(self, item):
        """The folders under a tree item (a project folder is a project, not a folder here)."""
        item.takeChildren()
        for f in workspace.browse(item.data(0, Qt.UserRole))[0]:
            sub = QTreeWidgetItem([os.path.basename(f)])
            sub.setData(0, Qt.UserRole, f)
            sub.setToolTip(0, f)
            if workspace.browse(f)[0]:
                sub.addChild(QTreeWidgetItem())              # (an arrow: its own folders load when it opens)
            item.addChild(sub)

    def _expanded(self, item):
        if item.childCount() == 1 and item.child(0).data(0, Qt.UserRole) is None:
            self._load(item)

    def _tree_clicked(self, item, _col):
        path = item.data(0, Qt.UserRole)
        if path is None:
            self.show_recent = True
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self.fill()
        else:
            self.open_folder(path)

    def sync_tree(self):
        """Pick the node of what is shown, opening the folders on the way."""
        self.tree.blockSignals(True)
        if self.show_recent:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        else:
            item = self.tree.topLevelItem(1)
            rel = os.path.relpath(self.folder, self.location)
            for part in [] if rel == "." else rel.replace("\\", "/").split("/"):
                self._expanded(item)
                item.setExpanded(True)
                item = next((item.child(i) for i in range(item.childCount()) if item.child(i).text(0) == part), None)
                if item is None:
                    break
            if item is not None:
                self.tree.setCurrentItem(item)
        self.tree.blockSignals(False)

    # -- the cards --------------------------------------------------------------------------------
    def at_top(self):
        return os.path.abspath(self.folder) == os.path.abspath(self.location) or self.show_recent

    def fill(self):
        self.list.clear()
        text = self.search.text().strip().lower()
        searching = bool(text)
        if searching:
            folders, projects = [], workspace.find_all(self.location)
            projects += [p for p in workspace.find_projects(self.location, self.recent) if p not in projects]
        elif self.show_recent:              # the recent ones, wherever they live
            folders, projects = [], [os.path.abspath(p).replace("\\", "/") for p in self.recent if os.path.isfile(p)]
        else:
            folders, projects = workspace.browse(self.folder)
            if not self.at_top():
                it = QListWidgetItem(QIcon(folder_card(up=True)), "上一層")
                it.setData(Qt.UserRole, os.path.dirname(self.folder))
                it.setData(KIND, "up")
                self.list.addItem(it)
        folders, projects = order(folders, self.sort.currentData()), order(projects, self.sort.currentData(), True)
        for f in folders:
            it = QListWidgetItem(QIcon(folder_card()), os.path.basename(f))
            it.setData(Qt.UserRole, f)
            it.setData(KIND, "folder")
            it.setToolTip(f)
            self.list.addItem(it)
        for path in projects:
            it = QListWidgetItem(QIcon(card(path)), label(path))
            it.setData(Qt.UserRole, path)
            it.setData(KIND, "project")
            it.setToolTip(path)
            if searching and text not in it.text().lower():
                continue
            self.list.addItem(it)
        has = self.list.count() > 0
        self.list.setVisible(has)
        self.empty.setVisible(not has)
        self.empty.setText("沒有符合的專案" if searching else "還沒有最近開過的專案" if self.show_recent
                           else "這個資料夾是空的：按「新增專案…」或「新增資料夾」")
        if has:
            first = next((i for i in range(self.list.count()) if self.list.item(i).data(KIND) == "project"), 0)
            self.list.setCurrentRow(first)
        self.fill_crumbs()
        self.sync_tree()
        self.up_btn.setEnabled(not self.at_top() and not searching)

    def fill_crumbs(self):
        """The path above as buttons: each goes back to that level."""
        while self.crumbs.count():
            w = self.crumbs.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        if self.show_recent:
            names = [("最近的專案", None)]
        else:
            rel = os.path.relpath(self.folder, self.location)
            names = [(self.location, self.location)]
            at = self.location
            for part in [] if rel == "." else rel.replace("\\", "/").split("/"):
                at = os.path.join(at, part).replace("\\", "/")
                names.append((part, at))
        for i, (text, path) in enumerate(names):
            b = QPushButton(text if i else f"{os.path.basename(text.rstrip('/')) or text}")
            b.setFlat(True)
            b.setToolTip(path or "")
            b.setEnabled(path is not None and i < len(names) - 1)
            if path is not None:
                b.clicked.connect(lambda _=False, p=path: self.open_folder(p))
            self.crumbs.addWidget(b)
            if i < len(names) - 1:
                self.crumbs.addWidget(QLabel("›"))
        self.crumbs.addStretch(1)
        self.where.setToolTip(self.location if self.show_recent else self.folder)

    def refresh(self):
        """After folders were made, renamed, moved or deleted: the tree and the cards again."""
        self.build_tree()
        self.fill()

    def pick_location(self):
        """✎: browse another projects folder (and make it 新專案's place)."""
        d = QFileDialog.getExistingDirectory(self, "選擇專案資料夾", self.location)
        if d:
            self.location = self.new_location = d.replace("\\", "/")
            self.build_tree()
            self.open_folder(self.location)

    def paths(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                if self.list.item(i).data(KIND) == "project"]

    def open_folder(self, folder):
        self.folder, self.show_recent = folder, False
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.fill()

    def go_up(self):
        if not self.at_top():
            self.open_folder(os.path.dirname(self.folder))

    def _activated(self, it):
        kind, path = it.data(KIND), it.data(Qt.UserRole)
        if kind == "project":
            self._open(path)
        elif path:
            self.open_folder(path)

    def _open(self, path):
        if path:
            self._done(("open", path))

    def _done(self, choice):
        self.choice = choice
        self.accept()

    # -- file operations --------------------------------------------------------------------------
    def _is_open(self, path):
        if not self.current:
            return False
        p = os.path.abspath(path)
        return p == self.current or self.current.startswith(p.rstrip(os.sep) + os.sep)

    def _refuse_open(self, path):
        if self._is_open(path):
            QMessageBox.information(self, "專案管理器", "這個專案正在編輯中：先關掉它（開啟別的專案）再做這件事。")
            return True
        return False

    def _changed(self, old, new):
        self.moved.append((old, new))
        self.recent = [new if os.path.abspath(r) == os.path.abspath(old) else r for r in self.recent]

    def _moved_folder(self, old, new):
        """Projects inside a moved / renamed folder: their new paths."""
        old_a = os.path.abspath(old).rstrip(os.sep) + os.sep
        for r in list(self.recent):
            if os.path.abspath(r).startswith(old_a):
                self._changed(r, os.path.join(new, os.path.abspath(r)[len(old_a):]).replace("\\", "/"))

    def make_folder(self):
        name, ok = QInputDialog.getText(self, "新增資料夾", "名稱", text="新資料夾")
        if not ok:
            return
        try:
            workspace.new_folder(self.folder, name)
        except OSError as exc:
            QMessageBox.warning(self, "新增資料夾", str(exc))
        self.refresh()

    def _on_current(self, fn):
        it = self.list.currentItem()
        if it is not None and it.isSelected() and it.data(KIND) != "up":
            fn(it)

    def remove_thumbnail(self, it, path):
        """拿掉縮圖; a project with a _thumbnail compound asks first (saving would draw it back,
        so it is turned off until 套用縮圖)."""
        if thumbnail.has_compound(path) and not ask.question(
                self, "remove_thumbnail", "拿掉縮圖", "這個專案有「_thumbnail」靜態複合片段，縮圖是用它畫的。\n"
                "真的要拿掉嗎？之後儲存也不會再用它畫縮圖；\n"
                "要用回來：開啟專案，在複合片段清單對「_thumbnail」按右鍵 →「套用縮圖」。"):
            return
        try:
            thumbnail.remove(path)
        except OSError as exc:
            QMessageBox.warning(self, "拿掉縮圖", str(exc))
        it.setIcon(QIcon(card(path)))

    def rename(self, it):
        kind, path = it.data(KIND), it.data(Qt.UserRole)
        if self._refuse_open(path):
            return
        old = workspace.project_name(path) if kind == "project" else os.path.basename(path)
        inplace.item_hint(self.list, it)
        name, ok = inplace.ask_name(self, old)
        if not ok or not name.strip() or name.strip() == old:
            return
        try:
            if kind == "project":
                self._changed(path, workspace.rename_project(path, name))
            else:
                new = os.path.join(os.path.dirname(path), workspace.safe_name(name, old))
                if os.path.exists(new):
                    raise FileExistsError(f"「{name}」已經有了")
                os.rename(path, new)
                self._moved_folder(path, new)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "重新命名", str(exc))
        self.refresh()

    def duplicate(self, path):
        try:
            workspace.copy_project(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "建立副本", str(exc))
        self.fill()

    def _move_into(self, path, folder):
        if self._refuse_open(path):
            return
        try:
            if path.endswith(workspace.EXTS):
                self._changed(path, workspace.move_project(path, folder))
            else:
                new = workspace.move_folder(path, folder)
                self._moved_folder(path, new)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "移動", str(exc))
        self.refresh()

    def move_to(self, path):
        folder = QFileDialog.getExistingDirectory(self, "移到哪個資料夾", self.location)
        if folder:
            self._move_into(path, folder)

    def delete(self, it):
        kind, path = it.data(KIND), it.data(Qt.UserRole)
        if self._refuse_open(path):
            return
        if kind == "project":
            what = (f"專案「{workspace.project_name(path)}」和它的整個資料夾（素材、匯出的影片）"
                    if workspace.owns_folder(path) else f"專案檔「{os.path.basename(path)}」")
        else:
            what = f"資料夾「{os.path.basename(path)}」和裡面所有的專案"
        if not ask.question(self, "delete_project", "刪除", f"把{what}移到資源回收筒？"):
            return
        try:
            if kind == "project":
                workspace.remove_project(path, self.trash)
                self.removed.append(path)
            else:
                self.trash(path)
                self.removed += [r for r in self.recent
                                 if os.path.abspath(r).startswith(os.path.abspath(path).rstrip(os.sep) + os.sep)]
        except OSError as exc:
            QMessageBox.warning(self, "刪除", str(exc))
        self.recent = [r for r in self.recent if r not in self.removed]
        self.refresh()

    @staticmethod
    def trash(path):
        if not QFile.moveToTrash(path):
            raise OSError(f"無法把 {os.path.basename(path)} 移到資源回收筒")

    def _menu(self, pos):
        it = self.list.itemAt(pos)
        menu = Menu(self)
        if it is None or it.data(KIND) == "up":
            menu.addAction("新增資料夾", self.make_folder)
            menu.addAction("新增專案…", lambda: self._done(("new", self.folder)))
            menu.exec(self.list.viewport().mapToGlobal(pos))
            return
        path, kind = it.data(Qt.UserRole), it.data(KIND)
        if kind == "project":
            menu.addAction("開啟", lambda: self._open(path))
            menu.addAction("開啟專案資料夾", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(workspace.root_of(path))))
            a = menu.addAction("拿掉縮圖", lambda: self.remove_thumbnail(it, path))
            a.setEnabled(thumbnail.load(path) is not None)
            menu.addSeparator()
            menu.addAction("重新命名…", lambda: self.rename(it))
            menu.addAction("建立副本", lambda: self.duplicate(path))
            a = menu.addAction("移到資料夾…", lambda: self.move_to(path))
            a.setEnabled(workspace.owns_folder(path))
        else:
            menu.addAction("開啟", lambda: self.open_folder(path))
            menu.addAction("在檔案總管中開啟", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(path)))
            menu.addSeparator()
            menu.addAction("重新命名…", lambda: self.rename(it))
            menu.addAction("移到資料夾…", lambda: self.move_to(path))
        menu.addSeparator()
        menu.addAction("刪除（移到資源回收筒）…", lambda: self.delete(it))
        menu.exec(self.list.viewport().mapToGlobal(pos))
