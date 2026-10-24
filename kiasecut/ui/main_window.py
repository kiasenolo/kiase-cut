"""Main window (Jianying-like): media library, preview, inspector, timeline.

Editing can happen on the main timeline or inside a compound clip (double-click it);
`path_ids` is the chain of compound clips that are open. Every edit runs through one undo
history on the whole project, applied to whichever level is open.
"""
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time

from PySide6.QtCore import (QEvent, QFile, QFileSystemWatcher, QMimeData, QObject, QSettings, QSize, QStandardPaths, Qt,
                            QThread, QTimer, QUrl, Signal, Slot)
from PySide6.QtGui import QAction, QColor, QDesktopServices, QDrag, QKeySequence
from PySide6.QtWidgets import (QApplication, QColorDialog, QComboBox, QDialog, QFileDialog, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMainWindow, QPlainTextEdit, QMessageBox, QProgressDialog, QSpinBox, QTextBrowser,
                               QMenu, QPushButton, QScrollArea, QSlider, QSplitter, QTabBar, QTabWidget, QVBoxLayout,
                               QWidget)

from .. import assets, build, curves, edit, fonts, fx, gpu, library, project, renderexport, userlib, waveform, workspace
from ..client import EngineClient
from ..importers import jianying
from .assets_panel import AssetsPanel
from .font_dialog import FontMapDialog
from .compounds import CompoundPanel
from .curve_editor import CurveEditor
from .beat_panel import BeatPanel
from .effects_panel import EffectsPanel
from .export_dialog import ExportDialog
from .inspector import Inspector
from .library import LibraryPanel
from .player import Player
from .project_dialogs import NewProjectDialog, ProjectInfoDialog
from .settings_dialog import SettingsDialog
from .userlib_panel import UserLibraryPanel
from .vfx_panel import VfxPanel
from . import icons
from .meter import MeterPanel
from .preview import FullscreenPreview, Preview
from .timeline import MEDIA_MIME, US, Timeline, timecode

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
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0px; border: none; subcontrol-origin: border; }
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


class TimelineTabs(QTabBar):
    """Timeline tabs; dragging a tab onto the timeline nests that timeline (as in Resolve)."""

    def mousePressEvent(self, e):
        self._press = (e.position(), self.tabAt(e.position().toPoint())) if e.button() == Qt.LeftButton else None
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        press = getattr(self, "_press", None)
        if press and press[1] >= 0 and (e.buttons() & Qt.LeftButton) and                 (e.position() - press[0]).manhattanLength() > QApplication.startDragDistance() * 2:
            self._press = None
            md = QMimeData()
            md.setData(MEDIA_MIME, f"cmp:{self.tabData(press[1])}".encode())
            drag = QDrag(self)
            drag.setMimeData(md)
            drag.exec(Qt.CopyAction)
            return
        super().mouseMoveEvent(e)


class Slider(QSlider):
    """A slider the mouse wheel does not move (the wheel scrolls what is under it)."""

    def wheelEvent(self, e):
        e.ignore()


def edit_rate(proj):
    """The editor's frames per second (時間線精度, saved with the view): the project's frame
    rate unless the user picked another."""
    v = proj.get("view") if isinstance(proj.get("view"), dict) else {}
    try:
        r = float(v.get("edit_fps") or 0)
    except (TypeError, ValueError):
        r = 0
    return r if 1 <= r <= 1000 else proj["fps"]


def group_holder(c, group, create=False):
    """The dict of clip c that holds the parameters of `group` ("transform", "mask", "clip", ...,
    or "fx:<effect id>" / "fxmask:<effect id>" for a filter's own)."""
    if group.startswith(("fx:", "fxmask:")):
        try:
            return edit.holder(c, group)
        except edit.EditError:
            return {}
    if group == "clip":
        return c
    return c.setdefault(group, {}) if create else (c.get(group) or {})


class MainWindow(QMainWindow):
    taskCall = Signal(object, object)          # (function, argument): run on the UI thread
    PARAM_LABELS = {("transform", "x"): "位置", ("transform", "y"): "位置", ("transform", "scale"): "縮放",
                    ("transform", "scale_y"): "縮放", ("transform", "scale_link"): "縮放連動",
                    ("transform", "rotation"): "旋轉", ("transform", "opacity"): "不透明度",
                    ("clip", "volume"): "音量", ("text", "size"): "字號", ("text", "color"): "文字顏色",
                    ("text", "letter_spacing"): "字距", ("text", "line_spacing"): "行距",
                    ("text", "italic_deg"): "斜體", ("text", "font_path"): "字體", ("clip", "blend"): "混合模式",
                    ("mask", "kind"): "遮罩形狀", ("mask", "invert"): "反轉遮罩"}

    def __init__(self):
        super().__init__()
        self.resize(1600, 940)
        self.proj = None
        self.history = None
        self.path = None
        self.root = None                # the project folder (the folder of the project file)
        self.dirty = False
        self.fs_epoch = 0               # counts changes made to the Media folder from here
        self.ulib = None                # the user's Library (userlib.UserLibrary)
        self.ul_epoch = 0               # counts changes made to the Library folder from here
        self.ul_busy = False
        self.ul_prober = None
        self.fonts = []                 # installed fonts for the text font picker
        self.font_check = None          # 字體對應 waiting for the font list (auto or not), or None
        self.font_dlg = None            # the 字體對應 window while it is open
        self.closing = False
        self.sync_busy = False
        self.sync_retries = 0
        self._last_tick = time.monotonic()
        self.path_ids = []              # open compound clips, outermost first
        self.tl_views = {}              # playhead / scroll / zoom of each timeline while another is open
        self.clipboard = None           # clips copied with 複製 / 剪下 (edit.copy_clips)
        self.open_tls = None            # timelines with a tab (None: all, until the first tab update)
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
        self.taskCall.connect(self._task_call)
        self.setAcceptDrops(True)       # files dragged in from the file manager go to the library

        # library | preview | inspector
        self.library = LibraryPanel()
        lb = self.library
        lb.importRequested.connect(self.import_media)
        lb.newFolderRequested.connect(self.new_folder)
        lb.renameRequested.connect(self.rename_library)
        lb.deleteRequested.connect(self.delete_library)
        lb.moveRequested.connect(self.move_library)
        lb.revealRequested.connect(self.reveal)
        lb.addRequested.connect(lambda iid: self.place_media(iid, "", self.playhead_us()))
        lb.filesDropped.connect(lambda paths, folder: self.drop_files(paths, folder))

        self.compounds = CompoundPanel()
        self.compounds.showRequested.connect(self.show_compound)
        self.compounds.openRequested.connect(self.open_compound_path)
        self.compounds.renameRequested.connect(self.rename_compound)
        self.compounds.timelineRequested.connect(self.switch_timeline)
        self.compounds.deleteRequested.connect(self.delete_compound_item)
        self.compounds.useDeleteRequested.connect(self.delete_use)
        self.ulpanel = UserLibraryPanel()
        self.ulpanel.settingsRequested.connect(self.open_settings)
        self.ulpanel.newFilterRequested.connect(self.new_filter_file)
        self.ulpanel.saveStyleRequested.connect(self.save_text_style)
        self.ulpanel.docRequested.connect(self.show_filter_doc)
        self.ulpanel.checkRequested.connect(self.check_filters)
        for key, panel in self.ulpanel.panels.items():
            panel.importRequested.connect(lambda folder, k=key: self.ul_import(k, folder))
            panel.newFolderRequested.connect(lambda parent, k=key: self.ul_new_folder(k, parent))
            panel.renameRequested.connect(lambda ident, k=key: self.ul_rename(k, ident))
            panel.deleteRequested.connect(lambda ident, k=key: self.ul_delete(k, ident))
            panel.moveRequested.connect(lambda ident, to, k=key: self.ul_move(k, ident, to))
            panel.revealRequested.connect(lambda ident, k=key: self.ul_reveal(k, ident))
            panel.addRequested.connect(lambda ident: self.place_media(ident, "", self.playhead_us()))
            panel.filesDropped.connect(lambda paths, folder, k=key: self.ul_drop(k, paths, folder))
            panel.extra_menu = lambda menu, ident, k=key: self.ul_menu(k, menu, ident)
        self.vfx = VfxPanel()
        self.vfx.addClipRequested.connect(lambda ref: self.add_filter_clip(ref))
        self.vfx.applyRequested.connect(self.apply_filter_to_selected)
        self.vfx.docRequested.connect(self.show_filter_doc)
        self.assets = AssetsPanel()
        self.assets.addRequested.connect(lambda ident: self.place_asset(ident, "", self.playhead_us()))
        self.left = QTabWidget()
        self.left.addTab(self.library, "專案素材")
        self.left.addTab(self.assets, "內建素材")
        self.left.addTab(self.ulpanel, "Library")
        self.left.addTab(self.vfx, "VFX")
        self.left.addTab(self.compounds, "複合片段")

        self.preview = Preview()
        self.preview.clipPicked.connect(lambda c: self.timeline.select(c))
        self.preview.paramsCommitted.connect(self.on_preview_params)
        self.preview.paramsLive.connect(self.live_params)
        self.preview.doubleClicked.connect(self.toggle_fullscreen)
        self.render_w = {"main": 0, "full": 0}       # width each view shows frames at; the player draws the largest
        self.preview.renderWidth.connect(lambda w: self.set_render_width("main", w))

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
        mp.maskInvertChosen.connect(lambda ids, on: self.apply_each_timed("反轉遮罩", edit.set_mask_invert, ids, on))
        mp.maskEnabledChosen.connect(
            lambda ids, on: self.apply_each("啟用遮罩" if on else "停用遮罩", edit.set_mask_enabled, ids, on))
        mp.keyJump.connect(self.jump_key)
        mask_scroll = QScrollArea()
        mask_scroll.setWidget(mp)
        mask_scroll.setWidgetResizable(True)
        ins.keyJump.connect(self.jump_key)
        ins.liveEdited.connect(self.on_live_edit)
        mp.liveEdited.connect(self.on_live_edit)
        scroll = QScrollArea()
        scroll.setWidget(self.inspector)
        scroll.setWidgetResizable(True)
        self.curves = CurveEditor()
        cv = self.curves
        cv.keysChanged.connect(self.on_curve_keys)
        cv.seekRequested.connect(self.seek_clip_time)
        cv.addAtPlayhead.connect(self.add_key_at_playhead)
        cv.keyJump.connect(self.jump_key)
        self.effects = EffectsPanel()
        ef = self.effects
        ef.addRequested.connect(lambda cid, ref: self.apply("新增效果", edit.add_effect, cid, ref, select=lambda c: c["id"]))
        ef.browseRequested.connect(self.browse_effect)
        ef.removeRequested.connect(lambda cid, eid: self.apply("移除效果", edit.remove_effect, cid, eid))
        ef.enabledChosen.connect(lambda cid, eid, on: self.apply(
            "啟用效果" if on else "停用效果", edit.set_effect_enabled, cid, eid, on))
        ef.moveRequested.connect(lambda cid, eid, d: self.apply("調整效果順序", edit.move_effect, cid, eid, d))
        ef.maskKindChosen.connect(lambda cid, eid, kind: self.apply(
            "效果範圍" if kind else "移除效果範圍", edit.set_effect_mask, cid, eid, kind, self.clip_time(cid)))
        ef.maskInvertChosen.connect(lambda cid, eid, on: self.apply(
            "反轉效果範圍", edit.set_effect_mask_invert, cid, eid, on, self.clip_time(cid)))
        ef.paramEdited.connect(self.on_param_edited)
        ef.keyToggled.connect(self.on_key_toggled)
        ef.liveEdited.connect(self.on_live_edit)
        ef.docRequested.connect(self.show_filter_doc)
        ef.revealFilter.connect(self.reveal_path)
        fx_scroll = QScrollArea()
        fx_scroll.setWidget(ef)
        fx_scroll.setWidgetResizable(True)
        self.side = QTabWidget()
        self.side.addTab(scroll, "屬性")
        self.side.addTab(fx_scroll, "效果")
        self.side.addTab(mask_scroll, "遮罩")
        self.beats = BeatPanel()
        self.beats.beatEdited.connect(self.on_beat_edited)
        self.beats.resetRequested.connect(lambda cid: self.apply("重置 BPM 對齊", edit.clear_beat, cid))
        beat_scroll = QScrollArea()
        beat_scroll.setWidget(self.beats)
        beat_scroll.setWidgetResizable(True)
        self.side.addTab(beat_scroll, "節拍")
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
        top.setSizes([360, 840, 420])

        # timeline with its toolbar and the compound breadcrumb
        self.timeline = Timeline()
        tl = self.timeline
        tl.seekRequested.connect(lambda f: self.seek(f, follow=False))     # the user is looking there
        tl.clipSelected.connect(lambda c: self.refresh_inspector())
        tl.moveRequested.connect(lambda cid, start, tid: self.apply("移動", edit.move, cid, start, tid))
        tl.trimRequested.connect(
            lambda cid, e, t: self.apply("裁切", edit.trim_start if e == "start" else edit.trim_end, cid, t))
        tl.groupMoveRequested.connect(lambda ids, dt, dr: self.apply("移動", edit.move_many, ids, dt, dr))
        tl.marksChanged.connect(self.marks_changed)
        tl.clipDragging.connect(lambda cid, start, dur: self.inspector.show_live_time(cid, start, dur, self.fps))
        tl.volumeEdited.connect(self.on_volume_line)
        tl.keyMoveRequested.connect(lambda cid, a, b: self.apply("移動關鍵幀", edit.move_keys_at, cid, a, b))
        tl.trackAction.connect(self.on_track_action)
        tl.clipAction.connect(self.on_clip_action)
        tl.mediaDropped.connect(self.place_media)
        tl.assetDropped.connect(self.place_asset)
        tl.compoundDropped.connect(self.place_compound)
        tl.replaceDropped.connect(self.replace_source)
        tl.filterDropped.connect(self.on_filter_dropped)
        tl.filesDropped.connect(lambda paths, tid, start: self.drop_files(
            paths, self.library.current_folder(), (tid, start)))
        tl.newTrackRequested.connect(
            lambda cid, start, top: self.apply("移到新軌道", edit.move_to_new_track, cid, start, top))
        # timelines (as in DaVinci Resolve: several per project, one open), as tabs
        tabs_row = QHBoxLayout()
        tabs_row.setContentsMargins(6, 2, 6, 0)
        tabs_row.setSpacing(2)
        self.tl_tabs = TimelineTabs()
        self.tl_tabs.setObjectName("timelines")
        self.tl_tabs.setExpanding(False)
        self.tl_tabs.setDrawBase(False)
        self.tl_tabs.setTabsClosable(False)         # our own X buttons (see _update_timeline_tabs)
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
        tools.addSpacing(16)
        tools.addWidget(QLabel("播放"))
        self.play_mode = QComboBox()
        self.play_mode.addItem("停在暫停處", "stay")
        self.play_mode.addItem("回到開始處", "return")
        self.play_mode.setToolTip("按空白鍵停止播放時：停在當下的位置，或回到這次開始播放的位置")
        i = self.play_mode.findData(str(self.settings().value("play_mode", "stay")))
        self.play_mode.setCurrentIndex(max(0, i))
        self.play_mode.currentIndexChanged.connect(
            lambda _i: self.settings().setValue("play_mode", self.play_mode.currentData()))
        tools.addWidget(self.play_mode)
        tools.addSpacing(10)
        tools.addWidget(QLabel("精度"))
        self.edit_fps_box = QSpinBox()
        self.edit_fps_box.setRange(0, 1000)
        self.edit_fps_box.setSpecialValueText("跟專案")
        self.edit_fps_box.setSuffix(" 格/秒")
        self.edit_fps_box.setKeyboardTracking(False)
        self.edit_fps_box.setToolTip("時間線每秒幾格：播放頭、關鍵幀、分割、步進（←/→）的最小單位。\n"
                                     "只影響剪輯，不影響輸出：匯出照專案（或匯出設定）的幀率。")
        self.edit_fps_box.valueChanged.connect(lambda v: self.set_edit_fps(v or None))
        tools.addWidget(self.edit_fps_box)
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
        # the library follows the Media folder: look again when something in it changes, when
        # this window comes back to the front, and after our own file operations
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _p: self.request_sync(700))
        self.ul_watcher = QFileSystemWatcher(self)         # the same for the user's Library folder
        self.ul_watcher.directoryChanged.connect(lambda _p: self.request_ul_sync(700))
        self.ul_timer = QTimer(self, singleShot=True)
        self.ul_timer.timeout.connect(self.sync_userlib)
        self.sync_timer = QTimer(self, singleShot=True)
        self.sync_timer.timeout.connect(self.sync_library)
        self.clock = QTimer(self, interval=5000)        # time spent on the project; autosave
        self.clock.timeout.connect(self._tick)
        self.clock.start()
        gpu.enabled = str(self.settings().value("gpu", True)).lower() not in ("false", "0")
        self.autosave_timer = QTimer(self, interval=self.autosave_min() * 60 * 1000)
        self.autosave_timer.timeout.connect(self._autosave)
        self.autosave_timer.start()
        self.apply_library_root(self.library_root())
        self.start_font_scan()
        self._menus()
        self._update_title()
        self._update_crumb()
        self._update_buttons()
        self.statusBar().showMessage("檔案 > 新專案…（或開啟最近的專案、匯入剪映草稿）")

    # -- menus ------------------------------------------------------------------------------------
    def _menus(self):
        def add(menu, text, key, fn):
            a = QAction(text, self)
            if key:
                a.setShortcut(QKeySequence(key))
            a.triggered.connect(fn)
            menu.addAction(a)

        m = self.menuBar().addMenu("檔案")
        add(m, "新專案…", "Ctrl+N", self.new_project)
        add(m, "開啟專案…", "Ctrl+O", self.open_project)
        self.recent_menu = m.addMenu("最近的專案")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        add(m, "儲存專案", "Ctrl+S", self.save_project)
        add(m, "另存新檔…", "Ctrl+Shift+S", lambda: self.save_project(True))
        m.addSeparator()
        add(m, "專案資訊…", "F11", self.show_project_info)
        add(m, "開啟專案資料夾", None, lambda: self.reveal(None))
        add(m, "整理素材到專案資料夾", None, self.collect_external)
        m.addSeparator()
        add(m, "設定…", "Ctrl+,", self.open_settings)
        m.addSeparator()
        add(m, "匯入剪映草稿…", "Ctrl+I", self.import_draft)
        add(m, "匯入素材…", "Ctrl+Shift+I", lambda: self.import_media(self.library.current_folder()))
        add(m, "匯出影片…", "Ctrl+E", self.export)
        m = self.menuBar().addMenu("編輯")
        add(m, "復原", "Ctrl+Z", self.do_undo)
        add(m, "重做", "Ctrl+Y", self.do_redo)
        m.addSeparator()
        add(m, "複製", "Ctrl+C", self.do_copy)
        add(m, "剪下", "Ctrl+X", lambda: self.do_copy(cut=True))
        add(m, "貼上", "Ctrl+V", self.do_paste)
        add(m, "建立副本", "Ctrl+Shift+C", self.do_duplicate)
        m.addSeparator()
        add(m, "分割", "Ctrl+B", self.do_split)
        add(m, "刪除", "Delete", self.do_delete)
        add(m, "移到上面的軌道", "Ctrl+Up", lambda: self.do_move_rows(-1))
        add(m, "移到下面的軌道", "Ctrl+Down", lambda: self.do_move_rows(1))
        add(m, "全選片段", "Ctrl+A", lambda: self.timeline.select_all())
        add(m, "取消選取", "Ctrl+D", lambda: self.timeline.select(None))
        add(m, "新增文字", "Ctrl+T", self.do_text)
        m.addSeparator()
        add(m, "字體對應…", None, lambda: self.check_fonts(auto=False))
        m = self.menuBar().addMenu("濾鏡")
        self.filter_menu = m.addMenu("新增濾鏡片段（在播放頭）")
        self.filter_menu.aboutToShow.connect(lambda: self._fill_filter_menu(self.filter_menu, self.add_filter_clip))
        self.apply_menu = m.addMenu("套用到選取的片段")
        self.apply_menu.aboutToShow.connect(lambda: self._fill_filter_menu(self.apply_menu, self.apply_filter_to_selected))
        m.addSeparator()
        add(m, "新增自訂濾鏡檔…", None, lambda: self.new_filter_file(None))
        add(m, "濾鏡寫法說明…", None, self.show_filter_doc)
        add(m, "檢查所有濾鏡", None, self.check_filters)
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
        name = workspace.title_of(self.proj, self.path) if self.proj else ""
        self.setWindowTitle("KiaseCut" + (f" — {name}" if name else "") + (" *" if self.dirty else ""))
        self.library.set_origin(f"專案資料夾：{os.path.basename(self.root)} / Media" if self.root else "（還沒有專案）",
                                self.root or "")

    def _update_buttons(self):
        h = self.history
        self.buttons["undo"].setEnabled(bool(h and h.undo_stack))
        self.buttons["redo"].setEnabled(bool(h and h.redo_stack))
        has = self.proj is not None
        for k in ("split", "text"):
            self.buttons[k].setEnabled(has)
        self.buttons["delete"].setEnabled(has and self.timeline.selected is not None)

    def _update_timeline_tabs(self):
        """One tab per open timeline, each with an X (closing hides the tab, the timeline stays
        in the project and in the compound list). The open one always has a tab."""
        self._tabs_updating = True
        while self.tl_tabs.count():
            self.tl_tabs.removeTab(0)
        if self.proj:
            ids = [tl["id"] for tl in self.proj["timelines"]]
            if self.open_tls is None:
                self.open_tls = list(ids)
            self.open_tls = [t for t in self.open_tls if t in ids]
            if self.proj["active_timeline"] not in self.open_tls:
                self.open_tls.append(self.proj["active_timeline"])
            many = len(self.open_tls) > 1
            for tid in self.open_tls:
                tl = project.timeline(self.proj, tid)
                i = self.tl_tabs.addTab(tl["name"])
                self.tl_tabs.setTabData(i, tid)
                close = self.tool("close", "關閉這個時間線（內容保留，可從「複合片段」重新打開）",
                                  lambda _=False, t=tid: self.close_timeline(t))
                close.setIconSize(QSize(12, 12))
                close.setFixedSize(18, 18)
                self.tl_tabs.setTabButton(i, QTabBar.RightSide, close)
                close.setVisible(many)                    # (setTabButton shows it)
                if tid == self.proj["active_timeline"]:
                    self.tl_tabs.setCurrentIndex(i)
        self._tabs_updating = False

    def close_timeline(self, tid):
        """Close a timeline's tab; the one before / after it opens if it was the open one."""
        if not self.proj or self.open_tls is None or len(self.open_tls) < 2 or tid not in self.open_tls:
            return
        i = self.open_tls.index(tid)
        self.open_tls.remove(tid)
        if tid == self.proj["active_timeline"]:
            self.switch_timeline(self.open_tls[max(0, i - 1)])
        else:
            self._update_timeline_tabs()

    def _tab_switched(self, i):
        if not self._tabs_updating and i >= 0:
            self.switch_timeline(self.tl_tabs.tabData(i))

    def switch_timeline(self, tl_id):
        """Open another timeline of the project (not an edit: undo does not step through it)."""
        if not self.proj or tl_id == self.proj["active_timeline"]:
            return
        self.tl_views[self.proj["active_timeline"]] = self.level_view()
        edit.open_timeline(self.proj, tl_id)
        self.dirty = True
        self.open_view(self.tl_views.get(tl_id, {}))
        self._update_title()

    def level_view(self):
        """Where the open timeline is looked at: playhead, open compounds, scroll, zoom,
        track heights."""
        v = dict(self.timeline.view_state(), pos=self.pos)
        if self.path_ids:
            v["path"] = list(self.path_ids)
        return v

    def view_state(self):
        """Every timeline's level_view, stored in the project file when it is saved."""
        tls = dict(self.tl_views)
        tls[self.proj["active_timeline"]] = self.level_view()
        out = {"vzoom": round(self.timeline.vzoom, 4), "timelines": tls}
        if self.fps != self.proj["fps"]:
            out["edit_fps"] = self.fps
        return out

    def open_view(self, v):
        """Open the active timeline as level_view() left it (a compound that is gone opens
        the timeline itself)."""
        path = v.get("path") if isinstance(v.get("path"), list) else []
        try:
            node = self.proj
            for cid in path:
                node = edit.find(node, cid)[1]["compound"]
        except (edit.EditError, KeyError, TypeError):
            path = []
        self.path_ids = list(path)
        try:
            pos = max(0, int(v.get("pos", 0)))
        except (TypeError, ValueError):
            pos = 0
        self._switch_level(pos)
        if v.get("px_per_s"):
            self.timeline.set_view_state(v)
            self.follow = False                          # (the saved scroll, not one around the playhead)

    def _timeline_menu(self, pos):
        i = self.tl_tabs.tabAt(pos)
        if i < 0:
            return
        menu = QMenu(self)
        menu.addAction("重新命名…", lambda: self.timeline_action("rename", i))
        menu.addAction("建立副本", lambda: self.timeline_action("duplicate", i))
        a = menu.addAction("關閉時間線", lambda: self.close_timeline(self.tl_tabs.tabData(i)))
        a.setEnabled(self.tl_tabs.count() > 1)
        menu.addSeparator()
        a = menu.addAction("刪除時間線", lambda: self.timeline_action("delete", i))
        a.setEnabled(self.tl_tabs.count() > 1)
        menu.exec(self.tl_tabs.mapToGlobal(pos))

    def timeline_action(self, action, i):
        if i >= 0:
            self.timeline_do(action, self.tl_tabs.tabData(i))

    def timeline_do(self, action, tid):
        if not self.proj:
            return
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
        if project.is_static(c):                         # its picture is the moment still_us
            inner = round(c["compound"].get("still_us", 0) / US * self.fps)
        else:
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
        if project.is_static(c):                         # (its time does not map onto the outer one)
            outer = round(c["start_us"] / US * self.fps)
        else:
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
        if self.root:
            return workspace.cache_dir(self.root)
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

    # recent projects and settings live in the user's profile, not in a project
    SETTINGS = ("KiaseCut", "KiaseCut")
    OLD_SETTINGS = ("tesetoa", "tesetoa")           # the program's earlier name: carried over once

    def settings(self):
        s = QSettings(*self.SETTINGS)
        if not s.allKeys():
            old = QSettings(*self.OLD_SETTINGS)
            for k in old.allKeys():
                s.setValue(k, old.value(k))
            s.sync()
        return s

    def default_location(self):
        s = self.settings().value("project_dir")
        if s and os.path.isdir(str(s)):
            return str(s)
        docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or os.path.expanduser("~")
        old = os.path.join(docs, "tesetoa")                 # the program's earlier name
        if os.path.isdir(old) and not os.path.isdir(os.path.join(docs, "KiaseCut")):
            return old.replace("\\", "/")
        return os.path.join(docs, "KiaseCut").replace("\\", "/")

    def recent(self):
        v = self.settings().value("recent", [])
        v = v if isinstance(v, list) else ([v] if v else [])
        return [str(p) for p in v]

    def remember(self, path):
        s = self.settings()
        s.setValue("recent", [path] + [p for p in self.recent() if p != path][:9])
        s.setValue("project_dir", os.path.dirname(workspace.root_of(path)))

    def _fill_recent(self):
        m = self.recent_menu
        m.clear()
        have = [p for p in self.recent() if os.path.exists(p)]
        for p in have:
            m.addAction(f"{workspace.project_name(p)}    {workspace.root_of(p)}", lambda p=p: self.open_recent(p))
        if not have:
            m.addAction("（沒有）").setEnabled(False)
        else:
            m.addSeparator()
            m.addAction("清除清單", lambda: self.settings().setValue("recent", []))

    def open_recent(self, path):
        if self.maybe_save():
            self.open_path(path)

    def ensure_project(self):
        """Media goes into a project folder, so there has to be a project first."""
        return bool(self.proj) or self.new_project()

    def new_project(self):
        if not self.maybe_save():
            return False
        dlg = NewProjectDialog(self, self.default_location())
        if dlg.exec() != QDialog.Accepted:
            return False
        location, name, w, h, fps = dlg.values()
        try:
            os.makedirs(location, exist_ok=True)
            proj, path = workspace.create(location, name, w, h, fps)
        except Exception as exc:
            QMessageBox.critical(self, "無法建立專案", str(exc))
            return False
        self.open_loaded(proj, path)
        return True

    def open_loaded(self, proj, path):
        self.path = path
        self.set_project(proj)
        self.remember(path)

    def import_draft(self):
        if not self.maybe_save():
            return
        fn, _ = QFileDialog.getOpenFileName(self, "匯入剪映草稿（已解密的 draft_content）", "",
                                            "Jianying draft (*.json)")
        if fn:
            self.import_draft_file(fn)

    def import_draft_file(self, fn):
        try:
            proj, warnings = jianying.import_draft(fn)
        except Exception as exc:
            QMessageBox.critical(self, "匯入失敗", str(exc))
            return
        guess = os.path.basename(os.path.dirname(os.path.abspath(fn))) or "剪映草稿"
        dlg = NewProjectDialog(self, self.default_location(), guess, (proj["width"], proj["height"], proj["fps"]),
                               "匯入剪映草稿")
        if dlg.exec() != QDialog.Accepted:
            return
        location, name = dlg.values()[:2]
        try:
            os.makedirs(location, exist_ok=True)
            path = workspace.adopt(proj, location, name)
        except Exception as exc:
            QMessageBox.critical(self, "無法建立專案", str(exc))
            return
        self.open_loaded(proj, path)
        if warnings:
            QMessageBox.information(self, "匯入完成", "部分內容無法匯入：\n" + "\n".join(sorted(set(warnings))))
        self.collect_external(ask=False)             # the draft's media are copied into the project

    def open_project(self):
        if not self.maybe_save():
            return
        fn, _ = QFileDialog.getOpenFileName(self, "開啟專案", self.default_location(),
                                            "KiaseCut 專案 (*.kiasecut.json *.tesetoa.json)")
        if fn:
            self.open_path(fn)

    def open_path(self, fn):
        try:
            proj = project.load(fn)
        except Exception as exc:
            QMessageBox.critical(self, "無法開啟專案", f"{fn}\n{exc}")
            return False
        old_format = "info" not in proj
        workspace.opened(proj, fn)
        self.open_loaded(proj, fn)
        if old_format and library.external_media(proj, self.root):
            self.collect_external(ask=True)
        return True

    def save_project(self, save_as=False):
        if not self.proj:
            return False
        if not self.path:
            if not self.new_location_for_unsaved():
                return False
        elif save_as:
            old = workspace.project_name(self.path)
            name, ok = QInputDialog.getText(self, "另存新檔", "專案檔名稱（存在同一個專案資料夾裡，共用素材）",
                                            text=old + " 2")
            name = workspace.safe_name(name, "")
            if not ok or not name:
                return False
            fn = workspace.project_file(self.root, name)
            if os.path.exists(fn) and QMessageBox.question(self, "覆蓋", f"「{name}」已經存在，要覆蓋嗎？") != QMessageBox.Yes:
                return False
            self.path = fn
        self.proj["view"] = self.view_state()
        try:
            workspace.save(self.proj, self.path)
        except OSError as exc:
            QMessageBox.critical(self, "儲存失敗", str(exc))
            return False
        self.dirty = False
        self.remember(self.path)
        self._update_title()
        self.statusBar().showMessage("已儲存", 3000)
        return True

    def new_location_for_unsaved(self):
        """A project without a folder (made by a tool): ask where its folder goes."""
        dlg = NewProjectDialog(self, self.default_location(), "新專案", (self.proj["width"], self.proj["height"],
                                                                       self.proj["fps"]), "儲存專案")
        if dlg.exec() != QDialog.Accepted:
            return False
        location, name = dlg.values()[:2]
        try:
            os.makedirs(location, exist_ok=True)
            self.path = workspace.adopt(self.proj, location, name)
        except Exception as exc:
            QMessageBox.critical(self, "無法建立專案", str(exc))
            return False
        self.root = workspace.root_of(self.path)
        self.collect_external(ask=False)
        self.watch_media()
        return True

    def set_project(self, proj):
        self.root = workspace.root_of(self.path) if self.path else None
        if self.root:                       # built-in assets are drawn again rather than looked for
            assets.restore(project.all_clips(proj), workspace.media_dir(self.root))
        self.relink(proj)
        workspace.ensure_info(proj, self.path)
        if self.root:
            workspace.ensure_layout(self.root)
        if not library.lib(proj)["items"]:
            library.add_from_project(proj)         # media already used, e.g. after a draft import
        self.proj = proj
        fonts.use_map(self.font_map_here())          # before anything draws its texts
        self.history = edit.History(proj)
        self.meter.set_gain(proj.get("master_gain", 1.0))
        self.dirty = False
        self.path_ids = []
        self.open_tls = None
        self.tl_views = {}
        self.fps = edit_rate(proj)
        self.timeline.edit_fps = self.fps if self.fps != proj["fps"] else None
        self.edit_fps_box.blockSignals(True)
        self.edit_fps_box.setValue(round(self.fps) if self.fps != proj["fps"] else 0)
        self.edit_fps_box.blockSignals(False)
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
        saved = proj.get("view") if isinstance(proj.get("view"), dict) else {}
        if saved.get("vzoom"):
            self.timeline.set_vzoom(float(saved["vzoom"]))
        views = saved.get("timelines") if isinstance(saved.get("timelines"), dict) else {}
        self.tl_views = {k: v for k, v in views.items() if isinstance(v, dict) and k != proj["active_timeline"]}
        if isinstance(views.get(proj["active_timeline"]), dict):
            self.open_view(views[proj["active_timeline"]])
        self._last_tick = time.monotonic()
        self.watch_media()
        self.request_sync(0)
        self.check_fonts(auto=True)

    # -- project folder: info, time spent, backups -----------------------------------------------
    def show_project_info(self):
        if not self.proj:
            return
        self._tick()
        mroot = workspace.media_dir(self.root) if self.root else None
        items = library.lib(self.proj)["items"]
        n_clips = sum(1 for _ in project.all_clips(self.proj))
        size = workspace.show_size(workspace.folder_size(mroot)) if mroot and os.path.isdir(mroot) else "—"
        stats = (f"{len(self.proj['timelines'])} 條時間線，{n_clips} 個片段\n"
                 f"素材庫 {len(items)} 個檔案（Media 資料夾 {size}）\n"
                 f"長度 {timecode(self.proj['duration_us'], self.proj['fps'])}")
        dlg = ProjectInfoDialog(self, self.proj, self.path, stats)
        dlg.openFolder.connect(lambda: self.reveal(None))
        if dlg.exec() != QDialog.Accepted:
            return
        info = workspace.info(self.proj)
        new = dlg.values()
        if any(info.get(k) != v for k, v in new.items()):
            info.update(new)
            self.dirty = True
            self._update_title()

    def _tick(self):
        """Every few seconds: add the time the window was in use to the project's time spent."""
        now = time.monotonic()
        dt, self._last_tick = min(now - self._last_tick, 30.0), now
        if self.proj and self.isActiveWindow():
            info = workspace.info(self.proj)
            info["time_spent_s"] = round(float(info.get("time_spent_s", 0)) + dt, 1)

    def _autosave(self):
        if self.proj and self.path and self.dirty:
            self.proj["view"] = self.view_state()
            try:
                workspace.autosave(self.proj, self.path)
            except OSError:
                pass

    def reveal(self, ident):
        """Show a library entry (None: the Media folder) in the file manager."""
        if not self.root:
            return
        target = workspace.media_dir(self.root)
        select = False
        if ident:
            if ident.startswith("f"):
                target = library.folder_dir(self.proj, self.root, ident)
            else:
                target, select = library.item(self.proj, ident)["path"], True
        if not os.path.exists(target):
            target = workspace.media_dir(self.root)
            select = False
        if select and sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", target.replace("/", "\\")])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(target) if select else target))

    # -- media folder <-> library -----------------------------------------------------------------
    def watch_media(self):
        old = self.watcher.directories()
        if old:
            self.watcher.removePaths(old)
        mroot = workspace.media_dir(self.root) if self.root else None
        if mroot and os.path.isdir(mroot):
            dirs = [d for d, _, _ in os.walk(mroot) if not any(p.startswith(".") for p in d[len(mroot):].split(os.sep))]
            self.watcher.addPaths(dirs)

    def request_sync(self, delay=500):
        if self.root:
            self.sync_timer.start(delay)

    def sync_library(self):
        """Read the Media folder (off the UI thread: new files are probed) and make the
        library match it."""
        if not self.proj or not self.root:
            return
        if self.sync_busy:
            self.request_sync(300)
            return
        self.sync_busy, root, epoch = True, self.root, self.fs_epoch
        known = library.known_paths(self.proj)

        def done(res):
            self.sync_busy = False
            if not self.proj or self.root != root:
                return
            if epoch != self.fs_epoch:                    # our own file operation came in between
                self.request_sync(100)
                return
            if library.apply_scan(self.proj, root, res):
                self.library.set_library(library.lib(self.proj))
            self.watch_media()
            if res["failed"] and self.sync_retries < 4:   # a file still being written: look again
                self.sync_retries += 1
                self.request_sync(3000)
            else:
                if res["failed"]:
                    self.statusBar().showMessage(f"無法讀取：{os.path.basename(res['failed'][0])}", 6000)
                self.sync_retries = 0

        def failed(msg):
            self.sync_busy = False
            self.statusBar().showMessage(f"整理素材庫失敗：{msg}", 6000)

        self.run_task(lambda _p: library.scan(root, known), done, failed)

    def changeEvent(self, e):
        if e.type() == QEvent.ActivationChange and self.isActiveWindow():
            self.request_sync(300)
            self.request_ul_sync(300)
        super().changeEvent(e)

    def paths_changed(self, pairs, label):
        """Files were renamed / moved: the undo history follows them, and the views refresh."""
        if pairs and self.history:
            def fix(text):
                for old, new, is_dir in pairs:
                    text = library.retarget_text(text, old, new, is_dir)
                return text
            self.history.rewrite(fix)
        self.fs_epoch += 1
        self.after_edit(label)
        self.request_sync(300)

    def collect_external(self, ask=True):
        """Copy the media that sit outside the project folder into Media."""
        if not self.proj or not self.root:
            return
        plan = library.external_media(self.proj, self.root)
        if not plan:
            self.statusBar().showMessage("所有素材都已經在專案資料夾裡了", 4000)
            return
        if ask and QMessageBox.question(
                self, "整理素材",
                f"有 {len(plan)} 個素材在專案資料夾外面。\n要把它們複製到專案的 Media 資料夾嗎？\n（原檔不會被動到）") != QMessageBox.Yes:
            return
        prog = QProgressDialog("複製素材到專案資料夾…", None, 0, 1000, self)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        root = self.root

        def done(copied):
            prog.close()
            if self.root != root:
                return
            pairs = []
            for src, dst in copied.items():
                library.retarget(self.proj, src, dst)
                pairs.append((src, dst, False))
            self.paths_changed(pairs, "已整理素材")
            if len(copied) < len(plan):
                QMessageBox.warning(self, "部分素材找不到",
                                    f"{len(plan) - len(copied)} 個素材的檔案不存在，沒有複製（片段保留原路徑）。")
            self.dirty = True

        self.run_task(lambda progress: library.collect(plan, progress), done,
                      lambda m: (prog.close(), QMessageBox.critical(self, "複製失敗", m)),
                      lambda p: prog.setValue(int(p * 1000)))

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

    def do_move_rows(self, d_rows):
        """Ctrl+Up / Ctrl+Down: the selected clips one track up (-1) or down (+1) the screen, at
        the same time; nothing moves when a clip would land on another one."""
        if self._typing_widget() is not None:
            return
        ids = [c["id"] for c in self.timeline.selected_clips()]
        if not ids:
            self.statusBar().showMessage("先在時間軸上選取片段", 3000)
            return
        where = "上面" if d_rows < 0 else "下面"

        def move(level):
            try:
                return edit.move_many(level, ids, 0, d_rows)
            except edit.EditError as exc:                # say why in words the user reads
                why = "被其他片段擋住了" if str(exc) == "no room there" else f"{where}沒有同類的軌道"
                raise edit.EditError(why) from exc

        self.apply(f"移到{where}的軌道", move)

    def _typing_widget(self):
        """The text field with the keyboard focus, if any: copy / paste then belong to it."""
        fw = QApplication.focusWidget()
        return fw if isinstance(fw, (QLineEdit, QPlainTextEdit)) else None

    def do_copy(self, cut=False):
        fw = self._typing_widget()
        if fw is not None:
            (fw.cut if cut else fw.copy)()
            return
        ids = [c["id"] for c in self.timeline.selected_clips()]
        if not self.proj or not ids:
            self.statusBar().showMessage("先在時間軸上選取片段", 3000)
            return
        self.clipboard = edit.copy_clips(self.container(), ids)
        self.statusBar().showMessage(f"已{'剪下' if cut else '複製'} {len(ids)} 個片段", 3000)
        if cut:
            self.do_delete()

    def do_paste(self):
        fw = self._typing_widget()
        if fw is not None:
            fw.paste()
            return
        if not self.proj or not self.clipboard:
            self.statusBar().showMessage("沒有複製的片段", 3000)
            return
        self._select_new(self.apply_root("貼上", lambda root: edit.paste_clips(
            root, self.container(root), self.clipboard, self.playhead_us())))

    def do_duplicate(self):
        ids = [c["id"] for c in self.timeline.selected_clips()]
        if not self.proj or not ids:
            self.statusBar().showMessage("先在時間軸上選取片段", 3000)
            return
        self._select_new(self.apply_root("建立副本", lambda root: edit.duplicate_clips(
            root, self.container(root), ids)))

    def _select_new(self, clips):
        if clips:
            self.timeline.set_selection({c["id"] for c in clips}, clips[-1]["id"])

    def delete_compound_item(self, kid):
        """From the compound list: a timeline, or a compound with the clips that show it."""
        if kid.startswith("tl"):
            self.timeline_do("delete", kid)
            return
        n = len(project.compound_uses(self.proj).get(kid, []))
        name = self.proj["compounds"][kid].get("name") or "複合片段"
        msg = f"刪除「{name}」？" + (f"\n時間軸上有 {n} 個片段在使用它，會一起刪除。" if n else "")
        if QMessageBox.question(self, "刪除複合片段", msg) == QMessageBox.Yes:
            self.timeline.selected_id = None
            self.apply_root("刪除複合片段", lambda root: edit.delete_compound(root, kid, force=True))

    def delete_use(self, tl_id, path, cid):
        self.timeline.selected_id = None
        self.apply_root("刪除片段", lambda root: edit.delete_use(root, tl_id, path, cid))

    def do_text(self):
        if self.proj:
            self.apply("新增文字", edit.add_text, self.playhead_us(), select=lambda c: c["id"])

    def apply_each(self, label, fn, ids, *args, merge=None):
        """fn(level, clip id, *args) for every clip of a selection, as one undo step."""
        def each(level):
            for cid in ids:
                fn(level, cid, *args)

        return self.apply(label, each, merge=merge)

    def apply_each_timed(self, label, fn, ids, *args):
        """fn(level, clip id, *args, playhead time in that clip) for every clip of a selection
        (keyframed choices get their keyframe at the playhead)."""
        times = {cid: self.clip_time(cid) for cid in ids}
        return self.apply_each(label, lambda lvl, cid, *a: fn(lvl, cid, *a, times[cid]), ids, *args)

    def on_text_edited(self, ids, fields):
        self.apply_each("修改文字", lambda lvl, cid: edit.set_text(lvl, cid, **fields), ids,
                        merge=("text", tuple(ids), tuple(sorted(fields))))

    def clip_time(self, cid):
        """Playhead time relative to the start of clip cid."""
        return self.playhead_us() - edit.find(self.container(), cid)[1]["start_us"]

    def on_param_edited(self, ids, group, key, value):
        """A value typed in the inspector: set on every selected clip (each at its own
        playhead time, so keyframed ones get or edit the keyframe there)."""
        label = ("調整效果" if group.startswith("fx") else "調整素材" if group == "asset" else
                 "調整" + self.PARAM_LABELS.get((group, key), "遮罩"))
        times = {cid: self.clip_time(cid) for cid in ids}
        self.apply_each(label, lambda lvl, cid: edit.set_param(lvl, cid, group, key, value, times[cid]), ids,
                        merge=("param", tuple(ids), group, key, round(times[ids[0]])))

    def on_key_toggled(self, ids, group, key):
        """◆: when every selected clip has a keyframe here, remove them; else add the missing."""
        times = {cid: self.clip_time(cid) for cid in ids}

        def has(cid):
            c = edit.find(self.container(), cid)[1]
            return edit.key_at(group_holder(c, group).get(key), times[cid]) is not None

        todo = ids if all(has(cid) for cid in ids) else [cid for cid in ids if not has(cid)]
        self.apply_each("關鍵幀", lambda lvl, cid: edit.toggle_key(lvl, cid, group, key, times[cid]), todo)
        self.curves.select_param(group, key)

    def add_key_at_playhead(self, cid, params):
        """The curve editor's "add here": a keyframe holding the current value, for every
        shown parameter that has none at the playhead."""
        t = self.clip_time(cid)
        c = edit.find(self.container(), cid)[1]
        todo = [(g, k) for g, k in params
                if edit.key_at(group_holder(c, g).get(k), t) is None]
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
                        group_holder(c, g, create=True)[k] = {"keys": keys} if keys else keep
        self.player.worker.set_view(view, self.cache_dir())

    def show_selection_props(self):
        clips, t = self.timeline.selected_clips_primary_first(), self.playhead_us()
        self.inspector.show_clips(clips, t, self.fps)
        self.effects.show_clips(clips, t, self.fps)
        self.mask_panel.show_clips(clips, t, self.fps)
        self.beats.show_clips(clips)

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
                    if curves.is_animated(p) and curves.discrete(p["keys"][0][1]):
                        continue                         # choices hold: no curve to shape
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
        self.apply_each_timed("遮罩" if kind else "移除遮罩", edit.set_mask, ids, kind)

    def on_preview_params(self, cid, group, values):
        """A drag of the clip or its mask on the canvas: one edit (keyframed values get or
        edit their keyframe at the playhead)."""
        t = self.clip_time(cid)
        if group == "mask":
            label = "遮罩"
        elif group == "multi":                          # a built-in asset resized: size and place
            label = "調整大小"
        else:
            label = "旋轉" if "rotation" in values else "縮放" if "scale" in values else "移動位置"

        def set_all(level):
            for g, vals in (values.items() if group == "multi" else [(group, values)]):
                for key, v in vals.items():
                    edit.set_param(level, cid, g, key, v, t)

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
        elif action == "clips:track":                   # the track's colour onto all its clips
            self.apply("片段顏色", edit.set_track_clip_colors, tid, t.get("color"))
        elif action == "clips:pick":
            first = next((c.get("color") for c in t["clips"] if c.get("color")), None)
            col = QColorDialog.getColor(QColor(first or t.get("color") or "#888888"), self, "所有片段的顏色")
            if col.isValid():
                self.apply("片段顏色", edit.set_track_clip_colors, tid, col.name())
        elif action == "clips:none":
            self.apply("片段顏色", edit.set_track_clip_colors, tid, None)
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
        if action == "paste":
            self.do_paste()
            return
        if action in ("copy", "cut", "duplicate"):
            {"copy": self.do_copy, "cut": lambda: self.do_copy(cut=True), "duplicate": self.do_duplicate}[action]()
            return
        if action == "new_static":                            # (cid is the track's id here)
            at = self.playhead_us()
            self.apply_root("新增靜態片段", lambda root: edit.new_static(root, self.container(root), at, cid),
                            select=lambda c: c["id"])
            return
        if action in ("make_static", "make_compound"):
            sel = self.timeline.selected_ids
            ids = sorted(sel) if cid in sel else [cid]
            static, at = action == "make_static", self.playhead_us()
            self.apply_root("建立靜態片段" if static else "建立複合片段",
                            lambda root: edit.make_compound(root, self.container(root), ids, at, static),
                            select=lambda c: c["id"])
            return
        _, c = edit.find(self.container(), cid)
        if action == "enter":
            self.enter_compound(cid)
        elif action == "rename":
            name, ok = QInputDialog.getText(self, "片段名稱", "名稱", text=self.timeline.clip_label(c))
            if ok:
                self.apply("重新命名片段", edit.rename_clip, cid, name)
        elif action in ("color", "nocolor"):
            sel = self.timeline.selected_ids                  # a multi-selection is coloured together
            ids = sorted(sel) if cid in sel else [cid]
            if action == "nocolor":
                self.apply_each("片段顏色", edit.set_clip_color, ids, None)
            else:
                col = QColorDialog.getColor(QColor(c.get("color") or "#888888"), self, "片段顏色")
                if col.isValid():
                    self.apply_each("片段顏色", edit.set_clip_color, ids, col.name())
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
        if not self.ensure_project():
            return
        files, _ = QFileDialog.getOpenFileNames(self, "匯入素材", "",
                                                "Media (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.svg *.mp4 *.mov *.mkv "
                                                "*.avi *.webm *.mp3 *.wav *.m4a *.aac *.flac *.ogg);;All files (*)")
        if files:
            self.import_files(files, folder)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            e.acceptProposedAction()
            self.drop_files(paths, self.library.current_folder())

    def drop_files(self, paths, folder, place=None):
        """Files (or folders of them) dragged in: they are copied into the project's Media folder
        (so into the media library), and onto the timeline too when dropped there
        (place = (track id, start us))."""
        files = library.media_files(paths)
        if not files:
            self.statusBar().showMessage("沒有可以匯入的圖片、影片或音訊檔案", 4000)
            return
        mine = [f for f in files if library.in_user_library(f)]      # in the Library: used where they are
        if mine:
            self.ul_use_files(mine, place)
            files = [f for f in files if f not in mine]
            if not files:
                return
            if place is not None:
                place = None                  # (the rest only joins the project's media library)
        self.import_files(files, folder, place)

    def import_files(self, files, folder, place=None):
        """Copy the files into Media (in `folder`), add them to the library and, with place,
        to the timeline."""
        if not self.ensure_project():
            return
        root = self.root
        dest = library.folder_dir(self.proj, root, folder)
        known = library.known_paths(self.proj)
        self.statusBar().showMessage(f"匯入 {len(files)} 個檔案…")

        def work(progress):
            got = library.import_copy(root, files, dest, progress)
            return got, library.scan(root, known)

        def add_and_place(proj, ids):
            if place is None:
                return None
            track_id, start = place
            level = self.container(proj)
            tracks, nxt, clip = {}, {}, None
            for iid in ids:
                it = library.item(proj, iid)
                want = "audio" if it["kind"] == "audio" else "video"
                clip = library.place(level, proj, iid, tracks.get(want, track_id), nxt.get(want, start))
                tracks[want] = edit.find(level, clip["id"])[0]["id"]
                nxt[want] = clip["start_us"] + clip["duration_us"]
            return clip

        def done(result):
            got, res = result
            if self.root != root:
                return
            self.fs_epoch += 1
            library.apply_scan(self.proj, root, res)
            self.library.set_library(library.lib(self.proj))
            self.watch_media()
            by_path = {it["path"]: it for it in library.lib(self.proj)["items"]}
            items = [by_path[p] for p in dict.fromkeys(got.values()) if p in by_path]
            bad = [os.path.basename(p) for p in dict.fromkeys(got.values()) if p not in by_path]
            self.left.setCurrentWidget(self.library)
            if items and place is not None:
                self.apply_root("匯入素材並加入時間軸", add_and_place, [it["id"] for it in items],
                                select=lambda c: c["id"])
            elif items:
                self.statusBar().showMessage(f"已匯入 {len(items)} 個素材到專案資料夾", 4000)
            if bad:
                QMessageBox.warning(self, "部分檔案無法匯入", "讀不到：\n" + "\n".join(bad))

        self.run_task(work, done, lambda m: QMessageBox.critical(self, "匯入失敗", m),
                      lambda p: self.statusBar().showMessage(f"匯入中… {int(p * 100)}%"))

    def library_do(self, label, fn):
        """A file operation on Media: it is done on the disk at once (not part of undo); clips,
        the undo history and the library follow the files."""
        if not self.proj or not self.root:
            return False, None
        try:
            result = fn()
        except (edit.EditError, OSError, shutil.Error) as exc:
            QMessageBox.warning(self, label, str(exc))
            return False, None
        finally:
            self.fs_epoch += 1
            self.library.set_library(library.lib(self.proj))
            self.watch_media()
        return True, result

    def new_folder(self, parent):
        if not self.ensure_project():
            return
        name, ok = QInputDialog.getText(self, "新資料夾", "名稱", text="新資料夾")
        if ok:
            self.library_do("新資料夾", lambda: library.make_folder(self.proj, self.root, name, parent))

    def rename_library(self, ident):
        target = library.folder(self.proj, ident) if ident.startswith("f") else library.item(self.proj, ident)
        name, ok = QInputDialog.getText(self, "重新命名", "名稱（檔案會一起改名）", text=target["name"])
        if ok:
            _ok, pairs = self.library_do("重新命名", lambda: library.rename_on_disk(self.proj, self.root, ident, name))
            if pairs:
                self.paths_changed(pairs, "重新命名素材")

    def move_library(self, ident, to_folder):
        _ok, pairs = self.library_do("移動素材", lambda: library.move_on_disk(self.proj, self.root, ident, to_folder))
        if pairs:
            self.paths_changed(pairs, "移動素材")

    def trash(self, path):
        if QFile.moveToTrash(path):
            return
        if QMessageBox.question(self, "無法移到資源回收筒", f"{os.path.basename(path)}\n要直接永久刪除嗎？") != QMessageBox.Yes:
            raise OSError("已取消")
        shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)

    def delete_library(self, ident):
        if ident.startswith("f"):
            what = "資料夾和裡面所有的檔案"
            gone = {it["path"] for it in library.lib(self.proj)["items"] if it.get("folder") in library.descendants(self.proj, ident)}
        else:
            what = "素材檔案"
            gone = {library.item(self.proj, ident)["path"]}
        used = sum(1 for c in project.all_clips(self.proj) if c.get("media") and c["media"]["path"] in gone)
        note = f"\n\n時間軸上有 {used} 個片段用到，刪除後它們會找不到素材。" if used else ""
        if QMessageBox.question(self, "刪除", f"要刪除這個{what}嗎？它們會被移到資源回收筒。{note}") == QMessageBox.Yes:
            ok, _ = self.library_do("刪除", lambda: library.delete_on_disk(self.proj, self.root, ident, self.trash))
            if ok:
                self.after_edit("刪除素材")
                self.request_sync(300)

    def place_compound(self, kid, track_id, start_us):
        if not self.proj:
            return
        self.apply_root("加入時間線" if kid.startswith("tl") else "加入複合片段",
                        lambda root: edit.place_compound(root, self.container(root), kid, track_id or None, start_us),
                        select=lambda c: c["id"])

    def rename_compound(self, kid):
        if kid.startswith("tl"):                                    # a timeline row
            self.timeline_do("rename", kid)
            return
        comp = self.proj["compounds"][kid]
        name, ok = QInputDialog.getText(self, "複合片段名稱", "名稱", text=comp.get("name") or "")
        if ok:
            self.apply_root("重新命名複合片段", edit.rename_compound, kid, name)

    def place_media(self, item_id, track_id, start_us):
        if not self.proj:
            return
        if item_id.startswith("mu"):                         # an item of the user's Library
            key, it = self.ulib.find(item_id)
            if it is None:
                return
            if key == "filters":
                self.add_filter_clip(it["path"], track_id, start_us)
            elif key == "textstyles":
                self.apply_text_style(it["path"])
            else:
                self.apply_root("加入素材", lambda root: library.place_item(
                    self.container(root), it, track_id or None, start_us), select=lambda c: c["id"])
            return
        self.apply_root("加入素材",
                        lambda root: library.place(self.container(root), root, item_id, track_id or None, start_us),
                        select=lambda c: c["id"])

    def store_asset(self, params):
        """Draw built-in asset parameters (assets.py) into the project's Media/.內建素材;
        the file's path, or None after telling the user why not."""
        try:
            return assets.store(workspace.media_dir(self.root), params)
        except OSError as exc:
            QMessageBox.critical(self, "無法建立素材", str(exc))
            return None

    def new_asset(self, ident):
        """(parameters, file path) of a new clip of the 內建素材 preset ident, sized for the
        open level's canvas; None when there is nothing to make."""
        got = assets.parse(ident)
        if got is None or not self.ensure_project():
            return None
        level = self.container()
        params = assets.make(*got, level.get("width") or self.proj["width"],
                             level.get("height") or self.proj["height"])
        path = self.store_asset(params)
        return (params, path) if path else None

    def place_asset(self, ident, track_id, start_us):
        made = self.new_asset(ident)
        if made is None:
            return
        params, path = made

        def fn(level):
            c = library.place_item(level, assets.item(params, path), track_id or None, start_us)
            c["asset"] = params
            return c
        self.apply("加入內建素材", fn, select=lambda c: c["id"])

    def replace_source(self, ident, cid):
        """Media dropped on a clip with Alt held: the clip shows (or plays) it instead, keeping
        its place, length, look and keyframes."""
        if not self.proj:
            return
        if ident.startswith(assets.PREFIX):
            made = self.new_asset(ident)
            if made is not None:
                params, path = made
                self.apply("替換素材", edit.replace_media, cid, assets.item(params, path), params,
                           select=lambda c: c["id"])
            return
        if ident.startswith("cmp:"):
            self.apply_root("替換素材", lambda root: edit.replace_with_compound(root, self.container(root), cid, ident[4:]),
                            select=lambda c: c["id"])
            return
        if ident.startswith("mu"):                         # an item of the user's Library
            key, it = self.ulib.find(ident)
            if it is None or key not in ("videos", "images", "sounds"):
                self.statusBar().showMessage("替換素材：只能換成圖片、影片或聲音", 4000)
                return
        else:
            try:
                it = library.item(self.proj, ident)
            except edit.EditError:
                return
        self.apply("替換素材", edit.replace_media, cid, dict(it), select=lambda c: c["id"])

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
        """A private copy of the open level for the renderer thread, counted in the editor's
        frames (時間線精度) and played at the project's frame rate."""
        v = json.loads(json.dumps(self.view()))
        v["play_fps"], v["fps"] = self.proj["fps"], self.fps
        return v

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
        parts = list(values.items()) if group == "multi" else [(group, values)]
        for c in project.walk_clips(view["tracks"]):
            if c["id"] == cid:
                for i, (g, vals) in enumerate(parts):
                    holder = group_holder(c, g, create=True)
                    if g == "transform":
                        vals = edit.with_linked_scale(holder, vals, self.playhead_us() - c["start_us"])
                        parts[i] = (g, vals)
                    holder.update(vals)
        self.player.worker.set_view(view, self.cache_dir())
        for panel in (self.inspector, self.mask_panel):         # the numbers follow the drag
            for g, vals in parts:
                panel.show_live(cid, g, vals)

    def on_live_edit(self, ids, group, key, value):
        """A value being typed or scrubbed in the inspector: the preview shows it at once
        (the edit itself follows after a short pause)."""
        if key == "scale_link":
            return                                  # (drawn when the edit is made)
        view = self.snapshot()
        for c in project.walk_clips(view["tracks"]):
            if c["id"] in ids and (group != "asset" or c.get("asset")):
                holder = group_holder(c, group, create=True)
                if group == "transform":
                    holder.update(edit.with_linked_scale(holder, {key: value}, self.playhead_us() - c["start_us"]))
                else:
                    holder[key] = value
        self.player.worker.set_view(view, self.cache_dir())

    @Slot(object, object)
    def _task_call(self, fn, arg):
        fn(arg)

    def run_task(self, fn, done, failed, progress=None):
        th, task = QThread(self), Task(fn)
        task.moveToThread(th)
        th.started.connect(task.run)
        # the results are handled on the UI thread: a plain function connected to a signal would
        # run on the worker thread (and touch widgets from there), so each goes through a
        # signal of the window, which Qt queues across threads
        task.finished.connect(lambda r: self.taskCall.emit(done, r))
        task.failed.connect(lambda m: self.taskCall.emit(failed, m))
        if progress:
            task.progress.connect(lambda v: self.taskCall.emit(progress, v))
        for sig in (task.finished, task.failed):
            sig.connect(th.quit)
        th.finished.connect(lambda: self.taskCall.emit(lambda _: self.tasks.remove((th, task)), None))
        self.tasks.append((th, task))
        th.start()

    # -- playback ---------------------------------------------------------------------------------
    def on_loaded(self, info):
        self.length = info["length"]
        if not self.statusBar().currentMessage():        # (it arrives after every edit: never hide what an edit said)
            fine = f"，時間線每秒 {self.fps:g} 格" if self.fps != self.proj["fps"] else ""
            self.statusBar().showMessage(f"{info['width']}×{info['height']} {self.proj['fps']:g}fps{fine}，"
                                         f"長度 {timecode(self.length / self.fps * US, self.fps)}", 3000)

    def on_frame(self, img, pos):
        self.pos = pos
        self.preview.show_image(img)
        if self.fullscreen:
            self.fullscreen.canvas.show_image(img)
            self.fullscreen.set_position(pos, self.length, self.fps)
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
        """Space: play, or stop - where playback is, or (播放模式 回到開始處) back where it began."""
        if self.proj is None:
            return
        w = self.player.worker
        if not w.playing:                          # (the player's own state: the UI's lags a moment)
            self.play_from = self.pos
            w.set_playing(True)
        elif self.play_mode.currentData() == "return" and getattr(self, "play_from", None) is not None:
            self.seek(self.play_from)
        else:
            w.set_playing(False)

    def set_edit_fps(self, rate):
        """時間線精度: the editor's frames per second (rate None: the project's). The playhead,
        time selection and saved positions are kept where they are in time. Not an edit and
        not part of the export, which uses the project's frame rate."""
        if not self.proj:
            return
        rate = float(rate or self.proj["fps"])
        if abs(rate - self.fps) < 1e-9:
            return
        k = rate / self.fps
        tl = self.timeline
        for v in self.tl_views.values():
            if isinstance(v.get("pos"), (int, float)):
                v["pos"] = round(v["pos"] * k)
        if tl.mark_in is not None:
            tl.mark_in = round(tl.mark_in * k)
        if tl.mark_out is not None:
            tl.mark_out = max(tl.mark_in or 0, round((tl.mark_out + 1) * k) - 1)
        if getattr(self, "play_from", None) is not None:
            self.play_from = round(self.play_from * k)
        pos = round(self.pos * k)
        self.fps = rate
        tl.edit_fps = rate if rate != self.proj["fps"] else None
        tl.fps = rate
        tl.px_per_s = min(tl.px_per_s, tl.max_zoom())
        self.player.worker.set_playing(False)
        self.pending_seek = pos
        self.rebuild()
        self.marks_changed()
        self.seek(pos)
        self.dirty = True
        self._update_title()

    def seek(self, frame, follow=True):
        if self.proj is not None:
            self.follow = follow
            if self.player.worker.playing:
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
        fs.seekRequested.connect(self.seek)
        fs.canvas.renderWidth.connect(lambda w: self.set_render_width("full", w))
        fs.closed.connect(self._fullscreen_closed)
        fs.set_position(self.pos, self.length, self.fps)
        self.fullscreen = fs
        fs.showFullScreen()

    def _fullscreen_closed(self):
        self.fullscreen = None
        self.set_render_width("full", 0)

    def set_render_width(self, who, w):
        """The preview (or the fullscreen one) shows frames w px wide: draw them that size."""
        self.render_w[who] = w
        self.player.worker.set_render_width(max(self.render_w.values()))

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

    def on_beat_edited(self, cid, fields):
        if "on" in fields:
            label = "啟用 BPM 對齊" if fields["on"] else "關閉 BPM 對齊"
        else:
            label = "調整 BPM" if "bpm" in fields else "BPM 細分" if "div" in fields else "調整起頭偏移"
        self.apply(label, lambda level: edit.set_beat(level, cid, **fields), merge=None if "on" in fields else ("beat", cid, tuple(fields)))

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
        default = (os.path.join(workspace.exports_dir(self.root), workspace.project_name(self.path) + ".mp4")
                   if self.root else os.path.join(os.path.expanduser("~"), "Videos", "KiaseCut.mp4"))
        if len(self.proj["timelines"]) > 1:              # one file per timeline
            default = default[:-4] + f" - {project.timeline(self.proj)['name']}.mp4"
        dlg = ExportDialog(self, default, self.fps, total, self.timeline.mark_in, self.timeline.mark_out,
                           self.proj["width"], self.proj["height"], out_fps=self.proj["fps"])
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
            os.makedirs(os.path.dirname(out), exist_ok=True)
            if renderexport.needs_renderer(snapshot):      # filters, blend modes: our own renderer
                return renderexport.export(snapshot, out, (fmt["width"], fmt["height"]), fps, first, last, opts,
                                           progress, cache)
            xml = build.build(snapshot, cache, os.path.join(cache, "export.mlt"),   # originals, no proxies
                              size=(fmt["width"], fmt["height"]), fps=fps)
            enc = gpu.mlt_video_opts(opts, (fmt["width"], fmt["height"]))
            for attempt in ([enc] if enc else []) + [None]:          # NVENC first; x264 if it fails
                eng = EngineClient(16, 16)        # its own process; the preview stays usable
                try:
                    r = eng.export(xml, out, progress, threads=os.cpu_count() or 4,
                                   **{"in": first, "out": last}, **dict(opts, **(attempt or {})))
                except RuntimeError:
                    if attempt is None:
                        raise
                    continue
                finally:
                    eng.close()
                if attempt is None or (os.path.exists(out) and os.path.getsize(out) > 1024):
                    return dict(r, encoder="NVENC (GPU)" if attempt else "x264 (CPU)")

        def done(r):
            prog.close()
            extra = ("\n\n" + "\n".join(r["errors"])) if r.get("errors") else ""
            enc = f"，{r['encoder']}" if r.get("encoder") else ""
            QMessageBox.information(self, "匯出完成", f"{out}\n{fmt['width']}×{fmt['height']}，{fps:g} fps{enc}\n"
                                    f"耗時 {r['elapsed']:.0f} 秒{extra}")

        self.run_task(work, done, lambda m: (prog.close(), QMessageBox.critical(self, "匯出失敗", m)),
                      lambda p: prog.setValue(int(p * 1000)))

    # -- settings ---------------------------------------------------------------------------------
    def documents_dir(self):
        return QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or os.path.expanduser("~")

    def default_library_root(self):
        return userlib.default_root(self.documents_dir())

    def library_root(self):
        s = self.settings().value("library_dir")
        return library.norm(str(s)) if s else self.default_library_root()

    def autosave_min(self):
        try:
            return max(1, int(self.settings().value("autosave_min", 5)))
        except (TypeError, ValueError):
            return 5

    def open_settings(self):
        dlg = SettingsDialog(self, self.ulib.root if self.ulib else self.library_root(), self.default_library_root(),
                             self.default_location(), self.autosave_min(), gpu.enabled)
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values()
        s = self.settings()
        s.setValue("project_dir", v["project_dir"])
        s.setValue("autosave_min", v["autosave_min"])
        s.setValue("gpu", v["gpu"])
        gpu.enabled = v["gpu"]
        self.autosave_timer.setInterval(v["autosave_min"] * 60 * 1000)
        if v["library"] != (self.ulib.root if self.ulib else None):
            self.change_library_root(v["library"], v["copy_library"])

    def change_library_root(self, new, copy):
        old = self.ulib.root if self.ulib else None
        if copy and old and library.within(new, old):
            QMessageBox.warning(self, "Library", "新的位置不能放在目前的 Library 資料夾裡面。")
            return
        prog = None
        if copy and old and os.path.isdir(old):
            prog = QProgressDialog("複製 Library…", None, 0, 0, self)
            prog.setWindowModality(Qt.WindowModal)
            prog.setMinimumDuration(0)

        def work(_progress):
            if prog is not None:
                shutil.copytree(old, new, dirs_exist_ok=True)

        def done(_r):
            if prog is not None:
                prog.close()
            self.settings().setValue("library_dir", new)
            was = self.ulib.root if self.ulib else None
            if not self.apply_library_root(new):
                return
            if was and self.proj:                  # clips that use Library files follow it
                library.retarget(self.proj, was, new, True)
                self.paths_changed([(was, new, True)], "變更 Library 位置")
            self.statusBar().showMessage(f"Library 已改為 {new}", 5000)

        def failed(msg):
            if prog is not None:
                prog.close()
            QMessageBox.critical(self, "無法複製 Library", msg)

        self.run_task(work, done, failed)

    # -- the user's Library -----------------------------------------------------------------------
    def apply_library_root(self, root):
        root = library.norm(root)
        try:
            os.makedirs(root, exist_ok=True)
            userlib.ensure_layout(root)
        except OSError as exc:
            QMessageBox.warning(self, "Library", f"無法使用這個資料夾：\n{root}\n{exc}")
            return False
        project.LIBRARY_ROOT = root
        self.ulib = userlib.UserLibrary(root)
        self.ul_prober = userlib.Prober(root)
        self.ulpanel.set_root(root)
        for key, _ in userlib.CATEGORIES:
            self.ulpanel.panels[key].set_library(self.ulib.lib(key))
        self.refresh_user_filters()
        self.watch_userlib()
        self.request_ul_sync(0)
        return True

    def watch_userlib(self):
        old = self.ul_watcher.directories()
        if old:
            self.ul_watcher.removePaths(old)
        if self.ulib and os.path.isdir(self.ulib.root):
            root = self.ulib.root
            dirs = [d for d, _, _ in os.walk(root) if not any(p.startswith(".") for p in d[len(root):].split(os.sep))]
            self.ul_watcher.addPaths(dirs)

    def request_ul_sync(self, delay=500):
        if self.ulib:
            self.ul_timer.start(delay)

    def sync_userlib(self):
        """Read the Library folder (off the UI thread) and make the panel match it."""
        if not self.ulib:
            return
        if self.ul_busy:
            self.request_ul_sync(300)
            return
        self.ul_busy, ulib, epoch, prober = True, self.ulib, self.ul_epoch, self.ul_prober
        known = {key: library.known_paths(ulib.proj(key)) for key, _ in userlib.CATEGORIES}

        def work(_p):
            return {key: ulib.scan(key, prober, known[key]) for key, _ in userlib.CATEGORIES}

        def done(res):
            self.ul_busy = False
            if self.ulib is not ulib:
                return
            if epoch != self.ul_epoch:                    # one of our own file operations came in between
                self.request_ul_sync(100)
                return
            for key, r in res.items():
                if ulib.apply(key, r):
                    self.ulpanel.panels[key].set_library(ulib.lib(key))
            self.refresh_user_filters()
            self.watch_userlib()

        def failed(msg):
            self.ul_busy = False
            self.statusBar().showMessage(f"整理 Library 失敗：{msg}", 6000)

        self.run_task(work, done, failed)

    def refresh_user_filters(self):
        if not self.ulib:
            return
        mine = []
        for it in sorted(self.ulib.lib("filters")["items"], key=lambda i: i["name"].lower()):
            mine.append((fx.get(it["path"]).name or it["name"], it["path"]))
        self.effects.set_user_filters(mine)
        self.vfx.set_user_filters(mine)

    def ul_item(self, key, ident):
        return next((it for it in self.ulib.lib(key)["items"] if it["id"] == ident), None)

    def ul_do(self, key, fn, label):
        """A file operation in the Library: done on the disk at once (not part of undo)."""
        try:
            result = fn()
        except (edit.EditError, OSError, shutil.Error) as exc:
            QMessageBox.warning(self, label, str(exc))
            return False, None
        finally:
            self.ul_epoch += 1
            self.ulpanel.panels[key].set_library(self.ulib.lib(key))
            self.refresh_user_filters()
            self.watch_userlib()
        return True, result

    def ul_paths_changed(self, pairs, label):
        """Library files were renamed / moved: clips that use them follow."""
        if not pairs:
            return
        if self.proj:
            for old, new, is_dir in pairs:
                library.retarget(self.proj, old, new, is_dir)
            self.paths_changed(pairs, label)
        self.request_ul_sync(300)

    def ul_new_folder(self, key, parent):
        name, ok = QInputDialog.getText(self, "新資料夾", "名稱", text="新資料夾")
        if ok:
            self.ul_do(key, lambda: library.make_folder(self.ulib.proj(key), self.ulib.mirror(key), name, parent), "新資料夾")

    def ul_rename(self, key, ident):
        proj = self.ulib.proj(key)
        target = library.folder(proj, ident) if ident.startswith("f") else library.item(proj, ident)
        name, ok = QInputDialog.getText(self, "重新命名", "名稱（檔案會一起改名）", text=target["name"])
        if ok:
            _ok, pairs = self.ul_do(key, lambda: library.rename_on_disk(proj, self.ulib.mirror(key), ident, name), "重新命名")
            self.ul_paths_changed(pairs, "重新命名 Library 檔案")

    def ul_move(self, key, ident, to_folder):
        proj = self.ulib.proj(key)
        _ok, pairs = self.ul_do(key, lambda: library.move_on_disk(proj, self.ulib.mirror(key), ident, to_folder), "移動")
        self.ul_paths_changed(pairs, "移動 Library 檔案")

    def ul_delete(self, key, ident):
        proj = self.ulib.proj(key)
        if ident.startswith("f"):
            what = "資料夾和裡面所有的檔案"
            gone = {it["path"] for it in library.lib(proj)["items"] if it.get("folder") in library.descendants(proj, ident)}
        else:
            what = "檔案"
            gone = {library.item(proj, ident)["path"]}
        used = 0
        if self.proj:
            for c in project.all_clips(self.proj):
                used += bool(c.get("media") and c["media"]["path"] in gone)
                used += sum(1 for e in c.get("effects") or [] if e["filter"] in gone)
        note = f"\n\n目前的專案有 {used} 個地方用到，刪除後它們會找不到檔案。" if used else ""
        if QMessageBox.question(self, "刪除", f"要刪除這個{what}嗎？它們會被移到資源回收筒。\n"
                                f"（Library 是所有專案共用的）{note}") != QMessageBox.Yes:
            return
        ok, _ = self.ul_do(key, lambda: library.delete_on_disk(proj, self.ulib.mirror(key), ident, self.trash), "刪除")
        if ok:
            if self.proj:
                self.after_edit("刪除 Library 檔案")
            self.request_ul_sync(300)

    def ul_reveal(self, key, ident):
        target = self.ulib.mirror(key)
        select = False
        if ident:
            proj = self.ulib.proj(key)
            if ident.startswith("f"):
                target = library.folder_dir(proj, self.ulib.mirror(key), ident)
            else:
                target, select = library.item(proj, ident)["path"], True
        self.reveal_path(target, select)

    def reveal_path(self, target, select=True):
        """Show a file in the file manager (a folder: open it)."""
        if not os.path.exists(target):
            return
        if os.path.isdir(target):
            QDesktopServices.openUrl(QUrl.fromLocalFile(target))
        elif select and sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", target.replace("/", "\\")])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(target)))

    IMPORT_FILTERS = {
        "videos": "影片 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.flv *.wmv *.ts *.mts)",
        "images": "圖片 (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff *.svg)",
        "sounds": "音效 (*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus *.wma)",
        "filters": "GLSL 濾鏡 (*.glsl)", "textstyles": "文字樣式 (*.json)"}

    def ul_import(self, key, folder):
        files, _ = QFileDialog.getOpenFileNames(self, "加入 Library", "", self.IMPORT_FILTERS[key] + ";;All files (*)")
        if files:
            self.ul_add_files(key, files, folder)

    def ul_drop(self, key, paths, folder):
        self.ul_add_files(key, userlib.expand(paths), folder)

    def ul_add_files(self, key, files, folder):
        """Copy files into the Library (sorted into their own category; into `folder` of the open
        tab's category). Files that are already in the Library stay where they are."""
        todo = {}
        for f in files:
            cat = userlib.category_for(f, prefer=key)
            if cat is not None and not userlib.inside(f, self.ulib.root):
                todo.setdefault(cat, []).append(f)
        if not todo:
            self.statusBar().showMessage("沒有可以加入的檔案（或它們已經在 Library 裡了）", 4000)
            return
        ulib = self.ulib
        dests = {cat: library.folder_dir(ulib.proj(cat), ulib.mirror(cat), folder if cat == key else None)
                 for cat in todo}

        def work(progress):
            n = sum(len(v) for v in todo.values())
            done = 0
            for cat, fs in todo.items():
                library.import_copy(ulib.mirror(cat), fs, dests[cat])
                done += len(fs)
                progress(done / n)
            return True

        def done(_r):
            self.ul_epoch += 1
            self.request_ul_sync(0)
            self.left.setCurrentWidget(self.ulpanel)
            self.ulpanel.show_category(key if key in todo else next(iter(todo)))
            self.statusBar().showMessage(f"已加入 {sum(len(v) for v in todo.values())} 個檔案到 Library", 4000)

        self.run_task(work, done, lambda m: QMessageBox.critical(self, "加入失敗", m),
                      lambda p: self.statusBar().showMessage(f"複製中… {int(p * 100)}%"))

    def ul_use_files(self, files, place):
        """Files that are in the Library are used where they are: onto the timeline when
        dropped there (place = (track id, start us)), else just shown in the Library."""
        items = []
        for f in files:
            it = self.ulib.item_for_path(f)
            if it["kind"] in ("image", "video", "audio"):
                items.append(it)
        if not items:
            return
        self.left.setCurrentWidget(self.ulpanel)
        cat = userlib.category_of(items[0]["path"], self.ulib.root)
        if cat in dict(userlib.CATEGORIES):
            self.ulpanel.show_category(cat)
        if place is None:
            self.statusBar().showMessage(f"{len(items)} 個檔案已經在 Library 裡，不需要複製到專案", 5000)
            return
        track_id, start = place

        def add(root):
            level = self.container(root)
            tracks, nxt, clip = {}, {}, None
            for it in items:
                want = "audio" if it["kind"] == "audio" else "video"
                clip = library.place_item(level, it, tracks.get(want, track_id), nxt.get(want, start))
                tracks[want] = edit.find(level, clip["id"])[0]["id"]
                nxt[want] = clip["start_us"] + clip["duration_us"]
            return clip

        self.apply_root("加入 Library 素材", add, select=lambda c: c["id"])

    def ul_menu(self, key, menu, ident):
        if not ident or ident.startswith("f"):
            return
        it = self.ul_item(key, ident)
        if it is None:
            return
        if key == "filters":
            menu.addAction("放成濾鏡片段（播放頭位置）", lambda: self.add_filter_clip(it["path"]))
            menu.addAction("套用到選取的片段", lambda: self.apply_filter_to_selected(it["path"]))
            menu.addAction("用編輯器開啟（改完存檔就會更新）", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(it["path"])))
        elif key == "textstyles":
            menu.addAction("套用到選取的文字", lambda: self.apply_text_style(it["path"], new_if_none=False))
            menu.addAction("用這個樣式新增文字", lambda: self.apply_text_style(it["path"], force_new=True))

    # -- filters ----------------------------------------------------------------------------------
    def _fill_filter_menu(self, menu, fn):
        menu.clear()
        cats = {}
        for ref in fx.builtin_refs():
            d = fx.get(ref)
            cats.setdefault(d.category or "其他", []).append((d.name, ref))
        for cat, items in cats.items():
            sub = menu.addMenu(cat)
            for name, ref in items:
                sub.addAction(name, lambda _=False, ref=ref: fn(ref))
        menu.addSeparator()
        mine = menu.addMenu("我的濾鏡（Library）")
        n = 0
        for it in sorted(self.ulib.lib("filters")["items"], key=lambda i: i["name"].lower()) if self.ulib else []:
            mine.addAction(fx.get(it["path"]).name, lambda _=False, p=it["path"]: fn(p))
            n += 1
        if not n:
            mine.addAction("（Library 的「濾鏡」頁還沒有檔案）").setEnabled(False)

    def add_filter_clip(self, ref, track_id="", start_us=None):
        """A filter as a clip of its own: it works on everything below it while it lasts."""
        if not self.proj:
            return
        start = self.playhead_us() if start_us is None else start_us
        self.apply("新增濾鏡片段", lambda lvl: edit.add_filter_clip(lvl, ref, start, track_id=track_id or None),
                   select=lambda c: c["id"])

    def on_filter_dropped(self, ref, cid, track_id, start_us):
        """A filter dragged from the VFX tab: onto a clip it joins that clip's effects (all the
        selected ones when it is one of them), elsewhere it becomes a filter clip."""
        if not cid:
            self.add_filter_clip(ref, track_id, start_us)
            return
        sel = self.timeline.selected_ids
        ids = [c["id"] for c in self.timeline.selected_clips_primary_first()
               if c["type"] in edit.VISUAL] if cid in sel else [cid]
        self.apply("新增效果", lambda lvl: [edit.add_effect(lvl, k, ref) for k in ids])
        self.side.setCurrentIndex(1)

    def apply_filter_to_selected(self, ref):
        ids = [c["id"] for c in self.timeline.selected_clips_primary_first() if c["type"] in edit.VISUAL]
        if not ids:
            self.statusBar().showMessage("先在時間軸選一個畫面片段（圖片、影片、文字、複合片段）", 4000)
            return
        self.apply("新增效果", lambda lvl: [edit.add_effect(lvl, cid, ref) for cid in ids])
        self.side.setCurrentIndex(1)

    def browse_effect(self, cid):
        start = self.ulib.mirror("filters") if self.ulib else ""
        path, _ = QFileDialog.getOpenFileName(self, "選擇濾鏡檔案", str(start), "GLSL 濾鏡 (*.glsl)")
        if path:
            self.apply("新增效果", edit.add_effect, cid, library.norm(path))

    def new_filter_file(self, folder):
        """A new filter file made from the template, opened in the user's editor."""
        if not self.ulib:
            return
        name, ok = QInputDialog.getText(self, "新增濾鏡", "名稱", text="我的濾鏡")
        if not ok or not name.strip():
            return
        base = library.folder_dir(self.ulib.proj("filters"), self.ulib.mirror("filters"), folder)
        os.makedirs(base, exist_ok=True)
        dst = os.path.join(base, library.unique_name(base, workspace.safe_name(name, "我的濾鏡") + ".glsl"))
        with open(fx.TEMPLATE_PATH, encoding="utf-8") as fh:
            text = fh.read()
        text = text.replace("// @filter 我的濾鏡", f"// @filter {name.strip()}", 1)
        with open(dst, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        self.ul_epoch += 1
        self.request_ul_sync(0)
        self.left.setCurrentWidget(self.ulpanel)
        self.ulpanel.show_category("filters")
        QDesktopServices.openUrl(QUrl.fromLocalFile(dst))
        self.statusBar().showMessage("已建立濾鏡檔，用編輯器改完存檔，預覽會自動更新（說明：Library > 濾鏡 > 說明）", 8000)

    def show_filter_doc(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("濾鏡寫法說明")
        dlg.resize(760, 640)
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        try:
            with open(fx.DOC_PATH, encoding="utf-8") as fh:
                view.setMarkdown(fh.read())
        except OSError as exc:
            view.setPlainText(f"找不到說明文件：{exc}")
        lay = QVBoxLayout(dlg)
        lay.addWidget(view)
        row = QHBoxLayout()
        if self.ulib:
            open_dir = QPushButton("開啟 Library 的濾鏡資料夾")
            open_dir.clicked.connect(lambda: self.reveal_path(self.ulib.mirror("filters")))
            row.addWidget(open_dir)
        row.addStretch(1)
        close = QPushButton("關閉")
        close.clicked.connect(dlg.accept)
        row.addWidget(close)
        lay.addLayout(row)
        dlg.exec()

    def check_filters(self):
        """Compile the built-in filters and the ones in the Library; list the ones with mistakes."""
        refs = fx.builtin_refs() + [it["path"] for it in self.ulib.lib("filters")["items"]] if self.ulib else []
        bad = []
        for ref in refs:
            err = fx.check(ref)
            if err:
                bad.append(f"{fx.get(ref).name}\n    {err.strip().splitlines()[0] if err.strip() else err}")
        if bad:
            QMessageBox.warning(self, "濾鏡檢查", f"{len(bad)} / {len(refs)} 個濾鏡有問題：\n\n" + "\n\n".join(bad))
        else:
            QMessageBox.information(self, "濾鏡檢查", f"{len(refs)} 個濾鏡都可以使用。")

    # -- text: styles and fonts -------------------------------------------------------------------
    def start_font_scan(self):
        cache = os.path.join(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation) or
                             os.path.expanduser("~"), "fonts.json")
        cached = fonts.load_cache(cache, time.time())
        if cached:
            self.set_fonts(cached)
            return

        def work(_p):
            found = fonts.scan(cancelled=lambda: self.closing)
            if not self.closing:
                fonts.save_cache(cache, found, time.time())
            return found

        self.run_task(work, self.set_fonts, lambda m: self.statusBar().showMessage(f"讀取字體失敗：{m}", 5000))

    def set_fonts(self, found):
        self.fonts = found
        self.inspector.set_fonts(found)
        self.refresh_inspector()
        if self.font_check is not None:             # a project opened before the list was read
            self.check_fonts(self.font_check)

    # 字體對應: a font the project names that this operating system does not have gets a stand-in,
    # kept per system in project["font_map"] (fonts.py)
    def font_map_here(self):
        """This system's part of the project's font map."""
        m = (self.proj or {}).get("font_map") or {}
        return dict(m.get(fonts.os_key()) or {}) if isinstance(m, dict) else {}

    def remembered_fonts(self):
        """Stand-ins chosen on this computer before (any project), offered first."""
        try:
            v = json.loads(str(self.settings().value("font_map_" + fonts.os_key(), "{}")))
        except ValueError:
            v = {}
        return v if isinstance(v, dict) else {}

    def check_fonts(self, auto=True):
        """Open 字體對應: auto (a project was opened) only when fonts are missing here, without
        waiting for an answer; from the menu also with the stand-ins already chosen. Waits for
        the list of installed fonts when it is still being read."""
        self.font_check = None
        if auto and self.font_dlg is not None:         # (one left open for another project)
            self.font_dlg.close()
        if not self.proj:
            return
        if not self.fonts:
            self.font_check = auto
            if not auto:
                self.statusBar().showMessage("還在讀取這台電腦的字體清單，讀完就會打開字體對應", 4000)
            return
        mapping = self.font_map_here()
        gone = fonts.missing(self.proj, mapping)
        known = self.remembered_fonts()
        rows = [(p, fonts.guess(p, self.fonts, known), True) for p in gone]
        if not auto:
            used = fonts.used(self.proj)
            rows += [(p, mapping[p], False) for p in sorted(mapping) if p in used and p not in gone]
            if not rows:
                self.statusBar().showMessage("專案用到的字體這台電腦都有", 4000)
                return
        if not rows:
            return
        if self.font_dlg is not None:
            self.font_dlg.close()
        dlg = FontMapDialog(self, rows, self.fonts)
        dlg.applied.connect(self.apply_font_map)
        dlg.destroyed.connect(lambda *_: setattr(self, "font_dlg", None) if self.font_dlg is dlg else None)
        self.font_dlg = dlg
        dlg.show()

    def apply_font_map(self, choices):
        """字體對應 answered: {font file: stand-in, or None to forget its stand-in} for this
        system; the texts are drawn again with them. Not an edit (undo leaves it alone)."""
        if not self.proj:
            return
        mapping = self.font_map_here()
        for p, repl in choices.items():
            if repl:
                mapping[p] = repl
            else:
                mapping.pop(p, None)
        whole = self.proj.setdefault("font_map", {})
        if mapping:
            whole[fonts.os_key()] = mapping
        else:
            whole.pop(fonts.os_key(), None)
        if not whole:
            self.proj.pop("font_map", None)
        known = self.remembered_fonts()
        known.update({p: r for p, r in choices.items() if r})
        self.settings().setValue("font_map_" + fonts.os_key(), json.dumps(known, ensure_ascii=False))
        fonts.use_map(mapping)
        self.dirty = True
        self._update_title()
        self.rebuild()
        self.refresh_inspector()
        self.timeline.update()
        n = sum(1 for r in choices.values() if r)
        self.statusBar().showMessage(f"已設定 {n} 個字體對應（只用在這個系統）", 4000)

    def apply_text_style(self, path, new_if_none=True, force_new=False):
        try:
            style = userlib.load_style(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "文字樣式", f"讀不到樣式：{exc}")
            return
        ids = [] if force_new else [c["id"] for c in self.timeline.selected_clips_primary_first() if c["type"] == "text"]
        if ids:
            self.apply("套用文字樣式", lambda lvl: [edit.apply_text_style(lvl, cid, style) for cid in ids])
        elif new_if_none or force_new:
            def make(level):
                c = edit.add_text(level, self.playhead_us())
                return edit.apply_text_style(level, c["id"], style)
            self.apply("用樣式新增文字", make, select=lambda c: c["id"])
        else:
            self.statusBar().showMessage("先在時間軸選一個文字片段", 4000)

    def save_text_style(self, folder):
        clips = [c for c in self.timeline.selected_clips_primary_first() if c["type"] == "text"]
        if not clips:
            self.statusBar().showMessage("先在時間軸選一個文字片段，再把它的樣式存進 Library", 5000)
            return
        name, ok = QInputDialog.getText(self, "存成文字樣式", "樣式名稱", text="我的樣式")
        if not ok or not name.strip():
            return
        base = library.folder_dir(self.ulib.proj("textstyles"), self.ulib.mirror("textstyles"), folder)
        userlib.save_style(base, name.strip(), clips[0])
        self.ul_epoch += 1
        self.request_ul_sync(0)
        self.left.setCurrentWidget(self.ulpanel)
        self.ulpanel.show_category("textstyles")
        self.statusBar().showMessage(f"已存到 Library > 文字樣式：{name.strip()}", 4000)

    def closeEvent(self, e):
        if not self.maybe_save():
            e.ignore()
            return
        self.closing = True
        if self.fullscreen:
            self.fullscreen.close()
        self.player.shutdown()
        for th, _task in list(self.tasks):               # background work still running: let it end
            th.quit()
            th.wait(4000)
        super().closeEvent(e)


def run(argv):
    app = QApplication(argv)
    app.setStyleSheet(STYLE)
    win = MainWindow()
    win.show()
    if len(argv) > 1:
        a = argv[1]
        if a.endswith(workspace.EXTS):
            win.open_path(os.path.abspath(a))
        else:
            win.import_draft_file(a)
    return app.exec()
