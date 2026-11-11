"""The pen tool (鋼筆工具): draw and edit Bézier paths on the preview.

P with the mouse over the preview (or the 鋼筆 button) starts a new path: a click puts a corner point, a click and drag a smooth
one (the drag pulls its out handle, the in handle mirrors it; Alt: only the out one), Shift keeps the next point to a 45° step
from the last, a click on the first point closes the path (a fill), Enter / double click / the right button ends an open one (a
line), Backspace takes the last point back, Esc drops the path. It becomes a "path" built-in asset clip (assets.path_params) at the
playhead, which has the usual fill / outline / colour parameters.

A path clip is edited with a double click on it (or Enter with it selected): drag a point or a handle (a smooth point keeps its
handles in line, Alt breaks that), click on a segment to add a point, Alt+click a point to toggle corner / smooth, Delete takes
the selected point out, Enter / Esc / a click elsewhere ends. Every change is one edit (paramsCommitted, group "multi": the nodes,
the frame they fill and where it sits).

Nodes here are [x, y, in dx, in dy, out dx, out dy] in canvas px (the handles as offsets from their point).
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen, QPolygonF

from .. import assets

PEN_COLOR = "#2dd4ff"
SEG_PICK_PX = 6
CLOSE_PICK_PX = 9


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
    """Whether the handles of node n are in line, opposite ways (and there is something to be in line)."""
    ix, iy, ox, oy = n[2:]
    li, lo = math.hypot(ix, iy), math.hypot(ox, oy)
    return li > 1e-6 and lo > 1e-6 and abs(ix * oy - iy * ox) <= 1e-3 * li * lo and ix * ox + iy * oy < 0


def toggle_smooth(nodes, closed, i):
    """Alt+click on a point: a smooth one becomes a corner (no handles), a corner a smooth one whose handles run along the line
    between its neighbours, a third of the way to each."""
    n = nodes[i]
    if n[2] or n[3] or n[4] or n[5]:
        n[2:] = [0.0, 0.0, 0.0, 0.0]
        return
    cnt = len(nodes)
    prev = nodes[(i - 1) % cnt] if (i > 0 or closed) and cnt > 1 else None
    nxt = nodes[(i + 1) % cnt] if (i < cnt - 1 or closed) and cnt > 1 else None
    a = prev or n
    b = nxt or n
    tx, ty = b[0] - a[0], b[1] - a[1]
    ln = math.hypot(tx, ty)
    if ln < 1e-9:
        return
    tx, ty = tx / ln, ty / ln
    lin = math.hypot(n[0] - prev[0], n[1] - prev[1]) / 3 if prev else 0.0
    lout = math.hypot(nxt[0] - n[0], nxt[1] - n[1]) / 3 if nxt else 0.0
    n[2:] = [-tx * lin, -ty * lin, tx * lout, ty * lout]


def set_handle(n, which, dx, dy, mirror):
    """Handle `which` ("in" / "out") of node n to offset (dx, dy); mirror: the other one turns to stay in line (its length kept)."""
    a, b = (2, 4) if which == "in" else (4, 2)
    n[a], n[a + 1] = dx, dy
    if mirror:
        ln, own = math.hypot(n[b], n[b + 1]), math.hypot(dx, dy)
        if own > 1e-9:
            n[b], n[b + 1] = -dx / own * ln, -dy / own * ln


# -- the tool, as part of the preview ----------------------------------------------------------------------------------------
class PenMixin:
    """The pen tool's state and events; Preview calls these first while self.pen is not None (see its mouse / key handlers).
    self.pen: {"nodes", "closed", "edit" (clip id or None), "box" (its Box), "sel", "drag", "hover"}."""

    def pen_begin(self):
        """Start drawing a new path."""
        if not self.interactive or not self.view or self.pen is not None or self.drag is not None or self.mask_mode:
            return False
        self.pen = {"nodes": [], "closed": False, "edit": None, "box": None, "sel": None, "drag": None, "hover": None}
        self.setCursor(Qt.CrossCursor)
        self.penToggled.emit(True)
        self.update()
        return True

    def pen_can_edit(self):
        box = self.selected_box()
        return (box is not None and self.pen is None and not self.multi() and not getattr(box, "group", False) and not box.locked
                and (box.clip.get("asset") or {}).get("family") == "path" and not self.mask_mode and self.drag is None)

    def pen_edit(self, box=None):
        """Edit the nodes of the selected path clip (box) on the canvas."""
        box = box or self.selected_box()
        if box is None or not self.interactive or self.pen is not None or (box.clip.get("asset") or {}).get("family") != "path":
            return False
        self.pen = {"nodes": [], "closed": False, "edit": box.clip["id"], "box": box, "sel": None, "drag": None, "hover": None}
        self._pen_load(box)
        self.setCursor(Qt.ArrowCursor)
        self.penToggled.emit(True)
        self.update()
        return True

    def pen_end(self):
        self.pen = None
        self.guides = []
        self.unsetCursor()
        self.penToggled.emit(False)
        self.update()

    def _pen_load(self, box):
        """The clip's nodes in canvas px (through its transform) into the tool."""
        q = box.clip["asset"]
        q = assets.at(q, box.t)
        w, h = q["w"], q["h"]
        xf = box.xf()
        nodes = []
        for n in q["nodes"]:
            lx, ly = (n[0] - 0.5) * w, (n[1] - 0.5) * h
            c = xf.map(QPointF(lx, ly))
            i = xf.map(QPointF(lx + n[2] * w, ly + n[3] * h)) - c
            o = xf.map(QPointF(lx + n[4] * w, ly + n[5] * h)) - c
            nodes.append([c.x(), c.y(), i.x(), i.y(), o.x(), o.y()])
        self.pen["nodes"], self.pen["closed"], self.pen["box"] = nodes, bool(q["closed"]), box

    def pen_reload(self):
        """The scene changed (an edit was made): an edited path takes the clip's nodes again, or the tool ends if it went."""
        pen = self.pen
        if pen is None or pen["edit"] is None or pen["drag"] is not None:
            return
        box = next((b for b in self.visible_boxes() if b.clip["id"] == pen["edit"]), None)
        if box is None or box.clip["id"] != self.selected_id:
            self.pen_end()
            return
        self._pen_load(box)

    # -- finishing ------------------------------------------------------------------------------------------------------
    def _pen_finish(self, closed=False):
        pen = self.pen
        nodes = [list(n) for n in pen["nodes"]]
        if pen["edit"] is not None:
            self.pen_end()
            return
        if len(nodes) > 1 and math.hypot(nodes[-1][0] - nodes[-2][0], nodes[-1][1] - nodes[-2][1]) < 1e-6:
            nodes.pop()                                   # (a double click adds its point twice)
        self.pen_end()
        if len(nodes) >= 2:
            self.penFinished.emit(nodes, bool(closed))

    def _pen_commit(self):
        """An edited path as one edit: its nodes in the clip's own frame, the frame they fill and where it sits."""
        pen = self.pen
        box = pen["box"]
        inv, ok = box.xf().inverted()
        if not ok or len(pen["nodes"]) < 2:
            return
        local = []
        for n in pen["nodes"]:
            c = inv.map(QPointF(n[0], n[1]))
            i = inv.map(QPointF(n[0] + n[2], n[1] + n[3])) - c
            o = inv.map(QPointF(n[0] + n[4], n[1] + n[5])) - c
            local.append([c.x(), c.y(), i.x(), i.y(), o.x(), o.y()])
        params, (cx, cy) = assets.path_params(local, pen["closed"])
        centre = box.xf().map(QPointF(cx, cy))
        self.paramsCommitted.emit(box.clip["id"], "multi", {
            "asset": {"nodes": params["nodes"], "closed": params["closed"], "w": params["w"], "h": params["h"]},
            "transform": {"x": box.x_at(centre.x()), "y": box.y_at(centre.y())}})

    # -- snapping -------------------------------------------------------------------------------------------------------
    def _pen_snap(self, pt, mods, skip=None):
        """pt (canvas px) settled on the canvas centre / edges, reference lines, the grid and the other points' lines (Ctrl:
        freely; Shift with a point before it: a 45° step from it)."""
        self.guides = []
        nodes = self.pen["nodes"]
        x, y = pt.x(), pt.y()
        last = next((n for i, n in reversed(list(enumerate(nodes))) if i != skip), None) if self.pen["edit"] is None else None
        if mods & Qt.ShiftModifier and last is not None:
            dx, dy = x - last[0], y - last[1]
            ang = round(math.atan2(dy, dx) / (math.pi / 4)) * math.pi / 4
            r = math.hypot(dx, dy)
            x, y = last[0] + r * math.cos(ang), last[1] + r * math.sin(ang)
            return QPointF(x, y)
        if mods & Qt.ControlModifier:
            return QPointF(x, y)
        tol = 7 * self._k()
        ex, ey = self._extra_targets()
        tx = [self.W / 2, 0, self.W] + ex + [n[0] for i, n in enumerate(nodes) if i != skip]
        ty = [self.H / 2, 0, self.H] + ey + [n[1] for i, n in enumerate(nodes) if i != skip]
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
        """What is under canvas point m: ("handle", node, "in" / "out"), ("node", i), ("seg", n, t) or None."""
        nodes = self.pen["nodes"]
        for i, n in enumerate(nodes):
            for which, a in (("in", 2), ("out", 4)):
                if (n[a] or n[a + 1]) and self._near(QPointF(n[0] + n[a], n[1] + n[a + 1]), m, k):
                    return "handle", i, which
        for i, n in enumerate(nodes):
            if self._near(QPointF(n[0], n[1]), m, k):
                return "node", i
        seg = hit_segment(nodes, self.pen["closed"], (m.x(), m.y()), SEG_PICK_PX * k)
        return ("seg",) + seg if seg else None

    def pen_press(self, e):
        pen = self.pen
        k = self._k()
        m = QPointF(*self._to_canvas(e.position()))
        if e.button() == Qt.RightButton:
            if pen["edit"] is None and pen["nodes"]:
                self._pen_finish(False)
            elif pen["edit"] is not None:
                self.pen_end()
            return
        if e.button() != Qt.LeftButton:
            return
        nodes = pen["nodes"]
        if pen["edit"] is None:                                     # drawing
            if len(nodes) >= 3 and self._near(QPointF(nodes[0][0], nodes[0][1]), m, k * CLOSE_PICK_PX / 9):
                self._pen_finish(True)
                return
            p = self._pen_snap(m, e.modifiers())
            nodes.append([p.x(), p.y(), 0.0, 0.0, 0.0, 0.0])
            pen["drag"] = {"kind": "new", "i": len(nodes) - 1, "m0": m, "moved": False}
            pen["sel"] = len(nodes) - 1
            self.update()
            return
        hit = self._pen_hit(m, k)                                   # editing
        if hit is None:
            self.pen_end()
            self.mousePressEvent(e)                                 # (the click goes on to select / pick what is there)
            return
        if hit[0] == "handle":
            n = nodes[hit[1]]
            pen["sel"] = hit[1]
            pen["drag"] = {"kind": "handle", "i": hit[1], "which": hit[2], "moved": False, "m0": m, "mirror": is_smooth(n)}
        elif hit[0] == "node":
            pen["sel"] = hit[1]
            if e.modifiers() & Qt.AltModifier:
                toggle_smooth(nodes, pen["closed"], hit[1])
                self._pen_commit()
            else:
                n = nodes[hit[1]]
                pen["drag"] = {"kind": "node", "i": hit[1], "m0": m, "moved": False, "p0": (n[0], n[1])}
        else:
            pen["nodes"], at = split(nodes, pen["closed"], hit[1], hit[2])
            pen["sel"] = at
            self._pen_commit()
        self.update()

    def pen_move(self, e):
        pen = self.pen
        m = QPointF(*self._to_canvas(e.position()))
        d = pen["drag"]
        k = self._k()
        if d is None:
            pen["hover"] = self._pen_snap(m, e.modifiers()) if pen["edit"] is None else m
            if pen["edit"] is not None:
                hit = self._pen_hit(m, k)
                self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)
            self.update()
            return
        if not d["moved"] and math.hypot(m.x() - d["m0"].x(), m.y() - d["m0"].y()) < 3 * k:
            return
        d["moved"] = True
        nodes = pen["nodes"]
        n = nodes[d["i"]]
        alt = bool(e.modifiers() & Qt.AltModifier)
        if d["kind"] == "new":                                      # pulling a smooth point's handles out of the click
            dx, dy = m.x() - n[0], m.y() - n[1]
            if e.modifiers() & Qt.ShiftModifier:
                ang = round(math.atan2(dy, dx) / (math.pi / 4)) * math.pi / 4
                r = math.hypot(dx, dy)
                dx, dy = r * math.cos(ang), r * math.sin(ang)
            n[4], n[5] = dx, dy
            n[2], n[3] = (0.0, 0.0) if alt else (-dx, -dy)
        elif d["kind"] == "node":
            p = self._pen_snap(m, e.modifiers(), skip=d["i"])
            n[0], n[1] = p.x() + (d["p0"][0] - d["m0"].x()), p.y() + (d["p0"][1] - d["m0"].y())
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
        if d is not None and pen["edit"] is not None and d["moved"]:
            self._pen_commit()
        self.update()

    def pen_double_click(self, e):
        if self.pen["edit"] is None and self.pen["nodes"]:
            self._pen_finish(False)

    def pen_key(self, e):
        """The action of key e while the pen tool is on (a function), or None."""
        pen = self.pen
        k = e.key()
        if k in (Qt.Key_Return, Qt.Key_Enter):
            return lambda: self._pen_finish(False)
        if k == Qt.Key_Escape:
            return self.pen_end
        if k in (Qt.Key_Backspace, Qt.Key_Delete):
            if pen["edit"] is None:
                def back():
                    if pen["nodes"]:
                        pen["nodes"].pop()
                    self.update()
                return back

            def remove():
                if pen["sel"] is not None and len(pen["nodes"]) > 2:
                    del pen["nodes"][pen["sel"]]
                    pen["sel"] = None
                    self._pen_commit()
                    self.update()
            return remove
        if k == Qt.Key_P and not e.modifiers():
            return self.pen_end if pen["edit"] is None and not pen["nodes"] else None
        return None

    # -- painting -------------------------------------------------------------------------------------------------------
    def paint_pen(self, p, k):
        pen = self.pen
        nodes = pen["nodes"]
        p.setBrush(Qt.NoBrush)
        if nodes:
            path = painter_path(nodes, pen["closed"])
            p.setPen(QPen(QColor("#111114"), 3 * k))
            p.drawPath(path)
            p.setPen(QPen(QColor(PEN_COLOR), 1.5 * k))
            p.drawPath(path)
        hover = pen["hover"]
        if pen["edit"] is None and nodes and hover is not None and pen["drag"] is None:      # the next segment, as it will be
            a = nodes[-1]
            q = QPainterPath(QPointF(a[0], a[1]))
            q.cubicTo(a[0] + a[4], a[1] + a[5], hover.x(), hover.y(), hover.x(), hover.y()) if (a[4] or a[5]) else q.lineTo(hover)
            p.setPen(QPen(QColor(PEN_COLOR), 1.2 * k, Qt.DashLine))
            p.drawPath(q)
            if len(nodes) >= 3 and self._near(QPointF(nodes[0][0], nodes[0][1]), hover, k):
                p.setPen(QPen(QColor("#ffffff"), 1.5 * k))
                p.drawEllipse(QPointF(nodes[0][0], nodes[0][1]), 8 * k, 8 * k)
        s = 4 * k
        for i, n in enumerate(nodes):
            sel = i == pen["sel"]
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
            p.drawRect(QRectF(n[0] - s, n[1] - s, 2 * s, 2 * s))
        p.setBrush(Qt.NoBrush)

    def pen_tip(self):
        """The line of help shown on the preview while the tool is on."""
        if self.pen["edit"] is None:
            return "鋼筆：點一下放角點，拖曳放平滑點；點第一個點封閉；Enter / 雙擊 / 右鍵結束；Backspace 退一點；Esc 取消"
        return "編輯路徑：拖點或把手；點線段加點；Alt+點 切換角點 / 平滑；Delete 刪點；Enter / Esc 結束"
