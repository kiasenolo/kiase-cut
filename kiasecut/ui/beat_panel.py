"""節拍: BPM alignment of a sound clip.

With it on, the clip's beats (a grid from its BPM and the first beat's time in the sound)
become snap targets on the timeline: moving and trimming clips, keyframes and the playhead
land on them. Switching it off keeps the numbers; 重置 (after asking) deletes them and
switches it off.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QFormLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from .. import edit
from .inspector import SpinBox, section
from .timeline import US


class BeatPanel(QWidget):
    beatEdited = Signal(str, dict)                  # clip id, {on / bpm / offset_us: value}
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
        note = QLabel("開啟後，拖曳片段、修剪、關鍵幀和播放頭都會吸附到這個片段的拍子上（片段上方的黃色刻度）。"
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
            spin.setEnabled(bool(beat["on"]))
        self.period.setText(f"{60 / beat['bpm']:.3f} 秒")
        self.reset.setEnabled("beat" in c)

    def _emit(self, **fields):
        if self.clip_id:
            self.beatEdited.emit(self.clip_id, fields)

    def _reset(self):
        if self.clip_id and QMessageBox.question(
                self, "重置 BPM 對齊", "刪除這個片段的 BPM 和起頭偏移，並關閉 BPM 對齊？") == QMessageBox.Yes:
            self.resetRequested.emit(self.clip_id)
