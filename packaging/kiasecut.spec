# PyInstaller spec for build_exec.sh / build_exec.bat: two programs, each with its own
# libraries, the second moved into the first's folder by the scripts:
#   kiasecut/kiasecut[.exe]                  the editor (entry.py)
#   kiasecut/engine/kiasecut-engine[.exe]    the render engine (engine_entry.py)
# The engine gets a folder of its own because the launcher puts its folder first in the
# library search path (LD_LIBRARY_PATH on Linux): next to the editor's PySide6 Qt and
# Qt's FFmpeg, MLT's plugins would load those instead of the Qt and FFmpeg they were built
# with. MLT itself is never built in: its plugins must come with it.
import os
import sys

ROOT = os.path.dirname(SPECPATH)
WIN = sys.platform == "win32"


def no_mlt(binaries):
    return [b for b in binaries if not os.path.basename(b[0]).lower().startswith(("libmlt", "mlt"))]


app = Analysis([os.path.join(SPECPATH, "entry.py")], pathex=[ROOT],
               hiddenimports=["kiasecut.fxthumbs"],
               datas=[(os.path.join(ROOT, "kiasecut", "filters"), "kiasecut/filters"),
                      (os.path.join(ROOT, "Icon.svg"), ".")],
               excludes=["tkinter", "kiasecut.engine"])
app.binaries = no_mlt(app.binaries)
app_exe = EXE(PYZ(app.pure), app.scripts, [], exclude_binaries=True, name="kiasecut",
              console=not WIN)
COLLECT(app_exe, app.binaries, app.datas, name="kiasecut")

eng = Analysis([os.path.join(SPECPATH, "engine_entry.py")], pathex=[ROOT],
               hiddenimports=["kiasecut.engine"],
               excludes=["tkinter", "PySide6", "shiboken6", "numpy", "PIL", "moderngl", "glcontext"])
eng.binaries = no_mlt(eng.binaries)
eng_exe = EXE(PYZ(eng.pure), eng.scripts, [], exclude_binaries=True, name="kiasecut-engine",
              console=True)
COLLECT(eng_exe, eng.binaries, eng.datas, name="kiasecut-engine")
