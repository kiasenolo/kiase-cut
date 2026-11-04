"""KiaseCut's start on Android (python-for-android runs main.py of the APK).

A selftest.py beside this file (put there with `adb shell run-as <app id> ...`, never packed) is run instead of the
program, its prints going to logcat: how the pieces are tried on the device without building the APK again."""
import os
import runpy
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
try:
    if os.path.exists(os.path.join(HERE, "selftest.py")):
        runpy.run_path(os.path.join(HERE, "selftest.py"), run_name="__main__")
        sys.exit(0)
    from kiasecut.ui.main_window import run
    sys.exit(run(["kiasecut"]))
except SystemExit:
    raise
except BaseException:
    print("KiaseCut did not start:\n" + traceback.format_exc(), flush=True)      # (python's stdout is logcat's "python" tag)
    raise
