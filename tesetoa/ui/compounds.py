"""Compound clip list: every compound clip of the project as a tree (nested ones under the
clip that holds them). Click shows the clip on its timeline, double-click opens it."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

US = 1_000_000


def compounds(tracks, path=()):
    """[(path of the clip's parents (clip ids), clip, children)] in timeline order."""
    found = []
    for t in tracks:
        for c in t["clips"]:
            if c["type"] == "compound":
                found.append((list(path), c, compounds(c["compound"]["tracks"], path + (c["id"],))))
    found.sort(key=lambda x: x[1]["start_us"])
    return found


def stamp(us):
    s = us / US
    return f"{int(s // 60):02d}:{s % 60:05.2f}"


class CompoundPanel(QWidget):
    showRequested = Signal(list, str)            # parent path (clip ids), clip id
    openRequested = Signal(list)                 # path of the compound to open (clip ids)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["複合片段", "開始", "長度"])
        self.tree.setColumnWidth(0, 150)
        self.tree.setColumnWidth(1, 64)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemDoubleClicked.connect(self._double)
        self.empty = QLabel("這個專案沒有複合片段")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("color: #777;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.tree)
        lay.addWidget(self.empty)
        self.open_path = []

    def set_project(self, proj, open_path=()):
        """Fill the tree; the compound being edited (open_path) is shown in bold."""
        self.open_path = list(open_path)
        expanded = {it.data(0, Qt.UserRole)[1] for it in self._items() if it.isExpanded()}
        self.tree.clear()
        found = compounds(proj["tracks"]) if proj else []

        def add(parent, entries):
            for path, c, kids in entries:
                n = sum(1 for _ in self._count(kids))
                name = c.get("name") or "複合片段"
                it = QTreeWidgetItem([name + (f"  ({n})" if n else ""), stamp(c["start_us"]),
                                      f"{c['duration_us'] / US:.2f}s"])
                it.setData(0, Qt.UserRole, (path, c["id"]))
                it.setToolTip(0, "按一下：在時間軸上選取　按兩下：進入編輯")
                if path + [c["id"]] == self.open_path:
                    f = it.font(0)
                    f.setBold(True)
                    it.setFont(0, f)
                parent.addChild(it) if parent is not None else self.tree.addTopLevelItem(it)
                add(it, kids)
                if c["id"] in expanded or self.open_path[: len(path) + 1] == path + [c["id"]]:
                    it.setExpanded(True)

        add(None, found)
        self.tree.setVisible(bool(found))
        self.empty.setVisible(not found)

    def _count(self, entries):
        for _, _, kids in entries:
            yield 1
            yield from self._count(kids)

    def _items(self):
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            it = stack.pop()
            yield it
            stack += [it.child(i) for i in range(it.childCount())]

    def _clicked(self, it, _col):
        path, cid = it.data(0, Qt.UserRole)
        self.showRequested.emit(list(path), cid)

    def _double(self, it, _col):
        path, cid = it.data(0, Qt.UserRole)
        self.openRequested.emit(list(path) + [cid])
