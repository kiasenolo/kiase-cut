"""LFO (低頻振盪器): a number that swings along a wave over time. Three places hold one:

    a global parameter of the rack (rack.py):  p["lfo"] = spec     the parameter is the LFO's output (time: the timeline)
    a clip's own number (propexpr.py):         clip["expr"][prop] = spec   (time: seconds into the clip)

spec {wave, unit, rate, amp, offset, phase, fade, fade_out, loop, width, bezier, curve, bipolar, rel, seed}
  wave     sine / triangle / saw / square / bezier (a CSS cubic-bezier over one cycle) / curve (a curve of any
           number of keys over one cycle, curves.unit_value) / random (a new value each cycle) / noise (smooth)
  unit     "hz": `rate` is cycles per second;  "sec": `rate` is the seconds one cycle lasts
  amp      how far the wave swings either way (bipolar) - its height (not bipolar)
  offset   the centre it swings about (the value of the wave's 0)
  phase    degrees into the cycle at time 0
  fade     seconds the swing takes to grow from nothing to `amp` (0: at once)
  fade_out seconds the swing takes to shrink to nothing, counted back from the end of the clip (a clip's number only; 0: no fade)
  ramp     seconds the speed takes to grow from `ramp_from` (a share of `rate`, slow) to `rate` (0: at full speed at once)
  ramp_out seconds the speed takes to slow back down to `ramp_from` × `rate`, counted back from the end of the clip (0: no slowing)
  hold     seconds the swing stands still at the very end of the clip (it stops that long before the end; the speed's slowing is over by then)
  loop     repeat: each cycle runs the wave from its start; mirror: forward, then back (saw, square, bezier, curve)
  width    the share of a square wave's cycle that is high
  bipolar  the wave runs -1 - 1 (else 0 - 1); the curves are drawn 0 - 1 either way
  rel      for a clip's number: offset is added to the number as it is (keyframes included) instead of replacing it

value(spec, t) = (number as it is, when rel) + offset + amp * wave * fade-in * fade-out.
The cycles gone by at t are the speed's integral: a ramping speed grows linearly, so x = f0 t + (f1 - f0) t² / 2T up to T.
"""
import copy
import math

from . import curves, expr

WAVES = (("sine", "正弦"), ("triangle", "三角"), ("saw", "鋸齒"), ("square", "方波"), ("bezier", "cubic-bezier 曲線"),
         ("curve", "自訂曲線（多個點）"), ("random", "隨機（每週期換一個）"), ("noise", "平滑雜訊"))
LOOPS = (("repeat", "重複"), ("mirror", "鏡像"))
UNITS = (("hz", "頻率（每秒幾次）"), ("sec", "週期（一次幾秒）"))
MIRRORABLE = ("saw", "square", "bezier", "curve")
DEFAULT_BEZIER = (0.42, 0.0, 0.58, 1.0)
DEFAULT_CURVE = [[0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [1.0, 1.0, 0.0, 0.0, 0.0, 0.0]]


def make(wave="sine", unit="hz", rate=1.0, amp=1.0, offset=0.0, phase=0.0, fade=0.0, fade_out=0.0, ramp=0.0, ramp_out=0.0, hold=0.0, ramp_from=0.2, loop="repeat", width=0.5,
         bezier=DEFAULT_BEZIER, curve=None, bipolar=True, rel=False, seed=0):
    return {"wave": wave, "unit": unit, "rate": float(rate), "amp": float(amp), "offset": float(offset),
            "phase": float(phase), "fade": float(fade), "fade_out": float(fade_out), "ramp": float(ramp), "ramp_out": float(ramp_out), "hold": float(hold), "ramp_from": float(ramp_from), "loop": loop, "width": float(width),
            "bezier": [float(x) for x in bezier], "curve": copy.deepcopy(curve or DEFAULT_CURVE),
            "bipolar": bool(bipolar), "rel": bool(rel), "seed": int(seed)}


def is_lfo(x):
    return isinstance(x, dict) and "wave" in x


def check(s):
    """None when the spec is usable, else why not."""
    if s.get("wave") not in dict(WAVES):
        return "不認得的波形"
    if s.get("unit") not in dict(UNITS) or s.get("loop") not in dict(LOOPS):
        return "不認得的單位或循環方式"
    nums = [s.get(k) for k in ("rate", "amp", "offset", "phase", "fade", "width")] + [s.get("fade_out", 0.0), s.get("ramp", 0.0), s.get("ramp_out", 0.0), s.get("hold", 0.0), s.get("ramp_from", 0.2)] + list(s.get("bezier") or [])
    if len(s.get("bezier") or []) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in nums):
        return "數字要是有限的"
    if s["unit"] == "sec" and s["rate"] <= 0:
        return "週期要大於 0 秒"
    if s["rate"] < 0 or s["fade"] < 0 or s.get("fade_out", 0.0) < 0 or s.get("ramp", 0.0) < 0 or s.get("ramp_out", 0.0) < 0 or s.get("hold", 0.0) < 0:
        return "頻率和漸入不能是負的"
    if not 0.0 <= s.get("ramp_from", 0.2) <= 1.0:
        return "起始速度要在 0 到 100% 之間"
    if s["wave"] == "bezier" and not (0.0 <= s["bezier"][0] <= 1.0 and 0.0 <= s["bezier"][2] <= 1.0):
        return "cubic-bezier 的 x1、x2 要在 0 到 1 之間"
    keys = s.get("curve")
    if keys is not None and not (isinstance(keys, list) and keys and all(
            isinstance(k, (list, tuple)) and len(k) == 6 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in k)
            for k in keys)):
        return "曲線的點要是有限的數字"
    return None


def hz(s):
    """Cycles per second."""
    return s["rate"] if s["unit"] == "hz" else (1.0 / s["rate"] if s["rate"] else 0.0)


def _speed(s, t, dur):
    """The speed at t as a share of rate: up from ramp_from over `ramp`, down to it over the last `ramp_out` seconds."""
    lo, T, To = s.get("ramp_from", 0.2), s.get("ramp", 0.0), s.get("ramp_out", 0.0)
    k = 1.0 if T <= 0 or t >= T else lo + (1 - lo) * t / T
    if dur is not None and To > 0 and t > dur - To:
        k *= 1.0 - (1 - lo) * min(1.0, (t - (dur - To)) / To)
    return k


def cycles(s, t, dur=None):
    """Cycles gone by t seconds in (the speed grows from ramp_from × rate to rate over `ramp` seconds, then stays; with `ramp_out`
    it slows again over the clip's last seconds - the two multiply, each piece between their corners is a quadratic: Simpson is exact)."""
    f1, T = hz(s), s.get("ramp", 0.0)
    if dur is not None and s.get("hold", 0.0) > 0:
        dur = max(0.0, dur - s["hold"])                  # (the motion is over `hold` seconds before the clip is)
        t = min(t, dur)
    if dur is not None and s.get("ramp_out", 0.0) > 0:
        cuts = sorted({0.0, t, *(c for c in (T, dur - s["ramp_out"], dur) if 0.0 < c < t)})
        return f1 * sum((b - a) / 6 * (_speed(s, a, dur) + 4 * _speed(s, (a + b) / 2, dur) + _speed(s, b, dur))
                        for a, b in zip(cuts, cuts[1:]))
    if T <= 0:
        return f1 * t
    f0 = f1 * s.get("ramp_from", 0.2)
    if t < T:
        return f0 * t + (f1 - f0) * t * t / (2 * T)
    return f0 * T + (f1 - f0) * T / 2 + f1 * (t - T)


def unit_wave(s, x):
    """The wave 0 - 1 at x cycles in (x: any number - its whole part is the cycle, for the ones that change by cycle)."""
    cycle = math.floor(x)
    p = x - cycle
    w = s["wave"]
    if s["loop"] == "mirror" and w in MIRRORABLE:
        p = 2 * p if p < 0.5 else 2 * (1 - p)
    if w == "sine":
        return 0.5 + 0.5 * math.sin(2 * math.pi * p)
    if w == "triangle":
        return abs(((p + 0.75) % 1.0) * 2 - 1)
    if w == "saw":
        return p
    if w == "square":
        return 1.0 if p < s["width"] else 0.0
    if w == "bezier":
        return expr._bezier_y(*s["bezier"], p)
    if w == "curve":
        return curves.unit_value(s.get("curve") or DEFAULT_CURVE, p)
    if w == "random":
        return expr._hash(cycle * 7919 + s.get("seed", 0) * 104729)
    return 0.5 + 0.5 * expr.noise(x, s.get("seed", 0))                # noise: one step of x a cycle


def wave(s, x):
    """The wave as the spec has it (bipolar: -1 - 1) at x cycles in."""
    u = unit_wave(s, x)
    return 2 * u - 1 if s["bipolar"] else u


def value(s, t, cur=0.0, dur=None):
    """The LFO's number t seconds in (cur: the number as it is, which a `rel` one adds itself to; dur: seconds the clip lasts, for the fade-out)."""
    x = cycles(s, t, dur) + s["phase"] / 360.0
    grow = 1.0 if s["fade"] <= 0 else min(1.0, max(0.0, t / s["fade"]))
    out = s.get("fade_out", 0.0)
    if dur is not None and out > 0:
        grow *= min(1.0, max(0.0, (dur - t) / out))
    return (cur if s.get("rel") else 0.0) + s["offset"] + s["amp"] * wave(s, x) * grow


def safe(s, t, cur=0.0, dur=None):
    """value(), or cur when the spec cannot be worked out."""
    try:
        return value(s, t, cur, dur) if check(s) is None else cur
    except (ArithmeticError, ValueError, TypeError, KeyError):
        return cur


def points(s, seconds, n=160, start=0.0):
    """[(t, number)] over `seconds` from `start` (what the dialog's preview draws)."""
    return [(start + seconds * i / n, safe(s, start + seconds * i / n)) for i in range(n + 1)]


def label(s):
    """A short description (for menus and tooltips)."""
    rate = f"{s['rate']:g} Hz" if s["unit"] == "hz" else f"{s['rate']:g} 秒一次"
    return f"LFO　{dict(WAVES).get(s['wave'], s['wave'])}　{rate}　{s['offset']:g} ± {s['amp']:g}"
