"""Vector shapes: outlines kept as paths (not pictures) so they can be added together and combined by boolean operations
(the 矢量 nodes of the node editor), and drawn sharp at any size.

A drawing is a list of Layers: a QPainterPath in canvas px (the clip's frame, centred on 0, y down) with the paint it is
drawn with (a fill and / or an outline). The built-in shapes, a text's glyphs and an SVG file give layers; 相加 puts the
layers of its inputs together, 布林 combines the outlines of its inputs into one layer painted as the first input is."""
import hashlib
import math
import os
import re
import xml.etree.ElementTree as ET

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient, QTransform)

from . import assets, svgimage, textures  # noqa: E402

OPS = (("聯集", "union"), ("差集", "subtract"), ("交集", "intersect"), ("排除", "xor"))
MAX_PX = 4096                      # longest side of a picture made from a drawing


class Layer:
    """One outline with its paint. fill / stroke: (r, g, b, a) in 0..1, a QBrush (a gradient or a picture, in the outline's own
    coordinates: it is turned and moved with it) or None; width px; join "miter" | "round" | "bevel";
    align "center" | "inside" | "outside" (which side of the outline the stroke is on)."""
    __slots__ = ("path", "fill", "stroke", "width", "join", "align")

    def __init__(self, path, fill=(1.0, 1.0, 1.0, 1.0), stroke=None, width=0.0, join="miter", align="center"):
        self.path, self.fill, self.stroke, self.width, self.join, self.align = path, fill, stroke, width, join, align

    def mapped(self, tf):
        """The layer moved / turned / scaled by QTransform tf (the stroke's width follows a scale)."""
        k = math.sqrt(abs(tf.determinant()))
        moved = lambda c: _brush_moved(c, tf)
        return Layer(tf.map(self.path), moved(self.fill), moved(self.stroke), self.width * k, self.join, self.align)

    def styled(self, path):
        return Layer(path, self.fill, self.stroke, self.width, self.join, self.align)


def _brush_moved(c, tf):
    if isinstance(c, QBrush):
        c = QBrush(c)
        c.setTransform(c.transform() * tf)
    return c


def _paint_key(c):
    if isinstance(c, QBrush):
        g = c.gradient()
        t = c.transform()
        return repr((int(c.style().value), g.type().value if g else None, [(round(x, 3), y.name(QColor.HexArgb)) for x, y in g.stops()] if g else
                     c.textureImage().cacheKey() if not c.textureImage().isNull() else None,
                     tuple(round(x, 2) for x in (t.m11(), t.m12(), t.m21(), t.m22(), t.dx(), t.dy()))))
    return c


# -- SVG path data -----------------------------------------------------------------------------------------------------------
_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}


def _arc(path, x0, y0, rx, ry, phi, large, sweep, x, y):
    """The elliptical arc of SVG path data from (x0, y0) to (x, y) as cubic curves."""
    if rx == 0 or ry == 0 or (x0 == x and y0 == y):
        path.lineTo(x, y)
        return
    rx, ry = abs(rx), abs(ry)
    cp, sp = math.cos(math.radians(phi)), math.sin(math.radians(phi))
    dx, dy = (x0 - x) / 2, (y0 - y) / 2
    x1, y1 = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    den = rx * rx * y1 * y1 + ry * ry * x1 * x1
    co = math.sqrt(max(0.0, (rx * rx * ry * ry - den) / den)) if den else 0.0
    if bool(large) == bool(sweep):
        co = -co
    cx1, cy1 = co * rx * y1 / ry, -co * ry * x1 / rx
    cx, cy = cp * cx1 - sp * cy1 + (x0 + x) / 2, sp * cx1 + cp * cy1 + (y0 + y) / 2
    ang = lambda ux, uy, vx, vy: math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
    th1 = ang(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    dth = ang((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and dth > 0:
        dth -= 2 * math.pi
    elif sweep and dth < 0:
        dth += 2 * math.pi
    n = max(1, math.ceil(abs(dth) / (math.pi / 2) - 1e-9))
    delta = dth / n
    k = 4 / 3 * math.tan(delta / 4)
    at = lambda ux, uy: (cx + cp * rx * ux - sp * ry * uy, cy + sp * rx * ux + cp * ry * uy)
    for i in range(n):
        a1, a2 = th1 + i * delta, th1 + (i + 1) * delta
        c1 = at(math.cos(a1) - k * math.sin(a1), math.sin(a1) + k * math.cos(a1))
        c2 = at(math.cos(a2) + k * math.sin(a2), math.sin(a2) - k * math.cos(a2))
        e = at(math.cos(a2), math.sin(a2))
        path.cubicTo(c1[0], c1[1], c2[0], c2[1], e[0], e[1])


def parse_d(d, rule=Qt.OddEvenFill):
    """The QPainterPath of SVG path data d (every command, relative or absolute)."""
    path = QPainterPath()
    path.setFillRule(rule)
    i, n = 0, len(d)
    cmd, cur, start, last_c, last_q = None, (0.0, 0.0), (0.0, 0.0), None, None

    def skip():
        nonlocal i
        while i < n and (d[i].isspace() or d[i] == ","):
            i += 1

    def number():
        nonlocal i
        skip()
        m = _NUM.match(d, i)
        if not m:
            raise ValueError("bad path data")
        i = m.end()
        return float(m.group())

    def flag():
        nonlocal i
        skip()
        if i < n and d[i] in "01":
            i += 1
            return d[i - 1] == "1"
        raise ValueError("bad arc flag")

    try:
        while True:
            skip()
            if i >= n:
                break
            if d[i].isalpha():
                cmd = d[i]
                i += 1
                if cmd in "Zz":
                    path.closeSubpath()
                    cur = start
                    last_c = last_q = None
                    continue
            elif cmd is None or cmd in "Zz":
                break
            elif cmd == "M":                      # (more pairs after a moveto are linetos)
                cmd = "L"
            elif cmd == "m":
                cmd = "l"
            rel = cmd.islower()
            c = cmd.upper()
            if c not in _ARGS:
                break
            ox, oy = cur if rel else (0.0, 0.0)
            if c == "M":
                x, y = number() + ox, number() + oy
                path.moveTo(x, y)
                cur = start = (x, y)
                last_c = last_q = None
            elif c == "L":
                x, y = number() + ox, number() + oy
                path.lineTo(x, y)
                cur = (x, y)
                last_c = last_q = None
            elif c == "H":
                x = number() + ox
                path.lineTo(x, cur[1])
                cur = (x, cur[1])
                last_c = last_q = None
            elif c == "V":
                y = number() + oy
                path.lineTo(cur[0], y)
                cur = (cur[0], y)
                last_c = last_q = None
            elif c in "CS":
                if c == "C":
                    x1, y1 = number() + ox, number() + oy
                else:
                    x1, y1 = (2 * cur[0] - last_c[0], 2 * cur[1] - last_c[1]) if last_c else cur
                x2, y2, x, y = number() + ox, number() + oy, number() + ox, number() + oy
                path.cubicTo(x1, y1, x2, y2, x, y)
                cur, last_c, last_q = (x, y), (x2, y2), None
            elif c in "QT":
                if c == "Q":
                    x1, y1 = number() + ox, number() + oy
                else:
                    x1, y1 = (2 * cur[0] - last_q[0], 2 * cur[1] - last_q[1]) if last_q else cur
                x, y = number() + ox, number() + oy
                path.quadTo(x1, y1, x, y)
                cur, last_q, last_c = (x, y), (x1, y1), None
            elif c == "A":
                rx, ry, phi = number(), number(), number()
                large, sweep = flag(), flag()
                x, y = number() + ox, number() + oy
                _arc(path, cur[0], cur[1], rx, ry, phi, large, sweep, x, y)
                cur = (x, y)
                last_c = last_q = None
    except ValueError:
        pass                                      # (what was read before the mistake is kept)
    return path


# -- colours and SVG files ---------------------------------------------------------------------------------------------------
def parse_colour(text, default=None):
    """(r, g, b, a) of a CSS colour, None for none, `default` when it is not understood."""
    t = (text or "").strip()
    if not t:
        return default
    if t == "none" or t == "transparent":
        return None
    if t == "currentColor":
        return (0.0, 0.0, 0.0, 1.0)
    m = re.fullmatch(r"rgba?\(([^)]*)\)", t)
    if m:
        v = [x.strip() for x in m.group(1).replace("/", ",").split(",")]
        if len(v) >= 3:
            try:
                ch = [min(max(float(x[:-1]) / 100 if x.endswith("%") else float(x) / 255, 0.0), 1.0) for x in v[:3]]
                a = float(v[3][:-1]) / 100 if len(v) > 3 and v[3].endswith("%") else float(v[3]) if len(v) > 3 else 1.0
                return (ch[0], ch[1], ch[2], min(max(a, 0.0), 1.0))
            except ValueError:
                return default
    c = QColor(t)
    if not c.isValid():
        return default
    return (c.redF(), c.greenF(), c.blueF(), c.alphaF())


def _transform(text):
    """QTransform of an SVG transform list."""
    tf = QTransform()
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", text or ""):
        try:
            a = [float(x) for x in re.split(r"[\s,]+", args.strip()) if x]
        except ValueError:
            continue
        if name == "matrix" and len(a) == 6:
            m = QTransform(a[0], a[1], a[2], a[3], a[4], a[5])
        elif name == "translate" and a:
            m = QTransform().translate(a[0], a[1] if len(a) > 1 else 0.0)
        elif name == "scale" and a:
            m = QTransform().scale(a[0], a[1] if len(a) > 1 else a[0])
        elif name == "rotate" and a:
            m = QTransform()
            if len(a) == 3:
                m.translate(a[1], a[2])
            m.rotate(a[0])
            if len(a) == 3:
                m.translate(-a[1], -a[2])
        elif name == "skewX" and a:
            m = QTransform(1, 0, math.tan(math.radians(a[0])), 1, 0, 0)
        elif name == "skewY" and a:
            m = QTransform(1, math.tan(math.radians(a[0])), 0, 1, 0, 0)
        else:
            continue
        tf = m * tf                                  # (the first one in the list is applied last)
    return tf


def _length(v, default=0.0):
    try:
        return float(re.match(_NUM, str(v).strip()).group())
    except (AttributeError, ValueError):
        return default


def _style(el, inherited):
    """The paint attributes of element el over its parent's."""
    s = dict(inherited)
    for k, v in el.attrib.items():
        if k in _PAINT:
            s[k] = v
    for part in (el.attrib.get("style") or "").split(";"):
        k, _, v = part.partition(":")
        if k.strip() in _PAINT:
            s[k.strip()] = v.strip()
    return s


_PAINT = ("fill", "stroke", "stroke-width", "fill-opacity", "stroke-opacity", "opacity", "fill-rule", "stroke-linejoin")


def _paint(s, ids):
    def colour(key, default):
        v = s.get(key, default)
        m = re.fullmatch(r"url\(\s*#([^)\s]+)\s*\)", v.strip())
        if m:                                        # (a gradient: its first stop's colour)
            g = ids.get(m.group(1))
            stop = next((x for x in g.iter() if x.tag.rpartition("}")[2] == "stop"), None) if g is not None else None
            if stop is None:
                return (0.5, 0.5, 0.5, 1.0)
            st = _style(stop, {})
            return parse_colour(st.get("stop-color") or stop.attrib.get("stop-color"), (0.0, 0.0, 0.0, 1.0))
        return parse_colour(v, (0.0, 0.0, 0.0, 1.0))
    fill, stroke = colour("fill", "black"), colour("stroke", "none")
    op = _length(s.get("opacity", 1.0), 1.0)
    if fill:
        fill = fill[:3] + (fill[3] * _length(s.get("fill-opacity", 1.0), 1.0) * op,)
    if stroke:
        stroke = stroke[:3] + (stroke[3] * _length(s.get("stroke-opacity", 1.0), 1.0) * op,)
    return fill, stroke


_svg_cache = {}


def load_svg(path):
    """(layers, QRectF of the picture) of an SVG file, in its own units; ([], empty) when it cannot be read. Paths, rectangles,
    circles, ellipses, lines and polygons are read, with their transforms and plain colours (a gradient: its first stop)."""
    try:
        stamp = os.stat(path).st_mtime_ns
    except OSError:
        return [], QRectF()
    hit = _svg_cache.get(path)
    if hit and hit[0] == stamp:
        return hit[1], hit[2]
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return [], QRectF()
    layers = parse_svg(root)
    box = _svg_box(root, layers)
    if len(_svg_cache) > 32:
        _svg_cache.clear()
    _svg_cache[path] = (stamp, layers, box)
    return layers, box


def _svg_box(root, layers):
    vb = re.split(r"[\s,]+", (root.attrib.get("viewBox") or "").strip())
    if len(vb) == 4:
        try:
            r = QRectF(*[float(x) for x in vb])
            if r.width() > 0 and r.height() > 0:
                return r
        except ValueError:
            pass
    w, h = _length(root.attrib.get("width", 0)), _length(root.attrib.get("height", 0))
    if w > 0 and h > 0:
        return QRectF(0, 0, w, h)
    box = QRectF()
    for l in layers:
        box = box.united(l.path.boundingRect())
    return box


def parse_svg(root):
    """The layers of an SVG document element."""
    ids = {el.attrib["id"]: el for el in root.iter() if "id" in el.attrib}
    out = []

    def walk(el, tf, inherited):
        tag = el.tag.rpartition("}")[2]
        if tag in ("defs", "clipPath", "mask", "symbol", "marker", "linearGradient", "radialGradient", "pattern", "style", "title", "desc", "metadata"):
            return
        tf = _transform(el.attrib.get("transform")) * tf
        s = _style(el, inherited)
        path = None
        a = el.attrib
        rule = Qt.WindingFill if s.get("fill-rule", "nonzero") == "nonzero" else Qt.OddEvenFill
        if tag == "path":
            path = parse_d(a.get("d", ""), rule)
        elif tag == "rect":
            x, y, w, h = (_length(a.get(k)) for k in ("x", "y", "width", "height"))
            rx, ry = _length(a.get("rx"), -1.0), _length(a.get("ry"), -1.0)
            rx, ry = (ry if rx < 0 else rx), (rx if ry < 0 else ry)
            path = QPainterPath()
            if w > 0 and h > 0:
                if rx > 0 or ry > 0:
                    path.addRoundedRect(QRectF(x, y, w, h), max(rx, 0.0), max(ry, 0.0))
                else:
                    path.addRect(QRectF(x, y, w, h))
        elif tag in ("circle", "ellipse"):
            cx, cy = _length(a.get("cx")), _length(a.get("cy"))
            rx = _length(a.get("r")) if tag == "circle" else _length(a.get("rx"))
            ry = rx if tag == "circle" else _length(a.get("ry"))
            path = QPainterPath()
            if rx > 0 and ry > 0:
                path.addEllipse(QPointF(cx, cy), rx, ry)
        elif tag in ("polygon", "polyline", "line"):
            if tag == "line":
                pts = [(_length(a.get("x1")), _length(a.get("y1"))), (_length(a.get("x2")), _length(a.get("y2")))]
            else:
                nums = [float(x) for x in _NUM.findall(a.get("points", ""))]
                pts = list(zip(nums[0::2], nums[1::2]))
            path = QPainterPath()
            path.setFillRule(rule)
            if pts:
                path.moveTo(*pts[0])
                for p in pts[1:]:
                    path.lineTo(*p)
                if tag == "polygon":
                    path.closeSubpath()
        if path is not None and not path.isEmpty():
            fill, stroke = _paint(s, ids)
            if tag in ("line", "polyline") and "fill" not in s:
                fill = None
            layer = Layer(path, fill, stroke, _length(s.get("stroke-width", 1.0), 1.0) if stroke else 0.0,
                          s.get("stroke-linejoin", "miter") if s.get("stroke-linejoin") in ("miter", "round", "bevel") else "miter")
            out.append(layer.mapped(tf))
        for child in el:
            walk(child, tf, s)

    walk(root, QTransform(), {})
    return out


# -- text ------------------------------------------------------------------------------------------------------------------
_fonts = {}


def _family(path):
    """The font family of a font file (Qt loads it once)."""
    if not path:
        return None
    if path not in _fonts:
        fid = QFontDatabase.addApplicationFont(path)
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        _fonts[path] = fams[0] if fams else None
    return _fonts[path]


def text_layers(spec, canvas_h=1080):
    """The glyph outlines of a text spec (the text tool's fields) as one layer centred on the text box's middle: every glyph where
    textlayout.py puts it (the same lines, wrapping, alignment and spacing), its outline from the font."""
    from . import textlayout
    lay = textlayout._layout(spec, 1.0, canvas_h)
    shear = math.tan(math.radians(spec.get("italic_deg", 0.0) or 0.0))
    fw, align = lay["fw"], spec.get("align") or "center"
    out = QPainterPath()
    out.setFillRule(Qt.WindingFill)
    fonts = {}
    for li, (glyphs, lw) in enumerate(lay["lines"]):
        ox = {"left": -fw / 2, "justify": -fw / 2, "right": fw / 2 - lw}.get(align, -lw / 2)
        spread = (fw - lw) / (len(glyphs) - 1) if align == "justify" and li < len(lay["lines"]) - 1 and len(glyphs) > 1 else 0.0
        base = lay["ct"] + lay["ext_top"] + li * lay["step"] + lay["asc"]
        for gi, (gx, ch, f, _rgba, _adv) in enumerate(glyphs):
            if not ch.strip():
                continue
            key = (f.path, f.size)
            font = fonts.get(key)
            if font is None:
                font = fonts[key] = QFont()
                fam = _family(f.path)
                if fam:
                    font.setFamily(fam)
                font.setPixelSize(max(1, round(f.size)))
            out.addText(ox + gx + gi * spread, base, font, ch)
    if shear:
        out = QTransform(1, 0, -shear, 1, 0, 0).map(out)
    col = spec.get("color") or (1.0, 1.0, 1.0, 1.0)
    fill = tuple(float(x) for x in (list(col) + [1.0])[:4]) if spec.get("fill", True) else None
    stroke = None
    width = float(spec.get("stroke", 2.0) or 0.0) * canvas_h / 1080
    if spec.get("stroke_on") and width > 0:
        sc = spec.get("stroke_color") or (0.0, 0.0, 0.0, 1.0)
        stroke = tuple(float(x) for x in (list(sc) + [1.0])[:4])
    return [Layer(out, fill, stroke, width if stroke else 0.0, "round",
                  {"inside": "inside", "outside": "outside", "center": "center"}.get(spec.get("stroke_align"), "inside"))]


# -- combining ---------------------------------------------------------------------------------------------------------------
def region(layers):
    """The outlines of layers as one path (their union)."""
    path = None
    for l in layers:
        path = QPainterPath(l.path) if path is None else path.united(l.path)
    return path if path is not None else QPainterPath()


def combine(op, groups):
    """The layers of boolean operation op ("union", "subtract", "intersect" or "xor") over groups (a list of the layers each
    input gave): one layer, painted as the first input is. Only one input: it as it is."""
    groups = [g for g in groups if g]
    if not groups:
        return []
    if len(groups) == 1:
        return list(groups[0])
    first = groups[0][0]
    path = region(groups[0])
    for g in groups[1:]:
        other = region(g)
        if op == "subtract":
            path = path.subtracted(other)
        elif op == "intersect":
            path = path.intersected(other)
        elif op == "xor":
            path = path.united(other).subtracted(path.intersected(other))
        else:
            path = path.united(other)
    return [first.styled(path)]


def rotated(layers, degrees, about_frame=False):
    """The layers turned clockwise by `degrees` about the middle of the frame, or of their own outlines."""
    if not layers or not degrees:
        return list(layers)
    if about_frame:
        c = QPointF(0, 0)
    else:
        c = region(layers).boundingRect().center()
    tf = QTransform().translate(c.x(), c.y()).rotate(degrees).translate(-c.x(), -c.y())
    return [l.mapped(tf) for l in layers]


def moved(layers, dx, dy):
    """The layers moved by dx, dy canvas px."""
    return [l.mapped(QTransform().translate(dx, dy)) for l in layers] if (dx or dy) else list(layers)


def scaled(layers, kx, ky, about_frame=False):
    """The layers scaled by kx, ky about the middle of the frame, or of their own outlines."""
    if not layers or (kx == 1 and ky == 1):
        return list(layers)
    c = QPointF(0, 0) if about_frame else region(layers).boundingRect().center()
    return [l.mapped(QTransform().translate(c.x(), c.y()).scale(kx, ky).translate(-c.x(), -c.y())) for l in layers]


def add(groups):
    """The layers of the inputs one over the other (the later on top)."""
    return [l for g in groups for l in g]


def signature(layers):
    """Something that is the same while the drawing is."""
    h = hashlib.sha1()
    for l in layers:
        p = l.path
        h.update(repr((_paint_key(l.fill), _paint_key(l.stroke), round(l.width, 3), l.join, l.align, p.fillRule() == Qt.WindingFill, p.elementCount())).encode())
        h.update(b"".join(("%d:%.2f:%.2f;" % (e.type.value, e.x, e.y)).encode() for e in (p.elementAt(i) for i in range(p.elementCount()))))
    return h.hexdigest()


# -- drawing ---------------------------------------------------------------------------------------------------------------
def _qcolour(c):
    if isinstance(c, QBrush):
        return c
    return QColor.fromRgbF(*[min(max(x, 0.0), 1.0) for x in c])


def _qcolor_of(hexa):
    r, g, b, a = assets.to_rgba(hexa)
    return QColor.fromRgbF(r, g, b, a)


PICTURE_PX = 2048


def _cover_image(img, w, h):
    """The picture scaled to cover a w x h box and cut to it from the middle (an SVG's preserveAspectRatio slice)."""
    k = min(1.0, PICTURE_PX / max(w, h, 1.0))
    bw, bh = max(1, round(w * k)), max(1, round(h * k))
    big = img.scaled(bw, bh, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    return big.copy((big.width() - bw) // 2, (big.height() - bh) // 2, bw, bh), k


def paint_of(q, pre, w, h):
    """How the fill (pre "fill") or outline ("stroke") of built-in shape parameters q (assets.at) is painted over its w x h box
    (origin at its middle): a colour tuple, or a QBrush for a gradient, a texture or a picture."""
    c = q.get("color") if pre == "fill" else q.get("stroke_color", "#000000")
    c2 = q.get(pre + "_color2", "#000000")
    kind = q.get(pre + "_type", "solid")
    plain = tuple(assets.to_rgba(c, (0.0, 0.0, 0.0, 1.0) if pre == "stroke" else (1.0, 1.0, 1.0, 1.0)))
    if kind == "gradient":
        stops = q.get(pre + "_stops") or None
        if q.get(pre + "_gtype", "linear") == "radial":
            g = QRadialGradient(0.0, 0.0, math.hypot(w, h) / 2)
            pts = stops or [(0.35, c), (1.0, c2)]
            if not stops:
                g.setColorAt(0.0, _qcolor_of(c))
        else:
            r = math.radians(q.get(pre + "_angle", 0))
            dx, dy = math.cos(r), math.sin(r)
            half = (abs(dx) * w + abs(dy) * h) / 2
            g = QLinearGradient(-dx * half, -dy * half, dx * half, dy * half)
            pts = stops or [(0.0, c), (1.0, c2)]
        for x, col in pts:
            g.setColorAt(min(max(float(x), 0.0), 1.0), _qcolor_of(col))
        return QBrush(g)
    img = None
    if kind in textures.KINDS:
        from PIL import Image
        a = textures.render(kind, max(1, round(w)), max(1, round(h)), q.get(pre + "_scale", 5), q.get(pre + "_seed", 0), q.get(pre + "_z", 0),
                            assets.to_rgba(c), assets.to_rgba(c2, (0.0, 0.0, 0.0, 1.0)))
        from PIL.ImageQt import ImageQt
        img = QImage(ImageQt(Image.fromarray(a, "RGBA"))).convertToFormat(QImage.Format_ARGB32_Premultiplied)
    elif kind == "image" and q.get(pre + "_image"):
        path = q[pre + "_image"]
        if svgimage.is_svg(path):
            try:
                sw, sh = svgimage.size(path)
                k = PICTURE_PX / max(sw, sh)
                img = svgimage.raster(path, sw * k, sh * k)
            except ValueError:
                img = None
        else:
            img = QImage(path)
            img = None if img.isNull() else img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    if img is None or img.isNull():
        return plain
    img, k = _cover_image(img, w, h)
    brush = QBrush(img)
    brush.setTransform(QTransform().translate(-w / 2, -h / 2).scale(1 / k, 1 / k))
    return brush


def render(layers, w, h, k=1.0):
    """The layers drawn into a w x h picture (ARGB32 premultiplied, transparent): their canvas px, centred on 0, k picture px each."""
    img = QImage(max(1, w), max(1, h), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing)
    p.translate(w / 2, h / 2)
    p.scale(k, k)
    for l in layers:
        if l.fill:
            p.fillPath(l.path, _qcolour(l.fill))
        if l.stroke and l.width > 0:
            joins = {"round": Qt.RoundJoin, "bevel": Qt.BevelJoin}.get(l.join, Qt.MiterJoin)
            if l.align == "center":
                pen = QPen(_qcolour(l.stroke), l.width, Qt.SolidLine, Qt.FlatCap, joins)
                p.strokePath(l.path, pen)
            else:                                    # (twice as wide, the other half cut off by the outline)
                pen = QPen(_qcolour(l.stroke), 2 * l.width, Qt.SolidLine, Qt.FlatCap, joins)
                p.save()
                if l.align == "inside":
                    p.setClipPath(l.path)
                else:
                    cut = QPainterPath()
                    cut.addRect(QRectF(-w / k, -h / k, 2 * w / k, 2 * h / k))
                    p.setClipPath(cut.subtracted(l.path))
                p.strokePath(l.path, pen)
                p.restore()
    p.end()
    return img
