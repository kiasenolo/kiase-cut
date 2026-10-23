"""Main window: preview, inspector, transport and timeline (Jianying-like layout)."""
import hashlib
import os

from PySide6.QtCore import QObject, QStandardPaths, Qt, QThread, Signal, Slot
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter
from PySide6.QtWidgets import (QApplication, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QProgressDialog, QPushButton, QSplitter,
                               QVBoxLayout, QWidget)

from .. import build, curves, project
from ..client import EngineClient
from ..importers import jianying
from .player import Player
from .timeline import US, Timeline, timecode

STYLE = """
QWidget { background: #1b1b1f; color: #e6e6e6; font-family: 'Segoe UI', 'Noto Sans CJK TC', sans-serif; }
QMenuBar, QMenu { background: #202024; }
QMenu::item:selected, QMenuBar::item:selected { background: #2c6e72; }
QPushButton { background: #2a2a30; border: 1px solid #3a3a42; border-radius: 4px; padding: 4px 12px; }
QPushButton:hover { background: #33333b; }
QSplitter::handle { background: #111114; }
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
        self.setWindowTitle("tesetoa")
        self.resize(1440, 900)
        self.proj = None
        self.path = None
        self.xml = None
        self.length = 0
        self.fps = 60.0
        self.pos = 0
        self.playing = False
        self.tasks = []

        self.preview = Preview()
        self.inspector = QWidget()
        self.form = QFormLayout(self.inspector)
        self.inspector.setMinimumWidth(260)
        title = QLabel("屬性")
        title.setObjectName("title")
        self.form.addRow(title)

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
        top.addWidget(self.inspector)
        top.setStretchFactor(0, 1)
        self.timeline = Timeline()
        self.timeline.seekRequested.connect(self.seek)
        self.timeline.clipSelected.connect(self.show_clip)
        main = QSplitter(Qt.Vertical)
        main.addWidget(top)
        main.addWidget(self.timeline)
        main.setSizes([560, 300])
        self.setCentralWidget(main)

        self.player = Player(self)
        w = self.player.worker
        w.frameReady.connect(self.on_frame)
        w.loaded.connect(self.on_loaded)
        w.failed.connect(lambda m: self.statusBar().showMessage(f"預覽錯誤：{m}", 10000))
        w.stateChanged.connect(self.on_state)
        self._menus()
        self.statusBar().showMessage("檔案 > 匯入剪映草稿")

    # -- menus ------------------------------------------------------------------------------------
    def _menus(self):
        m = self.menuBar().addMenu("檔案")
        for text, key, fn in (("匯入剪映草稿…", "Ctrl+I", self.import_draft),
                              ("開啟專案…", "Ctrl+O", self.open_project),
                              ("儲存專案", "Ctrl+S", self.save_project),
                              ("另存專案…", "Ctrl+Shift+S", lambda: self.save_project(True)),
                              ("匯出影片…", "Ctrl+E", self.export)):
            a = QAction(text, self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(fn)
            m.addAction(a)
        for key, fn in (("Space", self.toggle_play), ("Left", lambda: self.step(-1)),
                        ("Right", lambda: self.step(1)), ("Home", lambda: self.seek(0)),
                        ("End", lambda: self.seek(self.length - 1))):
            a = QAction(self)
            a.setShortcut(QKeySequence(key))
            a.setShortcutContext(Qt.ApplicationShortcut)
            a.triggered.connect(fn)
            self.addAction(a)

    # -- project ----------------------------------------------------------------------------------
    def cache_dir(self):
        if self.path:
            return self.path.replace(".tesetoa.json", "") + ".tesetoa-cache"
        base = QStandardPaths.writableLocation(QStandardPaths.CacheLocation)
        key = hashlib.sha1(str(id(self.proj)).encode()).hexdigest()[:10]
        return os.path.join(base, "unsaved", key)

    def import_draft(self):
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
        fn, _ = QFileDialog.getOpenFileName(self, "開啟專案", "", "tesetoa project (*.tesetoa.json)")
        if fn:
            self.path = fn
            self.set_project(project.load(fn))

    def save_project(self, save_as=False):
        if not self.proj:
            return
        if save_as or not self.path:
            fn, _ = QFileDialog.getSaveFileName(self, "儲存專案", "", "tesetoa project (*.tesetoa.json)")
            if not fn:
                return
            if not fn.endswith(".tesetoa.json"):
                fn = fn.removesuffix(".json") + ".tesetoa.json"
            self.path = fn
        project.save(self.proj, self.path)
        self.setWindowTitle(f"tesetoa — {os.path.basename(self.path)}")
        self.statusBar().showMessage("已儲存", 3000)

    def set_project(self, proj):
        self.relink(proj)
        self.proj = proj
        self.fps = proj["fps"]
        self.preview.aspect = proj["width"] / proj["height"]
        self.timeline.set_project(proj)
        self.setWindowTitle(f"tesetoa — {os.path.basename(self.path) if self.path else '未儲存'}")
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

    def rebuild(self):
        proj, cache = self.proj, self.cache_dir()
        xml = os.path.join(cache, "preview.mlt")
        dlg = QProgressDialog("準備預覽（第一次需要計算遮罩，可能要幾分鐘）…", None, 0, 0, self)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(400)

        def work(_progress):
            os.makedirs(cache, exist_ok=True)
            return build.build(proj, cache, xml)

        def done(path):
            dlg.close()
            self.xml = path
            self.player.worker.request_load(path)

        self.run_task(work, done, lambda m: (dlg.close(), QMessageBox.critical(self, "建置失敗", m)))

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
                                     f"{self.length} 幀", 5000)

    def on_frame(self, img, pos):
        self.pos = pos
        self.preview.show_image(img)
        self.timeline.set_position(pos)
        self.time_lbl.setText(f"{timecode(pos / self.fps * US, self.fps)} / "
                              f"{timecode(self.length / self.fps * US, self.fps)}")
        if self.timeline.selected is not None:
            self.show_clip(self.timeline.selected)

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

    # -- inspector --------------------------------------------------------------------------------
    def show_clip(self, c):
        while self.form.rowCount() > 1:
            self.form.removeRow(1)
        if c is None:
            return
        t = self.pos / self.fps * US - c["start_us"]
        add = lambda k, v: self.form.addRow(k, QLabel(str(v)))
        add("類型", c["type"])
        add("開始", timecode(c["start_us"], self.fps))
        add("長度", f"{c['duration_us'] / US:.2f} 秒")
        if c.get("text"):
            add("文字", c["text"]["content"])
            add("字號", f"{c['text']['size']:.2f}")
            add("字距", c["text"].get("letter_spacing", 0))
        tf = c.get("transform")
        if tf:
            v = lambda k, d: curves.value(tf.get(k, d), t)
            add("位置", f"{v('x', 0):.3f}, {v('y', 0):.3f}")
            add("縮放", f"{v('scale', 1):.3f}")
            add("旋轉", f"{v('rotation', 0):.1f}°")
            add("不透明度", f"{v('opacity', 1) * 100:.0f}%")
            anim = [k for k in ("x", "y", "scale", "rotation", "opacity") if curves.is_animated(tf.get(k))]
            if anim:
                add("關鍵幀", ", ".join(anim))
        if c.get("mask"):
            add("遮罩", c["mask"]["kind"] + ("（反轉）" if c["mask"].get("invert") else ""))
        if "volume" in c:
            add("音量", f"{curves.value(c['volume'], t):.2f}")

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
