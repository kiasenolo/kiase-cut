"""聲音轉數值 (soundmeter.py): which channel a global parameter listens to, the box of the spectrum it
measures - dragged on the spectrum of the moment the cursor is at - how fast the number rises and
falls, and the number over the seconds round the cursor, worked out as the project will read it.
The project goes on playing while the dialog is open (its button, or Space), the cursor with it."""
import math
import threading
import time

import numpy as np
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from .. import soundmeter
from . import icons
from .sound_visuals import HI, LO, freq_grid, hz_of, text, x_of

US = 1_000_000
VIEW_TOP, VIEW_BOTTOM = 6.0, -90.0      # the dB the spectrum shows
WINDOW_S = 8.0                          # the seconds the curve shows
GRAB = 6                                # px from an edge of the box that takes hold of it
PER_S = soundmeter.RATE / soundmeter.HOP


def levels_of(sound):
    """dB of every FFT bin of N samples, on the scale soundmeter.box_db measures on."""
    mag = np.abs(np.fft.rfft(sound * soundmeter._window, axis=-1)) / (soundmeter.N / 4)
    return 20 * np.log10(np.maximum(mag, 1e-6))


class BoxSpectrum(QWidget):
    """The spectrum at the cursor (and, dimmer, the most of each frequency over the seconds the
    curve shows) with the box: its sides dragged one by one, the whole by its inside; a drag on
    empty space draws a new one."""
    changed = Signal(dict)                  # {lo_hz, hi_hz, floor_db, top_db}
    done = Signal(dict)                     # ... when a drag of it is let go

    def __init__(self):
        super().__init__()
        self.box = {k: soundmeter.DEFAULTS[k] for k in ("lo_hz", "hi_hz", "floor_db", "top_db")}
        self.now = self.most = None
        self.drag = None
        self.moved = False
        self.setMinimumSize(560, 260)
        self.setMouseTracking(True)

    def y_of(self, db):
        return self.height() * (VIEW_TOP - db) / (VIEW_TOP - VIEW_BOTTOM)

    def db_of(self, y):
        return VIEW_TOP - y / max(1, self.height()) * (VIEW_TOP - VIEW_BOTTOM)

    def rect_of_box(self):
        b, w = self.box, self.width()
        return QRectF(QPointF(x_of(b["lo_hz"], w), self.y_of(b["top_db"])),
                      QPointF(x_of(b["hi_hz"], w), self.y_of(b["floor_db"])))

    def edges_at(self, pos):
        """The sides of the box under pos: a set of "l", "r", "t", "b", {"all"} inside it, empty outside."""
        r = self.rect_of_box()
        if not r.adjusted(-GRAB, -GRAB, GRAB, GRAB).contains(pos):
            return set()
        near = {"l": abs(pos.x() - r.left()), "r": abs(pos.x() - r.right()),
                "t": abs(pos.y() - r.top()), "b": abs(pos.y() - r.bottom())}
        out = set()
        for a, b in (("l", "r"), ("t", "b")):
            k = a if near[a] <= near[b] else b
            if near[k] <= GRAB:
                out.add(k)
        return out or {"all"}

    def put(self, lo, hi, floor, top):
        lo, hi = sorted((min(HI, max(LO, lo)), min(HI, max(LO, hi))))
        floor, top = sorted((floor, top))
        floor = min(soundmeter.MAX_DB - 1.0, max(soundmeter.MIN_DB, floor))
        top = min(soundmeter.MAX_DB, max(floor + 1.0, top))
        self.box = {"lo_hz": round(lo, 1), "hi_hz": round(hi, 1), "floor_db": round(floor, 1), "top_db": round(top, 1)}
        self.moved = True
        self.update()
        self.changed.emit(dict(self.box))

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pos = e.position()
        edges = self.edges_at(pos)
        self.drag = (edges or {"new"}, pos, dict(self.box))
        self.moved = False

    def mouseMoveEvent(self, e):
        pos, w = e.position(), self.width()
        if self.drag is None:
            edges = self.edges_at(pos)
            across, down = edges & {"l", "r"}, edges & {"t", "b"}
            corner = Qt.SizeFDiagCursor if edges in ({"l", "t"}, {"r", "b"}) else Qt.SizeBDiagCursor
            self.setCursor(Qt.SizeAllCursor if "all" in edges else corner if across and down else
                           Qt.SizeHorCursor if across else Qt.SizeVerCursor if down else Qt.CrossCursor)
            return
        edges, start, b = self.drag
        if "new" in edges:
            self.put(hz_of(start.x(), w), hz_of(pos.x(), w), self.db_of(start.y()), self.db_of(pos.y()))
            return
        dx, dy = pos.x() - start.x(), pos.y() - start.y()
        ddb = -dy / max(1, self.height()) * (VIEW_TOP - VIEW_BOTTOM)
        shift = lambda hz: hz_of(x_of(hz, w) + dx, w)
        if "all" in edges:
            self.put(shift(b["lo_hz"]), shift(b["hi_hz"]), b["floor_db"] + ddb, b["top_db"] + ddb)
            return
        self.put(shift(b["lo_hz"]) if "l" in edges else b["lo_hz"], shift(b["hi_hz"]) if "r" in edges else b["hi_hz"],
                 b["floor_db"] + (ddb if "b" in edges else 0.0), b["top_db"] + (ddb if "t" in edges else 0.0))

    def mouseReleaseEvent(self, _e):
        drag, self.drag = self.drag, None
        if drag is not None and self.moved:
            self.done.emit(dict(self.box))

    # -- as a picture in a node (電平 → 數值) -----------------------------------------------------------
    def set_values(self, values):
        box = {k: values[k] for k in self.box if k in values}
        if self.drag is None and box and any(self.box[k] != v for k, v in box.items()):
            self.box.update(box)
            self.update()

    def feed(self, mono):
        """The sound at the playhead: its middle N samples are drawn, with the most of each
        frequency falling away slowly."""
        middle = len(mono) // 2 - soundmeter.N // 2
        now = levels_of(mono[max(0, middle):max(0, middle) + soundmeter.N])
        most = now if self.most is None else np.maximum(now, self.most - 1.0)
        if self.now is None or np.abs(now - self.now).max() > 0.05 or np.abs(most - self.most).max() > 0.05:
            self.now, self.most = now, most
            self.update()

    def _line(self, levels):
        w = self.width()
        hz = np.arange(len(levels)) * soundmeter.RATE / soundmeter.N
        shown = np.nonzero((hz >= LO) & (hz <= HI))[0]
        path = QPainterPath(QPointF(0, self.height()))
        for i in shown:
            path.lineTo(QPointF(x_of(hz[i], w), self.y_of(max(VIEW_BOTTOM, float(levels[i])))))
        path.lineTo(QPointF(w, self.height()))
        return path

    def paintEvent(self, _e):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#0b0b0b"))
        freq_grid(p, w, h)
        for db in range(0, int(VIEW_BOTTOM), -12):
            p.setPen(QColor(255, 255, 255, 28))
            p.drawLine(QPointF(0, self.y_of(db)), QPointF(w, self.y_of(db)))
            text(p, 2, self.y_of(db) - 2, str(db))
        p.setRenderHint(QPainter.Antialiasing)
        if self.most is not None:
            p.setPen(QPen(QColor(122, 208, 255, 90), 1))
            p.setBrush(Qt.NoBrush)
            p.drawPath(self._line(self.most))
        if self.now is not None:
            p.setPen(QPen(QColor("#7ad0ff"), 1.2))
            p.setBrush(QColor(122, 208, 255, 60))
            p.drawPath(self._line(self.now))
        r = self.rect_of_box()
        p.setPen(QPen(QColor("#e0a030"), 1.5))
        p.setBrush(QColor(224, 160, 48, 34))
        p.drawRect(r)
        text(p, r.left() + 3, r.top() - 3, "1", "#e0a030", 11)
        text(p, r.left() + 3, r.bottom() + 12, "0", "#e0a030", 11)
        if self.now is not None:
            sel = soundmeter.bins(self.box["lo_hz"], self.box["hi_hz"])
            k = int(sel[np.argmax(self.now[sel])])
            at = QPointF(x_of(k * soundmeter.RATE / soundmeter.N, w), self.y_of(max(VIEW_BOTTOM, float(self.now[k]))))
            p.setPen(QPen(QColor("#ffffff"), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(at, 3.5, 3.5)


class NumberCurve(QWidget):
    """The number over the seconds round the cursor; pressed or dragged, the cursor goes there
    (past an end: the view moves along)."""
    moved = Signal(float)                   # the cursor, seconds

    def __init__(self):
        super().__init__()
        self.first, self.at_s = 0.0, 0.0
        self.values = None                  # one every HOP samples from `first`
        self.setMinimumHeight(90)

    def paintEvent(self, _e):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#0b0b0b"))
        for s in range(int(math.ceil(self.first)), int(self.first + WINDOW_S) + 1):
            x = (s - self.first) / WINDOW_S * w
            p.setPen(QColor(255, 255, 255, 24))
            p.drawLine(QPointF(x, 0), QPointF(x, h))
            text(p, x + 2, h - 3, f"{s}s")
        if self.values is not None and len(self.values):
            p.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath(QPointF(0, h - 2))
            for i, v in enumerate(self.values):
                path.lineTo(QPointF(i / PER_S / WINDOW_S * w, 2 + (h - 4) * (1.0 - float(v))))
            p.setPen(QPen(QColor("#e0a030"), 1.4))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        x = (self.at_s - self.first) / WINDOW_S * w
        p.setPen(QPen(QColor("#ffffff"), 1))
        p.drawLine(QPointF(x, 0), QPointF(x, h))

    def _go(self, e):
        self.moved.emit(max(0.0, self.first + e.position().x() / max(1, self.width()) * WINDOW_S))

    def mousePressEvent(self, e):
        self._go(e)

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._go(e)

    def wheelEvent(self, e):
        d = e.angleDelta().y() or e.angleDelta().x()
        self.moved.emit(max(0.0, self.at_s - d / 120 * 0.25))


class SoundDialog(QDialog):
    _done = Signal(object, object, str)     # (from the measuring thread: its cancel event, the tap or None, why not)
    _progress = Signal(object, float)

    def __init__(self, parent, title, root, spec, level, cache_dir, t_us, transport=None):
        """spec: what the parameter listens to now, or None. level: the open level's id.
        transport: the preview's playback - playing(), time_us(), toggle(), seek(us) - or None."""
        super().__init__(parent)
        self.setWindowTitle(title)
        self.root, self.cache_dir = root, cache_dir
        self.pcm = None
        self.job = None                     # the cancel event of the measuring under way
        self.transport = transport
        self.sought = None                  # (where the preview was told to go and has not got to yet, until when)
        self.heard_at = None                # what the playback's time was last, to follow it only when it moves
        spec = soundmeter.clean(spec) if soundmeter.check(spec) is None else None
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.level, self.channel = QComboBox(), QComboBox()
        for kid, comp in (root.get("compounds") or {}).items():
            if not comp.get("static"):
                self.level.addItem(comp.get("name") or kid, kid)
        wanted = spec["level"] if spec else level
        self.level.setCurrentIndex(max(0, self.level.findData(wanted)))
        self.status = QLabel()
        self.number = QLabel()
        self.number.setStyleSheet("color: #e0a030; font-size: 18px; font-weight: bold;")
        self.number.setMinimumWidth(64)
        self.number.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self.level)
        top.addWidget(self.channel)
        top.addWidget(self.status, 1)
        top.addWidget(self.number)
        lay.addLayout(top)
        self.spectrum, self.curve = BoxSpectrum(), NumberCurve()
        if spec:
            self.spectrum.box = {k: spec[k] for k in self.spectrum.box}
        lay.addWidget(self.spectrum, 1)
        lay.addWidget(self.curve)
        row = QHBoxLayout()
        self.play = None
        if transport is not None:
            self.play = QPushButton()
            self.play.setToolTip("播放 / 暫停（空白鍵）")
            self.play.setFocusPolicy(Qt.NoFocus)
            self.play.setAutoDefault(False)
            self.play.clicked.connect(lambda _c=False: self.toggle_play())
            row.addWidget(self.play)
            key = QShortcut(QKeySequence(Qt.Key_Space), self)   # (the window's own Space is off under a modal dialog)
            key.activated.connect(self.toggle_play)
        self.fields = {}
        values = spec or soundmeter.DEFAULTS
        for key, label, factor, decimals, step, suffix in (
                ("lo_hz", "低頻", 1, 0, 5, " Hz"), ("hi_hz", "高頻", 1, 0, 10, " Hz"),
                ("floor_db", "0 的音量", 1, 1, 1, " dB"), ("top_db", "1 的音量", 1, 1, 1, " dB"),
                ("attack", "啟動", 1000, 0, 5, " ms"), ("release", "釋放", 1000, 0, 10, " ms")):
            lo, hi = soundmeter.RANGES[key]
            box = QDoubleSpinBox()
            box.setRange(lo * factor, hi * factor)
            box.setDecimals(decimals)
            box.setSingleStep(step)
            box.setSuffix(suffix)
            box.setValue(values[key] * factor)
            box.valueChanged.connect(lambda v, key=key: self._typed(key))
            self.fields[key] = (box, factor)
            box.installEventFilter(self)
            row.addWidget(QLabel(label))
            row.addWidget(box)
        row.addStretch()
        lay.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.ok = buttons.button(QDialogButtonBox.Ok)
        lay.addWidget(buttons)
        self._fill_channels(spec["channel"] if spec else None)
        self.spectrum.changed.connect(self._dragged)
        self.curve.moved.connect(self.scrub)
        self.level.currentIndexChanged.connect(lambda _i: (self._fill_channels(None), self.measure()))
        self.channel.currentIndexChanged.connect(lambda _i: self.measure())
        self._done.connect(self._measured)
        self._progress.connect(self._said)
        self.curve.at_s = max(0.0, t_us / US)
        self.curve.first = max(0.0, self.curve.at_s - WINDOW_S / 3)
        self.finished.connect(lambda _r: self._stop())
        self.measure()
        if transport is not None:
            self.heard_at = transport.time_us()
            self._icon(transport.playing())
            self.follow_timer = QTimer(self)
            self.follow_timer.timeout.connect(self.follow)
            self.follow_timer.start(33)
            self.finished.connect(lambda _r: self.follow_timer.stop())

    # -- playing -------------------------------------------------------------------------------------
    def _icon(self, playing):
        if self.play.property("playing") != playing:
            self.play.setProperty("playing", playing)
            self.play.setIcon(icons.icon("pause" if playing else "play"))

    def toggle_play(self):
        if self.transport is not None:
            self.transport.toggle()

    def eventFilter(self, obj, e):
        if e.type() == QEvent.ShortcutOverride and e.key() == Qt.Key_Space and not e.modifiers():
            e.ignore()                      # (a number box would keep Space to itself: it is no digit)
            return True
        return super().eventFilter(obj, e)

    def scrub(self, seconds):
        """The cursor put somewhere by hand: playback goes there too (and plays on, if it was playing)."""
        self.seek(seconds)
        if self.transport is not None:
            self.transport.seek(seconds * US)
            self.sought = (seconds, time.monotonic() + 1.0)

    def follow(self):
        """Keeps the cursor where playback is."""
        playing = self.transport.playing()
        self._icon(playing)
        now = self.transport.time_us()
        if self.sought is not None:         # (frames from before the jump may still be coming in)
            if abs(now / US - self.sought[0]) > 0.25 and time.monotonic() < self.sought[1]:
                return
            self.sought, self.heard_at = None, now
            return
        if now == self.heard_at:
            return
        self.heard_at = now
        c = self.curve
        c.at_s = max(0.0, now / US)
        if not c.first <= c.at_s <= c.first + WINDOW_S * 0.9:      # (the next stretch: the view is turned like a page)
            c.first = max(0.0, c.at_s - WINDOW_S * 0.1)
            self.show_all()
        else:
            self.show_cursor()

    def _fill_channels(self, wanted):
        self.channel.blockSignals(True)
        self.channel.clear()
        comp = (self.root.get("compounds") or {}).get(self.level.currentData()) or {}
        kinds = {"track": "軌道　", "bus": "Bus　", "master": ""}
        for ident, kind, name in soundmeter.channels(comp):
            self.channel.addItem(kinds[kind] + name, ident)
        i = self.channel.findData(wanted) if wanted else -1
        if i < 0:                           # a new one: the first track that has a clip which can sound
            heard = next((t["id"] for t in comp.get("tracks") or () if any(
                c["type"] in ("audio", "video", "compound", "group") for c in t.get("clips") or ())
                and t.get("kind") == "audio"), None)
            i = max(0, self.channel.findData(heard or "master"))
        self.channel.setCurrentIndex(i)
        self.channel.blockSignals(False)

    def spec(self):
        values = {k: box.value() / factor for k, (box, factor) in self.fields.items()}
        return soundmeter.make(self.level.currentData(), self.channel.currentData(), **values)

    # -- the channel's sound -------------------------------------------------------------------------
    def _stop(self):
        if self.job is not None:
            self.job.set()
            self.job = None

    def measure(self):
        self._stop()
        self.pcm = None
        self.show_all()
        try:
            _snap, names, waits = soundmeter.needs(self.root, self.spec())
            todo = soundmeter.plan(self.root) if waits else None
            snap = soundmeter.snapshot(self.root, self.level.currentData(), self.channel.currentData())
            # (what a parameter already measuring this channel has in the cache is found under the same name)
            read = soundmeter.definitions(self.root, names, todo.keys() if todo else {})
            key = soundmeter.signature(snap, read)
        except (soundmeter.MeterError, ValueError) as exc:
            self.status.setText(str(exc))
            return
        self.status.setText("分析聲音中…")
        cancel = self.job = threading.Event()
        cache = self.cache_dir

        def work():
            try:
                if todo is not None:        # its effects follow other meters: those first
                    soundmeter.run(todo, cache, cancel.is_set)
                last = [0.0]

                def progress(f):
                    if f - last[0] >= 0.05:
                        last[0] = f
                        self._progress.emit(cancel, f)
                out, why = soundmeter.tap(snap, cache, key, cancel.is_set, progress).astype(np.float32), ""
            except soundmeter.Cancelled:
                return
            except Exception as exc:
                out, why = None, f"{type(exc).__name__}: {exc}"
            if not cancel.is_set():
                try:
                    self._done.emit(cancel, out, why)
                except RuntimeError:        # (closed meanwhile)
                    pass

        threading.Thread(target=work, daemon=True).start()

    def _said(self, job, f):
        if job is self.job:
            self.status.setText(f"分析聲音中… {f:.0%}")

    def _measured(self, job, pcm, why):
        if job is not self.job:
            return
        self.pcm = pcm
        self.status.setText(why if why else "" if len(pcm) else "這裡沒有聲音")
        self.show_all()

    # -- showing -------------------------------------------------------------------------------------
    def seek(self, seconds):
        c = self.curve
        c.at_s = seconds
        if not c.first <= seconds <= c.first + WINDOW_S:
            c.first = max(0.0, seconds - (WINDOW_S if seconds > c.first else 0.0))
        self.show_all()

    def _typed(self, key):
        box = self.spectrum.box
        if key in box:
            box[key] = self.fields[key][0].value()
            self.spectrum.update()
        self.show_numbers()

    def _dragged(self, box):
        for key, v in box.items():
            field = self.fields[key][0]
            field.blockSignals(True)
            field.setValue(v)
            field.blockSignals(False)
        self.show_numbers()

    def _stretch(self, first_s, seconds):
        """The tap's samples for the windows centred from first_s on, `seconds` long."""
        n, hop = soundmeter.N, soundmeter.HOP
        a = int(first_s * PER_S) * hop - n // 2
        b = a + int(seconds * PER_S) * hop + n
        out = np.zeros(b - a, np.float32)
        lo, hi = max(a, 0), min(b, len(self.pcm))
        if hi > lo:
            out[lo - a:hi - a] = self.pcm[lo:hi]
        return out

    def show_all(self):
        if self.pcm is None:
            self.spectrum.now = self.spectrum.most = None
        else:
            n, hop = soundmeter.N, soundmeter.HOP
            around = np.lib.stride_tricks.sliding_window_view(self._stretch(self.curve.first, WINDOW_S), n)[::hop]
            self.spectrum.most = levels_of(around).max(axis=0)
            self.spectrum.now = levels_of(self._stretch(self.curve.at_s, 0.0)[:n])
        self.spectrum.update()
        self.show_numbers()

    def show_cursor(self):
        """The cursor moved within what the curve shows: only what is at it changes."""
        if self.pcm is not None:
            self.spectrum.now = levels_of(self._stretch(self.curve.at_s, 0.0)[:soundmeter.N])
            self.spectrum.update()
        self.show_cursor_number()
        self.curve.update()

    def show_cursor_number(self):
        c = self.curve
        if c.values is None:
            self.number.setText("")
            return
        i = int((c.at_s - c.first) * PER_S)
        self.number.setText(f"{c.values[i]:.2f}" if 0 <= i < len(c.values) else "0.00")

    def show_numbers(self):
        c = self.curve
        if self.pcm is None:
            c.values = None
        else:
            spec = self.spec()
            lead = min(c.first, spec["release"] * 7 + spec["attack"] * 7)      # (what is still falling from before the view)
            begin = int((c.first - lead) * PER_S)
            skip = int(c.first * PER_S) - begin
            sound = self._stretch(begin / PER_S, lead + WINDOW_S)
            db = soundmeter.box_db(sound[soundmeter.N // 2:], spec["lo_hz"], spec["hi_hz"])
            got = soundmeter.shape(db, spec)[skip:skip + int(WINDOW_S * PER_S)]
            c.values = got
        self.show_cursor_number()
        c.update()


def ask_sound(parent, title, root, spec, level, cache_dir, t_us, transport=None):
    """The meter spec chosen, or None when cancelled."""
    d = SoundDialog(parent, title, root, spec, level, cache_dir, t_us, transport)
    d.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
    return d.spec() if d.exec() == QDialog.Accepted else None
