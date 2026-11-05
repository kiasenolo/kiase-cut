"""Fusing nodes: a chain / tree of pointwise nodes drawn in ONE pass instead of one pass each.

A pointwise filter reads its pictures only at the pixel it draws (src(uv), input_x(uv) with the very uv it was given), so the
filter that feeds it can be called right there instead of drawing its picture first: a node that is not the last of the group
is never written to a texture or read back. On the card every node of a graph costs a full read and write of a picture (about
1.4 ms at 1080p, memory bound), a fused group costs one.

can_fuse(d) says whether a filter is pointwise (from its code); build() writes the one filter of a group: every node's code, its
parameters and functions renamed n<i>_..., glued together; its pictures from outside are the @inputs e0, e1...
The in-between values stay 32-bit floats (the unfused nodes round them to 16-bit), so a result may differ in the last bit."""
import copy
import hashlib
import re

from . import fx

import os

enabled = os.environ.get("KIASECUT_NOFUSE") != "1"                # (KIASECUT_NOFUSE=1: every node is drawn on its own, to compare)
bad = set()                                         # keys of fused filters that did not compile: those groups are drawn node by node
MAX_NODES = 16                                      # nodes in a group (a longer chain is cut into groups)
MAX_EXTERNAL = 6                                    # pictures from outside a group (a texture unit each)

_COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_EFFECT = re.compile(r"\bvec4\s+effect\s*\(\s*vec2\s+(\w+)\s*\)\s*\{")
_CALL = re.compile(r"(?<![\w.])(src|input_\w+)\s*\(")
_FORBIDDEN = re.compile(r"(?<![\w.])(original|extra|texture|textureLod|texelFetch|textureSize|pass_index|pass_px|src_px|extra_px|"
                        r"source|original_|extra_|fragColor)\b|^\s*#|\bstruct\b|\bdiscard\b|\bin\s+vec|\bout\s+vec", re.M)
_DECL = re.compile(r"(?:^|[;}])\s*(?:const\s+)?(?:float|int|bool|uint|void|vec[234]|ivec[234]|bvec[234]|mat[234])\s+(\w+)\s*(?=[(\[=;,])")


def strip(code):
    return _COMMENTS.sub(" ", code)


def _match(text, i, open_, close):
    """Index just past the bracket that closes the one at text[i]."""
    depth = 0
    for j in range(i, len(text)):
        if text[j] == open_:
            depth += 1
        elif text[j] == close:
            depth -= 1
            if depth == 0:
                return j + 1
    return -1


def _top_level(text):
    """The text with everything inside braces and parentheses taken out (the brackets stay, empty): what is declared at the top
    of a file is left."""
    out, depth = [], 0
    for ch in text:
        if ch in "{(":
            if depth == 0:
                out.append(ch)
            depth += 1
        elif ch in "})":
            depth -= 1
            if depth == 0:
                out.append(ch)
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def analyse(d):
    """None when filter d cannot be fused, else (the effect's uv name, the names it declares at the top of its code), kept on d."""
    got = getattr(d, "_fuse", False)
    if got is not False:
        return got
    d._fuse = None
    if d.error or d.passes != 1 or d.levels or d.extras or d.shared or d.skips or d.precise:
        return None
    code = strip(d.code)
    if _FORBIDDEN.search(code):
        return None
    m = _EFFECT.search(code)
    if m is None:
        return None
    uv = m.group(1)
    start, end = m.end() - 1, _match(code, m.end() - 1, "{", "}")
    if end < 0:
        return None
    body = code[start:end]
    if re.search(r"(?<![\w.])%s(\.\w+)?\s*[-+*/]?=(?!=)" % re.escape(uv), body):          # (uv itself must stay the pixel's)
        return None
    for c in _CALL.finditer(code):                                  # (every picture is read at uv, inside effect())
        if not (start <= c.start() < end):
            return None
        close = _match(code, c.end() - 1, "(", ")")
        if close < 0 or code[c.end():close - 1].strip() != uv:
            return None
    top = _top_level(code)
    if re.search(r"(?:float|int|bool|uint|vec[234]|ivec[234]|mat[234])\s+\w+\s*(?:\[\s*\w*\s*\])?\s*,", top):         # (float a, b; is not read)
        return None
    names = set(_DECL.findall(top))
    names.discard("main")
    d._fuse = (uv, names)
    return d._fuse


def can_fuse(d):
    return analyse(d) is not None


def _renames(d, i, names):
    """{old name: new name} for node i of a group: its parameters, the pictures it reads and what it declares."""
    pre = f"n{i}_"
    r = {n: pre + n for n in names}
    for p in d.params:
        r[p.name] = pre + p.name
        if p.type == "gradient":
            for suffix in ("_p", "_c", "_n"):
                r[p.name + suffix] = pre + p.name + suffix
    for n in ("effect", "src", "has_src", "output_index"):
        r[n] = pre + n
    for name, _label in d.inputs:
        r["input_" + name] = pre + "input_" + name
        r["has_input_" + name] = pre + "has_input_" + name
    return r


def _rename(code, r):
    if not r:
        return code
    pattern = re.compile(r"(?<![\w.])(" + "|".join(sorted(map(re.escape, r), key=len, reverse=True)) + r")\b")
    return pattern.sub(lambda m: r[m.group(1)], code)


_built = {}


def build(members):
    """The one filter that draws a group. members: [(filter def, wiring, out)] in the order they are drawn, the last one the result;
    out: which of its outputs (output_index) it gives; wiring {"src" / input name: ("node", index of an earlier member) / ("ext", k) (the k-th picture from outside, a missing one
    is ("none", 0))}. Returns (a FilterDef, [(member, parameter name, name in the fused filter)]) - or None when the shader
    cannot be written."""
    key = hashlib.sha1(repr([(d.key(), sorted(w.items()), o) for d, w, o in members]).encode()).hexdigest()
    got = _built.get(key)
    if got is not None:
        return got
    code, params, names = [], [], []
    ext = 0
    for i, (d, wiring, out) in enumerate(members):
        uv, declared = analyse(d)
        r = _renames(d, i, declared)

        def read(socket):
            kind, k = wiring.get(socket, ("none", 0))
            return f"n{k}_effect(uv)" if kind == "node" else f"input_e{k}(uv)" if kind == "ext" else "vec4(0.0)"
        glue = [f"const int n{i}_output_index = {int(out)};",
                f"vec4 n{i}_src(vec2 uv) {{ return {read('src')}; }}",
                f"bool n{i}_has_src() {{ return {'true' if wiring.get('src', ('none', 0))[0] != 'none' else 'false'}; }}"]
        for name, _label in d.inputs:
            glue.append(f"vec4 n{i}_input_{name}(vec2 uv) {{ return {read(name)}; }}")
            glue.append(f"bool n{i}_has_input_{name}() {{ return {'true' if wiring.get(name, ('none', 0))[0] != 'none' else 'false'}; }}")
        code.append("\n".join(glue) + "\n" + _rename(strip(d.code), r))
        for p in d.params:
            q = copy.copy(p)
            q.name = f"n{i}_{p.name}"
            q.show = q.enable = []
            params.append(q)
            names.append((i, p.name, q.name))
    last = len(members) - 1
    code.append(f"vec4 effect(vec2 uv) {{ return n{last}_effect(uv); }}")
    fused = fx.FilterDef("fused:" + key[:12], "fused", "\n".join(code), params)
    n_ext = 1 + max([k for _d, w, _o in members for kind, k in w.values() if kind == "ext"] or [-1])
    fused.inputs = [(f"e{k}", "") for k in range(n_ext)]
    got = _built[key] = (fused, names)
    if len(_built) > 256:
        _built.clear()
    return got
