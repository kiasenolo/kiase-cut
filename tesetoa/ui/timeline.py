"""Timeline view and its mouse editing.

Layout follows Jianying: the topmost layer is drawn at the top, audio tracks at the bottom.
Click to seek or select; Ctrl / Shift + click adds to or removes from the selection, dragging
on empty track space draws a selection box, and a selection moves together. Drag a clip to move it (also to another track of the same kind),
drag its edges to trim. Moves and trims snap to the playhead and to other clips' edges.
The drag is only drawn while it happens; the edit is requested when the mouse is released.
The wheel scrolls the tracks up and down, Shift+wheel scrolls left and right, Ctrl+wheel
zooms time around the mouse, the middle button drags the view. Alt+wheel or the toolbar
slider changes the track height; dragging the line under a track header resizes that track
alone. Ctrl+D clears the selection. Dragging a picture clip above the top row, or a sound clip
below the bottom row, puts it on a new track.

Time selection (as in FL Studio): drag with the right button anywhere on the timeline to
select a span of time (it snaps like clips do); playback then starts at its beginning and
loops inside it, and it is the range a marked export uses. Ctrl+Shift+D clears it. A right
click without dragging opens the menu.

The selected clip shows its keyframes as diamonds along its bottom edge; drag one sideways
to move every keyframe at that time (it snaps to frames and to the playhead), click it to
go there.

Sound clips have a volume line (as in Jianying): drag it up or down to change the clip's
volume (with volume keyframes, all of them change together); the keyframes are points on
the line that can be dragged up / down (value) and sideways (time). The line's height is
in dB: the top is +20 dB (1000 %), 0 dB (100 %) two thirds of the way up.

Audio and video clips show their waveform (scaled by the clip volume and fades). Track
headers have mute / solo buttons (sound) and a hide button (pictures).
"""
import copy
import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QMenu, QScrollBar, QWidget

from .. import curves, edit, project, waveform

US = 1_000_000
MEDIA_MIME = "application/x-tesetoa-media"
COLORS = {"video": "#3f6585", "image": "#3f6585", "compound": "#5d5488",    # by type, muted as in
          "text": "#7c5574", "audio": "#3e7055"}                              # DaVinci Resolve
ROW_BG = QColor("#1f1f21")


def row_color(track):
    """A track's row background: its colour, mixed far down into the dark row grey."""
    if not track.get("color"):
        return ROW_BG
    c, k = QColor(track["color"]), 0.22
    return QColor(round(ROW_BG.red() + (c.red() - ROW_BG.red()) * k),
                  round(ROW_BG.green() + (c.green() - ROW_BG.green()) * k),
                  round(ROW_BG.blue() + (c.blue() - ROW_BG.blue()) * k))
RULER_H, TRACK_H, AUDIO_H, HEADER_W = 26, 34, 52, 140
BTN = 18                                             # header button size
MIN_H, MAX_H = 22, 240                               # track heights
EDGE_PX, SNAP_PX, DRAG_PX = 6, 8, 3


def timecode(us, fps):
    s = us / US
    return f"{int(s // 60):02d}:{int(s % 60):02d}.{int(round((s % 1) * fps)) % int(fps):02d}"


class Timeline(QWidget):
    seekRequested = Signal(int)                      # frame
    clipSelected = Signal(object)                    # clip dict or None (the primary selection)
    groupMoveRequested = Signal(list, int)           # clip ids, shift us
    keyMoveRequested = Signal(str, int, int)         # clip id, keyframe clip time from, to (us)
    marksChanged = Signal()                          # the time selection (mark_in / mark_out) changed
    volumeEdited = Signal(str, object)               # clip id, new volume (number or {"keys": ...})
    moveRequested = Signal(str, int, str)            # clip id, start us, track id
    trimRequested = Signal(str, str, int)            # clip id, "start" | "end", time us
    trackAction = Signal(str, str)                   # action, track id
    clipAction = Signal(str, str)                    # action, clip id
    mediaDropped = Signal(str, str, int)             # library item id, track id or "", start us
    compoundDropped = Signal(str, str, int)          # compound id, track id or "", start us
    filesDropped = Signal(list, str, int)            # file manager paths, track id or "", start us
    newTrackRequested = Signal(str, int, bool)       # clip id, start us, on top (else bottom)
    clipDragging = Signal(str, int, int)             # clip id, start us, duration us: while dragging
    peaksReady = Signal(str)                         # emitted from the waveform thread
    vzoomChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proj = None
        self.fps = 60.0
        self.pos = 0
        self.px_per_s = 40.0
        self.scroll_s = 0.0
        self._primary = None
        self.selected_ids = set()
        self.band = None                           # selection box (QRectF) while dragging
        self.snapping = True                       # 自動吸附: moves / trims snap to edges and the playhead
        self.rows = []
        self.drag = None
        self.mark_in = self.mark_out = None        # export range, frames
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setAcceptDrops(True)
        self.drop_at = None                        # (row, us) while library media hovers
        self.tops = []                             # y of each row (on screen)
        self.vzoom = 1.0                           # track height factor
        self.heights = {}                          # track id -> height set by dragging its edge
        self.scroll_y = 0
        self.vbar = QScrollBar(Qt.Vertical, self)
        self.vbar.hide()
        self.vbar.valueChanged.connect(self._on_vscroll)
        self.rows_end = RULER_H
        self.peaks = None                          # waveform.Peaks
        self._waves = {}                           # waveform polygons for the current view
        self.peaksReady.connect(self._on_peaks)

    def set_peaks(self, peaks):
        self.peaks = peaks
        self._waves.clear()
        self.update()

    def _on_peaks(self, _path):
        self._waves.clear()
        self.update()

    # -- data -----------------------------------------------------------------------------------
    def set_project(self, proj, keep_view=False):
        self.proj = proj
        self.fps = proj["fps"]
        visual = [t for t in proj["tracks"] if t["kind"] != "audio"]
        audio = [t for t in proj["tracks"] if t["kind"] == "audio"]
        self.rows = list(reversed(visual)) + audio
        self._layout()
        self._waves.clear()
        self.drag = None
        if not keep_view:
            self.selected_id = None
            dur = max(proj["duration_us"] / US, 1)
            self.px_per_s = max(2.0, (self.width() - HEADER_W - 20) / dur)
            self.scroll_s = 0
        self._layout()
        self.update()

    @property
    def selected_id(self):
        """The primary selected clip (shown in the inspector); setting it selects only it."""
        return self._primary

    @selected_id.setter
    def selected_id(self, cid):
        self._primary = cid
        self.selected_ids = {cid} if cid else set()

    def selected_clips(self):
        return [c for t in self.rows for c in t["clips"] if c["id"] in self.selected_ids]

    def selected_clips_primary_first(self):
        return sorted(self.selected_clips(), key=lambda c: c["id"] != self._primary)

    def set_selection(self, ids, primary=None):
        ids = set(ids)
        if primary not in ids:
            primary = next((c["id"] for c in self.selected_clips() if c["id"] in ids), None) \
                or next((c["id"] for t in self.rows for c in t["clips"] if c["id"] in ids), None)
        self._primary = primary
        self.selected_ids = ids if primary else set()
        self.clipSelected.emit(self.selected)
        self.update()

    def select_all(self):
        ids = {c["id"] for t in self.rows for c in t["clips"]}
        self.set_selection(ids, self._primary if self._primary in ids else None)

    @property
    def selected(self):
        for t in self.rows:
            for c in t["clips"]:
                if c["id"] == self.selected_id:
                    return c
        return None

    def select(self, clip):
        self.selected_id = clip["id"] if clip else None
        self.clipSelected.emit(clip)
        self.update()

    def set_position(self, frame, follow=True):
        """Move the playhead; with follow, scroll so it stays in view (playback, keys)."""
        self.pos = frame
        x = self._x(frame / self.fps)
        if follow and (x > self.width() - 30 or x < HEADER_W):
            self.scroll_s = max(0.0, frame / self.fps - (self.width() - HEADER_W) * 0.2 / self.px_per_s)
        self.update()

    # -- geometry -------------------------------------------------------------------------------
    def _x(self, sec):
        return HEADER_W + (sec - self.scroll_s) * self.px_per_s

    def _sec(self, x):
        return (x - HEADER_W) / self.px_per_s + self.scroll_s

    def row_h(self, i):
        t = self.rows[i]
        h = self.heights.get(t["id"])
        return h or round((AUDIO_H if t["kind"] == "audio" else TRACK_H) * self.vzoom)

    def _layout(self):
        """Row positions for the current heights and vertical scroll; updates the scroll bar."""
        view = max(1, self.height() - RULER_H)
        content = sum(self.row_h(i) for i in range(len(self.rows))) + AUDIO_H   # room to drop below
        top = max(0, content - view)
        self.scroll_y = min(max(0, self.scroll_y), top)
        self.vbar.blockSignals(True)
        self.vbar.setRange(0, top)
        self.vbar.setPageStep(view)
        self.vbar.setSingleStep(20)
        self.vbar.setValue(self.scroll_y)
        self.vbar.blockSignals(False)
        self.vbar.setGeometry(self.width() - 12, RULER_H, 12, view)
        self.vbar.setVisible(top > 0)
        self.tops, y = [], RULER_H - self.scroll_y
        for i in range(len(self.rows)):
            self.tops.append(y)
            y += self.row_h(i)
        self.rows_end = y

    def _on_vscroll(self, v):
        self.scroll_y = v
        self._layout()
        self._waves.clear()
        self.update()

    def set_vzoom(self, z):
        """Scale every track's height (tracks resized by hand keep their proportion)."""
        z = min(MAX_H / TRACK_H, max(MIN_H / TRACK_H, z))
        k = z / self.vzoom
        self.heights = {tid: min(MAX_H, max(MIN_H, round(h * k))) for tid, h in self.heights.items()}
        self.vzoom = z
        self._layout()
        self._waves.clear()
        self.vzoomChanged.emit(z)
        self.update()

    def resizeEvent(self, e):
        self._layout()
        super().resizeEvent(e)

    def _edge_at(self, pos):
        """Row whose bottom edge is under pos in the header (for resizing), or None."""
        if pos.x() >= HEADER_W:
            return None
        for i, top in enumerate(self.tops):
            if abs(pos.y() - (top + self.row_h(i) - 1)) <= 3 and pos.y() > RULER_H:
                return i
        return None

    def _row_at(self, y):
        for i, top in enumerate(self.tops):
            if top <= y < top + self.row_h(i):
                return i
        return None

    def header_buttons(self, i):
        """[(flag, rect)] of a track header's toggle buttons, right-aligned."""
        tr = self.rows[i]
        if tr["kind"] == "audio":
            flags = ["muted", "solo"]
        else:
            flags = ["hidden"]
            if any(c["type"] in ("video", "compound") for c in tr["clips"]):
                flags.append("muted")
        y = self.tops[i] + (self.row_h(i) - 2 - BTN) / 2
        return [(f, QRectF(HEADER_W - 6 - (len(flags) - k) * (BTN + 3), y, BTN, BTN))
                for k, f in enumerate(flags)]

    def _hit(self, pos):
        """(row, clip, zone) under pos; zone is 'start', 'end' or 'body'."""
        row = self._row_at(pos.y())
        if row is None:
            return None, None, None
        for c in self.rows[row]["clips"]:
            x0 = self._x(c["start_us"] / US)
            x1 = self._x((c["start_us"] + c["duration_us"]) / US)
            if x0 - EDGE_PX / 2 <= pos.x() <= x1 + EDGE_PX / 2:
                if x1 - x0 > 3 * EDGE_PX:
                    if pos.x() <= x0 + EDGE_PX:
                        return row, c, "start"
                    if pos.x() >= x1 - EDGE_PX:
                        return row, c, "end"
                if x0 <= pos.x() <= x1:
                    return row, c, "body"
        return row, None, None

    def _snap(self, t_us, exclude):
        """Snap a time to the playhead / 0 / clip edges within SNAP_PX; exclude is a clip or
        a set of clip ids (a moving group). With snapping off, times are left as they are."""
        if not self.snapping:
            return t_us
        best, limit = t_us, SNAP_PX / self.px_per_s * US
        cands = [0, self.pos / self.fps * US]
        for tr in self.rows:
            for c in tr["clips"]:
                if c is not exclude and not (isinstance(exclude, set) and c["id"] in exclude):
                    cands += [c["start_us"], c["start_us"] + c["duration_us"]]
        for t in cands:
            if abs(t - t_us) < limit:
                best, limit = t, abs(t - t_us)
        return best

    # -- painting -------------------------------------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        try:
            self._paint(p)
        finally:
            p.end()                                  # never leave the painter open on an error

    def _paint(self, p):
        p.fillRect(self.rect(), QColor("#161618"))
        if not self.proj:
            p.setPen(QColor("#777"))
            p.drawText(self.rect(), Qt.AlignCenter, "檔案 > 匯入剪映草稿")
            return
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        p.fillRect(0, 0, w, RULER_H, QColor("#1e1e21"))
        p.fillRect(0, RULER_H - 1, w, 1, QColor("#0e0e10"))
        step = next(s for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300) if s * self.px_per_s >= 70)
        p.setPen(QColor("#8a8a90"))
        p.setFont(QFont("Segoe UI", 8))
        t = (int(self.scroll_s / step)) * step
        while self._x(t) < w:
            x = self._x(t)
            if x >= HEADER_W:
                p.drawLine(int(x), RULER_H - 6, int(x), RULER_H)
                label = timecode(t * US, self.fps)
                p.drawText(int(x) + 3, RULER_H - 9, label if step < 1 else label[:5])
            t += step
        if self.mark_in is not None or self.mark_out is not None:
            a = self._x((self.mark_in or 0) / self.fps)
            b = self._x(((self.mark_out if self.mark_out is not None else
                          self.proj["duration_us"] / US * self.fps)) / self.fps)
            a, b = max(a, HEADER_W), max(b, HEADER_W)
            p.fillRect(QRectF(a, 0, b - a, RULER_H), QColor(255, 255, 255, 70))
            p.fillRect(QRectF(a, self.height() - 3, b - a, 3), QColor(255, 255, 255, 160))
            p.setPen(QPen(QColor("#e6e6e6"), 2))
            if self.mark_in is not None and a > HEADER_W:
                p.drawLine(int(a), 0, int(a), RULER_H)
            if self.mark_out is not None and b > HEADER_W:
                p.drawLine(int(b), 0, int(b), RULER_H)
        # a clip being moved / trimmed is drawn at its new place (other drags have no ghost)
        dragged = self.drag["clip"] if self.drag and self.drag["moved"] and self.drag["mode"] in ("body", "start", "end")             else None
        group = self.drag["ids"] if self.drag and self.drag["moved"] and self.drag["mode"] == "group" else ()
        tracks = self.proj["tracks"]
        p.save()
        p.setClipRect(QRectF(0, RULER_H, w, self.height() - RULER_H))
        for i, tr in enumerate(self.rows):
            if self.tops[i] > self.height() or self.tops[i] + self.row_h(i) < RULER_H:
                continue
            y, h = self.tops[i], self.row_h(i)
            p.fillRect(0, y, w, h - 1, row_color(tr))       # the track colour tints its row only
            p.fillRect(0, y, HEADER_W, h - 1, QColor("#242427"))     # header column, as in Resolve
            p.fillRect(HEADER_W - 1, y, 1, h - 1, QColor("#0e0e10"))
            if tr.get("color"):
                p.fillRect(0, y, 3, h - 1, QColor(tr["color"]))
            # V1 is the bottom picture track, A1 the first sound track (Resolve's numbering)
            if tr["kind"] == "audio":
                label = f"A{sum(1 for t in self.rows[:i] if t['kind'] == 'audio') + 1}"
            else:
                label = f"V{sum(1 for t in self.rows[i:] if t['kind'] != 'audio')}"
            p.setPen(QColor("#8e8e94"))
            f0 = p.font()
            fb = QFont(f0)
            fb.setBold(True)
            p.setFont(fb)
            p.drawText(QRectF(8, y, 26, min(h - 1, 26)), Qt.AlignVCenter, label)
            p.setFont(f0)
            btns = self.header_buttons(i)
            name_w = (btns[0][1].left() if btns else HEADER_W) - 40
            p.setPen(QColor("#c8c8cc"))
            name = p.fontMetrics().elidedText(tr.get("name") or tr["kind"], Qt.ElideRight, int(name_w))
            gain = tr.get("gain", 1.0)
            if abs(gain - 1.0) > 1e-6:
                p.drawText(QRectF(34, y + 5, name_w, 16), Qt.AlignVCenter, name)
                p.setPen(QColor("#8a8a90"))
                db = "-∞" if gain <= 0 else f"{20 * math.log10(gain):+.1f}"
                p.drawText(QRectF(34, y + 21, name_w, 16), Qt.AlignVCenter, f"{db} dB")
            else:
                p.drawText(QRectF(34, y, name_w, min(h - 1, 26)), Qt.AlignVCenter, name)
            for flag, r in btns:
                self._draw_button(p, flag, r, bool(tr.get(flag)))
            dim = (project.sounds(tr, tracks) <= 0) if tr["kind"] == "audio" else not project.visible(tr)
            for c in tr["clips"]:
                if c is not dragged and c["id"] not in group:
                    self._draw_clip(p, c, y, c["start_us"], c["duration_us"], track=tr, h=h, dim=dim)
            for c in tr["clips"]:
                if c["id"] in group:
                    self._draw_clip(p, c, y, c["start_us"] + self.drag["shift"], c["duration_us"],
                                    ghost=True, track=tr, h=h, dim=dim)
        if dragged:
            d = self.drag
            h = self.row_h(d["row"])
            if d.get("new") == "top":                   # landing on a new top track
                p.fillRect(QRectF(HEADER_W, RULER_H, w - HEADER_W, 3), QColor("#e6e6e6"))
                y = RULER_H - h + 2
            elif d.get("new") == "bottom":              # landing on a new last audio track
                p.fillRect(QRectF(HEADER_W, self.rows_end, w - HEADER_W, 3), QColor("#e6e6e6"))
                y = self.rows_end + 2
            else:
                y = self.tops[d["row"]]
            self._draw_clip(p, dragged, y, d["start"], d["end"] - d["start"], ghost=True,
                            track=self.rows[d["row"]], h=h)
        if self.band is not None:
            p.setPen(QPen(QColor("#e6e6e6"), 1, Qt.DashLine))
            p.setBrush(QColor(255, 255, 255, 35))
            p.drawRect(self.band)
        if self.drop_at is not None:
            row, t = self.drop_at
            dx = self._x(t / US)
            p.setPen(QPen(QColor("#e6e6e6"), 2, Qt.DashLine))
            p.drawLine(int(dx), RULER_H, int(dx), self.height())
            if row is not None:
                p.fillRect(QRectF(HEADER_W, self.tops[row], w - HEADER_W, self.row_h(row) - 2),
                           QColor(255, 255, 255, 30))
        p.restore()
        x = self._x(self.pos / self.fps)
        if x >= HEADER_W:
            p.setPen(QPen(QColor("#ff4d4f"), 2))
            p.drawLine(int(x), 0, int(x), self.height())

    @staticmethod
    def clip_label(c):
        if c.get("compound") and not c.get("named"):
            return c["compound"].get("name") or c.get("name") or "複合片段"
        if c.get("named") or not c.get("text"):
            return c.get("name") or c["type"]
        return c["text"]["content"]

    @staticmethod
    def _draw_button(p, flag, r, on):
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#e6e6e6") if on
                   else QColor("#2c2c31"))
        p.drawRoundedRect(r, 3, 3)
        ink = QColor("#111114") if on else QColor("#a0a0a6")
        p.setPen(QPen(ink, 1.3))
        cx, cy = r.center().x(), r.center().y()
        if flag == "solo":
            p.setFont(QFont("Segoe UI", 8, QFont.Bold))
            p.drawText(r, Qt.AlignCenter, "S")
        elif flag == "muted":                   # a speaker; crossed when muted
            p.setBrush(ink)
            p.drawPolygon(QPolygonF([QPointF(cx - 6, cy - 2), QPointF(cx - 3, cy - 2), QPointF(cx + 1, cy - 5),
                                     QPointF(cx + 1, cy + 5), QPointF(cx - 3, cy + 2), QPointF(cx - 6, cy + 2)]))
            p.setBrush(Qt.NoBrush)
            if on:
                p.drawLine(QPointF(cx + 3, cy - 3), QPointF(cx + 7, cy + 3))
                p.drawLine(QPointF(cx + 7, cy - 3), QPointF(cx + 3, cy + 3))
            else:
                p.drawArc(QRectF(cx - 2, cy - 4, 7, 8), -60 * 16, 120 * 16)
        else:                                   # an eye; crossed when hidden
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(cx - 6, cy - 3.5, 12, 7))
            p.setBrush(ink)
            p.drawEllipse(QPointF(cx, cy), 1.8, 1.8)
            if on:
                p.drawLine(QPointF(cx - 6, cy + 5), QPointF(cx + 6, cy - 5))
        p.restore()

    def _wave(self, c, start, x0, x1, top, height):
        """Waveform polygon of an audio / video clip between screen x0..x1, or None."""
        if self.peaks is None or not c.get("media") or c["type"] not in ("audio", "video"):
            return None
        key = (c["id"], start, c["duration_us"], c.get("source_start_us", 0), round(x0), round(x1),
               top, height, self.px_per_s, self.scroll_s)
        if key in self._waves:
            return self._waves[key]
        res = self.peaks.get(c["media"]["path"])
        if res is None or not len(res[0]):
            return None
        peaks, lead = res
        n = max(1, int(x1 - x0))
        t0 = self._sec(x0) - start / US                     # seconds into the clip
        t1 = self._sec(x0 + n) - start / US
        src = c.get("source_start_us", 0) / US
        amp = waveform.columns(peaks, lead, src + t0, src + t1, n)
        # the clip's volume and fades, sampled every few columns
        vol, fi, fo, dur = c.get("volume", 1.0), c.get("fade_in_us", 0), c.get("fade_out_us", 0), c["duration_us"]
        if curves.is_animated(vol) or fi or fo:
            ts = np.linspace(t0, t1, max(2, n // 4)) * US
            g = np.array([curves.value(vol, t) for t in ts], np.float32)
            if fi:
                g *= np.clip(ts / fi, 0, 1)
            if fo:
                g *= np.clip((dur - ts) / fo, 0, 1)
            amp *= np.interp(np.linspace(t0, t1, n) * US, ts, g)
        else:
            amp *= curves.value(vol, 0)
        amp = np.clip(amp, 0, 1) ** 0.7                      # quieter parts stay visible
        mid, half = top + height / 2, height / 2
        xs = x0 + np.arange(n) + 0.5
        upper = [QPointF(x, mid - a * half) for x, a in zip(xs, amp)]
        lower = [QPointF(x, mid + a * half) for x, a in zip(xs[::-1], amp[::-1])]
        poly = QPolygonF(upper + lower)
        if len(self._waves) > 400:
            self._waves.clear()
        self._waves[key] = poly
        return poly

    def _draw_clip(self, p, c, y, start, dur, ghost=False, track=None, h=TRACK_H, dim=False):
        w = self.width()
        x0, x1 = self._x(start / US), self._x((start + dur) / US)
        if x1 < HEADER_W or x0 > w:
            return
        r = QRectF(max(x0, HEADER_W) + 0.5, y + 3, max(1.0, x1 - max(x0, HEADER_W) - 1), h - 8)
        col = QColor(c.get("color") or COLORS.get(c["type"], "#555"))      # (not the track's colour)
        sel = c["id"] in self.selected_ids
        if sel:
            col = col.lighter(150)
        if dim:
            col = col.darker(220)
        if ghost:
            col.setAlpha(190)
        p.setPen(QPen(QColor("#ffffff") if sel else col.darker(140), 1))
        p.setBrush(col)
        p.drawRoundedRect(r, 3, 3)
        audio = c["type"] == "audio"
        wx0, wx1 = max(r.left() + 1, HEADER_W), min(r.right() - 1, w)
        if wx1 - wx0 >= 2:
            # sound clips: the waveform under the label; video: a thin strip at the bottom
            wt, wh = (r.top() + 15, r.height() - 17) if audio else (r.bottom() - 10, 9)
            if not audio and r.height() > 40:            # tall video rows: a bigger strip
                wt, wh = r.top() + r.height() / 2, r.height() / 2 - 1
            poly = self._wave(c, start, wx0, wx1, wt, wh) if wh >= 4 and (audio or r.height() >= 24) else None
            if poly is not None:
                p.save()
                p.setClipRect(r)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, 80 if dim else 150 if audio else 110))
                p.drawPolygon(poly)
                p.restore()
        if r.width() > 24:
            p.setPen(QColor("#9a9aa0") if dim else QColor("#f2f2f2"))
            label = self.clip_label(c).replace("\n", " ")
            if c["type"] == "compound":
                label = ("⧉ " if c.get("timeline_id") else "▣ ") + label
            lr = r.adjusted(4, 0, -2, 0)
            if audio and r.height() > 20:
                lr.setHeight(16)
            elif c["type"] == "video" and r.height() >= 24:
                lr.setBottom(wt - 1 if r.height() > 40 else r.bottom() - 9)
            p.drawText(lr, Qt.AlignVCenter, label)
        row = next((i for i, t in enumerate(self.rows) if c in t["clips"]), None)
        if row is not None and not ghost and abs(self.tops[row] - y) < 0.5:
            self._draw_volume(p, c, row, r)
        if c["id"] == self.selected_id and not ghost:
            # keyframes of the selected clip, as diamonds along its bottom edge
            d = self.drag if self.drag and self.drag["mode"] == "key" and self.drag["clip"] is c else None
            p.setPen(QPen(QColor("#111114"), 1))
            for k in edit.key_times(c):
                moving = d is not None and abs(k - d["t0"]) <= edit.KEY_TOL_US
                kx = self._x((start + (d["t"] if moving else k)) / US)
                if HEADER_W <= kx <= w:
                    ky = r.bottom() - 5
                    p.setBrush(QColor("#ffffff") if moving else QColor("#ffb020"))
                    p.drawPolygon([QPointF(kx, ky - 5), QPointF(kx + 5, ky), QPointF(kx, ky + 5), QPointF(kx - 5, ky)])

    # -- volume line ----------------------------------------------------------------------------
    DB_LO, DB_HI = -40.0, 20.0

    def _vol_band(self, c, row):
        """(top, bottom) of the area the volume line moves in, or None (no line on this clip)."""
        if "volume" not in c or c["type"] not in ("audio", "video"):
            return None
        h = self.row_h(row)
        top, bottom = self.tops[row] + 5, self.tops[row] + h - 7       # the clip's whole height
        if c["type"] == "video" and h < 44 or bottom - top < 10:
            return None
        return top, bottom

    def _vol_y(self, g, band):
        db = 20 * math.log10(g) if g > 1e-5 else self.DB_LO
        f = (min(max(db, self.DB_LO), self.DB_HI) - self.DB_LO) / (self.DB_HI - self.DB_LO)
        return band[1] - f * (band[1] - band[0])

    def _vol_of_y(self, y, band):
        f = (band[1] - y) / max(1.0, band[1] - band[0])
        db = self.DB_LO + min(max(f, 0.0), 1.0) * (self.DB_HI - self.DB_LO)
        return 0.0 if f <= 0 else 10 ** (db / 20)

    def _volume(self, c):
        """The clip's volume, or the one being dragged."""
        d = self.drag
        if d and d["mode"] in ("vol", "volkey") and d["clip"] is c:
            return d["vol"]
        return c.get("volume", 1.0)

    def _vol_hit(self, pos):
        """("vol" | "volkey", clip, row, key index) under pos, or None."""
        row = self._row_at(pos.y())
        if row is None or pos.x() < HEADER_W:
            return None
        for c in self.rows[row]["clips"]:
            band = self._vol_band(c, row)
            x0, x1 = self._x(c["start_us"] / US), self._x((c["start_us"] + c["duration_us"]) / US)
            if band is None or not x0 + EDGE_PX <= pos.x() <= x1 - EDGE_PX:
                continue
            vol = c.get("volume", 1.0)
            if curves.is_animated(vol):
                for i, k in enumerate(vol["keys"]):
                    kx = self._x((c["start_us"] + k[0]) / US)
                    if abs(pos.x() - kx) <= 5 and abs(pos.y() - self._vol_y(k[1], band)) <= 5:
                        return "volkey", c, row, i
            t = (self._sec(pos.x()) * US) - c["start_us"]
            if abs(pos.y() - self._vol_y(curves.value(vol, t), band)) <= 4:
                return "vol", c, row, None
        return None

    def _draw_volume(self, p, c, row, r):
        band = self._vol_band(c, row)
        if band is None:
            return
        vol = self._volume(c)
        x0, x1 = max(r.left(), HEADER_W), min(r.right(), self.width())
        p.save()
        p.setClipRect(r)
        p.setPen(QPen(QColor("#e6e6e6"), 1.4))
        if curves.is_animated(vol):
            pts = []
            x = x0
            while True:
                t = self._sec(x) * US - c["start_us"]
                pts.append(QPointF(x, self._vol_y(curves.value(vol, t), band)))
                if x >= x1:
                    break
                x = min(x + 3, x1)
            p.drawPolyline(QPolygonF(pts))
            p.setPen(QPen(QColor("#111114"), 1))
            p.setBrush(QColor("#ffb020"))
            for k in vol["keys"]:
                kx = self._x((c["start_us"] + k[0]) / US)
                if x0 - 4 <= kx <= x1 + 4:
                    p.drawEllipse(QPointF(kx, self._vol_y(k[1], band)), 3.5, 3.5)
        else:
            y = self._vol_y(curves.value(vol, 0), band)
            p.drawLine(QPointF(x0, y), QPointF(x1, y))
        d = self.drag
        if d and d["mode"] in ("vol", "volkey") and d["clip"] is c and d["moved"]:
            g = d["shown"]
            text = "-∞ dB" if g <= 1e-5 else f"{20 * math.log10(g):+.1f} dB"
            p.setPen(QColor("#ffffff"))
            p.drawText(QRectF(d["x"] + 8, band[0] - 2, 90, 14), Qt.AlignLeft | Qt.AlignVCenter, text)
        p.restore()

    # -- mouse ----------------------------------------------------------------------------------
    def _key_hit(self, pos):
        """(clip, keyframe clip time) of the selected clip's diamond under pos, or (None, None)."""
        c = self.selected
        if c is None:
            return None, None
        row = next((i for i, t in enumerate(self.rows) if c in t["clips"]), None)
        if row is None:
            return None, None
        ky = self.tops[row] + 3 + (self.row_h(row) - 8) - 5
        if abs(pos.y() - ky) > 7:
            return None, None
        best = None
        for k in edit.key_times(c):
            dx = abs(pos.x() - self._x((c["start_us"] + k) / US))
            if dx <= 7 and (best is None or dx < best[0]):
                best = (dx, k)
        return (c, best[1]) if best else (None, None)

    def mousePressEvent(self, e):
        if self.proj and e.button() == Qt.RightButton and e.position().x() >= HEADER_W:
            # right-drag selects time; a right click without moving opens the menu (on release)
            self.drag = {"clip": None, "mode": "region", "moved": False, "pos": e.position(),
                         "t0": self._snap(max(0.0, self._sec(e.position().x())) * US, None)}
            return
        if self.proj and e.button() == Qt.MiddleButton:     # drag the view
            self.drag = {"clip": None, "mode": "pan", "moved": False, "pos": e.position(),
                         "s": self.scroll_s, "y": self.scroll_y}
            self.setCursor(Qt.ClosedHandCursor)
            return
        if not self.proj or e.button() != Qt.LeftButton:
            return
        if e.position().x() < HEADER_W:
            edge = self._edge_at(e.position())
            if edge is not None:
                self.drag = {"clip": None, "mode": "resize", "row": edge, "y0": e.position().y(),
                             "h0": self.row_h(edge), "moved": False}
                return
            row = self._row_at(e.position().y())
            if row is not None:
                for flag, r in self.header_buttons(row):
                    if r.contains(e.position()):
                        self.trackAction.emit("toggle:" + flag, self.rows[row]["id"])
            return
        pos = e.position()
        vh = self._vol_hit(pos) if not e.modifiers() else None
        if vh is not None:
            kind, c, row, i = vh
            self.select(c)
            vol = copy.deepcopy(c.get("volume", 1.0))
            self.drag = {"clip": c, "mode": kind, "row": row, "i": i, "y0": pos.y(), "x0": pos.x(), "x": pos.x(),
                         "orig": copy.deepcopy(vol), "vol": vol, "moved": False,
                         "shown": curves.value(vol, self._sec(pos.x()) * US - c["start_us"]) if i is None
                         else vol["keys"][i][1]}
            return
        kc, kt = self._key_hit(pos)
        if kc is not None and not e.modifiers():
            self.drag = {"clip": kc, "mode": "key", "t0": kt, "t": kt, "x0": pos.x(), "moved": False}
            return
        row, c, zone = self._hit(pos)
        adding = bool(e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier))
        if c is None:
            if pos.y() < RULER_H or row is None and pos.y() < self.rows_end:
                self.seekRequested.emit(max(0, round(self._sec(pos.x()) * self.fps)))
                self.drag = {"clip": None, "mode": "seek", "moved": False}
                return
            # empty track space: a click seeks and clears, a drag draws a selection box
            self.drag = {"clip": None, "mode": "band", "moved": False, "x0": pos.x(), "y0": pos.y(),
                         "base": set(self.selected_ids) if adding else set()}
            return
        if adding:
            ids = set(self.selected_ids) ^ {c["id"]}
            self.set_selection(ids, c["id"] if c["id"] in ids else None)
            if c["id"] not in ids:
                return
        elif c["id"] not in self.selected_ids or len(self.selected_ids) == 1:
            self.select(c)
        else:
            self.set_selection(self.selected_ids, c["id"])
        if len(self.selected_ids) > 1 and zone == "body":
            self.drag = {"clip": c, "mode": "group", "x0": pos.x(), "moved": False, "shift": 0,
                         "ids": set(self.selected_ids), "adding": adding}
            return
        self.drag = {"clip": c, "mode": zone, "x0": pos.x(), "row0": row, "row": row,
                     "start": c["start_us"], "end": c["start_us"] + c["duration_us"], "moved": False}

    def mouseMoveEvent(self, e):
        pos = e.position()
        d = self.drag
        if d is None:
            if self.proj and self._edge_at(pos) is not None:
                self.setCursor(Qt.SizeVerCursor)
                return
            if self.proj and self._key_hit(pos)[0] is not None:
                self.setCursor(Qt.SizeHorCursor)
                return
            vh = self._vol_hit(pos) if self.proj else None
            if vh is not None:
                self.setCursor(Qt.SizeAllCursor if vh[0] == "volkey" else Qt.SizeVerCursor)
                return
            _, c, zone = self._hit(pos) if self.proj else (None, None, None)
            self.setCursor(Qt.SizeHorCursor if zone in ("start", "end") else Qt.ArrowCursor)
            return
        if d["mode"] == "region":
            if not d["moved"] and abs(pos.x() - d["pos"].x()) < DRAG_PX:
                return
            d["moved"] = True
            t = self._snap(max(0.0, self._sec(pos.x())) * US, None)
            a, b = sorted((d["t0"], t))
            self.mark_in = round(a / US * self.fps)
            self.mark_out = max(self.mark_in, round(b / US * self.fps) - 1)
            self.marksChanged.emit()
            self.update()
            return
        if d["mode"] in ("vol", "volkey"):
            if not d["moved"] and abs(pos.y() - d["y0"]) + abs(pos.x() - d["x0"]) < DRAG_PX:
                return
            d["moved"] = True
            d["x"] = pos.x()
            band = self._vol_band(d["clip"], d["row"])
            c, orig = d["clip"], d["orig"]
            if d["mode"] == "vol":                         # the whole volume, in dB steps
                db = -(pos.y() - d["y0"]) / max(1.0, band[1] - band[0]) * (self.DB_HI - self.DB_LO)
                k = 10 ** (db / 20)
                clamp = lambda g: min(10.0, max(0.0, g * k))
                if curves.is_animated(orig):
                    d["vol"] = {"keys": [[q[0], clamp(q[1])] + q[2:] for q in orig["keys"]]}
                    d["shown"] = clamp(curves.value(orig, self._sec(d["x0"]) * US - c["start_us"]))
                else:
                    d["vol"] = d["shown"] = clamp(curves.value(orig, 0))
            else:                                          # one keyframe: value and time
                keys = [list(q) for q in orig["keys"]]
                i = d["i"]
                frame = US / self.fps
                t = keys[i][0] + (pos.x() - d["x0"]) / self.px_per_s * US
                lo = keys[i - 1][0] + frame if i > 0 else 0
                hi = keys[i + 1][0] - frame if i + 1 < len(keys) else c["duration_us"]
                keys[i][0] = int(min(max(round(t / frame) * frame, lo), hi))
                keys[i][1] = min(10.0, self._vol_of_y(self._vol_y(orig["keys"][i][1], band) + pos.y() - d["y0"], band))
                d["vol"], d["shown"] = {"keys": keys}, keys[i][1]
            self.update()
            return
        if d["mode"] == "key":
            if not d["moved"] and abs(pos.x() - d["x0"]) < DRAG_PX:
                return
            d["moved"] = True
            c = d["clip"]
            frame = US / self.fps
            t = d["t0"] + (pos.x() - d["x0"]) / self.px_per_s * US
            g = c["start_us"] + t                                   # snap on the timeline's frames
            play = self.pos / self.fps * US
            snap = self.snapping and abs(g - play) < SNAP_PX / self.px_per_s * US
            g = play if snap else round(g / frame) * frame
            others = [k for k in edit.key_times(c) if abs(k - d["t0"]) > edit.KEY_TOL_US]
            lo = max([k + frame for k in others if k < d["t0"]], default=0)
            hi = min([k - frame for k in others if k > d["t0"]], default=c["duration_us"])
            d["t"] = int(round(min(max(g - c["start_us"], lo), hi)))
            self.update()
            return
        if d["mode"] == "pan":
            self.scroll_s = max(0.0, d["s"] - (pos.x() - d["pos"].x()) / self.px_per_s)
            self.vbar.setValue(round(d["y"] - (pos.y() - d["pos"].y())))
            self._waves.clear()
            self.update()
            return
        if d["mode"] == "resize":
            h = min(MAX_H, max(MIN_H, round(d["h0"] + pos.y() - d["y0"])))
            self.heights[self.rows[d["row"]]["id"]] = h
            self._layout()
            self._waves.clear()
            self.update()
            return
        if d["mode"] == "seek":
            self.seekRequested.emit(max(0, round(self._sec(pos.x()) * self.fps)))
            return
        if d["mode"] == "band":
            if not d["moved"] and abs(pos.x() - d["x0"]) + abs(pos.y() - d["y0"]) < DRAG_PX:
                return
            d["moved"] = True
            self.band = QRectF(QPointF(d["x0"], d["y0"]), pos).normalized()
            hit = set()
            for i, tr in enumerate(self.rows):
                if self.tops[i] + self.row_h(i) < self.band.top() or self.tops[i] > self.band.bottom():
                    continue
                for c in tr["clips"]:
                    if self._x(c["start_us"] / US) <= self.band.right() and \
                            self._x((c["start_us"] + c["duration_us"]) / US) >= self.band.left():
                        hit.add(c["id"])
            self.set_selection(d["base"] | hit)
            return
        if d["mode"] == "group":
            if not d["moved"] and abs(pos.x() - d["x0"]) < DRAG_PX:
                return
            d["moved"] = True
            c = d["clip"]
            dt = (pos.x() - d["x0"]) / self.px_per_s * US
            group = [k for t in self.rows for k in t["clips"] if k["id"] in d["ids"]]
            dt = max(dt, -min(k["start_us"] for k in group))
            # snap the clip under the mouse by its start or its end
            s = self._snap(c["start_us"] + dt, d["ids"]) - c["start_us"]
            e_ = self._snap(c["start_us"] + c["duration_us"] + dt, d["ids"]) - c["start_us"] - c["duration_us"]
            d["shift"] = s if abs(s - dt) <= abs(e_ - dt) else e_
            self.update()
            return
        if not d["moved"] and abs(pos.x() - d["x0"]) < DRAG_PX and self._row_at(pos.y()) == d["row0"]:
            return
        d["moved"] = True
        c = d["clip"]
        dt = (pos.x() - d["x0"]) / self.px_per_s * US
        s0, e0 = c["start_us"], c["start_us"] + c["duration_us"]
        if d["mode"] == "body":
            start = max(0.0, s0 + dt)
            snapped_s = self._snap(start, c)
            snapped_e = self._snap(start + (e0 - s0), c) - (e0 - s0)
            start = snapped_s if abs(snapped_s - start) <= abs(snapped_e - start) else snapped_e
            d["start"], d["end"] = start, start + (e0 - s0)
            row = self._row_at(pos.y())
            audio = self.rows[d["row0"]]["kind"] == "audio"
            d["new"] = None
            if row is not None and (self.rows[row]["kind"] == "audio") == audio:
                d["row"] = row
            elif row is None and not audio and pos.y() < RULER_H:
                d["new"] = "top"                        # above the top layer: a new top track
            elif row is None and audio and pos.y() >= self.rows_end:
                d["new"] = "bottom"                     # below the last audio row
        elif d["mode"] == "start":
            d["start"] = min(self._snap(s0 + dt, c), e0 - US / self.fps)
        else:
            d["end"] = max(self._snap(e0 + dt, c), s0 + US / self.fps)
        s1 = d.get("start", s0) if d["mode"] != "end" else s0
        e1 = d.get("end", e0) if d["mode"] != "start" else e0
        self.clipDragging.emit(c["id"], int(round(s1)), int(round(e1 - s1)))
        self.update()

    def mouseReleaseEvent(self, e):
        d, self.drag = self.drag, None
        if d and d["mode"] == "region":
            if not d["moved"]:
                self._menu(e.position().toPoint(), e.globalPosition().toPoint())
            return
        if d and d["mode"] in ("vol", "volkey"):
            if d["moved"]:
                self.volumeEdited.emit(d["clip"]["id"], d["vol"])
            self.update()
            return
        if d and d["mode"] == "key":
            if d["moved"] and d["t"] != d["t0"]:
                self.keyMoveRequested.emit(d["clip"]["id"], int(d["t0"]), int(d["t"]))
            elif not d["moved"]:                        # a click goes to the keyframe
                self.seekRequested.emit(round((d["clip"]["start_us"] + d["t0"]) / US * self.fps))
            self.update()
            return
        if d and d["mode"] == "pan":
            self.setCursor(Qt.ArrowCursor)
        if not d or d["mode"] in ("seek", "resize", "pan"):
            return
        if d["mode"] == "band":
            self.band = None
            if not d["moved"]:
                if not d["base"]:
                    self.select(None)
                self.seekRequested.emit(max(0, round(self._sec(e.position().x()) * self.fps)))
            self.update()
            return
        if d["mode"] == "group":
            if d["moved"] and d["shift"]:
                self.groupMoveRequested.emit(sorted(d["ids"]), int(round(d["shift"])))
            elif not d["moved"] and not d["adding"]:
                self.select(d["clip"])                  # a plain click picks one of the group
            self.update()
            return
        c = d["clip"]
        if not d["moved"]:                              # clicking a clip only selects it (as in
            self.update()                               # Jianying): the playhead stays put
            return
        if d["mode"] == "body" and d.get("new"):
            self.newTrackRequested.emit(c["id"], int(round(d["start"])), d["new"] == "top")
        elif d["mode"] == "body":
            self.moveRequested.emit(c["id"], int(round(d["start"])), self.rows[d["row"]]["id"])
        elif d["mode"] == "start":
            self.trimRequested.emit(c["id"], "start", int(round(d["start"])))
        else:
            self.trimRequested.emit(c["id"], "end", int(round(d["end"])))
        self.update()

    # -- drops from the media library -----------------------------------------------------------
    def _accepts(self, md):
        return (bool(self.proj) and md.hasFormat(MEDIA_MIME)) or md.hasUrls()

    def dragEnterEvent(self, e):
        if self._accepts(e.mimeData()):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if not self._accepts(e.mimeData()):
            return
        pos = e.position()
        if self.proj:
            self.drop_at = (self._row_at(pos.y()), max(0.0, self._sec(pos.x())) * US)
        e.acceptProposedAction()
        self.update()

    def dragLeaveEvent(self, e):
        self.drop_at = None
        self.update()

    def dropEvent(self, e):
        self.drop_at = None
        pos = e.position()
        row = self._row_at(pos.y()) if self.proj else None
        tid = self.rows[row]["id"] if row is not None else ""
        start = int(max(0.0, self._sec(pos.x())) * US) if self.proj else 0
        if not e.mimeData().hasFormat(MEDIA_MIME):           # files from the file manager
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            if paths:
                self.filesDropped.emit(paths, tid, start)
                e.acceptProposedAction()
            self.update()
            return
        for ident in bytes(e.mimeData().data(MEDIA_MIME)).decode().split(","):
            if ident.startswith("cmp:"):                 # from the compound browser
                self.compoundDropped.emit(ident[4:], tid, start)
            elif ident.startswith("m"):
                self.mediaDropped.emit(ident, tid, start)
        e.acceptProposedAction()
        self.update()

    def clear_marks(self):
        if self.mark_in is not None or self.mark_out is not None:
            self.mark_in = self.mark_out = None
            self.marksChanged.emit()
            self.update()

    def contextMenuEvent(self, e):
        # menus from the mouse open on the right button's release (a right drag selects
        # time instead); the keyboard's menu key still opens one here
        if e.reason() == e.Reason.Mouse and e.pos().x() >= HEADER_W:
            return
        self._menu(e.pos(), e.globalPos())

    def _menu(self, pos, global_pos):
        if not self.proj:
            return
        row, c, _ = self._hit(QPointF(pos))
        if row is None:
            return
        menu = QMenu(self)
        if pos.x() < HEADER_W:
            tr = self.rows[row]
            tid = tr["id"]
            items = [("重新命名軌道…", "rename"), ("軌道顏色…", "color"), ("預設顏色", "nocolor"), None]
            if tr["kind"] == "audio" or any(c["type"] in ("video", "compound") for c in tr["clips"]):
                items += [("軌道音量…", "gain")]
            items += [("上移", "up"), ("下移", "down"), None,
                      ("新增影片軌道", "add:video"), ("新增文字軌道", "add:text"), ("新增音訊軌道", "add:audio"),
                      None, ("刪除軌道", "delete")]
            for it in items:
                if it is None:
                    menu.addSeparator()
                else:
                    menu.addAction(it[0], lambda a=it[1]: self.trackAction.emit(a, tid))
        elif c is not None:
            if c["id"] not in self.selected_ids:
                self.select(c)
            items = [("複製", "copy"), ("剪下", "cut"), ("貼上到播放頭", "paste"), ("建立副本", "duplicate"), None,
                     ("重新命名…", "rename"), ("顏色…", "color"), ("預設顏色", "nocolor"), None,
                     ("在播放頭分割", "split"), ("刪除", "delete")]
            if c["type"] == "compound":
                items = [("編輯複合片段", "enter"), ("設為獨立（不再共用）", "unique"), None] + items
            if c["type"] == "video":
                items = [("分離音訊", "detach_audio"), None] + items
            for it in items:
                if it is None:
                    menu.addSeparator()
                else:
                    menu.addAction(it[0], lambda a=it[1]: self.clipAction.emit(a, c["id"]))
        else:                                          # a free spot on a track
            menu.addAction("貼上到播放頭", lambda: self.clipAction.emit("paste", ""))
        menu.exec(global_pos)

    def mouseDoubleClickEvent(self, e):
        if not self.proj:
            return
        row, c, _ = self._hit(e.position())
        if row is None:
            return
        if e.position().x() < HEADER_W:
            edge = self._edge_at(e.position())
            if edge is not None:                       # double-click the edge: default height
                self.heights.pop(self.rows[edge]["id"], None)
                self._layout()
                self._waves.clear()
                self.update()
                return
            if not any(r.contains(e.position()) for _, r in self.header_buttons(row)):
                self.trackAction.emit("rename", self.rows[row]["id"])
        elif c is not None and c["type"] == "compound":
            self.clipAction.emit("enter", c["id"])

    def wheelEvent(self, e):
        if not self.proj:
            return
        dy, dx = e.angleDelta().y(), e.angleDelta().x()
        d = dy or dx                                     # Alt / Shift may turn the wheel sideways
        mods = e.modifiers()
        if mods & Qt.AltModifier:                        # track height
            self.set_vzoom(self.vzoom * (1.15 if d > 0 else 1 / 1.15))
        elif mods & Qt.ControlModifier:                  # zoom time around the mouse
            anchor = self._sec(e.position().x())
            self.px_per_s = min(2000.0, max(1.0, self.px_per_s * (1.25 if d > 0 else 0.8)))
            self.scroll_s = max(0.0, anchor - (e.position().x() - HEADER_W) / self.px_per_s)
        elif mods & Qt.ShiftModifier or (dx and not dy):  # left / right (also touchpad sideways)
            self.scroll_s = max(0.0, self.scroll_s - d / 120 * 80 / self.px_per_s)
        else:                                            # up / down
            self.vbar.setValue(self.scroll_y - round(d / 120 * 40))
            return
        self._waves.clear()
        self.update()
