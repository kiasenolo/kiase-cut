"""Components (元件): compounds with parameters.

A component is a compound marked component: true, with params: [param] - a live one (元件,
edited on its timeline) or a static one (靜態元件, project.is_static: edited as layers).
Every clip that shows it (an instance) draws it with its own values for those parameters,
kept in clip["params"] {param id: value}; a parameter it leaves out shows what the component
itself has. Instance values animate like any other parameter (curves.py), in the instance's
time: colours blend between keyframes, words, pictures and switches hold until the next one
- an animated static instance is drawn afresh for each frame. A value holds for the whole
content: it replaces the layer's own (keyframed or not).

param {id, name, kind: text | number | color | image | visible, binds: [[clip id, prop]],
       exprs: {"clip id:prop": expression}}
      binds: the clips of the component's content (inside its groups too) it sets and what
      of them (PROPS); one parameter can set several clips (a 主色 for three shapes). Its
      default is what its first clip has at that clip's start (a static one: at the
      picture's moment). A clip that was deleted leaves its binding behind, unused. Visibility
      only touches the picture (a hidden clip still sounds, as on a hidden track).

Values: text a str, number a float (shown in the units the inspector shows: opacity in %),
color [r, g, b, a] (0 - 1), image a picture file's path, visible a bool.

A number parameter sets numbers of a layer - NUMBERS: its position, scale, rotation, opacity,
a text's size, a shape's corner radius, ... as "group.key" props - each through an expression
of its own (expr.py, exprs; absent: `input`, the parameter's value as it is). The expression
reads input, time (seconds into the instance), progress (0 - 1) and duration, so a number
can drive a layer with sin(time) as well as with the instance's value, and is worked out for
every frame an instance draws. An instance that leaves a number out gets the expression of
the default; a broken expression leaves the value as it is.

An image parameter's picture can also be placed in its layer's frame, per instance:
clip["places"] {param id: {cx, cy, w, h}} - its centre in half-frame units (y up) and its size
as fractions of the frame, as a mask's are (each animates like any value; absent: the whole
frame). It reaches the layer as layer["place"] (the renderers draw the picture there).
"""
import os

from . import assets, curves, expr, fx, lfo, mapping, project, svgimage, textvars

ICON = "❖"
KINDS = {"text": "文字", "number": "數字", "color": "顏色", "image": "圖片", "visible": "勾選"}
INST = "inst:"                             # a nested component instance's parameter that is no number: "inst:<kind>:<parameter id>" (a number's is "params.<id>")
FX_ON, FX_BOOL = "fxon:", "fxb:"          # the check props of a layer's filter: "fxon:<effect id>" (the effect on / off), "fxb:<effect id>.<name>" (one of its check boxes)
PROPS = {                         # prop: (kind, label)
    "content": ("text", "文字內容"),
    "text_color": ("color", "文字顏色"),
    "color": ("color", "顏色"),           # a built-in asset's (fill) colour
    "color2": ("color", "顏色 2"),
    "stroke_color": ("color", "外框顏色"),
    "source": ("image", "圖片"),
    "visible": ("visible", "顯示"),
}
FALLBACK = {"text": "", "number": 0.0, "color": [1.0, 1.0, 1.0, 1.0], "image": "", "visible": True}
# a layer's numbers a parameter can set: "group.key": (label, default, shown units per stored unit,
# lowest stored value, highest) - group transform / text / mask / clip (volume) / asset (assets.FIELD_INFO)
NUMBERS = {
    "transform.x": ("位置 X", 0.0, 1, None, None),
    "transform.y": ("位置 Y", 0.0, 1, None, None),
    "transform.scale": ("縮放 X", 1.0, 1, 0.0, None),
    "transform.scale_y": ("縮放 Y", 1.0, 1, 0.0, None),
    "transform.rotation": ("旋轉 °", 0.0, 1, None, None),
    "transform.opacity": ("不透明度 %", 1.0, 100, 0.0, 1.0),
    "transform.anchor_x": ("錨點 X", 0.0, 1, None, None),
    "transform.anchor_y": ("錨點 Y", 0.0, 1, None, None),
    "transform.radius_tl": ("圓角 左上", 0.0, 1, 0.0, None),
    "transform.radius_tr": ("圓角 右上", 0.0, 1, 0.0, None),
    "transform.radius_bl": ("圓角 左下", 0.0, 1, 0.0, None),
    "transform.radius_br": ("圓角 右下", 0.0, 1, 0.0, None),
    "text.size": ("文字大小", 48.0, 1, 0.0, None),
    "text.stroke": ("邊框粗細 px", 2.0, 1, 0.0, None),
    "text.letter_spacing": ("字距", 0.0, 1, None, None),
    "text.line_spacing": ("行距", 0.0, 1, None, None),
    "text.italic_deg": ("斜體角度", 0.0, 1, -89.0, 89.0),
    "text.box_w": ("文字框寬", 0.0, 1, 0.0, None),
    "text.box_h": ("文字框高", 0.0, 1, 0.0, None),
    "text.shadow_x": ("陰影 X px", 4.0, 1, None, None),
    "text.shadow_y": ("陰影 Y px", 4.0, 1, None, None),
    "text.shadow_blur": ("陰影模糊 px", 6.0, 1, 0.0, None),
    "text.bg_pad": ("背景內間隔 px（四邊）", 12.0, 1, None, None),
    "text.bg_pad_l": ("背景內間隔 左 px", 12.0, 1, None, None),
    "text.bg_pad_r": ("背景內間隔 右 px", 12.0, 1, None, None),
    "text.bg_pad_t": ("背景內間隔 上 px", 12.0, 1, None, None),
    "text.bg_pad_b": ("背景內間隔 下 px", 12.0, 1, None, None),
    "text.bg_radius": ("背景圓角 px", 0.0, 1, 0.0, None),
    "mask.cx": ("遮罩 中心 X", 0.0, 1, None, None),
    "mask.cy": ("遮罩 中心 Y", 0.0, 1, None, None),
    "mask.w": ("遮罩 寬", 1.0, 1, 0.0, None),
    "mask.h": ("遮罩 高", 1.0, 1, 0.0, None),
    "mask.rotation": ("遮罩 旋轉 °", 0.0, 1, None, None),
    "mask.feather": ("遮罩 羽化", 0.0, 1, 0.0, None),
    "clip.volume": ("音量 %", 1.0, 100, 0.0, None),
}
NO_NUMBERS = ("audio", "filter")          # (layer types that have no transform)
PLACE = {"cx": 0.0, "cy": 0.0, "w": 1.0, "h": 1.0}     # an image parameter's placement (the whole frame)


def is_component(comp):
    return bool(comp) and bool(comp.get("component"))


def of_clip(c):
    """The component clip c shows, or None."""
    comp = c.get("compound") if c.get("type") == "compound" else None
    return comp if is_component(comp) else None


def params(comp):
    return (comp or {}).get("params") or []


def param(comp, pid):
    return next((p for p in params(comp) if p["id"] == pid), None)


def props_of(c):
    """What of layer c a parameter can set."""
    out = []
    if c["type"] == "text":
        out += ["content", "text_color"]
    a = c.get("asset")
    if a:
        out += [f for f in ("color", "color2", "stroke_color") if f in assets.fields_of(a.get("family"))]
    if c["type"] == "image":
        out.append("source")
    if c["type"] != "filter":
        out.append("visible")
    return out + check_props_of(c) + [q for q in number_props_of(c) if not q.startswith("params.")] + instance_bind_props(c)


def instance_bind_props(c):
    """The parameters of the component that layer c shows, as props a parameter of the component it is in can set (passed down)."""
    return [f"params.{q['id']}" if q["kind"] == "number" else f"{INST}{q['kind']}:{q['id']}" for q in params(of_clip(c))]


def is_inst_prop(prop):
    return prop.startswith(INST)


def check_props_of(c):
    """The check boxes of layer c's filters a 勾選 parameter can set: each filter's on / off and its own check boxes."""
    out = []
    for e in c.get("effects") or []:
        out.append(FX_ON + e["id"])
        try:
            out += [f"{FX_BOOL}{e['id']}.{q.name}" for q in fx.def_of(e).params if q.type == "bool" and _public(e, q)]
        except Exception:
            pass
    return out


def _public(e, q):
    """Whether parameter q of filter e is one the filter shows: a node effect's own (exposed) ones, not what its nodes are set to."""
    return e.get("filter") != fx.GRAPH or q.panel is None


def is_check_prop(prop):
    return prop.startswith((FX_ON, FX_BOOL))


def effect_id_of(prop):
    """The filter a prop of a layer belongs to (None: it is not a filter's)."""
    if is_check_prop(prop):
        return prop.split(":", 1)[1].split(".")[0]
    if prop.startswith("fx:"):
        return prop[3:].split(".")[0]
    return None


def prop_in(c0, prop, c):
    """What prop of layer c0 is on layer c (None: c has no such thing): a filter's is the one at the same place in c's chain
    (the same filter), for the others it is prop itself."""
    eid = effect_id_of(prop)
    if eid is None or c is c0:
        return prop
    mine = [e["id"] for e in c0.get("effects") or []]
    if eid not in mine:
        return None
    i = mine.index(eid)
    theirs = c.get("effects") or []
    if i >= len(theirs) or theirs[i].get("filter") != c0["effects"][i].get("filter") or \
            theirs[i].get("vfx") != c0["effects"][i].get("vfx"):
        return None
    return prop.replace(eid, theirs[i]["id"], 1)


def prop_alive(c, prop):
    """Whether layer c still has what prop sets (a filter that was deleted leaves its bindings behind, unused)."""
    if is_inst_prop(prop) or prop.startswith("params."):
        return param(of_clip(c), prop.split(":", 2)[2] if is_inst_prop(prop) else prop.split(".", 1)[1]) is not None
    if is_check_prop(prop):
        eid = prop.split(":", 1)[1].split(".")[0]
    elif prop.startswith("fx:"):
        eid = prop.split(".", 1)[0][3:]
    else:
        return True
    return any(e["id"] == eid for e in c.get("effects") or [])


def prop_kind(prop):
    """The kind of parameter that can set prop (a "group.key" number prop is a number)."""
    return "visible" if is_check_prop(prop) else prop.split(":")[1] if is_inst_prop(prop) else "number" if "." in prop else PROPS[prop][0]


def number_info(c, prop):
    """(label, default, factor, lo, hi) of number prop "group.key" of layer c."""
    group, key = prop.split(".", 1)
    if group == "asset":
        info = assets.FIELD_INFO[key]
        lo, hi = assets.hard_range(key)
        return info[0], float(assets._DEFAULTS.get(key, info[2])), 1, lo, hi
    if group.startswith("fx:"):                          # a filter's own number: "fx:<effect id>.<name>"
        e = _effect_of(c, group[3:])
        d = fx.def_of(e)
        q = next(q for q in d.params if q.name == key)
        return f"{d.name}·{q.label}", float(q.default), 1, None, None
    if group.startswith("tvar:"):                        # a text variable's value
        return "變數 " + group[5:], 0.0, 1, None, None
    if group == "params":                                # a component instance's own value
        p = param(c["compound"], key)
        return p["name"], 0.0, 1, None, None
    return NUMBERS[prop]


def _effect_of(c, eid):
    return next(e for e in c.get("effects") or [] if e["id"] == eid)


def _holder_of(c, group):
    """The dict that holds the numbers of `group` of clip c (read only; {} when it has none)."""
    if group == "clip":
        return c
    if group.startswith("fx:"):
        return _effect_of(c, group[3:])["params"]
    if group.startswith("tvar:"):
        return textvars.find(c.get("text") or {}, group[5:]) or {}
    return c.get(group) or {}


def number_props_of(c):
    """The numbers of layer c a number parameter can set."""
    out = []
    t = c["type"]
    if t not in NO_NUMBERS:
        out += [k for k in NUMBERS if k.startswith("transform.")]
    if t == "text":
        out += [k for k in NUMBERS if k.startswith("text.")]
    if c.get("mask"):
        out += [k for k in NUMBERS if k.startswith("mask.")]
    if "volume" in c or t in ("video", "audio"):
        out.append("clip.volume")
    a = c.get("asset")
    if a:
        out += ["asset." + f for f in assets.fields_of(a.get("family"))
                if assets.FIELD_INFO[f][1] == "number" and f not in ("w", "h")]
    for e in c.get("effects") or []:                     # the numbers of its filters
        try:
            out += [f"fx:{e['id']}.{q.name}" for q in fx.def_of(e).params if q.type in ("float", "int") and _public(e, q)]
        except Exception:
            pass
    if c.get("text"):                                    # and of its text variables
        out += [f"tvar:{v['name']}.value" for v in textvars.variables(c["text"]) if v["kind"] in ("number", "float", "time")]
    return out


def instance_props(c):
    """The numbers a component instance's own number parameters are (they take expressions too)."""
    comp = of_clip(c)
    return [f"params.{p['id']}" for p in params(comp) if p["kind"] == "number"] if comp is not None else []


def number_prop_for(c, group, key):
    """The number prop of layer c that the inspector's group / key row is, or None."""
    prop = f"{group}.{key}"
    return prop if prop in number_props_of(c) else None


def prop_label(c, prop):
    """What prop of layer c is called (a shape's colour is its 填充顏色)."""
    if not prop_alive(c, prop):
        return "（已刪除的參數）" if is_inst_prop(prop) or prop.startswith("params.") else "（已刪除的效果）"
    if is_inst_prop(prop):
        return param(c["compound"], prop.split(":", 2)[2])["name"]
    if is_check_prop(prop):
        e = _effect_of(c, prop.split(":", 1)[1].split(".")[0])
        d = fx.def_of(e)
        if prop.startswith(FX_ON):
            return f"{d.name}（開／關）"
        return f"{d.name}·{next(q for q in d.params if q.name == prop.split('.', 1)[1]).label}"
    if "." in prop:
        return number_info(c, prop)[0]
    if prop == "color" and c is not None and "fill" in assets.fields_of((c.get("asset") or {}).get("family")):
        return "填充顏色"
    return PROPS[prop][1]


def layer_index(comp):
    """{clip id: (track, clip)} of the component's content, its groups' clips included."""
    return {c["id"]: (t, c) for t in project.all_tracks(comp["tracks"]) for c in t["clips"]}


def layer_value(track, c, prop):
    """What clip c has for prop at its start (a static component's layers: the picture's moment)."""
    if prop == "content":
        return c["text"].get("content", "")
    if prop == "text_color":
        col = curves.value(c["text"].get("color", [1.0, 1.0, 1.0]), 0)
        return [float(v) for v in col[:3]] + [1.0]
    if prop in ("color", "color2", "stroke_color"):
        return assets.clean(prop, curves.value(c["asset"].get(prop), 0))
    if prop == "source":
        return (c.get("media") or {}).get("path", "")
    if is_check_prop(prop):
        return check_at(c, prop)
    if is_inst_prop(prop):
        return value(c, param(c["compound"], prop.split(":", 2)[2]), 0)
    if "." in prop:
        return number_at(c, prop, 0)
    return not track.get("hidden")


def check_at(c, prop):
    """Check prop of layer c (check_props_of): on or off."""
    eid = prop.split(":", 1)[1].split(".")[0]
    e = _effect_of(c, eid)
    if prop.startswith(FX_ON):
        return not e.get("disabled")
    name = prop.split(".", 1)[1]
    q = next(q for q in fx.def_of(e).params if q.name == name)
    return bool(curves.value(e["params"].get(name, q.default), 0))


def number_at(c, prop, t):
    """Number prop "group.key" of layer c at clip time t, in the units the inspector shows."""
    group, key = prop.split(".", 1)
    _label, dflt, factor, _lo, _hi = number_info(c, prop)
    if group == "params":                                # (its own value, else the component's default)
        own = (c.get("params") or {}).get(key)
        return float(default(c["compound"], param(c["compound"], key)) if own is None else curves.value(own, t))
    h = _holder_of(c, group)
    return float(curves.value(h.get(key, dflt), t)) * factor


def default(comp, p, index=None):
    """A parameter's default: what its first (still there) layer has; a parameter that sets no layer (made by hand, or all its
    layers gone) has the one it was given (p["default"])."""
    index = layer_index(comp) if index is None else index
    for cid, prop in p.get("binds") or []:
        if cid in index and prop_alive(index[cid][1], prop):
            t, c = index[cid]
            return layer_value(t, c, prop)
    return clean(p, p["default"]) if "default" in p else FALLBACK[p["kind"]]


def value(c, p, t, index=None):
    """Instance c's value of parameter p at clip time t (the default when it has none)."""
    own = (c.get("params") or {}).get(p["id"])
    return default(c["compound"], p, index) if own is None else curves.value(own, t)


# -- number parameters' expressions -------------------------------------------------------------------
def expr_key(cid, prop):
    return f"{cid}:{prop}"


def expr_of(p, cid, prop):
    """The expression through which number parameter p sets prop of layer cid ("input": as it is)."""
    return (p.get("exprs") or {}).get(expr_key(cid, prop)) or "input"


def has_exprs(comp):
    """Whether a number parameter of the component has an expression of its own (an instance
    that sets nothing then still shows something other than the layers' values)."""
    return any(p["kind"] == "number" and p.get("exprs") for p in params(comp))


def number_out(p, cid, prop, v, c, t):
    """What number parameter p (valued v) sets prop of layer cid to for instance c at clip time t."""
    text = expr_of(p, cid, prop)
    if text == "input":
        return v
    dur = max(c.get("duration_us") or 1, 1)
    env = {"input": v, "time": t / curves.US, "progress": min(1.0, max(0.0, t / dur)), "duration": dur / curves.US}
    if mapping.is_mapping(text):                         # (a mapping of its value: 映射)
        return mapping.apply(text, v, env)
    return expr.safe(text, env, default=v)


def place_of(c, pid, t=None):
    """Instance c's placement of image parameter pid: its stored dict with what it leaves out
    filled in (kind "place", for the preview's box) - at clip time t: numbers."""
    own = (c.get("places") or {}).get(pid) or {}
    out = dict(PLACE, **own, kind="place")
    return out if t is None else {k: (curves.value(v, t) if k in PLACE else v) for k, v in out.items()}


def bound(comp):
    """{clip id: [(param, prop)]}: what sets each layer."""
    out = {}
    for p in params(comp):
        for cid, prop in p.get("binds") or []:
            out.setdefault(cid, []).append((p, prop))
    return out


# -- an instance's picture --------------------------------------------------------------------------
def content(c, t):
    """What compound clip c draws at clip time t: its compound, or for a component instance
    with values of its own a copy of the component with them put into its layers (only what
    they change is copied; the renderers key their stills on the content). A static compound's
    layers that have an LFO get its value at clip time t: the picture is drawn afresh as the clip plays."""
    comp = _content(c, t)
    if comp is not None and comp.get("static"):
        over = {}
        _lfo_over(comp["tracks"], t, over)
        if over:
            comp = dict(comp, tracks=_subst(comp["tracks"], over))
    return comp


def lfo_layers(tracks):
    """[(layer, prop)] of the layers of tracks (groups' too) whose number an LFO swings."""
    out = []
    for tr in tracks:
        for c in tr["clips"]:
            out += [(c, prop) for prop, text in (c.get("expr") or {}).items() if lfo.is_lfo(text)]
            if project.is_group(c):
                out += lfo_layers(c["tracks"])
    return out


def swings(comp, _seen=()):
    """Whether a static compound has an LFO to swing as it plays: on a layer of its own, or inside a static clip it shows."""
    if not comp or not comp.get("static") or id(comp) in _seen:
        return False
    if lfo_layers(comp["tracks"]):
        return True
    return any(swings(c.get("compound"), _seen + (id(comp),)) for tr in project.all_tracks(comp["tracks"]) for c in tr["clips"]
               if c.get("type") == "compound")


def _lfo_over(tracks, t, over):
    """over: {layer id: [(prop, value)]} of the LFOs of tracks' layers at clip time t (a static compound's layers are at 0); a
    static clip among the layers that has LFOs inside is handed the time too (passed down: its picture is worked out at t)."""
    for tr in project.all_tracks(tracks):
        for c in tr["clips"]:
            if c.get("type") == "compound" and swings(c.get("compound")):
                over.setdefault(c["id"], []).append((LFO_INSIDE, t))
    for c, prop in lfo_layers(tracks):
        try:
            cur = number_at(c, prop, 0)
        except (KeyError, ValueError, TypeError):
            continue                                             # (a prop the layer has not got any more)
        over.setdefault(c["id"], []).append((prop, lfo.safe(c["expr"][prop], t / curves.US, cur, (c.get("duration_us") or 0) / curves.US or None)))
    for c, _prop in lfo_layers(tracks):
        if c["id"] in over and (LFO_DONE, None) not in over[c["id"]]:
            over[c["id"]].append((LFO_DONE, None))               # (its LFOs have been put in: the renderer must not swing it again)
    for ops in over.values():                                    # (its own numbers first: the static clip inside is drawn with them)
        ops.sort(key=lambda op: op[0] == LFO_INSIDE)


LFO_DONE = "lfo!"
LFO_INSIDE = "lfo_inside!"


def _content(c, t):
    comp = c.get("compound")
    own = c.get("params") or {}
    places = c.get("places") or {}
    if not is_component(comp) or not (own or places or has_exprs(comp)):
        return comp
    over = {}
    index = None
    for p in params(comp):
        if p["kind"] == "number":
            if p["id"] not in own and not p.get("exprs"):
                continue
            index = layer_index(comp) if index is None else index
            v = float(value(c, p, t, index))
            for cid, prop in p.get("binds") or []:
                if cid in index:
                    over.setdefault(cid, []).append((prop, number_out(p, cid, prop, v, c, t)))
            continue
        if p["id"] in own:
            v = curves.value(own[p["id"]], t)
            for cid, prop in p.get("binds") or []:
                over.setdefault(cid, []).append((prop, v))
        if p["kind"] == "image" and places.get(p["id"]):
            pl = {k: float(curves.value(places[p["id"]].get(k, d), t)) for k, d in PLACE.items()}
            if pl != PLACE:
                for cid, prop in p.get("binds") or []:
                    if prop == "source":
                        over.setdefault(cid, []).append(("place", pl))
    if not over:
        return comp
    tracks = _subst(comp["tracks"], over)
    return comp if tracks is comp["tracks"] else dict(comp, tracks=tracks)


def _subst(tracks, over):
    """tracks with the values put in (the very list when nothing changed). A clip shown on a
    hidden track goes onto a shown copy of it, the others staying hidden."""
    out, changed = [], False
    for tr in tracks:
        clips, shown, moved = [], [], False
        for c in tr["clips"]:
            k = c
            if project.is_group(c):
                inner = _subst(c["tracks"], over)
                if inner is not c["tracks"]:
                    k = dict(c, tracks=inner)
            for prop, v in over.get(c["id"], ()):
                if prop == "visible":
                    if not v:
                        k = None
                        break
                    if tr.get("hidden"):
                        shown.append(c["id"])
                else:
                    k = _put(k, prop, v)
            if k is not c:
                moved = True
            if k is not None:
                clips.append(k)
        if shown:
            out.append(dict(tr, clips=[k for k in clips if k["id"] not in shown]))
            tr = dict(tr, id=tr["id"] + ":shown", clips=[k for k in clips if k["id"] in shown], hidden=False)
            changed = True
        elif moved:
            tr = dict(tr, clips=clips)
            changed = True
        out.append(tr)
    return out if changed else tracks


def _put(c, prop, v):
    """A copy of layer c with prop set to v."""
    if prop == "content":
        return dict(c, text=dict(c["text"], content=str(v)))
    if prop == "text_color":
        styles = [{k: x for k, x in st.items() if k != "color"} for st in c["text"].get("styles") or []]
        return dict(c, text=dict(c["text"], color=[float(x) for x in v[:3]], styles=styles))
    if prop in ("color", "color2", "stroke_color"):
        return dict(c, asset=dict(c["asset"], **{prop: assets.clean(prop, v)})) if c.get("asset") else c
    if prop == "source":
        size = media_size(v) if v else None
        if size is None:
            return c                                     # (no picture, or one that cannot be read)
        out = {k: x for k, x in c.items() if k != "asset"}
        out["media"] = {"path": v, "width": size[0], "height": size[1]}
        return out
    if prop == "place":
        return dict(c, place=v) if c["type"] == "image" else c
    if prop == LFO_INSIDE:
        return dict(c, compound=content(c, v))
    if prop == LFO_DONE:
        left = {k: x for k, x in (c.get("expr") or {}).items() if not lfo.is_lfo(x)}
        return dict(c, expr=left)
    if not prop_alive(c, prop):
        return c
    if is_inst_prop(prop):
        pid = prop.split(":", 2)[2]
        return dict(c, params=dict(c.get("params") or {}, **{pid: clean(param(c["compound"], pid), v)}))
    if is_check_prop(prop):
        eid = prop.split(":", 1)[1].split(".")[0]
        if prop.startswith(FX_ON):
            return dict(c, effects=[{k: x for k, x in e.items() if k != "disabled"} if e["id"] == eid and v else
                                    dict(e, disabled=True) if e["id"] == eid else e for e in c["effects"]])
        name = prop.split(".", 1)[1]
        return dict(c, effects=[dict(e, params=dict(e["params"], **{name: bool(v)})) if e["id"] == eid else e for e in c["effects"]])
    if "." in prop:
        group, key = prop.split(".", 1)
        _label, _d, factor, lo, hi = number_info(c, prop)
        if group == "asset" and not c.get("asset") or group in ("text", "mask") and not c.get(group):
            return c
        v = float(v) / factor
        v = min(max(v, -1e12 if lo is None else lo), 1e12 if hi is None else hi)
        if group == "clip":
            return dict(c, **{key: v})
        if group == "params":
            return dict(c, params=dict(c.get("params") or {}, **{key: v}))
        if group.startswith("fx:"):
            eid = group[3:]
            return dict(c, effects=[dict(e, params=dict(e["params"], **{key: v})) if e["id"] == eid else e
                                    for e in c["effects"]])
        if group.startswith("tvar:"):
            name = group[5:]
            tx = c["text"]
            return dict(c, text=dict(tx, vars=[dict(x, value=v) if x["name"] == name else x for x in tx["vars"]]))
        base = c.get(group) or {}
        new = dict(base, **{key: v})
        if group == "text" and key == "size":
            new.pop("styles", None)                     # (a size for the whole text replaces per-range ones)
        if group == "text" and key == "bg_pad":
            new.update({f"bg_pad_{k}": v for k in "lrtb"})      # (every side)
        return dict(c, **{group: new})
    return c


_sizes = {}


def media_size(path):
    """(width, height) of a picture file, or None when it cannot be read."""
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return None
    if key not in _sizes:
        try:
            if svgimage.is_svg(path):
                w, h = svgimage.size(path)
            else:
                from PIL import Image
                with Image.open(path) as im:
                    w, h = im.size
            _sizes[key] = (int(round(w)), int(round(h)))
        except Exception:
            _sizes[key] = None
    return _sizes[key]


def clean(p, v):
    """A value as stored for parameter p."""
    kind = p["kind"]
    if kind == "color":
        return [float(x) for x in assets.clean("color", v)]
    if kind == "visible":
        return bool(v)
    if kind == "number":
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
    return "" if v is None else str(v)
