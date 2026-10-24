"""Locate MLT and expose the few C functions KiaseCut needs through ctypes.

No compiled bindings are needed: libmlt is a plain C library on every platform.
Windows uses the copy bundled with Kdenlive or Shotcut; Linux/macOS the system library.

Two Windows quirks found while wiring this up:
  * MLT ignores MLT_REPOSITORY there, so the plugin folder is passed to mlt_factory_init.
  * MLT and Qt read the environment through their own C runtime, so PATH / QT_* / MLT_DATA
    must be in place before the process starts; engine.py is always spawned with env().
"""
import ctypes as C
import ctypes.util
import glob
import os
import sys

P = C.c_void_p


def locate():
    """dict(lib, repository, data, bin) for the first MLT 7 install found."""
    over = os.environ.get("KIASECUT_MLT") or os.environ.get("TESETOA_MLT")   # (the old name still works)
    roots = [over] if over else []
    if sys.platform == "win32":
        roots += [r"C:\Program Files\Kdenlive", r"C:\Program Files\Shotcut"]
        for root in roots:
            for lib in (os.path.join(root, "bin", "libmlt-7.dll"), os.path.join(root, "libmlt-7.dll")):
                if os.path.exists(lib):
                    return {"lib": lib, "bin": os.path.dirname(lib),
                            "repository": os.path.join(root, "lib", "mlt"),
                            "data": os.path.join(root, "share", "mlt")}
        raise FileNotFoundError("MLT not found: install Kdenlive or Shotcut, or set KIASECUT_MLT")
    lib = ctypes.util.find_library("mlt-7") or "libmlt-7.so.7"
    repo = next((d for d in glob.glob("/usr/lib*/mlt-7") + glob.glob("/usr/lib/*/mlt-7")
                 + glob.glob("/usr/local/lib*/mlt-7") if os.path.isdir(d)), None)
    data = next((d for d in ("/usr/share/mlt-7", "/usr/local/share/mlt-7") if os.path.isdir(d)), None)
    return {"lib": lib, "bin": None, "repository": repo, "data": data}


def env(base=None):
    """Environment the engine process must start with."""
    loc = locate()
    e = dict(base or os.environ)
    if loc["bin"]:
        e["PATH"] = loc["bin"] + os.pathsep + e.get("PATH", "")
        e["QT_PLUGIN_PATH"] = loc["bin"]
    e["QT_QPA_PLATFORM"] = "offscreen"          # titles/qimage need Qt, but no window
    if loc["data"]:
        e["MLT_DATA"] = loc["data"]
        e["MLT_PROFILES_PATH"] = os.path.join(loc["data"], "profiles")
    if loc["repository"]:
        e["MLT_REPOSITORY"] = loc["repository"]
    return e


class Profile(C.Structure):
    _fields_ = [("description", C.c_char_p), ("frame_rate_num", C.c_int), ("frame_rate_den", C.c_int),
                ("width", C.c_int), ("height", C.c_int), ("progressive", C.c_int),
                ("sample_aspect_num", C.c_int), ("sample_aspect_den", C.c_int),
                ("display_aspect_num", C.c_int), ("display_aspect_den", C.c_int),
                ("colorspace", C.c_int), ("is_explicit", C.c_int)]


IMAGE_RGBA = 2          # mlt_image_rgba
AUDIO_S16 = 1           # mlt_audio_s16


class Mlt:
    def __init__(self):
        loc = locate()
        if loc["bin"]:
            os.add_dll_directory(loc["bin"])
        self.lib = C.CDLL(loc["lib"])
        L = self.lib

        def fn(name, res, *args):
            f = getattr(L, name)
            f.restype, f.argtypes = res, list(args)
            return f

        self.factory_init = fn("mlt_factory_init", P, C.c_char_p)
        self.profile_init = fn("mlt_profile_init", C.POINTER(Profile), C.c_char_p)
        self.factory_producer = fn("mlt_factory_producer", P, C.POINTER(Profile), C.c_char_p, C.c_char_p)
        self.factory_consumer = fn("mlt_factory_consumer", P, C.POINTER(Profile), C.c_char_p, C.c_char_p)
        self.producer_seek = fn("mlt_producer_seek", C.c_int, P, C.c_int)
        self.producer_position = fn("mlt_producer_position", C.c_int, P)
        self.producer_get_length = fn("mlt_producer_get_length", C.c_int, P)
        self.producer_close = fn("mlt_producer_close", None, P)
        self.service_get_frame = fn("mlt_service_get_frame", C.c_int, P, C.POINTER(P), C.c_int)
        self.frame_get_image = fn("mlt_frame_get_image", C.c_int, P, C.POINTER(C.POINTER(C.c_uint8)),
                                  C.POINTER(C.c_int), C.POINTER(C.c_int), C.POINTER(C.c_int), C.c_int)
        self.frame_get_audio = fn("mlt_frame_get_audio", C.c_int, P, C.POINTER(P), C.POINTER(C.c_int),
                                  C.POINTER(C.c_int), C.POINTER(C.c_int), C.POINTER(C.c_int))
        self.frame_close = fn("mlt_frame_close", None, P)
        self.audio_samples = fn("mlt_audio_calculate_frame_samples", C.c_int, C.c_float, C.c_int, C.c_int64)
        self.properties_set = fn("mlt_properties_set", C.c_int, P, C.c_char_p, C.c_char_p)
        self.consumer_connect = fn("mlt_consumer_connect", C.c_int, P, P)
        self.consumer_start = fn("mlt_consumer_start", C.c_int, P)
        self.consumer_stop = fn("mlt_consumer_stop", C.c_int, P)
        self.consumer_is_stopped = fn("mlt_consumer_is_stopped", C.c_int, P)
        self.consumer_close = fn("mlt_consumer_close", None, P)
        if not self.factory_init(loc["repository"].encode() if loc["repository"] else None):
            raise RuntimeError("mlt_factory_init failed")

    def set(self, obj, **props):
        for k, v in props.items():
            self.properties_set(obj, k.encode(), str(v).encode())
