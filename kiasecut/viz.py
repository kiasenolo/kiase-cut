"""Audio Visualizer (音訊視覺化): a picture clip (type image, clip["viz"]) that draws the sound it
is given, drawn afresh for every frame by both renderers.

viz {kind, source, w, h, channel, attack, decay, color, color2, gradient, bar_w, gap, radius, mirror,
     radial, inner, f_lo, f_hi, log, smooth, line_w, grid, auto_scale}   (gradient: bars and waves only)
  w, h     the object's size, in canvas pixels, as a shape's: the picture is exactly that rectangle (bars
           grow from its bottom edge up to its top, a wave or a scope fills its height, a vectorscope its
           shorter side, a circle's outer edge is half the shorter side)
  kind     bars (Spectrum Bars) | wave (Smooth Filled Waveform) | scope (Wave: the sound's line) |
           oscilloscope (Oscilloscope: a graticule, glowing trace, optional XY) |
           vector (Vectorscope: side against mid, as iZotope Ozone Imager draws it)
  source   {type: file, path} - an audio / video file, played from the clip's source_start_us as a
           clip of its own would | {type: compound, id} - what a compound clip plays (from its
           start + source_start_us) | {type: track, id} - one track of the level the clip is on,
           at the level's time
  channel  M (middle) | L | R | S (side) - what bars, wave and scope look at (vector sees both)
  attack / decay  seconds the picture takes to rise / fall (one-pole, as an envelope follower)
  bar_w / gap / radius / line_w / inner   pixels of the object's own size (they scale with it)
  f_lo..f_hi, log  the frequencies the bars cover; log 0 - 1 mixes how they sit: 1 evenly in octaves (many
           bars for the bass), 0 evenly in Hz (a plain FFT, most bars for the treble)
  floor_db / top_db  the levels (dB, a sine of 1 is 0 dB) that give a bar no height / its full height
  level_map  a mapping (mapping.py) of that 0 - 1 to the height shown (direct: as it is)
  smooth   0 - 1, how much neighbouring bars / points are blended
  xy       (oscilloscope) left against right instead of the sound against time (a Lissajous figure)
  auto_freq (wave, oscilloscope) the picture shows `cycles` periods of the pitch it finds in the sound (the
           wave stands still while the note holds); without a clear pitch, or with it off, a window of
           time_ms milliseconds
  auto_scale (vectorscope) the picture is scaled so the widest swing of the last AUTO_BACK seconds just
           reaches the outer circle (a quiet sound fills it too; silence stays at the centre)
  mirror   bars and waves grow both ways;  radial  around a circle of radius `inner`
  gradient color at the foot to color2 at the top

Everything is worked out from the sound around the frame (Probe), nothing is kept between frames
but caches: the same moment always looks the same, wherever the playhead jumped from.
"""
import math
import os

import numpy as np
from . import mapping
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF

from . import audiomix, normalize, project, stretch

US = 1_000_000
RATE = audiomix.RATE
KINDS = {"bars": "Spectrum Bars", "wave": "Smooth Filled Waveform", "scope": "Wave", "vector": "Vectorscope",
         "oscilloscope": "Oscilloscope"}
CHANNELS = (("M", "中 (M)"), ("L", "左 (L)"), ("R", "右 (R)"), ("S", "側 (S)"))
SOURCE_TYPES = ("file", "compound", "track")
STEP_US = US // 60                      # the moments a picture is worked out for (and cached by)
NFFT = 4096
FLOOR_DB, TOP_DB = -72.0, -6.0
TILT_DB = 3.0                           # dB per octave added, so the highs are not always low
LAUNCH = 3.0                            # a picture looks back this many time constants
MAX_BACK = 60                           # ... but at most this many steps
WAVE_US = 60_000                        # the sound a waveform looks at
SCOPE_N = 16384                         # the sound an oscilloscope looks at (room for 300 ms and a trigger search)
AUTO_BACK = 0.5                         # seconds a vectorscope's 自動縮放 looks back for the widest swing
AUTO_MAX = 40.0                         # ... and the most it magnifies (a whisper is not blown up into noise)
MIN_HZ, MAX_HZ = 40.0, 2000.0            # the pitches 自動頻率 looks for

DEFAULTS = {
    "kind": "bars", "w": 1920.0, "h": 420.0, "channel": "M", "attack": 0.02, "decay": 0.3,
    "color": [1.0, 1.0, 1.0, 1.0], "color2": [1.0, 0.35, 0.8, 1.0], "gradient": False,
    "bar_w": 12.0, "gap": 6.0, "radius": 0.0, "mirror": False, "radial": False, "inner": 120.0,
    "f_lo": 30.0, "f_hi": 16000.0, "log": 1.0, "smooth": 0.4, "line_w": 4.0, "grid": True,
    "floor_db": FLOOR_DB, "top_db": TOP_DB, "level_map": mapping.make("direct"),
    "auto_scale": True, "xy": False, "auto_freq": True, "cycles": 2.0, "time_ms": 20.0,
}
LIMITS = {"radius": (0.0, 400.0), "attack": (0.0, 2.0), "decay": (0.0, 3.0), "bar_w": (1.0, 400.0), "gap": (0.0, 400.0),
          "w": (1.0, 16384.0), "h": (1.0, 16384.0), "inner": (10.0, 3000.0), "f_lo": (20.0, 20000.0), "f_hi": (40.0, 24000.0),
          "floor_db": (-120.0, -12.0), "top_db": (-60.0, 6.0), "smooth": (0.0, 1.0), "log": (0.0, 1.0), "line_w": (0.5, 100.0), "cycles": (0.5, 16.0), "time_ms": (1.0, 300.0)}


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
    if kind == "oscilloscope":
        v["w"], v["h"] = round(840.0 * k, 1), round(630.0 * k, 1)
        v["decay"] = 0.08
        v["line_w"] = round(v["line_w"] * 0.7, 1)
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
        elif k == "level_map":
            out[k] = x if mapping.is_mapping(x) and mapping.check(x) is None else mapping.make("direct")
        elif k == "channel":
            out[k] = x if x in "MLRS" and len(str(x)) == 1 else "M"
    if out["top_db"] <= out["floor_db"] + 6.0:
        out["top_db"] = out["floor_db"] + 6.0
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


def averaged_spectrum(window, t_us, channel):
    """spectrum() of three windows a quarter of a window apart, averaged as power: the chance spikes of a
    single window (each bin of noisy sound is random) fade, the steady parts stay."""
    step = NFFT / 4 / RATE * US
    pw = sum(np.square(spectrum(mono(window(t_us + k * step, NFFT), channel))) for k in (-1, 0, 1))
    return np.sqrt(pw / 3.0)


def band_levels(mag, n, f_lo, f_hi, log, floor_db=FLOOR_DB, top_db=TOP_DB):
    """0 - 1 for each of n bars: the level (rms) of the frequencies inside it, in dB between floor_db (0) and top_db (1)."""
    hz = RATE / NFFT
    log = float(log)
    edges = log * np.geomspace(f_lo, f_hi, n + 1) + (1.0 - log) * np.linspace(f_lo, f_hi, n + 1)
    lo, hi = edges[:-1] / hz, edges[1:] / hz
    mid, half = (lo + hi) / 2, np.maximum(hi - lo, 1.0) / 2           # (a bar narrower than a bin looks at one bin's
    lo, hi = mid - half, mid + half                                   # width round it: the bins fade into each other)
    cum = np.concatenate([[0.0], np.cumsum(np.square(mag))])         # bin i covers [i - 0.5, i + 0.5]
    at = lambda x: np.interp(x + 0.5, np.arange(len(cum)), cum)
    out = np.sqrt(np.maximum(at(hi) - at(lo), 0.0) / np.maximum(hi - lo, 1e-9))
    centre = (edges[:-1] + edges[1:]) / 2 if log < 1.0 else np.sqrt(edges[:-1] * edges[1:])
    db = 20 * np.log10(np.maximum(out, 1e-7)) + TILT_DB * np.log2(np.maximum(centre, 1.0) / 1000.0)
    return np.clip((db - floor_db) / (top_db - floor_db), 0.0, 1.0)


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

    {"bars": _bars, "wave": _wave, "scope": _scope, "vector": _vector,
     "oscilloscope": _oscilloscope}[spec["kind"]](
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
    fl, tp = spec["floor_db"], spec["top_db"]

    def raw_at(tt):
        return memo("bars", tt, (n, lo, hi, lg, ch, fl, tp),
                    lambda: band_levels(averaged_spectrum(window, tt, ch), n, lo, hi, lg, fl, tp))
    lm = spec["level_map"]
    v = follow(raw_at, t_us, spec["attack"], spec["decay"])
    if lm["mode"] != "direct":
        v = np.array([mapping.apply(lm, float(x)) for x in v])
    v = np.clip(smooth_across(v, spec["smooth"]), 0.0, 1.0)
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
        x, xw = x0 + i * (bw + gap), bw
        if gap <= 0.0:                                         # (touching bars share one whole-pixel edge: no hairline seam)
            x = round(x)
            xw = round(x0 + (i + 1) * bw) - x
        top, bottom = base - ln, base + (ln if spec["mirror"] else 0.0)
        r = min(rad, bw / 2, (bottom - top) / 2)
        p.drawRoundedRect(QRectF(x, top, xw, bottom - top), r, r)


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


def period_of(x):
    """The period (samples) of the pitch in x, 40 - 2000 Hz, or None when there is none clear: the first
    peak of its autocorrelation that is nearly as high as the highest (so an octave below is not taken)."""
    s = np.asarray(x[:8192], np.float64)
    s = s - s.mean()
    e = float(np.dot(s, s))
    if e < 1e-9:
        return None
    n = 1 << (2 * len(s) - 1).bit_length()
    f = np.fft.rfft(s, n)
    acf = np.fft.irfft(f * np.conj(f), n)[:len(s)] / e
    lo, hi = int(RATE / MAX_HZ), min(int(RATE / MIN_HZ), len(acf) - 2)
    seg = acf[lo:hi]
    peaks = np.nonzero((seg[1:-1] >= seg[:-2]) & (seg[1:-1] > seg[2:]))[0] + 1
    if not len(peaks):
        return None
    top = float(seg[peaks].max())
    if top < 0.4:
        return None
    first = peaks[seg[peaks] >= 0.9 * top][0]
    return float(lo + first)


def scope_segment(x, spec):
    """The part of the sound (centred in x) an oscilloscope draws: from a rising zero crossing, `cycles`
    periods long (自動頻率) or time_ms milliseconds."""
    mid = len(x) // 2
    length = int(spec["time_ms"] / 1000.0 * RATE)
    if spec["auto_freq"]:
        t = period_of(x[mid - 4096:mid + 4096])
        if t is not None:
            length = int(round(t * spec["cycles"]))
    length = max(16, min(length, len(x) // 2 - 1200))
    search = x[mid - 1200:mid + 1200]
    rising = np.nonzero((search[:-1] < 0) & (search[1:] >= 0))[0]
    start = mid - 1200 + (int(rising[len(rising) // 2]) if len(rising) else 1200)       # (the one nearest the middle)
    return x[start:start + length]


def _scope(p, spec, w, h, u, t_us, window, memo):
    ch = spec["channel"]
    x = mono(window(t_us, SCOPE_N), ch)
    seg = scope_segment(x, spec)
    if len(seg) < 8:
        seg = np.zeros(16)
    pts = max(16, min(len(seg), int(w / max(1.0, 2.0 * u)), 800))
    seg = np.interp(np.linspace(0, len(seg) - 1, pts), np.arange(len(seg)), seg)
    seg = smooth_across(seg, spec["smooth"] * 0.5)
    maxh, r0, span = _extent(spec, w, h, u)
    cx, cy = w / 2, h / 2
    pen = QPen(_qc(spec["color"]), max(1.0, spec["line_w"] * u), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
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

    def points(back):
        tt = (k0 - back) * STEP_US

        def make(tt=tt):
            pcm = window(tt, n)
            l, r = pcm[:, 0], pcm[:, 1]
            step = max(1, len(l) // 160)
            return np.stack([(l - r)[::step] / math.sqrt(2), (l + r)[::step] / math.sqrt(2)], axis=1)
        return memo("vector", tt, (n,), make)
    gain = 1.0
    if spec.get("auto_scale"):
        peak = max(float(np.hypot(xy[:, 0], xy[:, 1]).max()) if len(xy) else 0.0
                   for xy in (points(b) for b in range(max(trail, int(AUTO_BACK * US / STEP_US)) + 1)))
        gain = min(AUTO_MAX, 1.0 / peak) if peak > 1e-4 else 1.0
    for back in range(trail, -1, -1):
        xy = points(back)
        alpha = math.exp(-back * STEP_US / US / max(spec["decay"], 1e-3)) if spec["decay"] > 0 else (1.0 if back == 0 else 0.0)
        if alpha < 0.02:
            continue
        p.setPen(QPen(_qc(spec["color"], alpha), width, Qt.SolidLine, Qt.RoundCap))
        p.drawPoints(QPolygonF([QPointF(cx + float(a) * gain * radius, cy - float(b) * gain * radius) for a, b in xy]))


def _oscilloscope(p, spec, w, h, u, t_us, window, memo):
    """An oscilloscope: a 10 x 8 graticule (no screen behind it), and the trace as a glowing line (the sound
    against time from a rising zero crossing, or with xy the left channel against the right)."""
    pad = min(w, h) * 0.06
    area = QRectF(pad, pad, w - 2 * pad, h - 2 * pad)
    cx, cy = area.center().x(), area.center().y()
    if spec["grid"]:
        dx, dy = area.width() / 10, area.height() / 8
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_qc(spec["color"], 0.16), max(1.0, u)))
        for i in range(11):
            p.drawLine(QPointF(area.left() + i * dx, area.top()), QPointF(area.left() + i * dx, area.bottom()))
        for j in range(9):
            p.drawLine(QPointF(area.left(), area.top() + j * dy), QPointF(area.right(), area.top() + j * dy))
        p.setPen(QPen(_qc(spec["color"], 0.38), max(1.0, u)))
        p.drawLine(QPointF(cx, area.top()), QPointF(cx, area.bottom()))
        p.drawLine(QPointF(area.left(), cy), QPointF(area.right(), cy))
        tick = 0.12 * min(dx, dy)                                # (the minor divisions along the two centre axes)
        for i in range(51):
            x = area.left() + i * dx / 5
            p.drawLine(QPointF(x, cy - tick), QPointF(x, cy + tick))
        for j in range(41):
            y = area.top() + j * dy / 5
            p.drawLine(QPointF(cx - tick, y), QPointF(cx + tick, y))
    p.setClipRect(area)
    if spec["xy"]:
        n = int(RATE * STEP_US / US)

        def points(back):
            tt = (int(math.floor(t_us / STEP_US)) - back) * STEP_US

            def make():
                pcm = window(tt, n)
                step = max(1, len(pcm) // 400)
                return pcm[::step, :2]
            return memo("oscxy", tt, (n,), make)
        trail = max(0, min(6, int(spec["decay"] * LAUNCH * US / STEP_US)))
        polys = []
        for back in range(trail, -1, -1):
            xy = points(back)
            a = math.exp(-back * STEP_US / US / max(spec["decay"], 1e-3)) if spec["decay"] > 0 else (1.0 if back == 0 else 0.0)
            if a >= 0.02 and len(xy) > 1:
                polys.append((a, QPolygonF([QPointF(cx + float(l) * area.width() / 2, cy - float(r) * area.height() / 2) for l, r in xy])))
    else:
        seg = scope_segment(mono(window(t_us, SCOPE_N), spec["channel"]), spec)
        if len(seg) < 8:
            seg = np.zeros(16)
        pts = max(16, min(len(seg), int(area.width() / max(1.0, 2.0 * u)), 800))
        seg = np.interp(np.linspace(0, len(seg) - 1, pts), np.arange(len(seg)), seg)
        seg = smooth_across(seg, spec["smooth"] * 0.5)
        xs = np.linspace(area.left(), area.right(), pts)
        polys = [(1.0, QPolygonF([QPointF(x, cy - float(a) * area.height() / 2) for x, a in zip(xs, seg)]))]
    width = max(1.0, spec["line_w"] * u)
    p.setBrush(Qt.NoBrush)
    for alpha, poly in polys:
        for k, (mul, al) in enumerate(((5.0, 0.07), (3.0, 0.14), (1.8, 0.3))):          # (the glow: wide faint strokes)
            p.setPen(QPen(_qc(spec["color"], al * alpha), width * mul, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPolyline(poly)
        p.setPen(QPen(_qc(spec["color"], alpha), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline(poly)
        core = QColor(255, 255, 255)
        core.setAlphaF(0.55 * alpha)
        p.setPen(QPen(core, max(1.0, width * 0.35), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline(poly)
    p.setClipping(False)
