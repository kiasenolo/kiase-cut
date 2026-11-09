"""Expressions (表達式): a small JavaScript / After Effects-like language for values that follow
other values - a component's number parameter set through one (components.py), the global
parameter rack, wiggle on an ordinary property.

    input * 2 + Math.sin(time * 3)         arithmetic, Math.* and the plain names below
    input > 0.5 ? 1 : 0                    comparisons, && || !, a ? b : c
    cubicBezier(0.42, 0, 0.58, 1, input)   an eased value of 0 - 1 (CSS cubic-bezier)
    wiggle(2, 30)                          noise: 2 times a second, 30 either way

One expression, no statements. It is parsed here and never handed to Python's eval: the only
things it can reach are the names the caller gives it and the functions below, and it is cut
off when too long or too deep. Evaluation gives a float (or a bool / str / list if the
expression says so); a broken one raises ExprError, which callers answer with a value of their
own (see safe()).

Names (the caller's `env`): input, time (seconds), frame, fps, duration, ... and the
caller's own. Constants: pi, e, PI, E, Infinity, true, false.
Functions: sin cos tan asin acos atan atan2 sqrt abs floor ceil round trunc sign pow exp log
log2 log10 min max hypot, clamp(x, lo, hi), lerp(a, b, t) / mix, smoothstep(lo, hi, x),
step(edge, x), fract(x), mod(x, m) (always >= 0 for m > 0), degrees / radians, remap(x, a, b,
c, d), cubicBezier(x1, y1, x2, y2, x), random(seed), noise(x) (smooth, -1 - 1),
wiggle(freq, amp, seed = 0) (needs `time`), curve(x) (the custom curve of a 映射, 0 - 1; x itself elsewhere), len(list). Math.<fn> is the same as <fn>.
"""
import math
import re

MAX_LENGTH = 2000
MAX_DEPTH = 48


class ExprError(ValueError):
    """The expression cannot be read or worked out; the message says where."""


TOKEN = re.compile(r"""\s*(?:
    (?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<name>[A-Za-z_$一-鿿][\w$一-鿿]*)
  | (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<op>===|!==|\*\*|==|!=|<=|>=|&&|\|\||[-+*/%<>!?:,()\[\].])
)""", re.X)


def tokens(text):
    if len(text) > MAX_LENGTH:
        raise ExprError(f"表達式太長（最多 {MAX_LENGTH} 字）")
    out, pos = [], 0
    text = text.rstrip()
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if m is None or m.end() == pos:
            raise ExprError(f"第 {pos + 1} 個字讀不懂：{text[pos:pos + 1]!r}")
        pos = m.end()
        kind = m.lastgroup
        out.append((kind, m.group(kind), m.start(kind)))
    out.append(("end", "", len(text)))
    return out


class Parser:
    """A Pratt parser; the tree is tuples: ("num", v) ("str", s) ("name", n) ("un", op, a)
    ("bin", op, a, b) ("cond", c, a, b) ("call", fn name, [args]) ("index", a, i) ("list", [items])."""

    def __init__(self, text):
        self.toks = tokens(text)
        self.i = 0
        self.depth = 0

    def peek(self):
        return self.toks[self.i]

    def take(self, value=None):
        tok = self.toks[self.i]
        if value is not None and tok[1] != value:
            raise ExprError(f"第 {tok[2] + 1} 個字：要有 {value!r}，卻是 {tok[1] or '結尾'!r}")
        self.i += 1
        return tok

    def parse(self):
        node = self.ternary()
        if self.peek()[0] != "end":
            tok = self.peek()
            raise ExprError(f"第 {tok[2] + 1} 個字：多出來的 {tok[1]!r}")
        return node

    def nest(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ExprError("表達式巢狀太深")

    def ternary(self):
        self.nest()
        cond = self.binary(0)
        if self.peek()[1] == "?":
            self.take("?")
            a = self.ternary()
            self.take(":")
            b = self.ternary()
            cond = ("cond", cond, a, b)
        self.depth -= 1
        return cond

    LEVELS = (("||",), ("&&",), ("==", "!=", "===", "!=="), ("<", "<=", ">", ">="), ("+", "-"), ("*", "/", "%"))

    def binary(self, level):
        if level == len(self.LEVELS):
            return self.unary()
        node = self.binary(level + 1)
        while self.peek()[0] == "op" and self.peek()[1] in self.LEVELS[level]:
            op = self.take()[1]
            node = ("bin", op, node, self.binary(level + 1))
        return node

    def unary(self):
        tok = self.peek()
        if tok[0] == "op" and tok[1] in ("-", "+", "!"):
            self.take()
            self.nest()
            node = ("un", tok[1], self.unary())
            self.depth -= 1
            return node
        return self.power()

    def power(self):
        base = self.postfix()
        if self.peek()[1] == "**":
            self.take()
            return ("bin", "**", base, self.unary())            # (right to left; -2 ** 2 is -(2 ** 2) as in maths)
        return base

    def postfix(self):
        node = self.atom()
        while True:
            tok = self.peek()
            if tok[1] == "(" and tok[0] == "op":
                if node[0] != "name":
                    raise ExprError(f"第 {tok[2] + 1} 個字：只能呼叫函式名稱")
                self.take()
                args = []
                if self.peek()[1] != ")":
                    args.append(self.ternary())
                    while self.peek()[1] == ",":
                        self.take()
                        args.append(self.ternary())
                self.take(")")
                node = ("call", node[1], args)
            elif tok[1] == "[" and tok[0] == "op":
                self.take()
                idx = self.ternary()
                self.take("]")
                node = ("index", node, idx)
            elif tok[1] == "." and tok[0] == "op":
                self.take()
                name = self.take()
                if name[0] != "name":
                    raise ExprError(f"第 {name[2] + 1} 個字：. 後面要接名稱")
                if node == ("name", "Math"):
                    node = ("name", name[1])                        # Math.sin -> sin
                elif name[1] == "length":
                    node = ("call", "len", [node])
                else:
                    raise ExprError(f"沒有 .{name[1]}（可以用 Math.xxx、.length 和 [編號]）")
            else:
                return node

    def atom(self):
        tok = self.take()
        kind, text, pos = tok
        if kind == "num":
            return ("num", float(text))
        if kind == "str":
            return ("str", re.sub(r"\\(.)", r"\1", text[1:-1]))
        if kind == "name":
            return ("name", text)
        if text == "(":
            node = self.ternary()
            self.take(")")
            return node
        if text == "[":
            items = []
            if self.peek()[1] != "]":
                items.append(self.ternary())
                while self.peek()[1] == ",":
                    self.take()
                    items.append(self.ternary())
            self.take("]")
            return ("list", items)
        raise ExprError(f"第 {pos + 1} 個字：{text or '結尾'!r} 不該在這裡")


def parse(text):
    """The tree of expression text (ExprError when it cannot be read)."""
    if not str(text).strip():
        raise ExprError("表達式是空的")
    return Parser(str(text)).parse()


def names(tree):
    """The plain names an expression (text or tree) reads (not the functions it calls)."""
    tree = parse(tree) if isinstance(tree, str) else tree
    out = set()

    def walk(n):
        k = n[0]
        if k == "name":
            out.add(n[1])
        elif k in ("un",):
            walk(n[2])
        elif k == "bin":
            walk(n[2])
            walk(n[3])
        elif k == "cond":
            for x in n[1:]:
                walk(x)
        elif k == "call":
            for x in n[2]:
                walk(x)
        elif k == "index":
            walk(n[1])
            walk(n[2])
        elif k == "list":
            for x in n[1]:
                walk(x)
    walk(tree)
    return out - set(CONSTANTS)


# -- the functions ----------------------------------------------------------------------------------
def _bezier_y(x1, y1, x2, y2, x):
    """CSS cubic-bezier(x1, y1, x2, y2) at progress x (0 - 1): the eased value."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(40):
        s = (lo + hi) / 2
        bx = 3 * (1 - s) ** 2 * s * x1 + 3 * (1 - s) * s * s * x2 + s ** 3
        lo, hi = (s, hi) if bx < x else (lo, s)
    s = (lo + hi) / 2
    return 3 * (1 - s) ** 2 * s * y1 + 3 * (1 - s) * s * s * y2 + s ** 3


def _hash(n):
    """A repeatable number 0 - 1 for an integer n."""
    n = (int(n) * 0x27d4eb2d) & 0xffffffff
    n ^= n >> 15
    n = (n * 0x85ebca6b) & 0xffffffff
    n ^= n >> 13
    n = (n * 0xc2b2ae35) & 0xffffffff
    n ^= n >> 16
    return n / 0xffffffff


def _smooth(f):
    return f * f * f * (f * (f * 6 - 15) + 10)


def noise(x, seed=0):
    """Smooth noise -1 - 1: the same x (and seed) always gives the same value."""
    x = float(x)
    i = math.floor(x)
    f = x - i
    a, b = _hash(i * 7919 + seed * 104729) * 2 - 1, _hash((i + 1) * 7919 + seed * 104729) * 2 - 1
    return a + (b - a) * _smooth(f)


def _wiggle(env, freq, amp, seed=0):
    """AE's wiggle: noise at `freq` per second, `amp` either way (octaves 1)."""
    return noise(float(env.get("time", 0.0)) * float(freq), int(seed)) * float(amp)


def _curve(env, x):
    """curve(x): the custom curve of the 映射 the expression belongs to (映射 > 自訂曲線), x from 0 to 1; x itself where there is none."""
    keys = env.get("__curve__")
    if keys is None:
        return float(x)
    from . import curves
    return curves.unit_value(keys, x)


def _mod(x, m):
    return x % m if m else 0.0


def _clamp(x, lo, hi):
    return min(max(x, lo), hi) if lo <= hi else min(max(x, hi), lo)


def _smoothstep(lo, hi, x):
    if lo == hi:
        return 0.0 if x < lo else 1.0
    t = _clamp((x - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _remap(x, a, b, c, d):
    return c if a == b else c + (x - a) / (b - a) * (d - c)


def _sign(x):
    return (x > 0) - (x < 0) + 0.0


def _round(x):
    return math.floor(x + 0.5)                                      # (JS rounds halves up)


def _pow(a, b):
    try:
        r = math.pow(a, b)
    except (OverflowError, ValueError, ZeroDivisionError):
        return math.nan
    return r


def _log(x):
    return math.log(x) if x > 0 else (-math.inf if x == 0 else math.nan)


def _sqrt(x):
    return math.sqrt(x) if x >= 0 else math.nan


def _guard(fn):
    def call(*a):
        try:
            return fn(*a)
        except (ValueError, OverflowError, ZeroDivisionError):
            return math.nan
    return call


FUNCTIONS = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": _guard(math.asin), "acos": _guard(math.acos),
    "atan": math.atan, "atan2": math.atan2, "sqrt": _sqrt, "abs": abs, "floor": math.floor, "ceil": math.ceil,
    "round": _round, "trunc": math.trunc, "sign": _sign, "pow": _pow, "exp": _guard(math.exp), "log": _log,
    "log2": _guard(math.log2), "log10": _guard(math.log10), "hypot": math.hypot,
    "min": min, "max": max, "clamp": _clamp, "lerp": lambda a, b, t: a + (b - a) * t,
    "smoothstep": _smoothstep, "step": lambda edge, x: 1.0 if x >= edge else 0.0,
    "fract": lambda x: x - math.floor(x), "mod": _mod, "degrees": math.degrees, "radians": math.radians,
    "remap": _remap, "cubicBezier": _bezier_y, "noise": noise, "random": lambda seed=0: _hash(int(seed) * 31 + 17),
    "len": lambda a: float(len(a)) if isinstance(a, (list, str)) else 0.0,
}
FUNCTIONS["mix"] = FUNCTIONS["lerp"]
NEEDS_ENV = {"wiggle": _wiggle, "curve": _curve}                                     # (functions that read the caller's names)
CONSTANTS = {"pi": math.pi, "PI": math.pi, "e": math.e, "E": math.e, "Infinity": math.inf, "NaN": math.nan,
             "true": True, "false": False, "SQRT2": math.sqrt(2), "TAU": math.tau}


def _num(v):
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    raise ExprError("這裡要的是數字")


def _truthy(v):
    return bool(v) and not (isinstance(v, float) and math.isnan(v))


def _div(a, b):
    a, b = _num(a), _num(b)
    if b == 0:
        return math.nan if a == 0 or math.isnan(a) else math.copysign(math.inf, a)
    return a / b


def _js_mod(a, b):
    a, b = _num(a), _num(b)
    return math.nan if b == 0 or math.isinf(a) else math.fmod(a, b)


def _add(a, b):
    if isinstance(a, str) or isinstance(b, str):
        return _text(a) + _text(b)
    if isinstance(a, list) and isinstance(b, list):
        return [_num(x) + _num(y) for x, y in zip(a, b)]
    return _num(a) + _num(b)


def _text(v):
    if isinstance(v, float) and abs(v) < 1e15 and v == int(v):
        return str(int(v))
    return str(v)


BINARY = {
    "+": _add,
    "-": lambda a, b: _num(a) - _num(b),
    "*": lambda a, b: _num(a) * _num(b),
    "/": _div,
    "%": _js_mod,
    "**": lambda a, b: _pow(_num(a), _num(b)),
    "<": lambda a, b: _num(a) < _num(b),
    "<=": lambda a, b: _num(a) <= _num(b),
    ">": lambda a, b: _num(a) > _num(b),
    ">=": lambda a, b: _num(a) >= _num(b),
    "==": lambda a, b: a == b, "===": lambda a, b: a == b,
    "!=": lambda a, b: a != b, "!==": lambda a, b: a != b,
}


def run(tree, env):
    """The value of a parsed expression with the names in env (a dict of numbers / str / list)."""
    k = tree[0]
    if k == "num" or k == "str":
        return tree[1]
    if k == "name":
        n = tree[1]
        if n in env:
            return env[n]
        if n in CONSTANTS:
            return CONSTANTS[n]
        if n in FUNCTIONS or n in NEEDS_ENV:
            raise ExprError(f"{n} 是函式，要寫成 {n}(…)")
        raise ExprError(f"沒有叫 {n} 的值")
    if k == "un":
        v = run(tree[2], env)
        return not _truthy(v) if tree[1] == "!" else (-_num(v) if tree[1] == "-" else _num(v))
    if k == "bin":
        op = tree[1]
        if op == "&&":
            a = run(tree[2], env)
            return run(tree[3], env) if _truthy(a) else a
        if op == "||":
            a = run(tree[2], env)
            return a if _truthy(a) else run(tree[3], env)
        return BINARY[op](run(tree[2], env), run(tree[3], env))
    if k == "cond":
        return run(tree[2], env) if _truthy(run(tree[1], env)) else run(tree[3], env)
    if k == "list":
        return [run(x, env) for x in tree[1]]
    if k == "index":
        a, i = run(tree[1], env), run(tree[2], env)
        if not isinstance(a, list):
            raise ExprError("[編號] 只能用在清單上")
        i = _num(i)
        return a[int(i)] if 0 <= i < len(a) else 0.0             # (NaN and Infinity are no place in it)
    if k == "call":
        name, args = tree[1], [run(x, env) for x in tree[2]]
        try:
            if name in NEEDS_ENV:
                return NEEDS_ENV[name](env, *args)
            fn = FUNCTIONS.get(name)
            if fn is None:
                raise ExprError(f"沒有叫 {name} 的函式")
            if name in ("min", "max") and len(args) == 1 and isinstance(args[0], list):
                args = args[0]
            if name not in ("len",):
                args = [_num(a) for a in args]
            return fn(*args)
        except ExprError:
            raise
        except TypeError:
            raise ExprError(f"{name}() 的引數數量不對") from None
        except (ValueError, OverflowError, ZeroDivisionError):   # sin(Infinity), floor(1 / 0), noise(NaN): not a number, as in JavaScript
            return math.nan
    raise ExprError("表達式有讀不懂的東西")


def evaluate(text, env=None):
    """The value of expression text with the names of env."""
    return run(compile_cached(str(text)), env or {})


def number(text, env=None, default=0.0):
    """A finite float from expression text (ExprError when it breaks or is not a number)."""
    v = evaluate(text, env)
    if isinstance(v, bool):
        return float(v)
    if not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ExprError("結果不是有限的數字")
    return float(v)


def safe(text, env=None, default=0.0):
    """number(), but the default when the expression is broken or gives no usable number."""
    try:
        return number(text, env)
    except (ExprError, RecursionError):
        return default


def check(text):
    """None when text is a readable expression, else the reason (for the editor to show)."""
    try:
        parse(text)
    except ExprError as e:
        return str(e)
    except RecursionError:
        return "表達式巢狀太深"
    return None


def compile_cached(text, _cache={}):
    """parse() remembered: the renderers work the same expression out once per frame."""
    tree = _cache.get(text)
    if tree is None:
        if len(_cache) > 512:
            _cache.clear()
        tree = _cache[text] = parse(text)
    return tree
