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
from .inspector import ComboBox, SpinBox
from .timeline import BEAT_COLORS, US


class BeatDialog(QDialog):
    """Not modal: the timeline stays usable beside it. One window for one clip."""
    beatEdited = Signal(str, dict)
    pointEdited = Signal(str, str, dict)    # clip id, add / move / set / remove, arguments of edit.*_beat_point

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
        self.follow = QPushButton("跟隨")
        self.follow.setCheckable(True)
        self.follow.setChecked(True)
        self.follow.setToolTip("開著時，播放中畫面會連續捲動，播放頭停在畫面左邊約三成處；播放中拖動畫面或捲動就會自動關掉")
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
        self.add_point = QPushButton("在播放頭新增")
        self.add_point.setToolTip("在播放頭的位置新增變速點／變拍點（也可以在波形上雙擊或按右鍵新增；拖動調整位置，Alt 不吸附；Delete 刪除）")
        self.add_point.clicked.connect(self._add_at_playhead)
        bar.addWidget(self.add_point)
        lay.addLayout(bar)
        lay.addLayout(self._point_bar())
        self.wave = WaveView()
        self.fit.clicked.connect(self.wave.fit)
        lay.addWidget(self.wave, 1)
        self.overview = Overview(self.wave)
        lay.addWidget(self.overview)
        hint = QLabel("下方小圖：整份聲音，亮的是片段用到的，藍框是上面看到的範圍，點一下或拖動可以移動。\n滾輪：左右捲動　Ctrl＋滾輪：縮放　中鍵拖動：移動畫面（Ctrl＋中鍵：縮放）\n變速／變拍點：雙擊或右鍵新增，拖動調整（Alt 不吸附），選中後在上方改數字，Delete 刪除")
        hint.setStyleSheet("color: #8a8a90")
        lay.addWidget(hint)
        self.peaks = None
        self._seeking = False
        self._pick = None                       # time of a point just added: picked once the project has it
        self.preview = Preview(self)
        self.loop.toggled.connect(lambda v: setattr(self.preview, "loop", v))
        self.preview.positionChanged.connect(self._position)
        self.wave.userMoved.connect(self._user_moved)
        self.follow.toggled.connect(lambda on: on and self.wave.playhead is not None and self._position(self.wave.playhead))
        self.preview.playingChanged.connect(lambda on: self.play.setText("⏸ 暫停" if on else "▶ 播放"))
        self.preview.failed.connect(lambda m: self.title.setText(m))
        self.wave.seekRequested.connect(self._seek)
        self.wave.pointAdd.connect(self.add_at)
        self.wave.pointSelected.connect(lambda _i: self._sync_point())
        self.wave.pointMove.connect(lambda i, t: self.pointEdited.emit(self.clip_id, "move", {"index": i, "time_us": t}))
        self.wave.pointRemove.connect(self.remove_point)
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self.toggle_play)

    def _beat(self):
        return dict(edit.BEAT_DEFAULT, **(self.wave.clip.get("beat") or {}))

    def _add_at_playhead(self):
        a, b = self.wave.trim()
        t = self.wave.playhead if self.wave.playhead is not None else a
        self.add_at(t)

    def _point_bar(self):
        """The picked change point's numbers, edited here as they are (no window): its time, whether it changes the BPM
        and the meter, and what to."""
        row = QHBoxLayout()
        self.pt_label = QLabel()
        row.addWidget(self.pt_label)
        self.pt_use_bpm = QCheckBox("變速 BPM")
        self.pt_bpm = SpinBox()
        self.pt_bpm.setRange(edit.BPM_MIN, edit.BPM_MAX)
        self.pt_bpm.setDecimals(2)
        self.pt_bpm.setSingleStep(0.1)
        self.pt_use_meter = QCheckBox("變拍 每小節")
        self.pt_meter = ComboBox()
        for n in edit.METERS:
            self.pt_meter.addItem("不分小節" if n == 0 else f"{n} 拍", n)
        self.pt_delete = QPushButton("刪除")
        self.pt_delete.setToolTip("刪除選中的點（Delete）")
        for w in (self.pt_use_bpm, self.pt_bpm, self.pt_use_meter, self.pt_meter, self.pt_delete):
            row.addWidget(w)
        row.addStretch(1)
        self.pt_use_bpm.toggled.connect(lambda on: self._point_set(use_bpm=on))
        self.pt_use_meter.toggled.connect(lambda on: self._point_set(use_meter=on))
        self.pt_bpm.edited.connect(lambda v: self._point_set(bpm=v))
        self.pt_meter.currentIndexChanged.connect(lambda i: self._point_set(meter=self.pt_meter.itemData(i)))
        self.pt_delete.clicked.connect(lambda: self.remove_point(self.wave.sel_point))
        return row

    def _point(self):
        i = self.wave.sel_point
        pts = (self.wave.clip.get("beat") or {}).get("points") or [] if self.wave.clip else []
        return (i, pts[i]) if i is not None and i < len(pts) else (None, None)

    def _sync_point(self):
        """The point bar shows the picked point (and waits for one when none is)."""
        i, pt = self._point()
        widgets = (self.pt_use_bpm, self.pt_bpm, self.pt_use_meter, self.pt_meter, self.pt_delete)
        for w in widgets:
            w.setEnabled(pt is not None)
        if pt is None:
            self.pt_label.setText("變速／變拍點：點一下波形上的點來編輯（雙擊波形新增）")
            for box in (self.pt_use_bpm, self.pt_use_meter):
                box.blockSignals(True)
                box.setChecked(False)
                box.blockSignals(False)
            return
        bpm, meter = edit.beat_at(self._beat(), pt["time_us"])
        self.pt_label.setText(f"選中的點：{pt['time_us'] / US:.3f} 秒")
        for box, v in ((self.pt_use_bpm, bool(pt.get("bpm"))), (self.pt_use_meter, pt.get("meter") is not None)):
            box.blockSignals(True)
            box.setChecked(v)
            box.blockSignals(False)
        if not self.pt_bpm.editing and abs(self.pt_bpm.value() - bpm) > 1e-9:
            self.pt_bpm.show_value(bpm)
        i_meter = self.pt_meter.findData(meter)
        if i_meter != self.pt_meter.currentIndex():
            self.pt_meter.blockSignals(True)
            self.pt_meter.setCurrentIndex(max(0, i_meter))
            self.pt_meter.blockSignals(False)
        # (the last thing a point changes stays: it must set one of the two)
        self.pt_use_bpm.setEnabled(not (pt.get("bpm") and pt.get("meter") is None))
        self.pt_use_meter.setEnabled(not (pt.get("meter") is not None and not pt.get("bpm")))

    def _point_set(self, use_bpm=None, use_meter=None, bpm=None, meter=None):
        """An edit in the point bar: the picked point's BPM / meter (what it sets, and to what)."""
        i, pt = self._point()
        if pt is None:
            return
        cur_bpm, cur_meter = edit.beat_at(self._beat(), pt["time_us"])
        has_bpm = bool(pt.get("bpm")) if use_bpm is None else use_bpm
        has_meter = pt.get("meter") is not None if use_meter is None else use_meter
        new_bpm = self.pt_bpm.value() if bpm is None else bpm
        new_meter = self.pt_meter.currentData() if meter is None else meter
        if not (has_bpm or has_meter):
            return
        self.pointEdited.emit(self.clip_id, "set", {"index": i, "bpm": new_bpm if has_bpm else None,
                                                    "meter": new_meter if has_meter else None})

    def remove_point(self, i):
        if i is None:
            return
        self.wave.select_point(None)
        self.pointEdited.emit(self.clip_id, "remove", {"index": i})

    def add_at(self, t):
        """A change point at source time t, beginning with the BPM the grid has there; it is picked, to change in the bar."""
        bpm, _ = edit.beat_at(self._beat(), t)
        self._pick = round(t)
        self.pointEdited.emit(self.clip_id, "add", {"time_us": t, "bpm": bpm})

    def _position(self, t):
        """The playhead moved: the view goes with it when 跟隨 is on and the sound is playing (not for a click's seek)."""
        self.wave.set_playhead(t, self.follow.isChecked() and self.preview.playing and not self._seeking)

    def _seek(self, t):
        self._seeking = True
        try:
            self.preview.seek(t)
        finally:
            self._seeking = False

    def _user_moved(self):
        """The view was dragged or scrolled by hand while playing: it is not followed any more."""
        if self.preview.playing:
            self.follow.setChecked(False)

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
        if self._pick is not None:
            pts = beat.get("points") or []
            i = next((k for k, pt in enumerate(pts) if abs(pt["time_us"] - self._pick) <= 1), None)
            if i is not None:
                self._pick = None
                self.wave.select_point(i)
        self._sync_point()
        if c.get("media") and project.frozen(c) is None:
            a, b = self.wave.trim()
            self.preview.set_source(c["media"]["path"], build.audio_stream(c), a, b, project.speed(c))
        return True

    def peaks_ready(self, _path=None):
        self.wave.update()
        self.overview.update()
