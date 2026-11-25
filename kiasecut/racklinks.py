"""Links (綁定全局參數) of a clip's values that are no numbers to parameters of the global parameter rack
(rack.py): clip["links"] {prop: parameter name}. While the clip is drawn the prop is what the parameter
is at that moment of the timeline; a link to a parameter that is gone, or of another kind, does nothing.
(Numbers follow the rack through expressions and 映射 instead, propexpr.py.)

props of a clip c, and the kinds of parameter each takes:
    content                     a text's words                       text; menu (the choice's name)
    text_color, tc:<field>      its fill / outline, shadow and       color
                                background colours
    font                        its font                             font
    ac:<field>                  a built-in asset's colour            color
    inst:<kind>:<id>            a component's own text / colour /    text, menu / color / bool
                                switch
    fxon:<effect>               a filter on / off                    bool
    fxb:<effect>.<name>         a filter's check box                 bool
    fxp:<effect>.<name>         a filter's colour, menu, vector,     the same kind; text, menu for words
                                words or font
"""
from . import assets, components, fx, rack, textlayout

FXP = "fxp:"
TEXT_COLORS = {"stroke_color": "外框顏色", "shadow_color": "陰影顏色", "bg_color": "背景顏色"}
WORDS = ("text", "menu")
PARAM_KINDS = {"color": ("color",), "vec2": ("vec2",), "vec3": ("vec3",), "menu": ("menu",),
               "string": WORDS, "font": ("font",)}           # a filter parameter's type -> the rack kinds it takes
INST_KINDS = {"text": WORDS, "color": ("color",), "visible": ("bool",)}


def _effect(c, eid):
    return next((e for e in c.get("effects") or [] if e["id"] == eid), None)


def _fx_param(e, name):
    """Parameter name of filter e, if the filter shows it (None otherwise)."""
    try:
        q = next((q for q in fx.def_of(e).params if q.name == name), None)
    except Exception:
        return None
    return q if q is not None and components._public(e, q) else None


def _asset_colors(c):
    a = c.get("asset")
    if not a:
        return []
    fields = ("color",) + tuple(assets.fields_of(a.get("family")))
    return [f for f in dict.fromkeys(fields) if f in assets.FIELD_INFO and assets.FIELD_INFO[f][1] == "color"]


def kinds(c, prop):
    """The kinds of rack parameter that prop of clip c takes (() when it takes none)."""
    if prop == "content":
        return WORDS if c.get("text") else ()
    if prop == "text_color" or prop.startswith("tc:") and prop[3:] in TEXT_COLORS:
        return ("color",) if c.get("text") else ()
    if prop == "font":
        return ("font",) if c.get("text") else ()
    if prop.startswith("ac:"):
        return ("color",) if prop[3:] in _asset_colors(c) else ()
    if components.is_inst_prop(prop):
        return INST_KINDS.get(prop.split(":")[1], ()) if components.prop_alive(c, prop) else ()
    if prop.startswith(components.FX_ON):
        return ("bool",) if _effect(c, prop[len(components.FX_ON):]) else ()
    if prop.startswith((components.FX_BOOL, FXP)):
        eid, _, name = prop.split(":", 1)[1].partition(".")
        e = _effect(c, eid)
        q = _fx_param(e, name) if e else None
        if q is None:
            return ()
        if prop.startswith(components.FX_BOOL):
            return ("bool",) if q.type == "bool" else ()
        return PARAM_KINDS.get(q.type, ())
    return ()


def _asset_prop(c, prop):
    """The prop a right-click on a component's field names (components.PROPS) as the link prop it is here."""
    return "ac:" + prop if prop in ("color", "color2", "stroke_color") and c.get("asset") else prop


def label(c, prop):
    if prop == "content":
        return "文字內容"
    if prop == "text_color":
        return "文字顏色"
    if prop == "font":
        return "字體"
    if prop.startswith("tc:"):
        return TEXT_COLORS.get(prop[3:], prop)
    if prop.startswith("ac:"):
        return assets.FIELD_INFO.get(prop[3:], (prop,))[0]
    if prop.startswith(FXP):
        eid, _, name = prop[len(FXP):].partition(".")
        e = _effect(c, eid)
        q = _fx_param(e, name) if e else None
        return f"{fx.def_of(e).name}·{q.label}" if q is not None else "（已刪除的效果）"
    return components.prop_label(c, prop)


def current(c, prop, t_us):
    """What clip c itself has for prop at clip time t_us, as (rack kind, value, menu items) - what a new
    parameter made from the field starts as; None when prop takes no link."""
    from . import curves
    ks = kinds(c, prop)
    if not ks:
        return None
    kind, items, v = ks[0], [], None
    at = lambda x, d: curves.value(d if x is None else x, t_us)
    if prop == "content":
        v = c["text"].get("content", "")
    elif prop == "text_color":
        v = at(c["text"].get("color"), [1.0, 1.0, 1.0])
    elif prop.startswith("tc:"):
        v = at(c["text"].get(prop[3:]), textlayout.DECOR.get(prop[3:], [0.0, 0.0, 0.0, 1.0]))
    elif prop == "font":
        from .project import DEFAULT_FONT
        v = at(c["text"].get("font_path"), DEFAULT_FONT)
    elif prop.startswith("ac:"):
        v = _rgba(assets.clean(prop[3:], at(c["asset"].get(prop[3:]), None)))
    elif components.is_inst_prop(prop):
        pid = prop.split(":", 2)[2]
        p = components.param(c["compound"], pid)
        v = components.value(c, p, t_us)
    elif prop.startswith(components.FX_ON):
        v = not _effect(c, prop[len(components.FX_ON):]).get("disabled")
    else:
        eid, _, name = prop.split(":", 1)[1].partition(".")
        e = _effect(c, eid)
        q = _fx_param(e, name)
        v = at(e["params"].get(name), q.default)
        if q.type == "menu":
            items = list(q.items)
            v = items[fx.menu_index(q, v)]
        elif q.type == "color":
            v = (list(v) + [1.0])[:4]
    try:
        v = rack.clean(kind, v, items)
    except (ValueError, TypeError):
        v = rack.default_value(kind, items)
    return kind, v, items


def _rgba(v):
    """A colour as [r, g, b, a] 0 - 1 from a list or "#rrggbb[aa]"."""
    if isinstance(v, str):
        t = v.lstrip("#")
        got = [int(t[i:i + 2], 16) / 255 for i in range(0, len(t) - 1, 2)]
        return (got + [1.0])[:4]
    return list(v)


def prop_in(c0, prop, c):
    """What prop of clip c0 is on clip c of the same selection (None: c has no such thing): a filter's is the
    one at the same place in c's chain."""
    if prop.startswith(FXP):
        eid, _, name = prop[len(FXP):].partition(".")
        got = components.prop_in(c0, f"fx:{eid}.{name}", c)
        prop = None if got is None else FXP + got[3:]
    else:
        prop = components.prop_in(c0, prop, c)
    return prop if prop is not None and kinds(c, prop) else None


def put(c, prop, kind, v):
    """A copy of clip c with prop set to v, a value of a rack parameter of kind."""
    if prop == "content":
        return components._put(c, "content", v)
    if prop == "text_color":
        return components._put(c, "text_color", v)
    if prop.startswith("tc:") or prop == "font":
        field = "font_path" if prop == "font" else prop[3:]
        tx = dict(c["text"], **{field: v if prop == "font" else list(v)})
        if tx.get("styles"):                                  # (a value for the whole text replaces per-range ones)
            tx["styles"] = [{k: x for k, x in st.items() if k != field} for st in tx["styles"]]
        return dict(c, text=tx)
    if prop.startswith("ac:"):
        return dict(c, asset=dict(c["asset"], **{prop[3:]: assets.clean(prop[3:], list(v))}))
    if prop.startswith(FXP):
        eid, _, name = prop[len(FXP):].partition(".")
        q = _fx_param(_effect(c, eid), name)
        if q.type == "menu":                                  # (by the choice's name; a name the filter has not: its number)
            if v[0] not in q.items:
                v = q.items[min(v[1], len(q.items) - 1)]
            else:
                v = v[0]
        elif isinstance(v, list):
            v = list(v)
        return dict(c, effects=[dict(e, params=dict(e["params"], **{name: v})) if e["id"] == eid else e
                                for e in c["effects"]])
    return components._put(c, prop, v)


def apply(c, names):
    """Clip c with each of its links' parameters put in (names: rack.values of the moment): the very clip
    when none applies."""
    typed = getattr(names, "typed", None)
    if not typed:
        return c
    out = c
    for prop, name in (c.get("links") or {}).items():
        got = typed.get(name)
        if got is None:
            continue
        kind, v = got
        try:
            if kind not in kinds(out, prop):
                continue
            if prop.startswith(FXP) and _fx_param(_effect(out, prop[len(FXP):].partition(".")[0]),
                                                  prop.partition(".")[2]).type == "menu":
                v = (v, int(names[name]))
            out = put(out, prop, kind, v)
        except (KeyError, ValueError, TypeError, IndexError, StopIteration):
            continue
    return out
