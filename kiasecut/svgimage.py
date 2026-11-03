"""SVG pictures: vector images drawn at whatever size they are shown, so they stay sharp.

An SVG is used like any other picture (an "image" clip); only decoding differs: QImage would
draw it once at its nominal size, so the renderer, the export and the library ask this module
for a raster at the size they need. Needs a Qt GUI application (the program always has one).
"""
import math
import os

import numpy as np

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

EXT = {".svg"}
MAX_PX = 8192                  # longest side of any raster made from an SVG
DEFAULT_PX = 512               # an SVG without a size or viewBox


def is_svg(path):
    return os.path.splitext(path or "")[1].lower() in EXT


def _renderer(path):
    r = QSvgRenderer(path)
    if not r.isValid():
        raise ValueError(f"cannot read SVG {os.path.basename(str(path))}")
    r.setAspectRatioMode(Qt.KeepAspectRatio)
    return r


def size(path):
    """(width, height) of an SVG: its size, else its viewBox, else a square."""
    r = _renderer(path)
    s = r.defaultSize()
    if s.width() > 0 and s.height() > 0:
        return s.width(), s.height()
    box = r.viewBoxF()
    if box.width() > 0 and box.height() > 0:
        k = DEFAULT_PX / max(box.width(), box.height())
        return max(1, round(box.width() * k)), max(1, round(box.height() * k))
    return DEFAULT_PX, DEFAULT_PX


def raster_text(text, w, h):
    """SVG text drawn into a w x h transparent picture (ARGB32 premultiplied); built-in
    assets (assets.svg) are drawn this way, from their parameters at each moment."""
    k = min(1.0, MAX_PX / max(w, h, 1))
    w, h = max(1, round(w * k)), max(1, round(h * k))
    img = QImage(QSize(w, h), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    r = QSvgRenderer(QByteArray(text.encode("utf-8")))
    r.render(p, QRectF(0, 0, w, h))
    p.end()
    return img


def raster(path, w, h=None):
    """The SVG drawn into a w x h transparent picture (h from its proportions when None),
    ARGB32 premultiplied; never larger than MAX_PX on its long side."""
    sw, sh = size(path)
    if h is None:
        h = w * sh / sw
    k = min(1.0, MAX_PX / max(w, h, 1))
    w, h = max(1, round(w * k)), max(1, round(h * k))
    img = QImage(QSize(w, h), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    _renderer(path).render(p, QRectF(0, 0, w, h))
    p.end()
    return img


def inward(alpha, reach):
    """How far inside the edge each pixel of a shape is (px; 0 outside), from its alpha (0..255) - a distance field as Blender's
    Vignette measures. Made on a picture shrunk until `reach` is a few dozen px (the field is smooth: only its slope matters),
    then spread back up bilinearly."""
    h, w = alpha.shape
    k = max(1, math.ceil(reach / 48))
    if k > 1:
        H, W = -(-h // k), -(-w // k)
        pad = np.zeros((H * k, W * k), np.float32)
        pad[:h, :w] = alpha
        inside = pad.reshape(H, k, W, k).mean(axis=(1, 3)) >= 127.5
    else:
        inside = alpha >= 127.5
    reach_l = reach / k + 1
    r = int(math.ceil(reach_l)) + 1
    m = np.pad(inside, 1)                                    # (the frame's border is outside)
    H2, W2 = m.shape
    y = np.arange(H2, dtype=np.float32)[:, None]
    up = np.maximum.accumulate(np.where(~m, y, -1e9), axis=0)
    down = np.minimum.accumulate(np.where(~m, y, 1e9)[::-1], axis=0)[::-1]
    g = np.minimum(y - up, down - y)                         # (to the nearest outside pixel of the same column)
    g = np.minimum(g, r + 1.0)
    g2 = g * g
    d2 = g2.copy()
    for dx in range(1, r + 1):                               # (then along the row, as a lower envelope of parabolas)
        c = float(dx * dx)
        np.minimum(d2[:, dx:], g2[:, :-dx] + c, out=d2[:, dx:])
        np.minimum(d2[:, :-dx], g2[:, dx:] + c, out=d2[:, :-dx])
    dist = np.sqrt(d2)[1:-1, 1:-1] * m[1:-1, 1:-1] - 0.5 * m[1:-1, 1:-1]
    dist = np.maximum(dist, 0.0) * k
    if k == 1:
        return dist
    for ax, n in ((0, h), (1, w)):                           # bilinear back to the picture's size
        src = (np.arange(n, dtype=np.float32) + 0.5) / k - 0.5
        i0 = np.clip(np.floor(src).astype(int), 0, dist.shape[ax] - 1)
        i1 = np.clip(i0 + 1, 0, dist.shape[ax] - 1)
        f = np.clip(src - i0, 0.0, 1.0)
        a, b = np.take(dist, i0, axis=ax), np.take(dist, i1, axis=ax)
        dist = a + (b - a) * (f[:, None] if ax == 0 else f[None, :])
    return dist


def faded(fill, mask, reach):
    """The fill picture (ARGB32 premultiplied) fading in from clear at the edge of the shape in `mask` to itself `reach` px
    inside, as a smoothstep of the distance - the curve of Blender's Vignette."""
    w, h = fill.width(), fill.height()
    view = lambda im: np.frombuffer(im.constBits(), np.uint8).reshape(h, im.bytesPerLine() // 4, 4)[:, :w]
    d = inward(view(mask)[..., 3].astype(np.float32), reach)
    t = np.clip(d / max(reach, 1e-6), 0.0, 1.0)
    m = np.rint(t * t * (3.0 - 2.0 * t) * 256).astype(np.uint16)[..., None]
    out = np.ascontiguousarray(((view(fill).astype(np.uint16) * m + 128) >> 8).astype(np.uint8))
    return QImage(out.data, w, h, w * 4, QImage.Format_ARGB32_Premultiplied).copy()
