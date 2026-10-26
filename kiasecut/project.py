"""Project model: plain JSON-able dicts, saved as *.kiasecut.json.

project  {format, version, width, height, fps, duration_us, timelines: [timeline],
          active_timeline, tracks, compounds: {id: compound}, master_gain}
         Several timelines share the media and the compounds (as in DaVinci Resolve);
         "tracks" is the open timeline's track list (the very list in timelines), so every
         edit works on the open timeline.  master_gain (optional, 1) scales the
         whole output  tracks[0] is the bottom layer; later tracks draw on top
         (as in Jianying).  font_map (optional): {"windows" | "linux" | "mac": {font file:
         installed font file}} - per operating system, the font that stands in for one
         the texts name but that system does not have (fonts.py); not part of undo.
timeline {id, name, tracks: [track]}
track    {id, kind: video | text | audio, name, clips: [clip],
          muted, solo, hidden, locked, gain}                optional: muted / solo tracks
                     make no sound (solo silences the others), hidden ones draw nothing,
                     locked ones cannot have their clips picked (locked()), gain
                     multiplies the track's sound
clip     {id, type: image | video | audio | text | compound, name,
          start_us, duration_us, source_start_us,
          media: {path, width, height, duration_us}         image / video / audio
          transform: {x, y, scale, rotation, opacity}       visual clips, Jianying units:
                     x, y in half-canvas units (y up), clockwise degrees; scale is the
                     X scale, optional scale_y the Y one (absent: same as X), optional
                     scale_link (default true): X and Y change together, keeping their ratio
          asset: {key, family, w, h, color, ...}            built-in assets (assets.py): an
                     image clip drawn from these parameters, at its own size (picture_size)
          mask: {kind, invert, cx, cy, w, h, rotation, feather, enabled} or None;
                a mask with enabled: false keeps its settings but cuts nothing. kind
                "compound" (no keyframes) cuts with a compound's picture, stretched over the
                w x h frame: + compound_id (an entry of project.compounds; none chosen or
                gone: nothing is cut), matte "alpha" | "luma" (its opacity or its brightness
                lets the clip through); a live compound plays at clip time + t_off (編輯區域,
                optional, us; held at its first / last frame), a static one shows its still;
                no feather. kind "image" cuts the same way with a picture file: image (its
                path), img_w / img_h (its size, for its proportions)
          text: {content, font_path, size, color, letter_spacing, line_spacing,
                 italic_deg, styles}                        text clips
          volume, fade_in_us, fade_out_us                   clips with sound
          backdrop: {on, hide}                              visual clips with effects, optional:
                     套用至背景 - the effects work on what is under the clip, inside its
                     shape (its alpha, mask and opacity; a built-in asset's: where it is
                     and its mask, not its colours' alpha nor opacity), like CSS
                     backdrop-filter; hide
                     (隱藏本體) leaves the clip itself undrawn - always so but for built-in
                     assets (backdrop_of())
          speed                                             videos, sounds and (not static)
                     compound clips, optional (1): how fast the source plays - clip time t
                     shows source time source_start_us + t * speed (source_time())
          freeze: {on, src_us}                              the same clips, optional: with on,
                     the source holds at source time src_us for the whole clip (凍結幀; a
                     frozen clip makes no sound)
          beat: {on, bpm, offset_us, div}                   sound clips, optional: BPM alignment
                     (節拍): with on, its beats, split into div (1, 2, 3, 4, 6) lines per
                     beat or thinned to one line every 2 / 4 beats (div 0.5 / 0.25: BPM
                     ÷2 / ÷4), are snap targets; offset_us is the first beat's time in the
                     source. Off keeps the numbers.
          compound_id                                       compound clips: which entry of
                     project.compounds they show; clip.source_start_us selects the window
          params: {param id: value}                         clips of a component (元件), optional:
                     their own values of its parameters (absent: the component's), animated
                     like any parameter}
          timeline_id                                       nested timeline clips (as in
                     DaVinci Resolve): they show another timeline of the project, live
          tracks, matte: {on, show}                         group clips (type "group", 群組):
                     clips of their own on tracks of their own (tracks[0] the bottom one), in
                     the same canvas space as the level they are on, their times counted
                     from the group's start (like a compound's, but not shared and not a
                     canvas of its own: moving the group moves them, keeping their places).
                     The group is drawn as one layer through its own transform, effects and
                     mask; with matte on, its bottom track's clips (matte_tracks) cut the clips above them
                     (their alpha), and show draws them too (else only their shape counts)
compound {name, width, height, duration_us, tracks}   reusable content: any number of compound
         clips (anywhere, nested too) show the same one, so editing it changes all of them.
         Its children use compound time. optional: static - a static compound (靜態片段)
         is like a picture: it only ever shows its content's first frame (time 0); its clips
         can be any length and make no sound. (Older projects kept a still_us; loading
         re-times their content so that moment is the first frame.) One named _thumbnail
         is the project's thumbnail (thumbnail_compound). optional (with static): component,
         params - a component (元件, components.py): its layers' words, colours, pictures and
         visibility are parameters that each clip showing it sets for itself (in its params).
Numbers that animate are curve dicts, see curves.py.

view     {vzoom, timelines: {timeline id: {pos, path, scroll_s, px_per_s, scroll_y, heights}}}
         optional: where the editor was looking when the project was saved (playhead frame,
         open compound clips, timeline scroll and zoom, track heights by track id). It is
         not part of the edit: undo leaves it alone.

In memory every compound clip also has "compound": the very dict in project.compounds (so
code can walk into it). On disk, and in undo snapshots, only compound_id is kept: dumps()
leaves the links out and link() puts them back.
"""
import json
import os

FORMAT = "kiasecut"
OLD_FORMATS = ("tesetoa",)        # the program's earlier name: those projects still open
VERSION = 4                     # 2: shared compounds; 3: several timelines; 4: project folder
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
    if p.get("format") != FORMAT and p.get("format") not in OLD_FORMATS:
        raise ValueError(f"{path} is not a KiaseCut project")
    p["format"] = FORMAT
    root = os.path.dirname(os.path.abspath(path))
    _map_paths(p, lambda s: to_abs(s, root))              # media paths are stored relative to the project folder
    return normalize(p)


def save(p, path):
    """Write the project. Media inside the project folder (the file's own folder) are stored
    with paths relative to it, so the whole folder can be moved or copied."""
    root = os.path.dirname(os.path.abspath(path))
    data = json.loads(dumps(p))                           # a private copy to rewrite
    _map_paths(data, lambda s: to_rel(s, root))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)          # never leave a half-written project behind


# -- media paths ------------------------------------------------------------------------------------
def _slash(s):
    return s.replace("\\", "/")


def is_abs(s):
    s = _slash(s)
    return s.startswith("/") or (len(s) > 2 and s[1] == ":" and s[0].isalpha() and s[2] == "/")


def _fold(s):
    return s.lower() if os.name == "nt" else s


LIBRARY_ROOT = None            # the user's Library folder (set by the program from its settings)
LIB_TAG = "@library/"


def to_rel(path, root):
    """path relative to root when it is inside it; "@library/…" when it is in the user's
    Library; else unchanged."""
    p, r = _slash(path), _slash(root).rstrip("/")
    if is_abs(p) and _fold(p).startswith(_fold(r) + "/"):
        return p[len(r) + 1:]
    if LIBRARY_ROOT and is_abs(p):
        lr = _slash(LIBRARY_ROOT).rstrip("/")
        if _fold(p).startswith(_fold(lr) + "/"):
            return LIB_TAG + p[len(lr) + 1:]
    return path


def to_abs(path, root):
    if not path:
        return path
    if path.startswith(LIB_TAG):
        return _slash(LIBRARY_ROOT).rstrip("/") + "/" + path[len(LIB_TAG):] if LIBRARY_ROOT else path
    return path if is_abs(path) else _slash(root).rstrip("/") + "/" + _slash(path)


def _map_paths(data, fn):
    """Apply fn to every media path of a stored project: library items and clips (timelines
    and compounds)."""
    for it in data.get("library", {}).get("items", []):
        if it.get("path"):
            it["path"] = fn(it["path"])
    comps = data.get("compounds", {})
    holders = [tl["tracks"] for tl in data.get("timelines", [])]
    holders += [c["tracks"] for c in comps.values()]
    holders.append(data.get("tracks", []) if "timelines" not in data else [])
    for tracks in holders:
        for t in all_tracks(tracks):
            for c in t["clips"]:
                m = c.get("media")
                if m and m.get("path"):
                    m["path"] = fn(m["path"])
                mk = c.get("mask")
                if isinstance(mk, dict) and mk.get("image"):         # an image mask's picture
                    mk["image"] = fn(mk["image"])
                for e in c.get("effects") or []:              # filter files (the built-in ones are not paths)
                    if e.get("filter") and not e["filter"].startswith("builtin:"):
                        e["filter"] = fn(e["filter"])
                own = c.get("params") or {}                    # a component clip's own pictures
                for p in (comps.get(c.get("compound_id")) or {}).get("params") or []:
                    v = own.get(p["id"])
                    if p["kind"] != "image" or not v:
                        continue
                    if isinstance(v, dict):
                        for k in v.get("keys") or []:
                            if k[1]:
                                k[1] = fn(k[1])
                    else:
                        own[p["id"]] = fn(v)


def end_us(tracks):
    return max((c["start_us"] + c["duration_us"] for t in tracks for c in t["clips"]), default=0)


def refresh_duration(p):
    p["duration_us"] = end_us(p["tracks"])
    for tl in p.get("timelines", []):                    # (for clips that show a timeline)
        tl["duration_us"] = end_us(tl["tracks"])


def is_group(c):
    return c.get("type") == "group"


def matte_tracks(tracks):
    """A group's picture tracks that have clips, the bottom one first: with its matte on, the
    first is the mask object's (a track left empty under it, as grouping the mask object's
    clips leaves one, does not count)."""
    return [t for t in tracks if t["kind"] != "audio" and t["clips"]]


def walk_clips(tracks):
    """Yield every clip, descending into compound clips and groups."""
    for t in tracks:
        for c in t["clips"]:
            yield c
            if c.get("compound"):
                yield from walk_clips(c["compound"]["tracks"])
            elif is_group(c):
                yield from walk_clips(c["tracks"])


def all_tracks(tracks):
    """The tracks and, inside groups, theirs (each group's after the track holding it)."""
    for t in tracks:
        yield t
        for c in t["clips"]:
            if is_group(c):
                yield from all_tracks(c["tracks"])


def sounds(track, tracks):
    """Gain of a track's sound (0 when muted, or when another track of its level is solo)."""
    if track.get("muted"):
        return 0.0
    if any(t.get("solo") for t in tracks) and not track.get("solo"):
        return 0.0
    return float(track.get("gain", 1.0))


def speed(c):
    """How fast a clip's source plays (1: as recorded)."""
    try:
        v = float(c.get("speed", 1.0))
    except (TypeError, ValueError):
        return 1.0
    return v if v > 0 else 1.0


def frozen(c):
    """The source time a frozen clip holds at (凍結幀), or None."""
    f = c.get("freeze")
    return float(f.get("src_us", c.get("source_start_us", 0))) if f and f.get("on") else None


def source_time(c, t):
    """The source time a clip shows at clip time t: with its speed, held when frozen."""
    f = frozen(c)
    return f if f is not None else c.get("source_start_us", 0) + t * speed(c)


TIME_FILTER = "builtin:frame_rate"      # 降低幀數: a clip's time steps at its fps (no picture change)


def stepped(c, t):
    """Clip time t held to the frame grid of the clip's 降低幀數 effect (the first one that is
    on), else t: the content, keyframes and effects all move in its steps."""
    for e in c.get("effects") or ():
        if e.get("filter") == TIME_FILTER and not e.get("disabled"):
            from . import curves
            rate = curves.value((e.get("params") or {}).get("fps", 12.0), t)
            if rate > 0:
                step = 1_000_000 / rate
                return int(t // step * step)
    return t


def backdrop_of(c):
    """(on, hide body) of a clip's 套用至背景: off without effects that draw; a clip that is
    not a built-in asset always hides its body."""
    b = c.get("backdrop") or {}
    if not b.get("on") or not visual_effects(c):
        return False, False
    return True, bool(b.get("hide")) or not c.get("asset")


def visual_effects(c):
    """The effects that change a clip's picture: on, and not a time effect (stepped())."""
    return [e for e in c.get("effects") or () if not e.get("disabled") and e.get("filter") != TIME_FILTER]


def active_mask(c):
    """The clip's mask if it is switched on, else None."""
    m = c.get("mask")
    return m if m and m.get("enabled", True) else None


def picture_size(c, W, H, k=1.0, t=0):
    """On-canvas size at scale 1 of an image or video clip on a W x H level: fitted into it,
    as Jianying does. A built-in asset (clip["asset"]) has its own size in canvas pixels, at
    clip time t (it can have keyframes); k converts those to the units W and H are in."""
    m = c["media"]
    if c.get("asset"):
        from . import assets
        w, h = assets.size_at(c["asset"], t)
        return w * k, h * k
    fit = min(W / m["width"], H / m["height"])
    return m["width"] * fit, m["height"] * fit


def visible(track):
    return not track.get("hidden")


def locked(track):
    """A locked track (鎖定): its clips cannot be selected, on the timeline or the preview, and
    nothing is moved or dropped onto it; it still plays and shows."""
    return bool(track.get("locked"))


# -- shared compounds -------------------------------------------------------------------------------
def _tracks_out(tracks):
    """Tracks with compound clips reduced to their compound_id (shallow copies)."""
    out = []
    for t in tracks:
        clips = []
        for c in t["clips"]:
            if ("compound_id" in c or "timeline_id" in c) and "compound" in c:
                c = {k: v for k, v in c.items() if k != "compound"}
            elif is_group(c):
                c = dict(c, tracks=_tracks_out(c["tracks"]))
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

    by_id = {tl["id"]: tl for tl in tls}
    for tl in tls:                                       # a timeline shown by a clip is content
        tl["width"], tl["height"] = p.get("width", 1920), p.get("height", 1080)
        tl["duration_us"] = end_us(tl["tracks"])

    def visit(tracks):
        for t in tracks:
            for c in t["clips"]:
                if "compound_id" in c:
                    c["compound"] = comps[c["compound_id"]]
                elif "timeline_id" in c:
                    c["compound"] = by_id[c["timeline_id"]]
                elif is_group(c):
                    visit(c["tracks"])
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
        for t in all_tracks(tl["tracks"]):
            yield from t["clips"]
    for comp in p.get("compounds", {}).values():
        for t in all_tracks(comp["tracks"]):
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
                if is_group(c):
                    visit(c["tracks"])
                    continue
                if c.get("type") != "compound" or "compound_id" in c or "timeline_id" in c:
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
    for comp in comps.values():                            # static compounds once froze at still_us:
        still = comp.pop("still_us", 0)                    # that moment becomes their first frame
        if comp.get("static") and still:
            from .edit import freeze_at
            freeze_at(comp["tracks"], still)
    from . import assets
    for c in all_clips(p):                                 # built-in assets of older versions
        if c.get("asset") and "outline" in c["asset"]:
            c["asset"] = assets.normalize(c["asset"])
    p["version"] = VERSION
    return link(p)


THUMBNAIL = "_thumbnail"         # a static compound of this name is the project's thumbnail


def thumbnail_compound(p):
    """The compound named _thumbnail when it is static (only a static one counts), else None."""
    return next((c for c in p.get("compounds", {}).values()
                 if c.get("name") == THUMBNAIL and c.get("static")), None)


def is_static(c):
    """Whether clip c shows a static compound (靜態片段): its first frame, used like a picture."""
    return c.get("type") == "compound" and bool((c.get("compound") or {}).get("static"))


def ref_of(c):
    """The compound id or timeline id a clip shows, or None."""
    return c.get("compound_id") or c.get("timeline_id")


def content(p, ref):
    """The compound or timeline with id ref (compounds are k…, timelines tl…)."""
    return p["compounds"][ref] if ref in p.get("compounds", {}) else timeline(p, ref)


def compound_uses(p):
    """{compound or timeline id: [(timeline id, parent path (clip ids), clip)]} for every
    clip showing one, on every timeline, nested ones reached through every clip that shows
    their parent."""
    uses = {k: [] for k in p.get("compounds", {})}
    uses.update({t["id"]: [] for t in p.get("timelines", [])})

    def visit(tl, tracks, path):
        for t in all_tracks(tracks):
            for c in t["clips"]:
                if ref_of(c):
                    uses.setdefault(ref_of(c), []).append((tl, list(path), c))
                    if len(path) < 16:                    # (a loop cannot be made, but stay safe)
                        visit(tl, c["compound"]["tracks"], path + [c["id"]])
    for tl in p.get("timelines") or [{"id": None, "tracks": p["tracks"]}]:
        visit(tl["id"], tl["tracks"], [])
    return uses


def contains(p, outer_id, inner_id):
    """Whether compound / timeline outer_id shows inner_id (at any depth), or is it."""
    if outer_id == inner_id:
        return True
    stack, seen = [outer_id], set()
    while stack:
        k = stack.pop()
        if k in seen:
            continue
        seen.add(k)
        for t in all_tracks(content(p, k)["tracks"]):
            for c in t["clips"]:
                if ref_of(c):
                    if ref_of(c) == inner_id:
                        return True
                    stack.append(ref_of(c))
    return False
