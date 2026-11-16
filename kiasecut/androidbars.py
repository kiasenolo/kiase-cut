"""Whether Android's own bars (status bar, navigation bar) are showing (Android only; elsewhere, or when it cannot be
found out, they are reported as hidden).

With the window fullscreen the system bars are hidden, and a swipe from an edge brings them back for a few seconds
("transient": over the window, nothing is resized). The swipe never reaches the program and the window's insets keep
saying "hidden", so the Java side (packaging/android/java, SystemBars.java, added to the APK through android.add_src) listens
for the system taking and giving back the bars, and keeps its answer in the static field `shown`, read here.

PySide6 has no JNI, so this goes through the ctypes helper of haptic.py. FindClass does not find the application's own
classes from a thread the Java side did not start, so the classes come through the application's class loader.
"""
import ctypes
import sys

from . import haptic

# slots of the JNI function table (jni.h)
CALL_STATIC_VOID_A, GET_STATIC_FIELD, GET_STATIC_OBJECT_FIELD, GET_STATIC_BOOLEAN_FIELD = 143, 144, 145, 146

_probe = None            # None: not tried yet, False: cannot, else a function returning True while a system bar shows


def _build():
    j = haptic._Jni()
    p = ctypes.c_void_p
    thread = j.cls("android/app/ActivityThread")
    app = j.static_object(thread, j.static_method(thread, "currentApplication", "()Landroid/app/Application;"))
    if not app:
        raise RuntimeError("no application")
    loader = j.object(app, j.method(j.cls("android/content/Context"), "getClassLoader", "()Ljava/lang/ClassLoader;"))
    load = j.method(j.cls("java/lang/ClassLoader"), "loadClass", "(Ljava/lang/String;)Ljava/lang/Class;")

    def app_class(name):
        return j.keep(j.object(loader, load, ("l", j.string(name))))

    activity_cls = app_class("org.kivy.android.PythonActivity")
    activity_field = j.call(GET_STATIC_FIELD, p, (p, activity_cls), (ctypes.c_char_p, b"mActivity"),
                            (ctypes.c_char_p, b"Lorg/kivy/android/PythonActivity;"))
    j.check()
    activity = j.call(GET_STATIC_OBJECT_FIELD, p, (p, activity_cls), (p, activity_field))
    if not activity:
        raise RuntimeError("no activity")
    bars_cls = app_class("io.github.kiasenolo.kiasecut.SystemBars")
    install = j.static_method(bars_cls, "install", "(Landroid/app/Activity;)V")
    args = j.values(("l", activity))
    j.call(CALL_STATIC_VOID_A, None, (p, bars_cls), (p, install), (p, ctypes.addressof(args)))
    j.check()
    shown_field = j.call(GET_STATIC_FIELD, p, (p, bars_cls), (ctypes.c_char_p, b"shown"), (ctypes.c_char_p, b"Z"))
    j.check()
    return lambda: bool(j.call(GET_STATIC_BOOLEAN_FIELD, ctypes.c_ubyte, (p, bars_cls), (p, shown_field)))


def system_bars_shown():
    """True while the status bar or the navigation bar of Android is on the screen."""
    global _probe
    if sys.platform != "android" or _probe is False:
        return False
    try:
        if _probe is None:
            _probe = _build()
        return _probe()
    except Exception as exc:
        print("system bars unknown:", exc, flush=True)
        _probe = False
        return False
