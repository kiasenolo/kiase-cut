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
handle above it to rotate (a picture, video or compound clip also has a round handle inside each corner for 圓角: drag it in / out, Shift: all four) (Shift: 15° steps; it also settles on 0 / 90 / 180 / 270). It turns
and scales about its pivot (中心點, the ring with a cross, at its centre unless moved; with Alt a
scale drag keeps the pivot in place): drag the ring to move the pivot (Ctrl+drag while it is at
the centre, where a plain drag moves the clip) - x / y stay (a turned or scaled clip swings round the new pivot, as with CSS transform-origin) - and it snaps to the clip's centre, corners and edge middles (Shift: freely). With X / Y
scale linked a corner or an edge keeps their ratio; unlinked, a corner sets both freely (Shift
keeps the ratio) and an edge only its own axis. The anchor (錨點, the orange diamond: the point of the clip that 位置 places, unmoved while the pivot is) is dragged like the pivot (Alt+drag while it is at the centre): the diamond stays and the clip moves the other way. A picture, video or compound clip also has a round handle inside each corner for 圓角 (drag it in or out, Shift: all four; radius_*). A built-in asset (assets.py) is resized instead:
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
Alt held over another clip (or the canvas) while clips are selected shows the distances between the selection and it, in canvas px (measure).
Rulers (標尺, 檢視 menu, the canvas keeps clear of them): a drag out of the top ruler makes a flat reference line, out of the left one
an upright one (the project's / compound's "guides": {"x": [px], "y": [px]}; guidesCommitted); drag one in the open to move it, back onto
the ruler to take it away (Ctrl: freely). Clips, drops and scaled edges settle on the lines (吸附到參考線) and on the grid (格線,
吸附到格線, grid_size canvas px; also what a reference line settles on).
With the mouse over the preview (and no text being typed): the arrow keys nudge the selected clips by a canvas pixel
(Shift: ten; movesCommitted), Shift+H / Shift+V flip them across / down, Home fits the canvas in the view,
numpad . frames the selection, numpad 1 shows it 1:1, numpad 2 / 4 / 8 at 1:2 / 1:4 / 1:8 and
Ctrl+numpad 2 / 4 / 8 at 2:1 / 4:1 / 8:1, numpad + / - zoom in / out, and Shift+B then a drag
zooms into the box dragged (Esc or the right button: not).

Double-clicking a text clip opens a box over it to type its words in (textEdited while
typing, one undo step); Ctrl+Enter or a click elsewhere closes it, Esc puts the words back.
A text node of a node effect (編輯位置 of its fxsrc group) is edited the same way: its frame is what its
words take up (a clip box's eight handles, the ring at its centre, the round handle to turn it); an edge sets its
own side's 文字框 (box_w / box_h of the node, group "multi": {"fx:<effect id>": {...}}), a corner both - or, with no
box, scales its 字號; a double click types its words (sourceTextEdited) unless a string node gives them.

Every drag shows live (paramsLive) and becomes one edit on release (paramsCommitted), in
the project's units: transform x / y in half-canvas units (y up), scale, clockwise degrees;
mask cx / cy in half-material units (y up), w / h as fractions of the material, feather.
A fullscreen window shows the same frames.

Media can be dragged onto the canvas from the media library, the Library tab, 內建素材, the
compound list or the file manager: mediaDropped reports them and where they were let go (centred
there: a top layer when a static compound is open, else a clip at the playhead). The point snaps
to the canvas centre lines and edges and to the centres and edges of the clips shown (Ctrl: freely),
and the lines it has snapped to are drawn. With Alt
held, media dropped on a picture clip replace its source (replaceDropped; on one of several
selected clips, all of them: 批量替換), and the clips that would change are outlined. Dropped
on a group (its box lit while they would), they go into it instead (移入群組).

G, R and S with the mouse over the preview (Blender's grab, rotate, scale): the selected clip (G: the whole selection)
follows the pointer - R turns about the pivot, S scales by how far the pointer is from it - till a click or Enter keeps
it; Esc or the right button puts it back. X / Y keep a G to one way; a typed number (px, degrees, times) says how much.
"""
import json
import math
import os
import sys
import types

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPainterPath, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QPlainTextEdit, QTextEdit,
                               QWidget)

from .. import components, curves, edit, fonts, gizmos, nodegraph, project, render, sharedgl, textlayout, textvars
from . import appevents, touch, viewglide, wheel
from .zoomglide import ZoomGlide
from .wrapdrag import WrapDrag

SURROUND = "#2a2a2f"               # (what is round the canvas: lighter than a black picture, so the canvas shows)
CANVAS_EDGE = "#5a5a62"             # (and the line along the canvas edge)

US = 1_000_000
SNAP_PX = 7
HANDLE_PX = 4.5               # handle size on screen
ROT_PX = 34                   # rotation handle distance from the outline
PICK_PX = 9
ANGLE_SNAP = 3.0              # degrees within which rotation settles on a right angle
PIVOT_PICK = 0.7              # the pivot's ring is picked closer than a handle (it sits on the clip)
RULER_PX = 18                 # width of the rulers along the top and left edge
GUIDE_COLOR = "#2dd4ff"       # the user's reference lines
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
        spec = textvars.spec_at(c["text"], t, render.TEXT_FIELDS)
        return text_size(spec, H)
    if c["type"] == "compound":
        w, h = c["compound"]["width"], c["compound"]["height"]
    elif c.get("media", {}).get("width"):
        return project.picture_size(c, W, H, t=t)
    else:
        w, h = W, H
    k = min(W / w, H / h)
    return w * k, h * k


def text_node(clip, group, t):
    """(effect id, node id, node, text spec at t) of the text node that source group "fxsrc:<effect id>:<node id>" of
    clip edits, else None."""
    if not group.startswith("fxsrc:"):
        return None
    eid, _, nid = group[6:].partition(":")
    try:
        e = edit.holder(clip, "fxmix:" + eid)
    except (edit.EditError, KeyError):
        return None
    graph = e.get("graph") or {}
    node = (graph.get("nodes") or {}).get(nid)
    if node is None or not nodegraph.is_text(node):
        return None
    src = (e.get("sources") or {}).get(nid) or {}
    spec = textvars.spec_at(nodegraph.text_of(node, nid, e.get("params") or {}, t, nodegraph.binds(graph), src, graph), t,
                            render.TEXT_FIELDS)
    return eid, nid, node, spec


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
        self.anchor = (v("anchor_x", 0.0), v("anchor_y", 0.0))      # (錨點: what x / y place)
        self.pos = (W / 2 + v("x", 0.0) * W / 2 + self.ox, H / 2 - v("y", 0.0) * H / 2 + self.oy)
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

    def anchor_to(self, gx, gy):
        """{anchor_x, anchor_y, x, y} that move the anchor (錨點) to the clip's own edge / corner / centre (gx, gy: -1 / 0 / 1 along
        its own x / y, y down) and change x / y to match, so the clip itself stays where it is."""
        g = self.xf().map(QPointF(gx * self.bw / 2, gy * self.bh / 2))
        c0x = self.pos[0] - self.anchor[0] * self.W / 2              # (its centre before the pivot swings it)
        c0y = self.pos[1] + self.anchor[1] * self.H / 2
        return {"anchor_x": round((g.x() - c0x) / (self.W / 2), 5), "anchor_y": round(-(g.y() - c0y) / (self.H / 2), 5),
                "x": round((g.x() - self.ox - self.W / 2) / (self.W / 2), 5), "y": round((self.H / 2 - (g.y() - self.oy)) / (self.H / 2), 5)}

    def pivot_local(self):
        """Its pivot (中心點) in its own frame (centre origin, unscaled, y down, canvas px)."""
        return QPointF(self.pivot[0] * self.W / 2, -self.pivot[1] * self.H / 2)

    def anchor_pt(self):
        """Canvas point 位置 (x / y) puts the anchor (錨點) at."""
        return QPointF(*self.pos)

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

    def is_picture(self):
        """A picture or shape placed like a clip (not a mask that cuts one)."""
        return self.kind in ("shape", "text", "image", "video", "track", "compound")

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
        if self.kind in ("rectangle", "circle", "compound", "image", "video", "track", "place", "shape", "text"):
            out += [("w", self.xf.map(QPointF(self.hw, 0))), ("h", self.xf.map(QPointF(0, -self.hh))),
                    ("wh", self.xf.map(QPointF(self.hw, -self.hh)))]
            if self.is_picture():                   # (the clip box's eight: the sizing is about the centre either way)
                out += [("w", self.xf.map(QPointF(-self.hw, 0))), ("h", self.xf.map(QPointF(0, self.hh))),
                        ("wh", self.xf.map(QPointF(-self.hw, -self.hh))), ("wh", self.xf.map(QPointF(self.hw, self.hh))),
                        ("wh", self.xf.map(QPointF(-self.hw, self.hh)))]
        elif self.kind == "mirror":
            out.append(("h", self.xf.map(QPointF(0, -self.hh))))
        if self.kind == "place":                    # (a component's picture is moved and sized, not turned)
            return out
        u, hh = self.down()
        c = self.centre()
        out.append(("rot", c - u * (hh + ROT_PX * k)))
        if self.kind not in ("compound", "image", "video", "track", "shape", "text"):      # (a picture mask has no feather)
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


GIZMO_COLOR = "#4fc3f7"


def draw_handle(p, pt, k, round_=False, color="#ffffff"):
    s = HANDLE_PX * touch.scale() * k
    p.setPen(QPen(QColor("#070707"), 1 * k))
    p.setBrush(QColor(color))
    if round_:
        p.drawEllipse(pt, s / 1.6, s / 1.6)
    else:
        p.drawRect(QRectF(pt.x() - s / 2, pt.y() - s / 2, s, s))


def paint_gizmo(p, e, box, k):
    """The handles of effect e (gizmos.handles) of the clip in box, drawn in canvas px with k canvas px to a screen px: a ring with a
    cross for a place, a square on a circle for a size, a round handle on a line for a turn."""
    xf = box.xf()
    col = QColor(GIZMO_COLOR)
    casing, line = QPen(QColor("#070707"), 3.5 * k), QPen(col, 1.5 * k)
    for h in gizmos.handles(e, box.t, box.bw, box.bh):
        pt = xf.map(QPointF(*h["local"]))
        kind = h["kind"]
        p.setBrush(Qt.NoBrush)
        if kind in ("radius", "angle"):
            c = h["centre"]
            ring = QPainterPath()
            rr = h["reach"] if kind == "angle" else math.hypot(h["local"][0] - c[0], h["local"][1] - c[1])
            ring.addEllipse(QPointF(*c), rr, rr)
            ring = xf.map(ring)
            for pen in (casing, QPen(col, 1.25 * k, Qt.DashLine)):
                p.setPen(pen)
                p.drawPath(ring)
            if kind == "angle":
                for pen in (casing, line):
                    p.setPen(pen)
                    p.drawLine(xf.map(QPointF(*c)), pt)
                draw_handle(p, pt, k, round_=True, color=GIZMO_COLOR)
            else:
                draw_handle(p, pt, k, color=GIZMO_COLOR)
        else:
            if kind == "offset":
                o = xf.map(QPointF(*h["origin"]))
                p.setPen(QPen(col, 1 * k, Qt.DashLine))
                p.drawLine(o, pt)
            r = 5 * k
            for w, c in ((3 * k, "#111114"), (1.25 * k, GIZMO_COLOR)):
                p.setPen(QPen(QColor(c), w))
                p.drawEllipse(pt, r, r)
                p.drawLine(pt - QPointF(2 * r, 0), pt + QPointF(2 * r, 0))
                p.drawLine(pt - QPointF(0, 2 * r), pt + QPointF(0, 2 * r))
            if h.get("label"):
                f = p.font()
                f.setPixelSize(round(13 * k))
                p.setFont(f)
                p.setPen(col)
                p.drawText(pt + QPointF(9 * k, -7 * k), h["label"])


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


QUAD_VERT = """#version 330
in vec2 pos; in vec2 uv; out vec2 v_uv;
void main() { v_uv = uv; gl_Position = vec4(pos, 0.0, 1.0); }"""
QUAD_FRAG = """#version 330
uniform sampler2D t; in vec2 v_uv; out vec4 c;
void main() { c = vec4(texture(t, v_uv).rgb, 1.0); }"""


# 預覽用 GPU 繪圖 when the setting was never touched. Not on a tablet: Qt paints what lies under a QOpenGLWidget again each
# time it shows a picture (the panel, the dock, the window: four backgrounds the size of the preview) and sends all of it
# to the screen's texture with the picture; an ordinary widget that fills itself is painted alone, a third less work a picture
GL_DEFAULT = sys.platform != "android"


def _gl_wanted():
    """Whether the preview is drawn on the GPU (a QOpenGLWidget; 設定 > 預覽用 GPU 繪圖, read once at start - it fixes the base class)."""
    if os.environ.get("KIASECUT_PREVIEW_GL", "1") == "0":
        return False
    try:
        from PySide6.QtCore import QSettings
        return str(QSettings("KiaseCut", "KiaseCut").value("preview_gl", GL_DEFAULT)).lower() not in ("false", "0")
    except Exception:
        return False


try:
    from PySide6.QtOpenGLWidgets import QOpenGLWidget
    GL_PREVIEW = _gl_wanted()
except ImportError:
    GL_PREVIEW = False
_Surface = QOpenGLWidget if GL_PREVIEW else QWidget


class Preview(_Surface):
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
    sourceTextEdited = Signal(str, str, str, str)   # clip id, effect id, text node id, its words: typed in on the canvas
    renderWidth = Signal(int)                   # width of the canvas on screen, device px
    mediaDropped = Signal(list, list, float, float, str)  # idents, file paths, transform x / y there, group id or ""
    replaceDropped = Signal(str, str)           # media ident, clip it was Alt-dropped on (替換素材)
    textureFailed = Signal(str)                 # the GpuFrame could not be drawn: the player sends pictures from now on
    guidesCommitted = Signal(dict)              # {"x": [canvas px], "y": [canvas px]}: the reference lines after one was made, moved or taken away
    grabCancelled = Signal()                    # a G / R / S grab was put back (Esc / right button): draw the clips as they were

    def __init__(self, parent=None, interactive=True):
        super().__init__(parent)
        if GL_PREVIEW:
            self.setFormat(sharedgl.widget_format())     # (4 samples: smooth edges for the handles and guides, as the software painter's antialiasing)
            self.setUpdateBehavior(QOpenGLWidget.NoPartialUpdate)
        else:
            self.setAttribute(Qt.WA_OpaquePaintEvent)    # (it fills itself: what lies under it is not painted for every picture shown)
        self.img = None
        self._frame_img = None
        self.frame = None                  # a glrender.GpuFrame instead of img while the player keeps frames in the GPU (show_texture)
        self._mgl = None                   # (moderngl, its context of this widget's GL context, the program, the quad, its GL context)
        self.margin = 0.0                  # (the fraction of the canvas that self.img holds on every side of it)
        self.W, self.H = 1920, 1080
        self.view = None
        self.t_us = 0
        self.selected_id = None
        self.selected_ids = set()               # the whole selection (with selected_id, the primary)
        self.interactive = interactive
        self.show_rulers = False                         # 標尺: along the top and left edge, reference lines are dragged out of them
        self.show_grid = False                           # 格線 (grid_size canvas px apart)
        self.grid_size = 50
        self.snap_grid = False                           # clips, masks and reference lines settle on the grid lines
        self.snap_guides = True                          # clips settle on the reference lines
        self.measure = None                              # (selection rect, other rect) while Alt is held over another clip or the canvas
        self.guide_live = None                           # ([x], [y]) while a reference line is dragged
        self.show_guides = True                          # 輔助線: the frame, handles and notes drawn over the picture (off: just the picture)
        self.mask_mode = False
        self.gizmo_node = None                  # the node of that node effect whose handles they are
        self.gizmo = None                       # id of the effect whose handles (gizmos.py) are on the canvas (編輯控制點)
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
        self.glide = viewglide.ViewGlide(self, self._glide_pan)         # (the view goes on a little after a middle-button drag)
        self.setMinimumSize(320, 180)
        self.setMouseTracking(True)
        self.lit_id = None                      # the clip a finger has held, to be dragged: it is white
        if interactive:                         # (a finger swipes the view; what is on it is picked and dragged only once held)
            touch.enable(self, hold_left=self._holds, lit=self._light_box)
        else:
            touch.enable(self)                  # (fingers: pinch zooms, two fingers move the view)
        self.accept_media = False               # media may be dropped on it (a static compound is open)
        self.drop_at = None                     # canvas point a drag from elsewhere is over
        self.drop_replace = []                  # boxes an Alt-drop there would give its media to
        self.drop_group = None                  # the group box a drop there would go into
        self.setAcceptDrops(interactive)
        if interactive:                          # its keys work while the mouse is over it (see _view_key)
            appevents.watch(self, (QEvent.ShortcutOverride, QEvent.KeyPress, QEvent.KeyRelease), self.eventFilter)

    # -- state ------------------------------------------------------------------------------------
    def show_image(self, img):
        """img: the frame; when it holds what lies round the canvas too (its text "margin": the fraction of the canvas on
        every side), a preview that edits shows all of it, the other ones only the canvas."""
        self.img = img
        self.frame = None
        self.margin = 0.0
        try:
            self.margin = max(0.0, float(img.text("margin") or 0.0)) if img is not None else 0.0
        except ValueError:
            pass
        if self.margin and not self.interactive:
            mx, my = round(img.width() * self.margin / (1 + 2 * self.margin)), round(img.height() * self.margin / (1 + 2 * self.margin))
            self.img = img.copy(mx, my, img.width() - 2 * mx, img.height() - 2 * my)
            self.margin = 0.0
        self.update()

    def show_texture(self, frame):
        """frame: a glrender.GpuFrame, drawn from its texture without a trip through the CPU (image() reads it when it is wanted)."""
        self.frame, self.img, self._frame_img = frame, None, None
        self.margin = frame.margin
        self.update()

    def image(self):
        """The frame shown as a QImage (read back from the GPU when it is a texture), or None."""
        if self.img is not None or self.frame is None:
            return self.img
        fr = self.frame
        if getattr(self, "_frame_img", None) is None:
            self.makeCurrent()
            try:
                mgl = self._gl_objects()
                tex = mgl[0].external_texture(fr.glo, (fr.w, fr.h), 4, 0, "f1")
                img = QImage(tex.read(), fr.w, fr.h, fr.w * 4, QImage.Format_RGBA8888).copy()
            except Exception:
                return None
            finally:
                self.doneCurrent()
            img.setText("margin", repr(fr.margin))
            self._frame_img = img
        return self._frame_img

    def _gl_objects(self):
        """(moderngl context, program, quad) of this widget's GL context (made when first wanted; made current by the caller)."""
        cur = self.context()
        if self._mgl is None or self._mgl[3] is not cur:
            import moderngl
            import numpy as np
            ctx = moderngl.create_context()
            prog = ctx.program(vertex_shader=QUAD_VERT, fragment_shader=QUAD_FRAG)
            vbo = ctx.buffer(reserve=4 * 4 * 4, dynamic=True)
            self._mgl = (ctx, prog, ctx.vertex_array(prog, [(vbo, "2f 2f", "pos", "uv")]), cur, vbo, {})
        return self._mgl

    def _paint_texture(self, p, dest):
        """Draw the GpuFrame's texture into dest (QRectF, widget px) under the painter p (native painting)."""
        import numpy as np
        import moderngl
        fr = self.frame
        p.beginNativePainting()
        try:
            ctx, prog, vao, _cur, vbo, samplers = self._gl_objects()
            dpr = self.devicePixelRatioF()
            W, H = max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr))
            fb = ctx.detect_framebuffer(self.defaultFramebufferObject())
            fb.use()
            ctx.viewport = (0, 0, W, H)
            fb.scissor = None
            ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
            x0, x1 = dest.left() * dpr / W * 2 - 1, dest.right() * dpr / W * 2 - 1
            y0, y1 = 1 - dest.top() * dpr / H * 2, 1 - dest.bottom() * dpr / H * 2
            vbo.write(np.array([x0, y0, 0, 0, x1, y0, 1, 0, x0, y1, 0, 1, x1, y1, 1, 1], "f4").tobytes())
            tex = ctx.external_texture(fr.glo, (fr.w, fr.h), 4, 0, "f1")
            smooth = dest.width() * dpr < fr.w                  # (shown smaller: smoothed; zoomed in, the pixels stay square)
            sm = samplers.get(smooth)
            if sm is None:
                sm = samplers[smooth] = ctx.sampler(filter=(moderngl.LINEAR, moderngl.LINEAR) if smooth else (moderngl.NEAREST, moderngl.NEAREST),
                                                    repeat_x=False, repeat_y=False)
            tex.use(0)
            sm.use(0)
            prog["t"].value = 0
            vao.render(moderngl.TRIANGLE_STRIP)
        finally:
            p.endNativePainting()

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

    def set_show_guides(self, on):
        self.show_guides = bool(on)
        self.unsetCursor()
        self._view_changed()

    def set_mask_mode(self, on, group="mask"):
        self.mask_mode, self.mask_group = on, group
        self.update()

    def set_gizmo(self, eid, nid=None):
        """Show the handles of effect eid on the canvas (None: none); nid: those of one node of a node effect."""
        if (eid, nid) != (self.gizmo, self.gizmo_node):
            self.gizmo, self.gizmo_node = eid, nid
            self.update()

    def gizmo_effect(self, box):
        """The effect (of box's clip) whose handles are shown, or None."""
        if not self.gizmo or box is None or self.mask_mode or self.multi() or getattr(box, "group", False):
            return None
        e = next((e for e in box.clip.get("effects") or [] if e["id"] == self.gizmo), None)
        if e is not None and self.gizmo_node:             # (a node of a node effect: its parameters, as an effect of its own)
            return gizmos.node_effect(e, self.gizmo_node)
        return e if e is not None and gizmos.has_gizmo(e["filter"]) else None

    def gizmo_hit(self, box, m, k):
        """The handle (gizmos.handles, with its canvas point) under canvas point m, the last drawn first, or None."""
        e = self.gizmo_effect(box)
        if e is None:
            return None
        xf = box.xf()
        for h in reversed(gizmos.handles(e, box.t, box.bw, box.bh)):
            pt = xf.map(QPointF(*h["local"]))
            if self._near(pt, m, k):
                return dict(h, canvas=pt, effect=e["id"])
        return None

    def mask_of(self, clip):
        """The mask that mask mode edits on clip (編輯位置: a component picture's placement), or None."""
        if self.mask_group.startswith("place:"):
            p = components.param(components.of_clip(clip), self.mask_group[6:]) if components.of_clip(clip) else None
            return components.place_of(clip, p["id"]) if p and p["kind"] == "image" else None
        try:
            m = edit.holder(clip, self.mask_group)
        except (edit.EditError, KeyError):
            return None
        if m.get("kind") == "text":                      # (a text node's frame is what its words take up, as a text clip's box is)
            box = self.selected_box()
            info = box is not None and box.clip["id"] == clip["id"] and text_node(clip, self.mask_group, box.t)
            if info:
                w, h = text_size(info[3], self.H)
                return dict(m, w=w / max(box.bw, 1e-6), h=h / max(box.bh, 1e-6))
        return m

    def mask_box(self, box):
        """What mask mode edits in: the clip's box, or for 編輯位置 its layer's frame (or None)."""
        if box is not None and self.mask_mode and self.mask_group.startswith("place:"):
            return LayerFrame(box, self.mask_group[6:])
        return box

    def _report_size(self):
        self.renderWidth.emit(round(self._rect().width() * self.devicePixelRatioF()) if self.isVisible() else 0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._report_size()

    def showEvent(self, e):                     # (a preview that is not seen - its panel hidden, a full screen panel over it - asks for no size)
        super().showEvent(e)
        self._report_size()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._report_size()

    def _ruler_inset(self):
        return RULER_PX if self.show_rulers and self.interactive and self.show_guides else 0

    def _rect(self):
        i = self._ruler_inset()
        w, h = self.width() - i, max(1, self.height() - i)
        a = self.W / self.H
        dw, dh = (h * a, h) if w / h > a else (w, w / a)
        dw, dh = dw * self.zoom, dh * self.zoom
        return QRectF(i + (w - dw) / 2 + self.pan.x(), i + (h - dh) / 2 + self.pan.y(), dw, dh)

    def _fit_size(self):
        """(w, h) the canvas has on the widget at zoom 1."""
        i = self._ruler_inset()
        w, h = self.width() - i, max(1, self.height() - i)
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

    def _holds(self, pos):
        """Whether a finger at pos is held before it picks or drags (not while the view is boxed or a grab is on)."""
        return self.show_guides and not self.box_zoom and not (self.drag and self.drag.get("modal")) and not self._on_handle(pos)

    def _on_handle(self, pos):
        """Whether pos is on a handle of what is selected (they are taken at once, without a hold - they are small and are no part of the view)."""
        if not self.view:
            return False
        x, y = self._to_canvas(QPointF(pos))
        m, k = QPointF(x, y), self._k()
        box = self.selected_box()
        mbox = self.mask_box(box)
        if mbox is not None and self.masking(mbox):
            g = MaskGeo(mbox, self.mask_of(box.clip))
            return any(self._near(pt, m, k) for _n, pt in g.handles(k))
        if box is not None and not self.mask_mode and not self.multi() and not getattr(box, "group", False):
            return (self._near(box.rot_handle(k), m, k) or self._grabs_anchor(box, m, k, Qt.NoModifier)
                    or self._grabs_pivot(box, m, k, Qt.NoModifier)
                    or any(self._near(pt, m, k) for _sx, _sy, pt in box.handles()))
        return self._gap_at(m, k) is not None

    def _light_box(self, pos, on):
        """The clip a finger holds goes white (on) until it is lifted: the selected one if it is on it, else the one under it."""
        lit = None
        if on and pos is not None:
            x, y = self._to_canvas(QPointF(pos))
            boxes = [b for b in self.visible_boxes() if not b.locked]
            hit = next((b for b in boxes if b.clip["id"] in self.selected_ids and grabs(b, x, y)), None) \
                or next((b for b in boxes if b.contains(x, y)), None)
            lit = hit.clip["id"] if hit is not None else None
        if lit != self.lit_id:
            self.lit_id = lit
            self.update()

    def _glide_pan(self, dx, dy):
        """The view goes on after a middle-button drag by the pixels the pointer would have moved it."""
        self.pan = self.pan + QPointF(dx, dy)
        self._view_changed()

    def _view_changed(self):
        if self.text_box is not None:                    # it stays over its clip
            box = next((b for b in self.visible_boxes() if b.clip["id"] == self.text_box.clip_id), None)
            if box is not None and self.text_box.source is None:
                self._place_text_box(box)
            elif box is not None and self.mask_mode and self.masking(self.mask_box(box)):
                self._place_text_box(MaskGeo(self.mask_box(box), self.mask_of(box.clip)))
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
            if not hasattr(self, "_zoom_glide"):
                self._zoom_glide = ZoomGlide(self, lambda k, at: self.zoom_to(self.zoom * ZOOM_STEP ** k, at), "preview_zoom")
            if wheel.touchpad(e):
                self.zoom_to(self.zoom * ZOOM_STEP ** n, e.position())
            else:
                self._zoom_glide.add(n, e.position())

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
        grab = {Qt.Key_G: "move", Qt.Key_R: "rotate", Qt.Key_S: "gscale"}.get(k)
        if grab and not pad and not ctrl and not shift and not mods & Qt.AltModifier and self._can_grab(grab):
            return lambda: self._grab_begin(grab)
        if k == Qt.Key_B and shift and not ctrl:
            return self._arm_box_zoom
        if k in (Qt.Key_H, Qt.Key_V) and shift and not ctrl and not pad and not mods & Qt.AltModifier and self._can_nudge():
            return lambda: self.flip("flip_h" if k == Qt.Key_H else "flip_v")
        step = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}.get(k)
        if step and not pad and not ctrl and not mods & Qt.AltModifier and self._can_nudge():
            n = 10 if shift else 1
            return lambda: self.nudge(step[0] * n, step[1] * n)
        if k == Qt.Key_Escape and self.box_zoom:
            return lambda: self._arm_box_zoom(False)
        return None

    # -- rulers, reference lines and the grid ---------------------------------------------------
    def set_rulers(self, on):
        self.show_rulers = bool(on)
        self._view_changed()

    def set_grid(self, show=None, size=None, snap=None, snap_guides=None):
        if show is not None:
            self.show_grid = bool(show)
        if size is not None:
            self.grid_size = max(1, int(size))
        if snap is not None:
            self.snap_grid = bool(snap)
        if snap_guides is not None:
            self.snap_guides = bool(snap_guides)
        self.update()

    def guide_lists(self):
        """([x], [y]) canvas px of the reference lines (the ones being dragged, while one is)."""
        if self.guide_live is not None:
            return self.guide_live
        g = (self.view or {}).get("guides") or {}
        return list(g.get("x") or ()), list(g.get("y") or ())

    def _extra_targets(self):
        """([x], [y]) canvas px a moved edge or centre settles on besides the clips: reference lines and grid lines."""
        xs, ys = self.guide_lists() if self.snap_guides else ([], [])
        xs, ys = list(xs), list(ys)
        s = self.grid_size
        if self.snap_grid and s >= 1 and self.W / s <= 800 and self.H / s <= 800:
            xs += [i * s for i in range(int(self.W // s) + 1)]
            ys += [i * s for i in range(int(self.H // s) + 1)]
        return xs, ys

    def _guide_at(self, m, k):
        """("x" or "y", index) of the reference line within a few screen px of canvas point m, else None."""
        tol = 5 * k
        xs, ys = self.guide_lists()
        for i, v in enumerate(xs):
            if abs(m.x() - v) <= tol:
                return "x", i
        for i, v in enumerate(ys):
            if abs(m.y() - v) <= tol:
                return "y", i
        return None

    def _guide_move(self, d, e, m):
        """A reference line being made or moved: it settles on the canvas centre / edges and the grid (Ctrl: freely) and is
        taken away when the pointer is back on the ruler it came from (or the one for its kind)."""
        axis = d["axis"]
        v = m.x() if axis == "x" else m.y()
        full = self.W if axis == "x" else self.H
        if not e.modifiers() & Qt.ControlModifier:
            cands = [0, full / 2, full]
            if self.snap_grid and self.grid_size >= 1:
                cands.append(round(v / self.grid_size) * self.grid_size)
            near = min(cands, key=lambda c: abs(c - v))
            v = near if abs(near - v) < SNAP_PX * self._k() else round(v)
        if "base" not in d:
            g = (self.view or {}).get("guides") or {}
            d["base"] = (list(g.get("x") or ()), list(g.get("y") or ()))
        xs, ys = (list(a) for a in d["base"])
        lst = xs if axis == "x" else ys
        if d["idx"] is not None:
            del lst[d["idx"]]
        pos = e.position()
        away = (pos.x() if axis == "x" else pos.y()) < RULER_PX and self.show_rulers
        d["value"], d["pos_w"] = (None if away else v), pos
        if not away:
            lst.append(v)
            lst.sort()
        self.guide_live = (xs, ys)
        self.update()

    def _paint_grid(self, p, k):
        """The grid and the reference lines, in canvas coordinates under the handles."""
        s = self.grid_size
        if self.show_grid and s >= 1 and s / k >= 6:
            p.setPen(QPen(QColor(255, 255, 255, 38), 1 * k))
            for i in range(int(self.W // s) + 1):
                p.drawLine(QPointF(i * s, 0), QPointF(i * s, self.H))
            for i in range(int(self.H // s) + 1):
                p.drawLine(QPointF(0, i * s), QPointF(self.W, i * s))
        xs, ys = self.guide_lists()
        if xs or ys:
            far = (self.W + self.H) * 50
            p.setPen(QPen(QColor(GUIDE_COLOR), 1 * k))
            for v in xs:
                p.drawLine(QPointF(v, -far), QPointF(v, far))
            for v in ys:
                p.drawLine(QPointF(-far, v), QPointF(far, v))

    @staticmethod
    def _ruler_step(per_px):
        """Canvas px between the numbers of a ruler when one screen px is per_px canvas px (about 70 screen px apart)."""
        raw = 70 * per_px
        mag = 10 ** math.floor(math.log10(max(raw, 1e-9)))
        for m in (1, 2, 5, 10):
            if m * mag >= raw:
                return m * mag, m
        return 10 * mag, 10

    def _paint_rulers(self, p):
        r = self._rect()
        w, h = self.width(), self.height()
        bg, ink, tick = QColor(34, 34, 40), QColor("#9a9aa0"), QColor("#6a6a72")
        p.fillRect(QRectF(0, 0, w, RULER_PX), bg)
        p.fillRect(QRectF(0, 0, RULER_PX, h), bg)
        p.setPen(QPen(QColor("#4a4a52"), 1))
        p.drawLine(QPointF(0, RULER_PX), QPointF(w, RULER_PX))
        p.drawLine(QPointF(RULER_PX, 0), QPointF(RULER_PX, h))
        f = p.font()
        f.setPixelSize(9)
        p.setFont(f)
        for axis in ("x", "y"):
            full = self.W if axis == "x" else self.H
            size = r.width() if axis == "x" else r.height()
            origin = r.x() if axis == "x" else r.y()
            unit = size / full                                   # screen px per canvas px
            step, mant = self._ruler_step(1 / unit)
            minor = step / (4 if mant == 2 else 5 if mant in (1, 5) else 10)
            lo = math.floor((RULER_PX - origin) / unit / minor) * minor
            hi = ((w if axis == "x" else h) - origin) / unit
            n = int((hi - lo) / minor) + 2
            for i in range(min(n, 4000)):
                v = lo + i * minor
                sp = origin + v * unit
                if sp < RULER_PX:
                    continue
                major = abs(v / step - round(v / step)) < 1e-6
                p.setPen(tick)
                if axis == "x":
                    p.drawLine(QPointF(sp, RULER_PX - (9 if major else 4)), QPointF(sp, RULER_PX))
                else:
                    p.drawLine(QPointF(RULER_PX - (9 if major else 4), sp), QPointF(RULER_PX, sp))
                if major:
                    p.setPen(ink)
                    text = f"{v:g}"
                    if axis == "x":
                        p.drawText(QPointF(sp + 3, 9), text)
                    else:
                        p.save()
                        p.translate(9, sp - 3)
                        p.rotate(-90)
                        p.drawText(QPointF(0, 0), text)
                        p.restore()
        xs, ys = self.guide_lists()                              # the reference lines marked on the rulers
        p.setPen(QPen(QColor(GUIDE_COLOR), 2))
        for v in xs:
            sx = r.x() + v / self.W * r.width()
            if sx >= RULER_PX:
                p.drawLine(QPointF(sx, 0), QPointF(sx, RULER_PX))
        for v in ys:
            sy = r.y() + v / self.H * r.height()
            if sy >= RULER_PX:
                p.drawLine(QPointF(0, sy), QPointF(RULER_PX, sy))
        d = self.drag
        if d and d["kind"] == "guide" and d.get("value") is not None and d.get("pos_w") is not None:
            text = ("X " if d["axis"] == "x" else "Y ") + f"{d['value']:g}"
            pos = d["pos_w"]
            box = QRectF(pos.x() + 14, pos.y() + 14, p.fontMetrics().horizontalAdvance(text) + 10, 16)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(GUIDE_COLOR))
            p.drawRoundedRect(box, 3, 3)
            p.setPen(QColor("#10222a"))
            p.drawText(box, Qt.AlignCenter, text)

    # -- Alt: the distances between the selection and the clip (or the canvas) under the mouse ---------------------
    def _measure_update(self, on, x, y):
        """Alt held with the mouse over another clip (or over nothing: the canvas): self.measure = (the selection's rect, that one's)."""
        new = None
        if on and self.drag is None and not self.mask_mode and self.view and self.selected_ids:
            picked = self._picked_boxes()
            if picked:
                mine = self._union(picked)
                other = next((b for b in self.visible_boxes() if not b.locked and b.clip["id"] not in self.selected_ids
                              and b.contains(x, y)), None)
                new = (mine, other.extents() if other is not None else (0, self.W, 0, self.H))
        if new != self.measure:
            self.measure = new
            self.update()

    @staticmethod
    def measure_segments(a, b):
        """[(x1, y1, x2, y2)] canvas px: the gaps between rect a and rect b (left, right, top, bottom) along each axis -
        between them when they are apart, else from each edge of the inner one to the outer one's (those that differ)."""
        out = []
        apart = any(a[i + 1] <= b[i] or b[i + 1] <= a[i] for i in (0, 2))
        for axis in (0, 2):
            alo, ahi, blo, bhi = a[axis], a[axis + 1], b[axis], b[axis + 1]
            if apart and not (ahi <= blo or bhi <= alo):       # apart along one axis only: just that gap
                continue
            o = 2 - axis                                       # the other axis' pair of indexes
            lo, hi = max(a[o], b[o]), min(a[o + 1], b[o + 1])
            cross = (lo + hi) / 2 if lo < hi else (a[o] + a[o + 1]) / 2          # where along the other axis the line is drawn
            spans = []
            if ahi <= blo:
                spans.append((ahi, blo))
            elif bhi <= alo:
                spans.append((bhi, alo))
            else:
                for u, v in ((alo, blo), (ahi, bhi)):
                    if abs(u - v) > 0.5:
                        spans.append((min(u, v), max(u, v)))
            for u, v in spans:
                out.append((u, cross, v, cross) if axis == 0 else (cross, u, cross, v))
        return out

    def _paint_measure(self, p, k):
        if self.measure is None or self.drag is not None:
            return
        a, b = self.measure
        red = QColor("#ff4d4d")
        f = p.font()
        f.setPixelSize(round(11 * k))
        p.setFont(f)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(red, 1 * k, Qt.DashLine))
        p.drawRect(QRectF(b[0], b[2], b[1] - b[0], b[3] - b[2]))
        p.setPen(QPen(red, 1 * k))
        for x1, y1, x2, y2 in self.measure_segments(a, b):
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            n = QPointF(0, 4 * k) if y1 == y2 else QPointF(4 * k, 0)
            p.drawLine(QPointF(x1, y1) - n, QPointF(x1, y1) + n)
            p.drawLine(QPointF(x2, y2) - n, QPointF(x2, y2) + n)
            text = f"{math.hypot(x2 - x1, y2 - y1):.0f}"
            tw = p.fontMetrics().horizontalAdvance(text) + 8 * k
            box = QRectF(0, 0, tw, 16 * k)
            box.moveCenter(QPointF((x1 + x2) / 2, (y1 + y2) / 2) + (QPointF(0, -12 * k) if y1 == y2 else QPointF(tw / 2 + 4 * k, 0)))
            p.setPen(Qt.NoPen)
            p.setBrush(red)
            p.drawRoundedRect(box, 2 * k, 2 * k)
            p.setPen(QColor("#ffffff"))
            p.drawText(box, Qt.AlignCenter, text)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(red, 1 * k))

    # -- 圓角: a round handle inside each corner of a picture clip -------------------------------------------------
    CORNER_SIGNS = ((-1, -1), (1, -1), (1, 1), (-1, 1))             # project.CORNERS' order, in the clip's own frame (y down)

    def _has_radius_handles(self, box):
        return (not getattr(box, "group", False) and box.clip["type"] in ("image", "video", "compound") and not box.clip.get("asset")
                and not box.locked and min(box.w, box.h) / self._k() >= 70)

    def radius_handles(self, box, k):
        """[(radius key, canvas point)]: each handle sits as far in from its corner as that corner is rounded (at least a
        dozen screen px, so a square corner has one too)."""
        radii = project.corner_radii(box.clip, box.t, (box.bw, box.bh), box.H) or (0.0,) * 4
        floor = 14 * k / max(min(abs(box.s), abs(box.sy)), 1e-6)
        xf = box.xf()
        out = []
        for key, (sx, sy), r in zip(project.CORNERS, self.CORNER_SIGNS, radii):
            ins = min(max(r, floor), min(box.bw, box.bh) / 2)
            out.append((key, xf.map(QPointF(sx * (box.bw / 2 - ins), sy * (box.bh / 2 - ins)))))
        return out

    def _radius_values(self, box, d, m, mods):
        """{radius_*: px} of dragging a corner handle to canvas point m: how far in from the corner it is (all four with Shift)."""
        inv, _ = box.xf().inverted()
        q = inv.map(m)
        sx, sy = self.CORNER_SIGNS[project.CORNERS.index(d["corner"])]
        ins = ((box.bw / 2 - sx * q.x()) + (box.bh / 2 - sy * q.y())) / 2
        ins = min(max(ins, 0.0), min(box.bw, box.bh) / 2)
        v = round(ins * 1080 / box.H, 1)
        return {k: v for k in (project.CORNERS if mods & Qt.ShiftModifier else (d["corner"],))}

    # -- arrow keys: nudge the selection by a pixel (Shift: ten) ------------------------------------------------
    def _can_nudge(self):
        return (self.interactive and self.show_guides and not self.mask_mode and self.drag is None
                and self.text_box is None and bool(self._nudge_boxes()))

    def _nudge_boxes(self):
        boxes = self._picked_boxes()
        if boxes:
            return boxes
        kids = self._kid_boxes()
        return [k for k, _ in kids.values()]

    def anchor_grid(self, gx, gy):
        """The 9-point grid of the inspector: the anchor of every selected clip goes to the clip's corner, edge middle or centre
        (gx, gy: -1 / 0 / 1; y down) without the clip moving (paramsCommitted, one edit each)."""
        for b in self._picked_boxes():
            self.paramsCommitted.emit(b.clip["id"], "transform", b.anchor_to(gx, gy))

    def flip(self, key):
        """Shift+H / Shift+V (and the inspector's buttons): the selected clips are turned over - all of them like the
        primary one if it is not flipped yet, else all back."""
        boxes = self._nudge_boxes()
        if not boxes:
            return
        on = not (boxes[0].flip[0] < 0 if key == "flip_h" else boxes[0].flip[1] < 0)
        for b in boxes:
            self.paramsCommitted.emit(b.clip["id"], "transform", {key: on})

    def nudge_moves(self, dx, dy):
        """{clip id: {x, y}} of the selected clips moved by dx, dy canvas pixels (y down)."""
        return {b.clip["id"]: {"x": b.x_at(b.cx + dx), "y": b.y_at(b.cy + dy)} for b in self._nudge_boxes()}

    def nudge(self, dx, dy):
        moves = self.nudge_moves(dx, dy)
        if moves:
            self.movesCommitted.emit(moves)

    # -- G / R / S: Blender's grab, rotate and scale: the selected clip follows the pointer till a click --------------
    def _can_grab(self, kind):
        box = self.selected_box()
        if (not self.interactive or not self.show_guides or self.mask_mode or self.drag is not None or self.text_box is not None
                or box is None or box.locked):
            return False
        return kind == "move" or (not self.multi() and not getattr(box, "group", False))

    def _grab_begin(self, kind):
        """G (move, the whole selection), R (rotate) or S (scale) of the selected clip: it follows the pointer, X / Y
        keep a move to one way, a typed number says how much (px, degrees, times); a click or Enter keeps it, Esc or the
        right button puts it back."""
        box = self.selected_box()
        m = QPointF(*self._to_canvas(QPointF(self.mapFromGlobal(QCursor.pos()))))
        boxes = [b for b in self.visible_boxes() if b.clip["id"] in self.selected_ids and not b.locked]
        d = {"kind": kind, "box": box, "m0": m, "m": m, "moved": True, "modal": True, "axis": None, "num": "",
             "mods": Qt.NoModifier}
        if kind == "move":
            d.update(boxes=boxes, x0=m.x(), y0=m.y(), others=[b for b in self.visible_boxes() if b.clip["id"] not in self.selected_ids])
        self.drag = d
        self.wrap.start()                                # (endless, as a middle-button drag: the pointer wraps at the edges)
        self.setCursor(Qt.SizeAllCursor)
        self.update()

    def _grab_update(self):
        d = self.drag
        group, vals = self._values(types.SimpleNamespace(modifiers=lambda: d["mods"]), d["m"])
        self._live(d, group, vals)

    def _live(self, d, group, vals):
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

    def _grab_end(self, keep):
        d, self.drag = self.drag, None
        live, self.live = self.live, None
        self.wrap.stop(d.get("pos"))                     # (the pointer where the grab ended up)
        self.guides = []
        self.setCursor(Qt.ArrowCursor)
        if keep and live:
            self._commit(d, live)
        elif live:
            self.grabCancelled.emit()
        self.update()

    def _grab_key(self, e, act):
        """A key while a grab is on; True when the grab takes it."""
        d, k = self.drag, e.key()
        if e.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
            return False
        if k == Qt.Key_Escape:
            if act:
                self._grab_end(False)
            return True
        if k in (Qt.Key_Return, Qt.Key_Enter):
            if act:
                self._grab_end(True)
            return True
        text = e.text()
        if k in (Qt.Key_X, Qt.Key_Y):
            if act and d["kind"] == "move":
                axis = "x" if k == Qt.Key_X else "y"
                d["axis"] = None if d["axis"] == axis else axis
                self._grab_update()
            return True
        if k in (Qt.Key_G, Qt.Key_R, Qt.Key_S):
            return True
        if k == Qt.Key_Backspace or (len(text) == 1 and text in "0123456789.-"):
            if act:
                n = d["num"]
                if k == Qt.Key_Backspace:
                    n = n[:-1]
                elif text == "-":
                    n = n[1:] if n.startswith("-") else "-" + n
                elif text != "." or "." not in n:
                    n += text
                d["num"] = n
                self._grab_update()
            return True
        return False

    @staticmethod
    def _typed(d):
        """The number typed during a grab, or None."""
        try:
            return float(d["num"]) if d.get("num") else None
        except ValueError:
            return 0.0

    def eventFilter(self, obj, e):
        t = e.type()
        if t in (QEvent.KeyPress, QEvent.KeyRelease) and e.key() == Qt.Key_Alt and isinstance(obj, QWidget) and obj.window() is self.window():
            if self.interactive and self.view and self.show_guides and self.isVisible() and self.underMouse():
                x, y = self._to_canvas(QPointF(self.mapFromGlobal(QCursor.pos())))
                self._measure_update(t == QEvent.KeyPress and self.drag is None, x, y)
            return False
        if t == QEvent.KeyRelease:
            return False
        if (self.drag and self.drag.get("modal") and t in (QEvent.ShortcutOverride, QEvent.KeyPress)
                and isinstance(obj, QWidget) and obj.window() is self.window()):
            if self._grab_key(e, t == QEvent.KeyPress):
                e.accept()
                return True
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
        return self.view is not None and (md.hasFormat(MEDIA_MIME) or md.hasUrls())

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
        self.drop_at, self.guides = (None, []) if self.drop_replace else self._drop_point(e)
        self.drop_group = None if self.drop_replace or not self.accept_media else self._group_at(*self._to_canvas(e.position()))
        e.setDropAction(Qt.CopyAction)
        e.accept()
        self.update()

    def _drop_point(self, e):
        """(canvas point a drop is centred at, guides): where the pointer is, snapped to the canvas
        centre lines and edges and to the centres and edges of the clips shown (Ctrl: as it is)."""
        x, y = self._to_canvas(e.position())
        if e.modifiers() & Qt.ControlModifier:
            return QPointF(x, y), []
        tol = SNAP_PX * self._k()
        rects = [b.extents() for b in self.visible_boxes()]
        ex, ey = self._extra_targets()
        tx = [self.W / 2, 0, self.W] + [v for o in rects for v in ((o[0] + o[1]) / 2, o[0], o[1])] + ex
        ty = [self.H / 2, 0, self.H] + [v for o in rects for v in ((o[2] + o[3]) / 2, o[2], o[3])] + ey
        guides = []
        hit = self._best([x], tx, tol)
        if hit:
            x = hit[1]
            guides.append(("x", x))
        hit = self._best([y], ty, tol)
        if hit:
            y = hit[1]
            guides.append(("y", y))
        return QPointF(x, y), guides

    def dragLeaveEvent(self, e):
        self.guides = []
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
        at = self._drop_point(e)[0]
        self.guides = []
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
        tx, ty = round((at.x() - self.W / 2) / (self.W / 2), 5), round((self.H / 2 - at.y()) / (self.H / 2), 5)
        g = self._group_at(x, y) if self.accept_media else None
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
            holder = c if g == "clip" else edit.holder(c, g) if g.startswith(("fx:", "fxmask:", "fxsrc:", "place:")) else c.setdefault(g, {})
            holder.update(edit.with_linked_scale(holder, v, box.t) if g == "transform" else v)
        return box.moved(c)

    def masking(self, box):
        if not self.mask_mode or box is None or not self.mask_of(box.clip):
            return False
        return self.mask_group != "mask" or box.clip["type"] in edit.MASKABLE

    # -- painting ---------------------------------------------------------------------------------
    def _draw_picture(self, p, dest):
        if self.frame is None:
            p.drawImage(dest, self.img)
            return
        try:
            self._paint_texture(p, dest)
        except Exception as exc:                       # (this computer cannot show the texture: the player is told to send pictures)
            self.frame = None
            sharedgl.ENABLED = False
            self.textureFailed.emit(str(exc))

    def paintEvent(self, e):
        self._paint_view(e)
        if self.interactive and self.show_guides and self.show_rulers and self.view:
            p = QPainter(self)
            self._paint_rulers(p)
            p.end()

    def _paint_view(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(SURROUND))
        r = self._rect()
        p.fillRect(r, QColor("black"))
        shown = self.img is not None or self.frame is not None
        if shown and self.margin:       # (what lies outside the canvas: drawn dimmed)
            m = QRectF(r.x() - r.width() * self.margin, r.y() - r.height() * self.margin,
                       r.width() * (1 + 2 * self.margin), r.height() * (1 + 2 * self.margin))
            self._draw_picture(p, m)
            outside = QPainterPath()
            outside.addRect(m)
            outside.addRect(r)
            p.fillPath(outside, QColor(42, 42, 47, 150))
        elif shown:
            self._draw_picture(p, r)                   # (no smoothing: zoomed in, the pixels stay square)
        if self.interactive:                           # (a hair line round the canvas: where it ends, even where the picture is as dark as the surround)
            p.setPen(QPen(QColor(CANVAS_EDGE), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r.adjusted(-0.5, -0.5, 0.5, 0.5))
        if not self.interactive or not self.show_guides:
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
        self._paint_grid(p, k)
        self._paint_measure(p, k)
        box = self._live_box()
        mbox = self.mask_box(box)
        if self.multi():
            self._paint_group(p, k)
        elif box is not None:
            if mbox is not None and self.masking(mbox):
                self._paint_mask(p, mbox, k)
            elif self.mask_mode or self.gizmo_effect(box) is not None:     # no mask: just where the clip is
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(255, 255, 255, 120), 1 * k, Qt.DashLine))
                p.drawPolygon(QPolygonF(box.corners()))
                self._paint_gizmo(p, box, k)
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
        if self.lit_id is not None:                      # held by a finger: white, and it is let go to be dragged
            for b in self.visible_boxes():
                if b.clip["id"] == self.lit_id:
                    p.setPen(QPen(QColor("#ffffff"), 3 * k))
                    p.setBrush(QColor(255, 255, 255, 90))
                    p.drawPolygon(QPolygonF(b.corners()))
                    p.setBrush(Qt.NoBrush)
                    break
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
        s = HANDLE_PX * touch.scale() * k
        p.setPen(QPen(QColor("#070707"), 1 * k))
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
        if self._has_radius_handles(box):
            for key, pt in self.radius_handles(box, k):
                self._handle(p, pt, k, round_=True, color="#7fd1ff" if self.drag and self.drag["kind"] == "radius" else "#ffffff")
            if self.drag and self.drag["kind"] == "radius":
                v = (self.live[1] if self.live else {}).get(self.drag["corner"], curves.value((box.clip.get("transform") or {}).get(self.drag["corner"], 0.0), box.t))
                p.setPen(QColor("#ffffff"))
                f = p.font()
                f.setPixelSize(round(14 * k))
                p.setFont(f)
                p.drawText(dict(self.radius_handles(box, k))[self.drag["corner"]] + QPointF(12 * k, -8 * k), f"圓角 {v:g}")
        an, d = box.anchor_pt(), 4 * k                         # 錨點: a diamond
        diamond = QPolygonF([an + QPointF(0, -d), an + QPointF(d, 0), an + QPointF(0, d), an + QPointF(-d, 0)])
        for w, col in ((3 * k, "#111114"), (1.25 * k, "#ffb020")):
            p.setPen(QPen(QColor(col), w))
            p.setBrush(Qt.NoBrush)
            p.drawPolygon(diamond)
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
        pad = PICK_PX * touch.scale() * k
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

    def _paint_gizmo(self, p, box, k):
        """The handles of the effect picked for 編輯控制點."""
        e = self.gizmo_effect(box)
        if e is not None:
            paint_gizmo(p, e, box, k)

    def gizmo_frame(self):
        """(clip id, effect, box, node id or None) whose handles the preview shows now, or None: the node editor draws them on
        its backdrop too."""
        box = self.selected_box()
        e = self.gizmo_effect(box)
        return None if e is None else (box.clip["id"], e, box, self.gizmo_node)

    def _paint_mask(self, p, box, k):
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 90), 1 * k, Qt.DashLine))
        p.drawPolygon(QPolygonF(box.corners()))
        g = MaskGeo(box, self.mask_of(box.clip))
        path = g.outline()
        on = g.m.get("enabled", True)
        edge = QColor("#ffb020") if on else QColor(255, 176, 32, 110)
        if g.is_picture():                     # drawn as the clip's own box is (white, the same handles)
            edge = QColor("#ffffff") if on else QColor(255, 255, 255, 110)
        p.save()
        clip = QPainterPath()
        clip.addPolygon(QPolygonF(box.corners()))
        if g.kind != "place":                  # the mask only matters inside the clip (a picture may go past its frame)
            p.setClipPath(clip)
        p.setPen(QPen(QColor("#070707"), 3.5 * k))
        p.drawPath(path)
        p.setPen(QPen(edge, 2 * k, Qt.SolidLine if on else Qt.DashLine))
        p.drawPath(path)
        p.restore()
        c = g.centre()
        pic = g.is_picture()
        hcol = "#ffffff" if pic else "#ffb020"
        for name, pt in g.handles(k):
            if name == "rot":
                u, hh = g.down()
                p.setPen(QPen(QColor("#ffffff") if pic else QColor("#ffb020"), 1 * k))
                p.drawLine(c - u * hh if pic else c, pt)
                self._handle(p, pt, k, round_=True, color="#e6e6e6" if pic else "#ffb020")
            elif name == "feather":
                u, _ = g.down()
                n = QPointF(-u.y(), u.x())
                s = HANDLE_PX * touch.scale() * k
                p.setPen(QPen(QColor("#070707"), 1 * k))
                p.setBrush(QColor("#ffb020"))
                p.drawPolygon(QPolygonF([pt + u * s * 0.8, pt - u * s * 0.4 + n * s * 0.7, pt - u * s * 0.4 - n * s * 0.7]))
            else:
                self._handle(p, pt, k, color=hcol)
        if pic:                                # 中心點: a ring with a cross, as on a clip
            r = 5 * k
            for w, col in ((3 * k, "#111114"), (1.25 * k, "#ffffff")):
                p.setPen(QPen(QColor(col), w))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(c, r, r)
                p.drawLine(c - QPointF(2 * r, 0), c + QPointF(2 * r, 0))
                p.drawLine(c - QPointF(0, 2 * r), c + QPointF(0, 2 * r))
        else:
            self._handle(p, c, k, round_=True, color="#ffffff")
        if self.drag and self.drag["kind"] == "feather":
            f = p.font()
            f.setPixelSize(round(14 * k))
            p.setFont(f)
            p.setPen(QColor("#ffffff"))
            p.drawText(g.handles(k)[-1][1] + QPointF(12 * k, 4 * k), f"羽化 {g.feather * 100:.0f}")

    # -- mouse ------------------------------------------------------------------------------------
    def _near(self, a, b, k):
        return math.hypot(a.x() - b.x(), a.y() - b.y()) <= PICK_PX * touch.scale() * k

    def mousePressEvent(self, e):
        if self.drag and self.drag.get("modal"):         # (the click that keeps a grab, or the right button that puts it back)
            if e.button() in (Qt.LeftButton, Qt.RightButton):
                self._grab_end(e.button() == Qt.LeftButton)
            return
        self.glide.stop()
        if self.interactive and e.button() == Qt.MiddleButton:       # Ctrl: zoom, else move the view
            zoom = bool(e.modifiers() & Qt.ControlModifier)
            self.drag = {"kind": "zoomdrag" if zoom else "pan", "pos": e.position(), "pan": QPointF(self.pan),
                         "zoom": self.zoom, "moved": False}
            self.setCursor(Qt.SizeVerCursor if zoom else Qt.ClosedHandCursor)
            return
        if self.box_zoom and e.button() == Qt.RightButton:
            self._arm_box_zoom(False)
            return
        if not self.interactive or e.button() != Qt.LeftButton or not self.view or not self.show_guides:
            return
        x, y = self._to_canvas(e.position())
        m = QPointF(x, y)
        if self.show_rulers and (e.position().x() < RULER_PX) != (e.position().y() < RULER_PX):
            axis = "y" if e.position().y() < RULER_PX else "x"          # the top ruler makes a flat line, the left one an upright one
            self.drag = {"kind": "guide", "axis": axis, "idx": None, "m0": m, "moved": False}
            return
        if self.show_rulers and e.position().x() < RULER_PX and e.position().y() < RULER_PX:
            return
        if self.box_zoom:
            self.drag = {"kind": "zoombox", "m0": m, "moved": False, "rect": QRectF(m, m)}
            return
        k = self._k()
        box = self.selected_box()
        mbox = self.mask_box(box)
        if (h := self.gizmo_hit(box, m, k)) is not None:                # a handle of the effect picked for 編輯控制點
            self.drag = {"kind": "gizmo", "box": box, "m0": m, "moved": False, "handle": h, "grab": h["canvas"] - m, "turn": {}}
            return
        if mbox is not None and self.masking(mbox):
            g = MaskGeo(mbox, self.mask_of(box.clip))
            hit = next((n for n, pt in g.handles(k) if self._near(pt, m, k)), None)
            if hit is None and (g.contains(m) or self._near(g.centre(), m, k)):
                hit = "move"
            if hit is not None:
                self.drag = {"kind": hit, "box": mbox, "geo": g, "m0": m, "moved": False}
                return
        elif box is not None and not self.mask_mode and not self.multi() and not getattr(box, "group", False) and self.gizmo_effect(box) is None:
            if self._near(box.rot_handle(k), m, k):
                self.drag = {"kind": "rotate", "box": box, "m0": m, "moved": False}
                return
            if self._grabs_anchor(box, m, k, e.modifiers()):
                self.drag = {"kind": "anchor", "box": box, "m0": m, "a0": box.anchor, "moved": False}
                return
            if self._grabs_pivot(box, m, k, e.modifiers()):
                self.drag = {"kind": "pivot", "box": box, "m0": m, "moved": False}
                return
            side = next(((sx, sy) for sx, sy, pt in box.handles() if self._near(pt, m, k)), None)
            if side is not None:
                self.drag = {"kind": "scale", "box": box, "m0": m, "moved": False, "side": side,
                             "others": [b for b in self.visible_boxes() if b.clip["id"] != box.clip["id"]]}
                return
            if self._has_radius_handles(box):
                corner = next((key for key, pt in self.radius_handles(box, k) if self._near(pt, m, k)), None)
                if corner is not None:
                    self.drag = {"kind": "radius", "box": box, "m0": m, "moved": False, "corner": corner}
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
        if hit is None and (g := self._guide_at(m, k)) is not None:      # a reference line in the open: move it
            self.drag = {"kind": "guide", "axis": g[0], "idx": g[1], "m0": m, "moved": False}
            return
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
        ex, ey = self._extra_targets()
        tx = [self.W / 2, 0, self.W] + [v for o in others for v in ((o[0] + o[1]) / 2, o[0], o[1])] + ex
        ty = [self.H / 2, 0, self.H] + [v for o in others for v in ((o[2] + o[3]) / 2, o[2], o[3])] + ey

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
            typed = self._typed(d)
            if e.modifiers() & Qt.ControlModifier or typed is not None:    # Ctrl: move freely
                self.guides = []
            else:
                dx, dy, self.guides = self._snap(self._union(boxes), dx, dy, [o.extents() for o in d["others"]],
                                                 SNAP_PX * self._k())
            if d.get("modal"):                                 # (G: X / Y keep it to one way, a typed number is the way)
                axis = d["axis"]
                if typed is not None:
                    dx, dy = (0.0, typed) if axis == "y" else (typed, 0.0)
                elif axis:
                    dx, dy = (dx, 0.0) if axis == "x" else (0.0, dy)
            at = {b.clip["id"]: {"x": b.x_at(b.cx + dx), "y": b.y_at(b.cy + dy)} for b in boxes}
            return ("moves", at) if len(boxes) > 1 or d["dup"] else ("transform", at[box.clip["id"]])
        if kind == "gap":
            along = m.x() - d["m0"].x() if d["axis"] == "x" else m.y() - d["m0"].y()
            return "moves", self._spread(d["boxes"], d["axis"], max(0.0, round(d["gap0"] + along)))
        if kind == "gizmo":
            inv, _ = box.xf().inverted()
            pt = inv.map(m + d["grab"])
            h = d["handle"]
            vals = gizmos.dragged(h, (pt.x(), pt.y()), box.bw, box.bh, d["turn"], snap=not e.modifiers() & Qt.AltModifier,
                                  turn_snap=lambda v: snap_angle(v, free))
            if self.gizmo_node:
                vals = {f"{self.gizmo_node}.{k}": v for k, v in vals.items()}
            return "fx:" + h["effect"], vals
        c = QPointF(box.cx, box.cy)
        if kind == "scale":
            return self._scale_values(box, d, m, e.modifiers())
        if kind == "pivot":
            return "transform", self._pivot_values(box, m, e.modifiers())
        if kind == "anchor":
            return "transform", self._anchor_values(box, d, m)
        if kind == "radius":
            return "transform", self._radius_values(box, d, m, e.modifiers())
        if kind == "rotate":
            c = box.pivot_pt()                                 # (中心點: it turns about its pivot)
            a0 = math.degrees(math.atan2(d["m0"].y() - c.y(), d["m0"].x() - c.x()))
            a1 = math.degrees(math.atan2(m.y() - c.y(), m.x() - c.x()))
            if d.get("modal") and self._typed(d) is not None:
                return "transform", {"rotation": round(box.deg + self._typed(d), 2)}
            return "transform", {"rotation": round(snap_angle(box.deg + a1 - a0, free), 2)}
        if kind == "gscale":                                   # S: the scale follows how far the pointer is from the pivot
            c = box.pivot_pt()
            r0 = max(math.hypot(d["m0"].x() - c.x(), d["m0"].y() - c.y()), 30 * self._k())
            f = self._typed(d)
            if f is None:
                f = math.hypot(m.x() - c.x(), m.y() - c.y()) / r0
            scale = lambda s: math.copysign(max(0.01, abs(s * f)), s or 1.0)
            return "transform", {"scale": round(scale(box.s), 4), "scale_y": round(scale(box.sy), 4)}
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
        if g.kind == "text":
            return self._text_node_values(box, g, kind, q, free)
        out = {}
        if "w" in kind:
            out["w"] = round(max(0.01, 2 * abs(q.x()) / g.dw), 4)
        if "h" in kind:
            out["h"] = round(max(0.01, 2 * abs(q.y()) / g.dh), 4)
        if kind == "wh" and g.kind in ("compound", "image", "video", "track", "place") and not free:   # a picture keeps its proportions (Shift: free)
            vx, vy = g.mw * g.dw, g.mh * g.dh                       # the corner, from the centre
            f = max(0.01 / max(g.mw, g.mh, 1e-6), (abs(q.x()) * vx + abs(q.y()) * vy) * 2 / max(vx * vx + vy * vy, 1e-9))
            out = {"w": round(g.mw * f, 4), "h": round(g.mh * f, 4)}
            return "mask", self._snap_mask("w", out, g, box, bool(e.modifiers() & Qt.AltModifier), keep=g.mh / max(g.mw, 1e-9))
        return "mask", self._snap_mask(kind, out, g, box, bool(e.modifiers() & Qt.AltModifier))

    def _text_node_values(self, box, g, kind, q, free):
        """("multi", values) of a drag of a size handle of a text node's frame: its 文字框 (an edge fixes its own side, a
        corner both - as a text clip's), or, with no box, its 字號 as the clip is scaled."""
        eid, nid, _node, spec = text_node(box.clip, self.mask_group, box.t)
        nw, nh = max(1.0, 2 * abs(q.x())), max(1.0, 2 * abs(q.y()))        # (canvas px, about its centre)
        group = {}
        if textlayout.boxed(spec):
            k = 1080 / box.H
            for f, n, on in (("box_w", nw, "w" in kind), ("box_h", nh, "h" in kind)):
                if on:
                    group[nodegraph.param_key(nid, f)] = round(n * k, 1)
        else:
            cw, ch = g.mw * g.dw, g.mh * g.dh
            f = nw / cw if kind == "w" else nh / ch if kind == "h" else (
                (abs(q.x()) * cw + abs(q.y()) * ch) * 2 / max(cw * cw + ch * ch, 1e-9))
            group[nodegraph.param_key(nid, "size")] = round(min(200.0, max(0.1, (spec.get("size") or 1.0) * f)), 2)
        return "multi", {"fx:" + eid: group}

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

    def _grabs_anchor(self, box, m, k, mods):
        """Whether a press at m takes the anchor's diamond: once it is off the centre, else with
        Alt (a plain press there moves the clip)."""
        return self._near(box.anchor_pt(), m, k * PIVOT_PICK) and (
            any(abs(v) > 1e-9 for v in box.anchor) or bool(mods & Qt.AltModifier))

    def _anchor_values(self, box, d, m):
        """anchor_x / anchor_y of a drag of the anchor (錨點) from d["m0"] to m: the diamond stays
        where 位置 puts it and the clip moves the other way; x / y are not touched."""
        a0 = d["a0"]
        return {"anchor_x": round(a0[0] + (m.x() - d["m0"].x()) / (box.W / 2), 5),
                "anchor_y": round(a0[1] - (m.y() - d["m0"].y()) / (box.H / 2), 5)}

    def _grabs_pivot(self, box, m, k, mods):
        """Whether a press at m takes the pivot's ring: once it is off the centre, else with
        Ctrl (a plain press at the centre moves the clip)."""
        return self._near(box.pivot_pt(), m, k * PIVOT_PICK) and (
            any(abs(v) > 1e-9 for v in box.pivot) or bool(mods & Qt.ControlModifier))

    def _pivot_values(self, box, m, mods):
        """pivot_x / pivot_y of a drag of the pivot (中心點) to canvas point m, and x / y so
        unchanged (like CSS transform-origin: x / y place the clip, the pivot only says what it
        turns and scales about, so a turned or scaled clip swings round the new pivot). It snaps to the clip's centre, corners and edge
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
        return {"pivot_x": px, "pivot_y": py}

    def _snap_scale(self, box, others, driven, anchor, ks, tied):
        """Snap the factors ks = (kx, ky) of a scale drag so that a moving edge lands on the
        canvas centre lines / edges or another clip's centre / edges. Only for a clip turned by
        a right angle (its edges are then upright); `driven`: which axes the drag changes,
        `anchor`: the clip-frame point that stays put, `tied`: kx = ky. Returns (kx, ky, guides)."""
        r = box.deg % 90
        if min(r, 90 - r) > 0.01:
            return ks[0], ks[1], []
        tol = SNAP_PX * self._k()
        ex, ey = self._extra_targets()
        targets = {"x": [self.W / 2, 0, self.W] + ex, "y": [self.H / 2, 0, self.H] + ey}
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
        if d.get("modal"):
            d["pos"] = self.wrap.pos(e)
            d["m"], d["mods"] = QPointF(*self._to_canvas(d["pos"])), e.modifiers()
            self._grab_update()
            return
        if "wrap_pan" not in d:                          # (this drag's first move)
            self.wrap.start()
            d["wrap_pan"] = QPointF(self.pan)
        pos = self.wrap.pos(e)
        if d["kind"] == "pan":
            self.pan = d["pan"] + pos - d["pos"]
            self.glide.sample(pos.x(), pos.y())
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
        if d["kind"] == "guide":
            self._guide_move(d, e, m)
            return
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
        self._live(d, group, vals)

    def leaveEvent(self, e):
        if self.gap_hover:
            self.gap_hover = None
            self.update()
        super().leaveEvent(e)

    def _hover(self, e):
        if not self.interactive or not self.view or self.box_zoom or not self.show_guides:
            return
        x, y = self._to_canvas(e.position())
        m, k = QPointF(x, y), self._k()
        self._measure_update(bool(e.modifiers() & Qt.AltModifier), x, y)
        if self.show_rulers and (e.position().x() < RULER_PX) != (e.position().y() < RULER_PX):
            self.setCursor(Qt.SizeVerCursor if e.position().y() < RULER_PX else Qt.SizeHorCursor)
            return
        if (g := self._guide_at(m, k)) is not None and not any(b.contains(x, y) for b in self.visible_boxes() if not b.locked):
            self.setCursor(Qt.SizeVerCursor if g[0] == "y" else Qt.SizeHorCursor)
            return
        box = self.selected_box()
        cur = Qt.ArrowCursor
        hover = None
        mbox = self.mask_box(box)
        if self.gizmo_hit(box, m, k) is not None:
            cur = Qt.PointingHandCursor
        elif mbox is not None and self.masking(mbox):
            g = MaskGeo(mbox, self.mask_of(box.clip))
            if any(self._near(pt, m, k) for _, pt in g.handles(k)):
                cur = Qt.PointingHandCursor
            elif g.contains(m):
                cur = Qt.SizeAllCursor
        elif self.multi():
            boxes = self._live_boxes()
            l, r, t, b = self._union(boxes) if boxes else (0, 0, 0, 0)
            pad = 2 * PICK_PX * touch.scale() * k
            if (gap := self._gap_at(m, k)) is not None:
                cur, hover = (Qt.SizeHorCursor if gap[0] == "x" else Qt.SizeVerCursor), "handle"
            elif any(grabs(bx, x, y) for bx in boxes):
                cur, hover = Qt.SizeAllCursor, "group"
            elif l - pad <= x <= r + pad and t - pad <= y <= b + pad:
                hover = "group"
        elif box is not None and not self.mask_mode and self.gizmo_effect(box) is not None:
            if grabs(box, x, y):
                cur = Qt.SizeAllCursor
        elif box is not None and not self.mask_mode:
            if self._near(box.rot_handle(k), m, k):
                cur = Qt.PointingHandCursor
            elif not getattr(box, "group", False) and (self._grabs_anchor(box, m, k, e.modifiers())
                                                       or self._grabs_pivot(box, m, k, e.modifiers())):
                cur = Qt.CrossCursor
            elif (side := next(((sx, sy) for sx, sy, pt in box.handles() if self._near(pt, m, k)), None)):
                sx, sy = side
                cur = (Qt.SizeHorCursor if not sy else Qt.SizeVerCursor if not sx else
                       Qt.SizeFDiagCursor if sx == sy else Qt.SizeBDiagCursor)
            elif self._has_radius_handles(box) and any(self._near(pt, m, k) for _, pt in self.radius_handles(box, k)):
                cur = Qt.PointingHandCursor
            elif grabs(box, x, y):
                cur = Qt.SizeAllCursor
        if hover != self.gap_hover:                      # the gap bars show while over the selection
            self.gap_hover = hover
            self.update()
        self.setCursor(cur)

    def _commit(self, d, live):
        if live[0] == "moves" and d.get("dup"):
            self.dupCommitted.emit(live[1])
        elif live[0] == "moves":
            self.movesCommitted.emit(live[1])
        else:
            self.paramsCommitted.emit(d["box"].clip["id"], *live)

    def mouseReleaseEvent(self, e):
        if self.drag and self.drag.get("modal"):
            return
        d, self.drag = self.drag, None
        self.wrap.stop(d and d.get("live"))            # (the pointer where the drag ended up)
        if d and d["kind"] in ("pan", "zoomdrag"):
            self.setCursor(Qt.CrossCursor if self.box_zoom else Qt.ArrowCursor)
            if d["kind"] == "pan":
                self.glide.release()
            return
        if d and d["kind"] == "zoombox":
            self._arm_box_zoom(False)
            if d["moved"]:
                rc = d["rect"]
                self.view_rect(rc.left(), rc.right(), rc.top(), rc.bottom(), margin=0)
            self.update()
            return
        if d and d["kind"] == "guide":
            live, self.guide_live = self.guide_live, None
            if d["moved"] and live is not None:
                self.guidesCommitted.emit({"x": live[0], "y": live[1]})
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
            self._commit(d, live)
        self.update()

    def mouseDoubleClickEvent(self, e):
        if not self.interactive:
            self.doubleClicked.emit()
            return
        if e.button() != Qt.LeftButton or not self.view:
            return
        x, y = self._to_canvas(e.position())
        if self.mask_mode:                               # (a text node's frame: its words are typed in as a text clip's)
            self._edit_source_text(QPointF(x, y))
            return
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
        elif hit is None:                                # (double click / tap on nothing: the whole picture)
            self.view_fit()

    # -- typing a text clip's words on the canvas -------------------------------------------------
    def _screen_rect(self, box):
        """Where box (a clip's Box, or a text node's MaskGeo) is on the widget (its bounding rectangle)."""
        r = self._rect()
        pts = box.corners() if hasattr(box, "corners") else list(box.xf.map(QPolygonF(
            QRectF(-box.hw, -box.hh, 2 * box.hw, 2 * box.hh))))
        xs = [r.x() + pt.x() / self.W * r.width() for pt in pts]
        ys = [r.y() + pt.y() / self.H * r.height() for pt in pts]
        return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    def _edit_source_text(self, m):
        """Double-click at canvas point m while a text node's frame is edited: its words open for typing."""
        box = self.selected_box()
        mbox = self.mask_box(box)
        if mbox is None or not self.masking(mbox):
            return
        info = text_node(box.clip, self.mask_group, box.t)
        src = self.mask_of(box.clip)
        if not info or nodegraph.constant_into(self._graph_of(box.clip), info[1], nodegraph.TEXT_SOCKET) is not None \
                or curves.is_animated(src.get("content")):
            return                                       # (words that a string node gives are edited there)
        g = MaskGeo(mbox, src)
        if not g.contains(m):
            return
        self.drag = None
        self.close_text_box()
        eid, nid = info[0], info[1]
        self.text_box = TextBox(self, box.clip["id"], str(src.get("content", "")))
        self.text_box.source = (eid, nid)
        self.text_box.edited.connect(lambda cid, words: self.sourceTextEdited.emit(cid, eid, nid, words))
        self.text_box.finished.connect(self.close_text_box)
        self._place_text_box(g)
        self.text_box.show()
        self.text_box.setFocus()
        self.text_box.selectAll()

    def _graph_of(self, clip):
        eid = self.mask_group[6:].partition(":")[0]
        try:
            return edit.holder(clip, "fxmix:" + eid).get("graph")
        except (edit.EditError, KeyError):
            return None

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
        self.source = None                      # (effect id, node id) when it types a text node's words
        self.setPlainText(words)
        self.setToolTip("Ctrl+Enter 或點別的地方完成，Esc 還原")
        self.setStyleSheet("QPlainTextEdit { background: rgba(20, 20, 24, 225); color: #ffffff;"
                           " border: 2px solid #4da3ff; border-radius: 0; font-size: 15px; }")
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
        p.setPen(QColor("#ffffff"))
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

    def __init__(self, cover=None):
        """cover: a window to cover, as a widget of its own - where a second window of the program is a poor thing (Android's: closing
        it while the video plays ended the program); None: a window of its own, set fullscreen."""
        if cover is None:
            super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        else:
            super().__init__(cover)
            cover.installEventFilter(self)
        self.cover = cover
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
        elif obj is self.cover and e.type() == QEvent.Resize:
            self.setGeometry(self.cover.rect())                  # (it goes on covering the window)
        return False

    def present(self):
        """Show it over the whole screen (or over the window it covers)."""
        if self.cover is None:
            self.showFullScreen()
            return
        self.setGeometry(self.cover.rect())
        self.show()
        self.raise_()
        self.setFocus()

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
