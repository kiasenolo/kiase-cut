"""The VFX tab: every built-in filter (and the user's own ones from the Library), by category.

Drag one onto the timeline: on an empty spot it becomes a filter clip that works on everything
below it, on a clip it is added to that clip's effects. Double-click puts a filter clip at the
playhead; the right-click menu applies it to the selected clips."""
from PySide6.QtCore import QMimeData, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QLabel, QLineEdit, QMenu, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from .. import fx

FX_MIME = "application/x-tesetoa-fx"          # the filter's ref (a "builtin:…" name or a file path), utf-8
ROLE_REF = Qt.UserRole + 1
THUMB = (64, 36)


def sample_picture(w=160, h=90):
    """A small picture to show what a filter does: colour ramp, a disc, a square and stripes
    (premultiplied RGBA, uint8)."""
    import numpy as np
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.zeros((h, w, 4), np.float32)
    img[..., 0] = 255 * x / w
    img[..., 1] = 90 + 60 * y / h
    img[..., 2] = 255 * (1 - x / w)
    img[..., 3] = 255
    disc = (x - w * 0.55) ** 2 + (y - h * 0.5) ** 2 < (h * 0.3) ** 2
    img[disc] = (255, 220, 40, 255)
    img[int(h * 0.15):int(h * 0.4), int(w * 0.08):int(w * 0.25)] = (20, 200, 90, 255)
    img[int(h * 0.8):int(h * 0.86), :] = 255
    return img.round().astype(np.uint8)


class Thumbs:
    """Pictures of the filters at their default settings, made on the GPU the first time they
    are asked for. When the filter engine is not available there are none."""

    def __init__(self):
        self.engine = None
        self.failed = False
        self.cache = {}

    def get(self, ref):
        if self.failed:
            return None
        key = (ref, fx.get(ref).key())
        if key in self.cache:
            return self.cache[key]
        pix = None
        try:
            if self.engine is None:
                self.engine = fx.Engine()
            d = fx.get(ref)
            if not d.error:
                src = sample_picture()
                vals = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
                out = self.engine.run(d, vals, src, time=0.7, progress=0.5, frame=17)
                h, w = out.shape[:2]
                img = QImage(out.tobytes(), w, h, w * 4, QImage.Format_RGBA8888_Premultiplied).copy()
                pix = QPixmap.fromImage(img).scaled(*THUMB, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        except Exception:
            self.failed = self.engine is None
            pix = None
        self.cache[key] = pix
        return pix


class VfxTree(QTreeWidget):
    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setIconSize(QSize(*THUMB))
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setIndentation(12)
        self.setUniformRowHeights(False)

    def mimeTypes(self):
        return [FX_MIME]

    def mimeData(self, items):
        md = QMimeData()
        refs = [i.data(0, ROLE_REF) for i in items if i.data(0, ROLE_REF)]
        if refs:
            md.setData(FX_MIME, refs[0].encode("utf-8"))
        return md


class VfxPanel(QWidget):
    addClipRequested = Signal(str)          # filter ref: a filter clip at the playhead
    applyRequested = Signal(str)            # filter ref: add to the selected clips
    docRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        hint = QLabel("把濾鏡拖到時間軸：放在空白處＝濾鏡片段（影響下面所有軌道），放在片段上＝加到那個片段的效果。雙擊＝在播放頭新增濾鏡片段。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9a9aa0;")
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜尋濾鏡…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.tree = VfxTree()
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._ref(it) and self.addClipRequested.emit(self._ref(it)))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        lay.addWidget(hint)
        lay.addWidget(self.search)
        lay.addWidget(self.tree, 1)
        self.thumbs = Thumbs()
        self.mine = []                      # (name, ref) of the Library's filters
        self.rebuild()
        self.setMinimumWidth(260)

    @staticmethod
    def _ref(item):
        return item.data(0, ROLE_REF) if item is not None else None

    def set_user_filters(self, mine):
        if mine != self.mine:
            self.mine = list(mine)
            self.rebuild()

    def rebuild(self):
        self.tree.clear()
        cats = {}
        for ref in fx.builtin_refs():
            d = fx.get(ref)
            cats.setdefault(d.category or "其他", []).append((d.name, ref, d.description, d.error))
        if self.mine:
            cats["我的濾鏡（Library）"] = [(name, ref, fx.get(ref).description, fx.get(ref).error)
                                          for name, ref in self.mine]
        for cat, items in cats.items():
            top = QTreeWidgetItem([cat])
            top.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(top)
            for name, ref, desc, err in items:
                it = QTreeWidgetItem([name])
                it.setData(0, ROLE_REF, ref)
                it.setToolTip(0, f"{name}\n{desc}" + (f"\n（有錯誤：{err.splitlines()[0]}）" if err else ""))
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
                pix = self.thumbs.get(ref)
                if pix is not None:
                    it.setIcon(0, QIcon(pix))
                top.addChild(it)
            top.setExpanded(True)
        self._filter(self.search.text())

    def _filter(self, text):
        text = text.strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            shown = 0
            for j in range(top.childCount()):
                it = top.child(j)
                hit = not text or text in it.text(0).lower() or text in top.text(0).lower()
                it.setHidden(not hit)
                shown += hit
            top.setHidden(not shown)

    def _menu(self, pos):
        ref = self._ref(self.tree.itemAt(pos))
        if not ref:
            return
        menu = QMenu(self)
        menu.addAction("在播放頭新增濾鏡片段", lambda: self.addClipRequested.emit(ref))
        menu.addAction("套用到選取的片段", lambda: self.applyRequested.emit(ref))
        menu.addSeparator()
        menu.addAction("濾鏡寫法說明…", self.docRequested)
        menu.exec(self.tree.viewport().mapToGlobal(pos))
