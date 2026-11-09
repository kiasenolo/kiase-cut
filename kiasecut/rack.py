"""The global parameter rack (全局參數架): numbers of the whole project, named, that any clip's
number can follow through an expression (propexpr.py) by writing their name.

proj["rack"] = [{id, name, value, expr}]
    name   a name an expression can read (letters, digits, _; not one of expr.py's own)
    value  a number, or keyframes (curves.py) along the project's timeline
    lfo    optional: an LFO (lfo.py) - the parameter is its output along the timeline instead of value
    expr   optional: an expression (expr.py) that turns value into what the parameter is -
           input (value now), time (the timeline's seconds) and other parameters by name;
           absent: `input`

values() works them all out for a moment, in the order their expressions need; a parameter that
reads itself - through others too - is a circle (cycle()): edit.set_rack_expr refuses to make
one, and drawing one leaves such a parameter at its plain value.
"""
import copy
import json
import re

from . import curves, expr, lfo, mapping

RESERVED = ({"input", "value", "time", "progress", "duration", "Math", "undefined", "null"}
            | set(expr.CONSTANTS) | set(expr.FUNCTIONS) | set(expr.NEEDS_ENV))
NAME = re.compile(r"^[A-Za-z_$][\w$]*$")
FORMAT = "kiasecut-rack"


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


def values(root, t_us):
    """{name: number} of every parameter at timeline time t_us."""
    ps = params(root)
    if not ps:
        return {}
    out, busy = {}, set()
    by = {p["name"]: p for p in ps}

    def get(p):
        n = p["name"]
        if n in out:
            return out[n]
        base = curves.value(p.get("value", 0.0), t_us)
        base = float(base) if isinstance(base, (int, float)) else 0.0
        if lfo.is_lfo(p.get("lfo")):
            base = lfo.safe(p["lfo"], t_us / curves.US, base)
        if p.get("expr") and n not in busy:
            busy.add(n)
            env = {"input": base, "value": base, "time": t_us / curves.US}
            for m in refs(root, p):
                env[m] = get(by[m])
            base = expr.safe(p["expr"], env, default=base)
            busy.discard(n)
        out[n] = base
        return base

    for p in ps:
        get(p)
    return out


def clips_with_exprs(root):
    """Every clip of the project (all timelines, compounds, groups) that has expressions."""
    from . import project
    holders = list(root.get("timelines") or [root]) + list((root.get("compounds") or {}).values())
    for h in holders:
        for t in project.all_tracks(h.get("tracks") or []):
            for c in t["clips"]:
                if c.get("expr"):
                    yield c


def users(root, name):
    """How many clips (compounds' layers too) have an expression that reads the parameter `name`."""
    return sum(1 for c in clips_with_exprs(root) if any(name in _names(x) for x in c["expr"].values()))


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
        {"name": p["name"], "value": copy.deepcopy(p.get("value", 0.0)), **({"expr": p["expr"]} if p.get("expr") else {}),
         **({"lfo": copy.deepcopy(p["lfo"])} if lfo.is_lfo(p.get("lfo")) else {})}
        for p in params(root)]}, ensure_ascii=False, indent=1)


def parse_import(text):
    """[{name, value, expr}] of an exported rack (ValueError when it is not one)."""
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
        v = d.get("value", 0.0)
        if not (isinstance(v, (int, float)) or curves.is_animated(v)):
            v = 0.0
        e = d.get("expr")
        l = d.get("lfo")
        out.append({"name": d["name"], "value": v, **({"expr": e} if isinstance(e, str) and expr.check(e) is None else {}),
                    **({"lfo": l} if lfo.is_lfo(l) and lfo.check(l) is None else {})})
    if not out:
        raise ValueError("檔案裡沒有參數")
    return out
