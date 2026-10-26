"""How much memory the app uses and how much the system has left, for the export's progress
window (an export that asks for too much can take the whole system down with it).

used(): the resident memory of this process and every process it started (the MLT engine,
ffmpeg, the video readers). available(): (bytes free, bytes in all). Either is None where
the system does not say (Linux reads /proc, Windows asks the kernel; elsewhere: nothing).
"""
import ctypes
import os
import sys


def _linux_children():
    """{parent pid: [child pids]} of every process."""
    kids = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat", "rb") as f:
                stat = f.read()
        except OSError:
            continue
        ppid = int(stat[stat.rfind(b")") + 2:].split()[1])     # (the name may hold spaces and brackets)
        kids.setdefault(ppid, []).append(int(name))
    return kids


def _linux_rss(pid):
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 0


def _tree(root, kids):
    out, todo = [], [root]
    while todo:
        pid = todo.pop()
        out.append(pid)
        todo += kids.get(pid, [])
    return out


if sys.platform == "win32":
    from ctypes import wintypes

    class _MEMSTATUS(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    class _COUNTERS(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

    class _ENTRY(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _psapi = ctypes.WinDLL("psapi", use_last_error=True)
    _k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _k32.OpenProcess.restype = wintypes.HANDLE

    def _win_children():
        kids = {}
        snap = _k32.CreateToolhelp32Snapshot(0x2, 0)          # TH32CS_SNAPPROCESS
        if not snap or snap == wintypes.HANDLE(-1).value:
            return kids
        try:
            e = _ENTRY()
            e.dwSize = ctypes.sizeof(e)
            ok = _k32.Process32First(snap, ctypes.byref(e))
            while ok:
                kids.setdefault(e.th32ParentProcessID, []).append(e.th32ProcessID)
                ok = _k32.Process32Next(snap, ctypes.byref(e))
        finally:
            _k32.CloseHandle(snap)
        return kids

    def _win_rss(pid):
        h = _k32.OpenProcess(0x1000 | 0x0010, False, pid)     # QUERY_LIMITED_INFORMATION | VM_READ
        if not h:
            return 0
        try:
            c = _COUNTERS()
            c.cb = ctypes.sizeof(c)
            return c.WorkingSetSize if _psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb) else 0
        finally:
            _k32.CloseHandle(h)


def used():
    """Bytes of memory this process and the processes it started hold; None if unknown."""
    try:
        if sys.platform.startswith("linux"):
            return sum(_linux_rss(p) for p in _tree(os.getpid(), _linux_children()))
        if sys.platform == "win32":
            return sum(_win_rss(p) for p in _tree(os.getpid(), _win_children()))
    except Exception:
        pass
    return None


def available():
    """(bytes the system can still give, bytes in all); None if unknown."""
    try:
        if sys.platform.startswith("linux"):
            info = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, v = line.split(":", 1)
                    info[k] = int(v.split()[0]) * 1024
            return info["MemAvailable"], info["MemTotal"]
        if sys.platform == "win32":
            s = _MEMSTATUS()
            s.dwLength = ctypes.sizeof(s)
            if _k32.GlobalMemoryStatusEx(ctypes.byref(s)):
                return s.ullAvailPhys, s.ullTotalPhys
    except Exception:
        pass
    return None


class Guard:
    """Says when the system's free memory has fallen too low to go on: below 5% of it
    (at least 512 MB, at most 1 GB), or below half of what was free when the guard was
    made, if that was already less (so a system that starts low is not stopped at once)."""
    def __init__(self):
        a = available()
        self.floor = None if a is None else min(max(a[1] * 0.05, 512 * 2 ** 20), 2 ** 30, a[0] / 2)

    def low(self):
        """(bytes free, bytes in all) when free memory is under the floor, else None."""
        if self.floor is None:
            return None
        a = available()
        return a if a is not None and a[0] < self.floor else None


def gb(n):
    """n bytes as a short text: 512 MB, 3.4 GB."""
    return f"{n / 2 ** 30:.1f} GB" if n >= 2 ** 30 else f"{n / 2 ** 20:.0f} MB"
