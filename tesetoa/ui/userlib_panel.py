"""The user's Library panel: one tab for each kind of thing (videos, images, sounds, filters,
text styles), each a tree of the folders and files of that part of the Library folder."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget

from .. import userlib
from .library import LibraryPanel

IMPORT_LABELS = {"videos": "加入影片", "images": "加入圖片", "sounds": "加入音效", "filters": "加入檔案",
                 "textstyles": "加入檔案"}


class UserLibraryPanel(QWidget):
    settingsRequested = Signal()
    newFilterRequested = Signal(object)         # folder id or None
    saveStyleRequested = Signal(object)         # folder id or None
    docRequested = Signal()
    checkRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        head.setContentsMargins(6, 4, 4, 0)
        self.head = QLabel("")
        self.head.setStyleSheet("color: #9a9aa0;")
        self.head.setWordWrap(True)
        gear = QPushButton("設定…")
        gear.setToolTip("Library 的位置和其他設定")
        gear.clicked.connect(self.settingsRequested)
        head.addWidget(self.head, 1)
        head.addWidget(gear)
        lay.addLayout(head)
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North)
        self.tabs.tabBar().setUsesScrollButtons(False)
        self.tabs.tabBar().setExpanding(True)
        self.panels = {}
        for key, title in userlib.CATEGORIES:
            panel = LibraryPanel(import_label=IMPORT_LABELS[key])
            panel.head.hide()
            self.panels[key] = panel
            self.tabs.addTab(panel, title)
        # things only some categories have
        f = self.panels["filters"]
        b = QPushButton("新增濾鏡")
        b.setToolTip("用範本建立一個新的 .glsl 濾鏡檔")
        b.clicked.connect(lambda: self.newFilterRequested.emit(f.current_folder()))
        f.bar2.addWidget(b)
        for text, tip, sig in (("說明", "濾鏡的寫法、參數與範例", self.docRequested),
                               ("檢查", "編譯所有濾鏡，列出有錯的", self.checkRequested)):
            x = QPushButton(text)
            x.setToolTip(tip)
            x.clicked.connect(sig)
            f.bar2.addWidget(x)
        t = self.panels["textstyles"]
        b = QPushButton("存目前文字")
        b.setToolTip("把選取的文字片段的字體、顏色等存成樣式")
        b.clicked.connect(lambda: self.saveStyleRequested.emit(t.current_folder()))
        t.bar2.addWidget(b)
        lay.addWidget(self.tabs, 1)
        self.setMinimumWidth(260)

    def set_root(self, root):
        self.head.setText("Library：" + root)
        self.head.setToolTip(root)

    def show_category(self, key):
        self.tabs.setCurrentWidget(self.panels[key])

    def current_key(self):
        w = self.tabs.currentWidget()
        return next((k for k, p in self.panels.items() if p is w), None)
