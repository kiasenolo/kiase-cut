"""The VFX Node panel: the project's shared node effects (project.py _share_vfx). Many clips can use one VFX Node - one node
graph, so editing it in the node editor changes every use, while each clip keeps its own parameter values. The list says how
many clips use each; right-click (or the buttons) to apply one to the selected clips, rename, copy, keep it in the user's Library
(a 效果預設 file with the node effect) or delete it (the clips keep the effect as a copy of their own).
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from .menukeys import Menu


class VfxNodePanel(QWidget):
    applyRequested = Signal(str)                 # VFX Node id: put a use of it on the selected clips
    selectRequested = Signal(str)                # id: select the first clip that uses it (to edit it in the node editor)
    renameRequested = Signal(str)
    copyRequested = Signal(str)
    deleteRequested = Signal(str)
    libraryRequested = Signal(str)               # id: keep it in the user's Library
    importRequested = Signal()                   # take one from the Library into the project

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        note = QLabel("同一個 VFX Node 的所有使用共用一張節點圖：改一處，每個用它的片段都跟著變；數值各片段自己調。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #9a9aa0;")
        lay.addWidget(note)
        self.list = QListWidget()
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.itemDoubleClicked.connect(lambda it: self.selectRequested.emit(it.data(Qt.UserRole)))
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        use = QPushButton("套用到選取的片段")
        use.setToolTip("在選取的片段上加一個用這個 VFX Node 的節點效果")
        use.clicked.connect(lambda: self.current() and self.applyRequested.emit(self.current()))
        row.addWidget(use)
        lib = QPushButton("從 Library 匯入")
        lib.setToolTip("把 Library「效果預設」裡的節點效果拿進這個專案，成為一個 VFX Node")
        lib.clicked.connect(self.importRequested)
        row.addWidget(lib)
        lay.addLayout(row)

    def current(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def set_project(self, proj, uses):
        """Fill the list (uses: project.vfx_uses)."""
        keep = self.current()
        self.list.clear()
        for vid, m in (proj.get("vfx_nodes") or {}).items() if proj else ():
            n = len(uses.get(vid, ()))
            it = QListWidgetItem(f"{m['name']}  ×{n}")
            it.setData(Qt.UserRole, vid)
            it.setToolTip(f"{n} 個片段在用；按兩下選取第一個來編輯" if n else "還沒有片段在用；按「套用到選取的片段」")
            self.list.addItem(it)
            if vid == keep:
                self.list.setCurrentItem(it)

    def _menu(self, pos):
        it = self.list.itemAt(pos)
        if it is None:
            return
        vid = it.data(Qt.UserRole)
        menu = Menu(self)
        for text, sig in (("套用到選取的片段", self.applyRequested), ("選取第一個使用它的片段", self.selectRequested),
                          ("重新命名", self.renameRequested), ("建立副本", self.copyRequested),
                          ("存到 Library", self.libraryRequested), ("刪除（使用它的片段保留成各自的副本）", self.deleteRequested)):
            menu.addAction(text, lambda _=False, sig=sig: sig.emit(vid))
        menu.exec(self.list.viewport().mapToGlobal(pos))
