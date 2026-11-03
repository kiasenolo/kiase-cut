"""映射 (mapping): how a bound number follows the parameter it is bound to - a global parameter of the
rack (rack.py) or a component's parameter (components.py). Asked for when binding, with a preview of
its curve.

mapping {mode, src, in: [lo, hi], out: [lo, hi], bezier: [x1, y1, x2, y2], curve: [keys], js}
  src     the rack parameter it reads ("" for a component's: its own value)
  mode    direct   the number is the parameter's value as it is (what binding did before)
          linear   the parameter's range `in` becomes the number's range `out`
          bezier   the same, along a CSS cubic-bezier curve (ease in, ease out, ...)
          curve    the same, along a curve of any number of keys (the keyframe editor's: handles, eased segments);
                   it is what curve(x) reads in an expression too
          js       an expression (expr.py) of: input (the value), t (0 - 1 along `in`), lo and hi (`out`),
                   and the rack's parameters by name; its default is lerp(lo, hi, t)
Outside `in` the number stays at the end of `out`. A mapping that cannot be worked out leaves the
number as the parameter's value.
"""
import copy
import math

from . import curves, expr

MODES = (("direct", "直接（原值）"), ("linear", "線性（最小值 - 最大值）"), ("bezier", "cubic-bezier 曲線"),
         ("curve", "自訂曲線（多個點）"), ("js", "JavaScript 表達式"))
BEZIER_PRESETS = (("緩入緩出", (0.42, 0.0, 0.58, 1.0)), ("緩入", (0.42, 0.0, 1.0, 1.0)),
                  ("緩出", (0.0, 0.0, 0.58, 1.0)), ("線性", (0.0, 0.0, 1.0, 1.0)),
                  ("先衝後緩", (0.2, 0.9, 0.3, 1.0)), ("回彈", (0.34, 1.56, 0.64, 1.0)))
DEFAULT_JS = "lerp(lo, hi, t)"
DEFAULT_CURVE = [[0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [1.0, 1.0, 0.0, 0.0, 0.0, 0.0]]


def make(mode="direct", src="", in_=(0.0, 1.0), out=(0.0, 1.0), bezier=(0.42, 0.0, 0.58, 1.0), js=DEFAULT_JS, curve=None):
    return {"mode": mode, "src": src, "in": [float(in_[0]), float(in_[1])], "out": [float(out[0]), float(out[1])],
            "bezier": [float(x) for x in bezier], "curve": copy.deepcopy(curve or DEFAULT_CURVE), "js": js}


def is_mapping(x):
    return isinstance(x, dict) and "mode" in x


def check(m):
    """None when the mapping is usable, else why not."""
    if m.get("mode") not in dict(MODES):
        return "不認得的映射方式"
    nums = list(m.get("in", [])) + list(m.get("out", [])) + list(m.get("bezier", []))
    if len(m.get("in", [])) != 2 or len(m.get("out", [])) != 2 or len(m.get("bezier", [])) != 4 \
            or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in nums):
        return "範圍和曲線要是有限的數字"
    if m["mode"] == "bezier" and not (0.0 <= m["bezier"][0] <= 1.0 and 0.0 <= m["bezier"][2] <= 1.0):
        return "cubic-bezier 的 x1、x2 要在 0 到 1 之間"
    keys = m.get("curve")
    if keys is not None and not (isinstance(keys, list) and keys and all(
            isinstance(k, (list, tuple)) and len(k) == 6 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in k) for k in keys)):
        return "曲線的點要是有限的數字"
    if m["mode"] == "js":
        return expr.check(m.get("js", ""))
    return None


def _t(m, x):
    lo, hi = m["in"]
    return 0.0 if hi == lo else min(1.0, max(0.0, (x - lo) / (hi - lo)))


def apply(m, x, env=None):
    """The number a parameter valued x gives under mapping m (env: the other names an expression may read)."""
    if m["mode"] == "direct":
        return x
    t = _t(m, x)
    o0, o1 = m["out"]
    if m["mode"] == "linear":
        return o0 + (o1 - o0) * t
    if m["mode"] == "bezier":
        return o0 + (o1 - o0) * expr._bezier_y(*m["bezier"], t)
    if m["mode"] == "curve":
        return o0 + (o1 - o0) * curves.unit_value(m.get("curve") or DEFAULT_CURVE, t)
    return expr.safe(m.get("js") or DEFAULT_JS, dict(env or {}, input=x, t=t, lo=o0, hi=o1, __curve__=m.get("curve")),
                     default=o0 + (o1 - o0) * t)


def curve_points(m, n=64):
    """[(x, y)] of the mapping over its input range (what the preview draws; the whole 0 - 1 for a direct one)."""
    lo, hi = (m["in"] if m["mode"] != "direct" else (0.0, 1.0))
    return [(lo + (hi - lo) * i / n, apply(m, lo + (hi - lo) * i / n)) for i in range(n + 1)]


def names(m):
    """The rack parameters a mapping reads."""
    out = {m["src"]} if m.get("src") else set()
    if m.get("mode") == "js":
        try:
            out |= expr.names(m.get("js", "")) - {"input", "t", "lo", "hi"}
        except expr.ExprError:
            pass
    return out


def renamed(m, old, new):
    """A copy of mapping m with the rack parameter `old` called `new`."""
    from . import rack
    m = copy.deepcopy(m)
    if m.get("src") == old:
        m["src"] = new
    if m.get("mode") == "js":
        m["js"] = rack.rename_in(m.get("js", ""), old, new)
    return m


def label(m):
    """A short description of a mapping (for menus and tooltips)."""
    if m["mode"] == "direct":
        return "直接"
    span = f"{m['in'][0]:g}–{m['in'][1]:g} → {m['out'][0]:g}–{m['out'][1]:g}"
    if m["mode"] == "js":
        return f"JavaScript　{span}"
    return {"linear": "線性　", "curve": "自訂曲線　"}.get(m["mode"], "cubic-bezier　") + span
