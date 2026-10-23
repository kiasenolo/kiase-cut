"""Main window: preview, inspector, transport, edit toolbar and timeline (Jianying-like)."""
import hashlib
import json
import os

from PySide6.QtCore import QObject, QStandardPaths, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QProgressDialog, QPushButton, QScrollArea, QSplitter,
                               QVBoxLayout, QWidget)

from .. import build, edit, project
from ..client import EngineClient
from ..importers import jianying
from .inspector import Inspector
from .player import Player
from .timeline import US, Timeline, timecode

STYLE = """
QWidget { background: #1b1b1f; color: #e6e6e6; font-family: 'Segoe UI', 'Microsoft JhengHei UI', 'Noto Sans CJK TC', sans-serif; }
QMenuBar, QMenu { background: #202024; }
QMenu::item:selected, QMenuBar::item:selected { background: #2c6e72; }
QPushButton { background: #2a2a30; border: 1px solid #3a3a42; border-radius: 4px; padding: 4px 12px; }
QPushButton:hover { background: #33333b; }
QPushButton:disabled { color: #666; }
QSplitter::handle { background: #111114; }
QDoubleSpinBox, QPlainTextEdit { background: #26262c; border: 1px solid #3a3a42; border-radius: 3px; padding: 2px; }
QDoubleSpinBox:disabled { color: #777; }
QLabel#time { font-family: Consolas, monospace; color: #cfcfd4; }
QLabel#title { color: #8fd9d3; font-weight: 600; }
"""


class Preview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.img = None
        self.aspect = 16 / 9
        self.setMinimumSize(320, 180)

    def show_image(self, img):
        self.img = img
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#111114"))
        w, h = self.width(), self.height()
        if w / h > self.aspect:
            dw, dh = h * self.aspect, h
        else:
            dw, dh = w, w / self.aspect
        x, y = (w - dw) / 2, (h - dh) / 2
        p.fillRect(int(x), int(y), int(dw), int(dh), QColor("black"))
        if self.img is not None:
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(self.rect().adjusted(int(x), int(y), -int(x), -int(y)), self.img)


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
    def __init__(self):
        super().__init__()
        self.resize(1440, 900)
        self.proj = None
        self.history = None
        self.path = None
        self.dirty = False
        self.xml = None
        self.xml_slot = 0
        self.length = 0
        self.fps = 60.0
        self.pos = 0
        self.playing = False
        self.tasks = []
        self.building = False
        self.build_again = False
        self.first_build = True

        self.preview = Preview()
        self.inspector = Inspector()
        self.inspector.textEdited.connect(self.on_text_edited)
        ins = self.inspector
        ins.paramEdited.connect(self.on_param_edited)
        ins.keyToggled.connect(self.on_key_toggled)
        ins.easingChosen.connect(self.on_easing)
        ins.maskKindChosen.connect(lambda cid, kind: self.apply("遮罩", edit.set_mask, cid, kind))
        ins.maskInvertChosen.connect(lambda cid, on: self.apply("反轉遮罩", edit.set_mask_invert, cid, on))
        ins.keyJump.connect(self.jump_key)
        scroll = QScrollArea()
        scroll.setWidget(self.inspector)
        scroll.setWidgetResizable(True)

        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedWidth(48)
        self.play_btn.clicked.connect(self.toggle_play)
        self.time_lbl = QLabel("00:00.00 / 00:00.00")
        self.time_lbl.setObjectName("time")
        bar = QHBoxLayout()
        bar.addStretch()
        bar.addWidget(self.time_lbl)
        bar.addWidget(self.play_btn)
        bar.addStretch()
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(4, 4, 4, 4)
        cl.addWidget(self.preview, 1)
        cl.addLayout(bar)

        top = QSplitter(Qt.Horizontal)
        top.addWidget(center)
        top.addWidget(scroll)
        top.setStretchFactor(0, 1)
        top.setSizes([1100, 340])

        self.timeline = Timeline()
        self.timeline.seekRequested.connect(self.seek)
        self.timeline.clipSelected.connect(lambda c: self.refresh_inspector())
        self.timeline.moveRequested.connect(
            lambda cid, start, tid: self.apply("移動", edit.move, cid, start, tid))
        self.timeline.trimRequested.connect(
            lambda cid, edge, t: self.apply("裁切", edit.trim_start if edge == "start" else edit.trim_end, cid, t))
        tools = QHBoxLayout()
        tools.setContentsMargins(6, 2, 6, 2)
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
        ll.addWidget(self.timeline, 1)

        main = QSplitter(Qt.Vertical)
        main.addWidget(top)
        main.addWidget(lower)
        main.setSizes([540, 340])
        self.setCentralWidget(main)

        self.player = Player(self)
        w = self.player.worker
        w.frameReady.connect(self.on_frame)
        w.loaded.connect(self.on_loaded)
        w.failed.connect(lambda m: self.statusBar().showMessage(f"預覽錯誤：{m}", 10000))
        w.stateChanged.connect(self.on_state)
        self.rebuild_timer = QTimer(self, singleShot=True, interval=150)
        self.rebuild_timer.timeout.connect(self.rebuild)
        self._menus()
        self._update_title()
        self._update_buttons()
        self.statusBar().showMessage("檔案 > 匯入剪映草稿")

    # -- menus ------------------------------------------------------------------------------------
    def _menus(self):
        def add(menu, text, key, fn):
            a = QAction(text, self)
            if key:
                a.setShortcut(QKeySequence(key))
            a.triggered.connect(fn)
            menu.addAction(a)

        m = self.menuBar().addMenu("檔案")
        add(m, "匯入剪映草稿…", "Ctrl+I", self.import_draft)
        add(m, "開啟專案…", "Ctrl+O", self.open_project)
        add(m, "儲存專案", "Ctrl+S", self.save_project)
        add(m, "另存專案…", "Ctrl+Shift+S", lambda: self.save_project(True))
        add(m, "匯出影片…", "Ctrl+E", self.export)
        m = self.menuBar().addMenu("編輯")
        add(m, "復原", "Ctrl+Z", self.do_undo)
        add(m, "重做", "Ctrl+Y", self.do_redo)
        m.addSeparator()
        add(m, "分割", "Ctrl+B", self.do_split)
        add(m, "刪除", "Delete", self.do_delete)
        add(m, "新增文字", "Ctrl+T", self.do_text)
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
        self.proj = proj
        self.history = edit.History(proj)
        self.dirty = False
        self.fps = proj["fps"]
        self.preview.aspect = proj["width"] / proj["height"]
        self.timeline.set_project(proj)
        self.first_build = True
        self._update_title()
        self._update_buttons()
        self.refresh_inspector()
        self.rebuild()

    def relink(self, proj):
        """Offer to find missing media by file name under a folder the user picks."""
        clips = [c for c in project.walk_clips(proj["tracks"]) if c.get("media")]
        missing = sorted({c["media"]["path"] for c in clips if not os.path.exists(c["media"]["path"])})
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
        for c in clips:
            p = c["media"]["path"]
            if not os.path.exists(p) and os.path.basename(p).lower() in found:
                c["media"]["path"] = found[os.path.basename(p).lower()]
                fixed += 1
        self.statusBar().showMessage(f"已重新連結 {fixed} 個片段的素材", 8000)

    # -- editing ----------------------------------------------------------------------------------
    def apply(self, label, fn, *args, merge=None, select=None):
        """Run an edit through the undo history, then refresh views and the preview."""
        if not self.history:
            return None
        try:
            result = self.history.do(label, fn, *args, merge=merge)
        except edit.EditError as exc:
            self.statusBar().showMessage(f"{label}：{exc}", 4000)
            self.timeline.update()
            return None
        if select is not None:
            self.timeline.selected_id = select(result)
        self.after_edit(label)
        return result

    def after_edit(self, label):
        self.dirty = True
        sel = self.timeline.selected_id
        self.timeline.set_project(self.proj, keep_view=True)
        self.timeline.selected_id = sel
        self.timeline.update()
        self._update_title()
        self._update_buttons()
        self.refresh_inspector()
        self.statusBar().showMessage(label, 2000)
        self.rebuild_timer.start()

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
        targets = [c] if c else [k for tr in self.proj["tracks"] for k in tr["clips"]
                                 if k["start_us"] < t < k["start_us"] + k["duration_us"]]
        if not targets:
            self.statusBar().showMessage("播放頭下沒有片段", 3000)
            return
        ids = [k["id"] for k in targets]

        def split_all(proj):
            for cid in ids:
                edit.split(proj, cid, t)

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
        self.apply("修改文字", lambda p: edit.set_text(p, cid, **fields),
                   merge=("text", cid, tuple(sorted(fields))))

    PARAM_LABELS = {("transform", "x"): "位置", ("transform", "y"): "位置",
                    ("transform", "scale"): "縮放", ("transform", "rotation"): "旋轉",
                    ("transform", "opacity"): "不透明度", ("clip", "volume"): "音量"}

    def clip_time(self, cid):
        """Playhead time relative to the start of clip cid."""
        return self.playhead_us() - edit.find(self.proj, cid)[1]["start_us"]

    def on_param_edited(self, cid, group, key, value):
        label = "調整" + self.PARAM_LABELS.get((group, key), "遮罩")
        t = self.clip_time(cid)
        self.apply(label, edit.set_param, cid, group, key, value, t,
                   merge=("param", cid, group, key, round(t)))

    def on_key_toggled(self, cid, group, key):
        self.apply("關鍵幀", edit.toggle_key, cid, group, key, self.clip_time(cid))

    def on_easing(self, cid, easing):
        """Apply a curve preset to every parameter with a keyframe at the playhead."""
        t = self.clip_time(cid)
        c = edit.find(self.proj, cid)[1]
        targets = [(g, k) for g in ("transform", "mask") for k, v in (c.get(g) or {}).items()
                   if edit.key_at(v, t) is not None]
        if edit.key_at(c.get("volume"), t) is not None:
            targets.append(("clip", "volume"))

        def ease_all(proj):
            done = 0
            for g, k in targets:
                p = (edit.find(proj, cid)[1] if g == "clip" else edit.find(proj, cid)[1][g])[k]
                i = edit.key_at(p, t)
                if i is not None and i + 1 < len(p["keys"]):
                    edit.set_easing(proj, cid, g, k, t, easing)
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

    def refresh_inspector(self):
        self.inspector.show_clip(self.timeline.selected, self.playhead_us(), self.fps)
        self._update_buttons()

    # -- preview build ----------------------------------------------------------------------------
    def rebuild(self):
        """Rebuild the MLT document in the background and hand it to the player. Edits made
        meanwhile queue one more build; the project is copied so the build never sees a
        half-made edit."""
        if self.proj is None:
            return
        if self.building:
            self.build_again = True
            return
        self.building, self.build_again = True, False
        snapshot = json.loads(json.dumps(self.proj))
        cache = self.cache_dir()
        self.xml_slot ^= 1
        xml = os.path.join(cache, f"preview{self.xml_slot}.mlt")
        dlg = None
        if self.first_build:
            dlg = QProgressDialog("準備預覽（第一次要產生文字圖片）…", None, 0, 0, self)
            dlg.setWindowModality(Qt.WindowModal)
            dlg.setMinimumDuration(400)
        else:
            self.statusBar().showMessage("更新預覽…")

        def work(_progress):
            os.makedirs(cache, exist_ok=True)
            return build.build(snapshot, cache, xml)

        def finish():
            if dlg:
                dlg.close()
            self.building = False
            self.first_build = False
            if self.build_again:
                self.rebuild()

        def done(path):
            self.xml = path
            self.player.worker.request_load(path)
            finish()

        def failed(msg):
            finish()
            QMessageBox.critical(self, "建置失敗", msg)

        self.run_task(work, done, failed)

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
        self.timeline.set_position(pos)
        self.time_lbl.setText(f"{timecode(pos / self.fps * US, self.fps)} / "
                              f"{timecode(self.length / self.fps * US, self.fps)}")
        if self.timeline.selected is not None:
            self.inspector.show_clip(self.timeline.selected, self.playhead_us(), self.fps)

    def on_state(self, playing):
        self.playing = playing
        self.play_btn.setText("❚❚" if playing else "▶")

    def toggle_play(self):
        if self.xml:
            self.player.worker.set_playing(not self.playing)

    def seek(self, frame):
        if self.xml:
            if self.playing:
                self.player.worker.set_playing(False)
            self.player.worker.request_seek(frame)

    def step(self, d):
        self.seek(self.pos + d)

    # -- export -----------------------------------------------------------------------------------
    def export(self):
        if not self.xml:
            return
        fn, _ = QFileDialog.getSaveFileName(self, "匯出影片", "", "MP4 (*.mp4)")
        if not fn:
            return
        self.player.worker.set_playing(False)
        dlg = QProgressDialog("匯出中…", None, 0, 1000, self)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        xml = self.xml

        def work(progress):
            eng = EngineClient(16, 16)        # its own process; preview stays usable
            try:
                return eng.export(xml, fn, progress, crf=16, preset="medium", threads=os.cpu_count() or 4)
            finally:
                eng.close()

        def done(r):
            dlg.close()
            QMessageBox.information(self, "匯出完成", f"{fn}\n耗時 {r['elapsed']:.0f} 秒")

        self.run_task(work, done, lambda m: (dlg.close(), QMessageBox.critical(self, "匯出失敗", m)),
                      lambda p: dlg.setValue(int(p * 1000)))

    def closeEvent(self, e):
        if not self.maybe_save():
            e.ignore()
            return
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
