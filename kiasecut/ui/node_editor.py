"""The node editor (節點): the graph of a node effect (nodegraph.py) drawn as Blender's compositor draws it -
boxes with sockets, links between them. It only shows and asks: every change is a signal the main window
makes an edit of (and an undo step), and the graph it gets back is drawn again.

Left drag on a socket makes a link (dropped on a socket of another node: linked; a linked input picked up and
dropped on nothing: unlinked), on a node moves it, on the empty part selects with a box. Wheel zooms, the
middle button drags the view (middledrag.py), Shift+A (or the right button) adds a node where the pointer
is, X / Delete removes the selected ones, M mutes them (the picture goes through unchanged), Home shows
everything. Selecting a picture / video / compound / track node shows it on the preview to place it, as a
mask is (the main window follows nodeSelected).
"""
import glob
import json
import os

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QComboBox, QGraphicsItem, QGraphicsPathItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel,
                               QMenu, QPushButton, QVBoxLayout, QWidget)

from .. import fx, nodegraph as ng

WIDTH, HEAD, ROW, PAD = 160.0, 24.0, 20.0, 6.0
SOCKET_R = 5.5
HIT_R = 9.0
HEADS = {ng.INPUT: "#a8473f", ng.OUTPUT: "#a8473f", ng.SOURCE: "#3f8a5a"}
CATEGORY_COLORS = ("#3f6fa8", "#7a55a8", "#a8843f", "#3f8f9a", "#a8553f", "#5f8f3f", "#8f3f78")


def node_refs():
    """Refs of the filters made for graphs (filters/nodes/*.glsl)."""
    return sorted("builtin:nodes/" + os.path.splitext(os.path.basename(p))[0]
                  for p in glob.glob(os.path.join(fx.PKG, "nodes", "*.glsl")))


def head_colour(node):
    if node["type"] in HEADS:
        return QColor(HEADS[node["type"]])
    cat = fx.get(node["ref"]).category or ""
    return QColor(CATEGORY_COLORS[sum(map(ord, cat)) % len(CATEGORY_COLORS)] if cat != "節點" else "#3f6fa8")


class NodeItem(QGraphicsItem):
    def __init__(self, nid, node):
        super().__init__()
        self.nid, self.node = nid, node
        self.inputs = ng.sockets(node)
        self.has_out = ng.has_output(node)
        rows = max(1, len(self.inputs), 1 if self.has_out else 0)
        self.h = HEAD + PAD * 2 + rows * ROW
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setPos(node.get("x", 0.0), node.get("y", 0.0))
        self.setZValue(1)
        self.title = ng.title(node)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and self.scene() is not None:
            for view in self.scene().views():
                view.reroute()
        return super().itemChange(change, value)

    def boundingRect(self):
        return QRectF(-SOCKET_R - 1, -1, WIDTH + SOCKET_R * 2 + 2, self.h + 2)

    def input_pos(self, i):
        return self.mapToScene(QPointF(0, HEAD + PAD + i * ROW + ROW / 2))

    def output_pos(self):
        return self.mapToScene(QPointF(WIDTH, HEAD + PAD + ROW / 2))

    def paint(self, p, option, widget=None):
        pal = widget.palette() if widget else None
        base = pal.window().color().lighter(125) if pal else QColor("#38383c")
        text = pal.windowText().color() if pal else QColor("white")
        p.setRenderHint(QPainter.Antialiasing)
        body = QPainterPath()
        body.addRoundedRect(QRectF(0, 0, WIDTH, self.h), 6, 6)
        p.fillPath(body, base)
        head = QPainterPath()
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
        p.setPen(text)
        for i, (sock, label) in enumerate(self.inputs):
            y = HEAD + PAD + i * ROW
            p.drawText(QRectF(10, y, WIDTH - 20, ROW), Qt.AlignVCenter | Qt.AlignLeft, ("▸ " if sock.startswith(ng.PARAM) else "") + label)
        if self.has_out:
            p.setPen(text)
            p.drawText(QRectF(10, HEAD + PAD, WIDTH - 20, ROW), Qt.AlignVCenter | Qt.AlignRight, "圖像")
        for i, (sock, _l) in enumerate(self.inputs):
            self._socket(p, QPointF(0, HEAD + PAD + i * ROW + ROW / 2), sock.startswith(ng.PARAM))
        if self.has_out:
            self._socket(p, QPointF(WIDTH, HEAD + PAD + ROW / 2), False)

    @staticmethod
    def _socket(p, at, param):
        p.setPen(QPen(QColor(0, 0, 0, 160), 1))
        p.setBrush(QColor("#a0a0a8") if param else QColor("#c8c85a"))
        p.drawEllipse(at, SOCKET_R, SOCKET_R)


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
        self.link_items = []
        self.rubber = None                       # a link being dragged: (Link, source node id, old (dst, socket) or None)
        self.press_at = {}

    # -- finding sockets -----------------------------------------------------------------------------
    def socket_at(self, pos):
        """("out", node id, "") / ("in", node id, socket) near scene point pos, else None."""
        for nid, it in self.items_by_id.items():
            if it.has_out and (it.output_pos() - pos).manhattanLength() <= HIT_R * 1.5:
                return "out", nid, ""
            for i, (sock, _l) in enumerate(it.inputs):
                if (it.input_pos(i) - pos).manhattanLength() <= HIT_R * 1.5:
                    return "in", nid, sock
        return None

    # -- mouse ---------------------------------------------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            pos = self.mapToScene(e.position().toPoint())
            hit = self.socket_at(pos)
            if hit:
                kind, nid, sock = hit
                old = None
                if kind == "in":
                    link = next((l for l in self.editor.graph["links"] if l["to"] == nid and l["socket"] == sock), None)
                    if link is None:
                        pass
                    else:
                        old, nid = (nid, sock), link["from"]
                        kind = "out"
                if kind == "out":
                    ln = Link()
                    self.scene().addItem(ln)
                    self.rubber = (ln, nid, old)
                    self._route_temp(pos)
                    return
            self.press_at = {i: (it.pos().x(), it.pos().y()) for i, it in self.items_by_id.items()}
        elif e.button() == Qt.RightButton:
            self.editor.add_menu(self.mapToScene(e.position().toPoint()), e.globalPosition().toPoint())
            return
        super().mousePressEvent(e)

    def reroute(self):
        """Draw the links again (a node moved)."""
        for ln, a, b, i in self.link_items:
            ln.route(self.items_by_id[a].output_pos(), self.items_by_id[b].input_pos(i))

    def _route_temp(self, pos):
        ln, src, _old = self.rubber
        ln.route(self.items_by_id[src].output_pos(), pos)

    def mouseMoveEvent(self, e):
        if self.rubber:
            self._route_temp(self.mapToScene(e.position().toPoint()))
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.rubber:
            ln, src, old = self.rubber
            self.rubber = None
            self.scene().removeItem(ln)
            hit = self.socket_at(self.mapToScene(e.position().toPoint()))
            if hit and hit[0] == "in" and hit[1] != src:
                if old != (hit[1], hit[2]):
                    self.editor.connectRequested.emit(self.editor.eid, src, hit[1], hit[2])
            elif old:
                self.editor.disconnectRequested.emit(self.editor.eid, old[0], old[1])
            return
        super().mouseReleaseEvent(e)
        moved = {i: (it.pos().x(), it.pos().y()) for i, it in self.items_by_id.items()
                 if self.press_at.get(i) not in (None, (it.pos().x(), it.pos().y()))}
        self.press_at = {}
        if moved:
            self.editor.moveRequested.emit(self.editor.eid, moved)
        self.editor.selection_changed()

    def wheelEvent(self, e):
        k = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        s = self.transform().m11() * k
        if 0.2 <= s <= 3.0:
            self.scale(k, k)

    def keyPressEvent(self, e):
        key = e.key()
        if key in (Qt.Key_X, Qt.Key_Delete):
            self.editor.remove_selected()
        elif key == Qt.Key_M:
            self.editor.mute_selected()
        elif key == Qt.Key_Home:
            self.fit()
        elif key == Qt.Key_A and e.modifiers() & Qt.ShiftModifier:
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
    connectRequested = Signal(str, str, str, str)           # effect id, from node, to node, socket
    disconnectRequested = Signal(str, str, str)             # effect id, to node, socket
    moveRequested = Signal(str, dict)                       # effect id, {node id: (x, y)}
    muteRequested = Signal(str, list, bool)                 # effect id, node ids, on
    nodeSelected = Signal(str, str)                         # effect id, the one node selected ("" none)
    effectChosen = Signal(str)                              # effect id: another node effect of the clip

    def __init__(self, parent=None):
        super().__init__(parent)
        self.eid = None
        self.graph = {"nodes": {}, "links": []}
        self.effects = []                                   # [(effect id, name)]
        self.user_filters = []
        self._sig = None
        self._selected = ""
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

    def show_clip(self, clip, want=None):
        """Show a node effect of clip (None: nothing): want, else the one shown before, else the first."""
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
        sig = json.dumps(e["graph"], sort_keys=True)
        if sig != self._sig:
            self._sig = sig
            self.graph = e["graph"]
            self.rebuild(first)

    def rebuild(self, fit):
        v = self.view
        keep = {i for i, it in v.items_by_id.items() if it.isSelected()}
        sc = v.scene()
        sc.clear()
        v.items_by_id, v.link_items = {}, []
        for nid, node in self.graph["nodes"].items():
            it = NodeItem(nid, node)
            sc.addItem(it)
            v.items_by_id[nid] = it
            it.setSelected(nid in keep)
        for l in self.graph["links"]:
            a, b = v.items_by_id.get(l["from"]), v.items_by_id.get(l["to"])
            if a is None or b is None:
                continue
            names = [s for s, _ in b.inputs]
            if l["socket"] not in names:
                continue
            ln = Link()
            ln.route(a.output_pos(), b.input_pos(names.index(l["socket"])))
            sc.addItem(ln)
            v.link_items.append((ln, l["from"], l["to"], names.index(l["socket"])))
        r = sc.itemsBoundingRect()
        sc.setSceneRect(r.adjusted(-1500, -1500, 1500, 1500))
        if fit:
            v.fit()

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

    def add_menu(self, scene_pos, global_pos):
        if not self.eid:
            return
        menu = QMenu(self)
        inp = menu.addMenu("輸入")
        for text, node in (("輸入（片段的畫面）", {"type": ng.INPUT}), ("圖片", {"type": ng.SOURCE, "kind": "image"}),
                           ("影片", {"type": ng.SOURCE, "kind": "video"}), ("複合片段", {"type": ng.SOURCE, "kind": "compound"}),
                           ("時間線（軌道）", {"type": ng.SOURCE, "kind": "track"})):
            inp.addAction(text, lambda n=node: self.addRequested.emit(self.eid, n, scene_pos.x(), scene_pos.y()))
        cats = {}
        for ref in node_refs() + fx.builtin_refs():
            d = fx.get(ref)
            cats.setdefault("節點" if ref.startswith("builtin:nodes/") else d.category or "其他", []).append((d.name, ref))
        for cat in sorted(cats, key=lambda c: (c != "節點", c)):
            sub = menu.addMenu(cat)
            for name, ref in cats[cat]:
                sub.addAction(name, lambda r=ref: self.addRequested.emit(self.eid, {"type": ng.FILTER, "ref": r},
                                                                         scene_pos.x(), scene_pos.y()))
        if self.user_filters:
            mine = menu.addMenu("我的濾鏡（Library）")
            for name, path in self.user_filters:
                mine.addAction(name, lambda r=path: self.addRequested.emit(self.eid, {"type": ng.FILTER, "ref": r},
                                                                           scene_pos.x(), scene_pos.y()))
        menu.exec(global_pos)
