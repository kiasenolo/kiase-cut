"""Audio Visualizer (音訊視覺化): a picture clip (type image, clip["viz"]) that draws the sound it
is given, drawn afresh for every frame by both renderers.

viz {kind, source, w, h, channel, attack, decay, color, color2, gradient, bar_w, gap, radius, mirror,
     radial, inner, f_lo, f_hi, log, smooth, line_w, grid}
  w, h     the object's size, in canvas pixels, as a shape's: the picture is exactly that rectangle (bars
           grow from its bottom edge up to its top, a wave or a scope fills its height, a vectorscope its
           shorter side, a circle's outer edge is half the shorter side)
  kind     bars (Spectrum Bars) | wave (Smooth Filled Waveform) | scope (Oscilloscope) |
           vector (Vectorscope: side against mid, as iZotope Ozone Imager draws it)
  source   {type: file, path} - an audio / video file, played from the clip's source_start_us as a
           clip of its own would | {type: compound, id} - what a compound clip plays (from its
           start + source_start_us) | {type: track, id} - one track of the level the clip is on,
           at the level's time
  channel  M (middle) | L | R | S (side) - what bars, wave and scope look at (vector sees both)
  attack / decay  seconds the picture takes to rise / fall (one-pole, as an envelope follower)
  bar_w / gap / radius / line_w / inner   pixels of the object's own size (they scale with it)
  f_lo..f_hi, log  the frequencies the bars cover and whether they sit evenly in octaves (log) or Hz
  smooth   0 - 1, how much neighbouring bars / points are blended
  mirror   bars and waves grow both ways;  radial  around a circle of radius `inner`
  gradient color at the foot to color2 at the top

Everything is worked out from the sound around the frame (Probe), nothing is kept between frames
but caches: the same moment always looks the same, wherever the playhead jumped from.
"""
import math
import os

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF

from . import audiomix, normalize, project, stretch

US = 1_000_000
RATE = audiomix.RATE
KINDS = {"bars": "Spectrum Bars", "wave": "Smooth Filled Waveform", "scope": "Oscilloscope", "vector": "Vectorscope"}
CHANNELS = (("M", "中 (M)"), ("L", "左 (L)"), ("R", "右 (R)"), ("S", "側 (S)"))
SOURCE_TYPES = ("file", "compound", "track")
STEP_US = US // 60                      # the moments a picture is worked out for (and cached by)
NFFT = 4096
FLOOR_DB, TOP_DB = -72.0, -6.0
TILT_DB = 3.0                           # dB per octave added, so the highs are not always low
LAUNCH = 3.0                            # a picture looks back this many time constants
MAX_BACK = 60                           # ... but at most this many steps
WAVE_US = 60_000                        # the sound a waveform looks at
SCOPE_N = 2048

DEFAULTS = {
    "kind": "bars", "w": 1920.0, "h": 420.0, "channel": "M", "attack": 0.02, "decay": 0.3,
    "color": [1.0, 1.0, 1.0, 1.0], "color2": [1.0, 0.35, 0.8, 1.0], "gradient": False,
    "bar_w": 12.0, "gap": 6.0, "radius": 0.0, "mirror": False, "radial": False, "inner": 120.0,
    "f_lo": 30.0, "f_hi": 16000.0, "log": True, "smooth": 0.4, "line_w": 4.0, "grid": True,
}
LIMITS = {"radius": (0.0, 400.0), "attack": (0.0, 2.0), "decay": (0.0, 3.0), "bar_w": (1.0, 400.0), "gap": (0.0, 400.0),
          "w": (1.0, 16384.0), "h": (1.0, 16384.0), "inner": (10.0, 3000.0), "f_lo": (20.0, 20000.0), "f_hi": (40.0, 24000.0),
          "smooth": (0.0, 1.0), "line_w": (0.5, 100.0)}


def make(kind, source, canvas_w=1920, canvas_h=1080):
    """The parameters of a new visualizer of this kind on this source, sized for a canvas_w x canvas_h
    canvas (pixels of it: 1080 high is what the line widths are made for)."""
    v = {k: (list(x) if isinstance(x, list) else x) for k, x in DEFAULTS.items()}
    v["kind"], v["source"] = kind, dict(source)
    k = canvas_h / 1080
    for f in ("bar_w", "gap", "inner", "line_w", "radius"):
        v[f] = round(v[f] * k, 1)
    v["w"], v["h"] = float(canvas_w), round(420.0 * k, 1)
    if kind == "wave":
        v["h"] = round(v["h"] * 0.6, 1)
    if kind == "vector":
        v["w"] = v["h"] = round(630.0 * k, 1)
        v["decay"] = 0.15
        v["line_w"] = round(v["line_w"] * 0.6, 1)
    return v


def migrate(c):
    """A visualizer saved with a 最大高度 (max_h) and the canvas for a size gets its own size (w, h)."""
    v = c.get("viz")
    if v and "w" not in v:
        mh = float(v.pop("max_h", 420.0))
        m = c.get("media") or {}
        v["w"], v["h"] = (mh, mh) if v.get("kind") == "vector" else (float(m.get("width", 1920)), mh)
        m["width"], m["height"] = int(round(v["w"])), int(round(v["h"]))
    elif v:
        v.pop("max_h", None)


def clean(v):
    """A viz dict with every field present and in range."""
    out = make(v.get("kind") if v.get("kind") in KINDS else "bars", v.get("source") or {"type": "track", "id": ""})
    for k, d in DEFAULTS.items():
        x = v.get(k, d)
        if isinstance(d, bool):
            out[k] = bool(x)
        elif isinstance(d, list):
            out[k] = [min(1.0, max(0.0, float(c))) for c in (list(x) + [1.0] * 4)[:4]]
        elif isinstance(d, (int, float)):
            lo, hi = LIMITS.get(k, (-1e9, 1e9))
            out[k] = min(hi, max(lo, float(x)))
        elif k == "channel":
            out[k] = x if x in "MLRS" and len(str(x)) == 1 else "M"
    if out["f_hi"] <= out["f_lo"]:
        out["f_hi"] = min(24000.0, out["f_lo"] * 2)
    return out


# -- the sound ----------------------------------------------------------------------------------------
class Probe:
    """The sound a visualizer looks at: windows of PCM around a moment, mixed as the clips sound, and
    the pictures' numbers worked out from them kept for a while."""

    def __init__(self, cache_dir):
        self.cache_dir = cache_dir
        self.decoded = {}               # dkey -> (pcm, offset)
        self.srcs = {}                  # what a source was made of -> [audiomix.Source], decoded
        self.raw = {}                   # (what, moment) -> numbers

    def _load(self, srcs):
        for s in srcs:
            dk = s.dkey()
            if dk not in self.decoded:
                try:
                    pcm, offset = audiomix.decode(self.cache_dir, s.key())
                    normalize.remember(s.key(), pcm)
                    if s.pitched:
                        sp = project.speed(s.clip)
                        pcm, offset = stretch.stretch_all(pcm, sp), round(offset / sp)
                except Exception:
                    pcm, offset = np.zeros((0, audiomix.CHANNELS), np.int16), 0
                self.decoded[dk] = (pcm, offset)
            s.pcm, s.offset = self.decoded[dk]
        return srcs

    def sources(self, c, source, compounds, tracks):
        """([audiomix.Source], mixed time of the clip's start in us) for a visualizer clip's source."""
        typ = (source or {}).get("type")
        if len(self.srcs) > 64:
            self.srcs.clear()
        if typ == "file":
            path = source.get("path") or ""
            key = ("file", path, c.get("source_start_us", 0), c["duration_us"])
            if key not in self.srcs:
                srcs = []
                if path and os.path.isfile(path):
                    pseudo = {"type": "audio", "media": {"path": path}, "start_us": 0, "source_start_us": c.get("source_start_us", 0),
                              "duration_us": c["duration_us"] + 100_000}
                    srcs = [audiomix.Source(pseudo, 0, (0, float("inf")))]
                self.srcs[key] = self._load(srcs)
            return self.srcs[key], 0
        if typ == "compound":
            comp = (compounds or {}).get(source.get("id"))
            if comp is None:
                return [], 0
            key = ("compound", source["id"], id(comp["tracks"]))
            if key not in self.srcs:
                self.srcs[key] = self._load(audiomix.sources(comp["tracks"]))
            return self.srcs[key], c.get("source_start_us", 0)
        if typ == "track":
            tr = next((t for t in tracks or [] if t["id"] == source.get("id")), None)
            if tr is None:
                return [], 0
            key = ("track", id(tr), id(tracks))
            if key not in self.srcs:
                self.srcs[key] = self._load(audiomix.sources(tracks, only=tr))
            return self.srcs[key], c["start_us"]
        return [], 0

    def window(self, c, spec, t_us, n, compounds, tracks):
        """float32 [n, 2] (-1 .. 1) of the sound centred on clip time t_us."""
        srcs, base = self.sources(c, spec["source"], compounds, tracks)
        if not srcs:
            return np.zeros((n, 2), np.float32)
        start = base + t_us - n / 2 / RATE * US
        return audiomix.mix_window(srcs, n, start) / 32768.0

    def cached(self, key, make):
        got = self.raw.get(key)
        if got is None:
            if len(self.raw) > 6000:
                self.raw.clear()
            got = self.raw[key] = make()
        return got


def mono(pcm, channel):
    l, r = pcm[:, 0], pcm[:, 1]
    return {"L": l, "R": r, "S": (l - r) * 0.5}.get(channel, (l + r) * 0.5)


def spectrum(x):
    """Amplitude (a sine of 1 gives about 1) of each frequency of a window of 4096 samples."""
    w = np.hanning(len(x))
    mag = np.abs(np.fft.rfft(x * w)) * 2.0 / max(w.sum(), 1.0)
    return mag


def band_levels(mag, n, f_lo, f_hi, log):
    """0 - 1 for each of n bars: the loudest frequency inside it, in dB between FLOOR_DB and TOP_DB."""
    hz = RATE / NFFT
    edges = np.geomspace(f_lo, f_hi, n + 1) if log else np.linspace(f_lo, f_hi, n + 1)
    lo, hi = edges[:-1] / hz, edges[1:] / hz
    top = len(mag) - 1
    out = np.empty(n)
    for i in range(n):
        a, b = int(math.floor(lo[i])), int(math.ceil(hi[i]))
        if b - a <= 1:                                    # narrower than a bin: where its middle falls
            out[i] = np.interp((lo[i] + hi[i]) / 2, np.arange(top + 1), mag)
        else:
            out[i] = mag[max(a, 0):min(b, top) + 1].max()
    centre = np.sqrt(edges[:-1] * edges[1:]) if log else (edges[:-1] + edges[1:]) / 2
    db = 20 * np.log10(np.maximum(out, 1e-7)) + TILT_DB * np.log2(np.maximum(centre, 1.0) / 1000.0)
    return np.clip((db - FLOOR_DB) / (TOP_DB - FLOOR_DB), 0.0, 1.0)


def smooth_across(v, amount):
    """v with each value blended with its neighbours (amount 0 - 1)."""
    k = int(round(amount * 4))
    if k <= 0 or len(v) < 3:
        return v
    kernel = np.hanning(2 * k + 3)[1:-1]
    kernel /= kernel.sum()
    pad = np.pad(v, k, mode="edge")
    return np.convolve(pad, kernel, mode="valid")


def follow(raw_at, t_us, attack, decay):
    """The envelope of raw_at(moment) numbers up to t_us: each step it moves toward the new number
    with the attack time (rising) or decay time (falling), starting from a few time constants back."""
    back = min(MAX_BACK, int(min(max(attack, decay) * LAUNCH * US, US) / STEP_US))
    k = int(math.floor(t_us / STEP_US))
    s = raw_at((k - back) * STEP_US)
    for i in range(k - back + 1, k + 1):
        r = raw_at(i * STEP_US)
        tau = np.where(r > s, attack, decay)
        s = s + (r - s) * (1.0 - np.exp(-(STEP_US / US) / np.maximum(tau, 1e-4)))
    return s


# -- the picture ---------------------------------------------------------------------------------------
def _qc(rgba, alpha=1.0):
    c = QColor.fromRgbF(*[min(1.0, max(0.0, float(x))) for x in (list(rgba) + [1.0])[:4]])
    c.setAlphaF(c.alphaF() * alpha)
    return c


def _fill(spec, y0, y1):
    """The brush that fills a bar or wave: one colour, or color at y0 to color2 at y1."""
    if not spec["gradient"]:
        return QBrush(_qc(spec["color"]))
    g = QLinearGradient(0, y0, 0, y1)
    g.setColorAt(0, _qc(spec["color"]))
    g.setColorAt(1, _qc(spec["color2"]))
    g.setSpread(QLinearGradient.ReflectSpread)
    return QBrush(g)


def paint(spec, probe, c, t_us, w, h, design_h, compounds=None, tracks=None):
    """The visualizer clip c at clip time t_us as a w x h picture."""
    img = QImage(max(1, w), max(1, h), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    spec = clean(spec)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing)
    u = h / max(spec["h"], 1.0)                         # (the object's own pixels: design_h is its size when it was made)
    sig = (repr(spec["source"]), c["start_us"], c.get("source_start_us", 0), spec["channel"])

    def window(tt, n):
        if probe is None:
            return np.zeros((n, 2), np.float32)
        return probe.window(c, spec, tt, n, compounds, tracks)

    def memo(name, tt, extra, make):
        if probe is None:
            return make()
        return probe.cached((name, sig, tt, extra), make)

    {"bars": _bars, "wave": _wave, "scope": _scope, "vector": _vector}[spec["kind"]](
        p, spec, w, h, u, t_us, window, memo)
    p.end()
    return img


def _extent(spec, w, h, u):
    """(height, inner radius, radial length): the whole picture's height; the circle's inner radius and
    the length from there to its outer edge (half the shorter side)."""
    outer = min(w, h) / 2
    r0 = min(spec["inner"] * u, outer * 0.85)
    return float(h), r0, max(1.0, outer - r0)


def _count_bars(spec, w, u):
    bw, gap = max(1.0, spec["bar_w"] * u), max(0.0, spec["gap"] * u)
    if spec["radial"]:
        return max(8, min(360, int((2 * math.pi * spec["inner"] * u + gap) / (bw + gap)))), bw, gap
    return max(1, min(512, int((w * 1.0 + gap) / (bw + gap)))), bw, gap


def _bars(p, spec, w, h, u, t_us, window, memo):
    n, bw, gap = _count_bars(spec, w, u)
    ch, lo, hi, lg = spec["channel"], spec["f_lo"], min(spec["f_hi"], RATE / 2 - 1), spec["log"]

    def raw_at(tt):
        return memo("bars", tt, (n, lo, hi, lg, ch),
                    lambda: band_levels(spectrum(mono(window(tt, NFFT), ch)), n, lo, hi, lg))
    v = smooth_across(follow(raw_at, t_us, spec["attack"], spec["decay"]), spec["smooth"])
    maxh, r0, span = _extent(spec, w, h, u)
    rad = spec["radius"] * u                                   # (0: square ends)
    cx, cy = w / 2, h / 2
    p.setPen(Qt.NoPen)
    if spec["radial"]:
        p.setBrush(_fill(spec, cy - r0, cy - r0 - span))
        for i in range(n):
            ln = float(v[i]) * span
            if ln < 0.5:
                continue
            p.save()
            p.translate(cx, cy)
            p.rotate(360.0 * i / n)
            top, bottom = -r0 - ln, (-r0 + min(ln, r0)) if spec["mirror"] else -r0
            r = min(rad, bw / 2, (bottom - top) / 2)
            p.drawRoundedRect(QRectF(-bw / 2, top, bw, bottom - top), r, r)
            p.restore()
        return
    x0 = (w - (n * bw + (n - 1) * gap)) / 2
    base = cy if spec["mirror"] else float(h)
    p.setBrush(_fill(spec, base, base - (maxh / 2 if spec["mirror"] else maxh)))
    for i in range(n):
        ln = float(v[i]) * maxh * (0.5 if spec["mirror"] else 1.0)
        if ln < 0.5:
            continue
        x = x0 + i * (bw + gap)
        top, bottom = base - ln, base + (ln if spec["mirror"] else 0.0)
        r = min(rad, bw / 2, (bottom - top) / 2)
        p.drawRoundedRect(QRectF(x, top, bw, bottom - top), r, r)


def _curve(points, closed=False):
    """A QPainterPath through points (Catmull-Rom splines: smooth, and through every point)."""
    path = QPainterPath()
    n = len(points)
    if n == 0:
        return path
    path.moveTo(points[0])
    for i in range(n - 1 if not closed else n):
        p0, p1 = points[(i - 1) % n] if closed or i > 0 else points[0], points[i]
        p2 = points[(i + 1) % n]
        p3 = points[(i + 2) % n] if closed or i + 2 < n else points[-1]
        path.cubicTo(p1 + (p2 - p0) / 6.0, p2 - (p3 - p1) / 6.0, p2)
    return path


def _wave(p, spec, w, h, u, t_us, window, memo):
    bw, gap = max(1.0, spec["bar_w"] * u), max(0.0, spec["gap"] * u)
    count = max(24, min(240, int(w / max(4.0 * u, (bw + gap) / 2))))
    if spec["radial"]:
        count = max(24, min(240, count // 2))
    ch = spec["channel"]
    nwin = int(WAVE_US / US * RATE)

    def raw_at(tt):
        def make():
            x = np.abs(mono(window(tt, nwin), ch))
            cut = len(x) // count * count
            return x[:cut].reshape(count, -1).max(axis=1) if cut else np.zeros(count)
        return memo("wave", tt, (count, ch), make)
    v = np.clip(smooth_across(follow(raw_at, t_us, spec["attack"], spec["decay"]), spec["smooth"]), 0.0, 1.0)
    maxh, r0, span = _extent(spec, w, h, u)
    cx, cy = w / 2, h / 2
    p.setPen(Qt.NoPen)
    if spec["radial"]:
        ang = 2 * math.pi * np.arange(count) / count - math.pi / 2
        out_r = r0 + v * span
        in_r = np.maximum(r0 - v * span, 0.0) if spec["mirror"] else np.full(count, r0)
        outer = _curve([QPointF(cx + r * math.cos(a), cy + r * math.sin(a)) for r, a in zip(out_r, ang)], closed=True)
        inner = _curve([QPointF(cx + r * math.cos(a), cy + r * math.sin(a)) for r, a in zip(in_r, ang)], closed=True)
        path = QPainterPath()
        path.setFillRule(Qt.OddEvenFill)
        path.addPath(outer)
        path.addPath(inner)
        p.setBrush(_fill(spec, cy - r0, cy - r0 - span))
        p.drawPath(path)
        return
    xs = np.linspace(0, w, count)
    top = [QPointF(x, cy - float(a) * maxh / 2) for x, a in zip(xs, v)]
    bottom = [QPointF(x, cy + float(a) * maxh / 2) for x, a in zip(xs, v)]
    path = _curve(top)
    path.connectPath(_curve(bottom[::-1]))
    path.closeSubpath()
    p.setBrush(_fill(spec, cy, cy - maxh / 2))
    p.drawPath(path)


def _scope(p, spec, w, h, u, t_us, window, memo):
    ch = spec["channel"]
    x = mono(window(t_us, SCOPE_N), ch)
    half = len(x) // 2
    rising = np.nonzero((x[:half] < 0) & (x[1:half + 1] >= 0))[0]            # (starts where the wave crosses upward)
    seg = x[rising[0] if len(rising) else 0:][:half]
    if len(seg) < 8:
        seg = np.zeros(half)
    pts = max(16, min(len(seg), int(w / max(1.0, 2.0 * u)), 800))
    seg = np.interp(np.linspace(0, len(seg) - 1, pts), np.arange(len(seg)), seg)
    seg = smooth_across(seg, spec["smooth"] * 0.5)
    maxh, r0, span = _extent(spec, w, h, u)
    cx, cy = w / 2, h / 2
    pen = QPen(_qc(spec["color"]), max(1.0, spec["line_w"] * u), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    if spec["gradient"]:
        g = QLinearGradient(0, cy - maxh / 2, 0, cy + maxh / 2)
        g.setColorAt(0, _qc(spec["color2"]))
        g.setColorAt(1, _qc(spec["color"]))
        pen.setBrush(QBrush(g))
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    if spec["radial"]:
        ang = 2 * math.pi * np.arange(pts) / pts - math.pi / 2
        poly = QPolygonF([QPointF(cx + (r0 + float(a) * span) * math.cos(t), cy + (r0 + float(a) * span) * math.sin(t))
                          for a, t in zip(seg, ang)])
        poly.append(poly[0])
        p.drawPolyline(poly)
        return
    xs = np.linspace(0, w, pts)
    p.drawPolyline(QPolygonF([QPointF(x_, cy - float(a) * maxh / 2) for x_, a in zip(xs, seg)]))


def _vector(p, spec, w, h, u, t_us, window, memo):
    radius = min(w, h) / 2
    cx, cy = w / 2, h / 2
    if spec["grid"]:
        g = _qc(spec["color"], 0.25)
        p.setPen(QPen(g, max(1.0, u)))
        p.setBrush(Qt.NoBrush)
        for f in (1.0, 0.5):
            p.drawEllipse(QPointF(cx, cy), radius * f, radius * f)
        r2 = radius / math.sqrt(2)
        p.drawLine(QPointF(cx, cy - radius), QPointF(cx, cy + radius))
        p.drawLine(QPointF(cx - radius, cy), QPointF(cx + radius, cy))
        p.drawLine(QPointF(cx - r2, cy + r2), QPointF(cx + r2, cy - r2))
        p.drawLine(QPointF(cx - r2, cy - r2), QPointF(cx + r2, cy + r2))
    trail = max(0, min(20, int(spec["decay"] * LAUNCH * US / STEP_US)))
    k0 = int(math.floor(t_us / STEP_US))
    n = int(RATE * STEP_US / US)
    width = max(1.0, spec["line_w"] * u)
    for back in range(trail, -1, -1):
        tt = (k0 - back) * STEP_US

        def make(tt=tt):
            pcm = window(tt, n)
            l, r = pcm[:, 0], pcm[:, 1]
            step = max(1, len(l) // 160)
            return np.stack([(l - r)[::step] / math.sqrt(2), (l + r)[::step] / math.sqrt(2)], axis=1)
        xy = memo("vector", tt, (n,), make)
        alpha = math.exp(-back * STEP_US / US / max(spec["decay"], 1e-3)) if spec["decay"] > 0 else (1.0 if back == 0 else 0.0)
        if alpha < 0.02:
            continue
        p.setPen(QPen(_qc(spec["color"], alpha), width, Qt.SolidLine, Qt.RoundCap))
        p.drawPoints(QPolygonF([QPointF(cx + float(a) * radius, cy - float(b) * radius) for a, b in xy]))
