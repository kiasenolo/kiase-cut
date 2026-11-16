"""Whether Android's own bars (status bar, navigation bar) are showing (Android only; elsewhere, or when it cannot be
found out, they are reported as hidden).

With the window fullscreen the system bars are hidden, and a swipe from an edge brings them back for a few seconds
("transient": over the window, nothing is resized). The swipe itself never reaches the program, but its result can be read:
PythonActivity.mActivity.getWindow().getDecorView().getRootWindowInsets().isVisible(statusBars | navigationBars).
PySide6 has no JNI, so this goes through the ctypes helper of haptic.py. FindClass does not find the application's own
classes from a thread the Java side did not start, so PythonActivity comes through the application's class loader.
"""
import ctypes
import sys

from . import haptic

STATUS_BARS, NAVIGATION_BARS = 1 << 0, 1 << 1        # WindowInsets.Type.statusBars() / navigationBars()
# slots of the JNI function table (jni.h)
DELETE_LOCAL, CALL_BOOLEAN_A, GET_STATIC_FIELD, GET_STATIC_OBJECT_FIELD = 23, 39, 144, 145

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
    activity_cls = j.keep(j.object(loader, load, ("l", j.string("org.kivy.android.PythonActivity"))))
    field = j.call(GET_STATIC_FIELD, p, (p, activity_cls), (ctypes.c_char_p, b"mActivity"),
                   (ctypes.c_char_p, b"Lorg/kivy/android/PythonActivity;"))
    j.check()
    get_window = j.method(j.cls("android/app/Activity"), "getWindow", "()Landroid/view/Window;")
    get_decor = j.method(j.cls("android/view/Window"), "getDecorView", "()Landroid/view/View;")
    get_insets = j.method(j.cls("android/view/View"), "getRootWindowInsets", "()Landroid/view/WindowInsets;")
    is_visible = j.method(j.cls("android/view/WindowInsets"), "isVisible", "(I)Z")
    args = j.values(("i", STATUS_BARS | NAVIGATION_BARS))

    def shown():
        refs = []                               # (the local references of a thread Java did not start are never freed by themselves)
        try:
            activity = j.call(GET_STATIC_OBJECT_FIELD, p, (p, activity_cls), (p, field))
            refs.append(activity)
            window = j.object(activity, get_window) if activity else None
            refs.append(window)
            decor = j.object(window, get_decor) if window else None
            refs.append(decor)
            insets = j.object(decor, get_insets) if decor else None
            refs.append(insets)
            if not insets:
                return False
            r = j.call(CALL_BOOLEAN_A, ctypes.c_ubyte, (p, insets), (p, is_visible), (p, ctypes.addressof(args)))
            j.check()
            return bool(r)
        finally:
            for ref in refs:
                if ref:
                    j.call(DELETE_LOCAL, None, (p, ref))
    return shown


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
