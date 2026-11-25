"""The sound effects' C library (src/), loaded with ctypes.

The library is looked for in this order: the file KIASECUT_DSP names; a ready-made one in
bin/<platform>/ (packaged builds, and Windows); else it is compiled from src/ with the C
compiler there is (CC, cc, gcc, clang) into _build/ - or, where that folder cannot be
written, the user's cache - under a name made from the sources, so it is built again only
when they change.

    fx = dsp.Processor("highpass")
    fx.set("f", 200.0)
    out = fx.process(block)                 # float32 [n, 2], 1.0 = full scale
"""
import ctypes
import glob
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading

import numpy as np

ABI = 1
RATE = 48000
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
SUFFIX = ".dll" if sys.platform == "win32" else ".dylib" if sys.platform == "darwin" else ".so"


class DspError(RuntimeError):
    pass


_lock = threading.Lock()
_lib = None
_error = None
_types = {}                     # name -> (index, {param name: index}, {param name: default})


def sources():
    return sorted(glob.glob(os.path.join(SRC, "*.c")))


def platform_tag():
    """linux-x86_64, windows-x86_64, android-aarch64..."""
    machine = platform.machine().lower()
    machine = {"amd64": "x86_64", "arm64": "aarch64"}.get(machine, machine)
    system = "android" if hasattr(sys, "getandroidapilevel") else platform.system().lower()
    return f"{system}-{machine}"


def _stamp():
    h = hashlib.sha1()
    for p in sources() + sorted(glob.glob(os.path.join(SRC, "*.h"))):
        with open(p, "rb") as f:
            h.update(os.path.basename(p).encode() + f.read().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:12]


def compiler():
    for c in (os.environ.get("CC"), "cc", "gcc", "clang"):
        if c and shutil.which(c):
            return shutil.which(c)
    return None


def compile_to(out, cc=None):
    """Compile src/ into the shared library out."""
    cc = cc or compiler()
    if not cc:
        raise DspError("找不到 C 編譯器（gcc 或 clang）")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=SUFFIX, dir=os.path.dirname(os.path.abspath(out)))
    os.close(fd)
    # (no -ffast-math: linking with it makes the whole process, numpy too, flush denormals)
    cmd = [cc, "-std=c11", "-O3", "-fno-math-errno", "-shared", "-fvisibility=hidden", "-Wall"]
    if sys.platform != "win32":
        cmd.append("-fPIC")
    cmd += ["-o", tmp, *sources()]
    if sys.platform != "win32":
        cmd.append("-lm")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise DspError("聲音效果函式庫編譯失敗：\n" + r.stderr[-2000:])
        os.replace(tmp, out)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return out


def _build_dirs():
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return [os.path.join(HERE, "_build"), os.path.join(cache, "kiasecut", "dsp")]


def find_library():
    given = os.environ.get("KIASECUT_DSP")
    if given:
        return given
    ready = os.path.join(HERE, "bin", platform_tag(), "kcdsp" + SUFFIX)
    from_source = bool(sources())
    if os.path.exists(ready) and (not from_source or _read(ready + ".stamp") == _stamp()):
        return ready
    if not from_source:
        raise DspError("沒有這個平台的聲音效果函式庫：" + platform_tag())
    name = f"kcdsp-{platform_tag()}-{_stamp()}{SUFFIX}"
    for d in _build_dirs():
        if os.path.exists(os.path.join(d, name)):
            return os.path.join(d, name)
    try:
        failure = None
        for d in _build_dirs():
            try:
                return compile_to(os.path.join(d, name))
            except OSError as exc:                  # (a folder that cannot be written)
                failure = exc
        raise DspError(f"聲音效果函式庫無法寫入：{failure}")
    except DspError:
        if os.path.exists(ready):                   # an older ready-made one: the ABI check decides
            return ready
        raise


def _read(path):
    try:
        with open(path, encoding="ascii") as f:
            return f.read().strip()
    except OSError:
        return None


def _bind(lib):
    c = ctypes
    fp = c.c_void_p
    for name, res, args in (("kc_abi", c.c_int, []), ("kc_type_count", c.c_int, []),
                            ("kc_type_name", c.c_char_p, [c.c_int]), ("kc_param_count", c.c_int, [c.c_int]),
                            ("kc_param_name", c.c_char_p, [c.c_int, c.c_int]),
                            ("kc_param_default", c.c_double, [c.c_int, c.c_int]),
                            ("kc_new", fp, [c.c_int, c.c_double]), ("kc_free", None, [fp]), ("kc_reset", None, [fp]),
                            ("kc_set", None, [fp, c.c_int, c.c_double]),
                            ("kc_process", None, [fp, c.c_void_p, c.c_void_p, c.c_void_p, c.c_int, c.c_int64]),
                            ("kc_latency", c.c_int, [fp]), ("kc_tail", c.c_double, [fp]),
                            ("kc_meters", None, [fp, c.c_void_p, c.c_int]),
                            ("kc_response", None, [fp, c.c_int, c.c_void_p, c.c_void_p, c.c_int])):
        f = getattr(lib, name)
        f.restype, f.argtypes = res, args


def load():
    """The library, loaded (and compiled) the first time; DspError when there is none."""
    global _lib, _error
    with _lock:
        if _lib is not None:
            return _lib
        if _error is not None:
            raise _error
        try:
            path = find_library()
            lib = ctypes.CDLL(path)
            _bind(lib)
            if lib.kc_abi() != ABI:
                raise DspError("聲音效果函式庫的版本不合：" + path)
            for t in range(lib.kc_type_count()):
                names = [lib.kc_param_name(t, i).decode() for i in range(lib.kc_param_count(t))]
                _types[lib.kc_type_name(t).decode()] = (t, {n: i for i, n in enumerate(names)},
                                                       {n: lib.kc_param_default(t, i) for i, n in enumerate(names)})
        except (OSError, AttributeError, DspError) as exc:
            _error = exc if isinstance(exc, DspError) else DspError(f"聲音效果函式庫載入失敗：{exc}")
            raise _error
        _lib = lib
        return lib


def available():
    try:
        load()
    except DspError:
        return False
    return True


def error():
    """Why the library cannot be used (a message to show), or None."""
    return None if available() else str(_error)


def kinds():
    load()
    return list(_types)


def defaults(kind):
    load()
    return dict(_types[kind][2])


def _ptr(a):
    return a.ctypes.data_as(ctypes.c_void_p)


def _block(a, n=None):
    a = np.ascontiguousarray(a, np.float32)
    if a.ndim != 2 or a.shape[1] != 2 or (n is not None and len(a) != n):
        raise ValueError("sound is a float32 [n, 2] array")
    return a


class Processor:
    """One effect with its own memory of the sound heard so far."""

    def __init__(self, kind, rate=RATE):
        self.lib = load()
        if kind not in _types:
            raise DspError("沒有這個聲音效果：" + str(kind))
        self.kind = kind
        t, self.index, _ = _types[kind]
        self.fx = self.lib.kc_new(t, float(rate))
        if not self.fx:
            raise DspError("無法建立聲音效果：" + kind)

    def set(self, name, value):
        """A parameter by its name; one the effect does not have is ignored."""
        i = self.index.get(name)
        if i is not None:
            self.lib.kc_set(self.fx, i, float(value))

    def reset(self):
        self.lib.kc_reset(self.fx)

    def process(self, block, side=None, pos=0):
        """block through the effect: a new array. side: the side-chain, as long as block."""
        block = _block(block)
        out = np.empty_like(block)
        if side is not None:
            side = _block(side, len(block))
        if len(block):
            self.lib.kc_process(self.fx, _ptr(block), _ptr(side) if side is not None else None, _ptr(out),
                                len(block), int(pos))
        return out

    @property
    def latency(self):
        """Samples the output is late by."""
        return self.lib.kc_latency(self.fx)

    @property
    def tail(self):
        """Seconds it keeps sounding once its input is silent."""
        return self.lib.kc_tail(self.fx)

    def response(self, hz, part=-1):
        """The gain in dB at each frequency of hz, from the parameters as they are; part:
        one band of an equaliser."""
        hz = np.ascontiguousarray(hz, np.float64)
        out = np.zeros(len(hz), np.float64)
        self.lib.kc_response(self.fx, int(part), _ptr(hz), _ptr(out), len(hz))
        return out

    def meters(self, n=8):
        out = np.zeros(n, np.float32)
        self.lib.kc_meters(self.fx, _ptr(out), n)
        return out

    def close(self):
        if getattr(self, "fx", None):
            self.lib.kc_free(self.fx)
            self.fx = None

    def __del__(self):
        self.close()
