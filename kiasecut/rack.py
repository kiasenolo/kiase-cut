"""The global parameter rack (全局參數架): named values of the whole project. Any clip's number can
follow one through an expression (propexpr.py) by writing its name; its colours, words, fonts,
switches, menus and vectors can follow one of the same kind through a link (racklinks.py).

proj["rack"] = [{id, name, kind, value, expr, items}]
    name   a name an expression can read (letters, digits, _; not one of expr.py's own)
    kind   one of KINDS; absent: "number" (older projects)
    value  a value of the kind, or keyframes (curves.py) along the project's timeline:
             number, int   a number          bool   True / False        menu  one of items (its name)
             vec2, vec3    a list of numbers color  [r, g, b, a] 0 - 1  text  words
             font          a font file
           choices (bool, menu, text, font) hold until the next key, the others blend
    items  a menu's choices, in order
    lfo    optional (number, int): an LFO (lfo.py) - the parameter is its output along the timeline
           instead of value
    expr   optional (number, int): an expression (expr.py) that turns value into what the parameter
           is - input (value now), time (the timeline's seconds) and other parameters by name;
           absent: `input`

What an expression reads under a name: a number (int: rounded; menu: the choice's number from 0),
true / false, a list (vec2, vec3, color: name[0] ...) or words (text, font).

values() works them all out for a moment, in the order their expressions need; a parameter that
reads itself - through others too - is a circle (cycle()): edit.set_rack_expr refuses to make
one, and drawing one leaves such a parameter at its plain value.
"""
import copy
import json
import math
import re

from . import curves, expr, lfo, mapping

RESERVED = ({"input", "value", "time", "progress", "duration", "Math", "undefined", "null"}
            | set(expr.CONSTANTS) | set(expr.FUNCTIONS) | set(expr.NEEDS_ENV))
NAME = re.compile(r"^[A-Za-z_$][\w$]*$")
FORMAT = "kiasecut-rack"

KINDS = {"number": "數字", "int": "整數", "bool": "開關", "menu": "選單", "vec2": "二維向量",
         "vec3": "三維向量", "color": "顏色", "text": "文字", "font": "字體"}
NUMERIC = ("number", "int", "bool", "menu")      # (read as one number: what a 映射 can bind a clip's number to)
DRIVEN = ("number", "int")                       # (take an expression or an LFO of their own)
BLENDING = ("number", "int", "vec2", "vec3", "color")       # (blend between keyframes: easing curves apply)
SIZES = {"vec2": 2, "vec3": 3}
DEFAULT_ITEMS = ("選項 1", "選項 2")


def kind_of(p):
    return p.get("kind") or "number"


def default_value(kind, items=()):
    if kind == "font":
        from .project import DEFAULT_FONT
        return DEFAULT_FONT
    if kind == "menu":
        return (list(items) or list(DEFAULT_ITEMS))[0]
    return copy.deepcopy({"number": 0.0, "int": 0, "bool": False, "vec2": [0.0, 0.0], "vec3": [0.0, 0.0, 0.0],
                          "color": [1.0, 1.0, 1.0, 1.0], "text": ""}[kind])


def clean_items(items):
    """A menu's choices as stored: no empty ones, none twice."""
    return list(dict.fromkeys(s for s in (str(x).strip() for x in items or ()) if s))


def clean(kind, v, items=()):
    """v as a value of kind; ValueError when it cannot be one."""
    def num(x):
        if not isinstance(x, (int, float)) or not math.isfinite(x):
            raise ValueError("要是有限的數字")
        return float(x)
    if kind == "number":
        return num(float(v) if isinstance(v, bool) else v)
    if kind == "int":
        return int(round(num(v)))
    if kind == "bool":
        if not isinstance(v, (bool, int, float)):
            raise ValueError("要是開或關")
        return bool(v)
    if kind == "menu":
        items = list(items)
        if isinstance(v, str) and v in items:
            return v
        if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= int(v) < len(items):
            return items[int(v)]
        raise ValueError("選單裡沒有這個選項")
    if kind in SIZES:
        if not isinstance(v, (list, tuple)) or len(v) != SIZES[kind]:
            raise ValueError("向量的長度不對")
        return [num(x) for x in v]
    if kind == "color":
        if not isinstance(v, (list, tuple)) or len(v) not in (3, 4):
            raise ValueError("要是顏色")
        return [min(1.0, max(0.0, num(x))) for x in (list(v) + [1.0])[:4]]
    if kind in ("text", "font"):
        if not isinstance(v, str):
            raise ValueError("要是文字")
        return v
    raise ValueError("不認得的參數類型")


def value_at(p, t_us):
    """Parameter p's own value at t_us (its keyframes; no expression or LFO), as a value of its kind."""
    kind, items = kind_of(p), p.get("items") or ()
    try:
        return clean(kind, curves.value(p.get("value", default_value(kind, items)), t_us), items)
    except (ValueError, TypeError, KeyError, IndexError):
        return default_value(kind if kind in KINDS else "number", items)


def params(root):
    return (root or {}).get("rack") or []


def find(root, rid):
    return next((p for p in params(root) if p["id"] == rid), None)


def by_name(root, name):
    return next((p for p in params(root) if p["name"] == name), None)


def name_problem(root, name, rid=None):
    """Why name cannot be a parameter's name (None: it can)."""
    if not NAME.match(name or ""):
        return "名稱只能用英文字母、數字和 _，而且不能以數字開頭"
    if name in RESERVED:
        return f"「{name}」已經是表達式裡的名稱"
    other = by_name(root, name)
    if other is not None and other["id"] != rid:
        return f"已經有叫「{name}」的參數"
    return None


def refs(root, p):
    """The names of other rack parameters p's expression reads."""
    if not p.get("expr"):
        return set()
    try:
        used = expr.names(p["expr"])
    except expr.ExprError:
        return set()
    return {q["name"] for q in params(root) if q["name"] in used and q is not p}


def cycle(root):
    """The names of a circle of parameters that read each other (in order), or None."""
    graph = {p["name"]: refs(root, p) for p in params(root)}
    for p in params(root):                                   # (reading itself)
        if p.get("expr") and p["name"] in _names(p["expr"]):
            return [p["name"]]
    state, path = {}, []

    def visit(n):
        state[n] = 1
        path.append(n)
        for m in sorted(graph.get(n, ())):
            if state.get(m) == 1:
                return path[path.index(m):]
            if m not in state:
                found = visit(m)
                if found:
                    return found
        path.pop()
        state[n] = 2
        return None

    for n in graph:
        if n not in state:
            found = visit(n)
            if found:
                return found
    return None


def _names(text):
    """The names an expression (text) or a mapping (mapping.py) reads."""
    if lfo.is_lfo(text):
        return set()
    if mapping.is_mapping(text):
        return mapping.names(text)
    try:
        return expr.names(text)
    except expr.ExprError:
        return set()


def rename_expr(x, old, new):
    """An expression text or a mapping with the name `old` read as `new`."""
    if lfo.is_lfo(x):
        return x
    return mapping.renamed(x, old, new) if mapping.is_mapping(x) else rename_in(x, old, new)


class Values(dict):
    """{name: what an expression reads} of the rack's parameters at one moment. typed: {name: (kind, value)}
    as the parameter holds it (a menu's choice by its name), for links (racklinks.py)."""

    def __init__(self):
        super().__init__()
        self.typed = {}


def values(root, t_us):
    """Values of every parameter at timeline time t_us."""
    out = Values()
    ps = params(root)
    if not ps:
        return out
    busy = set()
    by = {p["name"]: p for p in ps}

    def get(p):
        n = p["name"]
        if n in out:
            return out[n]
        kind = kind_of(p)
        own = value_at(p, t_us)
        if kind in DRIVEN:
            base = float(own)
            if lfo.is_lfo(p.get("lfo")):
                base = lfo.safe(p["lfo"], t_us / curves.US, base)
            if p.get("expr") and n not in busy:
                busy.add(n)
                env = {"input": base, "value": base, "time": t_us / curves.US}
                for m in refs(root, p):
                    env[m] = get(by[m])
                base = expr.safe(p["expr"], env, default=base)
                busy.discard(n)
            if kind == "int":
                base = float(math.floor(base + 0.5))
            seen, own = base, int(base) if kind == "int" else base
        elif kind == "menu":
            items = p.get("items") or []
            seen = float(items.index(own)) if own in items else 0.0
        else:
            seen = own
        out[n] = seen
        out.typed[n] = (kind, own)
        return seen

    for p in ps:
        get(p)
    return out


def clips_with_exprs(root):
    """Every clip of the project (all timelines, compounds, groups) that has expressions or links."""
    from . import project
    holders = list((root.get("compounds") or {}).values()) or [root]
    for h in holders:
        for t in project.all_tracks(h.get("tracks") or [], inline=False):
            for c in t["clips"]:
                if c.get("expr") or c.get("links"):
                    yield c


def users(root, name):
    """How many clips (compounds' layers too) and sound effects have an expression or a link that
    reads the parameter `name`."""
    from . import soundfx
    sound = sum(1 for chain in soundfx.every_chain(root) for _path, e in soundfx.entries(chain)
                if any(name in _names(x) for x in (e.get("expr") or {}).values()))
    return sound + sum(1 for c in clips_with_exprs(root)
               if any(name in _names(x) for x in (c.get("expr") or {}).values()) or name in (c.get("links") or {}).values())


def rename_in(text, old, new):
    """expression text with the name `old` read as `new` (names only: not after a dot)."""
    try:
        toks = expr.tokens(text)
    except expr.ExprError:
        return text
    out, last = [], 0
    for i, (kind, val, pos) in enumerate(toks):
        if kind == "name" and val == old and not (i and toks[i - 1][1] == "."):
            out.append(text[last:pos] + new)
            last = pos + len(val)
    return "".join(out) + text[last:] if out else text


def export_text(root):
    return json.dumps({"format": FORMAT, "params": [
        {"name": p["name"], **({"kind": p["kind"]} if kind_of(p) != "number" else {}),
         **({"items": list(p.get("items") or [])} if kind_of(p) == "menu" else {}),
         "value": copy.deepcopy(p.get("value", 0.0)), **({"expr": p["expr"]} if p.get("expr") else {}),
         **({"lfo": copy.deepcopy(p["lfo"])} if lfo.is_lfo(p.get("lfo")) else {})}
        for p in params(root)]}, ensure_ascii=False, indent=1)


def _import_value(kind, v, items):
    """An imported value (a constant or keyframes) checked as one of kind; the kind's default when it is not."""
    try:
        if isinstance(v, dict):
            keys = [[int(k[0]), clean(kind, k[1], items), *(float(x) for x in k[2:6])] for k in v["keys"]]
            if keys and all(len(k) == 6 for k in keys):
                return {"keys": sorted(keys, key=lambda k: k[0])}
            raise ValueError
        return clean(kind, v, items)
    except (ValueError, TypeError, KeyError, IndexError):
        return default_value(kind, items)


def parse_import(text):
    """[{name, kind, value, expr, ...}] of an exported rack (ValueError when it is not one)."""
    try:
        data = json.loads(text)
    except ValueError:
        raise ValueError("這不是參數架檔案") from None
    items = data.get("params") if isinstance(data, dict) and data.get("format") == FORMAT else None
    if not isinstance(items, list):
        raise ValueError("這不是參數架檔案")
    out = []
    for d in items:
        if not isinstance(d, dict) or not NAME.match(str(d.get("name", ""))):
            continue
        kind = d.get("kind", "number")
        if kind not in KINDS:                          # (a kind of a newer version)
            continue
        choices = clean_items(d.get("items")) if kind == "menu" else []
        if kind == "menu" and not choices:
            continue
        e, l = d.get("expr"), d.get("lfo")
        out.append({"name": d["name"], **({"kind": kind} if kind != "number" else {}),
                    **({"items": choices} if kind == "menu" else {}),
                    "value": _import_value(kind, d.get("value"), choices),
                    **({"expr": e} if kind in DRIVEN and isinstance(e, str) and expr.check(e) is None else {}),
                    **({"lfo": l} if kind in DRIVEN and lfo.is_lfo(l) and lfo.check(l) is None else {})})
    if not out:
        raise ValueError("檔案裡沒有參數")
    return out
