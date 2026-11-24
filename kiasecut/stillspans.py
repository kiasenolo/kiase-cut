"""Still spans (靜態區段): the stretches of a level where nothing on it changes with time, so every frame there is the same
picture. The RAM preview (framecache.py) draws one frame of such a stretch and shows it for all of them: the whole
stretch is kept (green) at once.

Worked out from the project, never from the pictures, and on the safe side: a clip counts as still only when nothing in
it can read the time. It moves when it is (or holds) any of these:
    a video; an Audio Visualizer (viz); keyframes anywhere in it (a value {"keys": [...]}: its place, an effect's
    parameter, a mask, a text variable, a shape's numbers); an LFO (a value with "wave"); a 映射 to the rack (a value with
    "mode"); an expression of its own (clip["expr"]); an effect whose filter reads time / progress / frame (or cannot be
    read); a node effect with such a node, or with a picture source other than a picture, shape, text or vector; a mask
    of a video or of a compound that is not a still one; a compound or group whose content moves in the part it shows
    (a static compound is one still picture unless an LFO swings it).
A stretch is still where every clip that shows there is still there; where nothing shows it is still too. Anything not
known to be still counts as moving: a frame wrongly kept would show the wrong picture, a frame drawn again only costs time.
"""
import bisect
import math
import re

from . import components, curves, fx, project

US = 1_000_000
INF = float("inf")
COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_READS_TIME = r"\b(time|progress|frame)\b"


def _time_words():
    """The names a filter reads the time through: the uniforms, and the functions of the shader's prelude (fx.PRELUDE) that
    read them (frame_phase ...)."""
    names = {"time", "progress", "frame"}
    body = COMMENTS.sub("", fx.PRELUDE)
    for m in re.finditer(r"\b\w+\s+(\w+)\s*\([^)]*\)\s*\{(.*?)\n?\}", body, re.S):
        if re.search(_READS_TIME, m.group(2)):
            names.add(m.group(1))
    return re.compile(r"\b(" + "|".join(sorted(names)) + r")\b")


TIME_WORDS = _time_words()
STILL_SOURCES = ("image", "shape", "text", "vector")
LINKED = ("compound", "tracks", "matte", "graph", "sources")     # (in memory, shared objects a clip or effect points at: looked at on their own)


def _moves(x):
    """Whether a stored value holds keyframes, an LFO or a mapping anywhere in it."""
    if isinstance(x, dict):
        if curves.is_animated(x) or ("wave" in x and "rate" in x) or ("mode" in x and "src" in x):
            return True
        return any(_moves(v) for k, v in x.items() if k not in LINKED)
    if isinstance(x, list):
        return any(_moves(v) for v in x)
    return False


_filter_still = {}
_ctx = {"compounds": {}, "fps": 30.0}               # (the view frame_spans works on: the compounds a source or a mask names)
BIG = 1 << 50


def _whole_still(comp, live):
    """Whether a compound used as a picture (a source of an effect, a mask) is the same picture at every moment: a static
    one, not swung by an LFO, and when it is read at its own time (讀取時間) its layers all there from 0 and still."""
    if not comp or not comp.get("static") or components.swings(comp):
        return False
    if not live:
        return True
    try:
        ps = pieces(components._stretch(comp.get("tracks") or [], BIG), _ctx["fps"])
    except Exception:
        return False
    return len([q for q in ps if q[0] < BIG // 2]) == 1 and ps[0][2]


def _source_still(src):
    if not isinstance(src, dict) or _moves(src):
        return False
    kind = src.get("kind", "image")
    if kind == "compound":
        return _whole_still(_ctx["compounds"].get(src.get("compound_id")), src.get("static_live"))
    return kind in STILL_SOURCES


def _code_still(d, values=None):
    """Whether filter d draws the same at every moment: its code reads no time, or only while its @time conditions hold
    (每格不同 on ...) and with these values {name: value} they do not."""
    if d is None or d.error:
        return False
    key = (d.ref, d.code)
    got = _filter_still.get(key)
    if got is None:
        if len(_filter_still) > 512:
            _filter_still.clear()
        got = _filter_still[key] = not TIME_WORDS.search(COMMENTS.sub("", d.code))
    return got or (values is not None and bool(d.time_when) and not fx.reads_time(d, values))


def _values(d, params, prefix=""):
    return {p.name: params.get(prefix + p.name, p.default) for p in d.params}


def _effect_still(e):
    if e.get("disabled") or e.get("enabled") is False:
        return True
    if _moves({k: v for k, v in e.items() if k not in LINKED}):
        return False
    ref = e.get("filter")
    if ref == project.GRAPH_FILTER or e.get("graph") is not None:
        g = e.get("graph")
        if not g or _moves(g):
            return False
        from . import nodegraph as ng
        try:
            g = ng.flatten(g)                        # (the links through node groups go to their members, which are nodes of the graph)
        except Exception:
            return False
        bound = ng.binds(g)
        for nid, node in (g.get("nodes") or {}).items():
            t = node.get("type")
            if t == ng.FILTER:
                try:
                    d = fx.for_node(node)
                    own = {q.name: ng.bound_value(e.get("params") or {}, bound, nid, q.name, q.default) for q in d.params}
                    linked = {l.get("socket", "")[len(ng.PARAM):] for l in g.get("links") or ()
                              if l.get("to") == nid and str(l.get("socket", "")).startswith(ng.PARAM)
                              and (nid, l.get("socket")) not in bound}
                    if any(name in linked for conds in d.time_when for name, _n, _w in conds):
                        return False                 # (its switch fed by another node: whatever it gives)
                    if not _code_still(d, own):
                        return False
                except Exception:
                    return False
            elif t == ng.SOURCE:
                if node.get("kind") not in STILL_SOURCES + ("compound",):    # (a compound's: by its source, below)
                    return False
            elif t not in (ng.INPUT, ng.OUTPUT, ng.PARAMS, ng.REROUTE, ng.FRAME, ng.VIEWER, ng.FONT, ng.STRING, "groupin", "groupout"):
                return False                         # (a kind of node not known here: counted as moving)
        return all(_source_still(src) for src in (e.get("sources") or {}).values())
    if ref in project.PLACE_FILTERS:              # (降低幀數, 凍結, 動態模糊: only what moves changes under them)
        return True
    try:
        d = fx.get(ref)
        if not _code_still(d, _values(d, e.get("params") or {})):
            return False
    except Exception:
        return False
    return all(_source_still(src) for src in (e.get("sources") or {}).values())   # (a colour or number from a picture: 使用遮罩)


def _mask_still(m):
    if not m or m.get("enabled", True) is False:
        return True
    if _moves(m):
        return False
    kind = m.get("kind")
    if kind == "video":
        return False
    if kind == "compound":
        return _whole_still(_ctx["compounds"].get(m.get("compound_id")), m.get("static_live"))
    return True                                      # (a shape, a path, a picture; 軌道: its clips are on the level and count there)


def _compound_still(comp):
    """A static compound is one picture: still unless an LFO swings it."""
    return bool(comp.get("static")) and not components.swings(comp)


def _own_still(c):
    """Whether clip c itself (not what a compound shows) is the same at every moment."""
    t = c.get("type")
    if t in ("video", "audio") or c.get("viz") or c.get("expr") or (c.get("asset") or {}).get("family") == "particles":
        return False                                 # (a particle object moves by itself)
    if _moves({k: v for k, v in c.items() if k not in LINKED + ("effects", "mask")}):
        return False
    if not all(_effect_still(e) for e in c.get("effects") or ()):
        return False
    return _mask_still(project.active_mask(c))


def _shown(s, e, fps):
    """The stretch of time clip [s, e) shows over, as the renderers see it: on_frame rounds both the time and the clip's
    ends to frames, so it shows from half a frame before its rounded start (and to half a frame before its rounded end).
    Both kinds of edges are given, so a stretch between two of them has the same clips all through."""
    fs, fe = round(s * fps / US), round(e * fps / US)
    rs, re_ = (fs - 0.5) * US / fps, (fe - 0.5) * US / fps
    return min(s, rs), max(e, re_), (s, e, rs, re_)


def pieces(tracks, fps, _seen=()):
    """[(lo_us, hi_us, still)] of a level's tracks, in order, from 0 to INF with no gaps: between two moments where a clip
    starts or ends (or a part of a compound it shows does), so the same clips show all through each."""
    parts, edges = [], {0.0, INF}                    # (lo, hi, still) of every clip where it shows; where they begin and end
    for tr in project.all_tracks(tracks, inline=False):
        if tr.get("kind") == "audio":
            continue
        for c in tr.get("clips") or ():
            if c.get("type") == "audio":
                continue
            s = c.get("start_us", 0)
            e = s + max(0, c.get("duration_us", 0))
            if e <= s:
                continue
            lo, hi, ends = _shown(s, e, fps)
            edges.update(ends)
            for a, b, still in _clip_parts(c, s, e, fps, _seen):
                a, b = (lo if a <= s else a), (hi if b >= e else b)
                parts.append((a, b, still))
                edges.update((a, b))
    edges = sorted(x for x in edges if x >= 0)
    moving = [False] * (len(edges) - 1)
    for lo, hi, still in parts:
        if still:
            continue
        i = bisect.bisect_right(edges, max(lo, 0)) - 1
        while i < len(moving) and edges[i] < hi:
            moving[i] = True
            i += 1
    # (two still stretches side by side are not one: a clip starts or ends between them, the picture is another)
    return [(edges[i], edges[i + 1], not mv) for i, mv in enumerate(moving)]


def _clip_parts(c, s, e, fps, seen):
    if not _own_still(c):
        return [(s, e, False)]
    if c.get("type") not in ("compound", "group"):
        return [(s, e, True)]
    comp = c.get("compound")
    if comp is None or id(comp) in seen:
        return [(s, e, False)]
    if comp.get("static") and not project.static_live(c):
        return [(s, e, _compound_still(comp))]
    if components.is_component(comp) or c.get("params"):
        return [(s, e, False)]                       # (a component's own values: worked into its layers as it is drawn)
    tracks = comp.get("tracks") or []
    if comp.get("static"):                           # (讀取時間: drawn afresh at its own time, its layers lasting as long as it plays)
        if components.swings(comp):
            return [(s, e, False)]
        tracks = components._stretch(tracks, int(project.source_time(c, e - s)) + 2 * US)
    inner = pieces(tracks, fps, seen + (id(comp),))
    f = project.frozen(c)
    if f is not None:
        return [(s, e, _still_at(inner, f))]
    if c.get("speed_curve"):
        a, b = project.source_time(c, 0), project.source_time(c, e - s)
        return [(s, e, _still_over(inner, min(a, b), max(a, b)))]
    v = project.speed(c)
    src = c.get("source_start_us", 0)
    out = []
    for lo, hi, still in inner:                     # (inner time u shows at s + (u - src) / v)
        a, b = s + (lo - src) / v, (s + (hi - src) / v) if hi < INF else INF
        a, b = max(a, s), min(b, e)
        if a < b:
            out.append((a, b, still))
    return out or [(s, e, True)]


def _still_at(inner, u):
    i = bisect.bisect_right([p[0] for p in inner], u) - 1
    return i >= 0 and inner[i][2]


def _still_over(inner, a, b):
    i = bisect.bisect_right([p[0] for p in inner], a) - 1
    return i >= 0 and inner[i][2] and b < inner[i][1]


def _first_frame_at(us, fps):
    """The first frame whose time (frame / fps * US, as the renderers have it) is at or after us."""
    f = max(0, math.ceil(us * fps / US) - 1)
    while f / fps * US < us:
        f += 1
    return f


def frame_spans(view, length=None, least=2):
    """[(first, end)] frames of the view's still stretches, each at least `least` frames long."""
    fps = float(view.get("fps") or 30.0)
    _ctx["compounds"], _ctx["fps"] = view.get("compounds") or {}, fps
    out = []
    for lo, hi, still in pieces(view.get("tracks") or [], fps):
        if not still:
            continue
        a = _first_frame_at(lo, fps)
        b = _first_frame_at(hi, fps) if hi < INF else (length if length is not None else a)
        if length is not None:
            b = min(b, length)
        if b - a >= least:
            out.append((a, b))
    return out
