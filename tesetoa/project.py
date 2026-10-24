"""Project model: plain JSON-able dicts, saved as *.tesetoa.json.

project  {format, version, width, height, fps, duration_us, timelines: [timeline],
          active_timeline, tracks, compounds: {id: compound}, master_gain}
         Several timelines share the media and the compounds (as in DaVinci Resolve);
         "tracks" is the open timeline's track list (the very list in timelines), so every
         edit works on the open timeline.  master_gain (optional, 1) scales the
         whole output  tracks[0] is the bottom layer; later tracks draw on top
         (as in Jianying).
timeline {id, name, tracks: [track]}
track    {id, kind: video | text | audio, name, clips: [clip],
          muted, solo, hidden, gain}                        optional: muted / solo tracks
                     make no sound (solo silences the others), hidden ones draw nothing,
                     gain multiplies the track's sound
clip     {id, type: image | video | audio | text | compound, name,
          start_us, duration_us, source_start_us,
          media: {path, width, height, duration_us}         image / video / audio
          transform: {x, y, scale, rotation, opacity}       visual clips, Jianying units:
                     x, y in half-canvas units (y up), clockwise degrees
          mask: {kind, invert, cx, cy, w, h, rotation, feather, enabled} or None;
                a mask with enabled: false keeps its settings but cuts nothing
          text: {content, font_path, size, color, letter_spacing, line_spacing,
                 italic_deg, styles}                        text clips
          volume, fade_in_us, fade_out_us                   clips with sound
          compound_id                                       compound clips: which entry of
                     project.compounds they show; clip.source_start_us selects the window}
compound {name, width, height, duration_us, tracks}   reusable content: any number of compound
         clips (anywhere, nested too) show the same one, so editing it changes all of them.
         Its children use compound time.
Numbers that animate are curve dicts, see curves.py.

In memory every compound clip also has "compound": the very dict in project.compounds (so
code can walk into it). On disk, and in undo snapshots, only compound_id is kept: dumps()
leaves the links out and link() puts them back.
"""
import json
import os

FORMAT = "tesetoa"
VERSION = 3                     # 2: shared compounds; 3: several timelines
DEFAULT_FONT = next((f for f in (r"C:\Windows\Fonts\msjh.ttc",
                                 "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
                                 "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
                     if os.path.exists(f)), None)


def new(width=1920, height=1080, fps=60.0):
    p = {"format": FORMAT, "version": VERSION, "width": width, "height": height,
         "fps": fps, "duration_us": 0, "compounds": {},
         "timelines": [{"id": "tl1", "name": "時間線 1", "tracks": []}], "active_timeline": "tl1"}
    return link(p)


def load(path):
    with open(path, encoding="utf-8") as fh:
        p = json.load(fh)
    if p.get("format") != FORMAT:
        raise ValueError(f"{path} is not a tesetoa project")
    return normalize(p)


def save(p, path):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(dumps(p, indent=1))
    os.replace(tmp, path)          # never leave a half-written project behind


def end_us(tracks):
    return max((c["start_us"] + c["duration_us"] for t in tracks for c in t["clips"]), default=0)


def refresh_duration(p):
    p["duration_us"] = end_us(p["tracks"])


def walk_clips(tracks):
    """Yield every clip, descending into compound clips."""
    for t in tracks:
        for c in t["clips"]:
            yield c
            if c.get("compound"):
                yield from walk_clips(c["compound"]["tracks"])


def sounds(track, tracks):
    """Gain of a track's sound (0 when muted, or when another track of its level is solo)."""
    if track.get("muted"):
        return 0.0
    if any(t.get("solo") for t in tracks) and not track.get("solo"):
        return 0.0
    return float(track.get("gain", 1.0))


def active_mask(c):
    """The clip's mask if it is switched on, else None."""
    m = c.get("mask")
    return m if m and m.get("enabled", True) else None


def visible(track):
    return not track.get("hidden")


# -- shared compounds -------------------------------------------------------------------------------
def _tracks_out(tracks):
    """Tracks with compound clips reduced to their compound_id (shallow copies)."""
    out = []
    for t in tracks:
        clips = []
        for c in t["clips"]:
            if "compound_id" in c and "compound" in c:
                c = {k: v for k, v in c.items() if k != "compound"}
            clips.append(c)
        out.append(dict(t, clips=clips))
    return out


def _sync(p):
    """A list assigned to p["tracks"] becomes the open timeline's tracks."""
    tls = p.get("timelines")
    if tls and "tracks" in p:
        tl = next((t for t in tls if t["id"] == p.get("active_timeline")), tls[0])
        if tl["tracks"] is not p["tracks"]:
            tl["tracks"] = p["tracks"]


def detached(p):
    """The project as stored: links to shared compounds and the open timeline left out."""
    _sync(p)
    out = {k: v for k, v in p.items() if k != "tracks"}
    out["timelines"] = [dict(t, tracks=_tracks_out(t["tracks"])) for t in p.get("timelines", [])]
    out["compounds"] = {k: dict(v, tracks=_tracks_out(v["tracks"])) for k, v in p.get("compounds", {}).items()}
    return out


def dumps(p, **kw):
    return json.dumps(detached(p), ensure_ascii=False, **kw)


def link(p):
    """Point every compound clip at its shared entry and p.tracks at the open timeline (after
    loading or restoring a snapshot)."""
    comps = p.setdefault("compounds", {})
    _sync(p)
    tls = p.get("timelines") or []
    if tls:
        tl = next((t for t in tls if t["id"] == p.get("active_timeline")), tls[0])
        p["active_timeline"] = tl["id"]
        p["tracks"] = tl["tracks"]

    def visit(tracks):
        for t in tracks:
            for c in t["clips"]:
                if "compound_id" in c:
                    c["compound"] = comps[c["compound_id"]]
    for tl in tls or [{"tracks": p.get("tracks", [])}]:
        visit(tl["tracks"])
    for comp in comps.values():
        visit(comp["tracks"])
    return p


def timeline(p, tl_id=None):
    return next(t for t in p["timelines"] if t["id"] == (tl_id or p["active_timeline"]))


def all_clips(p):
    """Every clip of every timeline, compound content included (each compound once)."""
    for tl in p.get("timelines") or [{"tracks": p["tracks"]}]:
        for t in tl["tracks"]:
            yield from t["clips"]
    for comp in p.get("compounds", {}).values():
        for t in comp["tracks"]:
            yield from t["clips"]


def new_compound_id(p):
    ids = set(p.get("compounds", {}))
    n = len(ids) + 1
    while f"k{n}" in ids:
        n += 1
    return f"k{n}"


def _without_ids(obj):
    if isinstance(obj, dict):
        return {k: _without_ids(v) for k, v in obj.items() if k not in ("id", "name")}
    if isinstance(obj, list):
        return [_without_ids(v) for v in obj]
    return obj


def normalize(p):
    """Bring a loaded or imported project to the current model: compound content written
    inside clips (version 1, Jianying imports) becomes shared entries of p.compounds, one
    per distinct content (copies that differ only in ids are merged), and is linked."""
    if "timelines" not in p:                               # versions 1 and 2: one timeline
        p["timelines"] = [{"id": "tl1", "name": "時間線 1", "tracks": p.get("tracks", [])}]
        p["active_timeline"] = "tl1"
    _sync(p)
    comps = p.setdefault("compounds", {})

    def key_of(comp):
        return json.dumps(_without_ids(_tracks_out(comp["tracks"])), sort_keys=True)             + json.dumps([comp.get("width"), comp.get("height")])

    seen = {}

    def visit(tracks):
        for t in tracks:
            for c in t["clips"]:
                if c.get("type") != "compound" or "compound_id" in c:
                    continue
                comp = c.pop("compound")
                visit(comp["tracks"])                        # nested ones first
                key = key_of(comp)
                if key not in seen:
                    kid = new_compound_id(p)
                    comp.setdefault("name", c.get("name") or "複合片段")
                    comp.setdefault("duration_us", end_us(comp["tracks"]))
                    comps[kid] = comp
                    seen[key] = kid
                c["compound_id"] = seen[key]
    for cid, comp in list(comps.items()):                  # entries saved before
        visit(comp["tracks"])
        seen.setdefault(key_of(comp), cid)
    for tl in p["timelines"]:
        visit(tl["tracks"])
    p["version"] = VERSION
    return link(p)


def compound_uses(p):
    """{compound id: [(timeline id, parent path (clip ids), clip)]} for every compound clip
    of every timeline, nested ones reached through every clip that shows their parent."""
    uses = {k: [] for k in p.get("compounds", {})}

    def visit(tl, tracks, path):
        for t in tracks:
            for c in t["clips"]:
                if "compound_id" in c:
                    uses.setdefault(c["compound_id"], []).append((tl, list(path), c))
                    if len(path) < 16:                    # (a loop cannot be made, but stay safe)
                        visit(tl, c["compound"]["tracks"], path + [c["id"]])
    for tl in p.get("timelines") or [{"id": None, "tracks": p["tracks"]}]:
        visit(tl["id"], tl["tracks"], [])
    return uses


def contains(p, outer_id, inner_id):
    """Whether compound outer_id shows compound inner_id (at any depth), or is it."""
    if outer_id == inner_id:
        return True
    stack, seen = [outer_id], set()
    while stack:
        k = stack.pop()
        if k in seen:
            continue
        seen.add(k)
        for t in p["compounds"][k]["tracks"]:
            for c in t["clips"]:
                if "compound_id" in c:
                    if c["compound_id"] == inner_id:
                        return True
                    stack.append(c["compound_id"])
    return False
