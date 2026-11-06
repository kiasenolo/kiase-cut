"""A GL context for the player's thread that shares its textures with Qt's own (the preview's).

The player draws a frame into a texture. Normally it reads the pixels back to the CPU and the
preview uploads them again to draw them; here the preview draws that very texture (preview.py), so
nothing crosses to the CPU. That works as the contexts are in one share group: run() sets
Qt.AA_ShareOpenGLContexts (every QOpenGLWidget's context shares with QOpenGLContext.globalShareContext())
and this module makes the player's context share with it too, with moderngl attached to it.

ENABLED: the program wants it (設定 "預覽直接用 GPU 貼圖", set by main_window.run before the window);
nothing else changes while it is off.
"""
import os
import sys

ENABLED = False
_surface = None                    # the player context's surface: made on the UI thread (prepare)
_kept = {}                         # thread id -> its QOpenGLContext (it must outlive the moderngl context)


def wanted(setting=True):
    """Whether the zero-copy preview is to be tried at all: desktop OpenGL with moderngl, and not switched off."""
    if not setting or os.environ.get("KIASECUT_PREVIEW_DIRECT", "1") == "0":
        return False
    if sys.platform == "android" or os.environ.get("KIASECUT_GLES") == "1":
        return False
    try:
        import moderngl                                          # noqa: F401
        from PySide6.QtOpenGLWidgets import QOpenGLWidget        # noqa: F401
    except ImportError:
        return False
    return True


def configure_application():
    """Before the QApplication: one share group for all of Qt's GL contexts, and a core 3.3 default format (what moderngl needs)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QSurfaceFormat
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    QSurfaceFormat.setDefaultFormat(fmt)


def widget_format():
    """The format of a QOpenGLWidget (4 x multisampling on the default format)."""
    from PySide6.QtGui import QSurfaceFormat
    fmt = QSurfaceFormat(QSurfaceFormat.defaultFormat())
    fmt.setSamples(4)
    return fmt


def prepare():
    """On the UI thread, after the QApplication: the surface the player's context is made current on."""
    global _surface
    from PySide6.QtGui import QOffscreenSurface, QOpenGLContext
    share = QOpenGLContext.globalShareContext()
    if share is None:
        raise RuntimeError("no shared OpenGL context")
    _surface = QOffscreenSurface()
    _surface.setFormat(share.format())
    _surface.create()
    if not _surface.isValid():
        raise RuntimeError("no offscreen surface")


def make_context():
    """(moderngl, a moderngl context) made current on this thread, in Qt's share group; raises when that cannot be."""
    import moderngl
    import threading
    from PySide6.QtGui import QOpenGLContext
    if _surface is None:
        raise RuntimeError("sharedgl.prepare() was not called")
    share = QOpenGLContext.globalShareContext()
    qc = QOpenGLContext()
    qc.setFormat(share.format())
    qc.setShareContext(share)
    if not qc.create() or not qc.makeCurrent(_surface):
        raise RuntimeError("cannot make the shared OpenGL context")
    ctx = moderngl.create_context()
    _kept[threading.get_ident()] = qc
    return moderngl, ctx
