"""Built-in assets (內建素材): solid colours, gradients and basic shapes, made as SVG pictures.

A clip made from one is a picture clip that also holds its parameters:

clip["asset"] = {key, family, w, h, color, ...}   key: the preset it came from; family: what
                is drawn (solid, gradient, rect, ellipse, polygon, star, heart, arrow,
                parallelogram, line); w, h: its size in canvas pixels; the rest depends on the
                family (FIELDS).
                Every field is a parameter like a clip's position: a value or a curve dict
                with keyframes (curves.py). Colours are [r, g, b, a] (0 - 1), so their
                keyframes blend; choices and switches (gtype, fill, stroke_align...) hold until
                the next keyframe.

Shapes have a fill (fill: on / off, in color) and an outline (stroke_on, in stroke_color,
stroke px wide - 0 draws none) that can be on together. Each is painted with fill_type /
stroke_type: a plain colour, a gradient (to fill_color2 / stroke_color2, linear at fill_angle
or radial; across the shape's w x h box) or a picture (fill_image / stroke_image: a file,
covering the box) or one of Blender's textures (textures.py, in the two colours, at *_scale and
moved by *_seed and *_z, a third direction the 3D patterns change smoothly along). stroke_align puts the outline inside
the shape's edge, on it or outside it; join shapes its corners (miter, round, bevel). An
ellipse can be an arc (arc_start °, clockwise from 3 o'clock; arc_sweep % of the full turn)
with a hole (ratio: the inner radius, % of the outer), as in Lunacy; a parallelogram leans
by skew °; a rectangle's and a star's corners are rounded by radius px (a star's inner ones
curve inwards). An outline outside or on the edge reaches past the w x h frame (overflow()): the
SVG is drawn that much larger, around the same centre. Older projects had outline (filled or
outline only): normalize() turns it into fill / stroke_on.

Unlike other pictures, which are fitted into the canvas, an asset clip is drawn at its own
size (project.picture_size), so 寬 / 高 are canvas pixels and corners or outlines keep their
thickness when it is resized. The renderers draw it from its parameters at each moment
(at(), svg()); the SVG written into the project's Media/.內建素材 folder (hidden from the
media library) when the clip is made only gives it a file, as every picture clip has.

The 內建素材 tab names a preset on its drag data as "asset:<key>:<colour 1>:<colour 2>":
presets carry their own colours, the 自訂 ones and every shape take the tab's two colours.
"""
import hashlib
import math
import os
import re

from . import curves, textures

FOLDER = ".內建素材"
PREFIX = "asset:"
CATEGORIES = [("solid", "純色"), ("gradient", "漸變色"), ("shape", "基礎形狀"), ("empty", "空物體")]
DEFAULT_COLORS = ("#ffffff", "#000000")
SHAPE_PX = 400                             # a new shape's size on a 1080-high canvas

PAINT_TYPES = (("純色", "solid"), ("漸變", "gradient"), ("圖片", "image"), ("Blender 棋盤格", "checker"),
               ("Blender 磚塊", "brick"), ("Blender 噪點", "noise"), ("Blender Voronoi", "voronoi"),
               ("Blender 波浪", "wave"), ("Blender Magic", "magic"))
GRADIENT_TYPES = (("線性", "linear"), ("放射", "radial"))

# field: label, kind, min, max, step, decimals (min / max: the soft limits a drag keeps to)
FIELD_INFO = {
    "w": ("寬", "number", 1, 16384, 1, 0),
    "h": ("高", "number", 1, 16384, 1, 0),
    "color": ("顏色", "color"),
    "color2": ("顏色 2", "color"),
    "gtype": ("漸變類型", "choice", GRADIENT_TYPES),
    "stops": ("漸變色", "stops"),
    "fill_stops": ("填充漸變色", "stops"),
    "stroke_stops": ("外框漸變色", "stops"),
    "angle": ("角度 °", "number", -360, 360, 1, 0),
    "radius": ("圓角", "number", 0, 8192, 1, 0),
    "sides": ("邊數", "number", 3, 24, 1, 0),
    "points": ("角數", "number", 3, 24, 1, 0),
    "inner": ("內徑 %", "number", 5, 95, 1, 0),
    "arc_start": ("開始 °", "number", -360, 360, 1, 0),
    "arc_sweep": ("弧掃 %", "number", 0, 100, 1, 1),
    "ratio": ("比例 %", "number", 0, 100, 1, 1),
    "fade": ("邊緣淡出 %", "number", 0, 100, 1, 0),
    "skew": ("斜度 °", "number", -80, 80, 1, 0),
    "gcols": ("欄數", "number", 1, 100, 1, 0),
    "grows": ("列數", "number", 1, 100, 1, 0),
    "gratio": ("格子比例 寬/高（0＝填滿）", "number", 0, 10, 0.05, 2),
    "gline": ("線寬 px", "number", 0.5, 200, 0.5, 1),
    "gleft": ("左外框", "toggle"),
    "gright": ("右外框", "toggle"),
    "gtop": ("上外框", "toggle"),
    "gbottom": ("下外框", "toggle"),
    "fill": ("填充", "toggle"),
    "fill_type": ("填充類型", "choice", PAINT_TYPES),
    "fill_color2": ("填充顏色 2", "color"),
    "fill_gtype": ("填充漸變", "choice", GRADIENT_TYPES),
    "fill_angle": ("填充漸變角度 °", "number", -360, 360, 1, 0),
    "fill_image": ("填充圖片", "image"),
    "fill_scale": ("填充材質比例", "number", 0.1, 100, 0.1, 2),
    "fill_seed": ("填充材質位置", "number", -1000, 1000, 0.1, 2),
    "fill_z": ("填充材質 Z", "number", -1000, 1000, 0.05, 2),
    "stroke_on": ("外框", "toggle"),
    "stroke_type": ("外框類型", "choice", PAINT_TYPES),
    "stroke_color": ("外框顏色", "color"),
    "stroke_color2": ("外框顏色 2", "color"),
    "stroke_gtype": ("外框漸變", "choice", GRADIENT_TYPES),
    "stroke_angle": ("外框漸變角度 °", "number", -360, 360, 1, 0),
    "stroke_image": ("外框圖片", "image"),
    "stroke_scale": ("外框材質比例", "number", 0.1, 100, 0.1, 2),
    "stroke_seed": ("外框材質位置", "number", -1000, 1000, 0.1, 2),
    "stroke_z": ("外框材質 Z", "number", -1000, 1000, 0.05, 2),
    "stroke": ("外框粗細", "number", 0, 2000, 1, 0),
    "nodes": ("路徑", "path"),                  # (the pen tool's nodes: not a field to edit by number)
    "closed": ("封閉路徑", "toggle"),
    "stroke_align": ("外框位置", "choice", (("內側", "inside"), ("居中", "center"), ("外側", "outside"))),
    "join": ("轉角", "choice", (("直角", "miter"), ("圓角", "round"), ("倒角", "bevel"))),
}
# the hard limits of numbers (typing or Alt-dragging reaches them; None: unlimited), when not
# the soft ones; clean() keeps values inside them
HARD = {"w": (1, 65536), "h": (1, 65536), "angle": (None, None), "radius": (0, None),
        "sides": (3, 100), "points": (3, 100), "inner": (1, 99), "stroke": (0, None),
        "arc_start": (None, None), "skew": (-89, 89), "gcols": (1, 500), "grows": (1, 500),
        "gratio": (0, 100), "gline": (0.1, None), "fill_scale": (0.01, 1000), "stroke_scale": (0.01, 1000),
        "fill_seed": (None, None), "stroke_seed": (None, None), "fill_z": (None, None), "stroke_z": (None, None)}


def hard_range(f):
    """(lo, hi) a number field can be typed to; None: no limit."""
    info = FIELD_INFO[f]
    return HARD.get(f, (info[2], info[3]))


FILL_PAINT = ("fill_type", "fill_color2", "fill_stops", "fill_gtype", "fill_angle", "fill_image", "fill_scale", "fill_seed", "fill_z")    # (beside color)
STROKE = ("fade", "fill", "stroke_on", "stroke_type", "stroke_color", "stroke_color2", "stroke_stops", "stroke_gtype", "stroke_angle",
          "stroke_image", "stroke_scale", "stroke_seed", "stroke_z", "stroke", "stroke_align", "join") + FILL_PAINT
FIELDS = {                                 # what each family has besides w, h and color
    "solid": (),
    "gradient": ("color2", "gtype", "angle", "stops"),
    "rect": ("radius",) + STROKE,
    "ellipse": ("arc_start", "arc_sweep", "ratio") + STROKE,
    "polygon": ("sides",) + STROKE,
    "star": ("points", "inner", "radius") + STROKE,
    "heart": STROKE,
    "arrow": STROKE,
    "parallelogram": ("skew",) + STROKE,
    "line": (),
    "path": ("nodes", "closed") + STROKE,
    "empty": (),
    "grid": ("gcols", "grows", "gratio", "gline", "gleft", "gright", "gtop", "gbottom", "fade"),
}
NAMES = {"solid": "純色", "gradient": "漸變", "rect": "矩形", "ellipse": "橢圓", "polygon": "多邊形",
         "star": "星形", "heart": "心形", "arrow": "箭頭", "parallelogram": "平行四邊形", "line": "線條", "grid": "網格", "path": "路徑", "empty": "空物體"}


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
EMPTY_COLOR = "#ff9800"                    # (what an empty is drawn in while editing)
# invisible layers to parent, anchor or hold effects on; sizes in px of a 1080-high canvas (full: the canvas)
_EMPTIES = [("small", "空物體 小", {"w": 100, "h": 100}), ("medium", "空物體 中", {"w": 400, "h": 400}),
            ("large", "空物體 大", {"w": 800, "h": 800}), ("wide", "空物體 橫幅", {"w": 1200, "h": 300}),
            ("tall", "空物體 直幅", {"w": 300, "h": 1200}), ("full", "空物體 滿版", {})]
_SHAPES = [("rect", "矩形", "rect", {}), ("roundrect", "圓角矩形", "rect", {"radius": 64}),
           ("circle", "圓形", "ellipse", {}), ("triangle", "三角形", "polygon", {"sides": 3}),
           ("diamond", "菱形", "polygon", {"sides": 4}), ("pentagon", "五邊形", "polygon", {"sides": 5}),
           ("hexagon", "六邊形", "polygon", {"sides": 6}), ("star", "星形", "star", {"points": 5, "inner": 40}),
           ("heart", "心形", "heart", {}), ("arrow", "箭頭", "arrow", {"w": 480, "h": 300}),
           ("parallelogram", "平行四邊形", "parallelogram", {"w": 480, "h": 300, "skew": 20}),
           ("arc", "扇形", "ellipse", {"arc_start": -90, "arc_sweep": 75}),
           ("ring", "圓環", "ellipse", {"ratio": 68}),
           ("rectframe", "外框矩形", "rect", {"fill": False, "stroke_on": True, "stroke": 24}),
           ("circleframe", "外框圓形", "ellipse", {"fill": False, "stroke_on": True, "stroke": 24}),
           ("line", "線條", "line", {"w": 800, "h": 16}),
           ("grid", "網格", "grid", {"w": 1440, "h": 810})]

ASSETS = ([Asset(f"solid.{i}", "solid", name, "solid", (c, c)) for i, (name, c) in enumerate(_SOLIDS)]
          + [Asset("solid.custom", "solid", "自訂純色", "solid")]
          + [Asset(f"gradient.{i}", "gradient", name, "gradient", (a, b), gtype=g, angle=ang)
             for i, (name, a, b, g, ang) in enumerate(_GRADIENTS)]
          + [Asset(f"gradient.custom.{i}", "gradient", name, "gradient", gtype=g, angle=ang)
             for i, (name, g, ang) in enumerate(_CUSTOM_GRADIENTS)]
          + [Asset(f"shape.{k}", "shape", name, fam, **p) for k, name, fam, p in _SHAPES]
          + [Asset("path.pen", "path", "路徑", "path")]               # (made by the pen tool, not listed in the tab)
          + [Asset(f"empty.{k}", "empty", name, "empty", (EMPTY_COLOR, EMPTY_COLOR), **p) for k, name, p in _EMPTIES])
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
def to_rgba(c, default=(1.0, 1.0, 1.0, 1.0)):
    """[r, g, b, a] (0 - 1) of #rrggbb[aa] or of such a list; else the default."""
    if isinstance(c, (list, tuple)) and len(c) in (3, 4):
        try:
            v = [min(1.0, max(0.0, float(x))) for x in c]
        except (TypeError, ValueError):
            return list(default)
        return v + [1.0] * (4 - len(v))
    c = clean_color(c, "")
    if not c:
        return list(default)
    return [int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)] + [int(c[7:], 16) / 255 if len(c) == 9 else 1.0]


def hex_of(rgba):
    """#rrggbb, or #rrggbbaa when not opaque."""
    v = [round(min(1.0, max(0.0, x)) * 255) for x in to_rgba(rgba)]
    return "#" + "".join(f"{x:02x}" for x in v[:3]) + (f"{v[3]:02x}" if v[3] < 255 else "")


def fields_of(family):
    """Every parameter a family has (FIELDS plus size and colour)."""
    return ("w", "h", "color") + FIELDS.get(family, ())


def clean(f, v):
    """One value of field f as it is stored: a colour as [r, g, b, a], a choice that exists,
    a number in range (sides and points are rounded when drawn)."""
    info = FIELD_INFO[f]
    if info[1] == "path":
        return _nodes(v)
    if info[1] == "color":
        return to_rgba(v, (0.0, 0.0, 0.0, 1.0) if f in ("color2", "stroke_color", "fill_color2", "stroke_color2")
                       else (1.0, 1.0, 1.0, 1.0))
    if info[1] == "stops":
        return _stops(v)
    if info[1] == "image":
        return v.replace("\\", "/") if isinstance(v, str) else ""
    if info[1] == "toggle":
        return bool(_DEFAULTS.get(f) if v is None else v)
    if info[1] == "choice":
        vals = [x for _n, x in info[2]]
        return v if v in vals else vals[0]
    try:
        v = float(v)
    except (TypeError, ValueError):
        v = float(info[2])
    lo, hi = hard_range(f)
    return min(max(v, -math.inf if lo is None else lo), math.inf if hi is None else hi)


def _nodes(v):
    """A pen path's nodes [[x, y, in dx, in dy, out dx, out dy], ...] as stored: floats, in the units of its w x h box (0 - 1 across it,
    the handles as offsets from their node), or [] if v is not such a list."""
    out = []
    try:
        for n in v or ():
            n = [float(x) for x in n]
            if len(n) == 6 and all(math.isfinite(x) for x in n):
                out.append(n)
    except (TypeError, ValueError):
        return []
    return out[:5000]


def _stops(v):
    """A gradient's colour stops [[position 0 - 1, [r, g, b, a]], ...] in order, or [] (no stops of its
    own: the gradient goes from its colour to its colour 2)."""
    try:
        st = sorted(([min(1.0, max(0.0, float(x))), to_rgba(c)] for x, c in v), key=lambda q: q[0])
    except (TypeError, ValueError):
        return []
    return st if len(st) >= 2 else []


def stops_of(p, pre=""):
    """The colour stops [(position, #rrggbb[aa])] a gradient of p (as at() gives it) is made of: its own,
    or its two colours at 0 and 1. pre: "fill" / "stroke" for a shape's paint, "" for a gradient asset."""
    own = p.get((pre + "_" if pre else "") + "stops") or []
    if own:
        return [(x, c) for x, c in own]
    a = p.get("color") if pre in ("", "fill") else p.get("stroke_color", "#000000")
    return [(0.0, a), (1.0, p.get((pre + "_" if pre else "") + "color2", "#000000"))]


def make(a, c1, c2, canvas_w, canvas_h):
    """The parameters (clip["asset"]) of a new clip of preset a on a canvas_w x canvas_h canvas:
    solids and gradients fill it, shapes keep their size relative to its height."""
    c1, c2 = a.colors if a.colors else (c1, c2)
    p = {"key": a.key, "family": a.family, "color": clean_color(c1)}
    if a.family == "gradient":
        p.update(color2=clean_color(c2, "#000000"), gtype="linear", angle=0)
    if "stroke_color" in FIELDS[a.family]:                 # the tab's second colour outlines
        p["stroke_color"] = clean_color(c2, "#000000")
    for f in FIELDS[a.family]:
        p.setdefault(f, _DEFAULTS.get(f))
    k = canvas_h / 1080
    if a.cat == "shape":
        p.update(w=S, h=S)
    for f, v in a.params.items():
        p[f] = v
    if a.cat == "empty" and not a.params:                  # (滿版)
        p.update(w=int(canvas_w), h=int(canvas_h))
    elif a.cat in ("shape", "empty"):
        for f in ("w", "h", "radius", "stroke", "gline"):
            if f in p:
                p[f] = max(1, round(p[f] * k)) if f in ("w", "h") else round(p[f] * k)
    else:
        p.update(w=int(canvas_w), h=int(canvas_h))
    return normalize(p)


def _migrate(p):
    """Parameters of an older project (outline: filled or outline only) as fill / stroke_on;
    others as they are."""
    if "gborder" in p:                                      # (one switch for all four edges, before they had their own)
        p = dict(p)
        on = p.pop("gborder")
        p.update(gleft=on, gright=on, gtop=on, gbottom=on)
    if "outline" not in p or "fill" in p:
        return p
    p = dict(p)
    o = p.pop("outline")
    o = bool(o["keys"][0][1]) if curves.is_animated(o) else bool(o)
    p.update(fill=not o, stroke_on=o, stroke_color=p.get("color"), stroke_align="inside", join="round")
    return p


def normalize(p):
    """Parameters made valid (clean() for every value and keyframe); fields the family does
    not have are dropped, missing ones get a default."""
    p = _migrate(p)
    fam = p.get("family") if p.get("family") in FIELDS else "rect"
    out = {"key": str(p.get("key") or fam), "family": fam}
    for f in fields_of(fam):
        v = p.get(f)
        if curves.is_animated(v):
            out[f] = {"keys": [[k[0], clean(f, k[1])] + list(k[2:]) for k in v["keys"]]}
        else:
            out[f] = clean(f, v if v is not None else _DEFAULTS.get(f))
    return out


_DEFAULTS = {"fill": True, "stroke_on": False, "stroke": 8, "stroke_align": "inside", "join": "miter",
             "stroke_color": "#000000", "radius": 0, "sides": 6, "points": 5, "inner": 40, "angle": 0,
             "arc_start": 0, "arc_sweep": 100, "ratio": 0, "skew": 20, "fade": 0,
             "gcols": 16, "grows": 9, "gratio": 0, "gline": 4, "gleft": True, "gright": True, "gtop": True, "gbottom": True,
             "gtype": "linear", "w": SHAPE_PX, "h": SHAPE_PX, "nodes": [], "closed": False,
             "fill_type": "solid", "fill_color2": "#000000", "fill_gtype": "linear", "fill_angle": 0, "fill_image": "",
             "stroke_type": "solid", "stroke_color2": "#ffffff", "stroke_gtype": "linear", "stroke_angle": 0,
             "stroke_image": "",
             "fill_stops": [], "stroke_stops": [], "stops": [],
             "fill_scale": 5, "fill_seed": 0, "stroke_scale": 5, "stroke_seed": 0, "fill_z": 0, "stroke_z": 0}


def at(p, t):
    """The parameters at clip time t, ready to draw: plain values, colours as #rrggbb[aa],
    sides and points whole."""
    p = _migrate(p)
    fam = p.get("family") if p.get("family") in FIELDS else "rect"
    out = {"key": p.get("key"), "family": fam}
    for f in fields_of(fam):
        v = clean(f, curves.value(p[f], t) if f in p else _DEFAULTS.get(f))
        if FIELD_INFO[f][1] == "color":
            v = hex_of(v)
        elif FIELD_INFO[f][1] == "stops":
            v = [[x, hex_of(c)] for x, c in v]
        elif f in ("sides", "points", "gcols", "grows"):
            v = int(round(v))
        elif f in ("w", "h"):
            v = round(v, 2)
        out[f] = v
    return out


def size_at(p, t):
    """(w, h) in canvas px at clip time t."""
    q = at(p, t)
    return q["w"], q["h"]


def animated(p):
    return bool(p) and any(curves.is_animated(v) for v in p.values())


def name_of(p):
    preset = get(p.get("key", ""))
    return preset.name if preset else NAMES.get(p.get("family"), "素材")


# -- drawing --------------------------------------------------------------------------------------
def _alpha(c):
    """(#rrggbb, opacity) of #rrggbb[aa] (Qt's SVG reader wants the alpha apart)."""
    return c[:7], (int(c[7:], 16) / 255 if len(c) == 9 else 1.0)


def _fill(c):
    rgb, op = _alpha(c)
    return f'fill="{rgb}"' + (f' fill-opacity="{op:.3f}"' if op < 1 else "")


def _stop(offset, c):
    rgb, op = _alpha(c)
    return f'<stop offset="{offset}" stop-color="{rgb}" stop-opacity="{op:.3f}"/>'


def _svg(w, h, body, defs="", pad=0.0):
    """An SVG document of a w x h asset; pad: room around it for an outline reaching out."""
    vb = f"{-pad:g} {-pad:g} {w + 2 * pad:g} {h + 2 * pad:g}" if pad else f"0 0 {w} {h}"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{w + 2 * pad:g}" height="{h + 2 * pad:g}" viewBox="{vb}">\n'
            + (f"<defs>{defs}</defs>\n" if defs else "") + body + "\n</svg>\n")


def _grad_def(gid, a, b, gtype, angle, w, h, stops=None):
    """The SVG gradient element gid from colour a to b across the w x h box - or along stops
    [(position, colour)] when it has its own."""
    if gtype == "radial":                 # from the centre to the corners; the middle third holds colour 1
        body = ("".join(_stop(x, c) for x, c in stops) if stops else f"{_stop(0.35, a)}{_stop(1, b)}")
        return (f'<radialGradient id="{gid}" cx="{w / 2:g}" cy="{h / 2:g}" r="{math.hypot(w, h) / 2:.1f}" '
                f'gradientUnits="userSpaceOnUse">{body}</radialGradient>')
    r = math.radians(angle)               # 0° left to right, 90° top to bottom, across the whole box
    dx, dy = math.cos(r), math.sin(r)
    half = (abs(dx) * w + abs(dy) * h) / 2
    x1, y1, x2, y2 = w / 2 - dx * half, h / 2 - dy * half, w / 2 + dx * half, h / 2 + dy * half
    return (f'<linearGradient id="{gid}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'gradientUnits="userSpaceOnUse">'
            + ("".join(_stop(x, c) for x, c in stops) if stops else f"{_stop(0, a)}{_stop(1, b)}") + '</linearGradient>')


def _gradient(p, w, h):
    g = _grad_def("g", p["color"], p["color2"], p["gtype"], p["angle"], w, h, p.get("stops") or None)
    return _svg(w, h, f'<rect width="{w}" height="{h}" fill="url(#g)"/>', g)


_PICTURES = {}                             # (path, mtime) -> data URI of the picture (at most 2048 px)
PICTURE_PX = 2048


def _picture(path):
    """A data URI of the picture file (scaled down to PICTURE_PX), or "" when it cannot be read."""
    try:
        key = (path, os.stat(path).st_mtime_ns)
    except OSError:
        return ""
    uri = _PICTURES.get(key)
    if uri is None:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
        from PySide6.QtGui import QImage
        from . import svgimage
        if svgimage.is_svg(path):
            try:
                sw, sh = svgimage.size(path)
                k = PICTURE_PX / max(sw, sh)
                im = svgimage.raster(path, sw * k, sh * k)
            except ValueError:
                im = QImage()
        else:
            im = QImage(path)
        if not im.isNull() and max(im.width(), im.height()) > PICTURE_PX:
            im = im.scaled(PICTURE_PX, PICTURE_PX, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        uri = ""
        if not im.isNull():
            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            im.save(buf, "PNG")
            uri = "data:image/png;base64," + bytes(buf.data().toBase64()).decode("ascii")
        if len(_PICTURES) >= 16:
            _PICTURES.pop(next(iter(_PICTURES)))
        _PICTURES[key] = uri
    return uri


def _texture(kind, w, h, scale, seed, z, c1, c2):
    """A data URI of Blender texture `kind` (textures.py) in colours c1, c2 for a w x h shape."""
    key = (kind, round(w), round(h), scale, seed, z, c1, c2)
    uri = _PICTURES.get(key)
    if uri is None:
        from PIL import Image
        import base64
        import io
        a = textures.render(kind, w, h, scale, seed, z, to_rgba(c1), to_rgba(c2, (0.0, 0.0, 0.0, 1.0)))
        buf = io.BytesIO()
        Image.fromarray(a, "RGBA").save(buf, "PNG")
        uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        if len(_PICTURES) >= 16:
            _PICTURES.pop(next(iter(_PICTURES)))
        _PICTURES[key] = uri
    return uri


def _paint(p, pre, w, h):
    """How the fill (pre "fill") or outline ("stroke") of p is painted: (kind, value, defs) -
    ("solid", colour, ""), ("gradient", "url(#id)", the gradient) or ("image", data URI, "")."""
    c = p["color"] if pre == "fill" else p.get("stroke_color", "#000000")
    kind = p.get(pre + "_type", "solid")
    if kind == "gradient":
        gid = "g" + pre[0]
        return kind, f"url(#{gid})", _grad_def(gid, c, p.get(pre + "_color2", "#000000"), p.get(pre + "_gtype", "linear"),
                                               p.get(pre + "_angle", 0), w, h, p.get(pre + "_stops") or None)
    if kind in textures.KINDS:
        uri = _texture(kind, w, h, p.get(pre + "_scale", 5), p.get(pre + "_seed", 0), p.get(pre + "_z", 0), c,
                       p.get(pre + "_color2", "#000000"))
        return "image", uri, ""
    if kind == "image" and p.get(pre + "_image"):
        uri = _picture(p[pre + "_image"])
        if uri:
            return kind, uri, ""
    return "solid", c, ""


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


MITER_LIMIT = 4


def stroked(p):
    """Whether parameters p (as at() gives them) draw an outline."""
    return bool(p.get("stroke_on")) and p.get("stroke", 0) > 0


def overflow(p):
    """How far (asset px) the outline of p (as at() gives it) reaches past its w x h frame:
    all of it outside, half of it on the edge; sharp corners with miter joins reach further."""
    if not stroked(p) or p.get("stroke_align") == "inside":
        return 0.0
    s = p["stroke"] * (1.0 if p["stroke_align"] == "outside" else 0.5)
    return s * (MITER_LIMIT if p.get("join") == "miter" else 1.0)


def fade_distance(p):
    """How far (asset px) inside its edge the fill of p fades in: 邊緣淡出 % of half its short side (100: to the middle)."""
    return max(0.0, float(p.get("fade", 0) or 0)) / 100.0 * min(p["w"], p["h"]) / 2


def _num(x):
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _poly(q):
    return "M" + " L".join(f"{_num(x)} {_num(y)}" for x, y in q) + " Z"


def _rounded_d(q, r):
    """A closed polygon's path with every corner rounded by an arc of radius r (smaller where
    the sides are too short for it: at most half of each side is used)."""
    if r <= 0:
        return _poly(q)
    n, out = len(q), []
    for i, (px, py) in enumerate(q):
        (ax, ay), (bx, by) = q[i - 1], q[(i + 1) % n]
        ux, uy, vx, vy = ax - px, ay - py, bx - px, by - py
        la, lb = math.hypot(ux, uy), math.hypot(vx, vy)
        if la < 1e-9 or lb < 1e-9:
            continue
        ux, uy, vx, vy = ux / la, uy / la, vx / lb, vy / lb
        half = math.acos(max(-1.0, min(1.0, ux * vx + uy * vy))) / 2      # half the corner's angle
        if half < 1e-6 or half > math.pi / 2 - 1e-6:                      # (no corner to round)
            out.append((px, py, px, py, 0.0, 0))
            continue
        t = min(r / math.tan(half), la / 2, lb / 2)                      # from the corner to the arc's ends
        cross = (px - ax) * (by - py) - (py - ay) * (bx - px)             # (y down: > 0 turns clockwise)
        out.append((px + ux * t, py + uy * t, px + vx * t, py + vy * t, t * math.tan(half), 1 if cross > 0 else 0))
    if not out:
        return _poly(q)
    d = f"M{_num(out[0][0])} {_num(out[0][1])}"
    for i, (x0, y0, x1, y1, rr, sweep) in enumerate(out):
        if i:
            d += f" L{_num(x0)} {_num(y0)}"
        if rr > 0:
            d += f" A{_num(rr)} {_num(rr)} 0 0 {sweep} {_num(x1)} {_num(y1)}"
    return d + " Z"


def _rect_d(w, h, r):
    r = min(r, w / 2, h / 2)
    if r <= 0:
        return _poly([(0, 0), (w, 0), (w, h), (0, h)])
    k = r * (1 - 0.5522847498)
    n = _num
    return (f"M{n(r)} 0 L{n(w - r)} 0 C{n(w - k)} 0 {n(w)} {n(k)} {n(w)} {n(r)} L{n(w)} {n(h - r)} "
            f"C{n(w)} {n(h - k)} {n(w - k)} {n(h)} {n(w - r)} {n(h)} L{n(r)} {n(h)} C{n(k)} {n(h)} 0 {n(h - k)} 0 {n(h - r)} "
            f"L0 {n(r)} C0 {n(k)} {n(k)} 0 {n(r)} 0 Z")


def _ellipse_d(w, h, start, sweep, ratio):
    """An ellipse filling w x h; as Lunacy's: an arc from start ° (clockwise from 3 o'clock)
    over sweep % of a turn, with a hole of ratio % of the radius."""
    cx, cy, rx, ry = w / 2, h / 2, w / 2, h / 2
    sweep = min(max(sweep, 0.0), 100.0) / 100 * 360
    k = min(max(ratio, 0.0), 100.0) / 100           # (100: no fill left, only the outline)
    n = _num
    pt = lambda a, s=1.0: (cx + rx * s * math.cos(math.radians(a)), cy + ry * s * math.sin(math.radians(a)))
    if sweep <= 0:
        return ""
    if sweep >= 359.99:
        def loop(s, cw):
            (x0, y0), (x1, y1) = pt(start, s), pt(start + 180, s)
            f = 1 if cw else 0
            return (f"M{n(x0)} {n(y0)} A{n(rx * s)} {n(ry * s)} 0 1 {f} {n(x1)} {n(y1)} "
                    f"A{n(rx * s)} {n(ry * s)} 0 1 {f} {n(x0)} {n(y0)} Z")
        return loop(1.0, True) + (" " + loop(k, False) if k > 0 else "")
    big = 1 if sweep > 180 else 0
    (x0, y0), (x1, y1) = pt(start), pt(start + sweep)
    d = f"M{n(x0)} {n(y0)} A{n(rx)} {n(ry)} 0 {big} 1 {n(x1)} {n(y1)} "
    if k > 0:
        (x2, y2), (x3, y3) = pt(start + sweep, k), pt(start, k)
        d += f"L{n(x2)} {n(y2)} A{n(rx * k)} {n(ry * k)} 0 {big} 0 {n(x3)} {n(y3)} Z"
    else:
        d += f"L{n(cx)} {n(cy)} Z"
    return d


def _parallelogram(w, h, skew):
    off = max(-w, min(w, h * math.tan(math.radians(min(max(skew, -89.0), 89.0)))))
    if off >= 0:
        return [(off, 0), (w, 0), (w - off, h), (0, h)]
    return [(0, 0), (w + off, 0), (w, h), (-off, h)]


def outline_d(p, w, h):
    """The path (SVG d, in a w x h box) of a shape family."""
    fam = p["family"]
    if fam == "path":
        return _path_d(p, w, h)
    if fam in ("rect", "line"):
        return _rect_d(w, h, p.get("radius", 0))
    if fam == "ellipse":
        return _ellipse_d(w, h, p.get("arc_start", 0), p.get("arc_sweep", 100), p.get("ratio", 0))
    if fam == "star":
        return _rounded_d(_fit(_star_points(p["points"], p["inner"] / 100), 0, 0, w, h), p.get("radius", 0))
    if fam == "polygon":
        return _poly(_fit(_star_points(p["sides"], None), 0, 0, w, h))
    if fam == "arrow":
        return _poly([(x * w, y * h) for x, y in _ARROW])
    if fam == "parallelogram":
        return _poly(_parallelogram(w, h, p.get("skew", 0)))
    q = [(x * w, (y - 0.04) / 0.88 * h) for x, y in _HEART]       # heart: cubic segments through _HEART
    return (f"M{q[0][0]:.1f} {q[0][1]:.1f} " + " ".join(
        "C " + " ".join(f"{x:.1f} {y:.1f}" for x, y in q[i:i + 3]) for i in range(1, len(q), 3)) + " Z")


def _path_d(p, w, h):
    """The path (SVG d, in a w x h box) of a pen path: straight where a segment's handles are both 0, else a cubic curve."""
    nodes = p.get("nodes") or []
    if len(nodes) < 2:
        return ""
    d = [f"M{_num(nodes[0][0] * w)} {_num(nodes[0][1] * h)}"]
    pairs = list(zip(nodes, nodes[1:])) + ([(nodes[-1], nodes[0])] if p.get("closed") and len(nodes) > 2 else [])
    for a, b in pairs:
        if a[4] == a[5] == b[2] == b[3] == 0:
            d.append(f"L{_num(b[0] * w)} {_num(b[1] * h)}")
        else:
            d.append("C" + " ".join(_num(v) for v in ((a[0] + a[4]) * w, (a[1] + a[5]) * h, (b[0] + b[2]) * w, (b[1] + b[3]) * h,
                                                      b[0] * w, b[1] * h)))
    return " ".join(d) + (" Z" if p.get("closed") and len(nodes) > 2 else "")


def bezier_points(a, b, steps=24):
    """Points along the cubic from node a to node b ([x, y, in dx, in dy, out dx, out dy], any units), ends included."""
    p0, p1 = (a[0], a[1]), (a[0] + a[4], a[1] + a[5])
    p2, p3 = (b[0] + b[2], b[1] + b[3]), (b[0], b[1])
    out = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        out.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                    u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
    return out


def path_params(nodes, closed, color="#ffffff"):
    """(parameters, (cx, cy)) of a new pen path clip: nodes [[x, y, in dx, in dy, out dx, out dy], ...] in px (any origin; y down).
    The clip is as big as the path (w x h), its nodes stored across that box, (cx, cy) is the middle of it in the nodes' own
    coordinates. A closed path is filled, an open one is a line."""
    pts = [(n[0], n[1]) for n in nodes]
    pairs = list(zip(nodes, nodes[1:])) + ([(nodes[-1], nodes[0])] if closed and len(nodes) > 2 else [])
    for a, b in pairs:
        pts += bezier_points(a, b)
    x0, x1 = min(x for x, _ in pts), max(x for x, _ in pts)
    y0, y1 = min(y for _, y in pts), max(y for _, y in pts)
    w, h = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
    norm = [[(n[0] - x0) / w, (n[1] - y0) / h, n[2] / w, n[3] / h, n[4] / w, n[5] / h] for n in nodes]
    closed = bool(closed) and len(nodes) > 2
    p = {"key": "path.pen", "family": "path", "color": color, "nodes": norm, "closed": closed, "w": w, "h": h,
         "fill": closed, "stroke_on": not closed, "stroke": 8, "stroke_color": color, "stroke_align": "center", "join": "round"}
    return normalize(p), ((x0 + x1) / 2 if x1 > x0 else x0, (y0 + y1) / 2 if y1 > y0 else y0)


def _grid(p, w, h):
    """Lines of colour dividing the w x h box into gcols x grows cells; gratio > 0 holds the cells
    to that width / height (the grid is as large as fits, centred), gleft / gright / gtop / gbottom draw the outer edges."""
    cols, rows, s = p["gcols"], p["grows"], p["gline"]
    aw, ah = max(w - s, 1.0), max(h - s, 1.0)                 # (the lines stay inside the box)
    cw, ch = aw / cols, ah / rows
    if p["gratio"] > 0:
        cw = min(cw, ch * p["gratio"])
        ch = cw / p["gratio"]
    gw, gh = cw * cols, ch * rows
    x0, y0 = (w - gw) / 2, (h - gh) / 2
    xs = [x0 + i * cw for i in range(cols + 1)]
    ys = [y0 + j * ch for j in range(rows + 1)]
    xs = xs[(0 if p["gleft"] else 1):len(xs) - (0 if p["gright"] else 1)]
    ys = ys[(0 if p["gtop"] else 1):len(ys) - (0 if p["gbottom"] else 1)]
    d = "".join(f"M{_num(x)} {_num(y0)} V{_num(y0 + gh)} " for x in xs) + "".join(f"M{_num(x0)} {_num(y)} H{_num(x0 + gw)} " for y in ys)
    rgb, op = _alpha(p["color"])
    body = (f'<path d="{d}" fill="none" stroke="{rgb}" stroke-width="{s:g}" stroke-linecap="square"'
            + (f' stroke-opacity="{op:.3f}"' if op < 1 else "") + "/>") if d else ""
    return _svg(w, h, body)


def _shape(p, w, h, part=None):
    """part: only the "fill", only the "stroke", or only the shape's "mask" (white; what 邊緣淡出 measures from)."""
    d = outline_d(p, w, h)
    pad = overflow(p)
    body, defs = [], ""
    box = f'x="{-pad:g}" y="{-pad:g}" width="{w + 2 * pad:g}" height="{h + 2 * pad:g}"'

    def put(pre, make):
        """Add the fill / outline made by make(paint attributes): a picture shows through a mask
        of the same shape drawn in white."""
        nonlocal defs
        kind, value, gdefs = _paint(p, pre, w, h)
        defs += gdefs
        if kind == "image":
            defs += (f'<mask id="m{pre[0]}" maskUnits="userSpaceOnUse" {box}><rect {box} fill="#000"/>'
                     f'{make("fill" if pre == "fill" else "stroke", "#fff", 1.0)}</mask>')
            body.append(f'<image {box} preserveAspectRatio="xMidYMid slice" mask="url(#m{pre[0]})" '
                        f'xlink:href="{value}"/>')
        elif kind == "gradient":
            body.append(make(pre, value, 1.0))
        else:
            rgb, op = _alpha(value)
            body.append(make(pre, rgb, op))

    def attr(prop, v, op):
        return f'{prop}="{v}"' + (f' {prop}-opacity="{op:.3f}"' if op < 1 else "")

    if part == "mask":
        return _svg(w, h, f'<path d="{d}" fill-rule="evenodd" fill="#fff"/>', "", pad)
    if p.get("fill", True) and d and part != "stroke":
        put("fill", lambda prop, v, op: f'<path d="{d}" fill-rule="evenodd" {attr("fill", v, op)}/>')
    if stroked(p) and d and part != "fill":
        align, s = p.get("stroke_align", "inside"), p["stroke"]
        line = f'fill="none" stroke-linejoin="{p.get("join", "miter")}" stroke-miterlimit="{MITER_LIMIT}"'
        if align == "center":
            put("stroke", lambda prop, v, op: f'<path d="{d}" {line} {attr("stroke", v, op)} stroke-width="{s:g}"/>')
        else:                              # twice as wide, half of it masked off by the shape
            big = f'x="{-pad - s:g}" y="{-pad - s:g}" width="{w + 2 * (pad + s):g}" height="{h + 2 * (pad + s):g}"'
            if align == "inside":
                defs += f'<mask id="s" maskUnits="userSpaceOnUse" {big}><path d="{d}" fill-rule="evenodd" fill="#fff"/></mask>'
            else:
                defs += (f'<mask id="s" maskUnits="userSpaceOnUse" {big}><rect {big} fill="#fff"/>'
                         f'<path d="{d}" fill-rule="evenodd" fill="#000"/></mask>')
            put("stroke", lambda prop, v, op: f'<path d="{d}" {line} {attr("stroke", v, op)} '
                                              f'stroke-width="{2 * s:g}" mask="url(#s)"/>')
    return _svg(w, h, "\n".join(body), defs, pad)


def cover(p):
    """Parameters p (as at() gives them) drawn opaque: where the asset is, whatever its colours'
    alpha - what 套用至背景 works inside (a shape with neither fill nor outline: its fill)."""
    q = dict(p)
    for f in ("color", "color2", "stroke_color", "fill_color2", "stroke_color2"):
        if f in q:
            q[f] = "#ffffff"
    q["fill_type"] = q["stroke_type"] = "solid"
    for f in ("stops", "fill_stops", "stroke_stops"):
        if f in q:
            q[f] = [[x, "#ffffff"] for x, _c in q[f]]
    if q["family"] not in ("solid", "gradient") and not (q.get("fill", True) or stroked(q)):
        q["fill"] = True
    return q


def _empty(w, h):
    """An empty as the editor's preview shows it: its frame (dashed) and axes through the middle."""
    s = max(2.0, min(w, h) / 120)
    line = f'stroke="{EMPTY_COLOR}" stroke-width="{s:g}" fill="none"'
    return _svg(w, h, f'<rect x="{s / 2:g}" y="{s / 2:g}" width="{max(w - s, 1):g}" height="{max(h - s, 1):g}" {line} '
                      f'stroke-dasharray="{4 * s:g} {3 * s:g}"/>'
                      f'<path d="M0 {h / 2:g}H{w:g}M{w / 2:g} 0V{h:g}" {line}/>')


def svg(p, editing=False, part=None):
    """The SVG text of asset parameters p as at() gives them (editing: the editor's preview, which
    also shows an empty - nothing otherwise)."""
    w, h = p["w"], p["h"]
    if p["family"] == "empty":
        return _empty(w, h) if editing else _svg(w, h, "")
    if p["family"] == "solid":
        return _svg(w, h, f'<rect width="{w}" height="{h}" {_fill(p["color"])}/>')
    if p["family"] == "gradient":
        return _gradient(p, w, h)
    if p["family"] == "grid":
        if part == "mask":                       # (邊緣淡出 measures from the frame's edge)
            return _svg(w, h, f'<rect width="{w}" height="{h}" fill="#fff"/>')
        return _grid(p, w, h)
    return _shape(p, w, h, part)


def store(media_dir, p):
    """Write the SVG of p (at its start) into media_dir/.內建素材, named after its content
    (an identical one is reused). Returns its path."""
    text = svg(at(p, 0))
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
    w, h = size_at(p, 0)
    return {"kind": "image", "name": name_of(p), "path": path, "width": w, "height": h}


def restore(clips, media_dir):
    """Draw again the asset files that are missing (a cleaned Media folder, a project copied
    without hidden files). Returns [(old path, new path)] of the clips that changed."""
    out = []
    for c in clips:
        p = c.get("asset")
        if p and not os.path.exists((c.get("media") or {}).get("path") or ""):
            new = store(media_dir, normalize(p))
            out.append((c["media"].get("path"), new))
            w, h = size_at(p, 0)
            c["media"] = {"path": new, "width": w, "height": h}
    return out
