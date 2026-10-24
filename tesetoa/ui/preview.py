"""Preview canvas: shows frames and edits the selected clip with handles on the canvas.

Transform: drag the clip to move it (it snaps to the canvas centre lines and edges and to
other visible clips' centres and edges; Alt moves freely), drag a corner square to scale
it about its centre, drag the round handle above it to rotate (Shift: 15° steps; it also
settles on 0 / 90 / 180 / 270).

Mask mode (`mask_mode`, while the 遮罩 tab is open) edits only masks: the clip itself
cannot be moved, scaled or turned there, and a click on another clip just selects it. The
mask outline is drawn where it cuts the clip (dimmed while the mask is switched off). Drag inside it to move it, the squares on its edges / corner to size it, the
round handle to rotate it and the arrow below it for the feather.

Ctrl+wheel zooms the view around the mouse (to reach handles of clips larger than the
canvas), the middle button drags it; zooming back to about 100% fits it again.

Every drag shows live (paramsLive) and becomes one edit on release (paramsCommitted), in
the project's units: transform x / y in half-canvas units (y up), scale, clockwise degrees;
mask cx / cy in half-material units (y up), w / h as fractions of the material, feather.
A fullscreen window shows the same frames.
"""
import json
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import QWidget

from .. import curves, textlayout

US = 1_000_000
SNAP_PX = 7
HANDLE_PX = 9                 # handle size on screen
ROT_PX = 34                   # rotation handle distance from the outline
PICK_PX = 9
ANGLE_SNAP = 3.0              # degrees within which rotation settles on a right angle
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
        self.bw, self.bh = base_size(c, W, H, t)
        self.s = v("scale", 1.0)
        self.sy = curves.value(tf.get("scale_y", tf.get("scale", 1.0)), t)
        self.clip = c
        self.t = t
        self.W, self.H = W, H
        self.cx = W / 2 + v("x", 0.0) * W / 2
        self.cy = H / 2 - v("y", 0.0) * H / 2
        self.w, self.h = self.bw * abs(self.s), self.bh * abs(self.sy)
        self.deg = v("rotation", 0.0)
        self.rot = math.radians(self.deg)
        self.flip = (-1 if tf.get("flip_h") else 1, -1 if tf.get("flip_v") else 1)

    def xf(self, dx=0.0, dy=0.0):
        """Clip-local (centre origin, unscaled, y down) -> canvas, as the renderer draws."""
        return QTransform().translate(self.cx + dx, self.cy + dy).rotate(self.deg) \
            .scale(self.s * self.flip[0], self.sy * self.flip[1])

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

    def rot_handle(self, k):
        """Canvas point of the rotation handle (above the top edge; k = canvas px per screen px)."""
        up = QPointF(math.sin(self.rot), -math.cos(self.rot))
        return QPointF(self.cx, self.cy) + up * (self.h / 2 + ROT_PX * k)


class MaskGeo:
    """A clip's mask at one time: its frame on the canvas and handle points."""

    def __init__(self, box):
        m = box.clip["mask"]
        t = box.t
        v = lambda k, d: curves.value(m.get(k, d), t)
        self.box, self.m = box, m
        self.kind = m["kind"]
        self.dw, self.dh = box.bw, box.bh                       # material size at scale 1
        self.cx, self.cy, self.rot = v("cx", 0.0), v("cy", 0.0), v("rotation", 0.0)
        self.mw, self.mh, self.feather = v("w", 1.0), v("h", 1.0), v("feather", 0.0)
        self.hw = 0.0 if self.kind in ("line", "mirror") else self.mw * self.dw / 2   # half size, clip px
        self.hh = 0.0 if self.kind == "line" else self.mh * self.dh / 2
        self.local = QTransform().translate(self.cx * self.dw / 2, -self.cy * self.dh / 2).rotate(self.rot)
        self.xf = self.local * box.xf()                         # mask frame -> canvas

    def centre(self):
        return self.xf.map(QPointF(0, 0))

    def outline(self):
        """Canvas path of the mask edge (lines reach across the clip)."""
        path = QPainterPath()
        reach = 2 * math.hypot(self.dw, self.dh)
        if self.kind == "line":
            path.moveTo(-reach, 0)
            path.lineTo(reach, 0)
        elif self.kind == "mirror":
            for y in (-self.hh, self.hh):
                path.moveTo(-reach, y)
                path.lineTo(reach, y)
        elif self.kind == "circle":
            path.addEllipse(QPointF(0, 0), self.hw, self.hh)
        else:
            path.addRect(QRectF(-self.hw, -self.hh, 2 * self.hw, 2 * self.hh))
        return self.xf.map(path)

    def down(self):
        """Unit vector of the mask's 'down' on the canvas, and its half height there."""
        c, d = self.centre(), self.xf.map(QPointF(0, 1))
        u = d - c
        n = math.hypot(u.x(), u.y()) or 1.0
        u /= n
        e = self.xf.map(QPointF(0, self.hh))
        return u, math.hypot(e.x() - c.x(), e.y() - c.y())

    def handles(self, k):
        """[(name, canvas point)]; k = canvas px per screen px."""
        out = []
        if self.kind in ("rectangle", "circle"):
            out += [("w", self.xf.map(QPointF(self.hw, 0))), ("h", self.xf.map(QPointF(0, -self.hh))),
                    ("wh", self.xf.map(QPointF(self.hw, -self.hh)))]
        elif self.kind == "mirror":
            out.append(("h", self.xf.map(QPointF(0, -self.hh))))
        u, hh = self.down()
        c = self.centre()
        out.append(("rot", c - u * (hh + ROT_PX * k)))
        out.append(("feather", c + u * (hh + (14 + self.feather * 80) * k)))
        return out

    def contains(self, p):
        inv, ok = self.xf.inverted()
        if not ok:
            return False
        q = inv.map(p)
        if self.kind == "line":
            return abs(q.y()) < 12 * self.box.W / 1920 / max(abs(self.box.s), 1e-3)
        if self.kind == "mirror":
            return abs(q.y()) <= self.hh
        if self.kind == "circle":
            return (q.x() / max(self.hw, 1e-6)) ** 2 + (q.y() / max(self.hh, 1e-6)) ** 2 <= 1
        return abs(q.x()) <= self.hw and abs(q.y()) <= self.hh


def snap_angle(deg, free):
    if free:
        return round(deg / 15) * 15
    r = round(deg / 90) * 90
    return r if abs(deg - r) <= ANGLE_SNAP else deg


class Preview(QWidget):
    clipPicked = Signal(object)                 # clip dict
    paramsLive = Signal(str, str, dict)         # clip id, group, {key: value} while dragging
    paramsCommitted = Signal(str, str, dict)    # the same on release
    doubleClicked = Signal()

    def __init__(self, parent=None, interactive=True):
        super().__init__(parent)
        self.img = None
        self.W, self.H = 1920, 1080
        self.view = None
        self.t_us = 0
        self.selected_id = None
        self.interactive = interactive
        self.mask_mode = False
        self.drag = None
        self.guides = []
        self.live = None                        # (group, values) shown while dragging
        self.zoom = 1.0                         # view zoom (1 = canvas fits the widget)
        self.pan = QPointF(0, 0)                # view offset, screen px
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

    def set_mask_mode(self, on):
        self.mask_mode = on
        self.update()

    def _rect(self):
        w, h = self.width(), self.height()
        a = self.W / self.H
        dw, dh = (h * a, h) if w / h > a else (w, w / a)
        dw, dh = dw * self.zoom, dh * self.zoom
        return QRectF((w - dw) / 2 + self.pan.x(), (h - dh) / 2 + self.pan.y(), dw, dh)

    def wheelEvent(self, e):
        if not self.interactive or not e.modifiers() & Qt.ControlModifier:
            return
        d = e.angleDelta().y() or e.angleDelta().x()
        r0 = self._rect()
        cx, cy = self._to_canvas(e.position())
        z = min(8.0, max(0.2, self.zoom * (1.2 if d > 0 else 1 / 1.2)))
        if abs(z - 1.0) < 0.09:                          # back to fitting the widget
            self.zoom, self.pan = 1.0, QPointF(0, 0)
        else:
            self.zoom = z
            r = self._rect()                             # keep the canvas point under the mouse
            self.pan += e.position() - QPointF(r.x() + cx / self.W * r.width(), r.y() + cy / self.H * r.height())
        self.update()
        e.accept()

    def _to_canvas(self, pos):
        r = self._rect()
        return (pos.x() - r.x()) / r.width() * self.W, (pos.y() - r.y()) / r.height() * self.H

    def _k(self):
        """Canvas px per screen px."""
        return self.W / max(1.0, self._rect().width())

    def visible_boxes(self):
        """Boxes of clips showing now, topmost first."""
        if not self.view:
            return []
        out = []
        for tr in reversed(self.view["tracks"]):
            if tr["kind"] == "audio" or tr.get("hidden"):
                continue
            for c in tr["clips"]:
                if c["start_us"] <= self.t_us < c["start_us"] + c["duration_us"] and c.get("transform") is not None:
                    out.append(Box(c, self.W, self.H, self.t_us - c["start_us"]))
        return out

    def selected_box(self):
        return next((b for b in self.visible_boxes() if b.clip["id"] == self.selected_id), None)

    def _live_box(self):
        """The selected clip's box with the values being dragged applied."""
        box = self.selected_box()
        if box is None or self.live is None:
            return box
        group, vals = self.live
        c = json.loads(json.dumps(box.clip))
        holder = c.setdefault(group, {}) if group != "clip" else c
        holder.update(vals)
        if group == "transform" and "scale" in vals and "scale_y" in holder:
            holder["scale_y"] = vals["scale"]
        return Box(c, self.W, self.H, box.t)

    def masking(self, box):
        return self.mask_mode and box is not None and box.clip.get("mask") and \
            box.clip["type"] in ("image", "video", "compound")

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
        if self.zoom != 1.0:
            p.setPen(QColor("#9a9aa0"))
            p.drawText(QRectF(8, 6, 200, 18), Qt.AlignLeft, f"{self.zoom * 100:.0f}%（Ctrl+滾輪）")
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(r.x(), r.y())
        p.scale(r.width() / self.W, r.height() / self.H)
        k = self._k()
        box = self._live_box()
        if box is not None:
            if self.masking(box):
                self._paint_mask(p, box, k)
            elif self.mask_mode:                         # no mask: just where the clip is
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(255, 255, 255, 120), 1 * k, Qt.DashLine))
                p.drawPolygon(QPolygonF(box.corners()))
            else:
                self._paint_transform(p, box, k)
        if self.guides:
            p.setPen(QPen(QColor("#e6e6e6"), 1.5 * k, Qt.DashLine))
            for axis, v in self.guides:
                if axis == "x":
                    p.drawLine(QPointF(v, 0), QPointF(v, self.H))
                else:
                    p.drawLine(QPointF(0, v), QPointF(self.W, v))

    def _handle(self, p, pt, k, round_=False, color="#ffffff"):
        s = HANDLE_PX * k
        p.setPen(QPen(QColor("#111114"), 1 * k))
        p.setBrush(QColor(color))
        if round_:
            p.drawEllipse(pt, s / 1.6, s / 1.6)
        else:
            p.drawRect(QRectF(pt.x() - s / 2, pt.y() - s / 2, s, s))

    def _paint_transform(self, p, box, k):
        pts = box.corners()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor("#ffffff"), 2 * k))
        p.drawPolygon(QPolygonF(pts))
        p.setPen(QPen(QColor("#e6e6e6"), 1 * k))
        p.drawPolygon(QPolygonF(pts))
        top = (pts[0] + pts[1]) / 2
        rh = box.rot_handle(k)
        p.setPen(QPen(QColor("#ffffff"), 1 * k))
        p.drawLine(top, rh)
        for pt in pts:
            self._handle(p, pt, k)
        self._handle(p, rh, k, round_=True, color="#e6e6e6")
        if self.drag and self.drag["kind"] == "rotate":
            p.setPen(QColor("#ffffff"))
            f = p.font()
            f.setPixelSize(round(14 * k))
            p.setFont(f)
            p.drawText(rh + QPointF(12 * k, -8 * k), f"{box.deg:.1f}°")

    def _paint_mask(self, p, box, k):
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 90), 1 * k, Qt.DashLine))
        p.drawPolygon(QPolygonF(box.corners()))
        g = MaskGeo(box)
        path = g.outline()
        on = box.clip["mask"].get("enabled", True)
        edge = QColor("#ffb020") if on else QColor(255, 176, 32, 110)
        p.save()
        clip = QPainterPath()
        clip.addPolygon(QPolygonF(box.corners()))
        p.setClipPath(clip)                    # the mask only matters inside the clip
        p.setPen(QPen(QColor("#111114"), 3.5 * k))
        p.drawPath(path)
        p.setPen(QPen(edge, 2 * k, Qt.SolidLine if on else Qt.DashLine))
        p.drawPath(path)
        p.restore()
        c = g.centre()
        for name, pt in g.handles(k):
            if name == "rot":
                p.setPen(QPen(QColor("#ffb020"), 1 * k))
                p.drawLine(c, pt)
                self._handle(p, pt, k, round_=True, color="#ffb020")
            elif name == "feather":
                u, _ = g.down()
                n = QPointF(-u.y(), u.x())
                s = HANDLE_PX * k
                p.setPen(QPen(QColor("#111114"), 1 * k))
                p.setBrush(QColor("#ffb020"))
                p.drawPolygon(QPolygonF([pt + u * s * 0.8, pt - u * s * 0.4 + n * s * 0.7, pt - u * s * 0.4 - n * s * 0.7]))
            else:
                self._handle(p, pt, k, color="#ffb020")
        self._handle(p, c, k, round_=True, color="#ffffff")
        if self.drag and self.drag["kind"] == "feather":
            f = p.font()
            f.setPixelSize(round(14 * k))
            p.setFont(f)
            p.setPen(QColor("#ffffff"))
            p.drawText(g.handles(k)[-1][1] + QPointF(12 * k, 4 * k), f"羽化 {g.feather * 100:.0f}")

    # -- mouse ------------------------------------------------------------------------------------
    def _near(self, a, b, k):
        return math.hypot(a.x() - b.x(), a.y() - b.y()) <= PICK_PX * k

    def mousePressEvent(self, e):
        if self.interactive and e.button() == Qt.MiddleButton:
            self.drag = {"kind": "pan", "pos": e.position(), "pan": QPointF(self.pan), "moved": False}
            self.setCursor(Qt.ClosedHandCursor)
            return
        if not self.interactive or e.button() != Qt.LeftButton or not self.view:
            return
        x, y = self._to_canvas(e.position())
        m = QPointF(x, y)
        k = self._k()
        box = self.selected_box()
        if box is not None and self.masking(box):
            g = MaskGeo(box)
            hit = next((n for n, pt in g.handles(k) if self._near(pt, m, k)), None)
            if hit is None and (g.contains(m) or self._near(g.centre(), m, k)):
                hit = "move"
            if hit is not None:
                self.drag = {"kind": hit, "box": box, "geo": g, "m0": m, "moved": False}
                return
        elif box is not None and not self.mask_mode:
            if self._near(box.rot_handle(k), m, k):
                self.drag = {"kind": "rotate", "box": box, "m0": m, "moved": False}
                return
            if any(self._near(pt, m, k) for pt in box.corners()):
                self.drag = {"kind": "scale", "box": box, "m0": m, "moved": False}
                return
        boxes = self.visible_boxes()
        sel = next((b for b in boxes if b.clip["id"] == self.selected_id and b.contains(x, y)), None)
        hit = sel or next((b for b in boxes if b.contains(x, y)), None)
        if hit is None:
            return
        if hit.clip["id"] != self.selected_id:
            self.selected_id = hit.clip["id"]
            self.clipPicked.emit(hit.clip)
        if self.mask_mode:                               # masks only: the clip stays put
            self.update()
            return
        others = [b for b in boxes if b is not hit]
        self.drag = {"kind": "move", "box": hit, "x0": x, "y0": y, "moved": False, "others": others}
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

    def _values(self, e, m):
        """(group, {key: value}) for the drag at canvas point m."""
        d = self.drag
        box = d["box"]
        kind = d["kind"]
        free = bool(e.modifiers() & Qt.ShiftModifier)
        if kind == "move" and "geo" not in d:
            dx, dy = m.x() - d["x0"], m.y() - d["y0"]
            if e.modifiers() & Qt.AltModifier:                 # Alt: move freely
                self.guides = []
            else:
                dx, dy, self.guides = self._snap(box, dx, dy, d["others"], SNAP_PX * self._k())
            return "transform", {"x": round((box.cx + dx - self.W / 2) / (self.W / 2), 5),
                                 "y": round((self.H / 2 - (box.cy + dy)) / (self.H / 2), 5)}
        c = QPointF(box.cx, box.cy)
        if kind == "scale":
            r0 = math.hypot(d["m0"].x() - c.x(), d["m0"].y() - c.y()) or 1.0
            r1 = math.hypot(m.x() - c.x(), m.y() - c.y())
            return "transform", {"scale": round(max(0.01, box.s * r1 / r0), 4)}
        if kind == "rotate":
            a0 = math.degrees(math.atan2(d["m0"].y() - c.y(), d["m0"].x() - c.x()))
            a1 = math.degrees(math.atan2(m.y() - c.y(), m.x() - c.x()))
            return "transform", {"rotation": round(snap_angle(box.deg + a1 - a0, free), 2)}
        # mask handles work in the clip's own frame (they move and turn with the clip)
        g = d["geo"]
        inv, _ = box.xf().inverted()
        p0, p1 = inv.map(d["m0"]), inv.map(m)
        if kind == "move":
            return "mask", {"cx": round(g.cx + (p1.x() - p0.x()) / (g.dw / 2), 5),
                            "cy": round(g.cy - (p1.y() - p0.y()) / (g.dh / 2), 5)}
        if kind == "rot":
            o = g.local.map(QPointF(0, 0))
            a0 = math.degrees(math.atan2(p0.y() - o.y(), p0.x() - o.x()))
            a1 = math.degrees(math.atan2(p1.y() - o.y(), p1.x() - o.x()))
            return "mask", {"rotation": round(snap_angle(g.rot + a1 - a0, free), 2)}
        if kind == "feather":
            u, hh = g.down()
            ctr = g.centre()
            dist = (m.x() - ctr.x()) * u.x() + (m.y() - ctr.y()) * u.y()
            return "mask", {"feather": round(min(1.0, max(0.0, ((dist - hh) / self._k() - 14) / 80)), 3)}
        linv, _ = g.local.inverted()
        q = linv.map(p1)                                       # in the mask's own frame
        out = {}
        if "w" in kind:
            out["w"] = round(max(0.01, 2 * abs(q.x()) / g.dw), 4)
        if "h" in kind:
            out["h"] = round(max(0.01, 2 * abs(q.y()) / g.dh), 4)
        return "mask", out

    def mouseMoveEvent(self, e):
        d = self.drag
        if d is None:
            self._hover(e)
            return
        if d["kind"] == "pan":
            self.pan = d["pan"] + e.position() - d["pos"]
            self.update()
            return
        x, y = self._to_canvas(e.position())
        m = QPointF(x, y)
        if not d["moved"]:
            m0 = d["m0"] if "m0" in d else QPointF(d["x0"], d["y0"])
            if math.hypot(m.x() - m0.x(), m.y() - m0.y()) < 3 * self._k():
                return
        d["moved"] = True
        group, vals = self._values(e, m)
        self.live = (group, vals)
        self.paramsLive.emit(d["box"].clip["id"], group, vals)
        self.update()

    def _hover(self, e):
        if not self.interactive or not self.view:
            return
        x, y = self._to_canvas(e.position())
        m, k = QPointF(x, y), self._k()
        box = self.selected_box()
        cur = Qt.ArrowCursor
        if box is not None and self.masking(box):
            g = MaskGeo(box)
            if any(self._near(pt, m, k) for _, pt in g.handles(k)):
                cur = Qt.PointingHandCursor
            elif g.contains(m):
                cur = Qt.SizeAllCursor
        elif box is not None and not self.mask_mode:
            if self._near(box.rot_handle(k), m, k):
                cur = Qt.PointingHandCursor
            elif any(self._near(pt, m, k) for pt in box.corners()):
                cur = Qt.SizeFDiagCursor
            elif box.contains(x, y):
                cur = Qt.SizeAllCursor
        self.setCursor(cur)

    def mouseReleaseEvent(self, e):
        d, self.drag = self.drag, None
        if d and d["kind"] == "pan":
            self.setCursor(Qt.ArrowCursor)
            return
        self.guides = []
        live, self.live = self.live, None
        if d and d["moved"] and live:
            self.paramsCommitted.emit(d["box"].clip["id"], *live)
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
