"""SVG pictures: vector images drawn at whatever size they are shown, so they stay sharp.

An SVG is used like any other picture (an "image" clip); only decoding differs: QImage would
draw it once at its nominal size, so the renderer, the export and the library ask this module
for a raster at the size they need. Needs a Qt GUI application (the program always has one).
"""
import os

from PySide6.QtCore import QRectF, QSize, Qt
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
        raise ValueError(f"cannot read SVG {os.path.basename(path)}")
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
