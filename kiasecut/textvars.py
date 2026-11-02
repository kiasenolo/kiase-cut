"""文字變數: values a text shows that keyframes can change - text["vars"] [{name, kind, value, …}],
written into the words as {name}.

kind      value (keyframes: curves.py)          shown as
number    a whole number (eases, rounded)       12
float     a number (eases)                      3.14 - `decimals` places (definition), or
                                                {name:.Nf} for this place only
color     [r, g, b] 0 - 1 (eases)               #rrggbb (typed as HEX)
time      seconds (eases)                       by `format` (definition), or {name:format}:
                                                hh mm ss: hours, minutes, seconds (two digits;
                                                h m s: as many as they need), ff: frames (at the
                                                project's rate), SSS / SS / S: thousandths,
                                                hundredths, tenths; anything else as written
text      words (held to the next keyframe)     as typed

\\{ shows a { as it is (so does a {name} with no such variable)."""
import re

from . import curves

KINDS = {"number": "數字", "float": "浮點數", "color": "顏色", "time": "時間", "text": "文字"}
DEFAULTS = {"number": 0, "float": 0.0, "color": [1.0, 1.0, 1.0], "time": 0.0, "text": ""}
NAME = re.compile(r"^[A-Za-z_一-鿿][\w一-鿿]*$")
REF = re.compile(r"\\\{|\{([A-Za-z_一-鿿][\w一-鿿]*)(?::([^{}]*))?\}")
TIME_TOKENS = re.compile(r"hh|h|mm|m|ss|s|ff|SSS|SS|S")


def default_value(kind):
    v = DEFAULTS[kind]
    return list(v) if isinstance(v, list) else v


def variables(tx):
    return tx.get("vars") or []


def find(tx, name):
    return next((v for v in variables(tx) if v["name"] == name), None)


def hex_of(rgb):
    return "#" + "".join(f"{int(round(min(1.0, max(0.0, x)) * 255)):02x}" for x in list(rgb)[:3])


def parse_hex(text):
    """[r, g, b] of #rrggbb (or rrggbb, #rgb); ValueError otherwise."""
    t = text.strip().lstrip("#")
    if len(t) == 3:
        t = "".join(ch * 2 for ch in t)
    if len(t) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in t):
        raise ValueError("顏色要寫成 #rrggbb")
    return [int(t[i:i + 2], 16) / 255 for i in (0, 2, 4)]


def format_time(seconds, fmt, fps=30.0):
    """seconds shown by fmt (the module's time tokens)."""
    neg = seconds < 0
    s = abs(seconds)
    whole = int(s)
    parts = {"h": whole // 3600, "m": whole // 60 % 60, "s": whole % 60}
    has_h = "h" in fmt
    has_m = "m" in fmt
    if not has_h:
        parts["m"] = whole // 60 if has_m else 0
    if not has_m and not has_h:
        parts["s"] = whole
    frac = s - whole

    def tok(m):
        t = m.group(0)
        if t in ("hh", "mm", "ss"):
            return f"{parts[t[0]]:02d}"
        if t in ("h", "m", "s"):
            return str(parts[t])
        if t == "ff":
            return f"{int(frac * fps + 1e-6):02d}"
        n = len(t)                                       # S / SS / SSS
        return f"{int(frac * 10 ** n + 1e-6):0{n}d}"
    return ("-" if neg else "") + TIME_TOKENS.sub(tok, fmt)


def shown(v, t, spec=None, fps=30.0):
    """Variable v's value at clip time t as words (spec: what follows its name's colon)."""
    kind = v.get("kind", "text")
    val = curves.value(v.get("value", default_value(kind)), t)
    if kind == "number":
        return str(int(round(float(val))))
    if kind == "float":
        m = re.fullmatch(r"\.?(\d+)f?", spec.strip()) if spec else None
        places = int(m.group(1)) if m else int(v.get("decimals", 2))
        return f"{float(val):.{max(0, min(10, places))}f}"
    if kind == "color":
        return hex_of(val)
    if kind == "time":
        return format_time(float(val), spec if spec else v.get("format") or "mm:ss", fps)
    return str(val)


def expand(tx, t, fps=30.0):
    """A text's words at clip time t with its variables written in."""
    text = tx.get("content", "")
    vs = {v["name"]: v for v in variables(tx)}
    if not vs and "\\{" not in text:
        return text

    def sub(m):
        if m.group(0) == "\\{":
            return "{"
        v = vs.get(m.group(1))
        return m.group(0) if v is None else shown(v, t, m.group(2), fps)
    return REF.sub(sub, text)


def animated(tx):
    """Whether its words change along the clip (a variable with keyframes)."""
    return any(curves.is_animated(v.get("value")) for v in variables(tx))


def spec_at(tx, t, fields, fps=30.0):
    """A text's spec at clip time t (curves.static of fields) with its variables written into its
    words - what is drawn."""
    spec = curves.static(tx, t, fields)
    if tx.get("vars") or "\\{" in tx.get("content", ""):
        spec["content"] = expand(tx, t, fps)
        spec.pop("vars", None)
    return spec
