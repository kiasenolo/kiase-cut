"""Settings: where the Library lives, the default place for new projects, autosave (how often,
how many are kept), where project caches go, GPU acceleration, and a check that the filter engine works on this
computer."""
import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout)

from .. import fx, gpu, library, workspace

CACHE_CHOICES = ((workspace.CACHE_DEFAULT, "預設（使用者的緩存資料夾）"),
                 (workspace.CACHE_PROJECT, "專案內（專案資料夾裡的 Cache）"),
                 (workspace.CACHE_CUSTOM, "專案外（自訂資料夾）"))


class SettingsDialog(QDialog):
    def __init__(self, parent, library_dir, default_library, project_dir, autosave_min, use_gpu=True,
                 autosave_limit=30, autosave_dir="", cache_mode=workspace.CACHE_DEFAULT, cache_custom="",
                 default_cache=""):
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
        form.addRow("自動存檔間隔", self.autosave)
        row = QHBoxLayout()
        self.autosave_limit = QSpinBox()
        self.autosave_limit.setRange(1, 999)
        self.autosave_limit.setValue(autosave_limit)
        self.autosave_limit.setSuffix(" 個檔案")
        show = QPushButton("開啟資料夾")
        show.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(autosave_dir))
                             if os.path.isdir(autosave_dir) else None)
        row.addWidget(self.autosave_limit)
        row.addWidget(show)
        row.addStretch(1)
        form.addRow("自動存檔上限", row)
        note = QLabel(f"有未儲存的修改時，每隔一段時間存一份到 {autosave_dir}，只留最新的幾份。\n"
                      "程式沒有正常結束（當掉、斷電）時，下次開啟會問要不要回復。")
        note.setStyleSheet("color: #9a9aa0;")
        note.setWordWrap(True)
        form.addRow("", note)

        row = QHBoxLayout()
        self.cache_mode = QComboBox()
        for mode, text in CACHE_CHOICES:
            self.cache_mode.addItem(text, mode)
        self.cache_mode.setCurrentIndex(max(0, self.cache_mode.findData(cache_mode)))
        self.cache_custom = QLineEdit(cache_custom)
        self.cache_custom.setPlaceholderText("選擇放緩存的資料夾")
        self.cache_browse = QPushButton("瀏覽…")
        self.cache_browse.clicked.connect(lambda: self._browse(self.cache_custom, "選擇放緩存的資料夾"))
        row.addWidget(self.cache_mode)
        row.addWidget(self.cache_custom, 1)
        row.addWidget(self.cache_browse)
        form.addRow("緩存位置", row)
        self.default_cache = default_cache
        self.cache_note = QLabel("")
        self.cache_note.setStyleSheet("color: #9a9aa0;")
        self.cache_note.setWordWrap(True)
        form.addRow("", self.cache_note)
        self.cache_mode.currentIndexChanged.connect(self._cache_changed)
        self.cache_custom.textChanged.connect(self._cache_changed)

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
        self._cache_changed()

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
        self._cache_changed()                     # (also checks the library field)

    def _cache_changed(self):
        mode = self.cache_mode.currentData()
        custom = mode == workspace.CACHE_CUSTOM
        self.cache_custom.setVisible(custom)
        self.cache_browse.setVisible(custom)
        where = {workspace.CACHE_DEFAULT: f"放在 {self.default_cache}，每個專案一個資料夾。",
                 workspace.CACHE_PROJECT: "放在專案資料夾裡的 Cache，跟著專案一起搬移、複製。",
                 workspace.CACHE_CUSTOM: "放在上面選的資料夾裡，每個專案一個資料夾。"}[mode]
        self.cache_note.setText(where + "\n緩存是波形、聲音、文字和遮罩的圖片等，刪掉會在需要時重新產生；"
                                "放在專案外，搬移專案時就不用帶著它。換位置後舊的緩存留在原處，"
                                "可以用「檔案 > 清除專案緩存」刪掉。")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(bool(self.library.text().strip()) and
                                                           (not custom or bool(self.cache_custom.text().strip())))

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
        cache = self.cache_custom.text().strip()
        if self.cache_mode.currentData() == workspace.CACHE_CUSTOM and os.path.exists(cache) and not os.path.isdir(cache):
            QMessageBox.warning(self, "緩存位置", "這個位置是一個檔案，請選擇資料夾。")
            return
        self.accept()

    def values(self):
        return {"library": library.norm(self.library.text().strip()),
                "copy_library": self.copy.isVisible() and self.copy.isChecked(),
                "project_dir": self.projects.text().strip(), "autosave_min": self.autosave.value(),
                "autosave_limit": self.autosave_limit.value(),
                "gpu": self.gpu.isChecked(), "cache_mode": self.cache_mode.currentData(),
                "cache_custom": library.norm(self.cache_custom.text().strip()) if self.cache_custom.text().strip() else ""}
