"""Preview canvas: shows frames, lets clips be picked and dragged on the canvas.

While dragging, the clip's outline moves and snaps to the canvas centre lines and edges
and to other visible clips' centres and edges (guides are drawn); the move is committed
on release. A fullscreen window shows the same frames.
"""
import json
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from .. import curves, textlayout

US = 1_000_000
SNAP_PX = 7
_text_sizes = {}


def text_size(spec, canvas_h):
    """Text box (w, h) in canvas px at scale 1."""
    key = json.dumps([spec, canvas_h], sort_keys=True, default=str)
    if key not in _text_sizes:
        im = textlayout.render(spec, 1.0, canvas_h)
        _text_sizes[key] = (im.width, im.height)
    return _text_sizes[key]


def base_size(c, W, H, t):
    """On-canvas size of clip c at scale 1."""
    if c["type"] == "text":
        spec = curves.static(c["text"], t, ("size", "color", "letter_spacing", "line_spacing", "italic_deg"))
        return text_size(spec, H)
    if c["type"] == "compound":
        w, h = c["compound"]["width"], c["compound"]["height"]
    else:
        w, h = (c.get("media") or {}).get("width") or W, (c.get("media") or {}).get("height") or H
    k = min(W / w, H / h)
    return w * k, h * k


class Box:
    """A clip's outline on the canvas at one time (canvas px, y down)."""

    def __init__(self, c, W, H, t):
        tf = c.get("transform") or {}
        v = lambda k, d: curves.value(tf.get(k, d), t)
        bw, bh = base_size(c, W, H, t)
        s = v("scale", 1.0)
        self.clip = c
        self.cx = W / 2 + v("x", 0.0) * W / 2
        self.cy = H / 2 - v("y", 0.0) * H / 2
        self.w, self.h = bw * s, bh * s
        self.rot = math.radians(v("rotation", 0.0))

    def corners(self, dx=0.0, dy=0.0):
        c, s = math.cos(self.rot), math.sin(self.rot)
        out = []
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            x, y = sx * self.w / 2, sy * self.h / 2
            out.append(QPointF(self.cx + dx + x * c - y * s, self.cy + dy + x * s + y * c))
        return out

    def contains(self, x, y):
        c, s = math.cos(-self.rot), math.sin(-self.rot)
        lx, ly = (x - self.cx) * c - (y - self.cy) * s, (x - self.cx) * s + (y - self.cy) * c
        return abs(lx) <= self.w / 2 and abs(ly) <= self.h / 2

    def extents(self):
        """Axis-aligned (left, right, top, bottom) of the rotated outline."""
        pts = self.corners()
        xs, ys = [p.x() for p in pts], [p.y() for p in pts]
        return min(xs), max(xs), min(ys), max(ys)


class Preview(QWidget):
    clipPicked = Signal(object)                 # clip dict
    moveCommitted = Signal(str, float, float)   # clip id, x, y (Jianying units)
    doubleClicked = Signal()

    def __init__(self, parent=None, interactive=True):
        super().__init__(parent)
        self.img = None
        self.W, self.H = 1920, 1080
        self.view = None
        self.t_us = 0
        self.selected_id = None
        self.interactive = interactive
        self.drag = None
        self.guides = []
        self.setMinimumSize(320, 180)
        self.setMouseTracking(True)

    # -- state ------------------------------------------------------------------------------------
    def show_image(self, img):
        self.img = img
        self.update()

    def set_scene(self, view, t_us, selected_id):
        self.view = view
        if view:
            self.W, self.H = view["width"], view["height"]
        self.t_us = t_us
        self.selected_id = selected_id
        if self.drag is None:
            self.update()

    def _rect(self):
        w, h = self.width(), self.height()
        a = self.W / self.H
        dw, dh = (h * a, h) if w / h > a else (w, w / a)
        return QRectF((w - dw) / 2, (h - dh) / 2, dw, dh)

    def _to_canvas(self, pos):
        r = self._rect()
        return (pos.x() - r.x()) / r.width() * self.W, (pos.y() - r.y()) / r.height() * self.H

    def visible_boxes(self):
        """Boxes of clips showing now, topmost first."""
        if not self.view:
            return []
        out = []
        for tr in reversed(self.view["tracks"]):
            if tr["kind"] == "audio":
                continue
            for c in tr["clips"]:
                if c["start_us"] <= self.t_us < c["start_us"] + c["duration_us"] and c.get("transform") is not None:
                    out.append(Box(c, self.W, self.H, self.t_us - c["start_us"]))
        return out

    # -- painting ---------------------------------------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#111114"))
        r = self._rect()
        p.fillRect(r, QColor("black"))
        if self.img is not None:
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(r, self.img)
        if not self.interactive:
            return
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(r.x(), r.y())
        p.scale(r.width() / self.W, r.height() / self.H)
        k = self.W / r.width()                         # canvas px per screen px
        box = next((b for b in self.visible_boxes() if b.clip["id"] == self.selected_id), None)
        if box is not None:
            dx, dy = (self.drag["dx"], self.drag["dy"]) if self.drag else (0.0, 0.0)
            p.setPen(QPen(QColor("#ffffff"), 2 * k))
            p.setBrush(Qt.NoBrush)
            p.drawPolygon(QPolygonF(box.corners(dx, dy)))
            p.setPen(QPen(QColor("#2fd6c8"), 1 * k))
            p.drawPolygon(QPolygonF(box.corners(dx, dy)))
        if self.drag:
            p.setPen(QPen(QColor("#2fd6c8"), 1.5 * k, Qt.DashLine))
            for axis, v in self.guides:
                if axis == "x":
                    p.drawLine(QPointF(v, 0), QPointF(v, self.H))
                else:
                    p.drawLine(QPointF(0, v), QPointF(self.W, v))

    # -- mouse ------------------------------------------------------------------------------------
    def mousePressEvent(self, e):
        if not self.interactive or e.button() != Qt.LeftButton or not self.view:
            return
        x, y = self._to_canvas(e.position())
        boxes = self.visible_boxes()
        sel = next((b for b in boxes if b.clip["id"] == self.selected_id and b.contains(x, y)), None)
        hit = sel or next((b for b in boxes if b.contains(x, y)), None)
        if hit is None:
            return
        if hit.clip["id"] != self.selected_id:
            self.selected_id = hit.clip["id"]
            self.clipPicked.emit(hit.clip)
        others = [b for b in boxes if b is not hit]
        self.drag = {"box": hit, "x0": x, "y0": y, "dx": 0.0, "dy": 0.0, "moved": False, "others": others}
        self.update()

    def _snap(self, box, dx, dy, others, tol):
        """Snap the moved box's centre / edges to the canvas and to other clips."""
        l, r, t, b = box.extents()
        xs = [(box.cx + dx, 0), (l + dx, 0), (r + dx, 0)]
        ys = [(box.cy + dy, 0), (t + dy, 0), (b + dy, 0)]
        tx = [self.W / 2, 0, self.W]
        ty = [self.H / 2, 0, self.H]
        for o in others:
            ol, orr, ot, ob = o.extents()
            tx += [o.cx, ol, orr]
            ty += [o.cy, ot, ob]
        guides = []

        def best(cands, targets):
            hit = None
            for v, _ in cands:
                for g in targets:
                    if abs(v - g) < tol and (hit is None or abs(v - g) < abs(hit[0])):
                        hit = (g - v, g)
            return hit

        sx, sy = best(xs, tx), best(ys, ty)
        if sx:
            dx += sx[0]
            guides.append(("x", sx[1]))
        if sy:
            dy += sy[0]
            guides.append(("y", sy[1]))
        return dx, dy, guides

    def mouseMoveEvent(self, e):
        d = self.drag
        if d is None:
            return
        x, y = self._to_canvas(e.position())
        dx, dy = x - d["x0"], y - d["y0"]
        if not d["moved"] and math.hypot(dx, dy) < 3 * self.W / self._rect().width():
            return
        d["moved"] = True
        tol = SNAP_PX * self.W / self._rect().width()
        if e.modifiers() & Qt.AltModifier:          # Alt: move freely
            self.guides = []
        else:
            dx, dy, self.guides = self._snap(d["box"], dx, dy, d["others"], tol)
        d["dx"], d["dy"] = dx, dy
        self.update()

    def mouseReleaseEvent(self, e):
        d, self.drag = self.drag, None
        self.guides = []
        if d and d["moved"]:
            b = d["box"]
            x = (b.cx + d["dx"] - self.W / 2) / (self.W / 2)
            y = (self.H / 2 - (b.cy + d["dy"])) / (self.H / 2)
            self.moveCommitted.emit(b.clip["id"], x, y)
        self.update()

    def mouseDoubleClickEvent(self, e):
        self.doubleClicked.emit()


class FullscreenPreview(QWidget):
    """Frameless fullscreen copy of the preview. Esc / double-click closes, Space plays."""
    closed = Signal()
    togglePlay = Signal()
    step = Signal(int)

    def __init__(self):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.setStyleSheet("background: black;")
        self.canvas = Preview(self, interactive=False)
        self.canvas.doubleClicked.connect(self.close)

    def resizeEvent(self, e):
        self.canvas.setGeometry(self.rect())

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Escape, Qt.Key_F):
            self.close()
        elif k == Qt.Key_Space:
            self.togglePlay.emit()
        elif k in (Qt.Key_Left, Qt.Key_Right):
            self.step.emit(-1 if k == Qt.Key_Left else 1)

    def closeEvent(self, e):
        self.closed.emit()
        super().closeEvent(e)
