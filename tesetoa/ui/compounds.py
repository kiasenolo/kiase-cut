"""Compound browser: the project's shared compounds (reusable like media).

Each compound is listed once with how many clips show it; under it, where it is used.
Drag a compound onto the timeline to place another clip showing it (every clip shows the
same content, so editing one edits all). Click a use to select it on its timeline,
double-click a use (or the compound) to open it. Right-click to rename a compound or
delete an unused one.
"""
from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QLabel, QMenu, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from .. import project
from .library import MIME

US = 1_000_000
PREFIX = "cmp:"                # in the media drag format: "cmp:<compound id>"


def stamp(us):
    s = us / US
    return f"{int(s // 60):02d}:{s % 60:05.2f}"


class CompoundTree(QTreeWidget):
    def __init__(self):
        super().__init__()
        self.setHeaderLabels(["複合片段", "位置", "長度"])
        self.setColumnWidth(0, 160)
        self.setColumnWidth(1, 64)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)

    def mimeData(self, items):
        ids = [it.data(0, Qt.UserRole)[1] for it in items if it.data(0, Qt.UserRole)[0] == "def"]
        md = QMimeData()
        md.setData(MIME, ",".join(PREFIX + k for k in ids).encode())
        return md


class CompoundPanel(QWidget):
    showRequested = Signal(list, str)            # parent path (clip ids), clip id
    openRequested = Signal(list)                 # path of the compound clip to open (clip ids)
    renameRequested = Signal(str)                # compound id
    deleteRequested = Signal(str)                # compound id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tree = CompoundTree()
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemDoubleClicked.connect(self._double)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.empty = QLabel("這個專案沒有複合片段")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("color: #777;")
        hint = QLabel("拖到時間軸上重複使用；同一個複合片段的內容是共用的")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8a8a90;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.tree)
        lay.addWidget(self.empty)
        lay.addWidget(hint)
        self.open_path = []
        self.uses = {}

    def set_project(self, proj, open_path=()):
        """Fill the list; the compound being edited (open_path) is shown in bold."""
        self.open_path = list(open_path)
        expanded = {it.data(0, Qt.UserRole)[1] for it in self._items() if it.isExpanded()}
        self.tree.clear()
        comps = proj.get("compounds", {}) if proj else {}
        self.uses = project.compound_uses(proj) if proj else {}
        open_ids = set()
        if proj and self.open_path:
            for path, c in (u for us in self.uses.values() for u in us):
                if path + [c["id"]] == self.open_path:
                    open_ids.add(c["compound_id"])
        for kid, comp in sorted(comps.items(), key=lambda kv: kv[1].get("name") or ""):
            uses = self.uses.get(kid, [])
            it = QTreeWidgetItem([f"{comp.get('name') or '複合片段'}  ×{len(uses)}", "",
                                  f"{(comp.get('duration_us') or 0) / US:.2f}s"])
            it.setData(0, Qt.UserRole, ("def", kid))
            it.setToolTip(0, "拖到時間軸上使用；按兩下進入編輯")
            it.setFlags(it.flags() | Qt.ItemIsDragEnabled)
            if kid in open_ids:
                f = it.font(0)
                f.setBold(True)
                it.setFont(0, f)
            if not uses:
                it.setForeground(0, Qt.gray)
            for path, c in uses:
                where = "主時間軸" if not path else f"{len(path)} 層內"
                sub = QTreeWidgetItem([c.get("name") or comp.get("name") or "片段", stamp(c["start_us"]),
                                       f"{c['duration_us'] / US:.2f}s"])
                sub.setData(0, Qt.UserRole, ("use", c["id"], path))
                sub.setToolTip(0, f"{where}：按一下選取，按兩下進入編輯")
                sub.setFlags(sub.flags() & ~Qt.ItemIsDragEnabled)
                it.addChild(sub)
            self.tree.addTopLevelItem(it)
            if kid in expanded or kid in open_ids:
                it.setExpanded(True)
        self.tree.setVisible(bool(comps))
        self.empty.setVisible(not comps)

    def _items(self):
        for i in range(self.tree.topLevelItemCount()):
            yield self.tree.topLevelItem(i)

    def _clicked(self, it, _col):
        d = it.data(0, Qt.UserRole)
        if d[0] == "use":
            self.showRequested.emit(list(d[2]), d[1])

    def _double(self, it, _col):
        d = it.data(0, Qt.UserRole)
        if d[0] == "use":
            self.openRequested.emit(list(d[2]) + [d[1]])
        elif self.uses.get(d[1]):
            path, c = self.uses[d[1]][0]
            self.openRequested.emit(path + [c["id"]])

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        if it is None or it.data(0, Qt.UserRole)[0] != "def":
            return
        kid = it.data(0, Qt.UserRole)[1]
        menu = QMenu(self)
        menu.addAction("重新命名…", lambda: self.renameRequested.emit(kid))
        a = menu.addAction("刪除（沒有使用時）", lambda: self.deleteRequested.emit(kid))
        a.setEnabled(not self.uses.get(kid))
        menu.exec(self.tree.viewport().mapToGlobal(pos))
