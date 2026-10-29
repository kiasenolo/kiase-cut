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
neighbours, or as far from one as two other clips are apart, shown in pink; Ctrl moves
freely); with Alt held the selection stays and copies of it are dragged instead (dupLive
while dragging, dupCommitted on release: {original clip id: {x, y}}), as in Lunacy. Drag a
corner or edge square to
scale it with the opposite corner / edge staying put (Alt: about its centre; the moving edges
snap to the same lines while the clip is upright or turned by a right angle, Ctrl scales
freely), drag the round
handle above it to rotate (Shift: 15° steps; it also settles on 0 / 90 / 180 / 270). It turns
and scales about its pivot (中心點, the ring with a cross, at its centre unless moved; with Alt a
scale drag keeps the pivot in place): drag the ring to move the pivot (Ctrl+drag while it is at
the centre, where a plain drag moves the clip) - the ring stays where it is and the clip moves the other way (x / y make up for
it) - and it snaps to the clip's centre, corners and edge middles (Shift: freely). With X / Y
scale linked a corner or an edge keeps their ratio; unlinked, a corner sets both freely (Shift
keeps the ratio) and an edge only its own axis. A built-in asset (assets.py) is resized instead:
its 寬 / 高 change and its scale stays (an edge changes one side, a corner both, Shift keeps
their ratio); that drag reports group "multi": {"asset": {w, h}, "transform": {x, y}}. So is a
text with a 文字框 (textlayout.py; not one as big as its words, which scales): an edge sets its
own side's box_w / box_h, a corner both (a box of 自動高度 gets a fixed height), "multi":
{"text": {box_w, box_h}, "transform": {x, y}}.

Mask mode (`mask_mode`, while the 遮罩 tab is open, or 編輯遮罩 of an effect's 範圍 in the
效果 tab: `mask_group` "mask" or "fxmask:<effect id>"; 編輯位置 of an effect's colour source:
"fxsrc:<effect id>:<colour param>", placed like a picture mask) edits only that mask: the clip itself
cannot be moved, scaled or turned there, and a click on another clip just selects it. The
mask outline is drawn where it cuts the clip (dimmed while the mask is switched off). Drag inside it to move it, the squares on its edges / corner to size it, the
round handle to rotate it and the arrow below it for the feather. The mask snaps to the
clip's centre and edges (and to a square, to full size, to feather 0 / 1) while it is dragged; Alt
drags freely. Snapped lines show in amber. A 複合片段 mask is a frame like a rectangle (no
feather) whose corner keeps the compound's proportions (Shift: free); the renderer draws the
compound itself in it (matte_preview, see render.py). 影片 masks are the same.

編輯位置 of a component's image parameter (the 屬性 tab: `mask_group` "place:<param id>") edits
where that picture sits in its layer the same way, through the layer's frame inside the
component (LayerFrame): drag it to move it, its squares to size it (no turning, no feather).

Groups (群組): a group is one box around its clips (GroupBox, through the group's transform):
click one of its clips to select it, then drag it by anything inside its box - its clips or
the space between them - to move it (its transform; scale and turn it in the inspector); double-click picks the clip under the mouse inside it (groupPicked). A clip of a
group selected on the timeline is moved, scaled and turned on the canvas like any clip while
its groups are not moved, scaled or turned.

Align and space (the inspector's buttons, as Lunacy's): align_moves() lines the selected
clips up by their left / centre / right / top / middle / bottom edges (one clip: on the
canvas); spacing() and space_moves() put the same gap between neighbours (in the order of
their centres along the direction they spread in most), a typed gap or their average one;
a negative gap makes them overlap. Both give {clip id: {x / y}} for movesCommitted.

The view is moved about as in Blender's image editor: the wheel zooms around the mouse
(Ctrl+wheel too), the middle button drags the view (Shift+middle too), Ctrl+middle-drag
zooms smoothly (right / up: in), a touchpad's two-finger scroll moves it and its pinch zooms.
Every drag on the canvas is endless (無邊界, wrapdrag.py): the pointer reaching an edge of the
preview jumps to the other one and the drag goes on; what is moved or sized (a clip, a mask, a
selection box) keeps the view following it. The pointer hides while dragging and comes back
where the drag ended up.
With the mouse over the preview (and no text being typed): Home fits the canvas in the view,
numpad . frames the selection, numpad 1 shows it 1:1, numpad 2 / 4 / 8 at 1:2 / 1:4 / 1:8 and
Ctrl+numpad 2 / 4 / 8 at 2:1 / 4:1 / 8:1, numpad + / - zoom in / out, and Shift+B then a drag
zooms into the box dragged (Esc or the right button: not).

Double-clicking a text clip opens a box over it to type its words in (textEdited while
typing, one undo step); Ctrl+Enter or a click elsewhere closes it, Esc puts the words back.

Every drag shows live (paramsLive) and becomes one edit on release (paramsCommitted), in
the project's units: transform x / y in half-canvas units (y up), scale, clockwise degrees;
mask cx / cy in half-material units (y up), w / h as fractions of the material, feather.
A fullscreen window shows the same frames.

While a static compound is open (accept_media), media can be dragged onto the canvas from the
media library, the Library tab, 內建素材, the compound list or the file manager: mediaDropped
reports them and where they were let go (they become the top layer, centred there). With Alt
held, media dropped on a picture clip replace its source (replaceDropped; on one of several
selected clips, all of them: 批量替換), and the clips that would change are outlined. Dropped
on a group (its box lit while they would), they go into it instead (移入群組).
"""
import json
import math

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QPlainTextEdit, QTextEdit,
                               QWidget)

from .. import components, curves, edit, fonts, project, render, textlayout
from . import appevents, wheel
from .wrapdrag import WrapDrag

US = 1_000_000
SNAP_PX = 7
HANDLE_PX = 9                 # handle size on screen
ROT_PX = 34                   # rotation handle distance from the outline
PICK_PX = 9
ANGLE_SNAP = 3.0              # degrees within which rotation settles on a right angle
PIVOT_PICK = 0.7              # the pivot's ring is picked closer than a handle (it sits on the clip)
ZOOM_STEP = 1.25              # one wheel notch (as Blender's)
ZOOM_MIN, ZOOM_MAX = 0.05, 64.0   # view zoom, 1 = the canvas fits the widget
_text_sizes = {}


def text_size(spec, canvas_h):
    """Text box (w, h) in canvas px at scale 1: its 文字框 when it has one (textlayout.boxed),
    else the image drawn for it."""
    key = json.dumps([spec, canvas_h, fonts.map_key()], sort_keys=True, default=str)
    if key not in _text_sizes:
        if textlayout.boxed(spec):
            _text_sizes[key] = textlayout.frame_size(spec, canvas_h)
        else:
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

    def __init__(self, c, W, H, t, shift=(0.0, 0.0)):
        tf = c.get("transform") or {}
        v = lambda k, d: curves.value(tf.get(k, d), t)
        self.bw, self.bh = base_size(c, W, H, t)
        self.s = v("scale", 1.0)
        self.sy = curves.value(tf.get("scale_y", tf.get("scale", 1.0)), t)
        self.clip = c
        self.t = t
        self.W, self.H = W, H
        self.ox, self.oy = shift                # (canvas px: 中心點跟隨最下層物件 moves its clips)
        self.pdx, self.pdy = project.pivot_shift(tf, t, W, H)     # (中心點: turned about its pivot)
        self.pivot = (v("pivot_x", 0.0), v("pivot_y", 0.0))
        self.cx = W / 2 + v("x", 0.0) * W / 2 + self.ox + self.pdx
        self.cy = H / 2 - v("y", 0.0) * H / 2 + self.oy + self.pdy
        self.w, self.h = self.bw * abs(self.s), self.bh * abs(self.sy)
        self.deg = v("rotation", 0.0)
        self.rot = math.radians(self.deg)
        self.flip = (-1 if tf.get("flip_h") else 1, -1 if tf.get("flip_v") else 1)

    def x_at(self, cx, pdx=None):
        """The x value that puts its centre at canvas px cx (pdx: its pivot's shift then,
        when not this box's, project.pivot_shift)."""
        return round((cx - self.ox - (self.pdx if pdx is None else pdx) - self.W / 2) / (self.W / 2), 5)

    def y_at(self, cy, pdy=None):
        return round((self.H / 2 - (cy - self.oy - (self.pdy if pdy is None else pdy))) / (self.H / 2), 5)

    def pivot_local(self):
        """Its pivot (中心點) in its own frame (centre origin, unscaled, y down, canvas px)."""
        return QPointF(self.pivot[0] * self.W / 2, -self.pivot[1] * self.H / 2)

    def pivot_pt(self):
        """Canvas point of its pivot: what it turns and scales about."""
        return self.xf().map(self.pivot_local())

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

    def moved(self, c):
        """This box for c: its clip with the values being dragged."""
        return Box(c, self.W, self.H, self.t, (self.ox, self.oy))

    def rot_handle(self, k):
        """Canvas point of the rotation handle (above the top edge; k = canvas px per screen px)."""
        up = QPointF(math.sin(self.rot), -math.cos(self.rot))
        return QPointF(self.cx, self.cy) + up * (self.h / 2 + ROT_PX * k)


class LayerFrame:
    """The frame of the layer a component instance's image parameter sets (the first it is
    bound to), on the canvas: a stand-in for the instance's Box that MaskGeo edits the
    picture's placement (components.PLACE) in. Its time is the instance's (the placement's
    keyframes are the instance's); None when that layer is not shown now."""

    def __new__(cls, box, pid):
        c = box.clip
        comp = components.of_clip(c)
        p = components.param(comp, pid) if comp else None
        cid = next((k for k, prop in (p or {}).get("binds") or [] if prop == "source"), None)
        if cid is None:
            return None
        content = components.content(c, box.t)
        cw, ch = content["width"], content["height"]
        inner = 0 if project.is_static(c) else project.source_time(c, box.t)
        to_inst = QTransform().translate(-cw / 2, -ch / 2) * QTransform.fromScale(box.bw / cw, box.bh / ch)

        def find(tracks, t, xf):
            for tr in tracks:
                for k in tr["clips"]:
                    lt = t - k["start_us"]
                    if not 0 <= lt < k["duration_us"]:
                        continue
                    if k["id"] == cid:
                        return Box(k, cw, ch, lt), xf
                    if project.is_group(k):
                        hit = find(k["tracks"], lt, group_xf(k, cw, ch, lt) * xf)
                        if hit:
                            return hit
            return None
        hit = find(content["tracks"], inner, QTransform())
        if hit is None:
            return None
        self = super().__new__(cls)
        layer, gxf = hit
        self.inst, self.pid, self.clip, self.t = box, pid, c, box.t
        self.W, self.H = box.W, box.H
        self.bw, self.bh = layer.bw, layer.bh
        self._xf = layer.xf() * gxf * to_inst * box.xf()
        self.s = math.hypot(self._xf.m11(), self._xf.m12()) or 1e-6      # (canvas px per frame px)
        self.sy = math.hypot(self._xf.m21(), self._xf.m22()) or 1e-6
        o = self._xf.map(QPointF(0, 0))
        self.cx, self.cy = o.x(), o.y()
        return self

    def xf(self):
        return self._xf

    def corners(self):
        return [self._xf.map(QPointF(x * self.bw / 2, y * self.bh / 2)) for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1))]

    def moved(self, c):
        return LayerFrame(self.inst.moved(c), self.pid)


def group_xf(g, W, H, t):
    """A group's transform at group time t: its canvas -> the level's (about the centre)."""
    return QTransform().translate(-W / 2, -H / 2) * render.clip_world(g, t, W, H)


def is_identity(xf):
    return xf.isIdentity() or all(abs(a - b) < 1e-9 for a, b in zip(
        (xf.m11(), xf.m12(), xf.m21(), xf.m22(), xf.dx(), xf.dy()), (1, 0, 0, 1, 0, 0)))


class GroupBox(Box):
    """A group on the canvas: the box around its clips' outlines (kids: their Boxes, in the
    group's canvas) mapped through its transform; cx / cy stay its position, so dragging it
    moves the group."""
    group = True

    def __init__(self, c, W, H, t, kids, shift=(0.0, 0.0)):
        super().__init__(c, W, H, t, shift)
        self.kids = kids
        self.gxf = group_xf(c, W, H, t) * QTransform.fromTranslate(*shift)
        pts = [self.gxf.map(q) for b in kids for q in b.corners()] or [QPointF(self.cx, self.cy)]
        xs, ys = [q.x() for q in pts], [q.y() for q in pts]
        self._box = (min(xs), max(xs), min(ys), max(ys))

    def moved(self, c):
        """(Its clips stay where they are in it: only the group's own transform changes.)"""
        return GroupBox(c, self.W, self.H, self.t, self.kids, (self.ox, self.oy))

    def corners(self, dx=0.0, dy=0.0):
        l, r, t, b = self._box
        return [QPointF(l + dx, t + dy), QPointF(r + dx, t + dy), QPointF(r + dx, b + dy), QPointF(l + dx, b + dy)]

    def extents(self):
        return self._box

    def kid_at(self, x, y):
        """The topmost of its clips at canvas point (x, y), or None."""
        inv, ok = self.gxf.inverted()
        if not ok:
            return None
        q = inv.map(QPointF(x, y))
        return next((b for b in self.kids if b.contains(q.x(), q.y())), None)

    def contains(self, x, y):
        return self.kid_at(x, y) is not None

    def grabs(self, x, y):
        """Whether a press at (x, y) takes hold of it once it is selected: anywhere in its box."""
        l, r, t, b = self._box
        return l <= x <= r and t <= y <= b


def grabs(b, x, y):
    """A selected clip is taken hold of where it is (a selected group: anywhere in its box)."""
    return b.grabs(x, y) if getattr(b, "group", False) else b.contains(x, y)


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
        if self.kind in ("rectangle", "circle", "compound", "image", "video", "place"):
            out += [("w", self.xf.map(QPointF(self.hw, 0))), ("h", self.xf.map(QPointF(0, -self.hh))),
                    ("wh", self.xf.map(QPointF(self.hw, -self.hh)))]
        elif self.kind == "mirror":
            out.append(("h", self.xf.map(QPointF(0, -self.hh))))
        if self.kind == "place":                    # (a component's picture is moved and sized, not turned)
            return out
        u, hh = self.down()
        c = self.centre()
        out.append(("rot", c - u * (hh + ROT_PX * k)))
        if self.kind not in ("compound", "image", "video"):              # (a picture mask has no feather)
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
    groupPicked = Signal(object)                # a group's clip picked by double-clicking the group
    dupLive = Signal(dict)                      # {clip id: {x, y}}: copies of them dragged there (Alt)
    dupCommitted = Signal(dict)                 # the same on release: make the copies
    doubleClicked = Signal()
    textEdited = Signal(str, str)               # text clip id, its words: typed in on the canvas
    renderWidth = Signal(int)                   # width of the canvas on screen, device px
    mediaDropped = Signal(list, list, float, float, str)  # idents, file paths, transform x / y there, group id or ""
    replaceDropped = Signal(str, str)           # media ident, clip it was Alt-dropped on (替換素材)

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
        self.box_zoom = False                   # Shift+B: the next left drag is a box to zoom into
        self.wrap = WrapDrag(self, lambda: QRectF(self.rect()))
        self.setMinimumSize(320, 180)
        self.setMouseTracking(True)
        self.accept_media = False               # media may be dropped on it (a static compound is open)
        self.drop_at = None                     # canvas point a drag from elsewhere is over
        self.drop_replace = []                  # boxes an Alt-drop there would give its media to
        self.drop_group = None                  # the group box a drop there would go into
        self.setAcceptDrops(interactive)
        if interactive:                          # its keys work while the mouse is over it (see _view_key)
            appevents.watch(self, (QEvent.ShortcutOverride, QEvent.KeyPress), self.eventFilter)

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
        """The mask that mask mode edits on clip (編輯位置: a component picture's placement), or None."""
        if self.mask_group.startswith("place:"):
            p = components.param(components.of_clip(clip), self.mask_group[6:]) if components.of_clip(clip) else None
            return components.place_of(clip, p["id"]) if p and p["kind"] == "image" else None
        try:
            return edit.holder(clip, self.mask_group)
        except (edit.EditError, KeyError):
            return None

    def mask_box(self, box):
        """What mask mode edits in: the clip's box, or for 編輯位置 its layer's frame (or None)."""
        if box is not None and self.mask_mode and self.mask_group.startswith("place:"):
            return LayerFrame(box, self.mask_group[6:])
        return box

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

    def _fit_size(self):
        """(w, h) the canvas has on the widget at zoom 1."""
        w, h = self.width(), self.height()
        a = self.W / self.H
        return (h * a, h) if w / max(1, h) > a else (w, w / a)

    def zoom_to(self, z, at=None):
        """Zoom the view to z, the canvas point under at (widget px; the middle) staying there."""
        z = min(ZOOM_MAX, max(ZOOM_MIN, z))
        at = QPointF(self.width() / 2, self.height() / 2) if at is None else QPointF(at)
        cx, cy = self._to_canvas(at)
        self.zoom = z
        r = self._rect()
        self.pan += at - QPointF(r.x() + cx / self.W * r.width(), r.y() + cy / self.H * r.height())
        self._view_changed()

    def view_fit(self):
        self.zoom, self.pan = 1.0, QPointF(0, 0)
        self._view_changed()

    def view_ratio(self, ratio):
        """Canvas pixels at ratio screen pixels each (1: 1:1), about the middle of the view."""
        fw, _ = self._fit_size()
        self.zoom_to(self.W * ratio / self.devicePixelRatioF() / max(1.0, fw))

    def view_rect(self, l, r, t, b, margin=0.1):
        """Zoom and move the view so the canvas rectangle (left, right, top, bottom) fills it."""
        fw, fh = self._fit_size()
        w, h = max(1.0, r - l), max(1.0, b - t)
        z = min(ZOOM_MAX, max(ZOOM_MIN, min(self.W / w, self.H / h) / (1 + 2 * margin)))
        dw, dh = fw * z, fh * z
        self.zoom = z
        self.pan = QPointF(dw * (0.5 - (l + r) / 2 / self.W), dh * (0.5 - (t + b) / 2 / self.H))
        self._view_changed()

    def view_selected(self):
        boxes = self._picked_boxes()
        if boxes:
            self.view_rect(*self._union(boxes))
        else:
            self.view_fit()

    def _view_changed(self):
        if self.text_box is not None:                    # it stays over its clip
            box = next((b for b in self.visible_boxes() if b.clip["id"] == self.text_box.clip_id), None)
            if box is not None:
                self._place_text_box(box)
        self._report_size()
        self.update()

    def wheelEvent(self, e):
        if not self.interactive:
            return
        e.accept()
        if wheel.touchpad(e) and not e.modifiers() & Qt.ControlModifier:   # two-finger scroll: moves the view
            self.pan += QPointF(e.pixelDelta())
            self._view_changed()
            return
        n = wheel.notch(e)
        if n:
            self.zoom_to(self.zoom * ZOOM_STEP ** n, e.position())

    def event(self, e):
        f = wheel.pinch(e) if self.interactive else None
        if f is not None:                                # a touchpad's pinch
            self.zoom_to(self.zoom * f, e.position())
            return True
        return super().event(e)

    def _typing(self):
        w = QApplication.focusWidget()
        return isinstance(w, (QLineEdit, QAbstractSpinBox, QPlainTextEdit, QTextEdit)) or (
            isinstance(w, QComboBox) and w.isEditable())

    def _view_key(self, e):
        """The view action of key event e, or None: only while the mouse is over the preview, as
        in Blender (the area under the mouse gets the keys), and nothing is being typed."""
        if not self.view or not self.isVisible() or not self.underMouse() or self._typing():
            return None
        k, mods = e.key(), e.modifiers()
        pad = bool(mods & Qt.KeypadModifier)
        ctrl, shift = bool(mods & Qt.ControlModifier), bool(mods & Qt.ShiftModifier)
        if k == Qt.Key_Home and not ctrl:
            return self.view_fit
        if pad and k in (Qt.Key_Period, Qt.Key_Comma):
            return self.view_selected
        ratios = {Qt.Key_1: 1, Qt.Key_2: 2, Qt.Key_4: 4, Qt.Key_8: 8}
        if pad and k in ratios and not (ctrl and ratios[k] == 1):
            n = ratios[k]
            return lambda: self.view_ratio(n if ctrl else 1 / n)
        if pad and k in (Qt.Key_Plus, Qt.Key_Minus):
            return lambda: self.zoom_to(self.zoom * (ZOOM_STEP if k == Qt.Key_Plus else 1 / ZOOM_STEP))
        if k == Qt.Key_B and shift and not ctrl:
            return self._arm_box_zoom
        if k == Qt.Key_Escape and self.box_zoom:
            return lambda: self._arm_box_zoom(False)
        return None

    def eventFilter(self, obj, e):
        t = e.type()
        if t in (QEvent.ShortcutOverride, QEvent.KeyPress) and isinstance(obj, QWidget) and obj.window() is self.window():
            act = self._view_key(e)
            if act is not None:
                if t == QEvent.KeyPress:
                    act()
                e.accept()                               # (ShortcutOverride: no menu shortcut takes it)
                return True
        return False

    def _arm_box_zoom(self, on=True):
        self.box_zoom = on
        self.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)

    # -- drops ------------------------------------------------------------------------------------
    def _takes(self, md):
        from .timeline import MEDIA_MIME
        return self.accept_media and self.view is not None and (md.hasFormat(MEDIA_MIME) or md.hasUrls())

    def dragEnterEvent(self, e):
        if self._takes(e.mimeData()):
            e.setDropAction(Qt.CopyAction)
            e.accept()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if not self._takes(e.mimeData()):
            e.ignore()
            return
        self.drop_replace = self._replace_boxes(e)
        self.drop_at = None if self.drop_replace else QPointF(*self._to_canvas(e.position()))
        self.drop_group = None if self.drop_replace else self._group_at(*self._to_canvas(e.position()))
        e.setDropAction(Qt.CopyAction)
        e.accept()
        self.update()

    def dragLeaveEvent(self, e):
        self.drop_at, self.drop_replace, self.drop_group = None, [], None
        self.update()

    def _group_at(self, x, y):
        """The topmost group box (not locked) at canvas point x, y, or None."""
        return next((b for b in self.visible_boxes() if getattr(b, "group", False) and not b.locked
                     and b.contains(x, y)), None)

    def _replace_boxes(self, e):
        """With Alt held, media over a picture clip replace its source: its box, and the other
        selected picture clips' when it is selected (批量替換)."""
        from PySide6.QtWidgets import QApplication
        from .timeline import MEDIA_MIME
        alt = (e.modifiers() | QApplication.queryKeyboardModifiers()) & Qt.AltModifier
        if not alt or not e.mimeData().hasFormat(MEDIA_MIME):
            return []
        x, y = self._to_canvas(e.position())
        boxes = [b for b in self.visible_boxes() if not b.locked]
        hit = next((b for b in boxes if b.clip["type"] in edit.REPLACEABLE and b.contains(x, y)), None)
        if hit is None:
            return []
        if hit.clip["id"] not in self.selected_ids:
            return [hit]
        return [hit] + [b for b in boxes if b is not hit and b.clip["id"] in self.selected_ids
                        and b.clip["type"] in edit.REPLACEABLE]

    def dropEvent(self, e):
        from .timeline import MEDIA_MIME
        lit = self._replace_boxes(e) if self._takes(e.mimeData()) else []
        self.drop_at, self.drop_replace, self.drop_group = None, [], None
        self.update()
        md = e.mimeData()
        if not self._takes(md):
            return
        if lit:                                          # Alt: the clip's (clips') source
            self.replaceDropped.emit(bytes(md.data(MEDIA_MIME)).decode("utf-8").split(",")[0], lit[0].clip["id"])
            e.setDropAction(Qt.CopyAction)
            e.accept()
            return
        x, y = self._to_canvas(e.position())
        tx, ty = round((x - self.W / 2) / (self.W / 2), 5), round((self.H / 2 - y) / (self.H / 2), 5)
        g = self._group_at(x, y)
        gid = g.clip["id"] if g is not None else ""
        if md.hasFormat(MEDIA_MIME):
            ids = [i for i in bytes(md.data(MEDIA_MIME)).decode("utf-8").split(",") if i]
            self.mediaDropped.emit(ids, [], tx, ty, gid)
        else:
            self.mediaDropped.emit([], [u.toLocalFile() for u in md.urls() if u.isLocalFile()], tx, ty, gid)
        e.setDropAction(Qt.CopyAction)
        e.accept()

    def _to_canvas(self, pos):
        r = self._rect()
        return (pos.x() - r.x()) / r.width() * self.W, (pos.y() - r.y()) / r.height() * self.H

    def _k(self):
        """Canvas px per screen px."""
        return self.W / max(1.0, self._rect().width())

    def visible_boxes(self):
        """Boxes of clips showing now, topmost first (a group as one GroupBox; a selected clip
        of a group that is not moved, scaled or turned as a box of its own, first)."""
        if not self.view:
            return []
        picked = []
        fps = self.view["fps"]

        def boxes(tracks, t_us, locked, plain, nested=False, g=None):
            out = []
            for tr in reversed(tracks):
                if tr["kind"] == "audio" or tr.get("hidden"):
                    continue
                ax, ay = project.anchored(g, tr, t_us) if g is not None else (0.0, 0.0)
                shift = (ax * self.W / 2, -ay * self.H / 2)
                for c in tr["clips"]:
                    if c["type"] == "filter" and not (self.mask_mode and c["id"] == self.selected_id):
                        continue                # a filter covers the whole picture: only its mask is edited here
                    if not render.on_frame(c, t_us, fps) or c.get("transform") is None:
                        continue
                    t = t_us - c["start_us"]
                    lock = locked or project.locked(tr)     # (shown and snapped to, never picked)
                    if project.is_group(c):
                        inner = plain and is_identity(group_xf(c, self.W, self.H, t) * QTransform.fromTranslate(*shift))
                        b = GroupBox(c, self.W, self.H, t, boxes(c["tracks"], t, lock, inner, True, c), shift)
                    else:
                        b = Box(c, self.W, self.H, t, shift)
                        if nested and plain and c["id"] in self.selected_ids:
                            b.locked = lock
                            picked.append(b)
                    b.locked = lock
                    out.append(b)
            return out
        top = boxes(self.view["tracks"], self.t_us, False, True)
        return picked + top

    def group_kid(self, x, y):
        """The clip under canvas point (x, y) inside the topmost group there (double-click)."""
        for b in self.visible_boxes():
            if getattr(b, "group", False) and not b.locked and b.contains(x, y):
                kid = b.kid_at(x, y)
                while getattr(kid, "group", False):     # into nested groups, as deep as it goes
                    inv, _ = b.gxf.inverted()
                    q = inv.map(QPointF(x, y))
                    b, kid = kid, kid.kid_at(q.x(), q.y())
                    x, y = q.x(), q.y()
                return kid.clip if kid is not None else None
        return None

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
                    b = b.moved(dict(b.clip, transform=dict(b.clip["transform"], **moves[b.clip["id"]])))
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
            holder = c if g == "clip" else edit.holder(c, g) if g.startswith(("fxmask:", "fxsrc:", "place:")) else c.setdefault(g, {})
            holder.update(edit.with_linked_scale(holder, v, box.t) if g == "transform" else v)
        return box.moved(c)

    def masking(self, box):
        if not self.mask_mode or box is None or not self.mask_of(box.clip):
            return False
        return self.mask_group != "mask" or box.clip["type"] in edit.MASKABLE

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
        if self.zoom != 1.0 or self.pan != QPointF(0, 0):
            p.setPen(QColor("#9a9aa0"))
            px = r.width() * self.devicePixelRatioF() / self.W * 100     # as canvas pixels to screen pixels
            p.drawText(QRectF(8, 6, 260, 18), Qt.AlignLeft, f"{px:.0f}%（Home：適應視窗）")
        if self.box_zoom:
            p.setPen(QColor("#9a9aa0"))
            p.drawText(QRectF(8, 24, 260, 18), Qt.AlignLeft, "拖出要放大的範圍（Esc：取消）")
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(r.x(), r.y())
        p.scale(r.width() / self.W, r.height() / self.H)
        k = self._k()
        box = self._live_box()
        mbox = self.mask_box(box)
        if self.multi():
            self._paint_group(p, k)
        elif box is not None:
            if mbox is not None and self.masking(mbox):
                self._paint_mask(p, mbox, k)
            elif self.mask_mode:                         # no mask: just where the clip is
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(255, 255, 255, 120), 1 * k, Qt.DashLine))
                p.drawPolygon(QPolygonF(box.corners()))
            else:
                self._paint_transform(p, box, k)
        if self.drag and self.drag["kind"] == "zoombox" and self.drag["moved"]:
            p.setPen(QPen(QColor("#e6e6e6"), 1 * k, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(self.drag["rect"])
        if self.drag and self.drag["kind"] == "marquee" and self.drag["moved"]:
            p.setPen(QPen(QColor("#e6e6e6"), 1 * k, Qt.DashLine))
            p.setBrush(QColor(255, 255, 255, 28))
            p.drawRect(self.drag["rect"])
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor("#ffffff"), 1.5 * k))
            for b in self.drag["hits"]:
                p.drawPolygon(QPolygonF(b.corners()))
        for i, b in enumerate(self.drop_replace):         # an Alt-drop's clips (替換素材)
            p.setPen(QPen(QColor("#ffb020"), 2 * k))
            p.setBrush(QColor(255, 176, 32, 40))
            p.drawPolygon(QPolygonF(b.corners()))
            if i == 0:
                n = len(self.drop_replace)
                f = p.font()
                f.setPixelSize(round(14 * k))
                p.setFont(f)
                p.setPen(QColor("#ffd34d"))
                p.drawText(b.corners()[0] + QPointF(6 * k, -6 * k), "替換素材" + (f"（{n} 個）" if n > 1 else ""))
        p.setBrush(Qt.NoBrush)
        if self.drop_group is not None:                  # dropped media go into this group
            b = self.drop_group
            p.setPen(QPen(QColor("#b48ee0"), 2 * k))
            p.setBrush(QColor(122, 92, 150, 40))
            p.drawPolygon(QPolygonF(b.corners()))
            p.setBrush(Qt.NoBrush)
            f = p.font()
            f.setPixelSize(round(14 * k))
            p.setFont(f)
            p.setPen(QColor("#d6bdf5"))
            p.drawText(b.corners()[0] + QPointF(6 * k, -6 * k), "移入群組：" + (b.clip.get("name") or ""))
        if self.drop_at is not None:                     # where dropped media will be centred
            d = self.drop_at
            p.setPen(QPen(QColor("#4aa3ff"), 1.5 * k))
            p.drawLine(d - QPointF(14 * k, 0), d + QPointF(14 * k, 0))
            p.drawLine(d - QPointF(0, 14 * k), d + QPointF(0, 14 * k))
            p.drawEllipse(d, 6 * k, 6 * k)
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
        if getattr(box, "group", False):                # a group: its outline only (moved by dragging)
            p.setPen(QPen(QColor("#c9a0ff"), 1 * k, Qt.DashLine))
            for kid in box.kids:
                p.drawPolygon(QPolygonF([box.gxf.map(q) for q in kid.corners()]))
            return
        top = (pts[0] + pts[1]) / 2
        rh = box.rot_handle(k)
        p.setPen(QPen(QColor("#ffffff"), 1 * k))
        p.drawLine(top, rh)
        for _sx, _sy, pt in box.handles():
            self._handle(p, pt, k)
        self._handle(p, rh, k, round_=True, color="#e6e6e6")
        pv, r = box.pivot_pt(), 5 * k                          # 中心點: a ring with a cross
        for w, col in ((3 * k, "#111114"), (1.25 * k, "#ffffff")):
            p.setPen(QPen(QColor(col), w))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(pv, r, r)
            p.drawLine(pv - QPointF(2 * r, 0), pv + QPointF(2 * r, 0))
            p.drawLine(pv - QPointF(0, 2 * r), pv + QPointF(0, 2 * r))
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
                    out[b.clip["id"]] = {"x": b.x_at(b.cx + pos - lo)}
                else:
                    out[b.clip["id"]] = {"y": b.y_at(b.cy + pos - lo)}
            pos += hi - lo + gap
        return out

    # -- align and space (the inspector's buttons) ------------------------------------------------
    ALIGNS = ("left", "hcenter", "right", "top", "vcenter", "bottom")

    def _picked_boxes(self):
        return [b for b in self.visible_boxes() if b.clip["id"] in self.selected_ids and not b.locked]

    def _kid_boxes(self):
        """{clip id: (its Box in its group's canvas, the GroupBox)} of the selected clips inside groups."""
        out = {}

        def walk(bs):
            for b in bs:
                if getattr(b, "group", False):
                    for k in b.kids:
                        if k.clip["id"] in self.selected_ids and not k.locked:
                            out[k.clip["id"]] = (k, b)
                    walk(b.kids)
        walk(self.visible_boxes())
        return out

    def align_moves(self, how):
        """{clip id: {x} or {y}} lining the selected clips up by how (ALIGNS): to the box around
        them all, or one clip to the canvas - one inside a group to the box around the group's
        clips (all in the group's own canvas, so a moved or scaled group works too)."""
        boxes = self._picked_boxes()
        kids = self._kid_boxes()
        outer = {id(g): g for _, g in kids.values()}
        if len(outer) == 1 and all(b.clip["id"] in kids for b in boxes):
            boxes = [k for k, _ in kids.values()]
            g = next(iter(outer.values()))
            ref = boxes if len(boxes) > 1 else g.kids if len(g.kids) > 1 else None
        else:
            ref = boxes if len(boxes) > 1 else None
        if not boxes:
            return {}
        l, r, t, b = self._union(ref) if ref else (0, self.W, 0, self.H)
        out = {}
        for bx in boxes:
            e = bx.extents()
            if how in ("left", "hcenter", "right"):
                d = {"left": l - e[0], "right": r - e[1], "hcenter": (l + r) / 2 - (e[0] + e[1]) / 2}[how]
                out[bx.clip["id"]] = {"x": bx.x_at(bx.cx + d)}
            else:
                d = {"top": t - e[2], "bottom": b - e[3], "vcenter": (t + b) / 2 - (e[2] + e[3]) / 2}[how]
                out[bx.clip["id"]] = {"y": bx.y_at(bx.cy + d)}
        return out

    def spacing(self):
        """(axis, [gaps]) between the selected clips in the order of their centres along the
        axis they spread in most ("x" or "y"; gaps may be negative), or None for fewer than two."""
        boxes = self._picked_boxes()
        if len(boxes) < 2:
            return None
        ex = [b.extents() for b in boxes]
        cx = [(e[0] + e[1]) / 2 for e in ex]
        cy = [(e[2] + e[3]) / 2 for e in ex]
        axis = "x" if max(cx) - min(cx) >= max(cy) - min(cy) else "y"
        lo, hi = (0, 1) if axis == "x" else (2, 3)
        order = sorted(ex, key=lambda e: (e[lo] + e[hi]) / 2)
        return axis, [n[lo] - p[hi] for p, n in zip(order, order[1:])]

    def space_moves(self, gap=None):
        """{clip id: {x} or {y}} with the same gap between every two neighbours (spacing()):
        gap canvas px, or (None) their average gap; the first one stays where it is."""
        sp = self.spacing()
        if sp is None:
            return {}
        axis, gaps = sp
        if gap is None:
            gap = sum(gaps) / len(gaps)
        lo, hi = (0, 1) if axis == "x" else (2, 3)
        boxes = sorted(self._picked_boxes(), key=lambda b: (b.extents()[lo] + b.extents()[hi]) / 2)
        pos, out = None, {}
        for b in boxes:
            e = b.extents()
            pos = e[lo] if pos is None else pos
            d = pos - e[lo]
            if axis == "x":
                out[b.clip["id"]] = {"x": b.x_at(b.cx + d)}
            else:
                out[b.clip["id"]] = {"y": b.y_at(b.cy + d)}
            pos += e[hi] - e[lo] + gap
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
        if g.kind != "place":                  # the mask only matters inside the clip (a picture may go past its frame)
            p.setClipPath(clip)
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
        if self.interactive and e.button() == Qt.MiddleButton:       # Ctrl: zoom, else move the view
            zoom = bool(e.modifiers() & Qt.ControlModifier)
            self.drag = {"kind": "zoomdrag" if zoom else "pan", "pos": e.position(), "pan": QPointF(self.pan),
                         "zoom": self.zoom, "moved": False}
            self.setCursor(Qt.SizeVerCursor if zoom else Qt.ClosedHandCursor)
            return
        if self.box_zoom and e.button() == Qt.RightButton:
            self._arm_box_zoom(False)
            return
        if not self.interactive or e.button() != Qt.LeftButton or not self.view:
            return
        x, y = self._to_canvas(e.position())
        m = QPointF(x, y)
        if self.box_zoom:
            self.drag = {"kind": "zoombox", "m0": m, "moved": False, "rect": QRectF(m, m)}
            return
        k = self._k()
        box = self.selected_box()
        mbox = self.mask_box(box)
        if mbox is not None and self.masking(mbox):
            g = MaskGeo(mbox, self.mask_of(box.clip))
            hit = next((n for n, pt in g.handles(k) if self._near(pt, m, k)), None)
            if hit is None and (g.contains(m) or self._near(g.centre(), m, k)):
                hit = "move"
            if hit is not None:
                self.drag = {"kind": hit, "box": mbox, "geo": g, "m0": m, "moved": False}
                return
        elif box is not None and not self.mask_mode and not self.multi() and not getattr(box, "group", False):
            if self._near(box.rot_handle(k), m, k):
                self.drag = {"kind": "rotate", "box": box, "m0": m, "moved": False}
                return
            if self._grabs_pivot(box, m, k, e.modifiers()):
                self.drag = {"kind": "pivot", "box": box, "m0": m, "moved": False}
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
        sel = next((b for b in pickable if b.clip["id"] in self.selected_ids and grabs(b, x, y)), None)
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
            d["dup"] = bool(e.modifiers() & Qt.AltModifier)    # Alt: copies move, the clips stay
            if e.modifiers() & Qt.ControlModifier:             # Ctrl: move freely
                self.guides = []
            else:
                dx, dy, self.guides = self._snap(self._union(boxes), dx, dy, [o.extents() for o in d["others"]],
                                                 SNAP_PX * self._k())
            at = {b.clip["id"]: {"x": b.x_at(b.cx + dx), "y": b.y_at(b.cy + dy)} for b in boxes}
            return ("moves", at) if len(boxes) > 1 or d["dup"] else ("transform", at[box.clip["id"]])
        if kind == "gap":
            along = m.x() - d["m0"].x() if d["axis"] == "x" else m.y() - d["m0"].y()
            return "moves", self._spread(d["boxes"], d["axis"], max(0.0, round(d["gap0"] + along)))
        c = QPointF(box.cx, box.cy)
        if kind == "scale":
            return self._scale_values(box, d, m, e.modifiers())
        if kind == "pivot":
            return "transform", self._pivot_values(box, m, e.modifiers())
        if kind == "rotate":
            c = box.pivot_pt()                                 # (中心點: it turns about its pivot)
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
        if kind == "wh" and g.kind in ("compound", "image", "video", "place") and not free:   # a picture keeps its proportions (Shift: free)
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
        framed = box.clip["type"] == "text" and textlayout.boxed(box.clip["text"])     # (its 文字框 is resized)
        tied = bool((edit.linked(tf) and not (asset or framed)) or (sx and sy and mods & Qt.ShiftModifier))
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
        if asset or framed:                                    # its own size changes, not the scale
            w0, h0 = box.bw, box.bh
            nw, nh = max(1.0, w0 * kx), max(1.0, h0 * ky)
            kx, ky = nw / w0, nh / h0
            if asset:
                vals = {"asset": {"w": round(nw, 1), "h": round(nh, 1)}, "transform": {}}
            else:                                              # (an edge fixes its own side: 自動高度 -> 固定大小)
                k = 1080 / box.H
                vals = {"text": {f: round(n * k, 1) for f, n, on in (("box_w", nw, sx), ("box_h", nh, sy)) if on},
                        "transform": {}}
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
            pdx, pdy = (box.pdx, box.pdy) if asset or framed else project.pivot_shift(
                tf, box.t, box.W, box.H, scale=out["scale"], scale_y=out["scale_y"])
            out.update(x=box.x_at(cx, pdx), y=box.y_at(cy, pdy))
        if (asset or framed) and not out:
            del vals["transform"]
        return ("multi" if asset or framed else "transform"), vals

    def _grabs_pivot(self, box, m, k, mods):
        """Whether a press at m takes the pivot's ring: once it is off the centre, else with
        Ctrl (a plain press at the centre moves the clip)."""
        return self._near(box.pivot_pt(), m, k * PIVOT_PICK) and (
            any(abs(v) > 1e-9 for v in box.pivot) or bool(mods & Qt.ControlModifier))

    def _pivot_values(self, box, m, mods):
        """pivot_x / pivot_y of a drag of the pivot (中心點) to canvas point m, and x / y so
        that the pivot stays where it is on the canvas (the clip moves the other way: the pivot
        is only what it turns and scales about, x / y say where the pivot is). It snaps to the clip's centre, corners and edge
        middles (Shift: freely)."""
        inv, ok = box.xf().inverted()
        if not ok:
            return {}
        q = inv.map(m)
        if not mods & Qt.ShiftModifier:
            tol = SNAP_PX * self._k()
            spots = [QPointF(sx * box.bw / 2, sy * box.bh / 2) for sx in (-1, 0, 1) for sy in (-1, 0, 1)]
            dist = lambda s: math.hypot(box.xf().map(s).x() - m.x(), box.xf().map(s).y() - m.y())
            near = min(spots, key=dist)
            if dist(near) <= tol:
                q = near
        px, py = round(q.x() / (box.W / 2), 5), round(-q.y() / (box.H / 2), 5)
        tf = box.clip.get("transform") or {}
        x0, y0 = curves.value(tf.get("x", 0.0), box.t), curves.value(tf.get("y", 0.0), box.t)
        return {"pivot_x": px, "pivot_y": py,
                "x": round(x0 + box.pivot[0] - px, 5), "y": round(y0 + box.pivot[1] - py, 5)}

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

    FOLLOW = {"move", "scale", "marquee", "zoombox", "w", "h", "wh"}     # drags the view keeps in sight

    def _follow(self, p):
        """Pan so screen point p (where a drag is, on the view as it is now) is in the preview."""
        r = QRectF(self.rect())
        dx = min(0.0, p.x() - r.left()) + max(0.0, p.x() - r.right())
        dy = min(0.0, p.y() - r.top()) + max(0.0, p.y() - r.bottom())
        if dx or dy:
            self.pan -= QPointF(dx, dy)
            self._view_changed()

    def mouseMoveEvent(self, e):
        d = self.drag
        if d is None:
            self._hover(e)
            return
        if "wrap_pan" not in d:                          # (this drag's first move)
            self.wrap.start()
            d["wrap_pan"] = QPointF(self.pan)
        pos = self.wrap.pos(e)
        if d["kind"] == "pan":
            self.pan = d["pan"] + pos - d["pos"]
            self._view_changed()
            return
        if d["kind"] == "zoomdrag":                      # right / up: in
            v = pos - d["pos"]
            want = d["zoom"] * 2 ** ((v.x() - v.y()) / 200)
            self.zoom_to(want, d["pos"])
            return
        # the drag counts on the view as it was when it began (the view may follow it since)
        d["live"] = pos + self.pan - d["wrap_pan"]
        x, y = self._to_canvas(d["live"])
        m = QPointF(x, y)
        if not d["moved"]:
            m0 = d["m0"] if "m0" in d else QPointF(d["x0"], d["y0"])
            if math.hypot(m.x() - m0.x(), m.y() - m0.y()) < 3 * self._k():
                return
        d["moved"] = True
        if d["kind"] in self.FOLLOW:
            self._follow(d["live"])
            d["live"] = pos + self.pan - d["wrap_pan"]
        if d["kind"] == "zoombox":
            d["rect"] = QRectF(d["m0"], m).normalized()
            self.update()
            return
        if d["kind"] == "marquee":
            d["rect"] = QRectF(d["m0"], m).normalized()
            d["hits"] = self._marquee_hits(d["rect"])
            self.update()
            return
        group, vals = self._values(e, m)
        if group == "mask":
            group = self.mask_group
        self.live = (group, vals)
        if group == "moves" and d.get("dup"):
            self.dupLive.emit(vals)
        elif group == "moves":
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
        if not self.interactive or not self.view or self.box_zoom:
            return
        x, y = self._to_canvas(e.position())
        m, k = QPointF(x, y), self._k()
        box = self.selected_box()
        cur = Qt.ArrowCursor
        hover = None
        mbox = self.mask_box(box)
        if mbox is not None and self.masking(mbox):
            g = MaskGeo(mbox, self.mask_of(box.clip))
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
            elif any(grabs(bx, x, y) for bx in boxes):
                cur, hover = Qt.SizeAllCursor, "group"
            elif l - pad <= x <= r + pad and t - pad <= y <= b + pad:
                hover = "group"
        elif box is not None and not self.mask_mode:
            if self._near(box.rot_handle(k), m, k):
                cur = Qt.PointingHandCursor
            elif not getattr(box, "group", False) and self._grabs_pivot(box, m, k, e.modifiers()):
                cur = Qt.CrossCursor
            elif (side := next(((sx, sy) for sx, sy, pt in box.handles() if self._near(pt, m, k)), None)):
                sx, sy = side
                cur = (Qt.SizeHorCursor if not sy else Qt.SizeVerCursor if not sx else
                       Qt.SizeFDiagCursor if sx == sy else Qt.SizeBDiagCursor)
            elif grabs(box, x, y):
                cur = Qt.SizeAllCursor
        if hover != self.gap_hover:                      # the gap bars show while over the selection
            self.gap_hover = hover
            self.update()
        self.setCursor(cur)

    def mouseReleaseEvent(self, e):
        d, self.drag = self.drag, None
        self.wrap.stop(d and d.get("live"))            # (the pointer where the drag ended up)
        if d and d["kind"] in ("pan", "zoomdrag"):
            self.setCursor(Qt.CrossCursor if self.box_zoom else Qt.ArrowCursor)
            return
        if d and d["kind"] == "zoombox":
            self._arm_box_zoom(False)
            if d["moved"]:
                rc = d["rect"]
                self.view_rect(rc.left(), rc.right(), rc.top(), rc.bottom(), margin=0)
            self.update()
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
            if live[0] == "moves" and d.get("dup"):
                self.dupCommitted.emit(live[1])
            elif live[0] == "moves":
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
        if hit is not None and getattr(hit, "group", False):       # into the group: the clip under the mouse
            kid = self.group_kid(x, y)
            if kid is not None:
                self.drag = None
                self.selected_id, self.selected_ids = kid["id"], {kid["id"]}
                self.groupPicked.emit(kid)
                self.update()
            return
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
        self._place_text_box(box)
        self.text_box.show()
        self.text_box.setFocus()
        self.text_box.selectAll()

    def _place_text_box(self, box):
        sr = self._screen_rect(box)
        w = min(max(sr.width() + 24, 220), self.width() - 8)
        h = min(max(sr.height() + 16, 70), self.height() - 8)
        x = min(max(sr.center().x() - w / 2, 4), self.width() - w - 4)
        y = min(max(sr.center().y() - h / 2, 4), self.height() - h - 4)
        self.text_box.setGeometry(round(x), round(y), round(w), round(h))

    def close_text_box(self):
        tb, self.text_box = self.text_box, None
        if tb is not None:
            tb.flush()
            tb.hide()
            tb.deleteLater()


class TextBox(QPlainTextEdit):
    """The words of a text clip typed in on the preview. Changes go out a moment after typing
    stops (and when it closes); Esc puts the words it opened with back. A click anywhere else
    in the program finishes it, as Ctrl+Enter does (the click still does what it does there):
    the preview itself, among others, never takes the focus away, so losing it is not enough."""
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
        self.done = False
        self.watch = ClickOutside(self)
        self.finished.connect(self._finish)

    def _finish(self):
        if not self.done:
            self.done = True
            self.watch.stop()

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
        if e.reason() != Qt.PopupFocusReason and not self.done:   # (not for its own right-click menu)
            self.finished.emit()


class ClickOutside(QObject):
    """Watches every mouse press in the program while a TextBox is open: one outside it (and
    outside a popup, such as its own right-click menu) finishes it."""

    def __init__(self, box):
        super().__init__(box)
        self.box = box
        QApplication.instance().installEventFilter(self)

    def stop(self):
        QApplication.instance().removeEventFilter(self)

    def eventFilter(self, obj, e):
        if (e.type() == QEvent.MouseButtonPress and isinstance(obj, QWidget) and not self.box.done
                and obj is not self.box and not self.box.isAncestorOf(obj)
                and obj.window().windowType() != Qt.Popup):
            self.box.finished.emit()
        return False


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
