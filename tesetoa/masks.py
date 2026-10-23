"""Jianying masks baked to screen-space mattes.

Mask geometry lives in the clip's material space: centre in half-material units (y up),
width/height as fractions of the displayed material, rotation in clockwise degrees.
The clip transform (position, uniform scale, clockwise rotation) then maps it to screen.
Verified against a Jianying export: line keeps the side above the line, circle sizes are
diameters, invert flips the result.
"""
import math

import numpy as np

from . import curves

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
    soft = max(feather * (min(w, h) if kind != "line" else 0) / 2, 0.5)
    return np.clip(d / (2 * soft) + 0.5, 0, 1)


class Rasterizer:
    def __init__(self, width, height):
        self.W, self.H = width, height
        self.gx, self.gy = np.meshgrid(np.arange(width) + 0.5 - width / 2,
                                       height / 2 - (np.arange(height) + 0.5))

    def matte(self, mask, transform, disp_w, disp_h, t):
        """uint8 matte at t (us from clip start). transform: x, y, scale, rotation params."""
        W, H = self.W, self.H
        px = curves.value(transform.get("x", 0.0), t) * W / 2
        py = curves.value(transform.get("y", 0.0), t) * H / 2
        a = math.radians(curves.value(transform.get("rotation", 0.0), t))
        sc = curves.value(transform.get("scale", 1.0), t) or 1e-6
        dx, dy = self.gx - px, self.gy - py
        lx = (dx * math.cos(a) - dy * math.sin(a)) / sc
        ly = (dx * math.sin(a) + dy * math.cos(a)) / sc
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
        m = alpha(mask["kind"], v("w", 1.0) * disp_w, v("h", 1.0) * disp_h, v("feather", 0.0), rx, ry)
        if mask.get("invert"):
            m = 1 - m
        return (m * 255 + 0.5).astype(np.uint8)

    @staticmethod
    def animated(mask, transform):
        return any(curves.is_animated(mask.get(k)) for k in ("cx", "cy", "w", "h", "rotation", "feather")) \
            or any(curves.is_animated(transform.get(k)) for k in ("x", "y", "scale", "rotation"))
