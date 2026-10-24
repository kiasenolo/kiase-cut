"""字幕: the words of several text clips of one track, edited together.

Select text clips on one track (Ctrl / Shift + click, a selection box, or 選取軌道上的所有片段
in the track's menu) and their words show here one clip per line, in time order:

    text1
    text2
    text3

A line break inside one clip is written \\n. 套用 (Ctrl+Enter) gives every clip its line, as
one undo step; it needs exactly one line per clip. While the box has unapplied changes the
selection's own words do not overwrite it, until another set of clips is selected.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from .. import edit
from .inspector import section


class SubtitlePanel(QWidget):
    textsEdited = Signal(dict)                      # {clip id: new words}, only the changed ones

    def __init__(self, parent=None):
        super().__init__(parent)
        self.clips = []                             # the text clips shown, in time order
        self.key = None                             # their ids, to notice another selection
        self.contents = []                          # their words when shown
        self.dirty = False                          # the box has changes not applied yet
        self._loading = False
        lay = QVBoxLayout(self)
        lay.addWidget(section("批量編輯文字"))
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #8a8a90")
        lay.addWidget(self.hint)
        self.body = QWidget()
        b = QVBoxLayout(self.body)
        b.setContentsMargins(0, 0, 0, 0)
        self.editor = QPlainTextEdit()
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setToolTip("一行一個片段，依時間先後；片段內的換行寫成 \\n")
        self.editor.setFont(QFont(self.editor.font().family(), self.editor.font().pointSize() + 1))
        self.editor.textChanged.connect(self._changed)
        b.addWidget(self.editor, 1)
        self.count = QLabel()
        b.addWidget(self.count)
        row = QHBoxLayout()
        self.revert_btn = QPushButton("還原")
        self.revert_btn.setToolTip("放棄還沒套用的修改")
        self.revert_btn.clicked.connect(self.revert)
        self.apply_btn = QPushButton("套用")
        self.apply_btn.setToolTip("每個片段換成它那一行（Ctrl+Enter）")
        self.apply_btn.clicked.connect(self.apply)
        row.addStretch(1)
        row.addWidget(self.revert_btn)
        row.addWidget(self.apply_btn)
        b.addLayout(row)
        for keys in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(keys), self.editor, self.apply, context=Qt.WidgetShortcut)
        lay.addWidget(self.body, 1)
        self.show_selection([], set())

    def show_selection(self, rows, ids):
        """rows: the timeline's tracks; ids: the selected clips."""
        tracks = [t for t in rows if any(c["id"] in ids for c in t["clips"])]
        clips = sorted((c for t in tracks for c in t["clips"] if c["id"] in ids), key=lambda c: c["start_us"])
        if not clips:
            hint = "在同一條軌道上選取文字片段（Ctrl / Shift + 點選、框選，或軌道選單的「選取軌道上的所有片段」），就能在這裡一次編輯它們的文字。"
        elif len(tracks) > 1:
            hint = "選取的片段在不同軌道上：字幕只能編輯同一條軌道的文字片段。"
        elif any(c["type"] != "text" for c in clips):
            hint = "選取的片段中有不是文字的片段：字幕只能編輯文字片段。"
        else:
            hint = None
        if hint:
            clips = []
        self.hint.setText(hint or f"{tracks[0].get('name') or '文字軌道'}：{len(clips)} 個文字片段，一行一個。")
        self.body.setVisible(bool(clips))
        key = tuple(c["id"] for c in clips)
        contents = [c["text"]["content"] for c in clips]
        if key == self.key and (self.dirty or contents == self.contents):
            self.clips = clips
            return
        self.clips, self.key, self.contents = clips, key, contents
        self._load()

    def _load(self):
        self._loading = True
        self.editor.setPlainText("\n".join(edit.subtitle_line(t) for t in self.contents))
        self._loading = False
        self.dirty = False
        self._update()

    def _changed(self):
        if not self._loading:
            self.dirty = True
            self._update()

    def lines(self):
        return edit.subtitle_lines(self.editor.toPlainText())

    def _update(self):
        n, m = len(self.lines()), len(self.clips)
        self.count.setText(f"{n} 行 / {m} 個片段" + ("" if n == m else f"：行數要剛好 {m} 行"))
        self.count.setStyleSheet("" if n == m else "color: #e06c6c")
        self.apply_btn.setEnabled(self.dirty and n == m)
        self.revert_btn.setEnabled(self.dirty)

    def revert(self):
        self._load()

    def apply(self):
        lines = self.lines()
        if not self.dirty or len(lines) != len(self.clips):
            return
        changed = {c["id"]: ln for c, ln in zip(self.clips, lines) if ln != c["text"]["content"]}
        self.dirty = False                          # the edit's refresh then shows the new words
        self._update()
        if changed:
            self.textsEdited.emit(changed)
