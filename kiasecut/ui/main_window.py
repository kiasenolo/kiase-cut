"""Main window (Jianying-like): media library, preview, inspector, timeline.

Editing can happen on the main timeline or inside a compound clip (double-click it);
`path_ids` is the chain of compound clips that are open. Its first entry can instead be
"cmp:<compound id>": that compound opened by itself, from the compound list, so one that no
clip shows (a _thumbnail, a mask's) can be edited too. Every edit runs through one undo
history on the whole project, applied to whichever level is open.
"""
import hashlib
import json
import math
import os
import pickle
import shutil
import subprocess
import sys
import threading
import time

from PySide6.QtCore import (QEvent, QFile, QFileSystemWatcher, QMimeData, QObject, QPointF, QRect, QSettings, QSize,
                            QStandardPaths, Qt, QProcess,
                            QThread, QTimer, QUrl, Signal, Slot)
from PySide6.QtGui import QAction, QColor, QCursor, QDesktopServices, QDrag, QIcon, QImage, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QAbstractSlider, QAbstractSpinBox, QApplication, QComboBox, QDialog, QFileDialog, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMainWindow, QMenuBar, QPlainTextEdit, QMessageBox, QProgressDialog, QSpinBox, QTextBrowser,
                               QPushButton, QScrollArea, QSizePolicy, QSlider, QSplitter, QStackedWidget, QTabBar, QToolBar,
                               QVBoxLayout,
                               QWidget)

from .. import (androidfs, assets, build, components, curves, edit, fonts, fx, gpu, keybatch, layouts, library, project, recovery,
               mapping, nodegraph, rack, render, renderexport, sysmem, textpresets, thumbnail, toolsdata, userlib, viz, waveform, workspace)
from ..client import EngineClient
from ..importers import jianying
from .assets_panel import AssetsPanel
from . import colorpick
from .colorpick import pick_color, qcolor, rgba
from .font_dialog import FontMapDialog
from . import ask as questions
from .compounds import PREFIX as COMPOUND_PREFIX, CompoundPanel
from .docks import Panels
from .curve_editor import CurveEditor, param_rows as curve_param_rows
from .beat_panel import BeatPanel
from .effects_panel import EffectsPanel
from .node_editor import NodeEditor
from .export_dialog import QUALITY, ExportDialog, ExportProgress
from .inspector import Inspector
from .library import LibraryPanel, dropped_paths
from .layers import LayerPanel
from .params import ParamList, clip_name
from .player import RATES, Player
from .project_dialogs import CompoundSizeDialog, NewProjectDialog, ProjectInfoDialog
from .project_manager import ProjectManager
from .settings_dialog import SettingsDialog
from .still_dialog import StillDialog
from .subtitle_panel import SubtitlePanel
from .userlib_panel import UserLibraryPanel
from .vfx_panel import VfxPanel, dropped_fx
from .vfxnodes import VfxNodePanel
from . import androidfiles, appevents, dialogframe, exprdialog, escapekey, icons, inertia, inplace, look, mapdialog, menuanim, menubartap, menudebug, middledrag, sashtouch, softdrag, touch, wheel
from .rack_panel import RackPanel
from .meter import MeterPanel
from .preview import FullscreenPreview, Preview
from .preview import base_size as preview_base_size
from .timebase import button_text, edit_timebase
from .timeline import MEDIA_MIME, US, Timeline, time_text, timebase_of, timecode
from .menukeys import Menu, keyed


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


OVERFLOW = 0.5                 # 顯示畫布外: how much round the canvas is drawn too, as a fraction of the canvas on each side
PLAYING_PROPS_MS = 100         # while playing, the selection's panels show its values this often
OPEN_PREFIX = "cmp:"            # path_ids[0] = OPEN_PREFIX + compound id: that compound opened by itself


def walk_path(root, path):
    """[(compound clip or None, the content it shows, that content's id)] along a path of open
    levels (see the module notes); raises EditError / KeyError when a step is gone."""
    out, node = [], root
    for i, cid in enumerate(path):
        if cid.startswith(OPEN_PREFIX):
            if i:
                raise edit.EditError("a compound opened by itself comes first")
            kid = cid[len(OPEN_PREFIX):]
            node = root["compounds"][kid]
            out.append((None, node, kid))
        else:
            c = edit.find(node, cid)[1]
            node = c["compound"]
            out.append((c, node, project.ref_of(c)))
    return out


class TimelineTabs(QTabBar):
    """Timeline tabs; dragging a tab onto the timeline nests that timeline (as in Resolve).
    A tab opens when the button is let go over it, not when it is pressed, so a tab can be
    dragged down without the timeline below changing first. A compound (or timeline) dragged
    from the compound list onto the tabs opens in a tab of its own (tabRequested)."""
    tabRequested = Signal(str)                     # compound or timeline id dropped on the tabs

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

    def _dropped_id(self, e):
        md = e.mimeData()
        if not md.hasFormat(MEDIA_MIME):
            return None
        first = bytes(md.data(MEDIA_MIME)).decode("utf-8", "replace").split(",")[0]
        return first[len("cmp:"):] if first.startswith("cmp:") else None

    def dragEnterEvent(self, e):
        if self._dropped_id(e) and e.source() is not self:
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        self.dragEnterEvent(e)

    def dropEvent(self, e):
        kid = self._dropped_id(e)
        if kid:
            e.acceptProposedAction()
            self.tabRequested.emit(kid)

    def mousePressEvent(self, e):
        self._press = (e.position(), self.tabAt(e.position().toPoint())) if e.button() == Qt.LeftButton else None
        if self._press and self._press[1] >= 0:
            e.accept()                                     # (QTabBar would switch right away)
            return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        press = getattr(self, "_press", None)
        self._press = None
        if press and press[1] >= 0 and e.button() == Qt.LeftButton:
            if self.tabAt(e.position().toPoint()) == press[1]:
                self.setCurrentIndex(press[1])
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def mouseMoveEvent(self, e):
        press = getattr(self, "_press", None)
        if press and press[1] >= 0 and (e.buttons() & Qt.LeftButton) and                 (e.position() - press[0]).manhattanLength() > QApplication.startDragDistance() * 2:
            self._press = None
            md = QMimeData()
            md.setData(MEDIA_MIME, f"cmp:{self.tabData(press[1])}".encode())
            drag = QDrag(self)
            drag.setMimeData(md)
            softdrag.exec_drag(drag, Qt.CopyAction)
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


def same_group(c, other, group):
    """The group of clip other that matches group of clip c: itself, or for a filter's
    parameters (fx:<effect id>, fxmask:, fxmix:) the same filter at the same place among other's
    filters of that kind; None when other has none."""
    if not group.startswith(("fx:", "fxmask:", "fxmix:", "fxsrc:")):
        return group
    kind, eid = group.split(":", 1)
    eid, colon, name = eid.partition(":")                 # (fxsrc:<effect id>:<colour param>)
    mine = c.get("effects") or []
    e = next((e for e in mine if e["id"] == eid), None)
    if e is None:
        return None
    n = [x["id"] for x in mine if x["filter"] == e["filter"]].index(eid)
    theirs = [x for x in other.get("effects") or [] if x["filter"] == e["filter"]]
    return f"{kind}:{theirs[n]['id']}{colon}{name}" if n < len(theirs) else None


def many(clips):
    """"（N 個片段）" for an undo label of an edit of several clips."""
    return f"（{len(clips)} 個片段）" if len(clips) > 1 else ""


def group_holder(c, group, create=False):
    """The dict of clip c that holds the parameters of `group` ("transform", "mask", "clip", ...,
    or "fx:<effect id>" / "fxmask:<effect id>" / "fxmix:<effect id>" for a filter's own,
    "place:<param id>" for where a component's picture sits)."""
    if group.startswith("place:") and not create:
        return (c.get("places") or {}).get(group[6:]) or {}
    if group.startswith(("fx:", "fxmask:", "fxmix:", "fxsrc:", "place:", "tvar:")):
        try:
            return edit.holder(c, group)
        except edit.EditError:
            return {}
    if group == "clip":
        return c
    return c.setdefault(group, {}) if create else (c.get(group) or {})


def static_label(comp):
    """轉為靜態複合片段, or 轉為靜態元件 for a component."""
    return "轉為靜態元件" if components.is_component(comp) else "轉為靜態複合片段"


class MainWindow(QMainWindow):
    taskCall = Signal(object, object)          # (function, argument): run on the UI thread
    PARAM_LABELS = {("transform", "x"): "位置", ("transform", "y"): "位置", ("transform", "scale"): "縮放",
                    ("transform", "scale_y"): "縮放", ("transform", "scale_link"): "縮放連動",
                    ("transform", "rotation"): "旋轉", ("transform", "opacity"): "不透明度",
                    ("transform", "pivot_x"): "中心點", ("transform", "pivot_y"): "中心點",
                    ("transform", "anchor_x"): "錨點", ("transform", "anchor_y"): "錨點",
                    ("clip", "volume"): "音量", ("text", "size"): "字號", ("text", "color"): "文字顏色",
                    ("text", "fill"): "文字填充", ("text", "stroke_on"): "文字外框",
                    ("text", "stroke_color"): "外框顏色", ("text", "stroke"): "外框粗細",
                    ("text", "stroke_align"): "外框位置",
                    ("text", "letter_spacing"): "字距", ("text", "line_spacing"): "行距",
                    ("text", "italic_deg"): "斜體", ("text", "font_path"): "字體", ("text", "align"): "對齊", ("text", "valign"): "垂直對齊",
                    ("text", "box_mode"): "文字框", ("text", "box_w"): "文字框", ("text", "box_h"): "文字框", ("clip", "blend"): "混合模式",
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
        self.centre_drop = None         # media dropped on the picture of a timeline: (clips before, (x, y), when)
        self.layer_drop_at = None       # media dropped on the layer list: (layers above, layers before, when, where, group)
        self.group_drop_at = None       # media dropped on a group's lane: (group, its track, start, clips before, when)
        self.autosave_dir = None        # recovery: the autosave folder once this program's session began
        self._autosaved = None          # the project as last autosaved (not written again unchanged)
        self.sync_busy = False
        self.sync_retries = 0
        self._last_tick = time.monotonic()
        self.path_ids = []              # open compound clips, outermost first
        self.tl_views = {}              # playhead / scroll / zoom of each timeline while another is open
        self.level_zoom = {}            # (tab, compound path) -> time scroll / zoom as that level was left
        self._level_key = None          # the level the timeline shows now
        self.clipboard = None           # clips copied with 複製 / 剪下 (edit.copy_clips)
        self.open_tls = None            # timelines with a tab (None: all, until the first tab update)
        self.xml = None                 # truthy once the preview has a project
        self.length = 0
        self.fps = 60.0
        self.pos = 0
        self.playing = False
        self.matte_group = "mask"       # what 編輯區域 on the timeline sets: the mask's t_off, or "fxsrc:..."
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
        lb.collectRequested.connect(lambda: self.collect_external(ask=False))

        self.vfxnodes = VfxNodePanel()
        self.vfxnodes.applyRequested.connect(self.apply_vfx_to_selected)
        self.vfxnodes.selectRequested.connect(self.select_vfx_use)
        self.vfxnodes.renameRequested.connect(self.rename_vfx)
        self.vfxnodes.copyRequested.connect(lambda vid: self.apply_root("複製 VFX Node", edit.duplicate_vfx_node, vid))
        self.vfxnodes.deleteRequested.connect(self.delete_vfx)
        self.vfxnodes.libraryRequested.connect(self.save_vfx_to_library)
        self.vfxnodes.importRequested.connect(self.import_vfx_from_library)
        self.compounds = CompoundPanel()
        self.compounds.showRequested.connect(self.show_compound)
        self.compounds.openRequested.connect(self.open_compound_path)
        self.compounds.renameRequested.connect(self.rename_compound)
        self.compounds.timelineRequested.connect(self.switch_timeline)
        self.compounds.deleteRequested.connect(self.delete_compound_item)
        self.compounds.useDeleteRequested.connect(self.delete_use)
        self.compounds.createRequested.connect(self.create_from_panel)
        self.compounds.componentRequested.connect(self.component_kind)
        self.compounds.staticRequested.connect(self.compound_to_static)
        self.compounds.entryRequested.connect(self.open_compound_entry)
        self.compounds.tabRequested.connect(self.open_in_tab)
        self.compounds.libraryRequested.connect(self.save_compound_to_library)
        self.compounds.cloneRequested.connect(self.clone_compound_item)
        self.compounds.thumbnailRequested.connect(lambda _kid: self.apply_thumbnail_compound())
        self.ulpanel = UserLibraryPanel()
        self.ulpanel.settingsRequested.connect(self.open_settings)
        self.ulpanel.newFilterRequested.connect(self.new_filter_file)
        self.ulpanel.saveStyleRequested.connect(self.save_text_style)
        self.ulpanel.saveCompoundRequested.connect(self.save_selected_compound)
        self.ulpanel.savePresetRequested.connect(self.save_effect_preset)
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

        self.preview = Preview()
        self.preview.clipPicked.connect(lambda c: self.timeline.select(c))
        self.preview.groupPicked.connect(self.pick_in_group)
        self.preview.paramsCommitted.connect(self.on_preview_params)
        self.preview.paramsLive.connect(self.live_params)
        self.preview.selectionPicked.connect(lambda ids, primary: self.timeline.set_selection(ids, primary))
        self.preview.movesCommitted.connect(self.on_preview_moves)
        self.preview.movesLive.connect(self.live_moves)
        self.preview.dupLive.connect(self.live_dup)
        self.preview.grabCancelled.connect(lambda: (self.rebuild(), self.refresh_inspector()))
        self.preview.dupCommitted.connect(self.on_preview_dup)
        self.preview.textEdited.connect(lambda cid, words: self.on_text_edited([cid], {"content": words}))
        self.preview.sourceTextEdited.connect(lambda cid, eid, nid, words: self.fx_each(
            "文字", [cid], eid, lambda lvl, c, e: edit.set_effect_text(lvl, c, e, nid, words)))
        self.render_w = {"main": 0, "full": 0}       # width each view shows frames at; the player draws the largest
        self.preview.renderWidth.connect(lambda w: self.set_render_width("main", w))
        self.preview.mediaDropped.connect(self.preview_drop)
        self.preview.replaceDropped.connect(self.replace_source)

        self.inspector = Inspector()
        ins = self.inspector
        ins.pivot_units = self.pivot_units
        ins.textEdited.connect(self.on_text_edited)
        ins.paramEdited.connect(self.on_param_edited)
        ins.picture_of = self.dropped_picture
        ins.component_of = self.open_component
        ins.paramBindRequested.connect(self.layer_param_bind)
        ins.paramUnbindRequested.connect(self.unbind_params)
        ins.exprRequested.connect(self.ask_prop_expr)
        ins.menu_extender = self.number_menu
        ins.vizEdited.connect(lambda ids, fields: self.apply_each("Audio Visualizer", lambda lvl, cid: edit.set_viz(lvl, cid, **fields), ids))
        ins.exprChosen.connect(lambda ids, prop, text: self.apply_each("綁定全局參數", edit.set_prop_expr, ids, prop, text))
        ins.rack_names = lambda: [p["name"] for p in rack.params(self.proj)] if self.proj else []
        ins.exprCleared.connect(lambda ids, prop: self.apply_each("清除表達式", edit.set_prop_expr, ids, prop, ""))
        ins.keyToggled.connect(self.on_key_toggled)
        ins.easingChosen.connect(self.on_easing)
        ins.paramReset.connect(lambda ids, pids: self.apply_each(
            "重設元件參數", lambda lvl, cid: edit.reset_params(lvl, cid, pids), ids))
        self.mask_panel = Inspector(part="mask")
        mp = self.mask_panel
        mp.paramEdited.connect(self.on_param_edited)
        mp.menu_extender = self.number_menu
        mp.component_of = self.open_component
        mp.paramBindRequested.connect(self.layer_param_bind)
        mp.picture_of = self.dropped_picture
        mp.keyToggled.connect(self.on_key_toggled)
        mp.easingChosen.connect(self.on_easing)
        mp.maskKindChosen.connect(self.on_mask_kind)
        mp.maskInvertChosen.connect(lambda ids, on: self.apply_each_timed("反轉遮罩", edit.set_mask_invert, ids, on))
        mp.maskEnabledChosen.connect(
            lambda ids, on: self.apply_each("啟用遮罩" if on else "停用遮罩", edit.set_mask_enabled, ids, on))
        mp.maskCompoundChosen.connect(lambda ids, kid: self.apply_each(
            "遮罩複合片段", lambda lvl, cid: edit.set_mask_compound(lvl, cid, kid, self.proj["compounds"].get(kid)), ids))
        mp.maskMatteChosen.connect(lambda ids, matte: self.apply_each(
            "遮罩類型", lambda lvl, cid: edit.set_mask_compound(lvl, cid, matte=matte), ids))
        mp.mattePreviewChosen.connect(lambda _on: self._matte_preview_changed(force=True))
        mp.maskImageChosen.connect(self.on_mask_image)
        mp.maskVideoChosen.connect(self.on_mask_video)
        mp.maskTrackChosen.connect(lambda ids, tid: self.apply_each(
            "遮罩軌道", lambda lvl, cid: edit.set_mask_track(lvl, cid, tid, self.level_size()), ids))
        mp.matteRegionChosen.connect(lambda _on: self._update_matte_region())
        mp.keyJump.connect(self.jump_key)
        mask_scroll = QScrollArea()
        mask_scroll.setWidget(mp)
        mask_scroll.setWidgetResizable(True)
        ins.keyJump.connect(self.jump_key)
        ins.liveEdited.connect(self.on_live_edit)
        ins.liveCancelled.connect(self.rebuild)
        ins.speedChosen.connect(lambda ids, v: self.apply_each("速度", edit.set_speed, ids, v))
        ins.lengthChosen.connect(lambda ids, us: self.apply_each("目標長度", edit.set_duration_by_speed, ids, us))
        ins.speedCurveChosen.connect(lambda ids, pts: self.apply_each(
            "取消曲線變速" if pts is False else "曲線變速", edit.set_speed_curve, ids, pts))
        ins.textVarAction.connect(self.on_text_var)
        ins.keepPitchChosen.connect(lambda ids, on: self.apply_each("保持音高" if on else "取消保持音高",
                                                                    edit.set_keep_pitch, ids, on))
        ins.freezeChosen.connect(self.on_freeze)
        ins.normalizeChosen.connect(lambda ids, db: self.apply_each("標準化" if db is not None else "取消標準化",
                                                                    edit.set_normalize, ids, db))
        ins.audioStreamChosen.connect(lambda ids, n: self.apply_each("音軌", edit.set_audio_stream, ids, n))
        ins.groupMatteChosen.connect(lambda ids, fields: self.apply_each(
            "群組遮罩", lambda lvl, cid: edit.set_group_matte(lvl, cid, **fields), ids))
        ins.groupAnchorChosen.connect(lambda ids, on: self.apply_each(
            "中心點跟隨最下層物件", lambda lvl, cid: edit.set_group_anchor(lvl, cid, on), ids))
        ins.throughChosen.connect(lambda ids, on: self.apply_each(
            "效果穿透", lambda lvl, cid: edit.set_fx_through(lvl, cid, on), ids))
        ins.alignRequested.connect(lambda how: self.align_or_space("對齊", self.preview.align_moves(how)))
        ins.spacingRequested.connect(lambda gap: self.align_or_space("間距", self.preview.space_moves(gap)))
        mp.liveEdited.connect(self.on_live_edit)
        scroll = QScrollArea()
        scroll.setWidget(self.inspector)
        scroll.setWidgetResizable(True)
        self.curves = CurveEditor()
        cv = self.curves
        cv.saved_curves = lambda: toolsdata.load_curves(self.app_root())      # (工具 > cubic-bezier 編輯器)
        mapdialog.saved_curves = cv.saved_curves                              # (the 映射 window offers them too)
        mapdialog.save_curve = lambda name, value: toolsdata.save_curves(
            self.app_root(), toolsdata.load_curves(self.app_root()) + [{"name": name, "value": value}])
        colorpick.cards = lambda: toolsdata.load_cards(self.app_root())       # (工具 > 調色盤)
        cv.keysChanged.connect(self.on_curve_keys)
        cv.seekRequested.connect(self.seek_clip_time)
        cv.addAtPlayhead.connect(self.add_key_at_playhead)
        cv.keyJump.connect(self.jump_key)
        self.effects = EffectsPanel()
        ef = self.effects
        self.nodes = NodeEditor()                       # 節點 (nodegraph.py)
        nd = self.nodes
        nd.addRequested.connect(self.on_node_add)
        nd.removeRequested.connect(self.on_node_remove)
        nd.connectRequested.connect(self.on_node_connect)
        nd.exposeRequested.connect(self.on_node_expose)
        nd.itemRequested.connect(self.on_node_item)
        nd.removeExposedRequested.connect(self.on_node_remove_exposed)
        nd.exposedEdited.connect(self.on_node_exposed_edited)
        nd.exposedMoved.connect(self.on_node_exposed_moved)
        nd.disconnectManyRequested.connect(self.on_node_cut)
        nd.insertRequested.connect(self.on_node_insert)
        nd.addLinkedRequested.connect(self.on_node_add_linked)
        nd.addFeedingRequested.connect(self.on_node_add_feeding)
        nd.duplicateRequested.connect(self.on_node_duplicate)
        nd.rerouteRequested.connect(self.on_node_reroute)
        nd.mediaDropped.connect(self.on_node_media)
        nd.frameEdited.connect(self.on_node_frame)
        nd.widthEdited.connect(self.on_node_width)
        nd.linesEdited.connect(self.on_node_lines)
        nd.pasteRequested.connect(self.on_node_paste)
        nd.viewerRequested.connect(self.on_node_viewer)
        nd.groupRequested.connect(self.on_node_group)
        nd.ungroupRequested.connect(self.on_node_ungroup)
        nd.groupRenamed.connect(self.on_node_group_renamed)
        nd.groupPortRequested.connect(self.on_node_group_port)
        nd.groupUnplugRequested.connect(self.on_node_group_unplug)
        nd.thumbsToggled.connect(lambda _on: self.proj is not None and self.rebuild())
        nd.dissolveRequested.connect(self.on_node_dissolve)
        nd.disconnectRequested.connect(self.on_node_disconnect)
        nd.moveRequested.connect(self.on_node_move)
        nd.muteRequested.connect(self.on_node_mute)
        nd.nodeSelected.connect(self.on_node_selected)
        nd.saveRequested.connect(self.save_node_preset)
        nd.paramEdited.connect(lambda eid, key, v: self.node_clip() and self.on_fx_param_edited([self.node_clip()], "fx:" + eid, key, v))
        nd.paramLive.connect(lambda eid, group, key, v: self.node_clip() and self.on_fx_live_edit([self.node_clip()], group, key, v))
        nd.placeEdited.connect(lambda eid, nid, key, v: self.node_clip() and self.on_fx_param_edited(
            [self.node_clip()], f"fxsrc:{eid}:{nid}", key, v))
        nd.mediaChosen.connect(lambda eid, nid, value: self.node_clip() and self.on_fx_source_media([self.node_clip()], eid, nid, value))
        nd.shapeEdited.connect(lambda eid, nid, shape, col: self.node_clip() and self.fx_each(
            "形狀", [self.node_clip()], eid, lambda lvl, cid, e: edit.set_effect_shape(lvl, cid, e, nid, shape, col)))
        nd.textEdited.connect(lambda eid, nid, content, font: self.node_clip() and self.fx_each(
            "文字", [self.node_clip()], eid, lambda lvl, cid, e: edit.set_effect_text(lvl, cid, e, nid, content, font)))
        nd.stringEdited.connect(lambda eid, nid, value: self.node_clip() and self.fx_each(
            "字串", [self.node_clip()], eid, lambda lvl, cid, e: edit.set_graph_string(lvl, cid, e, nid, value)))
        nd.fontEdited.connect(lambda eid, nid, path: self.node_clip() and self.fx_each(
            "字體", [self.node_clip()], eid, lambda lvl, cid, e: edit.set_graph_font(lvl, cid, e, nid, path)))
        ef.nodesRequested.connect(self.open_node_editor)
        ef.addRequested.connect(lambda ids, ref: self.add_effects_to(ids, [ref]))
        ef.vfxRequested.connect(self.add_vfx_to)
        nd.unshareRequested.connect(lambda eid: self.node_clip() and self.apply(
            "取消共用", lambda lvl: edit.unshare_vfx(lvl, self.node_clip(), eid)))
        ef.browseRequested.connect(self.browse_effect)
        ef.removeRequested.connect(lambda ids, eid: self.fx_each(
            "移除效果", ids, eid, lambda lvl, cid, e: edit.remove_effect(lvl, cid, e, drop_empty=self.editing_static())))
        ef.enabledChosen.connect(lambda ids, eid, on: self.fx_each(
            "啟用效果" if on else "停用效果", ids, eid, lambda lvl, cid, e: edit.set_effect_enabled(lvl, cid, e, on)))
        ef.moveRequested.connect(lambda ids, eid, d: self.fx_each(
            "調整效果順序", ids, eid, lambda lvl, cid, e: edit.move_effect(lvl, cid, e, d)))
        ef.effectDropped.connect(self.effect_dropped)
        ef.effectsDropped.connect(self.effects_dropped)
        ef.effectSwapped.connect(self.effect_swapped)
        ef.maskKindChosen.connect(lambda ids, eid, kind: self.fx_each(
            "效果範圍" if kind else "移除效果範圍", ids, eid,
            lambda lvl, cid, e: edit.set_effect_mask(lvl, cid, e, kind, self.clip_time(cid))))
        ef.maskInvertChosen.connect(lambda ids, eid, on: self.fx_each(
            "反轉效果範圍", ids, eid, lambda lvl, cid, e: edit.set_effect_mask_invert(lvl, cid, e, on, self.clip_time(cid))))
        ef.sourceKindChosen.connect(lambda ids, eid, name, kind: self.fx_each(
            "效果來源" if kind else "移除效果來源", ids, eid,
            lambda lvl, cid, e: edit.set_effect_source(lvl, cid, e, name, kind)))
        ef.sourceMediaChosen.connect(self.on_fx_source_media)
        ef.shapeChosen.connect(lambda ids, eid, nid, shape, col: self.fx_each(
            "形狀", ids, eid, lambda lvl, cid, e: edit.set_effect_shape(lvl, cid, e, nid, shape, col)))
        ef.sourceRegionChanged.connect(self._update_matte_region)
        ef.paramEdited.connect(self.on_fx_param_edited)
        ef.menu_extender = self.number_menu
        ef.keyToggled.connect(self.on_key_toggled)
        ef.liveEdited.connect(self.on_fx_live_edit)
        ef.liveCancelled.connect(self.rebuild)
        ef.backdropChosen.connect(self.on_backdrop_chosen)
        ef.docRequested.connect(self.show_filter_doc)
        ef.revealFilter.connect(self.reveal_path)
        fx_scroll = QScrollArea()
        fx_scroll.setWidget(ef)
        fx_scroll.setWidgetResizable(True)
        fx_dock = QWidget()                             # 新增效果 stays put above the effects as they scroll
        fl = QVBoxLayout(fx_dock)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)
        fl.addWidget(ef.header)
        fl.addWidget(fx_scroll, 1)
        self.beats = BeatPanel()
        self.beats.beatEdited.connect(self.on_beat_edited)
        self.beats.resetRequested.connect(lambda cid: self.apply("重置 BPM 對齊", edit.clear_beat, cid))
        beat_scroll = QScrollArea()
        beat_scroll.setWidget(self.beats)
        beat_scroll.setWidgetResizable(True)
        self.subtitles = SubtitlePanel()
        self.subtitles.textsEdited.connect(lambda contents: self.apply("批量修改文字", edit.set_texts, contents))

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
        full_btn = tool("fullscreen", "全螢幕（F）", self.toggle_fullscreen)
        self.guides_btn = tool("guides", "顯示 / 隱藏預覽上的外框和控制點（只看畫面）", self.toggle_guides, True)
        self.guides_btn.setChecked(str(self.settings().value("show_guides", "true")).lower() not in ("false", "0"))
        self.preview.set_show_guides(self.guides_btn.isChecked())
        self.overflow_btn = tool("outside", "顯示 / 隱藏畫布外的畫面（開：超出畫布的內容也畫出來，畫布外的部分壓暗；只影響預覽，不影響匯出）",
                                 self.toggle_overflow, True)
        self.overflow_btn.setChecked(str(self.settings().value("show_outside", "false")).lower() in ("true", "1"))
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
        self.transport = []                             # (hidden while a static compound, one picture, is open)
        for name, tip, fn in (("start", "到開頭（Home）", lambda: self.seek(0)),
                              ("prev", "上一幀（←）", lambda: self.step(-1))):
            self.transport.append(tool(name, tip, fn))
        self.transport.append(self.play_btn)
        for name, tip, fn in (("next", "下一幀（→）", lambda: self.step(1)),
                              ("end", "到結尾（End）", lambda: self.seek(self.length - 1))):
            self.transport.append(tool(name, tip, fn))
        for b in self.transport:
            bar.addWidget(b)
        bar.addStretch()
        self.rate_box = QComboBox()                     # 播放速度
        for r in RATES:
            self.rate_box.addItem(f"{r:g}×", r)
        self.rate_box.setToolTip("播放速度：預覽播放得比原本慢或快（音高：旁邊的「保持音高」）。\n"
                                 "只影響預覽，不影響匯出。")
        self.rate_box.setFocusPolicy(Qt.NoFocus)        # (空白鍵 stays play / pause)
        try:
            rate = float(self.settings().value("play_rate", 1.0))
        except (TypeError, ValueError):
            rate = 1.0
        self.rate_box.setCurrentIndex(max(0, self.rate_box.findData(rate if rate in RATES else 1.0)))
        self.rate_box.currentIndexChanged.connect(lambda _i: self.set_play_rate(self.rate_box.currentData()))
        bar.addWidget(self.rate_box)
        self.pitch_btn = QPushButton("保持音高")
        self.pitch_btn.setCheckable(True)
        self.pitch_btn.setFocusPolicy(Qt.NoFocus)
        self.pitch_btn.setToolTip("不是 1× 時，聲音保持原本的音高（開）\n或音高跟著速度變，像錄音帶（關）")
        self.pitch_btn.setChecked(str(self.settings().value("keep_pitch", "true")).lower() not in ("false", "0"))
        self.pitch_btn.toggled.connect(self.set_keep_pitch)
        bar.addWidget(self.pitch_btn)
        self.transport += [self.rate_box, self.pitch_btn]
        bar.addWidget(self.guides_btn)
        bar.addWidget(self.overflow_btn)
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


        # timeline with its toolbar and the compound breadcrumb
        self.timeline = Timeline()
        tl = self.timeline
        tl.seekRequested.connect(lambda f: self.seek(f, follow=False))     # the user is looking there
        tl.clipSelected.connect(lambda c: self.refresh_inspector())
        tl.moveRequested.connect(lambda cid, start, tid: self.apply("移動", edit.move, cid, start, tid))
        tl.trimRequested.connect(
            lambda cid, e, t: self.apply("裁切", edit.trim_start if e == "start" else edit.trim_end, cid, t))
        tl.groupMoveRequested.connect(lambda ids, dt, dr: self.apply("移動", edit.move_many, ids, dt, dr))
        tl.matteOffsetLive.connect(lambda cid, off: self.on_live_edit([cid], self.matte_group, "t_off", off))
        tl.matteOffsetEdited.connect(self.on_matte_offset)
        tl.dupMoveRequested.connect(lambda ids, dt, dr: self._select_new(self.apply_root(
            "複製並移動", lambda root: edit.duplicate_moved(root, self.container(root), ids, dt, dr))))
        tl.marksChanged.connect(self.marks_changed)
        tl.markerAdd.connect(self.add_marker)
        tl.markerMoved.connect(lambda mid, t: self.apply("移動標記", edit.move_marker, mid, t))
        tl.markerAction.connect(self.on_marker_action)
        tl.clipDragging.connect(lambda cid, start, dur: self.inspector.show_live_time(cid, start, dur, self.fps))
        tl.grabCancelled.connect(lambda: self.refresh_inspector())
        tl.volumeEdited.connect(self.on_volume_line)
        tl.keyMoveRequested.connect(lambda cid, a, b: self.apply("移動關鍵幀", edit.move_keys_at, cid, a, b))
        tl.trackAction.connect(self.on_track_action)
        tl.clipAction.connect(self.on_clip_action)
        tl.paramBind.connect(self.layer_param_bind)
        tl.paramUnbind.connect(self.unbind_params)
        tl.mediaDropped.connect(self.place_media)
        tl.mediaManyDropped.connect(self.place_media_many)
        tl.assetDropped.connect(self.place_asset)
        tl.compoundDropped.connect(self.place_compound)
        tl.replaceDropped.connect(self.replace_source)
        tl.filterDropped.connect(self.on_filter_dropped)
        tl.filesDropped.connect(lambda paths, tid, start, across: self.drop_files(
            paths, self.library.current_folder(), (tid, start, across)))
        tl.intoGroupRequested.connect(lambda ids, gid, tid, start: self.move_into_group(ids, gid, tid, start))
        tl.groupDropped.connect(self.group_drop)
        tl.tracksReordered.connect(lambda order: self.apply("移動軌道", edit.set_track_order, order))
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
        self.tl_tabs.tabRequested.connect(self.open_in_tab)
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
        # 轉為靜態複合片段: shown while the open compound's content is steady (edit.steady)
        self.static_btn = QPushButton("轉為靜態複合片段")
        self.static_btn.setToolTip("裡面的東西全部從頭開始、長度一樣：變成靜態片段，像圖片一樣使用（只顯示第一幀，長度隨意），"
                                   "用圖層編輯")
        self.static_btn.clicked.connect(lambda: self.open_kid() and self.compound_to_static(self.open_kid()))
        self.static_btn.setVisible(False)
        tools.addWidget(self.back_btn)
        tools.addWidget(self.crumb)
        tools.addWidget(self.static_btn)
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
        self.edit_fps_box.setToolTip("時間線每秒幾格（時基 BPM：每拍幾格，BPM 改了也維持）：播放頭、關鍵幀、分割、"
                                     "步進（←/→）的最小單位。\n"
                                     "只影響剪輯，不影響輸出：匯出照專案（或匯出設定）的幀率。")
        self.edit_fps_box.valueChanged.connect(self.on_edit_fps_box)
        tools.addWidget(self.edit_fps_box)
        tools.addSpacing(10)
        tools.addWidget(QLabel("時基"))
        self.timebase = timebase_of(None)
        self.timebases = {}                             # 時基 of each timeline / compound (level_key) that has one
        self.tb_key = None                              # whose self.timebase is
        self.timebase_btn = QPushButton(button_text(self.timebase))
        self.timebase_btn.setToolTip("時間尺和播放時間怎麼數：時間（分:秒.格）或 BPM（小節.拍.格，含細分、拍號、偏移）。\n"
                                     "只是顯示，不會吸附。")
        self.timebase_btn.clicked.connect(self.edit_timebase)
        tools.addWidget(self.timebase_btn)
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
        self.tl_split = QSplitter(Qt.Horizontal)        # the timeline | a live component's parameters
        self.tl_split.setChildrenCollapsible(False)
        self.tl_split.addWidget(tl)
        tl_row.addWidget(self.tl_split, 1)
        # a live component's parameters, beside its timeline (a static one's are under its layers)
        self.tl_params = ParamList("")
        self.tl_params.setMinimumWidth(160)
        self.tl_params.setVisible(False)
        self.tl_params.selectionPicked.connect(lambda ids, primary: self.timeline.set_selection(ids, primary))
        self.tl_params.paramUnbind.connect(self.unbind_params)
        self.tl_params.paramAction.connect(self.layer_param_action)
        self.tl_params.defaultDropped.connect(self.param_default_dropped)
        self.tl_params.paramExpr.connect(self.layer_param_expr)
        self.tl_params.picture_of = self.dropped_picture
        self.tl_split.addWidget(self.tl_params)
        self.tl_split.setStretchFactor(0, 1)
        self.tl_split.setStretchFactor(1, 0)
        self.tl_split.setSizes([1300, 270])
        self.meter = MeterPanel()
        self.meter.masterChanged.connect(self.on_master)
        tl_row.addWidget(self.meter)
        # a static compound (a picture) is edited as layers, as in Photoshop, not on a timeline
        self.layers = LayerPanel()
        lp = self.layers
        lp.selectionPicked.connect(lambda ids, primary: self.timeline.set_selection(ids, primary))
        lp.orderChanged.connect(self.restack_layers)
        lp.thumb = self.layer_thumb
        lp.flagToggled.connect(lambda tid, flag, on: self.apply(
            {"hidden": "隱藏", "locked": "鎖定"}[flag] + "圖層" if on else "取消" + {"hidden": "隱藏", "locked": "鎖定"}[flag],
            edit.set_track_flag, tid, flag, on))
        lp.flagsToggled.connect(lambda tids, flag, on: self.apply(
            {"hidden": "隱藏", "locked": "鎖定"}[flag] + "圖層" if on else "取消" + {"hidden": "隱藏", "locked": "鎖定"}[flag],
            lambda lvl: [edit.set_track_flag(lvl, tid, flag, on) for tid in tids]))
        lp.mediaDropped.connect(lambda ids, paths, above, g: self.layer_drop(ids, paths, above, None, g or None))
        lp.movedInto.connect(self.layers_into_group)
        lp.fxDropped.connect(self.layer_fx_drop)
        lp.replaceDropped.connect(self.replace_source)
        lp.renameRequested.connect(lambda cid: self.on_clip_action("rename", cid))
        lp.actionRequested.connect(self.layer_action)
        lp.paramBind.connect(self.layer_param_bind)
        lp.paramUnbind.connect(self.unbind_params)
        lp.paramAction.connect(self.layer_param_action)
        lp.defaultDropped.connect(self.param_default_dropped)
        lp.paramExpr.connect(self.layer_param_expr)
        lp.params_box.picture_of = self.dropped_picture
        lp.componentRequested.connect(lambda: self.open_kid() and self.component_kind(self.open_kid(), True))
        lp.shapeRequested.connect(lambda key: self.place_asset(assets.ident(key, *self.assets.colors), "", 0))
        tl_page = QWidget()
        tl_page.setLayout(tl_row)
        self.lower_stack = QStackedWidget()
        self.lower_stack.addWidget(tl_page)
        self.lower_stack.addWidget(self.layers)
        ll.addWidget(self.lower_stack, 1)

        self.rack_panel = RackPanel()                  # 全局參數架 (rack.py)
        rp = self.rack_panel
        rp.action.connect(self.on_rack_action)
        rp.addRequested.connect(self.add_rack_param)
        rp.importRequested.connect(self.import_rack)
        rp.exportRequested.connect(self.export_rack)
        # every panel is a dock: moved, put in tabs, split, floated freely (docks.py); a layout
        # (佈局) is one arrangement of them (layouts.py)
        self.panels = Panels(self, {
            "library": self.library, "assets": self.assets, "userlib": self.ulpanel, "vfx": self.vfx,
            "vfxnodes": self.vfxnodes, "compounds": self.compounds, "preview": center, "inspector": scroll, "effects": fx_dock,
            "mask": mask_scroll, "beats": beat_scroll, "subtitles": self.subtitles, "curves": cv, "rack": self.rack_panel,
            "nodes": self.nodes, "timeline": lower})
        self.panels["rack"].visibilityChanged.connect(lambda on: on and self.show_rack())
        for key, split in (("split/curves", cv.split), ("split/component", self.tl_split),
                           ("split/layers", self.layers.split)):     # where their lines were dragged to
            state = self.settings().value(key)
            if state is not None:
                split.restoreState(state)
            split.splitterMoved.connect(lambda *_a, k=key, sp=split: self.settings().setValue(k, sp.saveState()))
        # the 遮罩 panel in use (or 編輯遮罩 of an effect in the 效果 one) turns the preview into the mask editor
        def mask_mode():
            pn = self.panels
            if pn.is_active("mask"):
                self.preview.set_mask_mode(True, "mask")
            elif pn.is_active("effects") and ef.mask_edit:
                self.preview.set_mask_mode(True, "fxmask:" + ef.mask_edit)
            elif pn.is_active("effects") and ef.source_edit:
                self.preview.set_mask_mode(True, "fxsrc:{}:{}".format(*ef.source_edit))
            elif pn.is_active("nodes") and self.node_source:
                self.preview.set_mask_mode(True, "fxsrc:{}:{}".format(*self.node_source))
            elif pn.is_active("inspector") and ins.place_edit:
                self.preview.set_mask_mode(True, "place:" + ins.place_edit)
            else:
                self.preview.set_mask_mode(False)
            self._matte_preview_changed()
            self._update_matte_region()
        self.node_source = None         # (effect id, node id) of the picture node selected in the node editor
        self.node_mask_mode = mask_mode
        self.panels.activeChanged.connect(lambda _k: mask_mode())
        ef.maskEditChanged.connect(mask_mode)
        ins.placeEditChanged.connect(mask_mode)
        self.layout_key = None          # the layout the panels are in (layouts.py key)

        self.player = Player(self)
        self.player.worker.set_rate(self.rate_box.currentData())     # (the 播放速度 used last time)
        self.player.worker.set_keep_pitch(self.pitch_btn.isChecked())
        self.player.worker.set_overflow(OVERFLOW if self.overflow_btn.isChecked() else 0.0)       # (the 畫布外 button as it was left)
        w = self.player.worker
        w.frameReady.connect(self.on_frame)
        w.thumbsReady.connect(self.nodes.set_thumbs)
        w.loaded.connect(self.on_loaded)
        w.failed.connect(lambda m: self.statusBar().showMessage(f"預覽錯誤：{m}", 10000))  # never modal
        w.stateChanged.connect(self.on_state)
        w.levels.connect(self.meter.bars.feed)
        self.props_timer = QTimer(self)             # while playing: the selection's panels a few times a second
        self.props_timer.setSingleShot(True)
        self.props_timer.setInterval(PLAYING_PROPS_MS)
        self.props_timer.timeout.connect(self._playing_props)
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
        inertia.load(self.settings())
        self.cache_base = self.cache_base_of(self.cache_mode(), self.cache_custom())
        self.autosave_timer = QTimer(self, interval=self.autosave_min() * 60 * 1000)
        self.autosave_timer.timeout.connect(self._autosave)
        self.autosave_timer.start()
        self.apply_library_root(self.library_root())
        self.start_font_scan()
        self._menus()
        self._global_menu()
        self.start_layout()
        self._update_title()
        self._update_crumb()
        self._update_buttons()
        self.statusBar().showMessage("檔案 > 新專案…（或開啟最近的專案、匯入剪映草稿）")

    # -- menus ------------------------------------------------------------------------------------
    def _global_menu(self):
        """The same menus in the desktop's global menu bar too (KDE's at the top of the screen), as well as in the window:
        a second menu bar of the window's, made native, with the actions of the first. Where the platform has no
        global menu it is not native, and is not kept."""
        self.menuBar().setNativeMenuBar(False)                    # (the one in the window stays here, and animated)
        self.global_bar = None
        if sys.platform == "android":
            return
        bar = QMenuBar(self)
        bar.setNativeMenuBar(True)
        if not bar.isNativeMenuBar():
            bar.deleteLater()
            return
        for a in self.menuBar().actions():
            bar.addAction(a)
        self.global_bar = bar

    def _menus(self):
        def add(menu, text, key, fn):
            a = QAction(text, self)
            if key:                                      # (a tuple: more than one key does it)
                a.setShortcuts([QKeySequence(k) for k in ((key,) if isinstance(key, str) else key)])
            a.triggered.connect(fn)
            menu.addAction(a)

        self.menuBar().setNativeMenuBar(False)           # (before the corner is set: a native bar shows none)
        m = keyed(self.menuBar().addMenu("檔案(&F)"))
        add(m, "專案管理器…", "Ctrl+Shift+O", self.show_project_manager)
        add(m, "新專案…", "Ctrl+N", self.new_project)
        add(m, "開啟專案…", "Ctrl+O", self.open_project)
        self.recent_menu = m.addMenu("最近的專案")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        add(m, "儲存專案", "Ctrl+S", self.save_project)
        add(m, "另存新檔…", "Ctrl+Shift+S", lambda: self.save_project(True))
        m.addSeparator()
        add(m, "專案資訊…", "F11", self.show_project_info)
        add(m, "把目前畫面設為專案縮圖", None, self.thumbnail_from_frame)
        add(m, "自己做縮圖", None, self.make_thumbnail)
        add(m, "開啟專案資料夾", None, lambda: self.reveal(None))
        add(m, "整理素材到專案資料夾", None, self.collect_external)
        add(m, "清除專案緩存…", None, self.clear_project_cache)
        m.addSeparator()
        add(m, "設定…", "Ctrl+,", self.open_settings)
        m.addSeparator()
        add(m, "匯入剪映草稿…", "Ctrl+I", self.import_draft)
        add(m, "匯入素材…", "Ctrl+Shift+I", lambda: self.import_media(self.library.current_folder()))
        add(m, "匯出影片…", "Ctrl+E", self.export)
        add(m, "匯出目前畫面…", "Ctrl+Shift+E", self.export_still)
        m = keyed(self.menuBar().addMenu("編輯(&E)"))
        add(m, "復原", "Ctrl+Z", self.do_undo)
        add(m, "重做", "Ctrl+Y", self.do_redo)
        touch.on_tap(2, self.do_undo)                  # (two fingers tap a view: undo; three: redo)
        touch.on_tap(3, self.do_redo)
        m.addSeparator()
        add(m, "複製", "Ctrl+C", self.do_copy)
        add(m, "剪下", "Ctrl+X", lambda: self.do_copy(cut=True))
        add(m, "貼上", "Ctrl+V", self.do_paste)
        add(m, "建立副本", ("Ctrl+Shift+C", "Shift+D"), self.do_duplicate)
        m.addSeparator()
        add(m, "分割", "Ctrl+B", self.do_split)
        add(m, "向左裁剪（刪掉播放頭之前）", "Q", lambda: self.do_trim_to_playhead("start"))
        add(m, "向右裁剪（刪掉播放頭之後）", "W", lambda: self.do_trim_to_playhead("end"))
        add(m, "頭尾對齊拍子", "Alt+Q", self.do_snap_beats)
        add(m, "打亂順序", "Alt+R", self.do_shuffle)
        add(m, "反轉排序（上下顛倒）", None, self.do_reverse_rows)
        add(m, "刪除", ("Delete", "Backspace", "X"), self.do_delete)
        add(m, "波紋刪除（後面的片段補上空隙）", ("Shift+Delete", "Shift+Backspace", "Shift+X"), self.do_ripple_delete)
        add(m, "移到上面的軌道", "Ctrl+Up", lambda: self.do_move_rows(-1))
        add(m, "移到下面的軌道", "Ctrl+Down", lambda: self.do_move_rows(1))
        add(m, "全選片段", "Ctrl+A", lambda: self.timeline.select_all())
        add(m, "取消選取", "Ctrl+D", lambda: self.timeline.select(None))
        add(m, "新增文字", "Ctrl+T", self.do_text)
        viz_menu = m.addMenu("新增 Audio Visualizer")
        for kind, name in viz.KINDS.items():
            add(viz_menu, name, None, lambda _=False, k=kind: self.add_visualizer(k))
        add(m, "重新命名", "F2", self.do_rename)
        add(m, "清除空軌道", None, self.clear_empty_tracks)
        m.addSeparator()
        add(m, "建立群組", "Ctrl+G", lambda: self.make_group())
        add(m, "解散群組", "Ctrl+Shift+G", lambda: self.ungroup())
        add(m, "建立複合片段", "Alt+G", self.do_make_compound)
        m.addSeparator()
        add(m, "字體對應…", None, lambda: self.check_fonts(auto=False))
        m = keyed(self.menuBar().addMenu("濾鏡(&T)"))
        self.filter_menu = m.addMenu("新增濾鏡片段（在播放頭）")
        self.filter_menu.aboutToShow.connect(lambda: self._fill_filter_menu(self.filter_menu, self.add_filter_clip))
        self.apply_menu = m.addMenu("套用到選取的片段")
        self.apply_menu.aboutToShow.connect(lambda: self._fill_filter_menu(self.apply_menu, self.apply_filter_to_selected))
        m.addSeparator()
        add(m, "新增自訂濾鏡檔…", None, lambda: self.new_filter_file(None))
        add(m, "濾鏡寫法說明…", None, self.show_filter_doc)
        add(m, "檢查所有濾鏡", None, self.check_filters)
        m = keyed(self.menuBar().addMenu("工具(&O)"))          # built in, each opened when wanted (ui/tools.py)
        add(m, "cubic-bezier 編輯器", None, lambda: self.open_tool("bezier"))
        add(m, "調色盤", None, lambda: self.open_tool("palette"))
        add(m, "全局參數架", None, self.open_rack)
        m = keyed(self.menuBar().addMenu("視窗(&W)"))
        self.layout_menu = m.addMenu("佈局")
        self.layout_menu.aboutToShow.connect(self._fill_layout_menu)
        add(m, "儲存目前佈局", None, self.save_layout)
        add(m, "另存為新佈局…", None, self.save_layout_as)
        add(m, "重設目前佈局", None, lambda: self.reset_layout(self.layout_key))
        add(m, "開啟佈局資料夾", None, self.reveal_layouts)
        add(m, "下一個佈局", "Ctrl+PgDown", lambda: self.step_layout(1))
        add(m, "上一個佈局", "Ctrl+PgUp", lambda: self.step_layout(-1))
        add(m, "關閉目前分頁", "Ctrl+W", lambda: self.close_timeline(self.current_tab()) if self.proj else None)
        m.addSeparator()
        self.panel_menu = m
        self.panel_actions = []
        m.aboutToShow.connect(self._fill_panel_actions)
        # the layouts as tabs at the right of the menu bar, as Blender's workspaces
        corner = QWidget()
        row = QHBoxLayout(corner)
        row.setContentsMargins(0, 0, 6, 0)
        row.setSpacing(2)
        self.layout_tabs = QTabBar()
        self.layout_tabs.setObjectName("layouts")
        self.layout_tabs.setDrawBase(False)
        self.layout_tabs.setExpanding(False)
        self.layout_tabs.setFocusPolicy(Qt.NoFocus)
        self.layout_tabs.setToolTip("佈局：面板的排法（右鍵：重設、覆寫、重新命名、刪除）")
        self.layout_tabs.currentChanged.connect(self._layout_tab_switched)
        self.layout_tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.layout_tabs.customContextMenuRequested.connect(self._layout_tab_menu)
        row.addWidget(self.layout_tabs)
        plus = self.tool("plus", "把目前的排法存成新佈局（存在 KiaseCut/preset/layout）", self.save_layout_as)
        plus.setIconSize(QSize(14, 14))
        row.addWidget(plus)
        self.layout_corner = corner                      # (PySide would delete it with this function's locals)
        self.menuBar().setCornerWidget(corner, Qt.TopRightCorner)     # (the window's own bar is not native: _global_menu keeps a second one for the desktop's)
        m = keyed(self.menuBar().addMenu("播放(&P)"))
        add(m, "標記入點", "I", lambda: self.set_mark("in"))
        add(m, "標記出點", "O", lambda: self.set_mark("out"))
        add(m, "清除標記", "Alt+X", lambda: self.set_mark(None))
        add(m, "取消選區", "Ctrl+Shift+D", lambda: self.set_mark(None))
        add(m, "新增時間線標記", "M", lambda: self.add_marker())
        add(m, "自動吸附", "N", lambda: self.snap_btn.toggle())
        add(m, "設定 / 取消為參考軌道", "R", self.toggle_reference)
        m.addSeparator()
        add(m, "上一個剪輯點", "Up", lambda: self.jump_edit(-1))
        add(m, "下一個剪輯點", "Down", lambda: self.jump_edit(1))
        add(m, "後退一秒", "Shift+Left", lambda: self.step(-round(self.fps)))
        add(m, "前進一秒", "Shift+Right", lambda: self.step(round(self.fps)))
        add(m, "上一個關鍵幀", "Alt+Left", lambda: self.jump_key(-1))
        add(m, "下一個關鍵幀", "Alt+Right", lambda: self.jump_key(1))
        m.addSeparator()
        add(m, "時間軸放大", ("Ctrl+=", "Ctrl++"), lambda: self.timeline.zoom_by(1.25, self.pos / self.fps))
        add(m, "時間軸縮小", "Ctrl+-", lambda: self.timeline.zoom_by(0.8, self.pos / self.fps))
        add(m, "時間軸縮放至適合", "Shift+Z", lambda: self.timeline.zoom_fit())
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
        appevents.watch(self, (QEvent.ShortcutOverride,), self.eventFilter)

    def eventFilter(self, obj, e):
        # ↑ / ↓ (剪輯點) stay with a focused widget that steps with them: a number field, a
        # menu box, a slider, a list
        if (e.type() == QEvent.ShortcutOverride and e.key() in (Qt.Key_Up, Qt.Key_Down)
                and not e.modifiers() & ~Qt.KeypadModifier
                and isinstance(QApplication.focusWidget(), (QAbstractSpinBox, QComboBox, QAbstractSlider, QAbstractItemView))):
            e.accept()
        return False

    def _update_title(self):
        name = (workspace.title_of(self.proj, self.path) or "未儲存的新專案") if self.proj else ""
        self.setWindowTitle("KiaseCut" + (f" — {name}" if name else "") + (" *" if self.dirty else ""))
        self.library.set_origin("", self.root or "")

    def _update_buttons(self):
        h = self.history
        self.buttons["undo"].setEnabled(bool(h and h.undo_stack))
        self.buttons["redo"].setEnabled(bool(h and h.redo_stack))
        has = self.proj is not None
        for k in ("split", "text"):
            self.buttons[k].setEnabled(has)
        self.buttons["delete"].setEnabled(has and self.timeline.selected is not None)

    def current_tab(self):
        """The tab the editor shows: "cmp:<id>" for a compound open in a tab of its own, else
        the open timeline's id."""
        if self.path_ids and self.path_ids[0].startswith(OPEN_PREFIX) and self.path_ids[0] in (self.open_tls or []):
            return self.path_ids[0]
        return self.proj["active_timeline"]

    def _update_timeline_tabs(self):
        """One tab per open timeline - and per compound opened in a tab of its own - each with
        an X (closing hides the tab, the timeline or compound stays in the project and in the
        compound list). The open timeline always has a tab."""
        self._tabs_updating = True
        while self.tl_tabs.count():
            self.tl_tabs.removeTab(0)
        if self.proj:
            ids = [tl["id"] for tl in self.proj["timelines"]]
            comps = self.proj.get("compounds", {})
            if self.open_tls is None:
                self.open_tls = list(ids)
            self.open_tls = [t for t in self.open_tls if t in ids or
                             (t.startswith(OPEN_PREFIX) and t[len(OPEN_PREFIX):] in comps)]
            if self.proj["active_timeline"] not in self.open_tls:
                self.open_tls.append(self.proj["active_timeline"])
            many = len(self.open_tls) > 1
            current = self.current_tab()
            for key in self.open_tls:
                if key.startswith(OPEN_PREFIX):
                    comp = comps[key[len(OPEN_PREFIX):]]
                    name = ("◧ " if comp.get("static") else "⧉ ") + (comp.get("name") or "複合片段")
                    tip = "關閉這個分頁（複合片段保留）"
                else:
                    name, tip = project.timeline(self.proj, key)["name"], "關閉這個時間線（內容保留，可從「複合片段」重新打開）"
                i = self.tl_tabs.addTab(name)
                self.tl_tabs.setTabData(i, key)
                close = self.tool("close", tip, lambda _=False, t=key: self.close_timeline(t))
                close.setIconSize(QSize(12, 12))
                close.setFixedSize(18, 18)
                self.tl_tabs.setTabButton(i, QTabBar.RightSide, close)
                close.setVisible(many)                    # (setTabButton shows it)
                if key == current:
                    self.tl_tabs.setCurrentIndex(i)
        self._tabs_updating = False

    def close_timeline(self, tid):
        """Close a tab (a timeline's or a compound's); the one before / after it opens if it
        was the one shown."""
        if not self.proj or self.open_tls is None or len(self.open_tls) < 2 or tid not in self.open_tls:
            return
        shown = self.current_tab() == tid
        i = self.open_tls.index(tid)
        rest = [t for t in self.open_tls if t != tid]
        if not tid.startswith(OPEN_PREFIX) and not any(not t.startswith(OPEN_PREFIX) for t in rest):
            return                                       # a timeline must keep a tab
        if shown:                                        # show the tab before it first
            self.open_tab(rest[max(0, i - 1)])
        if tid == self.proj["active_timeline"]:          # (a compound tab is shown: its timeline goes)
            edit.open_timeline(self.proj, next(t for t in rest if not t.startswith(OPEN_PREFIX)))
            self.dirty = True
        self.open_tls = rest
        self._update_timeline_tabs()

    def _tab_switched(self, i):
        if not self._tabs_updating and i >= 0:
            self.open_tab(self.tl_tabs.tabData(i))

    def open_in_tab(self, ref):
        """Open a compound (or timeline) in a tab of its own (added when it has none)."""
        if not self.proj:
            return
        key = ref if any(t["id"] == ref for t in self.proj["timelines"]) else OPEN_PREFIX + ref
        if key.startswith(OPEN_PREFIX) and ref not in self.proj.get("compounds", {}):
            return
        if self.open_tls is None:
            self.open_tls = [t["id"] for t in self.proj["timelines"]]
        if key not in self.open_tls:
            self.open_tls.append(key)
        self.open_tab(key)

    def open_tab(self, key):
        """Show a tab: a timeline (as it was left) or a compound opened by itself."""
        if not self.proj:
            return
        cur = self.current_tab()
        if key == cur:
            self._update_timeline_tabs()
            return
        self.tl_views[cur] = self.level_view()
        if key.startswith(OPEN_PREFIX):
            v = self.tl_views.get(key) or {}
            self.path_ids = [key]
            try:
                pos = max(0, int(v.get("pos", 0)))
            except (TypeError, ValueError):
                pos = 0
            self._switch_level(pos)
            if v.get("px_per_s"):
                self.timeline.set_view_state(v)
                self.follow = False
        else:
            if key != self.proj["active_timeline"]:
                edit.open_timeline(self.proj, key)
                self.dirty = True
            self.path_ids = []
            self.open_view(self.tl_views.get(key, {}))
        self._update_title()

    def switch_timeline(self, tl_id):
        """Open another timeline of the project (not an edit: undo does not step through it)."""
        if not self.proj or (tl_id == self.proj["active_timeline"] and self.current_tab() == tl_id):
            return
        self.open_tab(tl_id)

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
        tls[self.current_tab()] = self.level_view()
        out = {"vzoom": round(self.timeline.vzoom, 4), "timelines": tls}
        if self.open_tls:
            out["tabs"] = list(self.open_tls)
        if self.fps != self.proj["fps"]:
            out["edit_fps"] = self.fps
        tbs = {k: dict(tb) for k, tb in self.timebases.items() if tb != timebase_of(None)}
        if tbs:
            out["timebases"] = tbs
        out["workspace"] = self.workspace_state()
        return out

    def workspace_state(self):
        """The workspace (工作區): the layout and where its panels are, the selected clips, how the node editor
        is looked at - stored with the project, put back when it is opened."""
        ws = {"nodes": self.nodes.view_state()}
        if self.layout_key:
            ws["layout"] = self.layout_key
        ws["panels"] = layouts.pack(self.panels.state(), self.panels.closed())
        ids = [c["id"] for c in self.timeline.selected_clips_primary_first()]
        if ids:
            ws["selected"] = ids
        return ws

    def restore_workspace(self, ws):
        """Put the workspace back as workspace_state() left it (what is gone is left out)."""
        if not isinstance(ws, dict):
            return
        key = ws.get("layout")
        if isinstance(key, str) and key in self.layout_keys() and key != self.layout_key:
            self.use_layout(key)
        if isinstance(ws.get("panels"), dict):
            try:
                self.panels.restore(*layouts.unpack(ws["panels"]))
            except ValueError:
                pass
        ids = ws.get("selected")
        if isinstance(ids, list) and ids:
            self.timeline.set_selection({str(i) for i in ids}, str(ids[0]))
        self.nodes.set_view_state(ws.get("nodes"))

    def open_view(self, v):
        """Open the active timeline as level_view() left it (a compound that is gone opens
        the timeline itself)."""
        path = v.get("path") if isinstance(v.get("path"), list) else []
        try:
            walk_path(self.proj, path)
        except (edit.EditError, KeyError, TypeError, AttributeError):
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
        menu = Menu(self)
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
            i = next((k for k in range(self.tl_tabs.count()) if self.tl_tabs.tabData(k) == tid), -1)
            name, ok = inplace.ask_name(self, tl["name"], (self.tl_tabs, self.tl_tabs.tabRect(i)) if i >= 0 else None)
            if ok:
                self.apply_root("重新命名時間線", edit.rename_timeline, tid, name)
        elif action == "duplicate":
            self.apply_root("複製時間線", lambda root: edit.add_timeline(root, copy_of=tid))
        elif action == "delete":
            if questions.question(self, "delete_timeline", "刪除時間線", f"刪除「{tl['name']}」和上面的片段？"):
                self.apply_root("刪除時間線", edit.delete_timeline, tid)

    def _update_crumb(self):
        self._update_timeline_tabs()
        self.viewer_lbl.setText(project.timeline(self.proj)["name"] if self.proj else "")
        names = [project.timeline(self.proj)["name"] if self.proj else "主時間軸"]
        for c, node, _ref in walk_path(self.proj, self.path_ids) if self.proj else []:
            if c is None:                                # a compound opened by itself: no timeline around it
                names = ["複合片段：" + (node.get("name") or "複合片段")]
                self.viewer_lbl.setText(names[0])
            else:
                names.append(c.get("name") or "複合片段")
        self.crumb.setText(" › ".join(names) if self.path_ids else "")
        self.compounds.set_project(self.proj, self.path_ids)
        self._update_library_tabs()
        self.back_btn.setVisible(bool(self.path_ids))
        key = self.level_key()
        if key != self.tb_key:                           # 時基 goes with the level shown
            self.tb_key = key
            self.set_timebase(self.timebases.get(key) or timebase_of(None), edited=False)

    def level_key(self):
        """The open level's id: the open compound's (or nested timeline's), else the open
        timeline's - what its 時基 is kept under."""
        if not self.proj:
            return None
        return self.open_kid() or self.proj["active_timeline"]

    # -- levels (main timeline / compound clips) ------------------------------------------------
    def container(self, root=None):
        """The tracks owner that is open: the project or a compound's content."""
        root = self.proj if root is None else root
        steps = walk_path(root, self.path_ids)
        return steps[-1][1] if steps else root

    def view(self):
        """Project-like dict for the open level, for the timeline and the preview build."""
        if not self.path_ids:
            return self.proj
        node = self.container()
        return {"width": node["width"], "height": node["height"], "fps": self.proj["fps"],
                "master_gain": self.proj.get("master_gain", 1.0),
                "duration_us": max(project.end_us(node["tracks"]), node.get("duration_us") or 0, 1),
                "tracks": node["tracks"], "compounds": self.proj.get("compounds", {}),
                "markers": node.get("markers") or [], "rack": self.proj.get("rack") or [],
                "open_component": node if components.is_component(node) else None}

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

    def open_compound_entry(self, kid):
        """From the compound list: edit compound kid by itself (no clip has to show it)."""
        if not self.proj or kid not in self.proj.get("compounds", {}):
            return
        if not (self.path_ids and self.path_ids[0].startswith(OPEN_PREFIX)):
            self.return_pos = self.pos if not self.path_ids else 0     # where 返回上一層 goes back to
            self._return_path = list(self.path_ids)
        self.path_ids = [OPEN_PREFIX + kid]
        self._switch_level(0)

    def enter_compound(self, cid):
        _, c = edit.find(self.container(), cid)
        if project.is_static(c):                         # its picture is its first frame
            inner = 0
        else:
            inner = round(project.source_time(c, self.playhead_us() - c["start_us"]) / US * self.fps)
        self.path_ids.append(cid)
        self._switch_level(max(0, inner))

    def leave_compound(self):
        if not self.path_ids:
            if self.fullscreen:
                self.fullscreen.close()
            return
        cid = self.path_ids.pop()
        if cid.startswith(OPEN_PREFIX):                  # a compound opened by itself: back where it was opened
            self.path_ids = [p for p in getattr(self, "_return_path", []) if not p.startswith(OPEN_PREFIX)]
            try:
                self.container()
            except (edit.EditError, KeyError):
                self.path_ids = []
            self._switch_level(getattr(self, "return_pos", 0) if not self.path_ids else 0)
            return
        _, c = edit.find(self.container(), cid)
        if project.is_static(c):                         # (its time does not map onto the outer one)
            outer = round(c["start_us"] / US * self.fps)
        else:
            k = project.speed(c)                         # inner time back to outer time
            outer = round((c["start_us"] + (self.pos / self.fps * US - c.get("source_start_us", 0)) / k)
                          / US * self.fps)
        self._switch_level(max(0, outer), select=c)

    def _switch_level(self, pos, select=None):
        self.player.worker.set_playing(False)
        self.timeline.mark_in = self.timeline.mark_out = None      # selections belong to a level
        self.marks_changed()
        if self._level_key is not None and self.timeline.proj is not None:      # back to a level: as it was left
            self.level_zoom[self._level_key] = {k: v for k, v in self.timeline.view_state().items()
                                                if k in ("scroll_s", "px_per_s")}
        self._level_key = (self.current_tab(), tuple(self.path_ids))
        self.timeline.set_project(self.view())
        if self._level_key in self.level_zoom:
            self.timeline.set_view_state(self.level_zoom[self._level_key])
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
            base = self.cache_base
            return workspace.cache_dir(self.root, base, workspace.cache_id(self.proj, self.root) if base else None)
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
            return self.projects_root(str(s))
        docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or os.path.expanduser("~")
        old = os.path.join(docs, "tesetoa")                 # the program's earlier name
        if os.path.isdir(old) and not os.path.isdir(os.path.join(docs, "KiaseCut")) and \
                not self.settings().value("root_dir"):
            return old.replace("\\", "/")
        return self.app_root()

    def projects_root(self, folder):
        """The projects folder: what 設定 or the manager's ✎ chose. A folder left behind by the old way (every opened project made its folder
        the projects folder, so it drifted deeper) goes back up to its top folder under the root folder."""
        if self.settings().value("project_dir_chosen") in (True, "true"):
            return folder
        root = os.path.abspath(self.app_root())
        a = os.path.abspath(folder)
        if a.startswith(root.rstrip(os.sep) + os.sep):
            top = a[len(root.rstrip(os.sep)) + 1:].split(os.sep)[0]
            return os.path.join(root, top).replace("\\", "/")
        return folder

    def recent(self):
        v = self.settings().value("recent", [])
        v = v if isinstance(v, list) else ([v] if v else [])
        return [str(p) for p in v]

    def remember(self, path):
        s = self.settings()
        s.setValue("recent", [path] + [p for p in self.recent() if p != path][:9])

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

    def show_project_manager(self):
        """Every project with its thumbnail; open one, or start / find another."""
        dlg = ProjectManager(self, self.default_location(), self.recent(), current=self.path)
        accepted = dlg.exec() == QDialog.Accepted
        if dlg.new_location:                             # ✎: the projects folder changed there
            self.settings().setValue("project_dir", dlg.new_location)
            self.settings().setValue("project_dir_chosen", True)
        if dlg.moved or dlg.removed:                     # projects moved, renamed or deleted there
            moved = dict(dlg.moved)
            rec = [moved.get(p, p) for p in self.recent() if p not in dlg.removed]
            self.settings().setValue("recent", rec)
        if not accepted or not dlg.choice:
            return
        what = dlg.choice[0]
        if what == "open":
            self.open_recent(dlg.choice[1])
        elif what == "new":
            self.new_project(dlg.choice[1])
        else:
            self.open_project()

    def thumbnail_from_frame(self):
        """The frame the preview shows becomes the project's thumbnail."""
        if not self.proj or not self.path:
            QMessageBox.information(self, "專案縮圖", "先儲存專案，才能替它做縮圖。")
            return
        if project.thumbnail_compound(self.proj) is not None:
            QMessageBox.information(self, "專案縮圖", f"這個專案有「{project.THUMBNAIL}」靜態複合片段，縮圖會用它的畫面。\n"
                                                    f"要改用目前的畫面，先把它改名或刪掉。")
            return
        try:
            thumbnail.save_image(self.preview.img, self.path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "專案縮圖", str(exc))
            return
        self.statusBar().showMessage("已把目前的畫面設為專案縮圖", 4000)

    def open_tool(self, kind):
        """工具: the cubic-bezier editor or the palette, in a window of its own (one of each)."""
        tools = self.__dict__.setdefault("_tools", {})
        w = tools.get(kind)
        if w is None:
            from .tools import BezierTool, PaletteTool
            w = tools[kind] = (BezierTool if kind == "bezier" else PaletteTool)(self.app_root)
        else:
            w.fill()
        if sys.platform == "android" or os.environ.get("KIASECUT_TOOL_COVER"):      # (fullscreen: over the window, not a window of its own)
            from .tools import ToolCover
            covers = self.__dict__.setdefault("_tool_covers", {})
            cover = covers.get(kind)
            if cover is None:
                cover = covers[kind] = ToolCover(self, w)
            cover.present()
            return
        w.show()
        w.raise_()
        w.activateWindow()

    def on_text_var(self, ids, action, arg):
        """文字變數: 新增 (arg: its kind), 刪除 (its name) or a change (name, {new_name, kind, decimals, fmt})."""
        if action == "add":
            self.apply_each("新增變數", edit.add_text_var, ids, arg)
        elif action == "remove":
            self.apply_each("刪除變數", edit.remove_text_var, ids, arg)
        else:
            name, fields = arg
            self.apply_each("變數", lambda lvl, cid: edit.set_text_var(lvl, cid, name, **fields), ids)

    def make_thumbnail(self):
        """自己做縮圖: the _thumbnail static compound (made now, the canvas's size, when there is
        none) opened to be drawn; every save draws it into the thumbnail."""
        if not self.proj:
            return
        comp = project.thumbnail_compound(self.proj)
        if comp is None:
            if any(c.get("name") == project.THUMBNAIL for c in self.proj.get("compounds", {}).values()):
                QMessageBox.information(self, "自己做縮圖", f"已經有一個叫「{project.THUMBNAIL}」的複合片段，但它不是靜態的。\n"
                                                        f"把它改名，或轉為靜態複合片段。")
                return

            def make(root):
                kid = edit.add_compound(root, static=True)
                root["compounds"][kid]["name"] = project.THUMBNAIL
                return kid
            kid = self.apply_root("自己做縮圖", make)
        else:
            kid = next(k for k, c in self.proj["compounds"].items() if c is comp)
        if self.path:
            thumbnail.turn_on(self.path)
        if kid:
            self.open_compound_entry(kid)
            self.statusBar().showMessage(f"在「{project.THUMBNAIL}」裡做縮圖：每次儲存都會用它的畫面更新縮圖", 6000)

    def apply_thumbnail_compound(self):
        """套用縮圖: the _thumbnail compound is the thumbnail again (after the project manager's 拿掉縮圖)."""
        if not self.path:
            QMessageBox.information(self, "專案縮圖", "先儲存專案，才能替它做縮圖。")
            return
        thumbnail.turn_on(self.path)
        self.update_thumbnail()
        self.statusBar().showMessage(f"已用「{project.THUMBNAIL}」的畫面當專案縮圖", 4000)

    def update_thumbnail(self):
        """After a save: draw the _thumbnail static compound (if any) into the thumbnail."""
        try:
            done = thumbnail.update(self.proj, self.path, self._thumb_video)
        except Exception as exc:                          # a thumbnail must never spoil a save
            self.statusBar().showMessage(f"縮圖沒有更新：{exc}", 6000)
            return
        if done == "not static":
            self.statusBar().showMessage(f"「{project.THUMBNAIL}」不是靜態複合片段，沒有拿來做縮圖", 6000)

    def _thumb_video(self, path, us, w, h):
        """Video pictures for drawing a thumbnail (from the media engine)."""
        try:
            if getattr(self, "_thumb_engine", None) is None:
                self._thumb_engine = EngineClient(1920, 1080)
            k = min(1.0, (1920 * 1080 / max(1, w * h)) ** 0.5)
            px, rw, rh = self._thumb_engine.media_frame(path, us, self.proj["fps"], max(1, int(w * k)), max(1, int(h * k)))
            return QImage(px, rw, rh, rw * 4, QImage.Format_RGBA8888).copy()
        except Exception:
            return None

    def ensure_project(self):
        """Media goes into a project folder, so there has to be a project first."""
        return bool(self.proj) or self.new_project()

    def new_project(self, location=None):
        if not self.maybe_save():
            return False
        dlg = NewProjectDialog(self, location or self.default_location(), place=False)
        if dlg.exec() != QDialog.Accepted:
            return False
        _, _, w, h, fps = dlg.values()
        was, self.path = self.path, None                # nothing is written until 儲存 (Ctrl+S) asks where
        if not self.set_project(project.new(w, h, fps)):
            self.path = was
            return False
        self.new_location = location                    # (the first save offers it)
        return True

    def open_loaded(self, proj, path):
        """Whether it was opened (the user may back out when its media are missing)."""
        was, self.path = self.path, path
        if not self.set_project(proj):
            self.path = was
            return False
        self.remember(path)
        return True

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
        if not self.open_loaded(proj, path):
            return
        if warnings:
            QMessageBox.information(self, "匯入完成", "部分內容無法匯入：\n" + "\n".join(sorted(set(warnings))))
        # the draft's media stay where they are: the library's copy button brings them in

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
        if not self.open_loaded(proj, fn):
            return False
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
            name, ok = QInputDialog.getText(self, "另存新檔", "專案檔名稱",
                                            text=old + " 2")
            name = workspace.safe_name(name, "")
            if not ok or not name:
                return False
            fn = workspace.project_file(self.root, name)
            if os.path.exists(fn) and not questions.question(self, "overwrite_project", "覆蓋", f"「{name}」已經存在，要覆蓋嗎？"):
                return False
            self.path = fn
        self.proj["view"] = self.view_state()
        try:
            workspace.save(self.proj, self.path)
        except OSError as exc:
            QMessageBox.critical(self, "儲存失敗", str(exc))
            return False
        self.dirty = False
        self._session(autosave=None)
        self.remember(self.path)
        self._update_title()
        self.statusBar().showMessage("已儲存", 3000)
        self.update_thumbnail()
        return True

    def new_location_for_unsaved(self):
        """A project without a folder (made by a tool): ask where its folder goes."""
        dlg = NewProjectDialog(self, getattr(self, "new_location", None) or self.default_location(), "新專案",
                               (self.proj["width"], self.proj["height"], self.proj["fps"]), "儲存專案")
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
        """Whether it was opened (False: the user chose not to, over its missing media)."""
        root = workspace.root_of(self.path) if self.path else None
        if root:                            # built-in assets are drawn again rather than looked for
            assets.restore(project.all_clips(proj), workspace.media_dir(root))
        if not self.relink(proj):
            return False
        self.root = root
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
        self._session(autosave=None)
        self.path_ids = []
        self.open_tls = None
        self.tl_views = {}
        self.level_zoom, self._level_key = {}, (self.proj["active_timeline"], ())
        self._thumb_renderer = None                    # (layer thumbnails: the last project's pictures go)
        self.fps = edit_rate(proj)
        self.timeline.edit_fps = self.fps if self.fps != proj["fps"] else None
        view = proj.get("view") if isinstance(proj.get("view"), dict) else {}
        tbs = view.get("timebases") if isinstance(view.get("timebases"), dict) else {}
        self.timebases = {k: timebase_of(v) for k, v in tbs.items()}
        if "timebase" in view and not tbs:             # (saved before each level had its own)
            self.timebases[proj["active_timeline"]] = timebase_of(view["timebase"])
        self.tb_key = None
        self.set_timebase(timebase_of(None), edited=False)      # (_update_crumb shows the level's)
        self.timeline.mark_in = self.timeline.mark_out = None
        self.player.worker.set_loop(None)
        self.timeline.set_peaks(waveform.Peaks(self.cache_dir(), on_ready=self.timeline.peaksReady.emit))
        self.timeline.set_project(proj)
        self.refresh_library()
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
        if isinstance(saved.get("tabs"), list):          # the tabs that were open (compounds' too)
            self.open_tls = [str(t) for t in saved["tabs"]]
            self._update_timeline_tabs()
        if isinstance(views.get(proj["active_timeline"]), dict):
            self.open_view(views[proj["active_timeline"]])
        self.restore_workspace(saved.get("workspace"))
        self._last_tick = time.monotonic()
        self.watch_media()
        self.request_sync(0)
        self.check_fonts(auto=True)
        return True

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
        dlg.exec()                                       # (closed with Esc too: the text is kept)
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

    def _session(self, **fields):
        """Tell this program's session file (recovery.py) which project is open and its newest
        autosave (None: nothing unsaved to bring back)."""
        if self.autosave_dir:
            recovery.note(self.autosave_dir, project=self.path, **fields)

    def _autosave(self):
        """Every few minutes: unsaved changes go to the autosave folder (recovery.py), from
        where the next start offers them back if this program ends unexpectedly."""
        if not (self.autosave_dir and self.proj and self.dirty):
            return
        self.proj["view"] = self.view_state()
        state = project.dumps(self.proj)
        if state == self._autosaved:
            return
        try:
            recovery.autosave(self.autosave_dir, self.proj, self.path, self.autosave_limit())
            self._autosaved = state
        except OSError as exc:
            self.statusBar().showMessage(f"自動存檔失敗：{exc}", 6000)

    def begin_session(self):
        """At start: this program's session in the autosave folder (~/Documents/KiaseCut/auto-save)."""
        self.autosave_dir = self.autosave_folder()
        try:
            recovery.begin(self.autosave_dir)
        except OSError:
            self.autosave_dir = None

    def offer_recovery(self):
        """At start: a program that ended unexpectedly left unsaved changes in an autosave;
        offer to open them (as unsaved changes of their project). Whether it was opened."""
        if not self.autosave_dir:
            return False
        found = recovery.crashed(self.autosave_dir)
        if not found:
            return False
        session, data = found[0]                         # (others are offered at the next start)
        save, path = data["autosave"], data.get("project")
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(save)))
        box = QMessageBox(QMessageBox.Warning, "回復自動存檔",
                          "KiaseCut 上次沒有正常結束，留下了尚未儲存的修改。\n\n"
                          f"專案：{recovery.stem(path)}\n自動存檔時間：{when}\n\n"
                          "要打開自動存檔的內容嗎？打開後記得儲存（Ctrl+S）。", parent=self)
        yes = box.addButton("回復", QMessageBox.AcceptRole)
        box.addButton("不要", QMessageBox.RejectRole)
        box.setDefaultButton(yes)
        box.exec()
        recovery.forget(session)
        if box.clickedButton() is not yes:
            return False                                 # (the file stays in the folder, within the limit)
        try:
            proj = project.load(save)
        except Exception as exc:
            QMessageBox.critical(self, "無法回復", f"{save}\n{exc}")
            return False
        if path and os.path.exists(path):
            if not self.open_loaded(proj, path):
                return False
        else:                                            # its folder is gone: an unsaved project
            was, self.path = self.path, None
            if not self.set_project(proj):
                self.path = was
                return False
        self.dirty = True
        self._session(autosave=save)                     # (still unsaved: kept for another time)
        self._update_title()
        self.statusBar().showMessage(f"已從自動存檔回復（{when}）：記得儲存", 10000)
        return True

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
                self.refresh_library()
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

    def refresh_library(self):
        """Show the project's library, and the copy button while some media sit outside Media."""
        self.library.set_library(library.lib(self.proj) if self.proj else {})
        self.library.set_external(library.external_count(self.proj, self.root) if self.proj and self.root else 0)

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
        if ask and not questions.question(
                self, "collect_media", "整理素材",
                f"有 {len(plan)} 個素材在專案資料夾外面。\n要把它們複製到專案的 Media 資料夾嗎？\n（原檔不會被動到）"):
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
        """Offer to find missing media by file name under a folder the user picks.
        False when the user would rather not open the project after all."""
        clips = [c for c in project.all_clips(proj) if c.get("media")]
        items = library.lib(proj)["items"]
        refs = [c["media"] for c in clips] + items
        missing = sorted({x["path"] for x in refs if not os.path.exists(x["path"])})
        if not missing:
            return True
        box = QMessageBox(QMessageBox.Question, "找不到素材",
                          f"有 {len(missing)} 個素材檔案找不到，例如：\n{missing[0]}\n\n要選一個資料夾自動尋找嗎？",
                          parent=self)
        find = box.addButton("選資料夾尋找", QMessageBox.AcceptRole)
        skip = box.addButton("直接開啟", QMessageBox.RejectRole)
        back = box.addButton("那先不要開好了", QMessageBox.DestructiveRole)
        box.setDefaultButton(find)
        box.setEscapeButton(skip)
        box.exec()
        if box.clickedButton() is back:
            return False
        if box.clickedButton() is not find:
            return True
        root = QFileDialog.getExistingDirectory(self, "選擇素材所在的資料夾")
        if not root:
            return True
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
        return True

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
        if self.editing_static():                        # a static compound is one frame: what comes in fills it
            inner = fn

            def fn(root, *a):
                out = inner(root, *a)
                edit.flatten_static(self.container(root), self.proj["fps"])
                return out
        try:
            result = self.history.do(label, fn, *args, merge=merge)
        except edit.EditError as exc:
            self.statusBar().showMessage(f"{label}：{exc}", 4000)
            self.timeline.update()
            return None
        except Exception as exc:                       # a file that cannot be read, say
            self.statusBar().showMessage(f"{label}失敗：{exc}", 6000)
            return None
        if self.path_ids and not self.editing_static():  # content may outgrow the compound
            node = self.container()
            node["duration_us"] = max(node.get("duration_us") or 0, project.end_us(node["tracks"]))
        if select is not None:
            self.timeline.selected_id = select(result)
        self.after_edit(label)
        return result

    def after_edit(self, label):
        self.dirty = True
        self._place_dropped_layers()
        self._centre_dropped()
        self._place_into_group()
        self.meter.set_gain(self.proj.get("master_gain", 1.0))
        try:
            self.container()
        except (edit.EditError, KeyError):               # an undo (or a delete) removed an open compound
            self.path_ids = []
        sel, ids = self.timeline.selected_id, set(self.timeline.selected_ids)
        self.timeline.set_project(self.view(), keep_view=True)
        there = {c["id"] for c in self.timeline.level_clips()}          # (those inside groups too)
        alive = there - self.timeline.locked_ids()
        if sel and sel not in alive and sel in there:
            sel = next(iter(sorted(ids & alive)), None)  # (a track just locked lets go of its clips)
        self.timeline.selected_id = sel
        if sel:                                          # keep a multiple selection too
            self.timeline.selected_ids = (ids & alive) | {sel}
        self.timeline.update()
        self.refresh_library()
        self._update_title()
        self._update_crumb()
        self._update_buttons()
        self.refresh_inspector()
        self.show_rack()
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
        starts = edit.abs_starts(self.container())
        targets = [k for k in (sel and [self.placed(k, starts) for k in sel] or [k for tr in self.container()["tracks"]
                                                                       for k in tr["clips"]])
                   if k["start_us"] < t < k["start_us"] + k["duration_us"]]
        if not targets:
            self.statusBar().showMessage("播放頭下沒有片段", 3000)
            return
        ids = [k["id"] for k in targets]

        def split_all(level):
            for cid in ids:
                edit.split(level, cid, t)

        self.apply("分割", split_all)

    def do_trim_to_playhead(self, side):
        """Q / W (向左 / 向右裁剪, as in Jianying): the selected clips - or, none selected, every
        clip under the playhead - lose what is before / after the playhead."""
        if not self.proj:
            return
        ids = [c["id"] for c in self.timeline.selected_clips()] or [
            k["id"] for tr in self.container()["tracks"] if not project.locked(tr) for k in tr["clips"]]
        self.apply("向左裁剪" if side == "start" else "向右裁剪", edit.trim_to, ids, self.playhead_us(), side)

    def do_ripple_delete(self):
        """Shift+Delete: the selected clips go and the later clips of their tracks close up."""
        ids = [c["id"] for c in self.timeline.selected_clips()]
        if not ids:
            self.do_delete()                             # (tracks picked by their headers)
            return
        self.timeline.selected_id = None
        self.apply("波紋刪除", edit.ripple_delete, ids)

    def do_rename(self):
        """F2: rename what has the keyboard focus (an item of a panel's list), else the selected
        clip, else the one track picked by its header."""
        w = QApplication.focusWidget()
        while w is not None and not hasattr(w, "rename_current"):
            w = w.parentWidget()
        if w is not None and w.rename_current():
            return
        if not self.proj:
            return
        tl = self.timeline
        if tl.selected is not None:
            self.on_clip_action("rename", tl.selected["id"])
        elif len(tl.selected_tracks) == 1:
            self.on_track_action("rename", next(iter(tl.selected_tracks)))
        else:
            self.statusBar().showMessage("先選取要重新命名的片段或軌道", 3000)

    def do_make_compound(self):
        """Alt+G: the selected clips into a new compound clip."""
        ids = sorted(self.timeline.selected_ids)
        if not self.proj or not ids:
            self.statusBar().showMessage("先在時間軸上選取片段", 3000)
            return
        self.on_clip_action("make_compound", ids[0])

    def do_delete(self):
        if self.timeline.selected_tracks and not self.editing_static():     # tracks picked by their headers
            self.delete_tracks([t["id"] for t in self.timeline.rows if t["id"] in self.timeline.selected_tracks])
            return
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

    def do_snap_beats(self):
        """Alt+Q: the selected clips' starts and ends trimmed to the nearest beats."""
        ids = [c["id"] for c in self.timeline.selected_clips()]
        if not self.proj or not ids:
            self.statusBar().showMessage("先在時間軸上選取片段", 3000)
            return
        self.apply("頭尾對齊拍子", edit.snap_to_beats, ids)

    def do_shuffle(self):
        """Alt+R: the selected clips in a random order (each track's run of them)."""
        ids = [c["id"] for c in self.timeline.selected_clips()]
        if not self.proj or len(ids) < 2:
            self.statusBar().showMessage("先在時間軸上選取兩個以上的片段", 3000)
            return
        self.apply("打亂順序", edit.shuffle_clips, ids)

    def do_reverse_rows(self):
        """反轉排序: the selected clips' tracks the other way up (edit.reverse_rows)."""
        ids = [c["id"] for c in self.timeline.selected_clips()]
        if not self.proj or not edit.can_reverse_rows(self.container(), ids):
            self.statusBar().showMessage("先選取上下疊在一起（兩條以上軌道）的片段", 3000)
            return
        self.apply("反轉排序", edit.reverse_rows, ids)

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
        if questions.question(self, "delete_compound", "刪除複合片段", msg):
            self.timeline.selected_id = None
            self.apply_root("刪除複合片段", lambda root: edit.delete_compound(root, kid, force=True))

    def clone_compound_item(self, kid):
        """From the compound list: a copy of a timeline, or of a compound as one of its own."""
        if kid.startswith("tl"):
            self.timeline_do("duplicate", kid)
        else:
            self.apply_root("建立副本", edit.clone_compound, kid)

    def create_from_panel(self, kind):
        """From the compound list's menu: a new timeline, or a new empty compound / static
        compound, opened by itself to be filled (drag it onto a timeline to use it)."""
        if not self.proj:
            return
        if kind == "timeline":
            self.apply_root("新增時間線", edit.add_timeline)
            return
        component = kind in ("component", "static_component")
        static = kind in ("static", "static_component")
        label = "新增" + edit.kind_name(static, component)
        dlg = CompoundSizeDialog(self, edit.new_name(self.proj.get("compounds", {}), static, component),
                                 self.proj["width"], self.proj["height"], static, label)
        if dlg.exec() != QDialog.Accepted:
            return
        name, size = dlg.result()

        def make(root):
            kid = edit.add_compound(root, static, size, component)
            if name:
                root["compounds"][kid]["name"] = name
            return kid
        kid = self.apply_root(label, make)
        if kid:
            self.open_compound_entry(kid)

    def component_kind(self, kid, on):
        """Make a compound a component (元件), or a component a plain compound again (asking
        first when clips have set its parameters: those values go)."""
        if on:
            self.apply_root("轉為元件", edit.make_component, kid)
            return
        label = "轉回" + edit.kind_name(self.proj["compounds"][kid].get("static"))
        n = sum(1 for _tl, _p, c in project.compound_uses(self.proj).get(kid) or [] if c.get("params"))
        if n and not questions.question(self, "unmake_component", label, f"有 {n} 個片段自己設定了這個元件的參數，"
                                  f"{label}後這些設定會消失。要繼續嗎？"):
            return
        self.apply_root(label, edit.unmake_component, kid)

    def compound_to_static(self, kid):
        """轉為靜態複合片段 (or 靜態元件): a compound whose content all lasts its whole length."""
        self.apply_root(static_label(self.proj["compounds"][kid]), edit.to_static, kid)

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
        times = self.key_times(ids)
        return self.apply_each(label, lambda lvl, cid, *a: fn(lvl, cid, *a, times[cid]), ids, *args)

    def on_text_edited(self, ids, fields):
        self.apply_each("修改文字", lambda lvl, cid: edit.set_text(lvl, cid, **fields), ids,
                        merge=("text", tuple(ids), tuple(sorted(fields))))

    def clip_time(self, cid, starts=None):
        """Playhead time relative to the start of clip cid (a group's clip: counted from where
        it is on the timeline). starts: edit.abs_starts of the open level, when at hand."""
        s = starts.get(cid) if starts is not None else None
        return edit.time_in(self.playhead_us(), s if s is not None else edit.abs_start(self.container(), cid), self.fps)

    def clip_times(self, ids):
        """{clip id: clip_time} for several clips (one pass over the level)."""
        starts = edit.abs_starts(self.container())
        return {cid: self.clip_time(cid, starts) for cid in ids}

    def placed(self, c, starts=None):
        """Clip c as the panels see it: a group's clip with its start on the timeline (a
        shallow copy; its parameters are its own)."""
        if c is None:
            return None
        if starts is None:
            starts = edit.abs_starts(self.container())
        s = starts.get(c["id"])
        return c if s is None or s == c["start_us"] else dict(c, start_us=s)

    def on_param_edited(self, ids, group, key, value):
        """A value typed in the inspector: set on every selected clip (each at its own
        playhead time, so keyframed ones get or edit the keyframe there)."""
        label = ("調整效果" if group.startswith("fx") else "調整素材" if group == "asset" else
                 "調整元件參數" if group == "params" else "調整" + self.PARAM_LABELS.get((group, key), "遮罩"))
        times = self.key_times(ids)
        self.apply_each(label, lambda lvl, cid: edit.set_param(lvl, cid, group, key, value, times[cid]), ids,
                        merge=("param", tuple(ids), group, key, round(times[ids[0]])))

    def on_key_toggled(self, ids, group, key):
        """◆ (批量): when every clip it reaches has a keyframe there, remove them; else add the
        missing ones. One of a multi-selection reaches every selected clip with that
        parameter (key_targets), each at its key_times time."""
        targets = self.key_targets(ids, group, key)
        times = self.key_times([cid for cid, _g in targets])
        level = self.container()
        targets = [(cid, g) for cid, g in targets
                   if 0 <= times[cid] <= edit.find(level, cid)[1]["duration_us"]]
        if not targets:
            self.statusBar().showMessage("播放頭不在選取的片段上", 3000)
            return

        def has(cid, g):
            c = edit.find(self.container(), cid)[1]
            return edit.key_at(group_holder(c, g).get(key), times[cid]) is not None

        todo = targets if all(has(*x) for x in targets) else [x for x in targets if not has(*x)]

        def toggle_all(lvl):
            for cid, g in todo:
                edit.toggle_key(lvl, cid, g, key, times[cid])

        self.apply("關鍵幀" + (f"（{len(todo)} 個片段）" if len(todo) > 1 else ""), toggle_all)
        self.curves.select_param(group, key)

    def add_key_at_playhead(self, cid, params):
        """The curve editor's "add here": a keyframe holding the current value, for every
        shown parameter that has none there - in every selected clip with that parameter
        when cid is one of a multi-selection (批量, as ◆)."""
        level = self.container()
        todo = []
        for g, k in params:
            targets = self.key_targets([cid], g, k)
            times = self.key_times([c_id for c_id, _g in targets])
            for c_id, cg in targets:
                c = edit.find(level, c_id)[1]
                t = times[c_id]
                if 0 <= t <= c["duration_us"] and edit.key_at(group_holder(c, cg).get(k), t) is None:
                    todo.append((c_id, cg, k, t))
        if not todo:
            self.statusBar().showMessage("播放頭上已經有關鍵幀", 2000)
            return

        def add_all(level):
            for c_id, g, k, t in todo:
                edit.toggle_key(level, c_id, g, k, t)

        n = len({x[0] for x in todo})
        self.apply("關鍵幀" + (f"（{n} 個片段）" if n > 1 else ""), add_all)

    def key_targets(self, ids, group, key):
        """[(clip id, its group)] that a ◆ of group / key on clips ids reaches: those, and when
        the first is one of a multi-selection every other selected clip too (批量) - each
        that has the parameter (a filter's: the same filter at the same place, same_group)."""
        level = self.container()
        try:
            first = edit.find(level, ids[0])[1]
        except edit.EditError:
            return []
        sel = self.timeline.selected_ids
        every = list(ids) + ([i for i in sorted(sel) if i not in ids] if ids[0] in sel else [])
        out = []
        for cid in every:
            try:
                c = edit.find(level, cid)[1]
            except edit.EditError:
                continue
            g = same_group(first, c, group)
            if g is not None and edit.has_param(c, g, key):
                out.append((cid, g))
        return out

    def key_times(self, ids):
        """{clip id: the clip time a keyframe edit of it uses}: where the playhead is, for a clip
        it is over; for one it is not over (批量: copies spread along the timeline), as far
        from its start as the playhead is from the start of the main selected clip (or, when
        the playhead is not over that one, the first selected clip it is over), when that
        falls inside it."""
        if not ids:
            return {}
        level = self.container()
        starts = edit.abs_starts(level)
        durs = {c["id"]: c["duration_us"] for t in project.all_tracks(level["tracks"]) for c in t["clips"]}
        ref = None
        for c in self.timeline.selected_clips_primary_first():
            own = self.clip_time(c["id"], starts)
            if 0 <= own <= c["duration_us"]:
                ref = own
                break
        out = {}
        for cid in ids:
            own = self.clip_time(cid, starts)
            dur = durs.get(cid)
            if dur is None:
                out[cid] = own
                continue
            out[cid] = ref if not 0 <= own <= dur and ref is not None and 0 <= ref <= dur else own
        return out

    def seek_clip_time(self, t):
        c = self.placed(self.timeline.selected)
        if c is not None:
            self.seek(round((c["start_us"] + t) / US * self.fps))

    def on_curve_keys(self, cid, changes, final):
        """Curve editor edits ([(group, key, keys, value if no keys are left)]): shown live
        while dragging, one undo step when released. With 一起修改 (批量) the alike keyframes
        of the other selected clips change with them."""
        every = [(cid, *ch) for ch in changes] + self.curve_batch(cid, changes)
        if final:
            def set_all(level):
                for c_id, g, k, keys, keep in every:
                    if keys:
                        edit.set_keys(level, c_id, g, k, keys)
                    else:
                        edit.clear_keys(level, c_id, g, k, keep)

            n = len({e[0] for e in every}) - 1
            label = "刪除關鍵幀" if all(not ch[2] for ch in changes) else "編輯曲線"
            self.apply(label + (f"（另 {n} 個片段）" if n else ""), set_all)
            return
        view = self.snapshot()
        by_id = {}
        for c_id, g, k, keys, keep in every:
            by_id.setdefault(c_id, []).append((g, k, keys, keep))
        for tr in project.all_tracks(view["tracks"]):
            for c in tr["clips"]:
                for g, k, keys, keep in by_id.get(c["id"], ()):
                    group_holder(c, g, create=True)[k] = {"keys": keys} if keys else keep
        self.player.worker.set_view(view, self.cache_dir())

    def _batch_clips(self, cid):
        """(clip cid, [the other selected clips]) of the open level, for 批量."""
        clips = {k["id"]: k for t in project.all_tracks(self.container()["tracks"]) for k in t["clips"]}
        if cid not in clips:
            return None, []
        return clips[cid], [clips[oid] for oid in sorted(self.timeline.selected_ids - {cid}) if oid in clips]

    def _alike(self, c, others, g, k):
        """[(other clip, its group, its curve)] of others with keyframes on the parameter g / k
        of clip c, and c's curve (None when c's is not animated)."""
        mine = group_holder(c, g).get(k)
        if not curves.is_animated(mine):
            return None, []
        out = []
        for o in others:
            og = same_group(c, o, g)
            p = group_holder(o, og).get(k) if og else None
            if curves.is_animated(p):
                out.append((o, og, p))
        return mine, out

    def curve_batch(self, cid, changes):
        """批量: the curve editor's edit of clip cid done to the alike keyframes of the other
        selected clips (keybatch.carry; a typed value is set on them):
        [(clip id, group, key, keys, value if none are left)]."""
        if not self.curves.batch_on():
            return []
        c, others = self._batch_clips(cid)
        out = []
        for g, k, keys, _keep in (changes if c else ()):
            mine, theirs = self._alike(c, others, g, k)
            for o, og, p in theirs:
                r = keybatch.carry(mine["keys"], keys, p["keys"], self.proj["fps"], o["duration_us"], edit.KEY_TOL_US,
                                   self.curves.typing)
                if r is not None:
                    out.append((o["id"], og, k, r[0], r[1] if r[1] is not None else curves.value(p, 0)))
        return out

    def curve_links(self, sel):
        """批量, for the curve editor: (other clips selected, those with keyframes alike sel's,
        {(group, key): {sel's key index: how many clips have an alike one}})."""
        if sel is None or len(self.timeline.selected_ids) < 2:
            return 0, 0, {}
        c, others = self._batch_clips(sel["id"])
        if c is None:
            return 0, 0, {}
        links, linked = {}, set()
        for g, k, *_ in curve_param_rows(c):
            mine, theirs = self._alike(c, others, g, k)
            for o, _og, p in theirs:
                for i in keybatch.match(mine["keys"], p["keys"], self.proj["fps"]):
                    links.setdefault((g, k), {}).setdefault(i, 0)
                    links[(g, k)][i] += 1
                    linked.add(o["id"])
        return len(others), len(linked), links

    def show_selection_props(self):
        starts = edit.abs_starts(self.container()) if self.proj else {}
        clips, t = [self.placed(c, starts) for c in self.timeline.selected_clips_primary_first()], self.playhead_us()
        times = self.key_times([c["id"] for c in clips])
        if self.proj is not None and any(c.get("viz") for c in clips):       # (what an Audio Visualizer can listen to)
            self.inspector.set_sound_tracks([(tr["id"], tr.get("name") or tr["id"])
                                             for tr in reversed(self.container()["tracks"]) if self.sound_track(tr)])
            self.inspector.set_compounds(self.mask_compounds())
        self.inspector.show_clips(clips, t, self.fps, [times[c["id"]] for c in clips])
        if self.proj is not None:
            self.effects.set_media(self.mask_images(), self.mask_videos(), self.mask_compounds(), self.mask_tracks())
            self.nodes.set_media(self.mask_images(), self.mask_videos(), self.mask_compounds(), self.mask_tracks())
        self.effects.show_clips(clips, t, self.fps)
        if self.proj is not None:
            self.mask_panel.set_compounds(self.mask_compounds())
            self.mask_panel.set_images(self.mask_images())
            self.mask_panel.set_videos(self.mask_videos())
            self.mask_panel.set_tracks(self.mask_tracks())
            self.inspector.set_images(self.mask_images())          # (a component's picture parameters)
        self.mask_panel.show_clips(clips, t, self.fps)
        self.nodes.show_clip(clips[0] if len(clips) == 1 else None, t=times[clips[0]["id"]] if len(clips) == 1 else 0)
        self.beats.show_clips(clips)
        self.subtitles.show_selection(self.timeline.rows, self.timeline.selected_ids)
        self._update_side_tabs(clips)

    def _update_side_tabs(self, clips):
        """The side panels a selection has use for (屬性 always): 效果 for pictures, texts and
        filters, 遮罩 for what takes a mask, 節拍 for one clip with sound, 字幕 for texts,
        關鍵幀曲線 for any clip. One in tabs leaves them (they go on to another one), one on
        its own says it has nothing to show (docks.Panels.set_usable)."""
        show = {"fx": bool(clips) and all(c["type"] in edit.VISUAL for c in clips),
                "mask": bool(clips) and all(c["type"] in edit.MASKABLE for c in clips),
                "beat": len(clips) == 1 and edit.has_sound(clips[0]),
                "subtitle": any(c["type"] == "text" for c in clips),
                "curves": bool(clips),
                "nodes": len(clips) == 1 and any(e.get("filter") == fx.GRAPH for e in clips[0].get("effects") or [])}
        for key, dock in (("nodes", "nodes"), ("fx", "effects"), ("mask", "mask"), ("beat", "beats"), ("subtitle", "subtitles"),
                          ("curves", "curves")):
            self.panels.set_usable(dock, show[key])
        self._update_library_tabs()

    def _update_library_tabs(self):
        """The project's VFX Nodes and compounds: their tabs are there only while the project has some (appearing when the first is
        made, going when the last is deleted - docks.Panels.set_usable), and the panels that name VFX Nodes know them."""
        p = self.proj
        nodes = [(vid, m["name"]) for vid, m in (p.get("vfx_nodes") or {}).items()] if p else []
        self.vfxnodes.set_project(p, project.vfx_uses(p) if p else {})
        self.effects.set_vfx_nodes(nodes)
        self.nodes.vfx_names = dict(nodes)
        panels = getattr(self, "panels", None)
        if panels is not None:
            panels.set_usable("vfxnodes", bool(nodes))
            panels.set_usable("compounds", bool(p and p.get("compounds")))

    def on_easing(self, ids, easing, groups):
        """Apply a curve preset to every parameter (of these groups) with a keyframe at the playhead."""
        times = self.key_times(ids)

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

    def jump_edit(self, d):
        """↑ / ↓ (as in Jianying): the playhead to the clip start or end before / after it, of
        any clip of the open level."""
        if not self.proj:
            return
        pts = {0}
        for c in self.timeline.level_clips():
            s = self.placed(c)["start_us"]
            pts |= {round(s / US * self.fps), round((s + c["duration_us"]) / US * self.fps)}
        pts = {min(f, max(0, self.length - 1)) for f in pts}
        cands = [f for f in pts if (f > self.pos if d > 0 else f < self.pos)]
        if not cands:
            self.statusBar().showMessage("沒有更多剪輯點", 2000)
            return
        self.seek(min(cands) if d > 0 else max(cands))

    def jump_key(self, direction):
        c = self.timeline.selected
        if c is None:
            self.statusBar().showMessage("先在時間軸上選取片段", 2000)
            return
        t = self.clip_time(c["id"])
        times = edit.key_times(c)
        cands = [k for k in times if (k > t + edit.KEY_TOL_US if direction > 0 else k < t - edit.KEY_TOL_US)]
        if not cands:
            self.statusBar().showMessage("沒有更多關鍵幀", 2000)
            return
        k = min(cands) if direction > 0 else max(cands)
        self.seek(round((self.placed(c)["start_us"] + k) / US * self.fps))

    def on_mask_kind(self, ids, kind):
        self.apply_each_timed("遮罩" if kind else "移除遮罩", edit.set_mask, ids, kind)

    def on_preview_params(self, cid, group, values):
        """A drag of the clip or its mask on the canvas: one edit (keyframed values get or
        edit their keyframe at the playhead)."""
        t = self.clip_time(cid)
        if group == "mask" or group.startswith("fxmask:"):
            label = "遮罩"
        elif group.startswith("place:"):
            label = "圖片位置"
        elif group.startswith("fxsrc:"):
            label = "效果來源位置"
        elif group == "multi":                          # a built-in asset or a 文字框 resized: size and place
            label = "調整大小"
        else:
            label = "旋轉" if "rotation" in values else "縮放" if "scale" in values else \
                "中心點" if "pivot_x" in values else "錨點" if "anchor_x" in values else "移動位置"

        def set_all(level):
            for g, vals in (values.items() if group == "multi" else [(group, values)]):
                for key, v in vals.items():
                    edit.set_param(level, cid, g, key, v, t)

        self.apply(label, set_all)

    def on_preview_moves(self, moves):
        """Several clips dragged together on the canvas ({clip id: {x, y}}): one edit."""
        times = self.clip_times(moves)

        def set_all(level):
            for cid, vals in moves.items():
                for key, v in vals.items():
                    edit.set_param(level, cid, "transform", key, v, times[cid])

        self.apply("移動位置", set_all)

    def pick_in_group(self, c):
        """A clip inside a group picked on the canvas: its groups open on the timeline, it is selected."""
        level = self.container()
        try:
            t, _ = edit.find(level, c["id"])
            g = edit.group_of(level, t)
            while g is not None:
                self.timeline.open_groups.add(g["id"])
                g = edit.group_of(level, edit.find(level, g["id"])[0])
        except edit.EditError:
            return
        self.timeline._layout()
        self.timeline.select(c)

    def pivot_units(self, c, t):
        """(x, y): half-canvas units of 中心點 that are one width / height of clip c's picture (at scale 1, clip time
        t) - the inspector shows the pivot in those, 0 the centre, ±0.5 the edges."""
        W, H = self.preview.W, self.preview.H
        bw, bh = preview_base_size(c, W, H, t)
        return (W / 2) / max(bw, 1e-6), (H / 2) / max(bh, 1e-6)

    def editing_static(self):
        """Whether the open level is a static compound (edited as layers)."""
        try:
            steps = walk_path(self.proj, self.path_ids) if self.proj else []
        except (edit.EditError, KeyError):
            return False
        return bool(steps) and bool(steps[-1][1].get("static"))

    def open_kid(self):
        """The id of the open compound (None: a timeline is open)."""
        try:
            steps = walk_path(self.proj, self.path_ids) if self.proj else []
        except (edit.EditError, KeyError):
            return None
        return steps[-1][2] if steps else None

    def number_menu(self, menu, ids, prop):
        """What a number's right-click menu adds (the inspector's, the mask panel's, a filter's): 表達式,
        a global parameter of the rack (or a new one made from its value), and in a component its parameters."""
        if not self.proj:
            return
        try:
            c = edit.find(self.container(), ids[0])[1]
        except edit.EditError:
            return
        if prop not in components.number_props_of(c) + components.instance_props(c):
            return
        menu.addSeparator()
        have = (c.get("expr") or {}).get(prop)
        sub = menu.addMenu("綁定全局參數")
        sub.addAction("新增全局參數並綁定…", lambda: self.new_rack_and_bind(ids, prop))
        names = [p["name"] for p in rack.params(self.proj)]
        if names:
            sub.addSeparator()
        for n in names:
            sub.addAction(n, lambda n=n: self.bind_rack(ids, prop, n))
        if mapping.is_mapping(have) and have.get("src"):
            menu.addAction(f"映射…（{mapping.label(have)}）", lambda: self.bind_rack(ids, prop, have["src"]))
        menu.addAction("自訂表達式…", lambda: self.ask_prop_expr(ids, prop))
        if have:
            menu.addAction("解除綁定／清除表達式", lambda: self.apply_each("清除表達式", edit.set_prop_expr, ids, prop, ""))
        comp = self.open_component()
        if comp is not None and not prop.startswith("params."):
            sub = menu.addMenu("設為元件參數")
            sub.addAction("新參數", lambda: self.layer_param_bind("", prop, ids))
            nums = [p for p in components.params(comp) if p["kind"] == "number"]
            if nums:
                sub.addSeparator()
            for p in nums:
                sub.addAction(f"交給「{p['name']}」", lambda pid=p["id"]: self.layer_param_bind(pid, prop, ids))
            mine = [(cid, p) for cid in ids for p, pr in components.bound(comp).get(cid, ()) if pr == prop]
            if mine:
                menu.addAction("解除元件參數「" + "、".join(dict.fromkeys(p["name"] for _c, p in mine)) + "」",
                               lambda: self.unbind_params([(cid, prop) for cid in ids]))

    def field_range(self, c, prop):
        """(lo, hi) a number usually runs between: what its field drags across (a mapping's output at first)."""
        from .inspector import PARAMS
        g, k = prop.split(".", 1)
        for r in PARAMS.get(g, ()):
            if r[0] == k:
                return float(r[2]), float(r[3])
        try:
            if g == "asset":
                info = assets.FIELD_INFO[k]
                return float(info[2]), float(info[3])
            if g.startswith("fx:"):
                e = next(e for e in c.get("effects") or [] if e["id"] == g[3:])
                q = next(q for q in fx.def_of(e).params if q.name == k)
                return float(q.lo), float(q.hi)
        except (KeyError, StopIteration, IndexError, TypeError):
            pass
        return 0.0, 100.0

    def bind_rack(self, ids, prop, name):
        """綁定全局參數: the number follows rack parameter `name`, through a 映射 asked for now."""
        c = edit.find(self.container(), ids[0])[1]
        have = (c.get("expr") or {}).get(prop)
        m = have if mapping.is_mapping(have) and have.get("src") == name else mapping.make(src=name)
        vals = rack.values(self.proj, self.playhead_us())
        out = mapdialog.ask_mapping(self, f"綁定：{components.prop_label(c, prop)}", m, f"全局參數「{name}」",
                                    vals.get(name), vals, self.field_range(c, prop))
        if out is not None:
            self.apply_each("綁定全局參數", edit.set_prop_expr, ids, prop, out)

    def new_rack_and_bind(self, ids, prop):
        """新增全局參數並綁定: a rack parameter with the number's value now, and the number follows it."""
        c = edit.find(self.container(), ids[0])[1]
        t = self.key_times(ids)[ids[0]]
        cur = components.number_at(c, prop, t)
        taken = {p["name"] for p in rack.params(self.proj)}
        name, k = "param", 1
        while f"{name}{k}" in taken:
            k += 1
        name, ok = QInputDialog.getText(self, "新增全局參數", "名稱（在表達式裡直接寫它；英文字母、數字、_）：", text=f"{name}{k}")
        name = name.strip()
        if not ok or not name:
            return
        why = rack.name_problem(self.proj, name)
        if why:
            self.statusBar().showMessage(why, 5000)
            return

        out = mapdialog.ask_mapping(self, f"綁定：{components.prop_label(c, prop)}", mapping.make(src=name),
                                    f"新的全局參數「{name}」", cur, {name: cur}, self.field_range(c, prop))
        if out is None:
            return

        def fn(root):
            edit.add_rack_param(root, name, cur)
            level = self.container(root)
            for cid in ids:
                edit.set_prop_expr(level, cid, prop, out)
        self.apply_root("新增全局參數並綁定", fn)

    def ask_prop_expr(self, ids, prop):
        """表達式…: the expression a clip's number follows, asked for now (on every clip selected)."""
        c = edit.find(self.container(), ids[0])[1]
        label = components.prop_label(c, prop)
        text = exprdialog.ask_expression(
            self, f"表達式：{label}", (c.get("expr") or {}).get(prop, ""),
            {"value": components.number_at(c, prop, 0), "time": 0.0, "progress": 0.0, "duration": 1.0,
             **rack.values(self.proj, self.playhead_us())},
            default="value",
            note="value 是這個數字原本的值（關鍵幀的結果）；time 是片段內的秒數、progress 是 0–1 的進度；"
                 "全局參數直接寫名字。例：value + wiggle(2, 30)、100 * Math.abs(Math.sin(time))。")
        if text is not None:
            self.apply_each("表達式", edit.set_prop_expr, ids, prop, "" if text == "value" else text)

    # -- the parameter rack (全局參數架) ---------------------------------------------------------
    def open_rack(self):
        """工具 > 全局參數架: the panel, brought to the front."""
        self.panels.show("rack")
        self.show_rack()

    def show_rack(self):
        """Keep the rack panel in step with the project and the playhead."""
        if self.proj and self.panels["rack"].isVisible():
            self.rack_panel.fill(self.proj, self.playhead_us())

    def add_rack_param(self):
        name, ok = QInputDialog.getText(self, "新增全局參數", "名稱（在表達式裡直接寫它；英文字母、數字、_）：")
        if ok and name.strip():
            self.apply_root("新增全局參數", edit.add_rack_param, name, 0.0)

    def on_rack_action(self, rid, action, arg):
        p = rack.find(self.proj, rid)
        if p is None:
            return
        t = self.playhead_us()
        if action == "value":
            self.apply_root("調整全局參數", edit.set_rack_value, rid, arg, t, merge=("rack", rid, round(t)))
        elif action == "key":
            self.apply_root("全局參數關鍵幀", edit.toggle_rack_key, rid, t)
        elif action == "easing":
            self.apply_root("全局參數曲線", edit.set_rack_easing, rid, t, arg)
        elif action in ("up", "down"):
            self.apply_root("全局參數順序", edit.move_rack_param, rid, -1 if action == "up" else 1)
        elif action == "rename":
            name, ok = QInputDialog.getText(self, "重新命名全局參數", "名稱：", text=p["name"])
            if ok and name.strip() != p["name"]:
                self.apply_root("重新命名全局參數", edit.rename_rack_param, rid, name)
        elif action == "expr":
            others = {q["name"]: v for q, v in ((q, rack.values(self.proj, t).get(q["name"], 0.0))
                                                 for q in rack.params(self.proj)) if q is not p}
            text = exprdialog.ask_expression(
                self, f"表達式：{p['name']}", p.get("expr", ""), {"input": float(curves.value(p.get("value", 0.0), t)),
                                                                 "time": t / US, **others},
                note="input 是這個參數自己的值；time 是時間線的秒數；其他全局參數直接寫名字（不能繞一圈讀回自己）。")
            if text is not None:
                self.apply_root("全局參數表達式", edit.set_rack_expr, rid, "" if text == "input" else text)
        elif action == "delete":
            n = rack.users(self.proj, p["name"])
            if n and not questions.question(self, "delete_rack", "刪除全局參數", f"有 {n} 個片段的表達式用到「{p['name']}」，"
                                            "刪除後它們會讀不到這個名字（數字維持原樣）。要繼續嗎？"):
                return
            self.apply_root("刪除全局參數", edit.delete_rack_param, rid)

    def import_rack(self):
        path, _ = QFileDialog.getOpenFileName(self, "匯入全局參數", self.app_root(), "全局參數架 (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                items = rack.parse_import(fh.read())
        except (OSError, ValueError) as exc:
            self.statusBar().showMessage(f"匯入失敗：{exc}", 5000)
            return
        self.apply_root("匯入全局參數", edit.import_rack, items)

    def export_rack(self):
        if not rack.params(self.proj):
            self.statusBar().showMessage("還沒有全局參數可以匯出", 3000)
            return
        path, _ = QFileDialog.getSaveFileName(self, "匯出全局參數", os.path.join(self.app_root(), "參數架.json"),
                                              "全局參數架 (*.json)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(rack.export_text(self.proj))
            self.statusBar().showMessage(f"已匯出 {path}", 4000)

    def open_component(self):
        """The component being edited (its content), or None."""
        kid = self.open_kid()
        comp = self.proj["compounds"].get(kid) if kid and self.proj else None
        return comp if components.is_component(comp) else None

    def layer_param_expr(self, pid, cid, prop):
        """The 映射 a number parameter sets a layer's prop through, asked for now."""
        self.ask_bind_mapping(pid, [cid], prop)

    def ask_bind_mapping(self, pid, ids, prop):
        """映射: how component parameter pid's value becomes prop of layers ids (the first one's is shown)."""
        kid = self.open_kid()
        comp = self.open_component()
        p = components.param(comp, pid) if comp else None
        if p is None or p["kind"] != "number":
            return
        c = edit.find(comp, ids[0])[1]
        have = components.expr_of(p, ids[0], prop)
        if mapping.is_mapping(have):
            m = have
        elif have != "input":                              # (an expression written before: as it was)
            m = mapping.make(mode="js", js=have)
        else:
            m = mapping.make()
        cur = components.default(comp, p)
        out = mapdialog.ask_mapping(self, f"映射：{p['name']} → {components.prop_label(c, prop)}", m,
                                    f"元件參數「{p['name']}」", cur, {}, self.field_range(c, prop))
        if out is not None:
            self.apply_root("參數映射", lambda root: [edit.set_bind_expr(root, kid, pid, cid, prop, out) for cid in ids])

    def unbind_params(self, binds):
        if self.open_kid():
            self.apply_root("解除參數", edit.unbind_param, self.open_kid(), binds)

    def layer_param_bind(self, pid, prop, ids):
        """設為參數: prop of layers ids set by parameter pid, or ("") by a new one (named now)."""
        kid = self.open_kid()
        comp = self.proj["compounds"].get(kid) if kid else None
        if not components.is_component(comp):
            return
        binds = [(cid, prop) for cid in ids]
        if pid:
            self.apply_root("設為參數", edit.bind_param, kid, pid, binds)
        else:
            c = edit.find(comp, ids[0])[1]
            label = components.prop_label(c, prop)
            name, ok = QInputDialog.getText(self, "新參數", "參數名稱：",
                                            text=label if len(ids) > 1 else f"{clip_name(c)} {label}")
            if not ok:
                return
            made = self.apply_root("新增參數", edit.add_param, kid, components.PROPS[prop][0], name, binds)
            pid = made["id"] if made else None
        if pid and components.prop_kind(prop) == "number":
            self.ask_bind_mapping(pid, ids, prop)

    def layer_param_action(self, action, pid):
        """The 參數 list: set a parameter's default, rename, restack or delete it."""
        kid = self.open_kid()
        comp = self.proj["compounds"].get(kid) if kid else None
        p = components.param(comp, pid)
        if p is None:
            return
        if action == "rename":
            name, ok = inplace.ask_name(self, p["name"])
            if ok:
                self.apply_root("重新命名參數", edit.rename_param, kid, pid, name)
        elif action in ("up", "down"):
            self.apply_root("參數順序", edit.move_param, kid, pid, -1 if action == "up" else 1)
        elif action == "delete":
            n = sum(1 for _tl, _p, c in project.compound_uses(self.proj).get(kid) or []
                    if pid in (c.get("params") or {}))
            if n and not questions.question(self, "delete_param", "刪除參數", f"有 {n} 個片段自己設定了「{p['name']}」，"
                                      "刪除後這些設定會消失。要繼續嗎？"):
                return
            self.apply_root("刪除參數", edit.delete_param, kid, pid)
        elif action == "default":
            v = components.default(comp, p)
            if p["kind"] == "text":
                v, ok = QInputDialog.getMultiLineText(self, p["name"], "預設的文字：", v)
            elif p["kind"] == "color":
                col = pick_color(self, qcolor(assets.hex_of(v)), p["name"])
                v, ok = (rgba(col), True) if col is not None else (None, False)
            elif p["kind"] == "number":
                v, ok = QInputDialog.getDouble(self, p["name"], "預設的值：", float(v), -1e9, 1e9, 4)
            elif p["kind"] == "image":
                v, _ = QFileDialog.getOpenFileName(self, p["name"], self.root or "",
                                                   "圖片 (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff *.svg)")
                v, ok = v.replace("\\", "/"), bool(v)
            else:
                v, ok = not v, True
            if ok:
                self.apply_root("參數預設值", edit.set_param_default, kid, pid, v)

    def param_default_dropped(self, pid, path):
        """A picture dropped on a picture parameter in the 參數 list: its new default."""
        kid = self.open_kid()
        if kid and components.param(self.proj["compounds"].get(kid), pid) is not None:
            self.apply_root("參數預設值", edit.set_param_default, kid, pid, path.replace("\\", "/"))

    def media_at(self, gp, kinds):
        """點選來源: what is under global point gp that a picker of kinds ("image", "video",
        "compound") can use - a picture's / video's path (or a compound's id) of a clip on the
        timeline, of 專案素材 or the Library, or of the compound list; None when nothing there."""
        w = QApplication.widgetAt(gp)
        while w is not None:
            if w is self.timeline:
                _row, c, _zone = w._hit(QPointF(w.mapFromGlobal(gp)))
                if c is None:
                    return None
                if c["type"] == "compound" and "compound" in kinds and c.get("compound_id"):
                    return c["compound_id"]
                if c["type"] in kinds and c.get("media") and not c.get("asset"):
                    return c["media"]["path"]
                return None
            if isinstance(w, QAbstractItemView):
                idx = w.indexAt(w.viewport().mapFromGlobal(gp))
                md = w.model().mimeData([idx]) if idx.isValid() else None
                return self._media_of(md, kinds) if md is not None else None
            w = w.parentWidget()
        return None

    def _media_of(self, md, kinds):
        """The first path / compound id of kinds that drag data md carries (as media_at)."""
        if not md.hasFormat(MEDIA_MIME):
            return None
        for iid in bytes(md.data(MEDIA_MIME)).decode("utf-8").split(","):
            if iid.startswith(COMPOUND_PREFIX):
                if "compound" in kinds:
                    return iid[len(COMPOUND_PREFIX):]
                continue
            if iid.startswith("mu"):
                it = self.ulib.find(iid)[1] if self.ulib else None
            else:
                it = next((i for i in library.lib(self.proj)["items"] if i["id"] == iid), None) if self.proj else None
            ext = os.path.splitext((it or {}).get("path") or "")[1].lower()
            kind = "image" if ext in library.IMAGE_EXT else "video" if ext in userlib.VIDEO_EXT else None
            if kind in kinds:
                return it["path"]
        return None

    def dropped_picture(self, md):
        """The picture a drag carries: a picture of the media library or of the user's Library,
        or a picture file from the file manager (the first one); None when it carries none."""
        is_pic = lambda path: bool(path) and os.path.splitext(path)[1].lower() in library.IMAGE_EXT
        if md.hasFormat(MEDIA_MIME):
            for iid in bytes(md.data(MEDIA_MIME)).decode("utf-8").split(","):
                if iid.startswith("mu"):
                    it = self.ulib.find(iid)[1] if self.ulib else None
                else:
                    it = next((i for i in library.lib(self.proj)["items"] if i["id"] == iid), None) if self.proj else None
                if it and is_pic(it.get("path")):
                    return it["path"]
            return None
        return next((path for path in dropped_paths(md) if is_pic(path) and os.path.isfile(path)), None)

    def _update_layers(self):
        """The layer panel in the timeline's place while a static compound is open."""
        static = self.editing_static()
        kid = self.open_kid()
        comp = self.proj["compounds"].get(kid) if kid and self.proj else None
        live = components.is_component(comp) and not static
        self.tl_params.setVisible(live)
        if live:
            self.tl_params.set_component(comp)
        self.lower_stack.setCurrentIndex(1 if static else 0)
        self.static_btn.setVisible(bool(comp) and not static and edit.steady(comp))
        if comp:
            self.static_btn.setText(static_label(comp))
        for k in ("split",):
            self.buttons[k].setVisible(not static)
        for b in self.transport:                        # nothing to play in one picture
            b.setVisible(not static)
        if static and self.player.worker.playing:
            self.player.worker.set_playing(False)
        self.preview.accept_media = static              # (the layers of a static compound: groups take drops)
        if static:
            self.layers.set_layers(self.container(), self.timeline.selected_ids, self.timeline.selected_id)

    def restack_layers(self, orders):
        """{group id or "": its layers' ids, top first}: restacked in one edit (those that changed)."""
        def fn(level):
            for parent, ids in orders.items():
                holder = edit.find(level, parent)[1] if parent else level
                if [c["id"] for c in edit.layers(holder)] != ids:
                    edit.set_layer_order(level, ids, parent or None)
        self.apply("圖層順序", fn)

    def layer_thumb(self, c, level):
        """A layer's small picture: the clip alone at the picture's moment (its own start when it
        is not there), on a checkerboard; kept until the clip (or what it shows) changes."""
        cache = self.__dict__.setdefault("_layer_thumbs", {})
        comps = self.proj.get("compounds", {})
        key = json.dumps([c, level["width"], level["height"], fonts.map_key()],   # (a compound clip holds
                         sort_keys=True, default=str)                             # what it shows)
        pix = cache.get(key)
        if pix is not None:
            return pix
        from .layers import THUMB_H
        dpr = self.devicePixelRatioF()
        bw, bh = round(THUMB_H * 16 / 9), THUMB_H
        k = min(bw / level["width"], bh / level["height"])
        w, h = max(2, round(level["width"] * k * dpr)), max(2, round(level["height"] * k * dpr))
        at = 0 if c["start_us"] <= 0 < c["start_us"] + c["duration_us"] else c["start_us"]
        view = {"width": level["width"], "height": level["height"], "fps": self.proj["fps"],
                "duration_us": at + 1, "tracks": [{"id": "_", "kind": "video", "clips": [c]}],
                "compounds": comps}
        if getattr(self, "_thumb_renderer", None) is None:     # (one for all: its pictures are decoded once)
            self._thumb_renderer = render.Renderer(self._thumb_video)
        try:
            img = self._thumb_renderer.render(view, at / US * self.proj["fps"], w, h, alpha=True)
        except Exception:
            return None
        finally:
            self._thumb_renderer.errors.clear()
        out = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        p = QPainter(out)
        cell = max(2, round(4 * dpr))
        for y in range(0, h, cell):
            for x in range(0, w, cell):
                p.fillRect(x, y, cell, cell, QColor("#3a3a40" if (x // cell + y // cell) % 2 else "#2a2a2f"))
        p.drawImage(0, 0, img)
        p.end()
        pix = QPixmap.fromImage(out)
        pix.setDevicePixelRatio(dpr)
        if len(cache) > 300:
            cache.clear()
        cache[key] = pix
        return pix

    def layer_action(self, action):
        """The layer panel's buttons."""
        level = self.container()
        ids = [c["id"] for t in project.all_tracks(level["tracks"]) for c in t["clips"]   # (inside groups too)
               if c["id"] in self.timeline.selected_ids]
        if action.startswith("into:"):
            self.move_into_group(ids, action[5:])
        elif action == "text":
            self.do_text()
        elif action == "delete":
            self.do_delete()
        elif action == "group":
            self.make_group(ids)
        elif action == "group_matte":
            self.toggle_group_matte(ids)
        elif action == "group_invert":
            self.toggle_group_matte(ids, "invert")
        elif action == "copy" and ids:                       # copies right above, at the same moment
            self._select_new(self.apply_root("複製圖層", lambda root: edit.duplicate_moved(
                root, self.container(root), ids, moves={})))
        elif action in ("up", "down") and ids:
            orders = {}                                       # each layer moves inside its own group
            step = -1 if action == "up" else 1
            for cid in ids:
                parent = edit.layer_parent(level, cid) or ""
                if parent not in orders:
                    holder = edit.find(level, parent)[1] if parent else level
                    orders[parent] = [c["id"] for c in edit.layers(holder)]
            for order in orders.values():
                for cid in [k for k in (order if step < 0 else reversed(order)) if k in ids]:
                    i = order.index(cid)
                    j = i + step
                    if 0 <= j < len(order) and order[j] not in ids:
                        order[i], order[j] = order[j], order[i]
            self.restack_layers(orders)

    def layer_drop(self, idents, paths, above, at=None, group=None):
        """Media dropped on the layer list (or the preview): new layers, `above` layers from the
        top (of the group's layers when group: they go into it), centred at transform position
        at (x, y) when given. They are placed as on the timeline (at the picture's moment, 0) and
        moved there when they come (_place_dropped_layers; files are imported first)."""
        if not self.proj:
            return
        self.layer_drop_at = (above, {c["id"] for c in edit.layers(self.container())}, time.monotonic(), at, group)
        if paths:
            self.drop_files(paths, self.library.current_folder(), ("", 0, False))
            return
        self._place_idents(idents, "", 0)
        self.layer_drop_at = None                        # (placed by now; only imports come later)

    def preview_drop(self, idents, paths, x, y, group):
        """Media dropped on the picture: layers of a static compound, else clips at the playhead
        (as dropped on the timeline there), centred at transform position x, y."""
        if not self.proj:
            return
        if self.editing_static():
            self.layer_drop(idents, paths, 0, (x, y), group or None)
            return
        before = {c["id"] for c in project.walk_clips(self.container()["tracks"])}
        self.centre_drop = (before, (x, y), time.monotonic())
        start = self.playhead_us()
        if paths:
            self.drop_files(paths, self.library.current_folder(), ("", start, False))
            return
        self._place_idents(idents, "", start)
        self.centre_drop = None                          # (placed by now; only imports come later)

    def _centre_dropped(self):
        """After an edit: clips that came from a drop on the picture are centred where it was."""
        pend = self.centre_drop
        if not pend or self.editing_static():
            return
        before, (x, y), when = pend
        if time.monotonic() - when > 120:                # (an import that never came)
            self.centre_drop = None
            return
        new = [c for c in project.walk_clips(self.container()["tracks"]) if c["id"] not in before]
        if not new:
            return
        self.centre_drop = None
        for c in new:
            tf = c.get("transform")
            if tf is not None and not curves.is_animated(tf.get("x")) and not curves.is_animated(tf.get("y")):
                tf["x"], tf["y"] = x, y

    def _place_idents(self, idents, tid, start):
        """Media / assets / compounds by their drag idents, onto the level at start."""
        media = [i for i in idents if i.startswith("m")]
        if len(media) > 1:
            self.place_media_many(media, tid, start, False)
        else:
            for ident in idents:
                if ident.startswith("cmp:"):
                    self.place_compound(ident[4:], tid, start)
                elif ident.startswith((assets.PREFIX, "viz:", textpresets.PREFIX)):
                    self.place_asset(ident, tid, start)
                elif ident.startswith("m"):
                    self.place_media(ident, tid, start)

    def layers_into_group(self, ids, gid, order):
        """Layers dragged into a group in the layer list: moved in, then stacked as dropped."""
        if not self.proj:
            return

        def fn(root):
            level = self.container(root)
            out = edit.move_into_group(root, level, ids, gid)
            g = edit.find(level, gid)[1]
            have = [c["id"] for c in edit.layers(g)]
            want = [i for i in order if i in have]
            if sorted(want) == sorted(have) and want != have:
                edit.set_layer_order(level, want, gid)
            return out
        if self.apply_root("移入群組", fn) is not None:
            self.layers.opened.add(gid)
            self.timeline.open_groups.add(gid)
        self._update_layers()                            # (refused: the list as it was)

    def move_into_group(self, ids, gid, track_id=None, start_us=None):
        """移入群組: clips of the open level into one of its groups, one undo step."""
        ids = [i for i in ids if i != gid]
        if not self.proj or not ids:
            return
        if self.apply_root("移入群組", lambda root: edit.move_into_group(
                root, self.container(root), ids, gid, track_id or None, start_us)) is not None:
            self.timeline.open_groups.add(gid)
            self.layers.opened.add(gid)
            self.timeline._layout()
            self.timeline.update()

    def group_drop(self, idents, paths, gid, track_id, start):
        """Media dropped on an open group's lane: placed, then moved into the group there."""
        if not self.proj:
            return
        before = {c["id"] for c in project.walk_clips(self.container()["tracks"])}
        self.group_drop_at = (gid, track_id, start, before, time.monotonic())
        if paths:
            self.drop_files(paths, self.library.current_folder(), ("", start, False))
            return
        self._place_idents(idents, "", start)
        self.group_drop_at = None

    def _place_into_group(self):
        """After an edit: clips that came from a drop on a group's lane go into it."""
        pend = self.group_drop_at
        if not pend:
            return
        gid, tid, start, before, when = pend
        if time.monotonic() - when > 120:
            self.group_drop_at = None
            return
        level = self.container()
        new = [c["id"] for c in project.walk_clips(level["tracks"]) if c["id"] not in before]
        if not new:
            return
        self.group_drop_at = None
        try:                                             # (part of the same undo step)
            edit.move_into_group(self.proj, level, new, gid, tid, start)
        except edit.EditError as exc:
            self.statusBar().showMessage(f"沒有放進群組：{exc}", 5000)
            return
        self.timeline.open_groups.add(gid)

    def _place_dropped_layers(self):
        """After an edit: layers that came from a drop on the layer list go where it was."""
        pend = self.layer_drop_at
        if not pend or not self.editing_static():
            return
        above, before, when, at, group = pend
        if time.monotonic() - when > 120:                # (an import that never came)
            self.layer_drop_at = None
            return
        level = self.container()
        order = [c["id"] for c in edit.layers(level)]
        new = [cid for cid in order if cid not in before]
        if not new:
            return
        self.layer_drop_at = None
        old = [cid for cid in order if cid in before]
        i = min(above, len(old)) if not group else 0
        if order != old[:i] + new + old[i:]:             # (part of the same undo step)
            edit.set_layer_order(level, old[:i] + new + old[i:])
        for cid in new if at else ():                    # dropped on the preview: centred there
            tf = edit.find(level, cid)[1].get("transform")
            if tf is not None and not curves.is_animated(tf.get("x")) and not curves.is_animated(tf.get("y")):
                tf["x"], tf["y"] = at
        if group:                                        # into the group, `above` of its layers from its top
            try:
                edit.move_into_group(self.proj, level, new, group)
            except edit.EditError as exc:
                self.statusBar().showMessage(f"沒有放進群組：{exc}", 5000)
                return
            g = edit.find(level, group)[1]
            inner = [c["id"] for c in edit.layers(g) if c["id"] not in new]
            j = min(above, len(inner))
            edit.set_layer_order(level, inner[:j] + new + inner[j:], group)
            self.layers.opened.add(group)

    def layer_fx_drop(self, payload, cid, above):
        """An effect dropped on the layer list: onto the layer it landed on, or a filter layer
        between layers."""
        if cid:
            self.on_filter_dropped(payload, cid, "", 0)
            return
        top = edit.layers(self.container())[:1]
        if above == 0 and top and top[0]["type"] == "filter":      # on top of a filter layer already: stacked in it
            self.on_filter_dropped(payload, top[0]["id"], "", 0)
            return
        ref, effect, _src = dropped_fx(payload)
        self.layer_drop_at = (above, {c["id"] for c in edit.layers(self.container())}, time.monotonic(), None, None)
        self.add_filter_clip(ref, "", 0, effect)
        self.layer_drop_at = None

    def toggle_group_matte(self, ids, field="on"):
        """最下面的物件當遮罩 (field "on") or 反轉遮罩 ("invert") from a menu: on for the groups when
        any is off, else off."""
        groups = [c for c in (edit.find(self.container(), k)[1] for k in ids) if project.is_group(c)]
        if not groups:
            return
        on = not all((g.get("matte") or {}).get(field) for g in groups)
        name = {"on": "群組遮罩", "invert": "反轉遮罩"}[field]
        self.apply(name if on else "取消" + name,
                   lambda lvl: [edit.set_group_matte(lvl, g["id"], **{field: on}) for g in groups])

    def toggle_group_anchor(self, ids):
        """中心點跟隨最下層物件 from a menu: on for the groups when any is off, else off."""
        groups = [c for c in (edit.find(self.container(), k)[1] for k in ids) if project.is_group(c)]
        if not groups:
            return
        on = not all(g.get("anchor") for g in groups)
        self.apply("中心點跟隨最下層物件" if on else "取消中心點跟隨最下層物件",
                   lambda lvl: [edit.set_group_anchor(lvl, g["id"], on) for g in groups])

    def make_group(self, ids=None):
        """建立群組 (Ctrl+G): the selected picture clips into a new group, opened."""
        ids = ids if ids else sorted(self.timeline.selected_ids)
        if not self.proj or not ids:
            self.statusBar().showMessage("先選取要放進群組的片段", 3000)
            return
        g = self.apply_root("建立群組", lambda root: edit.make_group(root, self.container(root), ids),
                            select=lambda g: g["id"])
        if g:
            self.timeline.open_groups.add(g["id"])
            self.timeline._layout()
            self.timeline.update()

    def ungroup(self, gid=None):
        """解散群組 (Ctrl+Shift+G): the selected groups' clips back onto the level's tracks (gid:
        the group right-clicked - all the selected ones when it is one of them)."""
        if gid is not None and gid not in self.timeline.selected_ids:
            ids = [gid]
        else:
            ids = [c["id"] for c in self.timeline.selected_clips() if project.is_group(c)]
        if not self.proj or not ids:
            self.statusBar().showMessage("先選取群組", 3000)
            return
        self._select_new(self.apply_root("解散群組", lambda root: edit.ungroup_many(root, self.container(root), ids)))

    def on_freeze(self, ids, on, t):
        """凍結幀 switched, or its frame chosen (t: clip time, None: keep the one it has)."""
        level = self.container()

        def src(cid):
            c = edit.find(level, cid)[1]
            return None if t is None else project.source_time(dict(c, freeze=None), t)
        srcs = {cid: src(cid) for cid in ids}
        self.apply("凍結幀" if on else "取消凍結幀",
                   lambda lvl: [edit.set_freeze(lvl, cid, on, srcs[cid]) for cid in ids])

    def align_or_space(self, label, moves):
        """The align / spacing buttons: the selected clips go to moves (one edit)."""
        if not moves:
            return
        times = self.clip_times(moves)
        clips = {c["id"]: c for t in project.all_tracks(self.container()["tracks"]) for c in t["clips"]}
        moves = {cid: v for cid, v in moves.items() if any(
            abs(curves.value(clips[cid]["transform"].get(k, 0.0), times[cid]) - x) > 1e-6
            for k, x in v.items())}
        if moves:
            self.apply(label, lambda level: [edit.set_param(level, cid, "transform", k, x, times[cid])
                                            for cid, vals in moves.items() for k, x in vals.items()])

    def on_preview_dup(self, moves):
        """Alt+drag on the canvas: copies of the clips, put where they were dragged (one edit)."""
        new = self.apply_root("複製並移動", lambda root: edit.duplicate_moved(
            root, self.container(root), list(moves), moves=moves, t_of=self.clip_time))
        self._select_new(new)

    def track_anchor(self, tid, name=False):
        """Where on the timeline a track's header (its name: name) is, for inplace."""
        r = self.timeline.track_name_rect(tid)
        if r is not None and not name:
            r = QRect(0, r.top(), self.timeline.header_w, r.height())
        return (self.timeline, r) if r is not None else None

    def clip_anchor(self, cid):
        """Where on the timeline a clip's label is, for inplace (None when it is out of view)."""
        r = self.timeline.clip_rect(cid)
        return (self.timeline, r) if r is not None else None

    def pick_live(self, initial, title, holders, anchor=None):
        """A colour for tracks or clips (holders), shown on the timeline while it is picked
        (opening at anchor: inplace.anchor_of); what they had comes back before the edit is
        made (or when it is cancelled)."""
        old = [(h, h.get("color")) for h in holders]

        def show(col):
            for h, _ in old:
                h["color"] = col.name()
            self.timeline.update()

        col = pick_color(self, initial, title, alpha=False, live=show, anchor=anchor)
        for h, was in old:
            if was is None:
                h.pop("color", None)
            else:
                h["color"] = was
        self.timeline.update()
        return col

    def toggle_reference(self):
        """R: the selected tracks (else the tracks of the selected clips) become 參考 tracks, or stop being."""
        tl = self.timeline
        ids = set(tl.selected_tracks) or {t["id"] for t in tl.rows for c in project.walk_clips([t])
                                           if c["id"] in tl.selected_ids}
        tracks = [t for t in tl.rows if t["id"] in ids]
        if not tracks:
            return
        on = not all(t.get("reference") for t in tracks)
        tids = [t["id"] for t in tracks]
        self.apply(("設為" if on else "取消") + "參考軌道" + (f"（{len(tids)} 條）" if len(tids) > 1 else ""),
                   lambda lvl: [edit.set_track_flag(lvl, i, "reference", on) for i in tids])

    def on_track_action(self, action, tid):
        t = edit.track_by_id(self.container(), tid)
        if action == "rename":
            name, ok = inplace.ask_name(self, t.get("name") or t["kind"], self.track_anchor(tid, name=True))
            if ok:
                self.apply("重新命名軌道", edit.rename_track, tid, name)
        elif action == "color":
            col = self.pick_live(QColor(t.get("color") or "#888888"), "軌道顏色", [t], self.track_anchor(tid))
            if col is not None:
                self.apply("軌道顏色", edit.set_track_color, tid, col.name())
        elif action == "nocolor":
            self.apply("軌道顏色", edit.set_track_color, tid, None)
        elif action == "clips:track":                   # the track's colour onto all its clips
            self.apply("片段顏色", edit.set_track_clip_colors, tid, t.get("color"))
        elif action == "clips:pick":
            first = next((c.get("color") for c in t["clips"] if c.get("color")), None)
            col = self.pick_live(QColor(first or t.get("color") or "#888888"), "所有片段的顏色", t["clips"],
                                 self.track_anchor(tid))
            if col is not None:
                self.apply("片段顏色", edit.set_track_clip_colors, tid, col.name())
        elif action == "clips:none":
            self.apply("片段顏色", edit.set_track_clip_colors, tid, None)
        elif action.startswith("toggle:"):
            flag = action.split(":", 1)[1]
            if flag == "reference":                     # (the selected tracks together)
                sel = self.timeline.selected_tracks
                tids, on = sorted(sel) if tid in sel else [tid], not t.get(flag)
                self.apply(("設為" if on else "取消") + "參考軌道" + (f"（{len(tids)} 條）" if len(tids) > 1 else ""),
                           lambda lvl: [edit.set_track_flag(lvl, i, flag, on) for i in tids])
                return
            label = {"muted": "靜音", "solo": "獨奏", "hidden": "隱藏", "locked": "鎖定"}[flag]
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
            sel = self.timeline.selected_tracks
            self.delete_tracks(sorted(sel) if tid in sel else [tid])
        elif action == "clear_empty":
            self.clear_empty_tracks()

    def delete_tracks(self, tids):
        """Delete tracks of the open level (asking first when clips are on them), one undo step."""
        level = self.container()
        n = sum(len(edit.track_by_id(level, tid)["clips"]) for tid in tids)
        what = "軌道上" if len(tids) == 1 else f"這 {len(tids)} 條軌道上"
        if n and not questions.question(self, "delete_tracks", "刪除軌道", f"{what}有 {n} 個片段，一起刪除嗎？"):
            return
        self.timeline.selected_tracks = set()
        self.apply("刪除軌道" if len(tids) == 1 else f"刪除 {len(tids)} 條軌道", edit.delete_tracks, tids)

    def clear_empty_tracks(self):
        if self.proj is None:
            return
        if not any(not t["clips"] for t in self.container()["tracks"]):
            self.statusBar().showMessage("沒有空軌道", 3000)
            return
        self.apply("清除空軌道", edit.remove_empty_tracks)

    def on_clip_action(self, action, cid):
        if action.startswith("into:"):                       # 移入群組 (the selection, or the clip)
            sel = [c["id"] for c in self.timeline.selected_clips() if c["type"] != "audio"]
            self.move_into_group(sel if cid in sel else [cid], action[5:])
            return
        if action.startswith("audio_stream:"):              # 音軌 (the selection's sound clips, or the clip)
            sel = [c["id"] for c in self.timeline.selected_clips() if c["type"] in ("audio", "video")]
            self.apply_each("音軌", edit.set_audio_stream, sel if cid in sel else [cid], int(action[13:]))
            return
        if action == "paste":
            self.do_paste()
            return
        if action in ("copy", "cut", "duplicate", "snap_beats", "shuffle", "reverse_rows"):
            {"copy": self.do_copy, "cut": lambda: self.do_copy(cut=True), "duplicate": self.do_duplicate,
             "snap_beats": self.do_snap_beats, "shuffle": self.do_shuffle,
             "reverse_rows": self.do_reverse_rows}[action]()
            return
        if action in ("new_static", "new_component"):         # (cid is the track's id here)
            at, comp = self.playhead_us(), action == "new_component"
            self.apply_root("新增靜態元件" if comp else "新增靜態片段",
                            lambda root: edit.new_compound(root, self.container(root), at, cid, True, comp),
                            select=lambda c: c["id"])
            return
        if action in ("make_static", "make_static_component", "make_compound", "make_component"):
            sel = self.timeline.selected_ids
            ids = sorted(sel) if cid in sel else [cid]
            comp, at = action.endswith("component"), self.playhead_us()
            static = action.startswith("make_static")
            self.apply_root(f"建立{edit.kind_name(static, comp)}",
                            lambda root: edit.make_compound(root, self.container(root), ids, at, static, comp),
                            select=lambda c: c["id"])
            return
        if action in ("to_component", "from_component"):
            self.component_kind(edit.find(self.container(), cid)[1]["compound_id"], action == "to_component")
            return
        if action == "to_static":
            self.compound_to_static(edit.find(self.container(), cid)[1]["compound_id"])
            return
        if action == "group":
            sel = self.timeline.selected_ids
            self.make_group(sorted(sel) if cid in sel else [cid])
            return
        _, c = edit.find(self.container(), cid)
        if action == "fold":
            self.timeline.toggle_group(c)
        elif action == "ungroup":
            self.ungroup(cid)
        elif action == "group_matte":
            self.toggle_group_matte([cid])
        elif action == "group_anchor":
            self.toggle_group_anchor([cid])
        elif action == "group_invert":
            self.toggle_group_matte([cid], "invert")
        elif action == "enter":
            self.enter_compound(cid)
        elif action == "open_tab":
            self.open_in_tab(project.ref_of(c))
        elif action == "save_library":
            self.save_compound_to_library(c.get("compound_id"))
        elif action == "rename":                             # a multi-selection: all get the one name
            sel = self.timeline.selected_ids
            ids = sorted(sel) if cid in sel else [cid]
            name, ok = inplace.ask_name(self, self.timeline.clip_label(c), self.clip_anchor(cid))
            if ok:
                self.apply_each("重新命名片段", edit.rename_clip, ids, name)
        elif action in ("color", "nocolor"):
            sel = self.timeline.selected_ids                  # a multi-selection is coloured together
            ids = sorted(sel) if cid in sel else [cid]
            if action == "nocolor":
                self.apply_each("片段顏色", edit.set_clip_color, ids, None)
            else:
                level = self.container()
                col = self.pick_live(QColor(c.get("color") or "#888888"), "片段顏色",
                                     [edit.find(level, i)[1] for i in ids], self.clip_anchor(cid))
                if col is not None:
                    self.apply_each("片段顏色", edit.set_clip_color, ids, col.name())
        elif action == "unique":
            self.apply_root("設為獨立", lambda root: edit.make_unique(root, self.container(root), cid))
        elif action == "clone":
            sel = self.timeline.selected_ids
            ids = sorted(sel) if cid in sel else [cid]
            self._select_new(self.apply_root("建立獨立副本", lambda root: edit.clone_clips(
                root, self.container(root), ids)))
        elif action == "detach_audio":
            self.apply("分離音訊", edit.detach_audio, cid)
        elif action == "detach_all_audio":
            self.apply("分離所有音軌", edit.detach_audio, cid,
                       list(range(len(build.audio_streams(c["media"]["path"])))))
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
        """Files (or folders of them) dragged in: they join the media library where they are,
        and the timeline too when dropped there
        (place = (track id, start us, across): stacked, or one after another with Alt)."""
        saved = [p for p in paths if p.lower().endswith(userlib.COMPOUND_EXT) and os.path.isfile(p)]
        for p in saved if place is not None else ():    # compounds saved in a Library: onto the timeline
            self.place_library_compound(p, place[0], place[1])
        files = library.media_files(paths)
        if not files:
            if not saved:
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
        """Add the files to the library (in `folder`) where they are, without copying them (the
        library's copy button does that later) and, with place, to the timeline."""
        if not self.ensure_project():
            return
        root = self.root
        self.statusBar().showMessage(f"匯入 {len(files)} 個檔案…")

        def work(progress):                            # probing reads the files: off the UI thread
            probes, bad = {}, []
            for i, f in enumerate(files):
                try:
                    probes[library.norm(f)] = library.probe(f)
                except Exception:
                    bad.append(os.path.basename(f))
                progress((i + 1) / len(files))
            return probes, bad

        def add_and_place(proj, ids):
            track_id, start, across = place
            return library.place_items(self.container(proj), [library.item(proj, iid) for iid in ids],
                                       track_id or None, start, across)

        def done(result):
            probes, bad = result
            if self.root != root:
                return
            items = library.add_files(self.proj, list(probes), folder, probes, reuse=True)
            self.dirty = True
            self.fs_epoch += 1
            self.refresh_library()
            self.request_sync(300)                     # files already in Media go to their own folder
            self.panels.show("library")
            if items and place is not None:
                self._select_new(self.apply_root("匯入素材並加入時間軸", add_and_place, [it["id"] for it in items],
                                                 select=lambda cs: cs[-1]["id"]))
            elif items:
                self.statusBar().showMessage(f"已匯入 {len(items)} 個素材", 4000)
            if bad:
                QMessageBox.warning(self, "部分檔案無法匯入", "讀不到：\n" + "\n".join(bad))

        self.run_task(work, done, lambda m: QMessageBox.critical(self, "匯入失敗", m),
                      lambda p: self.statusBar().showMessage(f"匯入中… {int(p * 100)}%"))

    def library_do(self, label, fn):
        """A file operation on Media: it is done on the disk at once (not part of undo); clips,
        the undo history and the library follow the files."""
        if not self.proj or not self.root:
            if self.proj:
                self.statusBar().showMessage("先儲存專案（Ctrl+S），才有專案資料夾可以放素材", 6000)
            return False, None
        try:
            result = fn()
        except (edit.EditError, OSError, shutil.Error) as exc:
            QMessageBox.warning(self, label, str(exc))
            return False, None
        finally:
            self.fs_epoch += 1
            self.refresh_library()
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
        name, ok = inplace.ask_name(self, target["name"])
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
        if questions.question(self, "delete_media", "刪除", f"要刪除這個{what}嗎？它們會被移到資源回收筒。{note}"):
            ok, _ = self.library_do("刪除", lambda: library.delete_on_disk(self.proj, self.root, ident, self.trash))
            if ok:
                self.after_edit("刪除素材")
                self.request_sync(300)

    def place_library_compound(self, path, track_id, start_us):
        """A compound saved in the Library: into the project (once per version of the file) and
        onto the open level, as a compound clip."""
        try:
            pack = userlib.load_compound(path)
        except (OSError, ValueError) as exc:
            self.statusBar().showMessage(f"讀不到複合片段：{exc}", 5000)
            return

        def fn(root):
            kid = edit.add_library_compound(root, pack)
            assets.restore(project.walk_clips(root["compounds"][kid]["tracks"]), self.asset_media_dir())   # (drawn again for this project)
            return edit.place_compound(root, self.container(root), kid, track_id or None, start_us)
        self.apply_root("加入複合片段", fn, select=lambda c: c["id"])

    def save_compound_to_library(self, kid, folder=None):
        """存到 Library: compound kid (with what it shows) as a file in the Library's 複合片段,
        to use in any project."""
        if not self.proj or not self.ulib or kid not in self.proj.get("compounds", {}):
            return
        comp = self.proj["compounds"][kid]
        name, ok = QInputDialog.getText(self, "存到 Library", "名稱", text=comp.get("name") or "複合片段")
        if not ok or not name.strip():
            return
        base = library.folder_dir(self.ulib.proj("compounds"), self.ulib.mirror("compounds"), folder)
        try:
            userlib.save_compound(self.ulib.root, base, name.strip(), self.proj, kid)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "存到 Library", str(exc))
            return
        self.ul_epoch += 1
        self.request_ul_sync(0)
        self.panels.show("userlib")
        self.ulpanel.show_category("compounds")
        self.statusBar().showMessage(f"已存到 Library > 複合片段：{name.strip()}", 4000)

    def save_selected_compound(self, folder):
        """The Library's 存選取的複合片段: the compound the selected compound clip shows."""
        c = next((k for k in self.timeline.selected_clips_primary_first() if k.get("compound_id")), None)
        if c is None:
            self.statusBar().showMessage("先在時間軸選一個複合片段（或在「複合片段」分頁按右鍵 > 存到 Library）", 5000)
            return
        self.save_compound_to_library(c["compound_id"], folder)

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
        name, ok = inplace.ask_name(self, comp.get("name") or "")
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
            elif key == "compounds":
                self.place_library_compound(it["path"], track_id, start_us)
            elif key == "presets":
                self.use_effect_preset(it["path"], track_id, start_us)
            else:
                self.apply_root("加入素材", lambda root: library.place_item(
                    self.container(root), it, track_id or None, start_us), select=lambda c: c["id"])
            return
        self.apply_root("加入素材",
                        lambda root: library.place(self.container(root), root, item_id, track_id or None, start_us),
                        select=lambda c: c["id"])

    def place_media_many(self, item_ids, track_id, start_us, across):
        """Several media items dragged together: stacked on tracks of their own, or (Alt,
        across) one after another; one undo step, and they end up selected."""
        if not self.proj:
            return
        items = []
        for iid in item_ids:
            if iid.startswith("mu"):                         # the user's Library: media only
                key, it = self.ulib.find(iid)
                if it is not None and key not in ("filters", "textstyles", "compounds", "presets"):
                    items.append(it)
            else:
                it = next((i for i in library.lib(self.proj)["items"] if i["id"] == iid), None)
                if it is not None:
                    items.append(it)
        if not items:
            return
        self._select_new(self.apply_root("加入素材", lambda root: library.place_items(
            self.container(root), items, track_id or None, start_us, across), select=lambda cs: cs[-1]["id"]))

    def asset_media_dir(self):
        """Where the files of built-in assets are drawn: the Media folder, or for a project not saved yet (no
        folder) the project's cache - the first 儲存 copies them into Media with the other outside files."""
        if self.root:
            return workspace.media_dir(self.root)
        return os.path.join(self.cache_dir(), "media")

    def store_asset(self, params):
        """Draw built-in asset parameters (assets.py) into the project's Media/.內建素材;
        the file's path, or None after telling the user why not."""
        try:
            return assets.store(self.asset_media_dir(), params)
        except OSError as exc:
            QMessageBox.critical(self, "無法建立素材", str(exc))
            return None

    def viz_media(self):
        """The (empty) picture an Audio Visualizer clip stands on, in Media/.內建素材."""
        d = os.path.join(self.asset_media_dir(), assets.FOLDER)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "audio-visualizer.png")
        if not os.path.exists(path):
            img = QImage(1, 1, QImage.Format_ARGB32)
            img.fill(Qt.transparent)
            img.save(path)
        return path.replace("\\", "/")

    def add_visualizer(self, kind, track_id=None, start_us=None):
        """新增 Audio Visualizer: at start_us (the playhead), on track_id when it has room, listening to the first
        track with sound (else nothing yet: 屬性 chooses)."""
        if not self.ensure_project():
            return
        level = self.container()
        tr = next((t for t in level["tracks"] if self.sound_track(t)), None)
        start = round(self.playhead_us() if start_us is None else start_us)
        if tr is not None:
            source = {"type": "track", "id": tr["id"]}
            dur = max(US, project.end_us([tr]) - start) if project.end_us([tr]) > start else 5 * US
        else:                                           # (no sound yet: the source is chosen in 屬性 afterwards)
            source, dur = {"type": "track", "id": ""}, 10 * US
        media = self.viz_media()
        w, h = level.get("width") or self.proj["width"], level.get("height") or self.proj["height"]
        self.apply("新增 Audio Visualizer", lambda lvl: edit.add_visualizer(lvl, kind, source, media, start, dur, w, h, track_id or None),
                   select=lambda c: c["id"])

    @staticmethod
    def sound_track(t):
        """Whether a track has something a visualizer can listen to."""
        return any(c["type"] in ("audio", "video") and c.get("media") or project.is_group(c) or c["type"] == "compound"
                   for c in t["clips"])

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
        if ident.startswith(textpresets.PREFIX):           # a text preset of the 內建素材 tab: a new text clip with those looks
            style = textpresets.fields(ident)
            if style is not None and self.ensure_project():
                self.apply("加入文字", lambda lvl: edit.add_text(lvl, round(start_us), track_id=track_id or None, style=style),
                           select=lambda c: c["id"])
            return
        if ident.startswith("viz:"):                       # an Audio Visualizer of the 內建素材 tab
            self.add_visualizer(ident[4:], track_id, start_us)
            return
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
        its place, length, look and keyframes. Dropped on one of several selected clips, every
        selected clip that can take it does (批量替換), in one undo step."""
        if not self.proj:
            return
        picture = True
        if ident.startswith(("viz:", textpresets.PREFIX)):
            self.statusBar().showMessage("Audio Visualizer 和文字不能用來替換素材", 4000)
            return
        if ident.startswith(assets.PREFIX):
            made = self.new_asset(ident)
            if made is None:
                return
            params, path = made
            one = lambda root, level, k: edit.replace_media(level, k, assets.item(params, path), params)
        elif ident.startswith("cmp:"):
            one = lambda root, level, k: edit.replace_with_compound(root, level, k, ident[4:])
        else:
            if ident.startswith("mu"):                     # an item of the user's Library
                key, it = self.ulib.find(ident)
                if it is None or key not in ("videos", "images", "sounds", "compounds"):
                    self.statusBar().showMessage("替換素材：只能換成圖片、影片、聲音或複合片段", 4000)
                    return
            else:
                key = None
                try:
                    it = library.item(self.proj, ident)
                except edit.EditError:
                    return
            if key == "compounds":                         # a compound kept in the Library
                try:
                    pack = userlib.load_compound(it["path"])
                except (OSError, ValueError) as exc:
                    self.statusBar().showMessage(f"讀不到複合片段：{exc}", 5000)
                    return

                def one(root, level, k):
                    kid = edit.add_library_compound(root, pack)
                    assets.restore(project.walk_clips(root["compounds"][kid]["tracks"]), self.asset_media_dir())
                    return edit.replace_with_compound(root, level, k, kid)
            else:
                picture = it["kind"] != "audio"
                one = lambda root, level, k: edit.replace_media(level, k, dict(it))
        targets = self.replace_targets(cid, picture)

        def fn(root):
            level = self.container(root)
            return [one(root, level, k) for k in targets]
        if len(targets) == 1:
            self.apply_root("替換素材", fn, select=lambda cs: cs[0]["id"])
        else:                                            # (the selection stays as it was)
            self.apply_root(f"替換素材（{len(targets)} 個）", fn)

    def replace_targets(self, cid, picture):
        """The clips a source dropped on clip cid replaces: cid, and when it is selected, the
        other selected clips that can take it (pictures, videos and compounds for a picture,
        sounds for a sound) - cid first."""
        if cid not in self.timeline.selected_ids:
            return [cid]
        ok = edit.REPLACEABLE if picture else ("audio",)
        return [cid] + [c["id"] for c in self.timeline.selected_clips_primary_first()
                        if c["id"] != cid and c["type"] in ok]

    # -- inspector / preview overlay --------------------------------------------------------------
    def refresh_inspector(self):
        sel = self.timeline.selected
        self.show_selection_props()
        self.curves.set_clip(sel, self.clip_time(sel["id"]) if sel else 0, self.fps)
        self.curves.set_links(*self.curve_links(sel))
        self.preview.set_scene(self.view() if self.proj else None, self.playhead_us(),
                               sel["id"] if sel else None, self.timeline.selected_ids)
        sp = self.preview.spacing() if self.proj else None
        self.inspector.show_spacing(sp[1] if sp else None)
        self._matte_preview_changed()
        self._update_matte_region()
        self._update_layers()
        self._update_buttons()

    # -- preview ----------------------------------------------------------------------------------
    def snapshot(self):
        """A private copy of the open level for the renderer thread, counted in the editor's
        frames (時間線精度) and played at the project's frame rate. Pickled rather than through
        JSON: it keeps what clips share shared (a compound's content, written out again for each of
        its clips by JSON), so an edit or a drag tick of a big project takes 1 ms instead of 70.
        Its 參考 tracks show and sound (editing): an export's copy leaves them out."""
        v = pickle.loads(pickle.dumps(self.view(), pickle.HIGHEST_PROTOCOL))
        v["play_fps"], v["fps"], v["editing"] = self.proj["fps"], self.fps, True
        shown = self._matte_shown = self.matte_target()
        if shown:
            v["matte_preview"] = shown
        if self.nodes.show_thumbs:                       # the node effects of the selected clip: send each node's picture
            sel = self.timeline.selected
            v["thumbs"] = [e["id"] for e in (sel or {}).get("effects") or [] if e.get("filter") == fx.GRAPH]
        return v

    def matte_target(self):
        """{clip, opacity} while the 遮罩 tab edits a compound mask that has its compound and
        預覽複合片段 is on: the preview draws that compound over the clip, at the opacity
        typed beside it."""
        sel = self.timeline.selected if self.proj else None
        m = (sel or {}).get("mask") or {}
        has = (m.get("compound_id") in self.proj.get("compounds", {}) if m.get("kind") == "compound"
               else bool(m.get(m.get("kind"))) if m.get("kind") in ("image", "video") else False)
        if not (self.preview.mask_mode and self.preview.mask_group == "mask" and has and self.mask_panel.matte_preview):
            return None
        return {"clip": sel["id"], "opacity": self.mask_panel.matte_opacity}

    def _update_matte_region(self):
        """編輯區域: the ghost of the selected clip's (live) compound mask, or its video mask's
        video, on the timeline, while the 遮罩 tab edits it with 編輯區域 on."""
        sel = self.timeline.selected if self.proj else None
        m = (sel or {}).get("mask") or {}
        self.matte_group = "mask"
        ef = self.effects
        if sel is not None and ef.source_region and self.panels.is_active("effects"):     # a colour source's
            try:
                m = edit.holder(sel, "fxsrc:{}:{}".format(*ef.source_region))
                self.matte_group = "fxsrc:{}:{}".format(*ef.source_region)
            except edit.EditError:
                m = {}
        comp = self.proj.get("compounds", {}).get(m.get("compound_id")) if self.proj else None
        if m.get("kind") == "video" and m.get("video"):
            src = {"duration_us": m.get("vid_dur") or 0, "name": os.path.basename(m["video"]), "icon": "▶"}
        else:
            src = comp if m.get("kind") == "compound" and comp is not None and not comp.get("static") else None
        on = (self.mask_panel.matte_region and self.preview.mask_mode and self.preview.mask_group == "mask"
              or self.matte_group != "mask") and src
        self.timeline.set_matte_region({"clip": sel["id"], "t_off": int(m.get("t_off", 0)),
                                        "duration": src.get("duration_us") or 0, "name": src.get("name"),
                                        "icon": src.get("icon")}
                                       if on else None)

    def mask_images(self):
        """[(path, name)] of the media library's pictures (what an image mask can cut with)."""
        return [(it["path"], it.get("name") or os.path.basename(it["path"]))
                for it in library.lib(self.proj)["items"] if it.get("kind") == "image" and it.get("path")]

    def on_matte_offset(self, cid, t_off):
        """編輯區域 dragged on the timeline: a mask's part, or a colour source's."""
        g = self.matte_group
        if g == "mask":
            self.apply("編輯區域", edit.set_mask_offset, cid, t_off)
        else:
            eid, _, name = g[6:].partition(":")
            self.apply("編輯區域", edit.set_effect_source_offset, cid, eid, name, t_off)

    def on_fx_source_media(self, ids, eid, name, value):
        """What a colour source shows (of effect eid and the alike ones of the other clips ids): a
        picture / video of the media library's, a compound, or ("") a file picked now."""
        try:
            kind = edit.holder(edit.find(self.container(), ids[0])[1], f"fxsrc:{eid}:{name}")["kind"]
        except (edit.EditError, IndexError):
            return
        if kind == "compound":
            comp = self.proj.get("compounds", {}).get(value)
            self.fx_each("效果來源", ids, eid, lambda lvl, cid, e: edit.set_effect_source_media(
                lvl, cid, e, name, compound=(value, comp)))
            return
        if kind == "track":
            size = self.level_size()
            self.fx_each("效果來源", ids, eid, lambda lvl, cid, e: edit.set_effect_source_media(
                lvl, cid, e, name, track=(value, size)))
            return
        if not value:
            what = "圖片 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.svg)" if kind == "image" else \
                "影片 (*.mp4 *.mov *.mkv *.webm *.avi *.m4v *.gif)"
            value, _ = QFileDialog.getOpenFileName(self, "效果來源", self.root or "", what)
            if not value:
                self.refresh_inspector()
                return
            value = value.replace("\\", "/")
        try:
            info = library.probe(value)
        except Exception:
            info = {}
        if info.get("kind") != kind or not info.get("width"):
            self.statusBar().showMessage("讀不到這個檔案", 4000)
            self.refresh_inspector()
            return
        media = {"image": (value, info["width"], info["height"])} if kind == "image" else \
            {"video": (value, info["width"], info["height"], info.get("duration_us"))}
        self.fx_each("效果來源", ids, eid, lambda lvl, cid, e: edit.set_effect_source_media(lvl, cid, e, name, **media))

    def mask_videos(self):
        """[(path, name)] of the media library's videos (what a video mask can play)."""
        return [(it["path"], it.get("name") or os.path.basename(it["path"]))
                for it in library.lib(self.proj)["items"] if it.get("kind") == "video" and it.get("path")]

    def on_mask_video(self, ids, path):
        """A video mask's video: one of the library's, or ("") a file picked now."""
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "遮罩影片", self.root or "",
                                                  "影片 (*.mp4 *.mov *.mkv *.webm *.avi *.m4v *.gif)")
            if not path:
                self.refresh_inspector()
                return
            path = path.replace("\\", "/")
        try:
            info = library.probe(path)
        except Exception:
            info = {}
        if info.get("kind") != "video":
            self.statusBar().showMessage("讀不到這個影片", 4000)
            self.refresh_inspector()
            return
        self.apply_each("遮罩影片", lambda lvl, cid: edit.set_mask_video(
            lvl, cid, path, info["width"], info["height"], info.get("duration_us")), ids)

    def on_mask_image(self, ids, path):
        """An image mask's picture: one of the library's, or ("") a file picked now."""
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "遮罩圖片", self.root or "",
                                                  "圖片 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.svg)")
            if not path:
                self.refresh_inspector()
                return
            path = path.replace("\\", "/")
        info = library.probe(path) if os.path.exists(path) else {}
        w, h = info.get("width"), info.get("height")
        self.apply_each("遮罩圖片", lambda lvl, cid: edit.set_mask_image(lvl, cid, path, w, h), ids)

    def _matte_preview_changed(self, force=False):
        """Draw the frame again when what matte_target() shows has changed."""
        if self.proj is not None and (force or self.matte_target() != getattr(self, "_matte_shown", None)):
            self.rebuild()

    def mask_tracks(self):
        """[(id, name)] of the open level's picture tracks (what a 軌道 source can show)."""
        return [(t["id"], t.get("name") or t["id"]) for t in reversed(self.container()["tracks"]) if t["kind"] != "audio"]

    def level_size(self):
        """(width, height) of the open level's canvas."""
        lvl = self.container()
        return lvl.get("width") or self.proj["width"], lvl.get("height") or self.proj["height"]

    def mask_compounds(self):
        """[(id, name)] of the compounds a clip of the open level can be masked with: not one
        that shows this level (it would cut with itself)."""
        steps = walk_path(self.proj, self.path_ids)      # (the open level: the last compound's content)
        here = steps[-1][2] if steps else self.proj["active_timeline"]
        out = []
        for kid, comp in self.proj.get("compounds", {}).items():
            if not project.contains(self.proj, kid, here):
                out.append((kid, ("◧ " if comp.get("static") else "") + (comp.get("name") or kid)))
        return out

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
                        vals = edit.with_linked_scale(holder, vals, self.clip_time(cid))
                        parts[i] = (g, vals)
                    holder.update(vals)
        self.player.worker.set_view(view, self.cache_dir())
        for panel in (self.inspector, self.mask_panel, self.effects):   # the numbers follow the drag
            for g, vals in parts:
                panel.show_live(cid, g, vals)

    def live_moves(self, moves):
        """While several clips are dragged on the canvas: draw them there without editing yet."""
        view = self.snapshot()
        for c in project.walk_clips(view["tracks"]):
            if c["id"] in moves:
                group_holder(c, "transform", create=True).update(moves[c["id"]])
        self.player.worker.set_view(view, self.cache_dir())
        for cid, vals in moves.items():
            self.inspector.show_live(cid, "transform", vals)

    def live_dup(self, moves):
        """While copies are Alt-dragged on the canvas: the clips stay, their copies are drawn
        moved, on top of everything (not an edit yet)."""
        view = self.snapshot()
        copies = []
        for c in project.walk_clips(view["tracks"]):
            if c["id"] in moves:
                dup = dict(c, id=c["id"] + "~copy", transform=dict(c.get("transform") or {}, **moves[c["id"]]))
                copies.append(dup)
        audio_at = next((i for i, t in enumerate(view["tracks"]) if t["kind"] == "audio"), len(view["tracks"]))
        view["tracks"].insert(audio_at, {"id": "~copies", "kind": "video", "name": "", "clips": copies})
        self.player.worker.set_view(view, self.cache_dir())

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
                    holder.update(edit.with_linked_scale(holder, {key: value}, self.clip_time(c["id"])))
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
        self.show_rack()
        self.preview.show_image(img)
        if self.fullscreen:
            self.fullscreen.canvas.show_image(img)
            self.fullscreen.set_position(pos, self.length, self.fps)
        self.timeline.set_position(pos, follow=self.playing or getattr(self, "follow", True))
        self.show_time()
        sel = self.timeline.selected
        if sel is not None:
            if not self.playing:
                self.show_selection_props()
            elif not self.props_timer.isActive():     # (every frame cost playing its frame rate)
                self.props_timer.start()
            self.curves.set_time(sel, self.clip_time(sel["id"]))
        self.preview.set_scene(self.view() if self.proj else None, self.playhead_us(),
                               sel["id"] if sel else None, self.timeline.selected_ids)

    def on_state(self, playing):
        self.playing = playing
        self.play_btn.setIcon(icons.icon("pause" if playing else "play"))
        if not playing and self.props_timer.isActive():
            self.props_timer.stop()
            self._playing_props()                     # (where playing stopped)

    def _playing_props(self):
        if self.proj is not None and self.timeline.selected is not None:
            self.show_selection_props()

    def set_play_rate(self, rate):
        """播放速度 of the preview (remembered for the next time)."""
        self.player.worker.set_rate(rate)
        self.settings().setValue("play_rate", rate)
        if self.rate_box.currentData() != rate:
            self.rate_box.setCurrentIndex(max(0, self.rate_box.findData(rate)))

    def set_keep_pitch(self, on):
        """保持音高 at other 播放速度 (remembered for the next time)."""
        self.player.worker.set_keep_pitch(on)
        self.settings().setValue("keep_pitch", bool(on))

    def toggle_play(self):
        """Space: play, or stop - where playback is, or (播放模式 回到開始處) back where it began."""
        if self.proj is None or (self.editing_static() and not self.player.worker.playing):
            return
        w = self.player.worker
        if not w.playing:                          # (the player's own state: the UI's lags a moment)
            self.play_from = self.pos
            w.set_playing(True)
        elif self.play_mode.currentData() == "return" and getattr(self, "play_from", None) is not None:
            self.seek(self.play_from)
        else:
            w.set_playing(False)

    def show_time(self):
        """The playhead's time as the timebase counts it (and, on a BPM one, in seconds too)."""
        us = self.pos / self.fps * US
        self.time_lbl.setText(time_text(us, self.fps, self.timebase))
        clock = timecode(us, self.fps) + "　" if self.timebase["kind"] == "bpm" else ""
        self.dur_lbl.setText(clock + "長度 " + timecode(self.length / self.fps * US, self.fps))

    def per_beat(self):
        """精度 on a BPM timebase: the editor's frames per beat."""
        return self.fps * 60 / self.timebase["bpm"]

    def show_edit_fps(self):
        """精度 as the timebase counts it: frames a second, or on a BPM one frames a beat
        (0: 跟專案, the project's frame rate)."""
        box, bpm = self.edit_fps_box, self.timebase["kind"] == "bpm"
        box.blockSignals(True)
        box.setSuffix(" 格/拍" if bpm else " 格/秒")
        box.setRange(0, int(1000 * 60 / self.timebase["bpm"]) if bpm else 1000)
        own = self.proj is not None and self.fps != self.proj["fps"]
        box.setValue(round(self.per_beat() if bpm else self.fps) if own else 0)
        box.blockSignals(False)

    def on_edit_fps_box(self, v):
        if self.timebase["kind"] == "bpm":
            self.set_edit_fps(v * self.timebase["bpm"] / 60 if v else None)
        else:
            self.set_edit_fps(v or None)

    def set_timebase(self, tb, edited=True):
        """時基: how the ruler and the time readout count (timeline.timebase_of), for the open
        level (each timeline and compound has its own, level_key). Only shown, not an edit;
        saved with the view. On a BPM one 精度 counts frames a beat, and a new BPM keeps their
        number (the frames a second follow it)."""
        old, self.timebase = self.timebase, tb
        if self.tb_key is not None:
            self.timebases[self.tb_key] = tb
        if (edited and self.proj is not None and self.fps != self.proj["fps"] and old["kind"] == tb["kind"] == "bpm"
                and old["bpm"] != tb["bpm"]):
            self.set_edit_fps(min(1000, max(1, round(self.fps * 60 / old["bpm"])) * tb["bpm"] / 60))
        self.show_edit_fps()
        self.timeline.timebase = tb if tb["kind"] == "bpm" else None
        self.timeline.update()
        self.timebase_btn.setText(button_text(tb))
        if self.proj is not None:
            self.show_time()
            if edited:
                self.dirty = True
                self._update_title()

    def edit_timebase(self):
        if self.proj is None:
            return
        c = self.placed(self.timeline.selected)            # (a group's clip: its start on the timeline)
        edit_timebase(self.timebase_btn, self.timebase, self.playhead_us(),
                      c if c is not None and c.get("beat") else None, self.set_timebase)

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

    def toggle_guides(self):
        on = self.guides_btn.isChecked()
        self.preview.set_show_guides(on)
        self.settings().setValue("show_guides", "true" if on else "false")

    def toggle_overflow(self):
        on = self.overflow_btn.isChecked()
        self.player.worker.set_overflow(OVERFLOW if on else 0.0)
        self.settings().setValue("show_outside", "true" if on else "false")

    def toggle_fullscreen(self):
        if self.fullscreen:
            self.fullscreen.close()
            return
        fs = FullscreenPreview(self if sys.platform == "android" or os.environ.get("KIASECUT_FULLSCREEN_COVER") else None)
        fs.canvas.W, fs.canvas.H = self.preview.W, self.preview.H
        fs.canvas.show_image(self.preview.img)
        fs.togglePlay.connect(self.toggle_play)
        fs.step.connect(self.step)
        fs.seekRequested.connect(self.seek)
        fs.canvas.renderWidth.connect(lambda w: self.set_render_width("full", w))
        fs.closed.connect(self._fullscreen_closed)
        fs.set_position(self.pos, self.length, self.fps)
        self.fullscreen = fs
        fs.present()

    def _fullscreen_closed(self):
        fs, self.fullscreen = self.fullscreen, None
        self.set_render_width("full", 0)
        if fs is not None:
            # (closed from its own closeEvent, or from the double click on its canvas: dropping the last reference here deleted the window
            # - and the canvas - under the code that was still running in them, which ends the program on Android; deleted a turn later)
            QTimer.singleShot(0, lambda fs=fs: fs.deleteLater())

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

    def add_marker(self, t_us=None):
        """M: a 時間線標記 at the playhead (or at t_us)."""
        if self.proj:
            self.apply("新增標記", edit.add_marker, round(self.pos / self.fps * US) if t_us is None else t_us)

    def on_marker_action(self, action, mid):
        """The timeline's marker menu: rename, colour (a preset "color:#rrggbb", or picked),
        delete ("" : all of them)."""
        if action == "delete":
            self.apply("刪除標記" if mid else "刪除所有標記", edit.delete_marker, mid or None)
            return
        m = next((m for m in edit.markers_of(self.view()) if m["id"] == mid), None)
        if m is None:
            return
        anchor = self.timeline.marker_rect(mid)
        anchor = (self.timeline, anchor) if anchor is not None else None
        if action == "rename":
            name, ok = inplace.ask_name(self, m["name"], anchor)
            if ok:
                self.apply("重新命名標記", edit.rename_marker, mid, name)
        elif action.startswith("color:"):
            self.apply("標記顏色", edit.set_marker_color, mid, action[len("color:"):])
        elif action == "color":
            col = self.pick_live(QColor(m.get("color") or "#4c8dff"), "標記顏色", [m], anchor)
            if col is not None:
                self.apply("標記顏色", edit.set_marker_color, mid, col.name())

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
        out_tracks = [t for t in self.proj["tracks"] if project.present(t)]     # (參考 tracks are not exported)
        total = max(round(project.end_us(out_tracks or self.proj["tracks"]) / US * self.fps), 1)
        default = (os.path.join(workspace.exports_dir(self.root), workspace.project_name(self.path) + ".mp4")
                   if self.root else os.path.join(os.path.expanduser("~"), "Videos", "KiaseCut.mp4"))
        if len(self.proj["timelines"]) > 1:              # one file per timeline
            default = default[:-4] + f" - {project.timeline(self.proj)['name']}.mp4"
        try:
            last_spec = json.loads(self.settings().value("export_spec", "") or "{}")
        except (TypeError, ValueError):
            last_spec = {}
        dlg = ExportDialog(self, default, self.fps, total, self.timeline.mark_in, self.timeline.mark_out,
                           self.proj["width"], self.proj["height"], out_fps=self.proj["fps"], spec=last_spec)
        if dlg.exec() != QDialog.Accepted:
            return
        out, t0, t1, fmt, opts = dlg.result_options()
        spec = dlg.spec()
        self.settings().setValue("export_spec", json.dumps(spec))
        fps = fmt["fps"]
        first, last = dlg.frames()                      # frames of the export's own rate
        if not out:
            return
        self.player.worker.set_playing(False)
        snapshot = json.loads(json.dumps(self.proj))
        cache = self.cache_dir()
        f = dlg.format()
        own = renderexport.needs_renderer(snapshot) or not renderexport.uses_mlt(spec)
        desc = [f.label]
        if f.has_video:
            desc += [f"{fmt['width']}×{fmt['height']}", f"{fps:g} fps"]
        if f.quality:
            desc.append(QUALITY[dlg.quality.currentIndex()][0])
        desc.append("KiaseCut 渲染器" if own else "MLT")
        cancel = threading.Event()
        running = {"engine": None, "why": None}   # the MLT engine process now exporting, killed on 取消;
                                                  # why it was stopped for the user (memory), None: by them
        def stop(reason=None):
            if reason and not cancel.is_set():
                running["why"] = reason
            cancel.set()
            eng = running["engine"]
            if eng is not None:
                eng.proc.kill()                   # MLT has no way to stop between frames: end its process

        prog = ExportProgress(self, out, " · ".join(desc), last - first + 1 if f.has_video else 0, stop)
        prog.show()

        def stage(text):
            self.taskCall.emit(prog.set_stage, text)

        def check():
            if cancelled():
                raise RuntimeError("已取消")

        def cancelled():
            """Asked between frames: also stops at once when the system's memory runs low (the
            window looks too, but only every 250 ms, and an MLT export is stopped from there)."""
            low = None if cancel.is_set() else prog.guard.low()
            if low:
                stop(prog.low_memory_reason(*low))
                self.taskCall.emit(prog.cancel, running["why"])        # (the window shows it)
            return cancel.is_set()

        def work(progress):
            os.makedirs(cache, exist_ok=True)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            if own:
                # filters, blend modes, the other formats, transparency: our own renderer
                return renderexport.export(snapshot, out, (fmt["width"], fmt["height"]), fps, first, last, opts,
                                           progress, cache, cancelled, spec, stage)
            r = mlt_export(progress)
            if spec.get("stems"):
                stage("分軌音檔")
                r = dict(r, stems=renderexport.stems(snapshot, out, fps, first, last, spec["stems"], cache,
                                                     cancelled))
            return r

        def mlt_export(progress):
            stage("建立 MLT 文件")
            xml = build.build(snapshot, cache, os.path.join(cache, "export.mlt"),   # originals, no proxies
                              size=(fmt["width"], fmt["height"]), fps=fps)
            enc = gpu.mlt_video_opts(opts, (fmt["width"], fmt["height"]))
            for attempt in ([enc] if enc else []) + [None]:          # NVENC first; x264 if it fails
                check()
                stage("編碼（NVENC / GPU）" if attempt else "編碼（x264 / CPU）")
                eng = EngineClient(16, 16)        # its own process; the preview stays usable
                running["engine"] = eng
                try:
                    check()                       # (取消 while the engine was starting)
                    r = eng.export(xml, out, progress, threads=os.cpu_count() or 4,
                                   **{"in": first, "out": last}, **dict(opts, **(attempt or {})))
                except RuntimeError:
                    check()                       # a killed engine is a 取消, not a reason to try x264
                    if attempt is None:
                        raise
                    continue
                finally:
                    running["engine"] = None
                    eng.close()
                if attempt is None or (os.path.exists(out) and os.path.getsize(out) > 1024):
                    return dict(r, encoder="NVENC (GPU)" if attempt else "x264 (CPU)")

        def failed(m):
            prog.finish()
            if not cancel.is_set():
                QMessageBox.critical(self, "匯出失敗", m)
                return
            if f.kind != "sequence" and os.path.isfile(out):          # the half-written file is no use
                try:
                    os.remove(out)
                except OSError:
                    pass
            if running["why"]:
                peak = f"，KiaseCut 記憶體最高 {sysmem.gb(prog.peak)}" if prog.peak else ""
                QMessageBox.warning(self, "已自動取消匯出",
                                    f"{running['why']}\n\n已完成 {prog.frames_lbl.text()} 幀{peak}。")
            else:
                self.statusBar().showMessage(f"已取消匯出（{prog.frames_lbl.text()} 幀）", 6000)

        def done(r):
            prog.finish()
            extra = ("\n\n" + "\n".join(r["errors"])) if r.get("errors") else ""
            enc = f"，{r['encoder']}" if r.get("encoder") else ""
            what = (f"{fmt['width']}×{fmt['height']}，{fps:g} fps{enc}" if dlg.format().has_video
                    else enc.lstrip("，"))
            stems = (f"\n分軌音檔 {len(r['stems'])} 個：{renderexport.stems_dir(out)}" if r.get("stems")
                     else "\n沒有可分軌的聲音" if spec.get("stems") else "")
            made = r.get("done", out)
            size = (sum(e.stat().st_size for e in os.scandir(made) if e.is_file()) if os.path.isdir(made)
                    else os.path.getsize(made) if os.path.isfile(made) else None)
            n = last - first + 1
            facts = [f"耗時 {r['elapsed']:.0f} 秒"]
            if f.has_video and r["elapsed"] > 0:
                facts.append(f"平均 {n / r['elapsed']:.1f} 幀/秒（{n:,} 幀）")
            if size is not None:
                facts.append(f"檔案 {sysmem.gb(size)}")
            if prog.peak:
                facts.append(f"記憶體最高 {sysmem.gb(prog.peak)}")
            QMessageBox.information(self, "匯出完成", f"{made}\n{what}{stems}\n" + "，".join(facts) + extra)

        self.run_task(work, done, failed, prog.set_progress)

    # -- settings ---------------------------------------------------------------------------------
    def export_still(self):
        """截取並匯出當下幀: the frame at the playhead (of the open level) as a picture file."""
        if not self.proj:
            return
        view = json.loads(json.dumps(self.view()))
        view["fps"] = self.proj["fps"]
        name = workspace.project_name(self.path) if self.path else "KiaseCut"
        stamp = timecode(self.playhead_us(), self.fps).replace(":", "-")
        folder = workspace.exports_dir(self.root) if self.root else os.path.join(os.path.expanduser("~"), "Pictures")
        try:
            last = json.loads(self.settings().value("still_spec", "") or "{}")
        except (TypeError, ValueError):
            last = {}
        dlg = StillDialog(self, os.path.join(folder, f"{name} {stamp}.png"), view["width"], view["height"], last)
        if dlg.exec() != QDialog.Accepted:
            return
        out, size, alpha, bg, quality, st = dlg.options()
        if not out:
            return
        self.settings().setValue("still_spec", json.dumps(st))
        t = self.playhead_us()
        cache = self.cache_dir()

        def work(_progress):
            os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
            return renderexport.still(view, t, size, out, alpha, bg, quality, cache)

        def done(errors):
            self.statusBar().showMessage(f"已匯出目前畫面：{out}" + (f"（{len(errors)} 個片段畫不出來）" if errors else ""),
                                         6000)

        self.run_task(work, done, lambda m: QMessageBox.warning(self, "匯出目前畫面", m))

    def documents_dir(self):
        if sys.platform == "android" and androidfs.documents():          # (the shared Documents folder, where the user can find projects)
            return androidfs.documents()
        return QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or os.path.expanduser("~")

    def app_root(self):
        """設定 > 根資料夾: where the Library, new projects, autosaves, layouts and tools go unless
        set apart (Documents/KiaseCut to start with)."""
        s = self.settings().value("root_dir")
        return library.norm(str(s)) if s else os.path.join(self.documents_dir(), userlib.APP_FOLDER).replace("\\", "/")

    def autosave_folder(self):
        s = self.settings().value("autosave_dir")
        return library.norm(str(s)) if s else recovery.folder_in(self.app_root())

    def default_library_root(self):
        return os.path.join(self.app_root(), "Library").replace("\\", "/")

    def library_root(self):
        s = self.settings().value("library_dir")
        return library.norm(str(s)) if s else self.default_library_root()

    def default_cache_base(self):
        """Where project caches go by default (設定 > 緩存位置 > 預設): the user's cache folder."""
        base = QStandardPaths.writableLocation(QStandardPaths.GenericCacheLocation)   # (~/.cache, AppData/Local/cache)
        return os.path.join(base, "KiaseCut", "projects").replace("\\", "/")

    def cache_mode(self):
        m = str(self.settings().value("cache_mode", workspace.CACHE_DEFAULT))
        return m if m in workspace.CACHE_MODES else workspace.CACHE_DEFAULT

    def cache_custom(self):
        d = self.settings().value("cache_custom_dir")
        return library.norm(str(d)) if d else ""

    def cache_base_of(self, mode, custom):
        """The folder project caches go in for a 緩存位置 choice; None: in the project (Cache/)."""
        if mode == workspace.CACHE_PROJECT:
            return None
        return custom if mode == workspace.CACHE_CUSTOM and custom else self.default_cache_base()

    def set_cache_base(self, base):
        """Cache in a new place from now on (what was cached stays where it was)."""
        if base == self.cache_base:
            return
        self.cache_base = base
        if self.proj is not None:
            if self.timeline.peaks is not None:
                self.timeline.peaks.dir = os.path.join(self.cache_dir(), "peaks")
            self.rebuild()                            # the player's sound cache follows

    def clear_project_cache(self):
        """Delete the open project's cache wherever it is (in the project, in the default place,
        in the folder picked in 設定): it is made again when needed."""
        if self.proj is None:
            return
        if self.root:
            dirs = workspace.cache_dirs(self.root, workspace.cache_id(self.proj, self.root),
                                        [self.default_cache_base(), self.cache_custom()])
        else:
            dirs = [self.cache_dir()]
        size = sum(workspace.folder_size(d) for d in dirs if os.path.isdir(d))
        if not size:
            self.statusBar().showMessage("這個專案沒有緩存", 4000)
            return
        if not questions.question(self, "clear_cache", "清除專案緩存",
                            f"要刪除這個專案的緩存（{workspace.show_size(size)}）嗎？\n"
                            "波形、聲音、文字和遮罩的圖片、代理圖片會在需要時重新產生，素材和專案不受影響。"):
            return
        freed = workspace.clear_cache(dirs)
        self.statusBar().showMessage(f"已清除專案緩存（{workspace.show_size(freed)}）", 4000)

    def autosave_min(self):
        try:
            return max(1, int(self.settings().value("autosave_min", 5)))
        except (TypeError, ValueError):
            return 5

    def autosave_limit(self):
        """How many autosave files are kept."""
        try:
            return max(1, int(self.settings().value("autosave_limit", recovery.LIMIT)))
        except (TypeError, ValueError):
            return recovery.LIMIT

    def open_settings(self):
        dlg = SettingsDialog(self, self.ulib.root if self.ulib else self.library_root(), self.default_library_root(),
                             self.default_location(), self.autosave_min(), gpu.enabled, self.autosave_limit(),
                             self.autosave_dir or self.autosave_folder(),
                             self.cache_mode(), self.cache_custom(), self.default_cache_base(),
                             root_dir=self.app_root(), autosave_custom=str(self.settings().value("autosave_dir") or ""),
                             ui_scale=ui_scale())
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values()
        s = self.settings()
        if v["root"] and v["root"] != self.app_root():
            s.setValue("root_dir", v["root"])
        s.setValue("autosave_dir", v["autosave_dir"])
        if v["project_dir"] != str(s.value("project_dir") or ""):
            s.setValue("project_dir_chosen", True)
        s.setValue("project_dir", v["project_dir"])
        s.setValue("autosave_min", v["autosave_min"])
        s.setValue("autosave_limit", v["autosave_limit"])
        s.setValue("gpu", v["gpu"])
        scale_changed = v["ui_scale"] != ui_scale()
        s.setValue("ui_scale", v["ui_scale"])
        inertia.state.update(v["inertia"])
        inertia.save(s)
        s.setValue("cache_mode", v["cache_mode"])
        s.setValue("cache_custom_dir", v["cache_custom"])
        self.set_cache_base(self.cache_base_of(v["cache_mode"], v["cache_custom"]))
        gpu.enabled = v["gpu"]
        self.autosave_timer.setInterval(v["autosave_min"] * 60 * 1000)
        if self.autosave_dir:
            recovery.prune(self.autosave_dir, v["autosave_limit"])
        if v["library"] != (self.ulib.root if self.ulib else None):
            self.change_library_root(v["library"], v["copy_library"])
        if scale_changed:
            self.restart_for_scale()

    def restart_for_scale(self):
        """界面縮放 only takes hold as the program starts: offer to start it again now, with the project that is open."""
        if self.tasks:
            QMessageBox.information(self, "界面縮放", "有工作正在進行（匯出、載入…），所以沒有重新開啟。\n"
                                    "新的縮放比例下次開啟程式時生效。")
            return
        ans = QMessageBox.question(self, "界面縮放", "要現在重新開啟程式，讓新的縮放比例生效嗎？\n"
                                   "（未儲存的修改會先問你要不要儲存，開著的專案會再開起來。）")
        if ans != QMessageBox.Yes:
            return
        if self.dirty:
            if not self.maybe_save():
                return
            self.dirty = False                           # (the answer was 不儲存: closing is not asked again)
        args = ["-m", "kiasecut"] + ([self.path] if self.path and os.path.exists(self.path) else [])
        self.close()
        if self.closing:                                 # (closed: the new program starts when this one is gone)
            QProcess.startDetached(sys.executable, args)

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
        self.nodes.set_user_filters(mine)
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
        name, ok = inplace.ask_name(self, target["name"])
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
        if not questions.question(self, "delete_library", "刪除", f"要刪除這個{what}嗎？它們會被移到資源回收筒。\n"
                            f"（Library 是所有專案共用的）{note}"):
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
        "filters": "GLSL 濾鏡 (*.glsl)", "textstyles": "文字樣式 (*.json)", "compounds": "複合片段 (*.kccomp)",
        "presets": "效果預設 (*.kcfx)"}

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
            self.panels.show("userlib")
            self.ulpanel.show_category(key if key in todo else next(iter(todo)))
            self.statusBar().showMessage(f"已加入 {sum(len(v) for v in todo.values())} 個檔案到 Library", 4000)

        self.run_task(work, done, lambda m: QMessageBox.critical(self, "加入失敗", m),
                      lambda p: self.statusBar().showMessage(f"複製中… {int(p * 100)}%"))

    def ul_use_files(self, files, place):
        """Files that are in the Library are used where they are: onto the timeline when
        dropped there (place = (track id, start us, across)), else just shown in the Library."""
        items = []
        for f in files:
            it = self.ulib.item_for_path(f)
            if it["kind"] in ("image", "video", "audio"):
                items.append(it)
        if not items:
            return
        self.panels.show("userlib")
        cat = userlib.category_of(items[0]["path"], self.ulib.root)
        if cat in dict(userlib.CATEGORIES):
            self.ulpanel.show_category(cat)
        if place is None:
            self.statusBar().showMessage(f"{len(items)} 個檔案已經在 Library 裡，不需要複製到專案", 5000)
            return
        track_id, start, across = place
        self._select_new(self.apply_root("加入 Library 素材", lambda root: library.place_items(
            self.container(root), items, track_id or None, start, across), select=lambda cs: cs[-1]["id"]))

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
        elif key == "compounds":
            menu.addAction("放到播放頭", lambda: self.place_library_compound(it["path"], "", self.playhead_us()))
        elif key == "presets":
            menu.addAction("套用到選取的片段", lambda: self.use_effect_preset(it["path"], "", None, clip_ids=True))
            menu.addAction("放成濾鏡片段（播放頭位置）", lambda: self.use_effect_preset(it["path"], "", self.playhead_us(),
                                                                                  clip_ids=False))
        elif key == "textstyles":
            menu.addAction("套用到選取的文字", lambda: self.apply_text_style(it["path"], new_if_none=False))
            menu.addAction("用這個樣式新增文字", lambda: self.apply_text_style(it["path"], force_new=True))

    # -- filters ----------------------------------------------------------------------------------
    def _fill_filter_menu(self, menu, fn):
        menu.clear()
        menu.addAction("節點效果（用節點編輯器組合）", lambda: fn(fx.GRAPH))
        menu.addSeparator()
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

    def add_filter_clip(self, ref, track_id="", start_us=None, effect=None):
        """A filter as a clip of its own: it works on everything below it while it lasts (with
        effect: a copy of that one, settings and all)."""
        if not self.proj:
            return
        start = self.playhead_us() if start_us is None else start_us
        self.apply("新增濾鏡片段", lambda lvl: edit.add_filter_clip(lvl, ref, start, track_id=track_id or None,
                                                                 effect=effect, own_track=self.editing_static()),
                   select=lambda c: c["id"])

    def on_filter_dropped(self, payload, cid, track_id, start_us):
        """A filter dragged from the VFX tab, or an effect from the effects panel (a copy with
        its settings): onto a clip it joins that clip's effects (all the selected ones when it is
        one of them), elsewhere it becomes a filter clip."""
        ref, effect, _src = dropped_fx(payload)
        if not cid:
            self.add_filter_clip(ref, track_id, start_us, effect)
            return
        sel = self.timeline.selected_ids
        ids = [c["id"] for c in self.timeline.selected_clips_primary_first()
               if c["type"] in edit.VISUAL] if cid in sel else [cid]
        if cid not in ids:                                   # (a selected layer inside a group is not on the level's rows:
            ids = [cid]                                      # dropping on it must not do nothing)
        self.apply("複製效果" if effect else "新增效果", lambda lvl: [edit.put_effect(lvl, k, effect or ref) for k in ids])
        self.panels.show("effects")

    def effect_dropped(self, ids, payload, index):
        """Something dropped among the effects of clips ids (the main one's, the others alike) at
        place index: one of its own effects moves there, any other effect is copied there, a
        filter of the VFX tab is added there - in each of them (批量)."""
        ref, effect, src = dropped_fx(payload)
        try:
            c = edit.find(self.container(), ids[0])[1]
        except (edit.EditError, IndexError):
            return
        mine = [e["id"] for e in c.get("effects") or []]
        if effect and src == ids[0] and effect["id"] in mine:
            if index not in (mine.index(effect["id"]), mine.index(effect["id"]) + 1):     # (where it is)
                self.fx_each("調整效果順序", ids, effect["id"],
                             lambda lvl, cid, e: edit.move_effect_to(lvl, cid, e, index))
        else:
            self.apply(("複製效果" if effect else "新增效果") + many(ids),
                       lambda lvl: [edit.put_effect(lvl, cid, effect or ref, index) for cid in ids])

    def effect_swapped(self, ids, eid, payload):
        """A filter or an effect dropped with Alt onto effect eid of clips ids: that effect (and the
        alike ones of the others, 批量) becomes it, keeping its values when the parameters line up
        (edit.swap_filter)."""
        ref, effect, _src = dropped_fx(payload)
        if effect and effect["id"] == eid:
            return
        kept = []
        self.fx_each("替換濾鏡", ids, eid, lambda lvl, cid, e: kept.append(edit.swap_filter(lvl, cid, e, effect or ref)))
        if kept:
            self.statusBar().showMessage("參數位置相同，沿用原本的參數" if all(kept) else
                                         "參數不同，改用" + ("拖過來的效果的設定" if effect else "新濾鏡的預設值"), 4000)

    def effects_dropped(self, ids, payload):
        """A filter or an effect (a copy with its settings) dropped in the effects panel while
        the selected clips' effects are not alike: it replaces them all (add_effects_to)."""
        ref, effect, _src = dropped_fx(payload)
        self.add_effects_to(ids, [effect or ref], "複製效果" if effect else "新增效果")

    def use_effect_preset(self, path, track_id, start_us, clip_ids=None):
        """效果預設: its effects added to the selected picture clips (clip_ids True; None: when some
        are selected and it was not dropped on a track), else a filter clip carrying them all at
        start_us (the playhead when None)."""
        try:
            effects = userlib.load_preset(path)
        except (OSError, ValueError) as exc:
            self.statusBar().showMessage(f"讀不到效果預設：{exc}", 5000)
            return
        ids = [c["id"] for c in self.timeline.selected_clips_primary_first() if c["type"] in edit.VISUAL]
        if clip_ids is None:
            clip_ids = bool(ids) and not track_id
        if clip_ids:
            if not ids:
                self.statusBar().showMessage("先在時間軸選一個畫面片段", 4000)
                return
            self.apply("套用效果預設", lambda lvl: [edit.put_effect(lvl, cid, e) for cid in ids for e in effects])
            self.panels.show("effects")
            return
        start = self.playhead_us() if start_us is None else start_us

        def fn(lvl):
            c = edit.add_filter_clip(lvl, effects[0]["filter"], start, track_id=track_id or None, effect=effects[0],
                                     own_track=self.editing_static())
            for e in effects[1:]:
                edit.put_effect(lvl, c["id"], e)
            return c
        self.apply("新增濾鏡片段", fn, select=lambda c: c["id"])

    def save_effect_preset(self, folder, effects=None, default_name="我的效果"):
        """存選取片段的效果: the selected clip's effects, as they are, as a 效果預設 in the Library (effects: these
        instead - a node effect saved from the node editor)."""
        if effects is None:
            c = next((k for k in self.timeline.selected_clips_primary_first() if k.get("effects")), None)
            if c is None:
                self.statusBar().showMessage("先在時間軸選一個有效果的片段", 5000)
                return
            effects = c["effects"]
        if not self.ulib:
            self.statusBar().showMessage("先開啟專案，Library 才找得到", 5000)
            return
        name, ok = QInputDialog.getText(self, "存成效果預設", "名稱", text=default_name)
        if not ok or not name.strip():
            return
        base = library.folder_dir(self.ulib.proj("presets"), self.ulib.mirror("presets"), folder)
        try:
            userlib.save_preset(base, name.strip(), effects, self.ulib.root)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "存成效果預設", str(exc))
            return
        self.ul_epoch += 1
        self.request_ul_sync(0)
        self.panels.show("userlib")
        self.ulpanel.show_category("presets")
        self.statusBar().showMessage(f"已存到 Library > 效果預設：{name.strip()}", 4000)

    def save_node_preset(self, eid):
        """存成自定效果 in the node editor: this node effect (graph, settings, pictures) as a 效果預設."""
        cid = self.node_clip()
        if not cid:
            return
        e = next((x for x in edit.find(self.container(), cid)[1].get("effects") or [] if x["id"] == eid), None)
        if e is not None:
            self.save_effect_preset("", [e])

    def apply_filter_to_selected(self, ref):
        ids = [c["id"] for c in self.timeline.selected_clips_primary_first() if c["type"] in edit.VISUAL]
        if not ids:
            self.statusBar().showMessage("先在時間軸選一個畫面片段（圖片、影片、文字、複合片段）", 4000)
            return
        self.apply("新增效果", lambda lvl: [edit.add_effect(lvl, cid, ref) for cid in ids])
        self.panels.show("effects")

    # -- VFX Nodes (project.py _share_vfx): node effects many clips share ----------------------------------
    def add_vfx_to(self, ids, vid):
        """新增效果 > 節點效果 on clips ids: a use of VFX Node vid, or ("" ) of a new blank one, named first."""
        if not self.proj:
            return
        name = None
        if not vid:
            name, ok = QInputDialog.getText(self, "新增 VFX Node", "名稱",
                                            text=f"VFX Node {len(self.proj.get('vfx_nodes') or {}) + 1}")
            if not ok or not name.strip():
                return

        def fn(root):
            v = vid or edit.new_vfx_node(root, name)
            level = self.container(root)
            return [edit.add_vfx_effect(root, cid, v, level=level) for cid in ids]
        self.apply_root("新增效果" + many(ids), fn)

    def selected_visual_ids(self):
        return [c["id"] for c in self.timeline.selected_clips_primary_first() if c["type"] in edit.VISUAL]

    def apply_vfx_to_selected(self, vid):
        ids = self.selected_visual_ids()
        if not ids:
            self.statusBar().showMessage("先在時間軸選一個畫面片段（圖片、影片、文字、複合片段）", 4000)
            return
        self.add_vfx_to(ids, vid)
        self.panels.show("effects")

    def select_vfx_use(self, vid):
        """Select the first clip that uses VFX Node vid, and open the node editor on it."""
        use = next(iter(project.vfx_uses(self.proj).get(vid) or ()), None)
        if use is None:
            self.statusBar().showMessage("還沒有片段在用這個 VFX Node：先套用到一個片段", 4000)
            return
        c, e = use
        level = self.container()
        if all(k["id"] != c["id"] for k in project.walk_clips(level["tracks"])):
            self.statusBar().showMessage("它用在別的時間線或複合片段裡：先打開那裡", 5000)
            return
        self.timeline.select(c)
        self.open_node_editor(e["id"])

    def rename_vfx(self, vid):
        m = (self.proj.get("vfx_nodes") or {}).get(vid)
        if m is None:
            return
        name, ok = QInputDialog.getText(self, "重新命名 VFX Node", "名稱", text=m["name"])
        if ok and name.strip():
            self.apply_root("重新命名 VFX Node", edit.rename_vfx_node, vid, name)

    def delete_vfx(self, vid):
        n = len(project.vfx_uses(self.proj).get(vid) or ())
        if questions.question(self, "delete_vfx_node", "刪除 VFX Node",
                              "刪除這個 VFX Node？" + (f"\n{n} 個使用它的片段會各自留下一份節點效果。" if n else "")):
            self.apply_root("刪除 VFX Node", edit.delete_vfx_node, vid)

    def vfx_effect(self, vid):
        """VFX Node vid as an effect (what a 效果預設 file keeps): its graph, sources and the values uses start at."""
        m = self.proj["vfx_nodes"][vid]
        e = fx.new_effect(fx.GRAPH, "")
        e.update(graph=m["graph"], sources=m.get("sources") or {})
        e["params"].update(m.get("params") or {})
        return e

    def save_vfx_to_library(self, vid):
        m = (self.proj.get("vfx_nodes") or {}).get(vid)
        if m is not None:
            self.save_effect_preset("", [self.vfx_effect(vid)], m["name"])

    def import_vfx_from_library(self):
        """從 Library 匯入: a node effect of a 效果預設 file becomes a VFX Node of the project."""
        if not self.ulib or not self.proj:
            self.statusBar().showMessage("先開啟專案，Library 才找得到", 5000)
            return
        items = sorted(self.ulib.lib("presets")["items"], key=lambda it: it["name"])
        if not items:
            self.statusBar().showMessage("Library 的「效果預設」還沒有檔案：先在 VFX Node 上按右鍵 > 存到 Library", 5000)
            return
        menu = QMenu(self)
        for it in items:
            menu.addAction(os.path.splitext(it["name"])[0], lambda _=False, it=it: self._import_vfx(it))
        menu.exec(QCursor.pos())

    def _import_vfx(self, it):
        try:
            nodes = [e for e in userlib.load_preset(it["path"]) if e.get("filter") == fx.GRAPH]
        except (OSError, ValueError) as exc:
            self.statusBar().showMessage(f"讀不到效果預設：{exc}", 5000)
            return
        if not nodes:
            self.statusBar().showMessage("這個預設裡沒有節點效果", 4000)
            return
        base = os.path.splitext(it["name"])[0]

        def fn(root):
            for i, e in enumerate(nodes):
                edit.new_vfx_node(root, base if len(nodes) == 1 else f"{base} {i + 1}", e["graph"], e.get("sources") or {}, e["params"])
        self.apply_root("從 Library 匯入 VFX Node", fn)
        self.panels.show("vfxnodes")

    def add_effects_to(self, ids, whats, label="新增效果"):
        """Filters or effects (put_effect's) added to each of clips ids (批量: the picture clips of
        a selection), one undo step; when the clips' effects are not the same filters in the same
        order, they replace all of them."""
        level = self.container()
        if len({tuple(e["filter"] for e in edit.find(level, cid)[1].get("effects") or []) for cid in ids}) > 1:
            self.apply("覆寫效果" + many(ids), lambda lvl: [edit.replace_effects(lvl, cid, whats) for cid in ids])
        else:
            self.apply(label + many(ids), lambda lvl: [edit.put_effect(lvl, cid, w) for cid in ids for w in whats])

    def fx_targets(self, ids, group):
        """[(clip id, its group)] for an effect's group (fx:<id> / fxmask:<id> / fxmix:<id>) of clip ids[0] in
        each of clips ids: the same filter at the same place (same_group), where it has it."""
        level = self.container()
        try:
            first = edit.find(level, ids[0])[1]
        except (edit.EditError, IndexError):
            return []
        out = []
        for cid in ids:
            try:
                g = same_group(first, edit.find(level, cid)[1], group)
            except edit.EditError:
                continue
            if g is not None:
                out.append((cid, g))
        return out

    def fx_each(self, label, ids, eid, fn):
        """fn(level, clip id, its effect id) for effect eid of clip ids[0] and the alike ones of
        the other clips ids (批量), as one undo step."""
        targets = self.fx_targets(ids, "fx:" + eid)

        def each(level):
            for cid, g in targets:
                fn(level, cid, g.split(":", 1)[1])

        self.apply(label + many(targets), each)

    # -- the node editor (節點): one clip's node effect, every change an undo step ------------------------
    def node_clip(self):
        """The clip the node editor shows: the only one selected."""
        sel = self.timeline.selected_clips_primary_first()
        return sel[0]["id"] if len(sel) == 1 else None

    def open_node_editor(self, eid):
        self.panels.show("nodes")
        self.nodes.show_clip(self.timeline.selected_clips_primary_first()[0], eid)

    def on_node_add(self, eid, node, x, y):
        cid = self.node_clip()
        if cid:
            made = []
            self.apply("新增節點", lambda lvl: made.append(edit.add_graph_node(lvl, cid, eid, node, x, y)))
            if made:
                self.nodes.carry(made)                         # (stuck to the pointer till a click, as Blender's)

    def on_node_remove(self, eid, ids):
        cid = self.node_clip()
        if cid:
            self.apply("刪除節點", lambda lvl: [edit.remove_graph_node(lvl, cid, eid, n) for n in ids])

    def on_node_connect(self, eid, src, dst, socket, out=""):
        cid = self.node_clip()
        if cid:
            self.apply("連接節點", lambda lvl: edit.connect_graph(lvl, cid, eid, src, dst, socket, out))

    def on_node_expose(self, eid, src, dst, socket):
        cid = self.node_clip()
        if cid:
            self.apply("新增效果參數", lambda lvl: edit.expose_graph_param(lvl, cid, eid, src, dst, socket))

    def on_node_item(self, eid, nid, action, sock, name, src, out):
        cid = self.node_clip()
        if cid:
            label = {"add": "新增選項", "rename": "重新命名選項", "remove": "刪除選項"}.get(action, "移動選項")
            self.apply(label, lambda lvl: edit.node_item(lvl, cid, eid, nid, action, sock, name, src, out))

    def on_node_remove_exposed(self, eid, name):
        cid = self.node_clip()
        if cid:
            self.apply("刪除效果參數", lambda lvl: edit.remove_exposed_param(lvl, cid, eid, name))

    def on_node_exposed_edited(self, eid, name, fields):
        cid = self.node_clip()
        if cid:
            self.apply("修改效果參數", lambda lvl: edit.edit_exposed_param(lvl, cid, eid, name, fields),
                       merge=("exposed", cid, eid, name, tuple(fields)))

    def on_node_exposed_moved(self, eid, name, delta):
        cid = self.node_clip()
        if cid:
            self.apply("移動效果參數", lambda lvl: edit.move_exposed_param(lvl, cid, eid, name, delta))

    def on_node_cut(self, eid, pairs):
        cid = self.node_clip()
        if cid:
            self.apply("切斷連線", lambda lvl: [edit.disconnect_graph(lvl, cid, eid, dst, sock) for dst, sock in pairs])

    def on_node_insert(self, eid, nid, x, y, src, dst, socket, out):
        cid = self.node_clip()
        if cid:
            def do(lvl):
                edit.move_graph_nodes(lvl, cid, eid, {nid: (x, y)})
                edit.insert_graph_node(lvl, cid, eid, nid, src, dst, socket, out)
            self.apply("把節點放進連線", do)

    def on_node_add_linked(self, eid, node, x, y, src, out):
        """A node added where a link was let go: that link goes into its first picture input."""
        cid = self.node_clip()
        if not cid:
            return
        made = []

        def do(lvl):
            nid = edit.add_graph_node(lvl, cid, eid, node, x, y)
            made.append(nid)
            g = next(e for e in edit.find(lvl, cid)[1]["effects"] if e["id"] == eid)["graph"]
            ins = [s for s, _ in nodegraph.sockets(g["nodes"][nid]) if not s.startswith(nodegraph.PARAM)]
            if ins:
                edit.connect_graph(lvl, cid, eid, src, nid, ins[0], out)
        self.apply("新增節點", do)
        if made:
            self.nodes.carry(made)

    def on_node_add_feeding(self, eid, node, x, y, dst, socket):
        """A node added where a link dragged out of an input was let go: its output goes into that input, a constant keeping
        the value the input had."""
        cid = self.node_clip()
        if not cid:
            return
        made = []
        self.apply("新增節點", lambda lvl: made.append(edit.add_graph_node_feeding(lvl, cid, eid, node, x, y, dst, socket)))
        if made:
            self.nodes.carry(made)

    def on_node_media(self, eid, ids, paths, x, y):
        """Pictures, videos and compounds dragged into the node editor: a source node each, showing it."""
        cid = self.node_clip()
        if not cid:
            return
        found = []                                         # [(kind, what set_effect_source_media takes)]
        for ident in ids:
            if ident.startswith(textpresets.PREFIX):           # a text preset (內建素材 > 文字): a text node set the same way
                style = textpresets.fields(ident)
                if style is not None:
                    found.append(("text", style))
                continue
            if ident.startswith(assets.PREFIX):                # a built-in shape (內建素材): a shape node with all its parameters
                parsed = assets.parse(ident)
                if parsed and parsed[0].cat == "shape":
                    found.append(("asset", {"key": parsed[0].key, "colors": parsed[1:3]}))
                continue
            if ident.startswith("cmp:"):
                comp = self.proj.get("compounds", {}).get(ident[4:])
                if comp is not None:
                    found.append(("compound", {"compound": (ident[4:], comp)}))
                continue
            try:
                if ident.startswith("mu"):
                    key, it = self.ulib.find(ident)
                    if it is None or key not in ("videos", "images"):
                        continue
                    path = it["path"]
                    kind = "image" if key == "images" else "video"
                    info = library.probe(path)
                else:
                    it = library.item(self.proj, ident)
                    path, kind = it.get("path"), it.get("kind")
                    info = it if it.get("width") else library.probe(path)
            except Exception:
                continue
            if kind in ("image", "video") and path:
                found.append((kind, self._node_media(kind, path, info)))
        for path in paths:
            try:
                info = library.probe(path.replace("\\", "/"))
            except Exception:
                continue
            if info.get("kind") in ("image", "video") and info.get("width"):
                found.append((info["kind"], self._node_media(info["kind"], path.replace("\\", "/"), info)))
        if not found:
            self.statusBar().showMessage("節點編輯器只收圖片、影片、複合片段、內建形狀和文字", 4000)
            return
        made = []
        level = self.nodes.level

        def do(lvl):
            for i, (kind, media) in enumerate(found):
                if kind == "text":
                    nid = edit.add_graph_node(lvl, cid, eid, {"type": nodegraph.SOURCE, "kind": "text", "preset": media, **({"group": level} if level else {})}, x + 40 * i, y + 40 * i)
                    made.append(nid)
                    continue
                if kind == "asset":
                    nid = edit.add_graph_node(lvl, cid, eid, {"type": nodegraph.SOURCE, "kind": "shape", "asset": media, **({"group": level} if level else {})}, x + 40 * i, y + 40 * i)
                    made.append(nid)
                    continue
                nid = edit.add_graph_node(lvl, cid, eid, {"type": nodegraph.SOURCE, "kind": kind, **({"group": level} if level else {})}, x + 40 * i, y + 40 * i)
                edit.set_effect_source_media(lvl, cid, eid, nid, **media)
                made.append(nid)
        self.apply("拖入節點", do)
        if made:
            self.nodes.select(made[-1])

    @staticmethod
    def _node_media(kind, path, info):
        if kind == "image":
            return {"image": (path, info.get("width"), info.get("height"))}
        return {"video": (path, info.get("width"), info.get("height"), info.get("duration_us"))}

    def on_node_group(self, eid, ids):
        cid = self.node_clip()
        if cid:
            made = []
            self.apply("群組節點", lambda lvl: made.append(edit.group_graph_nodes(lvl, cid, eid, ids)))
            if made:
                self.nodes.select(made[0])

    def on_node_ungroup(self, eid, gid):
        cid = self.node_clip()
        if cid:
            self.apply("拆開群組", lambda lvl: edit.ungroup_graph(lvl, cid, eid, gid))

    def on_node_group_renamed(self, eid, gid, label):
        cid = self.node_clip()
        if cid:
            self.apply("群組名稱", lambda lvl: edit.rename_graph_group(lvl, cid, eid, gid, label))

    def on_node_group_port(self, eid, gid, member, socket, out, name, old_member, old_socket):
        cid = self.node_clip()
        if not cid:
            return

        def do(lvl):
            if old_member:
                edit.group_unplug(lvl, cid, eid, gid, old_member, old_socket)
            edit.group_port(lvl, cid, eid, gid, member, socket=socket or None, out=out, name=name or None)
        self.apply("群組的連線", do)

    def on_node_group_unplug(self, eid, gid, member, socket, output):
        cid = self.node_clip()
        if cid:
            self.apply("群組的連線", lambda lvl: edit.group_unplug(lvl, cid, eid, gid, member or None, socket or None, output))

    def on_node_viewer(self, eid, nid, out):
        cid = self.node_clip()
        if cid:
            self.apply("預覽節點", lambda lvl: edit.set_graph_viewer(lvl, cid, eid, nid or None, out))

    def on_node_paste(self, eid, data, x, y):
        cid = self.node_clip()
        if cid:
            made = []
            self.apply("貼上節點", lambda lvl: made.extend(edit.paste_graph_nodes(lvl, cid, eid, data, x, y, self.nodes.level or None)))
            if made:
                self.nodes.carry(made)

    def on_node_frame(self, eid, nid, change):
        cid = self.node_clip()
        if cid:
            self.apply("編輯框架", lambda lvl: edit.set_graph_frame(lvl, cid, eid, nid, **change))

    def on_node_width(self, eid, nid, width):
        cid = self.node_clip()
        if cid:
            self.apply("調整節點寬度", lambda lvl: edit.set_graph_node_width(lvl, cid, eid, nid, width))

    def on_node_lines(self, eid, nid, lines):
        cid = self.node_clip()
        if cid:
            self.apply("調整文字框高度", lambda lvl: edit.set_graph_node_lines(lvl, cid, eid, nid, lines))

    def on_node_reroute(self, eid, spots):
        cid = self.node_clip()
        if cid:
            self.apply("新增繞線點", lambda lvl: edit.add_graph_reroutes(lvl, cid, eid, spots))

    def on_node_duplicate(self, eid, ids):
        cid = self.node_clip()
        if cid:
            made = []
            self.apply("複製節點", lambda lvl: made.extend(edit.duplicate_graph_nodes(lvl, cid, eid, ids)))
            if made:
                self.nodes.carry(made, remove=False)

    def on_node_dissolve(self, eid, ids):
        cid = self.node_clip()
        if cid:
            self.apply("刪除節點（保留連線）", lambda lvl: [edit.dissolve_graph_node(lvl, cid, eid, n) for n in ids])

    def on_node_disconnect(self, eid, dst, socket):
        cid = self.node_clip()
        if cid:
            self.apply("中斷連線", lambda lvl: edit.disconnect_graph(lvl, cid, eid, dst, socket))

    def on_node_move(self, eid, positions):
        cid = self.node_clip()
        if cid:
            self.apply("移動節點", lambda lvl: edit.move_graph_nodes(lvl, cid, eid, positions))

    def on_node_mute(self, eid, ids, on):
        cid = self.node_clip()
        if cid:
            self.apply("停用節點" if on else "啟用節點", lambda lvl: [edit.mute_graph_node(lvl, cid, eid, n, on) for n in ids])

    def on_node_selected(self, eid, nid):
        """A node picked in the node editor: a picture / video / compound / track one is placed on the preview
        as a mask is (the node's own settings are in the 效果 panel)."""
        cid = self.node_clip()
        want = None
        if cid and nid:
            c = edit.find(self.container(), cid)[1]
            e = next((x for x in c.get("effects") or [] if x["id"] == eid), None)
            if e is not None and nid in (e.get("sources") or {}):
                want = (eid, nid)
        self.node_source = want
        self.node_mask_mode()

    def on_fx_param_edited(self, ids, group, key, value):
        """A value of an effect typed in the effects panel: set on the alike effect of every clip
        ids (each at its own playhead time, so keyframed ones get or edit the keyframe there)."""
        targets = self.fx_targets(ids, group)
        if not targets:
            return
        times = self.clip_times([cid for cid, _g in targets])

        def each(level):
            for cid, g in targets:
                edit.set_param(level, cid, g, key, value, times[cid])

        self.apply("調整效果" + many(targets), each, merge=("param", tuple(ids), group, key, round(times[ids[0]])))

    def on_fx_live_edit(self, ids, group, key, value):
        """An effect's value being typed or scrubbed: the preview shows it at once, on each clip."""
        targets = dict(self.fx_targets(ids, group))
        view = self.snapshot()
        for c in project.walk_clips(view["tracks"]):
            if c["id"] in targets:
                group_holder(c, targets[c["id"]], create=True)[key] = value
        self.player.worker.set_view(view, self.cache_dir())

    def on_backdrop_chosen(self, ids, on, hide):
        """套用至背景 / 隱藏本體 for clips ids (a filter clip has none)."""
        level = self.container()
        ids = [cid for cid in ids if edit.find(level, cid)[1]["type"] != "filter"]
        self.apply(("套用至背景" if on else "取消套用至背景" if on is not None else "隱藏本體") + many(ids),
                   lambda lvl: [edit.set_backdrop(lvl, cid, on, hide) for cid in ids])

    def browse_effect(self, ids):
        start = self.ulib.mirror("filters") if self.ulib else ""
        paths, _ = QFileDialog.getOpenFileNames(self, "選擇濾鏡檔案", str(start), "GLSL 濾鏡 (*.glsl)")
        if paths:                                   # several at once: one undo step
            self.add_effects_to(ids, [library.norm(p) for p in paths])

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
        self.panels.show("userlib")
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
        if getattr(self, "nodes", None) is not None:
            self.nodes.fonts = found                # (a text node's font list)
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
        rows = [(p, fonts.guess(p, self.fonts, known), "gone") for p in gone]
        if not auto:                                   # every font the project uses
            used = fonts.used(self.proj)
            rows += [(p, mapping[p], "mapped") for p in sorted(mapping) if p in used and p not in gone]
            rows += [(p, None, "here") for p in sorted(used) if p not in gone and p not in mapping
                     and os.path.exists(p)]
            if not rows:
                self.statusBar().showMessage("專案裡還沒有文字", 4000)
                return
        if not rows:
            return
        if self.font_dlg is not None:
            self.font_dlg.close()
        dlg = FontMapDialog(self, rows, self.fonts, fonts.usage(self.proj))
        dlg.applied.connect(self.apply_font_map)
        dlg.replaced.connect(self.replace_fonts)
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

    def replace_fonts(self, swaps):
        """字體對應's 換成: {font file: new font file} in every text of the project (an edit)."""
        n = self.apply_root("更換字體", edit.replace_fonts, swaps)
        if n:
            self.statusBar().showMessage(f"已更換 {len(swaps)} 個字體（{n} 個文字）", 4000)

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
        self.panels.show("userlib")
        self.ulpanel.show_category("textstyles")
        self.statusBar().showMessage(f"已存到 Library > 文字樣式：{name.strip()}", 4000)

    # -- layouts (佈局) -----------------------------------------------------------------------------
    def layout_dir(self):
        return layouts.folder_in(self.app_root())

    def layout_keys(self):
        return ([layouts.builtin_key(i) for i, _ in layouts.BUILTIN]
                + [layouts.user_key(n) for n in layouts.list_user(self.layout_dir())])

    def _live_layout(self, key):
        """The panels of layout key as last left in this program, or None."""
        raw = self.settings().value("layout_live/" + key)
        if not raw:
            return None
        try:
            return layouts.unpack(json.loads(str(raw)))
        except (ValueError, TypeError):
            return None

    def keep_layout(self):
        """Remember the panels as they are now for the layout they are in (each layout keeps
        its own arrangement while switching between them, as Blender's workspaces)."""
        if self.layout_key:
            self.settings().setValue("layout_live/" + self.layout_key,
                                     json.dumps(layouts.pack(self.panels.state(), self.panels.closed())))

    def start_layout(self):
        key = str(self.settings().value("layout", ""))
        self.use_layout(key if key in self.layout_keys() else layouts.builtin_key("edit"), keep=False)

    def use_layout(self, key, keep=True, fresh=False):
        """Put the panels as layout key has them: as last left (unless fresh), else as it is
        made (built in) or as its file has them (the user's)."""
        if keep:
            self.keep_layout()
        kind, _, rest = key.partition(":")
        self.panels.arrange(rest if kind == "builtin" else "edit")
        got = None if fresh else self._live_layout(key)
        if got is None and kind == "user":
            try:
                got = layouts.read(self.layout_dir(), rest)
            except ValueError as exc:
                self.statusBar().showMessage(str(exc), 6000)
        if got is not None and not self.panels.restore(*got):
            self.statusBar().showMessage(f"佈局「{layouts.title(key)}」用不了，面板照預設排", 6000)
        self.layout_key = key
        self.settings().setValue("layout", key)
        self._update_side_tabs(self.timeline.selected_clips_primary_first())
        self._fill_layout_tabs()

    def step_layout(self, d):
        keys = self.layout_keys()
        i = keys.index(self.layout_key) if self.layout_key in keys else 0
        self.use_layout(keys[(i + d) % len(keys)])

    def reset_layout(self, key):
        """Layout key back as it is made (built in) or as its file has it (the user's)."""
        self.settings().remove("layout_live/" + key)
        if key == self.layout_key:
            self.use_layout(key, keep=False, fresh=True)

    def save_layout(self):
        """The panels as they are now into the user's layout (a built-in one: into a new one)."""
        kind, _, name = (self.layout_key or "").partition(":")
        if kind != "user":
            self.save_layout_as()
            return
        self._write_layout(name)

    def save_layout_as(self):
        name, ok = QInputDialog.getText(self, "另存為新佈局", "佈局名稱", text="我的佈局")
        if not ok:
            return
        try:
            name = layouts.clean_name(name)
        except ValueError as exc:
            QMessageBox.warning(self, "另存為新佈局", str(exc))
            return
        if name in layouts.list_user(self.layout_dir()) and not questions.question(
                self, "overwrite_layout", "另存為新佈局", f"已經有叫「{name}」的佈局，要覆寫它嗎？"):
            return
        self.keep_layout()                               # the one left keeps its arrangement too
        self._write_layout(name)

    def _write_layout(self, name):
        try:
            path = layouts.write(self.layout_dir(), name, self.panels.state(), self.panels.closed())
        except OSError as exc:
            QMessageBox.warning(self, "儲存佈局", f"存不了佈局：{exc}")
            return
        key = layouts.user_key(name)
        self.settings().remove("layout_live/" + key)     # the file is now how it is
        self.layout_key = key
        self.settings().setValue("layout", key)
        self._fill_layout_tabs()
        self.statusBar().showMessage(f"已儲存佈局「{name}」：{path}", 5000)

    def rename_layout(self, key):
        old = key.partition(":")[2]
        i = next((k for k in range(self.layout_tabs.count()) if self.layout_tabs.tabData(k) == key), -1)
        name, ok = inplace.ask_name(self, old, (self.layout_tabs, self.layout_tabs.tabRect(i)) if i >= 0 else None)
        if not ok or name.strip() == old:
            return
        try:
            name = layouts.clean_name(name)
            layouts.rename(self.layout_dir(), old, name)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "重新命名佈局", str(exc))
            return
        new = layouts.user_key(name)
        live = self.settings().value("layout_live/" + key)
        self.settings().remove("layout_live/" + key)
        if live:
            self.settings().setValue("layout_live/" + new, live)
        if self.layout_key == key:
            self.layout_key = new
            self.settings().setValue("layout", new)
        self._fill_layout_tabs()

    def delete_layout(self, key):
        name = key.partition(":")[2]
        if not questions.question(self, "delete_layout", "刪除佈局", f"刪除佈局「{name}」？\n（它的檔案會從 KiaseCut/preset/layout 移除）"):
            return
        try:
            layouts.remove(self.layout_dir(), name)
        except OSError as exc:
            QMessageBox.warning(self, "刪除佈局", str(exc))
            return
        self.settings().remove("layout_live/" + key)
        if self.layout_key == key:
            self.use_layout(layouts.builtin_key("edit"), keep=False)
        else:
            self._fill_layout_tabs()

    def reveal_layouts(self):
        where = self.layout_dir()
        os.makedirs(where, exist_ok=True)
        self.reveal_path(where)

    def _fill_layout_tabs(self):
        tabs = self.layout_tabs
        tabs.blockSignals(True)
        while tabs.count():
            tabs.removeTab(0)
        for key in self.layout_keys():
            i = tabs.addTab(layouts.title(key))
            tabs.setTabData(i, key)
            if key == self.layout_key:
                tabs.setCurrentIndex(i)
        tabs.blockSignals(False)

    def _layout_tab_switched(self, i):
        key = self.layout_tabs.tabData(i)
        if key and key != self.layout_key:
            QTimer.singleShot(0, lambda: self.use_layout(key))   # (not while the tab bar is switching)

    def _layout_actions(self, menu, key):
        user = key.startswith("user:")
        menu.addAction("重設為" + ("檔案裡的排法" if user else "預設排法"), lambda: self.reset_layout(key))
        if user:
            a = menu.addAction("用目前的排法覆寫", lambda: self._write_layout(key.partition(":")[2]))
            a.setEnabled(key == self.layout_key)
            menu.addAction("重新命名…", lambda: self.rename_layout(key))
            menu.addAction("刪除…", lambda: self.delete_layout(key))
        menu.addSeparator()
        menu.addAction("另存為新佈局…", self.save_layout_as)
        menu.addAction("開啟佈局資料夾", self.reveal_layouts)

    def _layout_tab_menu(self, pos):
        i = self.layout_tabs.tabAt(pos)
        menu = Menu(self)
        if i >= 0:
            self._layout_actions(menu, self.layout_tabs.tabData(i))
        else:
            menu.addAction("另存為新佈局…", self.save_layout_as)
            menu.addAction("開啟佈局資料夾", self.reveal_layouts)
        menu.exec(self.layout_tabs.mapToGlobal(pos))

    def _fill_layout_menu(self):
        m = self.layout_menu
        m.clear()
        keys = self.layout_keys()
        for key in keys:
            a = m.addAction(layouts.title(key), lambda k=key: k != self.layout_key and self.use_layout(k))
            a.setCheckable(True)
            a.setChecked(key == self.layout_key)
            if key.startswith("user:") and (len(m.actions()) == 1 or not keys[keys.index(key) - 1].startswith("user:")):
                m.insertSeparator(a)
        self._fill_layout_tabs()                         # (files added to the folder by hand)

    def _fill_panel_actions(self):
        """The 視窗 menu's panels: checked while open (not closed on purpose)."""
        from .docks import ORDER, TITLES
        for a in self.panel_actions:
            self.panel_menu.removeAction(a)
        self.panel_actions = []
        for key in ORDER:
            a = self.panel_menu.addAction(TITLES[key])
            a.setCheckable(True)
            a.setChecked(not self.panels[key].user_closed)
            a.toggled.connect(lambda on, k=key: self.panels.show(k) if on else self.panels.close(k))
            self.panel_actions.append(a)

    def closeEvent(self, e):
        if not self.maybe_save():
            e.ignore()
            return
        self.closing = True
        self.keep_layout()
        if self.autosave_dir:                            # closed normally: nothing to bring back
            recovery.end(self.autosave_dir)
        if self.fullscreen:
            self.fullscreen.close()
        self.player.shutdown()
        if getattr(self, "_thumb_engine", None) is not None:
            self._thumb_engine.close()
        for th, _task in list(self.tasks):               # background work still running: let it end
            th.quit()
            th.wait(4000)
        super().closeEvent(e)


def ui_scale():
    """界面縮放 in percent, as saved in the settings (100 without one)."""
    try:
        return max(50, min(300, int(QSettings(*MainWindow.SETTINGS).value("ui_scale", 100))))
    except (TypeError, ValueError):
        return 100


def run(argv):
    if sys.platform.startswith("linux"):
        # Qt 6.12's own PipeWire sound output crashed the program as playing started (in
        # pw_stream_connect); its PulseAudio one (PipeWire serves it too) does not.
        # QT_AUDIO_BACKEND=pipewire in the environment still picks the former.
        os.environ.setdefault("QT_AUDIO_BACKEND", "pulseaudio")
    scale = ui_scale()
    if scale != 100 and sys.platform != "android":
        os.environ.setdefault("QT_SCALE_FACTOR", f"{scale / 100:g}")   # 界面縮放 (設定): the whole interface, at start
    if sys.platform == "android":
        QApplication.setAttribute(Qt.AA_DontUseNativeMenuBar)       # the menus in the window, not behind the system's "..."
    app = QApplication(argv)
    if sys.platform == "android":
        androidfiles.install()
        dialogframe.install()                       # a title bar, a ✕ and an outline on every dialog (the system gives none)
        touch.install_scrolling()                   # one finger scrolls every list and panel; a hold first, then it drags
    look.apply(app)                                 # the same on every platform
    middledrag.install()                            # 中鍵拖拽 on every scroll area
    escapekey.install()                             # Esc leaves a field; on Android the Back key is Esc
    menudebug.install()                             # (a log of the menus' events, for the tablet)
    menubartap.install()                            # a finger from one title of the menu bar to the next swaps the menus (Android)
    sashtouch.install()                             # the lines between panels are let go by a hold, with a finger (Android)
    softdrag.install()                              # a finger's drags (the library to the timeline) are made by the program on Android
    menuanim.install()                              # menus open from big and blurred to what they are
    # the logo (Icon.svg beside the package; Icon.free is its Lunacy source) on every window;
    # Wayland desktops take the icon from kiasecut.desktop instead, found by this name
    app.setDesktopFileName("kiasecut")
    logo = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "Icon.svg")
    if os.path.exists(logo):
        app.setWindowIcon(QIcon(logo))
    win = MainWindow()
    win.show()
    if sys.platform == "android" and not androidfs.can_read():
        QMessageBox.information(win, "需要權限", androidfs.HOW_TO_ALLOW)
    win.begin_session()
    if win.offer_recovery():
        pass
    elif len(argv) > 1:
        a = argv[1]
        if a.endswith(workspace.EXTS):
            win.open_path(os.path.abspath(a))
        else:
            win.import_draft_file(a)
    else:                                            # no project: pick one first
        QTimer.singleShot(0, win.show_project_manager)
    return app.exec()
