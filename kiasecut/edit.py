"""Edit operations on a project, with undo/redo.

Every operation works on clip ids, keeps clips on one track from overlapping and keeps
keyframes where they were on screen: keys are relative to the clip start, so trimming the
head or splitting shifts them by the amount cut. Video, audio and compound clips cannot
be trimmed past their source; images and texts can be stretched freely.
"""
import bisect
import copy
import json
import math
import random
import time
import uuid

from . import assets, components, curves, expr, fonts, fx, lfo, mapping, nodegraph, project, rack, textlayout, textvars, viz

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
        TOUCHED.clear()
        try:
            result = fn(self.proj, *args, **kw)
            project.sync_vfx(self.proj, TOUCHED)
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


def find_all(proj, clip_ids):
    """[find of each clip id], in one pass over the level."""
    want, got = set(clip_ids), {}
    for t in project.all_tracks(proj["tracks"]):
        for c in t["clips"]:
            if c["id"] in want:
                got.setdefault(c["id"], (t, c))
    for cid in clip_ids:
        if cid not in got:
            raise EditError(f"clip {cid} not found")
    return [got[cid] for cid in clip_ids]


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


def _level_starts(tracks, off=0):
    """(clip, its start in the level's time) for every clip of the tracks, groups' included."""
    for t in tracks:
        for c in t["clips"]:
            yield c, off + c["start_us"]
            if project.is_group(c):
                yield from _level_starts(c["tracks"], off + c["start_us"])


def abs_start(proj, clip_id):
    """A clip's start in the level's time (a group's clips count from the group's start)."""
    for c, s in _level_starts(proj["tracks"]):
        if c["id"] == clip_id:
            return s
    raise EditError(f"clip {clip_id} not found")


def abs_starts(proj):
    """{clip id: abs_start} for every clip of the level, in one pass (for a selection of many:
    abs_start of each would walk the level once per clip)."""
    return {c["id"]: s for c, s in _level_starts(proj["tracks"])}


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
    for group in (c.get("transform"), c.get("mask"), c.get("text"), c.get("asset"), c.get("params"),
                  *(c.get("places") or {}).values()):
        if group:
            out += [v for v in group.values() if curves.is_animated(v)]
    for key in ("volume", "blend"):
        if curves.is_animated(c.get(key)):
            out.append(c[key])
    for e in c.get("effects") or []:
        out += [v for v in list(e["params"].values()) + list((e.get("mask") or {}).values()) + [e.get("mix")]
                + [x for src in (e.get("sources") or {}).values() for x in src.values()]
                if curves.is_animated(v)]
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
    g = group_of(proj, t)
    if g is not None and new_start_us < 0 and free_range(t, c["start_us"], end(c), ignore=c)[0] == 0:
        # past its group's start: the group grows to the left (as far as its own track lets it),
        # its clips counting from its new start
        if c["type"] in ("video", "audio", "compound") and not project.is_static(c):
            new_start_us = max(new_start_us, c["start_us"] - c.get("source_start_us", 0) / project.speed(c))
        if new_start_us < 0:
            s0 = g["start_us"]
            trim_start(proj, g["id"], s0 + new_start_us)
            new_start_us += s0 - g["start_us"]
    e = end(c)
    rng = free_range(t, c["start_us"], e, ignore=c)
    lo = rng[0]
    if c["type"] in ("video", "audio", "compound") and not project.is_static(c):
        lo = max(lo, c["start_us"] - c.get("source_start_us", 0) / project.speed(c))    # not before the source
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
        if min(new_end_us, hi) > g["duration_us"]:               # past its group's end: the group grows
            trim_end(proj, g["id"], g["start_us"] + min(new_end_us, hi))
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
    if right.get("fade_in_us"):               # fades belong to the outer ends
        right["fade_in_us"] = 0
    if c.get("fade_out_us"):
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


def ripple_delete(proj, clip_ids):
    """波紋刪除: delete the clips and close the gaps they leave - each later clip of their
    tracks moves left by the time the deleted clips before it covered."""
    cut = {}                                             # id(track) -> (track, [(start, end)])
    for cid in clip_ids:
        t, c = find(proj, cid)
        cut.setdefault(id(t), (t, []))[1].append((c["start_us"], end(c)))
        t["clips"].remove(c)
    for t, spans in cut.values():
        for c in t["clips"]:
            c["start_us"] -= sum(e - s for s, e in spans if e <= c["start_us"])


def trim_to(proj, clip_ids, at_us, side):
    """向左裁剪 / 向右裁剪: what is before (side "start") or after ("end") at_us (the level's
    time) is cut off each clip at_us is inside; the others stay. Returns the clips trimmed."""
    done = []
    for cid in clip_ids:
        t, c = find(proj, cid)
        at = at_us - (abs_start(proj, cid) - c["start_us"])         # (a group's clip: in its group's time)
        if c["start_us"] + MIN_US <= at <= end(c) - MIN_US:
            (trim_start if side == "start" else trim_end)(proj, cid, at)
            done.append(c)
    if not done:
        raise EditError("播放頭下沒有片段")
    return done


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
    moving = find_all(proj, clip_ids)
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
    for t in {id(t): t for _, src, dst in plan for t in (src, dst)}.values():
        _sort(t)
    return [c for _, c in moving]


def shuffle_clips(proj, clip_ids, rng=random):
    """Alt+R: the clips in a random order, on each track - one run of clips next to each other
    (no other clip between them) at a time: they take the run's places one after another, the
    gaps between them kept, so the run spans what it did. Never the same order again (when
    there are two or more). Returns the clips."""
    ids = set(clip_ids)
    for t in project.all_tracks(proj["tracks"]):
        runs, run = [], []
        for c in sorted(t["clips"], key=lambda c: c["start_us"]):
            if c["id"] in ids:
                run.append(c)
            elif run:
                runs.append(run)
                run = []
        runs.append(run)
        for run in runs:
            if len(run) < 2:
                continue
            gaps_ = [b["start_us"] - end(a) for a, b in zip(run, run[1:])] + [0]
            order = list(run)
            while order == run:
                rng.shuffle(order)
            at = run[0]["start_us"]
            for c, gap in zip(order, gaps_):
                c["start_us"] = at
                at += c["duration_us"] + gap
        _sort(t)
    return [find(proj, cid)[1] for cid in clip_ids]


def stack_sets(proj, clip_ids):
    """The tracks clips are on, by the set they move among (a level's or a group's pictures,
    or its sound tracks), each set's tracks bottom first: [(tracks, clips by track)]."""
    picked = [find(proj, cid) for cid in dict.fromkeys(clip_ids)]
    ids = {c["id"] for _, c in picked}
    out = {}
    for t, _c in picked:
        holder = group_of(proj, t)
        key = (id(holder), t["kind"] == "audio")
        if key not in out:
            tracks = holder["tracks"] if holder is not None else proj["tracks"]
            out[key] = [x for x in tracks if (x["kind"] == "audio") == key[1]
                        and any(c["id"] in ids for c in x["clips"])]
    return [(used, [[c for c in t["clips"] if c["id"] in ids] for t in used]) for used in out.values()]


def can_reverse_rows(proj, clip_ids):
    """Whether 反轉排序 has something to turn round: clips on two or more tracks of one set."""
    return any(len(used) > 1 for used, _ in stack_sets(proj, clip_ids))


def reverse_rows(proj, clip_ids):
    """反轉排序: clips selected one above another the other way up - the clips of the top track
    of those they are on go to the bottom one, the second to the second from the bottom and
    so on (pictures and sound each among their own; in a group, among its tracks), each at
    its own time. Refuses (changing nothing) when one would land on a clip that stays. Returns
    the clips."""
    plan = []                                            # (clip, from track, to track)
    for used, moving in stack_sets(proj, clip_ids):
        for i, (t, clips) in enumerate(zip(used, moving)):
            plan += [(c, t, used[-1 - i]) for c in clips]
    if not any(src is not dst for _, src, dst in plan):
        raise EditError("選取的片段要在兩條以上的軌道上")
    going = {c["id"] for c, src, dst in plan if src is not dst}
    for c, src, dst in plan:
        if src is not dst and any(o["id"] not in going and o["start_us"] < end(c) and end(o) > c["start_us"]
                                  for o in dst["clips"]):
            raise EditError(f"「{dst.get('name') or '軌道'}」上沒有位置")
    for c, src, dst in plan:
        if src is not dst:
            src["clips"].remove(c)
    for c, src, dst in plan:
        if src is not dst:
            dst["clips"].append(c)
    for _, src, dst in plan:
        _sort(src)
        _sort(dst)
    return [c for c, _, _ in plan]


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
    held = {}                                            # a group's clips are copied inside it, among its tracks
    for item in payload["items"]:
        g = group_of(level, track_by_id(level, item["track"]))
        held.setdefault(id(g), (level if g is None else g, []))[1].append(item)
    made = {}
    for holder, items in held.values():
        pictures, sound = display_groups(holder)
        for item in items:
            c = item["clip"]
            src = track_by_id(holder, item["track"])
            group = sound if src["kind"] == "audio" else pictures
            i = next(j for j, x in enumerate(group) if x is src)
            s, e = c["start_us"] + d_us, end(c) + d_us
            if d_us == 0 and not d_rows:                 # in place: on top of the original
                above = group[i - 1] if i > 0 and src["kind"] != "audio" else None
                if above is None or above["kind"] != src["kind"] or free_range(above, s, e) is None:
                    above = add_track(holder, src["kind"], near_id=src["id"])
                    pictures, sound = display_groups(holder)
                item["track"] = above["id"]
            elif 0 <= i + int(d_rows) < len(group):
                dst = group[i + int(d_rows)]
                if dst["kind"] == src["kind"]:
                    item["track"] = dst["id"]
        anchor = items[0]["clip"]["start_us"]            # (the items are in the order of their starts)
        at = max(0, anchor + int(d_us))
        if holder is not level:                          # the group grows to hold them, as far as it can
            last = max(end(item["clip"]) for item in items) + at - anchor
            if last > holder["duration_us"]:
                trim_end(level, holder["id"], holder["start_us"] + last)
            if last > holder["duration_us"]:
                raise EditError("群組後面沒有空間放這些片段")
        copies = paste_clips(root, holder, {"anchor_us": anchor, "items": items}, at)
        made.update((id(item), c) for item, c in zip(items, copies))
    new = [made[id(item)] for item in payload["items"]]
    for item, c in zip(payload["items"], new):
        old = item["clip"]["id"]
        for key, v in ((moves or {}).get(old) or {}).items():
            set_param(level, c["id"], "transform", key, v, t_of(old) if t_of else None)
    return new


def add_text(proj, at_us, content="輸入文字", duration_us=3_000_000, track_id=None, style=None):
    """New text clip at at_us on track_id when that is a text track with room, else on the topmost text track with room,
    else a new track. style: fields of its text that replace the defaults (textpresets.py)."""
    clip = {
        "id": new_clip_id(proj), "type": "text", "name": content[:20],
        "start_us": int(at_us), "duration_us": int(duration_us), "source_start_us": 0,
        "text": {"content": content, "font_path": project.DEFAULT_FONT, "size": 7.95,
                 "color": [1.0, 1.0, 1.0], "fill": True, "stroke_on": False,
                 "stroke_color": [0.0, 0.0, 0.0], "stroke": 2.0, "stroke_align": "inside",
                 "letter_spacing": 0.0, "line_spacing": 0.02, "italic_deg": 0, **copy.deepcopy(style or {})},
        "transform": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0},
    }
    asked = [t for t in proj["tracks"] if t["id"] == track_id and t["kind"] == "text"]
    for t in asked + list(reversed(proj["tracks"])):
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


TEXT_FIELDS = ("content", "font_path", "size", "color", "fill", "stroke_on", "stroke_color", "stroke",
               "stroke_align", "letter_spacing", "line_spacing", "italic_deg", "align", "valign", "box_w", "box_h") \
    + tuple(textlayout.DECOR)
TEXT_ALIGNS = ("left", "center", "right", "justify")      # 對齊 (justify: 齊頭尾)
TEXT_VALIGNS = ("top", "middle", "bottom")               # 垂直對齊 in a 文字框
TEXT_STROKE_ALIGNS = ("inside", "center", "outside")
TEXT_BOX_MODES = ("auto", "auto_h", "fixed")             # 自動寬度 / 自動高度 / 固定大小 (Lunacy's)
TRANSFORM_FIELDS = ("x", "y", "scale", "scale_y", "rotation", "opacity", "pivot_x", "pivot_y",
                    "anchor_x", "anchor_y") + project.CORNERS   # (pivot: 中心點, anchor: 錨點; 圓角)


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
    """字體對應's 換成: every text and node font of the project (all timelines and compounds, keyframes and
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
    for d, k in fonts.node_fonts(proj):                     # the fonts of text nodes and font nodes
        new = swap(d[k])
        n += new != d[k]
        d[k] = new
    if not n:
        raise EditError("沒有文字用到這些字體")
    return n


STYLE_TEXT_FIELDS = ("font_path", "size", "color", "fill", "stroke_on", "stroke_color", "stroke",
                     "stroke_align", "letter_spacing", "line_spacing", "italic_deg", "align", "valign") \
    + tuple(textlayout.DECOR)


def add_visualizer(level, kind, source, media_path, start_us, duration_us, width, height, track_id=None):
    """A new Audio Visualizer (viz.py) clip of this kind drawing `source`, the size of a
    width x height canvas, on the topmost picture track with room (or track_id), else a new
    track. media_path is the (empty) picture file it stands on. Returns the clip."""
    if kind not in viz.KINDS:
        raise EditError(f"unknown visualizer {kind}")
    clip = {"id": new_clip_id(level), "type": "image", "name": viz.KINDS[kind], "start_us": int(start_us),
            "duration_us": int(duration_us), "source_start_us": 0,
            "media": {"path": media_path, "width": int(width), "height": int(height)},
            "transform": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0},
            "viz": viz.make(kind, source, width, height)}
    clip["media"]["width"], clip["media"]["height"] = (int(round(clip["viz"]["w"])), int(round(clip["viz"]["h"])))
    track = track_by_id(level, track_id) if track_id else None
    if track is not None and (track["kind"] == "audio" or free_range(track, clip["start_us"], end(clip)) is None):
        track = None
    if track is None:
        for t in reversed(level["tracks"]):
            if t["kind"] == "video" and not project.locked(t) and free_range(t, clip["start_us"], end(clip)) is not None:
                track = t
                break
    if track is not None:
        rng = free_range(track, clip["start_us"], end(clip))
        clip["duration_us"] = min(clip["duration_us"], rng[1] - clip["start_us"])
        track["clips"].append(clip)
        _sort(track)
        return clip
    n = sum(1 for t in level["tracks"] if t["kind"] == "video") + 1
    track = {"id": new_track_id(level), "kind": "video", "name": f"video {n}", "clips": [clip]}
    audio_at = next((i for i, t in enumerate(level["tracks"]) if t["kind"] == "audio"), len(level["tracks"]))
    level["tracks"].insert(audio_at, track)
    return clip


def set_viz(proj, clip_id, **fields):
    """Change an Audio Visualizer's settings (viz.py DEFAULTS' names, kind, source); the rest is cleaned."""
    _, c = find(proj, clip_id)
    if not c.get("viz"):
        raise EditError("不是 Audio Visualizer")
    new = dict(c["viz"])
    for k, v in fields.items():
        if k not in viz.DEFAULTS and k != "source":
            raise EditError(f"unknown visualizer setting {k}")
        new[k] = v
    if new.get("kind") not in viz.KINDS:
        raise EditError(f"unknown visualizer {new.get('kind')}")
    src = new.get("source") or {}
    if src.get("type") not in viz.SOURCE_TYPES:
        raise EditError("來源要是檔案、複合片段或軌道")
    c["viz"] = viz.clean(new)
    c["media"]["width"], c["media"]["height"] = int(round(c["viz"]["w"])), int(round(c["viz"]["h"]))   # (what the picture is)
    c["name"] = c["name"] if c.get("named") else viz.KINDS[c["viz"]["kind"]]
    return c


def add_text_var(proj, clip_id, kind="number"):
    """新增變數: a new variable of a text (named value, value2, …); returns it."""
    _, c = find(proj, clip_id)
    if not c.get("text"):
        raise EditError("只有文字片段有變數")
    if kind not in textvars.KINDS:
        raise EditError(f"unknown kind {kind}")
    names = {v["name"] for v in textvars.variables(c["text"])}
    name, k = "value", 2
    while name in names:
        name, k = f"value{k}", k + 1
    v = {"name": name, "kind": kind, "value": textvars.default_value(kind)}
    if kind == "float":
        v["decimals"] = 2
    if kind == "time":
        v["format"] = "mm:ss"
    c["text"].setdefault("vars", []).append(v)
    return v


def remove_text_var(proj, clip_id, name):
    _, c = find(proj, clip_id)
    vs = [v for v in textvars.variables(c.get("text") or {}) if v["name"] != name]
    if vs:
        c["text"]["vars"] = vs
    else:
        (c.get("text") or {}).pop("vars", None)
    return c


def set_text_var(proj, clip_id, name, new_name=None, kind=None, decimals=None, fmt=None):
    """A text variable's name (its {name}s in the words follow), its kind (its value goes back to
    that kind's start, keyframes and all), a float's decimal places or a time's format."""
    _, c = find(proj, clip_id)
    v = textvars.find(c.get("text") or {}, name)
    if v is None:
        raise EditError("沒有這個文字變數")
    if kind is not None and kind != v["kind"]:
        if kind not in textvars.KINDS:
            raise EditError(f"unknown kind {kind}")
        v["kind"], v["value"] = kind, textvars.default_value(kind)
        v.pop("decimals", None)
        v.pop("format", None)
        if kind == "float":
            v["decimals"] = 2
        if kind == "time":
            v["format"] = "mm:ss"
    if decimals is not None:
        v["decimals"] = max(0, min(10, int(decimals)))
    if fmt is not None:
        v["format"] = str(fmt) or "mm:ss"
    if new_name is not None and new_name != name:
        new_name = new_name.strip()
        if not textvars.NAME.match(new_name):
            raise EditError("變數名稱只能用文字、數字和底線，不能以數字開頭")
        if textvars.find(c["text"], new_name) is not None:
            raise EditError(f"已經有叫「{new_name}」的變數")
        c["text"]["content"] = textvars.REF.sub(
            lambda m: m.group(0) if m.group(1) != name else "{" + new_name + (":" + m.group(2) if m.group(2) is not None
                                                                                 else "") + "}",
            c["text"].get("content", ""))
        v["name"] = new_name
    return v


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


def text_box_mode(tx):
    """A text's 文字框 (TEXT_BOX_MODES): as big as its words, a fixed width it wraps in (the
    height follows), or a fixed width and height."""
    if curves.max_abs(tx.get("box_h") or 0.0) > 0:
        return "fixed"
    return "auto_h" if curves.max_abs(tx.get("box_w") or 0.0) > 0 else "auto"


def set_text_box(proj, clip_id, mode, t=None):
    """Switch a text's 文字框 (TEXT_BOX_MODES): a side that becomes fixed starts as big as the
    text is at clip time t (so nothing moves), a side that becomes automatic loses its size
    and its keyframes."""
    _, c = find(proj, clip_id)
    if c["type"] != "text":
        raise EditError("not a text clip")
    if mode not in TEXT_BOX_MODES:
        raise EditError(f"unknown text box {mode}")
    tx = c["text"]
    w, h = textlayout.frame_size(textvars.spec_at(tx, t or 0, TEXT_ANIM_FIELDS))
    for key, size, on in (("box_w", w, mode != "auto"), ("box_h", h, mode == "fixed")):
        if not on:
            tx.pop(key, None)
        elif not curves.max_abs(tx.get(key) or 0.0) > 0:
            tx[key] = math.ceil(size * 10) / 10
    return c


def set_transform(proj, clip_id, key, value, t=None):
    """Set a transform value; keyframed ones are edited at clip time t (see set_param)."""
    if key not in TRANSFORM_FIELDS:
        raise EditError(f"unknown transform field {key}")
    return set_param(proj, clip_id, "transform", key, value, t)


# -- keyframes ------------------------------------------------------------------------------------
TEXT_ANIM_FIELDS = ("size", "color", "fill", "stroke_on", "stroke_color", "stroke", "stroke_align",
                    "letter_spacing", "line_spacing", "italic_deg", "font_path", "align", "valign", "box_w", "box_h") \
    + tuple(textlayout.DECOR)
GROUP_FIELDS = {
    "transform": TRANSFORM_FIELDS,
    "text": TEXT_ANIM_FIELDS,
    "mask": ("cx", "cy", "w", "h", "rotation", "feather", "kind", "invert"),
    "clip": ("volume", "blend"),
}
# how a picture mixes with what is under it (render.BLEND_OPS draws them); a group's can also be
# pass_through (穿透, as in Photoshop: its clips mix with what is under the group themselves)
BLEND_MODES = ("normal", "multiply", "screen", "overlay", "darken", "lighten", "color_dodge", "color_burn",
               "hard_light", "soft_light", "difference", "exclusion", "add", "pass_through")
DISCRETE_DEFAULTS = {"font_path": project.DEFAULT_FONT, "kind": "rectangle", "invert": False, "blend": "normal",
                     "align": "center", "valign": "top", "fill": True, "stroke_on": False,
                     "stroke_align": "inside", "shadow_on": False, "bg_on": False}
KEY_TOL_US = 1_000_000 // 120      # half a 60 fps frame


def time_in(t_us, start_us, fps):
    """Timeline time t_us in a clip starting at start_us. A clip starts on the frame nearest its
    start (build.fr), whose time may be up to half a frame before it: there it is 0, so a
    playhead on a clip's first frame is on the clip."""
    t = t_us - start_us
    return 0 if -US / fps / 2 < t < 0 else t
EASINGS = {                        # CSS-style cubic-bezier control x positions
    "linear": (0.0, 1.0),
    "ease_in": (0.42, 1.0),
    "ease_out": (0.0, 0.58),
    "ease_in_out": (0.42, 0.58),
}


TOUCHED = []                      # the effects an edit went through (History.do hands those that use a VFX Node to the node)


def _effect(c, effect_id):
    for e in c.get("effects") or []:
        if e["id"] == effect_id:
            if e.get("vfx"):
                TOUCHED.append(e)
            return e
    raise EditError("effect not found")


def _valid_key(c, group, key):
    """Whether `key` is a parameter of `group` (groups "fx:<effect id>",
    "fxmask:<effect id>" and "fxmix:<effect id>" are an effect's own parameters, its mask and
    its 混合程度)."""
    if group.startswith("fx:"):
        return key in _effect(c, group[3:])["params"]
    if group.startswith("fxmix:"):
        return key == "mix" and bool(_effect(c, group[6:]))
    if group.startswith("fxmask:"):
        return key in GROUP_FIELDS["mask"]
    if group.startswith("fxsrc:"):
        return key in SOURCE_FIELDS + ("min", "max") and bool(_source(c, group))
    if group == "asset":
        return bool(c.get("asset")) and key in assets.fields_of(c["asset"].get("family"))
    if group == "params":                        # a component instance's own values (元件參數)
        return components.param(components.of_clip(c), key) is not None
    if group.startswith("tvar:"):                # a text variable's value (文字變數)
        return key == "value" and c.get("text") is not None and textvars.find(c["text"], group[5:]) is not None
    if group.startswith("place:"):               # where an image parameter's picture sits in its layer
        p = components.param(components.of_clip(c), group[6:])
        return p is not None and p["kind"] == "image" and key in components.PLACE
    return key in GROUP_FIELDS.get(group, ())


def has_param(c, group, key):
    """Whether clip c has the parameter group / key to keyframe: a transform, text or mask
    of its own, a sound for the volume, a picture for the blend mode, that filter."""
    if group in ("transform", "text", "mask") and not c.get(group):
        return False
    if group == "clip" and (key == "volume" and key not in c or key == "blend" and c["type"] not in VISUAL):
        return False
    try:
        return _valid_key(c, group, key)
    except EditError:
        return False


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
    if group.startswith("fxmix:"):              # (the effect itself: its "mix")
        return _effect(c, group[6:])
    if group.startswith("fxsrc:"):
        return _source(c, group)
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
    if group == "params":
        if components.of_clip(c) is None:
            raise EditError("不是元件")
        return c.setdefault("params", {})
    if group.startswith("tvar:"):
        v = textvars.find(c.get("text") or {}, group[5:])
        if v is None:
            raise EditError("沒有這個文字變數")
        return v
    if group.startswith("place:"):
        if components.of_clip(c) is None:
            raise EditError("不是元件")
        return c.setdefault("places", {}).setdefault(group[6:], {})
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
        return [_coerce(v) if isinstance(v, (list, tuple)) else float(v) for v in value]     # (gradient stops, a curve's keys: lists of lists)
    return value if curves.discrete(value) else float(value)


def _check_choice(c, group, key, value):
    if key == "kind" and value not in MASK_KINDS:
        raise EditError(f"unknown mask {value}")
    if key == "align" and group == "text" and value not in TEXT_ALIGNS:
        raise EditError(f"unknown text alignment {value}")
    if key == "valign" and group == "text" and value not in TEXT_VALIGNS:
        raise EditError(f"unknown vertical alignment {value}")
    if key == "stroke_align" and group == "text" and value not in TEXT_STROKE_ALIGNS:
        raise EditError(f"unknown text outline alignment {value}")
    if key == "blend" and group == "clip":
        if c["type"] not in VISUAL or c["type"] == "filter":
            raise EditError("blend modes go on pictures, videos, texts and compound clips")
        if value not in BLEND_MODES:
            raise EditError(f"unknown blend mode {value}")
        if value == "pass_through" and c["type"] != "group":
            raise EditError("only groups pass through")
    if group.startswith("fx:"):
        p = next((q for q in fx.def_of(_effect(c, group[3:])).params if q.name == key), None)
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
    if group.startswith("place:"):
        if not _valid_key(c, group, key):
            raise EditError("元件沒有這個圖片參數")
        value = max(0.01, float(value)) if key in ("w", "h") else float(value)
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
    if group == "text" and key == "box_mode":
        return set_text_box(proj, clip_id, value, t)
    if group == "text" and key in ("box_w", "box_h"):
        value = max(0.0, float(value))
    if group == "asset":
        if not _valid_key(c, group, key):
            raise EditError(f"unknown asset field {key}")
        value = assets.clean(key, value)
    if group == "params":
        p = components.param(components.of_clip(c), key)
        if p is None:
            raise EditError("元件沒有這個參數")
        value = components.clean(p, value)
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
    if group == "params":                        # (a component's own value until then)
        default = components.default(c["compound"], components.param(c["compound"], key))
    elif group.startswith("tvar:"):
        default = textvars.default_value(h.get("kind", "text"))
    elif key in DISCRETE_DEFAULTS and not group.startswith("fx:"):
        _check_choice(c, group, key, DISCRETE_DEFAULTS[key])
        default = DISCRETE_DEFAULTS[key]
    else:
        default = {"scale": 1.0, "opacity": 1.0, "volume": 1.0, "w": 1.0, "h": 1.0, "size": 5.0,
                   "color": [1.0, 1.0, 1.0], "stroke_color": [0.0, 0.0, 0.0],
                   "stroke": 2.0, "mix": 1.0, **textlayout.DECOR}.get(key, 0.0)
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
    for group in [c.get(g) for g in ("transform", "mask", "text", "asset", "params")] + list((c.get("places") or {}).values()):
        for v in (group or {}).values():
            if curves.is_animated(v):
                times |= {k[0] for k in v["keys"]}
    for key in ("volume", "blend"):
        if curves.is_animated(c.get(key)):
            times |= {k[0] for k in c[key]["keys"]}
    for e in c.get("effects") or []:
        for v in list(e["params"].values()) + list((e.get("mask") or {}).values()) + [e.get("mix")] + \
                [x for src in (e.get("sources") or {}).values() for x in src.values()]:
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
MASKABLE = ("image", "video", "text", "compound", "filter", "group")    # clips that take a mask (not sounds)


def _aspect(c):
    """Width / height of the clip's material, so default circles come out round."""
    if c.get("media", {}).get("width"):
        return c["media"]["width"] / c["media"]["height"]
    if c.get("compound"):
        return c["compound"]["width"] / c["compound"]["height"]
    if c.get("text"):
        w, h = textlayout.frame_size(textvars.spec_at(c["text"], 0, TEXT_ANIM_FIELDS))
        return w / h if w > 0 and h > 0 else 16 / 9
    return 16 / 9


MATTES = ("alpha", "luma")          # what of a compound mask's picture lets the clip through
PICTURE_MASKS = ("compound", "image", "video", "track")   # masks that cut with a picture: a compound's, an image
PICTURE_FIELDS = {"compound": ("compound_id", "t_off"),        # file's, a video's (playing), or what a track of
                  "image": ("image", "img_w", "img_h"),        # the clip's own level shows at that moment
                  "video": ("video", "vid_w", "vid_h", "vid_dur", "t_off"),
                  "track": ("track_id", "trk_w", "trk_h")}


def _new_mask(old, kind, aspect):
    """A mask of `kind` keeping what it can of the old one (shape keyframes too)."""
    if kind in PICTURE_MASKS:          # a compound's / an image's picture cuts the clip: chosen next
        m = {"kind": kind, "matte": old.get("matte", "alpha"),
             "invert": old.get("invert", False), "cx": old.get("cx", 0.0), "cy": old.get("cy", 0.0),
             "w": old.get("w", 1.0), "h": old.get("h", 1.0), "rotation": old.get("rotation", 0.0),
             "feather": old.get("feather", 0.0)}
        for k in PICTURE_FIELDS[kind]:
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
    if c["type"] not in MASKABLE:
        raise EditError("masks go on pictures, videos, texts, compound clips, groups and filters")
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


def set_mask_track(proj, clip_id, track_id, size):
    """A 軌道 mask's track (of the clip's own level: what it shows at the same moment cuts the
    clip); size: (width, height) of that level's canvas - the mask takes its proportions."""
    t, c = find(proj, clip_id)
    m = c.get("mask")
    if not m or m.get("kind") != "track":
        raise EditError("這個片段的遮罩不是軌道")
    if not any(tr["id"] == track_id for tr in project.all_tracks(proj["tracks"])):
        raise EditError("找不到這條軌道")
    a, b = _aspect(c), size[0] / size[1]
    m.update(track_id=track_id, trk_w=int(size[0]), trk_h=int(size[1]))
    m["w"], m["h"] = (1.0, round(a / b, 4)) if b > a else (round(b / a, 4), 1.0)
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


def beat_times(c, lo=None, hi=None, beyond=False):
    """Timeline times (us) of the grid lines (beats and their subdivisions) of a clip with
    BPM alignment on, inside the clip (and inside lo..hi when given); with beyond, also the
    line just before its start and the one just after its end."""
    return [t for t, _ in beat_grid(c, lo, hi, beyond=beyond)]


def beat_grid(c, lo=None, hi=None, bars=False, beyond=False):
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
    if beyond:
        a, b = a - period, b + period
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


def source_grid(beat, lo, hi, bars=False):
    """[(time us, d)] of a BPM grid's lines in the sound's own time (the 進階對齊編輯器's), between lo and
    hi: the same lines and d as beat_grid, without a clip, its speed or whether the grid is on."""
    beat = dict(BEAT_DEFAULT, **(beat or {}))
    div = beat["div"] if beat["div"] in BEAT_DIVS else 1
    period = 60 * US / beat["bpm"] / div
    k0, k1 = math.ceil((lo - beat["offset_us"]) / period - 1e-9), math.floor((hi - beat["offset_us"]) / period + 1e-9)
    meter = int(beat["meter"] or 0) if bars else 0
    if div < 1:
        step = round(1 / div)
        return [(beat["offset_us"] + k * period, 0 if meter and (k * step) % meter == 0 else 1) for k in range(k0, k1 + 1)]
    out = []
    for k in range(k0, k1 + 1):
        d = div // math.gcd(k % div, div)
        out.append((beat["offset_us"] + k * period, 0 if meter and d == 1 and (k // div) % meter == 0 else d))
    return out


def level_beats(proj):
    """Every beat grid line (us, the level's time) of the level's sound clips with BPM
    alignment on, a group's included, sorted - with the line just past each clip's ends, so
    an edge after a sound's last beat can go on to the next one."""
    out = set()
    for c, s in _level_starts(proj["tracks"]):
        if (c.get("beat") or {}).get("on"):
            off = s - c["start_us"]
            out |= {round(x + off) for x in beat_times(c, beyond=True)}
    return sorted(out)


def snap_to_beats(proj, clip_ids):
    """Alt+Q: trim each clip's start and end to the nearest beat grid line (level_beats); the
    end goes to the next line after the start when both would land on one. Edges that move
    in go first, so neighbours make room for the ones that move out. Returns the clips."""
    beats = level_beats(proj)
    if not beats:
        raise EditError("沒有拍子：先在有聲音的片段上開啟 BPM 對齊")

    def nearest(x):
        i = bisect.bisect_left(beats, x)
        return min(beats[max(0, i - 1):i + 1], key=lambda b: abs(b - x))
    off = lambda c: abs_start(proj, c["id"]) - c["start_us"]     # (a group's clip: its group's start)
    plans = []
    for cid in clip_ids:
        _, c = find(proj, cid)
        s, e = nearest(c["start_us"] + off(c)), nearest(end(c) + off(c))
        if e <= s:
            e = next((b for b in beats if b > s), None)
            if e is None:
                continue
        plans.append((c, s, e))
    # (in the level's time: a group that grows to the left moves its clips' times in it)
    for _ in range(2):                                   # (a second pass: room made by later clips)
        for grow in (False, True):
            for c, s, e in plans:
                if s != c["start_us"] + off(c) and (s < c["start_us"] + off(c)) == grow:
                    trim_start(proj, c["id"], s - off(c))
                if e != end(c) + off(c) and (e > end(c) + off(c)) == grow:
                    trim_end(proj, c["id"], e - off(c))
    return [c for c, _, _ in plans]


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
    """A clip's plain speed (曲線變速 off): _set_speed."""
    _, c = find(proj, clip_id)
    c.pop("speed_curve", None)
    return _set_speed(proj, clip_id, value)


def _room_after(proj, t, c, want):
    """How long clip c of track t can get when it is to last `want`: up to the next clip of its track and, in a group,
    the group's end - the group grows for it as far as it can itself (as trim_end's)."""
    room = free_range(t, c["start_us"], end(c), ignore=c)[1] - c["start_us"]
    g = group_of(proj, t)
    if g is not None:
        last = c["start_us"] + min(want, room)
        if last > g["duration_us"]:
            trim_end(proj, g["id"], g["start_us"] + last)
        room = min(room, g["duration_us"] - c["start_us"])
    return room


def _set_speed(proj, clip_id, value):
    """A clip's speed: its source plays value times as fast. The clip keeps the same stretch
    of its source, so it gets shorter or longer - as far as the room after it allows (and its
    source lasts); keyframes and fades stretch with it."""
    t, c = find(proj, clip_id)
    _timed(c)
    value = min(SPEED_MAX, max(SPEED_MIN, float(value)))
    old = project.speed(c)
    k = old / value                                      # the clip's new length / its old one
    dur = c["duration_us"] * k
    src_len = source_length(c)
    if src_len is not None and project.frozen(c) is None:
        dur = min(dur, (src_len - c.get("source_start_us", 0)) / value)
    new_dur = int(max(MIN_US, min(dur, _room_after(proj, t, c, dur))))
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


def set_normalize(proj, clip_id, target_db):
    """標準化: the clip's sound brought to a peak of target_db (dBFS) over the part it plays, on
    top of its 音量 (normalize.py); None turns it off."""
    _, c = find(proj, clip_id)
    if "volume" not in c and c["type"] not in ("audio", "video"):
        raise EditError("這個片段沒有聲音")
    if target_db is None:
        c.pop("normalize", None)
    else:
        c["normalize"] = round(min(0.0, max(-60.0, float(target_db))), 2)
    return c


CURVE_DEFAULT = [[0.0, 1.0], [0.25, 1.0], [0.5, 1.0], [0.75, 1.0], [1.0, 1.0]]


def _clean_curve(points):
    pts = sorted([min(1.0, max(0.0, float(u))), min(project.CURVE_MAX, max(project.CURVE_MIN, float(s)))]
                 for u, s in points)
    if len(pts) < 2:
        raise EditError("曲線變速至少要兩個點")
    pts[0][0], pts[-1][0] = 0.0, 1.0                     # (from the clip's start to its end)
    return [[round(u, 4), round(s, 4)] for u, s in pts]


def set_speed_curve(proj, clip_id, points):
    """曲線變速 on (points: [[u, speed]], None: the curve it has, or a flat one), or off (False:
    it keeps its mean speed as a plain one). The clip goes on playing the same part of its source,
    so its length follows the curve's mean speed (as far as the room after it allows - then it
    plays less of it); keyframes and fades stretch with it."""
    t, c = find(proj, clip_id)
    _timed(c)
    if points is False:
        c.pop("speed_curve", None)
        return c
    old = c.get("speed_curve")
    span = c["duration_us"] * project.speed(c)          # (the part of the source it plays)
    pts = _clean_curve(points if points is not None else (old or {}).get("points") or CURVE_DEFAULT)
    mean = project.curve_mean(pts)
    new_dur = int(max(MIN_US, min(span / mean, _room_after(proj, t, c, span / mean))))
    scale_keys(c, new_dur / c["duration_us"] if c["duration_us"] else 1.0)
    for f in ("fade_in_us", "fade_out_us"):
        if c.get(f):
            c[f] = int(min(c[f] * new_dur / max(c["duration_us"], 1), new_dur))
    c["duration_us"] = new_dur
    c["speed_curve"] = {"points": pts}
    c["speed"] = round(mean, 6)
    c.pop("keep_pitch", None)                           # (a curve's sound follows its speed)
    return c


def set_keep_pitch(proj, clip_id, on):
    """保持音高: a clip played faster or slower keeps its sound's pitch (off: it follows the speed)."""
    _, c = find(proj, clip_id)
    _timed(c)
    if on:
        c["keep_pitch"] = True
    else:
        c.pop("keep_pitch", None)
    return c


def set_duration_by_speed(proj, clip_id, target_us):
    """目標長度: the speed that makes the clip last target_us, playing the same part of its source
    (as far as the room after it allows - set_speed)."""
    _, c = find(proj, clip_id)
    _timed(c)
    if target_us <= 0:
        raise EditError("長度要大於 0")
    return set_speed(proj, clip_id, project.speed(c) * c["duration_us"] / float(target_us))


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


def set_mask_video(proj, clip_id, path, width, height, duration_us):
    """A video mask's video: the file at path (width x height px, duration_us long); the mask
    takes its proportions, fitted into the clip, and plays it from its start (t_off)."""
    _, c = find(proj, clip_id)
    m = c.get("mask")
    if not m or m.get("kind") != "video":
        raise EditError("這個片段的遮罩不是影片")
    if not path or not width or not height:
        raise EditError("找不到這個影片")
    a, b = _aspect(c), width / height
    m.update(video=path, vid_w=int(width), vid_h=int(height), vid_dur=int(duration_us or 0))
    m["w"], m["h"] = (1.0, round(a / b, 4)) if b > a else (round(b / a, 4), 1.0)
    return c


def set_mask_offset(proj, clip_id, t_off):
    """編輯區域: which part of a (live) compound mask's compound, or a video mask's video, plays -
    its time at the clip's start (us; it plays on from there with the clip)."""
    _, c = find(proj, clip_id)
    m = c.get("mask")
    if not m or m.get("kind") not in ("compound", "video"):
        raise EditError("這個片段的遮罩不是複合片段或影片")
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
    gs = float(tf.get("scale", 1.0))
    gsy = float(tf.get("scale_y", gs))
    gx, gy = _placed(tf, gs, gsy)
    go = float(tf.get("opacity", 1.0))
    outer = group_of(level, t)
    holder = outer["tracks"] if outer is not None else level["tracks"]
    moves = {id(k): project.anchored(g, ct, k["start_us"]) for ct in g["tracks"] for k in ct["clips"]}
    t["clips"].remove(g)
    at = holder.index(t)
    out = []
    for ct in g["tracks"]:                                       # bottom first: each goes above the last
        for k in ct["clips"]:
            k["start_us"] += g["start_us"]
            ktf = k.get("transform")
            if ktf is not None:
                ax, ay = moves[id(k)]                            # (中心點跟隨最下層物件: folded in)
                kpx, kpy = _pivot(ktf)                           # (its own 中心點 scales with it)
                kax, kay = _anchor(ktf)                          # (its own 錨點 does not: x / y place it)
                ktf["x"] = _map_value(ktf.get("x", 0.0), lambda v: gx + gs * (v + ax) + (gs - 1) * kpx + (1 - gs) * kax)
                ktf["y"] = _map_value(ktf.get("y", 0.0), lambda v: gy + gsy * (v + ay) + (gsy - 1) * kpy + (1 - gsy) * kay)
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


def ungroup_many(root, level, group_ids):
    """Several groups taken apart at once (outer ones first: a group in one comes out with
    its clips, then is taken apart too); returns the clips that came out."""
    def depth(gid):
        n, t = 0, find(level, gid)[0]
        while (g := group_of(level, t)) is not None:
            n, t = n + 1, find(level, g["id"])[0]
        return n
    out = []
    for gid in sorted(group_ids, key=depth):
        out = [k for k in out if k["id"] != gid] + ungroup(root, level, gid)
    return out


def _flat_group(g):
    """(x, y, scale x, scale y) of a group that is not turned, flipped or animated in place
    or size (its clips' canvas place folds in and out of it exactly), else EditError."""
    tf = g.get("transform") or {}
    if any(curves.is_animated(tf.get(k)) for k in ("x", "y", "scale", "scale_y", "rotation", "pivot_x", "pivot_y",
                                              "anchor_x", "anchor_y")) \
            or abs(curves.value(tf.get("rotation", 0.0), 0)) > 1e-9 or tf.get("flip_h") or tf.get("flip_v"):
        raise EditError(f"「{g.get('name') or '群組'}」有旋轉或關鍵幀動畫：片段沒辦法不移動地放進去")
    gs = float(tf.get("scale", 1.0))
    gsy = float(tf.get("scale_y", gs))
    if abs(gs) < 1e-9 or abs(gsy) < 1e-9:
        raise EditError("群組的縮放是 0")
    return _placed(tf, gs, gsy) + (gs, gsy)


def _pivot(tf):
    """A transform's pivot (中心點) at its start, half-canvas units."""
    return curves.value(tf.get("pivot_x", 0.0), 0), curves.value(tf.get("pivot_y", 0.0), 0)


def _anchor(tf):
    """A transform's anchor (錨點) at its start, half-canvas units."""
    return curves.value(tf.get("anchor_x", 0.0), 0), curves.value(tf.get("anchor_y", 0.0), 0)


def _placed(tf, gs, gsy):
    """(x, y) where an unturned, unanimated transform scaled gs x gsy puts its centre: x / y
    moved by scaling about its pivot (project.pivot_shift, which turning would add to)."""
    px, py = _pivot(tf)
    ax, ay = curves.value(tf.get("anchor_x", 0.0), 0), curves.value(tf.get("anchor_y", 0.0), 0)   # (錨點: x / y place it)
    return float(tf.get("x", 0.0)) - ax + (1 - gs) * px, float(tf.get("y", 0.0)) - ay + (1 - gsy) * py


def _groups_around(level, track):
    """The groups a track is inside, innermost first."""
    out, g = [], group_of(level, track)
    while g is not None:
        out.append(g)
        g = group_of(level, find(level, g["id"])[0])
    return out


def _space(level, track, t_us):
    """[(group (x, y, scale x, scale y), its anchored() move)] of the groups track is inside,
    innermost first: how a clip on it at level time t_us is placed on the level's canvas."""
    out, g = [], group_of(level, track)
    while g is not None:
        out.append((_flat_group(g), project.anchored(g, track, t_us - abs_start(level, g["id"]))))
        track = find(level, g["id"])[0]
        g = group_of(level, track)
    return out


def _refit(c, out_of, into):
    """Clip c's place and size from the space inside the groups out_of to the space inside
    into (both _space lists, innermost first), the same on the canvas."""
    ktf = c.get("transform")
    if ktf is None:
        return
    fx = [f for f, _ in out_of]
    tx = [f for f, _ in reversed(into)]                           # outermost first
    ax = [a for _, a in out_of]
    tax = [a for _, a in reversed(into)]

    piv = _pivot(ktf)                                             # (its 中心點 scales with it)
    anc = _anchor(ktf)                                            # (its 錨點 does not)

    def axis(v, i):
        for f, a in zip(fx, ax):
            v = f[i] + f[2 + i] * (v + a[i]) + (f[2 + i] - 1) * piv[i] + (1 - f[2 + i]) * anc[i]
        for f, a in zip(tx, tax):
            v = (v - f[i]) / f[2 + i] - a[i] + (1 / f[2 + i] - 1) * piv[i] + (1 - 1 / f[2 + i]) * anc[i]
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
    every = abs_starts(level)
    starts = {c["id"]: every[c["id"]] for _, c in picked}
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
    spaces = {id(c): _space(level, t, starts[c["id"]]) for t, c in picked}
    for t, c in picked:
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
        _refit(c, spaces[id(c)], _space(level, dst, starts[c["id"]] + shift))
        out.append(c)
    project.link(root)
    return out


def group_ids(level):
    """[(group id, name)] of every group in the level, nested ones too (not those inside its
    compound clips: another level's), in order."""
    out = []

    def walk(tracks):
        for t in tracks:
            for c in t["clips"]:
                if project.is_group(c):
                    out.append((c["id"], c.get("name") or "群組"))
                    walk(c["tracks"])
    walk(level["tracks"])
    return out


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


def set_group_anchor(proj, clip_id, on):
    """中心點跟隨最下層物件 (project.anchor_of): the clips above a group's bottom object count
    their x / y from its centre. They stay where they are: each one's x / y loses (or, turned
    off, gets back) the bottom object's centre at its own start."""
    _, g = find(proj, clip_id)
    if not project.is_group(g):
        raise EditError("這不是群組")
    if bool(g.get("anchor")) == bool(on):
        return g
    g["anchor"] = True                                   # (anchored() reads the moves with it on)
    moves = [(k, project.anchored(g, t, k["start_us"])) for t in g["tracks"] for k in t["clips"]]
    sign = -1 if on else 1
    for k, (ax, ay) in moves:
        ktf = k.get("transform")
        if ktf is not None and (ax or ay):
            ktf["x"] = _map_value(ktf.get("x", 0.0), lambda v: v + sign * ax)
            ktf["y"] = _map_value(ktf.get("y", 0.0), lambda v: v + sign * ay)
    g["anchor"] = bool(on)
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


def set_fx_through(proj, clip_id, on):
    """效果穿透 of a compound clip (project.passes_through)."""
    _, c = find(proj, clip_id)
    if c["type"] != "compound":
        raise EditError("只有複合片段可以讓效果穿透")
    if on:
        c["fx_through"] = True
    else:
        c.pop("fx_through", None)
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


# -- node graph effects (nodegraph.py) ---------------------------------------------------------------
def _graph(c, effect_id):
    e = _effect(c, effect_id)
    if e.get("filter") != fx.GRAPH:
        raise EditError("這不是節點效果")
    return e, e["graph"]


def add_graph_node(proj, clip_id, effect_id, node, x=0.0, y=0.0):
    """Add a node to a node effect: {"type": "filter", "ref": ...}, {"type": "source", "kind": "image" |
    "video" | "compound" | "track" | "shape"} (placed on the clip as a mask is: chosen next, set_effect_source_media). Returns
    its id."""
    _, c = find(proj, clip_id)
    e, g = _graph(c, effect_id)
    inside = node.get("group")                           # (added while looking inside a group: it is a member)
    if node["type"] == nodegraph.FILTER:
        d = fx.get(node["ref"])
        node = {"type": nodegraph.FILTER, "ref": node["ref"]}
    elif node["type"] == nodegraph.SOURCE:
        if node.get("kind") not in nodegraph.SOURCE_KINDS:
            raise EditError("來源節點要是圖片、影片、複合片段、軌道、形狀或文字")
        shape = node.get("shape")
        preset = node.get("preset")                      # (a text node: looks to start with)
        asset = node.get("asset")                        # {"key": a shape preset of assets.py, "colors": (c1, c2)}
        colors = (asset or {}).get("colors")
        if asset:
            preset = assets.get(asset.get("key", ""))
            if node["kind"] != "shape" or preset is None or preset.cat != "shape":
                raise EditError("這不是內建形狀")
            asset = {"key": preset.key, "family": preset.family}
        node = {"type": nodegraph.SOURCE, "kind": node["kind"], **({"asset": asset} if asset else {}),
                **({"op": node["op"] if node.get("op") in dict(nodegraph.VECOPS) else "add"} if node["kind"] == nodegraph.VECTOR else {}),
                **({"svg": True} if node["kind"] == "image" and node.get("svg") else {})}
    elif node["type"] in (nodegraph.INPUT, nodegraph.PARAMS, nodegraph.REROUTE, nodegraph.VIEWER):
        node = {"type": node["type"]}
    elif node["type"] == nodegraph.STRING:                 # (Blender's String constant: words for a text node)
        node = {"type": nodegraph.STRING, "value": str(node.get("value", "文字"))}
    elif node["type"] == nodegraph.FONT:                   # (Blender's Font constant: a font file for a text node)
        node = {"type": nodegraph.FONT, "value": str(node.get("value") or project.DEFAULT_FONT)}
    elif node["type"] == nodegraph.FRAME:
        node = nodegraph.frame_defaults(node)
    else:
        raise EditError("不能新增這種節點")
    if inside and (g["nodes"].get(inside) or {}).get("type") == nodegraph.GROUP:
        node["group"] = inside
    try:
        nid = nodegraph.add_node(g, node, x, y)
    except nodegraph.GraphError as exc:
        raise EditError(str(exc)) from exc
    if node["type"] == nodegraph.FILTER:
        for k, v in fx.default_params(d).items():
            e["params"][nodegraph.param_key(nid, k)] = v
    elif node["type"] == nodegraph.SOURCE:
        set_effect_source(proj, clip_id, effect_id, nid, node["kind"])
        if node["kind"] == "shape" and shape:
            set_effect_shape(proj, clip_id, effect_id, nid, shape)
        if node["kind"] == nodegraph.VECTOR:             # (its operation: a parameter of the effect)
            for q in nodegraph.vecop_def(node).params:
                e["params"][nodegraph.param_key(nid, q.name)] = copy.deepcopy(q.default)
        if node["kind"] == "text":                       # (its fields: parameters of the effect; a preset of the 內建素材 tab sets some)
            for q in nodegraph.text_def(node).params:
                e["params"][nodegraph.param_key(nid, q.name)] = copy.deepcopy(q.default)
            for k, v in (preset or {}).items():
                key = nodegraph.param_key(nid, k)
                if key in e["params"]:
                    e["params"][key] = nodegraph.text_value(k, v)
        if asset:                                        # (its fields: parameters of the effect; its frame keeps the preset's proportions)
            d = nodegraph.asset_def(node)
            for q in d.params:
                e["params"][nodegraph.param_key(nid, q.name)] = copy.deepcopy(q.default)
            c1, c2 = colors or ("#ffffff", "#000000")
            e["params"][nodegraph.param_key(nid, "color")] = assets.to_rgba(c1)
            if any(q.name == "stroke_color" for q in d.params):
                e["params"][nodegraph.param_key(nid, "stroke_color")] = assets.to_rgba(c2, (0.0, 0.0, 0.0, 1.0))
            made = assets.make(assets.get(asset["key"]), "#ffffff", "#000000", 1920, 1080)
            src = e["sources"][nid]
            src["h"] = round(min(1.0, src["w"] * made["h"] / max(made["w"], 1)), 4)
    return nid


def remove_graph_node(proj, clip_id, effect_id, nid):
    _, c = find(proj, clip_id)
    e, g = _graph(c, effect_id)
    node = g["nodes"].get(nid)
    if node is None:
        raise EditError("找不到這個節點")
    if node["type"] == nodegraph.OUTPUT:
        raise EditError("輸出節點不能刪除")
    gone = {nid}                                         # (a group goes with its members, at any depth)
    todo = [nid]
    while todo:
        for m in nodegraph.members(g, todo.pop()):
            gone.add(m)
            todo.append(m)
    nodegraph.remove_node(g, nid)
    for n in gone:
        for k in [k for k in e["params"] if k.startswith(n + ".")]:
            del e["params"][k]
        (e.get("sources") or {}).pop(n, None)
    if "sources" in e and not e["sources"]:
        e.pop("sources")


def group_graph_nodes(proj, clip_id, effect_id, ids, label="群組"):
    """Box nodes ids up in a group node (Ctrl+G); returns its id."""
    _, c = find(proj, clip_id)
    _, g = _graph(c, effect_id)
    try:
        return nodegraph.make_group(g, ids, label)
    except nodegraph.GraphError as exc:
        raise EditError(str(exc)) from exc


def ungroup_graph(proj, clip_id, effect_id, gid):
    """Take a group apart (Ctrl+Alt+G)."""
    _, c = find(proj, clip_id)
    _, g = _graph(c, effect_id)
    try:
        nodegraph.ungroup(g, gid)
    except nodegraph.GraphError as exc:
        raise EditError(str(exc)) from exc


def group_port(proj, clip_id, effect_id, gid, member, socket=None, out=None, name=None):
    """Inside group gid: socket of member is fed by the group's input name (a new one when None), or - with out -
    the group's output name is member's output out."""
    _, c = find(proj, clip_id)
    _, g = _graph(c, effect_id)
    try:
        if out is not None:
            return nodegraph.group_output(g, gid, member, out, name)
        return nodegraph.group_input(g, gid, member, socket, name)
    except nodegraph.GraphError as exc:
        raise EditError(str(exc)) from exc


def group_unplug(proj, clip_id, effect_id, gid, member=None, socket=None, output=None):
    _, c = find(proj, clip_id)
    _, g = _graph(c, effect_id)
    nodegraph.group_unplug(g, gid, member, socket, output)


def rename_graph_group(proj, clip_id, effect_id, gid, label):
    _, c = find(proj, clip_id)
    node = _graph(c, effect_id)[1]["nodes"].get(gid)
    if node is None or node["type"] != nodegraph.GROUP:
        raise EditError("這不是群組")
    node["label"] = label.strip() or "群組"


def add_graph_node_feeding(proj, clip_id, effect_id, node, x, y, dst, socket):
    """A node added where a link dragged out of input `socket` of node dst was let go: its output goes into that input. A
    constant (数值, 顏色...) starts at the value the input held; a 參數輸入 node makes the input's value a parameter of the
    effect (for what only those can feed). Returns the new node's id."""
    _, c = find(proj, clip_id)
    e, g = _graph(c, effect_id)
    value = nodegraph.socket_value(g, e["params"], dst, socket)
    nid = add_graph_node(proj, clip_id, effect_id, node, x, y)
    if node["type"] == nodegraph.PARAMS:
        expose_graph_param(proj, clip_id, effect_id, nid, dst, socket)
        return nid
    connect_graph(proj, clip_id, effect_id, nid, dst, socket)
    if node["type"] == nodegraph.FILTER and value is not None:
        for k, v in nodegraph.constant_params(node["ref"], value).items():
            e["params"][nodegraph.param_key(nid, k)] = v
    return nid


def connect_graph(proj, clip_id, effect_id, src, dst, socket, out=None):
    _, c = find(proj, clip_id)
    _, g = _graph(c, effect_id)
    try:
        nodegraph.connect(g, src, dst, socket, out or None)
    except nodegraph.GraphError as exc:
        raise EditError(str(exc)) from exc


def set_effect_overscan(proj, clip_id, effect_id, value):
    """A node effect's 延伸範圍: "auto" (a margin when the graph moves the picture), or 0 / 25 / 50 / 100 (% of the frame on each side)."""
    _, c = find(proj, clip_id)
    e, _g = _graph(c, effect_id)
    if value in (None, "auto"):
        e.pop("overscan", None)
    elif value in nodegraph.OVERSCAN_STEPS:
        e["overscan"] = value
    else:
        raise EditError("延伸範圍要是自動、0、25、50 或 100")
    return e


def node_item(proj, clip_id, effect_id, nid, action, sock="", name="", src="", out=""):
    """A node with options of its own (Menu Switch): action "add" (a new option at the end, named `name`; src: a node whose picture
    goes into it - the link let go on the empty socket), "rename" (option `sock`), "remove", "up" or "down". Returns the socket."""
    _, c = find(proj, clip_id)
    e, g = _graph(c, effect_id)
    if nid not in g["nodes"]:
        raise EditError("找不到這個節點")
    try:
        if action == "add":
            if src and nodegraph.is_vecop(g["nodes"][nid]) and src in g["nodes"] and not nodegraph.gives_vector(g["nodes"][src], (e.get("sources") or {}).get(src)):
                raise EditError("矢量節點只能接形狀、文字、SVG 圖片或別的矢量節點")
            sock = nodegraph.add_item(g, e["params"], nid, name or None)
            if src:
                nodegraph.connect(g, src, nid, sock, out or None)
        elif action == "rename":
            nodegraph.rename_item(g, e["params"], nid, sock, name)
        elif action == "remove":
            nodegraph.remove_item(g, e["params"], nid, sock)
        elif action in ("up", "down"):
            nodegraph.move_item(g, e["params"], nid, sock, -1 if action == "up" else 1)
        else:
            raise EditError("不知道這個動作")
    except nodegraph.GraphError as exc:
        raise EditError(str(exc)) from exc
    return sock


def expose_graph_param(proj, clip_id, effect_id, src, dst, socket):
    """Drag out of a 參數輸入 node's empty socket onto a parameter: it becomes a parameter of the effect (the 效果
    panel shows it) and is bound to that one. Returns its name."""
    _, c = find(proj, clip_id)
    e, g = _graph(c, effect_id)
    try:
        return nodegraph.expose(g, e["params"], src, dst, socket, e.get("sources"))
    except nodegraph.GraphError as exc:
        raise EditError(str(exc)) from exc


def add_exposed_param(proj, clip_id, effect_id, kind, label=None):
    """The 參數 panel's 新增參數: a parameter of the effect made by hand, of type kind. Returns its name."""
    _, c = find(proj, clip_id)
    e, g = _graph(c, effect_id)
    try:
        return nodegraph.add_exposed(g, e["params"], kind, label)
    except nodegraph.GraphError as exc:
        raise EditError(str(exc)) from exc


def remove_exposed_param(proj, clip_id, effect_id, name):
    _, c = find(proj, clip_id)
    e, g = _graph(c, effect_id)
    nodegraph.remove_exposed(g, e["params"], name)


# -- VFX Nodes: node effects shared by link (project.py _share_vfx) --------------------------------------------
def _vfx(proj, vid):
    m = (proj.get("vfx_nodes") or {}).get(vid)
    if m is None:
        raise EditError("找不到這個 VFX Node")
    return m


def new_vfx_node(proj, name=None, graph=None, sources=None, params=None):
    """A VFX Node of the project: blank unless given a graph (and its sources, and the parameters new uses start at). Returns its id."""
    nodes = proj.setdefault("vfx_nodes", {})
    vid = project.new_vfx_id(proj)
    nodes[vid] = {"id": vid, "name": (name or "").strip() or f"VFX Node {len(nodes) + 1}",
                  "graph": graph if graph is not None else nodegraph.new_graph(), "sources": sources if sources is not None else {}}
    nodes[vid]["params"] = copy.deepcopy(params) if params is not None else nodegraph.default_params(nodes[vid]["graph"])
    return vid


def add_vfx_effect(proj, clip_id, vid, index=None, level=None):
    """Put a use of VFX Node vid on a clip (of `level`, the open compound's content, else the project): the same graph as every
    other use, parameter values of its own (the node's to start)."""
    m = _vfx(proj, vid)
    _, c = find(level or proj, clip_id)
    if c["type"] not in VISUAL:
        raise EditError("filters go on pictures, videos, texts, compound clips and filter clips")
    e = fx.new_effect(fx.GRAPH, new_effect_id())
    e["vfx"] = vid
    e["params"].update(copy.deepcopy(m.get("params") or {}))
    project._share_vfx(proj, e)
    es = c.setdefault("effects", [])
    es.insert(len(es) if index is None else max(0, min(index, len(es))), e)
    return e


def vfx_from_effect(proj, clip_id, effect_id, name=None, level=None):
    """A node effect of a clip becomes a VFX Node (and this clip's use of it). Returns its id."""
    _, c = find(level or proj, clip_id)
    e = _effect(c, effect_id)
    if e.get("filter") != fx.GRAPH:
        raise EditError("這不是節點效果")
    if e.get("vfx"):
        raise EditError("這已經是 VFX Node")
    vid = new_vfx_node(proj, name, e["graph"], e.setdefault("sources", {}), e["params"])
    e["vfx"] = vid
    return vid


def unshare_vfx(proj, clip_id, effect_id):
    """This use of a VFX Node gets a graph of its own (a copy): editing it no longer changes the others."""
    _, c = find(proj, clip_id)
    e = _effect(c, effect_id)
    if not e.get("vfx"):
        raise EditError("這不是 VFX Node")
    e["graph"], e["sources"] = copy.deepcopy(e["graph"]), copy.deepcopy(e.get("sources") or {})
    del e["vfx"]


def rename_vfx_node(proj, vid, name):
    name = (name or "").strip()
    if not name:
        raise EditError("名字不能是空的")
    _vfx(proj, vid)["name"] = name


def delete_vfx_node(proj, vid):
    """Delete VFX Node vid; every clip that used it keeps the effect, as a copy of its own."""
    _vfx(proj, vid)
    for c, e in project.vfx_uses(proj)[vid]:
        e["graph"], e["sources"] = copy.deepcopy(e["graph"]), copy.deepcopy(e.get("sources") or {})
        del e["vfx"]
    del proj["vfx_nodes"][vid]


def duplicate_vfx_node(proj, vid):
    m = _vfx(proj, vid)
    return new_vfx_node(proj, m["name"] + " 副本", copy.deepcopy(m["graph"]), copy.deepcopy(m.get("sources") or {}), m.get("params"))


def edit_exposed_param(proj, clip_id, effect_id, name, fields):
    """The 參數 panel: change an effect parameter's label, type, range or default."""
    _, c = find(proj, clip_id)
    e, g = _graph(c, effect_id)
    try:
        nodegraph.edit_exposed(g, e["params"], name, fields)
    except nodegraph.GraphError as exc:
        raise EditError(str(exc)) from exc


def move_exposed_param(proj, clip_id, effect_id, name, delta):
    _, c = find(proj, clip_id)
    _, g = _graph(c, effect_id)
    try:
        nodegraph.move_exposed(g, name, delta)
    except nodegraph.GraphError as exc:
        raise EditError(str(exc)) from exc


def insert_graph_node(proj, clip_id, effect_id, nid, src, dst, socket, out=None):
    """A node dropped on a link: the link goes through it."""
    _, c = find(proj, clip_id)
    _, g = _graph(c, effect_id)
    try:
        nodegraph.insert_on_link(g, nid, src, dst, socket, out or None)
    except nodegraph.GraphError as exc:
        raise EditError(str(exc)) from exc


def add_graph_reroutes(proj, clip_id, effect_id, spots):
    """Bends put in links (Shift + right drag across them): spots [(x, y, from node, to node, socket, output)]. The links that
    start at the same output are merged: they share one bend, put where the drag crossed them on average."""
    byout = {}
    for spot in spots:
        byout.setdefault((spot[2], spot[5]), []).append(spot)
    for (src, out), group in byout.items():
        x = sum(g[0] for g in group) / len(group)
        y = sum(g[1] for g in group) / len(group)
        first = group[0]
        grp = (_graph(find(proj, clip_id)[1], effect_id)[1]["nodes"].get(first[3]) or {}).get("group")
        nid = add_graph_node(proj, clip_id, effect_id, {"type": nodegraph.REROUTE, **({"group": grp} if grp else {})}, x, y)
        insert_graph_node(proj, clip_id, effect_id, nid, src, first[3], first[4], out)
        for _x, _y, _src, dst, socket, _out in group[1:]:
            connect_graph(proj, clip_id, effect_id, nid, dst, socket)


def dissolve_graph_node(proj, clip_id, effect_id, nid):
    """Delete a node and keep the picture going through it."""
    _, c = find(proj, clip_id)
    e, g = _graph(c, effect_id)
    if (g["nodes"].get(nid) or {}).get("type") == nodegraph.OUTPUT:
        raise EditError("輸出節點不能刪除")
    if (g["nodes"].get(nid) or {}).get("type") == nodegraph.GROUP:     # (a group: taken apart, nothing lost)
        nodegraph.ungroup(g, nid)
        return
    nodegraph.dissolve(g, nid)
    for k in [k for k in e["params"] if k.startswith(nid + ".")]:
        del e["params"][k]
    (e.get("sources") or {}).pop(nid, None)
    if "sources" in e and not e["sources"]:
        e.pop("sources")


def duplicate_graph_nodes(proj, clip_id, effect_id, ids, dx=40.0, dy=40.0):
    """Copies of nodes (settings and pictures too, links among them); returns the new ids."""
    _, c = find(proj, clip_id)
    e, g = _graph(c, effect_id)
    made = nodegraph.duplicate(g, ids, dx, dy)
    for old, new in made.items():
        for k in [k for k in e["params"] if k.startswith(old + ".")]:
            e["params"][new + k[len(old):]] = copy.deepcopy(e["params"][k])
        if old in (e.get("sources") or {}):
            e["sources"][new] = copy.deepcopy(e["sources"][old])
    return list(made.values())


def paste_graph_nodes(proj, clip_id, effect_id, data, x=0.0, y=0.0, group=None):
    """Nodes copied from a node effect (nodegraph.pack) put in this one; returns the new ids."""
    _, c = find(proj, clip_id)
    e, g = _graph(c, effect_id)
    for n in data["nodes"].values():
        if n["type"] == nodegraph.FILTER:
            fx.get(n["ref"])
    made = nodegraph.paste(g, data, x, y, group if (g["nodes"].get(group) or {}).get("type") == nodegraph.GROUP else None)
    for old, new in made.items():
        for k, v in data["params"].items():
            if k.startswith(old + "."):
                e["params"][new + k[len(old):]] = copy.deepcopy(v)
        if old in data["sources"]:
            e.setdefault("sources", {})[new] = copy.deepcopy(data["sources"][old])
    return list(made.values())


def disconnect_graph(proj, clip_id, effect_id, dst, socket):
    _, c = find(proj, clip_id)
    nodegraph.disconnect(_graph(c, effect_id)[1], dst, socket)


def move_graph_nodes(proj, clip_id, effect_id, positions):
    """positions {node id: (x, y)}."""
    _, c = find(proj, clip_id)
    _, g = _graph(c, effect_id)
    for nid, (x, y) in positions.items():
        if nid in g["nodes"]:
            g["nodes"][nid]["x"], g["nodes"][nid]["y"] = float(x), float(y)


def set_graph_frame(proj, clip_id, effect_id, nid, label=None, text=None, color=None, w=None, h=None):
    """A frame's label, note, colour (nodegraph.FRAME_COLORS) and size."""
    _, c = find(proj, clip_id)
    node = _graph(c, effect_id)[1]["nodes"].get(nid)
    if node is None or node["type"] != nodegraph.FRAME:
        raise EditError("這不是框架")
    if color is not None and color not in nodegraph.FRAME_COLORS:
        raise EditError(f"unknown colour {color}")
    for k, v in (("label", label), ("text", text), ("color", color)):
        if v is not None:
            node[k] = v
    if w is not None:
        node["w"] = max(60.0, float(w))
    if h is not None:
        node["h"] = max(40.0, float(h))


def set_graph_node_width(proj, clip_id, effect_id, nid, width):
    """How wide a node's box is drawn in the editor (nodes.MIN_WIDTH and up)."""
    _, c = find(proj, clip_id)
    node = _graph(c, effect_id)[1]["nodes"].get(nid)
    if node is None:
        raise EditError("沒有這個節點")
    node["width"] = max(140.0, float(width))


def set_graph_node_lines(proj, clip_id, effect_id, nid, lines):
    """How many lines tall the words box of a string or text node is drawn."""
    _, c = find(proj, clip_id)
    node = _graph(c, effect_id)[1]["nodes"].get(nid)
    if node is None:
        raise EditError("沒有這個節點")
    lines = max(1, min(12, int(lines)))
    if lines > 1:
        node["lines"] = lines
    else:
        node.pop("lines", None)


def set_graph_viewer(proj, clip_id, effect_id, nid, out=""):
    """Point the editor's preview at node nid's output (Ctrl+Shift+click): the graph's 預覽 node (made when
    there is none, beside the node) takes its picture from there. nid None: the preview node lets go. Exports
    never use it."""
    _, c = find(proj, clip_id)
    g = _graph(c, effect_id)[1]
    viewers = [i for i, n in g["nodes"].items() if n["type"] == nodegraph.VIEWER]
    if nid is None:
        g["links"] = [l for l in g["links"] if l["to"] not in viewers]
        return
    node = g["nodes"].get(nid)
    if node is None or node["type"] in (nodegraph.PARAMS, nodegraph.FRAME, nodegraph.OUTPUT, nodegraph.GROUP, nodegraph.VIEWER):
        raise EditError("這個節點沒有圖可以預覽")
    if out not in [o for o, _ in nodegraph.outputs(node)]:
        raise EditError("這個節點沒有這個輸出")
    if viewers:
        vid = viewers[-1]
    else:
        vid = nodegraph.add_node(g, {"type": nodegraph.VIEWER, **({"group": node["group"]} if node.get("group") else {})},
                                 node.get("x", 0.0) + float(node.get("width", 210.0)) + 60.0, node.get("y", 0.0))
    g["links"] = [l for l in g["links"] if l["to"] != vid]
    try:
        nodegraph.connect(g, nid, vid, "src", out or None)
    except nodegraph.GraphError as exc:
        raise EditError(str(exc)) from exc


def mute_graph_node(proj, clip_id, effect_id, nid, on):
    """Mute a filter node: the picture goes through it unchanged."""
    _, c = find(proj, clip_id)
    node = _graph(c, effect_id)[1]["nodes"].get(nid)
    if node is None or node["type"] != nodegraph.FILTER:
        raise EditError("只有濾鏡節點可以停用")
    if on:
        node["mute"] = True
    else:
        node.pop("mute", None)


def put_effect(proj, clip_id, what, index=None):
    """Put an effect on a clip: what is a filter ref (a new effect at its defaults) or an effect
    (a copy of it, its settings, keyframes and mask included: one dragged from a clip), at index
    in the clip's chain, else after the others."""
    _, c = find(proj, clip_id)
    if c["type"] not in VISUAL:
        raise EditError("filters go on pictures, videos, texts, compound clips and filter clips")
    e = fx.new_effect(what, new_effect_id()) if isinstance(what, str) else dict(copy.deepcopy(what), id=new_effect_id())
    es = c.setdefault("effects", [])
    es.insert(len(es) if index is None else max(0, min(index, len(es))), e)
    return e


def add_effects(proj, clip_id, refs):
    """Several filters on a clip, in order (the files picked together in 選擇濾鏡檔案)."""
    return [add_effect(proj, clip_id, ref) for ref in refs]


def replace_effects(proj, clip_id, whats):
    """A clip's effects all replaced by whats (filter refs or effects, as put_effect): 新增效果 on
    selected clips whose effects are not alike."""
    _, c = find(proj, clip_id)
    c.pop("effects", None)
    return [put_effect(proj, clip_id, w) for w in whats]


_FITS = {"float": "number", "int": "number", "bool": "bool", "menu": "choice", "color": 4, "vec2": 2, "vec3": 3, "curve": 4, "gradient": "gradient"}


def _value_kind(v):
    """What kind of parameter a stored value (or its keyframes') is: as _FITS's values."""
    v = curves.value(v, 0)
    if isinstance(v, list) and v and isinstance(v[0], list) and len(v[0]) == 2 and isinstance(v[0][1], list):
        return "gradient"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "choice"
    return len(v) if isinstance(v, list) else None


def _map_keys(v, fn):
    """Stored value v (a constant or keyframes) with each value turned by fn."""
    if not curves.is_animated(v):
        return fn(v)
    out = copy.deepcopy(v)
    for k in out["keys"]:
        k[1] = fn(k[1])
    return out


def swap_filter(proj, clip_id, effect_id, what):
    """Alt-drop of a filter (or an effect) onto effect effect_id of a clip: the effect becomes
    that filter, keeping its place, switch and mask. When the parameters line up - as many, of
    the same kinds, in the same order (the same filter rewritten or renamed) - the effect keeps
    its values, keyframes included; else it takes what's settings (a dropped effect's, or the
    filter's defaults). Returns whether the values were kept."""
    _, c = find(proj, clip_id)
    e = _effect(c, effect_id)
    ref = what if isinstance(what, str) else what["filter"]
    new = fx.get(ref).params
    old = list((e.get("params") or {}).values())
    kept = bool(new) and len(old) == len(new) and all(_value_kind(v) == _FITS[p.type] for v, p in zip(old, new))
    if kept:
        before = fx.get(e["filter"]).params                   # (none when its file is gone)
        before = before if len(before) == len(new) else [None] * len(new)

        def carry(v, p, q):
            if p.type == "int":
                return _map_keys(v, lambda x: int(round(x)))
            if p.type != "menu":
                return v

            def choice(x):                                     # the same place in the new menu
                if x in p.items:
                    return x
                if q is not None and q.type == "menu" and x in q.items and q.items.index(x) < len(p.items):
                    return p.items[q.items.index(x)]
                return p.default
            return _map_keys(v, choice)
        params = {p.name: carry(v, p, q) for v, p, q in zip(old, new, before)}
    elif isinstance(what, str):
        params = fx.default_params(fx.get(ref))
    else:
        params = copy.deepcopy(what.get("params") or {})
    e["filter"] = ref
    e["params"] = params
    colours = {p.name for p in new if p.type in fx.SOURCE_TYPES}     # (those that can have a source)
    if not isinstance(what, str) and not kept:
        e["sources"] = copy.deepcopy(what.get("sources") or {})
    elif kept:                                     # (renamed with its values: the sources go along)
        names = dict(zip([p.name for p in before if p is not None], [p.name for p in new])) if before[0] else {}
        e["sources"] = {names.get(k, k): v for k, v in (e.get("sources") or {}).items()}
    else:
        e.pop("sources", None)
    e["sources"] = {k: v for k, v in (e.get("sources") or {}).items() if k in colours}
    if not e["sources"]:
        e.pop("sources", None)
    return kept


def remove_effect(proj, clip_id, effect_id, drop_empty=False):
    """Take an effect off a clip. A filter clip without effects does nothing but stays on a
    timeline; drop_empty (a static compound's layers) deletes it with its last effect."""
    _, c = find(proj, clip_id)
    c["effects"].remove(_effect(c, effect_id))
    if not c["effects"]:
        del c["effects"]
        if c["type"] == "filter" and drop_empty:
            delete(proj, clip_id)


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


def move_effect_to(proj, clip_id, effect_id, index):
    """Move an effect to place index of its clip's chain (counted with it still in its place)."""
    _, c = find(proj, clip_id)
    es = c["effects"]
    e = _effect(c, effect_id)
    i = es.index(e)
    es.remove(e)
    es.insert(max(0, min(index - (index > i), len(es))), e)


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


SOURCE_FIELDS = ("cx", "cy", "w", "h", "rotation", "fit")     # where an effect's colour source sits (as a mask)


def _source(c, group):
    """The colour source of group "fxsrc:<effect id>:<param>" of clip c."""
    eid, _, name = group[6:].partition(":")
    src = (_effect(c, eid).get("sources") or {}).get(name)
    if src is None:
        raise EditError("這個顏色沒有來源")
    return src


def set_effect_source(proj, clip_id, effect_id, param, kind):
    """Feed colour parameter param of an effect from a picture ("image"), a video ("video") or
    a compound ("compound"), chosen next (set_effect_source_media); None: its own colour again.
    A number parameter (使用遮罩) takes its number times that picture's brightness. The source
    sits on the clip as a mask does (the whole clip until it is placed)."""
    _, c = find(proj, clip_id)
    e = _effect(c, effect_id)
    if e["filter"] == fx.GRAPH:                          # a node graph's picture / video / compound / track node
        if (e["graph"]["nodes"].get(param) or {}).get("type") != nodegraph.SOURCE:
            raise EditError("這個節點不是來源節點")
    elif not any(p.name == param and p.type in fx.SOURCE_TYPES for p in fx.get(e["filter"]).params):
        raise EditError("這個濾鏡沒有這個顏色或數字參數")
    sources = e.setdefault("sources", {})
    if kind is None:
        sources.pop(param, None)
        if not sources:
            e.pop("sources")
        return e
    if kind == "shape" and e["filter"] == fx.GRAPH:      # a shape node: drawn, not a file (nodegraph.shape_image)
        old = sources.get(param) or {}
        sources[param] = {"kind": "shape", "shape": old.get("shape", "rectangle"), "color": old.get("color", [1.0, 1.0, 1.0, 1.0]),
                          **{k: old.get(k, d) for k, d in (("cx", 0.0), ("cy", 0.0), ("w", 0.5), ("h", 0.5), ("rotation", 0.0))}}
        return e
    if kind == nodegraph.VECTOR and e["filter"] == fx.GRAPH:      # a vector node: its outlines drawn over the whole clip (nothing to place)
        sources[param] = {"kind": nodegraph.VECTOR, "cx": 0.0, "cy": 0.0, "w": 1.0, "h": 1.0, "rotation": 0.0}
        return e
    if kind == "text" and e["filter"] == fx.GRAPH:       # a text node: the words drawn by textlayout.py
        old = sources.get(param) or {}
        sources[param] = {"kind": "text", "content": old.get("content", nodegraph.TEXT_CONTENT),
                          "font_path": old.get("font_path", project.DEFAULT_FONT),
                          **{k: old.get(k, d) for k, d in (("cx", 0.0), ("cy", 0.0), ("w", 1.0), ("h", 1.0), ("rotation", 0.0))}}
        return e
    if kind not in PICTURE_MASKS:
        raise EditError(f"unknown source {kind}")
    old = sources.get(param) or {}
    src = {"kind": kind, **{k: old.get(k, d) for k, d in (("cx", 0.0), ("cy", 0.0), ("w", 1.0), ("h", 1.0),
                                                          ("rotation", 0.0))}}
    for k in PICTURE_FIELDS[kind]:
        if old.get("kind") == kind and old.get(k) is not None:
            src[k] = old[k]
    sources[param] = src
    return e


def set_effect_shape(proj, clip_id, effect_id, nid, shape=None, color=None):
    """A shape node's shape (nodegraph.SHAPES id) and / or colour ([r, g, b, a], 0 - 1)."""
    _, c = find(proj, clip_id)
    src = _source(c, f"fxsrc:{effect_id}:{nid}")
    if src.get("kind") != "shape":
        raise EditError("這不是形狀節點")
    if shape is not None:
        if shape not in dict(nodegraph.SHAPES):
            raise EditError(f"unknown shape {shape}")
        src["shape"] = shape
    if color is not None:
        src["color"] = [float(x) for x in color][:4]
    return src


def set_graph_string(proj, clip_id, effect_id, nid, value):
    """The words of a string node."""
    _, c = find(proj, clip_id)
    _, g = _graph(c, effect_id)
    if (g["nodes"].get(nid) or {}).get("type") != nodegraph.STRING:
        raise EditError("這不是字串節點")
    g["nodes"][nid]["value"] = str(value)


def set_graph_font(proj, clip_id, effect_id, nid, path):
    """The font file of a font node."""
    _, c = find(proj, clip_id)
    _, g = _graph(c, effect_id)
    if (g["nodes"].get(nid) or {}).get("type") != nodegraph.FONT:
        raise EditError("這不是字體節點")
    g["nodes"][nid]["value"] = str(path)


def set_effect_text(proj, clip_id, effect_id, nid, content=None, font_path=None):
    """A text node's words and / or font (a file path)."""
    _, c = find(proj, clip_id)
    src = _source(c, f"fxsrc:{effect_id}:{nid}")
    if src.get("kind") != "text":
        raise EditError("這不是文字節點")
    if content is not None:
        src["content"] = str(content)
    if font_path is not None:
        src["font_path"] = str(font_path)
    return src


def set_effect_source_media(proj, clip_id, effect_id, param, image=None, video=None, compound=None, track=None):
    """What a colour source shows: image (path, width, height), video (path, width, height,
    duration_us) or compound (its id, its entry); it takes that picture's proportions, fitted
    into the clip."""
    _, c = find(proj, clip_id)
    src = _source(c, f"fxsrc:{effect_id}:{param}")
    kind = "image" if image else "video" if video else "track" if track else "compound"
    if src["kind"] != kind:
        raise EditError("來源的種類不對")
    if track:                                            # (track id, (width, height) of its level)
        tid, (w, h) = track
        src.update(track_id=tid, trk_w=int(w), trk_h=int(h))
    elif image:
        path, w, h = image
        if not path or not w or not h:
            raise EditError("找不到這張圖片")
        src.update(image=path, img_w=int(w), img_h=int(h))
    elif video:
        path, w, h, dur = video
        if not path or not w or not h:
            raise EditError("找不到這個影片")
        src.update(video=path, vid_w=int(w), vid_h=int(h), vid_dur=int(dur or 0))
    else:
        kid, comp = compound
        if comp is None:
            raise EditError("找不到這個複合片段")
        src["compound_id"] = kid
        w, h = comp["width"], comp["height"]
    a, b = _aspect(c), w / h
    src["w"], src["h"] = (1.0, round(a / b, 4)) if b > a else (round(b / a, 4), 1.0)
    return src


def set_effect_source_offset(proj, clip_id, effect_id, param, t_off):
    """編輯區域 of a video's or a compound's colour source: its time at the clip's start (us)."""
    _, c = find(proj, clip_id)
    src = _source(c, f"fxsrc:{effect_id}:{param}")
    if src["kind"] not in ("compound", "video"):
        raise EditError("圖片沒有時間")
    t_off = int(round(t_off))
    if t_off:
        src["t_off"] = t_off
    else:
        src.pop("t_off", None)
    return src


def set_effect_mask_invert(proj, clip_id, effect_id, invert, t=None):
    _, c = find(proj, clip_id)
    e = _effect(c, effect_id)
    if not e.get("mask"):
        raise EditError("effect has no mask")
    set_param(proj, clip_id, "fxmask:" + effect_id, "invert", bool(invert), t)


def add_filter_clip(proj, ref, at_us, duration_us=FILTER_DEFAULT_US, track_id=None, effect=None, own_track=False):
    """A filter as a clip of its own: it filters everything on the tracks below it while it
    lasts (with effect: a copy of that effect, settings and all, instead of ref at its
    defaults). It goes on the given track, else on a track that only holds filters (topmost
    with room), else on a new top picture track (own_track: always a new one - a layer of a static compound,
    which is one clip on its own track and always at time 0)."""
    clip = {"id": new_clip_id(proj), "type": "filter", "name": fx.label(ref), "start_us": int(at_us),
            "duration_us": int(duration_us), "source_start_us": 0,
            "transform": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0},
            "effects": [fx.new_effect(ref, new_effect_id()) if effect is None
                        else dict(copy.deepcopy(effect), id=new_effect_id())]}
    cands = []
    if track_id:
        t = track_by_id(proj, track_id)
        if t["kind"] != "audio":
            cands = [t]
    if not cands and not own_track:
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
TRACK_FLAGS = ("muted", "solo", "hidden", "locked", "reference")      # locked: its clips cannot be
                                                                     # picked; reference: 參考 (not output)


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
    tid = "g" + uuid.uuid4().hex[:8] if project.is_group(proj) else new_track_id(proj)   # (a group's tracks: as make_group names them)
    track = {"id": tid, "kind": kind, "name": f"{kind} {n}", "clips": []}
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


def set_track_order(proj, ids_on_screen):
    """The level's tracks in this order on screen, top first (as the timeline shows them:
    pictures, the top layer first, then sound); every track once, pictures above sound."""
    by_id = {t["id"]: t for t in proj["tracks"]}
    ids = list(dict.fromkeys(ids_on_screen))
    if set(ids) != set(by_id) or len(ids) != len(proj["tracks"]):
        raise EditError("軌道的順序要包含每一條軌道")
    rows = [by_id[i] for i in ids]
    sound = [t["kind"] == "audio" for t in rows]
    if sound != sorted(sound):
        raise EditError("畫面軌道要在聲音軌道上面")
    proj["tracks"][:] = [t for t in reversed(rows) if t["kind"] != "audio"] + [t for t in rows if t["kind"] == "audio"]


def reordered(ids, moving, slot):
    """ids (screen order) with the ids in moving taken out and put, in their order, before the
    row that was at index slot (len(ids): at the end)."""
    keep = [i for i in ids[:slot] if i not in moving]
    return keep + [i for i in ids if i in moving] + [i for i in ids[slot:] if i not in moving]


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


def detach_audio(proj, clip_id, streams=None):
    """Split a video clip's sound onto an audio track (as Jianying's 分離音訊): the new audio
    clip takes the volume and fades, the video clip is silenced. streams: the sound streams
    to detach, an audio clip each on its own track (a recording with several); None: the one
    the clip plays. Returns the first new clip."""
    _, c = find(proj, clip_id)
    if c["type"] != "video":
        raise EditError("only video clips have sound to detach")
    m = c["media"]
    fades = {k: c.pop(k) for k in ("fade_in_us", "fade_out_us") if c.get(k)}
    out = []
    for n in [c.get("audio_stream", 0)] if streams is None else streams:
        a = {"id": new_clip_id(proj), "type": "audio", "name": c.get("name") or "audio",
             "start_us": c["start_us"], "duration_us": c["duration_us"],
             "source_start_us": c.get("source_start_us", 0),
             "media": {"path": m["path"], "duration_us": m.get("duration_us")},
             "volume": copy.deepcopy(c.get("volume", 1.0)), **copy.deepcopy(fades)}
        if n:
            a["audio_stream"] = int(n)
        if c.get("speed"):
            a["speed"] = c["speed"]
        # the first audio track with room for it (free_range is None where it overlaps a clip)
        dst = next((t for t in proj["tracks"] if t["kind"] == "audio"
                    and free_range(t, a["start_us"], end(a)) is not None), None)
        if dst is None:
            dst = add_track(proj, "audio")
        dst["clips"].append(a)
        _sort(dst)
        out.append(a)
    c["volume"] = 0.0
    return out[0]


def set_audio_stream(proj, clip_id, n):
    """Which of its file's sound streams an audio or video clip plays (0: the first)."""
    _, c = find(proj, clip_id)
    if c["type"] not in ("audio", "video") or not c.get("media"):
        raise EditError("only video and audio clips have sound streams")
    n = int(n)
    if n < 0:
        raise EditError("no such sound stream")
    if n:
        c["audio_stream"] = n
    else:
        c.pop("audio_stream", None)


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
        renamed = {}
        for t in project.all_tracks(comp["tracks"]):
            for c in t["clips"]:
                renamed[c["id"]] = c["id"] = new_clip_id()
                for h in project.compound_holders(c):    # (a compound clip, mask or effect source)
                    if h["compound_id"] in ids:
                        h["compound_id"] = ids[h["compound_id"]]
        for p in comp.get("params") or []:               # a component's parameters follow its layers
            p["binds"] = [[renamed.get(cid, cid), prop] for cid, prop in p.get("binds") or []]
            if p.get("exprs"):
                p["exprs"] = {components.expr_key(renamed.get(k.split(":", 1)[0], k.split(":", 1)[0]), k.split(":", 1)[1]): x
                              for k, x in p["exprs"].items()}
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


def flatten_static(level, fps):
    """A static compound's content as one frame: every layer (inside its groups too) starts at 0
    and lasts one frame, a track holding more than one clip hands the others to tracks of their
    own right above it, and the compound lasts that frame - whatever is added fills the picture
    (a layer put after the first frame used never to show)."""
    frame = max(1, round(US / fps))
    taken = {t["id"] for t in project.all_tracks(level["tracks"])}      # (ids are the level's, groups' too)

    def new_id():
        k = len(taken)
        while f"t{k}" in taken:
            k += 1
        taken.add(f"t{k}")
        return f"t{k}"

    def flat(tracks):
        out = []
        for t in tracks:
            out.append(t)
            extra = t["clips"][1:]
            t["clips"] = t["clips"][:1]
            for c in extra:                              # (one clip a track: the layers' rule)
                out.append({"id": new_id(), "kind": t["kind"], "name": t.get("name", ""), "clips": [c]})
        for t in out:
            for c in t["clips"]:
                if c["start_us"] or c["duration_us"] != frame:
                    c["start_us"], c["duration_us"] = 0, frame
                    for f in ("fade_in_us", "fade_out_us"):
                        c.pop(f, None)
                if project.is_group(c):
                    c["tracks"] = flat(c["tracks"])
        return out
    level["tracks"] = flat(level["tracks"])
    level["duration_us"] = frame
    return level


def kind_name(static, component=False):
    """複合片段, 靜態片段, 元件 or 靜態元件."""
    return ("靜態" if static else "") + "元件" if component else "靜態片段" if static else "複合片段"


def new_name(comps, static, component=False):
    """"複合片段 n", "靜態片段 n", "元件 n" or "靜態元件 n": the next number of that kind."""
    kind = (component, bool(static))
    n = sum(1 for k in comps.values() if (components.is_component(k), bool(k.get("static"))) == kind) + 1
    return f"{kind_name(static, component)} {n}"


def make_compound(root, container, clip_ids, at_us=None, static=False, component=False):
    """Move clips of the open level into a new shared compound and leave one clip showing it
    in their place: over their whole span, on the topmost picture track they used (or a new
    one above it when that has no room). The tracks they were on come along, in order.
    static makes a static compound (靜態片段), which shows only its first frame, like a
    picture: the content is re-timed (freeze_at) so the moment at at_us (the playhead, kept
    inside the span) is that frame. component makes it a component (元件; with static a
    靜態元件)."""
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
    comp = {"name": new_name(comps, static, component), "width": size.get("width", 1920),
            "height": size.get("height", 1080), "duration_us": int(span), "tracks": inner}
    if static:
        t = span // 2 if at_us is None else at_us - s0
        freeze_at(inner, min(max(t, 0), max(0, span - 1)))
        comp["static"] = True
    if component:
        comp.update(component=True, params=[])
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


def steady(comp):
    """Whether everything in compound comp lasts its whole length: every clip starts at 0 and
    all are as long as each other (a group's clips as long as the group), and none is sound -
    so 轉為靜態片段 (to_static) loses nothing of its layout."""
    def ok(tracks, length):
        for t in tracks:
            for c in t["clips"]:
                if c["type"] == "audio" or c["start_us"] != 0:
                    return False
                if length is not None and abs(c["duration_us"] - length) > KEY_TOL_US:
                    return False
                length = c["duration_us"]
                if project.is_group(c) and not ok(c["tracks"], c["duration_us"]):
                    return False
        return True
    return ok(comp["tracks"], None)


def to_static(root, kid):
    """轉為靜態片段: compound kid (a steady one) becomes a static one, shown like a picture
    (its first frame) by every clip showing it; a component becomes a 靜態元件."""
    comp = (root.get("compounds") or {}).get(kid)
    if not comp:
        raise EditError("只有複合片段可以轉成靜態片段（時間線不行）")
    if comp.get("static"):
        raise EditError("已經是靜態片段")
    if not steady(comp):
        raise EditError("裡面的片段要全部從頭開始、長度一樣，而且沒有聲音")
    comp["static"] = True


def new_static(root, container, at_us, track_id=None):
    """An empty static clip at at_us (enter it to build its picture)."""
    return new_compound(root, container, at_us, track_id, static=True)


def add_compound(root, static=False, size=None, component=False):
    """A new empty compound entry (static: a static one; component: a component, 元件),
    size (width, height) or the project's; no clip shows it yet (it can be opened by
    itself). Returns its id."""
    comps = root.setdefault("compounds", {})
    w, h = size or (root.get("width", 1920), root.get("height", 1080))
    kid = project.new_compound_id(root)
    comps[kid] = {"name": new_name(comps, static, component), "width": w, "height": h,
                  "duration_us": STILL_DEFAULT_US, "tracks": [{"id": "t0", "kind": "video", "name": "V1", "clips": []}]}
    if static:
        comps[kid]["static"] = True
    if component:
        comps[kid].update(component=True, params=[])
    return kid


def new_compound(root, container, at_us, track_id=None, static=False, component=False):
    """A new empty compound (static: a static one; component: a component) and a clip
    showing it at at_us: on track_id, or else on the topmost picture track with room there,
    or a new track. Enter the clip to fill it."""
    size = root if container is root or "width" not in container else container
    kid = add_compound(root, static, (size.get("width", 1920), size.get("height", 1080)), component)
    if track_id is None:
        track_id = next((t["id"] for t in reversed(container["tracks"]) if t["kind"] == "video"
                         and not project.locked(t) and free_range(t, at_us, at_us + STILL_DEFAULT_US) is not None), None)
    return place_compound(root, container, kid, track_id, at_us)


def _copy_compound(root, src):
    """A new compound entry with a copy of src's content (a compound, or a nested timeline),
    named "… 副本". Returns its id (link the project afterwards)."""
    copy_ = {k: v for k, v in src.items() if k not in ("id", "tracks")}
    copy_["tracks"] = json.loads(json.dumps(project._tracks_out(src["tracks"])))
    kid = project.new_compound_id(root)
    copy_["name"] = (src.get("name") or "複合片段") + " 副本"
    root.setdefault("compounds", {})[kid] = copy_
    return kid


def clone_compound(root, compound_id):
    """A copy of compound compound_id as a compound of its own (no clip shows it yet).
    Returns its id."""
    kid = _copy_compound(root, root["compounds"][compound_id])
    project.link(root)
    return kid


def make_unique(root, container, clip_id):
    """Give one compound clip its own copy of its compound (edits no longer reach the others)."""
    _, c = find(container, clip_id)
    if not project.ref_of(c):
        raise EditError("not a compound clip")
    kid = _copy_compound(root, c["compound"])
    c.pop("timeline_id", None)
    c["compound_id"] = kid
    project.link(root)
    return c


def clone_clips(root, level, clip_ids):
    """建立獨立副本: copies of the clips right after them, as duplicate_clips, each compound
    copy with its own copy of its compound (editing it leaves the original alone)."""
    new = duplicate_clips(root, level, clip_ids)
    for c in new:
        if project.ref_of(c):
            make_unique(root, level, c["id"])
    return new


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


# -- components (元件: static compounds with parameters, components.py) ------------------------------
def _component(root, kid):
    comp = (root.get("compounds") or {}).get(kid)
    if not components.is_component(comp):
        raise EditError("不是元件")
    return comp


def make_component(root, kid):
    """Make compound kid a component (元件; a static one a 靜態元件): its clips can be given
    parameters, which every clip showing it sets for itself."""
    comp = (root.get("compounds") or {}).get(kid)
    if not comp:
        raise EditError("只有複合片段可以轉成元件（時間線不行）")
    comp["component"] = True
    comp.setdefault("params", [])


def unmake_component(root, kid):
    """A component back to a plain compound (or static compound): its parameters go, and what
    the clips showing it had set for them."""
    comp = _component(root, kid)
    comp.pop("component", None)
    comp.pop("params", None)
    for _tl, _path, c in project.compound_uses(root).get(kid) or []:
        c.pop("params", None)


def _check_binds(comp, kind, binds):
    index = components.layer_index(comp)
    out = []
    for cid, prop in binds:
        if cid not in index or prop not in components.props_of(index[cid][1]):
            raise EditError("這個圖層沒有那個屬性")
        if components.prop_kind(prop) != kind:
            raise EditError(f"「{components.prop_label(index[cid][1], prop)}」不是{components.KINDS[kind]}參數能設的")
        out.append([cid, prop])
    return out


def _unbind(comp, binds):
    gone = {tuple(b) for b in binds}
    for p in components.params(comp):
        p["binds"] = [b for b in p.get("binds") or [] if tuple(b) not in gone]
        for cid, prop in gone:                           # (the expression a number was set through goes too)
            (p.get("exprs") or {}).pop(components.expr_key(cid, prop), None)
        if "exprs" in p and not p["exprs"]:
            del p["exprs"]


def add_param(root, kid, kind, name, binds, make=False):
    """A new parameter of component kid setting prop of each layer of binds [(clip id,
    prop)] (taken from any parameter that set it before: one parameter per property); no
    binds: one made by hand, of the given kind, to be handed layers later. make: kid is
    made a component first when it is a plain compound. Returns it."""
    if make and not components.is_component((root.get("compounds") or {}).get(kid)):
        make_component(root, kid)
    comp = _component(root, kid)
    if kind not in components.KINDS:
        raise EditError(f"unknown parameter kind {kind}")
    binds = _check_binds(comp, kind, binds)
    _unbind(comp, binds)
    ids = {p["id"] for p in components.params(comp)}
    pid = next(f"p{i}" for i in range(1, len(ids) + 2) if f"p{i}" not in ids)
    p = {"id": pid, "name": str(name).strip() or components.KINDS[kind], "kind": kind, "binds": binds}
    if not binds:
        p["default"] = components.clean(p, components.FALLBACK[kind])
    comp.setdefault("params", []).append(p)
    return p


def set_param_kind(root, kid, pid, kind):
    """A parameter made by hand takes another kind: its default starts again, and what clips set for it goes. One that
    sets layers keeps its kind (the layers' props are of it): let go of them first."""
    comp = _component(root, kid)
    p = components.param(comp, pid)
    if p is None:
        raise EditError("元件沒有這個參數")
    if kind not in components.KINDS:
        raise EditError(f"unknown parameter kind {kind}")
    if kind == p["kind"]:
        return
    if p.get("binds"):
        raise EditError("這個參數還在控制片段：先解除片段，才能改種類")
    p["kind"] = kind
    p["default"] = components.clean(p, components.FALLBACK[kind])
    p.pop("exprs", None)
    for _tl, _path, c in project.compound_uses(root).get(kid) or []:
        for held in ("params", "places"):
            own = c.get(held) or {}
            own.pop(pid, None)
            if not own:
                c.pop(held, None)


def bind_param(root, kid, pid, binds):
    """Let parameter pid set these layers' props too."""
    comp = _component(root, kid)
    p = components.param(comp, pid)
    if p is None:
        raise EditError("元件沒有這個參數")
    binds = _check_binds(comp, p["kind"], binds)
    _unbind(comp, binds)
    p["binds"] = (p.get("binds") or []) + binds


def unbind_param(root, kid, binds):
    """No parameter sets these [(clip id, prop)] any more."""
    _unbind(_component(root, kid), binds)


def set_prop_expr(proj, clip_id, prop, text):
    """The expression (propexpr.py) the clip's number prop ("group.key", components.number_props_of)
    follows; "" takes it away."""
    _, c = find(proj, clip_id)
    if prop not in components.number_props_of(c) + components.instance_props(c):
        raise EditError("這個片段沒有那個數字")
    if lfo.is_lfo(text):
        why = lfo.check(text)
        if why:
            raise EditError(f"LFO 有問題：{why}")
        text = copy.deepcopy(text)
    elif mapping.is_mapping(text):
        why = mapping.check(text)
        if why:
            raise EditError(f"映射有問題：{why}")
        text = copy.deepcopy(text)
    else:
        text = str(text).strip()
        why = expr.check(text) if text else None
        if why:
            raise EditError(f"表達式有問題：{why}")
    if text:
        c.setdefault("expr", {})[prop] = text
    else:
        (c.get("expr") or {}).pop(prop, None)
        if not c.get("expr"):
            c.pop("expr", None)
    return c


# -- the parameter rack (全局參數架, rack.py) --------------------------------------------------------
def _rack_param(root, rid):
    p = rack.find(root, rid)
    if p is None:
        raise EditError("沒有這個全局參數")
    return p


def add_rack_param(root, name, value=0.0):
    """A new global parameter; returns it."""
    name = str(name).strip()
    why = rack.name_problem(root, name)
    if why:
        raise EditError(why)
    ids = {p["id"] for p in rack.params(root)}
    rid = next(f"r{i}" for i in range(1, len(ids) + 2) if f"r{i}" not in ids)
    p = {"id": rid, "name": name, "value": float(value)}
    root.setdefault("rack", []).append(p)
    return p


def rename_rack_param(root, rid, name):
    """Rename a parameter; every expression that reads it (clips', other parameters') follows."""
    p = _rack_param(root, rid)
    name = str(name).strip()
    why = rack.name_problem(root, name, rid)
    if why:
        raise EditError(why)
    old, p["name"] = p["name"], name
    if old == name:
        return p
    for q in rack.params(root):
        if q.get("expr"):
            q["expr"] = rack.rename_in(q["expr"], old, name)
    for c in rack.clips_with_exprs(root):
        c["expr"] = {k: rack.rename_expr(x, old, name) for k, x in c["expr"].items()}
    return p


def delete_rack_param(root, rid):
    """Remove a parameter (expressions that read it are left, and read nothing)."""
    _rack_param(root, rid)
    root["rack"] = [p for p in rack.params(root) if p["id"] != rid]
    if not root["rack"]:
        del root["rack"]


def move_rack_param(root, rid, d):
    ps = rack.params(root)
    i = next((i for i, p in enumerate(ps) if p["id"] == rid), None)
    if i is None:
        raise EditError("沒有這個全局參數")
    j = min(max(i + d, 0), len(ps) - 1)
    ps.insert(j, ps.pop(i))


def set_rack_expr(root, rid, text):
    """The expression of a parameter ("" or "input": none). Refused when it makes a circle."""
    p = _rack_param(root, rid)
    text = str(text).strip()
    why = expr.check(text) if text else None
    if why:
        raise EditError(f"表達式有問題：{why}")
    before = p.get("expr")
    if not text or text == "input":
        p.pop("expr", None)
        return p
    p["expr"] = text
    loop = rack.cycle(root)
    if loop:
        if before:
            p["expr"] = before
        else:
            p.pop("expr", None)
        raise EditError("循環依賴：" + " → ".join(loop + [loop[0]]))
    return p


def set_rack_lfo(root, rid, spec):
    """The LFO (lfo.py) a parameter is the output of; None takes it away (the parameter is its value again)."""
    p = _rack_param(root, rid)
    if spec is None:
        p.pop("lfo", None)
        return p
    why = lfo.check(spec)
    if why:
        raise EditError(f"LFO 有問題：{why}")
    p["lfo"] = copy.deepcopy(spec)
    return p


def set_rack_value(root, rid, value, t_us=None):
    """A parameter's value; with keyframes, the key at t_us (new when none is there)."""
    p = _rack_param(root, rid)
    value = float(value)
    cur = p.get("value", 0.0)
    if not curves.is_animated(cur):
        p["value"] = value
        return p
    if t_us is None:
        raise EditError("這個參數有關鍵幀：要給時間")
    i = key_at(cur, t_us)
    if i is None:
        cur["keys"].append([int(t_us), value, 0.0, 0.0, 0.0, 0.0])
        cur["keys"].sort(key=lambda k: k[0])
    else:
        cur["keys"][i][1] = value
    return p


def toggle_rack_key(root, rid, t_us):
    """Add a key at t_us holding the value there, or remove the key that is there."""
    p = _rack_param(root, rid)
    cur = p.get("value", 0.0)
    i = key_at(cur, t_us)
    if i is not None:
        k = cur["keys"].pop(i)
        if not cur["keys"]:
            p["value"] = k[1]
        return p
    v = curves.value(cur, t_us)
    if curves.is_animated(cur):
        cur["keys"].append([int(t_us), v, 0.0, 0.0, 0.0, 0.0])
        cur["keys"].sort(key=lambda k: k[0])
    else:
        p["value"] = {"keys": [[int(t_us), v, 0.0, 0.0, 0.0, 0.0]]}
    return p


def set_rack_easing(root, rid, t_us, easing):
    """Shape the curve from the key at t_us to the next one with a preset (EASINGS)."""
    p = _rack_param(root, rid)
    cur = p.get("value", 0.0)
    i = key_at(cur, t_us)
    if i is None or i + 1 >= len(cur["keys"]):
        raise EditError("需要播放頭上有關鍵幀，而且後面還有下一個")
    if easing not in EASINGS:
        raise EditError(f"unknown easing {easing}")
    a, b = cur["keys"][i], cur["keys"][i + 1]
    dt = b[0] - a[0]
    x1, x2 = EASINGS[easing]
    a[4], a[5] = x1 * dt, 0.0
    b[2], b[3] = (x2 - 1.0) * dt, 0.0
    return p


def import_rack(root, items):
    """Add the parameters of an exported rack (rack.parse_import); one whose name is taken gets a
    number after it. Returns how many were added."""
    for d in items:
        name, k = d["name"], 2
        while rack.name_problem(root, name):
            name, k = f"{d['name']}{k}", k + 1
        p = add_rack_param(root, name, 0.0)
        p["value"] = copy.deepcopy(d["value"])
        if d.get("expr"):
            p["expr"] = d["expr"]
        if d.get("lfo"):
            p["lfo"] = d["lfo"]
    loop = rack.cycle(root)
    if loop:                                                  # (names that were taken may have joined a circle)
        for p in rack.params(root)[-len(items):]:
            p.pop("expr", None)
    return len(items)


def set_bind_expr(root, kid, pid, cid, prop, text):
    """The expression (expr.py) through which number parameter pid sets prop of layer cid ("" or
    "input": the value as it is)."""
    p = components.param(_component(root, kid), pid)
    if p is None:
        raise EditError("元件沒有這個參數")
    if p["kind"] != "number":
        raise EditError("只有數字參數可以用表達式")
    if [cid, prop] not in [list(b) for b in p.get("binds") or []]:
        raise EditError("這個參數沒有設定那個屬性")
    if mapping.is_mapping(text):
        why = mapping.check(text)
        if why:
            raise EditError(f"映射有問題：{why}")
        text = None if text["mode"] == "direct" else copy.deepcopy(text)
    else:
        text = str(text).strip()
        why = expr.check(text) if text else None
        if why:
            raise EditError(f"表達式有問題：{why}")
    key = components.expr_key(cid, prop)
    if not text or text == "input":
        (p.get("exprs") or {}).pop(key, None)
        if "exprs" in p and not p["exprs"]:
            del p["exprs"]
    else:
        p.setdefault("exprs", {})[key] = text


def rename_param(root, kid, pid, name):
    p = components.param(_component(root, kid), pid)
    if p is None:
        raise EditError("元件沒有這個參數")
    p["name"] = str(name).strip() or components.KINDS[p["kind"]]


def move_param(root, kid, pid, d):
    """A parameter d places up (-) or down (+) the list (the order the inspector shows)."""
    ps = _component(root, kid)["params"]
    i = next((i for i, p in enumerate(ps) if p["id"] == pid), None)
    if i is None:
        raise EditError("元件沒有這個參數")
    j = min(max(i + d, 0), len(ps) - 1)
    ps.insert(j, ps.pop(i))


def delete_param(root, kid, pid):
    """Remove a parameter, and every clip's value for it."""
    comp = _component(root, kid)
    comp["params"] = [p for p in comp["params"] if p["id"] != pid]
    for _tl, _path, c in project.compound_uses(root).get(kid) or []:
        own, places = c.get("params") or {}, c.get("places") or {}
        own.pop(pid, None)
        places.pop(pid, None)
        if not own:
            c.pop("params", None)
        if not places:
            c.pop("places", None)


def set_param_default(root, kid, pid, value):
    """A parameter's default: every clip it sets gets value (at its start, where keyframed)."""
    comp = _component(root, kid)
    p = components.param(comp, pid)
    if p is None:
        raise EditError("元件沒有這個參數")
    value = components.clean(p, value)
    p["default"] = value                                 # (what it shows while no layer is set by it)
    index = components.layer_index(comp)
    for cid, prop in p.get("binds") or []:
        if cid not in index:
            continue
        t, c = index[cid]
        at = 0
        if prop == "content":
            c["text"]["content"] = value
        elif prop == "text_color":
            set_param(comp, cid, "text", "color", value[:3], at)
        elif prop in ("color", "color2", "stroke_color"):
            set_param(comp, cid, "asset", prop, value, at)
        elif prop == "source":
            size = components.media_size(value) if value else None
            if size is None:
                raise EditError("讀不到這張圖片")
            replace_media(comp, cid, {"kind": "image", "path": value, "width": size[0], "height": size[1]})
        elif "." in prop:
            group, key = prop.split(".", 1)
            _label, _d, factor, lo, hi = components.number_info(c, prop)
            v = min(max(float(value) / factor, -1e12 if lo is None else lo), 1e12 if hi is None else hi)
            set_param(comp, cid, group, key, v, at)
        elif prop == "visible":
            if len(t["clips"]) > 1:
                raise EditError(f"「{c.get('name') or c['type']}」的軌道上還有別的片段：顯示開關的預設值是"
                                "整條軌道的隱藏，先把它放到自己的軌道上")
            if value:
                t.pop("hidden", None)
            else:
                t["hidden"] = True


def reset_params(proj, clip_id, pids=None):
    """A component clip's values for these parameters (None: all) go: it shows the
    component's own again."""
    _, c = find(proj, clip_id)
    own = c.get("params") or {}
    places = c.get("places") or {}
    for pid in list(own) + list(places) if pids is None else pids:
        own.pop(pid, None)
        places.pop(pid, None)                    # (its picture's place goes with it)
    if not own:
        c.pop("params", None)
    if not places:
        c.pop("places", None)
    return c


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
    if proj["active_timeline"] == tl_id:                 # leave it first: proj["tracks"] is its tracks, and
        open_timeline(proj, proj["timelines"][i - 1 if i else 1]["id"])   # linking without it would put them in the first timeline
    proj["timelines"].remove(tl)


# -- markers (時間線標記) ----------------------------------------------------------------------------
# a marker: {"id", "t_us" (level time), "name", "color" (#rrggbb)}, kept by the level it is on: the
# open timeline (the project's: its timeline entry), a compound's content, a nested timeline
MARKER_COLORS = (("藍", "#4c8dff"), ("紅", "#e5484d"), ("橙", "#f76b15"), ("黃", "#f5d90a"),
                 ("綠", "#30a46c"), ("青", "#12a5a5"), ("紫", "#8e4ec6"), ("粉", "#e93d82"), ("白", "#e6e6e6"))


def _marker_owner(level):
    return project.timeline(level) if level.get("timelines") else level


def markers_of(level):
    """A level's markers in time order (a timeline view of a compound: its "markers")."""
    return sorted(_marker_owner(level).get("markers") or (), key=lambda m: m["t_us"])


def _marker(level, mid):
    m = next((m for m in _marker_owner(level).get("markers") or () if m["id"] == mid), None)
    if m is None:
        raise EditError("沒有這個標記")
    return m


def add_marker(level, t_us, name=None, color=None):
    """A marker at level time t_us (named 標記 n, in the colour of the last one added)."""
    ms = _marker_owner(level).setdefault("markers", [])
    t_us = int(max(0, t_us))
    if any(m["t_us"] == t_us for m in ms):
        raise EditError("這裡已經有標記")
    ids = {m["id"] for m in ms}
    n = len(ms) + 1
    while f"m{n}" in ids:
        n += 1
    m = {"id": f"m{n}", "t_us": t_us, "name": str(name).strip() if name else f"標記 {n}",
         "color": color or (ms[-1]["color"] if ms else MARKER_COLORS[0][1])}
    ms.append(m)
    return m


def move_marker(level, mid, t_us):
    m = _marker(level, mid)
    t_us = int(max(0, t_us))
    if any(o["t_us"] == t_us and o is not m for o in _marker_owner(level)["markers"]):
        raise EditError("那裡已經有標記")
    m["t_us"] = t_us
    return m


def rename_marker(level, mid, name):
    m = _marker(level, mid)
    m["name"] = str(name).strip() or m["name"]
    return m


def set_marker_color(level, mid, color):
    m = _marker(level, mid)
    m["color"] = color
    return m


def delete_marker(level, mid):
    """Remove a marker (None: every marker of the level)."""
    owner = _marker_owner(level)
    if mid is None:
        owner.pop("markers", None)
        return
    m = _marker(level, mid)
    owner["markers"].remove(m)
