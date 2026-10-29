"""Jianying masks baked to screen-space mattes.

Mask geometry lives in the clip's material space: centre in half-material units (y up),
width/height as fractions of the displayed material, rotation in clockwise degrees.
The clip transform (position, uniform scale, clockwise rotation) then maps it to screen.
Verified against a Jianying export: line keeps the side above the line, circle sizes are
diameters, invert flips the result.
"""
import math

import numpy as np

from . import curves, project

KINDS = ("line", "mirror", "circle", "rectangle")


def alpha(kind, w, h, feather, xs, ys):
    """Coverage for points (xs, ys) in mask space (origin at the mask centre, y up)."""
    if kind == "line":
        d = ys
    elif kind == "mirror":
        d = h / 2 - np.abs(ys)
    elif kind == "circle":
        rx, ry = max(w / 2, 1e-6), max(h / 2, 1e-6)
        r = np.sqrt((xs / rx) ** 2 + (ys / ry) ** 2)
        d = (1 - r) * min(rx, ry)
    elif kind == "rectangle":
        d = np.minimum(w / 2 - np.abs(xs), h / 2 - np.abs(ys))
    else:
        raise ValueError(f"unsupported mask {kind!r}")
    soft = max(feather * min(w, h) / 2, 0.5)
    return np.clip(d / (2 * soft) + 0.5, 0, 1)


class Rasterizer:
    def __init__(self, width, height):
        self.W, self.H = width, height
        self.gx, self.gy = np.meshgrid(np.arange(width) + 0.5 - width / 2,
                                       height / 2 - (np.arange(height) + 0.5))

    def matte(self, mask, transform, disp_w, disp_h, t):
        """uint8 matte at t (us from clip start). transform: x, y, scale, rotation params."""
        W, H = self.W, self.H
        cx, cy = project.centre_px(transform, t, W, H)      # (中心點: about its pivot)
        px, py = cx - W / 2, H / 2 - cy
        a = math.radians(curves.value(transform.get("rotation", 0.0), t))
        sx = curves.value(transform.get("scale", 1.0), t) or 1e-6
        sy = curves.value(transform.get("scale_y", transform.get("scale", 1.0)), t) or 1e-6
        dx, dy = self.gx - px, self.gy - py
        lx = (dx * math.cos(a) - dy * math.sin(a)) / sx
        ly = (dx * math.sin(a) + dy * math.cos(a)) / sy
        if transform.get("flip_h"):
            lx = -lx
        if transform.get("flip_v"):
            ly = -ly
        v = lambda k, d: curves.value(mask.get(k, d), t)
        mx = lx - v("cx", 0.0) * disp_w / 2
        my = ly - v("cy", 0.0) * disp_h / 2
        b = math.radians(v("rotation", 0.0))
        rx = mx * math.cos(b) - my * math.sin(b)
        ry = mx * math.sin(b) + my * math.cos(b)
        m = alpha(v("kind", "rectangle"), v("w", 1.0) * disp_w, v("h", 1.0) * disp_h, v("feather", 0.0), rx, ry)
        if v("invert", False):
            m = 1 - m
        return (m * 255 + 0.5).astype(np.uint8)

    @staticmethod
    def animated(mask, transform):
        return any(curves.is_animated(mask.get(k)) for k in ("cx", "cy", "w", "h", "rotation", "feather")) \
            or any(curves.is_animated(transform.get(k)) for k in ("x", "y", "scale", "scale_y", "rotation",
                                                                   "pivot_x", "pivot_y", "anchor_x", "anchor_y"))


# -- native masks: the same shapes as bezier splines for MLT's rotoscoping filter ----------
K_CIRCLE = 0.5522847498          # bezier handle length for a quarter circle


def _shape(kind, w, h, big):
    """Bezier points [(h1, p, h2)] in mask space (origin at the mask centre, y up), covering
    the visible area: line keeps y >= 0, mirror |y| <= h/2."""
    def corners(x0, y0, x1, y1):
        return [((x, y), (x, y), (x, y)) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]

    if kind == "line":
        return corners(-big, 0, big, big)
    if kind == "mirror":
        return corners(-big, -h / 2, big, h / 2)
    if kind == "rectangle":
        return corners(-w / 2, -h / 2, w / 2, h / 2)
    if kind == "circle":
        rx, ry = w / 2, h / 2
        kx, ky = K_CIRCLE * rx, K_CIRCLE * ry
        return [((rx, -ky), (rx, 0), (rx, ky)), ((kx, ry), (0, ry), (-kx, ry)),
                ((-rx, ky), (-rx, 0), (-rx, -ky)), ((-kx, -ry), (0, -ry), (kx, -ry))]
    raise ValueError(f"unsupported mask {kind!r}")


def spline(mask, t, disp_w, disp_h, frame_w, frame_h):
    """Mask at t as a rotoscoping spline in the clip's own frame (0-1 coordinates).
    The filter runs before the clip transform, so this is material space, as in Jianying."""
    v = lambda k, d: curves.value(mask.get(k, d), t)
    cx, cy = v("cx", 0.0) * disp_w / 2, v("cy", 0.0) * disp_h / 2
    b = math.radians(v("rotation", 0.0))
    cb, sb = math.cos(b), math.sin(b)
    big = 8 * (frame_w + frame_h)
    kind = v("kind", "rectangle")
    pts = _shape(kind, v("w", 1.0) * disp_w, v("h", 1.0) * disp_h, big)

    def to_frame(q):
        # rotate clockwise by b (y up), move to the centre, then to 0-1 image coordinates
        x, y = q[0] * cb + q[1] * sb, -q[0] * sb + q[1] * cb
        return [0.5 + (cx + x) / frame_w, 0.5 - (cy + y) / frame_h]

    if kind in ("line", "mirror"):
        # half-planes and bands are huge quads; rotoscoping rasterises their whole extent,
        # which made a line mask cost ~80 ms a frame. Clip them to the frame first.
        poly = clip_polygon([to_frame(p) for _, p, _ in pts], -0.01, 1.01)
        poly = (poly + [poly[-1]] * CLIP_POINTS)[:CLIP_POINTS] if poly else [[-1.0, -1.0]] * CLIP_POINTS
        return [[q, q, q] for q in poly]
    return [[to_frame(h1), to_frame(p), to_frame(h2)] for h1, p, h2 in pts]


CLIP_POINTS = 8      # a quad clipped by a rectangle has at most 8 corners; pad to a fixed count


def clip_polygon(poly, lo, hi):
    """Sutherland-Hodgman clip of a polygon to the square [lo, hi]^2."""
    for axis, bound, keep_above in ((0, lo, True), (0, hi, False), (1, lo, True), (1, hi, False)):
        if not poly:
            break
        out = []
        for i, cur in enumerate(poly):
            prev = poly[i - 1]
            inside = lambda q: q[axis] >= bound if keep_above else q[axis] <= bound
            if inside(cur):
                if not inside(prev):
                    out.append(_cross(prev, cur, axis, bound))
                out.append(cur)
            elif inside(prev):
                out.append(_cross(prev, cur, axis, bound))
        poly = out
    return poly


def _cross(a, b, axis, bound):
    k = (bound - a[axis]) / (b[axis] - a[axis])
    return [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k]
