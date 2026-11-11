"""Waiting for the GPU without holding Python's lock.

moderngl keeps the GIL through every call, so Context.finish() - which blocks until the GPU has drawn what was asked of it - froze
the whole program (the UI thread too) for as long as a heavy frame took. glFinish called through ctypes lets the other threads run
while the render thread waits.
"""
import ctypes
import ctypes.util
import sys

_finish = None
_tried = False


def _load():
    global _finish, _tried
    _tried = True
    names = {"win32": ["opengl32"], "darwin": ["/System/Library/Frameworks/OpenGL.framework/OpenGL"],
             "android": ["libGLESv3.so", "libGLESv2.so"]}.get(sys.platform, ["libGL.so.1", "libGLESv2.so.2", "libEGL.so.1"])
    for n in names:
        try:
            lib = ctypes.CDLL(ctypes.util.find_library(n.split(".")[0].replace("lib", "")) or n) if "/" not in n else ctypes.CDLL(n)
            fn = lib.glFinish
            fn.restype, fn.argtypes = None, []
            _finish = fn
            return
        except (OSError, AttributeError):
            continue


def finish(ctx):
    """ctx.finish() with the GIL let go while the GPU works (ctx must be current on this thread, as it is for ctx.finish())."""
    if not _tried:
        _load()
    if _finish is None:
        ctx.finish()
    else:
        _finish()


def read(obj, *args, **kw):
    """obj.read(...) of a texture or framebuffer after waiting for the GPU without the GIL (the read itself then only copies)."""
    finish(obj.ctx)
    return obj.read(*args, **kw)
