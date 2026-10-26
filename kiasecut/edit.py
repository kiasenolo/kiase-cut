"""Edit operations on a project, with undo/redo.

Every operation works on clip ids, keeps clips on one track from overlapping and keeps
keyframes where they were on screen: keys are relative to the clip start, so trimming the
head or splitting shifts them by the amount cut. Video, audio and compound clips cannot
be trimmed past their source; images and texts can be stretched freely.
"""
import copy
import json
import math
import time
import uuid

from . import assets, curves, fx, project

MIN_US = 1_000_000 // 60          # a clip never gets shorter than one 60 fps frame
MERGE_S = 2.0
US = 1_000_000


class EditError(Exception):
    pass


class History:
    """Snapshot undo stack: copies the project before each change (a few hundred KB).
    The media library and the project info mirror the project folder, not the edit, so
    they are left out of the snapshots: undo never brings back or hides a file. Nor is
    the saved view (playhead, scroll, track heights): undo leaves the view alone, and the
    font map (which installed font stands in for a missing one: fonts.py), which belongs
    to the computer the project is opened on, not to the edit."""
    SIDE = ("library", "info", "view", "font_map")

    def __init__(self, proj, limit=200):
        self.proj = proj
        self.undo_stack, self.redo_stack = [], []
        self.limit = limit

    def do(self, label, fn, *args, merge=None, **kw):
        """Apply fn(proj, *args, **kw) as one undoable step. Repeated edits with the same
        merge key within MERGE_S seconds (spinning a value, typing) share one step."""
        before = self.snap()                           # shared compounds stored once
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

    def snap(self):
        return json.dumps({k: v for k, v in project.detached(self.proj).items() if k not in self.SIDE},
                          ensure_ascii=False)

    def _restore(self, snapshot):
        data = json.loads(snapshot)
        keep = {k: self.proj[k] for k in self.SIDE if k in self.proj}
        self.proj.clear()
        self.proj.update(data)
        self.proj.update(keep)
        project.link(self.proj)

    def rewrite(self, fn):
        """Apply fn(text) -> text to every stored snapshot (media files that were renamed)."""
        self.undo_stack = [(l, fn(s), *rest) for l, s, *rest in self.undo_stack]
        self.redo_stack = [(l, fn(s)) for l, s in self.redo_stack]

    def undo(self):
        if not self.undo_stack:
            return None
        label, snap, _, _ = self.undo_stack.pop()
        self.redo_stack.append((label, self.snap()))
        self._restore(snap)
        return label

    def redo(self):
        if not self.redo_stack:
            return None
        label, snap = self.redo_stack.pop()
        self.undo_stack.append((label, self.snap(), None, 0.0))
        self._restore(snap)
        return label


# -- lookup ---------------------------------------------------------------------------------------
def find(proj, clip_id):
    """(track, clip) for a clip id of the level - a group's clips included (their track is
    the group's)."""
    for t in project.all_tracks(proj["tracks"]):
        for c in t["clips"]:
            if c["id"] == clip_id:
                return t, c
    raise EditError(f"clip {clip_id} not found")


def track_by_id(proj, track_id):
    for t in project.all_tracks(proj["tracks"]):
        if t["id"] == track_id:
            return t
    raise EditError(f"track {track_id} not found")


def group_of(proj, track):
    """The group clip whose track `track` is, or None (a track of the level itself)."""
    for t in project.all_tracks(proj["tracks"]):
        for c in t["clips"]:
            if project.is_group(c) and any(x is track for x in c["tracks"]):
                return c
    return None


def abs_start(proj, clip_id):
    """A clip's start in the level's time (a group's clips count from the group's start)."""
    t, c = find(proj, clip_id)
    s = c["start_us"]
    g = group_of(proj, t)
    while g is not None:
        s += g["start_us"]
        g = group_of(proj, find(proj, g["id"])[0])
    return s


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
    if c["type"] == "compound" and not project.is_static(c):       # a static one is a picture
        return c["compound"].get("duration_us")
    return None


def _params(c):
    """Every animatable parameter dict in a clip, for shifting keyframes."""
    out = []
    for group in (c.get("transform"), c.get("mask"), c.get("text"), c.get("asset")):
        if group:
            out += [v for v in group.values() if curves.is_animated(v)]
    for key in ("volume", "blend"):
        if curves.is_animated(c.get(key)):
            out.append(c[key])
    for e in c.get("effects") or []:
        out += [v for v in list(e["params"].values()) + list((e.get("mask") or {}).values()) if curves.is_animated(v)]
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
    if dst is not src and project.locked(dst):
        raise EditError("那條軌道已鎖定")
    if (dst["kind"] == "audio") != (src["kind"] == "audio"):
        raise EditError("audio clips stay on audio tracks, pictures on picture tracks")
    dur = c["duration_us"]
    g = group_of(proj, dst)
    if (g is None) != (group_of(proj, src) is None) or (g is not None and g is not group_of(proj, src)):
        raise EditError("片段只能在同一個群組裡的軌道之間移動")
    limit = g["duration_us"] if g is not None else float("inf")      # a group's clips stay inside it
    # land in the gap nearest to where it was dropped
    best = None
    for lo, hi in gaps(dst, ignore=c):
        hi = min(hi, limit)
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
    if c["type"] in ("video", "audio", "compound") and not project.is_static(c):
        lo = max(lo, c["start_us"] - c.get("source_start_us", 0) / project.speed(c))    # not before the source
    g = group_of(proj, t)
    if g is not None:
        lo = max(lo, 0)                                          # not out of its group
    hi = e - MIN_US
    if project.is_group(c):                                      # a group never cuts its clips
        hi = min(hi, c["start_us"] + _content_span(c)[0])
    new_start_us = int(min(max(new_start_us, lo), hi))
    d = new_start_us - c["start_us"]
    c["start_us"] = new_start_us
    c["duration_us"] = e - new_start_us
    c["source_start_us"] = max(0, round(c.get("source_start_us", 0) + d * project.speed(c)))
    shift_keys(c, d)
    if project.is_group(c):                                      # its clips stay where they were
        for ct in c["tracks"]:
            for k in ct["clips"]:
                k["start_us"] -= d
    return c


def trim_end(proj, clip_id, new_end_us):
    """Move the clip's right edge."""
    t, c = find(proj, clip_id)
    rng = free_range(t, c["start_us"], end(c), ignore=c)
    hi = rng[1]
    src_len = source_length(c)
    if src_len is not None and project.frozen(c) is None:      # (a frozen clip can be any length)
        hi = min(hi, c["start_us"] + (src_len - c.get("source_start_us", 0)) / project.speed(c))
    g = group_of(proj, t)
    if g is not None:
        hi = min(hi, g["duration_us"])                           # not out of its group
    lo = c["start_us"] + MIN_US
    if project.is_group(c):                                      # a group never cuts its clips
        lo = max(lo, c["start_us"] + _content_span(c)[1])
    new_end_us = int(max(min(new_end_us, hi), lo))
    c["duration_us"] = new_end_us - c["start_us"]
    return c


def split(proj, clip_id, at_us):
    """Cut a clip in two at at_us (timeline time); returns the new right-hand clip. A group
    is cut with its clips (those across at_us are cut too)."""
    t, c = find(proj, clip_id)
    at_us -= abs_start(proj, clip_id) - c["start_us"]            # (a group's clip: in its group's time)
    if not (c["start_us"] + MIN_US <= at_us <= end(c) - MIN_US):
        raise EditError("the playhead is not inside the clip")
    at_us = int(at_us)
    d = at_us - c["start_us"]
    right = copy.deepcopy({k: v for k, v in c.items() if k != "compound"})
    if "compound" in c:
        right["compound"] = c["compound"]      # both halves show the same shared compound
    right["id"] = new_clip_id(proj)
    if project.is_group(c):
        _split_group(c, right, at_us - c["start_us"])
    right["start_us"] = at_us
    right["duration_us"] = end(c) - at_us
    right["source_start_us"] = round(c.get("source_start_us", 0) + d * project.speed(c))
    shift_keys(right, d)
    c["duration_us"] = d
    if c.get("fade_out_us"):                  # fades belong to the outer ends
        right["fade_in_us"] = 0
        c["fade_out_us"] = 0
    t["clips"].append(right)
    _sort(t)
    return right


def _content_span(g):
    """(first start, last end) of a group's clips, in its time ((0, MIN_US) when empty)."""
    clips = [k for t in g["tracks"] for k in t["clips"]]
    if not clips:
        return 0, MIN_US
    return min(k["start_us"] for k in clips), max(end(k) for k in clips)


def _reid(c):
    """New ids for a copied group's clips and tracks (at every depth)."""
    if project.is_group(c):
        for t in c["tracks"]:
            t["id"] = "g" + uuid.uuid4().hex[:8]
            for k in t["clips"]:
                k["id"] = new_clip_id()
                _reid(k)


def _split_group(left, right, d):
    """Share a group's clips between its two halves cut d after its start: right is a copy
    (its own ids) that keeps what comes after d, shifted to its new start."""
    for lt, rt in zip(left["tracks"], right["tracks"]):
        keep_l, keep_r = [], []
        for lk, rk in zip(list(lt["clips"]), list(rt["clips"])):
            if end(lk) <= d:
                keep_l.append(lk)
            elif lk["start_us"] >= d:
                rk["start_us"] -= d
                keep_r.append(rk)
            else:                                                # across the cut: both halves
                piece = split({"tracks": [lt]}, lk["id"], d)
                lt["clips"].remove(piece)
                piece["start_us"] -= d
                keep_l.append(lk)
                keep_r.append(piece)
        lt["clips"], rt["clips"] = keep_l, keep_r
    _reid(right)


def delete(proj, clip_id):
    t, c = find(proj, clip_id)
    t["clips"].remove(c)


def delete_many(proj, clip_ids):
    for cid in clip_ids:
        delete(proj, cid)


def display_groups(proj):
    """(pictures, sound) tracks as the timeline lists them, top row first."""
    visual = [t for t in proj["tracks"] if t["kind"] != "audio"]
    return list(reversed(visual)), [t for t in proj["tracks"] if t["kind"] == "audio"]


def move_many(proj, clip_ids, d_us, d_rows=0):
    """Shift several clips by d_us in time and d_rows rows down the screen (negative: up). Every
    clip keeps its row distance to the others and stays among pictures / among sound. Refuses
    (changing nothing) when a clip would land on one that is not moving or outside the tracks;
    never moves anything before 0."""
    ids = set(clip_ids)
    moving = [find(proj, cid) for cid in clip_ids]
    if not moving:
        return []
    d_us = int(max(d_us, -min(c["start_us"] for _, c in moving)))
    pictures, sound = display_groups(proj)
    plan = []                                         # (clip, from track, to track)
    for t, c in moving:
        group = sound if t["kind"] == "audio" else pictures
        j = next((i for i, x in enumerate(group) if x is t), None)
        if j is None:
            raise EditError("群組裡的片段只能在群組的軌道之間移動")
        j += int(d_rows)
        if not 0 <= j < len(group):
            raise EditError("no track there")
        plan.append((c, t, group[j]))
    for c, _, dst in plan:
        s, e = c["start_us"] + d_us, end(c) + d_us
        if any(o["id"] not in ids and o["start_us"] < e and end(o) > s for o in dst["clips"]):
            raise EditError("no room there")
    for c, src, dst in plan:
        c["start_us"] += d_us
        if dst is not src:
            src["clips"].remove(c)
            dst["clips"].append(c)
    for _, src, dst in plan:
        _sort(src)
        _sort(dst)
    return [c for _, c in moving]


def copy_clips(level, clip_ids):
    """What paste_clips needs to make copies of these clips (any selection of one level)."""
    items = []
    for cid in clip_ids:
        t, c = find(level, cid)
        items.append({"track": t["id"], "kind": t["kind"], "compound": c.get("compound"),
                      "clip": copy.deepcopy({k: v for k, v in c.items() if k != "compound"})})
    if not items:
        raise EditError("nothing is selected")
    items.sort(key=lambda i: i["clip"]["start_us"])
    return {"anchor_us": items[0]["clip"]["start_us"], "items": items}


def paste_clips(root, level, payload, at_us):
    """Put copies of copy_clips' clips into `level` with the earliest one at at_us, keeping
    their spacing. Each goes back to its own track if it fits there, else to another track
    of its kind with room, else to a new track. Returns the new clips."""
    at_us, anchor = max(0, int(at_us)), payload["anchor_us"]
    own = _container_id(root, level)
    new = []
    for item in payload["items"]:
        c = copy.deepcopy(item["clip"])
        ref = project.ref_of(c)
        if ref and own is not None and project.contains(root, ref, own):
            raise EditError("a timeline or compound cannot show itself")
        c["id"] = new_clip_id()
        _reid(c)                                        # (a group's clips get ids of their own)
        c["start_us"] = at_us + c["start_us"] - anchor
        if ref:
            c["compound"] = item["compound"]            # shared, as for the original
        s, e = c["start_us"], c["start_us"] + c["duration_us"]
        kind = item["kind"]
        orig = next((t for t in level["tracks"] if t["id"] == item["track"] and t["kind"] == kind), None)
        tracks = ([orig] if orig else []) + [t for t in level["tracks"] if t["kind"] == kind and t is not orig]
        track = next((t for t in tracks if free_range(t, s, e) is not None), None)
        if track is None:
            track = add_track(level, kind, near_id=item["track"])
        track["clips"].append(c)
        _sort(track)
        new.append(c)
    project.link(root)
    return new


def duplicate_clips(root, level, clip_ids):
    """Copies of the clips right after the last of them (on the same tracks when free)."""
    payload = copy_clips(level, clip_ids)
    return paste_clips(root, level, payload,
                       max(i["clip"]["start_us"] + i["clip"]["duration_us"] for i in payload["items"]))


def duplicate_moved(root, level, clip_ids, d_us=0, d_rows=0, moves=None, t_of=None):
    """Alt+drag: copies of the clips, the originals staying where they are. On the timeline
    the copies go d_us later and d_rows rows down (negative: up) - onto that row when it is
    of their kind and free there, else wherever paste_clips finds room. On the preview
    (d_us 0) each copy goes just above its original (the free row above, else a new one) and
    gets moves[original id] ({x, y}) at clip time t_of(original id). Returns the new clips."""
    payload = copy_clips(level, clip_ids)
    pictures, sound = display_groups(level)
    for item in payload["items"]:
        c = item["clip"]
        src = track_by_id(level, item["track"])
        group = sound if src["kind"] == "audio" else pictures
        i = next(j for j, x in enumerate(group) if x is src)
        s, e = c["start_us"] + d_us, end(c) + d_us
        if d_us == 0 and not d_rows:                     # in place: on top of the original
            above = group[i - 1] if i > 0 and src["kind"] != "audio" else None
            if above is None or above["kind"] != src["kind"] or free_range(above, s, e) is None:
                above = add_track(level, src["kind"], near_id=src["id"])
                pictures, sound = display_groups(level)
            item["track"] = above["id"]
        elif 0 <= i + int(d_rows) < len(group):
            dst = group[i + int(d_rows)]
            if dst["kind"] == src["kind"]:
                item["track"] = dst["id"]
    new = paste_clips(root, level, payload, max(0, payload["anchor_us"] + int(d_us)))
    for item, c in zip(payload["items"], new):
        old = item["clip"]["id"]
        for key, v in ((moves or {}).get(old) or {}).items():
            set_param(level, c["id"], "transform", key, v, t_of(old) if t_of else None)
    return new


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


TEXT_FIELDS = ("content", "font_path", "size", "color", "letter_spacing", "line_spacing", "italic_deg", "align")
TEXT_ALIGNS = ("left", "center", "right", "justify")      # 對齊 (justify: 齊頭尾)
TRANSFORM_FIELDS = ("x", "y", "scale", "scale_y", "rotation", "opacity")


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


def subtitle_line(content):
    """A text clip's words as one line of the 字幕 tab: its own line breaks become \\n."""
    return content.replace("\n", "\\n")


def subtitle_lines(text):
    """The 字幕 tab's text back as one content per line (trailing blank lines dropped)."""
    lines = text.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    return [ln.replace("\\n", "\n") for ln in lines]


def set_texts(proj, contents):
    """Batch edit: {clip id: words} for several text clips at once."""
    for cid, content in contents.items():
        set_text(proj, cid, content=content)


def replace_fonts(proj, mapping):
    """字體對應's 換成: every text of the project (all timelines and compounds, keyframes and
    styled ranges too) that uses a font file of mapping {old file: new file} uses the new one
    instead. Returns how many texts changed."""
    want = {k.replace("\\", "/"): v for k, v in mapping.items() if v}
    swap = lambda v: want.get(v.replace("\\", "/"), v) if isinstance(v, str) else v
    n = 0
    for c in project.all_clips(proj):
        tx = c.get("text")
        if not tx:
            continue
        before = json.dumps(tx, sort_keys=True)
        p = tx.get("font_path")
        if curves.is_animated(p):
            for k in p["keys"]:
                k[1] = swap(k[1])
        else:
            tx["font_path"] = swap(p)
        for st in tx.get("styles") or []:
            if "font_path" in st:
                st["font_path"] = swap(st["font_path"])
        n += json.dumps(tx, sort_keys=True) != before
    if not n:
        raise EditError("沒有文字用到這些字體")
    return n


STYLE_TEXT_FIELDS = ("font_path", "size", "color", "letter_spacing", "line_spacing", "italic_deg", "align")


def apply_text_style(proj, clip_id, style):
    """Give a text clip a saved look (userlib.style_from_clip): font, size, colour, spacing,
    slant and scale. The words stay; keyframes of the replaced values are dropped."""
    _, c = find(proj, clip_id)
    if c["type"] != "text":
        raise EditError("not a text clip")
    for k, v in (style.get("text") or {}).items():
        if k in STYLE_TEXT_FIELDS:
            c["text"][k] = copy.deepcopy(v)
    c["text"].pop("styles", None)
    for k, v in (style.get("transform") or {}).items():
        if k in ("scale", "scale_y") and c.get("transform") is not None:
            c["transform"][k] = v
    return c


def set_transform(proj, clip_id, key, value, t=None):
    """Set a transform value; keyframed ones are edited at clip time t (see set_param)."""
    if key not in TRANSFORM_FIELDS:
        raise EditError(f"unknown transform field {key}")
    return set_param(proj, clip_id, "transform", key, value, t)


# -- keyframes ------------------------------------------------------------------------------------
TEXT_ANIM_FIELDS = ("size", "color", "letter_spacing", "line_spacing", "italic_deg", "font_path", "align")
GROUP_FIELDS = {
    "transform": TRANSFORM_FIELDS,
    "text": TEXT_ANIM_FIELDS,
    "mask": ("cx", "cy", "w", "h", "rotation", "feather", "kind", "invert"),
    "clip": ("volume", "blend"),
}
# how a picture mixes with what is under it (render.BLEND_OPS draws them)
BLEND_MODES = ("normal", "multiply", "screen", "overlay", "darken", "lighten", "color_dodge", "color_burn",
               "hard_light", "soft_light", "difference", "exclusion", "add")
DISCRETE_DEFAULTS = {"font_path": project.DEFAULT_FONT, "kind": "rectangle", "invert": False, "blend": "normal",
                     "align": "center"}
KEY_TOL_US = 1_000_000 // 120      # half a 60 fps frame
EASINGS = {                        # CSS-style cubic-bezier control x positions
    "linear": (0.0, 1.0),
    "ease_in": (0.42, 1.0),
    "ease_out": (0.0, 0.58),
    "ease_in_out": (0.42, 0.58),
}


def _effect(c, effect_id):
    for e in c.get("effects") or []:
        if e["id"] == effect_id:
            return e
    raise EditError("effect not found")


def _valid_key(c, group, key):
    """Whether `key` is a parameter of `group` (groups "fx:<effect id>" and
    "fxmask:<effect id>" are an effect's own parameters and mask)."""
    if group.startswith("fx:"):
        return key in _effect(c, group[3:])["params"]
    if group.startswith("fxmask:"):
        return key in GROUP_FIELDS["mask"]
    if group == "asset":
        return bool(c.get("asset")) and key in assets.fields_of(c["asset"].get("family"))
    return key in GROUP_FIELDS.get(group, ())


def holder(c, group):
    """The dict that holds the parameters of `group` of clip c."""
    return _holder(c, group)


def _holder(c, group):
    if group.startswith("fx:"):
        return _effect(c, group[3:])["params"]
    if group.startswith("fxmask:"):
        e = _effect(c, group[7:])
        if not e.get("mask"):
            raise EditError("effect has no mask")
        return e["mask"]
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
    if group == "asset":
        if not c.get("asset"):
            raise EditError("not a built-in asset")
        return c["asset"]
    return c.setdefault("transform", {})


def _check(c, group, key, t):
    if not _valid_key(c, group, key):
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


def _coerce(value):
    """A parameter value as stored: numbers as floats, colours as float lists, choices
    (text, true / false, nothing) as they are (curves.discrete)."""
    if isinstance(value, (list, tuple)):
        return [float(v) for v in value]
    return value if curves.discrete(value) else float(value)


def _check_choice(c, group, key, value):
    if key == "kind" and value not in MASK_KINDS:
        raise EditError(f"unknown mask {value}")
    if key == "align" and group == "text" and value not in TEXT_ALIGNS:
        raise EditError(f"unknown text alignment {value}")
    if key == "blend" and group == "clip":
        if c["type"] not in VISUAL or c["type"] == "filter":
            raise EditError("blend modes go on pictures, videos, texts and compound clips")
        if value not in BLEND_MODES:
            raise EditError(f"unknown blend mode {value}")
    if group.startswith("fx:"):
        p = next((q for q in fx.get(_effect(c, group[3:])["filter"]).params if q.name == key), None)
        if p is not None and p.type == "menu" and value not in p.items:
            raise EditError(f"{key} has no choice {value!r}")


def linked(h):
    """Whether a transform's X and Y scale change together (the default)."""
    return h.get("scale_link", True) is not False


def with_linked_scale(h, values, t):
    """A transform edit (values at clip time t) plus what X / Y scale linking adds: the other
    scale keeps their ratio. While Y has no curve of its own it follows X; unlinked, it keeps
    its value instead."""
    out = dict(values)
    if "scale_y" not in h:
        if linked(h) and "scale_y" in out:
            out.setdefault("scale", out.pop("scale_y"))
        elif not linked(h) and "scale" in out and "scale_y" not in out:
            out["scale_y"] = curves.value(h.get("scale", 1.0), t)
        return out
    if linked(h):
        for key, other in (("scale", "scale_y"), ("scale_y", "scale")):
            if key in out and other not in out:
                cur = curves.value(h.get(key, 1.0), t)
                out[other] = curves.value(h.get(other, 1.0), t) * out[key] / cur if cur else out[key]
    return out


def set_param(proj, clip_id, group, key, value, t=None):
    """Set a parameter. Static ones change outright; keyframed ones get their key at t
    (clip time) updated, or a new key there - as Jianying does when you change a value.
    Transform scales follow X / Y linking (with_linked_scale)."""
    _, c = find(proj, clip_id)
    h = _holder(c, group)
    if group == "transform" and key in ("scale", "scale_y"):
        if "scale_y" not in h and not linked(h):
            h["scale_y"] = copy.deepcopy(h.get("scale", 1.0))     # Y gets a curve of its own
        for k, v in with_linked_scale(h, {key: value}, t).items():
            _set_one(c, h, group, k, v, t)
        return c
    if group == "transform" and key == "scale_link":
        h[key] = bool(value)
        return c
    if group == "asset":
        if not _valid_key(c, group, key):
            raise EditError(f"unknown asset field {key}")
        value = assets.clean(key, value)
    _set_one(c, h, group, key, value, t)
    return c


def _set_one(c, h, group, key, value, t):
    p = h.get(key)
    value = _coerce(value)
    _check_choice(c, group, key, value)
    if group == "text" and key in ("size", "color"):
        h.pop("styles", None)                    # a whole-clip style replaces per-range ones
    if not curves.is_animated(p):
        h[key] = value
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
    Removing the last key leaves the parameter at that key's value. Linked X / Y scales
    get or lose their keys together."""
    _, c = find(proj, clip_id)
    _check(c, group, key, t)
    h = _holder(c, group)
    if group == "transform" and key in ("scale", "scale_y"):
        if key == "scale_y" and "scale_y" not in h:
            h["scale_y"] = copy.deepcopy(h.get("scale", 1.0))
        other = "scale_y" if key == "scale" else "scale"
        adding = key_at(h.get(key, 1.0), t) is None
        _toggle_one(c, h, group, key, t)
        if linked(h) and other in h and (key_at(h[other], t) is None) == adding:
            _toggle_one(c, h, group, other, t)
        return c
    return _toggle_one(c, h, group, key, t)


def _toggle_one(c, h, group, key, t):
    if key in DISCRETE_DEFAULTS and not group.startswith("fx:"):
        _check_choice(c, group, key, DISCRETE_DEFAULTS[key])
        default = DISCRETE_DEFAULTS[key]
    else:
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
    if curves.discrete(a[1]):
        raise EditError("a choice holds until the next keyframe: it has no curve")
    dt = b[0] - a[0]
    x1, x2 = EASINGS[easing]
    a[4], a[5] = x1 * dt, 0.0                    # handles are flat: ease, not overshoot
    b[2], b[3] = (x2 - 1.0) * dt, 0.0
    return c


def easing_at(p, t):
    """Name of the preset matching the segment that starts at the key at t, if any."""
    i = key_at(p, t)
    if i is None or i + 1 >= len(p["keys"]) or curves.discrete(p["keys"][i][1]):
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
    for group in ("transform", "mask", "text", "asset"):
        for v in (c.get(group) or {}).values():
            if curves.is_animated(v):
                times |= {k[0] for k in v["keys"]}
    for key in ("volume", "blend"):
        if curves.is_animated(c.get(key)):
            times |= {k[0] for k in c[key]["keys"]}
    for e in c.get("effects") or []:
        for v in list(e["params"].values()) + list((e.get("mask") or {}).values()):
            if curves.is_animated(v):
                times |= {k[0] for k in v["keys"]}
    return sorted(times)


def move_keys_at(proj, clip_id, t_from, t_to):
    """Move every keyframe of a clip at clip time t_from to t_to (the timeline's ◆)."""
    _, c = find(proj, clip_id)
    t_to = int(min(max(t_to, 0), c["duration_us"]))
    moved = 0
    for p in _params(c):
        i = key_at(p, t_from)
        if i is None:
            continue
        if any(j != i and abs(k[0] - t_to) <= KEY_TOL_US for j, k in enumerate(p["keys"])):
            raise EditError("another keyframe is already there")
        p["keys"][i][0] = t_to
        p["keys"].sort(key=lambda k: k[0])
        # keep the bezier handles inside their (new) neighbours
        for j, k in enumerate(p["keys"]):
            prev_dt = k[0] - p["keys"][j - 1][0] if j else 0
            next_dt = p["keys"][j + 1][0] - k[0] if j + 1 < len(p["keys"]) else 0
            k[2] = min(0.0, max(k[2], -prev_dt))
            k[4] = max(0.0, min(k[4], next_dt))
        moved += 1
    if not moved:
        raise EditError("no keyframe there")
    return c


# -- masks ----------------------------------------------------------------------------------------
MASK_KINDS = ("line", "mirror", "circle", "rectangle")


def _aspect(c):
    """Width / height of the clip's material, so default circles come out round."""
    if c.get("media", {}).get("width"):
        return c["media"]["width"] / c["media"]["height"]
    if c.get("compound"):
        return c["compound"]["width"] / c["compound"]["height"]
    return 16 / 9


MATTES = ("alpha", "luma")          # what of a compound mask's picture lets the clip through
PICTURE_MASKS = ("compound", "image")   # masks that cut with a picture: a compound's, or an image file


def _new_mask(old, kind, aspect):
    """A mask of `kind` keeping what it can of the old one (shape keyframes too)."""
    if kind in PICTURE_MASKS:          # a compound's / an image's picture cuts the clip: chosen next
        m = {"kind": kind, "matte": old.get("matte", "alpha"),
             "invert": old.get("invert", False), "cx": old.get("cx", 0.0), "cy": old.get("cy", 0.0),
             "w": old.get("w", 1.0), "h": old.get("h", 1.0), "rotation": old.get("rotation", 0.0),
             "feather": old.get("feather", 0.0)}
        for k in (("compound_id", "t_off") if kind == "compound" else ("image", "img_w", "img_h")):
            if old.get(k) is not None:
                m[k] = old[k]
        if kind == "compound":
            m.setdefault("compound_id", None)
        return m
    size = {"line": (1.0, 1.0), "mirror": (1.0, 0.3), "circle": (0.5, 0.5 * aspect),
            "rectangle": (0.5, 0.5 * aspect)}[kind]
    line = kind == "line" and not curves.is_animated(old.get("kind"))
    return {"kind": old["kind"] if curves.is_animated(old.get("kind")) else kind,
            "invert": old.get("invert", False), "cx": old.get("cx", 0.0), "cy": old.get("cy", 0.0),
            "w": old.get("w", size[0]) if not line else 1.0,
            "h": old.get("h", size[1]) if not line else 1.0,
            "rotation": old.get("rotation", 0.0), "feather": old.get("feather", 0.0)}


def set_mask(proj, clip_id, kind, t=None):
    """Give a clip a mask of `kind` (keeping its position), or remove it with None. A shape
    with keyframes gets its keyframe at clip time t set (or added), as numbers do."""
    _, c = find(proj, clip_id)
    if c["type"] not in ("image", "video", "compound", "filter", "group"):
        raise EditError("masks go on pictures, videos, compound clips, groups and filters")
    if kind is None:
        c.pop("mask", None)
        return c
    if kind not in MASK_KINDS and kind not in PICTURE_MASKS:
        raise EditError(f"unknown mask {kind}")
    old = c.get("mask") or {}
    if curves.is_animated(old.get("kind")) and kind not in PICTURE_MASKS:
        return set_param(proj, clip_id, "mask", "kind", kind, t)
    c["mask"] = _new_mask(dict(old, kind=None) if curves.is_animated(old.get("kind")) else old, kind, _aspect(c))
    if old.get("enabled") is False:
        c["mask"]["enabled"] = False
    return c


def set_mask_compound(proj, clip_id, compound_id=None, comp=None, matte=None):
    """A compound mask's compound (compound_id, its entry comp: the mask takes the compound's
    proportions, fitted into the clip) and / or what of its picture cuts: "alpha" or "luma"."""
    _, c = find(proj, clip_id)
    m = c.get("mask")
    if not m or m.get("kind") not in PICTURE_MASKS or (compound_id is not None and m.get("kind") != "compound"):
        raise EditError("這個片段的遮罩不是複合片段")
    if compound_id is not None:
        if comp is None:
            raise EditError("找不到這個複合片段")
        a, b = _aspect(c), comp["width"] / comp["height"]      # the clip's material, the compound
        m["compound_id"] = compound_id
        m["w"], m["h"] = (1.0, round(a / b, 4)) if b > a else (round(b / a, 4), 1.0)
    if matte is not None:
        if matte not in MATTES:
            raise EditError(f"unknown matte {matte}")
        m["matte"] = matte
    return c


def set_mask_enabled(proj, clip_id, on):
    """Switch a clip's mask on or off, keeping its settings; switching on a clip without
    a mask gives it a rectangle."""
    _, c = find(proj, clip_id)
    if not c.get("mask"):
        if not on:
            return c
        set_mask(proj, clip_id, "rectangle")
    if on:
        c["mask"].pop("enabled", None)
    else:
        c["mask"]["enabled"] = False
    return c


BEAT_DEFAULT = {"on": False, "bpm": 120.0, "offset_us": 0, "div": 1, "meter": 4}
# meter (拍號): beats in a bar - the first beat of every bar gets a longer line; 0: no bars
METERS = (0, 2, 3, 4, 5, 6, 7, 9, 12)
# grid lines per beat: 0.25 / 0.5 a line every 4 / 2 beats (the BPM ÷4 / ÷2: 180 -> 90, the
# BPM itself unchanged), 1 on every beat, 2 / 3 / 4 / 6 the beat split into halves ... sixths
BEAT_DIVS = (0.25, 0.5, 1, 2, 3, 4, 6)
BPM_MIN, BPM_MAX = 1.0, 999.0


def has_sound(c):
    """Whether a clip plays sound of its own: a sound clip, or a video with a sound track."""
    return c.get("type") == "audio" or (c.get("type") == "video" and "volume" in c)


def set_beat(proj, clip_id, **fields):
    """Change a sound clip's BPM grid (on, bpm, offset_us, div); a clip without one gets
    the defaults first. Switching it off keeps the numbers."""
    _, c = find(proj, clip_id)
    if not has_sound(c):
        raise EditError("只有有聲音的片段可以 BPM 對齊")
    beat = c.setdefault("beat", dict(BEAT_DEFAULT))
    for k, v in fields.items():
        if k not in BEAT_DEFAULT:
            raise EditError(f"unknown beat field {k}")
        if k == "div" and v not in BEAT_DIVS:
            raise EditError(f"細分只能是 {BEAT_DIVS}")
        if k == "meter":
            if int(v) not in METERS:
                raise EditError(f"拍號只能是 {METERS} 拍一小節")
            beat[k] = int(v)
            continue
        if k == "div":
            v = int(v) if v >= 1 else float(v)
        beat[k] = (bool(v) if k == "on" else v if k == "div" else int(round(v)) if k == "offset_us"
                   else min(BPM_MAX, max(BPM_MIN, float(v))))
    return c


def clear_beat(proj, clip_id):
    """Remove a clip's BPM grid altogether (it is off afterwards)."""
    _, c = find(proj, clip_id)
    c.pop("beat", None)
    return c


def beat_times(c, lo=None, hi=None):
    """Timeline times (us) of the grid lines (beats and their subdivisions) of a clip with
    BPM alignment on, inside the clip (and inside lo..hi when given)."""
    return [t for t, _ in beat_grid(c, lo, hi)]


def beat_grid(c, lo=None, hi=None, bars=False):
    """[(time us, d)] of a clip's grid lines: d is the line's place in the beat as the
    denominator of a reduced fraction - 1 on the beat, 2 on the half, 3 / 4 / 6 on thirds,
    quarters, sixths (a grid of every 2 or 4 beats is all on beats); with bars, 0 on the
    first beat of a bar (every meter beats from beat 0). The grid belongs to the sound:
    offset_us is the first beat's time in the source, so trimming or splitting the clip keeps
    it on the music."""
    beat = c.get("beat")
    if not beat or not beat.get("on") or not beat.get("bpm"):
        return []
    div = beat.get("div", 1) if beat.get("div", 1) in BEAT_DIVS else 1
    k = project.speed(c)                                 # (the beats are the source's: faster with it)
    period = 60 * US / beat["bpm"] / div / k
    zero = c["start_us"] + (beat.get("offset_us", 0) - c.get("source_start_us", 0)) / k   # timeline time of beat 0
    a, b = c["start_us"], end(c)
    if lo is not None:
        a = max(a, lo)
    if hi is not None:
        b = min(b, hi)
    if b < a:
        return []
    k0, k1 = math.ceil((a - zero) / period - 1e-9), math.floor((b - zero) / period + 1e-9)
    meter = int(beat.get("meter", BEAT_DEFAULT["meter"]) or 0) if bars else 0
    if div < 1:
        step = round(1 / div)                            # beats per line
        return [(zero + k * period, 0 if meter and (k * step) % meter == 0 else 1) for k in range(k0, k1 + 1)]
    out = []
    for k in range(k0, k1 + 1):
        d = div // math.gcd(k % div, div)
        out.append((zero + k * period, 0 if meter and d == 1 and (k // div) % meter == 0 else d))
    return out


TIMED = ("video", "audio", "compound")          # clips with a source time: speed and 凍結幀
SPEED_MIN, SPEED_MAX = 0.01, 100.0


def _timed(c):
    if c["type"] not in TIMED or project.is_static(c):
        raise EditError("只有影片、聲音和複合片段可以調速度或凍結")


def scale_keys(c, k):
    """Every keyframe's time (and bezier handles) times k: the clip's time stretched."""
    for p in _params(c):
        for key in p["keys"]:
            key[0] = round(key[0] * k)
            for i in (2, 4):
                if len(key) > i:
                    key[i] = round(key[i] * k)


def set_speed(proj, clip_id, value):
    """A clip's speed: its source plays value times as fast. The clip keeps the same stretch
    of its source, so it gets shorter or longer - as far as the room after it allows (and its
    source lasts); keyframes and fades stretch with it."""
    t, c = find(proj, clip_id)
    _timed(c)
    value = min(SPEED_MAX, max(SPEED_MIN, float(value)))
    old = project.speed(c)
    k = old / value                                      # the clip's new length / its old one
    dur = c["duration_us"] * k
    room = free_range(t, c["start_us"], end(c), ignore=c)[1] - c["start_us"]
    src_len = source_length(c)
    if src_len is not None and project.frozen(c) is None:
        room = min(room, (src_len - c.get("source_start_us", 0)) / value)
    new_dur = int(max(MIN_US, min(dur, room)))
    scale_keys(c, new_dur / c["duration_us"] if c["duration_us"] else k)
    for f in ("fade_in_us", "fade_out_us"):
        if c.get(f):
            c[f] = int(min(c[f] * k, new_dur))
    c["duration_us"] = new_dur
    if abs(value - 1.0) < 1e-9:
        c.pop("speed", None)
    else:
        c["speed"] = value
    return c


def set_freeze(proj, clip_id, on, src_us=None):
    """凍結幀: hold the clip at source time src_us (default: where it is now held, else its
    first frame) - or let it play again."""
    _, c = find(proj, clip_id)
    _timed(c)
    f = c.setdefault("freeze", {"on": False, "src_us": c.get("source_start_us", 0)})
    f["on"] = bool(on)
    if src_us is not None:
        length = source_length(c)
        f["src_us"] = int(max(0, min(src_us, (length - 1) if length else src_us)))
    if not f["on"] and src_us is None:
        c.pop("freeze", None)
    return c


def set_mask_image(proj, clip_id, path, width, height):
    """An image mask's picture: the file at path (width x height px); the mask takes its
    proportions, fitted into the clip."""
    _, c = find(proj, clip_id)
    m = c.get("mask")
    if not m or m.get("kind") != "image":
        raise EditError("這個片段的遮罩不是圖片")
    if not path or not width or not height:
        raise EditError("找不到這張圖片")
    a, b = _aspect(c), width / height
    m.update(image=path, img_w=int(width), img_h=int(height))
    m["w"], m["h"] = (1.0, round(a / b, 4)) if b > a else (round(b / a, 4), 1.0)
    return c


def set_mask_offset(proj, clip_id, t_off):
    """編輯區域: which part of a (live) compound mask's compound plays - its time at the clip's
    start (us; the compound plays on from there with the clip)."""
    _, c = find(proj, clip_id)
    m = c.get("mask")
    if not m or m.get("kind") != "compound":
        raise EditError("這個片段的遮罩不是複合片段")
    t_off = int(round(t_off))
    if t_off:
        m["t_off"] = t_off
    else:
        m.pop("t_off", None)
    return c


# -- groups (群組) ----------------------------------------------------------------------------------
GROUP_MATTE_DEFAULT = {"on": False, "show": False, "invert": False, "body": True}


def make_group(root, level, clip_ids):
    """Put picture clips of the open level into a new group (Ctrl+G) and return it: it spans
    them, sits on the topmost picture track they used (or a new one above it when that has no
    room), and the tracks they were on come along, in order - their clips keep their places
    on the canvas and in time."""
    picked = [find(level, cid) for cid in dict.fromkeys(clip_ids)]
    if not picked:
        raise EditError("先選取要放進群組的片段")
    if any(t["kind"] == "audio" for t, _ in picked):
        raise EditError("群組只放畫面片段：選取裡有聲音片段")
    owners = {id(group_of(level, t)) for t, _ in picked}
    if len(owners) > 1:
        raise EditError("選取的片段在不同的群組裡")
    outer = group_of(level, picked[0][0])
    holder = outer["tracks"] if outer is not None else level["tracks"]
    ids = {c["id"] for _, c in picked}
    s0 = min(c["start_us"] for _, c in picked)
    span = max(end(c) for _, c in picked) - s0
    used = [t for t in holder if any(t is tt for tt, _ in picked)]           # bottom first
    inner = []
    for t in used:
        moved = [c for c in t["clips"] if c["id"] in ids]
        t["clips"] = [c for c in t["clips"] if c["id"] not in ids]
        for c in moved:
            c["start_us"] -= s0
        inner.append({"id": "g" + uuid.uuid4().hex[:8], "kind": t["kind"], "name": t.get("name") or t["kind"],
                      "clips": moved})
    n = sum(1 for c in project.walk_clips(level["tracks"]) if project.is_group(c)) + 1
    group = {"id": new_clip_id(), "type": "group", "name": f"群組 {n}", "start_us": int(s0), "duration_us": int(span),
             "source_start_us": 0, "tracks": inner, "matte": dict(GROUP_MATTE_DEFAULT),
             "transform": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}}
    top = next((t for t in reversed(used) if t["kind"] == "video"), None)
    if top is None or free_range(top, s0, s0 + span) is None:
        at = holder.index(used[-1]) + 1
        n = sum(1 for t in holder if t["kind"] == "video") + 1
        top = {"id": "g" + uuid.uuid4().hex[:8] if outer is not None else new_track_id(level), "kind": "video",
               "name": f"video {n}", "clips": []}
        holder.insert(at, top)
    top["clips"].append(group)
    _sort(top)
    project.link(root)
    return group


def ungroup(root, level, group_id):
    """Take a group's clips out of it (Ctrl+Shift+G): onto tracks of the level around the
    group's (one of their kind with room, going up from it, else a new one above), at the same
    times, with the group's position, scale and opacity folded into theirs. A turned group,
    or one whose transform has keyframes, is refused (that cannot be folded in exactly)."""
    t, g = find(level, group_id)
    if not project.is_group(g):
        raise EditError("這不是群組")
    tf = g.get("transform") or {}
    if any(curves.is_animated(v) for v in tf.values()) or abs(curves.value(tf.get("rotation", 0.0), 0)) > 1e-9 \
            or tf.get("flip_h") or tf.get("flip_v"):
        raise EditError("群組有旋轉或關鍵幀動畫：先把它們歸零再解散")
    gx, gy = float(tf.get("x", 0.0)), float(tf.get("y", 0.0))
    gs = float(tf.get("scale", 1.0))
    gsy = float(tf.get("scale_y", gs))
    go = float(tf.get("opacity", 1.0))
    outer = group_of(level, t)
    holder = outer["tracks"] if outer is not None else level["tracks"]
    t["clips"].remove(g)
    at = holder.index(t)
    out = []
    for ct in g["tracks"]:                                       # bottom first: each goes above the last
        for k in ct["clips"]:
            k["start_us"] += g["start_us"]
            ktf = k.get("transform")
            if ktf is not None:
                ktf["x"] = _map_value(ktf.get("x", 0.0), lambda v: gx + gs * v)
                ktf["y"] = _map_value(ktf.get("y", 0.0), lambda v: gy + gsy * v)
                sx = ktf.get("scale", 1.0)
                if "scale_y" in ktf or abs(gs - gsy) > 1e-9:
                    ktf["scale_y"] = _map_value(ktf.get("scale_y", sx), lambda v: v * gsy)
                ktf["scale"] = _map_value(sx, lambda v: v * gs)
                ktf["opacity"] = _map_value(ktf.get("opacity", 1.0), lambda v: v * go)
        dst = None
        for cand in holder[at:]:
            if cand["kind"] == ct["kind"] and all(free_range(cand, k["start_us"], end(k)) is not None for k in ct["clips"]):
                dst = cand
                break
        if dst is None:
            n = sum(1 for x in holder if x["kind"] == ct["kind"]) + 1
            dst = {"id": "g" + uuid.uuid4().hex[:8] if outer is not None else new_track_id(level), "kind": ct["kind"],
                   "name": ct.get("name") or f"{ct['kind']} {n}", "clips": []}
            holder.insert(at + 1, dst)
        dst["clips"] += ct["clips"]
        _sort(dst)
        at = holder.index(dst)
        out += ct["clips"]
    project.link(root)
    return out


def _flat_group(g):
    """(x, y, scale x, scale y) of a group that is not turned, flipped or animated in place
    or size (its clips' canvas place folds in and out of it exactly), else EditError."""
    tf = g.get("transform") or {}
    if any(curves.is_animated(tf.get(k)) for k in ("x", "y", "scale", "scale_y", "rotation")) \
            or abs(curves.value(tf.get("rotation", 0.0), 0)) > 1e-9 or tf.get("flip_h") or tf.get("flip_v"):
        raise EditError(f"「{g.get('name') or '群組'}」有旋轉或關鍵幀動畫：片段沒辦法不移動地放進去")
    gs = float(tf.get("scale", 1.0))
    gsy = float(tf.get("scale_y", gs))
    if abs(gs) < 1e-9 or abs(gsy) < 1e-9:
        raise EditError("群組的縮放是 0")
    return float(tf.get("x", 0.0)), float(tf.get("y", 0.0)), gs, gsy


def _groups_around(level, track):
    """The groups a track is inside, innermost first."""
    out, g = [], group_of(level, track)
    while g is not None:
        out.append(g)
        g = group_of(level, find(level, g["id"])[0])
    return out


def _refit(c, out_of, into):
    """Clip c's place and size from the space inside the groups out_of (innermost first) to
    the space inside into (innermost first), the same on the canvas."""
    ktf = c.get("transform")
    if ktf is None:
        return
    fx = [_flat_group(g) for g in out_of]
    tx = [_flat_group(g) for g in reversed(into)]                 # outermost first

    def axis(v, i):
        for f in fx:
            v = f[i] + f[2 + i] * v
        for f in tx:
            v = (v - f[i]) / f[2 + i]
        return v

    def size(v, i):
        for f in fx:
            v *= f[2 + i]
        for f in tx:
            v /= f[2 + i]
        return v
    sx = ktf.get("scale", 1.0)
    sy = ktf.get("scale_y", sx)
    ktf["x"] = _map_value(ktf.get("x", 0.0), lambda v: axis(v, 0))
    ktf["y"] = _map_value(ktf.get("y", 0.0), lambda v: axis(v, 1))
    if "scale_y" in ktf or any(abs(f[2] - f[3]) > 1e-9 for f in fx + tx):
        ktf["scale_y"] = _map_value(sy, lambda v: size(v, 1))
    ktf["scale"] = _map_value(sx, lambda v: size(v, 0))


def move_into_group(root, level, clip_ids, group_id, track_id=None, start_us=None):
    """移入群組: put picture clips of the open level (on it or in another group of it) into a
    group, the same on the canvas (the groups' places and sizes folded out of theirs and into
    the new one's) and in time; the group grows to take them in. track_id: a track of the group
    to put them on when there is room (else each goes on a track of its kind in the group with
    room, going up, or on a new one on top); start_us: where the first of them starts, in the
    level's time (else they keep their times). Returns the clips."""
    gt, g = find(level, group_id)
    if not project.is_group(g):
        raise EditError("這不是群組")
    picked = [find(level, cid) for cid in dict.fromkeys(clip_ids)]
    picked = [(t, c) for t, c in picked if not any(t is x for x in g["tracks"])]   # (already in it)
    if not picked:
        raise EditError("片段已經在這個群組裡")
    for t, c in picked:
        if t["kind"] == "audio":
            raise EditError("群組只放畫面片段：選取裡有聲音片段")
        if c is g or (project.is_group(c) and any(k is g for k in project.walk_clips(c["tracks"]))):
            raise EditError("群組不能放進自己裡面")
    into = [g] + _groups_around(level, gt)
    for x in into:
        _flat_group(x)                                             # (refused before anything changes)
    starts = {c["id"]: abs_start(level, c["id"]) for _, c in picked}
    shift = 0 if start_us is None else int(start_us) - min(starts.values())
    lo = min(starts.values()) + shift
    hi = max(starts[c["id"]] + c["duration_us"] for _, c in picked) + shift
    if lo < 0:
        raise EditError("片段不能放到時間 0 之前")
    g0 = abs_start(level, group_id)
    leaving = {id(c) for _, c in picked}
    room = free_range({"clips": [k for k in gt["clips"] if id(k) not in leaving]}, g["start_us"], end(g), ignore=g) \
        or (g["start_us"], end(g))
    outer = group_of(level, gt)
    if outer is not None:                                          # (a group in a group stays inside it)
        room = (room[0], min(room[1], outer["duration_us"]))
    if lo < g0:                                                    # grows to the left
        d = g0 - lo
        if g["start_us"] - d < room[0]:
            raise EditError("群組前面沒有空間放這些片段")
        g["start_us"] -= d
        g["duration_us"] += d
        shift_keys(g, -d)
        for ct in g["tracks"]:
            for k in ct["clips"]:
                k["start_us"] += d
        g0 = lo
    if hi > g0 + g["duration_us"]:                                 # and to the right
        if g["start_us"] + (hi - g0) > room[1]:
            raise EditError("群組後面沒有空間放這些片段")
        g["duration_us"] = hi - g0
    for t, c in picked:
        _refit(c, _groups_around(level, t), into)
        t["clips"].remove(c)
    out = []
    for t, c in sorted(picked, key=lambda tc: starts[tc[1]["id"]]):
        c["start_us"] = starts[c["id"]] + shift - g0
        kind = "text" if t["kind"] == "text" else "video"
        want = next((x for x in g["tracks"] if x["id"] == track_id and x["kind"] != "audio"), None)
        cands = ([want] if want else []) + [x for x in g["tracks"] if x["kind"] == kind]
        dst = next((x for x in cands if free_range(x, c["start_us"], end(c)) is not None), None)
        if dst is None:
            n = sum(1 for x in g["tracks"] if x["kind"] == kind) + 1
            dst = {"id": "g" + uuid.uuid4().hex[:8], "kind": kind, "name": f"{kind} {n}", "clips": []}
            g["tracks"].append(dst)
        dst["clips"].append(c)
        _sort(dst)
        out.append(c)
    project.link(root)
    return out


def group_ids(level):
    """[(group id, name)] of every group in the level, nested ones too, in order."""
    return [(c["id"], c.get("name") or "群組") for c in project.walk_clips(level["tracks"]) if project.is_group(c)]


def _map_value(v, fn):
    """fn applied to a value, or to every keyframe value of a curve."""
    if curves.is_animated(v):
        return {"keys": [[k[0], fn(k[1])] + list(k[2:]) for k in v["keys"]]}
    return fn(float(v))


def set_group_matte(proj, clip_id, on=None, show=None, invert=None, body=None):
    """A group's 遮罩: its bottom track's clips cut the clips above them (on), and are drawn
    too (show) - else only their shape counts; invert (反轉遮罩): the clips above are kept
    where the bottom ones are not (a hole in their shape); body (顯示主體, on unless set
    off): the clips above are drawn at all."""
    _, g = find(proj, clip_id)
    if not project.is_group(g):
        raise EditError("這不是群組")
    m = g.setdefault("matte", dict(GROUP_MATTE_DEFAULT))
    if on is not None:
        m["on"] = bool(on)
    if show is not None:
        m["show"] = bool(show)
    if invert is not None:
        m["invert"] = bool(invert)
    if body is not None:
        m["body"] = bool(body)
    return g


def set_backdrop(proj, clip_id, on=None, hide=None):
    """套用至背景 (on) and 隱藏本體 (hide) of a clip's effects (project.backdrop_of)."""
    _, c = find(proj, clip_id)
    if c["type"] not in VISUAL or c["type"] == "filter":
        raise EditError("只有畫面片段可以把效果套用到背景")
    b = c.setdefault("backdrop", {"on": False, "hide": False})
    if on is not None:
        b["on"] = bool(on)
    if hide is not None:
        b["hide"] = bool(hide)
    if not b["on"] and not b["hide"]:
        c.pop("backdrop")
    return c


def set_mask_invert(proj, clip_id, invert, t=None):
    _, c = find(proj, clip_id)
    if not c.get("mask"):
        raise EditError("clip has no mask")
    return set_param(proj, clip_id, "mask", "invert", bool(invert), t)


# -- filters ----------------------------------------------------------------------------------------
VISUAL = ("image", "video", "text", "compound", "filter", "group")
FILTER_DEFAULT_US = 5_000_000


def new_effect_id():
    return "e" + uuid.uuid4().hex[:8]


def add_effect(proj, clip_id, ref):
    """Put filter `ref` ("builtin:blur" or a filter file) on a clip, after the others."""
    _, c = find(proj, clip_id)
    if c["type"] not in VISUAL:
        raise EditError("filters go on pictures, videos, texts, compound clips and filter clips")
    e = fx.new_effect(ref, new_effect_id())
    c.setdefault("effects", []).append(e)
    return e


def add_effects(proj, clip_id, refs):
    """Several filters on a clip, in order (the files picked together in 選擇濾鏡檔案)."""
    return [add_effect(proj, clip_id, ref) for ref in refs]


def remove_effect(proj, clip_id, effect_id):
    _, c = find(proj, clip_id)
    c["effects"].remove(_effect(c, effect_id))
    if not c["effects"]:
        del c["effects"]
        if c["type"] == "filter":
            pass                                # a filter clip without effects does nothing, but stays


def set_effect_enabled(proj, clip_id, effect_id, on):
    _, c = find(proj, clip_id)
    e = _effect(c, effect_id)
    if on:
        e.pop("disabled", None)
    else:
        e["disabled"] = True


def move_effect(proj, clip_id, effect_id, delta):
    """Move an effect earlier (-1) or later (+1) in the clip's chain."""
    _, c = find(proj, clip_id)
    es = c["effects"]
    i = es.index(_effect(c, effect_id))
    j = i + (1 if delta > 0 else -1)
    if 0 <= j < len(es):
        es[i], es[j] = es[j], es[i]


def set_effect_mask(proj, clip_id, effect_id, kind, t=None):
    """Limit an effect to a shape (None removes it): coverage in the clip's own space. A
    shape with keyframes gets its keyframe at clip time t set (or added)."""
    _, c = find(proj, clip_id)
    e = _effect(c, effect_id)
    if kind is None:
        e.pop("mask", None)
        return e
    if kind not in MASK_KINDS:
        raise EditError(f"unknown mask {kind}")
    old = e.get("mask") or {}
    if curves.is_animated(old.get("kind")):
        set_param(proj, clip_id, "fxmask:" + effect_id, "kind", kind, t)
        return e
    e["mask"] = _new_mask(old, kind, 1.0)
    return e


def set_effect_mask_invert(proj, clip_id, effect_id, invert, t=None):
    _, c = find(proj, clip_id)
    e = _effect(c, effect_id)
    if not e.get("mask"):
        raise EditError("effect has no mask")
    set_param(proj, clip_id, "fxmask:" + effect_id, "invert", bool(invert), t)


def add_filter_clip(proj, ref, at_us, duration_us=FILTER_DEFAULT_US, track_id=None):
    """A filter as a clip of its own: it filters everything on the tracks below it while it
    lasts. It goes on the given track, else on a track that only holds filters (topmost with
    room), else on a new top picture track."""
    clip = {"id": new_clip_id(proj), "type": "filter", "name": fx.label(ref), "start_us": int(at_us),
            "duration_us": int(duration_us), "source_start_us": 0,
            "transform": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0},
            "effects": [fx.new_effect(ref, new_effect_id())]}
    cands = []
    if track_id:
        t = track_by_id(proj, track_id)
        if t["kind"] != "audio":
            cands = [t]
    if not cands:
        cands = [t for t in reversed(proj["tracks"]) if t["kind"] == "video" and t["clips"] and
                 all(k["type"] == "filter" for k in t["clips"])]
    for t in cands:
        rng = free_range(t, clip["start_us"], end(clip))
        if rng is not None:
            t["clips"].append(clip)
            _sort(t)
            return clip
        gap = next(((lo, hi) for lo, hi in gaps(t) if hi - lo >= MIN_US and hi > clip["start_us"]), None)
        if gap and track_id is None:
            clip["start_us"] = int(max(gap[0], min(clip["start_us"], gap[1] - MIN_US)))
            clip["duration_us"] = int(min(clip["duration_us"], gap[1] - clip["start_us"]))
            t["clips"].append(clip)
            _sort(t)
            return clip
    n = sum(1 for t in proj["tracks"] if t["kind"] == "video" and t["clips"] and
            all(k["type"] == "filter" for k in t["clips"])) + 1
    track = {"id": new_track_id(proj), "kind": "video", "name": f"filter {n}", "clips": [clip]}
    audio_at = next((i for i, t in enumerate(proj["tracks"]) if t["kind"] == "audio"), len(proj["tracks"]))
    proj["tracks"].insert(audio_at, track)
    return clip


# -- replacing a clip's source ----------------------------------------------------------------------
REPLACEABLE = ("image", "video", "compound")          # clips whose picture can be swapped


def _source_check(c, picture):
    if c["type"] == "audio" and picture:
        raise EditError("聲音片段只能換成聲音")
    if c["type"] in REPLACEABLE and not picture:
        raise EditError("畫面片段只能換成圖片、影片或複合片段")
    if c["type"] not in REPLACEABLE + ("audio",):
        raise EditError("文字和濾鏡片段沒有素材可以替換")


def _fit_source(c, length):
    """Keep a clip inside a source `length` us long: its cut point stays when it fits, else
    it starts at the source's start and is shortened to the source."""
    if not length:
        return
    s = c.get("source_start_us", 0)
    if s + c["duration_us"] > length:
        c["source_start_us"] = int(max(0, min(s, length - c["duration_us"])))
        c["duration_us"] = int(min(c["duration_us"], length - c["source_start_us"]))
    if c["duration_us"] < MIN_US:
        raise EditError("素材太短")


def replace_media(proj, clip_id, it, asset=None):
    """Give a clip another source (a media library item {kind, path, name, width, height,
    duration_us}), keeping its place, length, look, mask, effects and keyframes (Jianying's
    替換素材). A picture or video replaces a picture, video or compound clip; a sound
    replaces a sound. A clip longer than its new source is shortened to it. asset: the
    parameters when the new source is a built-in asset (assets.py)."""
    _, c = find(proj, clip_id)
    kind = it["kind"]
    _source_check(c, kind in ("image", "video"))
    for k in ("compound", "compound_id", "timeline_id", "asset"):
        c.pop(k, None)
    if asset is not None:
        c["asset"] = copy.deepcopy(asset)
    c["type"] = kind
    c["media"] = {"path": it["path"]}
    if kind in ("image", "video"):
        c["media"].update(width=it["width"], height=it["height"])
    if kind == "image":
        c["source_start_us"] = 0
        for k in ("volume", "fade_in_us", "fade_out_us"):
            c.pop(k, None)
    else:
        c["media"]["duration_us"] = it.get("duration_us")
        c.setdefault("volume", 1.0)
        _fit_source(c, it.get("duration_us"))
    if not c.get("named"):
        c["name"] = it.get("name") or c["media"]["path"].replace("\\", "/").rsplit("/", 1)[-1]
    return c


def replace_with_compound(root, container, clip_id, ref):
    """Make a picture, video or compound clip show compound (or timeline) ref instead,
    keeping its place, length and look. A static compound fits any length."""
    _, c = find(container, clip_id)
    _source_check(c, True)
    try:
        comp = project.content(root, ref)
    except (StopIteration, KeyError):
        raise EditError("unknown compound or timeline") from None
    if project.contains(root, ref, _container_id(root, container)):
        raise EditError("a timeline or compound cannot show itself")
    for k in ("media", "volume", "fade_in_us", "fade_out_us", "compound_id", "timeline_id", "asset"):
        c.pop(k, None)
    c["type"] = "compound"
    c["timeline_id" if ref.startswith("tl") else "compound_id"] = ref
    c["compound"] = comp
    c["source_start_us"] = 0
    if not comp.get("static"):
        _fit_source(c, project.end_us(comp["tracks"]) if ref.startswith("tl") else
                    comp.get("duration_us") or project.end_us(comp["tracks"]))
    if not c.get("named"):
        c["name"] = comp.get("name") or "複合片段"
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


def set_track_clip_colors(proj, track_id, color):
    """Give every clip of a track the colour '#rrggbb' (None: each its default colour)."""
    for c in track_by_id(proj, track_id)["clips"]:
        if color:
            c["color"] = color
        else:
            c.pop("color", None)


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
    if not _valid_key(c, group, key):
        raise EditError(f"unknown {group} field {key}")
    if not keys:
        raise EditError("a curve needs at least one keyframe")
    h = _holder(c, group)
    clean = []
    for k in sorted(keys, key=lambda k: k[0]):
        t = int(min(max(k[0], 0), c["duration_us"]))
        if clean and t - clean[-1][0] <= KEY_TOL_US:
            raise EditError("two keyframes at the same time")
        clean.append([t, _coerce(k[1])] + [float(x) for x in k[2:6]])
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
    if not _valid_key(c, group, key):
        raise EditError(f"unknown {group} field {key}")
    _holder(c, group)[key] = _coerce(value)
    return c


# -- tracks -----------------------------------------------------------------------------------------
TRACK_FLAGS = ("muted", "solo", "hidden", "locked")      # locked: its clips cannot be picked


def set_track_flag(proj, track_id, flag, on):
    if flag not in TRACK_FLAGS:
        raise EditError(f"unknown track flag {flag}")
    t = track_by_id(proj, track_id)
    if on:
        t[flag] = True
    else:
        t.pop(flag, None)


# -- layers (the static compound editor: a picture made of layers, as in Photoshop) -----------------
def layers(level):
    """The picture clips of a level as layers, the top one first: tracks from the top, a
    track's clips by start."""
    out = []
    for t in reversed(level["tracks"]):
        if t["kind"] != "audio":
            out += sorted(t["clips"], key=lambda c: c["start_us"])
    return out


def set_layer_order(level, ids_top_first, parent=None):
    """Put a level's picture clips in this order, top first, one per track (as layers are):
    each keeps its own track's switches (hidden, locked, colour); sound tracks stay below.
    parent: a group's id - its clips are restacked instead (inside it)."""
    holder = find(level, parent)[1] if parent else level
    if parent and not project.is_group(holder):
        raise EditError("只有群組裡面有圖層")
    ids = list(dict.fromkeys(ids_top_first))
    clips = {c["id"]: (t, c) for t in holder["tracks"] if t["kind"] != "audio" for c in t["clips"]}
    if set(ids) != set(clips):
        raise EditError("圖層的順序要包含每一個圖層")
    tracks, used = [], set()
    for cid in reversed(ids):                                   # bottom first
        t, c = clips[cid]
        kind = "text" if c["type"] == "text" else "video"
        keep = {k: v for k, v in t.items() if k in ("hidden", "locked", "color", "name")} if id(t) not in used else {}
        used.add(id(t))
        if not any(x["id"] == t["id"] for x in tracks):
            tid = t["id"]
        elif parent:                                            # (a group's tracks: ids of their own kind)
            tid = "g" + uuid.uuid4().hex[:8]
        else:
            tid = new_track_id({"tracks": tracks + level["tracks"]})
        tracks.append(dict(keep, id=tid, kind=kind, name=keep.get("name") or c.get("name") or kind, clips=[c]))
    audio = [t for t in holder["tracks"] if t["kind"] == "audio"]
    holder["tracks"][:] = tracks + audio
    return tracks


def layer_parent(level, clip_id):
    """The id of the group a layer is directly inside, or None (the level itself)."""
    def walk(tracks, gid):
        for t in tracks:
            for c in t["clips"]:
                if c["id"] == clip_id:
                    return gid
                if project.is_group(c):
                    found = walk(c["tracks"], c["id"])
                    if found is not False:
                        return found
        return False
    found = walk(level["tracks"], None)
    if found is False:
        raise EditError(f"clip {clip_id} not found")
    return found


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


def delete_tracks(proj, track_ids):
    """Delete several tracks of the level (and their clips) at once."""
    gone = [track_by_id(proj, tid) for tid in dict.fromkeys(track_ids)]
    proj["tracks"][:] = [t for t in proj["tracks"] if not any(t is g for g in gone)]
    return len(gone)


def remove_empty_tracks(proj):
    """清除空軌道: delete every track of the level with no clips; returns how many."""
    kept = [t for t in proj["tracks"] if t["clips"]]
    n = len(proj["tracks"]) - len(kept)
    if not n:
        raise EditError("沒有空軌道")
    proj["tracks"][:] = kept
    return n


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


# -- shared compounds -------------------------------------------------------------------------------
def _container_id(root, container):
    """The id of the timeline or compound whose tracks `container` holds."""
    if container is root:
        return root["active_timeline"]
    for k, v in root["compounds"].items():
        if v is container:
            return k
    for t in root["timelines"]:
        if t is container:
            return t["id"]
    return None


def add_library_compound(root, pack):
    """A compound from the Library (userlib.load_compound) into the project, with the
    compounds it shows: new ids for them and their clips. The same file, unchanged since,
    is added once: its compound is used again. Returns the compound's id here."""
    comps = root.setdefault("compounds", {})
    for k, comp in comps.items():
        if comp.get("library_source") == pack["source"]:
            return k
    ids = {}
    for old in pack["compounds"]:
        ids[old] = project.new_compound_id(root)
        comps[ids[old]] = {"tracks": []}                 # (taken, for the next new id)
    for old, comp in pack["compounds"].items():
        comp = copy.deepcopy(comp)
        for t in project.all_tracks(comp["tracks"]):
            for c in t["clips"]:
                c["id"] = new_clip_id()
                if c.get("compound_id") in ids:
                    c["compound_id"] = ids[c["compound_id"]]
        comps[ids[old]] = comp
    comps[ids[pack["root"]]]["library_source"] = pack["source"]
    if pack.get("name"):                                 # named as it was saved
        comps[ids[pack["root"]]]["name"] = pack["name"]
    project.link(root)
    return ids[pack["root"]]


def place_compound(root, container, ref, track_id, start_us):
    """A new clip showing shared compound (or another timeline, nested as in Resolve) ref in
    container (the open timeline or an open compound) at start_us: on track_id when it has
    room, else a new picture track. A timeline or compound can never show itself."""
    try:
        comp = project.content(root, ref)
    except StopIteration:
        raise EditError("unknown compound or timeline") from None
    if project.contains(root, ref, _container_id(root, container)):
        raise EditError("a timeline or compound cannot show itself")
    # a timeline is as long as its content; a compound keeps its own length; a static one is
    # placed like a picture
    if comp.get("static"):
        dur = STILL_DEFAULT_US
    else:
        dur = int((project.end_us(comp["tracks"]) if ref.startswith("tl")
                   else comp.get("duration_us") or project.end_us(comp["tracks"])) or MIN_US)
    clip = {"id": new_clip_id(), "type": "compound", "name": comp.get("name") or "複合片段",
            "start_us": max(0, int(start_us)), "duration_us": dur, "source_start_us": 0,
            ("timeline_id" if ref.startswith("tl") else "compound_id"): ref, "compound": comp,
            "transform": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}}
    track = None
    if track_id:
        t = track_by_id(container, track_id)
        if t["kind"] != "audio" and not project.locked(t):
            best = None
            for lo, hi in gaps(t):
                if hi - lo >= dur:
                    s = min(max(clip["start_us"], lo), hi - dur)
                    if best is None or abs(s - clip["start_us"]) < abs(best - clip["start_us"]):
                        best = s
            if best is not None:
                track, clip["start_us"] = t, int(best)
    if track is None:
        n = sum(1 for t in container["tracks"] if t["kind"] == "video") + 1
        track = {"id": new_track_id(container), "kind": "video", "name": f"video {n}", "clips": []}
        container["tracks"].insert(_visual_slot(container), track)
    track["clips"].append(clip)
    _sort(track)
    return clip


STILL_DEFAULT_US = 5_000_000          # a new static clip lasts as long as a new picture


def freeze_at(tracks, t_us):
    """Re-time content so that what shows at t_us shows at 0 (a static compound shows only its
    first frame): clips are moved t_us earlier, one running across t_us loses what came before
    (as a trim, keyframes kept in place) and one that ended by then is dropped (it could never
    show). Returns the tracks."""
    t_us = int(t_us)
    if t_us <= 0:
        return tracks
    for t in tracks:
        kept = []
        for c in t["clips"]:
            if end(c) <= t_us:
                continue
            if c["start_us"] < t_us:
                d = t_us - c["start_us"]
                c["start_us"], c["duration_us"] = t_us, c["duration_us"] - d
                c["source_start_us"] = c.get("source_start_us", 0) + d
                shift_keys(c, d)
                if c.get("fade_in_us"):
                    c["fade_in_us"] = 0
            c["start_us"] -= t_us
            kept.append(c)
        t["clips"] = kept
    return tracks


def make_compound(root, container, clip_ids, at_us=None, static=False):
    """Move clips of the open level into a new shared compound and leave one clip showing it
    in their place: over their whole span, on the topmost picture track they used (or a new
    one above it when that has no room). The tracks they were on come along, in order.
    static makes a static compound (靜態片段), which shows only its first frame, like a
    picture: the content is re-timed (freeze_at) so the moment at at_us (the playhead, kept
    inside the span) is that frame."""
    picked = [find(container, cid) for cid in dict.fromkeys(clip_ids)]
    if not picked:
        raise EditError("先在時間軸上選取片段")
    if static and any(c["type"] == "audio" for _, c in picked):
        raise EditError("靜態片段只放畫面：選取裡有聲音片段")
    ids = {c["id"] for _, c in picked}
    s0 = min(c["start_us"] for _, c in picked)
    span = max(end(c) for _, c in picked) - s0
    used = [t for t in container["tracks"] if any(t is tt for tt, _ in picked)]       # bottom first
    inner = []
    for t in used:
        moved = [c for c in t["clips"] if c["id"] in ids]
        t["clips"] = [c for c in t["clips"] if c["id"] not in ids]
        for c in moved:
            c["start_us"] -= s0
        inner.append(dict({k: v for k, v in t.items() if k != "clips"}, clips=moved))
    size = root if container is root or "width" not in container else container
    comps = root.setdefault("compounds", {})
    n = sum(1 for k in comps.values() if bool(k.get("static")) == static) + 1
    comp = {"name": f"{'靜態片段' if static else '複合片段'} {n}", "width": size.get("width", 1920),
            "height": size.get("height", 1080), "duration_us": int(span), "tracks": inner}
    if static:
        t = span // 2 if at_us is None else at_us - s0
        freeze_at(inner, min(max(t, 0), max(0, span - 1)))
        comp["static"] = True
    kid = project.new_compound_id(root)
    comps[kid] = comp
    clip = {"id": new_clip_id(), "type": "compound", "name": comp["name"], "start_us": int(s0),
            "duration_us": int(span), "source_start_us": 0, "compound_id": kid, "compound": comp,
            "transform": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}}
    top = next((t for t in reversed(used) if t["kind"] != "audio"), None)
    if top is None or free_range(top, s0, s0 + span) is None:
        at = container["tracks"].index(top) + 1 if top is not None else _visual_slot(container)
        n = sum(1 for t in container["tracks"] if t["kind"] == "video") + 1
        top = {"id": new_track_id(container), "kind": "video", "name": f"video {n}", "clips": []}
        container["tracks"].insert(at, top)
    top["clips"].append(clip)
    _sort(top)
    project.link(root)
    return clip


def new_static(root, container, at_us, track_id=None):
    """An empty static clip at at_us (enter it to build its picture)."""
    return new_compound(root, container, at_us, track_id, static=True)


def add_compound(root, static=False, size=None):
    """A new empty compound entry (static: a static one), size (width, height) or the
    project's; no clip shows it yet (it can be opened by itself). Returns its id."""
    comps = root.setdefault("compounds", {})
    n = sum(1 for k in comps.values() if bool(k.get("static")) == static) + 1
    w, h = size or (root.get("width", 1920), root.get("height", 1080))
    kid = project.new_compound_id(root)
    comps[kid] = {"name": f"{'靜態片段' if static else '複合片段'} {n}", "width": w, "height": h,
                  "duration_us": STILL_DEFAULT_US, "tracks": [{"id": "t0", "kind": "video", "name": "V1", "clips": []}]}
    if static:
        comps[kid]["static"] = True
    return kid


def new_compound(root, container, at_us, track_id=None, static=False):
    """A new empty compound (static: a static one) and a clip showing it at at_us: on
    track_id, or else on the topmost picture track with room there, or a new track. Enter
    the clip to fill it."""
    size = root if container is root or "width" not in container else container
    kid = add_compound(root, static, (size.get("width", 1920), size.get("height", 1080)))
    if track_id is None:
        track_id = next((t["id"] for t in reversed(container["tracks"]) if t["kind"] == "video"
                         and not project.locked(t) and free_range(t, at_us, at_us + STILL_DEFAULT_US) is not None), None)
    return place_compound(root, container, kid, track_id, at_us)


def make_unique(root, container, clip_id):
    """Give one compound clip its own copy of its compound (edits no longer reach the others)."""
    _, c = find(container, clip_id)
    if not project.ref_of(c):
        raise EditError("not a compound clip")
    src = c["compound"]                                  # a compound, or a nested timeline
    copy_ = {k: v for k, v in src.items() if k not in ("id", "tracks")}
    copy_["tracks"] = json.loads(json.dumps(project._tracks_out(src["tracks"])))
    kid = project.new_compound_id(root)
    copy_["name"] = (src.get("name") or "複合片段") + " 副本"
    root["compounds"][kid] = copy_
    c.pop("timeline_id", None)
    c["compound_id"] = kid
    project.link(root)
    return c


def rename_compound(root, compound_id, name):
    """Rename a compound; _thumbnail (the project's thumbnail) only fits a static one."""
    comp = root["compounds"][compound_id]
    name = str(name).strip() or "複合片段"
    if name == project.THUMBNAIL and not comp.get("static"):
        raise EditError(f"{project.THUMBNAIL} 一定要是靜態複合片段")
    comp["name"] = name


def delete_compound(root, compound_id, force=False):
    """Remove a shared compound; with force also every clip that shows it (anywhere)."""
    uses = project.compound_uses(root).get(compound_id) or []
    if uses and not force:
        raise EditError("still used on a timeline")
    shown = {id(c) for _, _, c in uses}
    for owner in list(root.get("timelines", [])) + list(root.get("compounds", {}).values()):
        for t in owner["tracks"]:
            t["clips"] = [c for c in t["clips"] if id(c) not in shown]
    root["compounds"].pop(compound_id, None)
    project.link(root)


def delete_use(root, tl_id, path, clip_id):
    """Delete one clip showing a compound: it sits in timeline tl_id, inside the compound
    clips of `path` (their ids, outermost first)."""
    node = project.timeline(root, tl_id)
    for pid in path:
        node = find(node, pid)[1]["compound"]
    delete(node, clip_id)


def set_master_gain(proj, gain):
    """The whole output's volume (the meter's fader); 1 is unchanged."""
    g = min(4.0, max(0.0, float(gain)))
    if abs(g - 1.0) < 1e-4:
        proj.pop("master_gain", None)
    else:
        proj["master_gain"] = round(g, 5)


# -- timelines ------------------------------------------------------------------------------------
def _timeline_id(proj):
    ids = {t["id"] for t in proj["timelines"]}
    n = len(ids) + 1
    while f"tl{n}" in ids:
        n += 1
    return f"tl{n}"


def add_timeline(proj, name=None, copy_of=None):
    """A new timeline (empty with V1 / A1, or a copy of timeline copy_of), opened."""
    tid = _timeline_id(proj)
    if copy_of:
        src = project.timeline(proj, copy_of)
        tracks = json.loads(json.dumps(project._tracks_out(src["tracks"])))
        for t in tracks:
            for c in t["clips"]:
                c["id"] = new_clip_id()                  # (compound content stays shared)
        name = name or f"{src['name']} 副本"
    else:
        tracks = [{"id": "t0", "kind": "video", "name": "video 1", "clips": []},
                  {"id": "t1", "kind": "audio", "name": "audio 1", "clips": []}]
    tl = {"id": tid, "name": name or f"時間線 {len(proj['timelines']) + 1}", "tracks": tracks}
    proj["timelines"].append(tl)
    open_timeline(proj, tid)
    return tl


def open_timeline(proj, tl_id):
    project.link(proj)                                   # settle the open timeline first
    tl = project.timeline(proj, tl_id)                   # (raises for an unknown id)
    proj["active_timeline"] = tl_id
    proj["tracks"] = tl["tracks"]
    project.link(proj)
    project.refresh_duration(proj)


def rename_timeline(proj, tl_id, name):
    project.timeline(proj, tl_id)["name"] = str(name).strip() or "時間線"


def delete_timeline(proj, tl_id):
    if len(proj["timelines"]) < 2:
        raise EditError("a project keeps at least one timeline")
    if project.compound_uses(proj).get(tl_id):
        raise EditError("this timeline is used inside another one")
    tl = project.timeline(proj, tl_id)
    i = proj["timelines"].index(tl)
    proj["timelines"].remove(tl)
    if proj["active_timeline"] == tl_id:
        open_timeline(proj, proj["timelines"][max(0, i - 1)]["id"])
