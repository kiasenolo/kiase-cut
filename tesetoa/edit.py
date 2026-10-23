"""Edit operations on a project, with undo/redo.

Every operation works on clip ids, keeps clips on one track from overlapping and keeps
keyframes where they were on screen: keys are relative to the clip start, so trimming the
head or splitting shifts them by the amount cut. Video, audio and compound clips cannot
be trimmed past their source; images and texts can be stretched freely.
"""
import copy
import json
import time
import uuid

from . import curves, project

MIN_US = 1_000_000 // 60          # a clip never gets shorter than one 60 fps frame
MERGE_S = 2.0


class EditError(Exception):
    pass


class History:
    """Snapshot undo stack: copies the project before each change (a few hundred KB)."""

    def __init__(self, proj, limit=200):
        self.proj = proj
        self.undo_stack, self.redo_stack = [], []
        self.limit = limit

    def do(self, label, fn, *args, merge=None, **kw):
        """Apply fn(proj, *args, **kw) as one undoable step. Repeated edits with the same
        merge key within MERGE_S seconds (spinning a value, typing) share one step."""
        before = json.dumps(self.proj, ensure_ascii=False)
        try:
            result = fn(self.proj, *args, **kw)
        except Exception:
            self._restore(before)              # never leave a half-applied edit behind
            raise
        now = time.monotonic()
        last = self.undo_stack[-1] if self.undo_stack else None
        if merge is not None and last and last[2] == merge and now - last[3] < MERGE_S:
            self.undo_stack[-1] = (label, last[1], merge, now)
        else:
            self.undo_stack.append((label, before, merge, now))
            del self.undo_stack[:-self.limit]
        self.redo_stack.clear()
        project.refresh_duration(self.proj)
        return result

    def _restore(self, snapshot):
        data = json.loads(snapshot)
        self.proj.clear()
        self.proj.update(data)

    def undo(self):
        if not self.undo_stack:
            return None
        label, snap, _, _ = self.undo_stack.pop()
        self.redo_stack.append((label, json.dumps(self.proj, ensure_ascii=False)))
        self._restore(snap)
        return label

    def redo(self):
        if not self.redo_stack:
            return None
        label, snap = self.redo_stack.pop()
        self.undo_stack.append((label, json.dumps(self.proj, ensure_ascii=False), None, 0.0))
        self._restore(snap)
        return label


# -- lookup ---------------------------------------------------------------------------------------
def find(proj, clip_id):
    """(track, clip) for a top-level clip id."""
    for t in proj["tracks"]:
        for c in t["clips"]:
            if c["id"] == clip_id:
                return t, c
    raise EditError(f"clip {clip_id} not found")


def track_by_id(proj, track_id):
    for t in proj["tracks"]:
        if t["id"] == track_id:
            return t
    raise EditError(f"track {track_id} not found")


def new_clip_id(_proj=None):
    """Clip ids are unique across the whole project, compound clips included, because
    edits address clips by id from whichever level is open."""
    return "c" + uuid.uuid4().hex[:10]


def end(c):
    return c["start_us"] + c["duration_us"]


def free_range(track, start, end_, ignore=None):
    """(lo, hi) of the gap in track around [start, end_), ignoring clip `ignore`."""
    lo, hi = 0, float("inf")
    for c in track["clips"]:
        if c is ignore:
            continue
        if end(c) <= start:
            lo = max(lo, end(c))
        elif c["start_us"] >= end_:
            hi = min(hi, c["start_us"])
        else:
            return None                          # overlaps
    return lo, hi


def gaps(track, ignore=None):
    """Free (lo, hi) spans of a track from time 0, the last one open-ended."""
    out, cur = [], 0
    for c in sorted((c for c in track["clips"] if c is not ignore), key=lambda c: c["start_us"]):
        if c["start_us"] > cur:
            out.append((cur, c["start_us"]))
        cur = max(cur, end(c))
    out.append((cur, float("inf")))
    return out


def source_length(c):
    """How long the clip's source runs, or None when it can be stretched freely."""
    if c["type"] in ("video", "audio"):
        return (c.get("media") or {}).get("duration_us")
    if c["type"] == "compound":
        return c["compound"].get("duration_us")
    return None


def _params(c):
    """Every animatable parameter dict in a clip, for shifting keyframes."""
    out = []
    for group in (c.get("transform"), c.get("mask")):
        if group:
            out += [v for v in group.values() if curves.is_animated(v)]
    if curves.is_animated(c.get("volume")):
        out.append(c["volume"])
    return out


def shift_keys(c, d_us):
    """Move every keyframe by -d_us: the clip's start moved d_us later in its source."""
    for p in _params(c):
        for k in p["keys"]:
            k[0] -= d_us


def _sort(track):
    track["clips"].sort(key=lambda c: c["start_us"])


# -- operations -----------------------------------------------------------------------------------
def move(proj, clip_id, start_us, track_id=None):
    """Move a clip to start_us (and optionally another track of the same kind).
    Snaps into the nearest free gap if the spot is taken."""
    src, c = find(proj, clip_id)
    dst = track_by_id(proj, track_id) if track_id else src
    if (dst["kind"] == "audio") != (src["kind"] == "audio"):
        raise EditError("audio clips stay on audio tracks, pictures on picture tracks")
    dur = c["duration_us"]
    # land in the gap nearest to where it was dropped
    best = None
    for lo, hi in gaps(dst, ignore=c):
        if hi - lo < dur:
            continue
        s = min(max(int(start_us), lo), hi - dur)
        if best is None or abs(s - start_us) < abs(best - start_us):
            best = s
    if best is None:
        raise EditError("no room there")
    start_us = best
    if dst is not src:
        src["clips"].remove(c)
        dst["clips"].append(c)
    c["start_us"] = start_us
    _sort(dst)
    return c


def trim_start(proj, clip_id, new_start_us):
    """Move the clip's left edge, keeping its right edge and its content in place."""
    t, c = find(proj, clip_id)
    e = end(c)
    rng = free_range(t, c["start_us"], e, ignore=c)
    lo = rng[0]
    if c["type"] in ("video", "audio", "compound"):
        lo = max(lo, c["start_us"] - c.get("source_start_us", 0))    # cannot go before the source
    new_start_us = int(min(max(new_start_us, lo), e - MIN_US))
    d = new_start_us - c["start_us"]
    c["start_us"] = new_start_us
    c["duration_us"] = e - new_start_us
    c["source_start_us"] = c.get("source_start_us", 0) + d
    shift_keys(c, d)
    return c


def trim_end(proj, clip_id, new_end_us):
    """Move the clip's right edge."""
    t, c = find(proj, clip_id)
    rng = free_range(t, c["start_us"], end(c), ignore=c)
    hi = rng[1]
    src_len = source_length(c)
    if src_len is not None:
        hi = min(hi, c["start_us"] + src_len - c.get("source_start_us", 0))
    new_end_us = int(max(min(new_end_us, hi), c["start_us"] + MIN_US))
    c["duration_us"] = new_end_us - c["start_us"]
    return c


def split(proj, clip_id, at_us):
    """Cut a clip in two at at_us (timeline time); returns the new right-hand clip."""
    t, c = find(proj, clip_id)
    if not (c["start_us"] + MIN_US <= at_us <= end(c) - MIN_US):
        raise EditError("the playhead is not inside the clip")
    at_us = int(at_us)
    d = at_us - c["start_us"]
    right = copy.deepcopy(c)
    right["id"] = new_clip_id(proj)
    right["start_us"] = at_us
    right["duration_us"] = end(c) - at_us
    right["source_start_us"] = c.get("source_start_us", 0) + d
    shift_keys(right, d)
    c["duration_us"] = d
    if c.get("fade_out_us"):                  # fades belong to the outer ends
        right["fade_in_us"] = 0
        c["fade_out_us"] = 0
    t["clips"].append(right)
    _sort(t)
    return right


def delete(proj, clip_id):
    t, c = find(proj, clip_id)
    t["clips"].remove(c)


def add_text(proj, at_us, content="輸入文字", duration_us=3_000_000):
    """New text clip at at_us on the topmost text track with room, else a new track."""
    clip = {
        "id": new_clip_id(proj), "type": "text", "name": content[:20],
        "start_us": int(at_us), "duration_us": int(duration_us), "source_start_us": 0,
        "text": {"content": content, "font_path": project.DEFAULT_FONT, "size": 7.95,
                 "color": [1.0, 1.0, 1.0], "letter_spacing": 0.0, "line_spacing": 0.02,
                 "italic_deg": 0},
        "transform": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0},
    }
    for t in reversed(proj["tracks"]):
        if t["kind"] == "text" and free_range(t, clip["start_us"], end(clip)) is not None:
            rng = free_range(t, clip["start_us"], end(clip))
            if rng[1] - clip["start_us"] >= MIN_US:
                clip["duration_us"] = min(clip["duration_us"], rng[1] - clip["start_us"])
                t["clips"].append(clip)
                _sort(t)
                return clip
    n = sum(1 for t in proj["tracks"] if t["kind"] == "text") + 1
    track = {"id": new_track_id(proj), "kind": "text", "name": f"text {n}", "clips": [clip]}
    audio_at = next((i for i, t in enumerate(proj["tracks"]) if t["kind"] == "audio"), len(proj["tracks"]))
    proj["tracks"].insert(audio_at, track)       # topmost picture layer, below the audio rows
    return clip


def new_track_id(proj):
    ids = {t["id"] for t in proj["tracks"]}
    n = len(ids)
    while f"t{n}" in ids:
        n += 1
    return f"t{n}"


TEXT_FIELDS = ("content", "font_path", "size", "color", "letter_spacing", "line_spacing", "italic_deg")
TRANSFORM_FIELDS = ("x", "y", "scale", "rotation", "opacity")


def set_text(proj, clip_id, **fields):
    _, c = find(proj, clip_id)
    if c["type"] != "text":
        raise EditError("not a text clip")
    for k, v in fields.items():
        if k not in TEXT_FIELDS:
            raise EditError(f"unknown text field {k}")
        if curves.is_animated(c["text"].get(k)):
            raise EditError(f"{k} has keyframes: edit it at the playhead")
        c["text"][k] = v
    if "color" in fields or "size" in fields:
        c["text"].pop("styles", None)          # a whole-clip style replaces per-range ones
    if "content" in fields and not c.get("named"):
        c["name"] = fields["content"][:20]
    return c


def set_transform(proj, clip_id, key, value, t=None):
    """Set a transform value; keyframed ones are edited at clip time t (see set_param)."""
    if key not in TRANSFORM_FIELDS:
        raise EditError(f"unknown transform field {key}")
    return set_param(proj, clip_id, "transform", key, value, t)


# -- keyframes ------------------------------------------------------------------------------------
TEXT_ANIM_FIELDS = ("size", "color", "letter_spacing", "line_spacing", "italic_deg")
GROUP_FIELDS = {
    "transform": TRANSFORM_FIELDS,
    "text": TEXT_ANIM_FIELDS,
    "mask": ("cx", "cy", "w", "h", "rotation", "feather"),
    "clip": ("volume",),
}
KEY_TOL_US = 1_000_000 // 120      # half a 60 fps frame
EASINGS = {                        # CSS-style cubic-bezier control x positions
    "linear": (0.0, 1.0),
    "ease_in": (0.42, 1.0),
    "ease_out": (0.0, 0.58),
    "ease_in_out": (0.42, 0.58),
}


def _holder(c, group):
    if group == "clip":
        return c
    if group == "mask":
        if not c.get("mask"):
            raise EditError("clip has no mask")
        return c["mask"]
    if group == "text":
        if not c.get("text"):
            raise EditError("not a text clip")
        return c["text"]
    return c.setdefault("transform", {})


def _check(c, group, key, t):
    if key not in GROUP_FIELDS.get(group, ()):
        raise EditError(f"unknown {group} field {key}")
    if not (0 <= t <= c["duration_us"]):
        raise EditError("the playhead is not inside the clip")


def key_at(p, t):
    """Index of the key at t (within half a frame), or None."""
    if not curves.is_animated(p):
        return None
    for i, k in enumerate(p["keys"]):
        if abs(k[0] - t) <= KEY_TOL_US:
            return i
    return None


def set_param(proj, clip_id, group, key, value, t=None):
    """Set a parameter. Static ones change outright; keyframed ones get their key at t
    (clip time) updated, or a new key there - as Jianying does when you change a value."""
    _, c = find(proj, clip_id)
    h = _holder(c, group)
    p = h.get(key)
    value = [float(v) for v in value] if isinstance(value, (list, tuple)) else float(value)
    if group == "text" and key in ("size", "color"):
        h.pop("styles", None)                    # a whole-clip style replaces per-range ones
    if not curves.is_animated(p):
        h[key] = value
        if group == "transform" and key == "scale" and "scale_y" in h and not curves.is_animated(h["scale_y"]):
            h["scale_y"] = value
        return c
    if t is None:
        raise EditError(f"{key} has keyframes: give the time to edit")
    _check(c, group, key, t)
    i = key_at(p, t)
    if i is None:
        p["keys"].append([int(t), value, 0.0, 0.0, 0.0, 0.0])
        p["keys"].sort(key=lambda k: k[0])
    else:
        p["keys"][i][1] = value
    return c


def toggle_key(proj, clip_id, group, key, t):
    """Add a key at t holding the current value, or remove the key that is there.
    Removing the last key leaves the parameter at that key's value."""
    _, c = find(proj, clip_id)
    _check(c, group, key, t)
    h = _holder(c, group)
    default = {"scale": 1.0, "opacity": 1.0, "volume": 1.0, "w": 1.0, "h": 1.0, "size": 5.0,
               "color": [1.0, 1.0, 1.0]}.get(key, 0.0)
    p = h.get(key, default)
    i = key_at(p, t)
    if i is not None:
        k = p["keys"].pop(i)
        if not p["keys"]:
            h[key] = k[1]
        return c
    v = curves.value(p, t)
    if curves.is_animated(p):
        p["keys"].append([int(t), v, 0.0, 0.0, 0.0, 0.0])
        p["keys"].sort(key=lambda k: k[0])
    else:
        h[key] = {"keys": [[int(t), v, 0.0, 0.0, 0.0, 0.0]]}
    return c


def set_easing(proj, clip_id, group, key, t, easing):
    """Shape the curve from the key at t to the next key with a preset."""
    _, c = find(proj, clip_id)
    _check(c, group, key, t)
    p = _holder(c, group).get(key)
    i = key_at(p, t)
    if i is None or i + 1 >= len(p["keys"]):
        raise EditError("needs a keyframe here and another one after it")
    if easing not in EASINGS:
        raise EditError(f"unknown easing {easing}")
    a, b = p["keys"][i], p["keys"][i + 1]
    dt = b[0] - a[0]
    x1, x2 = EASINGS[easing]
    a[4], a[5] = x1 * dt, 0.0                    # handles are flat: ease, not overshoot
    b[2], b[3] = (x2 - 1.0) * dt, 0.0
    return c


def easing_at(p, t):
    """Name of the preset matching the segment that starts at the key at t, if any."""
    i = key_at(p, t)
    if i is None or i + 1 >= len(p["keys"]):
        return None
    a, b = p["keys"][i], p["keys"][i + 1]
    dt = b[0] - a[0] or 1
    for name, (x1, x2) in EASINGS.items():
        if abs(a[4] - x1 * dt) < 1 and abs(b[2] - (x2 - 1) * dt) < 1 and abs(a[5]) < 1e-9 and abs(b[3]) < 1e-9:
            return name
    return "custom"


def key_times(c):
    """Sorted clip-time positions of every keyframe in a clip."""
    times = set()
    for group in ("transform", "mask", "text"):
        for v in (c.get(group) or {}).values():
            if curves.is_animated(v):
                times |= {k[0] for k in v["keys"]}
    if curves.is_animated(c.get("volume")):
        times |= {k[0] for k in c["volume"]["keys"]}
    return sorted(times)


# -- masks ----------------------------------------------------------------------------------------
MASK_KINDS = ("line", "mirror", "circle", "rectangle")


def _aspect(c):
    """Width / height of the clip's material, so default circles come out round."""
    if c.get("media", {}).get("width"):
        return c["media"]["width"] / c["media"]["height"]
    if c.get("compound"):
        return c["compound"]["width"] / c["compound"]["height"]
    return 16 / 9


def set_mask(proj, clip_id, kind):
    """Give a clip a mask of `kind` (keeping its position), or remove it with None."""
    _, c = find(proj, clip_id)
    if c["type"] not in ("image", "video", "compound"):
        raise EditError("masks go on pictures, videos and compound clips")
    if kind is None:
        c.pop("mask", None)
        return c
    if kind not in MASK_KINDS:
        raise EditError(f"unknown mask {kind}")
    old = c.get("mask") or {}
    a = _aspect(c)
    size = {"line": (1.0, 1.0), "mirror": (1.0, 0.3), "circle": (0.5, 0.5 * a), "rectangle": (0.5, 0.5 * a)}[kind]
    c["mask"] = {"kind": kind, "invert": bool(old.get("invert")),
                 "cx": old.get("cx", 0.0), "cy": old.get("cy", 0.0),
                 "w": old.get("w", size[0]) if kind != "line" else 1.0,
                 "h": old.get("h", size[1]) if kind != "line" else 1.0,
                 "rotation": old.get("rotation", 0.0), "feather": old.get("feather", 0.0)}
    return c


def set_mask_invert(proj, clip_id, invert):
    _, c = find(proj, clip_id)
    if not c.get("mask"):
        raise EditError("clip has no mask")
    c["mask"]["invert"] = bool(invert)
    return c


# -- names and colours ----------------------------------------------------------------------------
def rename_track(proj, track_id, name):
    track_by_id(proj, track_id)["name"] = str(name).strip() or track_by_id(proj, track_id)["kind"]


def set_track_color(proj, track_id, color):
    """color: '#rrggbb' or None for the default."""
    t = track_by_id(proj, track_id)
    if color:
        t["color"] = color
    else:
        t.pop("color", None)


def rename_clip(proj, clip_id, name):
    _, c = find(proj, clip_id)
    c["name"] = str(name).strip()
    c["named"] = bool(c["name"])            # a user name wins over the text content label


def set_clip_color(proj, clip_id, color):
    _, c = find(proj, clip_id)
    if color:
        c["color"] = color
    else:
        c.pop("color", None)


def set_keys(proj, clip_id, group, key, keys):
    """Replace a parameter's keyframes (the curve editor's edits). Keys are
    [t, value, l_dt, l_dv, r_dt, r_dv] in clip time; they are sorted, kept inside the
    clip, and handles are kept from crossing the neighbouring keys."""
    _, c = find(proj, clip_id)
    if key not in GROUP_FIELDS.get(group, ()):
        raise EditError(f"unknown {group} field {key}")
    if not keys:
        raise EditError("a curve needs at least one keyframe")
    h = _holder(c, group)
    clean = []
    for k in sorted(keys, key=lambda k: k[0]):
        t = int(min(max(k[0], 0), c["duration_us"]))
        if clean and t - clean[-1][0] <= KEY_TOL_US:
            raise EditError("two keyframes at the same time")
        v = [float(x) for x in k[1]] if isinstance(k[1], (list, tuple)) else float(k[1])
        clean.append([t, v] + [float(x) for x in k[2:6]])
    for i, k in enumerate(clean):
        prev_dt = k[0] - clean[i - 1][0] if i else 0
        next_dt = clean[i + 1][0] - k[0] if i + 1 < len(clean) else 0
        k[2] = min(0.0, max(-prev_dt, k[2]))
        k[4] = max(0.0, min(next_dt, k[4]))
    h[key] = {"keys": clean}
    return c


def clear_keys(proj, clip_id, group, key, value):
    """Drop every keyframe of a parameter, leaving it at `value`."""
    _, c = find(proj, clip_id)
    if key not in GROUP_FIELDS.get(group, ()):
        raise EditError(f"unknown {group} field {key}")
    _holder(c, group)[key] = [float(x) for x in value] if isinstance(value, (list, tuple)) else float(value)
    return c


# -- tracks -----------------------------------------------------------------------------------------
TRACK_FLAGS = ("muted", "solo", "hidden")


def set_track_flag(proj, track_id, flag, on):
    if flag not in TRACK_FLAGS:
        raise EditError(f"unknown track flag {flag}")
    t = track_by_id(proj, track_id)
    if on:
        t[flag] = True
    else:
        t.pop(flag, None)


def set_track_gain(proj, track_id, gain):
    t = track_by_id(proj, track_id)
    g = min(4.0, max(0.0, float(gain)))
    if abs(g - 1.0) < 1e-6:
        t.pop("gain", None)
    else:
        t["gain"] = round(g, 4)


def _visual_slot(proj, top=True):
    """Index in proj['tracks'] for a new picture track: the topmost layer or the bottom one."""
    audio_at = next((i for i, t in enumerate(proj["tracks"]) if t["kind"] == "audio"), len(proj["tracks"]))
    return audio_at if top else 0


def add_track(proj, kind, near_id=None):
    """New empty track of kind: next to near_id (above it on screen), else on top of the
    pictures / below the audio."""
    if kind not in ("video", "text", "audio"):
        raise EditError(f"unknown track kind {kind}")
    n = sum(1 for t in proj["tracks"] if t["kind"] == kind) + 1
    track = {"id": new_track_id(proj), "kind": kind, "name": f"{kind} {n}", "clips": []}
    near = next((i for i, t in enumerate(proj["tracks"]) if t["id"] == near_id), None)
    if near is not None and (proj["tracks"][near]["kind"] == "audio") == (kind == "audio"):
        # pictures: a later index is a higher layer (higher on screen); audio rows go down
        proj["tracks"].insert(near + 1 if kind != "audio" else near, track)
    elif kind == "audio":
        proj["tracks"].append(track)
    else:
        proj["tracks"].insert(_visual_slot(proj), track)
    return track


def delete_track(proj, track_id):
    t = track_by_id(proj, track_id)
    proj["tracks"].remove(t)


def move_track(proj, track_id, up):
    """Move a track one row up or down on screen, among tracks of its group (pictures / audio)."""
    t = track_by_id(proj, track_id)
    audio = t["kind"] == "audio"
    group = [i for i, x in enumerate(proj["tracks"]) if (x["kind"] == "audio") == audio]
    pos = group.index(proj["tracks"].index(t))
    step = (1 if up else -1) if not audio else (-1 if up else 1)     # pictures: up = later
    j = pos + step
    if not 0 <= j < len(group):
        raise EditError("already at the edge")
    a, b = group[pos], group[j]
    proj["tracks"][a], proj["tracks"][b] = proj["tracks"][b], proj["tracks"][a]


def move_to_new_track(proj, clip_id, start_us, top):
    """Move a clip onto a new track: for pictures a new top layer (top) or bottom layer,
    for sound a new last audio row (top=False) or first one."""
    src, c = find(proj, clip_id)
    kind = src["kind"]
    n = sum(1 for t in proj["tracks"] if t["kind"] == kind) + 1
    track = {"id": new_track_id(proj), "kind": kind, "name": f"{kind} {n}", "clips": []}
    if kind == "audio":
        first = next(i for i, t in enumerate(proj["tracks"]) if t["kind"] == "audio")
        proj["tracks"].insert(first if top else len(proj["tracks"]), track)
    else:
        proj["tracks"].insert(_visual_slot(proj, top), track)
    src["clips"].remove(c)
    track["clips"].append(c)
    c["start_us"] = max(0, int(start_us))
    return c


def detach_audio(proj, clip_id):
    """Split a video clip's sound onto an audio track (as Jianying's 分離音訊): the new audio
    clip takes the volume and fades, the video clip is silenced."""
    _, c = find(proj, clip_id)
    if c["type"] != "video":
        raise EditError("only video clips have sound to detach")
    m = c["media"]
    a = {"id": new_clip_id(proj), "type": "audio", "name": c.get("name") or "audio",
         "start_us": c["start_us"], "duration_us": c["duration_us"],
         "source_start_us": c.get("source_start_us", 0),
         "media": {"path": m["path"], "duration_us": m.get("duration_us")},
         "volume": copy.deepcopy(c.get("volume", 1.0))}
    for k in ("fade_in_us", "fade_out_us"):
        if c.get(k):
            a[k] = c.pop(k)
    c["volume"] = 0.0
    # the first audio track with room for it (free_range is None where it overlaps a clip)
    dst = next((t for t in proj["tracks"] if t["kind"] == "audio"
                and free_range(t, a["start_us"], end(a)) is not None), None)
    if dst is None:
        dst = add_track(proj, "audio")
    dst["clips"].append(a)
    _sort(dst)
    return a
