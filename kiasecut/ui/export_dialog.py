"""Export settings: file, whole film or the marked range, frame rate, size, quality.

The project is not tied to a frame rate or a pixel size: times are microseconds and
positions are fractions of the canvas, so an export can use any frame rate and any size
with the project's shape. Size is a multiple of the project's own resolution.
"""
import os

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton, QVBoxLayout,
                               QWidget)

from .inspector import SpinBox
from .timeline import US, timecode

QUALITY = (("高畫質", {"crf": 16, "preset": "medium"}),
           ("標準", {"crf": 20, "preset": "medium"}),
           ("小檔案", {"crf": 26, "preset": "fast"}))
FPS_CHOICES = (10, 25, 30, 40, 60, 100)
SCALE_CHOICES = (0.25, 0.5, 1, 2, 4)


def even(v):
    """Encoders want even sizes."""
    return max(2, int(round(v / 2)) * 2)


def export_size(width, height, scale):
    return even(width * scale), even(height * scale)


class ExportDialog(QDialog):
    def __init__(self, parent, default_path, fps, length, mark_in, mark_out, width=1920, height=1080, out_fps=None):
        """fps, length, mark_in / mark_out: the editor's frames (時間線精度); out_fps: the frame
        rate offered for the file (the project's), fps when None."""
        super().__init__(parent)
        self.setWindowTitle("匯出影片")
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
        lay.addLayout(form)
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

    def out_fps(self):
        i = self.fps_box.currentIndex()
        return float(FPS_CHOICES[i]) if i < len(FPS_CHOICES) else self.fps_custom.value()

    def scale(self):
        i = self.scale_box.currentIndex()
        return float(SCALE_CHOICES[i]) if i < len(SCALE_CHOICES) else self.scale_custom.value()

    def _tc(self, frame):
        return timecode(frame / self.fps * US, self.fps)

    def _browse(self):
        fn, _ = QFileDialog.getSaveFileName(self, "匯出影片", self.path.text(), "MP4 (*.mp4)")
        if fn:
            self.path.setText(fn if fn.lower().endswith(".mp4") else fn + ".mp4")

    def result_options(self):
        """(path, first us, end us, {width, height, fps}, encoder options)."""
        a, b = self.range if self.marked.isChecked() else (0, self.length - 1)
        path = self.path.text().strip()
        if path and not path.lower().endswith(".mp4"):
            path += ".mp4"
        w, h = export_size(self.W, self.H, self.scale())
        fmt = {"width": w, "height": h, "fps": self.out_fps()}
        return (os.path.abspath(path) if path else "", a / self.fps * US, (b + 1) / self.fps * US, fmt,
                dict(QUALITY[self.quality.currentIndex()][1]))
