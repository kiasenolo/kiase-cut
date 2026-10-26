"""Text rendering that reproduces Jianying's layout.

Calibrated frame by frame against a Jianying export:
  * em (px) = font size * PX_PER_FONT_UNIT on a 1080-high canvas, times the clip scale
  * letter spacing adds letter_spacing * em between characters (not after the last)
  * line pitch is exactly em * (1 + line_spacing) for fonts with ascent + descent = 1 em
  * the box grows to fit glyphs above the ascent (first line) / below the descent (last)
  * lines are centred (or, by spec["align"], left / right aligned or justified: every line
    but the last spread to the widest one, as CSS does); the box centre is the clip
    position; italic shears about the centre
"""
import math
import os

from PIL import Image, ImageDraw, ImageFont

from . import fonts

PX_PER_FONT_UNIT = 11.13
FALLBACK_FONTS = [
    r"C:\Windows\Fonts\GenSekiGothic2-M.ttc", r"C:\Windows\Fonts\msjh.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]
_fonts = {}


def font(path, size):
    path = fonts.resolve(path)                  # a font this system lacks: its stand-in (font map)
    key = (path, round(size * 100))
    if key not in _fonts:
        for p in [path] + FALLBACK_FONTS:
            if p and os.path.exists(p):
                _fonts[key] = ImageFont.truetype(p, size, index=0)
                break
        else:
            _fonts[key] = ImageFont.load_default(size)
    return _fonts[key]


_has = {}


def has_glyph(f, ch):
    """Whether font f draws ch (a font without it draws its "missing" box, the same one it
    draws for a code point no font has)."""
    if ch.isspace() or ord(ch) < 128:
        return True
    key = (f.path, ch)
    if key not in _has:
        try:
            _has[key] = bytes(f.getmask(ch)) != bytes(f.getmask("\uffff"))
        except (OSError, ValueError):
            _has[key] = True
    return _has[key]


def with_fallback(f, ch, em):
    """f, or a font that has ch (a Latin-only font picked for Chinese text, say)."""
    if has_glyph(f, ch):
        return f
    for p in FALLBACK_FONTS:
        if os.path.exists(p) and p != f.path:
            g = font(p, em)
            if has_glyph(g, ch):
                return g
    return f


def _style_at(spec, i):
    for st in spec.get("styles") or []:
        a, b = st.get("range", [0, len(spec["content"])])
        if a <= i < b:
            return st
    return {}


def render(spec, scale, canvas_h=1080):
    """Render text spec at `scale` (1 = clip scale 1). Returns an RGBA image whose centre
    is the text box centre."""
    text = spec["content"]
    unit = PX_PER_FONT_UNIT * canvas_h / 1080 * scale
    base_em = spec.get("size", 5.0) * unit
    ls = spec.get("letter_spacing", 0.0)
    lsp = spec.get("line_spacing", 0.0)
    italic = spec.get("italic_deg", 0.0)
    path = spec.get("font_path")

    lines, cur, x = [], [], 0.0
    for i, ch in enumerate(text):
        if ch == "\n":
            lines.append((cur, x))
            cur, x = [], 0.0
            continue
        st = _style_at(spec, i)
        em = st.get("size", spec.get("size", 5.0)) * unit
        f = with_fallback(font(st.get("font_path") or path, em), ch, em)
        col = st.get("color") or spec.get("color") or [1, 1, 1]
        rgba = tuple(int(round(v * 255)) for v in col[:3]) + (255,)
        if cur:
            x += ls * base_em
        cur.append((x, ch, f, rgba))
        # unhinted advance: small sizes round each glyph and drift across a long line
        x += font(f.path, 1000).getlength(ch) / 1000 * em
    lines.append((cur, x))

    # PIL rounds metrics up to whole pixels; use exact ratios
    asc, desc = (m / 1000 * base_em for m in font(path, 1000).getmetrics())
    line_h = asc + desc
    step = line_h + lsp * base_em
    box_w = max(w for _, w in lines)

    def ink(glyphs, top):
        vals = [(-g[2].getbbox(g[1], anchor="ls")[1]) if top else g[2].getbbox(g[1], anchor="ls")[3]
                for g in glyphs if g[1].strip()]
        return max(vals, default=0)

    ext_top = max(0.0, ink(lines[0][0], True) - asc)
    ext_bot = max(0.0, ink(lines[-1][0], False) - desc)
    box_h = ext_top + line_h + step * (len(lines) - 1) + ext_bot
    shear = math.tan(math.radians(italic))
    pad = int(base_em * (0.3 + abs(shear))) + 4
    W = int(math.ceil(box_w)) + 2 * pad
    H = int(math.ceil(box_h)) + 2 * pad
    W += W % 2
    H += H % 2
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    align = spec.get("align") or "center"
    for li, (glyphs, lw) in enumerate(lines):
        left = (W - box_w) / 2
        ox = {"left": left, "justify": left, "right": left + box_w - lw}.get(align, (W - lw) / 2)
        spread = 0.0
        if align == "justify" and li < len(lines) - 1 and len(glyphs) > 1:
            spread = (box_w - lw) / (len(glyphs) - 1)          # between every two characters
        top = (H - box_h) / 2 + ext_top + li * step
        for gi, (gx, ch, f, rgba) in enumerate(glyphs):
            dr.text((ox + gx + gi * spread, top + asc), ch, font=f, fill=rgba, anchor="ls")
    if shear:
        im = im.transform(im.size, Image.AFFINE, (1, shear, -shear * H / 2, 0, 1, 0),
                          resample=Image.BICUBIC)
    return im
