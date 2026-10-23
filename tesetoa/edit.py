"""Edit operations on a project, with undo/redo.

Every operation works on clip ids, keeps clips on one track from overlapping and keeps
keyframes where they were on screen: keys are relative to the clip start, so trimming the
head or splitting shifts them by the amount cut. Video, audio and compound clips cannot
be trimmed past their source; images and texts can be stretched freely.
"""
import copy
import json
import time

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


def new_clip_id(proj):
    n = 0
    for c in project.walk_clips(proj["tracks"]):
        if c["id"][1:].isdigit():
            n = max(n, int(c["id"][1:]))
    return f"c{n + 1}"


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
        c["text"][k] = v
    if "color" in fields or "size" in fields:
        c["text"].pop("styles", None)          # a whole-clip style replaces per-range ones
    if "content" in fields:
        c["name"] = fields["content"][:20]
    return c


def set_transform(proj, clip_id, key, value):
    """Set a static transform value; refuses keyframed ones (edit their keys instead)."""
    _, c = find(proj, clip_id)
    if key not in TRANSFORM_FIELDS:
        raise EditError(f"unknown transform field {key}")
    tf = c.setdefault("transform", {})
    if curves.is_animated(tf.get(key)):
        raise EditError(f"{key} has keyframes")
    tf[key] = float(value)
    if key == "scale" and "scale_y" in tf and not curves.is_animated(tf["scale_y"]):
        tf["scale_y"] = float(value)
    return c
