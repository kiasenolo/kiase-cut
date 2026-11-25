"""The numbers of a 聲音節點效果 (soundnodes.py): the nodes that give one, and what each works out.

A number node's own numbers are in node["params"], like an effect node's (keyframed, bound to
global parameters, drawn in the curve editor the same way). 數學, 映射範圍 and 限制 are ports of the
picture side's nodes (filters/nodes/math.glsl, map_range.glsl, clamp.glsl), on one number
instead of a picture; 映射範圍 has one more way, 對數, for frequencies.

    value     數值: a number
    global    全局參數: what a global parameter reads - node["expr"]["value"] names it, so renaming
              the parameter, counting its users and the circles of 聲音轉數值 see it as a binding
    math      數學
    maprange  映射範圍
    clamp     限制
"""
import math

from . import curves, soundfx

TYPES = ("value", "global", "math", "maprange", "clamp")
TITLES = {"value": "數值", "global": "全局參數", "math": "數學", "maprange": "映射範圍", "clamp": "限制"}
KEYWORDS = {"value": "float number constant 浮點 數字 常數", "global": "rack parameter 全局 參數架",
            "math": "add subtract multiply divide math 加 減 乘 除 運算 計算 數學",
            "maprange": "map range remap rescale 重新映射 範圍 對應", "clamp": "limit min max 限制 夾住 範圍"}
HUGE = 1e9
# (filters/nodes/math.glsl's menu, in its order: a number is what is stored)
MATH_OPS = ("相加|相減|相乘|相除|乘加|次方|對數|平方根|平方根倒數|絕對值|指數|最小|最大|小於|大於|正負號|比較|平滑最小|平滑最大|"
            "四捨五入|向下取整|向上取整|截斷|小數部分|截斷取餘|向下取餘|迴繞|對齊|來回|正弦|餘弦|正切|反正弦|反餘弦|反正切|"
            "反正切2|雙曲正弦|雙曲餘弦|雙曲正切|轉弧度|轉角度").split("|")
ONE_INPUT = ("平方根", "平方根倒數", "絕對值", "指數", "正負號", "四捨五入", "向下取整", "向上取整", "截斷", "小數部分", "正弦",
             "餘弦", "正切", "反正弦", "反餘弦", "反正切", "雙曲正弦", "雙曲餘弦", "雙曲正切", "轉弧度", "轉角度")
THREE_INPUTS = ("乘加", "比較", "平滑最小", "平滑最大", "迴繞")
MAP_MODES = ("線性", "階梯", "平滑", "更平滑", "對數")
CLAMP_MODES = ("最小最大", "範圍")


def free(name, label, default, **kw):
    """A number with no range to speak of: dragged by steps, not along a bar."""
    return soundfx.P(name, label, -HUGE, HUGE, default, free=True, **kw)


def _op(v):
    return MATH_OPS[int(min(len(MATH_OPS) - 1, max(0, round(v.get("op", 0)))))]


SPECS = {
    "value": [free("value", "數值", 0.5)],
    "global": [free("value", "讀到的值", 0.0, nowire=True)],
    "math": [soundfx.C("op", "運算", MATH_OPS, 0), free("a", "A", 0.5),
             free("b", "B", 0.5, when=lambda v: _op(v) not in ONE_INPUT),
             free("c", "C", 0.5, when=lambda v: _op(v) in THREE_INPUTS),
             soundfx.switch("clamp", "限制在 0~1")],
    "maprange": [soundfx.C("mode", "插值", MAP_MODES, 0), free("x", "數值", 0.0),
                 free("from_min", "來源最小", 0.0), free("from_max", "來源最大", 1.0),
                 free("to_min", "目標最小", 0.0), free("to_max", "目標最大", 1.0),
                 free("steps", "階梯數", 4.0, when=lambda v: round(v.get("mode", 0)) == 1),
                 soundfx.switch("clamp", "限制範圍", 1)],
    "clamp": [soundfx.C("mode", "類型", CLAMP_MODES, 0), free("x", "數值", 0.0), free("lo", "最小", 0.0),
              free("hi", "最大", 1.0)],
}
THROUGH = {"math": "a", "maprange": "x", "clamp": "x"}      # (a muted one gives this number of its own as it is)


def new_params(kind):
    return {p["name"]: p["default"] for p in SPECS[kind]}


def spec(kind, name):
    return next((p for p in SPECS.get(kind, ()) if p["name"] == name), None)


def held(p, v):
    """v inside parameter p's limits; a choice is a whole number. What is not a number: its default."""
    if v != v or v in (math.inf, -math.inf):
        return float(p["default"])
    v = min(p["max"], max(p["min"], v))
    return float(math.floor(v + 0.5)) if p.get("choices") else float(v)


def own_values(node, t_us, names=None):
    """{name: number} a number node holds at t_us (keyframes, then what it follows)."""
    given = node.get("params") or {}
    out = {}
    for p in SPECS[node["type"]]:
        v = held(p, float(curves.value(given.get(p["name"], p["default"]), t_us)))
        out[p["name"]] = held(p, soundfx.followed(node, p["name"], v, t_us, names))
    return out


# -- the working out -----------------------------------------------------------------------------
def _sign(a):
    return (a > 0) - (a < 0)


def _power(a, b):
    if a >= 0:
        return a ** b if a or b >= 0 else 0.0
    return (1.0 if math.fmod(b, 2.0) == 0.0 else -1.0) * (-a) ** b if b == math.floor(b) else 0.0


def _smooth(a, b, c, pick, way):
    h = max(c - abs(a - b), 0.0) / max(c, 1e-30)
    return pick(a, b) + way * h * h * h * c / 6.0 if c != 0 else pick(a, b)


def _wrap(a, top, bottom):
    span = top - bottom
    return a - span * math.floor((a - bottom) / span) if span != 0 else bottom


def _clip(a, lo, hi):
    return min(max(a, lo), hi)


_MATH = {
    "相加": lambda a, b, c: a + b, "相減": lambda a, b, c: a - b, "相乘": lambda a, b, c: a * b,
    "相除": lambda a, b, c: a / b if b else 0.0, "乘加": lambda a, b, c: a * b + c,
    "次方": lambda a, b, c: _power(a, b),
    "對數": lambda a, b, c: math.log(a) / math.log(b) if a > 0 and b > 0 and b != 1 else 0.0,
    "平方根": lambda a, b, c: math.sqrt(a) if a > 0 else 0.0,
    "平方根倒數": lambda a, b, c: 1.0 / math.sqrt(a) if a > 0 else 0.0,
    "絕對值": lambda a, b, c: abs(a), "指數": lambda a, b, c: math.exp(a),
    "最小": lambda a, b, c: min(a, b), "最大": lambda a, b, c: max(a, b),
    "小於": lambda a, b, c: float(a < b), "大於": lambda a, b, c: float(a > b),
    "正負號": lambda a, b, c: float(_sign(a)), "比較": lambda a, b, c: float(abs(a - b) <= max(c, 1e-5)),
    "平滑最小": lambda a, b, c: _smooth(a, b, c, min, -1.0), "平滑最大": lambda a, b, c: _smooth(a, b, c, max, 1.0),
    "四捨五入": lambda a, b, c: float(math.floor(a + 0.5)), "向下取整": lambda a, b, c: float(math.floor(a)),
    "向上取整": lambda a, b, c: float(math.ceil(a)), "截斷": lambda a, b, c: float(math.trunc(a)),
    "小數部分": lambda a, b, c: a - math.floor(a),
    "截斷取餘": lambda a, b, c: a - b * math.trunc(a / b) if b else 0.0,
    "向下取餘": lambda a, b, c: a - math.floor(a / b) * b if b else 0.0,
    "迴繞": lambda a, b, c: _wrap(a, b, c),
    "對齊": lambda a, b, c: math.floor(a / b) * b if b else 0.0,
    "來回": lambda a, b, c: abs(((a - b) / (b * 2) % 1.0) * b * 2 - b) if b else 0.0,
    "正弦": lambda a, b, c: math.sin(a), "餘弦": lambda a, b, c: math.cos(a), "正切": lambda a, b, c: math.tan(a),
    "反正弦": lambda a, b, c: math.asin(_clip(a, -1, 1)), "反餘弦": lambda a, b, c: math.acos(_clip(a, -1, 1)),
    "反正切": lambda a, b, c: math.atan(a), "反正切2": lambda a, b, c: math.atan2(a, b),
    "雙曲正弦": lambda a, b, c: math.sinh(a), "雙曲餘弦": lambda a, b, c: math.cosh(a),
    "雙曲正切": lambda a, b, c: math.tanh(a),
    "轉弧度": lambda a, b, c: math.radians(a), "轉角度": lambda a, b, c: math.degrees(a),
}


def _map(v):
    mode = MAP_MODES[int(v["mode"])]
    span = v["from_max"] - v["from_min"]
    t = (v["x"] - v["from_min"]) / span if span else 0.0
    clamped = v["clamp"] > 0.5
    if clamped:
        t = _clip(t, 0.0, 1.0)
    if mode == "階梯":
        t = math.floor(t * (v["steps"] + 1.0)) / max(v["steps"], 1e-6)
    elif mode == "平滑":
        t = _clip(t, 0.0, 1.0)
        t = t * t * (3.0 - 2.0 * t)
    elif mode == "更平滑":
        t = _clip(t, 0.0, 1.0)
        t = t * t * t * (t * (t * 6.0 - 15.0) + 10.0)
    lo, hi = v["to_min"], v["to_max"]
    if mode == "對數" and lo > 0 and hi > 0:
        r = lo * (hi / lo) ** t
    else:
        r = lo + t * (hi - lo)
    return _clip(r, min(lo, hi), max(lo, hi)) if clamped else r


def calc(node, v):
    """The number node gives, from its numbers v ({name: number}). One that cannot be worked out: 0."""
    kind = node["type"]
    try:
        if kind == "math":
            r = _MATH[_op(v)](v["a"], v["b"], v["c"])
            if v["clamp"] > 0.5:
                r = _clip(r, 0.0, 1.0)
        elif kind == "maprange":
            r = _map(v)
        elif kind == "clamp":
            lo, hi = v["lo"], v["hi"]
            r = min(max(v["x"], lo), hi) if v["mode"] < 0.5 else _clip(v["x"], min(lo, hi), max(lo, hi))
        else:
            r = v["value"]
        r = float(r)
    except (ValueError, OverflowError, ZeroDivisionError, TypeError):
        return 0.0
    return r if math.isfinite(r) else 0.0


class Numbers:
    """A graph's numbers at one moment.

    nodes   graph["nodes"]
    wires   {(node id, parameter name): the number node wired into it} (soundnodes.wires)
    t_us    the time the chain's keyframes are counted in
    names   what the global parameters read now (rack.values), or a function that gives it"""

    def __init__(self, nodes, wires, t_us, names=None):
        self.nodes, self.wires, self.t_us = nodes, wires, t_us
        self._names, self.made = names, {}

    def names(self):
        if callable(self._names):
            self._names = self._names()
        return self._names

    def of(self, nid):
        """What node nid gives, or None: nothing (a muted 數值 or 全局參數: what it feeds keeps its own)."""
        if nid not in self.made:
            node = self.nodes.get(nid)
            out = None
            if node is not None and node["type"] in TYPES and not (node.get("mute") and node["type"] not in THROUGH):
                v = own_values(node, self.t_us, self.names() if node.get("expr") else None)
                v.update(self.into(nid, SPECS[node["type"]]))
                out = v[THROUGH[node["type"]]] if node.get("mute") else calc(node, v)
            self.made[nid] = out
        return self.made[nid]

    def into(self, nid, specs):
        """{name: number} wired into node nid's parameters (specs), each inside its limits."""
        out = {}
        for p in specs:
            source = self.wires.get((nid, p["name"]))
            if source is not None:
                v = self.of(source)
                if v is not None:
                    out[p["name"]] = held(p, v)
        return out
