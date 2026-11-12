"""The pen tool (鋼筆工具): draw and edit Bézier paths on the preview.

P with the mouse over the preview (or the 鋼筆 button) starts a new path: a click puts a corner point, a click and drag a smooth
one (the drag pulls its out handle, the in handle mirrors it; Alt: only the out one), Shift keeps the next point to a 45° step
from the last, a click on the first point closes the path (a fill), Enter / double click / the right button ends an open one (a
line), Backspace takes the last point back, Esc drops the path. It becomes a "path" built-in asset clip (assets.path_params) at the
playhead, which has the usual fill / outline / colour parameters.

A path clip is edited with a double click on it (or Enter with it selected). A clip has one or more paths (parts, holes show
where they overlap). Points: click selects one (Shift+click adds or takes out), a drag from empty space boxes some in (Shift: added),
dragging a selected point moves all selected ones, arrow keys move them by a pixel (Shift: ten), Delete takes them out, Ctrl+A
selects all. Handles: drag one (a smooth point keeps its handles in line, Alt breaks that). A click on a segment adds a point,
Alt+click on a point toggles corner / smooth (all selected ones). Ctrl+click on the end of an open path goes on drawing from it
(a click on the first point closes it, on the end of another open path joins the two), Shift+click on empty space starts a
new part. Enter / Esc end the drawing, then the tool; a click on another clip ends it and picks that clip. Every change is one
edit (paramsCommitted, group "multi": the paths, the frame they fill and where it sits).

A bar over the preview's bottom edge sets the kind of the selected points (the last one while drawing): 角點, 自動, 對齊 (handles in
line, any lengths), 自由 (independent; a 7th value 1 on the node), 向量 (handles toward the neighbours), and 封閉 / 開口 for their path.

Nodes here are [x, y, in dx, in dy, out dx, out dy] in canvas px (the handles as offsets from their point); a path is
{"nodes": [...], "closed": bool}. combine() / paths_of_qpath() / qpath_of_paths() are the boolean operations of 路徑運算.
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from .. import assets

PEN_COLOR = "#2dd4ff"
SEG_PICK_PX = 6
CLOSE_PICK_PX = 9
OPS = (("聯集", "union"), ("差集", "subtract"), ("交集", "intersect"), ("排除", "xor"))


# -- geometry (nodes are lists, points tuples) -------------------------------------------------------------------------------
def pairs(nodes, closed):
    """[(i, j)] the segments from node i to node j."""
    n = len(nodes)
    return [(i, i + 1) for i in range(n - 1)] + ([(n - 1, 0)] if closed and n > 2 else [])


def painter_path(nodes, closed):
    path = QPainterPath()
    if not nodes:
        return path
    path.moveTo(nodes[0][0], nodes[0][1])
    for i, j in pairs(nodes, closed):
        a, b = nodes[i], nodes[j]
        if a[4] == a[5] == b[2] == b[3] == 0:
            path.lineTo(b[0], b[1])
        else:
            path.cubicTo(a[0] + a[4], a[1] + a[5], b[0] + b[2], b[1] + b[3], b[0], b[1])
    if closed and len(nodes) > 2:
        path.closeSubpath()
    return path


def nearest_on_segment(nodes, i, j, pt, steps=32):
    """(distance, t) of the point of the segment i -> j closest to pt (t: 0 - 1 along it, by sampling)."""
    pts = assets.bezier_points(nodes[i], nodes[j], steps)
    best = (math.inf, 0.0)
    for s, (p, q) in enumerate(zip(pts, pts[1:])):
        dx, dy = q[0] - p[0], q[1] - p[1]
        ln = dx * dx + dy * dy
        u = 0.0 if ln == 0 else min(1.0, max(0.0, ((pt[0] - p[0]) * dx + (pt[1] - p[1]) * dy) / ln))
        d = math.hypot(pt[0] - (p[0] + u * dx), pt[1] - (p[1] + u * dy))
        if d < best[0]:
            best = (d, (s + u) / steps)
    return best


def hit_segment(nodes, closed, pt, tol):
    """(segment index into pairs(), t) of the segment within tol of pt, else None."""
    best = None
    for n, (i, j) in enumerate(pairs(nodes, closed)):
        d, t = nearest_on_segment(nodes, i, j, pt)
        if d <= tol and (best is None or d < best[0]):
            best = (d, n, t)
    return None if best is None else (best[1], best[2])


def split(nodes, closed, seg, t):
    """The nodes with a new one on segment `seg` (of pairs()) at t, the curve kept as it is (de Casteljau); (nodes, its index)."""
    nodes = [list(n) for n in nodes]
    i, j = pairs(nodes, closed)[seg]
    a, b = nodes[i], nodes[j]
    p0, p1 = (a[0], a[1]), (a[0] + a[4], a[1] + a[5])
    p2, p3 = (b[0] + b[2], b[1] + b[3]), (b[0], b[1])
    lerp = lambda u, v: (u[0] + (v[0] - u[0]) * t, u[1] + (v[1] - u[1]) * t)
    q0, q1, q2 = lerp(p0, p1), lerp(p1, p2), lerp(p2, p3)
    r0, r1 = lerp(q0, q1), lerp(q1, q2)
    m = lerp(r0, r1)
    a[4], a[5] = q0[0] - p0[0], q0[1] - p0[1]
    b[2], b[3] = q2[0] - p3[0], q2[1] - p3[1]
    new = [m[0], m[1], r0[0] - m[0], r0[1] - m[1], r1[0] - m[0], r1[1] - m[1]]
    at = i + 1
    nodes.insert(at, new)
    return nodes, at


def is_smooth(n):
    """Whether the handles of node n are held in line (a 對齊 / 自動 point): in line, opposite ways, and not set 自由."""
    if len(n) > 6 and n[6]:
        return False
    ix, iy, ox, oy = n[2:6]
    li, lo = math.hypot(ix, iy), math.hypot(ox, oy)
    return li > 1e-6 and lo > 1e-6 and abs(ix * oy - iy * ox) <= 1e-3 * li * lo and ix * ox + iy * oy < 0


def _neighbours(nodes, closed, i):
    cnt = len(nodes)
    prev = nodes[(i - 1) % cnt] if (i > 0 or closed) and cnt > 1 else None
    nxt = nodes[(i + 1) % cnt] if (i < cnt - 1 or closed) and cnt > 1 else None
    return prev, nxt


def auto_handles(nodes, closed, i):
    """Node i's handles along the line between its neighbours, a third of the way to each (an end: its one neighbour)."""
    n = nodes[i]
    prev, nxt = _neighbours(nodes, closed, i)
    a, b = prev or n, nxt or n
    tx, ty = b[0] - a[0], b[1] - a[1]
    ln = math.hypot(tx, ty)
    if ln < 1e-9:
        return
    tx, ty = tx / ln, ty / ln
    lin = math.hypot(n[0] - prev[0], n[1] - prev[1]) / 3 if prev else 0.0
    lout = math.hypot(nxt[0] - n[0], nxt[1] - n[1]) / 3 if nxt else 0.0
    n[2:6] = [-tx * lin, -ty * lin, tx * lout, ty * lout]


TYPES = (("corner", "角點：沒有把手"), ("auto", "自動：把手順著前後兩點的連線"), ("aligned", "對齊：兩邊把手成一直線，各自可長可短"),
         ("free", "自由：兩邊把手各自獨立"), ("vector", "向量：把手指向前後的點"))


def set_type(nodes, closed, i, kind):
    """Node i made a corner / auto / aligned / free / vector point (the handles it has are kept where that can be)."""
    n = nodes[i]
    prev, nxt = _neighbours(nodes, closed, i)
    del n[6:]
    if kind == "corner":
        n[2:6] = [0.0, 0.0, 0.0, 0.0]
    elif kind == "auto":
        auto_handles(nodes, closed, i)
    elif kind == "vector":
        n[2:6] = [(prev[0] - n[0]) / 3 if prev else 0.0, (prev[1] - n[1]) / 3 if prev else 0.0,
                  (nxt[0] - n[0]) / 3 if nxt else 0.0, (nxt[1] - n[1]) / 3 if nxt else 0.0]
        n.append(1.0)
    else:
        if not any(n[2:6]):
            auto_handles(nodes, closed, i)
        if kind == "free":
            n.append(1.0)
        else:                                                   # aligned: the longer handle sets the line
            li, lo = math.hypot(n[2], n[3]), math.hypot(n[4], n[5])
            if lo >= li and lo > 1e-9:
                n[2], n[3] = -n[4] / lo * li, -n[5] / lo * li
            elif li > 1e-9:
                n[4], n[5] = -n[2] / li * lo, -n[3] / li * lo


def toggle_smooth(nodes, closed, i):
    """Alt+click on a point: one with handles becomes a corner (no handles), a corner a smooth one (自動)."""
    n = nodes[i]
    set_type(nodes, closed, i, "corner" if any(n[2:6]) else "auto")


def set_handle(n, which, dx, dy, mirror):
    """Handle `which` ("in" / "out") of node n to offset (dx, dy); mirror: the other one turns to stay in line (its length kept)."""
    a, b = (2, 4) if which == "in" else (4, 2)
    n[a], n[a + 1] = dx, dy
    if mirror:
        ln, own = math.hypot(n[b], n[b + 1]), math.hypot(dx, dy)
        if own > 1e-9:
            n[b], n[b + 1] = -dx / own * ln, -dy / own * ln


def reversed_path(sub):
    """The path run the other way (in and out handles swap)."""
    return {"nodes": [[n[0], n[1], n[4], n[5], n[2], n[3]] + list(n[6:]) for n in reversed(sub["nodes"])], "closed": sub["closed"]}


def joined(a, b, a_end, b_end):
    """Open path a's end (a_end: "last" or "first") joined to open path b's end b_end, as one path."""
    a = a if a_end == "last" else reversed_path(a)
    b = b if b_end == "first" else reversed_path(b)
    nodes = [list(n) for n in a["nodes"]] + [list(n) for n in b["nodes"]]
    return {"nodes": nodes, "closed": False}


# -- boolean operations (路徑運算) -----------------------------------------------------------------------------------------------
def qpath_of_paths(paths):
    """One QPainterPath of subpaths (every one closed: an operation works on what a path encloses)."""
    out = QPainterPath()
    out.setFillRule(Qt.OddEvenFill)
    for sub in paths:
        if len(sub["nodes"]) > 1:
            q = painter_path(sub["nodes"], True)
            q.closeSubpath()
            out.addPath(q)
    return out


def paths_of_qpath(qp):
    """[{"nodes", "closed"}] of QPainterPath qp: its curves keep their handles, a subpath that comes back to its start is closed."""
    subs, cur = [], None
    n = qp.elementCount()
    i = 0
    while i < n:
        el = qp.elementAt(i)
        if el.type == QPainterPath.MoveToElement:
            cur = [[el.x, el.y, 0.0, 0.0, 0.0, 0.0]]
            subs.append(cur)
        elif el.type == QPainterPath.LineToElement and cur is not None:
            cur.append([el.x, el.y, 0.0, 0.0, 0.0, 0.0])
        elif el.type == QPainterPath.CurveToElement and cur is not None and i + 2 < n:
            c2, e = qp.elementAt(i + 1), qp.elementAt(i + 2)
            prev = cur[-1]
            prev[4], prev[5] = el.x - prev[0], el.y - prev[1]
            cur.append([e.x, e.y, c2.x - e.x, c2.y - e.y, 0.0, 0.0])
            i += 2
        i += 1
    out = []
    for nodes in subs:
        closed = len(nodes) > 2 and math.hypot(nodes[0][0] - nodes[-1][0], nodes[0][1] - nodes[-1][1]) < 1e-6
        if closed:
            last = nodes.pop()
            nodes[0][2], nodes[0][3] = last[2], last[3]
        # (points that sit on top of each other add nothing)
        clean = []
        for nd in nodes:
            if clean and math.hypot(nd[0] - clean[-1][0], nd[1] - clean[-1][1]) < 1e-6:
                clean[-1][4:] = nd[4:]
                continue
            clean.append(nd)
        if len(clean) > 1:
            out.append({"nodes": clean, "closed": closed and len(clean) > 2})
    return out


def combine(op, qpaths):
    """The QPainterPath of boolean operation op ("union", "subtract", "intersect", "xor") over qpaths: the first minus / with / ..."""
    path = qpaths[0]
    for other in qpaths[1:]:
        if op == "subtract":
            path = path.subtracted(other)
        elif op == "intersect":
            path = path.intersected(other)
        elif op == "xor":
            path = path.united(other).subtracted(path.intersected(other))
        else:
            path = path.united(other)
    return path


# -- the tool, as part of the preview ----------------------------------------------------------------------------------------
class PenMixin:
    """The pen tool's state and events; Preview calls these first while self.pen is not None (see its mouse / key handlers).
    self.pen: {"paths", "cur" (the path being drawn into, or None), "edit" (clip id or None), "box" (its Box), "sel" ({(path, node)}),
    "drag", "hover"}."""

    def pen_begin(self):
        """Start drawing a new path."""
        if not self.interactive or not self.view or self.pen is not None or self.drag is not None or self.mask_mode:
            return False
        self.pen = {"paths": [{"nodes": [], "closed": False}], "cur": 0, "edit": None, "box": None, "sel": set(), "drag": None,
                    "hover": None}
        self.setCursor(Qt.CrossCursor)
        self._show_penbar()
        self.penToggled.emit(True)
        self.update()
        return True

    def _show_penbar(self):
        if getattr(self, "penbar", None) is None:
            self.penbar = PenBar(self)
        self.penbar.show()
        self.place_penbar()

    def place_penbar(self):
        bar = getattr(self, "penbar", None)
        if bar is not None and bar.isVisible() and bar.parent() is self:      # (one in the header above the preview stays there)
            bar.adjustSize()
            bar.move(max(4, (self.width() - bar.width()) // 2), self.height() - bar.height() - 10)
            bar.raise_()

    def pen_can_edit(self):
        box = self.selected_box()
        return (box is not None and self.pen is None and not self.multi() and not getattr(box, "group", False)
                and not getattr(box, "locked", False) and (box.clip.get("asset") or {}).get("family") == "path"
                and not self.mask_mode and self.drag is None)

    def pen_edit(self, box=None):
        """Edit the paths of the selected path clip (box) on the canvas."""
        box = box or self.selected_box()
        if box is None or not self.interactive or self.pen is not None or (box.clip.get("asset") or {}).get("family") != "path":
            return False
        self.pen = {"paths": [], "cur": None, "edit": box.clip["id"], "box": box, "sel": set(), "drag": None, "hover": None}
        self._pen_load(box)
        self.setCursor(Qt.ArrowCursor)
        self._show_penbar()
        self.penToggled.emit(True)
        self.update()
        return True

    def pen_end(self):
        self.pen = None
        self.guides = []
        self.unsetCursor()
        if getattr(self, "penbar", None) is not None:
            self.penbar.hide()
        self.penToggled.emit(False)
        self.update()

    def _pen_load(self, box):
        """The clip's paths in canvas px (through its transform) into the tool."""
        q = assets.at(box.clip["asset"], box.t)
        w, h = q["w"], q["h"]
        xf = box.xf()
        paths = []
        for sub in q["paths"]:
            nodes = []
            for n in sub["nodes"]:
                lx, ly = (n[0] - 0.5) * w, (n[1] - 0.5) * h
                c = xf.map(QPointF(lx, ly))
                i = xf.map(QPointF(lx + n[2] * w, ly + n[3] * h)) - c
                o = xf.map(QPointF(lx + n[4] * w, ly + n[5] * h)) - c
                nodes.append([c.x(), c.y(), i.x(), i.y(), o.x(), o.y()] + list(n[6:]))
            paths.append({"nodes": nodes, "closed": bool(sub["closed"])})
        pen = self.pen
        pen["paths"], pen["box"] = paths, box
        pen["sel"] = {(pi, ni) for pi, ni in pen["sel"] if pi < len(paths) and ni < len(paths[pi]["nodes"])}

    def pen_reload(self):
        """The scene changed (an edit was made): an edited path takes the clip's paths again, or the tool ends if it went."""
        pen = self.pen
        if pen is None or pen["edit"] is None or pen["drag"] is not None or pen["cur"] is not None:
            return
        box = next((b for b in self.visible_boxes() if b.clip["id"] == pen["edit"]), None)
        if box is None or box.clip["id"] != self.selected_id:
            self.pen_end()
            return
        self._pen_load(box)

    # -- finishing ------------------------------------------------------------------------------------------------------
    def _pen_tidy(self):
        """Paths with a point twice in a row (a double click) or too short thrown out."""
        out = []
        for sub in self.pen["paths"]:
            nodes = [list(n) for n in sub["nodes"]]
            if len(nodes) > 1 and math.hypot(nodes[-1][0] - nodes[-2][0], nodes[-1][1] - nodes[-2][1]) < 1e-6:
                nodes.pop()
            if len(nodes) >= 2:
                out.append({"nodes": nodes, "closed": bool(sub["closed"]) and len(nodes) > 2})
        return out

    def _pen_finish(self):
        """Enter / double click / close: a new path becomes a clip; in an edited one the drawing stops and is kept."""
        pen = self.pen
        if pen["edit"] is not None:
            if pen["cur"] is not None:
                pen["cur"] = None
                pen["paths"] = self._pen_tidy() or pen["paths"]
                self._pen_commit()
            self.update()
            return
        paths = self._pen_tidy()
        self.pen_end()
        if paths:
            self.penFinished.emit(paths)

    def _pen_commit(self):
        """An edited path as one edit: its paths in the clip's own frame, the frame they fill and where it sits."""
        pen = self.pen
        box = pen["box"]
        inv, ok = box.xf().inverted()
        paths = [s for s in pen["paths"] if len(s["nodes"]) >= 2]
        if not ok or not paths:
            return
        local = []
        for sub in paths:
            nodes = []
            for n in sub["nodes"]:
                c = inv.map(QPointF(n[0], n[1]))
                i = inv.map(QPointF(n[0] + n[2], n[1] + n[3])) - c
                o = inv.map(QPointF(n[0] + n[4], n[1] + n[5])) - c
                nodes.append([c.x(), c.y(), i.x(), i.y(), o.x(), o.y()] + list(n[6:]))
            local.append({"nodes": nodes, "closed": sub["closed"]})
        params, (cx, cy) = assets.path_params(local)
        centre = box.xf().map(QPointF(cx, cy))
        self.paramsCommitted.emit(box.clip["id"], "multi", {
            "asset": {"paths": params["paths"], "w": params["w"], "h": params["h"]},
            "transform": {"x": box.x_at(centre.x()), "y": box.y_at(centre.y())}})

    # -- snapping -------------------------------------------------------------------------------------------------------
    def _pen_snap(self, pt, mods, skip=()):
        """pt (canvas px) settled on the canvas centre / edges, reference lines, the grid and the other points' lines (Ctrl:
        freely; Shift with a point before it: a 45° step from it)."""
        self.guides = []
        pen = self.pen
        x, y = pt.x(), pt.y()
        cur = pen["paths"][pen["cur"]]["nodes"] if pen["cur"] is not None else []
        last = cur[-1] if cur else None
        if mods & Qt.ShiftModifier and last is not None:
            dx, dy = x - last[0], y - last[1]
            ang = round(math.atan2(dy, dx) / (math.pi / 4)) * math.pi / 4
            r = math.hypot(dx, dy)
            return QPointF(last[0] + r * math.cos(ang), last[1] + r * math.sin(ang))
        if mods & Qt.ControlModifier:
            return QPointF(x, y)
        tol = 7 * self._k()
        ex, ey = self._extra_targets()
        others = [n for pi, sub in enumerate(pen["paths"]) for ni, n in enumerate(sub["nodes"]) if (pi, ni) not in skip]
        tx = [self.W / 2, 0, self.W] + ex + [n[0] for n in others]
        ty = [self.H / 2, 0, self.H] + ey + [n[1] for n in others]
        hx, hy = self._best([x], tx, tol), self._best([y], ty, tol)
        if hx:
            x = hx[1]
            self.guides.append(("x", x))
        if hy:
            y = hy[1]
            self.guides.append(("y", y))
        return QPointF(x, y)

    # -- events ---------------------------------------------------------------------------------------------------------
    def _pen_hit(self, m, k):
        """What is under canvas point m: ("handle", path, node, "in" / "out"), ("node", path, node), ("seg", path, seg, t) or None."""
        paths = self.pen["paths"]
        for pi, sub in enumerate(paths):
            for ni, n in enumerate(sub["nodes"]):
                for which, a in (("in", 2), ("out", 4)):
                    if (n[a] or n[a + 1]) and self._near(QPointF(n[0] + n[a], n[1] + n[a + 1]), m, k):
                        return "handle", pi, ni, which
        for pi, sub in enumerate(paths):
            for ni, n in enumerate(sub["nodes"]):
                if self._near(QPointF(n[0], n[1]), m, k):
                    return "node", pi, ni
        for pi, sub in enumerate(paths):
            seg = hit_segment(sub["nodes"], sub["closed"], (m.x(), m.y()), SEG_PICK_PX * k)
            if seg:
                return ("seg", pi) + seg
        return None

    @staticmethod
    def _is_end(sub, ni):
        return not sub["closed"] and ni in (0, len(sub["nodes"]) - 1)

    def _pen_continue(self, pi, ni):
        """Go on drawing from the end of open path pi (its first point: the path is turned round first)."""
        pen = self.pen
        sub = pen["paths"][pi]
        if ni == 0 and len(sub["nodes"]) > 1:
            pen["paths"][pi] = reversed_path(sub)
        pen["cur"] = pi
        pen["sel"] = set()

    def pen_press(self, e):
        pen = self.pen
        k = self._k()
        m = QPointF(*self._to_canvas(e.position()))
        mods = e.modifiers()
        if e.button() == Qt.RightButton:
            if pen["cur"] is not None:
                self._pen_finish()
            elif pen["edit"] is not None:
                self.pen_end()
            return
        if e.button() != Qt.LeftButton:
            return
        paths = pen["paths"]
        if pen["cur"] is not None:                                  # drawing into a path
            sub = paths[pen["cur"]]
            nodes = sub["nodes"]
            if len(nodes) >= 3 and self._near(QPointF(nodes[0][0], nodes[0][1]), m, k * CLOSE_PICK_PX / 9):
                sub["closed"] = True
                self._pen_finish()
                return
            if pen["edit"] is not None and nodes:                   # the end of another open path: the two are joined
                for pi, other in enumerate(paths):
                    if pi == pen["cur"] or other["closed"]:
                        continue
                    for ni in (0, len(other["nodes"]) - 1):
                        n = other["nodes"][ni]
                        if self._near(QPointF(n[0], n[1]), m, k):
                            ends = ("first" if ni == 0 else "last")
                            paths[pen["cur"]] = joined(sub, other, "last", ends)
                            del paths[pi]
                            pen["cur"] = None
                            self._pen_commit()
                            self.update()
                            return
            p = self._pen_snap(m, mods)
            nodes.append([p.x(), p.y(), 0.0, 0.0, 0.0, 0.0])
            pen["drag"] = {"kind": "new", "p": pen["cur"], "i": len(nodes) - 1, "m0": m, "moved": False}
            pen["sel"] = {(pen["cur"], len(nodes) - 1)}
            self.update()
            return
        hit = self._pen_hit(m, k)                                   # editing
        if hit is None:
            if mods & Qt.ShiftModifier:                             # a new part
                p = self._pen_snap(m, Qt.NoModifier)
                paths.append({"nodes": [[p.x(), p.y(), 0.0, 0.0, 0.0, 0.0]], "closed": False})
                pen["cur"] = len(paths) - 1
                pen["sel"] = set()
                self.update()
                return
            other = next((b for b in self.visible_boxes() if b.clip["id"] != pen["edit"] and not getattr(b, "locked", False)
                          and b.contains(m.x(), m.y())), None)
            if other is not None:                                   # another clip: the tool ends and the click picks it
                self.pen_end()
                self.mousePressEvent(e)
                return
            pen["drag"] = {"kind": "marquee", "m0": m, "rect": QRectF(m, m), "moved": False, "add": bool(mods & Qt.ShiftModifier),
                           "had": bool(pen["sel"])}
            return
        if hit[0] == "handle":
            _, pi, ni, which = hit
            pen["sel"] = {(pi, ni)}
            pen["drag"] = {"kind": "handle", "p": pi, "i": ni, "which": which, "moved": False, "m0": m,
                           "mirror": is_smooth(paths[pi]["nodes"][ni])}
        elif hit[0] == "node":
            _, pi, ni = hit
            sub = paths[pi]
            if mods & Qt.ControlModifier and self._is_end(sub, ni):
                self._pen_continue(pi, ni)
            elif mods & Qt.AltModifier:
                targets = pen["sel"] if (pi, ni) in pen["sel"] else {(pi, ni)}
                for tp, tn in targets:
                    toggle_smooth(paths[tp]["nodes"], paths[tp]["closed"], tn)
                pen["sel"] = set(targets)
                self._pen_commit()
            elif mods & Qt.ShiftModifier:
                pen["sel"] ^= {(pi, ni)}
            else:
                if (pi, ni) not in pen["sel"]:
                    pen["sel"] = {(pi, ni)}
                pen["drag"] = {"kind": "node", "p": pi, "i": ni, "m0": m, "moved": False,
                               "p0": {s: (paths[s[0]]["nodes"][s[1]][0], paths[s[0]]["nodes"][s[1]][1]) for s in pen["sel"]}}
        else:
            _, pi, seg, t = hit
            sub = paths[pi]
            sub["nodes"], at = split(sub["nodes"], sub["closed"], seg, t)
            pen["sel"] = {(pi, at)}
            self._pen_commit()
        self.update()

    def pen_move(self, e):
        pen = self.pen
        m = QPointF(*self._to_canvas(e.position()))
        d = pen["drag"]
        k = self._k()
        if d is None:
            pen["hover"] = self._pen_snap(m, e.modifiers()) if pen["cur"] is not None else m
            if pen["cur"] is None:
                self.setCursor(Qt.PointingHandCursor if self._pen_hit(m, k) else Qt.ArrowCursor)
            self.update()
            return
        if not d["moved"] and math.hypot(m.x() - d["m0"].x(), m.y() - d["m0"].y()) < 3 * k:
            return
        d["moved"] = True
        if d["kind"] == "marquee":
            d["rect"] = QRectF(d["m0"], m).normalized()
            self.update()
            return
        paths = pen["paths"]
        n = paths[d["p"]]["nodes"][d["i"]]
        alt = bool(e.modifiers() & Qt.AltModifier)
        if d["kind"] == "new":                                      # pulling a smooth point's handles out of the click
            dx, dy = m.x() - n[0], m.y() - n[1]
            if e.modifiers() & Qt.ShiftModifier:
                ang = round(math.atan2(dy, dx) / (math.pi / 4)) * math.pi / 4
                r = math.hypot(dx, dy)
                dx, dy = r * math.cos(ang), r * math.sin(ang)
            n[4], n[5] = dx, dy
            n[2], n[3] = (0.0, 0.0) if alt else (-dx, -dy)
        elif d["kind"] == "node":                                   # every selected point moves with the one dragged
            x0, y0 = d["p0"][(d["p"], d["i"])]
            p = self._pen_snap(QPointF(m.x() + x0 - d["m0"].x(), m.y() + y0 - d["m0"].y()), e.modifiers(), skip=set(d["p0"]))
            dx, dy = p.x() - x0, p.y() - y0
            for (sp, sn), (x0, y0) in d["p0"].items():
                node = paths[sp]["nodes"][sn]
                node[0], node[1] = x0 + dx, y0 + dy
        else:
            dx, dy = m.x() - n[0], m.y() - n[1]
            if e.modifiers() & Qt.ShiftModifier:
                ang = round(math.atan2(dy, dx) / (math.pi / 4)) * math.pi / 4
                r = math.hypot(dx, dy)
                dx, dy = r * math.cos(ang), r * math.sin(ang)
            set_handle(n, d["which"], dx, dy, d["mirror"] and not alt)
        self.update()

    def pen_release(self, e):
        pen = self.pen
        d, pen["drag"] = pen["drag"], None
        self.guides = []
        if d is not None and d["kind"] == "marquee":
            if d["moved"]:
                r = d["rect"]
                hit = {(pi, ni) for pi, sub in enumerate(pen["paths"]) for ni, n in enumerate(sub["nodes"]) if r.contains(n[0], n[1])}
                pen["sel"] = (pen["sel"] | hit) if d["add"] else hit
            elif not d["add"]:
                if d["had"]:
                    pen["sel"] = set()
                else:                                               # a click on nothing, with nothing selected: done
                    self.pen_end()
                    return
        elif d is not None and pen["edit"] is not None and d["moved"]:
            self._pen_commit()
        self.update()

    def pen_double_click(self, e):
        if self.pen["cur"] is not None:
            self._pen_finish()

    def pen_key(self, e):
        """The action of key e while the pen tool is on (a function), or None."""
        pen = self.pen
        k, mods = e.key(), e.modifiers()
        editing = pen["edit"] is not None
        if k in (Qt.Key_Return, Qt.Key_Enter):
            return self._pen_finish if pen["cur"] is not None else (self.pen_end if editing else self._pen_finish)
        if k == Qt.Key_Escape:
            if not editing:
                return self.pen_end
            if pen["cur"] is not None:
                return self._pen_finish
            return self._pen_clear_or_end
        if k in (Qt.Key_Backspace, Qt.Key_Delete):
            if pen["cur"] is not None and k == Qt.Key_Backspace:
                def back():
                    nodes = pen["paths"][pen["cur"]]["nodes"]
                    if nodes:
                        nodes.pop()
                    if not nodes and editing:
                        del pen["paths"][pen["cur"]]
                        pen["cur"] = None
                    self.update()
                return back
            if editing and pen["sel"]:
                return self._pen_delete_selected
            return None
        if k == Qt.Key_A and mods == Qt.ControlModifier and editing and pen["cur"] is None:
            def everything():
                pen["sel"] = {(pi, ni) for pi, sub in enumerate(pen["paths"]) for ni in range(len(sub["nodes"]))}
                self.update()
            return everything
        step = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}.get(k)
        if step and editing and pen["sel"] and pen["cur"] is None and not mods & (Qt.ControlModifier | Qt.AltModifier):
            n = 10 if mods & Qt.ShiftModifier else 1
            return lambda: self._pen_nudge(step[0] * n, step[1] * n)
        if k == Qt.Key_P and not mods:
            return self.pen_end if not editing and not pen["paths"][0]["nodes"] else None
        return None

    def pen_set_type(self, kind):
        """The toolbar's point types: the selected points (while drawing: the last one) become that kind."""
        pen = self.pen
        targets = set(pen["sel"])
        if not targets and pen["cur"] is not None and pen["paths"][pen["cur"]]["nodes"]:
            targets = {(pen["cur"], len(pen["paths"][pen["cur"]]["nodes"]) - 1)}
        if not targets:
            return
        for pi, ni in targets:
            sub = pen["paths"][pi]
            set_type(sub["nodes"], sub["closed"], ni, kind)
        if pen["edit"] is not None and pen["cur"] is None:
            self._pen_commit()
        self.update()

    def pen_toggle_closed(self):
        """The toolbar's 封閉 / 開口: the paths holding a selected point (the only one, or the one being drawn) are closed or opened."""
        pen = self.pen
        idx = {pi for pi, _ in pen["sel"]} or ({pen["cur"]} if pen["cur"] is not None else set(range(len(pen["paths"])))
                                               if len(pen["paths"]) == 1 else set())
        subs = [pen["paths"][pi] for pi in idx if len(pen["paths"][pi]["nodes"]) > 2 or pen["paths"][pi]["closed"]]
        if not subs:
            return
        on = not all(sub["closed"] for sub in subs)
        for sub in subs:
            sub["closed"] = on
        if pen["edit"] is None:
            if on:
                self._pen_finish()
        elif pen["cur"] is None:
            self._pen_commit()
        self.update()

    def pen_state(self):
        """(whether there is a point to give a kind to, whether the path in question is closed) for the toolbar."""
        pen = self.pen
        if pen is None:
            return False, False
        has = bool(pen["sel"]) or (pen["cur"] is not None and bool(pen["paths"][pen["cur"]]["nodes"]))
        idx = {pi for pi, _ in pen["sel"]} or ({pen["cur"]} if pen["cur"] is not None else set(range(len(pen["paths"]))))
        return has, bool(idx) and all(pen["paths"][pi]["closed"] for pi in idx if pi < len(pen["paths"]))

    def _pen_clear_or_end(self):
        if self.pen["sel"]:
            self.pen["sel"] = set()
            self.update()
        else:
            self.pen_end()

    def _pen_nudge(self, dx, dy):
        pen = self.pen
        for pi, ni in pen["sel"]:
            n = pen["paths"][pi]["nodes"][ni]
            n[0] += dx
            n[1] += dy
        self._pen_commit()
        self.update()

    def _pen_delete_selected(self):
        pen = self.pen
        keep = []
        for pi, sub in enumerate(pen["paths"]):
            nodes = [n for ni, n in enumerate(sub["nodes"]) if (pi, ni) not in pen["sel"]]
            if len(nodes) >= 2:
                keep.append({"nodes": nodes, "closed": sub["closed"] and len(nodes) > 2})
        if keep:
            pen["paths"] = keep
            pen["sel"] = set()
            self._pen_commit()
        self.update()

    # -- painting -------------------------------------------------------------------------------------------------------
    def paint_pen(self, p, k):
        pen = self.pen
        p.setBrush(Qt.NoBrush)
        for sub in pen["paths"]:
            if sub["nodes"]:
                path = painter_path(sub["nodes"], sub["closed"])
                p.setPen(QPen(QColor("#111114"), 3 * k))
                p.drawPath(path)
                p.setPen(QPen(QColor(PEN_COLOR), 1.5 * k))
                p.drawPath(path)
        hover = pen["hover"]
        cur = pen["paths"][pen["cur"]]["nodes"] if pen["cur"] is not None else []
        if cur and hover is not None and pen["drag"] is None:       # the next segment, as it will be
            a = cur[-1]
            q = QPainterPath(QPointF(a[0], a[1]))
            if a[4] or a[5]:
                q.cubicTo(a[0] + a[4], a[1] + a[5], hover.x(), hover.y(), hover.x(), hover.y())
            else:
                q.lineTo(hover)
            p.setPen(QPen(QColor(PEN_COLOR), 1.2 * k, Qt.DashLine))
            p.drawPath(q)
            if len(cur) >= 3 and self._near(QPointF(cur[0][0], cur[0][1]), hover, k):
                p.setPen(QPen(QColor("#ffffff"), 1.5 * k))
                p.drawEllipse(QPointF(cur[0][0], cur[0][1]), 8 * k, 8 * k)
        s = 4 * k
        for pi, sub in enumerate(pen["paths"]):
            for ni, n in enumerate(sub["nodes"]):
                sel = (pi, ni) in pen["sel"]
                for a in (2, 4):
                    if n[a] or n[a + 1]:
                        hp = QPointF(n[0] + n[a], n[1] + n[a + 1])
                        p.setPen(QPen(QColor(PEN_COLOR), 1 * k))
                        p.drawLine(QPointF(n[0], n[1]), hp)
                        p.setBrush(QColor("#ffffff"))
                        p.setPen(QPen(QColor("#111114"), 1 * k))
                        p.drawEllipse(hp, 3 * k, 3 * k)
                p.setPen(QPen(QColor("#111114"), 1 * k))
                p.setBrush(QColor(PEN_COLOR) if sel else QColor("#ffffff"))
                if pen["edit"] is not None and self._is_end(sub, ni) and pen["cur"] is None:
                    p.drawPolygon([QPointF(n[0], n[1] - 1.4 * s), QPointF(n[0] + 1.4 * s, n[1]), QPointF(n[0], n[1] + 1.4 * s),
                                   QPointF(n[0] - 1.4 * s, n[1])])      # (an end of an open path: a diamond, Ctrl+click goes on from it)
                else:
                    p.drawRect(QRectF(n[0] - s, n[1] - s, 2 * s, 2 * s))
        p.setBrush(Qt.NoBrush)
        d = pen["drag"]
        if d is not None and d["kind"] == "marquee" and d["moved"]:
            p.setPen(QPen(QColor("#e6e6e6"), 1 * k, Qt.DashLine))
            p.setBrush(QColor(255, 255, 255, 28))
            p.drawRect(d["rect"])
            p.setBrush(Qt.NoBrush)

    def pen_tip(self):
        """The line of help shown on the preview while the tool is on."""
        pen = self.pen
        if pen["edit"] is None:
            return "鋼筆：點一下放角點，拖曳放平滑點；點第一個點封閉；Enter / 雙擊 / 右鍵結束；Backspace 退一點；Esc 取消"
        if pen["cur"] is not None:
            return "接著畫：點一下加點；點起點封閉、點別條路徑的端點接起來；Enter / 雙擊 / 右鍵結束"
        return ("編輯路徑：點選／框選節點（Shift 加選），拖動、方向鍵移動，Delete 刪除；點線段加點；Alt+點 切換角點 / 平滑；"
                "Ctrl+點端點接著畫；Shift+點空白 新增一段；Enter / Esc 結束")


# -- the toolbar over the preview while the tool is on ----------------------------------------------------------------------------
def _icon(kind):
    """A 28 px picture of a point type (or "open" / "closed"): the path in white, the point a square, its handles round."""
    pm = QPixmap(28, 28)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor("#e8e8ec")
    pt = QPointF(14, 14)
    line = QPainterPath()
    if kind == "corner":
        line.moveTo(3, 22); line.lineTo(14, 8); line.lineTo(25, 22)
        hs = []
    elif kind == "auto":
        line.moveTo(3, 20); line.cubicTo(8, 6, 20, 6, 25, 20)
        hs = [QPointF(8, 8), QPointF(20, 8)]
    elif kind == "aligned":
        line.moveTo(3, 21); line.cubicTo(7, 8, 12, 10, 14, 14); line.cubicTo(17, 18, 21, 8, 25, 18)
        hs = [QPointF(8, 11), QPointF(20, 17)]
    elif kind == "free":
        line.moveTo(3, 21); line.cubicTo(5, 5, 10, 9, 14, 14); line.cubicTo(18, 19, 21, 9, 25, 21)
        hs = [QPointF(6, 7), QPointF(21, 11)]
    elif kind == "vector":
        line.moveTo(3, 22); line.lineTo(14, 8); line.lineTo(25, 22)
        hs = [QPointF(8.5, 15), QPointF(19.5, 15)]
    elif kind == "open":
        line.moveTo(5, 22); line.lineTo(5, 6); line.lineTo(23, 6); line.lineTo(23, 22)
        hs = []
        pt = None
    else:                                           # closed
        line.moveTo(5, 22); line.lineTo(5, 6); line.lineTo(23, 6); line.lineTo(23, 22); line.closeSubpath()
        hs = []
        pt = None
    p.setPen(QPen(c, 1.6))
    p.drawPath(line)
    if pt is not None:
        for h in hs:
            p.setPen(QPen(QColor(PEN_COLOR), 1))
            p.drawLine(pt, h)
            p.setBrush(c)
            p.drawEllipse(h, 2, 2)
        p.setPen(QPen(QColor("#111114"), 1))
        p.setBrush(QColor(PEN_COLOR))
        p.drawRect(QRectF(pt.x() - 3, pt.y() - 3, 6, 6))
    else:
        p.setBrush(c)
        for q in ((5, 22), (23, 22)) if kind == "open" else ((5, 6), (23, 6)):
            p.drawRect(QRectF(q[0] - 2.5, q[1] - 2.5, 5, 5))
    p.end()
    return QIcon(pm)


class PenBar(QWidget):
    """Point types (as Blender's handle types) and 封閉 / 開口 for the selected points: in the bar above the preview (parent: the
    bar) or, without one, floating over the preview's bottom edge."""

    def __init__(self, preview, parent=None):
        super().__init__(parent or preview)
        self.pv = preview
        self.size_px = 28 if parent is not None else 34
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(("PenBar { background: rgba(28, 28, 32, 235); border: 1px solid #4a4a52; border-radius: 4px; }"
                            if parent is None else "PenBar { background: transparent; }") +
                           "QPushButton { background: transparent; border: 1px solid transparent; border-radius: 3px; }"
                           "QPushButton:hover { background: #3a3a42; } QPushButton:disabled { opacity: 0.4; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(5, 4, 5, 4) if parent is None else lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.buttons = {}
        for kind, tip in TYPES:
            self._add(lay, kind, tip, lambda _=False, k=kind: preview.pen_set_type(k))
        lay.addSpacing(8)
        self.toggle = self._add(lay, "open", "", lambda _=False: preview.pen_toggle_closed())
        self.setFocusPolicy(Qt.NoFocus)
        preview.update_penbar = self.refresh

    def _add(self, lay, kind, tip, fn):
        b = QPushButton()
        b.setFixedSize(self.size_px, self.size_px - 2)
        b.setIcon(_icon(kind))
        b.setIconSize(b.size() * 0.85)
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.NoFocus)
        b.clicked.connect(fn)
        lay.addWidget(b)
        self.buttons[kind] = b
        return b

    def refresh(self):
        has, closed = self.pv.pen_state()
        for kind, _tip in TYPES:
            self.buttons[kind].setEnabled(has)
        self.toggle.setIcon(_icon("closed" if closed else "open"))
        self.toggle.setToolTip("路徑目前是封閉的：按一下開口（拿掉最後一段）" if closed else "路徑目前是開口的：按一下封閉（接回起點）")

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()
