"""字體對應: which installed font stands in for each font the project names but this computer
does not have (fonts.py, project["font_map"]).

The window does not block the editor: closing it, or 之後再說, leaves the fonts as they are
(the texts are drawn with a default font) and it comes back the next time the project opens.
A choice is kept for this operating system only: the project opened on the other system
still uses its own fonts, or its own choices.
"""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QCompleter, QDialog, QDialogButtonBox, QGridLayout, QLabel, QScrollArea,
                               QVBoxLayout, QWidget)

from .. import fonts

SYSTEMS = {"windows": "Windows", "linux": "Linux", "mac": "macOS"}
SKIP = "（不處理）"


class FontMapDialog(QDialog):
    applied = Signal(dict)              # {font file: stand-in file, or None to forget its stand-in}

    def __init__(self, parent, rows, installed):
        """rows: [(font file the project names, stand-in to show selected or None, whether it
        is missing here without a stand-in)]; installed: fonts.scan() entries."""
        super().__init__(parent)
        system = SYSTEMS.get(fonts.os_key(), fonts.os_key())
        self.setWindowTitle(f"字體對應（{system}）")
        self.setModal(False)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(720, min(560, 200 + 40 * len(rows)))
        lay = QVBoxLayout(self)
        n = sum(1 for r in rows if r[2])
        hint = QLabel((f"這台電腦（{system}）找不到專案用到的 {n} 個字體，文字會先用預設字體顯示。"
                       if n else "專案用到的字體和這台電腦上代替它們的字體。")
                      + f"\n選擇要用哪個字體代替：只記在 {system} 上，在另一個系統打開這個專案時仍用那邊自己的字體。"
                      + "\n不處理就關掉這個視窗，之後可以從「編輯 > 字體對應…」再設定。")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setColumnStretch(1, 1)
        grid.addWidget(QLabel("原本的字體"), 0, 0)
        grid.addWidget(QLabel("用這個字體代替"), 0, 1)
        self.boxes = {}
        for i, (path, choice, gone) in enumerate(rows, 1):
            name = QLabel(os.path.basename(path) + ("" if gone else "（已對應）"))
            name.setToolTip(path)
            box = QComboBox()
            box.setEditable(True)                 # type to search
            box.setInsertPolicy(QComboBox.NoInsert)
            box.setMaxVisibleItems(20)
            box.addItem(SKIP, None)
            for f in installed:
                box.addItem(f["name"], f["path"])
            comp = QCompleter(box.model(), box)
            comp.setFilterMode(Qt.MatchContains)
            comp.setCaseSensitivity(Qt.CaseInsensitive)
            box.setCompleter(comp)
            j = box.findData(choice) if choice else 0
            box.setCurrentIndex(max(0, j))
            grid.addWidget(name, i, 0)
            grid.addWidget(box, i, 1)
            self.boxes[path] = box
        grid.setRowStretch(len(rows) + 1, 1)
        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        lay.addWidget(scroll, 1)
        buttons = QDialogButtonBox()
        ok = buttons.addButton("套用", QDialogButtonBox.AcceptRole)
        later = buttons.addButton("之後再說", QDialogButtonBox.RejectRole)
        ok.clicked.connect(self._apply)
        later.clicked.connect(self.close)
        lay.addWidget(buttons)

    def choices(self):
        """{font file: chosen stand-in or None}, from what the boxes show (a typed name counts
        when it is one of the fonts)."""
        out = {}
        for path, box in self.boxes.items():
            i = box.findText(box.currentText(), Qt.MatchFixedString)
            out[path] = box.itemData(i) if i >= 0 else None
        return out

    def _apply(self):
        self.applied.emit(self.choices())
        self.close()
