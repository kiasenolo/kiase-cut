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
          muted, solo, hidden, locked, gain, reference}     optional: muted / solo tracks
                     make no sound (solo silences the others), hidden ones draw nothing,
                     locked ones cannot have their clips picked (locked()), gain
                     multiplies the track's sound; a reference (參考) track shows and sounds
                     only while its level is edited, in the editor's preview - not in an
                     export, nor where its timeline or compound is used (level_tracks())
clip     {id, type: image | video | audio | text | compound, name,
          start_us, duration_us, source_start_us,
          media: {path, width, height, duration_us}         image / video / audio
          transform: {x, y, scale, rotation, opacity}       visual clips, Jianying units:
                     x, y in half-canvas units (y up), clockwise degrees; scale is the
                     X scale, optional scale_y the Y one (absent: same as X), optional
                     scale_link (default true): X and Y change together, keeping their ratio;
                     optional pivot_x, pivot_y (中心點, animated like the rest): the point it
                     turns and scales about, in its own frame (half-canvas units from its
                     centre, y up, unscaled: it moves, turns and scales with it). x / y still
                     place its centre while it is not turned or scaled (pivot_shift); optional anchor_x,
                     anchor_y (錨點, the same units and frame): the point of the clip that x / y
                     place - moving the anchor moves the clip the other way, not x / y
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
                path), img_w / img_h (its size, for its proportions); kind "video" with a
                video file playing: video (its path), vid_w / vid_h, vid_dur (us), t_off as a
                compound's (its time at the clip's start)
          text: {content, font_path, size, color, fill, stroke_on, stroke_color, stroke, stroke_align,
                 letter_spacing, line_spacing, italic_deg, styles, align, valign, box_w, box_h}
                                                                  text clips; fill defaults on,
                 stroke_on defaults off, stroke is the outline width in 1080-high canvas px;
                 stroke_align: inside | center | outside, defaults inside;
                box_w / box_h: the 文字框 (textlayout.py; absent or 0: as big as the words)
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
          fx_through                                        compound clips, optional: 效果穿透 -
                     the 套用至背景 clips and filter clips inside also work on what is under
                     the clip, inside its frame (passes_through())
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
                     (their alpha), and show draws them too (else only their shape counts);
                     anchor (中心點跟隨最下層物件): the clips above the bottom track's are placed
                     from the bottom object's centre (anchor_of), so it carries them along
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
import copy
import json
import math
import os

from kiasecut import curves

FORMAT = "kiasecut"
OLD_FORMATS = ("tesetoa",)        # the program's earlier name: those projects still open
VERSION = 5                     # 2: shared compounds; 3: several timelines; 4: project folder; 5: Glare 光源位置 y up
DEFAULT_FONT = next((f for f in (r"C:\Windows\Fonts\msjh.ttc",
                                 "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
                                 "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                                 "/system/fonts/NotoSansCJK-Regular.ttc")                 # (Android)
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
    return _slash(path) if is_abs(path) else _slash(root).rstrip("/") + "/" + _slash(path)


def _map_sources(sources, fn):
    for src in (sources or {}).values():
        for k in ("image", "video"):
            if src.get(k):
                src[k] = fn(src[k])


def _map_paths(data, fn):
    """Apply fn to every media path of a stored project: library items and clips (timelines
    and compounds)."""
    for it in data.get("library", {}).get("items", []):
        if it.get("path"):
            it["path"] = fn(it["path"])
    for m in (data.get("vfx_nodes") or {}).values():          # a shared VFX Node's pictures and videos (its effects keep none of their own)
        _map_sources(m.get("sources"), fn)
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
                for k in ("image", "video"):                         # an image / video mask's file
                    if isinstance(mk, dict) and mk.get(k):
                        mk[k] = fn(mk[k])
                for e in c.get("effects") or []:              # filter files (the built-in ones are not paths)
                    if e.get("filter") and not e["filter"].startswith("builtin:") and e["filter"] != GRAPH_FILTER:
                        e["filter"] = fn(e["filter"])
                    _map_sources(e.get("sources"), fn)             # its colours' pictures and videos
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


def anchor_of(g, t_us):
    """中心點跟隨最下層物件: (bottom track, x, y) of group g at group time t_us - its bottom
    object's centre (the bottom track's clip then, else the nearest one), which the clips on
    the tracks above it count their x / y from - or None (off, or nothing above it)."""
    if not g.get("anchor"):
        return None
    tracks = matte_tracks(g["tracks"])
    if len(tracks) < 2:
        return None
    c = min(tracks[0]["clips"], key=lambda k: max(k["start_us"] - t_us, t_us - (k["start_us"] + k["duration_us"]), 0))
    tf = c.get("transform") or {}
    t = stepped(c, min(max(t_us - c["start_us"], 0), c["duration_us"]))
    return tracks[0], curves.value(tf.get("x", 0.0), t), curves.value(tf.get("y", 0.0), t)


def anchored(g, track, t_us):
    """(x, y) a clip on group g's track `track` is moved by at group time t_us (anchor_of:
    on a track above the bottom object's), else (0, 0)."""
    a = anchor_of(g, t_us)
    if a is None or not any(t is a[0] for t in g["tracks"]) or not any(t is track for t in g["tracks"]):
        return 0.0, 0.0
    ids = [id(t) for t in g["tracks"]]
    return (a[1], a[2]) if ids.index(id(track)) > ids.index(id(a[0])) else (0.0, 0.0)


def pivot_shift(tf, t, W, H, scale=None, scale_y=None, rotation=None):
    """錨點 and 中心點: (dx, dy) canvas px (y down) that placing the anchor (not the centre) at
    x / y, and turning and scaling about the pivot instead of
    the centre moves a W x H canvas clip's centre by, at clip time t (scale, scale_y, rotation:
    other values than tf's, for a drag); (0, 0) without either. The renderers draw a clip at
    centre_px, which adds this to where x / y put it."""
    px, py = curves.value(tf.get("pivot_x", 0.0), t), curves.value(tf.get("pivot_y", 0.0), t)
    ax, ay = curves.value(tf.get("anchor_x", 0.0), t), curves.value(tf.get("anchor_y", 0.0), t)
    gx, gy = -ax * W / 2, ay * H / 2                    # (錨點: x / y place the anchor, so the clip is moved off it)
    if not px and not py:
        return gx, gy
    sx = curves.value(tf.get("scale", 1.0), t) if scale is None else scale
    sy = (curves.value(tf.get("scale_y", tf.get("scale", 1.0)), t) if scale is None else scale) \
        if scale_y is None else scale_y
    deg = curves.value(tf.get("rotation", 0.0), t) if rotation is None else rotation
    lx, ly = px * W / 2, -py * H / 2                    # the pivot in the clip's frame (y down)
    qx = lx * sx * (-1 if tf.get("flip_h") else 1)
    qy = ly * sy * (-1 if tf.get("flip_v") else 1)
    b = math.radians(deg)                               # (clockwise on a y-down canvas)
    return gx + lx - (qx * math.cos(b) - qy * math.sin(b)), gy + ly - (qx * math.sin(b) + qy * math.cos(b))


def centre_px(tf, t, W, H):
    """Where a clip's centre is drawn on a W x H canvas at clip time t (canvas px, y down):
    x / y, moved by turning and scaling about its pivot (pivot_shift)."""
    dx, dy = pivot_shift(tf, t, W, H)
    return (W / 2 + curves.value(tf.get("x", 0.0), t) * W / 2 + dx,
            H / 2 - curves.value(tf.get("y", 0.0), t) * H / 2 + dy)


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


def level_tracks(view):
    """The tracks (their ids) whose 參考 (reference) setting does not leave them out: in the
    editor's preview (view["editing"]) the open level's and its groups'; none in an export,
    and never the tracks inside the compounds and timelines used on the level."""
    return {id(t) for t in all_tracks(view["tracks"])} if view.get("editing") else frozenset()


def present(track, level=()):
    """Whether a track is part of the picture and the sound at all: a 參考 track only on the
    level being edited (level: level_tracks())."""
    return not track.get("reference") or id(track) in level


def sounds(track, tracks, level=()):
    """Gain of a track's sound (0 when muted, when another track of its level is solo, or a
    參考 track out of level)."""
    if track.get("muted") or not present(track, level):
        return 0.0
    if any(t.get("solo") and present(t, level) for t in tracks) and not track.get("solo"):
        return 0.0
    return float(track.get("gain", 1.0))


def speed(c):
    """How fast a clip's source plays (1: as recorded)."""
    try:
        v = float(c.get("speed", 1.0))
    except (TypeError, ValueError):
        return 1.0
    return v if v > 0 else 1.0


CORNERS = ("radius_tl", "radius_tr", "radius_br", "radius_bl")    # 圓角 (in transform), clockwise from top left


def corner_radii(c, t, disp, H):
    """(top left, top right, bottom right, bottom left) 圓角 of picture clip c at clip time t, in
    the units of disp (its frame's (w, h) in canvas px; H the canvas height: the radii are px of a
    1080-high canvas at scale 1, so they grow with the clip), scaled down together where two of a
    side would overlap (as CSS does); None: square corners."""
    if c["type"] not in ("image", "video", "compound") or c.get("asset"):
        return None
    tf = c.get("transform") or {}
    r = [max(0.0, curves.value(tf.get(k, 0.0), t)) * H / 1080 for k in CORNERS]
    if not any(v > 0 for v in r):
        return None
    w, h = disp
    sides = ((w, r[0] + r[1]), (w, r[3] + r[2]), (h, r[0] + r[3]), (h, r[1] + r[2]))
    f = min([1.0] + [side / s for side, s in sides if s > 0])
    return tuple(v * f for v in r)


def has_corners(c):
    tf = c.get("transform") or {}
    return c["type"] in ("image", "video", "compound") and not c.get("asset") \
        and any(curves.is_animated(tf.get(k)) or (tf.get(k) or 0) > 0 for k in CORNERS)


def frozen(c):
    """The source time a frozen clip holds at (凍結幀), or None."""
    f = c.get("freeze")
    return float(f.get("src_us", c.get("source_start_us", 0))) if f and f.get("on") else None


def source_time(c, t):
    """The source time a clip shows at clip time t: with its speed (or its 曲線變速), held when frozen."""
    f = frozen(c)
    if f is not None:
        return f
    sc = c.get("speed_curve")
    if sc:
        dur = max(c["duration_us"], 1)
        return c.get("source_start_us", 0) + curve_progress(sc["points"], t / dur) * dur * curve_mean(sc["points"])
    return c.get("source_start_us", 0) + t * speed(c)


# 曲線變速: speed_curve {points: [[u, speed]]}: u the place in the clip (0 - 1, the first point at
# 0 and the last at 1), speed 0.1 - 10 there; between two points the speed eases from one to the
# other (smoothly, in log scale, as 剪映's curves look). The clip plays its length times the
# curve's mean speed of its source, and "speed" holds that mean (what the rest of the program
# takes as its speed: trimming, the sound's range); trimmed, the curve keeps its shape.
CURVE_SAMPLES = 512
CURVE_MIN, CURVE_MAX = 0.1, 10.0


def curve_speed_at(points, u):
    """The speed of a 曲線變速 at u (0 - 1)."""
    u = min(1.0, max(0.0, u))
    for (u0, s0), (u1, s1) in zip(points, points[1:]):
        if u <= u1:
            k = 0.0 if u1 <= u0 else (u - u0) / (u1 - u0)
            k = k * k * (3 - 2 * k)
            return math.exp(math.log(s0) + (math.log(s1) - math.log(s0)) * k)
    return points[-1][1]


_cum = {}


def curve_table(points):
    """(u samples, the share of the source played by each: 0 - 1) of a 曲線變速, and its mean speed."""
    key = tuple(map(tuple, points))
    hit = _cum.get(key)
    if hit is None:
        import numpy as np
        u = np.linspace(0.0, 1.0, CURVE_SAMPLES + 1)
        s = np.array([curve_speed_at(points, x) for x in u])
        cum = np.concatenate([[0.0], np.cumsum((s[1:] + s[:-1]) / 2) / CURVE_SAMPLES])
        mean = float(cum[-1])
        hit = (u, cum / mean, mean)
        if len(_cum) > 64:
            _cum.clear()
        _cum[key] = hit
    return hit


def curve_progress(points, u):
    """How much of its source a 曲線變速 clip has played at u (0 - 1) of its length."""
    import numpy as np
    us, share, _mean = curve_table(points)
    return float(np.interp(u, us, share))


def curve_mean(points):
    return curve_table(points)[2]


def curve_source_offsets(c, ts):
    """For a 曲線變速 clip: how far into the part of its source it plays (us) at clip times ts
    (a numpy array) - its sound's samples, all at once."""
    import numpy as np
    pts = c["speed_curve"]["points"]
    us, share, mean = curve_table(pts)
    dur = max(c["duration_us"], 1)
    return np.interp(np.asarray(ts, float) / dur, us, share) * dur * mean


TIME_FILTER = "builtin:frame_rate"      # 降低幀數: a clip's time steps at its fps (no picture change)
GRAPH_FILTER = "nodes:graph"       # a node effect (fx.GRAPH): not a file, whatever its name looks like
FREEZE_FILTER = "builtin:freeze"        # 凍結: a clip's time held where its effects begin (its start)
TIME_FILTERS = (TIME_FILTER, FREEZE_FILTER)
MOTION_BLUR_FILTER = "builtin:transform_motion_blur"   # 動態模糊: the clip drawn over the shutter (shutter_times)
PLACE_FILTERS = TIME_FILTERS + (MOTION_BLUR_FILTER,)   # effects the program does itself, not on the picture


def stepped(c, t):
    """Clip time t held to the frame grid of the clip's 降低幀數 effect (the first one that is
    on), or at 0 by 凍結, else t: the content, keyframes and effects all move in its steps.
    On a filter clip it is the time the tracks under it are drawn at (render.draw_filter_clip)."""
    for e in c.get("effects") or ():
        if e.get("filter") == FREEZE_FILTER and not e.get("disabled"):
            return 0
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


def backdrop_inside(comp):
    """Whether compound content comp has clips that work on what is under them: 套用至背景
    ones and filter clips, on its shown picture tracks, in its 穿透 groups (their clips draw
    straight on it) and in compound clips that pass theirs through (passes_through)."""
    for tr in (comp or {}).get("tracks") or ():
        if tr["kind"] == "audio" or not visible(tr):
            continue
        for c in tr["clips"]:
            if (visual_effects(c) if c["type"] == "filter" else backdrop_of(c)[0]) or passes_through(c):
                return True
            blend = c.get("blend")
            if is_group(c) and (blend == "pass_through" or curves.is_animated(blend)) and backdrop_inside(c):
                return True
    return False


def passes_through(c):
    """效果穿透: whether compound clip c lets the clips inside that work on what is under them
    (backdrop_inside) see what is under c as well - switched on, and it has some."""
    return c.get("type") == "compound" and bool(c.get("fx_through")) and backdrop_inside(c.get("compound"))


def visual_effects(c):
    """The effects that change a clip's picture: on, and not a time effect (stepped()) or 動態模糊."""
    return [e for e in c.get("effects") or () if not e.get("disabled") and e.get("filter") not in PLACE_FILTERS]


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
    if c.get("viz"):                                    # an Audio Visualizer has a size of its own, as a shape
        return float(c["viz"].get("w", m["width"])) * k, float(c["viz"].get("h", m["height"])) * k
    fit = min(W / m["width"], H / m["height"])
    return m["width"] * fit, m["height"] * fit


def visible(track, level=()):
    """Whether a track's pictures draw: not hidden, nor a 參考 track out of level (present())."""
    return not track.get("hidden") and present(track, level)


def locked(track):
    """A locked track (鎖定): its clips cannot be selected, on the timeline or the preview, and
    nothing is moved or dropped onto it; it still plays and shows."""
    return bool(track.get("locked"))


# -- shared compounds -------------------------------------------------------------------------------
def _tracks_out(tracks):
    """Tracks with compound clips reduced to their compound_id, and the effects that use a VFX Node to its id (shallow copies)."""
    out = []
    for t in tracks:
        clips = []
        for c in t["clips"]:
            if ("compound_id" in c or "timeline_id" in c) and "compound" in c:
                c = {k: v for k, v in c.items() if k != "compound"}
            elif is_group(c):
                c = dict(c, tracks=_tracks_out(c["tracks"]))
            if any(e.get("vfx") for e in c.get("effects") or ()):
                c = dict(c, effects=[{k: v for k, v in e.items() if k not in ("graph", "sources")} if e.get("vfx") else e
                                     for e in c["effects"]])
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


def legacy_text_padding(tx):
    """A text saved with one background padding (bg_pad) gets it on each of the four sides (bg_pad_l / r / t / b)."""
    if tx and "bg_pad" in tx and not any(f"bg_pad_{k}" in tx for k in "lrtb"):
        for k in "lrtb":
            tx[f"bg_pad_{k}"] = copy.deepcopy(tx["bg_pad"])


def _share_vfx(p, e):
    """Effect e uses a VFX Node: its graph and sources are the node's own (one object, so editing it in one clip edits every
    use), and the parameters the node has gained since get their defaults. A node the project lacks (an effect pasted
    from another project) is made from the effect."""
    nodes = p.setdefault("vfx_nodes", {})
    m = nodes.get(e["vfx"])
    if m is None:
        if not e.get("graph"):
            e.pop("vfx")
            return
        m = nodes[e["vfx"]] = {"id": e["vfx"], "name": "VFX Node", "graph": e["graph"], "sources": e.get("sources") or {}}
    e["graph"], e["sources"] = m["graph"], m.setdefault("sources", {})
    from . import nodegraph
    for k, v in nodegraph.default_params(e["graph"]).items():
        if k not in e["params"]:
            e["params"][k] = copy.deepcopy(v)


EXPOSE_PREFIX = "expose."                           # (nodegraph.expose_key)


def sync_vfx(p, touched=()):
    """After an edit: the effects of VFX Nodes it went through (touched) hand their graph and sources to the node, and what the
    nodes inside were set to (a Math's operation, its numbers: not the values of the effect's own parameters, which each use
    keeps) to the node's start values and to every other use - the graph is one, so are its settings; then every use points at
    the node's graph again (an edit may have replaced the graph object)."""
    nodes = p.get("vfx_nodes")
    if not nodes:
        return
    changed = {}
    for e in touched:
        m = nodes.get(e.get("vfx"))
        if m is not None and e.get("graph") is not None:
            m["graph"], m["sources"] = e["graph"], e.get("sources") if e.get("sources") is not None else m.get("sources", {})
            start = m.setdefault("params", {})
            for k, v in (e.get("params") or {}).items():
                if not k.startswith(EXPOSE_PREFIX) and start.get(k) != v:
                    start[k] = copy.deepcopy(v)
                    changed.setdefault(e["vfx"], {})[k] = v
    for c in all_clips(p):
        for e in c.get("effects") or ():
            if e.get("vfx"):
                for k, v in changed.get(e["vfx"], {}).items():
                    if e["params"].get(k) != v:
                        e["params"][k] = copy.deepcopy(v)
                _share_vfx(p, e)


def inline_vfx(comps, p):
    """Stored compounds (the form dumps gives) with the VFX Nodes their effects use written into them, the effects on their
    own: a compound kept for another project cannot count on this project's nodes."""
    nodes = p.get("vfx_nodes") or {}

    def visit(tracks):
        for t in tracks:
            for c in t["clips"]:
                for e in c.get("effects") or ():
                    m = nodes.get(e.get("vfx"))
                    if m is not None:
                        e["graph"], e["sources"] = copy.deepcopy(m["graph"]), copy.deepcopy(m.get("sources") or {})
                    e.pop("vfx", None)
                if is_group(c):
                    visit(c["tracks"])
    for comp in comps.values():
        visit(comp["tracks"])
    return comps


def vfx_uses(p):
    """{VFX Node id: [(clip, effect)]} of every use, in every timeline and compound."""
    out = {vid: [] for vid in p.get("vfx_nodes") or {}}
    for c in all_clips(p):
        for e in c.get("effects") or ():
            if e.get("vfx") in out:
                out[e["vfx"]].append((c, e))
    return out


def new_vfx_id(p):
    ids = set(p.get("vfx_nodes") or ())
    n = len(ids) + 1
    while f"vn{n}" in ids:
        n += 1
    return f"vn{n}"


def link(p):
    """Point every compound clip at its shared entry and p.tracks at the open timeline (after
    loading or restoring a snapshot)."""
    comps = p.setdefault("compounds", {})
    p.setdefault("vfx_nodes", {})
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
                legacy_text_padding(c.get("text"))
                if c.get("viz"):
                    from . import viz
                    viz.migrate(c)
                for e in c.get("effects") or []:
                    if e.get("vfx"):
                        _share_vfx(p, e)
                    if e.get("graph"):
                        from . import nodegraph
                        nodegraph.migrate(e["graph"])
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
        if "motion_blur" in c:                             # 動態模糊 was a clip setting: now an effect
            from .edit import new_effect_id
            mb = c.pop("motion_blur") or {}
            c.setdefault("effects", []).insert(0, {
                "id": new_effect_id(), "filter": MOTION_BLUR_FILTER, "enabled": True,
                "params": {"shutter": float(mb.get("shutter", 180.0)), "samples": int(mb.get("samples", 8))}})
    if p.get("version", VERSION) < 5:                      # Glare's 光源位置 counted y down: now up, as Blender's
        for c in all_clips(p):
            for e in c.get("effects") or []:
                _flip_sun(e)
    p["version"] = VERSION
    return link(p)


def _flip_y(v):
    """A parameter value of the height of a point (a number, or keys) seen from the other end: 1 - v."""
    if isinstance(v, dict) and v.get("keys"):
        keys = [[k[0], 1.0 - k[1]] + ([k[2], -k[3], k[4], -k[5]] if len(k) >= 6 else list(k[2:])) for k in v["keys"]]
        return dict(v, keys=keys)
    return 1.0 - v if isinstance(v, (int, float)) and not isinstance(v, bool) else v


def _flip_sun(e):
    """Turn the 光源位置 of the Blender Glare effects in effect e (the effect itself, or the nodes of its graph) upside down."""
    params = e.get("params") or {}
    keys = []
    if e.get("filter") == "builtin:blender_glare":
        keys.append("sun_position")
    if e.get("graph"):
        from . import nodegraph
        graph = nodegraph.flatten(e["graph"])
        bound = nodegraph.binds(graph)
        for nid, node in graph["nodes"].items():
            if node.get("type") == nodegraph.FILTER and node.get("ref") == "builtin:blender_glare":
                b = bound.get((nid, nodegraph.PARAM + "sun_position"))
                keys.append(nodegraph.expose_key(b) if b else nodegraph.param_key(nid, "sun_position"))
    for k in keys:
        v = params.get(k)
        if isinstance(v, (list, tuple)) and len(v) >= 2:
            params[k] = [v[0], _flip_y(v[1])] + list(v[2:])


THUMBNAIL = "_thumbnail"         # a static compound of this name is the project's thumbnail


def thumbnail_compound(p):
    """The compound named _thumbnail when it is static (only a static one counts), else None."""
    return next((c for c in p.get("compounds", {}).values()
                 if c.get("name") == THUMBNAIL and c.get("static")), None)


def is_static(c):
    """Whether clip c shows a static compound (靜態片段): its first frame, used like a picture."""
    return c.get("type") == "compound" and bool((c.get("compound") or {}).get("static"))


def shutter_times(c, t_us, fps):
    """動態模糊 (the clip's first 動態模糊 effect that is on: params shutter in degrees, samples):
    the times (us, on the clip's timeline) clip c is drawn at and averaged - the samples spread
    over the shutter (180°: half a frame) round t_us, as After Effects does, kept inside the clip -
    or None when it has none or works on what is under it (套用至背景, 效果穿透). The whole clip is
    drawn each time, so everything that moves in it smears: its place, its keyframes and
    expressions, a text's or a shape's animation, the clips in a compound, a video's frames."""
    mb = next((e.get("params") or {} for e in c.get("effects") or ()
               if e.get("filter") == MOTION_BLUR_FILTER and not e.get("disabled")), None)
    if mb is None or c.get("type") in ("filter", "audio") or backdrop_of(c)[0] or passes_through(c):
        return None
    t = t_us - c["start_us"]
    n = max(2, min(64, int(round(curves.value(mb.get("samples", 16), t)))))
    span = max(0.0, min(720.0, float(curves.value(mb.get("shutter", 180.0), t)))) / 360 * 1_000_000 / max(fps, 1e-6)
    if span <= 0:
        return None
    lo, hi = c["start_us"], c["start_us"] + max(0, c["duration_us"] - 1)
    return [min(hi, max(lo, t_us + ((i + 0.5) / n - 0.5) * span)) for i in range(n)]


def compound_holders(c):
    """The dicts of clip c that name a compound by its "compound_id": the clip itself (a
    compound clip), its compound mask, its effects' compound sources."""
    out = [c] if c.get("compound_id") else []
    if (c.get("mask") or {}).get("compound_id"):
        out.append(c["mask"])
    for e in c.get("effects") or []:
        out += [s for s in (e.get("sources") or {}).values() if isinstance(s, dict) and s.get("compound_id")]
    return out


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


def holders_of(p, inner_id):
    """The ids of every compound and timeline that contains() inner_id (itself too), found in one pass over the project
    (contains() of each compound walks what it shows again for every one asked about)."""
    shown_in = {}                                          # id -> the ids of what shows it
    for tl in p.get("timelines", []):
        for t in all_tracks(tl["tracks"]):
            for c in t["clips"]:
                if ref_of(c):
                    shown_in.setdefault(ref_of(c), set()).add(tl["id"])
    for kid, comp in p.get("compounds", {}).items():
        for t in all_tracks(comp["tracks"]):
            for c in t["clips"]:
                if ref_of(c):
                    shown_in.setdefault(ref_of(c), set()).add(kid)
    out, stack = set(), [inner_id]
    while stack:
        k = stack.pop()
        if k not in out:
            out.add(k)
            stack.extend(shown_in.get(k, ()))
    return out


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
