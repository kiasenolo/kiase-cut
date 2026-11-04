"""A short buzz when a long press registers (Android only; anywhere else, or when it cannot be done, nothing happens).

PySide6 on Android has no JNI, so this talks to the Java virtual machine of the process through ctypes: the VM is found
(JNI_GetCreatedJavaVMs), the calling thread attached, and Vibrator.vibrate(VibrationEffect.createOneShot(...)) called on the
application's Context (android.app.ActivityThread.currentApplication()). The manifest needs the VIBRATE permission.
One failure at any step turns the buzz off for the rest of the run.
"""
import ctypes
import sys

BUZZ_MS = 25
JNI_VERSION = 0x00010006
# slots of the JNI function table (jni.h)
FIND_CLASS, EXCEPTION_CLEAR, NEW_GLOBAL, GET_METHOD, CALL_OBJECT_A, CALL_VOID_A = 6, 17, 21, 33, 36, 63
GET_STATIC_METHOD, CALL_STATIC_OBJECT_A, NEW_STRING_UTF, EXCEPTION_CHECK = 113, 116, 167, 228

_jni = None            # None: not tried yet, False: cannot, else the helper


class _Jni:
    def __init__(self):
        c = ctypes
        self.void_p = c.c_void_p
        getvms = None
        for name in ("libnativehelper.so", "libart.so", "libandroid_runtime.so"):
            try:
                getvms = getattr(c.CDLL(name), "JNI_GetCreatedJavaVMs")
                break
            except (OSError, AttributeError):
                continue
        if getvms is None:
            raise RuntimeError("no JNI_GetCreatedJavaVMs")
        vm, n = c.c_void_p(), c.c_int()
        getvms.argtypes = [c.POINTER(c.c_void_p), c.c_int, c.POINTER(c.c_int)]
        if getvms(c.byref(vm), 1, c.byref(n)) != 0 or n.value < 1:
            raise RuntimeError("no Java VM")
        self.vm = vm
        table = c.cast(c.cast(vm, c.POINTER(c.c_void_p))[0], c.POINTER(c.c_void_p))        # JNIInvokeInterface
        env = c.c_void_p()
        get_env = c.CFUNCTYPE(c.c_int, c.c_void_p, c.POINTER(c.c_void_p), c.c_int)(table[6])
        if get_env(vm, c.byref(env), JNI_VERSION) != 0:
            attach = c.CFUNCTYPE(c.c_int, c.c_void_p, c.POINTER(c.c_void_p), c.c_void_p)(table[4])
            if attach(vm, c.byref(env), None) != 0:
                raise RuntimeError("cannot attach")
        self.env = env
        self.fn = c.cast(c.cast(env, c.POINTER(c.c_void_p))[0], c.POINTER(c.c_void_p))     # JNINativeInterface

    def call(self, slot, restype, *args):
        types = [self.void_p] + [a[0] for a in args]
        proto = ctypes.CFUNCTYPE(restype, *types)
        return proto(self.fn[slot])(self.env, *[a[1] for a in args])

    def check(self):
        if self.call(EXCEPTION_CHECK, ctypes.c_ubyte):
            self.call(EXCEPTION_CLEAR, None)
            raise RuntimeError("Java exception")

    def cls(self, name):
        r = self.call(FIND_CLASS, ctypes.c_void_p, (ctypes.c_char_p, name.encode()))
        self.check()
        return r

    def static_method(self, cls, name, sig):
        r = self.call(GET_STATIC_METHOD, ctypes.c_void_p, (ctypes.c_void_p, cls), (ctypes.c_char_p, name.encode()),
                      (ctypes.c_char_p, sig.encode()))
        self.check()
        return r

    def method(self, cls, name, sig):
        r = self.call(GET_METHOD, ctypes.c_void_p, (ctypes.c_void_p, cls), (ctypes.c_char_p, name.encode()),
                      (ctypes.c_char_p, sig.encode()))
        self.check()
        return r

    @staticmethod
    def values(*items):
        """A jvalue array: items are ('l', pointer), ('i', int), ('j', int)."""
        arr = (ctypes.c_int64 * max(1, len(items)))()
        for i, (kind, v) in enumerate(items):
            if kind == "l":
                arr[i] = v or 0
            elif kind == "i":
                arr[i] = v & 0xFFFFFFFF
            else:
                arr[i] = v
        return arr

    def static_object(self, cls, mid, *items):
        r = self.call(CALL_STATIC_OBJECT_A, ctypes.c_void_p, (ctypes.c_void_p, cls), (ctypes.c_void_p, mid),
                      (ctypes.c_void_p, ctypes.addressof(self.values(*items))))
        self.check()
        return r

    def object(self, obj, mid, *items):
        r = self.call(CALL_OBJECT_A, ctypes.c_void_p, (ctypes.c_void_p, obj), (ctypes.c_void_p, mid),
                      (ctypes.c_void_p, ctypes.addressof(self.values(*items))))
        self.check()
        return r

    def void(self, obj, mid, *items):
        self.call(CALL_VOID_A, None, (ctypes.c_void_p, obj), (ctypes.c_void_p, mid),
                  (ctypes.c_void_p, ctypes.addressof(self.values(*items))))
        self.check()

    def keep(self, obj):
        """A reference that stays valid (the local ones end with the call into Java that made them)."""
        return self.call(NEW_GLOBAL, ctypes.c_void_p, (ctypes.c_void_p, obj))

    def string(self, text):
        r = self.call(NEW_STRING_UTF, ctypes.c_void_p, (ctypes.c_char_p, text.encode()))
        self.check()
        return r


def _vibrate(ms):
    j = _Jni()
    thread = j.cls("android/app/ActivityThread")
    app = j.static_object(thread, j.static_method(thread, "currentApplication", "()Landroid/app/Application;"))
    if not app:
        raise RuntimeError("no application")
    context = j.cls("android/content/Context")
    service = j.keep(j.object(app, j.method(context, "getSystemService", "(Ljava/lang/String;)Ljava/lang/Object;"), ("l", j.string("vibrator"))))
    if not service:
        raise RuntimeError("no vibrator")
    effect_cls = j.cls("android/os/VibrationEffect")
    effect = j.keep(j.static_object(effect_cls, j.static_method(effect_cls, "createOneShot", "(JI)Landroid/os/VibrationEffect;"),
                                    ("j", ms), ("i", -1)))               # (-1: the default strength)
    vibrate = j.method(j.cls("android/os/Vibrator"), "vibrate", "(Landroid/os/VibrationEffect;)V")
    return lambda: j.void(service, vibrate, ("l", effect))


def tick():
    global _jni
    if sys.platform != "android" or _jni is False:
        return
    try:
        if _jni is None:
            _jni = _vibrate(BUZZ_MS)
        _jni()
    except Exception as exc:
        print("haptic off:", exc, flush=True)
        _jni = False
