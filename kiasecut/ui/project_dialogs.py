"""New project and project information dialogs (the project is a folder, as in FL Studio)."""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout)

from .. import workspace

PRESETS = (("1920 × 1080 橫式", 1920, 1080), ("3840 × 2160 橫式（4K）", 3840, 2160),
           ("1280 × 720 橫式", 1280, 720), ("1080 × 1920 直式", 1080, 1920),
           ("1080 × 1080 方形", 1080, 1080), ("2560 × 1440 橫式", 2560, 1440))
FPS = (24, 25, 30, 50, 60)


class CompoundSizeDialog(QDialog):
    """The name and shape of a new compound / static compound made from the compound list.
    Only its proportions matter: the content stays vector and is drawn at whatever size it
    is shown or exported at."""

    def __init__(self, parent, name, width, height, static=False):
        super().__init__(parent)
        self.setWindowTitle("新增靜態複合片段" if static else "新增複合片段")
        form = QFormLayout()
        self.name = QLineEdit(name)
        form.addRow("名稱", self.name)
        self.preset = QComboBox()
        self.preset.addItem(f"跟專案（{width} × {height}）", (width, height))
        for label, w, h in PRESETS:
            if (w, h) != (width, height):
                self.preset.addItem(label, (w, h))
        self.preset.addItem("自訂…", None)
        form.addRow("解析度", self.preset)
        self.custom = QWidget()
        cl = QHBoxLayout(self.custom)
        cl.setContentsMargins(0, 0, 0, 0)
        self.cw, self.ch = QSpinBox(), QSpinBox()
        for sb, v in ((self.cw, width), (self.ch, height)):
            sb.setRange(1, 16384)
            sb.setValue(v)
        cl.addWidget(self.cw)
        cl.addWidget(QLabel("×"))
        cl.addWidget(self.ch)
        cl.addStretch(1)
        form.addRow("自訂大小", self.custom)
        self.custom.setVisible(False)
        self.preset.currentIndexChanged.connect(lambda _i: self.custom.setVisible(self.preset.currentData() is None))
        note = QLabel("只用來決定畫面的比例：裡面的內容一樣是向量，顯示和匯出時照實際的大小重新畫，不會變模糊。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #9a9aa0;")
        form.addRow("", note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("建立")
        bb.button(QDialogButtonBox.Cancel).setText("取消")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(bb)

    def result(self):
        """(name, (width, height))."""
        size = self.preset.currentData() or (self.cw.value(), self.ch.value())
        return self.name.text().strip(), size


class NewProjectDialog(QDialog):
    """Name + where to put the project folder (+ size and frame rate for an empty project)."""

    def __init__(self, parent, location, name="新專案", fixed_format=None, title="新專案"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        form = QFormLayout()
        self.name = QLineEdit(name)
        form.addRow("專案名稱", self.name)
        row = QHBoxLayout()
        self.location = QLineEdit(location)
        browse = QPushButton("瀏覽…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.location, 1)
        row.addWidget(browse)
        form.addRow("存放位置", row)
        self.preset = QComboBox()
        self.fps = QComboBox()
        self.fixed = fixed_format
        if fixed_format:
            w, h, fps = fixed_format
            form.addRow("格式", QLabel(f"{w} × {h}，{fps:g} fps（沿用匯入的草稿）"))
        else:
            for label, w, h in PRESETS:
                self.preset.addItem(label, (w, h))
            self.preset.addItem("自訂…", None)
            form.addRow("解析度", self.preset)
            self.custom = QWidget()
            cl = QHBoxLayout(self.custom)
            cl.setContentsMargins(0, 0, 0, 0)
            self.cw, self.ch = QSpinBox(), QSpinBox()
            for sb, v in ((self.cw, 1920), (self.ch, 1080)):
                sb.setRange(16, 16384)
                sb.setSingleStep(2)
                sb.setValue(v)
            cl.addWidget(self.cw)
            cl.addWidget(QLabel("×"))
            cl.addWidget(self.ch)
            cl.addWidget(QLabel("像素"))
            cl.addStretch(1)
            form.addRow("自訂大小", self.custom)
            self.custom.setVisible(False)
            self.preset.currentIndexChanged.connect(lambda _i: self.custom.setVisible(self.preset.currentData() is None))
            for f in FPS:
                self.fps.addItem(f"{f} fps", f)
            self.fps.setCurrentIndex(FPS.index(60))
            form.addRow("影格率", self.fps)
        self.where = QLabel()
        self.where.setWordWrap(True)
        self.where.setStyleSheet("color: #9a9aa0;")
        form.addRow("", self.where)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.Ok).setText("建立專案")
        self.buttons.button(QDialogButtonBox.Cancel).setText("取消")
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.buttons)
        self.name.textChanged.connect(self._check)
        self.location.textChanged.connect(self._check)
        self._check()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "選擇存放位置", self.location.text() or "")
        if d:
            self.location.setText(d)

    def folder(self):
        return os.path.join(self.location.text().strip(), workspace.safe_name(self.name.text(), ""))

    def _check(self):
        ok, msg = True, ""
        if not self.name.text().strip() or not self.location.text().strip():
            ok, msg = False, "請輸入名稱和位置"
        else:
            f = self.folder()
            if os.path.isdir(f) and os.listdir(f):
                ok, msg = False, f"「{os.path.basename(f)}」已經存在，請換一個名稱"
            else:
                msg = f"將建立：{f}"
        self.where.setText(msg)
        self.where.setStyleSheet("color: " + ("#9a9aa0;" if ok else "#e0605a;"))
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ok)

    def values(self):
        """(location, name, width, height, fps)"""
        if self.fixed:
            w, h, fps = self.fixed
        else:
            size = self.preset.currentData() or (self.cw.value() // 2 * 2, self.ch.value() // 2 * 2)   # even sizes
            (w, h), fps = size, float(self.fps.currentData())
        return self.location.text().strip(), self.name.text().strip(), w, h, fps


class ProjectInfoDialog(QDialog):
    """File > Project info: title, author, genre, comments, and the project's history."""
    openFolder = Signal()

    def __init__(self, parent, proj, path, stats):
        super().__init__(parent)
        self.setWindowTitle("專案資訊")
        self.setMinimumWidth(560)
        info = workspace.info(proj)
        form = QFormLayout()
        self.title = QLineEdit(info.get("title", ""))
        self.author = QLineEdit(info.get("author", ""))
        self.genre = QLineEdit(info.get("genre", ""))
        self.url = QLineEdit(info.get("url", ""))
        self.comments = QPlainTextEdit(info.get("comments", ""))
        self.comments.setFixedHeight(96)
        form.addRow("標題", self.title)
        form.addRow("作者", self.author)
        form.addRow("類型 / 標籤", self.genre)
        form.addRow("網址", self.url)
        form.addRow("備註", self.comments)

        def ro(text):
            lab = QLabel(text)
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lab.setWordWrap(True)
            return lab
        form.addRow(QLabel(""), QLabel(""))
        form.addRow("開始於", ro(workspace.show_time(info.get("created"))))
        form.addRow("最後開啟", ro(workspace.show_time(info.get("last_opened"))))
        form.addRow("最後儲存", ro(workspace.show_time(info.get("last_saved"))))
        form.addRow("累計編輯時間", ro(workspace.show_duration(info.get("time_spent_s"))))
        form.addRow("開啟次數", ro(str(info.get("opens", 1))))
        form.addRow("", QLabel(""))
        folder = QHBoxLayout()
        where = ro(workspace.root_of(path) if path else "—")
        open_btn = QPushButton("開啟資料夾")
        open_btn.clicked.connect(self.openFolder)
        folder.addWidget(where, 1)
        folder.addWidget(open_btn)
        form.addRow("專案資料夾", folder)
        form.addRow("專案檔", ro(os.path.basename(path) if path else "—"))
        form.addRow("格式", ro(f"{proj['width']} × {proj['height']}，{proj['fps']:g} fps"))
        form.addRow("內容", ro(stats))
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.Ok).setText("確定")
        self.buttons.button(QDialogButtonBox.Cancel).setText("取消")
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.buttons)

    def values(self):
        return {"title": self.title.text().strip(), "author": self.author.text().strip(),
                "genre": self.genre.text().strip(), "url": self.url.text().strip(),
                "comments": self.comments.toPlainText()}
