"""Animatable parameters.

A parameter is either a plain number or {"keys": [[t, v, ldt, ldv, rdt, rdv], ...]}:
t is microseconds from the clip's start on the timeline, v the value, and (ldt, ldv) /
(rdt, rdv) the left/right bezier handle offsets, exactly as Jianying stores them.
Zero handles give a straight line; before the first and after the last key the value holds.
"""

US = 1_000_000


def is_animated(p):
    return isinstance(p, dict) and bool(p.get("keys"))


def value(p, t):
    """Value of parameter p at t (us from clip start)."""
    if not is_animated(p):
        return p if not isinstance(p, dict) else p.get("value", 0.0)
    keys = p["keys"]
    if t <= keys[0][0]:
        return keys[0][1]
    if t >= keys[-1][0]:
        return keys[-1][1]
    for a, b in zip(keys, keys[1:]):
        if a[0] <= t <= b[0]:
            break
    x0, x3 = a[0], b[0]
    x1, x2 = x0 + a[4], x3 + b[2]
    lo, hi = 0.0, 1.0
    for _ in range(48):
        s = (lo + hi) / 2
        x = (1 - s) ** 3 * x0 + 3 * (1 - s) ** 2 * s * x1 + 3 * (1 - s) * s * s * x2 + s ** 3 * x3
        lo, hi = (s, hi) if x < t else (lo, s)
    s = (lo + hi) / 2

    def bez(y0, y1, y2, y3):
        return (1 - s) ** 3 * y0 + 3 * (1 - s) ** 2 * s * y1 + 3 * (1 - s) * s * s * y2 + s ** 3 * y3

    if isinstance(a[1], list):          # colours: each channel follows the same timing,
        return [bez(p, p, q, q) for p, q in zip(a[1], b[1])]   # with flat handles
    return bez(a[1], a[1] + a[5], b[1] + b[3], b[1])


def span(p):
    """(first, last) key time, or None for a constant."""
    if not is_animated(p):
        return None
    return p["keys"][0][0], p["keys"][-1][0]


def max_abs(p):
    if not is_animated(p):
        return abs(value(p, 0))
    return max(abs(k[1]) for k in p["keys"])


def static(spec, t, fields):
    """Copy of dict spec with the listed animated fields evaluated at t."""
    out = dict(spec)
    for k in fields:
        if k in out:
            out[k] = value(out[k], t)
    return out


def from_jianying(kf_list, shift_us):
    """Jianying keyframe_list -> parameter; shift_us moves its time base to the clip start."""
    keys = []
    for k in kf_list:
        lc, rc = k.get("left_control", {}), k.get("right_control", {})
        keys.append([k.get("time_offset", 0) + shift_us, k["values"][0],
                     lc.get("x", 0.0), lc.get("y", 0.0), rc.get("x", 0.0), rc.get("y", 0.0)])
    keys.sort(key=lambda k: k[0])
    return {"keys": keys}


# -- CSS cubic-bezier <-> Jianying handles ---------------------------------------------------------
def segment_bezier(a, b):
    """The segment from key a to key b as CSS cubic-bezier(x1, y1, x2, y2).
    y is relative to the value change; a flat segment (no change, or colours) gives y1=0,
    y2=1 since its handles cannot be expressed that way."""
    dt = b[0] - a[0] or 1
    x1, x2 = a[4] / dt, 1 + b[2] / dt
    dv = None if isinstance(a[1], list) else b[1] - a[1]
    if not dv:
        return x1, 0.0, x2, 1.0
    return x1, a[5] / dv, x2, 1 + b[3] / dv


def apply_bezier(a, b, x1, y1, x2, y2):
    """Shape the segment a -> b (key lists, changed in place) like CSS cubic-bezier.
    x is clamped to 0..1 so time keeps moving forward; y may overshoot."""
    x1, x2 = min(1.0, max(0.0, x1)), min(1.0, max(0.0, x2))
    dt = b[0] - a[0]
    dv = 0.0 if isinstance(a[1], list) else b[1] - a[1]
    a[4], a[5] = x1 * dt, y1 * dv
    b[2], b[3] = (x2 - 1) * dt, (y2 - 1) * dv


def parse_bezier(text):
    """'cubic-bezier(0.42, 0, 0.58, 1)' or '0.42 0 0.58 1' -> four floats."""
    t = text.strip().lower()
    if t.startswith("cubic-bezier"):
        t = t[len("cubic-bezier"):]
    nums = [x for x in t.replace("(", " ").replace(")", " ").replace(",", " ").split() if x]
    if len(nums) != 4:
        raise ValueError("需要四個數字：x1, y1, x2, y2")
    return tuple(float(n) for n in nums)
