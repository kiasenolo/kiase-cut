"""The node editor (節點): the graph of a node effect (nodegraph.py) drawn as Blender's compositor draws it -
boxes with sockets, links between them. It only shows and asks: every change is a signal the main window
makes an edit of (and an undo step), and the graph it gets back is drawn again.

Left drag on a socket makes a link (dropped on a socket of another node: linked; a linked input picked up and
dropped on nothing: unlinked), on a node moves it, on the empty part selects with a box. Wheel zooms, the
middle button drags the view (middledrag.py), Shift+A (or the right button) adds a node where the pointer
is, X / Delete removes the selected ones, M mutes them (the picture goes through unchanged), Home shows
everything. Every parameter of a node has its field in the node as in Blender's compositor (drag a number to
change it, click it to type, click a tick, a menu or a colour); a number or colour parameter also has a socket:
link a picture to it and the field gives way to the link. Selecting a picture / video / compound / track node shows it on the preview to place it, as a
mask is (the main window follows nodeSelected).
"""
import glob
import json
import os

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPainterPathStroker, QPen
from PySide6.QtWidgets import (QComboBox, QGraphicsItem, QLineEdit, QGraphicsPathItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel,
                               QMenu, QPushButton, QVBoxLayout, QWidget)

from .. import curves, fx, nodegraph as ng

WIDTH, HEAD, ROW, PAD = 210.0, 24.0, 22.0, 6.0
SOCKET_R = 5.5
HIT_R = 9.0
LABEL_W = 0.42                                  # the part of a row the label takes; the field gets the rest
HEADS = {ng.INPUT: "#a8473f", ng.OUTPUT: "#a8473f", ng.SOURCE: "#3f8a5a", ng.PARAMS: "#8a6f3f"}
CATEGORY_COLORS = ("#3f6fa8", "#7a55a8", "#a8843f", "#3f8f9a", "#a8553f", "#5f8f3f", "#8f3f78")
SOCKET_COLORS = {"image": "#c8c85a", "float": "#a0a0a8", "color": "#d6b04a", "other": "#6a9fd0"}
GHOST = "\0ghost"                              # the empty socket of a 參數輸入 node: drag out of it to make a parameter


def node_refs():
    """Refs of the filters made for graphs (filters/nodes/*.glsl)."""
    return sorted("builtin:nodes/" + os.path.splitext(os.path.basename(p))[0]
                  for p in glob.glob(os.path.join(fx.PKG, "nodes", "*.glsl")))


def head_colour(node):
    if node["type"] in HEADS:
        return QColor(HEADS[node["type"]])
    cat = fx.get(node["ref"]).category or ""
    return QColor(CATEGORY_COLORS[sum(map(ord, cat)) % len(CATEGORY_COLORS)] if cat != "節點" else "#3f6fa8")


def number_text(p, v):
    if p.type == "int":
        return str(int(round(float(v))))
    return f"{float(v):.3f}".rstrip("0").rstrip(".") if abs(float(v)) < 1000 else f"{float(v):.1f}"


class NodeItem(QGraphicsItem):
    """One node: head, an output row, a row for every picture it takes and a row for every parameter with
    its field in it (a number, a tick, a menu, a colour...) - or just its socket's name when a link feeds it.
    Rows: {"y", "kind": out / image / param / panel / shape / shapecolor, "socket", "label", "p"}."""

    def __init__(self, nid, node, editor):
        super().__init__()
        self.nid, self.node, self.editor = nid, node, editor
        self.has_out = ng.has_output(node)
        self.rows = []
        self.linked = {l["socket"] for l in editor.graph["links"] if l["to"] == nid}
        self.drag = None                                    # a field being dragged: {...}
        self._layout()
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setPos(node.get("x", 0.0), node.get("y", 0.0))
        self.setZValue(1)
        self.title = ng.title(node)

    def _layout(self):
        node, rows = self.node, self.rows
        y = HEAD + PAD

        def add(kind, label, socket=None, p=None, panel=None):
            nonlocal y
            rows.append({"y": y, "kind": kind, "socket": socket, "label": label, "p": p, "panel": panel})
            y += ROW
        if node["type"] == ng.PARAMS:
            for x in ng.exposed(self.editor.graph):
                add("expose", x["label"], p=x)
            add("ghost", "（拉出一條線來新增參數）")
        elif self.has_out:
            add("out", "圖像")
        if node["type"] == ng.OUTPUT:
            add("image", "結果", "src")
        elif node["type"] == ng.FILTER:
            d = fx.get(node["ref"])
            add("image", d.src_label, "src")
            for name, label in d.inputs:
                add("image", label, name)
            for p in (q for q in d.params if q.panel is None):
                add("param", p.label, ng.PARAM + p.name if ng.has_socket(p) else None, p)
            for name, closed in d.panels:
                opened = self.editor.panel_open.get((self.nid, name), not closed)
                add("panel", name, panel=opened)
                if opened:
                    for p in (q for q in d.params if q.panel == name):
                        add("param", p.label, ng.PARAM + p.name if ng.has_socket(p) else None, p)
        elif node["type"] == ng.SOURCE and node.get("kind") == "shape":
            add("shape", "形狀")
            add("shapecolor", "顏色")
        self.h = y + PAD

    def row_of(self, socket):
        return next((r for r in self.rows if r["socket"] == socket), None)

    def input_pos(self, socket):
        r = self.row_of(socket)
        return self.mapToScene(QPointF(0, r["y"] + ROW / 2 if r else HEAD))

    def output_pos(self, out=""):
        r = next((r for r in self.rows if r["kind"] == "out"), None) if not out else \
            next((r for r in self.rows if r["kind"] in ("expose", "ghost") and (r["p"]["name"] if r["p"] else GHOST) == out), None)
        return self.mapToScene(QPointF(WIDTH, (r["y"] if r else HEAD + PAD) + ROW / 2))

    def outputs(self):
        """[(output name, scene point)]: one for a picture, one for each parameter (and the empty one) of a 參數輸入."""
        if self.node["type"] == ng.PARAMS:
            return [((r["p"]["name"] if r["p"] else GHOST), self.output_pos(r["p"]["name"] if r["p"] else GHOST))
                    for r in self.rows if r["kind"] in ("expose", "ghost")]
        return [("", self.output_pos())] if self.has_out else []

    def sockets(self):
        """[(socket name, scene point)] of the sockets a link can end at."""
        return [(r["socket"], self.input_pos(r["socket"])) for r in self.rows if r["socket"] and r["kind"] in ("image", "param")]

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and self.scene() is not None:
            for view in self.scene().views():
                view.reroute()
        return super().itemChange(change, value)

    def boundingRect(self):
        return QRectF(-SOCKET_R - 1, -1, WIDTH + SOCKET_R * 2 + 2, self.h + 2)

    # -- fields ---------------------------------------------------------------------------------------
    def field_rect(self, r, cell=0, cells=1):
        x0 = WIDTH * LABEL_W
        w = (WIDTH - 10 - x0) / cells
        return QRectF(x0 + cell * w + (2 if cell else 0), r["y"] + 3, w - (2 if cells > 1 and cell < cells - 1 else 0), ROW - 6)

    def has_field(self, r):
        if r["kind"] == "param":
            return not (r["socket"] and r["socket"] in self.linked) and r["p"].type not in ("curve", "gradient")
        return r["kind"] in ("shape", "shapecolor")

    def field_at(self, pos):
        """(row, cell) of the field under pos (item coordinates), or the panel header row, else None."""
        for r in self.rows:
            if not (r["y"] <= pos.y() < r["y"] + ROW):
                continue
            if r["kind"] == "panel":
                return r, 0
            if not self.has_field(r):
                return None
            n = 3 if r["kind"] == "param" and r["p"].type == "vec3" else 2 if r["kind"] == "param" and r["p"].type == "vec2" else 1
            for i in range(n):
                if self.field_rect(r, i, n).contains(pos):
                    return r, i
        return None

    def paint(self, p, option, widget=None):
        pal = widget.palette() if widget else None
        base = pal.window().color().lighter(125) if pal else QColor("#38383c")
        text = pal.windowText().color() if pal else QColor("white")
        field_bg = base.darker(150)
        p.setRenderHint(QPainter.Antialiasing)
        body = QPainterPath()
        body.addRoundedRect(QRectF(0, 0, WIDTH, self.h), 6, 6)
        p.fillPath(body, base)
        head = QPainterPath()
        head.setFillRule(Qt.WindingFill)
        head.addRoundedRect(QRectF(0, 0, WIDTH, HEAD), 6, 6)
        head.addRect(QRectF(0, HEAD / 2, WIDTH, HEAD / 2))
        muted = bool(self.node.get("mute"))
        col = head_colour(self.node)
        p.fillPath(head.intersected(body), col.darker(160) if muted else col)
        p.setPen(QPen(QColor("#f0a030") if self.isSelected() else QColor(0, 0, 0, 120), 2 if self.isSelected() else 1))
        p.drawPath(body)
        f = QFont(p.font())
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("white") if not muted else QColor(255, 255, 255, 110))
        p.drawText(QRectF(8, 0, WIDTH - 16, HEAD), Qt.AlignVCenter | Qt.AlignLeft,
                   self.title + ("（停用）" if muted else ""))
        f.setBold(False)
        p.setFont(f)
        vals = self.editor.node_values(self.nid)
        for r in self.rows:
            y, kind = r["y"], r["kind"]
            row = QRectF(10, y, WIDTH - 20, ROW)
            p.setPen(text)
            if kind == "out":
                p.drawText(row, Qt.AlignVCenter | Qt.AlignRight, r["label"])
                self._socket(p, QPointF(WIDTH, y + ROW / 2), SOCKET_COLORS["image"])
                continue
            if kind in ("expose", "ghost"):
                ghost = kind == "ghost"
                p.setPen(QColor(text.red(), text.green(), text.blue(), 120 if ghost else 255))
                p.drawText(row, Qt.AlignVCenter | Qt.AlignRight, r["label"])
                at = QPointF(WIDTH, y + ROW / 2)
                if ghost:
                    p.setPen(QPen(QColor("#a0a0a8"), 1, Qt.DashLine))
                    p.setBrush(Qt.NoBrush)
                    p.drawEllipse(at, SOCKET_R, SOCKET_R)
                else:
                    self._socket(p, at, SOCKET_COLORS.get(r["p"]["type"] if r["p"]["type"] in ("float", "color") else "other"))
                continue
            if kind == "panel":
                p.setPen(QColor("#c8c8cc"))
                p.drawText(row, Qt.AlignVCenter | Qt.AlignLeft, ("▾ " if r["panel"] else "▸ ") + r["label"])
                continue
            dim = kind == "param" and not vals.enabled(r["p"])
            p.setPen(QColor(text.red(), text.green(), text.blue(), 110 if dim else 255))
            linked = r["socket"] and r["socket"] in self.linked
            p.drawText(QRectF(10, y, WIDTH * LABEL_W - 6, ROW) if self.has_field(r) else row, Qt.AlignVCenter | Qt.AlignLeft,
                       fm_elide(p, r["label"], WIDTH * LABEL_W - 8 if self.has_field(r) else WIDTH - 20))
            if r["socket"]:
                self._socket(p, QPointF(0, y + ROW / 2), SOCKET_COLORS["image"] if kind == "image" else
                             SOCKET_COLORS.get(r["p"].type if r["p"].type in ("float", "color") else "other"))
            if not self.has_field(r):
                if kind == "param" and r["p"].type in ("curve", "gradient"):
                    p.setPen(QColor(text.red(), text.green(), text.blue(), 110))
                    p.drawText(QRectF(WIDTH * LABEL_W, y, WIDTH * (1 - LABEL_W) - 10, ROW), Qt.AlignVCenter | Qt.AlignRight, "（效果面板）")
                continue
            self._field(p, r, vals, field_bg, text, dim)

    def _field(self, p, r, vals, bg, text, dim):
        kind = r["kind"]
        if kind == "shape":
            box = self.field_rect(r)
            self._box(p, box, bg)
            p.setPen(text)
            p.drawText(box.adjusted(6, 0, -14, 0), Qt.AlignVCenter | Qt.AlignLeft,
                       dict(ng.SHAPES).get(vals.shape, vals.shape))
            p.drawText(box.adjusted(0, 0, -4, 0), Qt.AlignVCenter | Qt.AlignRight, "▾")
            return
        if kind == "shapecolor":
            box = self.field_rect(r)
            self._box(p, box, QColor.fromRgbF(*(list(vals.color) + [1.0] * 4)[:3]))
            return
        q = r["p"]
        v = vals.get(q.name)
        if q.type in ("float", "int"):
            box = self.field_rect(r)
            self._box(p, box, bg)
            p.setPen(text if not dim else QColor(text.red(), text.green(), text.blue(), 110))
            p.drawText(box, Qt.AlignCenter, number_text(q, v))
        elif q.type in ("vec2", "vec3"):
            n = 3 if q.type == "vec3" else 2
            for i in range(n):
                box = self.field_rect(r, i, n)
                self._box(p, box, bg)
                p.setPen(text)
                p.drawText(box, Qt.AlignCenter, number_text(q, (list(v) + [0.0] * 3)[i]))
        elif q.type == "bool":
            box = QRectF(WIDTH - 10 - ROW + 4, r["y"] + 4, ROW - 8, ROW - 8)
            self._box(p, box, bg)
            if v:
                p.setPen(QPen(QColor("#f0a030"), 2))
                p.drawLine(box.topLeft() + QPointF(2, box.height() / 2), box.center() + QPointF(-1, 3))
                p.drawLine(box.center() + QPointF(-1, 3), box.topRight() + QPointF(-2, 2))
        elif q.type == "menu":
            box = self.field_rect(r)
            self._box(p, box, bg)
            p.setPen(text)
            p.drawText(box.adjusted(6, 0, -14, 0), Qt.AlignVCenter | Qt.AlignLeft, q.items[fx.menu_index(q, v)] if q.items else "")
            p.drawText(box.adjusted(0, 0, -4, 0), Qt.AlignVCenter | Qt.AlignRight, "▾")
        elif q.type == "color":
            box = self.field_rect(r)
            c = (list(v) + [1.0] * 4)[:4]
            self._box(p, box, QColor.fromRgbF(max(0, min(1, c[0])), max(0, min(1, c[1])), max(0, min(1, c[2])), 1.0))

    @staticmethod
    def _box(p, box, colour):
        p.setPen(QPen(QColor(0, 0, 0, 90), 1))
        p.setBrush(colour)
        p.drawRoundedRect(box, 3, 3)

    @staticmethod
    def _socket(p, at, colour):
        p.setPen(QPen(QColor(0, 0, 0, 160), 1))
        p.setBrush(QColor(colour))
        p.drawEllipse(at, SOCKET_R, SOCKET_R)

    # -- mouse: a field takes the press (the rest of the node moves it) ------------------------------------
    def mousePressEvent(self, e):
        hit = self.field_at(e.pos()) if e.button() == Qt.LeftButton else None
        if hit is None:
            super().mousePressEvent(e)
            return
        if not self.isSelected():
            self.scene().clearSelection()
            self.setSelected(True)
        r, cell = hit
        self.drag = {"row": r, "cell": cell, "x0": e.pos().x(), "moved": False,
                     "v0": self.editor.field_number(self.nid, r, cell)}
        e.accept()

    def mouseMoveEvent(self, e):
        d = self.drag
        if d is None:
            super().mouseMoveEvent(e)
            return
        r = d["row"]
        q = r["p"] if r["kind"] == "param" else None
        if q is None or q.type not in ("float", "int", "vec2", "vec3") or d["v0"] is None:
            return
        dx = e.pos().x() - d["x0"]
        if not d["moved"] and abs(dx) < 3:
            return
        d["moved"] = True
        from .effects_panel import step_for
        step = step_for(q) / 2 * (0.1 if e.modifiers() & Qt.ShiftModifier else 1.0)
        self.editor.set_number(self.nid, r, d["cell"], d["v0"] + dx * step)

    def mouseReleaseEvent(self, e):
        d, self.drag = self.drag, None
        if d is None:
            super().mouseReleaseEvent(e)
            return
        if d["moved"]:
            return
        self.editor.field_clicked(self, d["row"], d["cell"], e.screenPos())

    def mouseDoubleClickEvent(self, e):
        if self.field_at(e.pos()) is None:
            super().mouseDoubleClickEvent(e)


def fm_elide(p, text, width):
    return p.fontMetrics().elidedText(text, Qt.ElideRight, int(width))


class Link(QGraphicsPathItem):
    def __init__(self):
        super().__init__()
        self.setZValue(0)
        self.setPen(QPen(QColor("#d0d0d8"), 2))

    def route(self, a, b):
        path = QPainterPath(a)
        dx = max(40.0, abs(b.x() - a.x()) * 0.5)
        path.cubicTo(a + QPointF(dx, 0), b - QPointF(dx, 0), b)
        self.setPath(path)


class GraphView(QGraphicsView):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setFocusPolicy(Qt.StrongFocus)
        self.items_by_id = {}
        self.link_items = []                     # [(Link, from node, to node, socket, output name)]
        self.rubber = None                       # a link being dragged: (Link, source node, old (dst, socket) or None, output name)
        self.cut = None                          # a Ctrl + right button cut: (the line, its points)
        self.over = None                         # the link a dragged node is over (it will go through the node)
        self.press_at = {}

    # -- finding sockets -----------------------------------------------------------------------------
    def socket_at(self, pos):
        """("out", node id, output name) / ("in", node id, socket) near scene point pos, else None."""
        for nid, it in self.items_by_id.items():
            for out, at in it.outputs():
                if (at - pos).manhattanLength() <= HIT_R * 1.5:
                    return "out", nid, out
            for sock, at in it.sockets():
                if (at - pos).manhattanLength() <= HIT_R * 1.5:
                    return "in", nid, sock
        return None

    # -- mouse ---------------------------------------------------------------------------------------
    def mousePressEvent(self, e):
        pos = self.mapToScene(e.position().toPoint())
        if e.button() == Qt.LeftButton:
            hit = self.socket_at(pos)
            if hit:
                kind, nid, sock = hit
                old, out = None, sock if kind == "out" else ""
                if kind == "in":
                    link = next((l for l in self.editor.graph["links"] if l["to"] == nid and l["socket"] == sock), None)
                    if link is not None:                # a linked input is picked up: the link comes with the pointer
                        old, nid, out, kind = (nid, sock), link["from"], link.get("out") or "", "out"
                if kind == "out":
                    ln = Link()
                    self.scene().addItem(ln)
                    self.rubber = (ln, nid, old, out)
                    self._route_temp(pos)
                    return
            self.press_at = {i: (it.pos().x(), it.pos().y()) for i, it in self.items_by_id.items()}
        elif e.button() == Qt.RightButton:
            if e.modifiers() & Qt.ControlModifier:      # Ctrl + right button: drag across links to cut them
                line = QGraphicsPathItem()
                line.setPen(QPen(QColor("#e0605a"), 2, Qt.DashLine))
                line.setZValue(20)
                self.scene().addItem(line)
                self.cut = (line, [pos])
                return
            hit = self.socket_at(pos)
            if hit and hit[0] == "out" and hit[2] not in ("", GHOST):
                self.editor.parameter_menu(hit[1], hit[2], e.globalPosition().toPoint())
                return
            self.editor.add_menu(pos, e.globalPosition().toPoint())
            return
        super().mousePressEvent(e)

    def reroute(self):
        """Draw the links again (a node moved)."""
        for ln, a, b, sock, out in self.link_items:
            ln.route(self.items_by_id[a].output_pos(out), self.items_by_id[b].input_pos(sock))

    def _route_temp(self, pos):
        ln, src, _old, out = self.rubber
        ln.route(self.items_by_id[src].output_pos(out), pos)

    def mouseMoveEvent(self, e):
        pos = self.mapToScene(e.position().toPoint())
        if self.rubber:
            self._route_temp(pos)
            return
        if self.cut:
            self.cut[1].append(pos)
            path = QPainterPath(self.cut[1][0])
            for q in self.cut[1][1:]:
                path.lineTo(q)
            self.cut[0].setPath(path)
            return
        super().mouseMoveEvent(e)
        if e.buttons() & Qt.LeftButton:
            self._hover_link()

    def _lone_node(self):
        """The one node being dragged if it has no links yet and could go in the middle of one: (id, item)."""
        sel = [(i, it) for i, it in self.items_by_id.items() if it.isSelected()]
        if len(sel) != 1:
            return None
        nid, it = sel[0]
        if any(nid in (l["from"], l["to"]) for l in self.editor.graph["links"]) or not it.has_out:
            return None
        if not [s for s, _ in ng.sockets(it.node) if not s.startswith(ng.PARAM)] or it.node["type"] == ng.PARAMS:
            return None
        if self.press_at.get(nid) in (None, (it.pos().x(), it.pos().y())):
            return None
        return nid, it

    def _hover_link(self):
        """Light the link under the node being dragged (dropped there, the link goes through the node)."""
        lone = self._lone_node()
        over = None
        if lone:
            box = lone[1].sceneBoundingRect().adjusted(8, 8, -8, -8)
            for ln, a, b, sock, out in self.link_items:
                if ln.path().intersects(box):
                    over = (ln, a, b, sock, out)
                    break
        if over != self.over:
            for ln, *_ in self.link_items:
                ln.setPen(QPen(QColor("#d0d0d8"), 2))
            if over:
                over[0].setPen(QPen(QColor("#ffffff"), 4))
            self.over = over

    def mouseReleaseEvent(self, e):
        pos = self.mapToScene(e.position().toPoint())
        if self.rubber:
            ln, src, old, out = self.rubber
            self.rubber = None
            self.scene().removeItem(ln)
            hit = self.socket_at(pos)
            ed = self.editor
            if hit and hit[0] == "in" and hit[1] != src:
                if out == GHOST:
                    ed.exposeRequested.emit(ed.eid, src, hit[1], hit[2])
                elif old != (hit[1], hit[2]):
                    ed.connectRequested.emit(ed.eid, src, hit[1], hit[2], out)
            elif hit is None and old:
                ed.disconnectRequested.emit(ed.eid, old[0], old[1])
            elif hit is None and out == "":                      # a link let go in the empty: add a node there to take it
                ed.add_menu(pos, e.globalPosition().toPoint(), (src, out))
            return
        if self.cut:
            line, pts = self.cut
            self.cut = None
            self.scene().removeItem(line)
            path = QPainterPath(pts[0])
            for q in pts[1:]:
                path.lineTo(q)
            stroke = QPainterPathStroker()
            stroke.setWidth(3)
            hit = stroke.createStroke(path)
            cut = [(b, sock) for ln, a, b, sock, out in self.link_items if ln.path().intersects(hit)]
            if cut:
                self.editor.disconnectManyRequested.emit(self.editor.eid, cut)
            return
        over, self.over = self.over, None
        lone = self._lone_node() if over else None
        super().mouseReleaseEvent(e)
        moved = {i: (it.pos().x(), it.pos().y()) for i, it in self.items_by_id.items()
                 if self.press_at.get(i) not in (None, (it.pos().x(), it.pos().y()))}
        self.press_at = {}
        for ln, *_ in self.link_items:
            ln.setPen(QPen(QColor("#d0d0d8"), 2))
        if over and lone and list(moved) == [lone[0]]:
            _ln, a, b, sock, out = over
            x, y = moved[lone[0]]
            self.editor.insertRequested.emit(self.editor.eid, lone[0], x, y, a, b, sock, out)
        elif moved:
            self.editor.moveRequested.emit(self.editor.eid, moved)
        self.editor.selection_changed()

    def wheelEvent(self, e):
        k = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        s = self.transform().m11() * k
        if 0.2 <= s <= 3.0:
            self.scale(k, k)

    def event(self, e):
        # the keys this editor uses are its own while it has the focus: the window's clip shortcuts (Ctrl+X cut,
        # Delete, M, Home...) would take them first otherwise
        if e.type() == QEvent.ShortcutOverride and self.claims(e.key(), e.modifiers()):
            e.accept()
            return True
        return super().event(e)

    @staticmethod
    def claims(key, mods):
        mods &= ~Qt.KeypadModifier
        if key in (Qt.Key_Delete, Qt.Key_Backspace, Qt.Key_Home, Qt.Key_M, Qt.Key_X):
            return mods in (Qt.NoModifier, Qt.ControlModifier) if key == Qt.Key_X else mods == Qt.NoModifier
        if key in (Qt.Key_A, Qt.Key_D):
            return mods == Qt.ShiftModifier or (key == Qt.Key_A and mods == Qt.NoModifier)
        return False

    def keyPressEvent(self, e):
        key, mods = e.key(), e.modifiers()
        if key == Qt.Key_A and mods == Qt.NoModifier:
            for it in self.items_by_id.values():
                it.setSelected(True)
            self.editor.selection_changed()
        elif key == Qt.Key_X and mods & Qt.ControlModifier:
            self.editor.dissolve_selected()
        elif key in (Qt.Key_X, Qt.Key_Delete):
            self.editor.remove_selected()
        elif key == Qt.Key_M:
            self.editor.mute_selected()
        elif key == Qt.Key_D and mods & Qt.ShiftModifier:
            self.editor.duplicate_selected()
        elif key == Qt.Key_Home:
            self.fit()
        elif key == Qt.Key_A and mods & Qt.ShiftModifier:
            pos = self.mapFromGlobal(self.cursor().pos())
            self.editor.add_menu(self.mapToScene(pos), self.cursor().pos())
        else:
            super().keyPressEvent(e)

    def fit(self):
        r = self.scene().itemsBoundingRect()
        if not r.isEmpty():
            self.fitInView(r.adjusted(-40, -40, 40, 40), Qt.KeepAspectRatio)
            if self.transform().m11() > 1.2:
                self.resetTransform()
                self.centerOn(r.center())


class NodeEditor(QWidget):
    addRequested = Signal(str, dict, float, float)          # effect id, node ({"type", "ref" / "kind"}), x, y
    removeRequested = Signal(str, list)                     # effect id, node ids
    connectRequested = Signal(str, str, str, str, str)      # effect id, from node, to node, socket, the output (a parameter's name; "": picture)
    exposeRequested = Signal(str, str, str, str)            # effect id, 參數輸入 node, to node, socket: make a parameter of it
    disconnectManyRequested = Signal(str, list)             # effect id, [(to node, socket)]: links cut with Ctrl + right drag
    insertRequested = Signal(str, str, float, float, str, str, str, str)   # effect id, node, x, y, then the link it was dropped on
    addLinkedRequested = Signal(str, dict, float, float, str, str)         # effect id, node, x, y, node and output to link into it
    duplicateRequested = Signal(str, list)                  # effect id, node ids
    dissolveRequested = Signal(str, list)                   # effect id, node ids: delete but keep the picture going through
    removeExposedRequested = Signal(str, str)               # effect id, parameter name
    disconnectRequested = Signal(str, str, str)             # effect id, to node, socket
    moveRequested = Signal(str, dict)                       # effect id, {node id: (x, y)}
    muteRequested = Signal(str, list, bool)                 # effect id, node ids, on
    nodeSelected = Signal(str, str)                         # effect id, the one node selected ("" none)
    effectChosen = Signal(str)                              # effect id: another node effect of the clip
    saveRequested = Signal(str)                             # effect id: keep it as a 效果預設 (a custom effect)
    paramEdited = Signal(str, str, object)                  # effect id, "<node>.<parameter>", value
    shapeEdited = Signal(str, str, object, object)          # effect id, shape node, shape id or None, colour or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.eid = None
        self.graph = {"nodes": {}, "links": []}
        self.effects = []                                   # [(effect id, name)]
        self.user_filters = []
        self._sig = None
        self._selected = ""
        self.params, self.sources, self.t = {}, {}, 0         # what the fields show: the effect's, at clip time t
        self.panel_open = {}                                  # (node id, panel name) -> opened or shut by the user
        self.edit_proxy = None                                # the text box of a number being typed
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        bar = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.activated.connect(lambda i: self.effectChosen.emit(self.combo.itemData(i)))
        bar.addWidget(self.combo)
        add = QPushButton("新增節點 (Shift+A)")
        add.clicked.connect(lambda: self.add_menu(self.view.mapToScene(self.view.viewport().rect().center()),
                                                  add.mapToGlobal(add.rect().bottomLeft())))
        bar.addWidget(add)
        fit = QPushButton("全部顯示 (Home)")
        fit.clicked.connect(lambda: self.view.fit())
        bar.addWidget(fit)
        save = QPushButton("存成自定效果")
        save.setToolTip("把這個節點效果（節點、設定、圖片）存進 Library 的「效果預設」，之後可以套用到別的片段")
        save.clicked.connect(lambda: self.eid and self.saveRequested.emit(self.eid))
        bar.addWidget(save)
        bar.addStretch()
        lay.addLayout(bar)
        self.note = QLabel("選取有節點效果的片段（效果面板 → 新增效果 → 節點效果）")
        self.note.setAlignment(Qt.AlignCenter)
        self.view = GraphView(self)
        lay.addWidget(self.note)
        lay.addWidget(self.view, 1)
        self.view.hide()
        self.setFocusProxy(self.view)

    # -- what it shows ---------------------------------------------------------------------------------
    def set_user_filters(self, filters):
        self.user_filters = list(filters)

    def show_clip(self, clip, want=None, t=0):
        """Show a node effect of clip (None: nothing): want, else the one shown before, else the first; its
        fields at clip time t."""
        es = [e for e in (clip or {}).get("effects") or [] if e.get("filter") == fx.GRAPH]
        names = [(e["id"], f"節點效果 {i + 1}") for i, e in enumerate(es)]
        if names != self.effects:
            self.effects = names
            self.combo.blockSignals(True)
            self.combo.clear()
            for eid, name in names:
                self.combo.addItem(name, eid)
            self.combo.blockSignals(False)
        e = next((x for x in es if x["id"] == (want or self.eid)), es[0] if es else None)
        if e is None:
            self.eid, self._sig = None, None
            self.note.show()
            self.view.hide()
            self.view.scene().clear()
            self.view.items_by_id, self.view.link_items = {}, []
            return
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(max(0, self.combo.findData(e["id"])))
        self.combo.blockSignals(False)
        self.note.hide()
        self.view.show()
        first = self.eid != e["id"]
        self.eid = e["id"]
        self.params, self.sources, self.t = e["params"], e.get("sources") or {}, t
        sig = json.dumps(e["graph"], sort_keys=True)
        if sig != self._sig:
            self._sig = sig
            self.graph = e["graph"]
            self.rebuild(first)
        else:
            self.view.viewport().update()                   # (the values only)

    def rebuild(self, fit=False):
        v = self.view
        keep = {i for i, it in v.items_by_id.items() if it.isSelected()}
        sc = v.scene()
        sc.clear()
        self.edit_proxy = None
        v.items_by_id, v.link_items = {}, []
        for nid, node in self.graph["nodes"].items():
            it = NodeItem(nid, node, self)
            sc.addItem(it)
            v.items_by_id[nid] = it
            it.setSelected(nid in keep)
        for l in self.graph["links"]:
            a, b = v.items_by_id.get(l["from"]), v.items_by_id.get(l["to"])
            out = l.get("out") or ""
            if a is None or b is None or b.row_of(l["socket"]) is None or out not in [o for o, _ in a.outputs()]:
                continue
            ln = Link()
            ln.route(a.output_pos(out), b.input_pos(l["socket"]))
            sc.addItem(ln)
            v.link_items.append((ln, l["from"], l["to"], l["socket"], out))
        r = sc.itemsBoundingRect()
        sc.setSceneRect(r.adjusted(-1500, -1500, 1500, 1500))
        if fit:
            v.fit()

    # -- the fields of the nodes -------------------------------------------------------------------------
    class Values:
        """What a node's fields show now."""

        def __init__(self, vals, d, shape, color):
            self.vals, self.d, self.shape, self.color = vals, d, shape, color
            self.named = fx.named(d, vals) if d is not None else {}

        def get(self, name):
            return self.vals.get(name)

        def enabled(self, p):
            return fx.enabled(p, self.named)

    def node_values(self, nid):
        node = self.graph["nodes"].get(nid) or {}
        src = self.sources.get(nid) or {}
        if node.get("type") != ng.FILTER:
            return self.Values({}, None, src.get("shape", "rectangle"), src.get("color") or [1.0, 1.0, 1.0, 1.0])
        d = fx.get(node["ref"])
        vals = {p.name: curves.value(self.params.get(ng.param_key(nid, p.name), p.default), self.t) for p in d.params}
        return self.Values(vals, d, "", [1.0, 1.0, 1.0, 1.0])

    def field_number(self, nid, row, cell):
        """The number a field holds (None: it holds none)."""
        if row["kind"] != "param":
            return None
        q, v = row["p"], self.node_values(nid).get(row["p"].name)
        if q.type in ("float", "int"):
            return float(v)
        if q.type in ("vec2", "vec3"):
            return float((list(v) + [0.0] * 3)[cell])
        return None

    def set_number(self, nid, row, cell, value):
        """A number field scrubbed or typed: clamped, asked for, and shown at once."""
        q = row["p"]
        value = min(max(value, q.lo), q.hi)
        key = ng.param_key(nid, q.name)
        if q.type == "int":
            new = int(round(value))
        elif q.type == "float":
            new = round(value, 4)
        else:
            cur = list(self.node_values(nid).get(q.name))
            cur[cell] = round(value, 4)
            new = cur
        self.params[key] = new if not curves.is_animated(self.params.get(key)) else self.params[key]
        self.paramEdited.emit(self.eid, key, new)
        self.view.viewport().update()

    def field_clicked(self, item, row, cell, global_pos):
        """A field pressed and let go without dragging: a tick turns over, a menu / colour / text box opens."""
        nid, kind = item.nid, row["kind"]
        gp = global_pos.toPoint() if hasattr(global_pos, "toPoint") else global_pos
        if kind == "panel":
            key = (nid, row["label"])
            self.panel_open[key] = not row["panel"]
            QTimer.singleShot(0, self.rebuild)
            return
        if kind == "shape":
            menu = QMenu(self)
            for sid, name in ng.SHAPES:
                menu.addAction(name, lambda sid=sid: self.shapeEdited.emit(self.eid, nid, sid, None))
            self.popup(menu, gp)
            return
        if kind == "shapecolor":
            self._pick(nid, self.node_values(nid).color, lambda c: self.shapeEdited.emit(self.eid, nid, None, c), item, row)
            return
        q = row["p"]
        key = ng.param_key(nid, q.name)
        v = self.node_values(nid).get(q.name)
        if q.type == "bool":
            self.paramEdited.emit(self.eid, key, not bool(v))
        elif q.type == "menu":
            menu = QMenu(self)
            for name in q.items:
                menu.addAction(name, lambda name=name: self.paramEdited.emit(self.eid, key, name))
            self.popup(menu, gp)
        elif q.type == "color":
            self._pick(nid, v, lambda c: self.paramEdited.emit(self.eid, key, c), item, row)
        elif q.type in ("float", "int", "vec2", "vec3"):
            self._type_number(item, row, cell)

    def _pick(self, nid, colour, done, item, row):
        from .colorpick import pick_color, qcolor, rgba
        c = list(colour) + [1.0] * 4
        start = qcolor("#%02x%02x%02x" % tuple(int(round(max(0, min(1, x)) * 255)) for x in c[:3]))
        start.setAlphaF(max(0.0, min(1.0, c[3])))
        col = pick_color(self, start, "顏色")
        if col is not None:
            done(rgba(col))

    def _type_number(self, item, row, cell):
        """A text box over the number's field: Enter keeps what was typed, Esc or leaving it does not."""
        q = row["p"]
        n = 3 if q.type == "vec3" else 2 if q.type == "vec2" else 1
        box = item.field_rect(row, cell, n)
        le = QLineEdit(number_text(q, self.field_number(item.nid, row, cell)))
        proxy = self.view.scene().addWidget(le)
        proxy.setZValue(10)
        proxy.setPos(item.mapToScene(box.topLeft()))
        proxy.resize(box.width(), box.height())
        le.selectAll()
        le.setFocus()
        self.edit_proxy = proxy

        def finish(keep):
            if self.edit_proxy is not proxy:
                return
            self.edit_proxy = None
            text = le.text()
            QTimer.singleShot(0, lambda: (proxy.scene() and proxy.scene().removeItem(proxy)))
            if keep:
                try:
                    self.set_number(item.nid, row, cell, float(text))
                except ValueError:
                    pass
        le.returnPressed.connect(lambda: finish(True))
        le.editingFinished.connect(lambda: finish(False))

    # -- asking for edits ------------------------------------------------------------------------------
    def selected(self):
        return [i for i, it in self.view.items_by_id.items() if it.isSelected()]

    def selection_changed(self):
        sel = self.selected()
        one = sel[0] if len(sel) == 1 else ""
        if one != self._selected:
            self._selected = one
            self.nodeSelected.emit(self.eid or "", one)

    def select(self, nid):
        for i, it in self.view.items_by_id.items():
            it.setSelected(i == nid)
        self.selection_changed()

    def remove_selected(self):
        ids = [i for i in self.selected() if self.graph["nodes"][i]["type"] != ng.OUTPUT]
        if ids and self.eid:
            self.removeRequested.emit(self.eid, ids)

    def mute_selected(self):
        ids = [i for i in self.selected() if self.graph["nodes"][i]["type"] == ng.FILTER]
        if ids and self.eid:
            self.muteRequested.emit(self.eid, ids, not all(self.graph["nodes"][i].get("mute") for i in ids))

    def popup(self, menu, pos):
        menu.exec(pos)

    def duplicate_selected(self):
        ids = [i for i in self.selected() if self.graph["nodes"][i]["type"] != ng.OUTPUT]
        if ids and self.eid:
            self.duplicateRequested.emit(self.eid, ids)

    def dissolve_selected(self):
        ids = [i for i in self.selected() if self.graph["nodes"][i]["type"] != ng.OUTPUT]
        if ids and self.eid:
            self.dissolveRequested.emit(self.eid, ids)

    def parameter_menu(self, nid, name, global_pos):
        menu = QMenu(self)
        menu.addAction("刪除這個參數", lambda: self.removeExposedRequested.emit(self.eid, name))
        self.popup(menu, global_pos)

    def add_menu(self, scene_pos, global_pos, link=None):
        """The menu of nodes to add at scene_pos; link (node id, output): a link let go in the empty - the new
        node takes it."""
        if not self.eid:
            return

        def ask(node):
            if link:
                self.addLinkedRequested.emit(self.eid, node, scene_pos.x(), scene_pos.y(), link[0], link[1])
            else:
                self.addRequested.emit(self.eid, node, scene_pos.x(), scene_pos.y())
        menu = QMenu(self)
        inp = menu.addMenu("輸入")
        for text, node in (("輸入（片段的畫面）", {"type": ng.INPUT}), ("參數輸入（效果自己的參數）", {"type": ng.PARAMS}), ("圖片", {"type": ng.SOURCE, "kind": "image"}),
                           ("影片", {"type": ng.SOURCE, "kind": "video"}), ("複合片段", {"type": ng.SOURCE, "kind": "compound"}),
                           ("時間線（軌道）", {"type": ng.SOURCE, "kind": "track"})):
            inp.addAction(text, lambda _=False, n=node: ask(n))
        shapes = menu.addMenu("形狀")
        for sid, name in ng.SHAPES:
            shapes.addAction(name, lambda _=False, sid=sid: ask({"type": ng.SOURCE, "kind": "shape", "shape": sid}))
        cats = {}
        for ref in node_refs() + fx.builtin_refs():
            d = fx.get(ref)
            cats.setdefault("節點" if ref.startswith("builtin:nodes/") else d.category or "其他", []).append((d.name, ref))
        for cat in sorted(cats, key=lambda c: (c != "節點", c)):
            sub = menu.addMenu(cat)
            for name, ref in cats[cat]:
                sub.addAction(name, lambda _=False, r=ref: ask({"type": ng.FILTER, "ref": r}))
        if self.user_filters:
            mine = menu.addMenu("我的濾鏡（Library）")
            for name, path in self.user_filters:
                mine.addAction(name, lambda _=False, r=path: ask({"type": ng.FILTER, "ref": r}))
        self.popup(menu, global_pos)
