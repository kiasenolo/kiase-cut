"""Autosave and recovery after the program ended unexpectedly (a crash, a power cut).

Every few minutes (設定 > 自動存檔間隔) a project with unsaved changes is written to the
autosave folder, ~/Documents/KiaseCut/auto-save, as "<project> <date time>.kiasecut.json"
(media paths absolute, so it opens from there); the newest LIMIT of them are kept (設定 >
自動存檔上限). The project file itself is left alone.

Each running program keeps a session file there, session-<pid>.json: {pid, started, project
(its file, or None), autosave (the newest autosave of unsaved changes, or None once saved)}.
Closing normally removes it. One left behind by a program that is no longer running means
that program ended unexpectedly: when its autosave is there, the next start offers to bring
it back (crashed()).

Python's own record of a crash (faulthandler: every thread's stack) is appended to
crash.log beside the autosaves.
"""
import datetime
import faulthandler
import json
import os
import sys

from . import project

SUBDIR = os.path.join("KiaseCut", "auto-save")
EXT = ".kiasecut.json"
LIMIT = 30                       # autosave files kept (the setting's default)
LOG_MAX = 1 << 20                # crash.log is started again past this size
_log = None


def folder(documents):
    return os.path.join(documents, SUBDIR)


def _session_file(where, pid=None):
    return os.path.join(where, f"session-{pid or os.getpid()}.json")


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def alive(pid):
    """Whether a process with this id is running."""
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259           # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:                              # someone else's: running
        return True
    return True


def begin(where):
    """This program has started: its session file, and crash.log taking crashes."""
    global _log
    os.makedirs(where, exist_ok=True)
    note(where, project=None, autosave=None)
    log = os.path.join(where, "crash.log")
    try:
        if os.path.exists(log) and os.path.getsize(log) > LOG_MAX:
            os.remove(log)
        _log = open(log, "a", encoding="utf-8")
        _log.write(f"\n== KiaseCut started {datetime.datetime.now():%Y-%m-%d %H:%M:%S} (pid {os.getpid()})\n")
        _log.flush()
        faulthandler.enable(_log, all_threads=True)
    except OSError:
        _log = None


def note(where, **fields):
    """Update this program's session file (project, autosave)."""
    path = _session_file(where)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {"pid": os.getpid(), "started": datetime.datetime.now().isoformat(timespec="seconds"),
                "project": None, "autosave": None}
    data.update(fields)
    try:
        _write_json(path, data)
    except OSError:
        pass


def end(where):
    """Closed normally: nothing to recover."""
    global _log
    try:
        os.remove(_session_file(where))
    except OSError:
        pass
    if _log is not None:
        faulthandler.disable()
        _log.close()
        _log = None


def sessions(where):
    """Every session file there: [(its path, its data)]."""
    out = []
    try:
        names = os.listdir(where)
    except OSError:
        return out
    for n in names:
        if n.startswith("session-") and n.endswith(".json"):
            p = os.path.join(where, n)
            try:
                with open(p, encoding="utf-8") as fh:
                    data = json.load(fh)
                int(data["pid"])
            except (OSError, ValueError, KeyError, TypeError):
                continue
            out.append((p, data))
    return out


def crashed(where):
    """Sessions of programs that ended without closing and left unsaved changes behind,
    newest autosave first: [(session file, data)]. Those that left nothing are forgotten."""
    out = []
    for p, data in sessions(where):
        if alive(int(data["pid"])):
            continue
        save = data.get("autosave")
        if save and os.path.exists(save):
            out.append((p, data))
        else:
            forget(p)
    return sorted(out, key=lambda s: os.path.getmtime(s[1]["autosave"]), reverse=True)


def forget(session_file):
    try:
        os.remove(session_file)
    except OSError:
        pass


def stem(project_path):
    if not project_path:
        return "未命名專案"
    name = os.path.basename(project_path)
    for e in (EXT, ".tesetoa.json", ".json"):
        if name.endswith(e):
            return name[:-len(e)]
    return name


def autosave(where, proj, project_path, limit=LIMIT):
    """Write proj to a new autosave file; returns its path. Older ones past limit go."""
    os.makedirs(where, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    path = os.path.join(where, f"{stem(project_path)} {stamp}{EXT}")
    project.save(proj, path)
    note(where, project=project_path, autosave=path)
    prune(where, limit)
    return path


def files(where):
    """The autosave files, newest first."""
    try:
        names = [n for n in os.listdir(where) if n.endswith(EXT)]
    except OSError:
        return []
    paths = [os.path.join(where, n) for n in names]
    return sorted(paths, key=os.path.getmtime, reverse=True)


def prune(where, limit):
    """Keep the newest `limit` autosaves - and every one a session may still need."""
    keep = {os.path.abspath(d["autosave"]) for _p, d in sessions(where) if d.get("autosave")}
    for path in files(where)[max(1, int(limit)):]:
        if os.path.abspath(path) not in keep:
            try:
                os.remove(path)
            except OSError:
                pass
