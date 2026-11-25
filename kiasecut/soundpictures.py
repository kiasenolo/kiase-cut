"""The pictures a node effect's 波形 and 頻譜 nodes draw of a sound: what soundmeter.py measured (a channel's tap: mono,
from the start of its level), round the moment drawn. The levels and the shapes are the Audio Visualizer's (viz.py), so
the two look alike; as there, nothing is kept between frames but caches - the same moment always looks the same,
wherever the playhead jumped from.

Sizes in `values` (line_w, bar_w, gap) are canvas pixels; `unit` is how many picture pixels one of them is."""
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF

from . import viz

US = viz.US
MAX_BARS, MAX_POINTS = 512, 240


def window(sound, level_us, n):
    """float32 [n, 2] of the n samples centred on time level_us of mono `sound` (None: silence), as both channels."""
    out = np.zeros(n, np.float32)
    if sound is not None:
        a = int(level_us * viz.RATE / US) - n // 2
        lo, hi = max(a, 0), min(a + n, len(sound))
        if hi > lo:
            out[lo - a:hi - a] = sound[lo:hi]
    return np.repeat(out[:, None], 2, axis=1)


def columns(x, count):
    """(lowest, highest) of each of `count` stretches of x (a stretch shorter than a sample reads its nearest)."""
    edges = np.linspace(0, len(x), count + 1)
    lo = np.minimum(edges[:-1].astype(int), len(x) - 1)
    hi = np.clip(np.ceil(edges[1:]).astype(int), lo + 1, len(x))
    return (np.array([x[a:b].min() for a, b in zip(lo, hi)]), np.array([x[a:b].max() for a, b in zip(lo, hi)]))


def _colour(values):
    return viz._qc(values.get("color") or [1.0, 1.0, 1.0, 1.0])


def _pen(colour, width):
    return QPen(colour, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)


def _waveform(p, values, sound, level_us, w, h, unit):
    n = max(16, int(values["length_ms"] / 1000.0 * viz.RATE))
    x = window(sound, level_us, n)[:, 0]
    line = max(0.5, values["line_w"] * unit)
    mid, tall = h / 2, h / 2 - (line / 2 if values["style"] == "線" else 0.0)
    if values["style"] == "填滿":                            # (how far the sound swings in each stretch, both ways)
        count = max(24, min(MAX_POINTS, int(w / 4)))
        lo, hi = columns(np.abs(x), count)
        v = viz.smooth_across(hi, values["smooth"])
        xs = np.linspace(0, w, count)
        top = [QPointF(a, mid - float(min(b, 1.0)) * tall - 0.5) for a, b in zip(xs, v)]      # (silence: a hairline)
        bottom = [QPointF(a, mid + float(min(b, 1.0)) * tall + 0.5) for a, b in zip(xs, v)]
        path = viz._curve(top)
        path.connectPath(viz._curve(bottom[::-1]))
        path.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(_colour(values))
        p.drawPath(path)
        return
    xs, top, bottom = outline(mid - np.clip(x, -1.0, 1.0) * tall, w, line / 2)
    p.setPen(Qt.NoPen)
    p.setBrush(_colour(values))
    p.drawPolygon(QPolygonF([QPointF(a, b) for a, b in zip(xs, top.tolist())]
                            + [QPointF(a, b) for a, b in zip(xs[::-1], bottom[::-1].tolist())]), Qt.WindingFill)


def outline(y, w, radius):
    """(x, top, bottom) of what a round pen of this radius covers along the line through heights y spread over width w, one
    place per pixel column. (Qt strokes a dense sound hundreds of times slower than it fills this.)"""
    count = max(2, int(w))
    edges = np.linspace(0, len(y) - 1, count + 1)
    at_edges = np.interp(edges, np.arange(len(y)), y)
    low, high = np.minimum(at_edges[:-1], at_edges[1:]), np.maximum(at_edges[:-1], at_edges[1:])
    first = np.ceil(edges).astype(int)                       # (the samples inside each column)
    inside = first[1:] > first[:-1]
    start = np.minimum(first[:-1], len(y) - 1)
    low = np.where(inside, np.minimum(low, np.minimum.reduceat(y, start)), low)
    high = np.where(inside, np.maximum(high, np.maximum.reduceat(y, start)), high)
    reach = int(radius)
    around_low, around_high = np.pad(low, reach, mode="edge"), np.pad(high, reach, mode="edge")
    top, bottom = low - radius, high + radius
    for k in range(-reach, reach + 1):                       # (the pen's round end, over the columns beside)
        tall = np.sqrt(max(radius * radius - k * k, 0.0))
        part = slice(reach + k, reach + k + count)
        top = np.minimum(top, around_low[part] - tall)
        bottom = np.maximum(bottom, around_high[part] + tall)
    return ((np.arange(count) + 0.5) * (w / count)).tolist(), top, bottom


def levels(values, count, sound, level_us, memo):
    """0 - 1 of each of `count` bars (or points) of the spectrum at level_us, with 啟動, 釋放 and 平滑."""
    f_lo = values["f_lo"]
    f_hi = min(max(values["f_hi"], f_lo + 1.0), viz.RATE / 2 - 1)
    floor, top = values["floor_db"], max(values["top_db"], values["floor_db"] + 6.0)
    key = (count, f_lo, f_hi, values["log"], floor, top)

    def raw_at(tt):
        make = lambda: viz.band_levels(viz.averaged_spectrum(lambda a, n: window(sound, a, n), tt, "M"), count, f_lo, f_hi,
                                       values["log"], floor, top)
        return memo((tt, key), make)
    v = viz.follow(raw_at, level_us, values["attack"], values["decay"])
    return np.clip(viz.smooth_across(v, values["smooth"]), 0.0, 1.0)


def _spectrum(p, values, sound, level_us, w, h, unit, memo):
    p.setBrush(_colour(values))
    if values["style"] == "曲線":
        count = max(16, min(MAX_POINTS, int(w / 4)))
        v = levels(values, count, sound, level_us, memo)
        line = max(0.5, values["line_w"] * unit)
        pts = [QPointF(x, h - line / 2 - float(a) * (h - line)) for x, a in zip(np.linspace(0, w, count), v)]
        p.setPen(_pen(_colour(values), line))
        p.setBrush(Qt.NoBrush)
        p.drawPath(viz._curve(pts))
        return
    bar, gap = max(1.0, values["bar_w"] * unit), max(0.0, values["gap"] * unit)
    count = max(1, min(MAX_BARS, int((w + gap) / (bar + gap))))
    v = levels(values, count, sound, level_us, memo)
    x0 = (w - (count * bar + (count - 1) * gap)) / 2
    p.setPen(Qt.NoPen)
    for i in range(count):
        tall = float(v[i]) * h
        if tall < 0.5:
            continue
        x, wide = x0 + i * (bar + gap), bar
        if gap <= 0.0:                                       # (touching bars share one whole-pixel edge: no hairline seam)
            x = round(x)
            wide = round(x0 + (i + 1) * bar) - x
        p.drawRect(QRectF(x, h - tall, wide, tall))


_raw = {}                                # (what the sound is, moment, settings) -> a spectrum's levels there
KEPT = 4000


def paint(kind, values, sound, level_us, w, h, unit, name=None):
    """The picture (w x h, premultiplied) a "waveform" or "spectrum" node with `values` (nodegraph.soundpic_of) gives
    at time level_us of the level its clip is on. sound: the tap it hears (None: silence); name: something that says
    which sound that is, to keep what is worked out of it (None: nothing is kept)."""
    img = QImage(max(1, int(w)), max(1, int(h)), QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing)

    def memo(key, make):
        if name is None:
            return make()
        got = _raw.get((name, key))
        if got is None:
            if len(_raw) >= KEPT:
                _raw.clear()
            got = _raw[name, key] = make()
        return got

    if kind == "waveform":
        _waveform(p, values, sound, level_us, img.width(), img.height(), unit)
    else:
        _spectrum(p, values, sound, level_us, img.width(), img.height(), unit, memo)
    p.end()
    return img
