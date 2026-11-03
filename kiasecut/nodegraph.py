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
pictures too. Each filter node is drawn once (Engine.run_tex) into a texture of its own; the costly ones that do not read the
picture the effect was given keep it from one evaluation to the next (Cache), so a frame that changes nothing they depend on draws none of them.
"""
import copy
import hashlib
import math
import re

from . import assets, curves, fx

US = 1_000_000
INPUT, OUTPUT, SOURCE, FILTER, PARAMS, REROUTE, FRAME, GROUP = "input", "output", "source", "filter", "params", "reroute", "frame", "group"
VIEWER = "viewer"                                           # 預覽: what the editor's preview shows (never exported)
SOURCE_KINDS = ("image", "video", "compound", "track", "shape")
SHAPES = (("rectangle", "矩形"), ("ellipse", "圓形"), ("rounded", "圓角矩形"), ("triangle", "三角形"),
          ("hexagon", "六邊形"), ("star", "星形"), ("heart", "愛心"))
PICTURE = "builtin:nodes/picture"
SHAPE_PAINT = "builtin:_shape_paint"      # (a built-in shape node whose fill / outline is a picture: the picture put where the paint is)
ASSET_PAINTS = (("fill", "fill_image", "填充圖片"), ("stroke", "stroke_image", "外框圖片"))
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
        elif is_asset(n):
            out.update({param_key(nid, k): v for k, v in fx.default_params(asset_def(n)).items()})
    return out


# -- shape nodes made from the built-in shapes (assets.py): node["asset"] = {"key": preset, "family": ...} ----------
ASSET_SKIP = ("w", "h", "fill_image", "stroke_image", "stops", "fill_stops", "stroke_stops")   # (size: the node's frame; pictures: its inputs; gradients: made with nodes)
PLACE = (("cx", "位置 X", -2.0, 2.0, 0.0), ("cy", "位置 Y", -2.0, 2.0, 0.0), ("w", "寬", 0.01, 4.0, 1.0),
         ("h", "高", 0.01, 4.0, 1.0), ("rotation", "旋轉 °", -360.0, 360.0, 0.0),
         ("fit", "寬高比 寬/高（0＝拉伸）", 0.0, 10.0, 0.0))   # where a source sits on the clip (the source's own fields)


def place_params():
    """The Params of where a shape node sits (position, size as fractions of the clip, rotation): sockets like any, fed by
    parameters of the effect; their values are the source's (what the preview's handles move)."""
    out = []
    for name, label, lo, hi, default in PLACE:
        q = fx.Param(name, "float", default, lo, hi, label)
        q.place = True
        out.append(q)
    return out
_asset_defs = {}


def is_asset(node):
    return node.get("type") == SOURCE and node.get("kind") == "shape" and bool((node.get("asset") or {}).get("key"))


def asset_groups(family):
    """([own fields], [fill fields], [stroke fields]) a shape of this family can be edited by."""
    fields = [f for f in assets.fields_of(family) if f not in ASSET_SKIP]
    fill = [f for f in fields if f.startswith("fill_")]
    stroke = [f for f in fields if f.startswith("stroke_") and f != "stroke_on"] + [f for f in ("stroke", "join") if f in fields]
    stroke = [f for f in fields if f in stroke]
    main = [f for f in fields if f not in fill and f not in stroke]
    return main, fill, stroke


def asset_def(node):
    """FilterDef standing for shape node `node`: the shape's fields as parameters (the numbers, colours, choices
    and switches; the size is the node's frame, set where it sits)."""
    a = node["asset"]
    key = (a["key"], a.get("family"))
    hit = _asset_defs.get(key)
    if hit is not None:
        return hit
    preset = assets.get(a["key"])
    base = assets.make(preset, "#ffffff", "#000000", 1920, 1080) if preset else {}
    family = base.get("family") or a.get("family") or "rect"
    main, fill, stroke = asset_groups(family)
    params, panels = [], []
    for names, panel in ((main, None), (fill, "填充"), (stroke, "外框")):
        if panel and names:
            panels.append((panel, True))
        for f in names:
            info = assets.FIELD_INFO[f]
            default = base.get(f, assets._DEFAULTS.get(f))
            if info[1] == "number":
                q = fx.Param(f, "float", float(default if default is not None else 0.0), info[2], info[3], info[0])
            elif info[1] == "color":
                q = fx.Param(f, "color", list(assets.to_rgba(default)), label=info[0])
            elif info[1] == "toggle":
                q = fx.Param(f, "bool", bool(default), label=info[0])
            elif info[1] == "choice":
                items = [n for n, _ in info[2]]
                label = next((n for n, v in info[2] if v == default), items[0])
                q = fx.Param(f, "menu", label, label=info[0], items=items)
            else:
                continue
            q.panel = panel
            params.append(q)
    out = fx.FilterDef("asset:" + a["key"], preset.name if preset else "形狀", "", params, "形狀", "", panels=panels)
    _asset_defs[key] = out
    return out


def bound_value(params, bound, nid, name, default=None):
    """What parameter `name` of node nid holds: the effect parameter it is bound to, or its own."""
    if bound and (nid, PARAM + name) in bound:
        return params.get(expose_key(bound[(nid, PARAM + name)]), default)
    return params.get(param_key(nid, name), default)


def placed_by(src, params, bound, nid, t):
    """Source dict src with the place fields that are bound to effect parameters taken from them."""
    out = dict(src)
    for name, *_ in PLACE:
        if bound and (nid, PARAM + name) in bound:
            out[name] = curves.value(params.get(expose_key(bound[(nid, PARAM + name)]), src.get(name)), t)
    return out


def asset_of(node, nid, params, t, bound=None):
    """The built-in shape's parameters (assets.at) of shape node nid at clip time t, from the effect's params
    (bound: binds(graph), the parameters fed by the effect's own)."""
    a = node["asset"]
    d = asset_def(node)
    out = {"key": a["key"], "family": a.get("family") or (assets.get(a["key"]) or assets.ASSETS[0]).family}
    for q in d.params:
        v = curves.value(bound_value(params, bound, nid, q.name, q.default), t)
        if q.type == "menu":
            v = next((val for n, val in assets.FIELD_INFO[q.name][2] if n == v), v)
        out[q.name] = v
    return assets.at(out, t)


def remove_node(graph, nid):
    if (graph["nodes"].get(nid) or {}).get("type") == GROUP:      # (a group takes its members with it)
        for m in members(graph, nid):
            remove_node(graph, m)
    graph["nodes"].pop(nid, None)
    graph["links"] = [l for l in graph["links"] if nid not in (l["from"], l["to"])]
    prune_groups(graph)


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


def gives_params(node, out=""):
    """Whether the link leaving `node` at output `out` is an effect parameter: from a 參數輸入, or from the named rows of the 輸入
    (Blender's Group Input: the picture and the parameters on one node)."""
    return node["type"] == PARAMS or (node["type"] == INPUT and bool(out))


def binds(graph):
    """{(node id, socket): exposed parameter name} of the parameters bound to the effect's own."""
    graph = flatten(graph)
    return {(l["to"], l["socket"]): l["out"] for l in graph["links"]
            if l.get("out") and l["from"] in graph["nodes"] and gives_params(graph["nodes"][l["from"]], l["out"])}


def sockets(node):
    """[(socket, label)] a node takes pictures in at."""
    if node["type"] == OUTPUT:
        return [("src", "結果")]
    if node["type"] == VIEWER:
        return [("src", "圖像")]
    if node["type"] == REROUTE:
        return [("src", "")]
    if node["type"] == GROUP:
        return [(i["name"], i["label"]) for i in node.get("inputs") or []]
    if is_asset(node):                                   # (a built-in shape: pictures to paint its fill and outline with, then every value)
        return ([(sock, label) for _p, sock, label in ASSET_PAINTS] +
                [(PARAM + q.name, q.label) for q in asset_def(node).params + place_params() if has_socket(q)])
    if node["type"] != FILTER:
        return []
    d = fx.get(node["ref"])
    return ([("src", d.src_label)] + [(n, lab) for n, lab in d.inputs] +
            [(PARAM + p.name, p.label) for p in d.params if has_socket(p)])


def outputs(node):
    """[(output name, label)] a node gives pictures at: one unnamed ("") for most, the @output ones of a filter."""
    if node["type"] == FILTER:
        d = fx.get(node["ref"])
        if d.outputs:
            return list(d.outputs)
    if node["type"] == GROUP:
        return [(o["name"], o["label"]) for o in node.get("outputs") or []]
    return [("", "圖像")]


def title(node):
    if node["type"] == FILTER:
        return fx.get(node["ref"]).name
    if node["type"] == GROUP:
        return node.get("label") or "群組"
    if is_asset(node):
        return asset_def(node).name
    return {"groupin": "群組輸入", "groupout": "群組輸出", FRAME: "框架", REROUTE: "繞線", PARAMS: "參數輸入", INPUT: "輸入", OUTPUT: "輸出", VIEWER: "預覽", SOURCE: {"image": "圖片", "video": "影片", "compound": "複合片段", "shape": "形狀",
                                                  "track": "時間線（軌道）"}.get(node.get("kind"), "來源")}[node["type"]]


# -- groups: nodes boxed up in one (a flat graph keeps the nodes; a member says node["group"] = the group's id) ----
def flatten(graph):
    """The graph without its group nodes: every link that goes into / out of a group goes to / from the members
    behind its socket instead (a graph with no group is returned as it is)."""
    nodes = graph["nodes"]
    if not any(n["type"] == GROUP for n in nodes.values()):
        return graph

    def source(nid, out, seen=()):
        n = nodes.get(nid)
        if n is None:
            return None
        if n["type"] != GROUP:
            return nid, out
        o = next((o for o in n.get("outputs") or [] if o["name"] == out), None)
        if o is None or (nid, out) in seen:
            return None
        return source(o["from"], o.get("out") or "", seen + ((nid, out),))

    def sinks(nid, socket, seen=()):
        n = nodes.get(nid)
        if n is None:
            return []
        if n["type"] != GROUP:
            return [(nid, socket)]
        i = next((i for i in n.get("inputs") or [] if i["name"] == socket), None)
        if i is None or (nid, socket) in seen:
            return []
        return [t for m, sk in i.get("to") or [] for t in sinks(m, sk, seen + ((nid, socket),))]
    links = []
    for l in graph["links"]:
        a = source(l["from"], l.get("out") or "")
        if a is None:
            continue
        for to, socket in sinks(l["to"], l["socket"]):
            link = {"from": a[0], "to": to, "socket": socket}
            if a[1]:
                link["out"] = a[1]
            links.append(link)
    return {**graph, "nodes": {i: n for i, n in nodes.items() if n["type"] != GROUP}, "links": links}


def make_group(graph, ids, label="群組"):
    """Box the nodes ids (all at one level, none the output) up in a group node; every link across the border
    goes through a socket of it. Returns the group's id."""
    nodes = graph["nodes"]
    ids = [i for i in ids if i in nodes and nodes[i]["type"] not in (OUTPUT, FRAME)]
    if not ids:
        raise GraphError("沒有可以群組的節點")
    level = {nodes[i].get("group") for i in ids}
    if len(level) != 1:
        raise GraphError("要群組的節點要在同一層")
    parent = level.pop()
    inside = set(ids)
    gid = new_node_id(graph, "group")
    group = {"type": GROUP, "label": label, "x": sum(nodes[i].get("x", 0.0) for i in ids) / len(ids),
             "y": sum(nodes[i].get("y", 0.0) for i in ids) / len(ids), "inputs": [], "outputs": []}
    if parent:
        group["group"] = parent
    ins, outs, links = {}, {}, []
    for l in graph["links"]:
        a, b = l["from"] in inside, l["to"] in inside
        if b and not a:                                           # a link in: one socket per source
            key = (l["from"], l.get("out") or "")
            if key not in ins:
                n = len(group["inputs"]) + 1
                label_in = dict(sockets(nodes[l["to"]])).get(l["socket"]) or f"輸入 {n}"
                group["inputs"].append({"name": f"in{n}", "label": label_in, "to": []})
                ins[key] = group["inputs"][-1]
                links.append({**l, "to": gid, "socket": ins[key]["name"]})
            ins[key]["to"].append([l["to"], l["socket"]])
        elif a and not b:                                         # a link out: one socket per member output
            key = (l["from"], l.get("out") or "")
            if key not in outs:
                n = len(group["outputs"]) + 1
                group["outputs"].append({"name": f"out{n}", "label": f"輸出 {n}", "from": key[0], "out": key[1]})
                outs[key] = group["outputs"][-1]
            links.append({**l, "from": gid, "out": outs[key]["name"]})
        else:
            links.append(l)
    graph["links"] = links
    graph["nodes"][gid] = group
    for i in ids:
        nodes[i]["group"] = gid
    return gid


def members(graph, gid):
    return [i for i, n in graph["nodes"].items() if n.get("group") == gid]


def ungroup(graph, gid):
    """Take group gid apart: its members go to the group's level and its links are joined again."""
    g = graph["nodes"].get(gid)
    if g is None or g["type"] != GROUP:
        raise GraphError("這不是群組")
    links = []
    for l in graph["links"]:
        if l["to"] == gid:
            i = next((i for i in g.get("inputs") or [] if i["name"] == l["socket"]), None)
            links += [{**l, "to": m, "socket": s} for m, s in (i or {}).get("to") or []]
        elif l["from"] == gid:
            o = next((o for o in g.get("outputs") or [] if o["name"] == (l.get("out") or "")), None)
            if o is not None:
                link = {**l, "from": o["from"]}
                link.pop("out", None)
                if o.get("out"):
                    link["out"] = o["out"]
                links.append(link)
        else:
            links.append(l)
    graph["links"] = links
    for i in members(graph, gid):
        if g.get("group"):
            graph["nodes"][i]["group"] = g["group"]
        else:
            graph["nodes"][i].pop("group", None)
    del graph["nodes"][gid]


def group_input(graph, gid, member, socket, name=None):
    """Feed socket of member from the group's input name (a new one when None): what fed it inside goes."""
    g = graph["nodes"][gid]
    if graph["nodes"].get(member, {}).get("group") != gid:
        raise GraphError("節點不在這個群組裡")
    if socket not in [s for s, _ in sockets(graph["nodes"][member])]:
        raise GraphError("這個節點沒有這個輸入")
    for i in g["inputs"]:
        i["to"] = [t for t in i["to"] if t != [member, socket]]
    graph["links"] = [l for l in graph["links"] if not (l["to"] == member and l["socket"] == socket)]
    entry = next((i for i in g["inputs"] if i["name"] == name), None)
    if entry is None:
        n = 1
        while any(i["name"] == f"in{n}" for i in g["inputs"]):
            n += 1
        entry = {"name": name or f"in{n}", "label": dict(sockets(graph["nodes"][member])).get(socket) or f"輸入 {n}", "to": []}
        g["inputs"].append(entry)
    entry["to"].append([member, socket])
    _tidy_group(graph, gid)
    return entry["name"]


def group_output(graph, gid, member, out="", name=None):
    """The group's output name (a new one when None) is member's output out."""
    g = graph["nodes"][gid]
    node = graph["nodes"].get(member)
    if node is None or node.get("group") != gid or not has_output(node):
        raise GraphError("節點不在這個群組裡")
    entry = next((o for o in g["outputs"] if o["name"] == name), None)
    if entry is None:
        n = 1
        while any(o["name"] == f"out{n}" for o in g["outputs"]):
            n += 1
        entry = {"name": name or f"out{n}", "label": f"輸出 {n}"}
        g["outputs"].append(entry)
    entry["from"], entry["out"] = member, out or ""
    return entry["name"]


def group_unplug(graph, gid, member=None, socket=None, output=None):
    """Cut member's socket from the group's input, or take away the group's output named output."""
    g = graph["nodes"][gid]
    if output is not None:
        g["outputs"] = [o for o in g["outputs"] if o["name"] != output]
        graph["links"] = [l for l in graph["links"] if not (l["from"] == gid and (l.get("out") or "") == output)]
        return
    for i in g["inputs"]:
        i["to"] = [t for t in i["to"] if t != [member, socket]]
    _tidy_group(graph, gid)


def _tidy_group(graph, gid):
    """Inputs nothing is behind any more go (with the links that fed them)."""
    g = graph["nodes"][gid]
    gone = {i["name"] for i in g["inputs"] if not i["to"]}
    g["inputs"] = [i for i in g["inputs"] if i["name"] not in gone]
    graph["links"] = [l for l in graph["links"] if not (l["to"] == gid and l["socket"] in gone)]


def prune_groups(graph):
    """After nodes were removed: group sockets that lead to a missing node go."""
    nodes = graph["nodes"]
    for gid, g in list(nodes.items()):
        if g["type"] != GROUP:
            continue
        for i in g["inputs"]:
            i["to"] = [t for t in i["to"] if t[0] in nodes]
        _tidy_group(graph, gid)
        dead = [o["name"] for o in g["outputs"] if o["from"] not in nodes]
        g["outputs"] = [o for o in g["outputs"] if o["name"] not in dead]
        graph["links"] = [l for l in graph["links"] if not (l["from"] == gid and (l.get("out") or "") in dead)]


FRAME_COLORS = {"gray": "#5a5a60", "red": "#a04848", "orange": "#a8742e", "green": "#4a8a52", "blue": "#3f6fa8", "purple": "#7a5aa0"}


def frame_defaults(node):
    """A frame (框架 / 註解): the box, its label, the note written in it and its colour."""
    return {"type": FRAME, "w": float(node.get("w", 320.0)), "h": float(node.get("h", 200.0)), "label": node.get("label", "框架"),
            "text": node.get("text", ""), "color": node.get("color", "gray") if node.get("color", "gray") in FRAME_COLORS else "gray"}


def ordered(graph):
    """Node ids from left to right (then top to bottom): the order their rows are listed in."""
    return sorted(graph["nodes"], key=lambda i: (graph["nodes"][i].get("x", 0.0), graph["nodes"][i].get("y", 0.0), i))


_defs = {}


def node_def(node):
    """FilterDef whose parameters node has: a filter's, or a shape made from a built-in one; else None."""
    if node["type"] == FILTER:
        return fx.get(node["ref"])
    return asset_def(node) if is_asset(node) else None


def virtual_def(e):
    """A FilterDef whose parameters are those of every filter node of effect e's graph, named
    "<node>.<parameter>" and in a panel (@panel) of the node each (so the effects panel, keyframes and the
    numbers lists treat a graph like any filter)."""
    g = e["graph"]
    rows = []
    for nid in ordered(g):
        n = g["nodes"][nid]
        d = node_def(n)
        if d is not None:
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
    if node["type"] == GROUP:
        return bool(node.get("outputs"))
    return node["type"] not in (OUTPUT, FRAME, VIEWER)


def param_of(graph, nid, socket):
    """The Param a socket "param:<name>" of filter node nid stands for (None: it is not one)."""
    node = graph["nodes"].get(nid)
    if node is None or not socket.startswith(PARAM):
        return None
    if is_asset(node):
        return next((p for p in asset_def(node).params + place_params() if p.name == socket[len(PARAM):]), None)
    if node["type"] != FILTER:
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
    if gives_params(nodes[src], out):
        x = next((x for x in exposed(graph) if x["name"] == out), None)
        if x is None or p is None:
            raise GraphError("參數只能接到節點的參數插槽")
        if (x["type"], x.get("items") or []) != (p.type, list(p.items)):
            raise GraphError("參數的種類和這個插槽不一樣")
    else:
        if out not in [o for o, _ in outputs(nodes[src])]:
            out = outputs(nodes[src])[0][0]
        if p is not None and is_asset(nodes[dst]):
            raise GraphError("形狀的數值只能接效果自己的參數（參數輸入節點）")
        if p is not None and p.type not in fx.SOURCE_TYPES:
            raise GraphError("這個參數只能接效果自己的參數（參數輸入節點）")
    if src == dst or reaches(graph, dst, src):
        raise GraphError("節點不能連成迴圈")
    graph["links"] = [l for l in graph["links"] if not (l["to"] == dst and l["socket"] == socket)]
    link = {"from": src, "to": dst, "socket": socket}
    if out:
        link["out"] = out
    graph["links"].append(link)


def expose(graph, params, src, dst, socket, sources=None):
    """Make a new effect parameter out of parameter socket of node dst and bind it (a link from node src, a
    參數輸入 node): it starts at the value the parameter had and takes its name, range and choices. Returns its
    name. (params: the effect's e["params"].)"""
    p = param_of(graph, dst, socket)
    if p is None or graph["nodes"].get(src, {}).get("type") not in (PARAMS, INPUT):
        raise GraphError("參數只能接到節點的參數插槽")
    names = {x["name"] for x in exposed(graph)}
    name, n = p.name, 1
    while name in names:
        n += 1
        name = f"{p.name}{n}"
    key = param_key(dst, p.name)
    if getattr(p, "place", False):                      # (where a shape sits is the source's own, not a node parameter)
        v = ((sources or {}).get(dst) or {}).get(p.name, p.default)
        value = copy.deepcopy(curves.value(v, 0) if curves.is_animated(v) else v)
    else:
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
    ids = [i for i in ids if i in graph["nodes"] and graph["nodes"][i]["type"] not in (OUTPUT, GROUP)]
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
    ids = [i for i in ids if i in graph["nodes"] and graph["nodes"][i]["type"] not in (OUTPUT, GROUP)]
    out = {"nodes": {i: {k: copy.deepcopy(v) for k, v in graph["nodes"][i].items() if k != "group"} for i in ids},
           "links": [copy.deepcopy(l) for l in graph["links"] if l["from"] in ids and l["to"] in ids],
           "params": {}, "sources": {i: copy.deepcopy(sources[i]) for i in ids if i in (sources or {})}}
    for k, v in (params or {}).items():
        if k.partition(".")[0] in ids:
            out["params"][k] = copy.deepcopy(v)
    return out


def paste(graph, data, x=0.0, y=0.0, group=None):
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
        if group:
            node["group"] = group
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


def migrate(graph):
    """Make every link leave an output its node has: one made before the filter had @output pictures (or from a
    picture it no longer gives) names none, and is the filter's first (what the editor draws and the renderer reads)."""
    nodes = graph.get("nodes") or {}
    for l in graph.get("links") or []:
        src = nodes.get(l["from"])
        if src is None or src["type"] != FILTER:
            continue
        names = [o for o, _ in outputs(src)]
        if names and (l.get("out") or "") not in names:
            l["out"] = names[0]


def check(graph):
    """A message when the graph cannot run (no output, a loop, a missing filter), else None."""
    nodes = graph.get("nodes") or {}
    if sum(n["type"] == OUTPUT for n in nodes.values()) != 1:
        return "節點圖要有一個輸出節點"
    if has_loop(flatten(graph)):
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


def read_rgba8(tex):
    """The picture of a node texture as 8-bit RGBA rows (floats - what nodes draw into - are clamped to 0 - 1)."""
    import numpy as np
    w, h = tex.size
    if tex.dtype == "f1":
        return np.frombuffer(tex.read(), np.uint8).reshape(h, w, 4)
    a = np.frombuffer(tex.read(), np.float16 if tex.dtype == "f2" else np.float32).reshape(h, w, 4)
    return (np.clip(a, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def small_rgba8(tex, size=96):
    """(width, height, 8-bit RGBA rows as bytes) of a node texture shrunk to about size px wide. The card shrinks it (a
    mip level: an average, so nothing is skipped over) and only that is read back - not a whole picture a few times
    the size of the screen (floats are clamped to 0 - 1)."""
    import numpy as np
    w, h = tex.size
    level = max(0, int(math.log2(max(1.0, w / size))))
    if level:
        tex.build_mipmaps(0, level)
    lw, lh = max(1, w >> level), max(1, h >> level)
    raw = tex.read(level=level)
    if tex.dtype == "f1":
        arr = np.frombuffer(raw, np.uint8).reshape(lh, lw, 4)
    else:
        a = np.frombuffer(raw, np.float16 if tex.dtype == "f2" else np.float32).reshape(lh, lw, 4)
        arr = (np.clip(a, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    return lw, lh, arr.tobytes()


def thumb_tap(store, size=96, memo=None):
    """A tap for evaluate that keeps a small RGBA (premultiplied) copy of every node's picture in store:
    {node id: {output: (width, height, bytes)}}. memo ({(node id, output): (signature, copy)}, the caller's, kept between
    frames): a picture whose signature (what evaluate knows it depends on) is the one of the last copy is not read again."""
    def tap(nid, out, tex, sig=None):
        if memo is not None and sig is not None:
            got = memo.get((nid, out))
            if got is not None and got[0] == sig:
                store.setdefault(nid, {})[out] = got[1]
                return
        small = store.setdefault(nid, {})[out] = small_rgba8(tex, size)
        if memo is not None and sig is not None:
            memo[(nid, out)] = (sig, small)
    return tap


# -- running it -----------------------------------------------------------------------------------
class Pool:
    """Textures to draw nodes into, for callers that have no layer pool of their own (alloc / free as
    glrender.GL.layer / release)."""

    class Item:
        def __init__(self, eng, w, h):
            self.w, self.h = w, h
            self.tex = eng.ctx.texture((w, h), 4, dtype="f2")        # (16-bit floats: a node can give more than 1 or less than 0)
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


def viewed(graph):
    """(node id, output) the graph's last 預覽 node takes its picture from, or None."""
    nodes = graph.get("nodes") or {}
    found = None
    for vid, n in nodes.items():
        if n["type"] == VIEWER:
            for l in graph.get("links") or []:
                if l["to"] == vid and l["socket"] == "src" and l["from"] in nodes and not gives_params(nodes[l["from"]], l.get("out")):
                    found = (l["from"], l.get("out") or "")
    return found


_SRC_WORDS = re.compile(r"\b(src|original|has_src|source|original_|src_px)\b")
_TIME_WORDS = re.compile(r"\b(time|progress|frame|frame_phase)\b")
HEAVY = 1200                                                # (a filter with more code than this - comments aside - or more passes is worth keeping)


def traits(d):
    """(reads the picture it is given, changes with the time, costs enough to keep its picture) of filter d, from its code
    (its comments left out): what decides whether a node's picture can be reused (see Cache)."""
    got = getattr(d, "_traits", None)
    if got is None:
        code = re.sub(r"//[^\n]*", "", d.code)
        got = d._traits = (bool(_SRC_WORDS.search(code)), bool(_TIME_WORDS.search(code)), d.passes > 1 or len(code) > HEAVY)
    return got


def _frozen(v):
    if isinstance(v, dict):
        return tuple(sorted((k, _frozen(x)) for k, x in v.items()))
    if isinstance(v, (list, tuple)):
        return tuple(_frozen(x) for x in v)
    return v.tobytes() if hasattr(v, "tobytes") else v


def _digest(*parts):
    return hashlib.blake2b(repr(_frozen(parts)).encode("utf-8", "replace"), digest_size=16).digest()


class Cache:
    """The pictures of the costly nodes of node effects (Cache.get / put: key (effect, node, output)), kept from one
    evaluation to the next while nothing they depend on changes (their settings, the pictures that go into them, the
    size, the time when the filter reads it) - as Blender's compositor keeps what is slow to make between its runs.
    A picture is the cache's, not the pool's, until it is dropped: when the effect no longer draws it (sweep), or for
    room (the ones longest unused go first, never one used by the evaluation going on) - limit bytes of them at most."""

    def __init__(self, limit=384 << 20, keep=240):
        self.limit, self.keep, self.bytes, self.serial, self.age, self.free = limit, keep, 0, 0, 0, None
        self.items = {}                          # key -> [signature, item, the serial of the evaluation that used it last, the frame that did]; least recently used first

    @staticmethod
    def size(item):
        return getattr(item, "bytes", item.w * item.h * 8)

    def frame(self):
        """A picture is being drawn: what none of the last `keep` frames used (an effect that was deleted, a place on the
        timeline the playhead has left) goes."""
        self.age += 1
        for k in [k for k, e in self.items.items() if self.age - e[3] > self.keep]:
            self._drop(k)

    def begin(self, free):
        """A new evaluation (free(item) gives a picture back)."""
        self.serial += 1
        self.free = free

    def get(self, key, sig):
        e = self.items.pop(key, None)
        if e is None:
            return None
        self.items[key] = e                      # (most recently used last)
        if e[0] != sig:
            return None
        e[2], e[3] = self.serial, self.age
        return e[1]

    def put(self, key, sig, item):
        """True when the cache took item: it is the cache's from now on (nothing else gives it back)."""
        size = self.size(item)
        old = self.items.pop(key, None)
        if old is not None:
            self.bytes -= self.size(old[1])
            self.free(old[1])
        if size > self.limit:
            return False
        while self.bytes + size > self.limit:
            victim = next((k for k, e in self.items.items() if e[2] < self.serial), None)
            if victim is None:
                return False
            self._drop(victim)
        self.items[key] = [sig, item, self.serial, self.age]
        self.bytes += size
        return True

    def _drop(self, key):
        e = self.items.pop(key)
        self.bytes -= self.size(e[1])
        self.free(e[1])

    def sweep(self, scope):
        """The effect scope has been drawn: what it did not use this time is not wanted any more."""
        for k in [k for k, e in self.items.items() if k[0] == scope and e[2] != self.serial]:
            self._drop(k)

    def clear(self):
        for k in list(self.items):
            self._drop(k)


def evaluate(eng, graph, params, src_tex, w, h, alloc, free, t=0, duration=1, fps=30.0, unit=1.0, picture=None, errors=None, viewer=False, tap=None,
             stamp=None, cache=None, scope=None, input_stamp=None):
    """Work out graph's output (params: the effect's e["params"]) for the w x h texture src_tex (the effect's input)
    at clip time t.
    alloc(w, h) -> an object with .tex and .fbo, free(it): where nodes are drawn. picture(node id) ->
    (texture, 3 x 3 map, done) of a source node's picture (see Engine.run_tex's sources) or None.
    viewer: show the picture a 預覽 node takes instead of the output (the editor's preview, not an export).
    tap(node id, output, texture, signature): told every picture a node gives (the editor's thumbnails, see thumb_tap; the
    signature is None unless there is a cache).
    cache (a Cache), scope (the effect's id) and stamp(node id[, paint, linked]) -> something hashable that says what a source's
    picture is (the same stamp: the same picture; None: it may be a different one every time, as a video's) keep the pictures of
    the costly nodes from one evaluation to the next: a node whose picture is kept, or that only nodes with kept pictures need, is
    not drawn. The nodes that read the picture the effect was given (the clip) are kept only with input_stamp, which says what
    that picture is in the same way (None: it may be a different one every time).
    Returns (texture, owner): owner is the object to give back to free when done with it (None: the
    texture is src_tex itself, or the cache's); (None, None) when the graph has no output. Node errors go to errors."""
    errors = errors if errors is not None else []
    graph = flatten(graph)
    nodes, links = graph["nodes"], graph["links"]
    out = next((i for i, n in nodes.items() if n["type"] == OUTPUT), None)
    if out is None:
        return None, None
    feed = {(l["to"], l["socket"]): (l["from"], l.get("out") or "") for l in links if l["from"] in nodes and l["to"] in nodes
            and not gives_params(nodes[l["from"]], l.get("out"))}        # (the node and the output it gives)
    view = viewed(graph) if viewer else None
    if view and (view[0] not in nodes or nodes[view[0]]["type"] in (PARAMS, FRAME, OUTPUT, VIEWER)):
        view = None
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
                visit(f[0])
        state[n] = 2
        order.append(n)

    visit(view[0] if view else out)                           # (a viewed node: the picture at it, not the output)
    final = view or feed.get((out, "src"))
    time = t / US
    prog = min(1.0, max(0.0, t / max(1, duration)))
    frame = max(0, round(t * fps / US))
    settings = {}

    def values(n, d):
        got = settings.get(n)
        if got is None:
            got = settings[n] = {p.name: fx.uniform_value(p, params.get(expose_key(bound[(n, PARAM + p.name)]))
                                                          if (n, PARAM + p.name) in bound else params.get(param_key(n, p.name)), t)
                                 for p in d.params}
        return got

    for (to, sock) in list(feed):                             # (@use: a picture the settings do not read is not worked out - Blender's lazy Switch)
        node = nodes[to]
        if node["type"] == FILTER and not node.get("mute"):
            d = fx.get(node["ref"])
            conds = d.input_use.get(sock)
            if conds is not None and not fx._holds(conds, fx.named(d, values(to, d))):
                del feed[(to, sock)]

    # what each picture depends on (None: something that changes whatever is set), and which are kept from before
    sigs = {}
    if cache is not None:
        cache.begin(free)
        for n in order:
            _sign(n, nodes[n], feed, sigs, values, w, h, unit, time, prog, frame, stamp, input_stamp)

    def cached(f):
        node = nodes[f[0]]
        if cache is None or sigs.get(f) is None or node["type"] != FILTER or node.get("mute"):
            return False
        d = fx.get(node["ref"])
        return not d.error and (traits(d)[2] or f == final)

    hits, miss, needed = {}, set(), set()

    def demand(f):
        if f in hits or f in miss:
            return
        item = cache.get((scope, *f), sigs[f]) if cached(f) else None
        if item is not None:
            hits[f] = item
            return
        miss.add(f)
        if f[0] in needed:
            return
        needed.add(f[0])
        for (to, _s), g in list(feed.items()):
            if to == f[0]:
                demand(g)

    if tap is not None:                                       # (every picture goes to the editor's thumbnails)
        for (to, _s), f in feed.items():
            if to in order and f[0] in order:
                demand(f)
    if final is not None:
        demand(final)
    if view is None:
        needed.add(out)                                       # (the output node records the result)
    if cache is not None:
        for f in sigs:                                        # (what is not asked for this time stays while the graph is the same)
            if cached(f):
                cache.get((scope, *f), sigs[f])
    users = {}
    for (to, _s), f in feed.items():
        if to in needed and f[0] in needed:
            users[f] = users.get(f, 0) + 1
    if final is not None and final[0] in needed:
        users[final] = users.get(final, 0) + 1                # (the caller keeps the result)
    made = {}                  # node id -> (texture, owner)
    left = {}                  # id(owner) -> uses left of it
    blank = [None]

    def empty():
        if blank[0] is None:
            blank[0] = alloc(w, h)
        return blank[0].tex

    def put(n, tex, owner, o=""):
        made[(n, o)] = (tex, owner)
        if tap is not None:
            tap(n, o, tex, sigs.get((n, o)))
        if owner is not None:
            left[id(owner)] = left.get(id(owner), 0) + users.get((n, o), 0)

    def keep(n, o, dest):
        """Whether the cache took the picture dest of node n's output o."""
        return cache is not None and cached((n, o)) and cache.put((scope, n, o), sigs[(n, o)], dest)

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

    def alias(n, f, o=""):
        tex, owner = made[f] if f in made else (empty(), None)
        put(n, tex, owner, o)

    for f, item in hits.items():
        put(f[0], item.tex, None, f[1])
    for n in order:
        if n not in needed:
            continue
        node = nodes[n]
        kind = node["type"]
        if kind in (PARAMS, FRAME, VIEWER):
            continue
        if kind == REROUTE:                                   # (a bend in a link: the picture goes on)
            alias(n, feed.get((n, "src")))
            done_with(n)
            continue
        if kind == INPUT:
            put(n, src_tex, None)
        elif kind == OUTPUT:
            f = feed.get((n, "src"))
            made[(n, "")] = made[f] if f in made else (src_tex, None)
        elif kind == SOURCE:
            def draw(pic, dest):
                ptex, pmap, give = pic[:3]
                try:
                    _run(eng, fx.get(PICTURE), {"color": (0.0, 0.0, 0.0, 0.0)}, empty(), w, h, [(0, dest)], time, prog, frame, unit,
                         {"color": (ptex, pmap)}, None, errors)
                finally:
                    if give:
                        give()
            asset = is_asset(node)
            linked = frozenset(part for part, sock, _l in ASSET_PAINTS if take(n, sock) is not None) if asset else frozenset()
            pic = (picture(n, None, linked) if asset else picture(n)) if picture else None
            dest = alloc(w, h)
            if pic is not None:
                draw(pic, dest)
                for part, sock, _label in ASSET_PAINTS:         # (a picture as the fill / outline: where that paint is, from it)
                    mask = picture(n, part, linked) if part in linked else None
                    if mask is None:
                        continue
                    where = alloc(w, h)
                    draw(mask, where)
                    mixed = alloc(w, h)
                    if _run(eng, fx.get(SHAPE_PAINT), {"over": part == "stroke"}, take(n, sock), w, h, [(0, mixed)], time, prog, frame, unit,
                            None, {"base": dest.tex, "mask": where.tex}, errors):
                        free(dest)
                        dest = mixed
                    else:
                        free(mixed)
                    free(where)
            put(n, dest.tex, dest)
        else:
            d = fx.get(node["ref"])
            main = feed.get((n, "src"))
            names = [o for o, _ in outputs(node)]
            if node.get("mute") or d.error:
                if d.error:
                    errors.append(f"{d.name}：{d.error}")
                for o in names:
                    alias(n, main, o)
            else:
                vals = dict(values(n, d))
                srcs = {}
                for p in d.params:
                    pt = take(n, PARAM + p.name)
                    if pt is not None and p.type in fx.SOURCE_TYPES:
                        srcs[p.name] = (pt, IDENTITY)
                        if p.type == "float":
                            vals[p.name + fx.RANGE_MIN], vals[p.name + fx.RANGE_MAX] = fx.source_range({}, vals[p.name], t)
                ins = {name: take(n, name) for name, _ in d.inputs}
                wanted = [(k, o) for k, o in enumerate(names) if (n, o) in miss]     # (an output nothing reads, or has kept, is not drawn)
                dests = [alloc(w, h) for _ in wanted]
                if not _run(eng, d, vals, take(n, "src") or empty(), w, h, [(k, dest) for (k, _o), dest in zip(wanted, dests)], time,
                            prog, frame, unit, srcs, ins, errors, src_on=take(n, "src") is not None):
                    for dest, (_k, o) in zip(dests, wanted):
                        free(dest)
                        alias(n, main, o)
                else:                                                 # (one run for all of them: see Engine.run_outputs)
                    for dest, (_k, o) in zip(dests, wanted):
                        put(n, dest.tex, None if keep(n, o, dest) else dest, o)
        done_with(n)
    if cache is not None:
        cache.sweep(scope)
    tex, owner = made[final] if final in made else made.get((out, ""), (src_tex, None))
    if blank[0] is not None:
        if tex is blank[0].tex:                               # (an empty graph: nothing drawn)
            return tex, blank[0]
        free(blank[0])
    return tex, owner


def _sign(n, node, feed, sigs, values, w, h, unit, time, prog, frame, stamp, input_stamp):
    """Set sigs[(n, output)] for node n: a digest of everything its picture depends on, or None when something it reads
    changes whatever the settings say (the picture the effect was given without an input_stamp, a source with no stamp)."""
    kind = node["type"]
    if kind == INPUT:
        if input_stamp is not None:
            sigs[(n, "")] = _digest("input", w, h, input_stamp)
    elif kind == REROUTE:
        f = feed.get((n, "src"))
        sigs[(n, "")] = sigs.get(f) if f is not None else _digest("blank", w, h)
    elif kind == SOURCE:
        if stamp is None:
            return
        asset = is_asset(node)
        linked = frozenset(part for part, sock, _l in ASSET_PAINTS if (n, sock) in feed) if asset else frozenset()
        what = stamp(n, None, linked) if asset else stamp(n)
        if what is None:                                      # (a picture that may be another every time: nothing kept from it)
            return
        parts = [("source", node.get("kind")), what, w, h, unit]
        for part, sock, _label in ASSET_PAINTS:
            if part in linked:
                s, mask = sigs.get(feed[(n, sock)]), stamp(n, part, linked)
                if s is None or mask is None:
                    return
                parts.append((part, mask, s))
        sigs[(n, "")] = _digest(*parts)
    elif kind == FILTER:
        d = fx.get(node["ref"])
        names = [o for o, _ in outputs(node)]
        main = feed.get((n, "src"))
        if node.get("mute") or d.error:                       # (the picture it is given goes on)
            s = sigs.get(main) if main is not None else _digest("blank", w, h)
            for o in names:
                sigs[(n, o)] = s
            return
        reads, timed, _heavy = traits(d)
        parts = [d.key(), w, h, unit, values(n, d), main is not None]
        links = [(name, feed.get((n, name))) for name, _l in d.inputs]
        links += [(p.name, feed.get((n, PARAM + p.name))) for p in d.params if p.type in fx.SOURCE_TYPES]
        if reads:
            links.append(("", main))
        for name, f in links:
            if f is not None:
                s = sigs.get(f)
                if s is None:
                    return
                parts.append((name, s))
        if timed:
            parts += [time, prog, frame]
        base = _digest(*parts)
        for o in names:
            sigs[(n, o)] = _digest(base, o)


def _run(eng, d, vals, src, w, h, outs, time, prog, frame, unit, sources, inputs, errors, src_on=True):
    """Draw filter d's outputs outs [(output index, where: an alloc's item)] over src; False when it failed."""
    try:
        eng.run_outputs(d, vals, src, w, h, [(k, (dest.tex, dest.fbo)) for k, dest in outs], time=time, progress=prog, frame=frame,
                        unit=unit, sources=sources, inputs=inputs, src_on=src_on)
        return True
    except fx.FilterError as exc:
        errors.append(f"節點「{d.name}」：{exc}")
        return False
