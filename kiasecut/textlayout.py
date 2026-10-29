"""Text rendering that reproduces Jianying's layout.

Calibrated frame by frame against a Jianying export:
  * em (px) = font size * PX_PER_FONT_UNIT on a 1080-high canvas, times the clip scale
  * letter spacing adds letter_spacing * em between characters (not after the last)
  * line pitch is exactly em * (1 + line_spacing) for fonts with ascent + descent = 1 em
  * the box grows to fit glyphs above the ascent (first line) / below the descent (last)
  * lines are centred (or, by spec["align"], left / right aligned or justified: every line
    but the last spread to the widest one, as CSS does); the box centre is the clip
    position; italic shears about the centre
  * a 文字框 (box_w / box_h, in px of a 1080-high canvas at scale 1; 0 or none: as wide /
    as high as the text, the default) is like Lunacy's fixed-size text: lines wrap at its
    width (a Latin word goes down whole, CJK breaks anywhere) and the text sits at its top,
    middle or bottom (spec["valign"]); text that does not fit runs over it. Its centre is
    the clip position
"""
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import curves, fonts

PX_PER_FONT_UNIT = 11.13
FALLBACK_FONTS = [
    r"C:\Windows\Fonts\GenSekiGothic2-M.ttc", r"C:\Windows\Fonts\msjh.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]
_fonts = {}
MAX_FONTS = 24      # a CJK face is ~10 MB in memory: a size that is animated asks for a new one every frame


def font(path, size):
    path = fonts.resolve(path)                  # a font this system lacks: its stand-in (font map)
    size = max(size, 0.01)                      # (字號 0: FreeType wants more than nothing; draws nothing seen)
    key = (path, round(size * 100))
    if key in _fonts:
        _fonts[key] = _fonts.pop(key)           # (most recently used last)
    else:
        while len(_fonts) >= MAX_FONTS:
            del _fonts[next(iter(_fonts))]
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


def boxed(tx):
    """Whether text spec tx has a fixed frame (文字框): a width it wraps in or a height it
    sits in (box_w / box_h above 0, either can have keyframes)."""
    return any(curves.max_abs(tx.get(k) or 0.0) > 0 for k in ("box_w", "box_h"))


def _wordish(ch):
    """A letter or digit of a word that wraps whole (not CJK, which breaks anywhere)."""
    return ch.isalnum() and ord(ch) < 0x2E80


def _layout(spec, scale, canvas_h):
    text = spec["content"]
    unit = PX_PER_FONT_UNIT * canvas_h / 1080 * scale
    base_em = spec.get("size", 5.0) * unit
    ls = spec.get("letter_spacing", 0.0)
    lsp = spec.get("line_spacing", 0.0)
    path = spec.get("font_path")
    px = canvas_h / 1080 * scale
    fix_w = max(0.0, spec.get("box_w") or 0.0) * px
    fix_h = max(0.0, spec.get("box_h") or 0.0) * px
    limit = fix_w + 0.01 * base_em                # (a width measured from the text fits it again)

    def rebase(glyphs):
        x0 = glyphs[0][0] if glyphs else 0.0
        return [(g[0] - x0,) + g[1:] for g in glyphs]

    def width(glyphs):
        return glyphs[-1][0] + glyphs[-1][4] if glyphs else 0.0

    lines, cur = [], []
    for i, ch in enumerate(text):
        if ch == "\n":
            lines.append(cur)
            cur = []
            continue
        st = _style_at(spec, i)
        em = st.get("size", spec.get("size", 5.0)) * unit
        f = with_fallback(font(st.get("font_path") or path, em), ch, em)
        col = st.get("color") or spec.get("color") or [1, 1, 1]
        rgba = tuple(int(round(v * 255)) for v in col[:3]) + (255,)
        # unhinted advance: small sizes round each glyph and drift across a long line
        adv = font(f.path, 1000).getlength(ch) / 1000 * em
        x = width(cur) + ls * base_em if cur else 0.0
        if fix_w and cur and x + adv > limit:      # 文字框: wrap
            if ch.isspace():
                lines.append(cur)
                cur = []
                continue
            sp = next((j for j in range(len(cur) - 1, -1, -1) if cur[j][1].isspace()), None)
            if _wordish(ch) and sp is not None and sp > 0 and all(_wordish(g[1]) for g in cur[sp + 1:]):
                lines.append(cur[:sp])             # a word goes down whole
                cur = rebase(cur[sp + 1:])
            else:
                lines.append(cur)
                cur = []
            x = width(cur) + ls * base_em if cur else 0.0
        cur.append((x, ch, f, rgba, adv))
    lines.append(cur)
    lines = [(g, width(g)) for g in lines]

    # PIL rounds metrics up to whole pixels; use exact ratios
    asc, desc = (m / 1000 * base_em for m in font(path, 1000).getmetrics())
    line_h = asc + desc
    step = line_h + lsp * base_em
    content_w = max(w for _, w in lines)

    def ink(glyphs, top):
        vals = [(-g[2].getbbox(g[1], anchor="ls")[1]) if top else g[2].getbbox(g[1], anchor="ls")[3]
                for g in glyphs if g[1].strip()]
        return max(vals, default=0)

    ext_top = max(0.0, ink(lines[0][0], True) - asc)
    ext_bot = max(0.0, ink(lines[-1][0], False) - desc)
    content_h = ext_top + line_h + step * (len(lines) - 1) + ext_bot
    fw, fh = fix_w or content_w, fix_h or content_h
    # where the text's top is, from the frame's centre (垂直對齊)
    ct = {"middle": -content_h / 2, "bottom": fh / 2 - content_h}.get(spec.get("valign"), -fh / 2)
    return dict(lines=lines, base_em=base_em, asc=asc, step=step, ext_top=ext_top, fw=fw, fh=fh, ct=ct,
                half_w=max(fw / 2, content_w - fw / 2), half_h=max(fh / 2, -ct, ct + content_h))


def frame_size(spec, canvas_h=1080, scale=1.0):
    """(w, h) of the text's frame in px: its 文字框 where fixed, else what the text takes up
    (without render's margin for overhangs and slant)."""
    lay = _layout(spec, scale, canvas_h)
    return lay["fw"], lay["fh"]


def _dilate(a, r):
    """a (uint8, H x W) grown by a round brush of radius r px: every pixel takes the largest value within r."""
    if r <= 0:
        return a
    h, w = a.shape
    pad = np.pad(a, r)
    rows = [int(math.sqrt(r * r - dy * dy) + 0.5) for dy in range(-r, r + 1)]
    out = a.copy()
    wide = pad                                               # pad grown sideways by k px
    for k in range(r + 1):
        if k:
            wide = np.maximum(wide, np.maximum(np.roll(pad, k, 1), np.roll(pad, -k, 1)))
        for i, hw in enumerate(rows):
            if hw == k:
                np.maximum(out, wide[i:i + h, r:r + w], out=out)
    return out


def render(spec, scale, canvas_h=1080):
    """Render text spec at `scale` (1 = clip scale 1). Returns an RGBA image whose centre
    is the text box centre (the 文字框's, when it has one)."""
    lay = _layout(spec, scale, canvas_h)
    lines, base_em, fw = lay["lines"], lay["base_em"], lay["fw"]
    shear = math.tan(math.radians(spec.get("italic_deg", 0.0)))
    stroke_width = max(0, int(round(spec.get("stroke", 2.0) * canvas_h / 1080 * scale))) \
        if spec.get("stroke_on", False) else 0
    stroke_align = spec.get("stroke_align", "inside")
    pad = int(base_em * (0.3 + abs(shear))) + (stroke_width if stroke_align != "inside" else 0) + 4
    W = int(math.ceil(2 * lay["half_w"])) + 2 * pad
    H = int(math.ceil(2 * lay["half_h"])) + 2 * pad
    W += W % 2
    H += H % 2
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    glyph_mask = Image.new("L", im.size, 0) if stroke_width else None
    mask_draw = ImageDraw.Draw(glyph_mask) if glyph_mask else None
    align = spec.get("align") or "center"
    fill_on = spec.get("fill", True)
    for li, (glyphs, lw) in enumerate(lines):
        left = (W - fw) / 2
        ox = {"left": left, "justify": left, "right": left + fw - lw}.get(align, (W - lw) / 2)
        spread = 0.0
        if align == "justify" and li < len(lines) - 1 and len(glyphs) > 1:
            spread = (fw - lw) / (len(glyphs) - 1)          # between every two characters
        top = H / 2 + lay["ct"] + lay["ext_top"] + li * lay["step"]
        for gi, (gx, ch, f, rgba, _adv) in enumerate(glyphs):
            at = (ox + gx + gi * spread, top + lay["asc"])
            dr.text(at, ch, font=f, fill=rgba if fill_on else (0, 0, 0, 0), anchor="ls")
            if mask_draw:
                mask_draw.text(at, ch, font=f, fill=255, anchor="ls")
    if glyph_mask:
        radius = stroke_width if stroke_align != "center" else (stroke_width + 1) // 2
        g = np.asarray(glyph_mask)
        expanded = _dilate(g, radius) if stroke_align != "inside" else g
        contracted = 255 - _dilate(255 - g, radius) if stroke_align != "outside" else g
        outline = np.clip(expanded.astype(np.int16) - contracted, 0, 255).astype(np.uint8)
        stroke_color = tuple(int(round(v * 255)) for v in (spec.get("stroke_color") or [0, 0, 0])[:3]) + (255,)
        stroke_layer = Image.new("RGBA", im.size, stroke_color)
        stroke_layer.putalpha(Image.fromarray(outline, "L"))
        im = Image.alpha_composite(im, stroke_layer)             # (the outline over the fill: inside and centre show)
    if shear:
        im = im.transform(im.size, Image.AFFINE, (1, shear, -shear * H / 2, 0, 1, 0),
                          resample=Image.BICUBIC)
    return im
