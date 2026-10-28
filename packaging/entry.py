"""Entry point of the built editor (build_exec.sh / build_exec.bat, kiasecut.spec).

The editor starts its filter-thumbnail process as `sys.executable -m kiasecut.fxthumbs`;
built, sys.executable is this program, so those arguments arrive here and run the module.
(The engine is a program of its own: engine_entry.py.)
MLT and ffmpeg are not built in: they are found as when run from source (system MLT 7 on
Linux, Kdenlive or Shotcut on Windows), or in an `mlt` folder beside the program
(build_exec.bat --bundle-mlt copies Kdenlive's there).
"""
import multiprocessing
import os
import runpy
import sys

if __name__ == "__main__":
    # shared memory's resource tracker: multiprocessing starts it as `sys.executable [flags]
    # -c "from multiprocessing.resource_tracker import main; ..."`. PyInstaller's
    # freeze_support() runs that only when the flags are exactly the ones it expects (they
    # were not here, and the editor opened a second time instead), so it is run here.
    if "-c" in sys.argv[1:-1]:
        command = sys.argv[sys.argv.index("-c") + 1]
        if command.startswith(("from multiprocessing.resource_tracker import main",
                               "from multiprocessing.forkserver import main")):
            exec(command)
            sys.exit()
    multiprocessing.freeze_support()
    # the launcher points LD_LIBRARY_PATH at the libraries built in, for the programs this one
    # starts: ffmpeg and MLT's plugins would then load those (copies of the building
    # machine's) over their own. This program does not need it, so put the user's back.
    if "LD_LIBRARY_PATH_ORIG" in os.environ:
        os.environ["LD_LIBRARY_PATH"] = os.environ.pop("LD_LIBRARY_PATH_ORIG")
    else:
        os.environ.pop("LD_LIBRARY_PATH", None)
    here = os.path.dirname(os.path.abspath(sys.executable))
    bundled = os.path.join(here, "mlt")
    if os.path.isdir(bundled) and not os.environ.get("KIASECUT_MLT"):
        os.environ["KIASECUT_MLT"] = bundled
    if len(sys.argv) > 2 and sys.argv[1] == "-m" and sys.argv[2].startswith("kiasecut."):
        module = sys.argv[2]
        sys.argv = [sys.argv[0]] + sys.argv[3:]
        runpy.run_module(module, run_name="__main__", alter_sys=True)
    else:
        from kiasecut.__main__ import main
        main()
