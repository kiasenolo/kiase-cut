"""Main window (Jianying-like): media library, preview, inspector, timeline.

Editing can happen on the main timeline or inside a compound clip (double-click it);
`path_ids` is the chain of compound clips that are open. Every edit runs through one undo
history on the whole project, applied to whichever level is open.
"""
import hashlib
import json
import math
import os

from PySide6.QtCore import QObject, QStandardPaths, Qt, QThread, Signal, Slot
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QColorDialog, QDialog, QFileDialog, QHBoxLayout,
                               QInputDialog, QLabel, QMainWindow, QMessageBox, QProgressDialog,
                               QPushButton, QScrollArea, QSplitter, QTabWidget, QVBoxLayout, QWidget)

from .. import build, edit, library, project, waveform
from ..client import EngineClient
from ..importers import jianying
from .curve_editor import CurveEditor
from .export_dialog import ExportDialog
from .inspector import Inspector
from .library import LibraryPanel
from .player import Player
from .preview import FullscreenPreview, Preview
from .timeline import US, Timeline, timecode

STYLE = """
QWidget { background: #1b1b1f; color: #e6e6e6; font-family: 'Segoe UI', 'Microsoft JhengHei UI', 'Noto Sans CJK TC', sans-serif; }
QMenuBar, QMenu { background: #202024; }
QMenu::item:selected, QMenuBar::item:selected { background: #2c6e72; }
QPushButton { background: #2a2a30; border: 1px solid #3a3a42; border-radius: 4px; padding: 4px 12px; }
QPushButton:hover { background: #33333b; }
QPushButton:disabled { color: #666; }
QSplitter::handle { background: #111114; }
QDoubleSpinBox, QPlainTextEdit, QLineEdit, QComboBox { background: #26262c; border: 1px solid #3a3a42; border-radius: 3px; padding: 2px; }
QDoubleSpinBox:disabled { color: #777; }
QTreeWidget { background: #1f1f23; border: none; }
QTreeWidget::item:selected { background: #2c6e72; }
QHeaderView::section { background: #202024; border: none; padding: 3px; }
QLabel#time { font-family: Consolas, monospace; color: #cfcfd4; }
QLabel#title { color: #8fd9d3; font-weight: 600; }
QLabel#crumb { color: #ffb020; font-weight: 600; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: #202024; padding: 5px 14px; border: none; }
QTabBar::tab:selected { background: #2c6e72; }
QMessageBox, QInputDialog, QColorDialog, QDialog { background: #1b1b1f; }
QMessageBox QLabel { color: #e6e6e6; background: transparent; }
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
        self.xml = None                 # truthy once the preview has a project
        self.length = 0
        self.fps = 60.0
        self.pos = 0
        self.playing = False
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

        self.preview = Preview()
        self.preview.clipPicked.connect(lambda c: self.timeline.select(c))
        self.preview.moveCommitted.connect(self.on_preview_move)
        self.preview.moveChanged.connect(self.live_move)
        self.preview.doubleClicked.connect(self.toggle_fullscreen)

        self.inspector = Inspector()
        ins = self.inspector
        ins.textEdited.connect(self.on_text_edited)
        ins.paramEdited.connect(self.on_param_edited)
        ins.keyToggled.connect(self.on_key_toggled)
        ins.easingChosen.connect(self.on_easing)
        ins.maskKindChosen.connect(lambda cid, kind: self.apply("遮罩", edit.set_mask, cid, kind))
        ins.maskInvertChosen.connect(lambda cid, on: self.apply("反轉遮罩", edit.set_mask_invert, cid, on))
        ins.keyJump.connect(self.jump_key)
        scroll = QScrollArea()
        scroll.setWidget(self.inspector)
        scroll.setWidgetResizable(True)
        self.curves = CurveEditor()
        cv = self.curves
        cv.keysChanged.connect(self.on_curve_keys)
        cv.removeAll.connect(lambda cid, g, k, v: self.apply("刪除關鍵幀", edit.clear_keys, cid, g, k, v))
        cv.seekRequested.connect(self.seek_clip_time)
        cv.addAtPlayhead.connect(self.add_key_at_playhead)
        self.side = QTabWidget()
        self.side.addTab(scroll, "屬性")
        self.side.addTab(cv, "關鍵幀曲線")

        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedWidth(48)
        self.play_btn.clicked.connect(self.toggle_play)
        full_btn = QPushButton("全螢幕")
        full_btn.setToolTip("F，或在預覽上按兩下")
        full_btn.clicked.connect(self.toggle_fullscreen)
        self.time_lbl = QLabel("00:00.00 / 00:00.00")
        self.time_lbl.setObjectName("time")
        bar = QHBoxLayout()
        bar.addStretch()
        bar.addWidget(self.time_lbl)
        bar.addWidget(self.play_btn)
        bar.addStretch()
        bar.addWidget(full_btn)
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(4, 4, 4, 4)
        cl.addWidget(self.preview, 1)
        cl.addLayout(bar)

        top = QSplitter(Qt.Horizontal)
        top.addWidget(self.library)
        top.addWidget(center)
        top.addWidget(self.side)
        top.setStretchFactor(1, 1)
        top.setSizes([280, 900, 420])

        # timeline with its toolbar and the compound breadcrumb
        self.timeline = Timeline()
        tl = self.timeline
        tl.seekRequested.connect(self.seek)
        tl.clipSelected.connect(lambda c: self.refresh_inspector())
        tl.moveRequested.connect(lambda cid, start, tid: self.apply("移動", edit.move, cid, start, tid))
        tl.trimRequested.connect(
            lambda cid, e, t: self.apply("裁切", edit.trim_start if e == "start" else edit.trim_end, cid, t))
        tl.trackAction.connect(self.on_track_action)
        tl.clipAction.connect(self.on_clip_action)
        tl.mediaDropped.connect(self.place_media)
        tl.newTrackRequested.connect(
            lambda cid, start, top: self.apply("移到新軌道", edit.move_to_new_track, cid, start, top))
        tools = QHBoxLayout()
        tools.setContentsMargins(6, 2, 6, 2)
        self.back_btn = QPushButton("← 返回上一層")
        self.back_btn.clicked.connect(self.leave_compound)
        self.crumb = QLabel()
        self.crumb.setObjectName("crumb")
        tools.addWidget(self.back_btn)
        tools.addWidget(self.crumb)
        self.buttons = {}
        for key, label, tip in (("undo", "復原", "Ctrl+Z"), ("redo", "重做", "Ctrl+Y"),
                                ("split", "分割", "Ctrl+B"), ("delete", "刪除", "Delete"),
                                ("text", "新增文字", "Ctrl+T")):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(getattr(self, "do_" + key))
            tools.addWidget(b)
            self.buttons[key] = b
        tools.addStretch()
        lower = QWidget()
        ll = QVBoxLayout(lower)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        ll.addLayout(tools)
        ll.addWidget(tl, 1)

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
        add(m, "新增文字", "Ctrl+T", self.do_text)
        m = self.menuBar().addMenu("播放")
        add(m, "標記入點", "I", lambda: self.set_mark("in"))
        add(m, "標記出點", "O", lambda: self.set_mark("out"))
        add(m, "清除標記", "Alt+X", lambda: self.set_mark(None))
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

    def _update_crumb(self):
        names = ["主時間軸"]
        node = self.proj
        for cid in self.path_ids:
            _, c = edit.find(node, cid)
            names.append(c.get("name") or "複合片段")
            node = c["compound"]
        self.crumb.setText(" › ".join(names) if self.path_ids else "")
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
                "duration_us": max(project.end_us(node["tracks"]), node.get("duration_us") or 0, 1),
                "tracks": node["tracks"]}

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
        self.dirty = False
        self.path_ids = []
        self.fps = proj["fps"]
        self.timeline.mark_in = self.timeline.mark_out = None
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
        clips = [c for c in project.walk_clips(proj["tracks"]) if c.get("media")]
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
        try:
            self.container()
        except edit.EditError:                           # an undo removed an open compound
            self.path_ids = []
        sel = self.timeline.selected_id
        self.timeline.set_project(self.view(), keep_view=True)
        self.timeline.selected_id = sel
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
        c = self.timeline.selected
        targets = [c] if c else [k for tr in self.container()["tracks"] for k in tr["clips"]
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
        c = self.timeline.selected
        if c is not None:
            self.timeline.selected_id = None
            self.apply("刪除", edit.delete, c["id"])

    def do_text(self):
        if self.proj:
            self.apply("新增文字", edit.add_text, self.playhead_us(), select=lambda c: c["id"])

    def on_text_edited(self, cid, fields):
        self.apply("修改文字", lambda lvl: edit.set_text(lvl, cid, **fields),
                   merge=("text", cid, tuple(sorted(fields))))

    def clip_time(self, cid):
        """Playhead time relative to the start of clip cid."""
        return self.playhead_us() - edit.find(self.container(), cid)[1]["start_us"]

    def on_param_edited(self, cid, group, key, value):
        label = "調整" + self.PARAM_LABELS.get((group, key), "遮罩")
        t = self.clip_time(cid)
        self.apply(label, edit.set_param, cid, group, key, value, t,
                   merge=("param", cid, group, key, round(t)))

    def on_key_toggled(self, cid, group, key):
        self.apply("關鍵幀", edit.toggle_key, cid, group, key, self.clip_time(cid))
        self.curves.select_param(group, key)

    def add_key_at_playhead(self, cid, group, key):
        """The curve editor's "add here": a keyframe holding the current value."""
        t = self.clip_time(cid)
        c = edit.find(self.container(), cid)[1]
        p = (c if group == "clip" else c.get(group) or {}).get(key)
        if edit.key_at(p, t) is not None:
            self.statusBar().showMessage("播放頭上已經有關鍵幀", 2000)
            return
        self.apply("關鍵幀", edit.toggle_key, cid, group, key, t)

    def seek_clip_time(self, t):
        c = self.timeline.selected
        if c is not None:
            self.seek(round((c["start_us"] + t) / US * self.fps))

    def on_curve_keys(self, cid, group, key, keys, final):
        """Curve editor edits: shown live while dragging, one undo step when released."""
        if final:
            self.apply("編輯曲線", edit.set_keys, cid, group, key, keys)
            return
        view = self.snapshot()
        for tr in view["tracks"]:
            for c in tr["clips"]:
                if c["id"] == cid:
                    (c if group == "clip" else c.setdefault(group, {}))[key] = {"keys": keys}
        self.player.worker.set_view(view, self.cache_dir())

    def on_easing(self, cid, easing):
        """Apply a curve preset to every parameter with a keyframe at the playhead."""
        t = self.clip_time(cid)

        def ease_all(level):
            c = edit.find(level, cid)[1]
            done = 0
            for g in ("transform", "mask", "text", "clip"):
                holder = c if g == "clip" else (c.get(g) or {})
                for k, p in list(holder.items()):
                    if g == "clip" and k != "volume":
                        continue
                    i = edit.key_at(p, t)
                    if i is not None and i + 1 < len(p["keys"]):
                        edit.set_easing(level, cid, g, k, t, easing)
                        done += 1
            if not done:
                raise edit.EditError("需要播放頭上有關鍵幀，而且後面還有下一個")

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

    def on_preview_move(self, cid, x, y):
        t = self.clip_time(cid)

        def move_xy(level):
            edit.set_param(level, cid, "transform", "x", round(x, 5), t)
            edit.set_param(level, cid, "transform", "y", round(y, 5), t)

        self.apply("移動位置", move_xy)

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

    def place_media(self, item_id, track_id, start_us):
        if not self.proj:
            return
        self.apply_root("加入素材",
                        lambda root: library.place(self.container(root), root, item_id, track_id or None, start_us),
                        select=lambda c: c["id"])

    # -- inspector / preview overlay --------------------------------------------------------------
    def refresh_inspector(self):
        sel = self.timeline.selected
        self.inspector.show_clip(sel, self.playhead_us(), self.fps)
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

    def live_move(self, cid, x, y):
        """While a clip is dragged on the canvas: draw it at (x, y) without editing yet."""
        view = self.snapshot()
        for tr in view["tracks"]:
            for c in tr["clips"]:
                if c["id"] == cid:
                    tf = c.setdefault("transform", {})
                    tf["x"], tf["y"] = x, y            # a keyframed value shows its new key
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
        self.timeline.set_position(pos)
        self.time_lbl.setText(f"{timecode(pos / self.fps * US, self.fps)} / "
                              f"{timecode(self.length / self.fps * US, self.fps)}")
        sel = self.timeline.selected
        if sel is not None:
            self.inspector.show_clip(sel, self.playhead_us(), self.fps)
            self.curves.set_clip(sel, self.playhead_us() - sel["start_us"], self.fps)
        self.preview.set_scene(self.view() if self.proj else None, self.playhead_us(),
                               sel["id"] if sel else None)

    def on_state(self, playing):
        self.playing = playing
        self.play_btn.setText("❚❚" if playing else "▶")

    def toggle_play(self):
        if self.proj is not None:
            self.player.worker.set_playing(not self.playing)

    def seek(self, frame):
        if self.proj is not None:
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
    def set_mark(self, which):
        if self.path_ids:
            self.statusBar().showMessage("匯出範圍標在主時間軸上", 3000)
            return
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

    def export(self):
        if not self.proj:
            return
        while self.path_ids:
            self.leave_compound()
        total = round(self.proj["duration_us"] / US * self.fps)
        default = (self.path.replace(".tesetoa.json", ".mp4") if self.path
                   else os.path.join(os.path.expanduser("~"), "Videos", "tesetoa.mp4"))
        dlg = ExportDialog(self, default, self.fps, total, self.timeline.mark_in, self.timeline.mark_out)
        if dlg.exec() != QDialog.Accepted:
            return
        out, first, last, opts = dlg.result_options()
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
            xml = build.build(snapshot, cache, os.path.join(cache, "export.mlt"))   # originals, no proxies
            eng = EngineClient(16, 16)        # its own process; the preview stays usable
            try:
                return eng.export(xml, out, progress, threads=os.cpu_count() or 4,
                                  **{"in": first, "out": last}, **opts)
            finally:
                eng.close()

        def done(r):
            prog.close()
            QMessageBox.information(self, "匯出完成", f"{out}\n耗時 {r['elapsed']:.0f} 秒")

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
