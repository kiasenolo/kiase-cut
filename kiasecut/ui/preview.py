"""Preview canvas: shows frames and edits the selected clip with handles on the canvas.

Selection (never a clip on a locked track, project.locked: those only show and are snapped
to): click a clip to select it; Shift / Ctrl+click adds a clip to the selection or
takes it out, and a drag from where no clip is draws a box that selects every clip it
touches (Shift / Ctrl: added to the selection); a click on nothing selects nothing. Several
selected clips show their outlines in one dashed box and can only be moved together
(selectionPicked; movesLive / movesCommitted, {clip id: {x, y}}). Clips that overlap along x
make a column, along y a row; with the mouse over the selection, the gaps between columns
show an upright pink bar and the gaps between rows a flat one (in line with each column).
Dragging a bar sets every gap of its kind to the same width (the first column / row stays
put; 間距 shows it), so a row, a column or a grid is spaced evenly.

Transform: drag the clip to move it (it snaps to the canvas centre lines and edges, to
other visible clips' centres and edges and to equal spacing - centred between its
neighbours, or as far from one as two other clips are apart, shown in pink; Alt moves
freely), drag a corner or edge square to
scale it with the opposite corner / edge staying put (Alt: about its centre; the moving edges
snap to the same lines while the clip is upright or turned by a right angle, Ctrl scales
freely), drag the round
handle above it to rotate (Shift: 15° steps; it also settles on 0 / 90 / 180 / 270). With X / Y
scale linked a corner or an edge keeps their ratio; unlinked, a corner sets both freely (Shift
keeps the ratio) and an edge only its own axis. A built-in asset (assets.py) is resized instead:
its 寬 / 高 change and its scale stays (an edge changes one side, a corner both, Shift keeps
their ratio); that drag reports group "multi": {"asset": {w, h}, "transform": {x, y}}.

Mask mode (`mask_mode`, while the 遮罩 tab is open, or 編輯遮罩 of an effect's 範圍 in the
效果 tab: `mask_group` "mask" or "fxmask:<effect id>") edits only that mask: the clip itself
cannot be moved, scaled or turned there, and a click on another clip just selects it. The
mask outline is drawn where it cuts the clip (dimmed while the mask is switched off). Drag inside it to move it, the squares on its edges / corner to size it, the
round handle to rotate it and the arrow below it for the feather. The mask snaps to the
clip's centre and edges (and to a square, to full size, to feather 0 / 1) while it is dragged; Alt
drags freely. Snapped lines show in amber. A 複合片段 mask is a frame like a rectangle (no
feather) whose corner keeps the compound's proportions (Shift: free); the renderer draws the
compound itself in it (matte_preview, see render.py).

Ctrl+wheel zooms the view around the mouse (to reach handles of clips larger than the
canvas), the middle button drags it; zooming back to about 100% fits it again.

Double-clicking a text clip opens a box over it to type its words in (textEdited while
typing, one undo step); Ctrl+Enter or a click elsewhere closes it, Esc puts the words back.

Every drag shows live (paramsLive) and becomes one edit on release (paramsCommitted), in
the project's units: transform x / y in half-canvas units (y up), scale, clockwise degrees;
mask cx / cy in half-material units (y up), w / h as fractions of the material, feather.
A fullscreen window shows the same frames.
"""
import json
import math

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from .. import curves, edit, fonts, project, render, textlayout

US = 1_000_000
SNAP_PX = 7
HANDLE_PX = 9                 # handle size on screen
ROT_PX = 34                   # rotation handle distance from the outline
PICK_PX = 9
ANGLE_SNAP = 3.0              # degrees within which rotation settles on a right angle
_text_sizes = {}


def text_size(spec, canvas_h):
    """Text box (w, h) in canvas px at scale 1."""
    key = json.dumps([spec, canvas_h, fonts.map_key()], sort_keys=True, default=str)
    if key not in _text_sizes:
        im = textlayout.render(spec, 1.0, canvas_h)
        _text_sizes[key] = (im.width, im.height)
    return _text_sizes[key]


def base_size(c, W, H, t):
    """On-canvas size of clip c at scale 1."""
    if c["type"] == "text":
        spec = curves.static(c["text"], t, render.TEXT_FIELDS)
        return text_size(spec, H)
    if c["type"] == "compound":
        w, h = c["compound"]["width"], c["compound"]["height"]
    elif c.get("media", {}).get("width"):
        return project.picture_size(c, W, H, t=t)
    else:
        w, h = W, H
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

    def handles(self):
        """(sx, sy, canvas point) of the scale handles: the corners, then the edge middles
        (sx, sy: -1 / 0 / 1 along the clip's own x / y, y down)."""
        c, s = math.cos(self.rot), math.sin(self.rot)
        out = []
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1), (0, -1), (1, 0), (0, 1), (-1, 0)):
            x, y = sx * self.w / 2, sy * self.h / 2
            out.append((sx, sy, QPointF(self.cx + x * c - y * s, self.cy + x * s + y * c)))
        return out

    def to_local(self, pt):
        """A canvas point in the clip's own frame (centre origin, unrotated, canvas px)."""
        c, s = math.cos(-self.rot), math.sin(-self.rot)
        dx, dy = pt.x() - self.cx, pt.y() - self.cy
        return dx * c - dy * s, dx * s + dy * c

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
    """A clip's mask (or one of its effects' masks: m) at one time: its frame on the canvas
    and handle points."""

    def __init__(self, box, m=None):
        m = m if m is not None else box.clip["mask"]
        t = box.t
        v = lambda k, d: curves.value(m.get(k, d), t)
        self.box, self.m = box, m
        self.kind = v("kind", "rectangle")                      # (a shape can have keyframes)
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
        if self.kind in ("rectangle", "circle", "compound"):
            out += [("w", self.xf.map(QPointF(self.hw, 0))), ("h", self.xf.map(QPointF(0, -self.hh))),
                    ("wh", self.xf.map(QPointF(self.hw, -self.hh)))]
        elif self.kind == "mirror":
            out.append(("h", self.xf.map(QPointF(0, -self.hh))))
        u, hh = self.down()
        c = self.centre()
        out.append(("rot", c - u * (hh + ROT_PX * k)))
        if self.kind != "compound":                             # (a compound's picture has no feather)
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


def gap_snaps(lo, hi, clo, chi, rects, tol):
    """Equal spacing along one axis. lo / hi: the moved outline's span along it, clo / chi:
    across it; rects: the other clips' (lo, hi, clo, chi). Returns [(lo, gaps)]: where lo
    would go for the gap next to it to equal another one (centred between its neighbours, or
    as wide as a gap between two other clips), with the gaps to show as (a, b, across)."""
    def across(p, q):
        return (max(p[0], q[0]) + min(p[1], q[1])) / 2

    w, me = hi - lo, (clo, chi)
    row = [o for o in rects if o[3] > clo and o[2] < chi]          # side by side with it
    left = max((o for o in row if o[1] <= lo + tol), key=lambda o: o[1], default=None)
    right = min((o for o in row if o[0] >= hi - tol), key=lambda o: o[0], default=None)
    out = []
    if left and right and right[0] - left[1] >= w:
        nl = (left[1] + right[0] - w) / 2
        out.append((nl, [(left[1], nl, across(me, left[2:])), (nl + w, right[0], across(me, right[2:]))]))
    for p in rects:                                                # the gaps between other clips
        q = min((o for o in rects if o[0] > p[1] and o[3] > p[2] and o[2] < p[3]), key=lambda o: o[0], default=None)
        if q is None or (p is left and q is right):
            continue
        g, seg = q[0] - p[1], (p[1], q[0], across(p[2:], q[2:]))
        if left:
            out.append((left[1] + g, [(left[1], left[1] + g, across(me, left[2:])), seg]))
        if right:
            out.append((right[0] - g - w, [(right[0] - g, right[0], across(me, right[2:])), seg]))
    return out


class Preview(QWidget):
    clipPicked = Signal(object)                 # clip dict
    selectionPicked = Signal(object, object)    # {clip ids}, the primary one (or None): Shift / Ctrl+click, a box
    paramsLive = Signal(str, str, dict)         # clip id, group, {key: value} while dragging
    paramsCommitted = Signal(str, str, dict)    # the same on release
    movesLive = Signal(dict)                    # {clip id: {x, y}} while several clips are dragged
    movesCommitted = Signal(dict)               # the same on release
    doubleClicked = Signal()
    textEdited = Signal(str, str)               # text clip id, its words: typed in on the canvas
    renderWidth = Signal(int)                   # width of the canvas on screen, device px

    def __init__(self, parent=None, interactive=True):
        super().__init__(parent)
        self.img = None
        self.W, self.H = 1920, 1080
        self.view = None
        self.t_us = 0
        self.selected_id = None
        self.selected_ids = set()               # the whole selection (with selected_id, the primary)
        self.interactive = interactive
        self.mask_mode = False
        self.mask_group = "mask"                # which mask mask mode edits: the clip's, "fxmask:<effect id>"
        self.text_box = None                    # TextBox while a text clip's words are typed on the canvas
        self.drag = None
        self.guides = []
        self.mask_guides = []                   # (a, b) canvas points: lines a mask drag has snapped to
        self.gap_hover = None                   # several clips selected, the mouse over them: "group" / "handle"
        self.live = None                        # (group, values) shown while dragging
        self.zoom = 1.0                         # view zoom (1 = canvas fits the widget)
        self.pan = QPointF(0, 0)                # view offset, screen px
        self.setMinimumSize(320, 180)
        self.setMouseTracking(True)

    # -- state ------------------------------------------------------------------------------------
    def show_image(self, img):
        self.img = img
        self.update()

    def set_scene(self, view, t_us, selected_id, selected_ids=None):
        self.view = view
        if view and (self.W, self.H) != (view["width"], view["height"]):
            self.W, self.H = view["width"], view["height"]
            self._report_size()
        self.t_us = t_us
        self.selected_id = selected_id
        self.selected_ids = (set(selected_ids or ()) | {selected_id}) if selected_id else set()
        if self.drag is None:
            self.update()

    def set_mask_mode(self, on, group="mask"):
        self.mask_mode, self.mask_group = on, group
        self.update()

    def mask_of(self, clip):
        """The mask that mask mode edits on clip, or None."""
        try:
            return edit.holder(clip, self.mask_group)
        except (edit.EditError, KeyError):
            return None

    def _report_size(self):
        self.renderWidth.emit(round(self._rect().width() * self.devicePixelRatioF()))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._report_size()

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
        self._report_size()
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
                if c["type"] == "filter" and not (self.mask_mode and c["id"] == self.selected_id):
                    continue                    # a filter covers the whole picture: only its mask is edited here
                if c["start_us"] <= self.t_us < c["start_us"] + c["duration_us"] and c.get("transform") is not None:
                    b = Box(c, self.W, self.H, self.t_us - c["start_us"])
                    b.locked = project.locked(tr)       # (shown and snapped to, never picked)
                    out.append(b)
        return out

    def selected_box(self):
        return next((b for b in self.visible_boxes() if b.clip["id"] == self.selected_id), None)

    def multi(self):
        """Several clips selected: they can only be moved together (no handles)."""
        return len(self.selected_ids) > 1 and not self.mask_mode

    def _live_boxes(self):
        """Boxes of the selected clips showing now, moved as they are being dragged."""
        moves = self.live[1] if self.live and self.live[0] == "moves" else {}
        out = []
        for b in self.visible_boxes():
            if b.clip["id"] in self.selected_ids:
                if b.clip["id"] in moves:
                    b = Box(dict(b.clip, transform=dict(b.clip["transform"], **moves[b.clip["id"]])), self.W, self.H, b.t)
                out.append(b)
        return out

    def _live_box(self):
        """The selected clip's box with the values being dragged applied."""
        box = self.selected_box()
        if box is None or self.live is None or self.live[0] == "moves":
            return box
        group, vals = self.live
        c = json.loads(json.dumps(box.clip))
        for g, v in (vals.items() if group == "multi" else [(group, vals)]):
            holder = c if g == "clip" else edit.holder(c, g) if g.startswith("fxmask:") else c.setdefault(g, {})
            holder.update(edit.with_linked_scale(holder, v, box.t) if g == "transform" else v)
        return Box(c, self.W, self.H, box.t)

    def masking(self, box):
        if not self.mask_mode or box is None or not self.mask_of(box.clip):
            return False
        return self.mask_group != "mask" or box.clip["type"] in ("image", "video", "compound", "filter")

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
        if self.multi():
            self._paint_group(p, k)
        elif box is not None:
            if self.masking(box):
                self._paint_mask(p, box, k)
            elif self.mask_mode:                         # no mask: just where the clip is
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(255, 255, 255, 120), 1 * k, Qt.DashLine))
                p.drawPolygon(QPolygonF(box.corners()))
            else:
                self._paint_transform(p, box, k)
        if self.drag and self.drag["kind"] == "marquee" and self.drag["moved"]:
            p.setPen(QPen(QColor("#e6e6e6"), 1 * k, Qt.DashLine))
            p.setBrush(QColor(255, 255, 255, 28))
            p.drawRect(self.drag["rect"])
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor("#ffffff"), 1.5 * k))
            for b in self.drag["hits"]:
                p.drawPolygon(QPolygonF(b.corners()))
        if self.mask_guides:
            p.setPen(QPen(QColor("#ffb020"), 1.5 * k, Qt.DashLine))
            for a, b in self.mask_guides:
                p.drawLine(a, b)
        for g in self.guides:
            if g[0] == "gap":                            # an equal gap: a line with ends
                a, b = g[1], g[2]
                n = QPointF(0, 5 * k) if abs(b.x() - a.x()) > abs(b.y() - a.y()) else QPointF(5 * k, 0)
                p.setPen(QPen(QColor("#ff5ca8"), 1.5 * k))
                p.drawLine(a, b)
                p.drawLine(a - n, a + n)
                p.drawLine(b - n, b + n)
                continue
            p.setPen(QPen(QColor("#e6e6e6"), 1.5 * k, Qt.DashLine))
            if g[0] == "x":
                p.drawLine(QPointF(g[1], 0), QPointF(g[1], self.H))
            else:
                p.drawLine(QPointF(0, g[1]), QPointF(self.W, g[1]))

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
        for _sx, _sy, pt in box.handles():
            self._handle(p, pt, k)
        self._handle(p, rh, k, round_=True, color="#e6e6e6")
        if self.drag and self.drag["kind"] == "rotate":
            p.setPen(QColor("#ffffff"))
            f = p.font()
            f.setPixelSize(round(14 * k))
            p.setFont(f)
            p.drawText(rh + QPointF(12 * k, -8 * k), f"{box.deg:.1f}°")

    def _paint_group(self, p, k):
        """Several clips selected: each outline and a dashed box around them all."""
        boxes = self._live_boxes()
        if not boxes:
            return
        p.setBrush(Qt.NoBrush)
        for b in boxes:
            p.setPen(QPen(QColor("#ffffff"), (2 if b.clip["id"] == self.selected_id else 1.25) * k))
            p.drawPolygon(QPolygonF(b.corners()))
        l, r, t, b = self._union(boxes)
        p.setPen(QPen(QColor("#e6e6e6"), 1 * k, Qt.DashLine))
        p.drawRect(QRectF(l, t, r - l, b - t))
        dragging = self.drag and self.drag["kind"] == "gap"
        if not (self.gap_hover or dragging):
            return
        gaps = self._gaps(boxes, k)
        pink = QColor("#ff5ca8")
        if dragging or self.gap_hover == "handle":       # where the gaps are (while dragging: its kind)
            area = QPainterPath()
            area.setFillRule(Qt.WindingFill)             # (where gaps cross: tinted once)
            for axis, _, _, rect, _ in gaps:
                if not dragging or axis == self.drag["axis"]:
                    area.addRect(rect)
            p.fillPath(area, QColor(255, 92, 168, 50))
        for _, _, bars, _, _ in gaps:                    # pink bars in each gap, drawn on white
            for line in bars:
                p.setPen(QPen(QColor("#ffffff"), 4 * k, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(*line)
                p.setPen(QPen(pink, 2 * k, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(*line)
        width = next((g[4] for g in gaps if dragging and g[0] == self.drag["axis"]), None)
        if width is not None:
            f = p.font()
            f.setPixelSize(round(13 * k))
            p.setFont(f)
            text = f"間距 {width:.0f}"
            box = QRectF(0, 0, p.fontMetrics().horizontalAdvance(text) + 12 * k, 20 * k)
            box.moveCenter(QPointF((l + r) / 2, b + 18 * k))
            p.setPen(Qt.NoPen)
            p.setBrush(pink)
            p.drawRoundedRect(box, 3 * k, 3 * k)
            p.setPen(QColor("#ffffff"))
            p.drawText(box, Qt.AlignCenter, text)

    @staticmethod
    def _bands(boxes, axis):
        """The boxes grouped where they overlap along axis - columns for "x", rows for "y" - in
        order: [[lo, hi, boxes]]."""
        lo, hi = (0, 1) if axis == "x" else (2, 3)
        out = []
        for b in sorted(boxes, key=lambda b: b.extents()[lo]):
            e = b.extents()
            if out and e[lo] < out[-1][1] - 0.5:
                out[-1][1] = max(out[-1][1], e[hi])
                out[-1][2].append(b)
            else:
                out.append([e[lo], e[hi], [b]])
        return out

    def _gaps(self, boxes, k):
        """[(axis, index, bars [(a, b)], gap area, gap width)] of the gaps between the columns
        ("x") and between the rows ("y") the boxes stand in; k = canvas px per screen px. A
        column gap has one bar halfway down; a row gap one in line with each column."""
        if len(boxes) < 2:
            return []
        l, r, t, b = self._union(boxes)
        cols, rows = self._bands(boxes, "x"), self._bands(boxes, "y")
        out = []
        half = min(10 * k, (b - t) / 2)
        for i, (c, n) in enumerate(zip(cols, cols[1:])):
            a, z = c[1], n[0]
            mid = QPointF((a + z) / 2, (t + b) / 2)
            out.append(("x", i, [(mid - QPointF(0, half), mid + QPointF(0, half))], QRectF(a, t, z - a, b - t), z - a))
        for i, (c, n) in enumerate(zip(rows, rows[1:])):
            a, z = c[1], n[0]
            bars = []
            for col in cols:
                mid, h = QPointF((col[0] + col[1]) / 2, (a + z) / 2), min(10 * k, (col[1] - col[0]) / 2)
                bars.append((mid - QPointF(h, 0), mid + QPointF(h, 0)))
            out.append(("y", i, bars, QRectF(l, a, r - l, z - a), z - a))
        return out

    def _gap_at(self, m, k):
        """(axis, index, gap width) of the gap bar at canvas point m while several clips are
        selected."""
        if not self.multi():
            return None
        pad = PICK_PX * k
        for axis, i, bars, _, width in self._gaps(self._live_boxes(), k):
            if any(QRectF(a, b).normalized().adjusted(-pad, -pad, pad, pad).contains(m) for a, b in bars):
                return axis, i, width
        return None

    def _spread(self, boxes, axis, gap):
        """{clip id: {x or y}} for the boxes with every gap between their columns (axis "x") or
        rows ("y") gap canvas px wide, the first column / row staying where it is."""
        pos, out = None, {}
        for lo, hi, members in self._bands(boxes, axis):
            pos = lo if pos is None else pos
            for b in members:
                if axis == "x":
                    out[b.clip["id"]] = {"x": round((b.cx + pos - lo - self.W / 2) / (self.W / 2), 5)}
                else:
                    out[b.clip["id"]] = {"y": round((self.H / 2 - (b.cy + pos - lo)) / (self.H / 2), 5)}
            pos += hi - lo + gap
        return out

    @staticmethod
    def _union(boxes):
        """(left, right, top, bottom) around all the boxes."""
        ex = [b.extents() for b in boxes]
        return min(e[0] for e in ex), max(e[1] for e in ex), min(e[2] for e in ex), max(e[3] for e in ex)

    def _paint_mask(self, p, box, k):
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 90), 1 * k, Qt.DashLine))
        p.drawPolygon(QPolygonF(box.corners()))
        g = MaskGeo(box, self.mask_of(box.clip))
        path = g.outline()
        on = g.m.get("enabled", True)
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
            g = MaskGeo(box, self.mask_of(box.clip))
            hit = next((n for n, pt in g.handles(k) if self._near(pt, m, k)), None)
            if hit is None and (g.contains(m) or self._near(g.centre(), m, k)):
                hit = "move"
            if hit is not None:
                self.drag = {"kind": hit, "box": box, "geo": g, "m0": m, "moved": False}
                return
        elif box is not None and not self.mask_mode and not self.multi():
            if self._near(box.rot_handle(k), m, k):
                self.drag = {"kind": "rotate", "box": box, "m0": m, "moved": False}
                return
            side = next(((sx, sy) for sx, sy, pt in box.handles() if self._near(pt, m, k)), None)
            if side is not None:
                self.drag = {"kind": "scale", "box": box, "m0": m, "moved": False, "side": side,
                             "others": [b for b in self.visible_boxes() if b.clip["id"] != box.clip["id"]]}
                return
        gap = self._gap_at(m, k)
        if gap is not None:                              # a gap bar: all the gaps of its kind change together
            boxes = self._live_boxes()
            self.drag = {"kind": "gap", "box": boxes[0], "boxes": boxes, "axis": gap[0], "gap0": gap[2],
                         "m0": m, "moved": False}
            return
        boxes = self.visible_boxes()
        adding = bool(e.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier)) and not self.mask_mode
        pickable = [b for b in boxes if not b.locked]          # clips on locked tracks are not picked
        sel = next((b for b in pickable if b.clip["id"] in self.selected_ids and b.contains(x, y)), None)
        hit = sel or next((b for b in pickable if b.contains(x, y)), None)
        if hit is None:
            if not self.mask_mode:                       # a box around the clips to select
                self.drag = {"kind": "marquee", "m0": m, "moved": False, "adding": adding, "hits": []}
            return
        cid = hit.clip["id"]
        if adding:                                       # Shift / Ctrl+click: in or out of the selection
            ids = set(self.selected_ids) ^ {cid}
            primary = cid if cid in ids else (self.selected_id if self.selected_id in ids else next(iter(ids), None))
            self._select(ids, primary)
            if cid not in ids:
                return
        elif cid != self.selected_id and (self.mask_mode or cid not in self.selected_ids):
            self.selected_id, self.selected_ids = cid, {cid}
            self.clipPicked.emit(hit.clip)
        if self.mask_mode:                               # masks only: the clip stays put
            self.update()
            return
        moving = [b for b in boxes if b.clip["id"] in self.selected_ids]
        others = [b for b in boxes if b.clip["id"] not in self.selected_ids]
        self.drag = {"kind": "move", "box": hit, "boxes": moving, "x0": x, "y0": y, "moved": False, "others": others}
        self.update()

    def _select(self, ids, primary):
        self.selected_ids, self.selected_id = (set(ids), primary) if primary else (set(), None)
        self.selectionPicked.emit(set(self.selected_ids), self.selected_id)
        self.update()

    def _marquee_hits(self, rect):
        """Visible clips the selection box touches, topmost first."""
        area = QPolygonF(rect)
        return [b for b in self.visible_boxes() if not b.locked and QPolygonF(b.corners()).intersects(area)]

    def _snap(self, rect, dx, dy, others, tol):
        """Snap an outline being moved by dx, dy (rect: its left, right, top, bottom) to the
        canvas centre lines and edges, to other clips' centres and edges and to equal gaps
        between clips (others: their rects). Returns dx, dy and the guides to draw."""
        l, r, t, b = rect
        tx = [self.W / 2, 0, self.W] + [v for o in others for v in ((o[0] + o[1]) / 2, o[0], o[1])]
        ty = [self.H / 2, 0, self.H] + [v for o in others for v in ((o[2] + o[3]) / 2, o[2], o[3])]

        def axis(name, lo, hi, d, gaps, point):
            hit = self._best([(lo + hi) / 2 + d, lo + d, hi + d], tx if name == "x" else ty, tol)
            best = (abs(hit[0]), hit[0], [(name, hit[1])]) if hit else None
            for nl, segs in gaps:
                s = nl - (lo + d)
                if abs(s) < tol and (best is None or abs(s) < best[0]):
                    best = (abs(s), s, [("gap", point(a, c), point(z, c)) for a, z, c in segs])
            return (d, []) if best is None else (d + best[1], best[2])

        dy, gy = axis("y", t, b, dy, gap_snaps(t + dy, b + dy, l + dx, r + dx, [(o[2], o[3], o[0], o[1]) for o in others], tol),
                      lambda a, c: QPointF(c, a))
        dx, gx = axis("x", l, r, dx, gap_snaps(l + dx, r + dx, t + dy, b + dy, others, tol), lambda a, c: QPointF(a, c))
        return dx, dy, gx + gy

    @staticmethod
    def _best(cands, targets, tol):
        """(shift, target) of the closest candidate / target pair within tol, else None."""
        hit = None
        for v in cands:
            for g in targets:
                if abs(v - g) < tol and (hit is None or abs(g - v) < abs(hit[0])):
                    hit = (g - v, g)
        return hit

    def _mask_line(self, box, g, axis, v):
        """A guide through clip-frame value v (half-material units) along `axis`, across the clip."""
        reach = 2 * math.hypot(g.dw, g.dh)
        if axis == "x":
            a, b = QPointF(v * g.dw / 2, -reach), QPointF(v * g.dw / 2, reach)
        else:
            a, b = QPointF(-reach, -v * g.dh / 2), QPointF(reach, -v * g.dh / 2)
        xf = box.xf()
        return xf.map(a), xf.map(b)

    def _snap_mask(self, kind, vals, g, box, free, keep=None):
        """Snap the mask values being dragged (move: cx / cy, size: w / h, feather) to the clip's
        centre and edges; keep = h / w to hold (a compound's corner: one side snaps, the other
        follows). Returns the values; self.mask_guides gets the lines shown."""
        self.mask_guides = []
        if free:
            return vals
        k = self._k()
        tx = SNAP_PX * k / max(g.dw / 2 * abs(box.s), 1e-6)       # canvas px -> half-material units
        ty = SNAP_PX * k / max(g.dh / 2 * abs(box.sy), 1e-6)
        upright = abs(g.rot) % 180 < 0.01                         # edges line up with the clip's
        guides = []
        if kind == "move":
            cx, cy = vals["cx"], vals["cy"]
            ex = [0.0] if g.hw == 0 else ([-g.mw, 0.0, g.mw] if upright else [0.0])
            ey = [0.0] if g.hh == 0 else ([-g.mh, 0.0, g.mh] if upright else [0.0])
            hx = self._best([cx + d for d in ex], [-1.0, 0.0, 1.0], tx)
            hy = self._best([cy + d for d in ey], [-1.0, 0.0, 1.0], ty)
            if hx:
                vals["cx"] = round(cx + hx[0], 5)
                guides.append(("x", hx[1]))
            if hy:
                vals["cy"] = round(cy + hy[0], 5)
                guides.append(("y", hy[1]))
        elif kind in ("w", "h", "wh") and upright:
            cx, cy = g.cx, g.cy
            if "w" in vals:                   # an edge reaches the clip's edge, or the full width
                hit = self._best([vals["w"]], [1.0 - cx, 1.0 + cx, 1.0], tx)
                if hit:
                    vals["w"] = round(vals["w"] + hit[0], 4)
                    guides += [("x", cx - vals["w"]), ("x", cx + vals["w"])]
            if keep is not None:              # one side snaps, the other keeps the proportions
                hit = None if guides else self._best([vals["h"]], [1.0 - cy, 1.0 + cy, 1.0], ty)
                if hit:
                    vals["h"] = round(vals["h"] + hit[0], 4)
                    vals["w"] = round(vals["h"] / keep, 4)
                    guides += [("y", cy - vals["h"]), ("y", cy + vals["h"])]
                else:
                    vals["h"] = round(vals["w"] * keep, 4)
            elif "h" in vals:
                hit = self._best([vals["h"]], [1.0 - cy, 1.0 + cy, 1.0], ty)
                if hit:
                    vals["h"] = round(vals["h"] + hit[0], 4)
                    guides += [("y", cy - vals["h"]), ("y", cy + vals["h"])]
            if kind == "wh" and "w" in vals and "h" in vals and not guides:
                # a square (or a circle): as wide as high on screen
                pw, ph = vals["w"] * g.dw, vals["h"] * g.dh
                if abs(pw - ph) < SNAP_PX * k:
                    vals["h"] = round(pw / g.dh, 4)
        elif kind == "feather":
            hit = self._best([vals["feather"]], [0.0, 1.0], 0.025)
            if hit:
                vals["feather"] = hit[1]
        self.mask_guides = [self._mask_line(box, g, ax, v) for ax, v in guides]
        return vals

    def _values(self, e, m):
        """(group, {key: value}) for the drag at canvas point m."""
        d = self.drag
        box = d["box"]
        kind = d["kind"]
        free = bool(e.modifiers() & Qt.ShiftModifier)
        if kind == "move" and "geo" not in d:
            dx, dy = m.x() - d["x0"], m.y() - d["y0"]
            boxes = d.get("boxes") or [box]
            if e.modifiers() & Qt.AltModifier:                 # Alt: move freely
                self.guides = []
            else:
                dx, dy, self.guides = self._snap(self._union(boxes), dx, dy, [o.extents() for o in d["others"]],
                                                 SNAP_PX * self._k())
            at = {b.clip["id"]: {"x": round((b.cx + dx - self.W / 2) / (self.W / 2), 5),
                                 "y": round((self.H / 2 - (b.cy + dy)) / (self.H / 2), 5)} for b in boxes}
            return ("moves", at) if len(boxes) > 1 else ("transform", at[box.clip["id"]])
        if kind == "gap":
            along = m.x() - d["m0"].x() if d["axis"] == "x" else m.y() - d["m0"].y()
            return "moves", self._spread(d["boxes"], d["axis"], max(0.0, round(d["gap0"] + along)))
        c = QPointF(box.cx, box.cy)
        if kind == "scale":
            return self._scale_values(box, d, m, e.modifiers())
        if kind == "rotate":
            a0 = math.degrees(math.atan2(d["m0"].y() - c.y(), d["m0"].x() - c.x()))
            a1 = math.degrees(math.atan2(m.y() - c.y(), m.x() - c.x()))
            return "transform", {"rotation": round(snap_angle(box.deg + a1 - a0, free), 2)}
        # mask handles work in the clip's own frame (they move and turn with the clip)
        g = d["geo"]
        inv, _ = box.xf().inverted()
        p0, p1 = inv.map(d["m0"]), inv.map(m)
        if kind == "move":
            return "mask", self._snap_mask("move", {"cx": round(g.cx + (p1.x() - p0.x()) / (g.dw / 2), 5),
                                                    "cy": round(g.cy - (p1.y() - p0.y()) / (g.dh / 2), 5)},
                                           g, box, bool(e.modifiers() & Qt.AltModifier))
        if kind == "rot":
            o = g.local.map(QPointF(0, 0))
            a0 = math.degrees(math.atan2(p0.y() - o.y(), p0.x() - o.x()))
            a1 = math.degrees(math.atan2(p1.y() - o.y(), p1.x() - o.x()))
            return "mask", {"rotation": round(snap_angle(g.rot + a1 - a0, free), 2)}
        if kind == "feather":
            u, hh = g.down()
            ctr = g.centre()
            dist = (m.x() - ctr.x()) * u.x() + (m.y() - ctr.y()) * u.y()
            return "mask", self._snap_mask("feather", {"feather": round(
                min(1.0, max(0.0, ((dist - hh) / self._k() - 14) / 80)), 3)}, g, box, bool(e.modifiers() & Qt.AltModifier))
        linv, _ = g.local.inverted()
        q = linv.map(p1)                                       # in the mask's own frame
        out = {}
        if "w" in kind:
            out["w"] = round(max(0.01, 2 * abs(q.x()) / g.dw), 4)
        if "h" in kind:
            out["h"] = round(max(0.01, 2 * abs(q.y()) / g.dh), 4)
        if kind == "wh" and g.kind == "compound" and not free:   # a compound keeps its proportions (Shift: free)
            vx, vy = g.mw * g.dw, g.mh * g.dh                       # the corner, from the centre
            f = max(0.01 / max(g.mw, g.mh, 1e-6), (abs(q.x()) * vx + abs(q.y()) * vy) * 2 / max(vx * vx + vy * vy, 1e-9))
            out = {"w": round(g.mw * f, 4), "h": round(g.mh * f, 4)}
            return "mask", self._snap_mask("w", out, g, box, bool(e.modifiers() & Qt.AltModifier), keep=g.mh / max(g.mw, 1e-9))
        return "mask", self._snap_mask(kind, out, g, box, bool(e.modifiers() & Qt.AltModifier))

    def _scale_values(self, box, d, m, mods):
        """(group, values) of a drag of scale handle d["side"] to canvas point m (see the
        module notes): scale, scale_y - or a built-in asset's w / h - and, unless Alt holds
        the centre, x / y so that the opposite corner or edge stays where it is."""
        sx, sy = d["side"]
        centre = bool(mods & Qt.AltModifier)
        lx0, ly0 = box.to_local(d["m0"])
        lx, ly = box.to_local(m)
        hx, hy = sx * box.w / 2, sy * box.h / 2               # the handle (clip frame, px)
        px, py = hx + lx - lx0, hy + ly - ly0                  # where it is dragged to
        ax, ay = (0.0, 0.0) if centre else (-hx, -hy)          # what stays put
        kx = (px - ax) / (hx - ax) if sx and hx != ax else 1.0
        ky = (py - ay) / (hy - ay) if sy and hy != ay else 1.0
        tf = box.clip.get("transform") or {}
        asset = box.clip.get("asset")
        tied = bool((edit.linked(tf) and not asset) or (sx and sy and mods & Qt.ShiftModifier))
        if tied:
            if sx and sy:                                      # along the diagonal
                vx, vy = hx - ax, hy - ay
                kx = ky = ((px - ax) * vx + (py - ay) * vy) / ((vx * vx + vy * vy) or 1.0)
            else:
                kx = ky = kx if sx else ky
        self.guides = []
        if not mods & Qt.ControlModifier:                      # Ctrl: scale freely
            kx, ky, self.guides = self._snap_scale(box, d.get("others", []), (bool(sx) or tied, bool(sy) or tied),
                                                   (ax, ay), (kx, ky), tied)
        if asset:                                              # its own size changes, not the scale
            w0, h0 = box.bw, box.bh
            nw, nh = max(1.0, w0 * kx), max(1.0, h0 * ky)
            kx, ky = nw / w0, nh / h0
            vals = {"asset": {"w": round(nw, 1), "h": round(nh, 1)}, "transform": {}}
            out = vals["transform"]
        else:
            scale = lambda s, k: math.copysign(max(0.01, abs(s * k)), s or 1.0)
            ns, nsy = scale(box.s, kx), scale(box.sy, ky)
            out = vals = {"scale": round(ns, 4), "scale_y": round(nsy, 4)}
            kx, ky = ns / box.s if box.s else 1.0, nsy / box.sy if box.sy else 1.0
        if not centre:
            dx, dy = ax - ax * kx, ay - ay * ky                    # the anchor's move, cancelled
            c, s = math.cos(box.rot), math.sin(box.rot)
            cx, cy = box.cx + dx * c - dy * s, box.cy + dx * s + dy * c
            out.update(x=round((cx - self.W / 2) / (self.W / 2), 5), y=round((self.H / 2 - cy) / (self.H / 2), 5))
        if asset and not out:
            del vals["transform"]
        return ("multi" if asset else "transform"), vals

    def _snap_scale(self, box, others, driven, anchor, ks, tied):
        """Snap the factors ks = (kx, ky) of a scale drag so that a moving edge lands on the
        canvas centre lines / edges or another clip's centre / edges. Only for a clip turned by
        a right angle (its edges are then upright); `driven`: which axes the drag changes,
        `anchor`: the clip-frame point that stays put, `tied`: kx = ky. Returns (kx, ky, guides)."""
        r = box.deg % 90
        if min(r, 90 - r) > 0.01:
            return ks[0], ks[1], []
        tol = SNAP_PX * self._k()
        targets = {"x": [self.W / 2, 0, self.W], "y": [self.H / 2, 0, self.H]}
        for o in others:
            ol, orr, ot, ob = o.extents()
            targets["x"] += [o.cx, ol, orr]
            targets["y"] += [o.cy, ot, ob]
        c, s = round(math.cos(box.rot)), round(math.sin(box.rot))
        hits = [None, None]                                    # per axis: (distance, k, canvas axis, target)
        for i, u, half in ((0, (c, s), box.w / 2), (1, (-s, c), box.h / 2)):
            if not driven[i]:
                continue
            axis, base, sign = ("x", box.cx, u[0]) if u[0] else ("y", box.cy, u[1])
            a = anchor[i]
            for e in (half, -half):                            # each edge: at base + (a + (e - a) k) sign
                v = (e - a) * sign
                if abs(v) < 1e-9:                              # the edge that stays put
                    continue
                pos = base + a * sign + v * ks[i]
                for g in targets[axis]:
                    k = (g - base - a * sign) / v
                    if abs(pos - g) < tol and k > 0 and (hits[i] is None or abs(pos - g) < hits[i][0]):
                        hits[i] = (abs(pos - g), k, axis, g)
        kx, ky = ks
        if tied:
            best = min((h for h in hits if h), default=None)
            if best is None:
                return kx, ky, []
            return best[1], best[1], [(best[2], best[3])]
        if hits[0]:
            kx = hits[0][1]
        if hits[1]:
            ky = hits[1][1]
        return kx, ky, [(h[2], h[3]) for h in hits if h]

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
        if d["kind"] == "marquee":
            d["rect"] = QRectF(d["m0"], m).normalized()
            d["hits"] = self._marquee_hits(d["rect"])
            self.update()
            return
        group, vals = self._values(e, m)
        if group == "mask":
            group = self.mask_group
        self.live = (group, vals)
        if group == "moves":
            self.movesLive.emit(vals)
        else:
            self.paramsLive.emit(d["box"].clip["id"], group, vals)
        self.update()

    def leaveEvent(self, e):
        if self.gap_hover:
            self.gap_hover = None
            self.update()
        super().leaveEvent(e)

    def _hover(self, e):
        if not self.interactive or not self.view:
            return
        x, y = self._to_canvas(e.position())
        m, k = QPointF(x, y), self._k()
        box = self.selected_box()
        cur = Qt.ArrowCursor
        hover = None
        if box is not None and self.masking(box):
            g = MaskGeo(box, self.mask_of(box.clip))
            if any(self._near(pt, m, k) for _, pt in g.handles(k)):
                cur = Qt.PointingHandCursor
            elif g.contains(m):
                cur = Qt.SizeAllCursor
        elif self.multi():
            boxes = self._live_boxes()
            l, r, t, b = self._union(boxes) if boxes else (0, 0, 0, 0)
            pad = 2 * PICK_PX * k
            if (gap := self._gap_at(m, k)) is not None:
                cur, hover = (Qt.SizeHorCursor if gap[0] == "x" else Qt.SizeVerCursor), "handle"
            elif any(bx.contains(x, y) for bx in boxes):
                cur, hover = Qt.SizeAllCursor, "group"
            elif l - pad <= x <= r + pad and t - pad <= y <= b + pad:
                hover = "group"
        elif box is not None and not self.mask_mode:
            if self._near(box.rot_handle(k), m, k):
                cur = Qt.PointingHandCursor
            elif (side := next(((sx, sy) for sx, sy, pt in box.handles() if self._near(pt, m, k)), None)):
                sx, sy = side
                cur = (Qt.SizeHorCursor if not sy else Qt.SizeVerCursor if not sx else
                       Qt.SizeFDiagCursor if sx == sy else Qt.SizeBDiagCursor)
            elif box.contains(x, y):
                cur = Qt.SizeAllCursor
        if hover != self.gap_hover:                      # the gap bars show while over the selection
            self.gap_hover = hover
            self.update()
        self.setCursor(cur)

    def mouseReleaseEvent(self, e):
        d, self.drag = self.drag, None
        if d and d["kind"] == "pan":
            self.setCursor(Qt.ArrowCursor)
            return
        self.guides = []
        self.mask_guides = []
        live, self.live = self.live, None
        if d and d["kind"] == "marquee":
            ids = {b.clip["id"] for b in d["hits"]} | (self.selected_ids if d["adding"] else set())
            primary = self.selected_id if self.selected_id in ids else next(
                (b.clip["id"] for b in d["hits"]), None)
            if d["moved"] or not d["adding"]:             # (a plain click on nothing selects nothing)
                self._select(ids, primary)
        elif d and d["moved"] and live:
            if live[0] == "moves":
                self.movesCommitted.emit(live[1])
            else:
                self.paramsCommitted.emit(d["box"].clip["id"], *live)
        self.update()

    def mouseDoubleClickEvent(self, e):
        if not self.interactive:
            self.doubleClicked.emit()
            return
        if e.button() != Qt.LeftButton or not self.view or self.mask_mode:
            return
        x, y = self._to_canvas(e.position())
        boxes = [b for b in self.visible_boxes() if not b.locked]
        hit = next((b for b in boxes if b.clip["id"] == self.selected_id and b.contains(x, y)), None) \
            or next((b for b in boxes if b.contains(x, y)), None)
        if hit is not None and hit.clip["type"] == "text" and not curves.is_animated(hit.clip["text"].get("content")):
            self.drag = None
            self.edit_text(hit)

    # -- typing a text clip's words on the canvas -------------------------------------------------
    def _screen_rect(self, box):
        """Where box is on the widget (its bounding rectangle)."""
        r, pts = self._rect(), box.corners()
        xs = [r.x() + pt.x() / self.W * r.width() for pt in pts]
        ys = [r.y() + pt.y() / self.H * r.height() for pt in pts]
        return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    def edit_text(self, box):
        self.close_text_box()
        self.text_box = TextBox(self, box.clip["id"], box.clip["text"]["content"])
        self.text_box.edited.connect(lambda cid, words: self.textEdited.emit(cid, words))
        self.text_box.finished.connect(self.close_text_box)
        sr = self._screen_rect(box)
        w = min(max(sr.width() + 24, 220), self.width() - 8)
        h = min(max(sr.height() + 16, 70), self.height() - 8)
        x = min(max(sr.center().x() - w / 2, 4), self.width() - w - 4)
        y = min(max(sr.center().y() - h / 2, 4), self.height() - h - 4)
        self.text_box.setGeometry(round(x), round(y), round(w), round(h))
        self.text_box.show()
        self.text_box.setFocus()
        self.text_box.selectAll()

    def close_text_box(self):
        tb, self.text_box = self.text_box, None
        if tb is not None:
            tb.flush()
            tb.hide()
            tb.deleteLater()


class TextBox(QPlainTextEdit):
    """The words of a text clip typed in on the preview. Changes go out a moment after typing
    stops (and when it closes); Esc puts the words it opened with back."""
    edited = Signal(str, str)                   # clip id, words
    finished = Signal()

    def __init__(self, parent, clip_id, words):
        super().__init__(parent)
        self.clip_id, self.original, self.sent = clip_id, words, words
        self.setPlainText(words)
        self.setToolTip("Ctrl+Enter 或點別的地方完成，Esc 還原")
        self.setStyleSheet("QPlainTextEdit { background: rgba(20, 20, 24, 225); color: #ffffff;"
                           " border: 2px solid #4da3ff; border-radius: 4px; font-size: 15px; }")
        self.timer = QTimer(self, singleShot=True, interval=300)
        self.timer.timeout.connect(self.flush)
        self.textChanged.connect(self.timer.start)

    def flush(self):
        self.timer.stop()
        words = self.toPlainText()
        if words != self.sent:
            self.sent = words
            self.edited.emit(self.clip_id, words)

    def event(self, e):
        if e.type() == QEvent.ShortcutOverride and e.key() in (Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter):
            e.accept()                          # these belong to the box, not the window's shortcuts
            return True
        return super().event(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.setPlainText(self.original)
            self.finished.emit()
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter) and e.modifiers() & Qt.ControlModifier:
            self.finished.emit()
        else:
            super().keyPressEvent(e)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        if e.reason() != Qt.PopupFocusReason:   # (not for its own right-click menu)
            self.finished.emit()


class SeekBar(QWidget):
    """Progress bar of the fullscreen preview: position / length, click or drag to seek."""
    seekRequested = Signal(int)                 # frame
    HEIGHT = 46

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pos, self.length, self.fps = 0, 1, 60.0
        self.dragging = False
        self.setFixedHeight(self.HEIGHT)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def set_position(self, pos, length, fps):
        if (pos, length, fps) != (self.pos, self.length, self.fps):
            self.pos, self.length, self.fps = pos, max(1, length), fps
            self.update()

    @staticmethod
    def _clock(frame, fps):
        s = frame / fps
        return f"{int(s // 60):02d}:{int(s % 60):02d}.{int(round((s % 1) * 100)) % 100:02d}"

    def _track(self):
        return QRectF(88, self.height() / 2 - 2, max(1, self.width() - 176), 4)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(0, 0, 0, 150))
        tr = self._track()
        frac = min(1.0, max(0.0, self.pos / max(1, self.length - 1)))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#4a4a52"))
        p.drawRoundedRect(tr, 2, 2)
        p.setBrush(QColor("#e6e6e6"))
        p.drawRoundedRect(QRectF(tr.x(), tr.y(), tr.width() * frac, tr.height()), 2, 2)
        p.drawEllipse(QPointF(tr.x() + tr.width() * frac, tr.center().y()), 6, 6)
        p.setPen(QColor("#d0d0d2"))
        f = p.font()
        f.setPixelSize(13)
        p.setFont(f)
        p.drawText(QRectF(8, 0, 76, self.height()), Qt.AlignRight | Qt.AlignVCenter, self._clock(self.pos, self.fps))
        p.drawText(QRectF(self.width() - 84, 0, 76, self.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   self._clock(self.length, self.fps))

    def _seek(self, x):
        tr = self._track()
        frac = min(1.0, max(0.0, (x - tr.x()) / tr.width()))
        self.seekRequested.emit(round(frac * (self.length - 1)))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.dragging = True
            self._seek(e.position().x())

    def mouseMoveEvent(self, e):
        if self.dragging:
            self._seek(e.position().x())

    def mouseReleaseEvent(self, e):
        self.dragging = False


class FullscreenPreview(QWidget):
    """Frameless fullscreen copy of the preview with a progress bar along the bottom (it shows
    when the mouse moves and hides after a moment). Esc / double-click closes, Space plays."""
    closed = Signal()
    togglePlay = Signal()
    step = Signal(int)
    seekRequested = Signal(int)                 # frame, from the progress bar

    def __init__(self):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.setStyleSheet("background: black;")
        self.canvas = Preview(self, interactive=False)
        self.canvas.doubleClicked.connect(self.close)
        self.canvas.setMouseTracking(True)
        self.canvas.installEventFilter(self)
        self.bar = SeekBar(self)
        self.bar.seekRequested.connect(self.seekRequested)
        self.hide_timer = QTimer(self, singleShot=True, interval=2500)
        self.hide_timer.timeout.connect(self._hide_bar)
        self.setMouseTracking(True)

    def set_position(self, pos, length, fps):
        self.bar.set_position(pos, length, fps)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.MouseMove:
            self._show_bar()
        return False

    def _show_bar(self):
        self.bar.show()
        self.bar.raise_()
        self.unsetCursor()
        self.hide_timer.start()

    def _hide_bar(self):
        if self.bar.dragging or self.bar.underMouse():
            self.hide_timer.start()
            return
        self.bar.hide()
        self.setCursor(Qt.BlankCursor)

    def showEvent(self, e):
        super().showEvent(e)
        self._show_bar()

    def resizeEvent(self, e):
        self.canvas.setGeometry(self.rect())
        self.bar.setGeometry(0, self.height() - SeekBar.HEIGHT, self.width(), SeekBar.HEIGHT)

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Escape, Qt.Key_F):
            self.close()
        elif k == Qt.Key_Space:
            self.togglePlay.emit()
        elif k in (Qt.Key_Left, Qt.Key_Right):
            self.step.emit(-1 if k == Qt.Key_Left else 1)
        self._show_bar()

    def closeEvent(self, e):
        self.hide_timer.stop()
        self.closed.emit()
        super().closeEvent(e)
