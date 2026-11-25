"""父子綁定: a clip bound to another of its level (c["parent"] = its id) goes where that one goes, turns as it turns and grows as it
grows, as in After Effects: its own 位置, 旋轉 and 縮放 are then in the parent's space (the parent's centre is 0, the parent's turns
and sizes are on top of them). Opacity, the pivot and everything else stay the clip's own. A parent can have a parent. It works for
flat pictures and for the planes, solids, 相機 and 燈光 objects of a 3D 場景; an 空物體 is a handle to move several things by.

A level here is one list of tracks: a group's clips can be bound among themselves, not to a clip outside the group.

Nothing that draws knows about it: bake() writes into a private copy that is going to be drawn (pathfollow.resolve calls it) the
numbers - or, when anything moves, keyframes at every frame - that put each bound clip where it is seen. What is dragged on the
canvas comes back as where it is seen: to_local turns it into the clip's own numbers. bind() and release() change the clip's
numbers so that it stays where it is.

(A parent stretched more one way than the other and turned against its child would shear it; the child keeps its shape and is
stretched along its own axes.)"""
import copy
import math

import numpy as np

from . import camera, components, curves, project, propexpr

PLACE = ("x", "y", "z")
TURN = ("rot_x", "rot_y", "rotation")
SIZE = ("scale", "scale_y")
KEYS = PLACE + TURN + SIZE
FLIPS = ("flip_h", "flip_v")
MOVES = KEYS + ("pivot_x", "pivot_y", "anchor_x", "anchor_y")
MAX_KEYS = 4000


def can_bind(c):
    """Whether clip c has a place of its own, to be bound or to be bound to."""
    return c.get("type") not in ("audio", "filter") and c.get("transform") is not None


def scopes(root):
    """[(tracks, width, height)] of every level under (and with) root, each once."""
    out, seen = [], set()

    def add(tracks, w, h):
        if id(tracks) in seen:
            return
        seen.add(id(tracks))
        out.append((tracks, w, h))
        for t in tracks:
            for c in t["clips"]:
                comp = c.get("compound")
                if comp and "tracks" in comp:
                    add(comp["tracks"], comp.get("width") or w, comp.get("height") or h)
                elif "tracks" in c:
                    add(c["tracks"], w, h)
    add(root["tracks"], root["width"], root["height"])
    for comp in (root.get("compounds") or {}).values():
        add(comp["tracks"], comp.get("width") or root["width"], comp.get("height") or root["height"])
    return out


def clips_of(tracks):
    return {c["id"]: c for t in tracks for c in t["clips"]}


def scope_of(tracks, clip_id):
    """{id: clip} of the level (tracks, or a group in them) that clip_id is in, or None."""
    here = clips_of(tracks)
    if clip_id in here:
        return here
    for c in here.values():
        if project.is_group(c) and "tracks" in c:
            got = scope_of(c["tracks"], clip_id)
            if got is not None:
                return got
    return None


def chain(c, by):
    """The parents of clip c, the nearest first (a ring stops where it comes round)."""
    out, seen = [], {c["id"]}
    while True:
        up = by.get(c.get("parent"))
        if up is None or up["id"] in seen or not can_bind(up):
            return out
        out.append(up)
        seen.add(up["id"])
        c = up


def has_parents(root):
    return any(c.get("parent") for tracks, _w, _h in scopes(root) for t in tracks for c in t["clips"])


def candidates(tracks, clip_id):
    """[(id, clip)] of what clip clip_id can be bound to: the others of its level that are not bound to it."""
    by = scope_of(tracks, clip_id) or {}
    return [(k, c) for k, c in by.items() if k != clip_id and can_bind(c) and all(u["id"] != clip_id for u in chain(c, by))]


# -- numbers ---------------------------------------------------------------------------------------------------------------------
def read(tf, t):
    """The numbers of transform tf at clip time t that a parent changes (and its flips)."""
    v = lambda k, d: float(curves.value(tf.get(k, d), t))
    out = {k: v(k, 0.0) for k in PLACE + TURN}
    out["scale"] = v("scale", 1.0)
    out["scale_y"] = float(curves.value(tf.get("scale_y", tf.get("scale", 1.0)), t))
    out.update({k: bool(tf.get(k)) for k in FLIPS})
    return out


def _signs(v):
    return -1.0 if v["flip_h"] else 1.0, -1.0 if v["flip_v"] else 1.0


def _safe(x):
    return x if abs(x) > 1e-6 else (1e-6 if x >= 0 else -1e-6)


def _frame(up, W, H):
    """(origin px, rotation matrix, per-axis scale with the flips) of a parent seen as `up` = (numbers, (dx, dy) its pivot and
    anchor move its centre by, px)."""
    p, shift = up
    sx, sy = _signs(p)
    origin = np.array([p["x"] * W / 2.0 + shift[0], -p["y"] * H / 2.0 + shift[1], p["z"] * H / 2.0])
    return origin, camera._rot(p["rot_x"], p["rot_y"], p["rotation"]), np.array([p["scale"] * sx, p["scale_y"] * sy, p["scale"]])


def _tilted(p):
    return abs(p["rot_x"]) > 1e-9 or abs(p["rot_y"]) > 1e-9


def _mirrored(angles, p):
    """The angles of something in a mirrored space as they are seen."""
    sx, sy = _signs(p)
    return angles[0] * sy, angles[1] * sx, angles[2] * sx * sy


def compose(up, local, W, H):
    """Where a clip with numbers `local` is seen when it is bound to a parent seen as `up`."""
    p = up[0]
    origin, turn, size = _frame(up, W, H)
    at = origin + turn @ (size * np.array([local["x"] * W / 2.0, -local["y"] * H / 2.0, local["z"] * H / 2.0]))
    out = {"x": at[0] / (W / 2.0), "y": -at[1] / (H / 2.0), "z": at[2] / (H / 2.0)}
    angles = _mirrored([local[k] for k in TURN], p)
    if not _tilted(p):                                # (turned in the picture only: the angles add up, whole turns kept)
        out.update(zip(TURN, (angles[0], angles[1], p["rotation"] + angles[2])))
    else:
        out.update(zip(TURN, camera.euler_of(turn @ camera._rot(*angles))))
    out["scale"], out["scale_y"] = p["scale"] * local["scale"], p["scale_y"] * local["scale_y"]
    out.update({k: bool(local[k]) != bool(p[k]) for k in FLIPS})
    return {k: (float(v) if k in KEYS else v) for k, v in out.items()}


def decompose(up, seen, W, H):
    """compose the other way: the numbers of a clip bound to `up` that is seen as `seen`."""
    p = up[0]
    origin, turn, size = _frame(up, W, H)
    size = np.array([_safe(x) for x in size])
    at = turn.T @ (np.array([seen["x"] * W / 2.0, -seen["y"] * H / 2.0, seen["z"] * H / 2.0]) - origin) / size
    out = {"x": at[0] / (W / 2.0), "y": -at[1] / (H / 2.0), "z": at[2] / (H / 2.0)}
    if not _tilted(p):
        angles = (seen["rot_x"], seen["rot_y"], seen["rotation"] - p["rotation"])
    else:
        angles = camera.euler_of(turn.T @ camera._rot(*[seen[k] for k in TURN]))
    out.update(zip(TURN, _mirrored(angles, p)))                       # (a mirror is its own way back)
    out["scale"], out["scale_y"] = seen["scale"] / _safe(p["scale"]), seen["scale_y"] / _safe(p["scale_y"])
    out.update({k: bool(seen[k]) != bool(p[k]) for k in FLIPS})
    return {k: (float(v) if k in KEYS else v) for k, v in out.items()}


def _at(c, by, T, W, H, names):
    """(numbers, pivot shift) of clip c as it is seen at its level's time T."""
    up = None
    for one in reversed([c] + chain(c, by)):                 # (from the top one down)
        t = T - one["start_us"]
        tf = propexpr.at(one, t, names).get("transform") or {}
        own = read(tf, t)
        if up is not None:
            own = compose(up, own, W, H)
        placed = dict(tf, **own)
        placed.pop("scale_link", None)
        up = (own, project.pivot_shift(placed, t, W, H))
    return up


def seen(tracks, clip_id, T, W, H, names=None):
    """The numbers clip clip_id is seen with at its level's time T."""
    by = scope_of(tracks, clip_id)
    return _at(by[clip_id], by, T, W, H, names)[0]


def parent_at(tracks, clip_id, T, W, H, names=None):
    """What clip clip_id's parent is seen as at time T (compose's `up`), or None for a clip bound to nothing."""
    by = scope_of(tracks, clip_id)
    above = chain(by[clip_id], by) if by else []
    return _at(above[0], by, T, W, H, names) if above else None


def to_local(tracks, clip_id, t, values, W, H, names=None):
    """What to set on clip clip_id (clip time t) so that it is seen with `values` of its transform - a drag's on the canvas.
    The very values for a clip bound to nothing. Numbers a turned parent ties together come out together."""
    by = scope_of(tracks, clip_id)
    c = by.get(clip_id) if by else None
    if c is None or not any(k in values for k in KEYS + FLIPS):
        return values
    T = c["start_us"] + t
    up = parent_at(tracks, clip_id, T, W, H, names)
    if up is None:
        return values
    own = read(propexpr.at(c, t, names).get("transform") or {}, t)
    now = compose(up, own, W, H)
    wanted = dict(now, **{k: v for k, v in values.items() if k in now})
    linked = "scale_y" not in (c.get("transform") or {})
    if linked and "scale" in values and "scale_y" not in values:
        wanted["scale_y"] = now["scale_y"] * values["scale"] / _safe(now["scale"])
    got = decompose(up, wanted, W, H)
    for k in TURN:                                   # (the angle nearest the one it had: no jump by whole turns)
        got[k] += 360.0 * round((own[k] - got[k]) / 360.0)
    out = {k: v for k, v in values.items() if k not in KEYS + FLIPS}
    for k in KEYS + FLIPS:
        if k == "scale_y" and linked and "scale_y" not in values:
            continue
        if k in values or abs(float(got[k]) - float(own[k])) > 1e-6:
            out[k] = got[k]
    return out


# -- binding and letting go --------------------------------------------------------------------------------------------------------
def _keys_of(tf, name):
    p = tf.get(name)
    if p is None and name == "scale_y":
        p = tf.get("scale")
    return [k[0] for k in p["keys"]] if curves.is_animated(p) else []


def _convert(tf, fn, W, H):
    """Rewrite transform tf's numbers through fn (numbers -> numbers, the same at every time): keyframed ones keep their keys -
    and, where each number depends on itself alone, their easing."""
    base = read(tf, 0)
    new = fn(base)
    for group in (PLACE, TURN, SIZE):
        apart, line = True, {}                        # name -> (a, b): new = a * old + b
        for name in group:
            moved = fn(dict(base, **{name: base[name] + 1.0}))
            line[name] = (moved[name] - new[name], new[name] - (moved[name] - new[name]) * base[name])
            apart = apart and all(abs(moved[other] - new[other]) < 1e-7 for other in group if other != name)
        times = sorted({k for name in group for k in _keys_of(tf, name)})
        if group == SIZE:
            linked = "scale_y" not in tf and all(abs(line["scale"][i] - line["scale_y"][i]) < 1e-9 for i in (0, 1))
            names = ("scale",) if linked else SIZE
            if not linked and "scale_y" not in tf:
                tf["scale_y"] = copy.deepcopy(tf.get("scale", 1.0))
                tf["scale_link"] = False
        else:
            names = group
        if apart:
            for name in names:
                a, b = line[name]
                p = tf.get(name)
                if curves.is_animated(p):
                    for k in p["keys"]:
                        k[1] = round(a * k[1] + b, 6)
                        for i in (3, 5):
                            if len(k) > i:
                                k[i] = round(a * k[i], 6)
                elif name in tf or abs(new[name] - (1.0 if name in SIZE else 0.0)) > 1e-9:
                    tf[name] = round(new[name], 6)
        elif not times:
            for name in names:
                if name in tf or abs(new[name]) > 1e-9:
                    tf[name] = round(new[name], 6)
        else:                                          # (numbers a turn mixes: keys at all their times, straight in between)
            rows = [fn(read(tf, t)) for t in times]
            for i in range(1, len(rows)):
                for name in TURN:
                    rows[i][name] += 360.0 * round((rows[i - 1][name] - rows[i][name]) / 360.0)
            made = {name: {"keys": [[t, round(r[name], 6), 0.0, 0.0, 0.0, 0.0] for t, r in zip(times, rows)]} for name in names}
            tf.update(made)
    for k in FLIPS:
        if new[k] or k in tf:
            tf[k] = bool(new[k])


def bind(tracks, clip_id, parent_id, T, W, H, names=None):
    """Bind clip clip_id to parent_id (None: to nothing), its numbers changed so that at its level's time T it stays where it is."""
    by = scope_of(tracks, clip_id)
    if by is None:
        raise ValueError("找不到片段")
    c = by[clip_id]
    if not can_bind(c):
        raise ValueError("這個片段沒有位置可以綁定")
    if parent_id is not None and parent_id not in dict(candidates(tracks, clip_id)):
        raise ValueError("不能綁到這個片段（要在同一層，而且不能繞成一圈）")
    if (c.get("parent") or None) == parent_id:
        return
    tf = c["transform"]
    old = parent_at(tracks, clip_id, T, W, H, names)
    if old is not None:
        _convert(tf, lambda v: compose(old, v, W, H), W, H)
    c.pop("parent", None)
    if parent_id is None:
        return
    new = _at(by[parent_id], by, T, W, H, names)
    _convert(tf, lambda v: decompose(new, v, W, H), W, H)
    c["parent"] = parent_id


def release(tracks, gone, W, H, names=None):
    """Before clips `gone` leave their level: the clips bound to them (that stay) are bound to nothing, where they are."""
    gone = set(gone)
    by = None
    for cid in list(gone):
        by = scope_of(tracks, cid)
        if by is None:
            continue
        for c in by.values():
            if c.get("parent") == cid and c["id"] not in gone:
                up = by[cid]
                T = min(max(c["start_us"], up["start_us"]), up["start_us"] + up["duration_us"])
                bind(tracks, c["id"], None, T, W, H, names)


def sever(tracks, moving, W, H, names=None):
    """Before clips `moving` go together to another level (a group, a compound, out of one): the bindings between them and the
    ones that stay are undone, the clips staying where they are."""
    moving = set(moving)
    for cid in list(moving):
        by = scope_of(tracks, cid)
        if by is None:
            continue
        for c in list(by.values()):
            up = by.get(c.get("parent"))
            if up is not None and (c["id"] in moving) != (up["id"] in moving):
                T = min(max(c["start_us"], up["start_us"]), up["start_us"] + up["duration_us"])
                bind(tracks, c["id"], None, T, W, H, names)


# -- drawing -----------------------------------------------------------------------------------------------------------------------
def _moving(c):
    tf = c.get("transform") or {}
    return any(curves.is_animated(tf.get(k)) for k in MOVES) or any(p.startswith("transform.") for p in propexpr.exprs_of(c))


def bake(root, names_at=None):
    """Write each bound clip of a private copy as it is seen - plain numbers, or keyframes at every frame when it or what it is
    bound to moves - and take the binding away. names_at(T): the names expressions read at level time T. True when there were
    any."""
    fps = float(root.get("play_fps") or root.get("fps") or 30.0)
    done = []                                           # (clip, new numbers): written when all are worked out from the old ones
    for tracks, W, H in scopes(root):
        by = clips_of(tracks)
        for c in by.values():
            above = chain(c, by) if c.get("parent") else []
            if not above:
                continue
            names = (lambda T: names_at(T)) if names_at else (lambda T: None)
            if not any(_moving(k) for k in [c] + above):
                done.append((c, _at(c, by, c["start_us"], W, H, names(c["start_us"]))[0], None))
                continue
            dur = max(int(c.get("duration_us") or 0), 1)
            step = max(1_000_000 / max(fps, 1.0), dur / MAX_KEYS)
            times = [int(i * step) for i in range(int(dur / step) + 1)]
            if times[-1] < dur:
                times.append(dur)
            rows = []
            for t in times:
                row = _at(c, by, c["start_us"] + t, W, H, names(c["start_us"] + t))[0]
                if rows:
                    for k in TURN:
                        row[k] += 360.0 * round((rows[-1][k] - row[k]) / 360.0)
                rows.append(row)
            done.append((c, rows, times))
    for c, got, times in done:
        tf = c["transform"]
        for name in KEYS:
            if times is None:
                tf[name] = round(got[name], 6)
                continue
            values = [round(r[name], 6) for r in got]
            tf[name] = values[0] if max(values) - min(values) < 1e-9 else \
                {"keys": [[t, v, 0.0, 0.0, 0.0, 0.0] for t, v in zip(times, values)]}
        first = got if times is None else got[0]
        for k in FLIPS:
            tf[k] = first[k]
        tf["scale_link"] = False
        if c.get("expr"):                               # (worked in already)
            c["expr"] = {p: e for p, e in c["expr"].items() if not (p.startswith("transform.") and p.split(".")[1] in KEYS)}
        c.pop("parent", None)
    return bool(done)
