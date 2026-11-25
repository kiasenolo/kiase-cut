"""Edits of a project's sound processing (soundfx.py), each fn(level, ...) as edit.py's are.

A target says whose chain or channel is meant: ("clip", id), ("track", id), ("bus", id) or
("master", ""). level: the open level - the project (its root) or a compound.
"""
import copy
import math
import uuid

from . import curves, edit, expr, mapping, project, soundfx, soundmeter, soundnodes, soundnumbers

PAN_RANGE = (-1.0, 1.0)


def mix_holder(level):
    """The compound that keeps the level's buses and master."""
    if "active_timeline" in level:
        return level["compounds"][level["active_timeline"]]
    return level


def buses(level):
    return mix_holder(level).get("buses") or []


def bus(level, bus_id):
    b = next((b for b in buses(level) if b["id"] == bus_id), None)
    if b is None:
        raise edit.EditError("沒有這個 bus")
    return b


def holder(level, target, make=False):
    """The dict that target's sound_effects (and, for a channel, its fader and routes) are
    kept in. make: the master's is made when the level has none yet."""
    kind, ident = target
    if kind == "clip":
        return edit.find(level, ident)[1]
    if kind == "track":
        return edit.track_by_id(level, ident)
    if kind == "bus":
        return bus(level, ident)
    mix = mix_holder(level)
    if make:
        return mix.setdefault(soundfx.MASTER, {})
    return mix.get(soundfx.MASTER) or {}


def chain(level, target):
    return holder(level, target).get("sound_effects") or []


def effect(level, target, effect_id):
    """An entry of target's chain; "<effect id>/<node id>": a node of a graph's (an effect
    node reads as an entry does, so its parameters are edited the same way)."""
    effect_id, _, nid = effect_id.partition("/")
    e = next((e for e in chain(level, target) if e["id"] == effect_id), None)
    if e is None:
        raise edit.EditError("找不到這個聲音效果")
    if not nid:
        return e
    node = (e.get("graph") or {}).get("nodes", {}).get(nid)
    if node is None:
        raise edit.EditError("找不到這個節點")
    return node


def sounding(c):
    """Whether clip c makes sound (what can take sound effects)."""
    if c["type"] in ("audio", "video"):
        return bool(c.get("media"))
    return project.is_group(c) or (c["type"] == "compound" and not project.is_static(c))


def new_id():
    return "s" + uuid.uuid4().hex[:8]


# -- chains ---------------------------------------------------------------------------------------
def add_effect(level, target, kind, at=None):
    """Put a new effect of this kind on target's chain (at the end, or at place at). Returns
    its id."""
    if kind not in soundfx.EFFECTS and kind != soundfx.GRAPH:
        raise edit.EditError("沒有這個聲音效果")
    if target[0] == "clip" and not sounding(edit.find(level, target[1])[1]):
        raise edit.EditError("這個片段沒有聲音")
    es = holder(level, target, make=True).setdefault("sound_effects", [])
    e = soundfx.new_effect(kind, new_id())
    es.insert(len(es) if at is None else max(0, min(at, len(es))), e)
    return e["id"]


def _prune(level, target):
    h = holder(level, target)
    if not h.get("sound_effects"):
        h.pop("sound_effects", None)
    if target[0] == "master" and not h:
        mix_holder(level).pop(soundfx.MASTER, None)


def remove_effect(level, target, effect_id):
    holder(level, target).get("sound_effects", []).remove(effect(level, target, effect_id))
    _prune(level, target)


def move_effect(level, target, effect_id, to):
    """Move an effect to place `to` of its chain."""
    e = effect(level, target, effect_id)
    es = holder(level, target)["sound_effects"]
    es.remove(e)
    es.insert(max(0, min(to, len(es))), e)


def set_enabled(level, target, effect_id, on):
    e = effect(level, target, effect_id)
    if on:
        e.pop("enabled", None)
    else:
        e["enabled"] = False


def set_side(level, target, effect_id, side_id):
    """The channel an effect listens to (None: itself)."""
    e = effect(level, target, effect_id)
    if side_id:
        e["side"] = {"id": side_id}
    else:
        e.pop("side", None)


def _spec(e, name):
    p = soundfx.spec(e, name)
    if p is None:
        raise edit.EditError("這個效果沒有這個參數")
    return p


def set_expr(level, target, effect_id, name, text):
    """What a parameter follows: an expression, a 映射 of a global parameter, or "" (nothing)."""
    e = effect(level, target, effect_id)
    _spec(e, name)
    if mapping.is_mapping(text):
        why = mapping.check(text)
        text = copy.deepcopy(text)
    else:
        text = str(text).strip()
        why = expr.check(text) if text else None
    if why:
        raise edit.EditError(f"表達式有問題：{why}")
    if text:
        e.setdefault("expr", {})[name] = text
    else:
        (e.get("expr") or {}).pop(name, None)
        if not e.get("expr"):
            e.pop("expr", None)


def bind(root, level, target, effect_id, name, text):
    """set_expr, refused when a global parameter's meter would come to hear its own number. level:
    the compound of root being edited. (A history step: what it raises is undone.)"""
    heard = soundmeter.loops(root)
    set_expr(level, target, effect_id, name, text)
    try:
        soundmeter.refuse_new_loops(root, heard)
    except soundmeter.MeterError as exc:
        raise edit.EditError(str(exc)) from None


def _set_number(h, key, value, t):
    """h[key] = value; a keyframed one gets its key at t set, or a new key there."""
    p = h.get(key)
    if not curves.is_animated(p):
        h[key] = value
        return
    if t is None:
        raise edit.EditError("有關鍵幀的參數要指定時間")
    i = edit.key_at(p, t)
    if i is None:
        p["keys"].append([int(t), value, 0.0, 0.0, 0.0, 0.0])
        p["keys"].sort(key=lambda k: k[0])
    else:
        p["keys"][i][1] = value


def _toggle_number(h, key, default, t):
    p = h.get(key, default)
    if not curves.is_animated(p):
        h[key] = {"keys": [[int(t), p, 0.0, 0.0, 0.0, 0.0]]}
        return
    i = edit.key_at(p, t)
    if i is None:
        p["keys"].append([int(t), curves.value(p, t), 0.0, 0.0, 0.0, 0.0])
        p["keys"].sort(key=lambda k: k[0])
        return
    gone = p["keys"].pop(i)
    if not p["keys"]:
        h[key] = gone[1]


def set_param(level, target, effect_id, name, value, t=None):
    """t: the time the chain's keys are counted in (clip time; for the others, the level's)."""
    e = effect(level, target, effect_id)
    p = _spec(e, name)
    value = float(min(p["max"], max(p["min"], value)))
    _set_number(e.setdefault("params", {}), name, value, t)


def set_params(level, target, effect_id, values, t=None):
    """Several parameters at once ({name: value}), as one step: a band dragged on the EQ."""
    for name, value in values.items():
        set_param(level, target, effect_id, name, value, t)


def reset_param(level, target, effect_id, name):
    e = effect(level, target, effect_id)
    e.setdefault("params", {})[name] = _spec(e, name)["default"]


def toggle_key(level, target, effect_id, name, t):
    e = effect(level, target, effect_id)
    _toggle_number(e.setdefault("params", {}), name, _spec(e, name)["default"], t)


def preset_entries(chain):
    """A chain as a preset keeps it, for any project: keyframed numbers held at their first
    value; no ids, bindings to global parameters or channels listened to."""
    out = copy.deepcopy(list(chain))
    for e in out:
        e.pop("side", None)
        for node in (e.get("graph") or {}).get("nodes", {}).values():
            if node.get("type") == "ext":
                node["channel"] = ""
    for _path, one in soundfx.entries(out):
        one.pop("expr", None)
        for name, v in (one.get("params") or {}).items():
            if curves.is_animated(v):
                one["params"][name] = v["keys"][0][1]
    for e in out:
        e.pop("id", None)
    return out


def add_preset(level, target, saved):
    """Put a preset's effects at the end of target's chain; returns their new ids. What this
    version does not know is left out."""
    if target[0] == "clip" and not sounding(holder(level, target)):
        raise edit.EditError("這個片段沒有聲音")
    good = [e for e in saved if isinstance(e, dict) and
            (e.get("effect") in soundfx.EFFECTS or e.get("effect") == soundfx.GRAPH and
             isinstance(e.get("graph"), dict) and isinstance(e["graph"].get("nodes"), dict) and
             isinstance(e["graph"].get("links"), list))]
    if not good:
        raise edit.EditError("這個預設裡沒有認得的效果")
    es = holder(level, target, make=True).setdefault("sound_effects", [])
    made = []
    for e in good:
        e = dict(copy.deepcopy(e), id=new_id())
        es.append(e)
        made.append(e["id"])
    return made


def channel_of(level, target):
    """The track or bus a target's sound is on (a clip's: its track), or None (the master)."""
    if target[0] == "clip":
        return edit.find(level, target[1])[0]["id"]
    return target[1] if target[0] in ("track", "bus") else None


def side_sources(level, target):
    """[(id, name)] of the channels an effect of target can listen to: not its own, none its
    own sound goes on into (that would be a loop). The master's effects: any."""
    every = channels(level)
    own = channel_of(level, target)
    downstream, stack = {own}, [own] if own else []
    while stack:
        h = every.get(stack.pop())
        for r in soundfx.routes_of(h) if h else ():
            if r["to"] not in downstream:
                downstream.add(r["to"])
                stack.append(r["to"])
    fed = fed_channels(level)
    sounds = lambda i, h: i in fed or h.get("kind") != "video" or any(sounding(c) for c in h.get("clips", ()))
    return [(i, h.get("name") or i) for i, h in every.items() if i not in downstream and sounds(i, h)]


def fed_channels(level):
    """The ids of the channels something is sent to."""
    return {r["to"] for h in channels(level).values() for r in soundfx.routes_of(h)}


# -- graphs (soundnodes.py) ------------------------------------------------------------------------
def graph(level, target, effect_id):
    e = effect(level, target, effect_id)
    if not e.get("graph"):
        raise edit.EditError("這不是聲音節點效果")
    return e["graph"]


def _graph_edit(fn):
    """fn(graph, ...) as an edit of a level; its ValueErrors are the edit's."""
    def run(level, target, effect_id, *args):
        try:
            return fn(graph(level, target, effect_id), *args)
        except ValueError as exc:
            raise edit.EditError(str(exc)) from None
    return run


@_graph_edit
def add_node(g, kind, x, y, feed=None, into=None, on_link=None):
    """A new node. feed: (from node, output) to wire into it; into: (to node, input) it
    feeds; on_link: a link to put it into."""
    nid = soundnodes.add(g, soundnodes.new_node(kind, x, y))
    node = g["nodes"][nid]
    if on_link:
        soundnodes.insert_on_link(g, nid, on_link)
    if feed:                    # a number goes into a number node's first number, a sound into a first input
        number = soundnodes.outputs(g["nodes"][feed[0]])[feed[1]][1] == "num"
        socket = 0 if not number else \
            soundnodes.PARAM + soundnumbers.THROUGH[node["type"]] if node["type"] in soundnumbers.THROUGH else None
        if socket is not None and soundnodes.can_link(g, feed[0], feed[1], nid, socket):
            soundnodes.connect(g, feed[0], feed[1], nid, socket)
    if into and soundnodes.outputs(node) and soundnodes.can_link(g, nid, 0, into[0], into[1]):
        soundnodes.connect(g, nid, 0, into[0], into[1])
    return nid


connect_nodes = _graph_edit(soundnodes.connect)
disconnect_nodes = _graph_edit(soundnodes.disconnect)
insert_node = _graph_edit(soundnodes.insert_on_link)
remove_nodes = _graph_edit(soundnodes.remove)
paste_nodes = _graph_edit(soundnodes.paste)


@_graph_edit
def move_nodes(g, positions, on_link=None):
    """positions: {node id: (x, y)}; on_link: (node id, link) it was dropped into."""
    for nid, (x, y) in positions.items():
        if nid in g["nodes"]:
            g["nodes"][nid].update(x=round(x, 1), y=round(y, 1))
    if on_link:
        soundnodes.insert_on_link(g, on_link[0], on_link[1])


@_graph_edit
def mute_nodes(g, ids, on):
    for nid in ids:
        node = g["nodes"].get(nid)
        if node and node["type"] not in soundnodes.FIXED + ("frame",):
            if on:
                node["mute"] = True
            else:
                node.pop("mute", None)


@_graph_edit
def set_node(g, nid, fields):
    """A node's own fields: width, a frame's name / colour / size, 外部輸入's channel."""
    node = g["nodes"].get(nid)
    if node is None:
        raise ValueError("找不到這個節點")
    for key, value in fields.items():
        if key not in ("w", "h", "x", "y", "name", "color", "channel", "curve", "names"):
            raise ValueError("unknown field " + key)
        node[key] = value


@_graph_edit
def reroute_link(g, link, x, y):
    nid = soundnodes.add(g, soundnodes.new_node("reroute", x, y))
    soundnodes.insert_on_link(g, nid, link)
    return nid


# -- channels: tracks, buses, the master ------------------------------------------------------------
MASTER_TARGET = ("master", "")


def channels(level):
    """{id: holder} of the level's tracks and buses."""
    return {h["id"]: h for h in [*level["tracks"], *buses(level)]}


def routes(level, target):
    """The routes of a track or bus that lead somewhere there is."""
    every = channels(level)
    return soundfx.live_routes(holder(level, target), set(every) | {soundfx.MASTER}, target[1])


def route_to(level, target, dest):
    """The route from target to channel id dest (soundfx.MASTER: the master), or None."""
    return next((r for r in routes(level, target) if r["to"] == dest), None)


def can_route(level, target, dest):
    """Whether target (a track or bus) may send to channel id dest: not itself, and nothing
    that would come round to it again."""
    if target[0] not in ("track", "bus") or dest == target[1]:
        return False
    if dest == soundfx.MASTER:
        return True
    every = channels(level)
    if dest not in every:
        return False
    seen, todo = set(), [dest]
    while todo:
        i = todo.pop()
        if i == target[1]:
            return False
        if i in every and i not in seen:
            seen.add(i)
            todo += [r["to"] for r in soundfx.routes_of(every[i])]
    return True


def destinations(level, target):
    """The channel ids target may send to."""
    return [i for i in [*channels(level), soundfx.MASTER] if can_route(level, target, i)]


def _keep_routes(h, found):
    h.pop("output", None)
    h.pop("sends", None)
    if found == soundfx.to_master():
        h.pop("routes", None)
    else:
        h["routes"] = found


def _own_routes(level, target):
    """target's routes, written out, to be changed and kept again."""
    return copy.deepcopy(routes(level, target))


def set_route(level, target, dest, on):
    """Connect target to dest, or take that line away."""
    found = _own_routes(level, target)
    there = next((r for r in found if r["to"] == dest), None)
    if on and there is None:
        if not can_route(level, target, dest):
            raise edit.EditError("不能接到那裡（會接成迴圈）")
        found.append({"to": dest})
    elif not on and there is not None:
        found.remove(there)
    _keep_routes(holder(level, target), found)


def set_routes(level, targets, dest, on):
    """The same for several channels at once; those that cannot be connected are left."""
    todo = [t for t in targets if not on or route_to(level, t, dest) or can_route(level, t, dest)]
    if not todo:
        raise edit.EditError("不能接到那裡（會接成迴圈）")
    for t in todo:
        set_route(level, t, dest, on)


def route_only(level, targets, dest):
    """Send these channels to dest alone."""
    todo = [t for t in targets if can_route(level, t, dest)]
    if not todo:
        raise edit.EditError("不能接到那裡（會接成迴圈）")
    for t in todo:
        keep = route_to(level, t, dest) or {"to": dest}
        _keep_routes(holder(level, t), [copy.deepcopy(keep)])


def to_new_bus(level, targets, name=None):
    """A new bus (into the master) that these channels are sent to instead of where they went."""
    ident = add_bus(level, name)
    route_only(level, [t for t in targets if t[0] in ("track", "bus")], ident)
    return ident


def _route(level, target, dest):
    """The route as it is kept in target, to be written to."""
    found = _own_routes(level, target)
    r = next((r for r in found if r["to"] == dest), None)
    if r is None:
        raise edit.EditError("沒有接到那裡")
    return found, r


def set_route_level(level, target, dest, gain=None, pre=None, t=None):
    """gain: dB of the line; pre: taken before the fader."""
    found, r = _route(level, target, dest)
    if gain is not None:
        _set_number(r, "gain", round(float(max(soundfx.SEND_OFF_DB, min(12.0, gain))), 2), t)
    if pre is not None:
        if pre:
            r["pre"] = True
        else:
            r.pop("pre", None)
    if r.get("gain") == 0.0:
        r.pop("gain")
    _keep_routes(holder(level, target), found)


def toggle_route_key(level, target, dest, t):
    found, r = _route(level, target, dest)
    _toggle_number(r, "gain", 0.0, t)
    if r.get("gain") == 0.0:
        r.pop("gain")
    _keep_routes(holder(level, target), found)


def nudge_route_level(level, targets, dest, delta, t=None):
    """Turn the lines of these channels to dest by delta dB, each from where it is."""
    for target in targets:
        r = route_to(level, target, dest)
        if r is not None:
            now = float(curves.value(r.get("gain", 0.0), t or 0))
            set_route_level(level, target, dest, now + delta, None, t)


def set_gain(level, target, gain):
    """推桿 of a track or bus, linear (1: as it is)."""
    if target[0] == "master":
        raise edit.EditError("總輸出的音量是主音量")
    h = holder(level, target)
    gain = round(max(0.0, min(4.0, float(gain))), 5)
    if abs(gain - 1.0) < 1e-4:
        h.pop("gain", None)
    else:
        h["gain"] = gain


def set_pan(level, target, pan):
    h = holder(level, target)
    pan = round(max(PAN_RANGE[0], min(PAN_RANGE[1], float(pan))), 3)
    if pan:
        h["pan"] = pan
    else:
        h.pop("pan", None)


def set_flag(level, target, flag, on):
    if flag not in ("muted", "solo"):
        raise edit.EditError("unknown flag")
    h = holder(level, target)
    if on:
        h[flag] = True
    else:
        h.pop(flag, None)


# -- several channels at once -------------------------------------------------------------------------
GAIN_DB = (-60.0, 12.0)                 # the faders' ends: at the lower one, silent


def gain_db(gain):
    return GAIN_DB[0] if gain <= 10 ** (GAIN_DB[0] / 20) else min(GAIN_DB[1], 20 * math.log10(gain))


def db_gain(db):
    return 0.0 if db <= GAIN_DB[0] else 10 ** (min(GAIN_DB[1], db) / 20)


def nudge_gain(level, targets, delta):
    """Move the faders of these channels by delta dB, each from where it is."""
    for t in targets:
        if t[0] != "master":
            set_gain(level, t, db_gain(gain_db(holder(level, t).get("gain", 1.0)) + delta))


def nudge_pan(level, targets, delta):
    for t in targets:
        if t[0] != "master":
            set_pan(level, t, holder(level, t).get("pan", 0.0) + delta)


def set_flags(level, targets, flag, on):
    for t in targets:
        if t[0] != "master":
            set_flag(level, t, flag, on)


def add_effects(level, targets, kind):
    """The effect added to each of these (one of its own on each); {target: id}."""
    return {t: add_effect(level, t, kind) for t in targets}


def add_presets(level, targets, saved):
    for t in targets:
        add_preset(level, t, saved)


def set_color(level, targets, color):
    """A strip's colour on the mixer ("#rrggbb"; None: its kind's)."""
    for t in targets:
        h = holder(level, t, make=True)
        if color:
            h["mix_color"] = color
        else:
            h.pop("mix_color", None)
            if t[0] == "master":
                _prune(level, t)


def ordered(level, ids):
    """ids in the order the mixer's strips are in: as they were dragged, any other after the
    one it follows in ids."""
    kept = [i for i in mix_holder(level).get("mixer_order") or () if i in ids]
    for at, i in enumerate(ids):
        if i not in kept:
            kept.insert(kept.index(ids[at - 1]) + 1 if at and ids[at - 1] in kept else 0 if not at else len(kept), i)
    return kept


def move_strips(level, ids, moving, before):
    """Put the strips `moving` (of ids, as they are shown) before strip `before` (None: last).
    Only the mixer's order: the timeline's tracks stay where they are."""
    moving = [i for i in ids if i in moving]
    rest = [i for i in ids if i not in moving]
    if before in moving:                                    # (dropped among themselves: where the block begins)
        after = ids[ids.index(before):]
        before = next((i for i in after if i not in moving), None)
    at = rest.index(before) if before in rest else len(rest)
    mix_holder(level)["mixer_order"] = rest[:at] + moving + rest[at:]


def add_bus(level, name=None):
    mix = mix_holder(level)
    ids = {b["id"] for b in mix.get("buses") or ()} | {t["id"] for t in level["tracks"]}
    n = 1
    while f"bus{n}" in ids:
        n += 1
    mix.setdefault("buses", []).append({"id": f"bus{n}", "name": name or f"Bus {n}"})
    return f"bus{n}"


def rename_bus(level, bus_id, name):
    name = (name or "").strip()
    if not name:
        raise edit.EditError("名稱不能是空的")
    bus(level, bus_id)["name"] = name


def remove_buses(level, ids):
    for i in ids:
        remove_bus(level, i)


def remove_bus(level, bus_id):
    """Take a bus out: what went only into it goes to the master, and nothing listens to it."""
    mix = mix_holder(level)
    gone = bus(level, bus_id)
    went = {i: _own_routes(level, ("track" if any(t["id"] == i for t in level["tracks"]) else "bus", i))
            for i in channels(level) if i != bus_id}
    mix["buses"].remove(gone)
    if not mix["buses"]:
        mix.pop("buses")
    for i, h in channels(level).items():
        if any(r["to"] == bus_id for r in went[i]):
            _keep_routes(h, [r for r in went[i] if r["to"] != bus_id] or soundfx.to_master())
    if mix.get("mixer_order"):
        mix["mixer_order"] = [i for i in mix["mixer_order"] if i != bus_id]
    chains = [mix.get(soundfx.MASTER) or {}]
    for h in list(level["tracks"]) + list(mix.get("buses") or ()):
        chains.append(h)
        chains += h.get("clips", [])
    for h in chains:
        for e in h.get("sound_effects") or ():
            if (e.get("side") or {}).get("id") == bus_id:
                e.pop("side")
            for node in (e.get("graph") or {}).get("nodes", {}).values():
                if node.get("channel") == bus_id:
                    node["channel"] = ""
