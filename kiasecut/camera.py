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


def plane(cam, tf, t, W, H):
    """(QTransform, depth): where a clip with transform tf is drawn at clip time t. The transform takes a point of the clip drawn flat
    on the W x H picture (its centre in the middle) to the picture; depth is how far its centre is from the camera in half-heights
    (<= 0: behind it, nothing to draw)."""
    s = H / 2.0
    f, c, cam = _basis(cam, t, W, H)
    o = np.array([_v(tf, "x", 0.0, t) * W / 2.0, -_v(tf, "y", 0.0, t) * s, _v(tf, "z", 0.0, t) * s])
    r = _rot(_v(tf, "rot_x", 0.0, t), _v(tf, "rot_y", 0.0, t), _v(tf, "rotation", 0.0, t))
    a = np.stack([cam @ r[:, 0], cam @ r[:, 1], cam @ (o - c)], axis=1)       # (u, v, 1) -> camera space
    k = np.array([[f, 0, W / 2.0], [0, f, H / 2.0], [0, 0, 1.0]])
    m = k @ a @ np.array([[1, 0, -W / 2.0], [0, 1, -H / 2.0], [0, 0, 1.0]])
    q = QTransform(m[0][0], m[1][0], m[2][0], m[0][1], m[1][1], m[2][1], m[0][2], m[1][2], m[2][2])
    return q, float(a[2][2]) / s


def depth(cam, tf, t, W, H):
    """How far the centre of a clip with transform tf is in front of the camera (half-heights)."""
    s = H / 2.0
    _f, c, cam_axes = _basis(cam, t, W, H)
    o = np.array([_v(tf, "x", 0.0, t) * W / 2.0, -_v(tf, "y", 0.0, t) * s, _v(tf, "z", 0.0, t) * s])
    return float((cam_axes @ (o - c))[2]) / s


def flat(c):
    """Clip c with the transform of its flat drawing: at the middle of the picture, not turned - where plane() puts it, the rest
    (scale, flips, mask, effects) as it is."""
    tf = dict(c.get("transform") or {})
    for k in ("x", "y", "rotation", "pivot_x", "pivot_y", "anchor_x", "anchor_y"):
        tf.pop(k, None)
    return dict(c, transform=tf)
