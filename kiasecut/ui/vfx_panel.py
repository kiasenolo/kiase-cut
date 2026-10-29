"""The VFX tab: every built-in filter (and the user's own ones from the Library), by category.

Drag one onto the timeline: on an empty spot it becomes a filter clip that works on everything
below it, on a clip it is added to that clip's effects. Double-click puts a filter clip at the
playhead; the right-click menu applies it to the selected clips."""
import json
import queue
import threading

from PySide6.QtCore import QEvent, QMimeData, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QLabel, QLineEdit, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from .. import fx, fxthumbs
from .menukeys import Menu

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
    moving = Signal(str)                    # the moving picture of a filter is made (animation(ref) has it)
    _made = Signal(object, object)          # (ref, filter key), QImage or None: from the thread

    def __init__(self):
        super().__init__()
        self.failed = False
        self.cache = {}                     # (ref, filter key) -> QPixmap or None
        self.moves = {}                     # ("anim", ref, filter key) -> [QPixmap] ([]: it never changes) or None
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

    def animation(self, ref):
        """The filter's thumbnail moving - the pictures of its first two seconds, [] when it looks
        the same all the time - or None while it is made (it is asked for the first time) or cannot be."""
        if self.failed:
            return None
        key = ("anim", ref, fx.get(ref).key())
        if key in self.moves:
            return self.moves[key]
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
            if key[0] == "anim":
                pics = None
                try:
                    if fx.get(key[1]).key() == key[2]:
                        frames = worker.make_anim(key[1])
                        if frames is not None:
                            pics = [QImage(f.tobytes(), f.shape[1], f.shape[0], f.shape[1] * 4,
                                           QImage.Format_RGBA8888_Premultiplied).copy() for f in frames]
                except OSError:
                    self.failed = True
                    return
                except Exception:
                    pics = None
                self._made.emit(key, pics)
                continue
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
        if key[0] == "anim":
            self.moves[key] = None if img is None else [
                QPixmap.fromImage(i).scaled(*THUMB, Qt.IgnoreAspectRatio, Qt.SmoothTransformation) for i in img]
            if img is not None:
                self.moving.emit(key[1])
            return
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
        self.thumbs.moving.connect(self._moving_ready)
        self.tree.setMouseTracking(True)                  # the filter under the mouse moves: what changes with time shows
        self.tree.viewport().setMouseTracking(True)
        self.tree.viewport().installEventFilter(self)
        self.hover = None                   # (item, ref) of the thumbnail playing
        self.step = 0
        self.clock = QTimer(self)
        self.clock.setInterval(1000 // fxthumbs.ANIM_FPS)
        self.clock.timeout.connect(self._tick)
        self.mine = []                      # (name, ref) of the Library's filters
        self.rebuild()
        self.setMinimumWidth(260)

    def eventFilter(self, obj, ev):
        if obj is self.tree.viewport():
            if ev.type() == QEvent.MouseMove:
                item = self.tree.itemAt(ev.position().toPoint())
                if item is not self.hover_item():
                    self._hover(item)
            elif ev.type() == QEvent.Leave:
                self._hover(None)
        return super().eventFilter(obj, ev)

    def hover_item(self):
        return self.hover[0] if self.hover else None

    def _hover(self, item):
        if self.hover:                                    # back to the still picture
            old, ref = self.hover
            pix = self.thumbs.get(ref)
            if pix is not None:
                old.setIcon(0, QIcon(pix))
        self.hover = None
        self.clock.stop()
        ref = self._ref(item)
        if ref:
            self.hover, self.step = (item, ref), 0
            self.thumbs.animation(ref)                    # (made the first time: the clock starts when it is)
            self._moving_ready(ref)

    def _moving_ready(self, ref):
        if self.hover and self.hover[1] == ref and self.thumbs.animation(ref):
            self.clock.start()

    def _tick(self):
        frames = self.thumbs.animation(self.hover[1]) if self.hover else None
        if not frames:
            self.clock.stop()
            return
        self.step = (self.step + 1) % len(frames)
        self.hover[0].setIcon(0, QIcon(frames[self.step]))

    @staticmethod
    def _ref(item):
        return item.data(0, ROLE_REF) if item is not None else None

    def set_user_filters(self, mine):
        if mine != self.mine:
            self.mine = list(mine)
            self.rebuild()

    def rebuild(self):
        self.hover = None
        self.clock.stop()
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
        menu = Menu(self)
        menu.addAction("在播放頭新增濾鏡片段", lambda: self.addClipRequested.emit(ref))
        menu.addAction("套用到選取的片段", lambda: self.applyRequested.emit(ref))
        menu.addSeparator()
        menu.addAction("濾鏡寫法說明…", self.docRequested)
        menu.exec(self.tree.viewport().mapToGlobal(pos))
