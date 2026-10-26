"""Export settings: file, format, whole film or the marked range, frame rate, size, quality,
and the advanced options: a transparent background, the sound, stems.

The project is not tied to a frame rate or a pixel size: times are microseconds and
positions are fractions of the canvas, so an export can use any frame rate and any size
with the project's shape. Size is a multiple of the project's own resolution.
Formats are formats.py's; the advanced options are renderexport.export's spec.
ExportProgress is the window shown while the export runs: what is being made, how far it
is, how long is left, the memory it holds, and a button that stops it.
"""
import os
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QRadioButton,
                               QToolButton, QVBoxLayout, QWidget)

from .. import formats, sysmem
from .inspector import SpinBox
from .timeline import US, timecode

QUALITY = (("高畫質", {"crf": 16, "preset": "medium"}),
           ("標準", {"crf": 20, "preset": "medium"}),
           ("小檔案", {"crf": 26, "preset": "fast"}))
FPS_CHOICES = (10, 25, 30, 40, 60, 100)
SCALE_CHOICES = (0.25, 0.5, 1, 2, 4)
BIG_PIXELS = 7680 * 4320          # past 8K the dialog warns: every frame takes a lot of memory
GREY, WARN = "color: #9a9aa0;", "color: #e0a040;"


def even(v):
    """Encoders want even sizes."""
    return max(2, int(round(v / 2)) * 2)


def export_size(width, height, scale):
    return even(width * scale), even(height * scale)


class ExportDialog(QDialog):
    def __init__(self, parent, default_path, fps, length, mark_in, mark_out, width=1920, height=1080, out_fps=None,
                 spec=None):
        """fps, length, mark_in / mark_out: the editor's frames (時間線精度); out_fps: the frame
        rate offered for the file (the project's), fps when None; spec: the advanced settings
        last used (renderexport.export's)."""
        super().__init__(parent)
        self.setWindowTitle("匯出影片")
        spec = dict(spec or {})
        self.fps, self.length = fps, length
        self.W, self.H = width, height
        lay = QVBoxLayout(self)
        form = QFormLayout()
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        self.path = QLineEdit(default_path)
        browse = QPushButton("瀏覽…")
        browse.clicked.connect(self._browse)
        rl.addWidget(self.path, 1)
        rl.addWidget(browse)
        form.addRow("檔案", row)
        self.format_box = QComboBox()
        for f in formats.FORMATS:
            self.format_box.addItem(f.label, f.key)
        self.format_box.setCurrentIndex(max(0, self.format_box.findData(formats.get(spec.get("format")).key)))
        form.addRow("格式", self.format_box)
        self.whole = QRadioButton(f"整部影片（{self._tc(0)} – {self._tc(length)}）")
        has_range = mark_in is not None or mark_out is not None
        a = mark_in or 0
        b = mark_out if mark_out is not None else length - 1
        self.range = (a, b)
        self.marked = QRadioButton(f"標記的範圍（{self._tc(a)} – {self._tc(b + 1)}）" if has_range
                                   else "標記的範圍（在時間軸按 I / O 標記）")
        self.marked.setEnabled(has_range)
        (self.marked if has_range else self.whole).setChecked(True)
        form.addRow("範圍", self.whole)
        form.addRow("", self.marked)

        # frame rate: a list plus a custom value
        out = out_fps or fps
        self.fps_box, self.fps_custom = self._choice(
            [f"{v} fps" for v in FPS_CHOICES], 1.0, 240.0, 0.001, 3, " fps",
            FPS_CHOICES.index(round(out)) if round(out) in FPS_CHOICES and abs(out - round(out)) < 1e-6 else None,
            out)
        form.addRow("幀率", self._pair(self.fps_box, self.fps_custom))
        # size: a multiple of the project's resolution
        self.scale_box, self.scale_custom = self._choice(
            [f"{v:g}×" for v in SCALE_CHOICES], 0.05, 8.0, 0.05, 3, "×", SCALE_CHOICES.index(1), 1.0)
        self.size_lbl = QLabel()
        self.size_lbl.setStyleSheet("color: #9a9aa0;")
        form.addRow("解析度", self._pair(self.scale_box, self.scale_custom, self.size_lbl))
        for w in (self.scale_box, self.fps_box):
            w.currentIndexChanged.connect(self._update)
        for w in (self.scale_custom, self.fps_custom):
            w.edited.connect(self._update)

        self.quality = QComboBox()
        for name, _ in QUALITY:
            self.quality.addItem(name)
        form.addRow("畫質", self.quality)
        self.info_lbl = QLabel()
        self.info_lbl.setWordWrap(True)
        form.addRow("內容", self.info_lbl)
        self.form = form
        lay.addLayout(form)

        # advanced: transparency, the sound, stems
        self.more = QToolButton()
        self.more.setText("進階匯出選項")
        self.more.setCheckable(True)
        self.more.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.more.setStyleSheet("QToolButton { border: none; font-weight: bold; }")
        self.more.toggled.connect(self._show_more)
        lay.addWidget(self.more)
        self.adv = QWidget()
        adv = QFormLayout(self.adv)
        adv.setContentsMargins(16, 0, 0, 0)
        self.alpha = QCheckBox("透明背景（沒有畫面的地方是透明的）")
        adv.addRow("畫面", self.alpha)
        self.audio = QCheckBox("包含混音")
        self.audio.setChecked(spec.get("audio", True))
        adv.addRow("聲音", self.audio)
        self.multitrack = QCheckBox("多音軌：每條軌道的聲音另成一個音訊串流（剪輯軟體可分開調整）")
        self.multitrack.setChecked(bool(spec.get("multitrack")))
        adv.addRow("", self.multitrack)
        self.stems = QCheckBox("分軌音檔：每條軌道的聲音各存一個檔案")
        self.stems.setChecked(bool(spec.get("stems")))
        self.stem_fmt = QComboBox()
        for ext in formats.STEM_FORMATS:
            self.stem_fmt.addItem(ext.upper(), ext)
        self.stem_fmt.setCurrentIndex(max(0, self.stem_fmt.findData(spec.get("stems") or "wav")))
        adv.addRow("", self._pair(self.stems, self.stem_fmt))
        self.adv_note = QLabel()
        self.adv_note.setWordWrap(True)
        self.adv_note.setStyleSheet("color: #9a9aa0;")
        adv.addRow("", self.adv_note)
        lay.addWidget(self.adv)
        self.alpha_choice = {}                 # format key -> the user's transparency choice
        if spec.get("alpha") is not None:
            self.alpha_choice[self.format().key] = bool(spec["alpha"])
        self.format_box.currentIndexChanged.connect(self._format_changed)
        self.alpha.toggled.connect(self._alpha_toggled)
        for w in (self.audio, self.multitrack, self.stems):
            w.toggled.connect(self._update)
        self.stem_fmt.currentIndexChanged.connect(self._update)
        self.path.textChanged.connect(self._update)
        self.whole.toggled.connect(self._update)
        self._format_changed()
        self.more.setChecked(bool(spec.get("alpha") or spec.get("stems") or spec.get("multitrack")
                                  or not spec.get("audio", True)))
        self._show_more(self.more.isChecked())
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("匯出")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._update()
        self.resize(560, 0)

    @staticmethod
    def _choice(labels, lo, hi, step, dec, suffix, index, custom):
        box = QComboBox()
        box.addItems(labels + ["自訂"])
        spin = SpinBox()
        spin.setRange(lo, hi)
        spin.setSingleStep(step)
        spin.setDecimals(dec)
        spin.setSuffix(suffix)
        spin.setKeyboardTracking(False)
        spin.show_value(custom)
        box.setCurrentIndex(len(labels) if index is None else index)
        return box, spin

    @staticmethod
    def _pair(*widgets):
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        for w in widgets:
            rl.addWidget(w, 1 if w is widgets[0] else 0)
        return row

    def _update(self, *_):
        self.fps_custom.setVisible(self.fps_box.currentIndex() == len(FPS_CHOICES))
        self.scale_custom.setVisible(self.scale_box.currentIndex() == len(SCALE_CHOICES))
        w, h = export_size(self.W, self.H, self.scale())
        self.size_lbl.setText(f"{w}×{h}")
        if not hasattr(self, "adv_note"):          # (still being built)
            return
        f = self.format()
        self.stem_fmt.setEnabled(self.stems.isChecked())
        name = os.path.basename(self._stem_path())
        notes = []
        if f.kind == "sequence":
            notes.append(f"每格存成一張 PNG，放在「{name}」資料夾。")
        if f.kind == "gif":
            notes.append("GIF 沒有聲音、只有 256 色，適合短片段與低幀率。")
        if self.alpha.isEnabled() and self.alpha.isChecked():
            notes.append("透明背景的檔案可放進 Premiere、After Effects、DaVinci Resolve 等，疊在其他畫面上。")
        if self.stems.isChecked():
            notes.append(f"分軌音檔放在「{name} - 分軌」資料夾（只含有聲音、沒被靜音的軌道）。")
        self.adv_note.setText("\n".join(notes))
        self.adv_note.setVisible(bool(notes))
        self._update_info(f, w, h)

    def frames(self):
        """(first, last): the frames, at the export's own rate, the export will make."""
        _path, t0, t1, fmt, _opts = self.result_options()
        first = round(t0 / US * fmt["fps"])
        return first, max(first, round(t1 / US * fmt["fps"]) - 1)

    def _update_info(self, f, w, h):
        """How many frames, how long, and how much one frame takes; a warning when it is a lot."""
        first, last = self.frames()
        n, fps = last - first + 1, self.out_fps()
        text = f"長度 {timecode(n / fps * US, fps)}"
        warn = False
        if f.has_video:
            text = f"{n:,} 幀，" + text + f"，每幀未壓縮 {sysmem.gb(w * h * 4)}"
            if w * h > max(BIG_PIXELS, 4 * self.W * self.H):
                text += f"\n⚠ {w}×{h} 非常大：匯出會用掉很多記憶體與時間，請確認解析度沒有調錯。"
                warn = True
            mem = sysmem.available()
            if mem and w * h * 4 * 8 > mem[0]:          # (a frame passes through a few buffers on the way)
                text += f"\n⚠ 系統只剩 {sysmem.gb(mem[0])} 可用記憶體，這個解析度可能會用完。"
                warn = True
        self.info_lbl.setText(text)
        self.info_lbl.setStyleSheet(WARN if warn else GREY)

    def format(self):
        return formats.get(self.format_box.currentData())

    def _format_changed(self, *_):
        f = self.format()
        p = self.path.text().strip()
        if p:
            base, ext = os.path.splitext(p)
            self.path.setText((base if ext.lower() in formats.EXTS else p) + f.ext)
        self.alpha.setEnabled(f.can_alpha)
        self.alpha.blockSignals(True)
        self.alpha.setChecked(f.can_alpha and self.alpha_choice.get(f.key, bool(f.alpha)))
        self.alpha.blockSignals(False)
        self.audio.setEnabled(f.has_video and f.audio is not None)
        self.multitrack.setEnabled(f.multitrack)
        for w in (self.fps_box, self.scale_box):
            self.form.setRowVisible(w.parentWidget(), f.has_video)
        self.form.setRowVisible(self.quality, f.quality)
        self.setWindowTitle("匯出影片" if f.has_video else "匯出音訊")
        self._update()

    def _alpha_toggled(self, on):
        self.alpha_choice[self.format().key] = on
        self._update()

    def _show_more(self, on):
        self.more.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.adv.setVisible(on)
        self.adjustSize()

    def _stem_path(self):
        return os.path.splitext(self.path.text().strip() or "export")[0]

    def spec(self):
        """The advanced settings: renderexport.export's spec."""
        f = self.format()
        return {"format": f.key, "alpha": f.can_alpha and self.alpha.isChecked(),
                "audio": self.audio.isChecked() if self.audio.isEnabled() else f.audio is not None,
                "multitrack": f.multitrack and self.multitrack.isChecked(),
                "stems": self.stem_fmt.currentData() if self.stems.isChecked() else None}

    def out_fps(self):
        i = self.fps_box.currentIndex()
        return float(FPS_CHOICES[i]) if i < len(FPS_CHOICES) else self.fps_custom.value()

    def scale(self):
        i = self.scale_box.currentIndex()
        return float(SCALE_CHOICES[i]) if i < len(SCALE_CHOICES) else self.scale_custom.value()

    def _tc(self, frame):
        return timecode(frame / self.fps * US, self.fps)

    def _browse(self):
        ext = self.format().ext
        fn, _ = QFileDialog.getSaveFileName(self, self.windowTitle(), self.path.text(),
                                            f"{ext[1:].upper()} (*{ext})")
        if fn:
            self.path.setText(fn if fn.lower().endswith(ext) else fn + ext)

    def result_options(self):
        """(path, first us, end us, {width, height, fps}, encoder options)."""
        a, b = self.range if self.marked.isChecked() else (0, self.length - 1)
        path = self.path.text().strip()
        ext = self.format().ext
        if path and not path.lower().endswith(ext):
            path += ext
        w, h = export_size(self.W, self.H, self.scale())
        fmt = {"width": w, "height": h, "fps": self.out_fps()}
        return (os.path.abspath(path) if path else "", a / self.fps * US, (b + 1) / self.fps * US, fmt,
                dict(QUALITY[self.quality.currentIndex()][1]))


class ExportProgress(QDialog):
    """The export's progress: what is being made, the stage, frames done, time spent and
    left, the speed, the memory the app holds and the system has left, and 取消匯出.
    cancel_requested(reason) is called (once) when the export is to stop: reason None when
    the user stopped it, else why it was stopped for them (the system's memory running out,
    seen by guard, a sysmem.Guard, on every tick). The window stays until finish(), so a
    second export cannot start while the first is still winding down."""
    def __init__(self, parent, out, what, frames, cancel_requested):
        super().__init__(parent)
        self.setWindowTitle("匯出中")
        self.setWindowModality(Qt.WindowModal)
        self.frames, self.cancel_requested = frames, cancel_requested
        self.t0, self.p, self.cancelling, self.peak, self.ended = time.monotonic(), 0.0, False, 0, False
        self.guard = sysmem.Guard()
        lay = QVBoxLayout(self)
        name = QLabel(os.path.basename(out) or out)
        name.setStyleSheet("font-weight: bold;")
        name.setToolTip(out)
        lay.addWidget(name)
        sub = QLabel(what)
        sub.setStyleSheet(GREY)
        sub.setWordWrap(True)
        lay.addWidget(sub)
        self.stage = QLabel("準備中…")
        lay.addWidget(self.stage)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFormat("%p%")
        lay.addWidget(self.bar)
        form = QFormLayout()
        self.frames_lbl, self.time_lbl, self.left_lbl, self.speed_lbl, self.mem_lbl, self.sys_lbl = (
            QLabel("–") for _ in range(6))
        form.addRow("幀", self.frames_lbl)
        form.addRow("經過時間", self.time_lbl)
        form.addRow("預估剩餘", self.left_lbl)
        form.addRow("速度", self.speed_lbl)
        form.addRow("KiaseCut 記憶體", self.mem_lbl)
        form.addRow("系統可用記憶體", self.sys_lbl)
        lay.addLayout(form)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = QPushButton("取消匯出")
        self.cancel_btn.clicked.connect(lambda: self.cancel())
        row.addWidget(self.cancel_btn)
        lay.addLayout(row)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(250)                  # (often: memory can run out fast)
        self._tick()
        self.resize(420, 0)

    def set_progress(self, p):
        self.p = max(self.p, min(1.0, p))
        self.bar.setValue(int(self.p * 1000))

    def set_stage(self, text):
        if not self.cancelling:
            self.stage.setText(text)

    @staticmethod
    def _clock(s):
        s = int(s)
        return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"

    @staticmethod
    def low_memory_reason(free, total):
        return (f"系統可用記憶體只剩 {sysmem.gb(free)}（共 {sysmem.gb(total)}），再繼續可能讓整個系統當掉，"
                "所以自動取消了匯出。\n\n請降低解析度或幀率、關掉其他程式，或改用較小的畫質後再試。")

    def _tick(self):
        low = None if self.cancelling else self.guard.low()
        if low:
            self.cancel(self.low_memory_reason(*low))
        spent = time.monotonic() - self.t0
        self.time_lbl.setText(self._clock(spent))
        done = int(self.p * self.frames)
        self.frames_lbl.setText(f"{done:,} / {self.frames:,}" if self.frames else "–")
        if 0.01 <= self.p < 1 and spent > 2:
            self.left_lbl.setText("約 " + self._clock(spent * (1 - self.p) / self.p))
            self.speed_lbl.setText(f"{done / spent:.1f} 幀/秒" if self.frames else "–")
        used, avail = sysmem.used(), sysmem.available()
        if used is not None:
            self.peak = max(self.peak, used)
            self.mem_lbl.setText(f"{sysmem.gb(used)}（最高 {sysmem.gb(self.peak)}）")
        if avail is not None:
            free, total = avail
            self.sys_lbl.setText(f"{sysmem.gb(free)} / {sysmem.gb(total)}" + ("　⚠ 快用完了" if free < total * 0.1 else ""))
            self.sys_lbl.setStyleSheet(WARN if free < total * 0.1 else "")

    def cancel(self, reason=None):
        if self.cancelling:
            return
        self.cancelling = True
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("取消中…")
        self.stage.setText("記憶體快用完了，正在停止匯出…" if reason else "正在停止匯出…")
        if reason:
            self.stage.setStyleSheet(WARN)
        self.cancel_requested(reason)

    def reject(self):                  # Esc and the window's close button stop the export too
        self.cancel()

    def closeEvent(self, e):
        if self.ended:
            e.accept()
            return
        self.cancel()
        e.ignore()

    def finish(self):
        """The export ended (done, failed or stopped): close for real."""
        self.ended = True
        self.timer.stop()
        self.done(QDialog.Accepted)
