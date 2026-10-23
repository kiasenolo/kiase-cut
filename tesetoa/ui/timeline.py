"""Timeline view and its mouse editing.

Layout follows Jianying: the topmost layer is drawn at the top, audio tracks at the bottom.
Click to seek or select. Drag a clip to move it (also to another track of the same kind),
drag its edges to trim. Moves and trims snap to the playhead and to other clips' edges.
The drag is only drawn while it happens; the edit is requested when the mouse is released.
Ctrl+wheel zooms, wheel scrolls. Dragging a picture clip above the top row, or a sound clip
below the bottom row, puts it on a new track.

Audio and video clips show their waveform (scaled by the clip volume and fades). Track
headers have mute / solo buttons (sound) and a hide button (pictures).
"""
import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QMenu, QWidget

from .. import curves, edit, project, waveform

US = 1_000_000
MEDIA_MIME = "application/x-tesetoa-media"
COLORS = {"video": "#2a7f8f", "image": "#2a7f8f", "compound": "#6b4fa3",
          "text": "#a8742a", "audio": "#3d7f45"}
RULER_H, TRACK_H, AUDIO_H, HEADER_W = 26, 34, 52, 140
BTN = 18                                             # header button size
EDGE_PX, SNAP_PX, DRAG_PX = 6, 8, 3


def timecode(us, fps):
    s = us / US
    return f"{int(s // 60):02d}:{int(s % 60):02d}.{int(round((s % 1) * fps)) % int(fps):02d}"


class Timeline(QWidget):
    seekRequested = Signal(int)                      # frame
    clipSelected = Signal(object)                    # clip dict or None
    moveRequested = Signal(str, int, str)            # clip id, start us, track id
    trimRequested = Signal(str, str, int)            # clip id, "start" | "end", time us
    trackAction = Signal(str, str)                   # action, track id
    clipAction = Signal(str, str)                    # action, clip id
    mediaDropped = Signal(str, str, int)             # library item id, track id or "", start us
    newTrackRequested = Signal(str, int, bool)       # clip id, start us, on top (else bottom)
    peaksReady = Signal(str)                         # emitted from the waveform thread

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proj = None
        self.fps = 60.0
        self.pos = 0
        self.px_per_s = 40.0
        self.scroll_s = 0.0
        self.selected_id = None
        self.rows = []
        self.drag = None
        self.mark_in = self.mark_out = None        # export range, frames
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setAcceptDrops(True)
        self.drop_at = None                        # (row, us) while library media hovers
        self.tops = []                             # y of each row
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
        self.tops, y = [], RULER_H
        for t in self.rows:
            self.tops.append(y)
            y += AUDIO_H if t["kind"] == "audio" else TRACK_H
        self.rows_end = y
        self._waves.clear()
        self.drag = None
        if not keep_view:
            self.selected_id = None
            dur = max(proj["duration_us"] / US, 1)
            self.px_per_s = max(2.0, (self.width() - HEADER_W - 20) / dur)
            self.scroll_s = 0
        self.setMinimumHeight(self.rows_end + 30)          # room to drop onto a new track
        self.update()

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

    def set_position(self, frame):
        self.pos = frame
        x = self._x(frame / self.fps)
        if x > self.width() - 30 or x < HEADER_W:         # keep the playhead in view
            self.scroll_s = max(0.0, frame / self.fps - (self.width() - HEADER_W) * 0.2 / self.px_per_s)
        self.update()

    # -- geometry -------------------------------------------------------------------------------
    def _x(self, sec):
        return HEADER_W + (sec - self.scroll_s) * self.px_per_s

    def _sec(self, x):
        return (x - HEADER_W) / self.px_per_s + self.scroll_s

    def row_h(self, i):
        return AUDIO_H if self.rows[i]["kind"] == "audio" else TRACK_H

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
        """Snap a time to the playhead / 0 / clip edges within SNAP_PX."""
        best, limit = t_us, SNAP_PX / self.px_per_s * US
        cands = [0, self.pos / self.fps * US]
        for tr in self.rows:
            for c in tr["clips"]:
                if c is not exclude:
                    cands += [c["start_us"], c["start_us"] + c["duration_us"]]
        for t in cands:
            if abs(t - t_us) < limit:
                best, limit = t, abs(t - t_us)
        return best

    # -- painting -------------------------------------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#18181b"))
        if not self.proj:
            p.setPen(QColor("#777"))
            p.drawText(self.rect(), Qt.AlignCenter, "檔案 > 匯入剪映草稿")
            return
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        p.fillRect(0, 0, w, RULER_H, QColor("#202024"))
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
            p.fillRect(QRectF(a, 0, b - a, RULER_H), QColor(47, 214, 200, 70))
            p.fillRect(QRectF(a, self.height() - 3, b - a, 3), QColor(47, 214, 200, 160))
            p.setPen(QPen(QColor("#2fd6c8"), 2))
            if self.mark_in is not None and a > HEADER_W:
                p.drawLine(int(a), 0, int(a), RULER_H)
            if self.mark_out is not None and b > HEADER_W:
                p.drawLine(int(b), 0, int(b), RULER_H)
        dragged = self.drag["clip"] if self.drag and self.drag["moved"] else None
        tracks = self.proj["tracks"]
        for i, tr in enumerate(self.rows):
            y, h = self.tops[i], self.row_h(i)
            p.fillRect(0, y, w, h - 2, QColor("#1f1f23"))
            if tr.get("color"):
                p.fillRect(0, y, 4, h - 2, QColor(tr["color"]))
            btns = self.header_buttons(i)
            name_w = (btns[0][1].left() if btns else HEADER_W) - 14
            p.setPen(QColor("#c8c8cc"))
            name = p.fontMetrics().elidedText(tr.get("name") or tr["kind"], Qt.ElideRight, int(name_w))
            gain = tr.get("gain", 1.0)
            if abs(gain - 1.0) > 1e-6:
                p.drawText(QRectF(10, y + 6, name_w, 16), Qt.AlignVCenter, name)
                p.setPen(QColor("#8a8a90"))
                db = "-∞" if gain <= 0 else f"{20 * math.log10(gain):+.1f}"
                p.drawText(QRectF(10, y + 22, name_w, 16), Qt.AlignVCenter, f"{db} dB")
            else:
                p.drawText(QRectF(10, y, name_w, h - 2), Qt.AlignVCenter, name)
            for flag, r in btns:
                self._draw_button(p, flag, r, bool(tr.get(flag)))
            dim = (project.sounds(tr, tracks) <= 0) if tr["kind"] == "audio" else not project.visible(tr)
            for c in tr["clips"]:
                if c is not dragged:
                    self._draw_clip(p, c, y, c["start_us"], c["duration_us"], track=tr, h=h, dim=dim)
        if dragged:
            d = self.drag
            h = self.row_h(d["row"])
            if d.get("new") == "top":                   # landing on a new top track
                p.fillRect(QRectF(HEADER_W, RULER_H - 3, w - HEADER_W, 3), QColor("#2fd6c8"))
                y = RULER_H - h + 2
            elif d.get("new") == "bottom":              # landing on a new last audio track
                p.fillRect(QRectF(HEADER_W, self.rows_end, w - HEADER_W, 3), QColor("#2fd6c8"))
                y = self.rows_end + 2
            else:
                y = self.tops[d["row"]]
            self._draw_clip(p, dragged, y, d["start"], d["end"] - d["start"], ghost=True,
                            track=self.rows[d["row"]], h=h)
        if self.drop_at is not None:
            row, t = self.drop_at
            dx = self._x(t / US)
            p.setPen(QPen(QColor("#2fd6c8"), 2, Qt.DashLine))
            p.drawLine(int(dx), RULER_H, int(dx), self.height())
            if row is not None:
                p.fillRect(QRectF(HEADER_W, self.tops[row], w - HEADER_W, self.row_h(row) - 2),
                           QColor(47, 214, 200, 30))
        x = self._x(self.pos / self.fps)
        if x >= HEADER_W:
            p.setPen(QPen(QColor("#ff4d4f"), 2))
            p.drawLine(int(x), 0, int(x), self.height())

    @staticmethod
    def clip_label(c):
        if c.get("named") or not c.get("text"):
            return c.get("name") or c["type"]
        return c["text"]["content"]

    @staticmethod
    def _draw_button(p, flag, r, on):
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor({"muted": "#c0453f", "solo": "#d0a020", "hidden": "#c0453f"}[flag]) if on
                   else QColor("#2c2c31"))
        p.drawRoundedRect(r, 3, 3)
        ink = QColor("#ffffff") if on else QColor("#a0a0a6")
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
        col = QColor(c.get("color") or (track or {}).get("color") or COLORS.get(c["type"], "#555"))
        sel = c["id"] == self.selected_id
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
            poly = self._wave(c, start, wx0, wx1, wt, wh)
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
                label = "▣ " + label
            lr = r.adjusted(4, 0, -2, 0)
            if audio:
                lr.setHeight(16)
            elif c["type"] == "video":
                lr.setBottom(r.bottom() - 9)
            p.drawText(lr, Qt.AlignVCenter, label)
        if sel and not ghost:
            # keyframes of the selected clip, as small diamonds along its bottom edge
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#ffb020"))
            for k in edit.key_times(c):
                kx = self._x((start + k) / US)
                if HEADER_W <= kx <= w:
                    ky = r.bottom() - 4
                    p.drawPolygon([QPointF(kx, ky - 4), QPointF(kx + 4, ky), QPointF(kx, ky + 4), QPointF(kx - 4, ky)])

    # -- mouse ----------------------------------------------------------------------------------
    def mousePressEvent(self, e):
        if not self.proj or e.button() != Qt.LeftButton:
            return
        if e.position().x() < HEADER_W:
            row = self._row_at(e.position().y())
            if row is not None:
                for flag, r in self.header_buttons(row):
                    if r.contains(e.position()):
                        self.trackAction.emit("toggle:" + flag, self.rows[row]["id"])
            return
        row, c, zone = self._hit(e.position())
        if c is None:
            self.select(None)
            self.seekRequested.emit(max(0, round(self._sec(e.position().x()) * self.fps)))
            self.drag = {"clip": None, "mode": "seek", "moved": False}
            return
        self.select(c)
        self.drag = {"clip": c, "mode": zone, "x0": e.position().x(), "row0": row, "row": row,
                     "start": c["start_us"], "end": c["start_us"] + c["duration_us"], "moved": False}

    def mouseMoveEvent(self, e):
        pos = e.position()
        d = self.drag
        if d is None:
            _, c, zone = self._hit(pos) if self.proj else (None, None, None)
            self.setCursor(Qt.SizeHorCursor if zone in ("start", "end") else Qt.ArrowCursor)
            return
        if d["mode"] == "seek":
            self.seekRequested.emit(max(0, round(self._sec(pos.x()) * self.fps)))
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
        self.update()

    def mouseReleaseEvent(self, e):
        d, self.drag = self.drag, None
        if not d or d["mode"] == "seek":
            return
        c = d["clip"]
        if not d["moved"]:
            self.seekRequested.emit(max(0, round(self._sec(e.position().x()) * self.fps)))
            self.update()
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
    def dragEnterEvent(self, e):
        if self.proj and e.mimeData().hasFormat(MEDIA_MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if not (self.proj and e.mimeData().hasFormat(MEDIA_MIME)):
            return
        pos = e.position()
        self.drop_at = (self._row_at(pos.y()), max(0.0, self._sec(pos.x())) * US)
        e.acceptProposedAction()
        self.update()

    def dragLeaveEvent(self, e):
        self.drop_at = None
        self.update()

    def dropEvent(self, e):
        self.drop_at = None
        pos = e.position()
        row = self._row_at(pos.y())
        tid = self.rows[row]["id"] if row is not None else ""
        start = int(max(0.0, self._sec(pos.x())) * US)
        for ident in bytes(e.mimeData().data(MEDIA_MIME)).decode().split(","):
            if ident.startswith("m"):
                self.mediaDropped.emit(ident, tid, start)
        e.acceptProposedAction()
        self.update()

    def contextMenuEvent(self, e):
        if not self.proj:
            return
        row, c, _ = self._hit(e.pos())
        if row is None:
            return
        menu = QMenu(self)
        if e.pos().x() < HEADER_W:
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
            self.select(c)
            items = [("重新命名…", "rename"), ("顏色…", "color"), ("預設顏色", "nocolor"), None,
                     ("在播放頭分割", "split"), ("刪除", "delete")]
            if c["type"] == "compound":
                items = [("編輯複合片段", "enter"), None] + items
            if c["type"] == "video":
                items = [("分離音訊", "detach_audio"), None] + items
            for it in items:
                if it is None:
                    menu.addSeparator()
                else:
                    menu.addAction(it[0], lambda a=it[1]: self.clipAction.emit(a, c["id"]))
        else:
            return
        menu.exec(e.globalPos())

    def mouseDoubleClickEvent(self, e):
        if not self.proj:
            return
        row, c, _ = self._hit(e.position())
        if row is None:
            return
        if e.position().x() < HEADER_W:
            if not any(r.contains(e.position()) for _, r in self.header_buttons(row)):
                self.trackAction.emit("rename", self.rows[row]["id"])
        elif c is not None and c["type"] == "compound":
            self.clipAction.emit("enter", c["id"])

    def wheelEvent(self, e):
        if not self.proj:
            return
        d = e.angleDelta().y() or e.angleDelta().x()
        if e.modifiers() & Qt.ControlModifier:
            anchor = self._sec(e.position().x())
            self.px_per_s = min(2000.0, max(1.0, self.px_per_s * (1.25 if d > 0 else 0.8)))
            self.scroll_s = max(0.0, anchor - (e.position().x() - HEADER_W) / self.px_per_s)
        else:
            self.scroll_s = max(0.0, self.scroll_s - d / 120 * 80 / self.px_per_s)
        self.update()
