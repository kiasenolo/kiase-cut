"""3D meshes of the objects of a scene: the letters of a 立體 text pushed out into solids (mesh3d.py draws them).

A mesh is an (n, 10) float32 array, three rows a triangle: position (canvas px of the object's own space: x right, y down, z away,
the middle of the text at 0), normal, colour (r, g, b, a: 0 - 1, as picked - sRGB).

The outlines come from the font file (QRawFont), the places of the letters from textlayout._layout, so a solid text stands where the
flat one does. Faces are cut into trapezoids between the heights of the outlines' corners (non-zero winding, as TrueType fills), which
takes holes and strokes that cross as they come.
"""
import json
import math

import numpy as np
from PySide6.QtGui import QFont, QRawFont, QTransform

from . import textlayout

EM = 200.0                       # the size outlines are taken at (their curves are cut as finely as at this size)
_raw = {}                        # font file -> QRawFont at EM
_glyphs = {}                     # (font file, character) -> [contour (m, 2)] at EM
_meshes = {}                     # what a mesh was made of -> the mesh
MAX_MESHES = 64
SMOOTH_COS = math.cos(math.radians(40.0))      # sides meeting flatter than this are shaded as one curve


def _raw_font(path):
    f = _raw.get(path)
    if f is None:
        f = _raw[path] = QRawFont(str(path), EM, QFont.PreferNoHinting)
    return f


def contours_of(path, ch):
    """The outline of character ch of the font file path, as closed polygons at EM px (y down, the baseline at 0)."""
    key = (path, ch)
    got = _glyphs.get(key)
    if got is None:
        raw = _raw_font(path)
        got = []
        if raw.isValid():
            for index in raw.glyphIndexesForString(ch)[:1]:
                for poly in raw.pathForGlyph(index).toSubpathPolygons(QTransform()):
                    pts = np.array([(p.x(), p.y()) for p in poly], float)
                    got.append(clean(pts))
        got = [c for c in got if len(c) >= 3]
        _glyphs[key] = got
    return got


def clean(pts, tol=0.05):
    """A polygon without points on top of each other (nor a last one on the first)."""
    if not len(pts):
        return pts
    keep = [pts[0]]
    for q in pts[1:]:
        if np.abs(q - keep[-1]).max() > tol:
            keep.append(q)
    if len(keep) > 1 and np.abs(keep[-1] - keep[0]).max() <= tol:
        keep.pop()
    return np.array(keep)


def triangulate(contours):
    """(m, 3, 2): triangles that cover what the closed polygons fill (non-zero winding)."""
    edges = []
    for c in contours:
        for a, b in zip(c, np.roll(c, -1, axis=0)):
            if abs(a[1] - b[1]) > 1e-9:
                top, bottom = (a, b) if a[1] < b[1] else (b, a)
                edges.append((top[1], bottom[1], top[0], (bottom[0] - top[0]) / (bottom[1] - top[1]), 1 if a[1] < b[1] else -1))
    if not edges:
        return np.zeros((0, 3, 2))
    e = np.array(edges)
    ys = np.unique(np.concatenate([e[:, 0], e[:, 1]]))
    out = []
    for y0, y1 in zip(ys[:-1], ys[1:]):
        if y1 - y0 < 1e-7:
            continue
        mid = (y0 + y1) / 2.0
        live = e[(e[:, 0] < mid) & (e[:, 1] > mid)]
        if not len(live):
            continue
        order = np.argsort(live[:, 2] + (mid - live[:, 0]) * live[:, 3])
        live = live[order]
        wind, start = 0, None
        for edge in live:
            before, wind = wind, wind + int(edge[4])
            if before == 0 and wind != 0:
                start = edge
            elif before != 0 and wind == 0:
                at = lambda edge_, y: edge_[2] + (y - edge_[0]) * edge_[3]
                a, b, c, d = (at(start, y0), y0), (at(edge, y0), y0), (at(edge, y1), y1), (at(start, y1), y1)
                if b[0] - a[0] > 1e-7:
                    out.append((a, b, c))
                if c[0] - d[0] > 1e-7:
                    out.append((a, c, d))
    return np.array(out, float) if out else np.zeros((0, 3, 2))


def winding(contours, p):
    """The winding number of the polygons round point p."""
    n = 0
    for c in contours:
        a, b = c, np.roll(c, -1, axis=0)
        up = (a[:, 1] <= p[1]) & (b[:, 1] > p[1])
        down = (b[:, 1] <= p[1]) & (a[:, 1] > p[1])
        side = (b[:, 0] - a[:, 0]) * (p[1] - a[:, 1]) - (p[0] - a[:, 0]) * (b[:, 1] - a[:, 1])
        n += int(np.sum(up & (side > 0))) - int(np.sum(down & (side < 0)))
    return n


def _outward(c, contours):
    """+1 when the outward side of polygon c is the (dy, -dx) of its edges, -1 when the other one (told by what is filled beside
    its longest edge)."""
    d = np.roll(c, -1, axis=0) - c
    lengths = np.hypot(d[:, 0], d[:, 1])
    i = int(np.argmax(lengths))
    n = np.array([d[i, 1], -d[i, 0]]) / max(lengths[i], 1e-9)
    mid = c[i] + d[i] / 2.0
    return -1.0 if winding(contours, mid + n * 0.01) != 0 else 1.0


def _edge_normals(c, sign):
    d = np.roll(c, -1, axis=0) - c
    n = np.stack([d[:, 1], -d[:, 0]], axis=1) * sign
    return n / np.maximum(np.hypot(n[:, 0], n[:, 1]), 1e-9)[:, None]


def _inset(c, normals, by):
    """Polygon c with every corner moved `by` inwards (normals: its edges' outward ones): along the corner's middle line, as far as
    keeps the edges that far (not more than twice as far at a sharp one)."""
    before = np.roll(normals, 1, axis=0)
    m = before + normals
    k = 1.0 + np.sum(before * normals, axis=1)
    m = m / np.maximum(k, 0.5)[:, None]
    return c - m * by


def _quad(out, p, n, color):
    """Two triangles of the four corners p (in turn round it) with their normals n."""
    for i in (0, 1, 2, 0, 2, 3):
        out.append((*p[i], *n[i], *color))


def extrude(contours, depth, bevel, bevel_steps, face, side):
    """The mesh of the polygons `contours` (px) pushed out `depth` px (the front at z = -depth / 2), with the corners of both faces
    rounded off over `bevel` px in bevel_steps strips. face, side: colours (r, g, b, a)."""
    contours = [c for c in contours if len(c) >= 3]
    if not contours:
        return np.zeros((0, 10), "f4")
    depth = max(float(depth), 0.0)
    bevel = max(0.0, min(float(bevel), depth / 2.0))
    steps = max(1, int(bevel_steps)) if bevel > 0 else 0
    signs = [_outward(c, contours) for c in contours]
    edge_n = [_edge_normals(c, s) for c, s in zip(contours, signs)]
    front, back = -depth / 2.0, depth / 2.0
    out = []
    caps = [_inset(c, n, bevel) for c, n in zip(contours, edge_n)] if steps else contours
    for tri in triangulate(caps):
        for z, nz, order in ((front, -1.0, (0, 1, 2)), (back, 1.0, (0, 2, 1))):
            for i in order:
                out.append((tri[i][0], tri[i][1], z, 0.0, 0.0, nz, *face))
    if depth <= 0:
        return np.array(out, "f4")
    # the profile from the front face's edge to the back face's: (how far in, z, share of the normal that is sideways, forwards)
    profile = []
    for i in range(steps + 1):
        a = (math.pi / 2.0) * i / steps if steps else math.pi / 2.0
        profile.append((bevel * (1 - math.sin(a)), front + bevel * (1 - math.cos(a)), math.sin(a), -math.cos(a)))
    if not steps:
        profile = [(0.0, front, 1.0, 0.0)]
    profile += [(inn, -z, s, -nz) for inn, z, s, nz in reversed(profile)]
    for c, normals in zip(contours, edge_n):
        count = len(c)
        before, after = np.roll(normals, 1, axis=0), np.roll(normals, -1, axis=0)
        rings = [(_inset(c, normals, inn) if inn else c, z, s, nz) for inn, z, s, nz in profile]
        for i in range(count):
            j = (i + 1) % count
            n = normals[i]
            ni, nj = n, n                                   # (a corner shared with a side nearly in line is shaded as a curve)
            if float(n @ before[i]) > SMOOTH_COS:
                ni = (n + before[i]) / np.linalg.norm(n + before[i])
            if float(n @ after[i]) > SMOOTH_COS:
                nj = (n + after[i]) / np.linalg.norm(n + after[i])
            for (p0, z0, s0, f0), (p1, z1, s1, f1) in zip(rings, rings[1:]):
                if abs(z1 - z0) < 1e-6 and np.abs(p1[i] - p0[i]).max() < 1e-6:
                    continue
                color = face if abs(f0) > 0.99 or abs(f1) > 0.99 else side
                _quad(out, ((p0[i][0], p0[i][1], z0), (p0[j][0], p0[j][1], z0), (p1[j][0], p1[j][1], z1), (p1[i][0], p1[i][1], z1)),
                      ((ni[0] * s0, ni[1] * s0, f0), (nj[0] * s0, nj[1] * s0, f0), (nj[0] * s1, nj[1] * s1, f1), (ni[0] * s1, ni[1] * s1, f1)),
                      color)
    return np.array(out, "f4")


def text_letters(spec, canvas_h):
    """[(contours in canvas px about the middle of the text, (r, g, b, 1))] of the letters of text spec - where the flat text has them."""
    lay = textlayout._layout(spec, 1.0, canvas_h)
    lines, fw = lay["lines"], lay["fw"]
    shear = math.tan(math.radians(spec.get("italic_deg", 0.0)))
    align = spec.get("align") or "center"
    out = []
    for li, (glyphs, lw) in enumerate(lines):
        left = -fw / 2.0
        ox = {"left": left, "justify": left, "right": left + fw - lw}.get(align, -lw / 2.0)
        spread = (fw - lw) / (len(glyphs) - 1) if align == "justify" and li < len(lines) - 1 and len(glyphs) > 1 else 0.0
        baseline = lay["ct"] + lay["ext_top"] + li * lay["step"] + lay["asc"]
        for gi, (gx, ch, f, rgba, _adv) in enumerate(glyphs):
            if ch.isspace() or not isinstance(f.path, str):
                continue
            k = f.size / EM
            moved = []
            for c in contours_of(f.path, ch):
                p = c * k + (ox + gx + gi * spread, baseline)
                if shear:
                    p = p - np.stack([shear * p[:, 1], np.zeros(len(p))], axis=1)
                moved.append(p)
            if moved:
                out.append((moved, tuple(v / 255.0 for v in rgba[:3]) + (1.0,)))
    return out


def text_mesh(spec, canvas_h, depth, bevel, bevel_steps=3, side=None):
    """The mesh of text spec made solid: depth and bevel in canvas px, side: the colour (r, g, b) of the sides (None: the letters' own).
    Kept while nothing of it changes."""
    key = (json.dumps(spec, sort_keys=True, default=str), canvas_h, round(depth, 3), round(bevel, 3), bevel_steps,
           None if side is None else tuple(round(v, 4) for v in side))
    got = _meshes.get(key)
    if got is None:
        parts = [extrude(contours, depth, bevel, bevel_steps, color, color if side is None else (*side[:3], 1.0))
                 for contours, color in text_letters(spec, canvas_h)]
        got = np.concatenate(parts) if parts else np.zeros((0, 10), "f4")
        while len(_meshes) >= MAX_MESHES:
            _meshes.pop(next(iter(_meshes)))
        _meshes[key] = got
    return got
