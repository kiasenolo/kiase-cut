"""Filters: GLSL fragment shaders (format in filters/FORMAT.md) run with moderngl.

A filter file has a header of `// @name value` lines and an `effect(vec2 uv)` function; the
program adds the version line, the uniforms and main(). The built-in filters in filters/
use the same format as the user's (<Library>/filters/*.glsl).

Engine().run(def, params, rgba, ...) filters a premultiplied RGBA8 picture (numpy, H x W x 4)
and returns the result. OpenGL contexts belong to the thread that made them, so every thread
that filters (the preview worker, the export) makes its own Engine.
"""
import glob
import hashlib
import os
import re
import shlex

import numpy as np

from . import curves

PKG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "filters")
DOC_PATH = os.path.join(PKG, "FORMAT.md")
TEMPLATE_PATH = os.path.join(PKG, "_template.glsl")
BUILTIN = "builtin:"
MAX_PASSES = 8
TYPES = ("float", "int", "bool", "color", "vec2", "vec3")
RESERVED = {"source", "resolution", "time", "progress", "frame", "scale", "pass_index", "src", "effect",
            "unpremultiply", "premultiply", "rand", "uv_", "fragColor", "main"}


class FilterError(Exception):
    pass


class Param:
    def __init__(self, name, type_, default, lo=-1000.0, hi=1000.0, label=None):
        self.name, self.type, self.default = name, type_, default
        self.lo, self.hi, self.label = lo, hi, label or name

    def __repr__(self):
        return f"Param({self.name}, {self.type}, {self.default})"


class FilterDef:
    def __init__(self, ref, name, code, params=(), category="", description="", passes=1, error=None):
        self.ref, self.name, self.code = ref, name, code
        self.params, self.category, self.description = list(params), category, description
        self.passes, self.error = passes, error

    def key(self):
        return hashlib.sha1((self.code + "|" + str(self.passes) + "|" +
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
    else:
        n = 2 if typ == "vec2" else 3
        d = [float(x) for x in default.split(",")]
        if len(d) != n:
            raise ValueError(f"{typ} 的預設值要寫成 {','.join('xyz'[:n])}")
    return Param(name, typ, d, lo, hi, label)


def parse(text, ref, fallback_name="濾鏡"):
    """FilterDef of a filter file's text. A file with mistakes still gives a FilterDef, with
    `error` set (the panel shows it) so that one bad file never breaks the program."""
    head = {}
    params, error = [], None
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
                params.append(p)
            elif key in ("filter", "category", "description"):
                head[key] = rest
            elif key == "passes":
                head["passes"] = max(1, min(MAX_PASSES, int(rest)))
        except ValueError as exc:
            error = error or f"{line.strip()}\n{exc}"
    if "effect" not in text:
        error = error or "找不到 effect() 函式"
    return FilterDef(ref, head.get("filter") or fallback_name, text, params, head.get("category", ""),
                     head.get("description", ""), head.get("passes", 1), error)


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


def get(ref):
    """FilterDef of "builtin:name" or of a filter file's path."""
    if ref.startswith(BUILTIN):
        name = ref[len(BUILTIN):]
        return _file_def(os.path.join(PKG, name + ".glsl"), ref, name)
    return _file_def(ref, ref, os.path.splitext(os.path.basename(ref))[0])


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
    """A new effect entry for a clip: {id, filter, enabled, params}."""
    return {"id": effect_id, "filter": ref, "enabled": True, "params": default_params(get(ref))}


def label(ref):
    return get(ref).name


def uniform_value(p, stored, t):
    """The value to give the shader for parameter p (stored: a number / list / curve)."""
    v = curves.value(stored if stored is not None else p.default, t)
    if p.type == "float":
        return float(v)
    if p.type == "int":
        return int(round(v))
    if p.type == "bool":
        return bool(v)
    if p.type == "color":
        v = list(v) + [1.0] * (4 - len(v))
        return tuple(float(x) for x in v[:4])
    n = 3 if p.type == "vec3" else 2
    v = list(v) + [0.0] * (n - len(v))
    return tuple(float(x) for x in v[:n])


# -- the shader -------------------------------------------------------------------------------------
PRELUDE = """#version 330
uniform sampler2D source;
uniform vec2 resolution;
uniform float time;
uniform float progress;
uniform int frame;
uniform float scale;
uniform int pass_index;
%(params)s
in vec2 uv_;
out vec4 fragColor;
vec4 src(vec2 uv) { return texture(source, clamp(uv, 0.0, 1.0)); }
vec4 unpremultiply(vec4 c) { return c.a > 0.0 ? vec4(c.rgb / c.a, c.a) : vec4(0.0); }
vec4 premultiply(vec4 c) { return vec4(c.rgb * c.a, c.a); }
float rand(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
#line 1
"""
EPILOGUE = "\nvoid main() { fragColor = effect(uv_); }\n"
# v = 0 is the first row of the picture (its top), both for what is read and what is written
VERTEX = """#version 330
in vec2 pos;
out vec2 uv_;
void main() { uv_ = pos * 0.5 + 0.5; gl_Position = vec4(pos, 0.0, 1.0); }
"""
GLSL_TYPES = {"float": "float", "int": "int", "bool": "bool", "color": "vec4", "vec2": "vec2", "vec3": "vec3"}


def shader_source(d):
    decl = "\n".join(f"uniform {GLSL_TYPES[p.type]} {p.name};" for p in d.params)
    return PRELUDE % {"params": decl} + d.code + EPILOGUE


class Engine:
    """Runs filters on the GPU (any OpenGL 3.3 context; a hidden one is made)."""

    def __init__(self):
        try:
            import moderngl
        except ImportError as exc:
            raise FilterError("濾鏡需要 moderngl：pip install moderngl") from exc
        self.mgl = moderngl
        try:
            self.ctx = moderngl.create_standalone_context()
        except Exception:
            try:
                self.ctx = moderngl.create_standalone_context(backend="egl")
            except Exception as exc:
                raise FilterError(f"無法建立 OpenGL（{exc}）") from exc
        quad = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="f4")
        self.quad = self.ctx.buffer(quad.tobytes())
        self.programs = {}
        self.targets = {}            # (w, h) -> [(texture, fbo)] x 2

    def _program(self, d):
        key = d.key()
        prog = self.programs.get(key)
        if prog is None:
            if d.error:
                raise FilterError(d.error)
            try:
                prog = self.ctx.program(vertex_shader=VERTEX, fragment_shader=shader_source(d))
            except Exception as exc:
                raise FilterError(f"{d.name}：{exc}") from exc
            vao = self.ctx.vertex_array(prog, [(self.quad, "2f", "pos")])
            if len(self.programs) > 64:
                self.programs.clear()
            self.programs[key] = prog = (prog, vao)
        return prog

    def _targets(self, w, h):
        t = self.targets.get((w, h))
        if t is None:
            if len(self.targets) > 6:
                self.targets.clear()
            t = []
            for _ in range(2):
                tex = self.ctx.texture((w, h), 4)
                tex.filter = (self.mgl.LINEAR, self.mgl.LINEAR)
                tex.repeat_x = tex.repeat_y = False
                t.append((tex, self.ctx.framebuffer(color_attachments=[tex])))
            self.targets[(w, h)] = t
        return t

    def run(self, d, values, rgba, time=0.0, progress=0.0, frame=0):
        """Filter rgba (H x W x 4, uint8, premultiplied) with filter d. values: {param: value
        for the shader}. Returns the same kind of array."""
        h, w = rgba.shape[:2]
        prog, vao = self._program(d)
        (ta, fa), (tb, fb) = self._targets(w, h)
        ta.write(np.ascontiguousarray(rgba).tobytes())
        for name, v in (("resolution", (float(w), float(h))), ("time", float(time)), ("progress", float(progress)),
                        ("frame", int(frame)), ("scale", h / 1080.0)):
            if name in prog:
                prog[name].value = v
        for p in d.params:
            if p.name in prog and p.name in values:
                prog[p.name].value = values[p.name]
        if "source" in prog:
            prog["source"].value = 0
        src_tex, dst = ta, (tb, fb)
        out_fbo = fb
        for i in range(d.passes):
            if "pass_index" in prog:
                prog["pass_index"].value = i
            dst_tex, dst_fbo = (tb, fb) if i % 2 == 0 else (ta, fa)
            src_tex = ta if i % 2 == 0 else tb
            dst_fbo.use()
            self.ctx.viewport = (0, 0, w, h)
            src_tex.use(0)
            vao.render(self.mgl.TRIANGLE_STRIP)
            out_fbo = dst_fbo
        data = out_fbo.read(components=4)
        return np.frombuffer(data, np.uint8).reshape(h, w, 4)

    def close(self):
        try:
            self.ctx.release()
        except Exception:
            pass


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
