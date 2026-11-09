"""Handles on the preview for the parameters of an effect that stand for a place, a size or a turn on the picture: the centre of a
swirl, the radius of a bulge, the angle of a spin blur, where a Translate moves to... (編輯控制點 of an effect in the 效果 tab).

Everything here is in the clip's own frame: the origin at the middle of the picture the effects work on, bw x bh canvas px,
y down - the preview maps it to the canvas with the clip's box. A spec says which parameter is what:

  point   a vec2 in the picture's uv (0 - 1, y down; "up": y from the bottom, as Blender's Sun Beams)
  offset  a vec2 in px that moves the picture ("origin": the point param it is measured from; else the middle)
  radius  a float in picture heights, round the point param "about"
  angle   a float in degrees, round "about": the handle sits on the circle of "reach" picture heights (of the param "reach_of"
          times "reach" when that is given), at "start" degrees (screen angle, clockwise from the right) turned by the value
          times "sign"

"when": (parameter, value) - the handle is there only while that parameter has that value."""
import math

from . import curves, fx


def point(param, up=False, label=""):
    return {"kind": "point", "param": param, "up": up, "label": label}


def offset(param, origin=None):
    return {"kind": "offset", "param": param, "origin": origin}


def radius(param, about):
    return {"kind": "radius", "param": param, "about": about}


def angle(param, about, sign=1, start=0.0, reach=0.3, reach_of=None):
    return {"kind": "angle", "param": param, "about": about, "sign": sign, "start": start, "reach": reach, "reach_of": reach_of}


SPECS = {
    "builtin:bulge": [point("center"), radius("radius", "center")],
    "builtin:swirl": [point("center"), radius("radius", "center"), angle("angle", "center", reach=0.6, reach_of="radius")],
    "builtin:ripple": [point("center")],
    "builtin:kaleidoscope": [point("center"), angle("rotation", "center", sign=-1, reach=0.3)],
    "builtin:zoom_pulse": [point("center")],
    "builtin:zoom_blur": [point("center")],
    "builtin:spin_blur": [point("center"), angle("angle", "center", reach=0.3)],
    "builtin:lens_flare": [point("position")],
    "builtin:blender_glare": [dict(point("sun_position", up=True), when=("type", "Sun Beams"))],
    "builtin:push_in": [point("from", label="起"), point("to", label="終")],
    "builtin:translate": [offset("offset")],
    "builtin:nodes/split": [point("position", up=True)],
    "builtin:transform": [offset("position", "anchor"), angle("rotation", "anchor", start=-90.0, reach=0.35)],
}


def node_effect(e, nid):
    """Node nid of node effect e as an effect of its own (its parameters without the node's name), or None when it has no
    handles: not a filter node, or its place is set by a link or by a parameter of the effect."""
    from . import nodegraph
    g = e.get("graph") or {}
    node = (g.get("nodes") or {}).get(nid)
    if node is None or node.get("type") != nodegraph.FILTER or not has_gizmo(node["ref"]):
        return None
    taken = {l["socket"][len(nodegraph.PARAM):] for l in g.get("links") or [] if l["to"] == nid and l["socket"].startswith(nodegraph.PARAM)}
    own = {k[len(nid) + 1:]: v for k, v in e["params"].items() if k.startswith(nid + ".")}
    out = {"id": e["id"], "filter": node["ref"], "params": own, "taken": taken}
    return out


def spec_of(ref):
    return SPECS.get(ref) or []


def has_gizmo(ref):
    return ref in SPECS


def _value(e, d, name, t):
    p = next((q for q in d.params if q.name == name), None)
    if p is None:
        return None, None
    return curves.value(e["params"].get(name, p.default), t), p


def _vec(v, n=2):
    try:
        return [float(x) for x in v][:n]
    except (TypeError, ValueError):
        return None


def local_of_uv(uv, up, bw, bh):
    """Clip-local point of a picture uv (y down, or from the bottom when `up`)."""
    return ((uv[0] - 0.5) * bw, ((1.0 - uv[1] if up else uv[1]) - 0.5) * bh)


def uv_of_local(pt, up, bw, bh):
    v = pt[1] / bh + 0.5
    return (pt[0] / bw + 0.5, 1.0 - v if up else v)


ANCHORS = ("anchor",)                       # vec2 params that are measured from the middle in picture widths / heights (not a uv)


def centre_of(e, d, name, t, bw, bh):
    """Clip-local point a point / anchor param stands for ((0, 0) when it has none)."""
    if name is None:
        return (0.0, 0.0)
    v, p = _value(e, d, name, t)
    uv = _vec(v)
    if uv is None:
        return (0.0, 0.0)
    if name in ANCHORS:
        return (uv[0] * bw, uv[1] * bh)
    return local_of_uv(uv, False, bw, bh)


def origin_of(e, d, item, t, bw, bh):
    """Clip-local origin an offset is measured from: the middle, or the anchor (a vec2 from the middle in picture widths / heights)."""
    if not item.get("origin"):
        return (0.0, 0.0)
    v, _ = _value(e, d, item["origin"], t)
    a = _vec(v)
    return (a[0] * bw, a[1] * bh) if a else (0.0, 0.0)


def shown(e, item):
    """Whether the handle is there with the settings the effect has (its "when")."""
    when = item.get("when")
    return when is None or e["params"].get(when[0]) == when[1]


def handles(e, t, bw, bh):
    """[{"kind", "param", "local": (x, y), "item", ...}] the handles of effect e at clip time t on a bw x bh picture, in their order
    (the preview takes the last under the pointer first: a point is under a radius or an angle that sits on the same spot)."""
    d = fx.def_of(e)
    out = []
    for item in spec_of(e["filter"]):
        if not shown(e, item) or item["param"] in e.get("taken", ()):
            continue
        v, p = _value(e, d, item["param"], t)
        if p is None or v is None:
            continue
        kind = item["kind"]
        if kind == "point":
            uv = _vec(v)
            if uv:
                out.append({"kind": "point", "item": item, "param": item["param"], "label": item.get("label", ""),
                            "local": local_of_uv(uv, item["up"], bw, bh), "range": (p.lo, p.hi)})
        elif kind == "offset":
            xy = _vec(v)
            if xy:
                ox, oy = origin_of(e, d, item, t, bw, bh)
                out.append({"kind": "offset", "item": item, "param": item["param"], "local": (ox + xy[0], oy + xy[1]),
                            "origin": (ox, oy), "range": (p.lo, p.hi)})
        elif kind == "radius":
            cx, cy = centre_of(e, d, item["about"], t, bw, bh)
            r = float(v)
            out.append({"kind": "radius", "item": item, "param": item["param"], "local": (cx + r * bh, cy), "centre": (cx, cy),
                        "range": (p.lo, p.hi)})
        elif kind == "angle":
            cx, cy = centre_of(e, d, item["about"], t, bw, bh)
            reach = item["reach"]
            if item["reach_of"]:
                rv, _ = _value(e, d, item["reach_of"], t)
                reach *= float(rv)
            phi = math.radians(item["start"] + item["sign"] * float(v))
            out.append({"kind": "angle", "item": item, "param": item["param"], "centre": (cx, cy), "reach": reach * bh,
                        "local": (cx + math.cos(phi) * reach * bh, cy + math.sin(phi) * reach * bh), "value": float(v),
                        "range": (p.lo, p.hi)})
    return out


def _clamp(v, lo, hi):
    return min(max(v, lo), hi)


def dragged(h, pt, bw, bh, state, snap=True, turn_snap=None):
    """{param: value} for handle h (from handles()) dragged to the clip-local point pt. state: a dict that belongs to the drag
    (the angle is followed round, turn after turn); snap: points settle on the middle (and a third) of the picture;
    turn_snap(degrees) -> degrees, for the angle."""
    kind, item = h["kind"], h["item"]
    lo, hi = h["range"]
    if kind == "point":
        u, v = uv_of_local(pt, item["up"], bw, bh)
        if snap:
            u, v = [0.5 if abs(x - 0.5) < 0.012 else x for x in (u, v)]
        return {item["param"]: [round(_clamp(u, lo, hi), 4), round(_clamp(v, lo, hi), 4)]}
    if kind == "offset":
        ox, oy = h["origin"]
        return {item["param"]: [round(_clamp(pt[0] - ox, lo, hi), 1), round(_clamp(pt[1] - oy, lo, hi), 1)]}
    if kind == "radius":
        cx, cy = h["centre"]
        return {item["param"]: round(_clamp(math.hypot(pt[0] - cx, pt[1] - cy) / bh, lo, hi), 4)}
    cx, cy = h["centre"]                                       # angle
    phi = math.degrees(math.atan2(pt[1] - cy, pt[0] - cx))
    last = state.setdefault("phi", math.degrees(math.atan2(h["local"][1] - cy, h["local"][0] - cx)))      # (from where the handle is)
    state.setdefault("value", h["value"])
    step = (phi - last + 180.0) % 360.0 - 180.0                # (the way round is the short one: the value goes on past 180)
    state["phi"] = phi
    value = state["value"] + item["sign"] * step
    value = _clamp(value, lo, hi)
    state["value"] = value
    shown_value = turn_snap(value) if turn_snap else value
    return {item["param"]: round(_clamp(shown_value, lo, hi), 2)}
