"""The fonts painters are given stay loaded.

Qt keeps the fonts it has loaded only while something uses them once there are many of them (its font cache lets go of
every font nothing holds each time another is loaded, past 256), and a font made for one drawing - QFont("Segoe UI", 8)
in a paintEvent - is held by nothing when the drawing is over. On a tablet there are that many (a text with letters of
another script loads a font for each: Roboto has no 中文, no かな, no ✦), so each drawing of the timeline loaded Noto Sans
CJK again from its file to write one clip's name: 10 to 25 ms, forty times a second while playing.

install() makes QPainter.setFont keep a copy of each font it is given (the newest KEPT of them): the copy holds what
the font loaded, so the next QFont of the same family and size finds it loaded.
"""
from collections import OrderedDict

from PySide6.QtGui import QPainter

KEPT = 64                        # fonts held (a zoomed view's font is another size at every step)
_kept = OrderedDict()            # QFont.key() -> the painter's font of it, least recently set first
_set_font = None


def _keep(painter, font):
    _set_font(painter, font)
    key = font.key()
    if key in _kept:
        _kept.move_to_end(key)
        return
    _kept[key] = painter.font()                 # (the painter's own: the one that loads what is drawn with it)
    while len(_kept) > KEPT:
        _kept.popitem(last=False)


def install():
    global _set_font
    if _set_font is None:
        _set_font = QPainter.setFont
        QPainter.setFont = _keep


def uninstall():
    global _set_font
    if _set_font is not None:
        QPainter.setFont = _set_font
        _set_font = None
        _kept.clear()
