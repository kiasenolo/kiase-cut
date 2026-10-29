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
import time

import numpy as np

from . import curves

PKG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "filters")
DOC_PATH = os.path.join(PKG, "FORMAT.md")
TEMPLATE_PATH = os.path.join(PKG, "_template.glsl")
BUILTIN = "builtin:"
MAX_PASSES = 8
BIG = 40000                      # a filter this long is first compiled with Python's lock let go (precompile())
TYPES = ("float", "int", "bool", "color", "vec2", "vec3", "menu")
RESERVED = {"source", "original_", "resolution", "time", "progress", "frame", "scale", "pass_index", "src",
            "original", "effect", "unpremultiply", "premultiply", "rand", "uv_", "fragColor", "main"}


class FilterError(Exception):
    pass


class Param:
    def __init__(self, name, type_, default, lo=-1000.0, hi=1000.0, label=None, items=()):
        self.name, self.type, self.default = name, type_, default
        self.lo, self.hi, self.label = lo, hi, label or name
        self.items = list(items)                 # a menu's choices, in order (the shader gets the index)

    def __repr__(self):
        return f"Param({self.name}, {self.type}, {self.default})"


class FilterDef:
    def __init__(self, ref, name, code, params=(), category="", description="", passes=1, error=None, precise=False):
        self.ref, self.name, self.code = ref, name, code
        self.precise = precise                   # the passes before the last one keep 16-bit floats, not 8 bits
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
    else:
        n = 2 if typ == "vec2" else 3
        d = [float(x) for x in default.split(",")]
        if len(d) != n:
            raise ValueError(f"{typ} 的預設值要寫成 {','.join('xyz'[:n])}")
    return Param(name, typ, d, lo, hi, label)


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
            elif key == "precision":
                if rest.lower() not in ("float", "8bit"):
                    raise ValueError("@precision 要寫 float 或 8bit")
                head["precise"] = rest.lower() == "float"
        except ValueError as exc:
            error = error or f"{line.strip()}\n{exc}"
    if "effect" not in text:
        error = error or "找不到 effect() 函式"
    return FilterDef(ref, head.get("filter") or fallback_name, text, params, head.get("category", ""),
                     head.get("description", ""), head.get("passes", 1), error, head.get("precise", False))


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
    """A new effect entry for a clip: {id, filter, enabled, params}; an optional "mix" (0 - 1,
    may be keyframed: 混合程度) blends the result with the picture it was given, 1 when absent."""
    d = get(ref)
    params = default_params(d)
    for p in d.params:
        if p.name == "seed" and p.type in ("float", "int") and p.hi > p.lo:
            stamp = time.time_ns() / 1_000_000_000
            seed = p.lo + (stamp % (p.hi - p.lo))
            params[p.name] = round(seed) if p.type == "int" else seed
    return {"id": effect_id, "filter": ref, "enabled": True, "params": params}


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
%(params)s
in vec2 uv_;
out vec4 fragColor;
vec4 src(vec2 uv) { return texture(source, clamp(uv, 0.0, 1.0)); }
vec4 original(vec2 uv) { return texture(original_, clamp(uv, 0.0, 1.0)); }
vec4 unpremultiply(vec4 c) { return c.a > 0.0 ? vec4(c.rgb / c.a, c.a) : vec4(0.0); }
vec4 premultiply(vec4 c) { return vec4(c.rgb * c.a, c.a); }
float rand(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
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
              "menu": "int"}


def shader_source(d, sampled=()):
    """The fragment shader of filter d; sampled: its colour and number parameters that read a
    picture."""
    decl = "\n".join(f"uniform {GLSL_TYPES[p.type]} {p.name};" for p in d.params if p.name not in sampled)
    kinds = {p.name: SAMPLED if p.type == "color" else SAMPLED_NUMBER for p in d.params}
    return PRELUDE % {"params": decl, "sampled": "\n".join(kinds[n] % {"n": n} for n in sampled)} + d.code + EPILOGUE


def make_context():
    """(moderngl, a hidden OpenGL 3.3 context of this thread); FilterError when there is none."""
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

    def _program(self, d, sampled=()):
        key = (d.key(), sampled)
        prog = self.programs.get(key)
        if prog is None:
            if d.error:
                raise FilterError(d.error)
            if len(d.code) > BIG:
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

    def run_tex(self, d, values, src, w, h, time=0.0, progress=0.0, frame=0, unit=1.0, sources=None):
        """Filter the w x h texture src (premultiplied RGBA) on the card; returns the texture
        holding the result, one of this engine's own (valid until its next run at that size).
        unit: texture px per canvas px. The filter is told the canvas size as its resolution, so
        its pixel lengths are canvas px whatever size the picture is drawn at (a small preview,
        full screen, the export). sources {colour or number param: (texture, map)}: those read a
        picture (premultiplied), map the 3 x 3 matrix (9 numbers, by columns) from src's uv to
        the picture's (both with v = 0 at the top)."""
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
            if p.name in prog and p.name in values:
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
        self.ctx.disable(self.mgl.BLEND)
        read = src
        for i in range(d.passes):
            if "pass_index" in prog:
                prog["pass_index"].value = i
            pool = self._mid_targets(w, h) if d.precise and i < d.passes - 1 else targets
            dst_tex, dst_fbo = next(t for t in pool if t[0] is not read and t[0] is not src)
            dst_fbo.use()
            self.ctx.viewport = (0, 0, w, h)
            read.use(0)
            src.use(1)
            vao.render(self.mgl.TRIANGLE_STRIP)
            read = dst_tex
        return read

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
