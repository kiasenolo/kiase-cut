"""Monochrome icons drawn with QPainter (no image files): icon(name) -> QIcon.

Drawn on a 24-unit grid in the UI's light grey, with a dimmer copy for disabled buttons and
a dark copy for checked (light) buttons.
"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

INK, DIM, DARK = "#d6d6d8", "#5c5c62", "#151517"
_cache = {}


def _poly(p, pts):
    p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))


def _draw(p, name):
    pen = p.pen()
    if name == "play":
        _poly(p, [(7, 5), (19, 12), (7, 19)])
    elif name == "pause":
        p.drawRect(QRectF(7, 5, 3.5, 14))
        p.drawRect(QRectF(13.5, 5, 3.5, 14))
    elif name in ("prev", "next"):
        s = 1 if name == "next" else -1
        _poly(p, [(12 - 5 * s, 6), (12 + 4 * s, 12), (12 - 5 * s, 18)])
        p.drawRect(QRectF(12 + 4.5 * s - (0 if s > 0 else 2), 6, 2, 12))
    elif name in ("start", "end"):
        s = 1 if name == "end" else -1
        for dx in (-4, 3):
            _poly(p, [(12 + (dx - 3) * s, 6), (12 + (dx + 4) * s, 12), (12 + (dx - 3) * s, 18)])
        p.drawRect(QRectF(12 + 7.5 * s - (0 if s > 0 else 2), 6, 2, 12))
    elif name == "fullscreen":
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(pen.color(), 2))
        for x, y, dx, dy in ((4, 4, 1, 1), (20, 4, -1, 1), (4, 20, 1, -1), (20, 20, -1, -1)):
            p.drawPolyline(QPolygonF([QPointF(x, y + 5 * dy), QPointF(x, y), QPointF(x + 5 * dx, y)]))
    elif name in ("undo", "redo"):
        s = 1 if name == "redo" else -1
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(pen.color(), 2))
        path = QPainterPath(QPointF(12 + 6 * s, 10))
        path.cubicTo(QPointF(12 + 2 * s, 5), QPointF(12 - 7 * s, 6), QPointF(12 - 7 * s, 13))
        path.cubicTo(QPointF(12 - 7 * s, 18), QPointF(12 - 2 * s, 19), QPointF(12 + 1 * s, 19))
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(pen.color())
        _poly(p, [(12 + 9 * s, 11), (12 + 7 * s, 4), (12 + 2 * s, 9.5)])
    elif name == "blade":                                  # razor blade (split)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(pen.color(), 2))
        p.drawLine(QPointF(12, 3), QPointF(12, 21))
        p.setPen(Qt.NoPen)
        p.setBrush(pen.color())
        _poly(p, [(6, 7), (11, 9.5), (6, 12)])
        _poly(p, [(18, 12), (13, 14.5), (18, 17)])
    elif name == "trash":
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(pen.color(), 2))
        p.drawLine(QPointF(5, 7), QPointF(19, 7))
        p.drawLine(QPointF(10, 4.5), QPointF(14, 4.5))
        p.drawPolyline(QPolygonF([QPointF(7, 7), QPointF(8, 20), QPointF(16, 20), QPointF(17, 7)]))
        p.drawLine(QPointF(10.5, 10), QPointF(10.5, 17))
        p.drawLine(QPointF(13.5, 10), QPointF(13.5, 17))
    elif name == "text":
        p.drawRect(QRectF(5, 5, 14, 3))
        p.drawRect(QRectF(10.5, 5, 3, 14))
    elif name == "magnet":                                 # snapping
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(pen.color(), 3.2, Qt.SolidLine, Qt.FlatCap))
        path = QPainterPath(QPointF(6.5, 5))
        path.lineTo(6.5, 12)
        path.arcTo(QRectF(6.5, 6.5, 11, 11), 180, 180)
        path.lineTo(17.5, 5)
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(pen.color())
        p.drawRect(QRectF(4.9, 3, 3.2, 3))
        p.drawRect(QRectF(15.9, 3, 3.2, 3))
    elif name == "plus":
        p.drawRect(QRectF(11, 5, 2.4, 14))
        p.drawRect(QRectF(5, 10.8, 14, 2.4))
    elif name == "back":
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(pen.color(), 2))
        p.drawPolyline(QPolygonF([QPointF(11, 6), QPointF(5, 12), QPointF(11, 18)]))
        p.drawLine(QPointF(5, 12), QPointF(19, 12))
    elif name == "height":                                 # track height
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(pen.color(), 2))
        p.drawLine(QPointF(12, 4), QPointF(12, 20))
        p.drawPolyline(QPolygonF([QPointF(8, 8), QPointF(12, 4), QPointF(16, 8)]))
        p.drawPolyline(QPolygonF([QPointF(8, 16), QPointF(12, 20), QPointF(16, 16)]))
    elif name == "timeline":
        for y, x0, x1 in ((6, 4, 14), (11, 8, 20), (16, 4, 17)):
            p.drawRoundedRect(QRectF(x0, y - 1.6, x1 - x0, 3.2), 1, 1)


def icon(name, size=24):
    key = (name, size)
    if key in _cache:
        return _cache[key]
    ic = QIcon()
    for mode, color in ((QIcon.Normal, INK), (QIcon.Disabled, DIM), (QIcon.Selected, DARK)):
        for state in (QIcon.Off, QIcon.On):
            pm = QPixmap(size * 2, size * 2)              # drawn at 2x for high-dpi screens
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            p.scale(size * 2 / 24, size * 2 / 24)
            ink = QColor(DARK if state == QIcon.On and mode == QIcon.Normal else color)
            p.setPen(QPen(ink, 1))
            p.setBrush(ink)
            _draw(p, name)
            p.end()
            pm.setDevicePixelRatio(2)
            ic.addPixmap(pm, mode, state)
    _cache[key] = ic
    return ic
