"""The VFX tab: every built-in filter (and the user's own ones from the Library), by category.

Drag one onto the timeline: on an empty spot it becomes a filter clip that works on everything
below it, on a clip it is added to that clip's effects. Double-click puts a filter clip at the
playhead; the right-click menu applies it to the selected clips."""
import json
import queue
import threading

from PySide6.QtCore import QEvent, QMimeData, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QScrollArea, QVBoxLayout, QWidget)

from .. import fx, fxthumbs
from .menukeys import Menu
from .viewmode import list_toggle

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


class VfxList(QListWidget):
    """One category's filters: icons in a grid, or a list (the same arrangement as the 內建素材 tab)."""
    GRID = QSize(THUMB[0] + 18, THUMB[1] + 34)

    def __init__(self):
        super().__init__()
        self.setViewMode(QListWidget.IconMode)
        self.setIconSize(QSize(*THUMB))
        self.setGridSize(self.GRID)
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setWordWrap(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def shown(self):
        return sum(1 for i in range(self.count()) if not self.item(i).isHidden())

    def fit(self):
        """As tall as its items need: the tab scrolls, not each list."""
        g = self.gridSize()
        if self.viewMode() == QListWidget.IconMode and g.width() > 0:
            cols = max(1, self.viewport().width() // g.width())
            h = max(1, -(-self.shown() // cols)) * g.height() + 2 * self.frameWidth() + 4
        else:                                               # 列表: one row each
            h = self.shown() * max(1, self.sizeHintForRow(0)) + 2 * self.frameWidth() + 4
        if self.height() != h:
            self.setFixedHeight(h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit()

    def mimeTypes(self):
        return [FX_MIME]

    def mimeData(self, items):
        md = QMimeData()
        refs = [i.data(ROLE_REF) for i in items if i.data(ROLE_REF)]
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
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜尋濾鏡…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.top = QHBoxLayout()                          # (the 網格 / 列表 button is added once there are lists)
        self.top.addWidget(self.search, 1)
        lay.addLayout(self.top)
        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidget(self.body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        lay.addWidget(scroll, 1)
        self.cats = []                      # [(header label, VfxList)]
        self.toggle = None
        self.thumbs = Thumbs()
        self.thumbs.ready.connect(self._thumb_ready)
        self.thumbs.moving.connect(self._moving_ready)
        self.hover = None                   # (list, item, ref) of the thumbnail playing
        self.step = 0
        self.clock = QTimer(self)
        self.clock.setInterval(1000 // fxthumbs.ANIM_FPS)
        self.clock.timeout.connect(self._tick)
        self.mine = []                      # (name, ref) of the Library's filters
        self.rebuild()
        self.setMinimumWidth(260)

    def eventFilter(self, obj, ev):
        for _head, lst in self.cats:                      # (the filter under the mouse moves: what changes with time shows)
            if obj is lst.viewport():
                if ev.type() == QEvent.MouseMove:
                    item = lst.itemAt(ev.position().toPoint())
                    if item is not self.hover_item():
                        self._hover(lst, item)
                elif ev.type() == QEvent.Leave:
                    self._hover(None, None)
        return super().eventFilter(obj, ev)

    def hover_item(self):
        return self.hover[1] if self.hover else None

    def _hover(self, lst, item):
        if self.hover:                                    # back to the still picture
            _l, old, ref = self.hover
            pix = self.thumbs.get(ref)
            if pix is not None:
                old.setIcon(QIcon(pix))
        self.hover = None
        self.clock.stop()
        ref = self._ref(item)
        if ref:
            self.hover, self.step = (lst, item, ref), 0
            self.thumbs.animation(ref)                    # (made the first time: the clock starts when it is)
            self._moving_ready(ref)

    def _moving_ready(self, ref):
        if self.hover and self.hover[2] == ref and self.thumbs.animation(ref):
            self.clock.start()

    def _tick(self):
        frames = self.thumbs.animation(self.hover[2]) if self.hover else None
        if not frames:
            self.clock.stop()
            return
        self.step = (self.step + 1) % len(frames)
        self.hover[1].setIcon(QIcon(frames[self.step]))

    @staticmethod
    def _ref(item):
        return item.data(ROLE_REF) if item is not None else None

    def set_user_filters(self, mine):
        if mine != self.mine:
            self.mine = list(mine)
            self.rebuild()

    def rebuild(self):
        self.hover = None
        self.clock.stop()
        for head, lst in self.cats:
            head.deleteLater()
            lst.deleteLater()
        self.cats = []
        cats = {}
        for ref in fx.builtin_refs():
            d = fx.get(ref)
            cats.setdefault(d.category or "其他", []).append((d.name, ref, d.description, d.error))
        if self.mine:
            cats["我的濾鏡（Library）"] = [(name, ref, fx.get(ref).description, fx.get(ref).error)
                                          for name, ref in self.mine]
        while self.body_lay.count():
            self.body_lay.takeAt(0)
        for cat, items in cats.items():
            head = QLabel(cat)
            head.setStyleSheet("font-weight: bold; margin-top: 4px;")
            lst = VfxList()
            lst.itemDoubleClicked.connect(lambda it: self._ref(it) and self.addClipRequested.emit(self._ref(it)))
            lst.setContextMenuPolicy(Qt.CustomContextMenu)
            lst.customContextMenuRequested.connect(lambda pos, l=lst: self._menu(l, pos))
            lst.viewport().installEventFilter(self)
            for name, ref, desc, err in items:
                it = QListWidgetItem(name)
                it.setData(ROLE_REF, ref)
                it.setToolTip(f"{name}\n{desc}" + (f"\n（有錯誤：{err.splitlines()[0]}）" if err else ""))
                pix = self.thumbs.get(ref)
                if pix is not None:
                    it.setIcon(QIcon(pix))
                lst.addItem(it)
            self.body_lay.addWidget(head)
            self.body_lay.addWidget(lst)
            self.cats.append((head, lst))
        self.body_lay.addStretch(1)
        if self.toggle is not None:
            self.top.removeWidget(self.toggle)
            self.toggle.deleteLater()
        buttons = [list_toggle("vfx", lst, QSize(*THUMB), VfxList.GRID, QSize(32, 24)) for _h, lst in self.cats]
        for b in buttons[1:]:                             # (one button for all of them)
            b.hide()
            buttons[0].toggled.connect(b.setChecked)
        self.toggle = buttons[0] if buttons else None
        if self.toggle is not None:
            self.top.addWidget(self.toggle)
        self._filter(self.search.text())

    def _thumb_ready(self, ref):
        pix = self.thumbs.get(ref)
        if pix is None:
            return
        for _head, lst in self.cats:
            for i in range(lst.count()):
                if lst.item(i).data(ROLE_REF) == ref:
                    lst.item(i).setIcon(QIcon(pix))

    def _filter(self, text):
        text = text.strip().lower()
        for head, lst in self.cats:
            for i in range(lst.count()):
                it = lst.item(i)
                it.setHidden(bool(text) and text not in it.text().lower() and text not in head.text().lower())
            head.setHidden(lst.shown() == 0)
            lst.setHidden(lst.shown() == 0)
            lst.fit()

    def _menu(self, lst, pos):
        ref = self._ref(lst.itemAt(pos))
        if not ref:
            return
        menu = Menu(self)
        menu.addAction("在播放頭新增濾鏡片段", lambda: self.addClipRequested.emit(ref))
        menu.addAction("套用到選取的片段", lambda: self.applyRequested.emit(ref))
        menu.addSeparator()
        menu.addAction("濾鏡寫法說明…", self.docRequested)
        menu.exec(lst.viewport().mapToGlobal(pos))
