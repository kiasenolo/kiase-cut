"""Blender's basic procedural textures drawn as pictures (for the fill and outline of 內建素材 shapes).

The same patterns as the [Blender] texture filters (kiasecut/filters/blender_tex_*.glsl), with
Blender's default settings, in NumPy: checker, brick, noise, voronoi, wave and magic.
Source: the matching Blender shader nodes (source/blender/gpu/shaders/material/
gpu_shader_material_tex_*.glsl), rewritten by hand - the same patterns, the cell randomness is
not bit-identical with Blender.
Blender: https://github.com/blender/blender
SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
SPDX-License-Identifier: GPL-3.0-or-later

Coordinates are Blender's image coordinates (the long side -1..1, y up) times the scale; the
patterns are 3D - z (a number of cells) moves through them, so the picture changes smoothly with it.
"""
import numpy as np

KINDS = ("checker", "brick", "noise", "voronoi", "wave", "magic")
MAX_PX = 1024                    # longest side of the picture made (it is stretched to the shape)


def _coords(w, h, scale, seed):
    k = min(1.0, MAX_PX / max(w, h, 1))
    pw, ph = max(1, round(w * k)), max(1, round(h * k))
    xs = (np.arange(pw) + 0.5) / pw * 2.0 - 1.0
    ys = 1.0 - (np.arange(ph) + 0.5) / ph * 2.0
    m = max(pw, ph)
    x, y = np.meshgrid(xs * pw / m * scale + seed, ys * ph / m * scale)
    return x, y


def _hash(*cols):
    """A float 0 - 1 per cell, from integer cell numbers (a PCG-like integer hash)."""
    v = np.uint32(2166136261)
    h = np.full(np.broadcast(*cols).shape, v, dtype=np.uint32)
    for c in cols:
        h = (h ^ np.asarray(c).astype(np.int64).astype(np.uint32)) * np.uint32(16777619)
        h ^= h >> np.uint32(15)
        h *= np.uint32(2246822519)
        h ^= h >> np.uint32(13)
    return h.astype(np.float64) / 4294967295.0


# -- Blender's perlin noise (Jenkins lookup3 hash + gradient noise) -------------------------------
def _rotl(x, k):
    return (x << np.uint32(k)) | (x >> np.uint32(32 - k))


def _jfinal(a, b, c):
    c ^= b; c -= _rotl(b, 14)
    a ^= c; a -= _rotl(c, 11)
    b ^= a; b -= _rotl(a, 25)
    c ^= b; c -= _rotl(b, 16)
    a ^= c; a -= _rotl(c, 4)
    b ^= a; b -= _rotl(a, 14)
    c ^= b; c -= _rotl(b, 24)
    return c


def _hash3(x, y, z):
    base = np.uint32((0xdeadbeef + (3 << 2) + 13) & 0xFFFFFFFF)
    a = base + x.astype(np.int64).astype(np.uint32)
    b = base + y.astype(np.int64).astype(np.uint32)
    c = base + z.astype(np.int64).astype(np.uint32)
    return _jfinal(a, b, c)


def _grad(h, x, y, z):
    h = h & np.uint32(15)
    u = np.where(h < 8, x, y)
    v = np.where(h < 4, y, np.where((h == 12) | (h == 14), x, z))
    return np.where(h & 1, -u, u) + np.where(h & 2, -v, v)


def _gnoise(x, y, z):
    fx, fy, fz = np.floor(x), np.floor(y), np.floor(z)
    x, y, z = x - fx, y - fy, z - fz
    f = lambda t: t * t * t * (t * (t * 6 - 15) + 10)
    u, v, w = f(x), f(y), f(z)

    def g(dx, dy, dz):
        return _grad(_hash3(fx + dx, fy + dy, fz + dz), x - dx, y - dy, z - dz)

    lerp = lambda a, b, t: a + (b - a) * t
    r = lerp(lerp(lerp(g(0, 0, 0), g(1, 0, 0), u), lerp(g(0, 1, 0), g(1, 1, 0), u), v),
             lerp(lerp(g(0, 0, 1), g(1, 0, 1), u), lerp(g(0, 1, 1), g(1, 1, 1), u), v), w)
    return 0.9820 * r


def _fbm(x, y, z, detail=2.0, rough=0.5, lac=2.0):
    total, amp, mx = 0.0, 1.0, 0.0
    for _ in range(int(detail) + 1):
        total = total + _gnoise(x, y, z) * amp
        mx += amp
        amp *= rough
        x, y, z = x * lac, y * lac, z * lac
    rmd = detail - int(detail)
    base = 0.5 * total / mx + 0.5
    if rmd > 0:
        t2 = total + _gnoise(x, y, z) * amp
        return base * (1 - rmd) + (0.5 * t2 / (mx + amp) + 0.5) * rmd
    return base


# -- the textures: a factor 0 - 1 (or a colour for magic) per pixel -------------------------------
def _checker(x, y, z):
    xi, yi = np.abs(np.floor(x * 0.999999)), np.abs(np.floor(y * 0.999999))
    zi = abs(np.floor(z * 0.999999))
    return (((xi % 2) != (yi % 2)) != (zi % 2 == 1)).astype(np.float64)       # 1: colour 1


def _brick(x, y):
    bw0, rh, off_amt, sq, mortar_size, smooth = 0.5, 0.25, 0.5, 1.0, 0.02, 0.1
    row = np.floor(y / rh)
    bw = np.where(row % 2 == 0, bw0 * sq, bw0)
    off = np.where(row % 2 == 0, bw * off_amt, 0.0)
    num = np.floor((x + off) / bw)
    bx = (x + off) - bw * num
    by = y - rh * row
    tint = np.clip(_hash(row, num), 0, 1)
    d = np.minimum(np.minimum(bx, by), np.minimum(bw - bx, rh - by))
    t = np.clip(1.0 - d / mortar_size, 0, 1)
    mortar = np.where(d >= mortar_size, 0.0, t * t * (3 - 2 * t) if smooth > 0 else 1.0)
    return tint, mortar


def _voronoi(x, y, z):
    """Distance to the nearest of the points hashed in each 3D cell (so it moves smoothly with z)."""
    ix, iy, iz = np.floor(x), np.floor(y), np.floor(z)
    fz = z - iz
    best = np.full(x.shape, 8.0)
    for k in range(-1, 2):
        for j in range(-1, 2):
            for i in range(-1, 2):
                cx, cy, cz = ix + i, iy + j, iz + k
                px = cx + _hash(cx, cy, cz, 1)
                py = cy + _hash(cx, cy, cz, 2)
                pz = cz + _hash(cx, cy, cz, 3)
                best = np.minimum(best, np.sqrt((x - px) ** 2 + (y - py) ** 2 + (iz + fz - pz) ** 2))
    return np.clip(best, 0, 1)


def _wave(x, y, z):
    n = x * 20.0 + z * 6.28318530718                      # (a z of 1 moves the bands one period)
    return 0.5 + 0.5 * np.sin(n - 1.57079632679)


def _magic(x, y, z, depth=2, d=1.0):
    a = np.sin((x + y + z) * 5.0)
    b = np.cos((-x + y - z) * 5.0)
    c = -np.cos((-x - y + z) * 5.0)
    if depth > 0:
        a, b, c = a * d, b * d, c * d
        b = -np.cos(a - b + c) * d
        if depth > 1:
            a = np.cos(a - b - c) * d
    dd = d * 2.0
    return 0.5 - a / dd, 0.5 - b / dd, 0.5 - c / dd


def render(kind, w, h, scale, seed, z, c1, c2):
    """RGBA (uint8, rows top to bottom) of texture `kind` for a w x h shape; colours are
    [r, g, b, a] (0 - 1): colour 1 and 2 of the texture (a brick's mortar is colour 2 darkened)."""
    x, y = _coords(w, h, scale, seed)
    z = np.full_like(x, z)
    c1, c2 = np.array(c1, dtype=np.float64), np.array(c2, dtype=np.float64)
    mix = lambda f: c1 + (c2 - c1) * np.asarray(f)[..., None]
    if kind == "checker":
        out = mix(1.0 - _checker(x, y, z))
    elif kind == "brick":
        tint, mortar = _brick(x, y)
        brick = mix(tint)
        out = brick + (c2 * np.array([0.25, 0.25, 0.25, 1.0]) - brick) * mortar[..., None]
    elif kind == "noise":
        out = mix(np.clip(_fbm(x, y, z + 0.5), 0, 1))
    elif kind == "voronoi":
        out = mix(_voronoi(x, y, z))
    elif kind == "wave":
        out = mix(_wave(x, y, z))
    else:                                                  # magic: its own colours
        r, g, b = _magic(x, y, z)
        out = np.stack([r, g, b, np.ones_like(r) * c1[3]], axis=-1)
    return (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)
