"""The editor of a 聲音節點效果 (soundnodes.py), on the 聲音 page.

It looks and works as KiaseCut's node editor (and qpwgraph-kc, whose behaviours these are):
    drag from a socket          a link (onto empty space: the add menu, wired up)
    drag a wired input          picks the link up (drop on nothing: unwired)
    drag a node                 moves it; dropped on a link: put into it
    drag empty space            box select;  middle button: pan;  wheel: zoom
    right click                 add menu;  Ctrl + right drag: cut;  Shift + right drag: reroute
    on a value: drag sideways to change it (Shift: fine), double click to type, right click
    for keyframes and the default
    Shift+A add, A all, X / Delete delete, Ctrl+X delete keeping the wires, M mute,
    Shift+D duplicate, Ctrl+C / V, G grab, Ctrl+J frame, Home show all
"""
import math

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QCursor, QPainter, QPainterPath, QPainterPathStroker, QPen
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsPathItem, QGraphicsProxyWidget, QGraphicsScene, QGraphicsView,
                               QHBoxLayout, QInputDialog, QLabel, QPushButton, QVBoxLayout, QWidget)

from .. import curves, edit, rack, soundedit, soundfx, soundnodes, soundnumbers
from . import sound_follow
from . import inplace
from .menukeys import Menu
from .node_editor import GRID, HEAD, HIT_R, LINK_W, ROW, SNAP_R, SOCKET_R, ZOOM_MAX, ZOOM_MIN, Link
from .searchbox import SearchBox
from .sound_visuals import Dynamics, Response, Spectrum

WIDTH, WIDE, MIN_W = 210.0, 300.0, 150.0
VISUAL_H = {"eq": 150, "response": 100, "dynamics": 140, "spectrum": 100}
SOCKET = {"stereo": "#7438ff", "l": "#e6c84a", "r": "#4ab5e6", "num": "#a1a1a1"}
HEADS = {"in": "#3f8a5a", "out": "#a8473f", "ext": "#7a55a8", "split": "#b3702f", "merge": "#b3702f", "mix": "#b3702f",
         "reroute": "#262626", **{k: "#4a7a3f" for k in soundnumbers.TYPES}}
CATEGORY_HEADS = ["#3f6fa8", "#8a5a3f", "#3f7f8a", "#6a5a9a", "#8a3f6f"]     # one per soundfx.CATEGORIES, in order
BASICS = ["ext", "split", "merge", "mix", "reroute", "frame"]
US = 1_000_000


def head_color(node):
    if node["type"] == "fx":
        for i, (_, kinds) in enumerate(soundfx.CATEGORIES):
            if node.get("effect") in kinds:
                return CATEGORY_HEADS[i % len(CATEGORY_HEADS)]
    return HEADS.get(node["type"], "#6c696f")


def value_text(p, v):
    if p.get("choices"):
        i = int(round(v))
        return p["choices"][i] if 0 <= i < len(p["choices"]) else str(i)
    if p.get("free"):
        return f"{v:.6g}"
    span = p["max"] - p["min"]
    digits = 0 if span >= 1000 and abs(v) >= 100 else 1 if span >= 50 else 2
    return f"{v:.{digits}f}" + (f" {p['unit']}" if p["unit"] else "")


def fraction(p, v):
    lo, hi = p["min"], p["max"]
    if p.get("log") and lo > 0:
        return min(1.0, max(0.0, math.log(max(v, lo) / lo) / math.log(hi / lo)))
    return min(1.0, max(0.0, (v - lo) / (hi - lo)))


def at_fraction(p, f):
    lo, hi = p["min"], p["max"]
    f = min(1.0, max(0.0, f))
    if p.get("log") and lo > 0:
        return lo * (hi / lo) ** f
    return lo + (hi - lo) * f


class Row:
    """A line of a node's body that shows a value: its parameter spec, and where it is."""

    def __init__(self, name, spec, rect):
        self.name, self.spec, self.rect = name, spec, rect
        self.value, self.text, self.mark = 0.0, "", ""
        self.own = 0.0                      # the node's own number, where value is what it follows (dragged and typed)
        self.dot = None                     # where a number can be wired into it (item coordinates)
        self.wired = False


class NodeItem(QGraphicsItem):
    def __init__(self, editor, nid, node):
        super().__init__()
        self.editor, self.nid, self.node = editor, nid, node
        self.kind = node["type"]
        self.spec = soundfx.EFFECTS.get(node.get("effect")) if self.kind == "fx" else None
        self.visual = self.proxy = None
        self.result = ""
        self.selected_look = False
        self.setZValue(2)
        self.setPos(node.get("x", 0.0), node.get("y", 0.0))
        self.layout()

    def layout(self):
        node = self.node
        ins, outs = soundnodes.inputs(node), soundnodes.outputs(node)
        if self.kind == "reroute":
            self.w, self.h = 24.0, 24.0
            self.in_at, self.out_at, self.rows = [QPointF(0, 12)], [QPointF(24, 12)], []
            return
        visual = (self.spec or {}).get("visual")
        self.w = float(node.get("w") or (WIDE if visual else WIDTH))
        y = HEAD + 4
        self.out_at, self.in_at, self.rows = [], [], []
        for _ in outs:
            self.out_at.append(QPointF(self.w, y + ROW / 2))
            y += ROW
        for _ in ins:
            self.in_at.append(QPointF(0, y + ROW / 2))
            y += ROW
        self.ghost_at = None
        if self.kind == "mix" and len(ins) < soundnodes.MIX_MAX:
            self.ghost_at = QPointF(0, y + ROW / 2)
            y += ROW
        if visual:
            h = VISUAL_H[visual]
            cls = Dynamics if visual == "dynamics" else Spectrum if visual == "spectrum" else Response
            self.visual = cls(h) if cls is Spectrum else cls(node["effect"], h)
            self.visual.setFixedSize(int(self.w - 8), h)
            if cls is Response:
                self.visual.band = self.editor.bands.get(self.nid, 1)
                self.visual.bandPicked.connect(lambda i: self.editor.pick_band(self.nid, i))
            if cls is not Spectrum:
                self.visual.live.connect(lambda values: self.editor.live_params(self.nid, values))
                self.visual.done.connect(lambda values: self.editor.write_params(self.nid, values))
            self.proxy = QGraphicsProxyWidget(self)
            self.proxy.setWidget(self.visual)
            self.proxy.setPos(4, y)
            y += h + 4
        specs = []
        if self.kind == "ext":
            specs.append(("channel", None))
        if self.kind == "global":
            specs.append(("rack", None))
        elif self.spec or self.kind in soundnumbers.TYPES:
            if visual == "eq":
                specs.append(("band", None))
            specs += [(p["name"], p) for p in self.editor.shown_params(self.nid, node)]
        if self.kind == "mix":
            specs += [(f"g{i + 1}", soundfx.P(f"g{i + 1}", f"音量 {i + 1}", -60.0, 12.0, 0.0, "dB"))
                      for i in range(len(ins))]
        wires = self.editor.wired_into(self.nid)
        wireable = {p["name"] for p in soundnodes.wire_specs(node)}
        for name, spec in specs:
            row = Row(name, spec, QRectF(6, y + 1, self.w - 12, ROW - 2))
            if name in wireable:
                row.dot, row.wired = QPointF(0, y + ROW / 2), name in wires
            self.rows.append(row)
            y += ROW
        self.h = y + 5

    def boundingRect(self):
        return QRectF(-SOCKET_R - 2, -2, self.w + 2 * SOCKET_R + 4, self.h + 4)

    def dot_of(self, socket):
        """Where the number input socket ("param:<name>") is, or None while its row is not shown."""
        name = soundnodes.param_of(socket)
        return next((r.dot for r in self.rows if r.name == name and r.dot is not None), None)

    def socket_pos(self, is_input, i):
        if is_input and soundnodes.is_param(i):
            return self.pos() + (self.dot_of(i) or QPointF(0, HEAD / 2))
        at = self.in_at if is_input else self.out_at
        if is_input and i == len(at) and getattr(self, "ghost_at", None) is not None:
            return self.pos() + self.ghost_at
        return self.pos() + at[i]

    def show_values(self):
        """Bring the rows and the picture up to the node's values now."""
        node, t = self.node, self.editor.time()
        names = self.editor.names() if node.get("expr") else None
        given = {}                              # what is wired into it
        if any(r.wired for r in self.rows):
            given = self.editor.numbers().into(self.nid, soundnodes.wire_specs(node))
        for row in self.rows:
            if row.name == "rack":              # (全局參數: which one, and what it reads)
                source = (node.get("expr") or {}).get("value")
                got = soundfx.followed(node, "value", 0.0, t, names)
                row.text = f"{sound_follow.said(source)}　{got:.4g}" if source else "（沒有選）"
            elif row.name == "channel":
                row.text = self.editor.channel_name(node.get("channel"))
            elif row.name == "band":
                row.text = str(self.editor.bands.get(self.nid, 1))
            else:
                held = (node.get("params") or {}).get(row.name, row.spec["default"])
                row.value = row.own = curves.value(held, t)
                if (node.get("expr") or {}).get(row.name):            # (it follows a global parameter: what it sounds as)
                    row.value = soundfx.followed(node, row.name, float(row.own), t, names)
                row.value = given.get(row.name, row.value)
                row.text = value_text(row.spec, row.value)
                row.mark = ("◆ " if edit.key_at(held, t) is not None else "◈ ") if curves.is_animated(held) else ""
                if (node.get("expr") or {}).get(row.name):            # (it follows a global parameter)
                    row.mark = "= " + row.mark
                if row.wired:
                    row.mark = ""
        if self.kind in soundnumbers.TYPES:
            got = self.editor.numbers().of(self.nid)
            self.result = "" if got is None or self.kind in ("value", "global") else f"{got:.4g}"
        if self.visual is not None and not isinstance(self.visual, Spectrum):
            self.visual.set_values(dict(soundfx.values(node, t, names), **given))
        self.update()

    def paint(self, p, _option, _widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        outline = QPen(QColor("#ffffff") if self.selected_look else QColor("#000000"), 1.5 if self.selected_look else 1)
        muted = bool(self.node.get("mute"))
        if self.kind == "reroute":
            p.setPen(outline)
            p.setBrush(QColor(SOCKET["stereo"]))
            p.drawEllipse(QPointF(12, 12), 7, 7)
            return
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(26, 26, 26, 150 if muted else 245))
        p.drawRoundedRect(QRectF(0, 0, self.w, self.h), 4, 4)
        head = QPainterPath()
        head.addRoundedRect(QRectF(0, 0, self.w, HEAD + 4), 4, 4)
        p.save()
        p.setClipRect(QRectF(0, 0, self.w, HEAD))
        colour = QColor(head_color(self.node))
        if muted:
            colour.setAlpha(90)
        p.fillPath(head, colour)
        p.restore()
        p.setPen(QColor("#ffffff" if not muted else "#8e8e94"))
        f = p.font()
        f.setPixelSize(12)
        p.setFont(f)
        p.drawText(QRectF(8, 0, self.w - 16, HEAD), Qt.AlignVCenter | Qt.AlignLeft,
                   soundnodes.title(self.node) + ("（停用）" if muted else ""))
        f.setPixelSize(11)
        p.setFont(f)
        p.setPen(QColor("#dddddd"))
        for (label, _), at in zip(soundnodes.outputs(self.node), self.out_at):
            if self.result:                     # (a number node: what it gives, by its output)
                label = f"{label}　{self.result}"
            p.drawText(QRectF(8, at.y() - ROW / 2, self.w - 18, ROW), Qt.AlignVCenter | Qt.AlignRight, label)
        for (label, _), at in zip(soundnodes.inputs(self.node), self.in_at):
            p.drawText(QRectF(11, at.y() - ROW / 2, self.w - 18, ROW), Qt.AlignVCenter | Qt.AlignLeft, label)
        for row in self.rows:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#2a2a2e"))
            p.drawRect(row.rect)
            if row.spec is not None and not row.spec.get("choices") and not row.spec.get("free"):
                p.setBrush(QColor("#45454e"))
                p.drawRect(QRectF(row.rect.x(), row.rect.y(), row.rect.width() * fraction(row.spec, row.value),
                                  row.rect.height()))
            label = {"channel": "來源", "band": "頻段", "rack": "參數"}.get(row.name) or row.spec["label"]
            inner = row.rect.adjusted(5, 0, -5, 0)
            p.setPen(QColor("#e0c060") if row.mark else QColor("#aaaaaa"))
            p.drawText(inner, Qt.AlignVCenter | Qt.AlignLeft, row.mark + label)
            p.setPen(QColor("#ffffff"))
            p.drawText(inner, Qt.AlignVCenter | Qt.AlignRight, row.text)
        p.setPen(outline)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0, 0, self.w, self.h), 4, 4)
        p.setPen(QPen(QColor(0, 0, 0, 160), 1))
        for row in self.rows:
            if row.dot is not None:
                p.setBrush(QColor(SOCKET["num"]))
                p.drawEllipse(row.dot, SOCKET_R - 1.5, SOCKET_R - 1.5)
        for (_, kind), at in zip(soundnodes.inputs(self.node), self.in_at):
            p.setBrush(QColor(SOCKET[kind]))
            p.drawEllipse(at, SOCKET_R, SOCKET_R)
        for (_, kind), at in zip(soundnodes.outputs(self.node), self.out_at):
            p.setBrush(QColor(SOCKET[kind]))
            p.drawEllipse(at, SOCKET_R, SOCKET_R)
        if getattr(self, "ghost_at", None) is not None:
            p.setPen(QPen(QColor("#808080"), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(self.ghost_at, SOCKET_R, SOCKET_R)


class FrameItem(QGraphicsItem):
    CORNER = 16.0

    def __init__(self, nid, node):
        super().__init__()
        self.nid, self.node, self.kind = nid, node, "frame"
        self.w, self.h = float(node.get("w", 300)), float(node.get("h", 200))
        self.selected_look = False
        self.setZValue(-1)
        self.setPos(node.get("x", 0.0), node.get("y", 0.0))

    def boundingRect(self):
        return QRectF(-2, -2, self.w + 4, self.h + 4)

    def paint(self, p, _option, _widget=None):
        c = QColor(self.node.get("color", "#6c696f"))
        fill = QColor(c)
        fill.setAlpha(46)
        p.setBrush(fill)
        p.setPen(QPen(QColor("#ffffff") if self.selected_look else c, 1.5))
        p.drawRoundedRect(QRectF(0, 0, self.w, self.h), 6, 6)
        f = p.font()
        f.setPixelSize(14)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(10, 2, self.w - 20, HEAD), Qt.AlignVCenter | Qt.AlignLeft, self.node.get("name", ""))
        p.setPen(QPen(c, 2))
        for k in (5, 10):
            p.drawLine(QPointF(self.w - k, self.h - 3), QPointF(self.w - 3, self.h - k))


class GraphView(QGraphicsView):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.scene_ = QGraphicsScene(self)
        self.scene_.setSceneRect(-20000, -20000, 40000, 40000)
        self.setScene(self.scene_)
        self.setBackgroundBrush(QColor("#080808"))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.drag = None                    # {"mode": ..., ...}
        self.nodes = {}                     # nid -> NodeItem / FrameItem
        self.links = {}                     # (from, output, to, input) -> Link

    def drawBackground(self, p, rect):
        super().drawBackground(p, rect)
        if self.transform().m11() < 0.35:
            return
        p.setPen(QPen(QColor(255, 255, 255, 22), 2))
        x0, y0 = math.floor(rect.left() / GRID) * GRID, math.floor(rect.top() / GRID) * GRID
        points = [QPointF(x0 + i * GRID, y0 + j * GRID) for i in range(int(rect.width() / GRID) + 2)
                  for j in range(int(rect.height() / GRID) + 2)]
        p.drawPoints(points)

    # -- building --------------------------------------------------------------------------------
    def build(self, graph):
        self.drag = None
        self.scene_.clear()
        self.nodes, self.links = {}, {}
        for nid, node in graph["nodes"].items():
            item = FrameItem(nid, node) if node["type"] == "frame" else NodeItem(self.editor, nid, node)
            item.selected_look = nid in self.editor.selected
            self.scene_.addItem(item)
            self.nodes[nid] = item
        for l in graph["links"]:
            if l[0] in self.nodes and l[2] in self.nodes:
                link = Link(LINK_W * 0.7)
                self.scene_.addItem(link)
                self.links[tuple(l)] = link
        self.route()

    def route(self):
        for (src, out, dst, socket), link in self.links.items():
            a, b = self.nodes[src], self.nodes[dst]
            number = soundnodes.is_param(socket)
            if out < len(a.out_at) and (b.dot_of(socket) is not None if number else socket < len(b.in_at)):
                kind = soundnodes.outputs(a.node)[out][1]
                link.style(SOCKET[kind], SOCKET["num" if number else soundnodes.inputs(b.node)[socket][1]])
                link.route(a.socket_pos(False, out), b.socket_pos(True, socket))

    def set_selected(self, ids):
        self.editor.selected = set(ids)
        for nid, item in self.nodes.items():
            item.selected_look = nid in self.editor.selected
            item.update()

    # -- finding -----------------------------------------------------------------------------------
    def zoom(self):
        return self.transform().m11()

    def socket_near(self, pos, want=None, radius=HIT_R + 2):
        """(nid, is input, index) of the socket nearest the scene point pos, or None."""
        best = None
        for nid, item in self.nodes.items():
            if item.kind == "frame":
                continue
            ins = len(item.in_at) + (1 if getattr(item, "ghost_at", None) is not None else 0)
            for is_input, count in ((True, ins), (False, len(item.out_at))):
                if want is not None and is_input != want:
                    continue
                for i in range(count):
                    d = (item.socket_pos(is_input, i) - pos)
                    d = math.hypot(d.x(), d.y())
                    if d <= radius and (best is None or d < best[0]):
                        best = (d, nid, is_input, i)
            if want is not False:
                for row in getattr(item, "rows", ()):
                    if row.dot is not None:
                        d = item.pos() + row.dot - pos
                        d = math.hypot(d.x(), d.y())
                        if d <= min(radius, SOCKET_R + 4) and (best is None or d < best[0]):
                            best = (d, nid, True, soundnodes.PARAM + row.name)
        return best[1:] if best else None

    def node_at(self, pos, frames=False):
        found = [i for i in self.nodes.values() if (i.kind == "frame") == frames
                 and QRectF(i.pos().x(), i.pos().y(), i.w, i.h).contains(pos)]
        return found[-1] if found else None

    def row_at(self, item, pos):
        local = pos - item.pos()
        return next((r for r in getattr(item, "rows", ()) if r.rect.contains(local)), None)

    def link_hit(self, pos, width=10.0, skip=()):
        stroker = QPainterPathStroker()
        stroker.setWidth(width / max(self.zoom(), 0.1))
        for key, link in self.links.items():
            if key[0] not in skip and key[2] not in skip and stroker.createStroke(link.path()).contains(pos):
                return key
        return None

    def links_crossing(self, path):
        stroker = QPainterPathStroker()
        stroker.setWidth(2.0)
        stroke = stroker.createStroke(path)
        return [key for key, link in self.links.items() if link.path().intersects(stroke)]

    # -- the mouse ----------------------------------------------------------------------------------
    def _over_picture(self, view_pos):
        item = self.itemAt(view_pos)
        return isinstance(item, QGraphicsProxyWidget)

    def mousePressEvent(self, e):
        self.setFocus()
        pos = self.mapToScene(e.position().toPoint())
        if self.drag and self.drag["mode"] == "grab":
            self.finish_move(cancel=e.button() == Qt.RightButton)
            return
        if e.button() == Qt.MiddleButton:
            self.drag = {"mode": "pan", "at": e.position()}
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() == Qt.RightButton:
            mods = e.modifiers()
            if mods & (Qt.ControlModifier | Qt.ShiftModifier):
                path = QPainterPath(pos)
                line = QGraphicsPathItem(path)
                colour = "#e0605a" if mods & Qt.ControlModifier else "#5fbf6a"
                line.setPen(QPen(QColor(colour), 1.5 / self.zoom(), Qt.DashLine))
                line.setZValue(10)
                self.scene_.addItem(line)
                self.drag = {"mode": "cut" if mods & Qt.ControlModifier else "bend", "path": path, "line": line}
                return
            self.context(e, pos)
            return
        if e.button() != Qt.LeftButton:
            return
        socket = self.socket_near(pos)
        if socket:
            self.start_link(socket, pos)
            return
        if self._over_picture(e.position().toPoint()):
            super().mousePressEvent(e)                      # (the curve in a node: its own hands)
            self.drag = {"mode": "picture"}
            return
        item = self.node_at(pos)
        if item is not None:
            row = self.row_at(item, pos)
            if row is not None:
                self.press_row(item, row, pos, e)
                return
            self.start_move(item, pos, e.modifiers())
            return
        frame = self.node_at(pos, frames=True)
        if frame is not None:
            local = pos - frame.pos()
            if local.x() > frame.w - frame.CORNER and local.y() > frame.h - frame.CORNER:
                self.drag = {"mode": "size", "item": frame, "at": pos, "size": (frame.w, frame.h)}
                return
            if local.y() <= HEAD:
                self.start_move(frame, pos, e.modifiers())
                return
        add = bool(e.modifiers() & Qt.ShiftModifier)
        if not add:
            self.set_selected(())
        band = QGraphicsPathItem()
        band.setPen(QPen(QColor(255, 255, 255, 120), 1 / self.zoom(), Qt.DashLine))
        band.setBrush(QBrush(QColor(255, 255, 255, 20)))
        band.setZValue(10)
        self.scene_.addItem(band)
        self.drag = {"mode": "box", "from": pos, "band": band, "had": set(self.editor.selected)}

    def press_row(self, item, row, pos, e):
        if row.name == "channel":
            self.editor.channel_menu(item.nid, e.globalPosition().toPoint())
        elif row.name == "rack":
            self.editor.rack_menu(item.nid, e.globalPosition().toPoint())
        elif row.wired:                             # (the wire's: nothing to set here)
            self.start_move(item, pos, e.modifiers())
        elif row.name == "band":
            menu = Menu(self)
            for i in range(1, soundfx.EQ_BANDS + 1):
                menu.addAction(f"頻段 {i}", lambda i=i, nid=item.nid: self.editor.pick_band(nid, i))
            menu.exec(e.globalPosition().toPoint())
        elif row.spec.get("choices"):
            if row.spec["choices"] == ["關", "開"]:
                self.editor.write_params(item.nid, {row.name: 0 if row.own > 0.5 else 1})
                return
            menu = Menu(self)
            for i, label in enumerate(row.spec["choices"]):
                a = menu.addAction(label, lambda i=i, nid=item.nid, n=row.name: self.editor.write_params(nid, {n: i}))
                a.setCheckable(True)
                a.setChecked(i == int(round(row.own)))
            menu.exec(e.globalPosition().toPoint())
        else:
            self.set_selected({item.nid})
            self.drag = {"mode": "value", "item": item, "row": row, "x": e.position().x(), "value": row.own,
                         "now": None}

    def start_link(self, socket, pos):
        nid, is_input, i = socket
        graph = self.editor.graph()
        if is_input:
            held = soundnodes.link_into(graph, nid, i)
            if held is not None:                            # pick the wire up by this end
                self.links[tuple(held)].setVisible(False)
                self.begin_wire((held[0], False, held[1]), pos, held)
                return
        self.begin_wire(socket, pos, None)

    def begin_wire(self, start, pos, held):
        wire = Link(LINK_W)
        wire.setZValue(9)
        self.scene_.addItem(wire)
        self.drag = {"mode": "wire", "start": start, "wire": wire, "held": held, "to": None, "end": pos}
        self.move_wire(pos)

    def move_wire(self, pos):
        d = self.drag
        nid, is_input, i = d["start"]
        item = self.nodes[nid]
        anchor = item.socket_pos(is_input, i)
        graph = self.editor.graph()
        d["to"], end = None, pos
        near = self.socket_near(pos, want=not is_input, radius=SNAP_R / self.zoom())
        if not near and not is_input and self.nodes[nid].node["type"] in soundnumbers.TYPES:
            over = self.node_at(pos)            # (a number let go on a row, not just on its dot)
            row = self.row_at(over, pos) if over is not None else None
            if row is not None and row.dot is not None:
                near = (over.nid, True, soundnodes.PARAM + row.name)
        if near:
            other, _, j = near
            link = (other, j, nid, i) if is_input else (nid, i, other, j)
            if soundnodes.can_link(graph, *link):
                d["to"], end = link, self.nodes[other].socket_pos(not is_input, j)
        if is_input and soundnodes.is_param(i):
            colour = SOCKET["num"]
        else:
            kind = (soundnodes.inputs(item.node) if is_input else soundnodes.outputs(item.node))
            colour = SOCKET[kind[i][1]] if i < len(kind) else SOCKET["stereo"]
        d["wire"].style(colour, colour)
        d["wire"].route(end, anchor) if is_input else d["wire"].route(anchor, end)
        d["end"] = pos

    def start_move(self, item, pos, mods):
        if mods & Qt.ShiftModifier:
            self.set_selected(self.editor.selected ^ {item.nid})
            if item.nid not in self.editor.selected:
                return
        elif item.nid not in self.editor.selected:
            self.set_selected({item.nid})
        self.begin_move(pos, "move")

    def begin_move(self, pos, mode):
        ids = set(self.editor.selected)
        for nid in list(ids):                               # a frame takes what is in it along
            frame = self.nodes.get(nid)
            if frame is not None and frame.kind == "frame":
                box = QRectF(frame.pos().x(), frame.pos().y(), frame.w, frame.h)
                ids |= {k for k, i in self.nodes.items() if k != nid and box.contains(i.pos() + QPointF(i.w / 2, 12))}
        start = {k: QPointF(self.nodes[k].pos()) for k in ids if k in self.nodes}
        self.drag = {"mode": mode, "from": pos, "start": start, "moved": False, "over": None}

    def move_nodes_to(self, pos):
        d = self.drag
        delta = pos - d["from"]
        if not d["moved"] and math.hypot(delta.x(), delta.y()) * self.zoom() < 4:
            return
        d["moved"] = True
        for nid, was in d["start"].items():
            at = was + delta
            self.nodes[nid].setPos(round(at.x() / GRID) * GRID, round(at.y() / GRID) * GRID)
        self.route()
        if d["over"] in self.links:
            self.links[d["over"]].normal()
        d["over"] = None
        if len(d["start"]) == 1:                            # one node over a wire: it would go into it
            nid = next(iter(d["start"]))
            item = self.nodes[nid]
            graph = self.editor.graph()
            if item.kind != "frame" and soundnodes.inputs(item.node) and soundnodes.outputs(item.node) \
                    and not any(nid in (l[0], l[2]) for l in graph["links"]):
                d["over"] = self.link_hit(item.pos() + QPointF(item.w / 2, min(item.h / 2, 30)), 24.0, skip=(nid,))
                if d["over"] and soundnodes.is_param(d["over"][3]):     # (nothing goes into a number's wire)
                    d["over"] = None
                if d["over"]:
                    self.links[d["over"]].light(LINK_W)

    def finish_move(self, cancel=False):
        d, self.drag = self.drag, None
        if cancel or not d["moved"]:
            for nid, was in d["start"].items():
                if nid in self.nodes:
                    self.nodes[nid].setPos(was)
            self.route()
            if d.get("created"):                            # (Shift+D cancelled: the copies stay put)
                self.editor.rebuild()
            return
        positions = {k: (self.nodes[k].pos().x(), self.nodes[k].pos().y()) for k in d["start"]}
        on_link = (next(iter(d["start"])), list(d["over"])) if d["over"] else None
        self.editor.edit("移動節點", soundedit.move_nodes, positions, on_link)

    def mouseMoveEvent(self, e):
        pos = self.mapToScene(e.position().toPoint())
        d = self.drag
        if d is None:
            super().mouseMoveEvent(e)
            return
        mode = d["mode"]
        if mode == "pan":
            delta = (e.position() - d["at"]) / self.zoom()
            d["at"] = e.position()
            self.translate(delta.x(), delta.y())
        elif mode == "picture":
            super().mouseMoveEvent(e)
        elif mode == "wire":
            self.move_wire(pos)
        elif mode in ("move", "grab"):
            self.move_nodes_to(pos)
        elif mode == "box":
            rect = QRectF(d["from"], pos).normalized()
            path = QPainterPath()
            path.addRect(rect)
            d["band"].setPath(path)
            inside = {k for k, i in self.nodes.items()
                      if i.kind != "frame" and rect.intersects(QRectF(i.pos().x(), i.pos().y(), i.w, i.h))}
            self.set_selected(inside | (d["had"] if e.modifiers() & Qt.ShiftModifier else set()))
        elif mode == "size":
            item, delta = d["item"], pos - d["at"]
            item.prepareGeometryChange()
            item.w, item.h = max(MIN_W, d["size"][0] + delta.x()), max(60.0, d["size"][1] + delta.y())
            item.update()
        elif mode == "value":
            dx = e.position().x() - d["x"]
            if d["now"] is None and abs(dx) < 3:
                return
            row = d["row"]
            fine = 0.1 if e.modifiers() & Qt.ShiftModifier else 1.0
            if row.spec.get("free"):                # (a step a pixel; bigger numbers go by their size)
                value = round(d["value"] + dx * fine * max(0.01, abs(d["value"]) / 200.0), 4)
            else:
                value = at_fraction(row.spec, fraction(row.spec, d["value"]) + dx / 300.0 * fine)
            d["now"] = value
            row.value = row.own = value
            row.text = value_text(row.spec, value)
            d["item"].update()
            self.editor.live_params(d["item"].nid, {row.name: value})
        elif mode in ("cut", "bend"):
            d["path"].lineTo(pos)
            d["line"].setPath(d["path"])

    def mouseReleaseEvent(self, e):
        pos = self.mapToScene(e.position().toPoint())
        d = self.drag
        if d is None:
            super().mouseReleaseEvent(e)
            return
        mode = d["mode"]
        if mode == "grab":
            return
        if mode == "move":
            self.finish_move()
            return
        self.drag = None
        if mode == "pan":
            self.unsetCursor()
        elif mode == "picture":
            super().mouseReleaseEvent(e)
        elif mode == "box":
            self.scene_.removeItem(d["band"])
        elif mode == "wire":
            self.drop_wire(d, pos, e.globalPosition().toPoint())
        elif mode == "size":
            self.editor.edit("調整框架大小", soundedit.set_node, d["item"].nid, {"w": d["item"].w, "h": d["item"].h})
        elif mode == "value":
            if d["now"] is not None:
                self.editor.write_params(d["item"].nid, {d["row"].name: d["now"]})
        elif mode in ("cut", "bend"):
            self.scene_.removeItem(d["line"])
            crossed = self.links_crossing(d["path"])
            if mode == "bend":                          # (a reroute takes sound only)
                crossed = [k for k in crossed if not soundnodes.is_param(k[3])]
            if crossed and mode == "cut":
                self.editor.edit("切斷連線", soundedit.disconnect_nodes, [list(k) for k in crossed])
            elif crossed:
                path = d["path"]
                link = self.links[crossed[0]].path()
                at = next((path.pointAtPercent(i / 60) for i in range(61)
                           if link.intersects(QRectF(path.pointAtPercent(i / 60) - QPointF(6, 6),
                                                     path.pointAtPercent(i / 60) + QPointF(6, 6)))), pos)
                self.editor.edit("加繞線", soundedit.reroute_link, list(crossed[0]), at.x() - 12, at.y() - 12)

    def drop_wire(self, d, pos, global_pos):
        self.scene_.removeItem(d["wire"])
        held = d["held"]
        if d["to"] is not None:
            link = list(d["to"])
            if held is not None and link != held:
                def rewire(level, target, eid):
                    soundedit.disconnect_nodes(level, target, eid, [held])
                    soundedit.connect_nodes(level, target, eid, *link)
                self.editor.edit("改接", rewire)
            elif held is None:
                self.editor.edit("連接節點", soundedit.connect_nodes, *link)
            else:
                self.editor.rebuild()
            return
        if held is not None:                                # let go over nothing: unwired
            self.editor.edit("拆掉連線", soundedit.disconnect_nodes, [held])
            return
        nid, is_input, i = d["start"]
        if self.node_at(pos) is None:
            if is_input:
                self.editor.add_menu(global_pos, pos, into=(nid, i))
            else:
                self.editor.add_menu(global_pos, pos, feed=(nid, i))

    def mouseDoubleClickEvent(self, e):
        pos = self.mapToScene(e.position().toPoint())
        if e.button() == Qt.LeftButton and self._over_picture(e.position().toPoint()):
            super().mouseDoubleClickEvent(e)
            return
        item = self.node_at(pos)
        if item is not None and e.button() == Qt.LeftButton:
            row = self.row_at(item, pos)
            if row is not None and row.spec is not None and not row.spec.get("choices") and not row.wired:
                self.drag = None
                self.editor.type_value(item.nid, row)
                return
        frame = self.node_at(pos, frames=True)
        if item is None and frame is not None and (pos - frame.pos()).y() <= HEAD:
            self.drag = None
            self.editor.rename_frame(frame.nid)

    def context(self, e, pos):
        at = e.globalPosition().toPoint()
        item = self.node_at(pos)
        if item is not None:
            row = self.row_at(item, pos)
            if row is not None and row.name == "rack":
                self.editor.rack_menu(item.nid, at)
                return
            if row is not None and row.spec is not None:
                self.editor.row_menu(item.nid, row, at)
                return
            if item.nid not in self.editor.selected:
                self.set_selected({item.nid})
            self.editor.node_menu(at)
            return
        frame = self.node_at(pos, frames=True)
        if frame is not None and (pos - frame.pos()).y() <= HEAD:
            self.set_selected({frame.nid})
            self.editor.node_menu(at)
            return
        link = self.link_hit(pos)
        if link and soundnodes.is_param(link[3]):
            link = None
        self.editor.add_menu(at, pos, on_link=list(link) if link else None)

    def contextMenuEvent(self, e):
        e.accept()                                          # (the right button is handled when pressed)

    def wheelEvent(self, e):
        k = 1.15 ** (e.angleDelta().y() / 120)
        now = self.zoom()
        k = max(ZOOM_MIN, min(ZOOM_MAX, now * k)) / now
        before = self.mapToScene(e.position().toPoint())
        self.scale(k, k)
        moved = self.mapToScene(e.position().toPoint()) - before
        self.translate(moved.x(), moved.y())

    def show_all(self):
        if not self.nodes:
            return
        box = QRectF()
        for i in self.nodes.values():
            box = box.united(QRectF(i.pos().x(), i.pos().y(), i.w, i.h))
        box.adjust(-40, -40, 40, 40)
        vw, vh = max(50, self.viewport().width()), max(50, self.viewport().height())
        k = max(ZOOM_MIN, min(1.0, vw / box.width(), vh / box.height()))
        self.resetTransform()
        self.scale(k, k)
        self.centerOn(box.center())

    # -- keys --------------------------------------------------------------------------------------
    KEYS = {(Qt.Key_A, "shift"), (Qt.Key_A, ""), (Qt.Key_X, ""), (Qt.Key_Delete, ""), (Qt.Key_X, "ctrl"),
            (Qt.Key_M, ""), (Qt.Key_D, "shift"), (Qt.Key_C, "ctrl"), (Qt.Key_V, "ctrl"), (Qt.Key_G, ""),
            (Qt.Key_J, "ctrl"), (Qt.Key_Home, ""), (Qt.Key_Escape, ""), (Qt.Key_Backspace, "")}

    def _which(self, e):
        mods = e.modifiers()
        return e.key(), "ctrl" if mods & Qt.ControlModifier else "shift" if mods & Qt.ShiftModifier else ""

    def event(self, e):
        if e.type() == QEvent.ShortcutOverride and self._which(e) in self.KEYS:
            e.accept()                                      # (here, not the window's: Delete is not "delete the clip")
            return True
        return super().event(e)

    def keyPressEvent(self, e):
        which = self._which(e)
        if which not in self.KEYS:
            e.ignore()
            return
        ed = self.editor
        cursor = self.mapToScene(self.mapFromGlobal(QCursor.pos()))
        if which == (Qt.Key_Escape, ""):
            if self.drag and self.drag["mode"] in ("grab", "move"):
                self.finish_move(cancel=True)
            elif self.drag:
                ed.rebuild()
            else:
                self.set_selected(())
        elif which == (Qt.Key_A, "shift"):
            ed.add_menu(QCursor.pos(), cursor)
        elif which == (Qt.Key_A, ""):
            self.set_selected(set(self.nodes))
        elif which in ((Qt.Key_X, ""), (Qt.Key_Delete, ""), (Qt.Key_Backspace, "")):
            ed.delete_selected()
        elif which == (Qt.Key_X, "ctrl"):
            ed.delete_selected(keep_links=True)
        elif which == (Qt.Key_M, ""):
            ed.mute_selected()
        elif which == (Qt.Key_D, "shift"):
            ed.duplicate(cursor)
        elif which == (Qt.Key_C, "ctrl"):
            ed.copy()
        elif which == (Qt.Key_V, "ctrl"):
            ed.paste(cursor)
        elif which == (Qt.Key_G, "") and ed.selected and self.drag is None:
            self.begin_move(cursor, "grab")
        elif which == (Qt.Key_J, "ctrl"):
            ed.frame_selected()
        elif which == (Qt.Key_Home, ""):
            self.show_all()


class SoundNodeEditor(QWidget):
    clipboard = None                        # copied nodes, shared by every editor

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.target = self.eid = None
        self.selected = set()
        self.bands = {}                     # node id -> the EQ band shown
        self.views = {}                     # effect id -> (transform, centre): where each was looked at
        self._graph = None
        self._shape = None
        self._numbers = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QWidget()
        bar.setObjectName("bar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 3, 6, 3)
        self.title = QLabel("")
        self.title.setObjectName("crumb")
        row.addWidget(self.title, 1)
        self.view = GraphView(self)
        for text, tip, fn in (("＋ 節點", "新增節點（Shift+A、右鍵）", self.add_from_button),
                              ("全部顯示", "Home", self.view.show_all),
                              ("放大", "讓節點圖占滿整個聲音頁 / 縮回右邊", lambda: page.enlarge_graph()),
                              ("✕", "關閉節點圖", lambda: page.close_graph())):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _c=False, fn=fn: fn())
            row.addWidget(b)
            if text == "放大":
                self.big_btn = b
        lay.addWidget(bar)
        lay.addWidget(self.view, 1)

    # -- what is shown -----------------------------------------------------------------------------------
    def open(self, target, effect_id):
        self.keep_view()
        self.target, self.eid = target, effect_id
        self.selected = set()
        self._shape = None
        self.refresh()
        kept = self.views.get(effect_id)
        if kept:
            self.view.setTransform(kept[0])
            self.view.centerOn(kept[1])
        else:
            self.view.show_all()

    def keep_view(self):
        if self.eid:
            self.views[self.eid] = (self.view.transform(),
                                    self.view.mapToScene(self.view.viewport().rect().center()))

    def graph(self):
        return soundedit.graph(self.page.level(), self.target, self.eid)

    def time(self):
        if self.target and self.target[0] == "clip":
            return int(self.page.win.clip_time(self.target[1]))
        return self.page.level_time()

    def channel_name(self, channel_id):
        if not channel_id:
            return "（沒有選）"
        level = self.page.level()
        found = next((h for h in list(level["tracks"]) + soundedit.buses(level) if h["id"] == channel_id), None)
        return (found.get("name") or channel_id) if found else "（已經不在）"

    def wired_into(self, nid):
        """The names of node nid's parameters a number is wired into."""
        return {soundnodes.param_of(l[3]) for l in self.graph()["links"] if l[2] == nid and soundnodes.is_param(l[3])}

    def shown_params(self, nid, node):
        """The specs of the parameters an effect or number node shows rows for: those that count as its
        values are (of an equaliser, the band picked) - and every wired one."""
        if node["type"] == "fx":
            specs = (soundfx.EFFECTS.get(node.get("effect")) or {}).get("params", [])
        else:
            specs = soundnumbers.SPECS.get(node["type"], [])
        if not specs:
            return []
        t = self.time()
        values = soundfx.values(node, t) if node["type"] == "fx" else soundnumbers.own_values(node, t)
        wires = self.wired_into(nid)
        band = self.bands.get(nid, 1)
        return [p for p in specs if p["name"] in wires or p.get("band") in (None, band)
                and ("when" not in p or p["when"](values))]

    def numbers(self):
        """The graph's numbers at the playhead (worked out once a refresh)."""
        if self._numbers is None:
            self._numbers = soundnodes.numbers(self.graph(), self.time(), self.names)
        return self._numbers

    def _signature(self, graph):
        out = []
        for nid, n in graph["nodes"].items():
            names = tuple(p["name"] for p in self.shown_params(nid, n)) if n["type"] != "mix" else ()
            out.append((nid, n["type"], n.get("effect"), n.get("x"), n.get("y"), n.get("w"), n.get("h"),
                        n.get("name"), n.get("color"), n.get("channel"), n.get("inputs"), n.get("mute"), names))
        return tuple(out), tuple(tuple(l) for l in graph["links"])

    def refresh(self):
        """After an edit, an undo or a move of the playhead. False: the graph is gone."""
        if self.eid is None:
            return False
        try:
            graph = self.graph()
        except (edit.EditError, KeyError):
            return False
        self.title.setText(f"{self.page.target_name(self.target)}　▸　聲音節點效果")
        if self.view.drag is not None:                      # (not under the hand)
            return True
        self._numbers = None
        shape = self._signature(graph)
        if shape != self._shape or graph is not self._graph:
            self.selected &= set(graph["nodes"])
            self._shape, self._graph = shape, graph
            self.view.build(graph)
        for item in self.view.nodes.values():
            if item.kind != "frame":
                item.show_values()
        return True

    def rebuild(self):
        """Draw the graph again, whatever was being done to it."""
        self.view.drag = None
        self._shape = None
        self.refresh()

    def drawn(self):
        """{meter name: widget} of the pictures in the nodes."""
        return {f"{self.eid}/{nid}": item.visual for nid, item in self.view.nodes.items()
                if getattr(item, "visual", None) is not None}

    def names(self):
        """What the global parameters read at the playhead."""
        return rack.values(self.page.win.view(), self.page.level_time())

    # -- edits ---------------------------------------------------------------------------------------------
    def edit(self, label, fn, *args, merge=None):
        self.view.drag = None
        self._shape = None                                  # (what was moved by hand goes back if refused)
        result = self.page.win.apply(label, fn, self.target, self.eid, *args, merge=merge)
        self.refresh()
        return result

    def live_params(self, nid, values):
        self.page.live_target(self.target, soundedit.set_params, f"{self.eid}/{nid}", values, self.time())

    def write_params(self, nid, values):
        self.page.win.apply("調整聲音節點", soundedit.set_params, self.target, f"{self.eid}/{nid}", values, self.time(),
                            merge=("snode", self.eid, nid, tuple(sorted(values))))
        self.refresh()

    def pick_band(self, nid, band):
        from PySide6.QtCore import QTimer
        self.bands[nid] = band
        item = self.view.nodes.get(nid)
        if item is not None and isinstance(item.visual, Response):
            item.visual.band = band
        QTimer.singleShot(0, self.refresh)                  # (not while the curve that asked is being pressed)

    def type_value(self, nid, row):
        spec = row.spec
        value, ok = QInputDialog.getDouble(self, spec["label"], f"{spec['label']}（{spec['unit']}）" if spec["unit"]
                                           else spec["label"], row.own, spec["min"], spec["max"],
                                           4 if spec.get("free") else 2)
        if ok:
            self.write_params(nid, {row.name: value})

    def row_menu(self, nid, row, at):
        menu = Menu(self)
        address = f"{self.eid}/{nid}"
        if row.wired:
            wire = soundnodes.link_into(self.graph(), nid, soundnodes.PARAM + row.name)
            menu.addAction("拆掉連線", lambda: self.edit("拆掉連線", soundedit.disconnect_nodes, [wire]))
            menu.exec(at)
            return
        if not row.spec.get("choices"):
            held = (self.graph()["nodes"][nid].get("params") or {}).get(row.name)
            has = curves.is_animated(held) and edit.key_at(held, self.time()) is not None
            menu.addAction("移除這裡的關鍵幀" if has else "在播放頭加關鍵幀", lambda: (self.page.win.apply(
                "聲音參數關鍵幀", soundedit.toggle_key, self.target, address, row.name, self.time()), self.refresh()))
            menu.addAction("輸入數值…", lambda: self.type_value(nid, row))
            sound_follow.add_items(menu, self.page, self.target, address, row.spec, self.time(), self.refresh)
        menu.addAction("重設為預設值", lambda: (self.page.win.apply(
            "重設參數", soundedit.reset_param, self.target, address, row.name), self.refresh()))
        menu.exec(at)

    def rack_menu(self, nid, at):
        """Which global parameter a 全局參數 node reads."""
        menu = Menu(self)
        win, address = self.page.win, f"{self.eid}/{nid}"

        def put(source, label="全局參數節點"):
            win.apply_root(label, lambda root: soundedit.bind(root, win.container(root), self.target, address,
                                                              "value", source))
            self.refresh()

        for p in rack.params(win.proj):
            kind, name = rack.kind_of(p), p["name"]
            if kind in rack.NUMERIC:
                menu.addAction(name, lambda name=name: put(name))
            elif kind in rack.SIZES:
                parts = menu.addMenu(name)
                for i, axis in enumerate("XYZ"[:rack.SIZES[kind]]):
                    part = f"{name}[{i}]"
                    parts.addAction(f"{axis}　{part}", lambda part=part: put(part))

        def new():
            made = win.ask_rack_name()
            if made:
                def fn(root):
                    edit.add_rack_param(root, made, 0.0)
                    soundedit.bind(root, win.container(root), self.target, address, "value", made)
                win.apply_root("新增全局參數", fn)
                self.refresh()

        if menu.actions():
            menu.addSeparator()
        menu.addAction("新增全局參數…", new)
        menu.exec(at)

    def channel_menu(self, nid, at):
        menu = Menu(self)
        entries = soundedit.side_sources(self.page.level(), self.target)
        for ident, name in entries:
            menu.addAction(name, lambda ident=ident: self.edit("外部輸入來源", soundedit.set_node, nid,
                                                              {"channel": ident}))
        if not entries:
            menu.addAction("（沒有可以接的軌道或 bus）").setEnabled(False)
        menu.exec(at)

    def add_from_button(self):
        centre = self.view.mapToScene(self.view.viewport().rect().center())
        self.add_menu(QCursor.pos(), centre)

    def add_menu(self, global_pos, scene_pos, feed=None, into=None, on_link=None):
        menu = Menu(self)
        self.view.drag = None

        def pick(kind):
            x, y = scene_pos.x(), scene_pos.y() - HEAD / 2
            if into is not None:                            # (it feeds that input: it goes left of the point)
                x -= WIDE if (soundfx.EFFECTS.get(kind) or {}).get("visual") else WIDTH
            made = self.edit("新增節點", soundedit.add_node, kind, round(x / GRID) * GRID, round(y / GRID) * GRID,
                             feed, into, on_link)
            if made:
                self.view.set_selected({made})
        box = SearchBox(menu, pick, "搜尋節點…")
        groups = [("基本", BASICS)] + soundfx.CATEGORIES + [("數值", list(soundnumbers.TYPES))]
        number_wire = into is not None and soundnodes.is_param(into[1]) or \
            feed is not None and soundnodes.outputs(self.graph()["nodes"][feed[0]])[feed[1]][1] == "num"
        if number_wire:                                     # (only number nodes take or give a number by themselves)
            groups = groups[-1:]
        for title, kinds in groups:
            sub = menu.addMenu(title)
            box.groups.append(sub.menuAction())
            for kind in kinds:
                name = soundfx.EFFECTS[kind]["title"] if kind in soundfx.EFFECTS else soundnodes.TITLES[kind]
                sub.addAction(name, lambda kind=kind: pick(kind))
                words = soundnumbers.KEYWORDS.get(kind) or soundfx.KEYWORDS.get(kind, kind)
                box.add(title, name, kind, words + " " + name)
        if SoundNodeEditor.clipboard:
            sep = menu.addSeparator()
            box.groups.append(sep)
            box.groups.append(menu.addAction("貼上", lambda: self.paste(scene_pos)))
        box.reset(focus=True)
        menu.exec(global_pos)
        self.rebuild()                                      # (a wire let go for the menu is put away)

    def node_menu(self, at):
        menu = Menu(self)
        menu.addAction("複製一份（Shift+D）", lambda: self.duplicate(None))
        menu.addAction("拷貝（Ctrl+C）", self.copy)
        menu.addAction("停用 / 啟用（M）", self.mute_selected)
        menu.addAction("加框架（Ctrl+J）", self.frame_selected)
        menu.addSeparator()
        menu.addAction("刪除但保留連線（Ctrl+X）", lambda: self.delete_selected(True))
        menu.addAction("刪除（X）", self.delete_selected)
        menu.exec(at)

    def rename_frame(self, nid):
        item = self.view.nodes[nid]
        corner = self.view.mapFromScene(item.pos())
        from PySide6.QtCore import QRect
        name, ok = inplace.ask_name(self.view, item.node.get("name", ""), (self.view.viewport(), QRect(corner.x(), corner.y(), 200, 24)))
        if ok:
            self.edit("重新命名框架", soundedit.set_node, nid, {"name": name})

    def delete_selected(self, keep_links=False):
        if self.selected:
            self.edit("刪除節點", soundedit.remove_nodes, list(self.selected), keep_links)

    def mute_selected(self):
        nodes = self.graph()["nodes"]
        ids = [i for i in self.selected if i in nodes and nodes[i]["type"] not in soundnodes.FIXED + ("frame",)]
        if ids:
            on = not all(nodes[i].get("mute") for i in ids)
            self.edit("停用節點" if on else "啟用節點", soundedit.mute_nodes, ids, on)

    def copy(self):
        data = soundnodes.copy_nodes(self.graph(), list(self.selected))
        if data["nodes"]:
            SoundNodeEditor.clipboard = data

    def paste(self, at):
        data = SoundNodeEditor.clipboard
        if not data:
            return
        left = min(n["x"] for n in data["nodes"].values())
        top = min(n["y"] for n in data["nodes"].values())
        new = self.edit("貼上節點", soundedit.paste_nodes, data, at.x() - left, at.y() - top)
        if new:
            self.view.set_selected(new)

    def duplicate(self, grab_from):
        """Copies of what is selected; grab_from: they stick to the pointer until a click."""
        data = soundnodes.copy_nodes(self.graph(), list(self.selected))
        if not data["nodes"]:
            return
        new = self.edit("複製節點", soundedit.paste_nodes, data, 30.0, 30.0)
        if new:
            self.view.set_selected(new)
            if grab_from is not None:
                self.view.begin_move(grab_from, "grab")
                self.view.drag["created"] = True

    def frame_selected(self):
        items = [self.view.nodes[i] for i in self.selected if i in self.view.nodes
                 and self.view.nodes[i].kind != "frame"]
        if not items:
            return
        left = min(i.pos().x() for i in items) - 20
        top = min(i.pos().y() for i in items) - HEAD - 14
        right = max(i.pos().x() + i.w for i in items) + 20
        bottom = max(i.pos().y() + i.h for i in items) + 20

        def fn(level, target, eid):
            nid = soundedit.add_node(level, target, eid, "frame", left, top)
            soundedit.set_node(level, target, eid, nid, {"w": right - left, "h": bottom - top})
            return nid
        self.edit("加框架", fn)
