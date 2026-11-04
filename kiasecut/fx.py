"""Filters: GLSL fragment shaders (format in filters/FORMAT.md) run with moderngl.

A filter file has a header of `// @name value` lines and an `effect(vec2 uv)` function; the
program adds the version line, the uniforms and main(). The built-in filters in filters/
use the same format as the user's (<Library>/filters/*.glsl).

Engine().run(def, params, rgba, ...) filters a premultiplied RGBA8 picture (numpy, H x W x 4)
and returns the result. An effect's colour parameter can read a picture instead (effect
"sources" {param: a picture / video / compound placed on the clip as a mask is, with the same
fields}): the shader then gets that colour per pixel (SAMPLED), the picture over the colour;
a number parameter (float, 使用遮罩) gets its number times the picture's brightness there
(SAMPLED_NUMBER), the number itself where the picture does not reach or is see-through. OpenGL contexts belong to the thread that made them, so every thread
that filters (the preview worker, the export) makes its own Engine.
"""
import glob
import hashlib
import os
import re
import shlex
import sys
import time

import numpy as np

from . import curves

PKG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "filters")
DOC_PATH = os.path.join(PKG, "FORMAT.md")
TEMPLATE_PATH = os.path.join(PKG, "_template.glsl")
BUILTIN = "builtin:"
MAX_PASSES = 32
BIG = 40000                      # a filter this long is first compiled with Python's lock let go (precompile())
TYPES = ("float", "int", "bool", "color", "vec2", "vec3", "menu", "curve", "gradient")
RESERVED = {"extra", "extra_", "pass_px", "src_px", "extra_px", "source", "original_", "resolution", "time", "progress", "frame", "scale", "pass_index", "output_index", "src",
            "original", "effect", "curve_ease", "gradient_eval", "unpremultiply", "premultiply", "rand", "uv_", "fragColor", "main"}


class FilterError(Exception):
    pass


class Param:
    def __init__(self, name, type_, default, lo=-1000.0, hi=1000.0, label=None, items=()):
        self.name, self.type, self.default = name, type_, default
        self.lo, self.hi, self.label = lo, hi, label or name
        self.items = list(items)                 # a menu's choices, in order (the shader gets the index)
        self.panel = None                        # the @panel it is in (None: the effect's own rows)
        self.enable = []                         # @enable conditions: (other param, negate, values or None)
        self.show = []                           # @show conditions (the same): a node shows the row only while they hold

    def __repr__(self):
        return f"Param({self.name}, {self.type}, {self.default})"


class FilterDef:
    def __init__(self, ref, name, code, params=(), category="", description="", passes=1, error=None, precise=False,
                 panels=(), levels=(), level_param=None, extras=(), fixed=()):
        self.ref, self.name, self.code = ref, name, code
        self.levels = list(levels)               # @levels: pass i < len is drawn 2^levels[i] times smaller than the canvas
        self.level_param = level_param           # ... and another 2^(that menu's choice number) times (Glare's 品質)
        self.fixed = list(fixed)                 # ... except the passes written "2f": those keep to the canvas size
        self.extras = list(extras)               # @extras: the earlier pass each pass can also read with extra() (None: none)
        self.panels = list(panels)               # [(name, closed at first)], in order (@panel)
        self.precise = precise                   # the passes before the last one keep 16-bit floats, not 8 bits
        self.params, self.category, self.description = list(params), category, description
        self.passes, self.error = passes, error
        self.src_label = "圖像"                  # @source: what the main picture socket is called
        self.out_label = "圖像"                  # what the main output is called (@socket out - ...)
        self.socket_types = {}                   # @socket: {("in" / "out", name): type} - what a socket carries, as Blender types its sockets (none: a picture)
        self.outputs = []                        # @output: [(name, label)] pictures a node gives (output_index tells which is drawn); none: one
        self.shared = False                      # @shared: only the last pass looks at output_index, the ones before it are drawn once for every output asked
        self.alone = []                          # @alone: outputs the last pass draws from nothing the earlier passes drew (they are not drawn for it)
        self.skips = []                          # @skip: (first pass, last pass, conditions): not drawn while the conditions hold
        self.input_param = {}                    # @input name "Label" param: the number box of that parameter sits on the input's row, hidden while a link feeds it
        self.input_show = {}                     # @show on an @input: {name: conditions}
        self.dynamic = None                      # @dynamic: the name of the generator that makes this filter's text from a node's items (dynamic.py)
        self.input_use = {}                      # @use: {input or "src": conditions}: the picture is read only while they hold (else it is not worked out at all)
        self.inputs = []                         # @input: [(name, label)] more pictures the filter reads, input_<name>(uv) (a node's sockets)

    def socket_type(self, way, name):
        """What socket `name` ("src" for the main input, "" for the main output) of way "in" / "out" carries: one of SOCKET_TYPES."""
        return self.socket_types.get((way, name), "image")

    def key(self):
        return hashlib.sha1((self.code + "|" + str(self.passes) + "|" + ",".join(n for n, _ in self.inputs) + "|" +
                             ",".join(f"{p.name}:{p.type}" for p in self.params)).encode()).hexdigest()


# -- reading filter files ---------------------------------------------------------------------------
HEADER = re.compile(r"^\s*//\s*@(\w+)[ \t]*(.*?)\s*$")
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _color(text):
    t = text.strip()
    if t.startswith("#") and len(t) in (7, 9):
        v = [int(t[i:i + 2], 16) / 255 for i in range(1, len(t), 2)]
        return v + [1.0] * (4 - len(v))
    parts = [float(x) for x in t.split(",")]
    if len(parts) not in (3, 4):
        raise ValueError("顏色要寫成 #rrggbb 或 #rrggbbaa")
    return parts + [1.0] * (4 - len(parts))


def _param(rest):
    tok = shlex.split(rest)
    if len(tok) < 3:
        raise ValueError("@param 需要：名稱 型別 預設值")
    name, typ, default, extra = tok[0], tok[1].lower(), tok[2], tok[3:]
    if not IDENT.match(name) or name in RESERVED:
        raise ValueError(f"參數名稱不能用「{name}」")
    if typ not in TYPES:
        raise ValueError(f"參數型別要是 {'、'.join(TYPES)}，不是「{typ}」")
    lo, hi, label = -1000.0, 1000.0, None
    nums = []
    while extra:
        try:
            nums.append(float(extra[0]))
            extra = extra[1:]
        except ValueError:
            break
    if typ == "menu":
        return _menu_param(name, default, extra)
    if len(nums) >= 2:
        lo, hi = nums[0], nums[1]
    if extra:
        label = extra[0]
    if typ == "float":
        d = float(default)
    elif typ == "int":
        d = int(float(default))
    elif typ == "bool":
        d = default.lower() in ("1", "true", "yes", "on")
    elif typ == "color":
        d = _color(default)
    elif typ == "curve":
        d = [float(x) for x in default.split(",")]
        if len(d) != 4 or not (0 <= d[0] <= 1 and 0 <= d[2] <= 1):
            raise ValueError("curve 的預設值要寫成 x1,y1,x2,y2（cubic-bezier 的兩個控制點，x 在 0 - 1）")
    elif typ == "gradient":
        d = _gradient_default(default)
    else:
        n = 2 if typ == "vec2" else 3
        d = [float(x) for x in default.split(",")]
        if len(d) != n:
            raise ValueError(f"{typ} 的預設值要寫成 {','.join('xyz'[:n])}")
    return Param(name, typ, d, lo, hi, label)


def _gradient_default(text):
    """`0:#000000,0.5:#ff0000,1:#ffffff`: the colour stops (position 0 - 1: colour) of a gradient parameter."""
    try:
        stops = [[float(a), _color(b)] for a, b in (x.split(":", 1) for x in text.split(","))]
    except ValueError:
        raise ValueError("gradient 的預設值要寫成 位置:顏色,位置:顏色…（例如 0:#000000,1:#ffffff）") from None
    if len(stops) < 2 or len(stops) > GRADIENT_N or not all(0 <= x[0] <= 1 for x in stops):
        raise ValueError(f"gradient 要有 2 - {GRADIENT_N} 個色標，位置在 0 - 1")
    return sorted(stops, key=lambda x: x[0])


def _menu_param(name, default, extra):
    """`// @param name menu default "A|B|C" ["label"]`: the default is one of the choices, or its
    number (0 is the first)."""
    items = [x.strip() for x in extra[0].split("|")] if extra else []
    if not items or not all(items):
        raise ValueError("menu 要寫出選項，用 | 隔開，例如 \"線性|平滑|銳利\"")
    if len(set(items)) != len(items):
        raise ValueError("menu 的選項重複了")
    if default not in items:
        try:
            default = items[int(default)]
        except (ValueError, IndexError):
            raise ValueError(f"menu 的預設值要是其中一個選項（{'、'.join(items)}）") from None
    return Param(name, "menu", default, 0, len(items) - 1, extra[1] if len(extra) > 1 else None, items)


ENABLE = re.compile(r"^(\w+)\s+(?:(!?)(\w+)|(\w+)\s*(==|!=)\s*(.+))$")


def _enable(rest, params, inputs=(), show=None, word=None):
    """`// @enable target cond`: cond is `flag`, `!flag` (a bool parameter) or `other == A|B`,
    `other != A` (a menu's choices, or numbers)."""
    m = ENABLE.match(rest.strip())
    if not m:
        raise ValueError("@enable 要寫成：參數 條件（例如 size type == Bloom|Fog Glow，或 maximum clamp_on）")
    target, neg, flag, other, op, vals = m.groups()
    by = {p.name: p for p in params}
    word = word or ("@enable" if show is None else "@show" if "src" not in inputs else "@use")
    name = flag or other
    if target in by:
        into = by[target].show if show is not None else by[target].enable
    elif show is not None and target in inputs:
        into = show.setdefault(target, [])
    else:
        raise ValueError(f"{word}：沒有叫「{target}」的參數")
    if name not in by:
        raise ValueError(f"{word}：沒有叫「{name}」的參數")
    if flag:
        into.append((name, bool(neg), None))
    else:
        into.append((name, op == "!=", [v.strip() for v in vals.split("|")]))


SKIP = re.compile(r"^(\d+)(?:\s*-\s*(\d+))?\s+(\w+)\s*(==|!=)\s*(.+)$")


def _skip(rest, params):
    """`// @skip 1-23 type != Bloom`: passes 1 to 23 (`3`: just that one) are not drawn while the condition holds (a
    menu parameter's choices, or numbers, as @enable's)."""
    m = SKIP.match(rest.strip())
    if not m:
        raise ValueError("@skip 要寫成：第幾次（或 起-訖） 參數 == 選項（例如 1-23 type != Bloom）")
    first, last, name, op, vals = m.groups()
    if all(q.name != name for q in params):
        raise ValueError(f"@skip：沒有叫「{name}」的參數")
    first, last = int(first), int(last if last is not None else first)
    return first, max(first, last), [(name, op == "!=", [v.strip() for v in vals.split("|")])]


def enabled(p, values):
    """Whether parameter p does anything with the effect's other values {name: value} (its
    @enable conditions; a menu's value is its choice's name, or its number)."""
    return _holds(p.enable + p.show, values)


def shown(d, name, values):
    """Whether a node of filter d shows the row of input or parameter `name` (its @show conditions, as enabled())."""
    conds = d.input_show.get(name)
    if conds is None:
        conds = next((p.show for p in d.params if p.name == name), [])
    return _holds(conds, values)


def _holds(conds, values):
    for other, negate, want in conds:
        v = values.get(other)
        if want is None:
            ok = bool(v)
        else:
            ok = str(v) in want or (isinstance(v, (int, float)) and not isinstance(v, bool)
                                    and any(_num(w) == v for w in want))
        if ok == negate:
            return False
    return True


def named(d, values):
    """values {name: value} of filter d with each menu's value as its choice's name (a number
    stored for one becomes the name), as enabled() compares them."""
    out = dict(values)
    for p in d.params:
        v = out.get(p.name)
        if p.type == "menu" and isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= int(v) < len(p.items):
            out[p.name] = p.items[int(v)]
    return out


def _num(text):
    try:
        return float(text)
    except ValueError:
        return None


SOCKET_TYPES = ("image", "float", "int", "bool", "vector", "color", "menu")       # what a socket can carry (@socket)
SOCKET_LABELS = {"image": "圖像", "float": "數值", "int": "整數", "bool": "布林", "vector": "向量", "color": "顏色", "menu": "選單"}


def parse(text, ref, fallback_name="濾鏡"):
    """FilterDef of a filter file's text. A file with mistakes still gives a FilterDef, with
    `error` set (the panel shows it) so that one bad file never breaks the program."""
    head = {}
    params, error = [], None
    panels, panel, enables, inputs, outputs = [], None, [], [], []
    input_param, alone, skips = {}, [], []
    sockets = []
    for line in text.splitlines():
        m = HEADER.match(line)
        if not m:
            continue
        key, rest = m.group(1).lower(), m.group(2)
        try:
            if key == "param":
                p = _param(rest)
                if any(q.name == p.name for q in params):
                    raise ValueError(f"參數「{p.name}」重複了")
                p.panel = panel
                params.append(p)
            elif key == "panel":                          # the params after it go in a folding panel
                words = shlex.split(rest) if rest.strip() else []
                panel = words[0] if words and words[0] != "-" else None
                if panel and all(n != panel for n, _ in panels):
                    panels.append((panel, "closed" in words[1:]))
            elif key == "source":
                words = shlex.split(rest)
                head["source"] = words[0] if words else ""
                if len(words) > 1:                            # (the same pairing as @input: this parameter's box sits on the row)
                    input_param["src"] = words[1]
            elif key == "input":                          # a picture more than src(): input_<name>(uv)
                words = shlex.split(rest)
                if not words or not IDENT.match(words[0]) or words[0] in RESERVED or any(words[0] == n for n, _ in inputs):
                    raise ValueError("@input 要寫：名稱（英文、數字、底線，不重複）[\"顯示名稱\"]")
                inputs.append((words[0], words[1] if len(words) > 1 else words[0]))
                if len(words) > 2:
                    input_param[words[0]] = words[2]
            elif key == "output":                         # a picture more than one a node gives: drawn again with output_index = its place
                words = shlex.split(rest)
                if not words or not IDENT.match(words[0]) or any(words[0] == n for n, _ in outputs):
                    raise ValueError("@output 要寫：名稱（英文、數字、底線，不重複）[\"顯示名稱\"]")
                outputs.append((words[0], words[1] if len(words) > 1 else words[0]))
            elif key == "socket":                         # @socket in|out name|- type ["label"]: a socket that carries a value, not a picture
                words = shlex.split(rest)
                if len(words) < 3 or words[0] not in ("in", "out") or words[2] not in SOCKET_TYPES:
                    raise ValueError("@socket 要寫：in 或 out、插槽名稱（- 是主要的）、種類（" + " / ".join(SOCKET_TYPES) + "）[\"顯示名稱\"]")
                sockets.append((words[0], "" if words[1] == "-" and words[0] == "out" else "src" if words[1] == "-" else words[1],
                                words[2], words[3] if len(words) > 3 else None))
            elif key == "shared":
                head["shared"] = True
            elif key == "alone":
                alone += shlex.split(rest)
            elif key == "skip":                           # (read once every @param is known)
                skips.append((line, rest))
            elif key in ("enable", "show", "use"):         # (read once every @param is known)
                enables.append((line, rest, key))
            elif key in ("filter", "category", "description"):
                head[key] = rest
            elif key == "dynamic":
                head["dynamic"] = rest.strip()
            elif key == "passes":
                head["passes"] = max(1, min(MAX_PASSES, int(rest)))
            elif key == "levels":                         # (read once every @param is known)
                head["levels"] = rest.split()
            elif key == "extras":
                head["extras"] = [None if w == "-" else int(w) for w in rest.split()]
            elif key == "precision":
                if rest.lower() not in ("float", "8bit"):
                    raise ValueError("@precision 要寫 float 或 8bit")
                head["precise"] = rest.lower() == "float"
        except ValueError as exc:
            error = error or f"{line.strip()}\n{exc}"
    input_show, input_use = {}, {}
    for line, rest, kind in enables:
        try:
            _enable(rest, params, [n for n, _ in inputs] + (["src"] if kind != "enable" else []) + ([n for n, _ in outputs] if kind == "show" else []),
                    input_show if kind == "show" else input_use if kind == "use" else None, "@" + kind)       # (@show: also the main picture and the outputs)
        except ValueError as exc:
            error = error or f"{line.strip()}\n{exc}"
    skipped = []
    for line, rest in skips:
        try:
            skipped.append(_skip(rest, params))
        except ValueError as exc:
            error = error or f"{line.strip()}\n{exc}"
    for name in alone:
        if all(name != n for n, _ in outputs):
            error = error or f"@alone：沒有叫「{name}」的 @output"
    levels, level_param, fixed = [], None, []
    words = head.get("levels", [])
    if words and not words[-1].rstrip("f").lstrip("-").isdigit():
        level_param = words.pop()
        if not any(q.name == level_param and q.type == "menu" for q in params):
            error = error or f"@levels：「{level_param}」不是選單參數"
    try:
        levels = [max(0, int(w.rstrip("f"))) for w in words]
        fixed = [w.endswith("f") for w in words]
    except ValueError:
        error = error or "@levels 要寫一串數字（每一次繪製縮小幾次），最後可以接一個選單參數的名字"
    n = head.get("passes", 1)
    if len(levels) > n or any(e is not None and not 0 <= e < i for i, e in enumerate(head.get("extras", []))):
        error = error or "@levels 不能比 @passes 多；@extras 只能讀前面的繪製"
    if "effect" not in text:
        error = error or "找不到 effect() 函式"
    d = FilterDef(ref, head.get("filter") or fallback_name, text, params, head.get("category", ""),
                  head.get("description", ""), n, error, head.get("precise", False), panels, levels, level_param,
                  head.get("extras", []), fixed)
    d.inputs = inputs
    d.input_show = input_show
    d.input_use = input_use
    d.dynamic = head.get("dynamic")
    d.input_param = input_param
    for iname, pname in input_param.items():
        if not any(q.name == pname and q.type in ("float", "int") for q in params):
            d.error = d.error or f"@input {iname}：「{pname}」不是數字參數"
    d.outputs = outputs
    d.shared, d.alone, d.skips = head.get("shared", False), alone, skipped
    d.src_label = head.get("source") or d.src_label
    for way, name, kind, label in sockets:
        d.socket_types[(way, name)] = kind
        if way == "in" and name == "src":
            d.src_label = label or (d.src_label if head.get("source") else SOCKET_LABELS[kind])
        elif way == "out" and name == "":
            d.out_label = label or SOCKET_LABELS[kind]
        elif way == "out" and label:
            d.outputs = [(n, label if n == name else l) for n, l in d.outputs]
    return d


_cache = {}


def _file_def(path, ref, fallback):
    try:
        st = os.stat(path)
    except OSError:
        return FilterDef(ref, fallback, "", error="找不到濾鏡檔案")
    key = (path, st.st_mtime_ns, st.st_size)
    hit = _cache.get(path)
    if hit and hit[0] == key:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        d = FilterDef(ref, fallback, "", error=f"讀不到檔案：{exc}")
    else:
        d = parse(text, ref, fallback)
    _cache[path] = (key, d)
    return d


GRAPH = "nodes:graph"            # the filter of an effect that is a node graph (nodegraph.py; e["graph"])
GRAPH_DEF = FilterDef(GRAPH, "節點效果", "", category="節點", description="用節點編輯器組出來的效果")


def get(ref):
    """FilterDef of "builtin:name" or of a filter file's path."""
    if ref == GRAPH:
        return GRAPH_DEF
    if ref.startswith(BUILTIN):
        name = ref[len(BUILTIN):]
        return _file_def(os.path.join(PKG, name + ".glsl"), ref, name)
    return _file_def(ref, ref, os.path.splitext(os.path.basename(ref))[0])


_special = {}


def for_node(node):
    """FilterDef of a filter node: its file's, or - for a filter that says @dynamic - one made from the node's own items
    (the Menu Switch's options, named and counted by the user): the generator of dynamic.py writes the filter text."""
    d = get(node["ref"])
    if not d.dynamic:
        return d
    from . import dynamic
    items = dynamic.items_of(node, d.dynamic)
    key = (node["ref"], d.dynamic, tuple(items))
    got = _special.get(key)
    if got is None:
        if len(_special) > 256:
            _special.clear()
        got = _special[key] = parse(dynamic.generate(d.dynamic, items), node["ref"], d.name)
    return got


def def_of(e):
    """FilterDef of effect e: its filter's, or for a node graph one whose parameters are those of its nodes."""
    if e["filter"] == GRAPH and "graph" in e:
        from . import nodegraph
        return nodegraph.virtual_def(e)
    return get(e["filter"])


def builtin_refs():
    """Refs of the built-in filters, in the order the menus list them."""
    out = []
    for path in sorted(glob.glob(os.path.join(PKG, "*.glsl"))):
        name = os.path.splitext(os.path.basename(path))[0]
        if not name.startswith("_"):
            out.append(BUILTIN + name)
    return sorted(out, key=lambda r: (get(r).category, get(r).name))


def default_params(d):
    return {p.name: (list(p.default) if isinstance(p.default, list) else p.default) for p in d.params}


def new_effect(ref, effect_id):
    """A new effect entry for a clip: {id, filter, enabled, params}; an optional "mix" (0 - 1,
    may be keyframed: 混合程度) blends the result with the picture it was given, 1 when absent."""
    d = get(ref)
    params = default_params(d)
    for p in d.params:
        if p.name == "seed" and p.type in ("float", "int") and p.hi > p.lo:
            stamp = time.time_ns() / 1_000_000_000
            seed = p.lo + (stamp % (p.hi - p.lo))
            params[p.name] = round(seed) if p.type == "int" else seed
    e = {"id": effect_id, "filter": ref, "enabled": True, "params": params}
    if ref == GRAPH:                             # (nodegraph.py)
        from . import nodegraph
        e["graph"] = nodegraph.new_graph()
        e["params"].update(nodegraph.default_params(e["graph"]))
    return e


def mix_at(e, t):
    """How much of effect e's result shows at clip time t (0 - 1: its 混合程度)."""
    return min(1.0, max(0.0, float(curves.value(e.get("mix", 1.0), t))))


def label(ref):
    return get(ref).name


def menu_index(p, v):
    """Index of choice v of menu parameter p (a choice that is not there: the default's)."""
    if isinstance(v, str) and v in p.items:
        return p.items.index(v)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return min(max(int(round(v)), 0), len(p.items) - 1)
    return p.items.index(p.default)


GRADIENT_N = 32                  # most colour stops a gradient parameter has (Blender's colour ramp has as many)
CURVE_N = 128                    # a curve parameter reaches the shader as this many samples


def curve_keys(v):
    """The keys [[x, y, left dx, left dy, right dx, right dy], ...] (x from 0 to 1, as the
    keyframe editor's, handles as offsets) of a curve parameter's value: a list of keys, or the
    four numbers of a cubic-bezier (x1, y1, x2, y2); an empty or unusable one is a straight line."""
    try:
        if isinstance(v, (list, tuple)) and len(v) == 4 and not isinstance(v[0], (list, tuple)):
            x1, y1, x2, y2 = (float(a) for a in v)
            return [[0.0, 0.0, 0.0, 0.0, x1, y1], [1.0, 1.0, x2 - 1.0, y2 - 1.0, 0.0, 0.0]]
        keys = [[float(a) for a in k][:6] for k in v]
        if keys and all(len(k) == 6 for k in keys):
            return sorted(keys, key=lambda k: k[0])
    except (TypeError, ValueError):
        pass
    return [[0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [1.0, 1.0, 0.0, 0.0, 0.0, 0.0]]


def gradient_stops(v):
    """The stops [[position, [r, g, b, a]], ...] (positions 0 - 1, in order, up to GRADIENT_N) of a gradient
    parameter's value; an empty or unusable one is black to white."""
    try:
        stops = [[min(1.0, max(0.0, float(x))), [min(1.0, max(0.0, float(a))) for a in (list(c) + [1.0])[:4]]]
                 for x, c in v][:GRADIENT_N]
        if len(stops) >= 1 and all(len(c) == 4 for _x, c in stops):
            return sorted(stops, key=lambda s: s[0])
    except (TypeError, ValueError):
        pass
    return [[0.0, [0.0, 0.0, 0.0, 1.0]], [1.0, [1.0, 1.0, 1.0, 1.0]]]


def gradient_color(stops, x, interp=2, mode=0, hue=0):
    """The colour [r, g, b, a] of gradient `stops` at x (0 - 1) as gradient_eval() of the shader gives it (interp 0 ease,
    1 cardinal, 2 linear, 3 b-spline, 4 constant; mode 0 rgb, 1 hsv, 2 hsl; hue 0 near, 1 far, 2 clockwise, 3 counter-
    clockwise): what a node's picture of a gradient draws."""
    import colorsys
    p = [s[0] for s in stops]
    c = [list(s[1]) for s in stops]
    n = len(stops)
    x = min(1.0, max(0.0, x))
    if n < 2:
        return c[0]
    if mode != 0:
        interp = 2
    spline = interp in (1, 3)
    a = 0
    while a < n and p[a] <= x:
        a += 1
    if (a == n or a == 0) and not spline:
        return c[n - 1] if a == n else c[0]
    if a == 0:
        l = pl = c[0]; lp = 0.0; r = c[0]; rp = p[0]; nr = c[1]
    elif a == n:
        if p[n - 1] >= 1.0:
            l = c[n - 2]; lp = p[n - 2]; r = nr = c[n - 1]; rp = p[n - 1]; pl = c[max(n - 3, 0)]
        else:
            l = c[n - 1]; lp = p[n - 1]; r = nr = c[n - 1]; rp = 1.0; pl = c[n - 2]
    else:
        l = c[a - 1]; lp = p[a - 1]; r = c[a]; rp = p[a]
        pl = l if a < 2 else c[a - 2]
        nr = r if a >= n - 1 else c[a + 1]
    u = (x - lp) / (rp - lp) if rp > lp else 0.0
    if interp == 4:
        return l
    if interp == 0:
        u = u * u * (3.0 - 2.0 * u)
    if spline:
        u2, u3 = u * u, u * u * u
        if interp == 1:
            w = (-0.71 * u3 + 1.42 * u2 - 0.71 * u, 1.29 * u3 - 2.29 * u2 + 1.0, -1.29 * u3 + 1.58 * u2 + 0.71 * u, 0.71 * u3 - 0.71 * u2)
        else:
            w = (-u3 / 6.0 + 0.5 * u2 - 0.5 * u + 1.0 / 6.0, 0.5 * u3 - u2 + 2.0 / 3.0, -0.5 * u3 + 0.5 * u2 + 0.5 * u + 1.0 / 6.0, u3 / 6.0)
        return [min(1.0, max(0.0, pl[i] * w[0] + l[i] * w[1] + r[i] * w[2] + nr[i] * w[3])) for i in range(4)]
    if mode == 0:
        return [l[i] + (r[i] - l[i]) * u for i in range(4)]
    conv = colorsys.rgb_to_hsv if mode == 1 else lambda *q: colorsys.rgb_to_hls(*q)
    back = colorsys.hsv_to_rgb if mode == 1 else lambda h, s_, l_: colorsys.hls_to_rgb(h, l_, s_)

    def split(col):                                     # (hue, saturation, value / lightness)
        if mode == 1:
            return colorsys.rgb_to_hsv(*col[:3])
        h, lt, s_ = colorsys.rgb_to_hls(*col[:3])
        return h, s_, lt
    x1, x2 = split(l), split(r)
    h1, h2 = x1[0], x2[0]
    d = h2 - h1
    if hue == 0:
        if d > 0.5: h1 += 1.0
        elif d < -0.5: h2 += 1.0
    elif hue == 1:
        if 0.0 < d < 0.5: h1 += 1.0
        elif d <= 0.0 and d > -0.5: h2 += 1.0
    elif hue == 2:
        if h2 < h1: h2 += 1.0
    elif h1 < h2:
        h1 += 1.0
    h = (h1 + (h2 - h1) * u) % 1.0
    s_ = x1[1] + (x2[1] - x1[1]) * u
    v = x1[2] + (x2[2] - x1[2]) * u
    rgb = colorsys.hsv_to_rgb(h, s_, v) if mode == 1 else colorsys.hls_to_rgb(h, v, s_)
    return [rgb[0], rgb[1], rgb[2], l[3] + (r[3] - l[3]) * u]


def gradient_uniforms(v):
    """(positions padded to GRADIENT_N, colours padded to GRADIENT_N x 4 flat, how many) for the shader."""
    st = gradient_stops(v)
    pos = [s[0] for s in st] + [1.0] * (GRADIENT_N - len(st))
    col = [a for s in st for a in s[1]] + list(st[-1][1]) * (GRADIENT_N - len(st))
    return tuple(pos), tuple(col), len(st)


def curve_samples(v, n=CURVE_N):
    """n samples of a curve parameter's value from x = 0 to 1 (the keyframe editor's curve: the value
    holds before its first key and after its last)."""
    u = 1_000_000
    param = {"keys": [[k[0] * u, k[1], k[2] * u, k[3], k[4] * u, k[5]] for k in curve_keys(v)]}
    return tuple(float(curves.value(param, u * i / (n - 1))) for i in range(n))


def uniform_value(p, stored, t):
    """The value to give the shader for parameter p (stored: a number / list / curve; a menu
    stores the name of its choice)."""
    v = curves.value(stored if stored is not None else p.default, t)
    if p.type == "menu":
        return menu_index(p, v)
    if p.type == "float":
        return float(v)
    if p.type == "int":
        return int(round(v))
    if p.type == "bool":
        return bool(v)
    if p.type == "color":
        v = list(v) + [1.0] * (4 - len(v))
        return tuple(float(x) for x in v[:4])
    if p.type == "curve":
        return curve_samples(v)
    if p.type == "gradient":
        return gradient_uniforms(v)
    n = 3 if p.type == "vec3" else 2
    v = list(v) + [0.0] * (n - len(v))
    return tuple(float(x) for x in v[:n])


# -- the shader -------------------------------------------------------------------------------------
PRELUDE = """#version 330
uniform sampler2D source;
uniform sampler2D original_;
uniform vec2 resolution;
uniform float time;
uniform float progress;
uniform int frame;
uniform float scale;
uniform int pass_index;
uniform int output_index;
uniform sampler2D extra_;
uniform vec2 pass_px;
uniform vec2 src_px;
uniform vec2 extra_px;
%(params)s
in vec2 uv_;
out vec4 fragColor;
uniform bool src_on_;
bool has_src() { return src_on_; }
vec4 src(vec2 uv) { return texture(source, clamp(uv, 0.0, 1.0)); }
vec4 original(vec2 uv) { return texture(original_, clamp(uv, 0.0, 1.0)); }
vec4 extra(vec2 uv) { return texture(extra_, clamp(uv, 0.0, 1.0)); }
vec4 unpremultiply(vec4 c) { return c.a > 0.0 ? vec4(c.rgb / c.a, c.a) : vec4(0.0); }
vec4 premultiply(vec4 c) { return vec4(c.rgb * c.a, c.a); }
// a curve parameter: its y at x (0 - 1), between its samples
float curve_ease(float c[128], float x) {
    float f = clamp(x, 0.0, 1.0) * float(127);
    int i = int(floor(f));
    return mix(c[i], c[min(i + 1, 127)], f - float(i));
}
// a gradient parameter (name_p positions, name_c colours, name_n how many): its colour at x (0 - 1), as Blender's
// colour ramp gives it. interp 0 ease, 1 cardinal, 2 linear, 3 b-spline, 4 constant; mode 0 rgb, 1 hsv, 2 hsl;
// hue (hsv / hsl): 0 near, 1 far, 2 clockwise, 3 counter-clockwise. Straight (not premultiplied) colours
vec3 gradient_hsv_(vec3 c) {
    float mx = max(c.r, max(c.g, c.b)), mn = min(c.r, min(c.g, c.b)), d = mx - mn, h = 0.0;
    if (d > 0.0) {
        if (mx == c.r) h = (c.g - c.b) / d; else if (mx == c.g) h = 2.0 + (c.b - c.r) / d; else h = 4.0 + (c.r - c.g) / d;
        h /= 6.0; if (h < 0.0) h += 1.0;
    }
    return vec3(h, mx > 0.0 ? d / mx : 0.0, mx);
}
vec3 gradient_hsl_(vec3 c) {
    float mx = max(c.r, max(c.g, c.b)), mn = min(c.r, min(c.g, c.b)), d = mx - mn, l = (mx + mn) * 0.5, h = 0.0, s = 0.0;
    if (d > 0.0) {
        s = l <= 0.5 ? d / (mx + mn) : d / (2.0 - mx - mn);
        if (mx == c.r) h = (c.g - c.b) / d; else if (mx == c.g) h = 2.0 + (c.b - c.r) / d; else h = 4.0 + (c.r - c.g) / d;
        h /= 6.0; if (h < 0.0) h += 1.0;
    }
    return vec3(h, s, l);
}
vec3 gradient_from_hsv_(vec3 c) {
    vec3 k = clamp(abs(fract(c.x + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0) - 1.0, 0.0, 1.0);
    return c.z * mix(vec3(1.0), k, c.y);
}
vec3 gradient_from_hsl_(vec3 c) {
    vec3 k = clamp(abs(fract(c.x + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0) - 1.0, 0.0, 1.0);
    float ch = (1.0 - abs(2.0 * c.z - 1.0)) * c.y;
    return (k - 0.5) * ch + c.z;
}
vec4 gradient_blend_(vec4 a, vec4 b, float f, int mode, int hue) {
    if (mode == 0) return mix(a, b, f);
    vec3 x = mode == 1 ? gradient_hsv_(a.rgb) : gradient_hsl_(a.rgb), y = mode == 1 ? gradient_hsv_(b.rgb) : gradient_hsl_(b.rgb);
    float h1 = x.x, h2 = y.x, d = h2 - h1;
    if (hue == 0) { if (d > 0.5) h1 += 1.0; else if (d < -0.5) h2 += 1.0; }
    else if (hue == 1) { if (d > 0.0 && d < 0.5) h1 += 1.0; else if (d <= 0.0 && d > -0.5) h2 += 1.0; }
    else if (hue == 2) { if (h2 < h1) h2 += 1.0; }
    else { if (h1 < h2) h1 += 1.0; }
    vec3 m = vec3(fract(mix(h1, h2, f)), mix(x.yz, y.yz, f));
    return vec4(mode == 1 ? gradient_from_hsv_(m) : gradient_from_hsl_(m), mix(a.a, b.a, f));
}
vec4 gradient_eval(float p[32], vec4 c[32], int n, float x, int interp, int mode, int hue) {
    x = clamp(x, 0.0, 1.0);
    if (n < 2) return c[0];
    if (mode != 0) interp = 2;                                 // (hsv / hsl: always linear, as Blender's)
    bool spline = interp == 1 || interp == 3;
    int a = 0;                                                // the first stop after x
    while (a < n && p[a] <= x) a++;
    if (a == n && !spline) return c[n - 1];
    if (a == 0 && !spline) return c[0];
    vec4 l, r, pl, nr;                                        // the segment's left and right, and the stops outside them
    float lp, rp;
    if (a == 0) { l = pl = c[0]; lp = 0.0; r = c[0]; rp = p[0]; nr = c[1]; }
    else if (a == n) {
        if (p[n - 1] >= 1.0) { l = c[n - 2]; lp = p[n - 2]; r = nr = c[n - 1]; rp = p[n - 1]; pl = c[max(n - 3, 0)]; }
        else { l = c[n - 1]; lp = p[n - 1]; r = nr = c[n - 1]; rp = 1.0; pl = c[n - 2]; }
    } else { l = c[a - 1]; lp = p[a - 1]; r = c[a]; rp = p[a]; pl = a < 2 ? l : c[a - 2]; nr = a >= n - 1 ? r : c[a + 1]; }
    float u = rp > lp ? (x - lp) / (rp - lp) : 0.0;
    if (interp == 4) return l;
    if (interp == 0) u = u * u * (3.0 - 2.0 * u);
    if (spline) {
        float u2 = u * u, u3 = u2 * u;
        vec4 w = interp == 1 ? vec4(-0.71 * u3 + 1.42 * u2 - 0.71 * u, 1.29 * u3 - 2.29 * u2 + 1.0, -1.29 * u3 + 1.58 * u2 + 0.71 * u, 0.71 * u3 - 0.71 * u2)
                             : vec4(-u3 / 6.0 + 0.5 * u2 - 0.5 * u + 1.0 / 6.0, 0.5 * u3 - u2 + 2.0 / 3.0, -0.5 * u3 + 0.5 * u2 + 0.5 * u + 1.0 / 6.0, u3 / 6.0);
        return clamp(pl * w.x + l * w.y + r * w.z + nr * w.w, 0.0, 1.0);
    }
    return gradient_blend_(l, r, u, mode, hue);
}
float rand(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
// the frame as two small numbers (the frame itself is too big for a hash to stay fine: past ~20000 the float
// loses its fraction and noise made from it stops changing): .x the frame within a block of 1024, .y the block
vec2 frame_phase() { return vec2(float(frame & 1023), float(frame >> 10)); }
%(sampled)s
#line 1
"""
# a colour parameter fed by a picture (an effect's "sources"): its value at this pixel is the
# picture's colour there (placed by NAME_map_: this layer's uv -> the picture's), over its own
# colour where the picture does not reach or is see-through; straight alpha, as a colour is
SAMPLED = """uniform vec4 %(n)s_col_;
uniform sampler2D %(n)s_tex_;
uniform mat3 %(n)s_map_;
vec4 %(n)s_at_() {
    vec3 q = %(n)s_map_ * vec3(uv_, 1.0);
    vec4 s = (q.x < 0.0 || q.y < 0.0 || q.x > 1.0 || q.y > 1.0) ? vec4(0.0) : texture(%(n)s_tex_, q.xy);
    vec4 c = %(n)s_col_;
    float a = s.a + c.a * (1.0 - s.a);
    return a > 0.0 ? vec4((s.rgb + c.rgb * c.a * (1.0 - s.a)) / a, a) : vec4(0.0);
}
#define %(n)s %(n)s_at_()"""
# a number parameter fed by a picture (使用遮罩): from its minimum (black) to its maximum (white) by
# the picture's brightness at this pixel (Rec. 709 weights, as a 明度 mask's) - 0 and the number
# itself unless the source says otherwise - and its own number where the picture does not reach,
# fading to it where the picture is see-through
SAMPLED_NUMBER = """uniform float %(n)s_val_;
uniform float %(n)s_min_;
uniform float %(n)s_max_;
uniform sampler2D %(n)s_tex_;
uniform mat3 %(n)s_map_;
float %(n)s_at_() {
    vec3 q = %(n)s_map_ * vec3(uv_, 1.0);
    vec4 s = (q.x < 0.0 || q.y < 0.0 || q.x > 1.0 || q.y > 1.0) ? vec4(0.0) : texture(%(n)s_tex_, q.xy);
    float k = s.a > 0.0 ? dot(s.rgb, vec3(0.2126, 0.7152, 0.0722)) / s.a : 0.0;
    return mix(%(n)s_val_, mix(%(n)s_min_, %(n)s_max_, clamp(k, 0.0, 1.0)), s.a);
}
#define %(n)s %(n)s_at_()"""
SOURCE_TYPES = ("color", "float")              # parameters that can read a picture
RANGE_MIN, RANGE_MAX = "\0min", "\0max"        # (suffixes of a number source's value keys: what black and white give)


def source_range(src, own, t):
    """(minimum, maximum) a number source gives for black and white at clip time t: 0 and the
    parameter's own number unless the source has its own."""
    mn, mx = src.get("min"), src.get("max")
    return (0.0 if mn is None else float(curves.value(mn, t)), own if mx is None else float(curves.value(mx, t)))
EPILOGUE = "\nvoid main() { fragColor = effect(uv_); }\n"
# v = 0 is the first row of the picture (its top), both for what is read and what is written
VERTEX = """#version 330
in vec2 pos;
out vec2 uv_;
void main() { uv_ = pos * 0.5 + 0.5; gl_Position = vec4(pos, 0.0, 1.0); }
"""
GLSL_TYPES = {"float": "float", "int": "int", "bool": "bool", "color": "vec4", "vec2": "vec2", "vec3": "vec3",
              "menu": "int", "curve": "float", "gradient": "vec4"}


def shader_source(d, sampled=()):
    """The fragment shader of filter d; sampled: its colour and number parameters that read a
    picture."""
    decl = "\n".join((f"uniform float {p.name}_p[{GRADIENT_N}];\nuniform vec4 {p.name}_c[{GRADIENT_N}];\nuniform int {p.name}_n;"
                      if p.type == "gradient" else
                      f"uniform {GLSL_TYPES[p.type]} {p.name}" + (f"[{CURVE_N}]" if p.type == "curve" else "") + ";")
                     for p in d.params if p.name not in sampled)
    kinds = {p.name: SAMPLED if p.type == "color" else SAMPLED_NUMBER for p in d.params}
    for name, _label in d.inputs:
        decl += (f"\nuniform sampler2D inp_{name}_;\nuniform bool inp_{name}_on_;\n"
                 f"bool has_input_{name}() {{ return inp_{name}_on_; }}\n"
                 f"vec4 input_{name}(vec2 uv) {{ return texture(inp_{name}_, clamp(uv, 0.0, 1.0)); }}")
    return PRELUDE % {"params": decl, "sampled": "\n".join(kinds[n] % {"n": n} for n in sampled)} + d.code + EPILOGUE


def use_gles():
    """Whether filters run on OpenGL ES (gles.py): on Android, which has no desktop OpenGL and no moderngl,
    or with KIASECUT_GLES=1 (how it is tried on a PC)."""
    return sys.platform == "android" or os.environ.get("KIASECUT_GLES") == "1"


def make_context():
    """(moderngl or gles, a hidden OpenGL 3.3 / ES 3 context of this thread); FilterError when there is none."""
    if use_gles():
        from . import gles
        try:
            return gles, gles.create_standalone_context()
        except Exception as exc:
            raise FilterError(f"無法建立 OpenGL ES（{exc}）") from exc
    try:
        import moderngl
    except ImportError as exc:
        raise FilterError("濾鏡需要 moderngl：pip install moderngl") from exc
    try:
        return moderngl, moderngl.create_standalone_context()
    except Exception:
        try:
            return moderngl, moderngl.create_standalone_context(backend="egl")
        except Exception as exc:
            raise FilterError(f"無法建立 OpenGL（{exc}）") from exc


class Engine:
    """Runs filters on the GPU (any OpenGL 3.3 context; a hidden one is made, or the GPU
    compositor's own is shared: glrender.py)."""

    def __init__(self, mgl=None, ctx=None):
        if ctx is None:
            mgl, ctx = make_context()
        self.mgl, self.ctx = mgl, ctx
        quad = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="f4")
        self.quad = self.ctx.buffer(quad.tobytes())
        self.programs = {}
        self.targets = {}            # (w, h) -> [(texture, fbo)] x 3
        self.mid_targets = {}        # (w, h) -> [(texture, fbo)] x 2, 16-bit floats (@precision float)
        self.level_targets = {}      # (filter key, pass, w, h) -> (texture, fbo): a pass of @levels (16-bit floats, kept)

    def _program(self, d, sampled=()):
        key = (d.key(), sampled)
        prog = self.programs.get(key)
        if prog is None:
            if d.error:
                raise FilterError(d.error)
            if len(d.code) > BIG and not use_gles():          # (gles.py's calls already let go of Python's lock)
                with self.ctx:
                    precompile(shader_source(d, sampled))
            try:
                prog = self.ctx.program(vertex_shader=VERTEX, fragment_shader=shader_source(d, sampled))
            except Exception as exc:
                raise FilterError(f"{d.name}：{exc}") from exc
            vao = self.ctx.vertex_array(prog, [(self.quad, "2f", "pos")])
            if len(self.programs) > 64:
                self.programs.clear()
            self.programs[key] = prog = (prog, vao)
        return prog

    def blank_texture(self):
        """A 1 x 1 transparent texture: what an @input nothing was given reads."""
        t = getattr(self, "_blank", None)
        if t is None:
            t = self._blank = self.ctx.texture((1, 1), 4, bytes(4))
            t.filter = (self.mgl.NEAREST, self.mgl.NEAREST)
        return t

    def _targets(self, w, h):
        t = self.targets.get((w, h))
        if t is None:
            if len(self.targets) > 6:
                self.targets.clear()
            t = []
            for _ in range(3):              # the input can stay one of them while two take turns
                tex = self.ctx.texture((w, h), 4)
                tex.filter = (self.mgl.LINEAR, self.mgl.LINEAR)
                tex.repeat_x = tex.repeat_y = False
                t.append((tex, self.ctx.framebuffer(color_attachments=[tex])))
            self.targets[(w, h)] = t
        return t

    def _mid_targets(self, w, h):
        """Two 16-bit float targets for the passes between the first and the last of a @precision float filter."""
        t = self.mid_targets.get((w, h))
        if t is None:
            if len(self.mid_targets) > 6:
                self.mid_targets.clear()
            t = []
            for _ in range(2):
                tex = self.ctx.texture((w, h), 4, dtype="f2")
                tex.filter = (self.mgl.LINEAR, self.mgl.LINEAR)
                tex.repeat_x = tex.repeat_y = False
                t.append((tex, self.ctx.framebuffer(color_attachments=[tex])))
            self.mid_targets[(w, h)] = t
        return t

    def _level_target(self, d, i, w, h):
        key = (d.key(), i, w, h)
        t = self.level_targets.get(key)
        if t is None:
            if len(self.level_targets) > 96:
                self.level_targets.clear()
            tex = self.ctx.texture((w, h), 4, dtype="f4")
            tex.filter = (self.mgl.LINEAR, self.mgl.LINEAR)
            tex.repeat_x = tex.repeat_y = False
            t = self.level_targets[key] = (tex, self.ctx.framebuffer(color_attachments=[tex]))
        return t

    @staticmethod
    def level_size(d, i, values, w, h, canvas):
        """(w, h) pass i of a filter with @levels is drawn at: the canvas shrunk 2^level times (and 2^choice
        more for the @levels menu), never bigger than the picture it is drawn for."""
        q = 0 if d.fixed and d.fixed[i] else int(values.get(d.level_param, 0) if d.level_param else 0)
        shrink = 2 ** (d.levels[i] + q)
        return (max(1, min(w, int(canvas[0]) // shrink)), max(1, min(h, int(canvas[1]) // shrink)))

    def run(self, d, values, rgba, time=0.0, progress=0.0, frame=0, unit=1.0, sources=None):
        """Filter rgba (H x W x 4, uint8, premultiplied) with filter d. values: {param: value
        for the shader}; unit: rgba's px per canvas px (see run_tex); sources {colour param:
        (picture as such an array, map)} (see run_tex). Returns the same kind of array."""
        h, w = rgba.shape[:2]
        with self.ctx:                           # this engine's context, whatever else the thread uses
            (ta, _), _, _ = self._targets(w, h)
            ta.write(np.ascontiguousarray(rgba).tobytes())
            texs = {}
            try:
                for name, (pic, m) in (sources or {}).items():
                    tex = self.ctx.texture((pic.shape[1], pic.shape[0]), 4, np.ascontiguousarray(pic).tobytes())
                    tex.filter = (self.mgl.LINEAR, self.mgl.LINEAR)
                    tex.repeat_x = tex.repeat_y = False
                    texs[name] = (tex, m)
                out = self.run_tex(d, values, ta, w, h, time, progress, frame, unit, texs)
                data = out.read()
            finally:
                for tex, _m in texs.values():
                    tex.release()
        return np.frombuffer(data, np.uint8).reshape(h, w, 4)

    def run_tex(self, d, values, src, w, h, time=0.0, progress=0.0, frame=0, unit=1.0, sources=None, inputs=None,
                dest=None, output=0, src_on=True):
        """Filter the w x h texture src (premultiplied RGBA) on the card; returns the texture
        holding the result, one of this engine's own (valid until its next run at that size).
        unit: texture px per canvas px. The filter is told the canvas size as its resolution, so
        its pixel lengths are canvas px whatever size the picture is drawn at (a small preview,
        full screen, the export). sources {colour or number param: (texture, map)}: those read a
        picture (premultiplied), map the 3 x 3 matrix (9 numbers, by columns) from src's uv to
        the picture's (both with v = 0 at the top). inputs {@input name: texture} (w x h, premultiplied;
        a missing one reads as transparent); dest (texture, framebuffer) of w x h: the last pass is drawn
        there instead of into this engine's own targets (so the result outlives the next run); output: which of the
        filter's @output pictures is drawn (output_index)."""
        return self.run_outputs(d, values, src, w, h, [(output, dest)], time, progress, frame, unit, sources, inputs, src_on)[0]

    def run_outputs(self, d, values, src, w, h, outs, time=0.0, progress=0.0, frame=0, unit=1.0, sources=None, inputs=None,
                    src_on=True):
        """run_tex for several of the filter's @output pictures at once: outs [(output, dest)], each dest a
        (texture, framebuffer) of w x h (None: this engine's own, only for one); the textures holding the results,
        in the same order. A filter that says @shared draws the passes before its last once for all of them (as Blender's
        nodes are worked out once, whichever of their outputs are used), and an @alone output is drawn by the last
        pass alone; any other is drawn all over again for every output."""
        types = {p.name: p.type for p in d.params}
        sources = {n: v for n, v in (sources or {}).items() if types.get(n) in SOURCE_TYPES}
        prog, vao = self._program(d, tuple(sorted(sources)))
        targets = self._targets(w, h)
        unit = unit if unit > 1e-9 else 1.0
        for name, v in (("resolution", (w / unit, h / unit)), ("time", float(time)), ("progress", float(progress)),
                        ("frame", int(frame)), ("scale", 1.0)):
            if name in prog:
                prog[name].value = v
        for p in d.params:
            if p.type == "gradient" and p.name in values:
                pos, col, n = values[p.name]
                for u, v in ((p.name + "_p", np.array(pos, "f4")), (p.name + "_c", np.array(col, "f4"))):
                    if u in prog:
                        prog[u].write(v.tobytes())
                if p.name + "_n" in prog:
                    prog[p.name + "_n"].value = n
            elif p.name in prog and p.name in values:
                prog[p.name].value = values[p.name]
        if "source" in prog:
            prog["source"].value = 0
        if "original_" in prog:
            prog["original_"].value = 1
        for i, (name, (tex, m)) in enumerate(sorted(sources.items())):
            tex.use(2 + i)
            own = ((name + "_col_", tuple(values.get(name, (1.0, 1.0, 1.0, 1.0)))) if types[name] == "color"
                   else (name + "_val_", float(values.get(name, 0.0))))
            more = [] if types[name] == "color" else [
                (name + "_min_", float(values.get(name + RANGE_MIN, 0.0))),
                (name + "_max_", float(values.get(name + RANGE_MAX, values.get(name, 0.0))))]
            for u, v in ((name + "_tex_", 2 + i), (name + "_map_", tuple(float(x) for x in m)), own, *more):
                if u in prog:
                    prog[u].value = v
        for k, (name, _label) in enumerate(d.inputs):
            tex = (inputs or {}).get(name)
            if tex is None:
                tex = self.blank_texture()
            tex.use(8 + k)
            if "inp_" + name + "_" in prog:
                prog["inp_" + name + "_"].value = 8 + k
            if "inp_" + name + "_on_" in prog:
                prog["inp_" + name + "_on_"].value = (inputs or {}).get(name) is not None
        if "src_on_" in prog:
            prog["src_on_"].value = bool(src_on)
        if "extra_" in prog:
            prog["extra_"].value = 7
        self.ctx.disable(self.mgl.BLEND)
        run = (d, prog, vao, values, src, w, h, (w / unit, h / unit), targets, self._skipped(d, values))
        last = d.passes - 1
        if not (d.shared and last > 0):
            return [self._chain(run, 0, d.passes, src, [], k, dst) for k, dst in outs]
        names = [n for n, _ in d.outputs]
        read, made = None, []
        if any(names[k] not in d.alone for k, _ in outs):       # (the passes before the last, once)
            read, made = self._chain(run, 0, last, src, made, None, None, whole=False)
        results = []
        for k, dst in outs:
            alone = names[k] in d.alone
            results.append(self._chain(run, last, d.passes, src if alone else read, [] if alone else list(made), k, dst))
        return results

    @staticmethod
    def _skipped(d, values):
        """The passes of filter d that its settings (@skip) leave undrawn."""
        if not d.skips:
            return ()
        named_values = named(d, values)
        return {i for first, last, conds in d.skips if _holds(conds, named_values) for i in range(first, last + 1)}

    def _chain(self, run, first, stop, read, made, output, dest, whole=True):
        """Draw passes first .. stop - 1 of a run (see run_outputs) from picture read, the earlier passes' sizes and
        results being made [(texture, w, h)] (it is added to); output: the output_index to draw (None: leave as it was);
        dest: where the last pass of the filter goes. Returns the texture holding the result - or, with whole False,
        (that, made)."""
        d, prog, vao, values, src, w, h, canvas, targets, skip = run
        if output is not None and "output_index" in prog:
            prog["output_index"].value = int(output)
        for i in range(first, stop):
            if "pass_index" in prog:
                prog["pass_index"].value = i
            if i < len(d.levels):
                tw, th = self.level_size(d, i, values, w, h, canvas)
                if i in skip:                          # (not drawn: it keeps its place in made, and what the pass after reads)
                    made.append((None, tw, th))
                    continue
                dst_tex, dst_fbo = self._level_target(d, i, tw, th)
            elif dest is not None and i == d.passes - 1:
                tw, th = w, h
                dst_tex, dst_fbo = dest
            else:
                tw, th = w, h
                if i in skip:
                    made.append((None, tw, th))
                    continue
                pool = self._mid_targets(w, h) if d.precise and i < d.passes - 1 else targets
                dst_tex, dst_fbo = next(t for t in pool if t[0] is not read and t[0] is not src)
            sw, sh = read.size
            ex = d.extras[i] if i < len(d.extras) else None
            for name, v in (("pass_px", (float(tw), float(th))), ("src_px", (float(sw), float(sh))),
                            ("extra_px", (float(made[ex][1]), float(made[ex][2])) if ex is not None else (1.0, 1.0))):
                if name in prog:
                    prog[name].value = v
            dst_fbo.use()
            self.ctx.viewport = (0, 0, tw, th)
            read.use(0)
            src.use(1)
            if ex is not None:
                (made[ex][0] or self.blank_texture()).use(7)
            vao.render(self.mgl.TRIANGLE_STRIP)
            read = dst_tex
            made.append((dst_tex, tw, th))
        return read if whole else (read, made)

    def close(self):
        try:
            self.ctx.release()
        except Exception:
            pass


def precompile(source):
    """Compile and link VERTEX + source on this thread's current context through ctypes, which
    lets go of Python's lock while the driver works. moderngl keeps the lock, and the first
    compile of a big filter can take the driver half a minute: every thread, the window too,
    would stand still. The driver remembers what it compiled, so moderngl's own compile of the
    same source right after is quick. Does nothing when the functions cannot be found."""
    import ctypes
    try:
        import glcontext
        gl = None
        for backend in (glcontext.default_backend, lambda: glcontext.get_backend_by_name("egl")):
            try:
                gl = backend()(mode="detect", glversion=330)
                break
            except Exception:
                continue
        if gl is None:
            return
        uint, c_int = ctypes.c_uint, ctypes.c_int

        def fn(name, res, *args):
            addr = gl.load(name)
            if not addr:
                raise OSError(name)
            return ctypes.CFUNCTYPE(res, *args)(addr)
        create_shader = fn("glCreateShader", uint, uint)
        shader_source = fn("glShaderSource", None, uint, c_int, ctypes.POINTER(ctypes.c_char_p), ctypes.c_void_p)
        compile_shader = fn("glCompileShader", None, uint)
        create_program = fn("glCreateProgram", uint)
        attach = fn("glAttachShader", None, uint, uint)
        link = fn("glLinkProgram", None, uint)
        get_programiv = fn("glGetProgramiv", None, uint, uint, ctypes.POINTER(c_int))
        delete_shader = fn("glDeleteShader", None, uint)
        delete_program = fn("glDeleteProgram", None, uint)
    except Exception:
        return
    prog = create_program()
    shaders = []
    for kind, text in ((0x8B31, VERTEX), (0x8B30, source)):          # GL_VERTEX_SHADER, GL_FRAGMENT_SHADER
        sh = create_shader(kind)                                      # (stripped, as moderngl does: the same text)
        shader_source(sh, 1, (ctypes.c_char_p * 1)(text.strip().encode("utf-8")), None)
        compile_shader(sh)
        attach(prog, sh)
        shaders.append(sh)
    link(prog)
    ok = c_int(0)
    get_programiv(prog, 0x8B82, ctypes.byref(ok))                   # GL_LINK_STATUS: waits for the driver
    for sh in shaders:
        delete_shader(sh)
    delete_program(prog)


def missing():
    """Why filters cannot run on this computer (the panels show it), or None."""
    if use_gles():
        from . import gles
        return None if gles.available() else "這台裝置沒有 OpenGL ES 3，預覽和匯出都看不到效果。"
    try:
        import moderngl  # noqa: F401
    except ImportError:
        return "濾鏡引擎沒有安裝，預覽和匯出都看不到效果。請執行：python -m pip install moderngl"
    return None


def check(ref):
    """Compile a filter on its own (for the Library and tests): None, or the error text."""
    d = get(ref)
    if d.error:
        return d.error
    try:
        Engine()._program(d)
    except FilterError as exc:
        return str(exc)
    return None
