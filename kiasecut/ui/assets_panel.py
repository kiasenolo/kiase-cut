"""The 內建素材 tab: solid colours, gradients and basic shapes (see assets.py).

Drag one onto the timeline (hold Alt over a picture clip to replace its source), or
double-click to add it at the playhead. The two colours at the top paint the shapes and the
自訂 solid / gradients; presets keep their own colours. Once placed, everything about it
(size, colours, corners, outline…) is set in the inspector's 素材參數."""
from PySide6.QtCore import QByteArray, QMimeData, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMenu, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .. import assets
from .colorpick import hex_of, pick_color, qcolor
from .timeline import MEDIA_MIME

ROLE_KEY = Qt.UserRole + 1
THUMB = (72, 40)


def thumbnail(a, c1, c2):
    """A small picture of asset a on a checkerboard (so clear parts show)."""
    w, h = THUMB
    img = QImage(QSize(w, h), QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("#2a2a2e"))
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    for y in range(0, h, 6):
        for x in range(0, w, 6):
            if (x // 6 + y // 6) % 2:
                p.fillRect(x, y, 6, 6, QColor("#38383d"))
    r = QSvgRenderer(QByteArray(assets.svg(assets.at(assets.make(a, c1, c2, 160, 90), 0)).encode("utf-8")))
    r.setAspectRatioMode(Qt.KeepAspectRatio)
    pad = 5 if a.cat == "shape" else 0
    r.render(p, QRectF(pad, pad, w - 2 * pad, h - 2 * pad))
    p.end()
    return QPixmap.fromImage(img)


class AssetList(QListWidget):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.setViewMode(QListWidget.IconMode)
        self.setIconSize(QSize(*THUMB))
        self.setGridSize(QSize(THUMB[0] + 18, THUMB[1] + 34))
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setWordWrap(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def resizeEvent(self, e):
        # as tall as its items need: the tab scrolls, not each list
        super().resizeEvent(e)
        g = self.gridSize()
        cols = max(1, self.viewport().width() // g.width())
        rows = max(1, -(-self.count() // cols))
        h = rows * g.height() + 2 * self.frameWidth() + 4
        if self.height() != h:
            self.setFixedHeight(h)

    def mimeTypes(self):
        return [MEDIA_MIME]

    def mimeData(self, items):
        md = QMimeData()
        keys = [i.data(ROLE_KEY) for i in items if i.data(ROLE_KEY)]
        if keys:
            md.setData(MEDIA_MIME, self.panel.ident(keys[0]).encode("utf-8"))
        return md


class AssetsPanel(QWidget):
    addRequested = Signal(str)              # asset ident: add at the playhead

    def __init__(self, parent=None):
        super().__init__(parent)
        self.colors = list(assets.DEFAULT_COLORS)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        hint = QLabel("把素材拖到時間軸（按住 Alt 放到圖片片段上＝替換素材），雙擊＝在播放頭加入。"
                      "顏色 1 / 2 用在形狀和「自訂」素材；放上去之後在「屬性」的素材參數裡調大小、顏色、圓角、外框等。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9a9aa0;")
        row = QHBoxLayout()
        self.color_btns = []
        for i, title in enumerate(("顏色 1", "顏色 2")):
            row.addWidget(QLabel(title))
            b = QPushButton()
            b.setFixedSize(46, 22)
            b.setToolTip(f"選擇{title}")
            b.clicked.connect(lambda _=False, k=i: self._pick(k))
            row.addWidget(b)
            self.color_btns.append(b)
        swap = QPushButton("交換")
        swap.setToolTip("交換兩個顏色")
        swap.clicked.connect(self._swap)
        row.addWidget(swap)
        row.addStretch(1)
        lay.addWidget(hint)
        lay.addLayout(row)
        body = QWidget()
        blay = QVBoxLayout(body)
        blay.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        lay.addWidget(scroll, 1)
        self.lists = {}
        for cat, title in assets.CATEGORIES:
            head = QLabel(title)
            head.setStyleSheet("font-weight: bold; margin-top: 4px;")
            lst = AssetList(self)
            lst.itemDoubleClicked.connect(lambda it: self.addRequested.emit(self.ident(it.data(ROLE_KEY))))
            lst.setContextMenuPolicy(Qt.CustomContextMenu)
            lst.customContextMenuRequested.connect(lambda pos, l=lst: self._menu(l, pos))
            for a in assets.ASSETS:
                if a.cat == cat:
                    it = QListWidgetItem(a.name)
                    it.setData(ROLE_KEY, a.key)
                    it.setToolTip(a.name + ("（用顏色 1 / 2）" if a.custom else ""))
                    lst.addItem(it)
            blay.addWidget(head)
            blay.addWidget(lst)
            self.lists[cat] = lst
        blay.addStretch(1)
        self.refresh()
        self.setMinimumWidth(260)

    def ident(self, key):
        return assets.ident(key, *self.colors)

    def refresh(self):
        for b, c in zip(self.color_btns, self.colors):
            b.setStyleSheet(f"background: {c}; border: 1px solid #555;")
        for lst in self.lists.values():
            for i in range(lst.count()):
                it = lst.item(i)
                a = assets.get(it.data(ROLE_KEY))
                if a.custom or it.icon().isNull():
                    it.setIcon(QIcon(thumbnail(a, *self.colors)))

    def _pick(self, k):
        was = self.colors[k]

        def show(col):
            self.colors[k] = hex_of(col)
            self.refresh()
        col = pick_color(self, qcolor(was), f"顏色 {k + 1}", live=show)
        self.colors[k] = hex_of(col) if col is not None else was
        self.refresh()

    def _swap(self):
        self.colors.reverse()
        self.refresh()

    def _menu(self, lst, pos):
        it = lst.itemAt(pos)
        if it is None:
            return
        menu = QMenu(self)
        menu.addAction("在播放頭加入", lambda: self.addRequested.emit(self.ident(it.data(ROLE_KEY))))
        menu.exec(lst.viewport().mapToGlobal(pos))
