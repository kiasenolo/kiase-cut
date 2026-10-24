"""節拍: BPM alignment of a sound clip.

With it on, the clip's beats (a grid from its BPM and the first beat's time in the sound),
split into 1, 1/2, 1/3, 1/4 or 1/6 (or thinned to every 2nd / 4th beat: BPM ÷2 / ÷4, as 180
-> 90, without changing the BPM typed in), become snap targets on the timeline: moving and
trimming clips, keyframes and the playhead land on them.
Switching it off keeps the numbers; 重置 (after asking) deletes them and switches it off.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QCheckBox, QFormLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from .. import edit
from .inspector import ComboBox, SpinBox, section
from .timeline import BEAT_COLORS, US

DIV_NAMES = {0.25: "BPM ÷4（每 4 拍）", 0.5: "BPM ÷2（每 2 拍）", 1: "1", 2: "1/2", 3: "1/3", 4: "1/4", 6: "1/6"}


class BeatPanel(QWidget):
    beatEdited = Signal(str, dict)                  # clip id, {on / bpm / offset_us / div: value}
    resetRequested = Signal(str)                    # clip id: delete its BPM settings

    def __init__(self, parent=None):
        super().__init__(parent)
        self.clip_id = None
        lay = QVBoxLayout(self)
        lay.addWidget(section("BPM 對齊"))
        self.hint = QLabel("選一個聲音片段，就能為它設定節拍。")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #8a8a90")
        lay.addWidget(self.hint)
        self.body = QWidget()
        form = QFormLayout(self.body)
        form.setContentsMargins(0, 0, 0, 0)
        self.on = QCheckBox("啟用 BPM 對齊")
        self.on.toggled.connect(lambda v: self._emit(on=v))
        form.addRow(self.on)
        self.bpm = SpinBox()
        self.bpm.setRange(1.0, 999.0)
        self.bpm.setDecimals(2)
        self.bpm.setSingleStep(0.1)
        self.bpm.edited.connect(lambda v: self._emit(bpm=v))
        form.addRow("BPM", self.bpm)
        self.div = ComboBox()
        for d, name in DIV_NAMES.items():
            self.div.addItem(name, d)
            self.div.setItemData(self.div.count() - 1, QColor(BEAT_COLORS.get(d, BEAT_COLORS[1])), Qt.ForegroundRole)
        self.div.setToolTip("每拍再分成幾格，或隔幾拍一格（BPM ÷2：180 → 90，填的 BPM 不變）；格線都會吸附")
        self.div.currentIndexChanged.connect(lambda i: self._emit(div=self.div.itemData(i)))
        form.addRow("細分", self.div)
        legend = QLabel("　".join(f'<span style="color:{BEAT_COLORS[d]}">{"拍" if d == 1 else name}</span>'
                                 for d, name in DIV_NAMES.items() if d in BEAT_COLORS))
        legend.setToolTip("片段上方刻度的顏色：格線落在拍子的哪個位置")
        form.addRow("", legend)
        self.offset = SpinBox()
        self.offset.setRange(-3600.0, 3600.0)
        self.offset.setDecimals(3)
        self.offset.setSingleStep(0.001)
        self.offset.setSuffix(" 秒")
        self.offset.setToolTip("第一拍在這段聲音裡的時間（從素材開頭算，修剪片段時拍子不會跑掉）")
        self.offset.edited.connect(lambda v: self._emit(offset_us=v * US))
        form.addRow("起頭偏移", self.offset)
        self.period = QLabel()
        self.period.setStyleSheet("color: #8a8a90")
        form.addRow("每拍", self.period)
        note = QLabel("開啟後，拖曳片段、修剪、關鍵幀和播放頭都會吸附到這個片段的拍子上（片段上方的刻度，顏色同上）。"
                      "關掉時設定會保留。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #8a8a90")
        form.addRow(note)
        self.reset = QPushButton("重置")
        self.reset.setToolTip("刪除這個片段的 BPM 設定並關閉 BPM 對齊")
        self.reset.clicked.connect(self._reset)
        form.addRow(self.reset)
        lay.addWidget(self.body)
        lay.addStretch(1)
        self.body.hide()

    def show_clips(self, clips, _t_us=None, _fps=None):
        c = clips[0] if len(clips) == 1 and clips[0]["type"] == "audio" else None
        self.clip_id = c["id"] if c else None
        self.hint.setVisible(c is None)
        self.body.setVisible(c is not None)
        if c is None:
            return
        beat = dict(edit.BEAT_DEFAULT, **(c.get("beat") or {}))
        self.on.blockSignals(True)
        self.on.setChecked(bool(beat["on"]))
        self.on.blockSignals(False)
        for spin, v in ((self.bpm, beat["bpm"]), (self.offset, beat["offset_us"] / US)):
            if not spin.editing and abs(spin.value() - v) > 1e-9:       # (never under the user's typing)
                spin.show_value(v)
        i = self.div.findData(beat["div"])
        if i != self.div.currentIndex():
            self.div.blockSignals(True)
            self.div.setCurrentIndex(max(0, i))
            self.div.blockSignals(False)
        for w in (self.bpm, self.offset, self.div):
            w.setEnabled(bool(beat["on"]))
        step = 60 / beat["bpm"]
        self.period.setText(f"{step:.3f} 秒" + (f"（每格 {step / beat['div']:.3f} 秒）" if beat["div"] != 1 else ""))
        self.reset.setEnabled("beat" in c)

    def _emit(self, **fields):
        if self.clip_id:
            self.beatEdited.emit(self.clip_id, fields)

    def _reset(self):
        if self.clip_id and QMessageBox.question(
                self, "重置 BPM 對齊", "刪除這個片段的 BPM 和起頭偏移，並關閉 BPM 對齊？") == QMessageBox.Yes:
            self.resetRequested.emit(self.clip_id)
