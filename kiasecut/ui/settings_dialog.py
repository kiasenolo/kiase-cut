"""Settings: the KiaseCut root folder (where the Library, projects, autosaves, layouts and tools
go unless set apart), where the Library lives, the default place for new projects, autosave (how
often, how many are kept, where), where project caches go, GPU acceleration, a check that the
filter engine works on this computer, and the questions answered for good (不再詢問, ask.py)."""
import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from .. import fx, gpu, library, workspace
from . import ask

CACHE_CHOICES = ((workspace.CACHE_DEFAULT, "預設（使用者的緩存資料夾）"),
                 (workspace.CACHE_PROJECT, "專案內（專案資料夾裡的 Cache）"),
                 (workspace.CACHE_CUSTOM, "專案外（自訂資料夾）"))


class SettingsDialog(QDialog):
    def __init__(self, parent, library_dir, default_library, project_dir, autosave_min, use_gpu=True,
                 autosave_limit=30, autosave_dir="", cache_mode=workspace.CACHE_DEFAULT, cache_custom="",
                 default_cache="", root_dir="", autosave_custom=""):
        super().__init__(parent)
        self.setWindowTitle("設定")
        self.setMinimumWidth(600)
        self.old_library = library_dir
        self.default_library = default_library
        form = QFormLayout()

        row = QHBoxLayout()
        self.root = QLineEdit(root_dir)
        self.root_was = root_dir
        browse = QPushButton("瀏覽…")
        browse.clicked.connect(lambda: self._browse(self.root, "選擇 KiaseCut 根資料夾"))
        row.addWidget(self.root, 1)
        row.addWidget(browse)
        form.addRow("根資料夾", row)
        note = QLabel("Library、新專案、自動存檔、佈局和額外工具的資料，沒有另外設定位置時都放在這裡。")
        note.setStyleSheet("color: #9a9aa0;")
        note.setWordWrap(True)
        form.addRow("", note)
        self.root.textChanged.connect(self._root_changed)

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
        note = QLabel("直接把檔案放進這個資料夾裡也可以，程式會自動認得；放在裡面的檔案不會被複製到專案。")
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
        row = QHBoxLayout()
        self.autosave_dir = QLineEdit(autosave_custom)
        self.autosave_dir.setPlaceholderText("根資料夾裡的 auto-save")
        browse = QPushButton("瀏覽…")
        browse.clicked.connect(lambda: self._browse(self.autosave_dir, "選擇放自動存檔的資料夾"))
        row.addWidget(self.autosave_dir, 1)
        row.addWidget(browse)
        form.addRow("自動存檔位置", row)
        note = QLabel("換位置在下次開啟程式時生效。")
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

        row = QHBoxLayout()
        reset_all = QPushButton("重置所有的「不再詢問」")
        reset_all.clicked.connect(self._reset_questions)
        each = QPushButton("選擇哪些要問…")
        each.clicked.connect(lambda: QuestionsDialog(self).exec())
        row.addWidget(reset_all)
        row.addWidget(each)
        row.addStretch(1)
        form.addRow("詢問", row)

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

    def _root_changed(self, text):
        """Fields that were the old root's own places follow it to the new one."""
        old, new = self.root_was.rstrip("/\\"), text.strip().rstrip("/\\")
        if old and new:
            for edit_, sub in ((self.library, "Library"), (self.projects, "")):
                if library.norm(edit_.text().strip() or "-") == library.norm(os.path.join(old, sub) if sub else old):
                    edit_.setText((os.path.join(new, sub) if sub else new).replace("\\", "/"))
        self.root_was = text.strip()

    def _reset_questions(self):
        ask.reset()
        QMessageBox.information(self, "詢問", "之後每個問題都會再問一次。")

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
        self.cache_note.setText(where + "\n換位置後舊的緩存留在原處，可以用「檔案 > 清除專案緩存」刪掉。")
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
        return {"root": library.norm(self.root.text().strip()) if self.root.text().strip() else "",
                "autosave_dir": library.norm(self.autosave_dir.text().strip()) if self.autosave_dir.text().strip() else "",
                "library": library.norm(self.library.text().strip()),
                "copy_library": self.copy.isVisible() and self.copy.isChecked(),
                "project_dir": self.projects.text().strip(), "autosave_min": self.autosave.value(),
                "autosave_limit": self.autosave_limit.value(),
                "gpu": self.gpu.isChecked(), "cache_mode": self.cache_mode.currentData(),
                "cache_custom": library.norm(self.cache_custom.text().strip()) if self.cache_custom.text().strip() else ""}


class QuestionsDialog(QDialog):
    """Each question with 不再詢問: 每次詢問, 一律「是」 or 一律「否」 (ask.py)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("詢問")
        self.setMinimumSize(460, 420)
        body = QWidget()
        form = QFormLayout(body)
        self.boxes = {}
        for key, name in ask.QUESTIONS.items():
            box = QComboBox()
            for value, text in ask.ANSWERS:
                box.addItem(text, value)
            box.setCurrentIndex(max(0, box.findData(ask.remembered(key))))
            self.boxes[key] = box
            form.addRow(name, box)
        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("確定")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._keep)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        note = QLabel("未儲存的修改、永久刪除這類問題一定會問。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #9a9aa0;")
        lay.addWidget(note)
        lay.addWidget(scroll, 1)
        lay.addWidget(buttons)

    def _keep(self):
        for key, box in self.boxes.items():
            ask.remember(key, box.currentData())
        self.accept()
