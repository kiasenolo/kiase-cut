"""Main window (Jianying-like): media library, preview, inspector, timeline.

Editing can happen on the main timeline or inside a compound clip (double-click it);
`path_ids` is the chain of compound clips that are open. Every edit runs through one undo
history on the whole project, applied to whichever level is open.
"""
import hashlib
import json
import math
import os

from PySide6.QtCore import QObject, QSize, QStandardPaths, Qt, QThread, Signal, Slot
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QColorDialog, QDialog, QFileDialog, QHBoxLayout,
                               QInputDialog, QLabel, QMainWindow, QMessageBox, QProgressDialog,
                               QMenu, QPushButton, QScrollArea, QSlider, QSplitter, QTabBar, QTabWidget, QVBoxLayout,
                               QWidget)

from .. import build, curves, edit, library, project, waveform
from ..client import EngineClient
from ..importers import jianying
from .compounds import CompoundPanel
from .curve_editor import CurveEditor
from .export_dialog import ExportDialog
from .inspector import Inspector
from .library import LibraryPanel
from .player import Player
from . import icons
from .meter import MeterPanel
from .preview import FullscreenPreview, Preview
from .timeline import US, Timeline, timecode

# DaVinci Resolve-like: charcoal panels on a near-black frame, flat controls, light grey
# text; colour is left to clips, keyframes, the playhead and the meter
STYLE = """
QWidget { background: #1c1c1e; color: #d0d0d2; font-family: 'Segoe UI', 'Microsoft JhengHei UI', 'Noto Sans CJK TC', sans-serif; font-size: 12px; }
QMainWindow { background: #111113; }
QMenuBar { background: #18181a; border-bottom: 1px solid #0e0e10; }
QMenu { background: #26262a; border: 1px solid #0e0e10; }
QMenu::item { padding: 4px 22px; }
QMenu::item:selected, QMenuBar::item:selected { background: #3d3d43; }
QMenu::separator { height: 1px; background: #3a3a40; margin: 3px 6px; }
QPushButton { background: #2b2b2f; border: 1px solid #141416; border-radius: 3px; padding: 4px 10px; }
QPushButton:hover { background: #36363b; }
QPushButton:pressed { background: #1f1f22; }
QPushButton:checked { background: #c9c9cd; color: #121214; border-color: #c9c9cd; }
QPushButton:disabled { color: #5c5c62; }
QPushButton#tool { background: transparent; border: 1px solid transparent; padding: 3px; }
QPushButton#tool:hover { background: #33333a; border-color: #141416; }
QPushButton#tool:checked { background: #4a4a52; border-color: #5c5c64; }
QPushButton#tool:disabled { background: transparent; }
QSplitter::handle { background: #0e0e10; }
QSplitter::handle:horizontal { width: 3px; }
QSplitter::handle:vertical { height: 3px; }
QDoubleSpinBox, QPlainTextEdit, QLineEdit, QComboBox { background: #141416; border: 1px solid #2c2c31; border-radius: 3px; padding: 2px 4px; selection-background-color: #4a4a52; }
QDoubleSpinBox:focus, QPlainTextEdit:focus, QLineEdit:focus, QComboBox:focus { border-color: #6a6a72; }
QDoubleSpinBox:disabled { color: #5c5c62; }
QComboBox QAbstractItemView { background: #26262a; selection-background-color: #3d3d43; }
QTreeWidget, QListWidget { background: #1c1c1e; border: none; alternate-background-color: #202023; }
QTreeWidget::item, QListWidget::item { padding: 2px; }
QTreeWidget::item:selected, QListWidget::item:selected { background: #3d3d43; color: #ffffff; }
QHeaderView::section { background: #232326; color: #8e8e94; border: none; border-bottom: 1px solid #0e0e10; padding: 4px; }
QLabel#time { font-family: Consolas, 'Cascadia Mono', monospace; font-size: 15px; color: #e8e8ea; }
QLabel#viewer { color: #8e8e94; }
QLabel#title { color: #8e8e94; font-weight: 600; font-size: 11px; }
QLabel#crumb { color: #d0d0d2; font-weight: 600; }
QWidget#bar { background: #232326; border-top: 1px solid #0e0e10; border-bottom: 1px solid #0e0e10; }
QTabWidget::pane { border: none; border-top: 1px solid #0e0e10; }
QTabBar { background: #18181a; }
QTabBar::tab { background: #18181a; color: #8e8e94; padding: 6px 14px; border: none; border-right: 1px solid #0e0e10; }
QTabBar::tab:selected { background: #232326; color: #ffffff; }
QTabBar::tab:hover:!selected { color: #c0c0c4; }
QTabBar#timelines::tab { padding: 4px 14px; border-top-left-radius: 3px; border-top-right-radius: 3px; }
QTabBar#timelines::tab:selected { background: #2b2b2f; }
QMessageBox, QInputDialog, QColorDialog, QDialog { background: #1c1c1e; }
QMessageBox QLabel { color: #d0d0d2; background: transparent; }
QStatusBar { background: #18181a; color: #8e8e94; border-top: 1px solid #0e0e10; }
QSlider::groove:horizontal { height: 4px; background: #34343a; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #8e8e94; border-radius: 2px; }
QSlider::handle:horizontal { background: #d0d0d2; width: 10px; margin: -4px 0; border-radius: 5px; }
QSlider::groove:vertical { width: 4px; background: #34343a; border-radius: 2px; }
QSlider::add-page:vertical { background: #8e8e94; border-radius: 2px; }
QSlider::handle:vertical { background: #d0d0d2; height: 10px; margin: 0 -5px; border-radius: 5px; }
QScrollBar { background: #1c1c1e; width: 10px; height: 10px; }
QScrollBar::handle { background: #3a3a40; border-radius: 4px; min-height: 20px; min-width: 20px; }
QScrollBar::handle:hover { background: #4a4a52; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { width: 0; height: 0; background: none; }
QCheckBox::indicator { width: 12px; height: 12px; border-radius: 2px; }
QCheckBox::indicator:checked { background: #c9c9cd; border: 1px solid #c9c9cd; }
QCheckBox::indicator:unchecked { background: #141416; border: 1px solid #4a4a52; }
QToolTip { background: #2b2b2f; color: #e0e0e2; border: 1px solid #0e0e10; }
"""


class Task(QObject):
    """Run a blocking function in a thread; report finished(result) or failed(message)."""
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(float)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    @Slot()
    def run(self):
        try:
            self.finished.emit(self.fn(self.progress.emit))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class Slider(QSlider):
    """A slider the mouse wheel does not move (the wheel scrolls what is under it)."""

    def wheelEvent(self, e):
        e.ignore()


class MainWindow(QMainWindow):
    PARAM_LABELS = {("transform", "x"): "位置", ("transform", "y"): "位置", ("transform", "scale"): "縮放",
                    ("transform", "rotation"): "旋轉", ("transform", "opacity"): "不透明度",
                    ("clip", "volume"): "音量", ("text", "size"): "字號", ("text", "color"): "文字顏色",
                    ("text", "letter_spacing"): "字距", ("text", "line_spacing"): "行距",
                    ("text", "italic_deg"): "斜體"}

    def __init__(self):
        super().__init__()
        self.resize(1600, 940)
        self.proj = None
        self.history = None
        self.path = None
        self.dirty = False
        self.path_ids = []              # open compound clips, outermost first
        self.tl_pos = {}                # playhead of each timeline while another is open
        self.xml = None                 # truthy once the preview has a project
        self.length = 0
        self.fps = 60.0
        self.pos = 0
        self.playing = False
        self.follow = True              # the timeline scrolls to the playhead after this seek
        self.tasks = []
        self.building = False            # kept for tools: previews no longer build anything
        self.pending_seek = None
        self.fullscreen = None

        # library | preview | inspector
        self.library = LibraryPanel()
        lb = self.library
        lb.importRequested.connect(self.import_media)
        lb.newFolderRequested.connect(self.new_folder)
        lb.renameRequested.connect(self.rename_library)
        lb.deleteRequested.connect(self.delete_library)
        lb.moveRequested.connect(lambda ident, f: self.apply_root("移動素材", library.move, ident, f))
        lb.addRequested.connect(lambda iid: self.place_media(iid, "", self.playhead_us()))

        self.compounds = CompoundPanel()
        self.compounds.showRequested.connect(self.show_compound)
        self.compounds.openRequested.connect(self.open_compound_path)
        self.compounds.renameRequested.connect(self.rename_compound)
        self.compounds.deleteRequested.connect(lambda kid: self.apply_root("刪除複合片段", edit.delete_compound, kid))
        self.left = QTabWidget()
        self.left.addTab(self.library, "素材庫")
        self.left.addTab(self.compounds, "複合片段")

        self.preview = Preview()
        self.preview.clipPicked.connect(lambda c: self.timeline.select(c))
        self.preview.paramsCommitted.connect(self.on_preview_params)
        self.preview.paramsLive.connect(self.live_params)
        self.preview.doubleClicked.connect(self.toggle_fullscreen)

        self.inspector = Inspector()
        ins = self.inspector
        ins.textEdited.connect(self.on_text_edited)
        ins.paramEdited.connect(self.on_param_edited)
        ins.keyToggled.connect(self.on_key_toggled)
        ins.easingChosen.connect(self.on_easing)
        self.mask_panel = Inspector(part="mask")
        mp = self.mask_panel
        mp.paramEdited.connect(self.on_param_edited)
        mp.keyToggled.connect(self.on_key_toggled)
        mp.easingChosen.connect(self.on_easing)
        mp.maskKindChosen.connect(self.on_mask_kind)
        mp.maskInvertChosen.connect(lambda ids, on: self.apply_each("反轉遮罩", edit.set_mask_invert, ids, on))
        mp.maskEnabledChosen.connect(
            lambda ids, on: self.apply_each("啟用遮罩" if on else "停用遮罩", edit.set_mask_enabled, ids, on))
        mp.keyJump.connect(self.jump_key)
        mask_scroll = QScrollArea()
        mask_scroll.setWidget(mp)
        mask_scroll.setWidgetResizable(True)
        ins.keyJump.connect(self.jump_key)
        scroll = QScrollArea()
        scroll.setWidget(self.inspector)
        scroll.setWidgetResizable(True)
        self.curves = CurveEditor()
        cv = self.curves
        cv.keysChanged.connect(self.on_curve_keys)
        cv.seekRequested.connect(self.seek_clip_time)
        cv.addAtPlayhead.connect(self.add_key_at_playhead)
        self.side = QTabWidget()
        self.side.addTab(scroll, "屬性")
        self.side.addTab(mask_scroll, "遮罩")
        # the 遮罩 tab turns the preview into the mask editor
        self.side.currentChanged.connect(lambda _: self.preview.set_mask_mode(self.side.currentWidget() is mask_scroll))
        self.side.addTab(cv, "關鍵幀曲線")

        def tool(name, tip, fn, checkable=False):
            b = QPushButton()
            b.setObjectName("tool")
            b.setIcon(icons.icon(name))
            b.setIconSize(QSize(18, 18))
            b.setToolTip(tip)
            b.setCheckable(checkable)
            b.clicked.connect(fn)
            return b
        self.tool = tool

        self.play_btn = tool("play", "播放 / 暫停（空白鍵）", self.toggle_play)
        self.play_btn.setIconSize(QSize(22, 22))
        full_btn = tool("fullscreen", "全螢幕（F，或在預覽上按兩下）", self.toggle_fullscreen)
        self.time_lbl = QLabel("00:00.00")
        self.time_lbl.setObjectName("time")
        self.dur_lbl = QLabel("")
        self.dur_lbl.setObjectName("viewer")
        self.viewer_lbl = QLabel("")
        self.viewer_lbl.setObjectName("viewer")
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 2, 6, 2)
        bar.addWidget(self.dur_lbl)
        bar.addStretch()
        for name, tip, fn in (("start", "到開頭（Home）", lambda: self.seek(0)),
                              ("prev", "上一幀（←）", lambda: self.step(-1))):
            bar.addWidget(tool(name, tip, fn))
        bar.addWidget(self.play_btn)
        for name, tip, fn in (("next", "下一幀（→）", lambda: self.step(1)),
                              ("end", "到結尾（End）", lambda: self.seek(self.length - 1))):
            bar.addWidget(tool(name, tip, fn))
        bar.addStretch()
        bar.addWidget(full_btn)
        head = QHBoxLayout()
        head.setContentsMargins(8, 3, 8, 3)
        head.addWidget(self.viewer_lbl)
        head.addStretch()
        head.addWidget(self.time_lbl)
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(4, 4, 4, 4)
        head_w, bar_w = QWidget(), QWidget()
        head_w.setObjectName("bar")
        bar_w.setObjectName("bar")
        head_w.setLayout(head)
        bar_w.setLayout(bar)
        cl.addWidget(head_w)
        cl.addWidget(self.preview, 1)
        cl.addWidget(bar_w)

        top = QSplitter(Qt.Horizontal)
        top.addWidget(self.left)
        top.addWidget(center)
        top.addWidget(self.side)
        top.setStretchFactor(1, 1)
        top.setSizes([280, 900, 420])

        # timeline with its toolbar and the compound breadcrumb
        self.timeline = Timeline()
        tl = self.timeline
        tl.seekRequested.connect(lambda f: self.seek(f, follow=False))     # the user is looking there
        tl.clipSelected.connect(lambda c: self.refresh_inspector())
        tl.moveRequested.connect(lambda cid, start, tid: self.apply("移動", edit.move, cid, start, tid))
        tl.trimRequested.connect(
            lambda cid, e, t: self.apply("裁切", edit.trim_start if e == "start" else edit.trim_end, cid, t))
        tl.groupMoveRequested.connect(lambda ids, dt: self.apply("移動", edit.move_many, ids, dt))
        tl.marksChanged.connect(self.marks_changed)
        tl.volumeEdited.connect(self.on_volume_line)
        tl.keyMoveRequested.connect(lambda cid, a, b: self.apply("移動關鍵幀", edit.move_keys_at, cid, a, b))
        tl.trackAction.connect(self.on_track_action)
        tl.clipAction.connect(self.on_clip_action)
        tl.mediaDropped.connect(self.place_media)
        tl.compoundDropped.connect(self.place_compound)
        tl.newTrackRequested.connect(
            lambda cid, start, top: self.apply("移到新軌道", edit.move_to_new_track, cid, start, top))
        # timelines (as in DaVinci Resolve: several per project, one open), as tabs
        tabs_row = QHBoxLayout()
        tabs_row.setContentsMargins(6, 2, 6, 0)
        tabs_row.setSpacing(2)
        self.tl_tabs = QTabBar()
        self.tl_tabs.setObjectName("timelines")
        self.tl_tabs.setExpanding(False)
        self.tl_tabs.setDrawBase(False)
        self.tl_tabs.currentChanged.connect(self._tab_switched)
        self.tl_tabs.tabBarDoubleClicked.connect(lambda i: self.timeline_action("rename", i))
        self.tl_tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tl_tabs.customContextMenuRequested.connect(self._timeline_menu)
        add_tl = tool("plus", "新增時間線", lambda: self.proj and self.apply_root("新增時間線", edit.add_timeline))
        tl_icon = QLabel()
        tl_icon.setPixmap(icons.icon("timeline").pixmap(16, 16))
        tabs_row.addWidget(tl_icon)
        tabs_row.addWidget(self.tl_tabs)
        tabs_row.addWidget(add_tl)
        tabs_row.addStretch()
        self._tabs_updating = False

        tools = QHBoxLayout()
        tools.setContentsMargins(6, 2, 6, 2)
        self.back_btn = QPushButton(" 返回上一層")
        self.back_btn.setIcon(icons.icon("back"))
        self.back_btn.clicked.connect(self.leave_compound)
        self.crumb = QLabel()
        self.crumb.setObjectName("crumb")
        tools.addWidget(self.back_btn)
        tools.addWidget(self.crumb)
        self.buttons = {}
        for key, ic, tip in (("undo", "undo", "復原（Ctrl+Z）"), ("redo", "redo", "重做（Ctrl+Y）"),
                             (None, None, None),
                             ("split", "blade", "在播放頭分割（Ctrl+B）"), ("delete", "trash", "刪除（Delete）"),
                             ("text", "text", "新增文字（Ctrl+T）")):
            if key is None:
                tools.addSpacing(10)
                continue
            b = tool(ic, tip, getattr(self, "do_" + key))
            tools.addWidget(b)
            self.buttons[key] = b
        tools.addStretch()
        self.snap_btn = tool("magnet", "自動吸附（N）：移動、裁切時對齊播放頭和其他片段的邊緣",
                             lambda: None, checkable=True)
        self.snap_btn.setChecked(True)
        self.snap_btn.toggled.connect(self.set_snapping)
        tools.addWidget(self.snap_btn)
        tools.addSpacing(10)
        hl = QLabel()
        hl.setPixmap(icons.icon("height").pixmap(16, 16))
        hl.setToolTip("軌道高度")
        tools.addWidget(hl)
        self.vzoom = Slider(Qt.Horizontal)
        self.vzoom.setRange(65, 400)
        self.vzoom.setValue(100)
        self.vzoom.setFixedWidth(120)
        self.vzoom.setToolTip("也可以在時間軸上 Alt+滾輪；拖曳軌道名稱下方的線調整單一軌道")
        self.vzoom.valueChanged.connect(lambda v: abs(tl.vzoom * 100 - v) > 0.5 and tl.set_vzoom(v / 100))
        tl.vzoomChanged.connect(lambda z: self.vzoom.setValue(round(z * 100)))
        tools.addWidget(self.vzoom)
        lower = QWidget()
        ll = QVBoxLayout(lower)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        ll.addLayout(tabs_row)
        ll.addLayout(tools)
        tl_row = QHBoxLayout()
        tl_row.setContentsMargins(0, 0, 0, 0)
        tl_row.setSpacing(0)
        tl_row.addWidget(tl, 1)
        self.meter = MeterPanel()
        self.meter.masterChanged.connect(self.on_master)
        tl_row.addWidget(self.meter)
        ll.addLayout(tl_row, 1)

        main = QSplitter(Qt.Vertical)
        main.addWidget(top)
        main.addWidget(lower)
        main.setSizes([560, 360])
        self.setCentralWidget(main)

        self.player = Player(self)
        w = self.player.worker
        w.frameReady.connect(self.on_frame)
        w.loaded.connect(self.on_loaded)
        w.failed.connect(lambda m: self.statusBar().showMessage(f"預覽錯誤：{m}", 10000))  # never modal
        w.stateChanged.connect(self.on_state)
        w.levels.connect(self.meter.bars.feed)
        self._menus()
        self._update_title()
        self._update_crumb()
        self._update_buttons()
        self.statusBar().showMessage("檔案 > 匯入剪映草稿，或從素材庫匯入素材")

    # -- menus ------------------------------------------------------------------------------------
    def _menus(self):
        def add(menu, text, key, fn):
            a = QAction(text, self)
            if key:
                a.setShortcut(QKeySequence(key))
            a.triggered.connect(fn)
            menu.addAction(a)

        m = self.menuBar().addMenu("檔案")
        add(m, "新專案", "Ctrl+N", self.new_project)
        add(m, "匯入剪映草稿…", "Ctrl+I", self.import_draft)
        add(m, "開啟專案…", "Ctrl+O", self.open_project)
        add(m, "儲存專案", "Ctrl+S", self.save_project)
        add(m, "另存專案…", "Ctrl+Shift+S", lambda: self.save_project(True))
        m.addSeparator()
        add(m, "匯入素材…", "Ctrl+Shift+I", lambda: self.import_media(self.library.current_folder()))
        add(m, "匯出影片…", "Ctrl+E", self.export)
        m = self.menuBar().addMenu("編輯")
        add(m, "復原", "Ctrl+Z", self.do_undo)
        add(m, "重做", "Ctrl+Y", self.do_redo)
        m.addSeparator()
        add(m, "分割", "Ctrl+B", self.do_split)
        add(m, "刪除", "Delete", self.do_delete)
        add(m, "全選片段", "Ctrl+A", lambda: self.timeline.select_all())
        add(m, "取消選取", "Ctrl+D", lambda: self.timeline.select(None))
        add(m, "新增文字", "Ctrl+T", self.do_text)
        m = self.menuBar().addMenu("播放")
        add(m, "標記入點", "I", lambda: self.set_mark("in"))
        add(m, "標記出點", "O", lambda: self.set_mark("out"))
        add(m, "清除標記", "Alt+X", lambda: self.set_mark(None))
        add(m, "取消選區", "Ctrl+Shift+D", lambda: self.set_mark(None))
        add(m, "自動吸附", "N", lambda: self.snap_btn.toggle())
        m.addSeparator()
        add(m, "全螢幕預覽", "F", self.toggle_fullscreen)
        add(m, "返回上一層", "Esc", self.leave_compound)
        for key, fn in (("Space", self.toggle_play), ("Left", lambda: self.step(-1)),
                        ("Right", lambda: self.step(1)), ("Home", lambda: self.seek(0)),
                        ("End", lambda: self.seek(self.length - 1)), ("Ctrl+Shift+Z", self.do_redo)):
            a = QAction(self)
            a.setShortcut(QKeySequence(key))
            a.setShortcutContext(Qt.WindowShortcut)
            a.triggered.connect(fn)
            self.addAction(a)

    def _update_title(self):
        name = os.path.basename(self.path) if self.path else ("未儲存" if self.proj else "")
        self.setWindowTitle("tesetoa" + (f" — {name}" if name else "") + (" *" if self.dirty else ""))

    def _update_buttons(self):
        h = self.history
        self.buttons["undo"].setEnabled(bool(h and h.undo_stack))
        self.buttons["redo"].setEnabled(bool(h and h.redo_stack))
        has = self.proj is not None
        for k in ("split", "text"):
            self.buttons[k].setEnabled(has)
        self.buttons["delete"].setEnabled(has and self.timeline.selected is not None)

    def _update_timeline_tabs(self):
        self._tabs_updating = True
        while self.tl_tabs.count():
            self.tl_tabs.removeTab(0)
        if self.proj:
            for tl in self.proj["timelines"]:
                i = self.tl_tabs.addTab(tl["name"])
                self.tl_tabs.setTabData(i, tl["id"])
                if tl["id"] == self.proj["active_timeline"]:
                    self.tl_tabs.setCurrentIndex(i)
        self._tabs_updating = False

    def _tab_switched(self, i):
        if not self._tabs_updating and i >= 0:
            self.switch_timeline(self.tl_tabs.tabData(i))

    def switch_timeline(self, tl_id):
        """Open another timeline of the project (not an edit: undo does not step through it)."""
        if not self.proj or tl_id == self.proj["active_timeline"]:
            return
        self.tl_pos[self.proj["active_timeline"]] = self.pos
        edit.open_timeline(self.proj, tl_id)
        self.dirty = True
        self.path_ids = []
        self._switch_level(self.tl_pos.get(tl_id, 0))
        self._update_title()

    def _timeline_menu(self, pos):
        i = self.tl_tabs.tabAt(pos)
        if i < 0:
            return
        menu = QMenu(self)
        menu.addAction("重新命名…", lambda: self.timeline_action("rename", i))
        menu.addAction("建立副本", lambda: self.timeline_action("duplicate", i))
        menu.addSeparator()
        a = menu.addAction("刪除時間線", lambda: self.timeline_action("delete", i))
        a.setEnabled(self.tl_tabs.count() > 1)
        menu.exec(self.tl_tabs.mapToGlobal(pos))

    def timeline_action(self, action, i):
        if i < 0 or not self.proj:
            return
        tid = self.tl_tabs.tabData(i)
        tl = project.timeline(self.proj, tid)
        if action == "rename":
            name, ok = QInputDialog.getText(self, "時間線名稱", "名稱", text=tl["name"])
            if ok:
                self.apply_root("重新命名時間線", edit.rename_timeline, tid, name)
        elif action == "duplicate":
            self.apply_root("複製時間線", lambda root: edit.add_timeline(root, copy_of=tid))
        elif action == "delete":
            if QMessageBox.question(self, "刪除時間線", f"刪除「{tl['name']}」和上面的片段？") == QMessageBox.Yes:
                self.apply_root("刪除時間線", edit.delete_timeline, tid)

    def _update_crumb(self):
        self._update_timeline_tabs()
        self.viewer_lbl.setText(project.timeline(self.proj)["name"] if self.proj else "")
        names = [project.timeline(self.proj)["name"] if self.proj else "主時間軸"]
        node = self.proj
        for cid in self.path_ids:
            _, c = edit.find(node, cid)
            names.append(c.get("name") or "複合片段")
            node = c["compound"]
        self.crumb.setText(" › ".join(names) if self.path_ids else "")
        self.compounds.set_project(self.proj, self.path_ids)
        self.back_btn.setVisible(bool(self.path_ids))

    # -- levels (main timeline / compound clips) ------------------------------------------------
    def container(self, root=None):
        """The tracks owner that is open: the project or a compound clip's content."""
        node = self.proj if root is None else root
        for cid in self.path_ids:
            node = edit.find(node, cid)[1]["compound"]
        return node

    def view(self):
        """Project-like dict for the open level, for the timeline and the preview build."""
        if not self.path_ids:
            return self.proj
        node = self.container()
        return {"width": node["width"], "height": node["height"], "fps": self.proj["fps"],
                "master_gain": self.proj.get("master_gain", 1.0),
                "duration_us": max(project.end_us(node["tracks"]), node.get("duration_us") or 0, 1),
                "tracks": node["tracks"]}

    def show_compound(self, tl_id, parent_path, cid):
        """From the compound list: open the level holding the clip, select it, seek to it."""
        if tl_id and tl_id != self.proj["active_timeline"]:
            self.switch_timeline(tl_id)
        try:
            node = self.proj
            for pid in parent_path:
                node = edit.find(node, pid)[1]["compound"]
            _, c = edit.find(node, cid)
        except edit.EditError:
            return
        self.path_ids = list(parent_path)
        self._switch_level(round(c["start_us"] / US * self.fps), select=c)

    def open_compound_path(self, tl_id, path):
        """From the compound list: edit that compound, at the start of the part that shows."""
        if tl_id and tl_id != self.proj["active_timeline"]:
            self.switch_timeline(tl_id)
        try:
            node, c = self.proj, None
            for pid in path:
                c = edit.find(node, pid)[1]
                node = c["compound"]
        except edit.EditError:
            return
        self.path_ids = list(path)
        self._switch_level(round(c.get("source_start_us", 0) / US * self.fps))

    def enter_compound(self, cid):
        _, c = edit.find(self.container(), cid)
        inner = round((self.playhead_us() - c["start_us"] + c.get("source_start_us", 0)) / US * self.fps)
        self.path_ids.append(cid)
        self._switch_level(max(0, inner))

    def leave_compound(self):
        if not self.path_ids:
            if self.fullscreen:
                self.fullscreen.close()
            return
        cid = self.path_ids.pop()
        _, c = edit.find(self.container(), cid)
        outer = round((c["start_us"] - c.get("source_start_us", 0)) / US * self.fps) + self.pos
        self._switch_level(max(0, outer), select=c)

    def _switch_level(self, pos, select=None):
        self.player.worker.set_playing(False)
        self.timeline.mark_in = self.timeline.mark_out = None      # selections belong to a level
        self.marks_changed()
        self.timeline.set_project(self.view())
        if select is not None:
            self.timeline.select(select)
        self.pos = pos
        self.pending_seek = pos
        self._update_crumb()
        self.refresh_inspector()
        self.rebuild()

    # -- project ----------------------------------------------------------------------------------
    def cache_dir(self):
        if self.path:
            return self.path.replace(".tesetoa.json", "") + ".tesetoa-cache"
        base = QStandardPaths.writableLocation(QStandardPaths.CacheLocation)
        key = hashlib.sha1(str(id(self.proj)).encode()).hexdigest()[:10]
        return os.path.join(base, "unsaved", key)

    def maybe_save(self):
        if not self.dirty:
            return True
        ans = QMessageBox.question(self, "尚未儲存", "專案有未儲存的修改，要先儲存嗎？",
                                   QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if ans == QMessageBox.Save:
            return self.save_project()
        return ans == QMessageBox.Discard

    def new_project(self):
        if self.maybe_save():
            self.path = None
            self.set_project(project.new())

    def import_draft(self):
        if not self.maybe_save():
            return
        fn, _ = QFileDialog.getOpenFileName(self, "匯入剪映草稿（已解密的 draft_content）", "",
                                            "Jianying draft (*.json)")
        if not fn:
            return
        try:
            proj, warnings = jianying.import_draft(fn)
        except Exception as exc:
            QMessageBox.critical(self, "匯入失敗", str(exc))
            return
        self.path = None
        self.set_project(proj)
        if warnings:
            QMessageBox.information(self, "匯入完成", "部分內容無法匯入：\n" + "\n".join(sorted(set(warnings))))

    def open_project(self):
        if not self.maybe_save():
            return
        fn, _ = QFileDialog.getOpenFileName(self, "開啟專案", "", "tesetoa project (*.tesetoa.json)")
        if fn:
            self.path = fn
            self.set_project(project.load(fn))

    def save_project(self, save_as=False):
        if not self.proj:
            return False
        if save_as or not self.path:
            fn, _ = QFileDialog.getSaveFileName(self, "儲存專案", "", "tesetoa project (*.tesetoa.json)")
            if not fn:
                return False
            if not fn.endswith(".tesetoa.json"):
                fn = fn.removesuffix(".json") + ".tesetoa.json"
            self.path = fn
        project.save(self.proj, self.path)
        self.dirty = False
        self._update_title()
        self.statusBar().showMessage("已儲存", 3000)
        return True

    def set_project(self, proj):
        self.relink(proj)
        if not library.lib(proj)["items"]:
            library.add_from_project(proj)         # media already used, e.g. after a draft import
        self.proj = proj
        self.history = edit.History(proj)
        self.meter.set_gain(proj.get("master_gain", 1.0))
        self.dirty = False
        self.path_ids = []
        self.fps = proj["fps"]
        self.timeline.mark_in = self.timeline.mark_out = None
        self.player.worker.set_loop(None)
        self.timeline.set_peaks(waveform.Peaks(self.cache_dir(), on_ready=self.timeline.peaksReady.emit))
        self.timeline.set_project(proj)
        self.library.set_library(library.lib(proj))
        self._update_title()
        self._update_crumb()
        self._update_buttons()
        self.refresh_inspector()
        self.rebuild()

    def relink(self, proj):
        """Offer to find missing media by file name under a folder the user picks."""
        clips = [c for c in project.all_clips(proj) if c.get("media")]
        items = library.lib(proj)["items"]
        refs = [c["media"] for c in clips] + items
        missing = sorted({x["path"] for x in refs if not os.path.exists(x["path"])})
        if not missing:
            return
        ans = QMessageBox.question(self, "找不到素材",
                                   f"有 {len(missing)} 個素材檔案找不到，例如：\n{missing[0]}\n\n要選一個資料夾自動尋找嗎？")
        if ans != QMessageBox.Yes:
            return
        root = QFileDialog.getExistingDirectory(self, "選擇素材所在的資料夾")
        if not root:
            return
        found = {}
        for d, _, files in os.walk(root):
            for f in files:
                found.setdefault(f.lower(), os.path.join(d, f).replace("\\", "/"))
        fixed = 0
        for x in refs:
            name = os.path.basename(x["path"]).lower()
            if not os.path.exists(x["path"]) and name in found:
                x["path"] = found[name]
                fixed += 1
        self.statusBar().showMessage(f"已重新連結 {fixed} 個素材", 8000)

    # -- editing ----------------------------------------------------------------------------------
    def apply(self, label, fn, *args, merge=None, select=None):
        """Run fn(open level, *args) through the undo history; refresh views and preview."""
        return self._do(label, lambda root, *a: fn(self.container(root), *a), args, merge, select)

    def apply_root(self, label, fn, *args, merge=None, select=None):
        """Same, for edits of the whole project (the media library)."""
        return self._do(label, fn, args, merge, select)

    def _do(self, label, fn, args, merge, select):
        if not self.history:
            return None
        try:
            result = self.history.do(label, fn, *args, merge=merge)
        except edit.EditError as exc:
            self.statusBar().showMessage(f"{label}：{exc}", 4000)
            self.timeline.update()
            return None
        except Exception as exc:                       # a file that cannot be read, say
            self.statusBar().showMessage(f"{label}失敗：{exc}", 6000)
            return None
        if self.path_ids:                                # content may outgrow the compound
            node = self.container()
            node["duration_us"] = max(node.get("duration_us") or 0, project.end_us(node["tracks"]))
        if select is not None:
            self.timeline.selected_id = select(result)
        self.after_edit(label)
        return result

    def after_edit(self, label):
        self.dirty = True
        self.meter.set_gain(self.proj.get("master_gain", 1.0))
        try:
            self.container()
        except edit.EditError:                           # an undo removed an open compound
            self.path_ids = []
        sel, ids = self.timeline.selected_id, set(self.timeline.selected_ids)
        self.timeline.set_project(self.view(), keep_view=True)
        self.timeline.selected_id = sel
        if sel:                                          # keep a multiple selection too
            alive = {c["id"] for t in self.timeline.rows for c in t["clips"]}
            self.timeline.selected_ids = (ids & alive) | {sel}
        self.timeline.update()
        self.library.set_library(library.lib(self.proj))
        self._update_title()
        self._update_crumb()
        self._update_buttons()
        self.refresh_inspector()
        self.statusBar().showMessage(label, 2000)
        self.rebuild()

    def do_undo(self):
        if self.history and (label := self.history.undo()):
            self.after_edit(f"已復原：{label}")

    def do_redo(self):
        if self.history and (label := self.history.redo()):
            self.after_edit(f"已重做：{label}")

    def playhead_us(self):
        return self.pos / self.fps * US

    def do_split(self):
        if not self.proj:
            return
        t = self.playhead_us()
        sel = self.timeline.selected_clips()
        targets = [k for k in (sel or [k for tr in self.container()["tracks"] for k in tr["clips"]])
                   if k["start_us"] < t < k["start_us"] + k["duration_us"]]
        if not targets:
            self.statusBar().showMessage("播放頭下沒有片段", 3000)
            return
        ids = [k["id"] for k in targets]

        def split_all(level):
            for cid in ids:
                edit.split(level, cid, t)

        self.apply("分割", split_all)

    def do_delete(self):
        ids = [c["id"] for c in self.timeline.selected_clips()]
        if ids:
            self.timeline.selected_id = None
            self.apply("刪除" if len(ids) == 1 else f"刪除 {len(ids)} 個片段", edit.delete_many, ids)

    def do_text(self):
        if self.proj:
            self.apply("新增文字", edit.add_text, self.playhead_us(), select=lambda c: c["id"])

    def apply_each(self, label, fn, ids, *args, merge=None):
        """fn(level, clip id, *args) for every clip of a selection, as one undo step."""
        def each(level):
            for cid in ids:
                fn(level, cid, *args)

        return self.apply(label, each, merge=merge)

    def on_text_edited(self, ids, fields):
        self.apply_each("修改文字", lambda lvl, cid: edit.set_text(lvl, cid, **fields), ids,
                        merge=("text", tuple(ids), tuple(sorted(fields))))

    def clip_time(self, cid):
        """Playhead time relative to the start of clip cid."""
        return self.playhead_us() - edit.find(self.container(), cid)[1]["start_us"]

    def on_param_edited(self, ids, group, key, value):
        """A value typed in the inspector: set on every selected clip (each at its own
        playhead time, so keyframed ones get or edit the keyframe there)."""
        label = "調整" + self.PARAM_LABELS.get((group, key), "遮罩")
        times = {cid: self.clip_time(cid) for cid in ids}
        self.apply_each(label, lambda lvl, cid: edit.set_param(lvl, cid, group, key, value, times[cid]), ids,
                        merge=("param", tuple(ids), group, key, round(times[ids[0]])))

    def on_key_toggled(self, ids, group, key):
        """◆: when every selected clip has a keyframe here, remove them; else add the missing."""
        times = {cid: self.clip_time(cid) for cid in ids}

        def has(cid):
            c = edit.find(self.container(), cid)[1]
            return edit.key_at((c if group == "clip" else c.get(group) or {}).get(key), times[cid]) is not None

        todo = ids if all(has(cid) for cid in ids) else [cid for cid in ids if not has(cid)]
        self.apply_each("關鍵幀", lambda lvl, cid: edit.toggle_key(lvl, cid, group, key, times[cid]), todo)
        self.curves.select_param(group, key)

    def add_key_at_playhead(self, cid, params):
        """The curve editor's "add here": a keyframe holding the current value, for every
        shown parameter that has none at the playhead."""
        t = self.clip_time(cid)
        c = edit.find(self.container(), cid)[1]
        todo = [(g, k) for g, k in params
                if edit.key_at((c if g == "clip" else c.get(g) or {}).get(k), t) is None]
        if not todo:
            self.statusBar().showMessage("播放頭上已經有關鍵幀", 2000)
            return

        def add_all(level):
            for g, k in todo:
                edit.toggle_key(level, cid, g, k, t)

        self.apply("關鍵幀", add_all)

    def seek_clip_time(self, t):
        c = self.timeline.selected
        if c is not None:
            self.seek(round((c["start_us"] + t) / US * self.fps))

    def on_curve_keys(self, cid, changes, final):
        """Curve editor edits ([(group, key, keys, value if no keys are left)]): shown live
        while dragging, one undo step when released."""
        if final:
            def set_all(level):
                for g, k, keys, keep in changes:
                    if keys:
                        edit.set_keys(level, cid, g, k, keys)
                    else:
                        edit.clear_keys(level, cid, g, k, keep)

            self.apply("刪除關鍵幀" if all(not ch[2] for ch in changes) else "編輯曲線", set_all)
            return
        view = self.snapshot()
        for tr in view["tracks"]:
            for c in tr["clips"]:
                if c["id"] == cid:
                    for g, k, keys, keep in changes:
                        (c if g == "clip" else c.setdefault(g, {}))[k] = {"keys": keys} if keys else keep
        self.player.worker.set_view(view, self.cache_dir())

    def show_selection_props(self):
        clips, t = self.timeline.selected_clips_primary_first(), self.playhead_us()
        self.inspector.show_clips(clips, t, self.fps)
        self.mask_panel.show_clips(clips, t, self.fps)

    def on_easing(self, ids, easing, groups):
        """Apply a curve preset to every parameter (of these groups) with a keyframe at the playhead."""
        times = {cid: self.clip_time(cid) for cid in ids}

        def ease_all(level):
            done = 0
            for cid in ids:
                done += ease_clip(level, cid, times[cid])
            if not done:
                raise edit.EditError("需要播放頭上有關鍵幀，而且後面還有下一個")

        def ease_clip(level, cid, t):
            c = edit.find(level, cid)[1]
            done = 0
            for g in groups:
                holder = c if g == "clip" else (c.get(g) or {})
                for k, p in list(holder.items()):
                    if g == "clip" and k != "volume":
                        continue
                    i = edit.key_at(p, t)
                    if i is not None and i + 1 < len(p["keys"]):
                        edit.set_easing(level, cid, g, k, t, easing)
                        done += 1
            return done

        self.apply("曲線", ease_all)

    def jump_key(self, direction):
        c = self.timeline.selected
        if c is None:
            return
        t = self.clip_time(c["id"])
        times = edit.key_times(c)
        cands = [k for k in times if (k > t + edit.KEY_TOL_US if direction > 0 else k < t - edit.KEY_TOL_US)]
        if not cands:
            self.statusBar().showMessage("沒有更多關鍵幀", 2000)
            return
        k = min(cands) if direction > 0 else max(cands)
        self.seek(round((c["start_us"] + k) / US * self.fps))

    def on_mask_kind(self, ids, kind):
        self.apply_each("遮罩" if kind else "移除遮罩", edit.set_mask, ids, kind)

    def on_preview_params(self, cid, group, values):
        """A drag of the clip or its mask on the canvas: one edit (keyframed values get or
        edit their keyframe at the playhead)."""
        t = self.clip_time(cid)
        if group == "mask":
            label = "遮罩"
        else:
            label = "旋轉" if "rotation" in values else "縮放" if "scale" in values else "移動位置"

        def set_all(level):
            for key, v in values.items():
                edit.set_param(level, cid, group, key, v, t)

        self.apply(label, set_all)

    def on_track_action(self, action, tid):
        t = edit.track_by_id(self.container(), tid)
        if action == "rename":
            name, ok = QInputDialog.getText(self, "軌道名稱", "名稱", text=t.get("name") or t["kind"])
            if ok:
                self.apply("重新命名軌道", edit.rename_track, tid, name)
        elif action == "color":
            col = QColorDialog.getColor(parent=self, title="軌道顏色")
            if col.isValid():
                self.apply("軌道顏色", edit.set_track_color, tid, col.name())
        elif action == "nocolor":
            self.apply("軌道顏色", edit.set_track_color, tid, None)
        elif action.startswith("toggle:"):
            flag = action.split(":", 1)[1]
            label = {"muted": "靜音", "solo": "獨奏", "hidden": "隱藏"}[flag]
            self.apply(("取消" if t.get(flag) else "") + label + "軌道", edit.set_track_flag, tid, flag,
                       not t.get(flag))
        elif action == "gain":
            g = t.get("gain", 1.0)
            db, ok = QInputDialog.getDouble(self, "軌道音量", "音量（dB，-60 以下為靜音）",
                                            20 * math.log10(g) if g > 0 else -60.0, -60.0, 12.0, 1)
            if ok:
                self.apply("軌道音量", edit.set_track_gain, tid, 0.0 if db <= -60 else 10 ** (db / 20))
        elif action in ("up", "down"):
            self.apply("移動軌道", edit.move_track, tid, action == "up")
        elif action.startswith("add:"):
            self.apply("新增軌道", edit.add_track, action.split(":", 1)[1], tid)
        elif action == "delete":
            if t["clips"] and QMessageBox.question(
                    self, "刪除軌道", f"軌道上有 {len(t['clips'])} 個片段，一起刪除嗎？") != QMessageBox.Yes:
                return
            self.apply("刪除軌道", edit.delete_track, tid)

    def on_clip_action(self, action, cid):
        _, c = edit.find(self.container(), cid)
        if action == "enter":
            self.enter_compound(cid)
        elif action == "rename":
            name, ok = QInputDialog.getText(self, "片段名稱", "名稱", text=self.timeline.clip_label(c))
            if ok:
                self.apply("重新命名片段", edit.rename_clip, cid, name)
        elif action == "color":
            col = QColorDialog.getColor(parent=self, title="片段顏色")
            if col.isValid():
                self.apply("片段顏色", edit.set_clip_color, cid, col.name())
        elif action == "nocolor":
            self.apply("片段顏色", edit.set_clip_color, cid, None)
        elif action == "unique":
            self.apply_root("設為獨立", lambda root: edit.make_unique(root, self.container(root), cid))
        elif action == "detach_audio":
            self.apply("分離音訊", edit.detach_audio, cid)
        elif action == "split":
            self.do_split()
        elif action == "delete":
            self.do_delete()

    # -- media library ----------------------------------------------------------------------------
    def import_media(self, folder):
        if not self.proj:
            self.set_project(project.new())
        files, _ = QFileDialog.getOpenFileNames(self, "匯入素材", "",
                                                "Media (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.mp4 *.mov *.mkv "
                                                "*.avi *.webm *.mp3 *.wav *.m4a *.aac *.flac *.ogg);;All files (*)")
        if not files:
            return
        self.statusBar().showMessage(f"讀取 {len(files)} 個檔案…")

        def work(_p):
            out, errors = {}, []
            for f in files:
                p = os.path.abspath(f).replace("\\", "/")
                try:
                    out[p] = library.probe(p)
                except Exception as exc:
                    errors.append(f"{os.path.basename(p)}：{exc}")
            return out, errors

        def done(result):
            probes, errors = result
            if probes:
                self.apply_root("匯入素材", library.add_files, list(probes), folder, probes)
            if errors:
                QMessageBox.warning(self, "部分檔案無法匯入", "\n".join(errors))

        self.run_task(work, done, lambda m: QMessageBox.critical(self, "匯入失敗", m))

    def new_folder(self, parent):
        if not self.proj:
            return
        name, ok = QInputDialog.getText(self, "新資料夾", "名稱", text="新資料夾")
        if ok:
            self.apply_root("新資料夾", library.add_folder, name, parent)

    def rename_library(self, ident):
        target = library.folder(self.proj, ident) if ident.startswith("f") else library.item(self.proj, ident)
        name, ok = QInputDialog.getText(self, "重新命名", "名稱", text=target["name"])
        if ok:
            self.apply_root("重新命名素材", library.rename, ident, name)

    def delete_library(self, ident):
        what = "資料夾（內容會移到上一層）" if ident.startswith("f") else "素材（時間軸上的片段不受影響）"
        if QMessageBox.question(self, "刪除", f"要從素材庫刪除這個{what}嗎？") == QMessageBox.Yes:
            self.apply_root("刪除素材", library.delete, ident)

    def place_compound(self, kid, track_id, start_us):
        if not self.proj:
            return
        self.apply_root("加入複合片段",
                        lambda root: edit.place_compound(root, self.container(root), kid, track_id or None, start_us),
                        select=lambda c: c["id"])

    def rename_compound(self, kid):
        comp = self.proj["compounds"][kid]
        name, ok = QInputDialog.getText(self, "複合片段名稱", "名稱", text=comp.get("name") or "")
        if ok:
            self.apply_root("重新命名複合片段", edit.rename_compound, kid, name)

    def place_media(self, item_id, track_id, start_us):
        if not self.proj:
            return
        self.apply_root("加入素材",
                        lambda root: library.place(self.container(root), root, item_id, track_id or None, start_us),
                        select=lambda c: c["id"])

    # -- inspector / preview overlay --------------------------------------------------------------
    def refresh_inspector(self):
        sel = self.timeline.selected
        self.show_selection_props()
        self.curves.set_clip(sel, self.playhead_us() - sel["start_us"] if sel else 0, self.fps)
        self.preview.set_scene(self.view() if self.proj else None, self.playhead_us(),
                               sel["id"] if sel else None)
        self._update_buttons()

    # -- preview ----------------------------------------------------------------------------------
    def snapshot(self):
        """A private copy of the open level for the renderer thread."""
        return json.loads(json.dumps(self.view()))

    def rebuild(self):
        """Hand the current project state to the live renderer: it shows on the next frame.
        (No MLT document is built for the preview; exports build one.)"""
        if self.proj is None:
            return
        w = self.player.worker
        if self.pending_seek is not None:
            w.pos, self.pending_seek = self.pending_seek, None
        w.set_view(self.snapshot(), self.cache_dir())
        self.xml = True

    def live_params(self, cid, group, values):
        """While a clip or its mask is dragged on the canvas: draw it so without editing yet
        (a keyframed value shows as if its key held the new value)."""
        view = self.snapshot()
        for c in project.walk_clips(view["tracks"]):
            if c["id"] == cid:
                holder = c if group == "clip" else c.setdefault(group, {})
                holder.update(values)
                if group == "transform" and "scale" in values and "scale_y" in holder:
                    holder["scale_y"] = values["scale"]
        self.player.worker.set_view(view, self.cache_dir())

    def run_task(self, fn, done, failed, progress=None):
        th, task = QThread(self), Task(fn)
        task.moveToThread(th)
        th.started.connect(task.run)
        task.finished.connect(done)
        task.failed.connect(failed)
        if progress:
            task.progress.connect(progress)
        for sig in (task.finished, task.failed):
            sig.connect(th.quit)
        th.finished.connect(lambda: self.tasks.remove((th, task)))
        self.tasks.append((th, task))
        th.start()

    # -- playback ---------------------------------------------------------------------------------
    def on_loaded(self, info):
        self.length = info["length"]
        self.statusBar().showMessage(f"{info['width']}×{info['height']} {info['fps']:g}fps，"
                                     f"{self.length} 幀", 3000)

    def on_frame(self, img, pos):
        self.pos = pos
        self.preview.show_image(img)
        if self.fullscreen:
            self.fullscreen.canvas.show_image(img)
        self.timeline.set_position(pos, follow=self.playing or getattr(self, "follow", True))
        self.time_lbl.setText(timecode(pos / self.fps * US, self.fps))
        self.dur_lbl.setText("長度 " + timecode(self.length / self.fps * US, self.fps))
        sel = self.timeline.selected
        if sel is not None:
            self.show_selection_props()
            self.curves.set_time(sel, self.playhead_us() - sel["start_us"])
        self.preview.set_scene(self.view() if self.proj else None, self.playhead_us(),
                               sel["id"] if sel else None)

    def on_state(self, playing):
        self.playing = playing
        self.play_btn.setIcon(icons.icon("pause" if playing else "play"))

    def toggle_play(self):
        if self.proj is not None:
            self.player.worker.set_playing(not self.playing)

    def seek(self, frame, follow=True):
        if self.proj is not None:
            self.follow = follow
            if self.playing:
                self.player.worker.set_playing(False)
            self.player.worker.request_seek(frame)

    def step(self, d):
        self.seek(self.pos + d)

    def toggle_fullscreen(self):
        if self.fullscreen:
            self.fullscreen.close()
            return
        fs = FullscreenPreview()
        fs.canvas.W, fs.canvas.H = self.preview.W, self.preview.H
        fs.canvas.show_image(self.preview.img)
        fs.togglePlay.connect(self.toggle_play)
        fs.step.connect(self.step)
        fs.closed.connect(lambda: setattr(self, "fullscreen", None))
        self.fullscreen = fs
        fs.showFullScreen()

    # -- range and export -------------------------------------------------------------------------
    def on_volume_line(self, cid, vol):
        """The timeline's volume line was dragged: the clip's whole volume (or its keyframes)."""
        def set_vol(level):
            if curves.is_animated(vol):
                edit.set_keys(level, cid, "clip", "volume", vol["keys"])
            else:
                edit.set_param(level, cid, "clip", "volume", round(vol, 5))

        self.apply("調整音量", set_vol)

    def on_master(self, gain, final):
        """The meter's fader: heard at once, one undo step per drag."""
        if self.player.worker.mixer is not None:
            self.player.worker.mixer.master = gain
        if final and self.proj is not None and abs(gain - self.proj.get("master_gain", 1.0)) > 1e-6:
            self.apply_root("主音量", edit.set_master_gain, gain, merge=("master",))

    def set_snapping(self, on):
        self.timeline.snapping = on
        self.statusBar().showMessage("自動吸附：開" if on else "自動吸附：關", 2000)

    def marks_changed(self):
        """The time selection: playback loops inside it."""
        tl = self.timeline
        if tl.mark_in is None and tl.mark_out is None:
            self.player.worker.set_loop(None)
        else:
            a = tl.mark_in or 0
            b = tl.mark_out if tl.mark_out is not None else max(a, self.length - 1)
            self.player.worker.set_loop((a, b))

    def set_mark(self, which):
        tl = self.timeline
        if which is None:
            tl.mark_in = tl.mark_out = None
        elif which == "in":
            tl.mark_in = self.pos
            if tl.mark_out is not None and tl.mark_out < self.pos:
                tl.mark_out = None
        else:
            tl.mark_out = self.pos
            if tl.mark_in is not None and tl.mark_in > self.pos:
                tl.mark_in = None
        tl.update()
        self.marks_changed()

    def export(self):
        if not self.proj:
            return
        while self.path_ids:
            self.leave_compound()
        total = round(self.proj["duration_us"] / US * self.fps)
        default = (self.path.replace(".tesetoa.json", ".mp4") if self.path
                   else os.path.join(os.path.expanduser("~"), "Videos", "tesetoa.mp4"))
        if len(self.proj["timelines"]) > 1:              # one file per timeline
            default = default[:-4] + f" - {project.timeline(self.proj)['name']}.mp4"
        dlg = ExportDialog(self, default, self.fps, total, self.timeline.mark_in, self.timeline.mark_out,
                           self.proj["width"], self.proj["height"])
        if dlg.exec() != QDialog.Accepted:
            return
        out, t0, t1, fmt, opts = dlg.result_options()
        fps = fmt["fps"]
        first = round(t0 / US * fps)                    # frames of the export's own rate
        last = max(first, round(t1 / US * fps) - 1)
        if not out:
            return
        self.player.worker.set_playing(False)
        prog = QProgressDialog("匯出中…", None, 0, 1000, self)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        snapshot = json.loads(json.dumps(self.proj))
        cache = self.cache_dir()

        def work(progress):
            os.makedirs(cache, exist_ok=True)
            xml = build.build(snapshot, cache, os.path.join(cache, "export.mlt"),   # originals, no proxies
                              size=(fmt["width"], fmt["height"]), fps=fps)
            eng = EngineClient(16, 16)        # its own process; the preview stays usable
            try:
                return eng.export(xml, out, progress, threads=os.cpu_count() or 4,
                                  **{"in": first, "out": last}, **opts)
            finally:
                eng.close()

        def done(r):
            prog.close()
            QMessageBox.information(self, "匯出完成", f"{out}\n{fmt['width']}×{fmt['height']}，{fps:g} fps\n"
                                    f"耗時 {r['elapsed']:.0f} 秒")

        self.run_task(work, done, lambda m: (prog.close(), QMessageBox.critical(self, "匯出失敗", m)),
                      lambda p: prog.setValue(int(p * 1000)))

    def closeEvent(self, e):
        if not self.maybe_save():
            e.ignore()
            return
        if self.fullscreen:
            self.fullscreen.close()
        self.player.shutdown()
        super().closeEvent(e)


def run(argv):
    app = QApplication(argv)
    app.setStyleSheet(STYLE)
    win = MainWindow()
    win.show()
    if len(argv) > 1:
        a = argv[1]
        if a.endswith(".tesetoa.json"):
            win.path = a
            win.set_project(project.load(a))
        else:
            proj, _ = jianying.import_draft(a)
            win.set_project(proj)
    return app.exec()
