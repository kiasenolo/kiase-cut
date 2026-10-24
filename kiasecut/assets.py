"""Built-in assets (內建素材): solid colours, gradients and basic shapes, made as SVG pictures.

A clip made from one is a picture clip that also holds its parameters:

clip["asset"] = {key, family, w, h, color, ...}   key: the preset it came from; family: what
                is drawn (solid, gradient, rect, ellipse, polygon, star, heart, arrow, line);
                w, h: its size in canvas pixels; the rest depends on the family (FIELDS)

Unlike other pictures, which are fitted into the canvas, an asset clip is drawn at its own
size (project.picture_size), so 寬 / 高 are canvas pixels and corners or outlines keep their
thickness when it is resized. Every change of parameters draws a new SVG into the project's
Media/.內建素材 folder (hidden from the media library), named after its content, so undo
only has to point the clip back at the earlier file.

The 內建素材 tab names a preset on its drag data as "asset:<key>:<colour 1>:<colour 2>":
presets carry their own colours, the 自訂 ones and every shape take the tab's two colours.
"""
import copy
import hashlib
import math
import os
import re

FOLDER = ".內建素材"
PREFIX = "asset:"
CATEGORIES = [("solid", "純色"), ("gradient", "漸變色"), ("shape", "基礎形狀")]
DEFAULT_COLORS = ("#ffffff", "#000000")
SHAPE_PX = 400                             # a new shape's size on a 1080-high canvas

# field: label, kind, min, max, step, decimals
FIELD_INFO = {
    "w": ("寬", "number", 1, 16384, 1, 0),
    "h": ("高", "number", 1, 16384, 1, 0),
    "color": ("顏色", "color"),
    "color2": ("顏色 2", "color"),
    "gtype": ("漸變類型", "choice", (("線性", "linear"), ("放射", "radial"))),
    "angle": ("角度 °", "number", -360, 360, 1, 0),
    "radius": ("圓角", "number", 0, 8192, 1, 0),
    "sides": ("邊數", "number", 3, 24, 1, 0),
    "points": ("角數", "number", 3, 24, 1, 0),
    "inner": ("內徑 %", "number", 5, 95, 1, 0),
    "outline": ("樣式", "choice", (("填滿", False), ("外框", True))),
    "stroke": ("邊框粗細", "number", 1, 2000, 1, 0),
}
_OUTLINE = ("outline", "stroke")
FIELDS = {                                 # what each family has besides w, h and color
    "solid": (),
    "gradient": ("color2", "gtype", "angle"),
    "rect": ("radius",) + _OUTLINE,
    "ellipse": _OUTLINE,
    "polygon": ("sides",) + _OUTLINE,
    "star": ("points", "inner") + _OUTLINE,
    "heart": _OUTLINE,
    "arrow": _OUTLINE,
    "line": (),
}
NAMES = {"solid": "純色", "gradient": "漸變", "rect": "矩形", "ellipse": "橢圓", "polygon": "多邊形",
         "star": "星形", "heart": "心形", "arrow": "箭頭", "line": "線條"}


class Asset:
    """A preset of the 內建素材 tab."""

    def __init__(self, key, cat, name, family, colors=None, **params):
        self.key = key
        self.cat = cat
        self.name = name
        self.family = family
        self.colors = colors               # fixed (c1, c2), or None: the tab's colours
        self.params = params               # family parameters; sizes in px of a 1080-high canvas

    @property
    def custom(self):
        return self.colors is None


_SOLIDS = [("白", "#ffffff"), ("黑", "#000000"), ("灰", "#808080"), ("紅", "#e53935"), ("橙", "#fb8c00"),
           ("黃", "#fdd835"), ("綠", "#43a047"), ("青", "#00acc1"), ("藍", "#1e88e5"), ("紫", "#8e24aa"),
           ("粉", "#ec407a")]
_GRADIENTS = [("日落", "#ff5f6d", "#ffc371", "linear", 30), ("海洋", "#2193b0", "#6dd5ed", "linear", 90),
              ("森林", "#134e5e", "#71b280", "linear", 30), ("紫霞", "#8e2de2", "#4a00e0", "linear", 30),
              ("桃粉", "#ee9ca7", "#ffdde1", "linear", 90), ("夜空", "#0f2027", "#2c5364", "linear", 90),
              ("黑白", "#000000", "#ffffff", "linear", 0),
              ("底部黑色漸層", "#00000000", "#000000cc", "linear", 90),      # behind subtitles
              ("暗角", "#00000000", "#000000d9", "radial", 0)]
_CUSTOM_GRADIENTS = [("橫向漸變", "linear", 0), ("直向漸變", "linear", 90), ("斜向漸變", "linear", 30),
                     ("放射漸變", "radial", 0)]
S = SHAPE_PX
_SHAPES = [("rect", "矩形", "rect", {}), ("roundrect", "圓角矩形", "rect", {"radius": 64}),
           ("circle", "圓形", "ellipse", {}), ("triangle", "三角形", "polygon", {"sides": 3}),
           ("diamond", "菱形", "polygon", {"sides": 4}), ("pentagon", "五邊形", "polygon", {"sides": 5}),
           ("hexagon", "六邊形", "polygon", {"sides": 6}), ("star", "星形", "star", {"points": 5, "inner": 40}),
           ("heart", "心形", "heart", {}), ("arrow", "箭頭", "arrow", {"w": 480, "h": 300}),
           ("ring", "圓環", "ellipse", {"outline": True, "stroke": 64}),
           ("rectframe", "外框矩形", "rect", {"outline": True, "stroke": 24}),
           ("circleframe", "外框圓形", "ellipse", {"outline": True, "stroke": 24}),
           ("line", "線條", "line", {"w": 800, "h": 16})]

ASSETS = ([Asset(f"solid.{i}", "solid", name, "solid", (c, c)) for i, (name, c) in enumerate(_SOLIDS)]
          + [Asset("solid.custom", "solid", "自訂純色", "solid")]
          + [Asset(f"gradient.{i}", "gradient", name, "gradient", (a, b), gtype=g, angle=ang)
             for i, (name, a, b, g, ang) in enumerate(_GRADIENTS)]
          + [Asset(f"gradient.custom.{i}", "gradient", name, "gradient", gtype=g, angle=ang)
             for i, (name, g, ang) in enumerate(_CUSTOM_GRADIENTS)]
          + [Asset(f"shape.{k}", "shape", name, fam, **p) for k, name, fam, p in _SHAPES])
_BY_KEY = {a.key: a for a in ASSETS}


def get(key):
    return _BY_KEY.get(key)


_HEX = re.compile(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")


def clean_color(c, default="#ffffff"):
    """#rrggbb or #rrggbbaa (lower case), else the default."""
    c = (c or "").strip() if isinstance(c, str) else ""
    return c.lower() if _HEX.match(c) else default


def ident(key, c1, c2):
    return f"{PREFIX}{key}:{clean_color(c1)}:{clean_color(c2, '#000000')}"


def parse(text):
    """(preset, colour 1, colour 2) from an ident(), or None."""
    if not text.startswith(PREFIX):
        return None
    parts = text[len(PREFIX):].split(":")
    a = get(parts[0])
    if a is None:
        return None
    c1 = clean_color(parts[1] if len(parts) > 1 else "", DEFAULT_COLORS[0])
    c2 = clean_color(parts[2] if len(parts) > 2 else "", DEFAULT_COLORS[1])
    return a, c1, c2


# -- parameters -------------------------------------------------------------------------------------
def make(a, c1, c2, canvas_w, canvas_h):
    """The parameters (clip["asset"]) of a new clip of preset a on a canvas_w x canvas_h canvas:
    solids and gradients fill it, shapes keep their size relative to its height."""
    c1, c2 = a.colors if a.colors else (c1, c2)
    p = {"key": a.key, "family": a.family, "color": clean_color(c1)}
    if a.family == "gradient":
        p.update(color2=clean_color(c2, "#000000"), gtype="linear", angle=0)
    for f in FIELDS[a.family]:
        p.setdefault(f, {"outline": False, "stroke": 24, "radius": 0, "sides": 6, "points": 5,
                         "inner": 40}.get(f))
    k = canvas_h / 1080
    if a.cat == "shape":
        p.update(w=S, h=S)
    for f, v in a.params.items():
        p[f] = v
    if a.cat == "shape":
        for f in ("w", "h", "radius", "stroke"):
            if f in p:
                p[f] = max(1, round(p[f] * k)) if f in ("w", "h") else round(p[f] * k)
    else:
        p.update(w=int(canvas_w), h=int(canvas_h))
    return normalize(p)


def normalize(p):
    """Parameters made valid: known family, numbers in range, colours as #rrggbb[aa]; fields
    the family does not have are dropped."""
    fam = p.get("family") if p.get("family") in FIELDS else "rect"
    out = {"key": str(p.get("key") or fam), "family": fam}
    for f in ("w", "h", "color") + FIELDS[fam]:
        info = FIELD_INFO[f]
        v = p.get(f)
        if info[1] == "color":
            out[f] = clean_color(v, "#000000" if f == "color2" else "#ffffff")
        elif info[1] == "choice":
            vals = [x for _n, x in info[2]]
            out[f] = v if v in vals else vals[0]
        else:
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = info[2]
            v = min(max(v, info[2]), info[3])
            out[f] = int(round(v)) if info[5] == 0 else v
    return out


def name_of(p):
    preset = get(p.get("key", ""))
    return preset.name if preset else NAMES.get(p.get("family"), "素材")


# -- drawing --------------------------------------------------------------------------------------
def _alpha(c):
    """(#rrggbb, opacity) of #rrggbb[aa] (Qt's SVG reader wants the alpha apart)."""
    return c[:7], (int(c[7:], 16) / 255 if len(c) == 9 else 1.0)


def _paint(c, outline, stroke):
    rgb, op = _alpha(c)
    if outline:
        return (f'fill="none" stroke="{rgb}" stroke-width="{stroke:g}" stroke-linejoin="round"'
                + (f' stroke-opacity="{op:.3f}"' if op < 1 else ""))
    return f'fill="{rgb}"' + (f' fill-opacity="{op:.3f}"' if op < 1 else "")


def _stop(offset, c):
    rgb, op = _alpha(c)
    return f'<stop offset="{offset}" stop-color="{rgb}" stop-opacity="{op:.3f}"/>'


def _svg(w, h, body, defs=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">\n'
            + (f"<defs>{defs}</defs>\n" if defs else "") + body + "\n</svg>\n")


def _gradient(p, w, h):
    a, b = p["color"], p["color2"]
    if p["gtype"] == "radial":            # from the centre to the corners; the middle third holds colour 1
        g = (f'<radialGradient id="g" cx="{w / 2:g}" cy="{h / 2:g}" r="{math.hypot(w, h) / 2:.1f}" '
             f'gradientUnits="userSpaceOnUse">{_stop(0.35, a)}{_stop(1, b)}</radialGradient>')
    else:                                  # 0° left to right, 90° top to bottom, across the whole box
        r = math.radians(p["angle"])
        dx, dy = math.cos(r), math.sin(r)
        half = (abs(dx) * w + abs(dy) * h) / 2
        x1, y1, x2, y2 = w / 2 - dx * half, h / 2 - dy * half, w / 2 + dx * half, h / 2 + dy * half
        g = (f'<linearGradient id="g" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
             f'gradientUnits="userSpaceOnUse">{_stop(0, a)}{_stop(1, b)}</linearGradient>')
    return _svg(w, h, f'<rect width="{w}" height="{h}" fill="url(#g)"/>', g)


def _star_points(n, inner):
    """Unit-circle points of a regular polygon (inner None) or star, the first at the top."""
    m = n * (2 if inner else 1)
    return [((inner if inner and i % 2 else 1.0) * math.cos(math.radians(-90 + i * 360 / m)),
             (inner if inner and i % 2 else 1.0) * math.sin(math.radians(-90 + i * 360 / m))) for i in range(m)]


def _fit(pts, x0, y0, bw, bh):
    """Points stretched to fill the box (x0, y0, bw, bh)."""
    xs, ys = [x for x, _ in pts], [y for _, y in pts]
    lx, ly = (max(xs) - min(xs)) or 1, (max(ys) - min(ys)) or 1
    return [(x0 + (x - min(xs)) / lx * bw, y0 + (y - min(ys)) / ly * bh) for x, y in pts]


_HEART = [(0.5, 0.92), (0.12, 0.66), (0.0, 0.47), (0.0, 0.29), (0.0, 0.13), (0.12, 0.04), (0.26, 0.04),
          (0.37, 0.04), (0.45, 0.11), (0.5, 0.2), (0.55, 0.11), (0.63, 0.04), (0.74, 0.04), (0.88, 0.04),
          (1.0, 0.13), (1.0, 0.29), (1.0, 0.47), (0.88, 0.66), (0.5, 0.92)]
_ARROW = [(0, 0.35), (0.6, 0.35), (0.6, 0.12), (1, 0.5), (0.6, 0.88), (0.6, 0.65), (0, 0.65)]


def _shape(p, w, h):
    fam, c = p["family"], p["color"]
    outline = p.get("outline", False)
    s = min(p.get("stroke", 0), w / 2, h / 2) if outline else 0
    paint = _paint(c, outline, s)
    x0, y0, bw, bh = s / 2, s / 2, w - s, h - s           # an outline stays inside the box
    pts = lambda q: " ".join(f"{x:.1f},{y:.1f}" for x, y in q)
    if fam in ("rect", "line"):
        r = min(p.get("radius", 0), bw / 2, bh / 2)
        body = f'<rect x="{x0:g}" y="{y0:g}" width="{bw:g}" height="{bh:g}"' + (f' rx="{r:g}"' if r else "") + f" {paint}/>"
    elif fam == "ellipse":
        body = f'<ellipse cx="{w / 2:g}" cy="{h / 2:g}" rx="{bw / 2:g}" ry="{bh / 2:g}" {paint}/>'
    elif fam in ("polygon", "star"):
        unit = _star_points(p["points"], p["inner"] / 100) if fam == "star" else _star_points(p["sides"], None)
        body = f'<polygon points="{pts(_fit(unit, x0, y0, bw, bh))}" {paint}/>'
    elif fam == "arrow":
        body = f'<polygon points="{pts([(x0 + x * bw, y0 + y * bh) for x, y in _ARROW])}" {paint}/>'
    else:                                  # heart: cubic segments through _HEART
        q = [(x0 + x * bw, y0 + (y - 0.04) / 0.88 * bh) for x, y in _HEART]
        d = f"M{q[0][0]:.1f} {q[0][1]:.1f} " + " ".join(
            "C " + " ".join(f"{x:.1f} {y:.1f}" for x, y in q[i:i + 3]) for i in range(1, len(q), 3)) + " Z"
        body = f'<path d="{d}" {paint}/>'
    return _svg(w, h, body)


def svg(p):
    """The SVG text of asset parameters p (normalized)."""
    w, h = p["w"], p["h"]
    if p["family"] == "solid":
        return _svg(w, h, f'<rect width="{w}" height="{h}" {_paint(p["color"], False, 0)}/>')
    if p["family"] == "gradient":
        return _gradient(p, w, h)
    return _shape(p, w, h)


def store(media_dir, p):
    """Write the SVG of p into media_dir/.內建素材, named after its content (an identical one
    is reused). Returns its path."""
    text = svg(p)
    d = os.path.join(media_dir, FOLDER)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{p['family']}-{hashlib.sha1(text.encode('utf-8')).hexdigest()[:12]}.svg")
    if not os.path.exists(path):
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(path + ".tmp", path)
    return path.replace("\\", "/")


def item(p, path):
    """A library-item-like dict for placing or replacing with asset p (stored at path)."""
    return {"kind": "image", "name": name_of(p), "path": path, "width": p["w"], "height": p["h"]}


def restore(clips, media_dir):
    """Draw again the asset files that are missing (a cleaned Media folder, a project copied
    without hidden files). Returns [(old path, new path)] of the clips that changed."""
    out = []
    for c in clips:
        p = c.get("asset")
        if p and not os.path.exists((c.get("media") or {}).get("path") or ""):
            new = store(media_dir, normalize(p))
            out.append((c["media"].get("path"), new))
            c["media"] = {"path": new, "width": p["w"], "height": p["h"]}
    return out


def updated(p, fields):
    """p with fields changed (a deep copy, normalized)."""
    q = copy.deepcopy(p)
    q.update(fields)
    return normalize(q)
