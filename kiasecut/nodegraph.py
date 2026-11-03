"""Node graphs: an effect (filter "nodes:graph", fx.GRAPH) whose picture is worked out by a graph of
nodes, as in Blender's compositor. The graph is e["graph"]:

    {"nodes": {id: {"type", "x", "y", "mute"?, ...}}, "links": [{"from": id, "to": id, "socket": s}]}

A filter node's parameters are in the effect's own e["params"] as "<node id>.<parameter>" (so they are
keyframed, edited and copied as an ordinary effect's are).

Node types: "params" (參數輸入, Blender's group input: the effect's own parameters, graph["exposed"], one output
socket each - a link from one into a parameter socket of a node (any kind of parameter) binds that parameter
to it; the value is e["params"]["expose.<name>"], shown in the 效果 panel as the effect's own), "input" (the picture the effect was given), "output" (the graph's result; one), "source"
(a picture, video, compound or track: "kind" says which, and where it sits on the clip is
e["sources"][node id], placed as a mask is) and "filter" ("ref": a filter, built-in or the user's -
every filter is a node; "builtin:nodes/..." are the ones made for graphs). A link goes into a socket
of the node it ends at: "src" (the main picture), an @input name of the filter, or "param:<name>" (a
colour or number parameter fed from the picture, as the effect's sources do: fx.py). Every socket
carries a picture (premultiplied RGBA, the size of the layer): colours, numbers and masks are
pictures too. Each filter node is drawn once (Engine.run_tex) into a texture of its own.
"""
import copy

from . import curves, fx

US = 1_000_000
INPUT, OUTPUT, SOURCE, FILTER, PARAMS, REROUTE, FRAME = "input", "output", "source", "filter", "params", "reroute", "frame"
SOURCE_KINDS = ("image", "video", "compound", "track", "shape")
SHAPES = (("rectangle", "矩形"), ("ellipse", "圓形"), ("rounded", "圓角矩形"), ("triangle", "三角形"),
          ("hexagon", "六邊形"), ("star", "星形"), ("heart", "愛心"))
PICTURE = "builtin:nodes/picture"
IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
PARAM = "param:"


class GraphError(Exception):
    pass


# -- the graph as data ----------------------------------------------------------------------------
def new_graph():
    """A graph of an Input going straight to an Output."""
    return {"nodes": {"input": {"type": INPUT, "x": -240.0, "y": 0.0},
                      "output": {"type": OUTPUT, "x": 240.0, "y": 0.0}},
            "links": [{"from": "input", "to": "output", "socket": "src"}]}


def new_effect(effect_id, graph=None):
    """A node-graph effect for a clip (edit.add_effect makes them from fx.GRAPH)."""
    e = fx.new_effect(fx.GRAPH, effect_id)
    if graph:
        e["graph"] = copy.deepcopy(graph)
        e["params"] = default_params(e["graph"])
    return e


def new_node_id(graph, base):
    n = 1
    while f"{base}{n}" in graph["nodes"]:
        n += 1
    return f"{base}{n}"


def add_node(graph, node, x=0.0, y=0.0, base=None):
    """Put node ({"type": ...}) in the graph at (x, y); returns its id."""
    if node["type"] == OUTPUT and any(n["type"] == OUTPUT for n in graph["nodes"].values()):
        raise GraphError("只能有一個輸出節點")
    nid = new_node_id(graph, base or (node.get("ref") or node["type"]).rsplit("/", 1)[-1].replace(":", "_"))
    graph["nodes"][nid] = {**node, "x": float(x), "y": float(y)}
    return nid


def param_key(nid, name):
    return f"{nid}.{name}"


def default_params(graph):
    """{"<node>.<param>": default} of every filter node of the graph, and of the effect's own parameters."""
    out = {expose_key(x["name"]): copy.deepcopy(x["default"]) for x in exposed(graph)}
    for nid, n in graph["nodes"].items():
        if n["type"] == FILTER:
            out.update({param_key(nid, k): v for k, v in fx.default_params(fx.get(n["ref"])).items()})
    return out


def remove_node(graph, nid):
    graph["nodes"].pop(nid, None)
    graph["links"] = [l for l in graph["links"] if nid not in (l["from"], l["to"])]


def reaches(graph, a, b):
    """Whether b can be reached from a following the links."""
    seen, todo = set(), [a]
    while todo:
        n = todo.pop()
        if n == b:
            return True
        if n in seen:
            continue
        seen.add(n)
        todo += [l["to"] for l in graph["links"] if l["from"] == n]
    return False


def has_loop(graph):
    nxt = {}
    for l in graph["links"]:
        nxt.setdefault(l["from"], []).append(l["to"])
    state = {}

    def walk(n):
        if state.get(n) == 1:
            return True
        if state.get(n) == 2:
            return False
        state[n] = 1
        if any(walk(m) for m in nxt.get(n, ())):
            return True
        state[n] = 2
        return False

    return any(walk(n) for n in list(graph["nodes"]))


EXPOSE = "expose."


def has_socket(p):
    """Whether parameter p can be fed by a link: a picture (a number or colour) or a bound effect parameter."""
    return p.type not in ("curve", "gradient")


def expose_key(name):
    return EXPOSE + name


def exposed(graph):
    return graph.get("exposed") or []


def binds(graph):
    """{(node id, socket): exposed parameter name} of the parameters bound to the effect's own."""
    return {(l["to"], l["socket"]): l["out"] for l in graph["links"]
            if l.get("out") and graph["nodes"].get(l["from"], {}).get("type") == PARAMS}


def sockets(node):
    """[(socket, label)] a node takes pictures in at."""
    if node["type"] == OUTPUT:
        return [("src", "結果")]
    if node["type"] == REROUTE:
        return [("src", "")]
    if node["type"] != FILTER:
        return []
    d = fx.get(node["ref"])
    return ([("src", d.src_label)] + [(n, lab) for n, lab in d.inputs] +
            [(PARAM + p.name, p.label) for p in d.params if has_socket(p)])


def title(node):
    if node["type"] == FILTER:
        return fx.get(node["ref"]).name
    return {FRAME: "框架", REROUTE: "繞線", PARAMS: "參數輸入", INPUT: "輸入", OUTPUT: "輸出", SOURCE: {"image": "圖片", "video": "影片", "compound": "複合片段", "shape": "形狀",
                                                  "track": "時間線（軌道）"}.get(node.get("kind"), "來源")}[node["type"]]


FRAME_COLORS = {"gray": "#5a5a60", "red": "#a04848", "orange": "#a8742e", "green": "#4a8a52", "blue": "#3f6fa8", "purple": "#7a5aa0"}


def frame_defaults(node):
    """A frame (框架 / 註解): the box, its label, the note written in it and its colour."""
    return {"type": FRAME, "w": float(node.get("w", 320.0)), "h": float(node.get("h", 200.0)), "label": node.get("label", "框架"),
            "text": node.get("text", ""), "color": node.get("color", "gray") if node.get("color", "gray") in FRAME_COLORS else "gray"}


def ordered(graph):
    """Node ids from left to right (then top to bottom): the order their rows are listed in."""
    return sorted(graph["nodes"], key=lambda i: (graph["nodes"][i].get("x", 0.0), graph["nodes"][i].get("y", 0.0), i))


_defs = {}


def virtual_def(e):
    """A FilterDef whose parameters are those of every filter node of effect e's graph, named
    "<node>.<parameter>" and in a panel (@panel) of the node each (so the effects panel, keyframes and the
    numbers lists treat a graph like any filter)."""
    g = e["graph"]
    rows = []
    for nid in ordered(g):
        n = g["nodes"][nid]
        if n["type"] == FILTER:
            d = fx.get(n["ref"])
            rows.append((nid, n.get("mute"), d))
    bound = binds(g)
    own = exposed(g)
    key = (tuple((nid, mute, d.key(), d.error) for nid, mute, d in rows), tuple(sorted(bound)),
           tuple((x["name"], x["label"], x["type"], x["lo"], x["hi"], tuple(x.get("items") or ())) for x in own))
    hit = _defs.get(key)
    if hit is not None:
        return hit
    params, panels = [], []
    for x in own:                                              # the effect's own parameters first
        params.append(fx.Param(expose_key(x["name"]), x["type"], copy.deepcopy(x["default"]), x["lo"], x["hi"], x["label"],
                               x.get("items") or ()))
    for nid, mute, d in rows:
        name = f"{d.name}（{nid}）"
        panels.append((name, False))
        for q in d.params:
            if (nid, PARAM + q.name) in bound:                 # (fed by an effect parameter)
                continue
            c = fx.Param(param_key(nid, q.name), q.type, q.default, q.lo, q.hi, q.label, q.items)
            c.panel = name
            c.enable = [(param_key(nid, o), neg, want) for o, neg, want in q.enable]
            params.append(c)
    out = fx.FilterDef(fx.GRAPH, fx.GRAPH_DEF.name, "", params, fx.GRAPH_DEF.category, fx.GRAPH_DEF.description,
                       panels=panels, error=next((f"{d.name}：{d.error}" for _n, _m, d in rows if d.error), None))
    if len(_defs) > 64:
        _defs.clear()
    _defs[key] = out
    return out


_shape_cache = {}


def shape_image(src, size=512):
    """The picture of a shape source ({"shape", "color"}): the shape in its colour, filling a size x size square
    (the source's frame: where and how big it is on the clip is cx / cy / w / h / rotation, as a picture's).
    QImage, premultiplied; the same image object while its settings are the same."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPolygonF
    import math
    shape = src.get("shape", "rectangle")
    col = [max(0.0, min(1.0, float(x))) for x in (list(src.get("color") or [1, 1, 1, 1]) + [1.0] * 4)[:4]]
    key = (shape, tuple(round(x, 4) for x in col), size)
    hit = _shape_cache.get(key)
    if hit is not None:
        return hit
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor.fromRgbF(*col))
    r = QRectF(0, 0, size, size)
    c = size / 2
    if shape == "ellipse":
        p.drawEllipse(r)
    elif shape == "rounded":
        p.drawRoundedRect(r, size * 0.2, size * 0.2)
    elif shape == "triangle":
        p.drawPolygon(QPolygonF([QPointF(c, 0), QPointF(size, size), QPointF(0, size)]))
    elif shape in ("hexagon", "star"):
        n, inner = (6, 1.0) if shape == "hexagon" else (10, 0.42)
        pts = []
        for i in range(n):
            a = -math.pi / 2 + i * 2 * math.pi / n
            k = 1.0 if shape == "hexagon" or i % 2 == 0 else inner
            pts.append(QPointF(c + math.cos(a) * c * k, c + math.sin(a) * c * k))
        p.drawPolygon(QPolygonF(pts))
    elif shape == "heart":
        path = QPainterPath(QPointF(c, size * 0.95))
        path.cubicTo(QPointF(-size * 0.15, size * 0.55), QPointF(size * 0.1, -size * 0.05), QPointF(c, size * 0.3))
        path.cubicTo(QPointF(size * 0.9, -size * 0.05), QPointF(size * 1.15, size * 0.55), QPointF(c, size * 0.95))
        p.drawPath(path)
    else:
        p.drawRect(r)
    p.end()
    if len(_shape_cache) > 64:
        _shape_cache.clear()
    _shape_cache[key] = img
    return img


def has_output(node):
    return node["type"] not in (OUTPUT, FRAME)


def param_of(graph, nid, socket):
    """The Param a socket "param:<name>" of filter node nid stands for (None: it is not one)."""
    node = graph["nodes"].get(nid)
    if node is None or node["type"] != FILTER or not socket.startswith(PARAM):
        return None
    return next((p for p in fx.get(node["ref"]).params if p.name == socket[len(PARAM):]), None)


def connect(graph, src, dst, socket, out=None):
    """Link node src's picture (or its exposed parameter out) into socket of node dst (replacing what was
    there); GraphError when it would make a loop, the socket does not exist or the kinds do not fit."""
    nodes = graph["nodes"]
    if src not in nodes or dst not in nodes or not has_output(nodes[src]):
        raise GraphError("找不到這個節點")
    if socket not in [s for s, _ in sockets(nodes[dst])]:
        raise GraphError("這個節點沒有這個輸入")
    p = param_of(graph, dst, socket)
    if nodes[src]["type"] == PARAMS:
        x = next((x for x in exposed(graph) if x["name"] == out), None)
        if x is None or p is None:
            raise GraphError("參數只能接到節點的參數插槽")
        if (x["type"], x.get("items") or []) != (p.type, list(p.items)):
            raise GraphError("參數的種類和這個插槽不一樣")
    else:
        out = None
        if p is not None and p.type not in fx.SOURCE_TYPES:
            raise GraphError("這個參數只能接效果自己的參數（參數輸入節點）")
    if src == dst or reaches(graph, dst, src):
        raise GraphError("節點不能連成迴圈")
    graph["links"] = [l for l in graph["links"] if not (l["to"] == dst and l["socket"] == socket)]
    link = {"from": src, "to": dst, "socket": socket}
    if out:
        link["out"] = out
    graph["links"].append(link)


def expose(graph, params, src, dst, socket):
    """Make a new effect parameter out of parameter socket of node dst and bind it (a link from node src, a
    參數輸入 node): it starts at the value the parameter had and takes its name, range and choices. Returns its
    name. (params: the effect's e["params"].)"""
    p = param_of(graph, dst, socket)
    if p is None or graph["nodes"].get(src, {}).get("type") != PARAMS:
        raise GraphError("參數只能接到節點的參數插槽")
    names = {x["name"] for x in exposed(graph)}
    name, n = p.name, 1
    while name in names:
        n += 1
        name = f"{p.name}{n}"
    key = param_key(dst, p.name)
    value = copy.deepcopy(params.pop(key, p.default))
    graph.setdefault("exposed", []).append({"name": name, "label": p.label, "type": p.type, "default": copy.deepcopy(p.default),
                                            "lo": p.lo, "hi": p.hi, "items": list(p.items)})
    params[expose_key(name)] = value
    connect(graph, src, dst, socket, name)
    return name


def remove_exposed(graph, params, name):
    graph["exposed"] = [x for x in exposed(graph) if x["name"] != name]
    graph["links"] = [l for l in graph["links"] if l.get("out") != name]
    params.pop(expose_key(name), None)


def insert_on_link(graph, nid, src, dst, socket, out=None):
    """Put node nid in the middle of the link src -> dst (socket): its main picture in, its picture out."""
    nodes = graph["nodes"]
    node = nodes[nid]
    ins = [s for s, _ in sockets(node) if not s.startswith(PARAM)]
    if not ins or not has_output(node):
        raise GraphError("這個節點不能放在連線上")
    if any(l["from"] == nid or l["to"] == nid for l in graph["links"]):
        raise GraphError("節點已經有連線")
    connect(graph, nid, dst, socket)
    connect(graph, src, nid, ins[0], out)


def dissolve(graph, nid):
    """Delete node nid but keep the picture going through it (its first picture input to what its output fed)."""
    feeds = [l for l in graph["links"] if l["to"] == nid and not l["socket"].startswith(PARAM)]
    main = next((l for l in feeds if l["socket"] == "src"), feeds[0] if feeds else None)
    outs = [l for l in graph["links"] if l["from"] == nid]
    remove_node(graph, nid)
    if main is not None:
        for l in outs:
            try:
                connect(graph, main["from"], l["to"], l["socket"], main.get("out"))
            except GraphError:
                pass


def duplicate(graph, ids, dx=40.0, dy=40.0):
    """Copies of the nodes ids (with the links among them); returns {old id: new id}."""
    ids = [i for i in ids if i in graph["nodes"] and graph["nodes"][i]["type"] != OUTPUT]
    made = {}
    for i in ids:
        node = copy.deepcopy(graph["nodes"][i])
        node["x"], node["y"] = node.get("x", 0.0) + dx, node.get("y", 0.0) + dy
        made[i] = add_node(graph, node, node["x"], node["y"], base=i.rstrip("0123456789") or "node")
    for l in list(graph["links"]):
        if l["from"] in made and l["to"] in made:
            graph["links"].append({**l, "from": made[l["from"]], "to": made[l["to"]]})
    return made


def pack(graph, ids, params=None, sources=None):
    """What copying nodes ids takes along (to paste in this or another graph): the nodes, the links among them,
    their settings and pictures."""
    ids = [i for i in ids if i in graph["nodes"] and graph["nodes"][i]["type"] != OUTPUT]
    out = {"nodes": {i: copy.deepcopy(graph["nodes"][i]) for i in ids},
           "links": [copy.deepcopy(l) for l in graph["links"] if l["from"] in ids and l["to"] in ids],
           "params": {}, "sources": {i: copy.deepcopy(sources[i]) for i in ids if i in (sources or {})}}
    for k, v in (params or {}).items():
        if k.partition(".")[0] in ids:
            out["params"][k] = copy.deepcopy(v)
    return out


def paste(graph, data, x=0.0, y=0.0):
    """Put a pack (see pack) in the graph with its top left corner at (x, y); returns {old id: new id}. The
    caller copies params and sources under the new ids."""
    nodes = data["nodes"]
    if not nodes:
        return {}
    x0 = min(n.get("x", 0.0) for n in nodes.values())
    y0 = min(n.get("y", 0.0) for n in nodes.values())
    made = {}
    for i, n in nodes.items():
        node = copy.deepcopy(n)
        node["x"], node["y"] = node.get("x", 0.0) - x0 + x, node.get("y", 0.0) - y0 + y
        made[i] = add_node(graph, node, node["x"], node["y"], base=i.rstrip("0123456789") or "node")
    for l in data["links"]:
        if l["from"] in made and l["to"] in made:
            graph["links"].append({**copy.deepcopy(l), "from": made[l["from"]], "to": made[l["to"]]})
    return made


def depths(graph):
    """{node id: column} - how many nodes a picture passes before it (0: nothing feeds it)."""
    ins = {}
    for l in graph["links"]:
        ins.setdefault(l["to"], []).append(l["from"])
    out = {}

    def depth(n, seen=()):
        if n in out:
            return out[n]
        if n in seen:
            return 0
        out[n] = 1 + max((depth(f, seen + (n,)) for f in ins.get(n, [])), default=-1)
        return out[n]
    for n in graph["nodes"]:
        depth(n)
    return out


def disconnect(graph, dst, socket):
    graph["links"] = [l for l in graph["links"] if not (l["to"] == dst and l["socket"] == socket)]


def check(graph):
    """A message when the graph cannot run (no output, a loop, a missing filter), else None."""
    nodes = graph.get("nodes") or {}
    if sum(n["type"] == OUTPUT for n in nodes.values()) != 1:
        return "節點圖要有一個輸出節點"
    if has_loop(graph):
        return "節點連成了迴圈"
    for n in nodes.values():
        if n["type"] == FILTER:
            d = fx.get(n["ref"])
            if d.error:
                return f"{d.name}：{d.error}"
    return None


def source_nodes(graph):
    """{node id: kind} of the graph's picture / video / compound / track nodes."""
    return {i: n.get("kind") for i, n in graph["nodes"].items() if n["type"] == SOURCE}


# -- running it -----------------------------------------------------------------------------------
class Pool:
    """Textures to draw nodes into, for callers that have no layer pool of their own (alloc / free as
    glrender.GL.layer / release)."""

    class Item:
        def __init__(self, eng, w, h):
            self.w, self.h = w, h
            self.tex = eng.ctx.texture((w, h), 4)
            self.tex.filter = (eng.mgl.LINEAR, eng.mgl.LINEAR)
            self.tex.repeat_x = self.tex.repeat_y = False
            self.fbo = eng.ctx.framebuffer(color_attachments=[self.tex])

    def __init__(self, eng):
        self.eng, self.spare = eng, []

    def alloc(self, w, h):
        for i, it in enumerate(self.spare):
            if (it.w, it.h) == (w, h):
                it = self.spare.pop(i)
                break
        else:
            it = Pool.Item(self.eng, w, h)
        it.fbo.clear(0.0, 0.0, 0.0, 0.0)
        return it

    def free(self, it):
        self.spare.append(it)

    def close(self):
        for it in self.spare:
            it.fbo.release()
            it.tex.release()
        self.spare = []


def evaluate(eng, graph, params, src_tex, w, h, alloc, free, t=0, duration=1, fps=30.0, unit=1.0, picture=None, errors=None):
    """Work out graph's output (params: the effect's e["params"]) for the w x h texture src_tex (the effect's input)
    at clip time t.
    alloc(w, h) -> an object with .tex and .fbo, free(it): where nodes are drawn. picture(node id) ->
    (texture, 3 x 3 map, done) of a source node's picture (see Engine.run_tex's sources) or None.
    Returns (texture, owner): owner is the object to give back to free when done with it (None: the
    texture is src_tex itself); (None, None) when the graph has no output. Node errors go to errors."""
    errors = errors if errors is not None else []
    nodes, links = graph["nodes"], graph["links"]
    out = next((i for i, n in nodes.items() if n["type"] == OUTPUT), None)
    if out is None:
        return None, None
    feed = {(l["to"], l["socket"]): l["from"] for l in links if l["from"] in nodes and l["to"] in nodes
            and nodes[l["from"]]["type"] != PARAMS}
    bound = binds(graph)
    order, state = [], {}

    def visit(n):
        if state.get(n) == 2:
            return
        if state.get(n) == 1:
            raise GraphError("節點連成了迴圈")
        state[n] = 1
        for (to, _s), f in feed.items():
            if to == n:
                visit(f)
        state[n] = 2
        order.append(n)

    visit(out)
    users = {n: 0 for n in order}
    for (to, _s), f in feed.items():
        if to in users and f in users:
            users[f] += 1
    if feed.get((out, "src")) in users:
        users[feed[(out, "src")]] += 1                        # (the caller keeps the result)
    made = {}                  # node id -> (texture, owner)
    left = {}                  # id(owner) -> uses left of it
    blank = [None]

    def empty():
        if blank[0] is None:
            blank[0] = alloc(w, h)
        return blank[0].tex

    def put(n, tex, owner):
        made[n] = (tex, owner)
        if owner is not None:
            left[id(owner)] = left.get(id(owner), 0) + users.get(n, 0)

    def take(n, socket):
        f = feed.get((n, socket))
        return made[f][0] if f in made else None

    def done_with(n):
        for (to, _s), f in feed.items():
            if to == n and f in made:
                owner = made[f][1]
                if owner is not None:
                    left[id(owner)] -= 1
                    if left[id(owner)] <= 0:
                        free(owner)

    def alias(n, f):
        tex, owner = made[f] if f in made else (empty(), None)
        put(n, tex, owner)

    time = t / US
    prog = min(1.0, max(0.0, t / max(1, duration)))
    frame = max(0, round(t * fps / US))
    for n in order:
        node = nodes[n]
        kind = node["type"]
        if kind in (PARAMS, FRAME):
            continue
        if kind == REROUTE:                                   # (a bend in a link: the picture goes on)
            alias(n, feed.get((n, "src")))
            done_with(n)
            continue
        if kind == INPUT:
            put(n, src_tex, None)
        elif kind == OUTPUT:
            f = feed.get((n, "src"))
            made[n] = made[f] if f in made else (src_tex, None)
        elif kind == SOURCE:
            pic = picture(n) if picture else None
            dest = alloc(w, h)
            if pic is not None:
                ptex, pmap, give = pic
                try:
                    _run(eng, fx.get(PICTURE), {"color": (0.0, 0.0, 0.0, 0.0)}, empty(), w, h, dest, time, prog, frame, unit,
                         {"color": (ptex, pmap)}, None, errors)
                finally:
                    if give:
                        give()
            put(n, dest.tex, dest)
        else:
            d = fx.get(node["ref"])
            main = feed.get((n, "src"))
            if node.get("mute") or d.error:
                if d.error:
                    errors.append(f"{d.name}：{d.error}")
                alias(n, main)
            else:
                dest = alloc(w, h)
                vals = {p.name: fx.uniform_value(p, params.get(expose_key(bound[(n, PARAM + p.name)]))
                                                 if (n, PARAM + p.name) in bound else params.get(param_key(n, p.name)), t)
                        for p in d.params}
                srcs = {}
                for p in d.params:
                    pt = take(n, PARAM + p.name)
                    if pt is not None and p.type in fx.SOURCE_TYPES:
                        srcs[p.name] = (pt, IDENTITY)
                        if p.type == "float":
                            vals[p.name + fx.RANGE_MIN], vals[p.name + fx.RANGE_MAX] = fx.source_range({}, vals[p.name], t)
                ins = {name: take(n, name) for name, _ in d.inputs}
                if not _run(eng, d, vals, take(n, "src") or empty(), w, h, dest, time, prog, frame, unit, srcs, ins, errors):
                    free(dest)
                    alias(n, main)
                else:
                    put(n, dest.tex, dest)
        done_with(n)
    tex, owner = made[out]
    if blank[0] is not None:
        if tex is blank[0].tex:                               # (an empty graph: nothing drawn)
            return tex, blank[0]
        free(blank[0])
    return tex, owner


def _run(eng, d, vals, src, w, h, dest, time, prog, frame, unit, sources, inputs, errors):
    try:
        eng.run_tex(d, vals, src, w, h, time=time, progress=prog, frame=frame, unit=unit, sources=sources,
                    inputs=inputs, dest=(dest.tex, dest.fbo))
        return True
    except fx.FilterError as exc:
        errors.append(f"節點「{d.name}」：{exc}")
        return False
