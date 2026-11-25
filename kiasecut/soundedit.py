"""Edits of a project's sound processing (soundfx.py), each fn(level, ...) as edit.py's are.

A target says whose chain or channel is meant: ("clip", id), ("track", id), ("bus", id) or
("master", ""). level: the open level - the project (its root) or a compound.
"""
import uuid

from . import curves, edit, project, soundfx

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
    e = next((e for e in chain(level, target) if e["id"] == effect_id), None)
    if e is None:
        raise edit.EditError("找不到這個聲音效果")
    return e


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
    if kind not in soundfx.EFFECTS:
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
    p = next((p for p in soundfx.EFFECTS[e["effect"]]["params"] if p["name"] == name), None)
    if p is None:
        raise edit.EditError("這個效果沒有這個參數")
    return p


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


# -- channels: tracks, buses, the master ------------------------------------------------------------
def destinations(level, target):
    """The buses target (a track or bus) may send to: not itself, none that would make a loop."""
    all_buses = {b["id"]: b for b in buses(level)}
    if target[0] != "bus":
        return list(all_buses.values())

    def reaches(i, goal, seen):
        if i == goal:
            return True
        b = all_buses.get(i)
        if b is None or i in seen:
            return False
        seen.add(i)
        return any(reaches(d, goal, seen) for d in [b.get("output")] + [s.get("bus") for s in b.get("sends") or ()] if d)
    return [b for i, b in all_buses.items() if not reaches(i, target[1], set())]


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


def _check_destination(level, target, bus_id):
    if all(b["id"] != bus_id for b in destinations(level, target)):
        raise edit.EditError("不能接到那裡（會接成迴圈）")


def set_output(level, target, bus_id):
    """Where a track's or bus's output goes: a bus id, or None for the master."""
    h = holder(level, target)
    if bus_id:
        _check_destination(level, target, bus_id)
        h["output"] = bus_id
    else:
        h.pop("output", None)


def add_send(level, target, bus_id):
    _check_destination(level, target, bus_id)
    sends = holder(level, target).setdefault("sends", [])
    if any(s["bus"] == bus_id for s in sends):
        raise edit.EditError("已經有傳送到那個 bus")
    sends.append({"bus": bus_id, "gain": 0.0})


def _send(level, target, bus_id):
    s = next((s for s in holder(level, target).get("sends") or () if s["bus"] == bus_id), None)
    if s is None:
        raise edit.EditError("找不到這個傳送")
    return s


def remove_send(level, target, bus_id):
    h = holder(level, target)
    h["sends"].remove(_send(level, target, bus_id))
    if not h["sends"]:
        h.pop("sends")


def set_send(level, target, bus_id, gain=None, pre=None, t=None):
    """gain: dB; pre: taken before the fader."""
    s = _send(level, target, bus_id)
    if gain is not None:
        _set_number(s, "gain", round(float(max(soundfx.SEND_OFF_DB, min(12.0, gain))), 2), t)
    if pre is not None:
        if pre:
            s["pre"] = True
        else:
            s.pop("pre", None)


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


def remove_bus(level, bus_id):
    """Take a bus out: what went into it goes to the master, and nothing listens to it."""
    mix = mix_holder(level)
    gone = bus(level, bus_id)
    mix["buses"].remove(gone)
    if not mix["buses"]:
        mix.pop("buses")
    chains = [mix.get(soundfx.MASTER) or {}]
    for h in list(level["tracks"]) + list(mix.get("buses") or ()):
        if h.get("output") == bus_id:
            h.pop("output")
        if h.get("sends"):
            h["sends"] = [s for s in h["sends"] if s["bus"] != bus_id]
            if not h["sends"]:
                h.pop("sends")
        chains.append(h)
        chains += h.get("clips", [])
    for h in chains:
        for e in h.get("sound_effects") or ():
            if (e.get("side") or {}).get("id") == bus_id:
                e.pop("side")
