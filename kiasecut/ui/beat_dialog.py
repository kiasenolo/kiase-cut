"""進階對齊編輯器: the window for a sound clip's BPM alignment in detail (opened from the 節拍 panel's
進階設定… or Alt+Shift+B). All its times are the sound's own (source time, us), not the timeline's.

The big picture (beat_wave.WaveView) shows the sound's waveform with the grid on it; the bar above it has
the switch and 細分. Edits go out as beatEdited(clip id, fields) - the main window's on_beat_edited, the
same as the panel's, so they are undoable."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .. import build, edit, project
from .beat_panel import DIV_NAMES
from .beat_preview import Preview
from .beat_wave import Overview, WaveView
from .inspector import ComboBox
from .timeline import BEAT_COLORS


class BeatDialog(QDialog):
    """Not modal: the timeline stays usable beside it. One window for one clip."""
    beatEdited = Signal(str, dict)

    def __init__(self, clip_id, parent=None):
        super().__init__(parent)
        self.clip_id = clip_id
        self.setWindowTitle("進階對齊編輯器")
        self.setModal(False)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(1000, 520)
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.title = QLabel()
        self.play = QPushButton("▶ 播放")
        self.play.setToolTip("只播這個片段用到的那一段聲音（空白鍵）；點大圖可以指定從哪裡播")
        self.play.clicked.connect(self.toggle_play)
        bar.addWidget(self.play)
        self.loop = QCheckBox("循環")
        self.loop.setChecked(True)
        bar.addWidget(self.loop)
        self.follow = QCheckBox("跟隨")
        self.follow.setChecked(True)
        self.follow.setToolTip("播放時，播放頭跑出畫面就翻頁")
        bar.addWidget(self.follow)
        bar.addWidget(self.title, 1)
        self.on = QCheckBox("啟用 BPM 對齊")
        self.on.toggled.connect(lambda v: self.beatEdited.emit(self.clip_id, {"on": v}))
        bar.addWidget(self.on)
        bar.addWidget(QLabel("細分"))
        self.div = ComboBox()
        for d, name in DIV_NAMES.items():
            self.div.addItem(name, d)
            self.div.setItemData(self.div.count() - 1, QColor(BEAT_COLORS.get(d, BEAT_COLORS[1])), Qt.ForegroundRole)
        self.div.currentIndexChanged.connect(lambda i: self.beatEdited.emit(self.clip_id, {"div": self.div.itemData(i)}))
        bar.addWidget(self.div)
        self.fit = QPushButton("對準片段")
        self.fit.setToolTip("把畫面移到這個片段用到的那一段聲音")
        bar.addWidget(self.fit)
        lay.addLayout(bar)
        self.wave = WaveView()
        self.fit.clicked.connect(self.wave.fit)
        lay.addWidget(self.wave, 1)
        self.overview = Overview(self.wave)
        lay.addWidget(self.overview)
        hint = QLabel("下方小圖：整份聲音，亮的是片段用到的，藍框是上面看到的範圍，點一下或拖動可以移動。\n滾輪：左右捲動　Ctrl＋滾輪：縮放　中鍵拖動：移動畫面（Ctrl＋中鍵：縮放）")
        hint.setStyleSheet("color: #8a8a90")
        lay.addWidget(hint)
        self.peaks = None
        self.preview = Preview(self)
        self.loop.toggled.connect(lambda v: setattr(self.preview, "loop", v))
        self.preview.positionChanged.connect(lambda t: self.wave.set_playhead(t, self.follow.isChecked()))
        self.preview.playingChanged.connect(lambda on: self.play.setText("⏸ 暫停" if on else "▶ 播放"))
        self.preview.failed.connect(lambda m: self.title.setText(m))
        self.wave.seekRequested.connect(self.preview.seek)
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self.toggle_play)

    def toggle_play(self):
        if self.preview.playing:
            self.preview.pause()
        else:
            self.preview.play(self.wave.playhead)

    def closeEvent(self, e):
        self.preview.stop()
        super().closeEvent(e)

    def show_clip(self, proj, peaks=None):
        """Refresh from the project; False when the clip no longer exists (or has no sound)."""
        try:
            _, c = edit.find(proj, self.clip_id)
        except Exception:
            return False
        if not edit.has_sound(c):
            return False
        if peaks is not None:
            self.peaks = peaks
        beat = dict(edit.BEAT_DEFAULT, **(c.get("beat") or {}))
        self.title.setText(f"片段：{c.get('name', '')}　{beat['bpm']:g} BPM")
        self.on.blockSignals(True)
        self.on.setChecked(bool(beat["on"]))
        self.on.blockSignals(False)
        i = self.div.findData(beat["div"])
        if i != self.div.currentIndex():
            self.div.blockSignals(True)
            self.div.setCurrentIndex(max(0, i))
            self.div.blockSignals(False)
        self.wave.set_clip(c, self.peaks)
        if c.get("media") and project.frozen(c) is None:
            a, b = self.wave.trim()
            self.preview.set_source(c["media"]["path"], build.audio_stream(c), a, b, project.speed(c))
        return True

    def peaks_ready(self, _path=None):
        self.wave.update()
        self.overview.update()
