"""Settings: where the Library lives, the default place for new projects, backups, GPU
acceleration, and a check that the filter engine works on this computer."""
import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout)

from .. import fx, gpu, library


class SettingsDialog(QDialog):
    def __init__(self, parent, library_dir, default_library, project_dir, autosave_min, use_gpu=True):
        super().__init__(parent)
        self.setWindowTitle("設定")
        self.setMinimumWidth(600)
        self.old_library = library_dir
        self.default_library = default_library
        form = QFormLayout()

        row = QHBoxLayout()
        self.library = QLineEdit(library_dir)
        browse = QPushButton("瀏覽…")
        browse.clicked.connect(lambda: self._browse(self.library, "選擇 Library 資料夾"))
        row.addWidget(self.library, 1)
        row.addWidget(browse)
        form.addRow("Library 位置", row)
        row = QHBoxLayout()
        reset = QPushButton("恢復預設位置")
        reset.clicked.connect(lambda: self.library.setText(default_library))
        show = QPushButton("開啟資料夾")
        show.clicked.connect(self._show_library)
        row.addWidget(reset)
        row.addWidget(show)
        row.addStretch(1)
        form.addRow("", row)
        self.copy = QCheckBox("把目前 Library 的內容複製到新位置")
        self.copy.setChecked(True)
        form.addRow("", self.copy)
        note = QLabel("Library 是所有專案共用的素材：影片、圖片、音效、濾鏡、文字樣式。\n"
                      "直接把檔案放進這個資料夾裡也可以，程式會自動認得；放在裡面的檔案不會被複製到專案。")
        note.setStyleSheet("color: #9a9aa0;")
        note.setWordWrap(True)
        form.addRow("", note)

        row = QHBoxLayout()
        self.projects = QLineEdit(project_dir)
        browse = QPushButton("瀏覽…")
        browse.clicked.connect(lambda: self._browse(self.projects, "新專案預設的存放位置"))
        row.addWidget(self.projects, 1)
        row.addWidget(browse)
        form.addRow("新專案預設位置", row)

        self.autosave = QSpinBox()
        self.autosave.setRange(1, 60)
        self.autosave.setValue(autosave_min)
        self.autosave.setSuffix(" 分鐘")
        form.addRow("自動備份間隔", self.autosave)

        self.gpu = QCheckBox("使用 GPU 加速（NVIDIA：匯出用 NVENC 編碼，HEVC / AV1 / VP9 影片用 GPU 解碼）")
        self.gpu.setChecked(use_gpu)
        self.gpu_note = QLabel(gpu.describe())
        self.gpu_note.setStyleSheet("color: #9a9aa0;")
        self.gpu.toggled.connect(self._gpu_toggled)
        form.addRow("GPU 加速", self.gpu)
        form.addRow("", self.gpu_note)

        row = QHBoxLayout()
        self.engine = QLabel("")
        self.engine.setWordWrap(True)
        test = QPushButton("測試")
        test.clicked.connect(self._test_engine)
        row.addWidget(self.engine, 1)
        row.addWidget(test)
        form.addRow("濾鏡引擎", row)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.Ok).setText("確定")
        self.buttons.button(QDialogButtonBox.Cancel).setText("取消")
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.buttons)
        self.library.textChanged.connect(self._library_changed)
        self._library_changed()

    def _browse(self, edit, title):
        d = QFileDialog.getExistingDirectory(self, title, edit.text() or "")
        if d:
            edit.setText(d.replace("\\", "/"))

    def _show_library(self):
        path = self.library.text().strip()
        if os.path.isdir(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.information(self, "Library", "這個資料夾還不存在，按確定後會建立。")

    def _library_changed(self):
        new = library.norm(self.library.text().strip()) if self.library.text().strip() else ""
        old = library.norm(self.old_library)
        moved = bool(new) and new != old and os.path.isdir(old)
        self.copy.setVisible(moved)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(bool(new))

    def _gpu_toggled(self, on):
        was, gpu.enabled = gpu.enabled, on
        self.gpu_note.setText(gpu.describe())
        gpu.enabled = was                         # (applied on 確定)

    def _test_engine(self):
        try:
            err = fx.check("builtin:blur")
        except Exception as exc:                 # no OpenGL at all
            err = str(exc)
        self.engine.setText("可以使用" if not err else "無法使用：" + err)
        self.engine.setStyleSheet("color: " + ("#5cb85c;" if not err else "#e0605a;"))

    def _accept(self):
        new = self.library.text().strip()
        if os.path.exists(new) and not os.path.isdir(new):
            QMessageBox.warning(self, "Library", "這個位置是一個檔案，請選擇資料夾。")
            return
        self.accept()

    def values(self):
        return {"library": library.norm(self.library.text().strip()),
                "copy_library": self.copy.isVisible() and self.copy.isChecked(),
                "project_dir": self.projects.text().strip(), "autosave_min": self.autosave.value(),
                "gpu": self.gpu.isChecked()}
