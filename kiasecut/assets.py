"""Built-in assets (內建素材): solid colours, gradients and basic shapes, made as SVG pictures.

An asset is drawn from its definition and one or two colours: presets carry their own,
the "custom" ones and every shape use the colours picked in the 內建素材 tab. Using one
writes the SVG into the project's Media folder (Media/內建素材), so from then on it is a
picture like any imported one. Solids and gradients have the canvas's size, so they fill
the frame; shapes are drawn on their own (transparent) box and placed smaller.

An asset is named on the timeline's drag data as "asset:<key>:<colour 1>:<colour 2>".
"""
import math
import os
import re

FOLDER = "內建素材"
PREFIX = "asset:"
CATEGORIES = [("solid", "純色"), ("gradient", "漸變色"), ("shape", "基礎形狀")]
DEFAULT_COLORS = ("#ffffff", "#000000")
SHAPE_SCALE = 0.4                          # a shape's scale when placed (1 = as tall as the canvas)
SHAPE_BOX = 1000                           # a shape's drawing size (its SVG units)


class Asset:
    def __init__(self, key, cat, name, colors=None, kind="", scale=1.0):
        self.key = key
        self.cat = cat
        self.name = name
        self.colors = colors               # fixed (c1, c2), or None: the picked colours
        self.kind = kind                   # gradient direction / shape name
        self.scale = scale

    @property
    def custom(self):
        return self.colors is None


_SOLIDS = [("白", "#ffffff"), ("黑", "#000000"), ("灰", "#808080"), ("紅", "#e53935"), ("橙", "#fb8c00"),
           ("黃", "#fdd835"), ("綠", "#43a047"), ("青", "#00acc1"), ("藍", "#1e88e5"), ("紫", "#8e24aa"),
           ("粉", "#ec407a")]
_GRADIENTS = [("日落", "#ff5f6d", "#ffc371", "d"), ("海洋", "#2193b0", "#6dd5ed", "v"),
              ("森林", "#134e5e", "#71b280", "d"), ("紫霞", "#8e2de2", "#4a00e0", "d"),
              ("桃粉", "#ee9ca7", "#ffdde1", "v"), ("夜空", "#0f2027", "#2c5364", "v"),
              ("黑白", "#000000", "#ffffff", "h"),
              ("底部黑色漸層", "#00000000", "#000000cc", "v"),      # behind subtitles
              ("暗角", "#00000000", "#000000d9", "r")]
_CUSTOM_GRADIENTS = [("橫向漸變", "h"), ("直向漸變", "v"), ("斜向漸變", "d"), ("放射漸變", "r")]
_SHAPES = [("矩形", "rect"), ("圓角矩形", "roundrect"), ("圓形", "circle"), ("三角形", "triangle"),
           ("菱形", "diamond"), ("五邊形", "pentagon"), ("六邊形", "hexagon"), ("星形", "star"),
           ("心形", "heart"), ("箭頭", "arrow"), ("圓環", "ring"), ("外框矩形", "rectframe"),
           ("外框圓形", "circleframe"), ("線條", "line")]

ASSETS = ([Asset(f"solid.{i}", "solid", name, (c, c)) for i, (name, c) in enumerate(_SOLIDS)]
          + [Asset("solid.custom", "solid", "自訂純色")]
          + [Asset(f"gradient.{i}", "gradient", name, (a, b), d) for i, (name, a, b, d) in enumerate(_GRADIENTS)]
          + [Asset(f"gradient.custom.{d}", "gradient", name, None, d) for name, d in _CUSTOM_GRADIENTS]
          + [Asset(f"shape.{k}", "shape", name, None, k, SHAPE_SCALE * (1.5 if k == "line" else 1))
             for name, k in _SHAPES])
_BY_KEY = {a.key: a for a in ASSETS}


def get(key):
    return _BY_KEY.get(key)


_HEX = re.compile(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")


def clean_color(c, default="#ffffff"):
    """#rrggbb or #rrggbbaa (lower case), else the default."""
    c = (c or "").strip()
    return c.lower() if _HEX.match(c) else default


def ident(key, c1, c2):
    return f"{PREFIX}{key}:{clean_color(c1)}:{clean_color(c2, '#000000')}"


def parse(text):
    """(asset, colour 1, colour 2) from an ident(), or None."""
    if not text.startswith(PREFIX):
        return None
    parts = text[len(PREFIX):].split(":")
    a = get(parts[0])
    if a is None:
        return None
    c1 = clean_color(parts[1] if len(parts) > 1 else "", DEFAULT_COLORS[0])
    c2 = clean_color(parts[2] if len(parts) > 2 else "", DEFAULT_COLORS[1])
    return a, c1, c2


def colors_of(a, c1, c2):
    return a.colors if a.colors else (clean_color(c1), clean_color(c2, "#000000"))


def _alpha(c):
    """(#rrggbb, opacity) of #rrggbb[aa] (Qt's SVG reader wants the alpha apart)."""
    return c[:7], (int(c[7:], 16) / 255 if len(c) == 9 else 1.0)


def _fill(c):
    rgb, op = _alpha(c)
    return f'fill="{rgb}"' + (f' fill-opacity="{op:.3f}"' if op < 1 else "")


def _stroke(c, width):
    rgb, op = _alpha(c)
    return f'fill="none" stroke="{rgb}" stroke-width="{width:.0f}"' + (f' stroke-opacity="{op:.3f}"' if op < 1 else "")


def _stop(offset, c):
    rgb, op = _alpha(c)
    return f'<stop offset="{offset}" stop-color="{rgb}" stop-opacity="{op:.3f}"/>'


def _svg(w, h, body, defs=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">\n'
            + (f"<defs>{defs}</defs>\n" if defs else "") + body + "\n</svg>\n")


def _gradient(kind, a, b, w, h):
    if kind == "r":                        # from the centre to the corners; the middle third holds colour 1
        g = (f'<radialGradient id="g" cx="{w / 2:.1f}" cy="{h / 2:.1f}" r="{math.hypot(w, h) / 2:.1f}" '
             f'gradientUnits="userSpaceOnUse">{_stop(0.35, a)}{_stop(1, b)}</radialGradient>')
    else:
        x2, y2 = {"h": (w, 0), "v": (0, h), "d": (w, h)}[kind]
        g = (f'<linearGradient id="g" x1="0" y1="0" x2="{x2}" y2="{y2}" gradientUnits="userSpaceOnUse">'
             f'{_stop(0, a)}{_stop(1, b)}</linearGradient>')
    return _svg(w, h, f'<rect width="{w}" height="{h}" fill="url(#g)"/>', g)


def _poly(n, r, cx, cy, start=-90.0, inner=None):
    pts = []
    for i in range(n * (2 if inner else 1)):
        ang = math.radians(start + i * 360 / (n * (2 if inner else 1)))
        rr = inner if inner and i % 2 else r
        pts.append(f"{cx + rr * math.cos(ang):.1f},{cy + rr * math.sin(ang):.1f}")
    return " ".join(pts)


def _shape(kind, c):
    S = SHAPE_BOX
    f = _fill(c)
    if kind == "line":
        return _svg(S, 40, f'<rect width="{S}" height="40" {f}/>')
    body = {
        "rect": f'<rect width="{S}" height="{S}" {f}/>',
        "roundrect": f'<rect width="{S}" height="{S}" rx="{S * 0.16:.0f}" {f}/>',
        "circle": f'<circle cx="{S / 2}" cy="{S / 2}" r="{S / 2}" {f}/>',
        "triangle": f'<polygon points="{S / 2},0 {S},{S} 0,{S}" {f}/>',
        "diamond": f'<polygon points="{S / 2},0 {S},{S / 2} {S / 2},{S} 0,{S / 2}" {f}/>',
        "pentagon": f'<polygon points="{_poly(5, S / 2, S / 2, S * 0.53)}" {f}/>',
        "hexagon": f'<polygon points="{_poly(6, S / 2, S / 2, S / 2, 0)}" {f}/>',
        "star": f'<polygon points="{_poly(5, S / 2, S / 2, S * 0.53, inner=S * 0.2)}" {f}/>',
        "heart": f'<path d="M500 920 C 120 660 0 470 0 290 C 0 130 120 40 260 40 C 370 40 450 110 500 200 '
                 f'C 550 110 630 40 740 40 C 880 40 1000 130 1000 290 C 1000 470 880 660 500 920 Z" {f}/>',
        "arrow": f'<polygon points="0,350 600,350 600,120 1000,500 600,880 600,650 0,650" {f}/>',
        "ring": f'<circle cx="{S / 2}" cy="{S / 2}" r="{S * 0.42}" {_stroke(c, S * 0.16)}/>',
        "rectframe": f'<rect x="30" y="30" width="{S - 60}" height="{S - 60}" {_stroke(c, 60)}/>',
        "circleframe": f'<circle cx="{S / 2}" cy="{S / 2}" r="{S / 2 - 30}" {_stroke(c, 60)}/>',
    }[kind]
    return _svg(S, S, body)


def svg(a, c1, c2, w, h):
    """The SVG text of asset a; solids and gradients are w x h (the canvas)."""
    a1, a2 = colors_of(a, c1, c2)
    if a.cat == "solid":
        return _svg(w, h, f'<rect width="{w}" height="{h}" {_fill(a1)}/>')
    if a.cat == "gradient":
        return _gradient(a.kind, a1, a2, w, h)
    return _shape(a.kind, a1)


def file_name(a, c1, c2, w, h):
    a1, a2 = colors_of(a, c1, c2)
    if a.cat == "shape":
        stem = f"{a.name} {a1}"
    elif not a.custom:
        stem = a.name
    elif a.cat == "solid":
        stem = f"純色 {a1}"
    else:
        stem = f"{a.name} {a1}-{a2}"
    if a.cat != "shape":
        stem += f" {w}x{h}"
    return stem.replace("#", "") + ".svg"


def write(directory, a, c1, c2, w, h):
    """Write asset a into directory; an identical file already there is reused. Returns its path."""
    text = svg(a, c1, c2, w, h)
    os.makedirs(directory, exist_ok=True)
    name = file_name(a, c1, c2, w, h)
    stem, ext = os.path.splitext(name)
    path, n = os.path.join(directory, name), 2
    while os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                if fh.read() == text:
                    return path
        except OSError:
            pass
        path = os.path.join(directory, f"{stem} ({n}){ext}")
        n += 1
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path
