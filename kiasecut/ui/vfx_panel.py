"""The VFX tab: every built-in filter (and the user's own ones from the Library), by category.

Drag one onto the timeline: on an empty spot it becomes a filter clip that works on everything
below it, on a clip it is added to that clip's effects. Double-click puts a filter clip at the
playhead; the right-click menu applies it to the selected clips."""
import json
import queue
import threading

from PySide6.QtCore import QMimeData, QObject, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QLabel, QLineEdit, QMenu, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from .. import fx, fxthumbs

FX_MIME = "application/x-kiasecut-fx"          # the filter's ref (a "builtin:…" name or a file path), utf-8,
                                               # or an effect dragged from a clip (effect_mime)
ROLE_REF = Qt.UserRole + 1
THUMB = (64, 36)


class Thumbs(QObject):
    """Pictures of the filters at their default settings, made by a process of their own
    (fxthumbs.py: the first compile of a big filter can take the driver half a minute, which
    must not freeze the window). get() is None until the picture is made; ready(ref) says when
    it is. When the filter engine is not available there are none."""
    ready = Signal(str)
    _made = Signal(object, object)          # (ref, filter key), QImage or None: from the thread

    def __init__(self):
        super().__init__()
        self.failed = False
        self.cache = {}                     # (ref, filter key) -> QPixmap or None
        self.asked = set()
        self.todo = queue.Queue()
        self.thread = None
        self._made.connect(self._keep)

    def get(self, ref):
        if self.failed:
            return None
        key = (ref, fx.get(ref).key())
        if key in self.cache:
            return self.cache[key]
        if key not in self.asked:
            self.asked.add(key)
            self.todo.put(key)
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, name="filter thumbnails", daemon=True)
                self.thread.start()
        return None

    def _run(self):                         # waits on the process, so the window goes on
        try:
            worker = fxthumbs.Worker()
        except OSError:
            self.failed = True
            return
        while True:
            key = self.todo.get()
            img = None
            try:
                if fx.get(key[0]).key() == key[1]:
                    out = worker.make(key[0])
                    if out is not None:
                        h, w = out.shape[:2]
                        img = QImage(out.tobytes(), w, h, w * 4, QImage.Format_RGBA8888_Premultiplied).copy()
            except OSError:                 # the process is gone: no more pictures
                self.failed = True
                return
            except Exception:
                img = None
            self._made.emit(key, img)

    def _keep(self, key, img):
        self.cache[key] = None if img is None else \
            QPixmap.fromImage(img).scaled(*THUMB, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        if img is not None:
            self.ready.emit(key[0])


def effect_mime(effect, clip_id):
    """A drag of an effect of clip clip_id (from the effects panel): its settings go along."""
    md = QMimeData()
    md.setData(FX_MIME, json.dumps({"effect": effect, "clip": clip_id}, ensure_ascii=False).encode("utf-8"))
    return md


def dropped_fx(payload):
    """(filter ref, effect or None, clip id or None) of what FX_MIME carries: a filter of the VFX
    tab, or an effect of a clip with its settings."""
    if payload.startswith("{"):
        d = json.loads(payload)
        return d["effect"]["filter"], d["effect"], d.get("clip")
    return payload, None, None


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
        self.thumbs.ready.connect(self._thumb_ready)
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

    def _thumb_ready(self, ref):
        pix = self.thumbs.get(ref)
        if pix is None:
            return
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                if top.child(j).data(0, ROLE_REF) == ref:
                    top.child(j).setIcon(0, QIcon(pix))

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
