"""攝影機: a container (the timeline, a compound clip, a group) can have a camera; the clips in it are then planes in space that
the camera looks at, and are drawn through the perspective it gives them.

The camera is `camera` on the container: {on, fov, x, y, z, tx, ty, tz} (numbers or keyframed curves, like a transform's).
fov is the vertical angle of view in degrees (40). x, y, z is where it is and tx, ty, tz what it looks at, in half-canvas
units (x to the right, y UP, z away from the picture; a unit is half the canvas's width for x and half its height for y and z -
as a transform's x / y). Without z the camera stands where the z = 0 plane fills the picture exactly (so a clip at z = 0 with no turn
is drawn as it would be without a camera, whatever the angle of view); without tx, ty, tz it looks at the middle of the picture.

A clip in the scene has its transform's x, y (and z, 3D位置) for where its centre is, rotation (about the axis towards the
camera) and rot_x, rot_y for the turns about the other two, and scale as always. Each clip is drawn flat on a layer of its own with
its scale, mask, effects and opacity, and that layer is put in the picture through plane() - a homography, so the picture is
foreshortened as it should be. The layers are put far to near (the clips of the same depth in their order).
"""
import math

import numpy as np
from PySide6.QtGui import QTransform

from . import curves

FOV = 40.0
NEAR = 1e-3                                   # (half-heights) a plane nearer than this to the camera is not drawn


def on(cam):
    return bool(cam) and bool(cam.get("on"))


def _v(d, key, default, t):
    return float(curves.value(d.get(key, default), t))


def _rot(deg_x, deg_y, deg_z):
    """The turn of a plane: z (clockwise on the y-down picture), then y, then x. Positive rot_y takes the right edge away from the
    camera and positive rot_x the top edge (as AE)."""
    a, b, g = math.radians(-deg_x), math.radians(-deg_y), math.radians(deg_z)
    rx = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    ry = np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]])
    rz = np.array([[math.cos(g), -math.sin(g), 0], [math.sin(g), math.cos(g), 0], [0, 0, 1]])
    return rz @ ry @ rx


def _basis(cam, t, W, H):
    """(focal length in px, camera position, rows of the camera's axes: right, down, forward) for a W x H picture."""
    s = H / 2.0
    fov = min(max(_v(cam, "fov", FOV, t), 1.0), 170.0)
    f = s / math.tan(math.radians(fov) / 2.0)                      # px
    cx, cy = _v(cam, "x", 0.0, t) * W / 2.0, -_v(cam, "y", 0.0, t) * s
    cz = _v(cam, "z", -f / s, t) * s if cam.get("z") is not None else -f
    tx, ty, tz = _v(cam, "tx", 0.0, t) * W / 2.0, -_v(cam, "ty", 0.0, t) * s, _v(cam, "tz", 0.0, t) * s
    c = np.array([cx, cy, cz])
    fwd = np.array([tx, ty, tz]) - c
    n = np.linalg.norm(fwd)
    fwd = fwd / n if n > 1e-9 else np.array([0.0, 0.0, 1.0])
    right = np.cross([0.0, 1.0, 0.0], fwd)
    n = np.linalg.norm(right)
    right = right / n if n > 1e-9 else np.array([1.0, 0.0, 0.0])      # (looking straight up or down)
    down = np.cross(fwd, right)
    return f, c, np.array([right, down, fwd])


def plane(cam, tf, t, W, H, tc=None):
    """(QTransform, depth): where a clip with transform tf is drawn at clip time t (the camera is at its own time tc: the container's, not the
    clip's; default t). The transform takes a point of the clip drawn flat
    on the W x H picture (its centre in the middle) to the picture; depth is how far its centre is from the camera in half-heights
    (<= 0: behind it, nothing to draw)."""
    s = H / 2.0
    f, c, cam = _basis(cam, t if tc is None else tc, W, H)
    o = np.array([_v(tf, "x", 0.0, t) * W / 2.0, -_v(tf, "y", 0.0, t) * s, _v(tf, "z", 0.0, t) * s])
    r = _rot(_v(tf, "rot_x", 0.0, t), _v(tf, "rot_y", 0.0, t), _v(tf, "rotation", 0.0, t))
    a = np.stack([cam @ r[:, 0], cam @ r[:, 1], cam @ (o - c)], axis=1)       # (u, v, 1) -> camera space
    k = np.array([[f, 0, W / 2.0], [0, f, H / 2.0], [0, 0, 1.0]])
    m = k @ a @ np.array([[1, 0, -W / 2.0], [0, 1, -H / 2.0], [0, 0, 1.0]])
    q = QTransform(m[0][0], m[1][0], m[2][0], m[0][1], m[1][1], m[2][1], m[0][2], m[1][2], m[2][2])
    return q, float(a[2][2]) / s


def depth(cam, tf, t, W, H, tc=None):
    """How far the centre of a clip with transform tf is in front of the camera (half-heights)."""
    s = H / 2.0
    _f, c, cam_axes = _basis(cam, t if tc is None else tc, W, H)
    o = np.array([_v(tf, "x", 0.0, t) * W / 2.0, -_v(tf, "y", 0.0, t) * s, _v(tf, "z", 0.0, t) * s])
    return float((cam_axes @ (o - c))[2]) / s


def blur(cam, tf, t, W, H, tc=None):
    """景深: the radius (px of the flat picture, as a 模糊 effect takes it) a clip with transform tf is blurred by - the farther it is from
    the focus (cam["focus"], half-heights from the camera; without it the target's distance), the more, as a lens does: aperture (光圈,
    0: no depth of field) x |distance - focus| / distance of a fiftieth of the picture's height. It is the blur on the picture, so it
    is divided by the plane's scale (a far plane is drawn smaller)."""
    tc = t if tc is None else tc
    aperture = _v(cam, "aperture", 0.0, tc)
    if aperture <= 0:
        return 0.0
    f, c, tg, _axes = _pose(cam, tc, W, H)
    s = H / 2.0
    d = depth(cam, tf, t, W, H, tc)
    if d <= NEAR:
        return 0.0
    focus = _v(cam, "focus", 0.0, tc) if cam.get("focus") is not None else float(np.linalg.norm(tg - c)) / s
    scale = f / s / d                                          # the plane's size on the picture, in its own
    return aperture * H / 50.0 * abs(d - focus) / d / max(scale, 1e-6)


def flat(c):
    """Clip c with the transform of its flat drawing: at the middle of the picture, not turned - where plane() puts it, the rest
    (scale, flips, mask, effects) as it is."""
    tf = dict(c.get("transform") or {})
    for k in ("x", "y", "rotation", "pivot_x", "pivot_y", "anchor_x", "anchor_y"):
        tf.pop(k, None)
    return dict(c, transform=tf)


# -- what the preview's handles do (gizmos.camera_handles): each takes the camera as it was when the drag began and says what it is now ----

def _pose(cam, t, W, H):
    """(focal px, position, target, [right, down, forward]) in px of a W x H picture: x to the right, y down, z away."""
    s = H / 2.0
    f, c, axes = _basis(cam, t, W, H)
    tg = np.array([_v(cam, "tx", 0.0, t) * W / 2.0, -_v(cam, "ty", 0.0, t) * s, _v(cam, "tz", 0.0, t) * s])
    return f, c, tg, axes


def _units(c, W, H, prefix=""):
    s = H / 2.0
    return {prefix + "x": float(c[0] / (W / 2.0)), prefix + "y": float(-c[1] / s), prefix + "z": float(c[2] / s)}


def track(cam, t, W, H, dx, dy):
    """平移: the picture follows a drag of dx, dy picture px - the camera and its target move the other way, in the plane of the picture."""
    f, c, tg, (right, down, _fwd) = _pose(cam, t, W, H)
    k = max(float(np.linalg.norm(tg - c)), 1e-6) / f
    move = -(dx * right + dy * down) * k
    return dict(_units(c + move, W, H), **_units(tg + move, W, H, "t"))


def orbit(cam, t, W, H, dx, dy, per_px=0.25):
    """環繞: the camera goes round its target - dx picture px turn it about the vertical, dy up and down (a drag down takes it up)."""
    _f, c, tg, _axes = _pose(cam, t, W, H)
    v = c - tg
    a = math.radians(dx * per_px)
    v = np.array([v[0] * math.cos(a) + v[2] * math.sin(a), v[1], -v[0] * math.sin(a) + v[2] * math.cos(a)])
    n = float(np.linalg.norm(v))
    if n < 1e-6:
        return _units(c, W, H)
    right = np.cross([0.0, 1.0, 0.0], -v)
    m = np.linalg.norm(right)
    right = right / m if m > 1e-9 else np.array([1.0, 0.0, 0.0])
    elev = math.asin(max(-1.0, min(1.0, -v[1] / n)))                 # (up is -y)
    elev2 = max(math.radians(-85), min(math.radians(85), elev + math.radians(dy * per_px)))
    th = elev2 - elev
    ax = right                                                       # rotate v about the camera's right axis
    v = v * math.cos(-th) + np.cross(ax, v) * math.sin(-th) + ax * float(ax @ v) * (1 - math.cos(-th))
    return _units(tg + v, W, H)


def dolly(cam, t, W, H, dy, per_px=0.004):
    """推拉: the camera goes towards its target (a drag up) or away from it."""
    _f, c, tg, _axes = _pose(cam, t, W, H)
    return _units(tg + (c - tg) * math.exp(dy * per_px), W, H)


def deepfocus(cam, c, t, W, H, tc=None):
    """The clip drawn flat for the scene (flat()), with the 景深 blur its distance gives it as the last of its effects."""
    from . import fx
    out = flat(dict(c, blend="normal"))
    r = blur(cam, c.get("transform") or {}, t, W, H, tc)
    if r >= 0.25:
        e = fx.new_effect("builtin:blur", "~dof")
        e["params"].update(radius=r, link_xy=True)
        out["effects"] = list(c.get("effects") or []) + [e]
    return out


# -- seeing the scene from outside (the preview's 3D view, ui/view3d.py) ------------------------------------------------------------

def world_of(tf, t, W, H, local):
    """World points (px: x right, y down, z away) of points `local` of a plane drawn flat - (u, v) from its centre, canvas px - for a clip
    with transform tf at clip time t."""
    s = H / 2.0
    o = np.array([_v(tf, "x", 0.0, t) * W / 2.0, -_v(tf, "y", 0.0, t) * s, _v(tf, "z", 0.0, t) * s])
    r = _rot(_v(tf, "rot_x", 0.0, t), _v(tf, "rot_y", 0.0, t), _v(tf, "rotation", 0.0, t))
    return [o + r @ np.array([u, v, 0.0]) for u, v in local]


class Seen:
    """A camera at one moment for a W x H picture: world points to the picture (canvas px), with lines cut where they pass behind it."""

    def __init__(self, cam, t, W, H):
        self.W, self.H = W, H
        self.f, self.c, self.target, self.axes = _pose(cam, t, W, H)

    def space(self, p):
        """The point in the camera's own axes (x right, y down, z forward), px."""
        return self.axes @ (np.asarray(p, float) - self.c)

    def screen(self, q):
        return (self.W / 2.0 + self.f * q[0] / q[2], self.H / 2.0 + self.f * q[1] / q[2])

    def point(self, p):
        q = self.space(p)
        return self.screen(q) if q[2] > NEAR * self.H / 2.0 else None

    def segment(self, a, b):
        """((x0, y0), (x1, y1)) on the picture of the line from world a to b, or None when it is all behind the camera."""
        qa, qb = self.space(a), self.space(b)
        near = NEAR * self.H / 2.0
        if qa[2] <= near and qb[2] <= near:
            return None
        if qa[2] <= near:
            qa = qa + (qb - qa) * ((near - qa[2]) / (qb[2] - qa[2]))
        elif qb[2] <= near:
            qb = qb + (qa - qb) * ((near - qb[2]) / (qa[2] - qb[2]))
        return self.screen(qa), self.screen(qb)

    def ray(self, x, y):
        """(origin, direction) in the world of the line of sight through picture point (x, y)."""
        d = np.array([(x - self.W / 2.0) / self.f, (y - self.H / 2.0) / self.f, 1.0])
        w = self.axes.T @ d
        return self.c, w / np.linalg.norm(w)


def frustum(cam, t, W, H, reach=0.5):
    """World points of a camera drawn as a pyramid: its position, then the four corners of its picture `reach` of the way to its target."""
    f, c, tg, axes = _pose(cam, t, W, H)
    d = max(float(np.linalg.norm(tg - c)), 1e-6) * reach
    right, down, fwd = axes
    k = d / f
    corners = [c + fwd * d + right * sx * W / 2.0 * k + down * sy * H / 2.0 * k for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    return c, corners, tg


PRESETS = {"front": (0.0, 0.0), "back": (180.0, 0.0), "right": (-90.0, 0.0), "left": (90.0, 0.0), "top": (0.0, 89.0), "bottom": (0.0, -89.0)}


def look_from(cam, t, W, H, name):
    """{x, y, z} that put the camera on the `name` side of its target (front, back, right, left, top, bottom: the numpad 1, Ctrl+1, 3, Ctrl+3, 7,
    Ctrl+7 of Blender), the same distance away."""
    _f, c, tg, _axes = _pose(cam, t, W, H)
    n = float(np.linalg.norm(c - tg)) or 1.0
    yaw, pitch = (math.radians(a) for a in PRESETS[name])
    v = np.array([-math.sin(yaw) * math.cos(pitch), -math.sin(pitch), -math.cos(yaw) * math.cos(pitch)]) * n      # (front: in front of the scene, on the viewer's side; top: above, y is down)
    return _units(tg + v, W, H)
