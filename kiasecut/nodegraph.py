"""Node graphs: an effect (filter "nodes:graph", fx.GRAPH) whose picture is worked out by a graph of
nodes, as in Blender's compositor. The graph is e["graph"]:

    {"nodes": {id: {"type", "x", "y", "mute"?, ...}}, "links": [{"from": id, "to": id, "socket": s}]}

A filter node's parameters are in the effect's own e["params"] as "<node id>.<parameter>" (so they are
keyframed, edited and copied as an ordinary effect's are).

Node types: "input" (the picture the effect was given), "output" (the graph's result; one), "source"
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
INPUT, OUTPUT, SOURCE, FILTER = "input", "output", "source", "filter"
SOURCE_KINDS = ("image", "video", "compound", "track")
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
    """{"<node>.<param>": default} of every filter node of the graph."""
    out = {}
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


def sockets(node):
    """[(socket, label)] a node takes pictures in at."""
    if node["type"] == OUTPUT:
        return [("src", "結果")]
    if node["type"] != FILTER:
        return []
    d = fx.get(node["ref"])
    return ([("src", d.src_label)] + [(n, lab) for n, lab in d.inputs] +
            [(PARAM + p.name, p.label) for p in d.params if p.type in fx.SOURCE_TYPES])


def has_output(node):
    return node["type"] != OUTPUT


def connect(graph, src, dst, socket):
    """Link node src's picture into socket of node dst (replacing what was there); GraphError when it
    would make a loop or the socket does not exist."""
    nodes = graph["nodes"]
    if src not in nodes or dst not in nodes or not has_output(nodes[src]):
        raise GraphError("找不到這個節點")
    if socket not in [s for s, _ in sockets(nodes[dst])]:
        raise GraphError("這個節點沒有這個輸入")
    if src == dst or reaches(graph, dst, src):
        raise GraphError("節點不能連成迴圈")
    graph["links"] = [l for l in graph["links"] if not (l["to"] == dst and l["socket"] == socket)]
    graph["links"].append({"from": src, "to": dst, "socket": socket})


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
    feed = {(l["to"], l["socket"]): l["from"] for l in links if l["from"] in nodes and l["to"] in nodes}
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
                vals = {p.name: fx.uniform_value(p, params.get(param_key(n, p.name)), t) for p in d.params}
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
