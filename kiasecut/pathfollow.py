"""路徑跟隨: a clip moves along the outline of a shape or pen path clip of its own level.

clip["transform"]["path_id"] = the shape / path clip's id, ["path_progress"] = how far along (0 - 1, a number or a curve: keyframes,
easing, LFOs like any other); the clip's own x / y then are an offset from the point of the path it is at. The outline is the
asset's (assets.outline_d: a path's parts, a rectangle's edge, a star...) as the path clip is placed, scaled and turned - at each
moment, so a moving path takes its followers with it.

resolve(root) is for a private copy that is going to be drawn (the renderer's snapshot, an export's, the preview's): it writes each
follower's x / y as the numbers (or, when anything moves, keyframes at every frame) that put it there, and takes the path_id away so
a second pass leaves it alone. resolved(view) does that on a copy only when something follows.
"""
import copy

from PySide6.QtCore import QPointF
from PySide6.QtGui import QTransform

from . import assets, curves, project, vector

FIELDS = ("path_id", "path_progress")
NOT_PATHS = ("solid", "gradient", "empty", "grid")
MAX_KEYS = 4000
MOVING = ("x", "y", "scale", "scale_y", "rotation", "pivot_x", "pivot_y", "anchor_x", "anchor_y")


def is_follower(c):
    return bool((c.get("transform") or {}).get("path_id"))


def is_path(c):
    """Whether clip c is something a clip can follow: a built-in shape or a pen path."""
    a = c.get("asset")
    return bool(a) and a.get("family") not in NOT_PATHS


def _levels(root):
    """Every list of tracks that is a level of its own: the timelines' and the compounds'; [(tracks, width, height)]."""
    out, seen = [], set()

    def add(tracks, w, h):
        if id(tracks) not in seen:
            seen.add(id(tracks))
            out.append((tracks, w, h))
    add(root["tracks"], root["width"], root["height"])
    for tl in root.get("timelines") or ():
        add(tl["tracks"], root["width"], root["height"])
    for comp in (root.get("compounds") or {}).values():
        add(comp["tracks"], comp.get("width") or root["width"], comp.get("height") or root["height"])
    return out


def _clips(tracks):
    """The clips of one level: its tracks' and those of the groups in them (a compound's are its own level)."""
    for t in project.all_tracks(tracks):
        yield from t["clips"]


def has_followers(root):
    return any(is_follower(c) for tracks, _w, _h in _levels(root) for c in _clips(tracks))


def candidates(level_tracks):
    """[(id, name)] of the clips of a level that can be followed."""
    from .ui.params import clip_name
    return [(c["id"], clip_name(c)) for c in _clips(level_tracks) if is_path(c)]


def _outline(path_clip):
    """The path clip's outline in its own frame (QPainterPath centred on 0, y down), as at its start."""
    q = assets.at(path_clip["asset"], 0)
    qp = vector.parse_d(assets.outline_d(q, q["w"], q["h"]))
    qp.translate(-q["w"] / 2, -q["h"] / 2)
    return qp


def _frame(path_clip, tp, W, H):
    """QTransform of the path clip's frame at its own time tp, as the renderers place it."""
    tf = path_clip.get("transform") or {}
    v = lambda k, d: curves.value(tf.get(k, d), tp)
    sx = v("scale", 1.0)
    sy = curves.value(tf.get("scale_y", tf.get("scale", 1.0)), tp)
    return QTransform().translate(*project.centre_px(tf, tp, W, H)).rotate(v("rotation", 0.0)) \
        .scale(sx * (-1 if tf.get("flip_h") else 1), sy * (-1 if tf.get("flip_v") else 1))


def point_at(path_clip, progress, tp, W, H, outline=None):
    """Canvas point (px) of the path clip's outline `progress` (0 - 1) of the way along, at the path clip's time tp."""
    qp = outline if outline is not None else _outline(path_clip)
    if qp.isEmpty():
        return None
    return _frame(path_clip, tp, W, H).map(qp.pointAtPercent(min(1.0, max(0.0, float(progress)))))


def _moving(c):
    tf = c.get("transform") or {}
    return any(curves.is_animated(tf.get(k)) for k in MOVING + ("path_progress",)) or tf.get("scale_link") is False


def _apply(c, p, W, H, fps):
    tf = c["transform"]
    bx, by = tf.get("x", 0.0), tf.get("y", 0.0)
    if p is None or not is_path(p):
        return
    qp = _outline(p)
    if qp.isEmpty():
        return
    still = not curves.is_animated(tf.get("path_progress")) and not _moving(p) and not curves.is_animated(bx) \
        and not curves.is_animated(by)

    def at(t):
        pt = point_at(p, curves.value(tf.get("path_progress", 0.0), t), c["start_us"] + t - p["start_us"], W, H, qp)
        return ((pt.x() - W / 2) / (W / 2) + curves.value(bx, t), (H / 2 - pt.y()) / (H / 2) + curves.value(by, t))
    if still:
        tf["x"], tf["y"] = (round(v, 5) for v in at(0))
        return
    dur = max(int(c.get("duration_us") or 0), 1)
    step = max(1_000_000 / max(fps, 1.0), dur / MAX_KEYS)
    times = [int(i * step) for i in range(int(dur / step) + 1)]
    if times[-1] < dur:
        times.append(dur)
    xs, ys = [], []
    for t in times:
        x, y = at(t)
        xs.append([t, round(x, 5), 0.0, 0.0, 0.0, 0.0])
        ys.append([t, round(y, 5), 0.0, 0.0, 0.0, 0.0])
    tf["x"], tf["y"] = {"keys": xs}, {"keys": ys}


def resolve(root):
    """Write the followers of a private copy of a project (or of the open level's view) as plain x / y; True when there were any."""
    found = False
    fps = float(root.get("play_fps") or root.get("fps") or 30.0)
    for tracks, W, H in _levels(root):
        clips = list(_clips(tracks))
        by_id = {c["id"]: c for c in clips}
        for c in clips:
            tf = c.get("transform")
            if tf and tf.get("path_id"):
                found = True
                _apply(c, by_id.get(tf["path_id"]), W, H, fps)
                tf["_followed"] = True
                tf.pop("path_id", None)
                tf.pop("path_progress", None)
    return found


def resolved(view):
    """view with its followers placed: the view itself when nothing follows, else a copy."""
    if not has_followers(view):
        return view
    out = copy.deepcopy(view)
    resolve(out)
    return out
