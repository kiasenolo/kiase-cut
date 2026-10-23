"""Timeline view: tracks with clips, a ruler and the playhead.

Layout follows Jianying: the topmost layer is drawn at the top, audio tracks at the bottom.
Click empty space or the ruler to seek, click a clip to select it, Ctrl+wheel zooms,
wheel scrolls horizontally.
"""
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

US = 1_000_000
COLORS = {"video": "#2a7f8f", "image": "#2a7f8f", "compound": "#6b4fa3",
          "text": "#a8742a", "audio": "#3d7f45"}
RULER_H, TRACK_H, HEADER_W = 26, 34, 70


def timecode(us, fps):
    s = us / US
    return f"{int(s // 60):02d}:{int(s % 60):02d}.{int(round((s % 1) * fps)) % int(fps):02d}"


class Timeline(QWidget):
    seekRequested = Signal(int)          # frame
    clipSelected = Signal(object)        # clip dict or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proj = None
        self.fps = 60.0
        self.pos = 0
        self.px_per_s = 40.0
        self.scroll_s = 0.0
        self.selected = None
        self.rows = []
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)

    def set_project(self, proj):
        self.proj = proj
        self.fps = proj["fps"]
        visual = [t for t in proj["tracks"] if t["kind"] != "audio"]
        audio = [t for t in proj["tracks"] if t["kind"] == "audio"]
        self.rows = list(reversed(visual)) + audio
        self.selected = None
        dur = max(proj["duration_us"] / US, 1)
        self.px_per_s = max(2.0, (self.width() - HEADER_W - 20) / dur)
        self.scroll_s = 0
        self.setMinimumHeight(RULER_H + TRACK_H * len(self.rows) + 8)
        self.update()

    def set_position(self, frame):
        self.pos = frame
        x = self._x(frame / self.fps)
        if x > self.width() - 30 or x < HEADER_W:         # keep the playhead in view
            self.scroll_s = max(0.0, frame / self.fps - (self.width() - HEADER_W) * 0.2 / self.px_per_s)
        self.update()

    def _x(self, sec):
        return HEADER_W + (sec - self.scroll_s) * self.px_per_s

    def _sec(self, x):
        return (x - HEADER_W) / self.px_per_s + self.scroll_s

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#18181b"))
        if not self.proj:
            p.setPen(QColor("#777"))
            p.drawText(self.rect(), Qt.AlignCenter, "File > Import Jianying draft…")
            return
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        # ruler
        p.fillRect(0, 0, w, RULER_H, QColor("#202024"))
        step = next(s for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300) if s * self.px_per_s >= 70)
        p.setPen(QColor("#8a8a90"))
        p.setFont(QFont("Segoe UI", 8))
        t = (int(self.scroll_s / step)) * step
        while self._x(t) < w:
            x = self._x(t)
            if x >= HEADER_W:
                p.drawLine(int(x), RULER_H - 6, int(x), RULER_H)
                p.drawText(int(x) + 3, RULER_H - 9, timecode(t * US, self.fps)[:5])
            t += step
        # tracks
        for i, tr in enumerate(self.rows):
            y = RULER_H + i * TRACK_H
            p.fillRect(0, y, w, TRACK_H - 2, QColor("#1f1f23"))
            p.setPen(QColor("#9a9aa0"))
            p.drawText(QRectF(6, y, HEADER_W - 8, TRACK_H - 2), Qt.AlignVCenter, tr["kind"])
            for c in tr["clips"]:
                x0 = self._x(c["start_us"] / US)
                x1 = self._x((c["start_us"] + c["duration_us"]) / US)
                if x1 < HEADER_W or x0 > w:
                    continue
                r = QRectF(max(x0, HEADER_W) + 0.5, y + 3, max(1.0, x1 - max(x0, HEADER_W) - 1), TRACK_H - 8)
                col = QColor(COLORS.get(c["type"], "#555"))
                if c is self.selected:
                    col = col.lighter(150)
                p.setPen(QPen(QColor("#ffffff") if c is self.selected else col.darker(140), 1))
                p.setBrush(col)
                p.drawRoundedRect(r, 3, 3)
                if r.width() > 24:
                    p.setPen(QColor("#f2f2f2"))
                    label = (c.get("text") or {}).get("content") or c.get("name") or c["type"]
                    p.drawText(r.adjusted(4, 0, -2, 0), Qt.AlignVCenter, label.replace("\n", " "))
        # playhead
        x = self._x(self.pos / self.fps)
        if x >= HEADER_W:
            p.setPen(QPen(QColor("#ff4d4f"), 2))
            p.drawLine(int(x), 0, int(x), self.height())

    def _clip_at(self, pos):
        row = int((pos.y() - RULER_H) // TRACK_H)
        if pos.y() < RULER_H or not (0 <= row < len(self.rows)):
            return None
        sec = self._sec(pos.x())
        for c in self.rows[row]["clips"]:
            if c["start_us"] / US <= sec < (c["start_us"] + c["duration_us"]) / US:
                return c
        return None

    def mousePressEvent(self, e):
        if not self.proj or e.position().x() < HEADER_W:
            return
        c = self._clip_at(e.position())
        if c is not None:
            self.selected = c
            self.clipSelected.emit(c)
        self.seekRequested.emit(max(0, round(self._sec(e.position().x()) * self.fps)))
        self.update()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton and self.proj:
            self.seekRequested.emit(max(0, round(self._sec(e.position().x()) * self.fps)))

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
