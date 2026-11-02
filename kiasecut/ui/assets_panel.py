"""The 內建素材 tab: solid colours, gradients and basic shapes (see assets.py), and the four Audio
Visualizers (viz.py; their ident is "viz:<kind>").

Drag one onto the timeline (hold Alt over a picture clip to replace its source), or
double-click to add it at the playhead. The two colours at the top paint the shapes and the
自訂 solid / gradients; presets keep their own colours. Once placed, everything about it
(size, colours, corners, outline…) is set in the inspector's 素材參數."""
from PySide6.QtCore import QByteArray, QMimeData, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .. import assets, viz
from .colorpick import hex_of, pick_color, qcolor
from .timeline import MEDIA_MIME
from .menukeys import Menu
from .viewmode import list_toggle

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


VIZ_CAT = ("viz", "Audio Visualizer")           # (after the presets: drawn from sound, not from colours)


def viz_thumbnail(kind):
    """A small picture of an Audio Visualizer kind (viz.py) on a dark ground."""
    import math
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath, QPen
    w, h = THUMB
    img = QImage(QSize(w, h), QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("#202024"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    col = QColor.fromRgbF(*viz.make(kind, {"type": "track", "id": ""})["color"])
    p.setPen(Qt.NoPen)
    p.setBrush(col)
    if kind == "bars":
        for i in range(11):
            ln = 6 + 22 * abs(math.sin(i * 0.9 + 0.4)) * (1 - abs(i - 5) / 9)
            p.drawRoundedRect(QRectF(6 + i * 5.6, h - 5 - ln, 3.6, ln), 1.5, 1.5)
    elif kind == "wave":
        top, bottom = QPainterPath(), QPainterPath()
        pts = [(6 + i * (w - 12) / 24, 14 * abs(math.sin(i * 0.55)) * (0.4 + 0.6 * math.sin(i * 0.13 + 0.5) ** 2) + 1) for i in range(25)]
        path = QPainterPath(QPointF(pts[0][0], h / 2 - pts[0][1]))
        for x, a in pts[1:]:
            path.lineTo(x, h / 2 - a)
        for x, a in reversed(pts):
            path.lineTo(x, h / 2 + a)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "scope":
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(col, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        path = QPainterPath(QPointF(6, h / 2))
        for i in range(1, 61):
            x = 6 + i * (w - 12) / 60
            path.lineTo(x, h / 2 - 13 * math.sin(i * 0.33) * math.sin(i * 0.07 + 0.3))
        p.drawPath(path)
    else:
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 70), 1))
        p.drawEllipse(QPointF(w / 2, h / 2), 15, 15)
        p.drawLine(QPointF(w / 2, 3), QPointF(w / 2, h - 3))
        p.setPen(QPen(col, 2, Qt.SolidLine, Qt.RoundCap))
        for i in range(60):
            m = (i / 60 - 0.5) * 2
            p.drawPoint(QPointF(w / 2 + 4 * math.sin(i * 2.7) * (1 - abs(m)), h / 2 + m * 13))
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

    def fit(self):
        """As tall as its items need: the tab scrolls, not each list."""
        g = self.gridSize()
        if self.viewMode() == QListWidget.IconMode and g.width() > 0:
            cols = max(1, self.viewport().width() // g.width())
            rows = max(1, -(-self.count() // cols))
            h = rows * g.height() + 2 * self.frameWidth() + 4
        else:                                               # 列表: one row each
            rows = [self.sizeHintForRow(i) for i in range(self.count())]
            h = sum(max(r, self.iconSize().height() + 8) for r in rows) + 2 * self.frameWidth() + 4
        if self.height() != h:
            self.setFixedHeight(h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit()

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
        self.view_row = row                                 # (網格 / 列表: added once the lists exist)
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
        head = QLabel(VIZ_CAT[1])                           # Audio Visualizer: a picture drawn from sound
        head.setStyleSheet("font-weight: bold; margin-top: 4px;")
        lst = AssetList(self)
        lst.itemDoubleClicked.connect(lambda it: self.addRequested.emit(self.ident(it.data(ROLE_KEY))))
        for kind, name in viz.KINDS.items():
            it = QListWidgetItem(name)
            it.setData(ROLE_KEY, "viz." + kind)
            it.setToolTip(name + "（聽時間線上有聲音的軌道，或一個檔案；在屬性裡設定）")
            it.setIcon(QIcon(viz_thumbnail(kind)))
            lst.addItem(it)
        blay.addWidget(head)
        blay.addWidget(lst)
        self.lists[VIZ_CAT[0]] = lst
        blay.addStretch(1)
        toggles = [list_toggle("assets", lst, QSize(*THUMB), QSize(THUMB[0] + 18, THUMB[1] + 34), QSize(*THUMB))
                   for lst in self.lists.values()]
        for b in toggles[1:]:                               # (one button for all of them)
            b.hide()
            toggles[0].toggled.connect(b.setChecked)
        self.view_row.addWidget(toggles[0])
        self.refresh()
        self.setMinimumWidth(260)

    def ident(self, key):
        if key.startswith("viz."):
            return "viz:" + key[4:]
        return assets.ident(key, *self.colors)

    def refresh(self):
        for b, c in zip(self.color_btns, self.colors):
            b.setStyleSheet(f"background: {c}; border: 1px solid #555;")
        for lst in self.lists.values():
            for i in range(lst.count()):
                it = lst.item(i)
                a = assets.get(it.data(ROLE_KEY))
                if a is None:                                   # (an Audio Visualizer: no colours of the panel's)
                    continue
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
        menu = Menu(self)
        menu.addAction("在播放頭加入", lambda: self.addRequested.emit(self.ident(it.data(ROLE_KEY))))
        menu.exec(lst.viewport().mapToGlobal(pos))
