"""說明 Wiki (說明 menu, F1): a window with the pages of wiki.py - a tree of them and a search field at the left, the page at the right
(links between pages, 上一頁 / 下一頁). The window is made when first wanted and keeps its place."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSplitter, QTextBrowser, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import wiki, wikidata

STYLE = "table {border-color: #555555;} th {background-color: #2a2a2a;} code {color: #c8c85a;} a {color: #6a9fd0;}"


def socket_image(colour, shape, size=64):
    """A socket as the node editor draws it (NodeItem._socket): a circle holds one value, a diamond a value for every pixel (a field), a
    diamond with a dot either."""
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(0, 0, 0, 160), size / 16))
    p.setBrush(QColor(colour))
    c, r = QPointF(size / 2, size / 2), size * 0.36
    if shape == "single":
        p.drawEllipse(c, r, r)
    else:
        r *= 1.3
        p.drawPolygon(QPolygonF([c + QPointF(0, -r), c + QPointF(r, 0), c + QPointF(0, r), c + QPointF(-r, 0)]))
        if shape == "either":
            p.setBrush(QColor(0, 0, 0, 200))
            p.drawEllipse(c, r * 0.25, r * 0.25)
    p.end()
    return img


def diagram_image(name, scale=2):
    """A little node graph, drawn as the node editor draws one: dark boxes with a title, sockets down the sides, links between them."""
    w, h, nodes, links = wikidata.DIAGRAMS[name]
    img = QImage(w * scale, h * scale, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(scale, scale)
    NW, HEAD, ROW = 120, 22, 22
    font = QFont(p.font())
    font.setPixelSize(12)
    p.setFont(font)
    pos = {}
    for nid, (title, x, y, ins, outs) in nodes.items():
        pos[nid] = ([QPointF(x, y + HEAD + ROW * (i + .5)) for i in range(len(ins))],
                    [QPointF(x + NW, y + HEAD + ROW * (i + .5)) for i in range(len(outs))])
    p.setBrush(Qt.NoBrush)
    for a, o, b, i in links:
        s, e = pos[a][1][o], pos[b][0][i]
        path = QPainterPath(s)
        d = max(30, abs(e.x() - s.x()) / 2)
        path.cubicTo(s + QPointF(d, 0), e - QPointF(d, 0), e)
        p.setPen(QPen(QColor("#b3b3b3"), 2))
        p.drawPath(path)
    for nid, (title, x, y, ins, outs) in nodes.items():
        rows = max(len(ins), len(outs), 0)
        body = QRectF(x, y, NW, HEAD + ROW * max(rows, 1))
        p.setPen(QPen(QColor(0, 0, 0, 160), 1))
        p.setBrush(QColor("#1a1a1a"))
        p.drawRoundedRect(body, 5, 5)
        p.setBrush(QColor("#6c696f"))
        p.drawRoundedRect(QRectF(x, y, NW, HEAD), 5, 5)
        p.setPen(QColor("#f0f0f0"))
        p.drawText(QRectF(x + 8, y, NW - 16, HEAD), Qt.AlignVCenter, title)
        for k, (names, pts) in enumerate(((ins, pos[nid][0]), (outs, pos[nid][1]))):
            for n, pt in zip(names, pts):
                p.setPen(QColor("#d0d0d0"))
                box = QRectF(pt.x() + 8, pt.y() - 10, NW - 20, 20) if k == 0 else QRectF(pt.x() - NW + 12, pt.y() - 10, NW - 20, 20)
                p.drawText(box, Qt.AlignVCenter | (Qt.AlignLeft if k == 0 else Qt.AlignRight), n)
                p.setPen(QPen(QColor(0, 0, 0, 160), 1))
                p.setBrush(QColor("#c8c85a"))
                p.drawEllipse(pt, 5, 5)
    p.end()
    return img


class Browser(QTextBrowser):
    """The page: it draws the "socket:<colour>:<shape>" images the pages hold (wiki.dot)."""
    def loadResource(self, kind, url):
        if url.scheme() == "socket":
            colour, _, shape = url.path().partition(":")
            return socket_image("#" + colour.lstrip("#"), shape or "single")
        if url.scheme() == "diagram" and url.path() in wikidata.DIAGRAMS:
            return diagram_image(url.path())
        return super().loadResource(kind, url)


class WikiWindow(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Window)
        self.setWindowTitle("KiaseCut 說明")
        self.resize(1000, 680)
        self.back, self.forward, self.page = [], [], "home"
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜尋節點、參數、說明…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._searched)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(lambda item, _: self.show_page(item.data(0, Qt.UserRole)))
        self.found = QListWidget()
        self.found.itemClicked.connect(lambda item: self.show_page(item.data(Qt.UserRole)))
        self.found.hide()
        left = QWidget()
        col = QVBoxLayout(left)
        col.setContentsMargins(0, 0, 0, 0)
        col.addWidget(self.search)
        col.addWidget(self.tree, 1)
        col.addWidget(self.found, 1)
        self.view = Browser()
        self.view.setOpenLinks(False)
        self.view.document().setDefaultStyleSheet(STYLE)
        self.view.anchorClicked.connect(lambda url: self.show_page(wiki.page_of(url.toString())))
        self.back_btn, self.fwd_btn = QPushButton("◀ 上一頁"), QPushButton("下一頁 ▶")
        self.back_btn.clicked.connect(lambda: self._step(self.back, self.forward))
        self.fwd_btn.clicked.connect(lambda: self._step(self.forward, self.back))
        bar = QHBoxLayout()
        bar.addWidget(self.back_btn)
        bar.addWidget(self.fwd_btn)
        bar.addStretch(1)
        right = QWidget()
        col = QVBoxLayout(right)
        col.setContentsMargins(0, 0, 0, 0)
        col.addLayout(bar)
        col.addWidget(self.view, 1)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([280, 720])
        lay = QVBoxLayout(self)
        lay.addWidget(split)
        self.items = {}
        self._fill(self.tree.invisibleRootItem(), wiki.tree())
        self.show_page("home", remember=False)

    def _fill(self, parent, nodes):
        for pid, title, children in nodes:
            item = QTreeWidgetItem(parent, [title])
            item.setData(0, Qt.UserRole, pid)
            self.items.setdefault(pid, item)
            self._fill(item, children)
        if parent is self.tree.invisibleRootItem():
            self.items["guides"].setExpanded(True)

    def show_page(self, pid, remember=True):
        if not pid:
            return
        if remember and pid != self.page:
            self.back.append(self.page)
            self.forward.clear()
        self.page = pid
        kind, text = wiki.render(pid)
        if kind == "markdown":
            self.view.setMarkdown(text)
        else:
            self.view.setHtml(text)
        self.back_btn.setEnabled(bool(self.back))
        self.fwd_btn.setEnabled(bool(self.forward))
        item = self.items.get(pid)
        if item is not None:
            self.tree.setCurrentItem(item)

    def _step(self, source, other):
        if source:
            other.append(self.page)
            self.show_page(source.pop(), remember=False)

    def _searched(self, text):
        self.found.clear()
        text = text.strip()
        self.tree.setVisible(not text)
        self.found.setVisible(bool(text))
        for pid, title, hit in wiki.search(text):
            item = QListWidgetItem(title + (f"\n    {hit[:50]}" if hit else ""))
            item.setData(Qt.UserRole, pid)
            self.found.addItem(item)
