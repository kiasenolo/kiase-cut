"""Export settings: file, whole film or the marked range, quality."""
import os

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLineEdit, QPushButton, QRadioButton, QVBoxLayout, QWidget)

from .timeline import US, timecode

QUALITY = (("高畫質", {"crf": 16, "preset": "medium"}),
           ("標準", {"crf": 20, "preset": "medium"}),
           ("小檔案", {"crf": 26, "preset": "fast"}))


class ExportDialog(QDialog):
    def __init__(self, parent, default_path, fps, length, mark_in, mark_out):
        super().__init__(parent)
        self.setWindowTitle("匯出影片")
        self.fps, self.length = fps, length
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
        self.resize(560, 0)

    def _tc(self, frame):
        return timecode(frame / self.fps * US, self.fps)

    def _browse(self):
        fn, _ = QFileDialog.getSaveFileName(self, "匯出影片", self.path.text(), "MP4 (*.mp4)")
        if fn:
            self.path.setText(fn if fn.lower().endswith(".mp4") else fn + ".mp4")

    def result_options(self):
        """(path, in frame, out frame, encoder options)."""
        a, b = self.range if self.marked.isChecked() else (0, self.length - 1)
        path = self.path.text().strip()
        if path and not path.lower().endswith(".mp4"):
            path += ".mp4"
        return os.path.abspath(path) if path else "", a, b, dict(QUALITY[self.quality.currentIndex()][1])
