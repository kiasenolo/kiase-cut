"""The browser panels by kind (問17, 2026-11-24): 素材, 基礎物件, VFX and 複合片段 each show their things from wherever they
come from - 本專案 (this project's), 我的 Library (the user's own folder, every project's) and 內建 (KiaseCut's) - picked
with the row of buttons at the top. A kind that has nothing from one of the three has no button for it. The source picked
last is remembered per panel. The pages themselves are the panels there were before (library.LibraryPanel, assets_panel,
vfx_panel, vfxnodes, compounds and the Library's category trees); `mine_page` puts the Library's path and its 設定… above
the user's own ones, with tabs when a kind has several of the Library's categories (videos, images, sounds)."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QTabWidget, QVBoxLayout,
                               QWidget)

SOURCES = (("project", "本專案"), ("mine", "我的 Library"), ("builtin", "內建"))


class SourceBrowser(QWidget):
    """One kind of thing; pages {source: widget} for the sources it has."""
    sourceChanged = Signal(str)

    def __init__(self, key, pages, store=None, default=None, parent=None):
        super().__init__(parent)
        self.key, self.store = key, store              # store: (get(name, default), set(name, value)) to remember the source
        self.pages = {s: pages[s] for s, _t in SOURCES if s in pages}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        for s, title in SOURCES:
            if s not in self.pages:
                continue
            b = QPushButton(title)
            b.setObjectName("sourcebtn")
            b.setCheckable(True)
            b.setToolTip({"project": "這個專案裡的", "mine": "你自己的 Library：每個專案都能用",
                          "builtin": "KiaseCut 本身帶的"}[s])
            b.clicked.connect(lambda _=False, s=s: self.set_source(s))
            self.group.addButton(b)
            self.buttons[s] = b
            row.addWidget(b)
        row.addStretch()
        self.row = QWidget()
        self.row.setLayout(row)
        self.row.setVisible(len(self.pages) > 1)
        lay.addWidget(self.row)
        self.stack = QStackedWidget()
        for w in self.pages.values():
            self.stack.addWidget(w)
        lay.addWidget(self.stack, 1)
        first = default if default in self.pages else next(iter(self.pages))
        saved = store[0]("browser_source/" + key, first) if store else first
        self.set_source(saved if saved in self.pages else first, remember=False)

    def source(self):
        return next((s for s, w in self.pages.items() if w is self.stack.currentWidget()), None)

    def set_source(self, source, remember=True):
        if source not in self.pages:
            return
        self.stack.setCurrentWidget(self.pages[source])
        self.buttons[source].setChecked(True)
        if remember and self.store:
            self.store[1]("browser_source/" + self.key, source)
        self.sourceChanged.emit(source)


class MinePage(QWidget):
    """The user's own things of a kind: the Library's path and 設定… above them; tabs when there are several categories."""

    def __init__(self, panels, settings_cb, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        head.setContentsMargins(6, 2, 4, 0)
        self.head = QLabel("")
        self.head.setStyleSheet("color: #9a9aa0;")
        self.head.setWordWrap(True)
        gear = QPushButton("設定…")
        gear.setToolTip("Library 的位置和其他設定")
        gear.clicked.connect(settings_cb)
        head.addWidget(self.head, 1)
        head.addWidget(gear)
        lay.addLayout(head)
        self.panels = dict(panels)                     # {category key: (title, panel)}
        if len(self.panels) == 1:
            self.tabs = None
            lay.addWidget(next(iter(self.panels.values()))[1], 1)
        else:
            self.tabs = QTabWidget()
            self.tabs.tabBar().setUsesScrollButtons(False)
            self.tabs.tabBar().setExpanding(True)
            for _key, (title, panel) in self.panels.items():
                self.tabs.addTab(panel, title)
            lay.addWidget(self.tabs, 1)

    def set_root(self, root):
        self.head.setText("Library：" + root)
        self.head.setToolTip(root)

    def show_category(self, key):
        if self.tabs is not None and key in self.panels:
            self.tabs.setCurrentWidget(self.panels[key][1])


# where each of the Library's categories is shown: (browser key, its order there)
CATEGORY_BROWSER = {"videos": "library", "images": "library", "sounds": "library", "textstyles": "assets",
                    "filters": "vfx", "presets": "vfx", "compounds": "compounds"}
