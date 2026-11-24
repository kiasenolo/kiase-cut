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


PARTICLES = "builtin:particle_system"
CAMERA = "builtin:camera"                    # (not a filter: the 攝影機 of a group or compound clip, handles that move it)
ACCEL_SCALE = 0.25                           # the gravity / wind arrow: a px of it is this many px/s² (of a 1080-high canvas)
SPEED_SCALE = 0.25                           # the velocity handle: its distance is the way a particle goes in this many seconds (without forces)


def particle_effect(clip):
    """The particle system of a particle object (clip["asset"]), as an effect with its own handles - None for any other clip."""
    from . import assets
    p = clip.get("asset")
    if not p or p.get("family") != "particles":
        return None
    e = assets.particle_effect(p)
    e["asset"] = True                        # (its handles edit the object's fields, not an effect's parameters)
    return e


def camera_effect(clip, W, H):
    """The camera of a group or compound clip, as an effect with its own handles - None when it has none on. W x H: the size of its picture."""
    from . import camera
    cam = clip.get("camera")
    if camera.is_clip(clip):                           # a 相機 object: its place is the clip's transform, the rest its own; handles over the picture
        tf = clip.get("transform") or {}
        merged = dict(cam, on=True, **{k: tf[k] for k in ("x", "y", "z") if k in tf})
        if not any(k in cam for k in ("tx", "ty", "tz")):                  # (turned by its angles, not looking at a target)
            merged.update({k: tf.get(k, 0.0) for k in ("rot_x", "rot_y", "rotation")})
        return {"id": "camera", "filter": CAMERA, "params": {}, "camera": merged, "W": W, "H": H, "asset": True, "canvas": True}
    if clip.get("type") not in ("group", "compound") or not camera.on(cam):
        return None
    if clip["type"] == "compound":
        comp = clip.get("compound") or {}
        W, H = comp.get("width", W), comp.get("height", H)
    return {"id": "camera", "filter": CAMERA, "params": {}, "camera": cam, "W": W, "H": H, "asset": True}


def camera_handles(e, t, bw, bh):
    """Four handles that stay where they are on the picture - the camera looks at its target, so that is always the middle - and change
    the camera by how far they are dragged: the middle moves it sideways (平移), one beside goes round the target (環繞), one on the other
    side goes nearer or farther (推拉), the one above widens or narrows the angle of view (視角). Clip-local px of the picture."""
    from . import camera
    cam, W, H = e["camera"], e["W"], e["H"]
    k = W / max(bw, 1e-9)                                         # picture px per clip px
    r = 0.22 * bh

    def drag(fn, home):
        return lambda pt, st, snap: {key: round(v, 4) for key, v in fn((pt[0] - home[0]) * k, (pt[1] - home[1]) * k).items()}
    fov0 = float(curves.value(cam.get("fov", camera.FOV), t))
    pos = {"pan": (0.0, 0.0), "orbit": (r, 0.0), "dolly": (-r, 0.0), "fov": (0.0, -r)}
    return [
        _custom("pan", pos["pan"], "cross", "平移", drag(lambda dx, dy: camera.track(cam, t, W, H, dx, dy), pos["pan"])),
        _custom("orbit", pos["orbit"], "round", "環繞", drag(lambda dx, dy: camera.orbit(cam, t, W, H, dx, dy), pos["orbit"]), pos["pan"]),
        _custom("dolly", pos["dolly"], "round", "推拉", drag(lambda dx, dy: camera.dolly(cam, t, W, H, dy), pos["dolly"]), pos["pan"]),
        _custom("fov", pos["fov"], "round", "視角",
                drag(lambda dx, dy: {"fov": min(150.0, max(5.0, fov0 - dy / H * 100.0))}, pos["fov"]), pos["pan"]),
    ]


def _custom(id_, local, style, label, apply, origin=None, **more):
    return dict({"kind": "custom", "item": {"kind": "custom"}, "param": id_, "id": id_, "local": local, "style": style, "label": label,
                 "apply": apply, "range": (0.0, 0.0), "from": origin}, **more)


def particle_handles(e, t, bw, bh):
    """The handles of a particle system e: its place, the size and turn of its emitter, where the particles go (a velocity handle and the
    two edges of the spread), the gravity and the wind as one arrow, the floor. All in the clip-local px of the picture."""
    d = fx.def_of(e)

    def val(name, default=0.0):
        v, par = _value(e, d, name, t)
        if v is not None and par.type == "menu":
            v = fx.menu_index(par, v)
        return default if v is None else v
    k = bh / 1080.0
    ox, oy = float(val("origin_x", 0.5)), float(val("origin_y", 0.5))
    o = ((ox - 0.5) * bw, (oy - 0.5) * bh)
    emitter, rot = int(val("emitter")), math.radians(float(val("erot")))
    ax, ay = (math.cos(rot), math.sin(rot)), (-math.sin(rot), math.cos(rot))
    out = []

    def at(v, along):
        return (o[0] + v[0] * along, o[1] + v[1] * along)

    def along(pt, v):
        return (pt[0] - o[0]) * v[0] + (pt[1] - o[1]) * v[1]

    out.append(_custom("origin", o, "cross", "發射位置",
                       lambda pt, st, snap: {"origin_x": round(pt[0] / bw + 0.5, 4), "origin_y": round(pt[1] / bh + 0.5, 4)}))
    if emitter in (1, 2, 3, 5):
        w = float(val("ewidth"))
        out.append(_custom("ewidth", at(ax, w * k / 2), "square", "寬",
                           lambda pt, st, snap: {"ewidth": round(min(4000.0, abs(along(pt, ax)) * 2 / k), 1)}, o))
    if emitter == 3:
        h = float(val("eheight"))
        out.append(_custom("eheight", at(ay, h * k / 2), "square", "高",
                           lambda pt, st, snap: {"eheight": round(min(4000.0, abs(along(pt, ay)) * 2 / k), 1)}, o))
    if emitter in (1, 3):
        reach = float(val("ewidth")) * k / 2 + 0.06 * bh
        out.append(_custom("erot", at(ax, reach), "round", "旋轉",
                           lambda pt, st, snap: {"erot": round(math.degrees(math.atan2(pt[1] - o[1], pt[0] - o[0])), 1)}, o))
    speed = float(val("speed"))
    length = min(max(speed * k * SPEED_SCALE, 0.07 * bh), 0.45 * bh)
    if bool(val("outward")):                                   # (away from the place: only how fast)
        out.append(_custom("speed", (o[0] + length, o[1]), "round", "初速",
                           lambda pt, st, snap: {"speed": round(min(4000.0, max(0.0, abs(pt[0] - o[0]) / (k * SPEED_SCALE))), 1)}, o))
    else:
        ang, spread = math.radians(float(val("angle"))), float(val("spread"))

        def direction(a):
            return (math.sin(a), -math.cos(a))

        def aim(pt, st, snap):
            dx, dy = pt[0] - o[0], pt[1] - o[1]
            a = math.degrees(math.atan2(dx, -dy))
            if snap:
                a = round(a / 5) * 5 if abs(a - round(a / 15) * 15) > 1.5 else round(a / 15) * 15
            return {"angle": round(a, 1), "speed": round(min(4000.0, math.hypot(dx, dy) / (k * SPEED_SCALE)), 1)}

        def edge(pt, st, snap):
            a = math.degrees(math.atan2(pt[0] - o[0], -(pt[1] - o[1]))) - math.degrees(ang)
            a = abs((a + 180.0) % 360.0 - 180.0)
            return {"spread": round(min(360.0, a * 2), 1)}
        for sign, name in ((1, "spread_b"), (-1, "spread_a")):
            out.append(_custom(name, at(direction(ang + sign * math.radians(spread) / 2), length), "square", "散開" if sign > 0 else "", edge, o))
        out.append(_custom("aim", at(direction(ang), length), "round", "方向和初速", aim, o))
    anchor = (0.38 * bw, -0.34 * bh)
    wind, gravity = float(val("wind")), float(val("gravity"))
    out.append(_custom("accel", (anchor[0] + wind * k * ACCEL_SCALE, anchor[1] + gravity * k * ACCEL_SCALE), "arrow", "重力／風",
                       lambda pt, st, snap: {"wind": round(max(-2000.0, min(2000.0, (pt[0] - anchor[0]) / (k * ACCEL_SCALE))), 0),
                                             "gravity": round(max(-3000.0, min(3000.0, (pt[1] - anchor[1]) / (k * ACCEL_SCALE))), 0)}, anchor))
    if bool(val("floor_on")):
        fy = (float(val("floor_y")) - 0.5) * bh
        out.append(_custom("floor", (0.0, fy), "hline", "地面",
                           lambda pt, st, snap: {"floor_y": round(max(0.0, min(1.0, pt[1] / bh + 0.5)), 4)}, None, span=bw))
    return out


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
    if e["filter"] == PARTICLES:
        return particle_handles(e, t, bw, bh)
    if e["filter"] == CAMERA:
        return camera_handles(e, t, bw, bh)
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
    if kind == "custom":                                       # (a particle system's: it knows what it changes)
        return h["apply"](pt, state, snap)
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
