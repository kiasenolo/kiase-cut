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

from . import fuse, assets, curves, dynamic, fx

US = 1_000_000
INPUT, OUTPUT, SOURCE, FILTER, PARAMS, REROUTE, FRAME, GROUP = "input", "output", "source", "filter", "params", "reroute", "frame", "group"
FONT = "font"                                               # 字體: Blender's Font constant - a font file that feeds a text node (never a picture)
STRING = "string"                                           # 字串: Blender's String constant - words that feed a text node (never a picture)
VIEWER = "viewer"                                           # 預覽: what the editor's preview shows (never exported)
SOURCE_KINDS = ("image", "video", "compound", "track", "shape", "text", "vector")
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
    if node["type"] == FILTER and fx.get(node["ref"]).dynamic and not node.get("items"):
        graph["nodes"][nid]["items"] = dynamic.default_items(fx.get(node["ref"]).dynamic)      # (a Menu Switch starts with three options)
    return nid


def param_key(nid, name):
    return f"{nid}.{name}"


# -- nodes with items of their own (Menu Switch): node["items"] = [{"sock", "name"}], see dynamic.py ------------------------
def is_dynamic(node):
    return (is_vecop(node) and node.get("op") not in SINGLE_OPS) or (node["type"] == FILTER and bool(fx.get(node["ref"]).dynamic))


def _items(node):
    if not node.get("items"):
        node["items"] = dynamic.default_items(fx.get(node["ref"]).dynamic)
    return node["items"]


def _swap_sockets(graph, nid, a, b):
    """Links into socket a of node nid go to b and the other way round."""
    oa, ob = dynamic.selected_output(a), dynamic.selected_output(b)
    for l in graph["links"]:
        if l["to"] == nid and l["socket"] in (a, b):
            l["socket"] = b if l["socket"] == a else a
        if l["from"] == nid and l.get("out") in (oa, ob):                   # (a Menu Switch's "this one is chosen" outputs go with their options too)
            l["out"] = ob if l["out"] == oa else oa


def _settle_items(graph, params, nid, old_names):
    """After the items of node nid changed: the first one is on "src", names stay clean and unique, the choice (and an effect
    parameter bound to it) follows the names (old_names: the names before, by item)."""
    node = graph["nodes"][nid]
    items = node["items"]
    if items and items[0]["sock"] != "src":
        first = items[0]["sock"]
        for it in items:
            if it["sock"] == "src":
                it["sock"] = first
        items[0]["sock"] = "src"
        _swap_sockets(graph, nid, first, "src")
    names = dynamic.unique(it["name"] for it in items)
    for it, n in zip(items, names):
        it["name"] = n
    key = param_key(nid, "choice")
    now = {id(it): it["name"] for it in items}
    was = params.get(key)
    if isinstance(was, str):                                    # (the choice follows its option's new name; a removed one: the first)
        sock = next((s for s, n in old_names.items() if n == was), None)
        params[key] = now.get(sock, items[0]["name"]) if sock else (was if was in now.values() else items[0]["name"])
    for l in graph["links"]:                                     # (an effect parameter bound to the choice has the same options)
        if l["to"] == nid and l["socket"] == PARAM + "choice" and l.get("out"):
            x = next((x for x in exposed(graph) if x["name"] == l["out"]), None)
            if x is not None:
                x["items"] = list(now.values())
                x["default"] = items[0]["name"]
                pk = expose_key(x["name"])
                v = params.get(pk)
                sock = next((s for s, n in old_names.items() if n == v), None)
                params[pk] = now.get(sock, items[0]["name"]) if sock else (v if v in x["items"] else items[0]["name"])


def add_item(graph, params, nid, name=None):
    """A new option at the end of node nid's items; returns its socket."""
    node = graph["nodes"][nid]
    if is_vecop(node):
        if node.get("op") in SINGLE_OPS:
            raise GraphError("這個節點只有一個輸入")
        items = vecop_items(node)
        node["items"] = items
        node["next_item"] = max(node.get("next_item", 0), len(items), *(int(it["sock"][1:]) for it in items)) + 1
        sock = f"v{node['next_item']}"
        items.append({"sock": sock})
        return sock
    if not is_dynamic(node):
        raise GraphError("這個節點沒有選項")
    items = _items(node)
    old = {id(it): it["name"] for it in items}
    node["next_item"] = max(node.get("next_item", 0), len(items) + 1, *(int(it["sock"][1:]) for it in items if it["sock"] != "src")) + 1
    sock = f"i{node['next_item']}"
    items.append({"sock": sock, "name": name or f"選項 {len(items) + 1}"})
    _settle_items(graph, params, nid, old)
    return sock


def rename_item(graph, params, nid, sock, name):
    node = graph["nodes"][nid]
    if is_vecop(node):
        raise GraphError("矢量節點的輸入不用命名")
    items = _items(node)
    old = {id(it): it["name"] for it in items}
    it = next((i for i in items if i["sock"] == sock), None)
    if it is None:
        raise GraphError("找不到這個選項")
    it["name"] = name
    _settle_items(graph, params, nid, old)


def remove_item(graph, params, nid, sock):
    node = graph["nodes"][nid]
    if is_vecop(node):
        items = vecop_items(node)
        if len(items) <= 2:
            raise GraphError("矢量節點至少要有兩個輸入")
        if not any(it["sock"] == sock for it in items):
            raise GraphError("找不到這個輸入")
        node["items"] = [it for it in items if it["sock"] != sock]
        graph["links"] = [l for l in graph["links"] if not (l["to"] == nid and l["socket"] == sock)]
        return
    items = _items(node)
    if len(items) <= 2:
        raise GraphError("選單切換至少要有兩個選項")
    old = {id(it): it["name"] for it in items}
    if not any(it["sock"] == sock for it in items):
        raise GraphError("找不到這個選項")
    node["items"] = [it for it in items if it["sock"] != sock]
    gone = dynamic.selected_output(sock)
    graph["links"] = [l for l in graph["links"] if not (l["to"] == nid and l["socket"] == sock) and not (l["from"] == nid and l.get("out") == gone)]
    _settle_items(graph, params, nid, old)


def move_item(graph, params, nid, sock, delta):
    node = graph["nodes"][nid]
    if is_vecop(node):
        items = node["items"] = vecop_items(node)
        i = next((k for k, it in enumerate(items) if it["sock"] == sock), None)
        if i is not None and 0 <= i + delta < len(items):
            items[i], items[i + delta] = items[i + delta], items[i]
        return
    items = _items(node)
    old = {id(it): it["name"] for it in items}
    i = next((k for k, it in enumerate(items) if it["sock"] == sock), None)
    if i is None or not 0 <= i + delta < len(items):
        return
    items[i], items[i + delta] = items[i + delta], items[i]
    _settle_items(graph, params, nid, old)


def default_params(graph):
    """{"<node>.<param>": default} of every filter node of the graph, and of the effect's own parameters."""
    out = {expose_key(x["name"]): copy.deepcopy(x["default"]) for x in exposed(graph)}
    for nid, n in graph["nodes"].items():
        if n["type"] == FILTER:
            out.update({param_key(nid, k): v for k, v in fx.default_params(fx.for_node(n)).items()})
        elif is_asset(n) or is_text(n) or is_vecop(n):
            out.update({param_key(nid, k): v for k, v in fx.default_params(node_def(n)).items()})
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


# -- vector nodes (矢量): 相加 puts the outlines of its inputs one over the other, 布林 combines them by an operation. A source node
# of kind "vector" (node["op"]: "add" | "boolean"); its inputs are the sockets of node["items"] ("v1", "v2"...), each taking the outline of
# a shape, a text, an SVG file or another vector node (vector.py; the picture of the node is its outlines drawn) ---------------------------
VECTOR = "vector"
VECOPS = (("add", "相加"), ("boolean", "布林運算"), ("rotate", "旋轉"), ("move", "移動"), ("scale", "縮放"))
SINGLE_OPS = ("rotate", "move", "scale")                    # the vector nodes that change one vector (the others take many)
ROTATE_ABOUT = ("自己的中心", "畫面中心")
BOOLEAN_OPS = (("聯集", "union"), ("差集", "subtract"), ("交集", "intersect"), ("排除", "xor"))
_vecop_defs = {}


def is_vecop(node):
    return node.get("type") == SOURCE and node.get("kind") == VECTOR


def vecop_items(node):
    """[{"sock"}] the inputs of a vector node (two to start with)."""
    return node.get("items") or ([{"sock": "v1"}] if node.get("op") in SINGLE_OPS else [{"sock": "v1"}, {"sock": "v2"}])


def vecop_sockets(node):
    return [it["sock"] for it in vecop_items(node)]


def vecop_def(node):
    """FilterDef standing for a vector node: 布林's operation as its only parameter."""
    op = node.get("op", "add")
    hit = _vecop_defs.get(op)
    if hit is None:
        params = {"boolean": [fx.Param("operation", "menu", BOOLEAN_OPS[0][0], label="運算", items=[n for n, _ in BOOLEAN_OPS])],
                  "rotate": [fx.Param("angle", "float", 0.0, -3600.0, 3600.0, "角度 °"),
                             fx.Param("about", "menu", ROTATE_ABOUT[0], label="繞著", items=list(ROTATE_ABOUT))],
                  "move": [fx.Param("offset", "vec2", [0.0, 0.0], -10000.0, 10000.0, "位移（px）")],
                  "scale": [fx.Param("factor", "vec2", [1.0, 1.0], 0.001, 1000.0, "縮放"),
                            fx.Param("about", "menu", ROTATE_ABOUT[0], label="以此為中心", items=list(ROTATE_ABOUT))]}.get(op, [])
        hit = _vecop_defs[op] = fx.FilterDef("vector:" + op, dict(VECOPS).get(op, "相加"), "", params, "矢量", "")
    return hit


def vecop_of(node, nid, params, t, bound=None):
    """The operation of vector node nid at clip time t: "add", "union", "subtract", "intersect" or "xor"."""
    if node.get("op", "add") in SINGLE_OPS:
        return node["op"]
    if node.get("op", "add") != "boolean":
        return "add"
    v = curves.value(bound_value(params, bound, nid, "operation", BOOLEAN_OPS[0][0]), t)
    return dict(BOOLEAN_OPS).get(v, "union")


def gives_vector(node, source=None):
    """Whether the node's outline can go into a vector node: a built-in shape, a text, a vector node, or an SVG picture
    (source: its entry of the effect's sources, which says the file)."""
    if is_asset(node) or is_text(node) or is_vecop(node):
        return True
    if node.get("type") == SOURCE and node.get("kind") == "image":
        return source is None or str(source.get("image", "")).lower().endswith(".svg") or not source.get("image")
    return False


# -- text nodes: KiaseCut's text tool as a node (node["kind"] == "text"; its words and font are its source's "content" and
# "font_path", everything else a parameter like a text clip's - textlayout.py draws it) ---------------------------------------
TEXT_ALIGNS = (("靠左", "left"), ("置中", "center"), ("靠右", "right"), ("齊頭尾", "justify"))
TEXT_VALIGNS = (("上", "top"), ("中", "middle"), ("下", "bottom"))
TEXT_STROKE_ALIGNS = (("內側", "inside"), ("居中", "center"), ("外側", "outside"))
TEXT_CONTENT = "輸入文字"
TEXT_SOCKET = "content"                                     # (where a string node is linked into a text node)
FONT_SOCKET = "font"                                        # (and a font node)
WORDS = {STRING: TEXT_SOCKET, FONT: FONT_SOCKET}            # the constants that are no picture: their node type -> the socket of a text node they go into
# name, type, label, default, lo, hi (menus: the choices instead), panel
TEXT_FIELDS = (
    ("size", "float", "字號", 7.95, 0.0, 200.0, None),
    ("color", "color", "顏色", [1.0, 1.0, 1.0, 1.0], None, None, None),
    ("fill", "bool", "填色", True, None, None, None),
    ("letter_spacing", "float", "字距", 0.0, -0.5, 5.0, None),
    ("line_spacing", "float", "行距", 0.02, -0.5, 5.0, None),
    ("italic_deg", "float", "斜體角度", 0.0, -89.0, 89.0, None),
    ("align", "menu", "對齊", TEXT_ALIGNS, None, None, None),
    ("valign", "menu", "垂直對齊", TEXT_VALIGNS, None, None, None),
    ("stroke_on", "bool", "外框", False, None, None, "外框"),
    ("stroke_color", "color", "外框顏色", [0.0, 0.0, 0.0, 1.0], None, None, "外框"),
    ("stroke", "float", "外框粗細 px", 2.0, 0.0, 100.0, "外框"),
    ("stroke_align", "menu", "外框位置", TEXT_STROKE_ALIGNS, None, None, "外框"),
    ("box_w", "float", "寬（0＝自動）", 0.0, 0.0, 4000.0, "文字框"),
    ("box_h", "float", "高（0＝自動）", 0.0, 0.0, 4000.0, "文字框"),
    ("shadow_on", "bool", "陰影", False, None, None, "陰影"),
    ("shadow_color", "color", "陰影顏色", [0.0, 0.0, 0.0, 0.6], None, None, "陰影"),
    ("shadow_x", "float", "陰影 X px", 4.0, -500.0, 500.0, "陰影"),
    ("shadow_y", "float", "陰影 Y px", 4.0, -500.0, 500.0, "陰影"),
    ("shadow_blur", "float", "陰影模糊 px", 6.0, 0.0, 200.0, "陰影"),
    ("bg_on", "bool", "背景", False, None, None, "背景"),
    ("bg_color", "color", "背景顏色", [0.0, 0.0, 0.0, 0.6], None, None, "背景"),
    ("bg_pad_t", "float", "背景間隔 上", 12.0, -500.0, 500.0, "背景"),
    ("bg_pad_b", "float", "背景間隔 下", 12.0, -500.0, 500.0, "背景"),
    ("bg_pad_l", "float", "背景間隔 左", 12.0, -500.0, 500.0, "背景"),
    ("bg_pad_r", "float", "背景間隔 右", 12.0, -500.0, 500.0, "背景"),
    ("bg_radius", "float", "背景圓角 px", 0.0, 0.0, 500.0, "背景"),
)
TEXT_MENUS = {"align": TEXT_ALIGNS, "valign": TEXT_VALIGNS, "stroke_align": TEXT_STROKE_ALIGNS}
TEXT_MENU_DEFAULTS = {"align": "置中"}                      # (the first choice otherwise)
_text_def = []


def is_text(node):
    return node.get("type") == SOURCE and node.get("kind") == "text"


def text_def(_node=None):
    """FilterDef standing for every text node: the text tool's fields as parameters (the words and the font are the
    source's, set from the node)."""
    if _text_def:
        return _text_def[0]
    params, panels = [], []
    for name, typ, label, default, lo, hi, panel in TEXT_FIELDS:
        if typ == "menu":
            q = fx.Param(name, "menu", TEXT_MENU_DEFAULTS.get(name, default[0][0]), label=label, items=[n for n, _ in default])
        elif typ == "color":
            q = fx.Param(name, "color", list(default), label=label)
        elif typ == "bool":
            q = fx.Param(name, "bool", default, label=label)
        else:
            q = fx.Param(name, "float", float(default), lo, hi, label)
        q.panel = panel
        if panel and (panel, True) not in panels:
            panels.append((panel, True))
        params.append(q)
    _text_def.append(fx.FilterDef("text", "文字", "", params, "文字", "", panels=panels))
    return _text_def[0]


def text_value(name, v):
    """What text field `name` holds as a node parameter, from the value a clip's text has (a colour without alpha, a menu's word)."""
    q = next(q for q in text_def().params if q.name == name)
    if q.type == "color":
        return [float(x) for x in (list(v) + [1.0])[:4]] if len(v) < 4 else [float(x) for x in v[:4]]
    if q.type == "menu":
        return next((n for n, val in TEXT_MENUS[name] if val == v), v)
    return v


def text_place_params():
    """Where a text node sits: its centre and turn (its size comes from the words and the font)."""
    return [q for q in place_params() if q.name in ("cx", "cy", "rotation")]


def constant_into(graph, nid, socket):
    """The value of the string / font node linked into `socket` of text node nid (None: there is no such link)."""
    for l in (graph or {}).get("links") or []:
        if l["to"] == nid and l["socket"] == socket and WORDS.get((graph["nodes"].get(l["from"]) or {}).get("type")) == socket:
            return str(graph["nodes"][l["from"]].get("value", ""))
    return None


def text_of(node, nid, params, t, bound=None, src=None, graph=None):
    """The text spec (textlayout.render) of text node nid at clip time t: the words (a linked string node's, else the
    source's) and the source's font, the fields from the effect's params (bound: binds(graph), the parameters fed by the
    effect's own)."""
    words, font = constant_into(graph, nid, TEXT_SOCKET), constant_into(graph, nid, FONT_SOCKET)
    out = {"content": (src or {}).get("content", TEXT_CONTENT) if words is None else words,
           "font_path": (src or {}).get("font_path") if font is None else font}
    for k in ("vars", "styles"):
        if (src or {}).get(k):
            out[k] = (src or {})[k]
    for q in text_def(node).params:
        v = curves.value(bound_value(params, bound, nid, q.name, q.default), t)
        if q.type == "menu":
            v = dict(TEXT_MENUS[q.name]).get(v, v)
        out[q.name] = v
    if out.get("font_path") is None:
        out.pop("font_path")
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
        elif param_key(nid, name) in params:                 # (read from a node linked into it: evaluate puts the value there while it runs)
            out[name] = curves.value(params[param_key(nid, name)], t)
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
    if is_vecop(node):                                   # (its outlines, then the operation)
        return ([(sock, f"矢量 {i + 1}") for i, sock in enumerate(vecop_sockets(node))] +
                [(PARAM + q.name, q.label) for q in vecop_def(node).params if has_socket(q)])
    if is_text(node):                                    # (a text: its words from a string node, then every value)
        return [(TEXT_SOCKET, "文字"), (FONT_SOCKET, "字體")] + [(PARAM + q.name, q.label) for q in text_def(node).params + text_place_params() if has_socket(q)]
    if node["type"] != FILTER:
        return []
    d = fx.for_node(node)
    return ([("src", d.src_label)] + [(n, lab) for n, lab in d.inputs] +
            [(PARAM + p.name, p.label) for p in d.params if has_socket(p)])


def outputs(node):
    """[(output name, label)] a node gives pictures at: one unnamed ("") for most, the @output ones of a filter."""
    if node["type"] == FILTER:
        d = fx.for_node(node)
        if d.outputs:
            return list(d.outputs)
        return [("", d.out_label)]
    if node["type"] == GROUP:
        return [(o["name"], o["label"]) for o in node.get("outputs") or []]
    if node["type"] in WORDS:
        return [("", "字串" if node["type"] == STRING else "字體")]
    return [("", "圖像")]


def short_name(name):
    """A filter's name as the node editor shows it: without the "[Blender] " mark the filter list has (a node
    there is Blender's by its look, the mark in a row of Chinese is odd)."""
    return name[len("[Blender] "):] if name.startswith("[Blender] ") else name


def title(node):
    if node["type"] == FILTER:
        return short_name(fx.for_node(node).name)
    if node["type"] == GROUP:
        return node.get("label") or "群組"
    if is_asset(node) or is_vecop(node):
        return node_def(node).name
    return {"groupin": "群組輸入", "groupout": "群組輸出", STRING: "字串", FONT: "字體", FRAME: "框架", REROUTE: "繞線", PARAMS: "參數輸入", INPUT: "輸入", OUTPUT: "輸出", VIEWER: "預覽", SOURCE: {"image": "圖片", "video": "影片", "compound": "複合片段", "shape": "形狀", "text": "文字", "vector": "矢量",
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
        return fx.for_node(node)
    return asset_def(node) if is_asset(node) else text_def(node) if is_text(node) else vecop_def(node) if is_vecop(node) else None


def programs_needed(proj):
    """{(filter key, baked values): the filter's name} of the shaders the node effects of project proj run (every clip's, compounds
    included), as the graphs' settings choose them: what opening the project compiles (the progress bar counts it against fx.compiled)."""
    from . import project                     # (project imports this module)
    out = {}
    for c in project.all_clips(proj):
        for e in c.get("effects") or ():
            g = e.get("graph") if e.get("filter") == fx.GRAPH else None
            if not g:
                continue
            params = e.get("params") or {}
            for nid, node in flatten(g)["nodes"].items():
                d = node_def(node) if node["type"] == FILTER else None
                if d is None or d.error:
                    continue
                values = {p.name: fx.uniform_value(p, params.get(f"{nid}.{p.name}"), 0.0) for p in d.params if p.name in d.bakes}
                out[(d.key(), fx.baked_values(d, values))] = d.name
    return out


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
    if is_text(node):
        return next((p for p in text_def(node).params + text_place_params() if p.name == socket[len(PARAM):]), None)
    if is_vecop(node):
        return next((p for p in vecop_def(node).params if p.name == socket[len(PARAM):]), None)
    if node["type"] != FILTER:
        return None
    return next((p for p in fx.for_node(node).params if p.name == socket[len(PARAM):]), None)


def takes_picture(graph, nid, socket):
    """Whether a picture (a constant node's, say) can be linked into `socket` of node nid: false for a parameter that only
    the effect's own parameters feed (where a shape or a text sits...)."""
    node = graph["nodes"].get(nid)
    if node is None:
        return False
    if socket in WORDS.values():
        return is_text(node)
    p = param_of(graph, nid, socket)
    if p is None:
        return True
    if is_asset(node) or is_text(node) or is_vecop(node):    # (a shape's or a text's values, and where it sits, are read once)
        return p.type in fx.SOURCE_TYPES + CONTROL_TYPES
    return p.type in fx.SOURCE_TYPES + CONTROL_TYPES + VECTOR_TYPES


CONSTANTS = {"float": "builtin:nodes/value", "int": "builtin:nodes/integer", "bool": "builtin:nodes/boolean",
             "color": "builtin:nodes/rgb", "vector": "builtin:nodes/vector"}       # (the constant node for a kind of socket)


def socket_kind(graph, nid, socket):
    """What input `socket` of node nid takes: "float", "int", "bool", "color", "vector" or "menu" (a picture: "color")."""
    node = graph["nodes"].get(nid)
    if node is not None and (is_asset(node) or is_text(node) or is_vecop(node)):          # (a shape's or a text's field: its own type)
        p = param_of(graph, nid, socket)
        return "color" if p is None else "vector" if p.type in ("vec2", "vec3") else p.type if p.type in ("float", "int", "bool", "menu") else "color"
    if node is None or node["type"] != FILTER:
        return "color"
    d = fx.for_node(node)
    if ("in", socket) in d.socket_types:
        kind = d.socket_types[("in", socket)]
        return "color" if kind == "image" else kind
    name = socket[len(PARAM):] if socket.startswith(PARAM) else d.input_param.get(socket)
    p = param_of(graph, nid, PARAM + name) if name else None
    if p is None:
        return "color"
    return "vector" if p.type in ("vec2", "vec3") else p.type if p.type in ("float", "int", "bool", "menu") else "color"


# -- the shape of a socket (Blender's): a circle holds one value (0-D), a diamond a value for every pixel (a field) -------------
SINGLE_NODES = ("value", "integer", "boolean", "rgb", "vector", "integer_vector", "menu")      # builtin:nodes/<these> give one value


def output_shape(graph, nid, out=""):
    """What output `out` of node nid gives: "single" (one number, colour or switch: a constant, a parameter of the effect)
    or "field" (a picture - or a number that changes over the picture)."""
    node = (graph or {}).get("nodes", {}).get(nid)
    if node is None:
        return "field"
    t = node["type"]
    if t in WORDS or t == PARAMS:
        return "single"
    if t == FILTER and node.get("ref", "").rpartition("/")[2] in SINGLE_NODES and node.get("ref", "").startswith("builtin:nodes/"):
        return "single"
    return "field"


def input_shape(graph, nid, socket):
    """What input `socket` of node nid takes: "field" (a picture), "either" (a number or colour that may be one value or a
    picture read at every pixel) or "single" (a whole number, switch, choice or vector: a picture linked in is read once, at its
    middle)."""
    node = (graph or {}).get("nodes", {}).get(nid)
    if node is None or socket in WORDS.values():
        return "single" if node is not None else "field"
    if not socket.startswith(PARAM):
        if node["type"] == FILTER:
            d = fx.for_node(node)
            name = d.input_param.get(socket)
            if name is None:
                kind = d.socket_types.get(("in", socket), "image")
                return "field" if kind == "image" else "either" if kind in ("float", "color") else "single"
            p = param_of(graph, nid, PARAM + name)
            if p is not None:
                return "either" if p.type in fx.SOURCE_TYPES else "single"
        return "field"
    p = param_of(graph, nid, socket)
    if p is None:
        return "field"
    if is_asset(node) or is_text(node) or is_vecop(node):    # (a shape's or a text's values are read once)
        return "single"
    return "either" if p.type in fx.SOURCE_TYPES else "single"


def socket_value(graph, params, nid, socket):
    """The value of the number / colour / switch `socket` of filter node nid stands for - its field's (None: it has none)."""
    node = graph["nodes"].get(nid)
    if node is not None and (is_asset(node) or is_text(node) or is_vecop(node)) and socket.startswith(PARAM):
        p = param_of(graph, nid, socket)
        if p is None:
            return None
        v = params.get(param_key(nid, p.name), p.default)
        return curves.value(v, 0) if curves.is_animated(v) else v
    if node is None or node["type"] != FILTER:
        return None
    name = socket[len(PARAM):] if socket.startswith(PARAM) else fx.for_node(node).input_param.get(socket)
    p = param_of(graph, nid, PARAM + name) if name else None
    if p is None:
        return None
    v = params.get(param_key(nid, name), p.default)
    return curves.value(v, 0) if curves.is_animated(v) else v


def constant_params(ref, value):
    """{parameter: value} a constant node `ref` (builtin:nodes/value, rgb, ...) starts with so that it gives `value` - what
    the socket it is made for held (Blender: a Value node made from a socket keeps the socket's value). {} when it does
    not fit."""
    name = ref.rpartition("/")[2]
    nums = isinstance(value, (int, float)) and not isinstance(value, bool)
    vec = isinstance(value, (list, tuple)) and len(value) >= 3 and all(isinstance(x, (int, float)) for x in value)
    if name == "value" and (nums or isinstance(value, bool)):
        return {"value": float(value)}
    if name == "integer" and (nums or isinstance(value, bool)):
        return {"value": int(round(float(value)))}
    if name == "boolean" and (nums or isinstance(value, bool)):
        return {"value": bool(value)}
    if name == "rgb" and vec:
        return {"color": [float(x) for x in value[:3]] + [float(value[3]) if len(value) > 3 else 1.0]}
    if name == "vector" and vec:
        return {"vector": [float(x) for x in value[:3]]}
    if name == "integer_vector" and vec:
        return dict(zip("xyz", (int(round(float(x))) for x in value[:3])))
    return {}


def connect(graph, src, dst, socket, out=None):
    """Link node src's picture (or its exposed parameter out) into socket of node dst (replacing what was
    there); GraphError when it would make a loop, the socket does not exist or the kinds do not fit."""
    nodes = graph["nodes"]
    if src not in nodes or dst not in nodes or not has_output(nodes[src]):
        raise GraphError("找不到這個節點")
    if socket not in [s for s, _ in sockets(nodes[dst])]:
        raise GraphError("這個節點沒有這個輸入")
    if nodes[src]["type"] in WORDS or socket in WORDS.values():     # (words go from a string node to a text node's 文字, a font from a font node to its 字體, and nowhere else)
        if WORDS.get(nodes[src]["type"]) != socket or not is_text(nodes[dst]):
            raise GraphError("字串只能接到文字節點的「文字」，字體只能接到「字體」")
        graph["links"] = [l for l in graph["links"] if not (l["to"] == dst and l["socket"] == socket)]
        graph["links"].append({"from": src, "to": dst, "socket": socket})
        return
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
        if is_vecop(nodes[dst]) and socket in vecop_sockets(nodes[dst]) and not gives_vector(nodes[src]):
            raise GraphError("矢量節點只能接形狀、文字、SVG 圖片或別的矢量節點")
        if p is not None and (is_asset(nodes[dst]) or is_text(nodes[dst]) or is_vecop(nodes[dst])) and p.type not in fx.SOURCE_TYPES + CONTROL_TYPES:
            raise GraphError("這個參數只能接效果自己的參數（參數輸入節點）")
        if p is not None and p.type not in fx.SOURCE_TYPES + CONTROL_TYPES + VECTOR_TYPES:
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


# the parameter types made by hand in the 參數 panel: type -> (label, default, lo, hi); a link needs the very type of the socket
MANUAL_TYPES = {"float": ("浮點", 0.0, 0.0, 1.0), "int": ("整數", 0, 0, 10), "bool": ("開關", False, 0, 1),
                "color": ("顏色", [1.0, 1.0, 1.0, 1.0], 0.0, 1.0), "vec2": ("二維向量", [0.0, 0.0], -1000.0, 1000.0),
                "vec3": ("三維向量", [0.0, 0.0, 0.0], -1000.0, 1000.0)}


def add_exposed(graph, params, kind, label=None):
    """A new effect parameter made by hand (the 參數 panel's 新增參數) of type kind (MANUAL_TYPES); it is bound to nothing
    until a link from the 參數輸入 node's row of it goes into a socket of that type. Returns its name."""
    if kind not in MANUAL_TYPES:
        raise GraphError("不能新增這種參數")
    text, default, lo, hi = MANUAL_TYPES[kind]
    names = {x["name"] for x in exposed(graph)}
    n = 1
    while f"param{n}" in names:
        n += 1
    name = f"param{n}"
    graph.setdefault("exposed", []).append({"name": name, "label": (label or "").strip() or f"{text} {n}", "type": kind,
                                            "default": copy.deepcopy(default), "lo": lo, "hi": hi, "items": []})
    params[expose_key(name)] = copy.deepcopy(default)
    return name


def remove_exposed(graph, params, name):
    graph["exposed"] = [x for x in exposed(graph) if x["name"] != name]
    graph["links"] = [l for l in graph["links"] if l.get("out") != name]
    params.pop(expose_key(name), None)


def edit_exposed(graph, params, name, fields):
    """Change an effect parameter (the 參數 panel): fields may hold label, type (a number between float and int only), lo, hi,
    default. The value it has now follows the range."""
    x = next((x for x in exposed(graph) if x["name"] == name), None)
    if x is None:
        raise GraphError("找不到這個參數")
    fields = dict(fields)
    if "label" in fields:
        fields["label"] = str(fields["label"]).strip() or x["label"]
    number = x["type"] in ("float", "int")
    if "type" in fields and fields["type"] != x["type"]:
        if number and fields["type"] in ("float", "int"):
            pass
        elif x["type"] in MANUAL_TYPES and fields["type"] in MANUAL_TYPES:
            if any(l.get("out") == name for l in graph["links"]):
                raise GraphError("這個參數已經接在節點上，先斷開連線才能改種類")
            _t, default, lo, hi = MANUAL_TYPES[fields["type"]]
            x.update({"type": fields.pop("type"), "default": copy.deepcopy(default), "lo": lo, "hi": hi})
            params[expose_key(name)] = copy.deepcopy(default)
            number = x["type"] in ("float", "int")
        else:
            raise GraphError("這種參數不能改種類")
    if not number and {"lo", "hi"} & fields.keys():
        raise GraphError("這個參數沒有範圍")
    x.update({k: v for k, v in fields.items() if k in ("label", "type", "lo", "hi", "default")})
    if x["type"] in ("float", "int"):
        whole = x["type"] == "int"
        conv = (lambda v: int(round(v))) if whole else float
        x["lo"], x["hi"] = conv(x["lo"]), conv(x["hi"])
        if x["lo"] > x["hi"]:
            x["lo"], x["hi"] = x["hi"], x["lo"]
        clamp = lambda v: min(x["hi"], max(x["lo"], conv(v)))
        x["default"] = clamp(x["default"])
        key = expose_key(name)
        v = params.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            params[key] = clamp(v)


def move_exposed(graph, name, delta):
    """Move effect parameter `name` up (-1) or down (1) in the list."""
    xs = graph.get("exposed") or []
    i = next((i for i, x in enumerate(xs) if x["name"] == name), None)
    if i is None:
        raise GraphError("找不到這個參數")
    j = i + delta
    if 0 <= j < len(xs):
        xs[i], xs[j] = xs[j], xs[i]


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
            d = fx.for_node(n)
            if d.error:
                return f"{d.name}：{d.error}"
    return None


def source_nodes(graph):
    """{node id: kind} of the graph's picture / video / compound / track nodes."""
    return {i: n.get("kind") for i, n in graph["nodes"].items() if n["type"] == SOURCE}


CONTROL_TYPES = ("bool", "int", "menu")        # parameters a number can set: a picture linked into one is read as a number (Blender's implicit conversions)
VECTOR_TYPES = ("vec2", "vec3")                # a picture linked into one is read as its colour at the middle: R, G (, B) (a grey one gives
                                               # the same number to each: Blender's float to vector)


def _centre(eng, graph, f, params, src_tex, alloc, free, t, duration, fps, unit, picture, errors):
    """The colour (R, G, B) a picture (node f[0]'s output f[1]) has at the middle. Worked out small (a number does not care how big
    its picture is)."""
    import numpy as np
    g = {"nodes": {**graph["nodes"], "\0control": {"type": VIEWER}},
         "links": [l for l in graph["links"] if graph["nodes"][l["to"]]["type"] != VIEWER] +
                  [{"from": f[0], "to": "\0control", "socket": "src", **({"out": f[1]} if f[1] else {})}]}
    tex, owner = evaluate(eng, g, params, src_tex, 4, 4, alloc, free, t=t, duration=duration, fps=fps, unit=unit, picture=picture,
                          errors=errors, viewer=True)
    if tex is None:
        return 0.0, 0.0, 0.0
    a = np.frombuffer(tex.read(), np.float16 if tex.dtype == "f2" else np.float32 if tex.dtype == "f4" else np.uint8).reshape(
        tex.size[1], tex.size[0], 4).astype(np.float64)
    if tex.dtype == "f1":
        a /= 255.0
    if owner is not None:
        free(owner)
    return tuple(float(x) for x in a[tex.size[1] // 2, tex.size[0] // 2, :3])


def _control(*args):
    """The value a picture says for a tick or a menu: its brightness at the middle (as a number node's picture is a float). True when
    above 0.5; a menu takes the number as the index of its choice."""
    r, g, b = _centre(*args)
    return float(0.2126 * r + 0.7152 * g + 0.0722 * b)


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
                if l["to"] == vid and l["socket"] == "src" and l["from"] in nodes and not gives_params(nodes[l["from"]], l.get("out")) \
                        and nodes[l["from"]]["type"] not in WORDS:
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


OVERSCAN_STEPS = (0, 25, 50, 100)                           # 延伸範圍: % of the frame on each side; "auto": GEOMETRY_NODES have 50
GEOMETRY_NODES = ("rotate", "transform", "map_uv")          # (builtin:nodes/...) and the filters below: what moves a picture, so the part that leaves the frame is wanted again
GEOMETRY_FILTERS = ("transform", "scale", "translate")
OVERSCAN_IN, OVERSCAN_OUT = "builtin:_overscan_in", "builtin:_overscan_out"
OVERSCAN_MAX_PX = 8192


def overscan_safe(d):
    """Whether filter d works the same with a bigger picture under it: it does not read pixels by their place on the card."""
    code = d.code or ""
    return "gl_FragCoord" not in code and "texelFetch" not in code


def overscan_fraction(graph, setting="auto"):
    """The margin (a fraction of the frame, on each side) a node effect's graph is worked out with: its 延伸範圍 setting (a number of
    %, or "auto": 50 % when the graph has a node that moves the picture and none that cannot work with a margin)."""
    nodes = [n for n in (graph.get("nodes") or {}).values() if n["type"] == FILTER]
    if setting in (None, "auto"):
        refs = {n["ref"] for n in nodes}
        moves = any(r.rpartition("/")[2] in GEOMETRY_NODES and r.startswith("builtin:nodes/") for r in refs) or \
            any(r in ["builtin:" + f for f in GEOMETRY_FILTERS] for r in refs)
        percent = 50 if moves and all(overscan_safe(fx.get(r)) for r in refs) else 0
    else:
        try:
            percent = float(setting)
        except (TypeError, ValueError):
            percent = 0
    return max(0.0, min(percent, 100.0)) / 100.0


def evaluate(eng, graph, params, src_tex, w, h, alloc, free, *args, overscan=None, **kw):
    """Work out graph's output - see _evaluate. The values a shape or text node reads from the nodes linked into its parameters are
    put into `params` while it runs (the shape and the text are drawn from the effect's params) and taken out again after.
    overscan: the effect's 延伸範圍 (overscan_fraction): the graph is worked out on pictures that many times bigger round the frame,
    so what a Rotate or Transform takes out of the frame can come back; the result is the frame's part. None: no margin."""
    m = 0.0 if overscan is None else overscan_fraction(graph, overscan)
    mx, my = round(w * m), round(h * m)
    while m > 0 and max(w + 2 * mx, h + 2 * my) > OVERSCAN_MAX_PX:
        mx, my = mx * 3 // 4, my * 3 // 4
    if mx <= 0 and my <= 0:
        return _evaluate_given(eng, graph, params, src_tex, w, h, alloc, free, *args, **kw)
    W, H = w + 2 * mx, h + 2 * my
    ov = (w / W, h / H, mx / W, my / H)
    ident = (1.0, 1.0, 0.0, 0.0)
    unit, errors = kw.get("unit", 1.0), kw.setdefault("errors", [])
    big = alloc(W, H)
    result = (None, None)
    try:
        eng.overscan = (ident, ov)                                  # (drawn in the middle of the bigger picture)
        if not _run(eng, fx.get(OVERSCAN_IN), {}, src_tex, W, H, [(0, big)], 0.0, 0.0, 0, unit, None, None, errors):
            return _evaluate_given(eng, graph, params, src_tex, w, h, alloc, free, *args, **kw)
        eng.overscan = (ov, ov)
        tex, owner = _evaluate_given(eng, graph, params, big.tex, W, H, alloc, free, *args, **kw)
        if tex is None:
            return None, None
        out = alloc(w, h)
        eng.overscan = (ov, ident)                                  # (and the frame's part taken back)
        ok = _run(eng, fx.get(OVERSCAN_OUT), {}, tex, w, h, [(0, out)], 0.0, 0.0, 0, unit, None, None, errors)
        if owner is not None:
            free(owner)
        if not ok:
            free(out)
            return None, None
        result = (out.tex, out)
        return result
    finally:
        eng.overscan = None
        free(big)


def _evaluate_given(eng, graph, params, src_tex, w, h, alloc, free, *args, **kw):
    given = {}
    try:
        return _evaluate(eng, graph, params, src_tex, w, h, alloc, free, *args, _given=given, **kw)
    finally:
        for key, old in given.items():
            if old is _MISSING:
                params.pop(key, None)
            else:
                params[key] = old


_MISSING = object()


def _evaluate(eng, graph, params, src_tex, w, h, alloc, free, t=0, duration=1, fps=30.0, unit=1.0, picture=None, errors=None, viewer=False, tap=None,
              stamp=None, cache=None, scope=None, input_stamp=None, _given=None):
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
            and not gives_params(nodes[l["from"]], l.get("out")) and nodes[l["from"]]["type"] not in WORDS}        # (the node and the output it gives; words are no picture)
    view = viewed(graph) if viewer else None
    if view and (view[0] not in nodes or nodes[view[0]]["type"] in (PARAMS, FRAME, OUTPUT, VIEWER)):
        view = None
    bound = binds(graph)
    ctrl = {}                                                 # (node, parameter) -> what a picture linked into its tick / menu socket says
    reach, todo = set(), [view[0] if view else out]
    feeds_of = {}                                             # consumer -> the pictures that feed it
    for (to, _s), f in feed.items():
        feeds_of.setdefault(to, []).append(f)
    while todo:                                               # (only the nodes the result comes from: a control of any other is not read)
        n = todo.pop()
        if n not in reach:
            reach.add(n)
            todo += [f[0] for f in feeds_of.get(n, ())]
    for (to, sock), f in list(feed.items()):
        p = param_of(graph, to, sock) if sock.startswith(PARAM) else None
        drawn = nodes[to]["type"] == SOURCE and (is_asset(nodes[to]) or is_text(nodes[to]) or is_vecop(nodes[to]))      # (a shape / text node: its fields are read once)
        if p is not None and (p.type in CONTROL_TYPES + VECTOR_TYPES or (drawn and p.type in fx.SOURCE_TYPES)):
            del feed[(to, sock)]                              # (read once, a number: the picture itself is not drawn for it)
            if to not in reach:
                continue
            if drawn:
                if p.type == "color":
                    c = _centre(eng, graph, f, params, src_tex, alloc, free, t, duration, fps, unit, picture, errors)
                    v = [float(c[0]), float(c[1]), float(c[2]), 1.0]
                else:
                    v = _control(eng, graph, f, params, src_tex, alloc, free, t, duration, fps, unit, picture, errors)
                    if p.type == "bool":
                        v = v > 0.5
                    elif p.type == "menu":
                        v = p.items[min(max(int(round(v)), 0), len(p.items) - 1)] if p.items else v
                key = param_key(to, p.name)
                if _given is not None:
                    _given.setdefault(key, params.get(key, _MISSING))
                params[key] = v
                continue
            if p.type in VECTOR_TYPES:
                c = _centre(eng, graph, f, params, src_tex, alloc, free, t, duration, fps, unit, picture, errors)
                ctrl[(to, p.name)] = list(c[:2 if p.type == "vec2" else 3])
                continue
            v = _control(eng, graph, f, params, src_tex, alloc, free, t, duration, fps, unit, picture, errors)
            ctrl[(to, p.name)] = v > 0.5 if p.type == "bool" else v         # (a whole number: rounded where it is used)
    order, state = [], {}

    def visit(n):
        if state.get(n) == 2:
            return
        if state.get(n) == 1:
            raise GraphError("節點連成了迴圈")
        state[n] = 1
        for f in feeds_of.get(n, ()):
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
            got = settings[n] = {p.name: fx.uniform_value(p, ctrl[(n, p.name)] if (n, p.name) in ctrl else
                                                          params.get(expose_key(bound[(n, PARAM + p.name)]))
                                                          if (n, PARAM + p.name) in bound else params.get(param_key(n, p.name)), t)
                                 for p in d.params}
        return got

    for (to, sock) in list(feed):                             # (@use: a picture the settings do not read is not worked out - Blender's lazy Switch)
        node = nodes[to]
        if node["type"] == FILTER and not node.get("mute"):
            d = fx.for_node(node)
            conds = d.input_use.get(sock)
            if conds is not None and not fx._holds(conds, fx.named(d, values(to, d))):
                del feed[(to, sock)]

    feeds_of = {}                                             # (again: the controls and the pictures a setting does not read are gone)
    for (to, _s), f in feed.items():
        feeds_of.setdefault(to, []).append(f)
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
        d = fx.for_node(node)
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
        for g in feeds_of.get(f[0], ()):
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
        for f in feeds_of.get(n, ()):
            if f in made:
                owner = made[f][1]
                if owner is not None:
                    left[id(owner)] -= 1
                    if left[id(owner)] <= 0:
                        free(owner)

    def alias(n, f, o=""):
        tex, owner = made[f] if f in made else (empty(), None)
        put(n, tex, owner, o)

    def filter_node(n, node):
        d = fx.for_node(node)
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
                    if p.type == "float":                 # (a node's number is the number: 0 gives 0 and 1 gives 1, and 5 gives 5)
                        vals[p.name + fx.RANGE_MIN], vals[p.name + fx.RANGE_MAX] = 0.0, 1.0
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

    groups, absorbed = ({}, set()) if tap is not None or not fuse.enabled else _plan_fusion(nodes, feed, order, needed, miss, users, final, cached, fx, ctrl)

    def fused_group(members):
        """Draw the nodes of a group (see fuse.py) in one pass; False when that cannot be done (they are drawn one by one then)."""
        rank = {m: i for i, m in enumerate(members)}
        wanted_out = next(o for o, _ in outputs(nodes[members[-1]]) if (members[-1], o) in miss)
        wirings, ext, exts, defs, outs = [], [], {}, [], []
        for m in members:
            d = fx.for_node(nodes[m])
            names = [o for o, _ in outputs(nodes[m])]
            wiring = {}
            for sock in ["src"] + [name for name, _ in d.inputs]:
                f = feed.get((m, sock))
                if f is None:
                    continue
                if f[0] in rank:
                    wiring[sock] = ("node", rank[f[0]])
                elif f in made:
                    if f not in exts:
                        exts[f] = len(ext)
                        ext.append(f)
                    wiring[sock] = ("ext", exts[f])
            o = wanted_out if m == members[-1] else next(o for o, _ in outputs(nodes[m]) if (m, o) in miss)
            outs.append(names.index(o) if o in names else 0)
            defs.append((d, wiring, outs[-1]))
            wirings.append(wiring)
        if len(ext) > fuse.MAX_EXTERNAL:
            return False
        built = fuse.build(defs)
        if built is None or built[0].key() in fuse.bad:
            return False
        fused, mapping = built
        vals = {}
        for i, pname, new in mapping:
            vals[new] = values(members[i], defs[i][0])[pname]
        dest = alloc(w, h)
        mine = []
        if not _run(eng, fused, vals, empty(), w, h, [(0, dest)], time, prog, frame, unit, None,
                    {f"e{k}": made[f][0] for k, f in enumerate(ext)}, mine, src_on=False):
            free(dest)
            fuse.bad.add(fused.key())
            return False
        put(members[-1], dest.tex, dest, wanted_out)
        return True

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
            if n in absorbed:                                     # (drawn inside the group it belongs to, see below)
                continue
            if n in groups:
                if not fused_group(groups[n]):
                    for m in groups[n]:
                        filter_node(m, nodes[m])
                for m in groups[n]:
                    done_with(m)
                continue
            filter_node(n, node)
        done_with(n)
    if cache is not None:
        cache.sweep(scope)
    tex, owner = made[final] if final in made else made.get((out, ""), (src_tex, None))
    if blank[0] is not None:
        if tex is blank[0].tex:                               # (an empty graph: nothing drawn)
            return tex, blank[0]
        free(blank[0])
    return tex, owner


def _plan_fusion(nodes, feed, order, needed, miss, users, final, cached, fx_, ctrl):
    """({last node id: [member ids, drawn first to last]}, the ids of the members that are not the last): the nodes drawn in
    one pass (fuse.py). A group is a pointwise node and the pointwise nodes before it whose picture only it reads."""
    def fusable(n):
        node = nodes[n]
        if node["type"] != FILTER or node.get("mute") or n not in needed:
            return None
        d = fx_.for_node(node)
        if not fuse.can_fuse(d) or any((n, PARAM + p.name) in feed for p in d.params):
            return None
        names = [o for o, _ in outputs(node)]
        if len([o for o in names if (n, o) in miss]) != 1 or any(cached((n, o)) for o in names):
            return None
        return d
    ok = {n: fusable(n) for n in order}
    absorbed, groups = set(), {}
    for root in reversed(order):
        if root in absorbed or ok.get(root) is None:
            continue
        members, todo, uniforms = [root], [root], fuse.uniforms(ok[root])
        while todo and len(members) < fuse.MAX_NODES:
            c = todo.pop()
            for sock in ["src"] + [name for name, _ in ok[c].inputs]:
                f = feed.get((c, sock))
                if f is None or len(members) >= fuse.MAX_NODES:
                    continue
                p = f[0]
                if p in members or p in absorbed or ok.get(p) is None or users.get(f) != 1 or f == final or (p, f[1]) not in miss:
                    continue
                if uniforms + fuse.uniforms(ok[p]) > fuse.MAX_UNIFORMS:        # (it starts a group of its own)
                    continue
                uniforms += fuse.uniforms(ok[p])
                members.append(p)
                todo.append(p)
        if len(members) < 2:
            continue
        absorbed.update(members[1:])
        groups[root] = sorted(members, key=order.index)
    return groups, absorbed


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
        d = fx.for_node(node)
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
