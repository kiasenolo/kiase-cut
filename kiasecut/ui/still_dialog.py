"""截取並匯出當下幀: the frame at the playhead as a picture file - its format (PNG, JPEG, WebP,
TIFF, BMP), its size (a multiple of the project's resolution, as the video export), and a
transparent background where the format keeps one, or a background colour."""
import os

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QVBoxLayout, QWidget)
from PySide6.QtCore import Qt

from ..renderexport import STILL_FORMATS
from .colorpick import hex_of, pick_color, qcolor
from .export_dialog import SCALE_CHOICES


class StillDialog(QDialog):
    def __init__(self, parent, default_path, width, height, settings=None):
        """settings: what was used last time {format, scale, alpha, background, quality}."""
        super().__init__(parent)
        self.setWindowTitle("匯出目前畫面")
        st = dict({"format": ".png", "scale": 1, "alpha": True, "background": "#000000", "quality": 92},
                  **(settings or {}))
        self.W, self.H = width, height
        lay = QVBoxLayout(self)
        form = QFormLayout()
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        self.path = QLineEdit(os.path.splitext(default_path)[0] + st["format"])
        browse = QPushButton("瀏覽…")
        browse.clicked.connect(self._browse)
        rl.addWidget(self.path, 1)
        rl.addWidget(browse)
        form.addRow("檔案", row)
        self.fmt = QComboBox()
        for name, ext, _a in STILL_FORMATS:
            self.fmt.addItem(name, ext)
        self.fmt.setCurrentIndex(max(0, self.fmt.findData(st["format"])))
        self.fmt.currentIndexChanged.connect(self._format_changed)
        form.addRow("格式", self.fmt)
        self.scale = QComboBox()
        for k in SCALE_CHOICES:
            self.scale.addItem(f"{k:g}×（{round(width * k)} × {round(height * k)}）", k)
        self.scale.setCurrentIndex(max(0, self.scale.findData(st["scale"])))
        form.addRow("大小", self.scale)
        self.alpha = QCheckBox("透明背景")
        self.alpha.setChecked(bool(st["alpha"]))
        self.alpha.toggled.connect(self._update)
        form.addRow("", self.alpha)
        self.bg = qcolor(st["background"], "black")
        self.bg_btn = QPushButton()
        self.bg_btn.clicked.connect(self._pick_bg)
        form.addRow("背景顏色", self.bg_btn)
        self.quality = QSlider(Qt.Horizontal)
        self.quality.setRange(10, 100)
        self.quality.setValue(int(st["quality"]))
        self.q_lbl = QLabel()
        self.quality.valueChanged.connect(lambda v: self.q_lbl.setText(str(v)))
        qrow = QWidget()
        ql = QHBoxLayout(qrow)
        ql.setContentsMargins(0, 0, 0, 0)
        ql.addWidget(self.quality, 1)
        ql.addWidget(self.q_lbl)
        form.addRow("品質", qrow)
        lay.addLayout(form)
        self.note = QLabel()
        self.note.setStyleSheet("color: #8a8a90")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("匯出")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.q_lbl.setText(str(self.quality.value()))
        self._update()

    def _can_alpha(self):
        return next(a for _n, e, a in STILL_FORMATS if e == self.fmt.currentData())

    def _format_changed(self, _i):
        base = os.path.splitext(self.path.text())[0]
        self.path.setText(base + self.fmt.currentData())
        self._update()

    def _update(self):
        can = self._can_alpha()
        self.alpha.setEnabled(can)
        transparent = can and self.alpha.isChecked()
        self.bg_btn.setEnabled(not transparent)
        name = hex_of(self.bg)
        self.bg_btn.setText(name)
        self.bg_btn.setStyleSheet(f"background: {name[:7]}; color: {'#000' if self.bg.lightness() > 140 else '#fff'};")
        lossy = self.fmt.currentData() in (".jpg", ".webp")
        self.quality.setEnabled(lossy)
        self.note.setText("" if can else f"{self.fmt.currentText()} 不能存透明，空白的地方會填上背景顏色。")

    def _pick_bg(self):
        col = pick_color(self, self.bg, "背景顏色", alpha=False)
        if col is not None:
            self.bg = col
            self._update()

    def _browse(self):
        ext = self.fmt.currentData()
        path, _ = QFileDialog.getSaveFileName(self, "匯出目前畫面", self.path.text(), f"{self.fmt.currentText()} (*{ext})")
        if path:
            if not os.path.splitext(path)[1]:
                path += ext
            self.path.setText(path)

    def options(self):
        """(path, (w, h), alpha, background QColor, quality, settings to remember)."""
        k = self.scale.currentData()
        size = (max(1, round(self.W * k)), max(1, round(self.H * k)))
        alpha = self._can_alpha() and self.alpha.isChecked()
        st = {"format": self.fmt.currentData(), "scale": k, "alpha": self.alpha.isChecked(),
              "background": hex_of(self.bg), "quality": self.quality.value()}
        return self.path.text().strip(), size, alpha, QColor(self.bg), self.quality.value(), st
