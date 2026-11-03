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
                               QMenu, QPushButton, QVBoxLayout, QWidget, QWidgetAction)

from .. import assets, curves, fx, nodegraph as ng

WIDTH, HEAD, ROW, PAD = 210.0, 24.0, 22.0, 6.0
SOCKET_R = 5.5
HIT_R = 9.0
THUMB_H = 54.0                                 # the height of a node's thumbnail (縮圖)
PLOT_H = {"curve": 64.0, "gradient": 30.0}           # the height of a curve / gradient parameter's picture in a node
LABEL_W = 0.42                                  # the part of a row the label takes; the field gets the rest
HEADS = {ng.INPUT: "#a8473f", ng.OUTPUT: "#a8473f", ng.SOURCE: "#3f8a5a", ng.PARAMS: "#8a6f3f", ng.GROUP: "#3f7f78",
         "groupin": "#7a5f3f", "groupout": "#7a5f3f"}
GHOST_IN = "\0newsocket"                       # the empty input of a 群組輸出: drag a link into it to make a group output
PORT_IN, PORT_OUT = "\0gin", "\0gout"            # the ids of the 群組輸入 / 群組輸出 boxes drawn inside a group
CATEGORY_COLORS = ("#3f6fa8", "#7a55a8", "#a8843f", "#3f8f9a", "#a8553f", "#5f8f3f", "#8f3f78")
SOCKET_COLORS = {"image": "#c8c85a", "float": "#a0a0a8", "color": "#d6b04a", "other": "#6a9fd0"}
GHOST = "\0ghost"                              # the empty socket of a 參數輸入 node: drag out of it to make a parameter


def node_refs():
    """Refs of the filters made for graphs (filters/nodes/*.glsl)."""
    refs = sorted("builtin:nodes/" + os.path.splitext(os.path.basename(p))[0]
                  for p in glob.glob(os.path.join(fx.PKG, "nodes", "*.glsl")))
    return [r for r in refs if r != ng.PICTURE]                  # (the picture node is what source nodes are drawn with)


NODE_HEADS = {"輸入": "#a8473f", "色彩": "#8a8a3f", "向量": "#5a5aa8", "轉換器": "#3f6fa8", "變換": "#3f8f9a"}   # the tool nodes, as Blender colours them


def is_tool(ref):
    return ref.startswith("builtin:nodes/")


def head_colour(node):
    if node["type"] in HEADS:
        return QColor(HEADS[node["type"]])
    cat = fx.get(node["ref"]).category or ""
    if is_tool(node["ref"]):
        return QColor(NODE_HEADS.get(cat, "#3f6fa8"))
    return QColor(CATEGORY_COLORS[sum(map(ord, cat)) % len(CATEGORY_COLORS)])


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
        self.has_out = node["type"] != "groupout" and ng.has_output(node)
        self.rows = []
        self.linked = {l["socket"] for l in editor.graph["links"] if l["to"] == nid}
        self.drag = None                                    # a field being dragged: {...}
        self._layout()
        if node["type"] in ("groupin", "groupout"):          # (drawn from the group, not nodes of the graph)
            self.setFlags(QGraphicsItem.ItemSendsGeometryChanges)
        else:
            self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setPos(node.get("x", 0.0), node.get("y", 0.0))
        self.setZValue(1)
        self.title = ng.title(node)

    def _layout(self):
        node, rows = self.node, self.rows
        y = HEAD + PAD

        def add(kind, label, socket=None, p=None, panel=None, h=ROW):
            nonlocal y
            rows.append({"y": y, "kind": kind, "socket": socket, "label": label, "p": p, "panel": panel, "h": h})
            y += h
            if kind == "param" and p is not None and p.type in ("curve", "gradient"):     # (its picture, under the label)
                rows.append({"y": y, "kind": "plot", "socket": None, "label": "", "p": p, "panel": None, "h": PLOT_H[p.type]})
                y += PLOT_H[p.type]
        if node["type"] == ng.PARAMS:
            for x in ng.exposed(self.editor.graph):
                add("expose", x["label"], p=x)
            add("ghost", "（拉出一條線來新增參數）")
        elif node["type"] == "groupin":
            for i in node["items"]:
                add("out", i["label"], p=i["name"])
            add("ghost", "（拉出一條線來新增輸入）")
        elif node["type"] == "groupout":
            for i in node["items"]:
                add("image", i["label"], i["name"])
            add("image", "（拉一條線進來新增輸出）", GHOST_IN)
        elif node["type"] == ng.GROUP:
            for name, label in ng.sockets(node):
                add("image", label, name)
            for name, label in ng.outputs(node):
                add("out", label, p=name)
        elif self.has_out:
            for name, label in ng.outputs(node):
                add("out", label, p=name)
        if node["type"] == ng.OUTPUT:
            add("image", "結果", "src")
        elif node["type"] == ng.FILTER or ng.is_asset(node):         # (a built-in shape: its fields, no sockets)
            d = ng.node_def(node)
            socket = lambda p: ng.PARAM + p.name if ng.has_socket(p) else None
            if node["type"] == ng.FILTER:
                add("image", d.src_label, "src")
                for name, label in d.inputs:
                    add("image", label, name)
            else:                                                      # (pictures to paint its fill and its outline with, then where it sits)
                for _part, sock, label in ng.ASSET_PAINTS:
                    add("image", label, sock)
                opened = self.editor.panel_open.get((self.nid, "位置"), True)
                add("panel", "位置", panel=opened)
                if opened:
                    for p in ng.place_params():
                        add("param", p.label, socket(p), p)
            for p in (q for q in d.params if q.panel is None):
                add("param", p.label, socket(p), p)
            for name, closed in d.panels:
                opened = self.editor.panel_open.get((self.nid, name), not closed)
                add("panel", name, panel=opened)
                if opened:
                    for p in (q for q in d.params if q.panel == name):
                        add("param", p.label, socket(p), p)
        elif node["type"] == ng.SOURCE and node.get("kind") == "shape":
            add("shape", "形狀")
            add("shapecolor", "顏色")
        if self.editor.show_thumbs and node["type"] not in (ng.OUTPUT, ng.PARAMS, ng.GROUP, "groupin", "groupout"):
            for name, _label in ng.outputs(node):
                add("thumb", "", p=name, h=THUMB_H)
        self.h = y + PAD

    def row_of(self, socket):
        return next((r for r in self.rows if r["socket"] == socket), None)

    def input_pos(self, socket):
        r = self.row_of(socket)
        return self.mapToScene(QPointF(0, r["y"] + ROW / 2 if r else HEAD))

    def output_pos(self, out=""):
        if self.node["type"] == ng.PARAMS:
            r = next((r for r in self.rows if r["kind"] in ("expose", "ghost") and (r["p"]["name"] if r["p"] else GHOST) == out), None)
        else:
            r = next((r for r in self.rows if (r["kind"] == "out" and (r["p"] or "") == out) or (r["kind"] == "ghost" and out == GHOST)), None)
        return self.mapToScene(QPointF(WIDTH, (r["y"] if r else HEAD + PAD) + ROW / 2))

    def outputs(self):
        """[(output name, scene point)]: one for a picture, one for each parameter (and the empty one) of a 參數輸入."""
        if self.node["type"] == ng.PARAMS:
            return [((r["p"]["name"] if r["p"] else GHOST), self.output_pos(r["p"]["name"] if r["p"] else GHOST))
                    for r in self.rows if r["kind"] in ("expose", "ghost")]
        return [((r["p"] or "") if r["kind"] == "out" else GHOST, self.output_pos((r["p"] or "") if r["kind"] == "out" else GHOST))
                for r in self.rows if r["kind"] in ("out", "ghost")]

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
        if r["kind"] == "plot":
            return QRectF(10, r["y"] + 2, WIDTH - 20, r["h"] - 4)
        x0 = WIDTH * LABEL_W
        w = (WIDTH - 10 - x0) / cells
        return QRectF(x0 + cell * w + (2 if cell else 0), r["y"] + 3, w - (2 if cells > 1 and cell < cells - 1 else 0), ROW - 6)

    def has_field(self, r):
        if r["kind"] == "param":
            return not (r["socket"] and r["socket"] in self.linked) and r["p"].type not in ("curve", "gradient")
        return r["kind"] in ("shape", "shapecolor", "plot")

    def field_at(self, pos):
        """(row, cell) of the field under pos (item coordinates), or the panel header row, else None."""
        for r in self.rows:
            if not (r["y"] <= pos.y() < r["y"] + r["h"]):
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
        viewed = self.editor.graph.get("viewer") or {}
        if viewed.get("node") == self.nid:                  # the node the preview shows (Ctrl + Shift + click)
            p.setPen(QColor("#ffe27a"))
            tag = "◉ 預覽" + (f"：{dict(ng.outputs(self.node)).get(viewed.get('out') or '', '')}" if len(ng.outputs(self.node)) > 1 else "")
            p.drawText(QRectF(8, 0, WIDTH - 16, HEAD), Qt.AlignVCenter | Qt.AlignRight, tag)
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
            if kind == "thumb":
                self._thumb(p, QRectF(10, y + 2, WIDTH - 20, r["h"] - 4), self.editor.thumb_image(self.nid, r["p"]))
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
        if kind == "plot":                                  # a curve or a gradient: drawn, click to edit it
            self._plot(p, self.field_rect(r), q, v, bg)
            return
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
    def _thumb(p, box, img):
        p.setPen(QPen(QColor(0, 0, 0, 90), 1))
        p.setBrush(QColor("#1c1c1f"))
        p.drawRoundedRect(box, 3, 3)
        if img is None:
            return
        k = min((box.width() - 2) / img.width(), (box.height() - 2) / img.height())
        w, h = img.width() * k, img.height() * k
        at = QRectF(box.center().x() - w / 2, box.center().y() - h / 2, w, h)
        n = 6
        for i in range(int(w // n) + 1):                    # (the checkerboard that shows transparency)
            for j in range(int(h // n) + 1):
                p.fillRect(QRectF(at.left() + i * n, at.top() + j * n, n, n).intersected(at),
                           QColor("#9a9a9a") if (i + j) % 2 else QColor("#6a6a6a"))
        p.drawImage(at, img)

    @staticmethod
    def _plot(p, box, q, v, bg):
        p.setPen(QPen(QColor(0, 0, 0, 90), 1))
        if q.type == "gradient":
            from PySide6.QtGui import QLinearGradient
            n = 6
            for i in range(int(box.width() // n) + 1):                    # (the checkerboard that shows opacity)
                for j in range(int(box.height() // n) + 1):
                    p.fillRect(QRectF(box.left() + i * n, box.top() + j * n, n, n).intersected(box),
                               QColor("#cfcfcf") if (i + j) % 2 else QColor("#8a8a8a"))
            g = QLinearGradient(box.left(), 0, box.right(), 0)
            for x, c in fx.gradient_stops(v):
                g.setColorAt(x, QColor.fromRgbF(*c))
            p.setBrush(g)
            p.drawRoundedRect(box, 3, 3)
            return
        p.setBrush(bg)
        p.drawRoundedRect(box, 3, 3)
        ys = fx.curve_samples(v, 48)
        lo, hi = min(0.0, min(ys)), max(1.0, max(ys))
        pts = QPainterPath()
        for i, y in enumerate(ys):
            pt = QPointF(box.left() + 3 + (box.width() - 6) * i / (len(ys) - 1), box.bottom() - 3 - (box.height() - 6) * (y - lo) / (hi - lo))
            pts.moveTo(pt) if i == 0 else pts.lineTo(pt)
        p.setPen(QPen(QColor("#f0a030"), 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawPath(pts)

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
        if self.node["type"] == ng.GROUP:                    # the head: a new name; anywhere else: look inside
            if e.pos().y() < HEAD:
                self.editor.rename_group(self.nid)
            else:
                self.editor.enter(self.nid)
            return
        if self.field_at(e.pos()) is None:
            super().mouseDoubleClickEvent(e)


class RerouteItem(QGraphicsItem):
    """A bend in a link: a small knob taking a picture in and passing it on."""
    W, H = 30.0, 24.0

    def __init__(self, nid, node, editor):
        super().__init__()
        self.nid, self.node, self.editor = nid, node, editor
        self.has_out, self.rows, self.linked, self.drag = True, [], set(), None
        self.title = ""
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setPos(node.get("x", 0.0), node.get("y", 0.0))
        self.setZValue(1)

    def boundingRect(self):
        return QRectF(-SOCKET_R - 1, -1, self.W + SOCKET_R * 2 + 2, self.H + 2)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and self.scene() is not None:
            for view in self.scene().views():
                view.reroute()
        return super().itemChange(change, value)

    def row_of(self, socket):
        return {} if socket == "src" else None

    def input_pos(self, socket="src"):
        return self.mapToScene(QPointF(0, self.H / 2))

    def output_pos(self, out=""):
        return self.mapToScene(QPointF(self.W, self.H / 2))

    def outputs(self):
        return [("", self.output_pos())]

    def sockets(self):
        return [("src", self.input_pos())]

    def paint(self, p, option, widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        body = QPainterPath()
        body.addRoundedRect(QRectF(0, 0, self.W, self.H), self.H / 2, self.H / 2)
        p.fillPath(body, QColor("#4a4a50"))
        p.setPen(QPen(QColor("#f0a030") if self.isSelected() else QColor(0, 0, 0, 120), 2 if self.isSelected() else 1))
        p.drawPath(body)
        NodeItem._socket(p, QPointF(0, self.H / 2), SOCKET_COLORS["image"])
        NodeItem._socket(p, QPointF(self.W, self.H / 2), SOCKET_COLORS["image"])


class FrameItem(QGraphicsItem):
    """A frame (框架 / 註解): a coloured box behind the nodes with a label and a note; dragging it takes the nodes
    inside along, the corner grip sizes it, double click edits it."""
    GRIP, BAR = 16.0, 24.0

    def __init__(self, nid, node, editor):
        super().__init__()
        self.nid, self.node, self.editor = nid, node, editor
        self.has_out, self.rows, self.linked, self.drag = False, [], set(), None
        self.w, self.h = float(node.get("w", 320.0)), float(node.get("h", 200.0))
        self.title = node.get("label", "")
        self.carry = None                                   # while dragged: the items inside it and where it was
        self.size = None                                    # while sized: (scene point, w, h) at the press
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setPos(node.get("x", 0.0), node.get("y", 0.0))
        self.setZValue(-1)

    def boundingRect(self):
        return QRectF(-1, -1, self.w + 2, self.h + 2)

    def row_of(self, socket):
        return None

    def outputs(self):
        return []

    def sockets(self):
        return []

    def grip_at(self, pos):
        return pos.x() > self.w - self.GRIP and pos.y() > self.h - self.GRIP

    def inside(self):
        """The other items whose middle is in the box."""
        me = self.sceneBoundingRect()
        return [it for it in self.scene().items() if it is not self and isinstance(it, (NodeItem, RerouteItem))
                and me.contains(it.sceneBoundingRect().center())]

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.grip_at(e.pos()):
            self.size = (e.scenePos(), self.w, self.h)
            e.accept()
            return
        if e.button() == Qt.LeftButton:
            self.carry = (self.pos(), [it for it in self.inside() if not it.isSelected()])
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.size:
            at, w0, h0 = self.size
            d = e.scenePos() - at
            self.prepareGeometryChange()
            self.w, self.h = max(60.0, w0 + d.x()), max(40.0, h0 + d.y())
            self.update()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        size, self.size = self.size, None
        if size:
            self.editor.frameEdited.emit(self.editor.eid, self.nid, {"w": self.w, "h": self.h})
            return
        super().mouseReleaseEvent(e)
        self.carry = None

    def mouseDoubleClickEvent(self, e):
        self.editor.frame_menu(self, e.screenPos())

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and self.scene() is not None:
            if self.carry:
                at, items = self.carry
                d = self.pos() - at
                self.carry = (self.pos(), items)
                for it in items:
                    it.setPos(it.pos() + d)
            for view in self.scene().views():
                view.reroute()
        return super().itemChange(change, value)

    def paint(self, p, option, widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor(ng.FRAME_COLORS.get(self.node.get("color"), ng.FRAME_COLORS["gray"]))
        box = QRectF(0, 0, self.w, self.h)
        fill = QColor(col)
        fill.setAlpha(70)
        p.setBrush(fill)
        p.setPen(QPen(QColor("#f0a030") if self.isSelected() else col.lighter(130), 2 if self.isSelected() else 1))
        p.drawRoundedRect(box, 6, 6)
        p.setPen(QColor("white"))
        f = QFont(p.font())
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(8, 0, self.w - 16, self.BAR), Qt.AlignVCenter | Qt.AlignLeft, self.title)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 200))
        p.drawText(QRectF(8, self.BAR, self.w - 16, self.h - self.BAR - 8), Qt.AlignTop | Qt.AlignLeft | Qt.TextWordWrap,
                   self.node.get("text", ""))
        tri = QPainterPath()
        tri.moveTo(self.w - 2, self.h - self.GRIP + 4)
        tri.lineTo(self.w - 2, self.h - 2)
        tri.lineTo(self.w - self.GRIP + 4, self.h - 2)
        p.fillPath(tri, col.lighter(160))


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
        self.pseudo_links = []                   # [(from, to, socket, output)] the links to and from a group's own sockets, inside it
        self.rubber = None                       # a link being dragged: (Link, source node, old (dst, socket) or None, output name)
        self.cut = None                          # a Ctrl + right button cut: (the line, its points)
        self.over = None                         # the link a dragged node is over (it will go through the node)
        self.press_at = {}
        self.setAcceptDrops(True)

    # -- media dragged in (the library's pictures / videos / compounds, or files): source nodes
    @staticmethod
    def _takes(md):
        from .timeline import MEDIA_MIME
        return md.hasFormat(MEDIA_MIME) or md.hasUrls()

    def dragEnterEvent(self, e):
        if self.editor.eid and self._takes(e.mimeData()):
            e.setDropAction(Qt.CopyAction)
            e.accept()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if self.editor.eid and self._takes(e.mimeData()):
            e.setDropAction(Qt.CopyAction)
            e.accept()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        from .timeline import MEDIA_MIME
        md = e.mimeData()
        if not (self.editor.eid and self._takes(md)):
            return super().dropEvent(e)
        at = self.mapToScene(e.position().toPoint())
        if md.hasFormat(MEDIA_MIME):
            ids = [i for i in bytes(md.data(MEDIA_MIME)).decode("utf-8").split(",") if i]
            paths = []
        else:
            ids, paths = [], [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
        e.setDropAction(Qt.CopyAction)
        e.accept()
        if ids or paths:
            self.editor.mediaDropped.emit(self.editor.eid, ids, paths, at.x(), at.y())

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
        if e.button() == Qt.LeftButton and e.modifiers() & Qt.ControlModifier and e.modifiers() & Qt.ShiftModifier:
            # Ctrl + Shift + click: the preview shows this node; again: its next output, and after the last, the effect's
            for nid, it in self.items_by_id.items():
                if it.sceneBoundingRect().contains(pos) and not isinstance(it, FrameItem):
                    self.editor.view_node(nid)
                    return
        if e.button() == Qt.LeftButton:
            hit = self.socket_at(pos)
            if hit:
                kind, nid, sock = hit
                old, out = None, sock if kind == "out" else ""
                if kind == "in":
                    link = self.editor.link_at(nid, sock)
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
            if e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
                # Ctrl + right button: drag across links to cut them; Shift + right button: to put a bend (繞線) in each
                line = QGraphicsPathItem()
                reroute = bool(e.modifiers() & Qt.ShiftModifier) and not e.modifiers() & Qt.ControlModifier
                line.setPen(QPen(QColor("#5fbf6a" if reroute else "#e0605a"), 2, Qt.DashLine))
                line.setZValue(20)
                self.scene().addItem(line)
                self.cut = (line, [pos], reroute)
                return
            hit = self.socket_at(pos)
            if hit and hit[0] == "out" and hit[2] not in ("", GHOST) and self.editor.node_of(hit[1])["type"] == ng.PARAMS:
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
                if ln.path().intersects(box) and a not in (PORT_IN, PORT_OUT) and b not in (PORT_IN, PORT_OUT):
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
            self.editor.drop_link(src, out, old, self.socket_at(pos), pos, e.globalPosition().toPoint())
            return
        if self.cut:
            line, pts, reroute = self.cut
            self.cut = None
            self.scene().removeItem(line)
            path = QPainterPath(pts[0])
            for q in pts[1:]:
                path.lineTo(q)
            stroke = QPainterPathStroker()
            stroke.setWidth(3)
            hit = stroke.createStroke(path)
            if reroute:
                spots = []
                for ln, a, b, sock, out in self.link_items:
                    if not ln.path().intersects(hit):
                        continue
                    near = [ln.path().pointAtPercent(i / 80) for i in range(81)]
                    near = [q for q in near if hit.contains(q)]
                    if near:
                        x = sum(q.x() for q in near) / len(near) - RerouteItem.W / 2
                        y = sum(q.y() for q in near) / len(near) - RerouteItem.H / 2
                        spots.append((x, y, a, b, sock, out))
                if spots:
                    self.editor.rerouteRequested.emit(self.editor.eid, spots)
                return
            cut = [(b, sock) for ln, a, b, sock, out in self.link_items if ln.path().intersects(hit) and a != PORT_IN and b != PORT_OUT]
            for ln, a, b, sock, out in self.link_items:         # (the links to and from the group's own sockets)
                if ln.path().intersects(hit) and a == PORT_IN:
                    self.editor.unplug(b, sock, None)
                elif ln.path().intersects(hit) and b == PORT_OUT:
                    self.editor.unplug("", "", sock)
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

    def focusNextPrevChild(self, forward):
        return False                                       # (Tab goes into a group, not to the next widget)

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
        if key in (Qt.Key_J, Qt.Key_C, Qt.Key_V):
            return mods == Qt.ControlModifier
        if key == Qt.Key_G:
            return mods in (Qt.ControlModifier, Qt.ControlModifier | Qt.AltModifier)
        if key == Qt.Key_Tab:
            return mods == Qt.NoModifier
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
        elif key == Qt.Key_C and mods == Qt.ControlModifier:
            self.editor.copy_selected()
        elif key == Qt.Key_V and mods == Qt.ControlModifier:
            self.editor.paste_here()
        elif key == Qt.Key_G and mods == Qt.ControlModifier:
            self.editor.group_selected()
        elif key == Qt.Key_G and mods == Qt.ControlModifier | Qt.AltModifier:
            self.editor.ungroup_selected()
        elif key == Qt.Key_Tab and mods == Qt.NoModifier:
            self.editor.tab()
        elif key == Qt.Key_J and mods == Qt.ControlModifier:
            self.editor.frame_selected()
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


CLIPBOARD = {"pack": None}                      # nodes copied (Ctrl+C), for any node effect to paste


class NodeEditor(QWidget):
    addRequested = Signal(str, dict, float, float)          # effect id, node ({"type", "ref" / "kind"}), x, y
    removeRequested = Signal(str, list)                     # effect id, node ids
    connectRequested = Signal(str, str, str, str, str)      # effect id, from node, to node, socket, the output (a parameter's name; "": picture)
    exposeRequested = Signal(str, str, str, str)            # effect id, 參數輸入 node, to node, socket: make a parameter of it
    disconnectManyRequested = Signal(str, list)             # effect id, [(to node, socket)]: links cut with Ctrl + right drag
    insertRequested = Signal(str, str, float, float, str, str, str, str)   # effect id, node, x, y, then the link it was dropped on
    addLinkedRequested = Signal(str, dict, float, float, str, str)         # effect id, node, x, y, node and output to link into it
    rerouteRequested = Signal(str, list)                    # effect id, [(x, y, from, to, socket, output)]: bends to put in links
    mediaDropped = Signal(str, list, list, float, float)    # effect id, library item ids, file paths, x, y: dragged in as source nodes
    thumbsToggled = Signal(bool)                            # the 縮圖 button: the preview sends every node's picture
    groupRequested = Signal(str, list)                      # effect id, node ids: box them up (Ctrl+G)
    ungroupRequested = Signal(str, str)                     # effect id, group id: take it apart
    groupRenamed = Signal(str, str, str)                    # effect id, group id, the new name
    groupPortRequested = Signal(str, str, str, str, object, str, str, str)   # effect id, group, member, socket, member output (None: an input), socket name ("": new), old member, old socket
    groupUnplugRequested = Signal(str, str, str, str, object)  # effect id, group, member, socket, group output name (None: an input)
    viewerRequested = Signal(str, str, str)                 # effect id, node, output ("" node: the effect's output again)
    pasteRequested = Signal(str, dict, float, float)        # effect id, nodegraph.pack, x, y: nodes pasted
    frameEdited = Signal(str, str, dict)                    # effect id, frame id, what changed (label / text / color / w / h)
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
    placeEdited = Signal(str, str, str, object)             # effect id, node id, where it sits (cx / cy / w / h / rotation), value
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
        self.level = ""                                     # the group being looked into ("": the effect's own level)
        self.pseudo = {}                                    # the 群組輸入 / 群組輸出 boxes shown inside a group
        self.here = QLabel("")
        bar.addWidget(self.here)
        leave = QPushButton("離開群組 (Tab)")
        leave.clicked.connect(lambda: self.leave())
        leave.hide()
        self.leave_btn = leave
        bar.addWidget(leave)
        group = QPushButton("群組 (Ctrl+G)")
        group.setToolTip("把選取的節點包成一個群組節點；雙擊群組（或選取後按 Tab）進去看，Ctrl+Alt+G 拆開")
        group.clicked.connect(self.group_selected)
        bar.addWidget(group)
        self.show_thumbs = False
        self.thumbs = {}                                    # {node id: {output: QImage}} of the last frame drawn
        thumb = QPushButton("縮圖")
        thumb.setCheckable(True)
        thumb.setToolTip("每個節點下面顯示它輸出的圖（預覽目前這一格的結果）")
        thumb.toggled.connect(self.set_show_thumbs)
        bar.addWidget(thumb)
        tidy = QPushButton("整理 ▾")
        tidy.setToolTip("對齊、均分、自動排列選取的節點")
        tidy.clicked.connect(lambda: self.tidy_menu(tidy.mapToGlobal(tidy.rect().bottomLeft())))
        bar.addWidget(tidy)
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
        if first:
            self.level = ""
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
        nodes = self.graph["nodes"]
        if self.level and (nodes.get(self.level) or {}).get("type") != ng.GROUP:
            self.level = ""
        here = {nid: node for nid, node in nodes.items() if (node.get("group") or "") == self.level}
        links = [(l["from"], l["to"], l["socket"], l.get("out") or "") for l in self.graph["links"]
                 if l["from"] in here and l["to"] in here]
        self.pseudo = {}
        if self.level:                                      # inside a group: its own sockets at the sides
            g = nodes[self.level]
            xs = [n.get("x", 0.0) for n in here.values()] or [0.0]
            ys = [n.get("y", 0.0) for n in here.values()] or [0.0]
            self.pseudo = {PORT_IN: {"type": "groupin", "x": min(xs) - 300, "y": min(ys),
                                     "items": [{"name": i["name"], "label": i["label"]} for i in g.get("inputs") or []]},
                           PORT_OUT: {"type": "groupout", "x": max(xs) + 340, "y": min(ys),
                                      "items": [{"name": o["name"], "label": o["label"]} for o in g.get("outputs") or []]}}
            links += [(PORT_IN, m, sk, i["name"]) for i in g.get("inputs") or [] for m, sk in i.get("to") or [] if m in here]
            links += [(o["from"], PORT_OUT, o["name"], o.get("out") or "") for o in g.get("outputs") or [] if o["from"] in here]
        v.pseudo_links = [l for l in links if PORT_IN in l[:1] or PORT_OUT in l[1:2]]
        for nid, node in list(here.items()) + list(self.pseudo.items()):
            it = {ng.REROUTE: RerouteItem, ng.FRAME: FrameItem}.get(node["type"], NodeItem)(nid, node, self)
            sc.addItem(it)
            v.items_by_id[nid] = it
            it.setSelected(nid in keep)
        for a_id, b_id, socket, out in links:
            a, b = v.items_by_id.get(a_id), v.items_by_id.get(b_id)
            if a is None or b is None or b.row_of(socket) is None or out not in [o for o, _ in a.outputs()]:
                continue
            ln = Link()
            ln.route(a.output_pos(out), b.input_pos(socket))
            sc.addItem(ln)
            v.link_items.append((ln, a_id, b_id, socket, out))
        self.here.setText(("位置：根 › " + (nodes[self.level].get("label") or "群組")) if self.level else "")
        self.leave_btn.setVisible(bool(self.level))
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
        if node.get("type") != ng.FILTER and not ng.is_asset(node):
            return self.Values({}, None, src.get("shape", "rectangle"), src.get("color") or [1.0, 1.0, 1.0, 1.0])
        d = ng.node_def(node)
        vals = {p.name: curves.value(self.params.get(ng.param_key(nid, p.name), p.default), self.t) for p in d.params}
        if ng.is_asset(node):                                  # (where it sits: the source's own fields)
            vals.update({p.name: curves.value(src.get(p.name, p.default), self.t) for p in ng.place_params()})
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
        if getattr(q, "place", False):
            src = self.sources.get(nid)
            if src is not None and not curves.is_animated(src.get(q.name)):
                src[q.name] = new
            self.placeEdited.emit(self.eid, nid, q.name, new)
            self.view.viewport().update()
            return
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
        if kind == "plot":
            self.edit_popup(q, v, lambda value: self.paramEdited.emit(self.eid, key, value), gp)
            return
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

    def edit_popup(self, q, v, done, pos):
        """The curve or gradient editor of the 效果 panel in a small window at pos; done(value) hears every change."""
        from PySide6.QtWidgets import QFrame
        from .curvefield import CurveField
        from .gradientbar import GradientEditor
        frame = QFrame(self, Qt.Popup)
        frame.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(6, 6, 6, 6)
        if q.type == "curve":
            w = CurveField()
            w.set_value(v)
            frame.setMinimumWidth(320)
        else:
            w = GradientEditor()
            w.set_stops(fx.gradient_stops(v))
            frame.setMinimumWidth(360)
        w.changed.connect(done)
        lay.addWidget(w)
        frame.move(pos)
        frame.show()
        self._popup_editor = frame

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

    def ask_text(self, title, text, multi=False):
        from PySide6.QtWidgets import QInputDialog
        if multi:
            got, ok = QInputDialog.getMultiLineText(self, title, title, text)
        else:
            got, ok = QInputDialog.getText(self, title, title, text=text)
        return got if ok else None

    def frame_menu(self, item, pos):
        """Double click on a frame: its label, its note, its colour."""
        menu = QMenu(self)
        node = item.node

        def ask(key, title, multi):
            got = self.ask_text(title, node.get(key, ""), multi)
            if got is not None and got != node.get(key):
                self.frameEdited.emit(self.eid, item.nid, {key: got})
        menu.addAction("改標籤…", lambda: ask("label", "標籤", False))
        menu.addAction("改文字…", lambda: ask("text", "文字", True))
        colors = menu.addMenu("顏色")
        names = {"gray": "灰", "red": "紅", "orange": "橘", "green": "綠", "blue": "藍", "purple": "紫"}
        for key in ng.FRAME_COLORS:
            colors.addAction(names[key], lambda _=False, k=key: self.frameEdited.emit(self.eid, item.nid, {"color": k}))
        self.popup(menu, pos.toPoint() if hasattr(pos, "toPoint") else pos)

    # -- groups ---------------------------------------------------------------------------------------
    def node_of(self, nid):
        return self.graph["nodes"].get(nid) or self.pseudo[nid]

    def link_at(self, nid, socket):
        """The link into socket of nid, as {"from", "out"} (None: there is none) - one from the group's own input too."""
        for l in self.graph["links"]:
            if l["to"] == nid and l["socket"] == socket and l["from"] in self.view.items_by_id:
                return l
        for a, b, sk, out in self.view.pseudo_links:
            if b == nid and sk == socket and a == PORT_IN:
                return {"from": a, "out": out}
        return None

    def drop_link(self, src, out, old, hit, pos, gpos):
        """A link dragged from output out of src let go at hit (None: in the empty); old: (node, socket) it was
        picked up from."""
        gid = self.level
        into = hit if hit and hit[0] == "in" and hit[1] != src else None
        if src == PORT_IN:                                  # from a group input: onto a member's socket
            name = "" if out == GHOST else out
            if into and into[1] != PORT_OUT:
                self.groupPortRequested.emit(self.eid, gid, into[1], into[2], None, name, *(old or ("", "")))
            elif hit is None and old:
                self.unplug(old[0], old[1], None)
            return
        if into and into[1] == PORT_OUT:                    # onto a group output
            name = "" if into[2] == GHOST_IN else into[2]
            self.groupPortRequested.emit(self.eid, gid, src, "", out, name, "", "")
            return
        if old and old[0] == PORT_OUT:                      # a group output picked up and let go elsewhere
            if hit is None:
                self.unplug("", "", old[1])
            return
        if into:
            if out == GHOST:
                self.exposeRequested.emit(self.eid, src, into[1], into[2])
            elif old != (into[1], into[2]):
                self.connectRequested.emit(self.eid, src, into[1], into[2], out)
        elif hit is None and old:
            self.disconnectRequested.emit(self.eid, old[0], old[1])
        elif hit is None and self.node_of(src)["type"] not in (ng.PARAMS, "groupin"):   # a link let go in the empty: add a node there to take it
            self.add_menu(pos, gpos, (src, out))

    def unplug(self, member, socket, output):
        if self.level and self.eid:
            self.groupUnplugRequested.emit(self.eid, self.level, member, socket, output)

    def enter(self, gid):
        if (self.graph["nodes"].get(gid) or {}).get("type") == ng.GROUP:
            self.level = gid
            self.rebuild(True)

    def leave(self):
        if self.level:
            parent = self.graph["nodes"][self.level].get("group") or ""
            self.level = parent
            self.rebuild(True)

    def group_selected(self):
        ids = [i for i in self.selected() if self.graph["nodes"][i]["type"] not in (ng.OUTPUT, ng.FRAME)]
        if ids and self.eid:
            self.groupRequested.emit(self.eid, ids)

    def ungroup_selected(self):
        for i in self.selected():
            if self.graph["nodes"][i]["type"] == ng.GROUP:
                self.ungroupRequested.emit(self.eid, i)

    def tab(self):
        """Tab: into the selected group, else out of the one looked into."""
        one = [i for i in self.selected() if self.graph["nodes"][i]["type"] == ng.GROUP]
        if len(one) == 1:
            self.enter(one[0])
        else:
            self.leave()

    def rename_group(self, gid):
        node = self.graph["nodes"].get(gid)
        got = self.ask_text("群組名稱", node.get("label", "")) if node else None
        if got and got != node.get("label"):
            self.groupRenamed.emit(self.eid, gid, got)

    def set_show_thumbs(self, on):
        self.show_thumbs = bool(on)
        self.thumbsToggled.emit(self.show_thumbs)
        self.rebuild()

    def set_thumbs(self, data):
        """{effect id: {node id: {output: (w, h, RGBA bytes)}}} from the preview: what the thumbnails show."""
        from PySide6.QtGui import QImage
        mine = data.get(self.eid) or {}
        self.thumbs = {nid: {o: QImage(b, w, h, w * 4, QImage.Format_RGBA8888_Premultiplied).copy()
                             for o, (w, h, b) in outs.items()} for nid, outs in mine.items()}
        if self.show_thumbs:
            self.view.viewport().update()

    def thumb_image(self, nid, out):
        return (self.thumbs.get(nid) or {}).get(out)

    def view_node(self, nid):
        """Ctrl + Shift + click on node nid: step the preview along nid's outputs (then off)."""
        node = self.graph["nodes"][nid]
        if node["type"] in (ng.PARAMS, ng.OUTPUT) or not self.eid:
            return
        names = [o for o, _ in ng.outputs(node)]
        now = self.graph.get("viewer") or {}
        if now.get("node") == nid:
            k = names.index(now.get("out") or "") + 1 if (now.get("out") or "") in names else 0
        else:
            k = 0
        if k >= len(names):
            self.viewerRequested.emit(self.eid, "", "")
        else:
            self.viewerRequested.emit(self.eid, nid, names[k])

    def copy_selected(self):
        ids = self.selected()
        pack = ng.pack(self.graph, ids, self.params, self.sources)
        if pack["nodes"]:
            CLIPBOARD["pack"] = pack

    def paste_here(self, at=None):
        pack = CLIPBOARD["pack"]
        if not (pack and self.eid):
            return
        if at is None:
            at = self.view.mapToScene(self.view.mapFromGlobal(self.view.cursor().pos()))
            if not self.view.viewport().rect().contains(self.view.mapFromGlobal(self.view.cursor().pos())):
                at = self.view.mapToScene(self.view.viewport().rect().center())
        self.pasteRequested.emit(self.eid, pack, at.x(), at.y())

    def _moves(self, new):
        """Ask for the positions new {node id: (x, y)} (those that changed)."""
        new = {i: p for i, p in new.items() if (round(p[0], 3), round(p[1], 3)) != (round(self.graph["nodes"][i].get("x", 0.0), 3), round(self.graph["nodes"][i].get("y", 0.0), 3))}
        if new and self.eid:
            self.moveRequested.emit(self.eid, new)

    def align(self, how):
        """how: left / right / top / bottom / hcenter / vcenter / hspread / vspread of the selected nodes."""
        its = {i: self.view.items_by_id[i] for i in self.selected() if self.graph["nodes"][i]["type"] != ng.FRAME}
        if len(its) < 2:
            return
        box = {i: it.sceneBoundingRect() for i, it in its.items()}
        new = {}
        left, right = min(r.left() for r in box.values()), max(r.right() for r in box.values())
        top, bottom = min(r.top() for r in box.values()), max(r.bottom() for r in box.values())
        for i, r in box.items():
            p = its[i].pos()
            dx = dy = 0.0
            if how == "left":
                dx = left - r.left()
            elif how == "right":
                dx = right - r.right()
            elif how == "top":
                dy = top - r.top()
            elif how == "bottom":
                dy = bottom - r.bottom()
            elif how == "hcenter":
                dx = (left + right) / 2 - r.center().x()
            elif how == "vcenter":
                dy = (top + bottom) / 2 - r.center().y()
            new[i] = (p.x() + dx, p.y() + dy)
        if how in ("hspread", "vspread"):
            h = how == "hspread"
            order = sorted(box, key=lambda i: box[i].left() if h else box[i].top())
            total = sum(box[i].width() if h else box[i].height() for i in order)
            gap = ((right - left) if h else (bottom - top)) - total
            gap /= len(order) - 1
            at = left if h else top
            for i in order:
                r, p = box[i], its[i].pos()
                new[i] = (p.x() + (at - r.left()), p.y()) if h else (p.x(), p.y() + (at - r.top()))
                at += (r.width() if h else r.height()) + gap
        self._moves(new)

    def arrange(self):
        """Every node in a column by how far it is from the start, left to right, tidy rows in each."""
        cols = {}
        for i, d in ng.depths(self.graph).items():
            if self.graph["nodes"][i]["type"] != ng.FRAME and i in self.view.items_by_id:
                cols.setdefault(d, []).append(i)
        new, x = {}, 0.0
        for d in sorted(cols):
            y, width = 0.0, 0.0
            for i in sorted(cols[d], key=lambda i: (self.graph["nodes"][i].get("y", 0.0), i)):
                r = self.view.items_by_id[i].sceneBoundingRect()
                new[i] = (x + (self.view.items_by_id[i].pos().x() - r.left()), y + (self.view.items_by_id[i].pos().y() - r.top()))
                y += r.height() + 30
                width = max(width, r.width())
            x += width + 80
        self._moves(new)

    def tidy_menu(self, pos):
        menu = QMenu(self)
        for key, text in (("left", "靠左對齊"), ("right", "靠右對齊"), ("top", "靠上對齊"), ("bottom", "靠下對齊"),
                          ("hcenter", "水平置中"), ("vcenter", "垂直置中"), ("hspread", "水平均分"), ("vspread", "垂直均分")):
            menu.addAction(text, lambda _=False, k=key: self.align(k))
        menu.addSeparator()
        menu.addAction("自動排列（全部）", self.arrange)
        self.popup(menu, pos)

    def frame_selected(self):
        """Ctrl+J: a frame around the selected nodes."""
        items = [self.view.items_by_id[i] for i in self.selected() if self.graph["nodes"][i]["type"] != ng.FRAME]
        if not items or not self.eid:
            return
        r = items[0].sceneBoundingRect()
        for it in items[1:]:
            r = r.united(it.sceneBoundingRect())
        r = r.adjusted(-24, -FrameItem.BAR - 16, 24, 24)
        self.addRequested.emit(self.eid, {"type": ng.FRAME, "w": r.width(), "h": r.height(), **({"group": self.level} if self.level else {})}, r.x(), r.y())

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
            if self.level:
                node = dict(node, group=self.level)
            if link:
                self.addLinkedRequested.emit(self.eid, node, scene_pos.x(), scene_pos.y(), link[0], link[1])
            else:
                self.addRequested.emit(self.eid, node, scene_pos.x(), scene_pos.y())
        menu = QMenu(self)
        entries = []                                      # [(menu path, name, node)] - what the search looks through
        search = QLineEdit()
        search.setPlaceholderText("搜尋節點…")
        box = QWidgetAction(menu)
        box.setDefaultWidget(search)
        menu.addAction(box)
        groups = []                                       # the category submenus (hidden while searching)
        inp = menu.addMenu("輸入")
        groups.append(inp.menuAction())
        for text, node in (("輸入（片段的畫面）", {"type": ng.INPUT}), ("參數輸入（效果自己的參數）", {"type": ng.PARAMS}), ("繞線點", {"type": ng.REROUTE}), ("框架／註解", {"type": ng.FRAME}), ("圖片", {"type": ng.SOURCE, "kind": "image"}),
                           ("影片", {"type": ng.SOURCE, "kind": "video"}), ("複合片段", {"type": ng.SOURCE, "kind": "compound"}),
                           ("時間線（軌道）", {"type": ng.SOURCE, "kind": "track"})):
            inp.addAction(text, lambda _=False, n=node: ask(n))
            entries.append(("輸入", text, node))
        shapes = menu.addMenu("形狀")
        groups.append(shapes.menuAction())
        for a in assets.ASSETS:                           # the built-in shapes, with all their parameters
            if a.cat == "shape":
                node = {"type": ng.SOURCE, "kind": "shape", "asset": {"key": a.key}}
                shapes.addAction(a.name, lambda _=False, n=node: ask(n))
                entries.append(("形狀", a.name, node))
        tools = {}                                        # the tool nodes (filters/nodes), by Blender-like category
        for ref in node_refs():
            d = fx.get(ref)
            tools.setdefault(d.category or "其他", []).append((d.name, ref))
        for name, ref in tools.pop("輸入", []):             # (the inputs menu has the time and coordinate nodes too)
            node = {"type": ng.FILTER, "ref": ref}
            inp.addAction(name, lambda _=False, n=node: ask(n))
            entries.append(("輸入", name, node))
        for cat in [c for c in NODE_HEADS if c in tools] + sorted(c for c in tools if c not in NODE_HEADS):
            sub = menu.addMenu(cat)
            groups.append(sub.menuAction())
            for name, ref in tools[cat]:
                node = {"type": ng.FILTER, "ref": ref}
                sub.addAction(name, lambda _=False, n=node: ask(n))
                entries.append((cat, name, node))
        effects = menu.addMenu("內建／效果")                # every effect of the 效果 list, as a node
        groups.append(effects.menuAction())
        cats = {}
        for ref in fx.builtin_refs():
            if not is_tool(ref):
                d = fx.get(ref)
                cats.setdefault(d.category or "其他", []).append((d.name, ref))
        for cat in sorted(cats):
            sub = effects.addMenu(cat)
            for name, ref in cats[cat]:
                node = {"type": ng.FILTER, "ref": ref}
                sub.addAction(name, lambda _=False, n=node: ask(n))
                entries.append(("內建／效果 ▸ " + cat, name, node))
        if self.user_filters:
            mine = menu.addMenu("我的濾鏡（Library）")
            groups.append(mine.menuAction())
            for name, path in self.user_filters:
                node = {"type": ng.FILTER, "ref": path}
                mine.addAction(name, lambda _=False, n=node: ask(n))
                entries.append(("我的濾鏡", name, node))
        found = []                                        # the actions of the matches, shown in place of the categories

        def refresh(text):
            for act in found:
                menu.removeAction(act)
            found.clear()
            text = text.strip().lower()
            for act in groups:
                act.setVisible(not text)
            if not text:
                return
            for cat, name, node in entries:
                if text in name.lower() or text in cat.lower() or text in str(node.get("ref", node.get("shape", ""))).lower():
                    found.append(menu.addAction(f"{name}　（{cat}）", lambda _=False, n=node: ask(n)))
            if not found:
                none = menu.addAction("沒有符合的節點")
                none.setEnabled(False)
                found.append(none)
        search.textChanged.connect(refresh)

        def first():
            for act in found:
                if act.isEnabled():
                    act.trigger()
                    menu.close()
                    return
        search.returnPressed.connect(first)
        menu.search, menu.found = search, found           # (for the tests)
        menu.setActiveAction(box)
        QTimer.singleShot(0, search.setFocus)
        self.popup(menu, global_pos)
