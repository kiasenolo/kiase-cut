"""Compound browser: the project's timelines and shared compounds (reusable like media).

Timelines are listed first: drag one into another timeline to nest it (as in DaVinci
Resolve; the clip shows that timeline live), double-click to open it.

Each compound is listed once with how many clips show it; under it, where it is used.
Static compounds (◧ 靜態片段) are pictures built in the editor: their clips show one moment
of the content and can be any length.
Drag a compound onto the timeline to place another clip showing it (every clip shows the
same content, so editing one edits all). Click a use to select it on its timeline,
double-click a use (or the compound) to open it. Right-click to rename or delete a compound
(with the clips that show it), a timeline, or one use, and anywhere in the list to add a
timeline, a compound or a static compound (createRequested: "timeline" / "compound" /
"static"; the new compounds start empty, with a clip at the playhead to enter them by).
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
    showRequested = Signal(str, list, str)       # timeline id, parent path (clip ids), clip id
    openRequested = Signal(str, list)            # timeline id, path of the compound clip to open
    renameRequested = Signal(str)                # compound id
    deleteRequested = Signal(str)                # compound id
    timelineRequested = Signal(str)              # timeline id to open
    useDeleteRequested = Signal(str, list, str)  # timeline id, parent path, clip id: delete that clip
    createRequested = Signal(str)                # "timeline", "compound" or "static": a new empty one

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
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.tree)
        lay.addWidget(self.empty)
        self.open_path = []
        self.uses = {}
        self.tl_count = 1

    def set_project(self, proj, open_path=()):
        """Fill the list; the compound being edited (open_path) is shown in bold."""
        self.open_path = list(open_path)
        self.tl_count = len(proj.get("timelines", [])) if proj else 1
        expanded = {it.data(0, Qt.UserRole)[1] for it in self._items() if it.isExpanded()}
        self.tree.clear()
        comps = proj.get("compounds", {}) if proj else {}
        self.uses = project.compound_uses(proj) if proj else {}
        open_ids = set()
        if proj and self.open_path:
            for tl, path, c in (u for us in self.uses.values() for u in us):
                if tl == proj.get("active_timeline") and path + [c["id"]] == self.open_path:
                    open_ids.add(project.ref_of(c))
        timelines = [(t["id"], t) for t in proj.get("timelines", [])] if proj else []
        rows = timelines + sorted(comps.items(), key=lambda kv: kv[1].get("name") or "")
        for kid, comp in rows:
            uses = self.uses.get(kid, [])
            is_tl = kid.startswith("tl")
            static = bool(comp.get("static"))
            label = ("⧉ " if is_tl else "◧ " if static else "▣ ") + (comp.get("name") or "複合片段")
            it = QTreeWidgetItem([label + (f"  ×{len(uses)}" if uses or not is_tl else ""), "",
                                  "靜態" if static else f"{(comp.get('duration_us') or 0) / US:.2f}s"])
            it.setData(0, Qt.UserRole, ("def", kid))
            it.setToolTip(0, "時間線：拖進另一條時間線使用（巢狀）；按兩下打開" if is_tl
                          else "靜態片段：像圖片一樣使用，長度隨意；按兩下進入編輯它的畫面" if static
                          else "拖到時間軸上使用；按兩下進入編輯")
            it.setFlags(it.flags() | Qt.ItemIsDragEnabled)
            if kid in open_ids:
                f = it.font(0)
                f.setBold(True)
                it.setFont(0, f)
            if not uses and not is_tl:
                it.setForeground(0, Qt.gray)
            names = {t["id"]: t["name"] for t in proj.get("timelines", [])}
            for tl, path, c in uses:
                where = names.get(tl, "") + ("" if not path else f"，{len(path)} 層內")
                sub = QTreeWidgetItem([c.get("name") or comp.get("name") or "片段", stamp(c["start_us"]),
                                       f"{c['duration_us'] / US:.2f}s"])
                sub.setData(0, Qt.UserRole, ("use", c["id"], path, tl))
                if len(names) > 1:
                    sub.setText(1, f"{stamp(c['start_us'])}")
                    sub.setToolTip(1, names.get(tl, ""))
                sub.setToolTip(0, f"{where}：按一下選取，按兩下進入編輯")
                sub.setFlags(sub.flags() & ~Qt.ItemIsDragEnabled)
                it.addChild(sub)
            self.tree.addTopLevelItem(it)
            if kid in expanded or kid in open_ids:
                it.setExpanded(True)
        self.tree.setVisible(bool(rows))
        self.empty.setVisible(not rows)

    def _items(self):
        for i in range(self.tree.topLevelItemCount()):
            yield self.tree.topLevelItem(i)

    def _clicked(self, it, _col):
        d = it.data(0, Qt.UserRole)
        if d[0] == "use":
            self.showRequested.emit(d[3], list(d[2]), d[1])

    def _double(self, it, _col):
        d = it.data(0, Qt.UserRole)
        if d[0] == "use":
            self.openRequested.emit(d[3], list(d[2]) + [d[1]])
        elif d[1].startswith("tl"):
            self.timelineRequested.emit(d[1])
        elif self.uses.get(d[1]):
            tl, path, c = self.uses[d[1]][0]
            self.openRequested.emit(tl, path + [c["id"]])

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        menu = QMenu(self)
        if it is not None:
            self._item_actions(menu, it.data(0, Qt.UserRole))
            menu.addSeparator()
        self._create_actions(menu)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _create_actions(self, menu):
        for text, kind, tip in (("新增時間線", "timeline", "一條新的空白時間線"),
                                ("新增複合片段", "compound", "空白的複合片段，片段放在播放頭；按兩下進入編輯"),
                                ("新增靜態複合片段", "static", "空白的靜態片段（像圖片），片段放在播放頭；按兩下進入編輯")):
            a = menu.addAction(text, lambda k=kind: self.createRequested.emit(k))
            a.setToolTip(tip)
        menu.setToolTipsVisible(True)

    def _item_actions(self, menu, d):
        if d[0] == "use":
            menu.addAction("選取", lambda: self.showRequested.emit(d[3], list(d[2]), d[1]))
            menu.addAction("進入編輯", lambda: self.openRequested.emit(d[3], list(d[2]) + [d[1]]))
            menu.addSeparator()
            menu.addAction("刪除這個片段", lambda: self.useDeleteRequested.emit(d[3], list(d[2]), d[1]))
        else:
            kid = d[1]
            menu.addAction("重新命名…", lambda: self.renameRequested.emit(kid))
            if kid.startswith("tl"):
                a = menu.addAction("刪除時間線", lambda: self.deleteRequested.emit(kid))
                a.setEnabled(self.tl_count > 1)
            else:
                n = len(self.uses.get(kid, []))
                menu.addAction("刪除" + (f"（連同 {n} 個使用的片段）" if n else ""),
                               lambda: self.deleteRequested.emit(kid))
