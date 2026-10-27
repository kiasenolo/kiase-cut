"""時基: how the timeline's ruler and the time readout count time.

時間 shows mm:ss.ff; BPM shows 小節.拍.格 - bars of `meter` beats (or beats alone), each beat
split into `div` parts, bar 1 starting at the offset (the shown level's time; shown moved to
the nearest frame, so the beats fall on frames). It is only a way of reading time: nothing
snaps to it (a sound clip's 節拍 settings are what snap). Saved with the view, not an edit.

TimebasePopup opens under the toolbar button (inplace.Overlay: a click outside closes it);
every change applies at once; Esc puts back what was there.
"""
from PySide6.QtCore import QEvent, QRect, Signal
from PySide6.QtWidgets import QApplication, QFormLayout, QHBoxLayout, QLabel, QPushButton, QWidget

from .. import edit, project
from . import inplace
from .inspector import ComboBox, SpinBox
from .timeline import TIMEBASE_DIVS, US

DIV_NAMES = {1: "不細分", 2: "1/2", 3: "1/3", 4: "1/4", 6: "1/6"}


def clip_zero(c):
    """(bpm, level time us of beat 0) of a clip's 節拍 settings, as they play on the timeline
    (its speed included); None without them."""
    beat = c.get("beat") if c else None
    if not beat or not beat.get("bpm"):
        return None
    k = project.speed(c)
    return beat["bpm"] * k, c["start_us"] + (beat.get("offset_us", 0) - c.get("source_start_us", 0)) / k


def button_text(tb):
    return f"{tb['bpm']:g} BPM" if tb["kind"] == "bpm" else "時間"


class TimebasePopup(inplace.Overlay):
    """The timebase's settings; `changed` fires with the whole timebase on every change."""
    changed = Signal(dict)

    def __init__(self, widget, tb, playhead_us, clip=None):
        super().__init__(widget)
        self.tb = dict(tb)
        self.setObjectName("timebase")
        self.setStyleSheet("QFrame#timebase { background: #26262a; border: 1px solid #45454c; border-radius: 4px; }")
        form = QFormLayout(self)
        form.setContentsMargins(10, 8, 10, 8)
        self.kind = ComboBox()
        self.kind.addItem("時間（分:秒.格）", "time")
        self.kind.addItem("BPM（小節.拍.格）", "bpm")
        self.kind.setCurrentIndex(self.kind.findData(self.tb["kind"]))
        self.kind.currentIndexChanged.connect(lambda i: self._set(kind=self.kind.itemData(i)))
        form.addRow("時基", self.kind)
        self.bpm = SpinBox()
        self.bpm.setRange(edit.BPM_MIN, edit.BPM_MAX)
        self.bpm.setDecimals(2)
        self.bpm.setSingleStep(0.1)
        self.bpm.show_value(self.tb["bpm"])
        self.bpm.edited.connect(lambda v: self._set(bpm=v))
        form.addRow("BPM", self.bpm)
        self.div = ComboBox()
        for d in TIMEBASE_DIVS:
            self.div.addItem(DIV_NAMES[d], d)
        self.div.setCurrentIndex(self.div.findData(self.tb["div"]))
        self.div.setToolTip("每拍再分成幾格：時間顯示的最後一個數字")
        self.div.currentIndexChanged.connect(lambda i: self._set(div=self.div.itemData(i)))
        form.addRow("細分", self.div)
        self.meter = ComboBox()
        for n in edit.METERS:
            self.meter.addItem("不分小節" if n == 0 else f"{n}/{8 if n in (6, 9, 12) else 4}", n)
        self.meter.setCurrentIndex(self.meter.findData(self.tb["meter"]))
        self.meter.setToolTip("一小節幾拍；不分小節：只數第幾拍")
        self.meter.currentIndexChanged.connect(lambda i: self._set(meter=self.meter.itemData(i)))
        form.addRow("拍號", self.meter)
        self.offset = SpinBox()
        self.offset.setRange(-3600.0, 3600.0)
        self.offset.setDecimals(3)
        self.offset.setSingleStep(0.001)
        self.offset.setSuffix(" 秒")
        self.offset.show_value(self.tb["offset_us"] / US)
        self.offset.setToolTip("第 1 小節第 1 拍在時間線上的時間（顯示時對齊到最近的一格，拍子才會落在格上）")
        self.offset.edited.connect(lambda v: self._set(offset_us=round(v * US)))
        here = QPushButton("設為播放頭")
        here.setToolTip("第 1 小節第 1 拍從播放頭的位置開始")
        here.clicked.connect(lambda: self._set(offset_us=round(playhead_us), show=True))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.offset, 1)
        row.addWidget(here)
        form.addRow("偏移", row)
        self.zero = clip_zero(clip)
        self.take = QPushButton("用選取片段的節拍")
        self.take.setToolTip("BPM 和偏移照選取的聲音片段的節拍設定：第 1 小節從它的第一拍開始")
        self.take.clicked.connect(self._take)
        form.addRow(self.take)
        note = QLabel("只顯示第幾小節、第幾拍，不會吸附")
        note.setStyleSheet("color: #8a8a90")
        form.addRow(note)
        self.fields = (self.bpm, self.div, self.meter, self.offset, here)
        self._enable()

    def _enable(self):
        on = self.tb["kind"] == "bpm"
        for w in self.fields:
            w.setEnabled(on)
        self.take.setEnabled(on and self.zero is not None)

    def _take(self):
        bpm, zero = self.zero
        self._set(bpm=min(edit.BPM_MAX, max(edit.BPM_MIN, bpm)), offset_us=round(zero), show=True)

    def _set(self, show=False, **fields):
        self.tb.update(fields)
        if show:
            self.bpm.show_value(self.tb["bpm"])
            self.offset.show_value(self.tb["offset_us"] / US)
        self._enable()
        self.changed.emit(dict(self.tb))

    def eventFilter(self, obj, e):
        if QApplication.activePopupWidget() is not None and e.type() in (
                QEvent.MouseButtonPress, QEvent.MouseButtonDblClick, QEvent.Wheel):
            return False                                     # (a combo box's list: not outside)
        return super().eventFilter(obj, e)

    def place(self, widget, rect):
        """Just under rect of widget (its coordinates), inside the window."""
        win = self.window()
        self.adjustSize()
        r = inplace.window_rect(widget, rect)
        w, h = self.sizeHint().width(), self.sizeHint().height()
        y = r.bottom() + 2 if r.bottom() + 2 + h <= win.height() else max(0, r.top() - h - 2)
        self.setGeometry(QRect(max(0, min(r.left(), win.width() - w)), y, w, h))


def edit_timebase(button, tb, playhead_us, clip, live):
    """Open the popup under button; live(timebase) on every change. The timebase it ends
    with: left with Esc, tb again (live has it back too)."""
    pop = TimebasePopup(button, tb, playhead_us, clip)
    pop.place(button, button.rect())
    pop.changed.connect(live)
    if pop.run(pop.kind):
        return pop.tb
    live(dict(tb))
    return tb
