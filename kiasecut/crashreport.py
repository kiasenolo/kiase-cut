"""Crash reports: every crash leaves a text file in ~/Documents/KiaseCut/crashReport (beside the auto-save folder).

Each running program starts "crash-<date time>-<pid>.txt" there: what it runs on (versions, system, command line) and, as it
goes, what was opened. faulthandler writes into it when the program dies in native code (a segmentation fault, abort: every
thread's stack), so that file *is* the report of that crash. Closing normally removes it. One left behind by a program that is
no longer running and that has no stack in it (killed, out of memory, power cut) gets a line saying so at the next start.

An exception nobody catches (main thread, other thread, a Qt slot, a destructor) does not end the program but is as much a
fault: it goes to "exception-<date time>-<pid>-<n>.txt" at once, with what the program was doing lately. The same
exception in a loop is written once, and at most MAX_EXCEPTIONS a run.
"""
import collections
import datetime
import faulthandler
import os
import platform
import sys
import threading
import traceback

from . import __version__

FOLDER = "crashReport"
MAX_EXCEPTIONS = 20
FILES_MAX = 100                  # the oldest reports are removed past this many
EVENTS = 40                      # what was done lately, kept for the exception reports
ENDED = "== The program ended without closing"

_fh = None
_path = None
_dir = None
_seen = set()
_count = 0
_events = collections.deque(maxlen=EVENTS)
_old_hooks = None
_lock = threading.Lock()


def folder(autosave_dir):
    """The crash report folder that goes with an autosave folder (~/Documents/KiaseCut/auto-save)."""
    return os.path.join(os.path.dirname(os.path.normpath(autosave_dir)), FOLDER)


def _now():
    return datetime.datetime.now()


def system_info():
    lines = [f"KiaseCut {__version__}", f"time: {_now():%Y-%m-%d %H:%M:%S}", f"pid: {os.getpid()}",
             f"system: {platform.platform()} ({platform.machine()})", f"python: {sys.version.split()[0]} ({sys.executable})"]
    try:
        import PySide6
        from PySide6.QtCore import qVersion
        lines.append(f"PySide6 {PySide6.__version__}, Qt {qVersion()}")
    except Exception:                                    # (a report is worth more than the version of Qt)
        pass
    lines.append("command line: " + " ".join(sys.argv))
    lines.append("platform plugin / GL: " + ", ".join(f"{k}={os.environ[k]}" for k in
                                                       ("QT_QPA_PLATFORM", "QT_QUICK_BACKEND", "LIBGL_ALWAYS_SOFTWARE") if k in os.environ)
                 if any(k in os.environ for k in ("QT_QPA_PLATFORM", "QT_QUICK_BACKEND", "LIBGL_ALWAYS_SOFTWARE")) else "platform plugin / GL: default")
    lines += [f"{k}={v}" for k, v in sorted(os.environ.items()) if k.startswith("KIASECUT_")]
    return "\n".join(lines)


def event(text):
    """Something the program did (a project opened ...): kept for the exception reports, and written into the crash report."""
    stamp = f"[{_now():%H:%M:%S}] {text}"
    _events.append(stamp)
    if _fh is not None:
        try:
            _fh.write(stamp + "\n")
            _fh.flush()
        except (OSError, ValueError):
            pass


def _prune(where):
    try:
        names = sorted(n for n in os.listdir(where) if n.endswith(".txt") and (n.startswith("crash-") or n.startswith("exception-")))
    except OSError:
        return
    for n in names[:-FILES_MAX] if len(names) > FILES_MAX else []:
        try:
            os.remove(os.path.join(where, n))
        except OSError:
            pass


def _mark_left_behind(where):
    """Reports of programs that are gone and left no stack: say how they ended."""
    from .recovery import alive
    for n in os.listdir(where):
        if not (n.startswith("crash-") and n.endswith(".txt")):
            continue
        try:
            pid = int(n[:-4].rsplit("-", 1)[1])
        except ValueError:
            continue
        p = os.path.join(where, n)
        if alive(pid):
            continue
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            if ENDED in text or "Fatal Python error" in text or "Current thread" in text:
                continue
            with open(p, "a", encoding="utf-8") as fh:
                fh.write(f"\n{ENDED}: no stack was recorded (it was killed, ran out of memory, or the power went). Found at "
                         f"{_now():%Y-%m-%d %H:%M:%S}.\n")
        except OSError:
            pass


def begin(autosave_dir):
    """This program has started: its report file, faulthandler writing into it, and the hooks for exceptions nobody catches."""
    global _fh, _path, _dir, _old_hooks
    where = _dir = folder(autosave_dir)
    try:
        os.makedirs(where, exist_ok=True)
        _mark_left_behind(where)
        _prune(where)
        _path = os.path.join(where, f"crash-{_now():%Y%m%d-%H%M%S}-{os.getpid()}.txt")
        _fh = open(_path, "a", encoding="utf-8")
        _fh.write(system_info() + "\n\n-- what the program did:\n")
        _fh.flush()
        faulthandler.enable(_fh, all_threads=True)
    except OSError:
        _fh = _path = None
        return
    if _old_hooks is None:
        _old_hooks = (sys.excepthook, threading.excepthook, sys.unraisablehook)
        sys.excepthook = _on_exception
        threading.excepthook = _on_thread_exception
        sys.unraisablehook = _on_unraisable


def end():
    """Closed normally: no crash, no report."""
    global _fh, _path, _old_hooks
    if _fh is None:
        return
    faulthandler.disable()
    try:
        _fh.close()
        os.remove(_path)
    except OSError:
        pass
    _fh = _path = None
    if _old_hooks is not None:
        sys.excepthook, threading.excepthook, sys.unraisablehook = _old_hooks
        _old_hooks = None


def write_exception(kind, exc_type, exc, tb, where_from=""):
    """An exception nobody caught: a report of its own. Returns its path (None: not written)."""
    global _count
    if _dir is None:
        return None
    frames = traceback.extract_tb(tb)
    key = (getattr(exc_type, "__name__", str(exc_type)), frames[-1].filename if frames else "", frames[-1].lineno if frames else 0)
    with _lock:
        if key in _seen or _count >= MAX_EXCEPTIONS:
            return None
        _seen.add(key)
        _count += 1
        n = _count
    path = os.path.join(_dir, f"exception-{_now():%Y%m%d-%H%M%S}-{os.getpid()}-{n}.txt")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(system_info() + f"\n\n-- {kind}{(' in ' + where_from) if where_from else ''}:\n")
            fh.write("".join(traceback.format_exception(exc_type, exc, tb)))
            fh.write("\n-- what the program did:\n" + "\n".join(_events) + "\n")
    except OSError:
        return None
    return path


def _on_exception(exc_type, exc, tb):
    if not issubclass(exc_type, KeyboardInterrupt):
        write_exception("an exception nobody caught", exc_type, exc, tb)
    (_old_hooks[0] if _old_hooks else sys.__excepthook__)(exc_type, exc, tb)


def _on_thread_exception(args):
    write_exception("an exception nobody caught", args.exc_type, args.exc_value, args.exc_traceback,
                    f"thread {args.thread.name if args.thread else '?'}")
    if _old_hooks:
        _old_hooks[1](args)


def _on_unraisable(args):
    if args.exc_type is not None:
        write_exception("an exception that could not be raised", args.exc_type, args.exc_value, args.exc_traceback,
                        repr(args.object) if args.object is not None else "")
    if _old_hooks:
        _old_hooks[2](args)
