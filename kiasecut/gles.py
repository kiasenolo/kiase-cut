"""The part of moderngl that KiaseCut uses, on OpenGL ES 3 through ctypes (libEGL + libGLESv3).

Android has no desktop OpenGL and no moderngl wheel; its GPUs speak OpenGL ES. fx.make_context() hands this
module to fx.py / glrender.py in moderngl's place there (or anywhere with KIASECUT_GLES=1, which is how it is
tested on a PC), so those two files do not know the difference: the module itself is the `mgl` they read
constants from (LINEAR, TRIANGLE_STRIP, BLEND, ...), create_standalone_context() makes the context, and
texture / framebuffer / program / buffer / vertex_array / copy_framebuffer / viewport / blend_func and the
`with ctx:` that makes it current work as they do in moderngl.

The shaders are KiaseCut's own, written as #version 330; program() turns them into #version 300 es.
ctypes lets go of Python's lock during every call, so a long shader compile does not freeze the other threads.
"""
import ctypes as C
import re
import threading

import numpy as np

LINEAR, NEAREST, LINEAR_MIPMAP_LINEAR = 0x2601, 0x2600, 0x2703
TRIANGLE_STRIP = 5
BLEND = 0x0BE2
ZERO, ONE, SRC_ALPHA, ONE_MINUS_SRC_ALPHA = 0, 1, 0x0302, 0x0303

GL_TEXTURE_2D, GL_TEXTURE0, GL_RGBA = 0x0DE1, 0x84C0, 0x1908
GL_FRAMEBUFFER, GL_READ_FRAMEBUFFER, GL_DRAW_FRAMEBUFFER = 0x8D40, 0x8CA8, 0x8CA9
GL_COLOR_ATTACHMENT0, GL_FRAMEBUFFER_COMPLETE, GL_COLOR_BUFFER_BIT = 0x8CE0, 0x8CD5, 0x4000
GL_ARRAY_BUFFER, GL_STATIC_DRAW, GL_DYNAMIC_DRAW = 0x8892, 0x88E4, 0x88E8
GL_VERTEX_SHADER, GL_FRAGMENT_SHADER, GL_COMPILE_STATUS, GL_LINK_STATUS = 0x8B31, 0x8B30, 0x8B81, 0x8B82
GL_ACTIVE_UNIFORMS, GL_UNSIGNED_BYTE, GL_HALF_FLOAT, GL_FLOAT = 0x8B86, 0x1401, 0x140B, 0x1406
GL_TEX_MAG, GL_TEX_MIN, GL_TEX_WRAP_S, GL_TEX_WRAP_T, GL_CLAMP_TO_EDGE, GL_REPEAT = 0x2800, 0x2801, 0x2802, 0x2803, 0x812F, 0x2901
GL_SWIZZLE = (0x8E42, 0x8E43, 0x8E44, 0x8E45)                  # TEXTURE_SWIZZLE_R, _G, _B, _A
GL_SWIZZLE_VALUES = {"R": 0x1903, "G": 0x1904, "B": 0x1905, "A": 0x1906, "0": 0, "1": 1}
UNPACK_ALIGNMENT, PACK_ALIGNMENT = 0x0CF5, 0x0D05
SCRATCH_UNIT = 31                                            # texture parameters are set through this unit, so a texture
                                                             # the caller bound with use() stays where it is

# dtype -> (internal format, pixel type, numpy dtype, bytes per pixel)
DTYPES = {"f1": (0x8058, GL_UNSIGNED_BYTE, np.uint8, 4), "f2": (0x881A, GL_HALF_FLOAT, np.float16, 8),
          "f4": (0x8814, GL_FLOAT, np.float32, 16)}

# GLSL uniform types: gl type -> (letter of the glUniform call, numbers in one value)
UNIFORM_TYPES = {0x1406: ("f", 1), 0x8B50: ("f", 2), 0x8B51: ("f", 3), 0x8B52: ("f", 4),
                 0x1404: ("i", 1), 0x8B53: ("i", 2), 0x8B54: ("i", 3), 0x8B55: ("i", 4),
                 0x8B56: ("i", 1), 0x8B57: ("i", 2), 0x8B58: ("i", 3), 0x8B59: ("i", 4),      # bool (and its vectors)
                 0x8B5E: ("i", 1), 0x8B5A: ("m", 4), 0x8B5B: ("m", 9), 0x8B5C: ("m", 16)}      # sampler2D, mat2 / 3 / 4

ES_HEAD = "#version 300 es\nprecision highp float;\nprecision highp int;\nprecision highp sampler2D;\n"
# curve_ease(float c[128], x) reads its array by value; the Adreno compiler gets that wrong when x comes from a
# texture fetch (duotone: +-3e38). The same lookup as a macro indexes the uniform itself.
CURVE_EASE_FN = re.compile(r"float curve_ease\(float c\[128\], float x\) \{.*?\n\}\n", re.S)
CURVE_EASE_MACRO = """int curve_i_(float x) { return int(floor(clamp(x, 0.0, 1.0) * 127.0)); }
#define curve_ease(c, x) mix(c[curve_i_(x)], c[min(curve_i_(x) + 1, 127)], clamp(x, 0.0, 1.0) * 127.0 - float(curve_i_(x)))
"""


class GLError(Exception):
    pass


def _undefined_as_zero(text):
    """Desktop GLSL reads a macro that is not defined (yet) in an #if as 0; GLSL ES makes it an error.
    The same meaning for ES: such a name in an #if / #elif becomes 0."""
    defined, out = set(), []
    for line in text.split("\n"):
        s = line.strip()
        m = re.match(r"#\s*(define|undef)\s+(\w+)", s)
        if m:
            (defined.add if m.group(1) == "define" else defined.discard)(m.group(2))
        m = re.match(r"(#\s*(?:el)?if\s+)(.*)", s)
        if m:
            cond, _, comment = m.group(2).partition("//")
            cond = re.sub(r"\bdefined\s*\(?\s*\w+\s*\)?|\b[A-Za-z_]\w*\b",
                          lambda t: t.group(0) if t.group(0).startswith("defined") or t.group(0) in defined else "0", cond)
            if cond != m.group(2).partition("//")[0]:
                line = m.group(1) + cond + (" //" + comment if comment else "")
        out.append(line)
    return "\n".join(out)


FLOAT_ARRAY = re.compile(r"\bfloat\s*\[\s*\d*\s*\]\s*\(")
NUMBER = re.compile(r"\d+\.\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?|\d+[eE][+-]?\d+|\w+")


def _floats_in_array_constructors(text):
    """float[N](0, 1, 2.5): desktop GLSL converts the integers, GLSL ES does not - they get a ".0"."""
    out, pos = [], 0
    for m in FLOAT_ARRAY.finditer(text):
        if m.start() < pos:
            continue
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        out.append(text[pos:m.end()] + NUMBER.sub(lambda t: t.group(0) + ".0" if t.group(0).isdigit() else t.group(0), text[m.end():i]))
        pos = i
    return "".join(out) + text[pos:]


# gradient_eval(float p[32], vec4 c[32], ...) takes two arrays by value, which the Adreno compiler gets wrong the same way
# (colour ramps come out in steps). Each gradient it is called with gets its own copy that reads the uniforms itself.
GRADIENT_FN = re.compile(r"vec4 gradient_eval\(float p\[32\], vec4 c\[32\], (.*?)\) \{(.*?)\n\}\n", re.S)
GRADIENT_CALL = re.compile(r"\bgradient_eval\((\w+), (\w+), ")


def _gradient_per_uniform(text):
    fn = GRADIENT_FN.search(text)
    if not fn:
        return text
    pairs = list(dict.fromkeys(GRADIENT_CALL.findall(text[:fn.start()] + text[fn.end():])))
    copies = []
    for i, (pos, col) in enumerate(pairs):
        body = re.sub(r"\bc\[", col + "[", re.sub(r"\bp\[", pos + "[", fn.group(2)))
        copies.append(f"vec4 gradient_eval_{i}_({fn.group(1)}) {{{body}\n}}\n")
        text = re.sub(r"\bgradient_eval\(%s, %s, " % (pos, col), f"gradient_eval_{i}_(", text)
    fn = GRADIENT_FN.search(text)
    return text[:fn.end()] + "".join(copies) + text[fn.end():]


# Blender's compatible_mod: an int times a float
INT_TIMES_FLOAT = ("return a - N * b;", "return a - float(N) * b;")
PASTE_MACRO = re.compile(r"^#define[ \t]+(\w+)\(\s*(\w+)\s*\)[ \t]*(.*##.*)$", re.M)


def _paste_macros(text):
    """GLSL ES has no ## (token pasting). A macro that uses it, NAME(F) with F##_1d in its body, is written out at every
    place it is used (what the preprocessor would do, with the pasting done)."""
    for m in list(PASTE_MACRO.finditer(text)):
        name, param, body = m.groups()
        text = text.replace(m.group(0), "", 1)
        def expand(use, param=param, body=body):
            arg = use.group(1).strip()
            return re.sub(r"\b%s\s*##\s*" % param, arg, body.replace("\\", ""))
        text = re.sub(r"\b%s\(([^()]*)\)" % name, expand, text)
    return text


def converted(source):
    """KiaseCut's #version 330 shader as #version 300 es."""
    first, _, rest = source.strip().partition("\n")
    if not first.startswith("#version 330"):
        raise GLError(f"expected a #version 330 shader, got {first!r}")
    rest = CURVE_EASE_FN.sub(lambda m: CURVE_EASE_MACRO, rest, count=1).replace(*INT_TIMES_FLOAT)
    rest = _gradient_per_uniform(_paste_macros(rest))
    return ES_HEAD + _floats_in_array_constructors(_undefined_as_zero(rest))


# -- the libraries ---------------------------------------------------------------------------------------------------
_lib = {}
_lock = threading.Lock()
vp, ip, up, fp = C.c_void_p, C.POINTER(C.c_int), C.POINTER(C.c_uint), C.POINTER(C.c_float)
u32, i32, f32, sz = C.c_uint, C.c_int, C.c_float, C.c_ssize_t

EGL_FUNCS = {                                              # name: (result, arguments)
    "eglGetDisplay": (vp, [vp]), "eglGetProcAddress": (vp, [C.c_char_p]),
    "eglInitialize": (i32, [vp, ip, ip]), "eglBindAPI": (i32, [u32]),
    "eglChooseConfig": (i32, [vp, ip, C.POINTER(vp), i32, ip]),
    "eglCreateContext": (vp, [vp, vp, vp, ip]), "eglCreatePbufferSurface": (vp, [vp, vp, ip]),
    "eglMakeCurrent": (i32, [vp, vp, vp, vp]), "eglDestroyContext": (i32, [vp, vp]),
    "eglDestroySurface": (i32, [vp, vp]), "eglGetError": (i32, []), "eglGetCurrentContext": (vp, []),
    "eglGetCurrentSurface": (vp, [i32]), "eglGetCurrentDisplay": (vp, []),
}
GL_FUNCS = {
    "glGetString": (C.c_char_p, [u32]), "glGetError": (u32, []), "glFinish": (None, []),
    "glGenTextures": (None, [i32, up]), "glDeleteTextures": (None, [i32, up]), "glBindTexture": (None, [u32, u32]),
    "glActiveTexture": (None, [u32]), "glTexParameteri": (None, [u32, u32, i32]),
    "glTexImage2D": (None, [u32, i32, i32, i32, i32, i32, u32, u32, vp]),
    "glTexSubImage2D": (None, [u32, i32, i32, i32, i32, i32, u32, u32, vp]),
    "glGenerateMipmap": (None, [u32]), "glPixelStorei": (None, [u32, i32]),
    "glGenFramebuffers": (None, [i32, up]), "glDeleteFramebuffers": (None, [i32, up]),
    "glBindFramebuffer": (None, [u32, u32]), "glFramebufferTexture2D": (None, [u32, u32, u32, u32, i32]),
    "glCheckFramebufferStatus": (u32, [u32]), "glClearColor": (None, [f32] * 4), "glClear": (None, [u32]),
    "glReadPixels": (None, [i32, i32, i32, i32, u32, u32, vp]),
    "glBlitFramebuffer": (None, [i32] * 8 + [u32, u32]),
    "glViewport": (None, [i32] * 4), "glEnable": (None, [u32]), "glDisable": (None, [u32]),
    "glBlendFunc": (None, [u32, u32]),
    "glGenBuffers": (None, [i32, up]), "glDeleteBuffers": (None, [i32, up]), "glBindBuffer": (None, [u32, u32]),
    "glBufferData": (None, [u32, sz, vp, u32]), "glBufferSubData": (None, [u32, sz, sz, vp]),
    "glGenVertexArrays": (None, [i32, up]), "glDeleteVertexArrays": (None, [i32, up]),
    "glBindVertexArray": (None, [u32]), "glEnableVertexAttribArray": (None, [u32]),
    "glVertexAttribPointer": (None, [u32, i32, u32, C.c_ubyte, i32, vp]),
    "glDrawArrays": (None, [u32, i32, i32]),
    "glCreateShader": (u32, [u32]), "glShaderSource": (None, [u32, i32, C.POINTER(C.c_char_p), vp]),
    "glCompileShader": (None, [u32]), "glGetShaderiv": (None, [u32, u32, ip]),
    "glGetShaderInfoLog": (None, [u32, i32, ip, C.c_char_p]), "glDeleteShader": (None, [u32]),
    "glCreateProgram": (u32, []), "glAttachShader": (None, [u32, u32]), "glLinkProgram": (None, [u32]),
    "glGetProgramiv": (None, [u32, u32, ip]), "glGetProgramInfoLog": (None, [u32, i32, ip, C.c_char_p]),
    "glBindAttribLocation": (None, [u32, u32, C.c_char_p]), "glDeleteProgram": (None, [u32]),
    "glUseProgram": (None, [u32]), "glGetAttribLocation": (i32, [u32, C.c_char_p]),
    "glGetActiveUniform": (None, [u32, u32, i32, ip, ip, up, C.c_char_p]),
    "glGetUniformLocation": (i32, [u32, C.c_char_p]),
    "glUniform1f": (None, [i32, f32]), "glUniform1i": (None, [i32, i32]),
    "glUniform1fv": (None, [i32, i32, vp]), "glUniform2fv": (None, [i32, i32, vp]),
    "glUniform3fv": (None, [i32, i32, vp]), "glUniform4fv": (None, [i32, i32, vp]),
    "glUniform1iv": (None, [i32, i32, vp]), "glUniform2iv": (None, [i32, i32, vp]),
    "glUniform3iv": (None, [i32, i32, vp]), "glUniform4iv": (None, [i32, i32, vp]),
    "glUniformMatrix2fv": (None, [i32, i32, C.c_ubyte, vp]), "glUniformMatrix3fv": (None, [i32, i32, C.c_ubyte, vp]),
    "glUniformMatrix4fv": (None, [i32, i32, C.c_ubyte, vp]),
}


def _open(names):
    for name in names:
        try:
            return C.CDLL(name)
        except OSError:
            continue
    raise GLError("no " + names[0] + " here")


def libs():
    """(egl, gl): the libraries, with every function's types set. Android's own names first."""
    with _lock:
        if not _lib:
            egl = _open(["libEGL.so", "libEGL.so.1"])
            gl = _open(["libGLESv3.so", "libGLESv2.so", "libGLESv2.so.2"])
            for lib, funcs in ((egl, EGL_FUNCS), (gl, GL_FUNCS)):
                for name, (res, args) in funcs.items():
                    fn = getattr(lib, name)
                    fn.restype, fn.argtypes = res, args
            _lib["egl"], _lib["gl"] = egl, gl
        return _lib["egl"], _lib["gl"]


def available():
    """Whether this computer has OpenGL ES 3 to make a context with."""
    try:
        libs()
    except GLError:
        return False
    return True


_local = threading.local()


def _display(egl):
    dpy = egl.eglGetDisplay(None)
    major, minor = C.c_int(), C.c_int()
    if egl.eglInitialize(dpy, C.byref(major), C.byref(minor)):
        return dpy
    get = egl.eglGetProcAddress(b"eglGetPlatformDisplayEXT")            # (a PC with no window system: Mesa's surfaceless)
    if get:
        dpy = C.CFUNCTYPE(vp, u32, vp, ip)(get)(0x31DD, None, None)
        if dpy and egl.eglInitialize(dpy, C.byref(major), C.byref(minor)):
            return dpy
    raise GLError("eglInitialize failed")


def _check_size(size):
    w, h = int(size[0]), int(size[1])
    if w < 1 or h < 1:
        raise GLError(f"a picture of {w} x {h}")
    return w, h


class Context:
    """An OpenGL ES 3 context (with a 16 x 16 pbuffer to be current on), made current on the thread that made it."""

    def __init__(self):
        egl, gl = libs()
        self.egl, self.gl = egl, gl
        self.dpy = _display(egl)
        egl.eglBindAPI(0x30A0)                                                       # EGL_OPENGL_ES_API
        want = (i32 * 9)(0x3040, 0x40, 0x3033, 0x01, 0x3024, 8, 0x3025, 0, 0x3038)    # ES3 bit, pbuffer, red 8, no depth
        cfg, n = (vp * 1)(), C.c_int()
        if not egl.eglChooseConfig(self.dpy, want, cfg, 1, C.byref(n)) or n.value < 1:
            raise GLError("no EGL configuration with OpenGL ES 3")
        self.ctx = egl.eglCreateContext(self.dpy, cfg[0], None, (i32 * 3)(0x3098, 3, 0x3038))
        if not self.ctx:
            raise GLError(f"eglCreateContext failed (0x{egl.eglGetError():x})")
        self.surface = egl.eglCreatePbufferSurface(self.dpy, cfg[0], (i32 * 5)(0x3057, 16, 0x3056, 16, 0x3038))
        self.stack = []
        self._make_current()
        self.program_in_use = 0
        self._viewport, self._blend = (0, 0, 0, 0), (ONE, ZERO)
        self.info = {k: (gl.glGetString(v) or b"").decode() for k, v in (("vendor", 0x1F00), ("renderer", 0x1F01),
                                                                         ("version", 0x1F02))}
        gl.glPixelStorei(UNPACK_ALIGNMENT, 1)
        gl.glPixelStorei(PACK_ALIGNMENT, 1)
        self.scratch_fbo = None

    def _make_current(self):
        if not self.egl.eglMakeCurrent(self.dpy, self.surface, self.surface, self.ctx):
            raise GLError(f"eglMakeCurrent failed (0x{self.egl.eglGetError():x})")

    def __enter__(self):
        e = self.egl
        self.stack.append((e.eglGetCurrentDisplay(), e.eglGetCurrentSurface(0x3059), e.eglGetCurrentSurface(0x3056),
                           e.eglGetCurrentContext()))
        self._make_current()
        return self

    def __exit__(self, *exc):
        dpy, draw, read, ctx = self.stack.pop()
        if dpy and ctx:
            self.egl.eglMakeCurrent(dpy, draw, read, ctx)
        else:
            self.egl.eglMakeCurrent(self.dpy, None, None, None)
        return False

    def release(self):
        if self.ctx:
            self.egl.eglMakeCurrent(self.dpy, None, None, None)
            self.egl.eglDestroySurface(self.dpy, self.surface)
            self.egl.eglDestroyContext(self.dpy, self.ctx)
            self.ctx = None

    # -- state ---------------------------------------------------------------------------------------------------------
    @property
    def viewport(self):
        return self._viewport

    @viewport.setter
    def viewport(self, v):
        self._viewport = tuple(int(x) for x in v)
        self.gl.glViewport(*self._viewport)

    def enable(self, flags):
        self.gl.glEnable(flags)

    def disable(self, flags):
        self.gl.glDisable(flags)

    @property
    def blend_func(self):
        return self._blend

    @blend_func.setter
    def blend_func(self, v):
        self._blend = tuple(v)
        self.gl.glBlendFunc(*self._blend)

    def finish(self):
        self.gl.glFinish()

    def use_program(self, prog):
        if self.program_in_use != prog:
            self.gl.glUseProgram(prog)
            self.program_in_use = prog

    # -- objects -------------------------------------------------------------------------------------------------------
    def texture(self, size, components=4, data=None, dtype="f1"):
        return Texture(self, size, components, data, dtype)

    def framebuffer(self, color_attachments):
        return Framebuffer(self, color_attachments)

    def buffer(self, data=None, reserve=0, dynamic=False):
        return Buffer(self, data, reserve, dynamic)

    def program(self, vertex_shader, fragment_shader):
        return Program(self, vertex_shader, fragment_shader)

    def vertex_array(self, program, content):
        return VertexArray(self, program, content)

    def copy_framebuffer(self, dst, src):
        """Copy the pixels of the framebuffer src into dst (a texture or a framebuffer of the same size)."""
        gl = self.gl
        target = dst if isinstance(dst, Framebuffer) else dst.framebuffer()
        gl.glBindFramebuffer(GL_READ_FRAMEBUFFER, src.glo)
        gl.glBindFramebuffer(GL_DRAW_FRAMEBUFFER, target.glo)
        w, h = src.size
        gl.glBlitFramebuffer(0, 0, w, h, 0, 0, w, h, GL_COLOR_BUFFER_BIT, 0x2600)


def create_standalone_context(*args, **kwargs):
    return Context()


def _gen(fn, n=1):
    v = C.c_uint()
    fn(n, C.byref(v))
    return v.value


class Texture:
    def __init__(self, ctx, size, components=4, data=None, dtype="f1"):
        if components != 4 or dtype not in DTYPES:
            raise GLError(f"a texture of {components} components, {dtype}")
        self.ctx, self.size, self.dtype = ctx, _check_size(size), dtype
        self.internal, self.kind, self.np_dtype, self.pixel = DTYPES[dtype]
        self.glo = _gen(ctx.gl.glGenTextures)
        self._fbo = None
        self._filter = (LINEAR, LINEAR)
        self._repeat = [True, True]
        gl = ctx.gl
        self._bind()
        for p, v in ((GL_TEX_MIN, LINEAR), (GL_TEX_MAG, LINEAR), (GL_TEX_WRAP_S, GL_REPEAT), (GL_TEX_WRAP_T, GL_REPEAT)):
            gl.glTexParameteri(GL_TEXTURE_2D, p, v)
        data = None if data is None else bytes(data)
        if data is not None and len(data) != self.size[0] * self.size[1] * self.pixel:
            raise GLError(f"{len(data)} bytes for a {self.size[0]} x {self.size[1]} {dtype} texture")
        gl.glTexImage2D(GL_TEXTURE_2D, 0, self.internal, self.size[0], self.size[1], 0, GL_RGBA, self.kind,
                        C.c_char_p(data) if data is not None else None)

    width = property(lambda self: self.size[0])
    height = property(lambda self: self.size[1])

    def _bind(self):
        self.ctx.gl.glActiveTexture(GL_TEXTURE0 + SCRATCH_UNIT)
        self.ctx.gl.glBindTexture(GL_TEXTURE_2D, self.glo)

    def use(self, location=0):
        self.ctx.gl.glActiveTexture(GL_TEXTURE0 + location)
        self.ctx.gl.glBindTexture(GL_TEXTURE_2D, self.glo)

    @property
    def filter(self):
        return self._filter

    @filter.setter
    def filter(self, v):
        self._filter = tuple(v)
        self._bind()
        self.ctx.gl.glTexParameteri(GL_TEXTURE_2D, GL_TEX_MIN, v[0])
        self.ctx.gl.glTexParameteri(GL_TEXTURE_2D, GL_TEX_MAG, v[1])

    def _set_repeat(self, axis, on):
        self._repeat[axis] = bool(on)
        self._bind()
        self.ctx.gl.glTexParameteri(GL_TEXTURE_2D, (GL_TEX_WRAP_S, GL_TEX_WRAP_T)[axis], GL_REPEAT if on else GL_CLAMP_TO_EDGE)

    repeat_x = property(lambda self: self._repeat[0], lambda self, on: self._set_repeat(0, on))
    repeat_y = property(lambda self: self._repeat[1], lambda self, on: self._set_repeat(1, on))

    @property
    def swizzle(self):
        return self._swizzle

    @swizzle.setter
    def swizzle(self, letters):
        self._swizzle = letters
        self._bind()
        for pname, letter in zip(GL_SWIZZLE, letters):
            self.ctx.gl.glTexParameteri(GL_TEXTURE_2D, pname, GL_SWIZZLE_VALUES[letter])

    def write(self, data):
        data = bytes(data)
        if len(data) != self.size[0] * self.size[1] * self.pixel:
            raise GLError(f"{len(data)} bytes for a {self.size[0]} x {self.size[1]} {self.dtype} texture")
        self._bind()
        self.ctx.gl.glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, self.size[0], self.size[1], GL_RGBA, self.kind, C.c_char_p(data))

    def build_mipmaps(self, base=0, max_level=1000):
        self._bind()
        self.ctx.gl.glTexParameteri(GL_TEXTURE_2D, 0x813C, base)                  # TEXTURE_BASE_LEVEL
        self.ctx.gl.glTexParameteri(GL_TEXTURE_2D, 0x813D, max_level)             # TEXTURE_MAX_LEVEL
        self.ctx.gl.glGenerateMipmap(GL_TEXTURE_2D)

    def framebuffer(self):
        if self._fbo is None:
            self._fbo = Framebuffer(self.ctx, [self])
        return self._fbo

    def read(self, level=0):
        if level == 0:
            return self.framebuffer().read(4, self.dtype)
        fbo = Framebuffer(self.ctx, [self], level)             # (a mip level is read through a framebuffer of its own)
        try:
            return fbo.read(4, self.dtype)
        finally:
            fbo.release()

    def release(self):
        if self._fbo is not None:
            self._fbo.release()
        if self.glo:
            self.ctx.gl.glDeleteTextures(1, C.byref(C.c_uint(self.glo)))
            self.glo = 0


class Framebuffer:
    def __init__(self, ctx, color_attachments, level=0):
        gl = ctx.gl
        self.ctx, self.attachments = ctx, list(color_attachments)
        tex = self.attachments[0]
        self.size, self.dtype = (max(1, tex.size[0] >> level), max(1, tex.size[1] >> level)), tex.dtype
        self.glo = _gen(gl.glGenFramebuffers)
        gl.glBindFramebuffer(GL_FRAMEBUFFER, self.glo)
        gl.glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex.glo, level)
        status = gl.glCheckFramebufferStatus(GL_FRAMEBUFFER)
        if status != GL_FRAMEBUFFER_COMPLETE:
            self.release()
            raise GLError(f"the framebuffer ({tex.dtype}, {self.size[0]} x {self.size[1]}) is not complete (0x{status:x})")

    width = property(lambda self: self.size[0])
    height = property(lambda self: self.size[1])

    def use(self):
        self.ctx.gl.glBindFramebuffer(GL_FRAMEBUFFER, self.glo)
        self.ctx.viewport = (0, 0, *self.size)

    def clear(self, red=0.0, green=0.0, blue=0.0, alpha=0.0):
        gl = self.ctx.gl
        gl.glBindFramebuffer(GL_FRAMEBUFFER, self.glo)
        gl.glClearColor(red, green, blue, alpha)
        gl.glClear(GL_COLOR_BUFFER_BIT)

    def read(self, components=4, dtype="f1"):
        """The pixels (first row at the bottom of the card's picture, which the callers know about) as bytes of dtype."""
        if components != 4 or dtype not in DTYPES:
            raise GLError(f"reading {components} components as {dtype}")
        gl = self.ctx.gl
        w, h = self.size
        gl.glBindFramebuffer(GL_FRAMEBUFFER, self.glo)
        if dtype == self.dtype and dtype == "f1":                        # (a float target is read as floats, ES has no more)
            out = np.empty((h, w, 4), np.uint8)
            gl.glReadPixels(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE, out.ctypes.data)
            return out.tobytes()
        out = np.empty((h, w, 4), np.float32)
        if self.dtype == "f1":
            raw = np.empty((h, w, 4), np.uint8)
            gl.glReadPixels(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE, raw.ctypes.data)
            out[:] = raw / 255.0
        else:
            gl.glReadPixels(0, 0, w, h, GL_RGBA, GL_FLOAT, out.ctypes.data)
        if dtype == "f1":
            return np.clip(np.rint(out * 255.0), 0, 255).astype(np.uint8).tobytes()
        return out.astype(DTYPES[dtype][2]).tobytes()

    def release(self):
        if self.glo:
            self.ctx.gl.glDeleteFramebuffers(1, C.byref(C.c_uint(self.glo)))
            self.glo = 0


class Buffer:
    def __init__(self, ctx, data=None, reserve=0, dynamic=False):
        self.ctx = ctx
        self.glo = _gen(ctx.gl.glGenBuffers)
        data = None if data is None else bytes(data)
        self.size = len(data) if data is not None else int(reserve)
        ctx.gl.glBindBuffer(GL_ARRAY_BUFFER, self.glo)
        ctx.gl.glBufferData(GL_ARRAY_BUFFER, self.size, C.c_char_p(data) if data is not None else None,
                            GL_DYNAMIC_DRAW if dynamic else GL_STATIC_DRAW)

    def write(self, data, offset=0):
        data = bytes(data)
        if offset + len(data) > self.size:
            raise GLError(f"{len(data)} bytes past the end of a {self.size} byte buffer")
        self.ctx.gl.glBindBuffer(GL_ARRAY_BUFFER, self.glo)
        self.ctx.gl.glBufferSubData(GL_ARRAY_BUFFER, offset, len(data), C.c_char_p(data))

    def release(self):
        if self.glo:
            self.ctx.gl.glDeleteBuffers(1, C.byref(C.c_uint(self.glo)))
            self.glo = 0


class Uniform:
    def __init__(self, program, name, loc, gltype, size):
        self.program, self.name, self.loc, self.size = program, name, loc, size
        self.letter, self.count = UNIFORM_TYPES.get(gltype, (None, 1))

    @property
    def value(self):
        raise GLError("a uniform cannot be read back here")

    @value.setter
    def value(self, v):
        if self.letter is None:
            raise GLError(f"uniform {self.name} has a type that is not supported")
        gl = self.program.ctx.gl
        self.program.ctx.use_program(self.program.glo)
        if self.count == 1 and self.size == 1:
            if self.letter == "f":
                gl.glUniform1f(self.loc, float(v))
            else:
                gl.glUniform1i(self.loc, int(v))
            return
        arr = np.ascontiguousarray(v, dtype=np.float32 if self.letter in "fm" else np.int32).ravel()
        self._set(arr, min(self.size, arr.size // self.count))

    def write(self, data):
        arr = np.frombuffer(bytes(data), dtype=np.float32 if self.letter in "fm" else np.int32)
        self.program.ctx.use_program(self.program.glo)
        self._set(arr, min(self.size, arr.size // self.count))

    def _set(self, arr, n):
        gl = self.program.ctx.gl
        if self.letter == "m":
            getattr(gl, f"glUniformMatrix{round(self.count ** 0.5)}fv")(self.loc, n, 0, arr.ctypes.data)
        else:
            getattr(gl, f"glUniform{self.count}{self.letter}v")(self.loc, n, arr.ctypes.data)


class Program:
    def __init__(self, ctx, vertex_shader, fragment_shader):
        gl = self.gl = ctx.gl
        self.ctx = ctx
        shaders = []
        for kind, text in ((GL_VERTEX_SHADER, vertex_shader), (GL_FRAGMENT_SHADER, fragment_shader)):
            sh = gl.glCreateShader(kind)
            gl.glShaderSource(sh, 1, (C.c_char_p * 1)(converted(text).encode("utf-8")), None)
            gl.glCompileShader(sh)
            shaders.append(sh)
        self.glo = gl.glCreateProgram()
        for sh in shaders:
            gl.glAttachShader(self.glo, sh)
        gl.glBindAttribLocation(self.glo, 0, b"pos")
        gl.glLinkProgram(self.glo)
        ok = C.c_int()
        gl.glGetProgramiv(self.glo, GL_LINK_STATUS, C.byref(ok))
        problems = []
        if not ok.value:
            for kind, sh in zip(("vertex", "fragment"), shaders):
                gl.glGetShaderiv(sh, GL_COMPILE_STATUS, C.byref(ok))
                if not ok.value:
                    problems.append(f"{kind} shader: {self._log(gl.glGetShaderInfoLog, sh)}")
            problems.append("link: " + self._log(gl.glGetProgramInfoLog, self.glo))
        for sh in shaders:
            gl.glDeleteShader(sh)
        if problems:
            gl.glDeleteProgram(self.glo)
            self.glo = 0
            raise GLError("\n".join(problems))
        self.uniforms = {}
        count = C.c_int()
        gl.glGetProgramiv(self.glo, GL_ACTIVE_UNIFORMS, C.byref(count))
        for i in range(count.value):
            length, size, kind = C.c_int(), C.c_int(), C.c_uint()
            name = C.create_string_buffer(256)
            gl.glGetActiveUniform(self.glo, i, 256, C.byref(length), C.byref(size), C.byref(kind), name)
            raw = name.value.decode()
            loc = gl.glGetUniformLocation(self.glo, raw.encode())
            if loc >= 0:
                key = raw[:-3] if raw.endswith("[0]") else raw
                self.uniforms[key] = Uniform(self, key, loc, kind.value, size.value)

    @staticmethod
    def _log(fn, obj):
        buf = C.create_string_buffer(8192)
        fn(obj, 8192, C.byref(C.c_int()), buf)
        return buf.value.decode(errors="replace").strip()

    def __contains__(self, name):
        return name in self.uniforms

    def __getitem__(self, name):
        try:
            return self.uniforms[name]
        except KeyError:
            raise KeyError(f"no uniform {name!r} (the compiler drops one that nothing reads)") from None

    def release(self):
        if self.glo:
            self.gl.glDeleteProgram(self.glo)
            self.glo = 0


class VertexArray:
    def __init__(self, ctx, program, content):
        gl = self.gl = ctx.gl
        self.ctx, self.program = ctx, program
        self.glo = _gen(gl.glGenVertexArrays)
        gl.glBindVertexArray(self.glo)
        self.vertices = 0
        for buf, fmt, *names in content:
            m = re.fullmatch(r"(\d)f", fmt)
            if not m:
                raise GLError(f"vertex format {fmt!r}")
            n = int(m.group(1))
            gl.glBindBuffer(GL_ARRAY_BUFFER, buf.glo)
            for name in names:
                loc = gl.glGetAttribLocation(program.glo, name.encode())
                if loc >= 0:
                    gl.glEnableVertexAttribArray(loc)
                    gl.glVertexAttribPointer(loc, n, GL_FLOAT, 0, n * 4, None)
            self.vertices = buf.size // (n * 4)
        gl.glBindVertexArray(0)

    def render(self, mode=TRIANGLE_STRIP, vertices=-1, first=0):
        self.ctx.use_program(self.program.glo)
        self.gl.glBindVertexArray(self.glo)
        self.gl.glDrawArrays(mode, first, self.vertices if vertices < 0 else vertices)

    def release(self):
        if self.glo:
            self.gl.glDeleteVertexArrays(1, C.byref(C.c_uint(self.glo)))
            self.glo = 0
