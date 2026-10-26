"""字體對應: the fonts the project uses. A font this computer does not have gets a stand-in
(fonts.py, project["font_map"]); one it has can be swapped for another in every text (換成).

The window does not block the editor: closing it, or 之後再說, leaves the fonts as they are
(missing ones are drawn with a default font) and it comes back the next time the project
opens with fonts missing. A stand-in is kept for this operating system only: the project
opened on the other system still uses its own fonts, or its own choices. Swapping a font that
is here is an edit of the texts themselves (every system, and Ctrl+Z undoes it).
"""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QCompleter, QDialog, QDialogButtonBox, QGridLayout, QLabel, QScrollArea,
                               QVBoxLayout, QWidget)

from .. import fonts

SYSTEMS = {"windows": "Windows", "linux": "Linux", "mac": "macOS"}
SKIP = "（不處理）"
KEEP = "（不變）"


class FontMapDialog(QDialog):
    applied = Signal(dict)              # {font file: stand-in file, or None to forget its stand-in}
    replaced = Signal(dict)             # {font file here: font file every text using it takes instead}

    def __init__(self, parent, rows, installed, counts=None):
        """rows: [(font file the project names, stand-in to show selected or None, kind)] -
        kind "gone" (missing here, no stand-in), "mapped" (missing here, has a stand-in) or
        "here" (this computer has it: the box offers a font to swap it for); installed:
        fonts.scan() entries; counts: {font file: how many texts use it}."""
        super().__init__(parent)
        system = SYSTEMS.get(fonts.os_key(), fonts.os_key())
        self.setWindowTitle(f"字體對應（{system}）")
        self.setModal(False)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(760, min(600, 220 + 40 * len(rows)))
        lay = QVBoxLayout(self)
        n = sum(1 for r in rows if r[2] == "gone")
        text = (f"這台電腦（{system}）找不到專案用到的 {n} 個字體，文字會先用預設字體顯示。\n"
                if n else "專案用到的所有字體。\n")
        if any(r[2] != "here" for r in rows):
            text += f"這台電腦沒有的字體：選一個字體代替，只記在 {system} 上，在另一個系統打開時仍用那邊自己的字體。\n"
        if any(r[2] == "here" for r in rows):
            text += "這台電腦有的字體：選一個新字體，所有用到它的文字都會換掉（Ctrl+Z 可以復原）。\n"
        hint = QLabel(text + "不處理就關掉這個視窗，之後可以從「編輯 > 字體對應…」再設定。")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        names = {f["path"]: f["name"] for f in installed}
        counts = counts or {}
        body = QWidget()
        grid = QGridLayout(body)
        grid.setColumnStretch(2, 1)
        grid.addWidget(QLabel("原本的字體"), 0, 0)
        grid.addWidget(QLabel("文字"), 0, 1)
        grid.addWidget(QLabel("換成 / 用這個字體代替"), 0, 2)
        self.boxes, self.kinds = {}, {}
        for i, (path, choice, kind) in enumerate(rows, 1):
            label = names.get(path) or os.path.basename(path)
            name = QLabel(label + {"gone": "（這台電腦沒有）", "mapped": "（已對應）", "here": ""}[kind])
            name.setToolTip(path)
            used = QLabel(f"{counts[path]} 個" if path in counts else "")
            used.setStyleSheet("color: #9a9aa0;")
            box = QComboBox()
            box.setEditable(True)                 # type to search
            box.setInsertPolicy(QComboBox.NoInsert)
            box.setMaxVisibleItems(20)
            box.addItem(KEEP if kind == "here" else SKIP, None)
            for f in installed:
                if not (kind == "here" and f["path"] == path):
                    box.addItem(f["name"], f["path"])
            comp = QCompleter(box.model(), box)
            comp.setFilterMode(Qt.MatchContains)
            comp.setCaseSensitivity(Qt.CaseInsensitive)
            box.setCompleter(comp)
            j = box.findData(choice) if choice else 0
            box.setCurrentIndex(max(0, j))
            grid.addWidget(name, i, 0)
            grid.addWidget(used, i, 1)
            grid.addWidget(box, i, 2)
            self.boxes[path], self.kinds[path] = box, kind
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

    def _picked(self, box):
        """What a box shows (a typed name counts when it is one of the fonts)."""
        i = box.findText(box.currentText(), Qt.MatchFixedString)
        return box.itemData(i) if i >= 0 else None

    def choices(self):
        """{missing font file: chosen stand-in or None}."""
        return {p: self._picked(b) for p, b in self.boxes.items() if self.kinds[p] != "here"}

    def swaps(self):
        """{font file here: the font its texts take instead}, for the boxes that were changed."""
        out = {p: self._picked(b) for p, b in self.boxes.items() if self.kinds[p] == "here"}
        return {p: v for p, v in out.items() if v}

    def _apply(self):
        stand_ins, swaps = self.choices(), self.swaps()
        if stand_ins:
            self.applied.emit(stand_ins)
        if swaps:
            self.replaced.emit(swaps)
        self.close()
