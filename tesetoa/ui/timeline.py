"""Timeline view and its mouse editing.

Layout follows Jianying: the topmost layer is drawn at the top, audio tracks at the bottom.
Click to seek or select. Drag a clip to move it (also to another track of the same kind),
drag its edges to trim. Moves and trims snap to the playhead and to other clips' edges.
The drag is only drawn while it happens; the edit is requested when the mouse is released.
Ctrl+wheel zooms, wheel scrolls.
"""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .. import edit

US = 1_000_000
COLORS = {"video": "#2a7f8f", "image": "#2a7f8f", "compound": "#6b4fa3",
          "text": "#a8742a", "audio": "#3d7f45"}
RULER_H, TRACK_H, HEADER_W = 26, 34, 70
EDGE_PX, SNAP_PX, DRAG_PX = 6, 8, 3


def timecode(us, fps):
    s = us / US
    return f"{int(s // 60):02d}:{int(s % 60):02d}.{int(round((s % 1) * fps)) % int(fps):02d}"


class Timeline(QWidget):
    seekRequested = Signal(int)                      # frame
    clipSelected = Signal(object)                    # clip dict or None
    moveRequested = Signal(str, int, str)            # clip id, start us, track id
    trimRequested = Signal(str, str, int)            # clip id, "start" | "end", time us

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
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)

    # -- data -----------------------------------------------------------------------------------
    def set_project(self, proj, keep_view=False):
        self.proj = proj
        self.fps = proj["fps"]
        visual = [t for t in proj["tracks"] if t["kind"] != "audio"]
        audio = [t for t in proj["tracks"] if t["kind"] == "audio"]
        self.rows = list(reversed(visual)) + audio
        self.drag = None
        if not keep_view:
            self.selected_id = None
            dur = max(proj["duration_us"] / US, 1)
            self.px_per_s = max(2.0, (self.width() - HEADER_W - 20) / dur)
            self.scroll_s = 0
        self.setMinimumHeight(RULER_H + TRACK_H * len(self.rows) + 8)
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

    def _row_at(self, y):
        row = int((y - RULER_H) // TRACK_H)
        return row if y >= RULER_H and 0 <= row < len(self.rows) else None

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
        dragged = self.drag["clip"] if self.drag and self.drag["moved"] else None
        for i, tr in enumerate(self.rows):
            y = RULER_H + i * TRACK_H
            p.fillRect(0, y, w, TRACK_H - 2, QColor("#1f1f23"))
            p.setPen(QColor("#9a9aa0"))
            p.drawText(QRectF(6, y, HEADER_W - 8, TRACK_H - 2), Qt.AlignVCenter, tr["kind"])
            for c in tr["clips"]:
                if c is not dragged:
                    self._draw_clip(p, c, y, c["start_us"], c["duration_us"])
        if dragged:
            d = self.drag
            y = RULER_H + d["row"] * TRACK_H
            self._draw_clip(p, dragged, y, d["start"], d["end"] - d["start"], ghost=True)
        x = self._x(self.pos / self.fps)
        if x >= HEADER_W:
            p.setPen(QPen(QColor("#ff4d4f"), 2))
            p.drawLine(int(x), 0, int(x), self.height())

    def _draw_clip(self, p, c, y, start, dur, ghost=False):
        w = self.width()
        x0, x1 = self._x(start / US), self._x((start + dur) / US)
        if x1 < HEADER_W or x0 > w:
            return
        r = QRectF(max(x0, HEADER_W) + 0.5, y + 3, max(1.0, x1 - max(x0, HEADER_W) - 1), TRACK_H - 8)
        col = QColor(COLORS.get(c["type"], "#555"))
        sel = c["id"] == self.selected_id
        if sel:
            col = col.lighter(150)
        if ghost:
            col.setAlpha(190)
        p.setPen(QPen(QColor("#ffffff") if sel else col.darker(140), 1))
        p.setBrush(col)
        p.drawRoundedRect(r, 3, 3)
        if r.width() > 24:
            p.setPen(QColor("#f2f2f2"))
            label = (c.get("text") or {}).get("content") or c.get("name") or c["type"]
            p.drawText(r.adjusted(4, 0, -2, 0), Qt.AlignVCenter, label.replace("\n", " "))
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
        if not self.proj or e.button() != Qt.LeftButton or e.position().x() < HEADER_W:
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
            if row is not None and (self.rows[row]["kind"] == "audio") == (self.rows[d["row0"]]["kind"] == "audio"):
                d["row"] = row
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
        if d["mode"] == "body":
            self.moveRequested.emit(c["id"], int(round(d["start"])), self.rows[d["row"]]["id"])
        elif d["mode"] == "start":
            self.trimRequested.emit(c["id"], "start", int(round(d["start"])))
        else:
            self.trimRequested.emit(c["id"], "end", int(round(d["end"])))
        self.update()

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
