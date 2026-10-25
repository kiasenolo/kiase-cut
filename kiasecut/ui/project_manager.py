"""Project manager: every project, as cards with their thumbnails (thumbnail.py).

Shown when the program starts without a project (and from 檔案 > 專案管理器…). It lists the
project files in the projects folder (the 新專案 location: there and one folder down) and
those in the recent list, newest first. A project without a thumbnail shows a blank card.
Double-click (or 開啟) opens one; 新增專案… and 開啟其他專案… do what the 檔案 menu does.
Right-click a card to open its folder or take its thumbnail away. The choice is left in
`choice`: ("open", project file), ("new",) or ("browse",).
"""
import datetime
import os

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem,
                               QMenu, QPushButton, QSizePolicy, QVBoxLayout)

from .. import thumbnail, workspace

CARD = QSize(240, 135)


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


class ProjectManager(QDialog):
    def __init__(self, parent, location, recent=()):
        super().__init__(parent)
        self.setWindowTitle("專案管理器")
        self.resize(880, 600)
        self.location, self.recent = location, list(recent)
        self.choice = None
        top = QHBoxLayout()
        where = QLabel(f"專案資料夾：{location}")
        where.setStyleSheet("color: #9a9aa0;")
        where.setToolTip(location)
        where.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)     # a long path gives way
        self.search = QLineEdit()
        self.search.setMinimumWidth(220)
        self.search.setPlaceholderText("搜尋專案…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        top.addWidget(where, 1)
        top.addWidget(self.search)
        self.list = QListWidget()
        self.list.setViewMode(QListView.IconMode)
        self.list.setIconSize(CARD)
        self.list.setGridSize(QSize(CARD.width() + 24, CARD.height() + 56))
        self.list.setResizeMode(QListView.Adjust)
        self.list.setMovement(QListView.Static)
        self.list.setWordWrap(True)
        self.list.setUniformItemSizes(True)
        self.list.itemActivated.connect(lambda it: self._open(it.data(Qt.UserRole)))
        self.list.currentItemChanged.connect(lambda cur, _old: self.open_btn.setEnabled(cur is not None))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.empty = QLabel("還沒有專案：按「新增專案…」開始")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("color: #777;")
        bottom = QHBoxLayout()
        new = QPushButton("新增專案…")
        new.clicked.connect(lambda: self._done(("new",)))
        browse = QPushButton("開啟其他專案…")
        browse.clicked.connect(lambda: self._done(("browse",)))
        self.open_btn = QPushButton("開啟")
        self.open_btn.setDefault(True)
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(lambda: self.list.currentItem() and self._open(self.list.currentItem().data(Qt.UserRole)))
        close = QPushButton("關閉")
        close.clicked.connect(self.reject)
        for b in (new, browse):
            bottom.addWidget(b)
        bottom.addStretch(1)
        bottom.addWidget(self.open_btn)
        bottom.addWidget(close)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.empty, 1)
        lay.addLayout(bottom)
        self.fill()

    def fill(self):
        self.list.clear()
        for path in workspace.find_projects(self.location, self.recent):
            when = datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
            it = QListWidgetItem(QIcon(card(path)), f"{workspace.project_name(path)}\n{when}")
            it.setData(Qt.UserRole, path)
            it.setToolTip(path)
            self.list.addItem(it)
        has = self.list.count() > 0
        self.list.setVisible(has)
        self.empty.setVisible(not has)
        if has:
            self.list.setCurrentRow(0)
        self._filter(self.search.text())

    def paths(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    def _filter(self, text):
        text = text.strip().lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(text) and text not in it.text().lower())

    def _open(self, path):
        if path:
            self._done(("open", path))

    def _done(self, choice):
        self.choice = choice
        self.accept()

    def _menu(self, pos):
        it = self.list.itemAt(pos)
        if it is None:
            return
        path = it.data(Qt.UserRole)
        menu = QMenu(self)
        menu.addAction("開啟", lambda: self._open(path))
        menu.addAction("開啟專案資料夾", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(workspace.root_of(path))))
        a = menu.addAction("拿掉縮圖", lambda: (thumbnail.remove(path), it.setIcon(QIcon(card(path)))))
        a.setEnabled(thumbnail.load(path) is not None)
        menu.exec(self.list.viewport().mapToGlobal(pos))
