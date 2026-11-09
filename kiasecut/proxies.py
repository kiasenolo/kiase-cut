"""Preview proxies (預覽代理檔): a small, short-GOP copy of a long-GOP video that the preview reads when the playhead jumps.

A camera or screen-capture file keeps one key frame every few seconds (HEVC, 2.5 s = 250 frames in a test file). Showing a frame
after a jump means decoding from the key frame before it, so scrubbing such a file costs 0.2-0.3 s a picture, however little the
timeline does with it - a cut that changes nothing about the picture does not help. A copy made once with a key frame every
10 frames, at most 540 lines, with the same frame rate and time line, takes about 0.05 s a jump.

The preview only: videoreader.Readers(proxy_dir) asks for it, exports build their readers without and read the original. A proxy
is used only where the picture asked for is no bigger than it (the 預覽畫質 1/2× and 1/4× of a 1080 file; 1× reads the file), and only
once it is finished: it is made in the background, one file at a time, at low priority, written as `.part` and renamed.

Which files get one: pictures of 720 lines and more whose key frames are more than a second apart (read from the first half
minute). Nothing is made when the 設定 switch is off (`enabled`) or ffmpeg cannot.
"""
import hashlib
import os
import shutil
import subprocess
import threading

from .build import find_ffmpeg

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MAX_LINES = 540               # a proxy is at most this tall
MIN_LINES = 720               # smaller pictures decode fast enough
GOP_S = 1.0                   # key frames further apart than this make a file worth a proxy
GOP_FRAMES = 10               # the proxy's own
enabled = True                # the 設定 switch

_lock = threading.Lock()
_wanted = {}                  # path -> True (queued or made) / False (not worth it, or failed)
_queue = []                   # [(path, out, info, lines)]
_running = [False]


def key(path):
    st = os.stat(path)
    return hashlib.sha1(f"{path}|{st.st_size}|{st.st_mtime_ns}".encode("utf-8")).hexdigest()[:16]


def proxy_path(proxy_dir, path):
    try:
        return os.path.join(proxy_dir, f"video-{key(path)}.mp4")
    except OSError:
        return None


def _ffprobe():
    ff = find_ffmpeg() or "ffmpeg"
    p = os.path.join(os.path.dirname(ff), os.path.basename(ff).replace("ffmpeg", "ffprobe"))
    return p if os.path.exists(p) else "ffprobe"


def key_frame_gap(path, seconds=30):
    """The longest time between key frames in the first `seconds` of the file's picture (None: unknown)."""
    try:
        r = subprocess.run([_ffprobe(), "-v", "error", "-select_streams", "v:0", "-read_intervals", f"%+{seconds}",
                            "-skip_frame", "nokey", "-show_entries", "frame=pts_time", "-of", "csv=p=0", path],
                           capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW)
        ts = sorted(float(x) for x in r.stdout.split() if x.replace(".", "", 1).replace("-", "", 1).isdigit())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if len(ts) < 2:
        return None
    return max(b - a for a, b in zip(ts, ts[1:]))


def worth(inf, path):
    """Whether the file (videoreader.info) is worth a proxy."""
    if not inf or inf.get("alpha") or inf["h"] < MIN_LINES:
        return False
    gap = key_frame_gap(path)
    return gap is not None and gap > GOP_S


def command(path, out, fps, lines, matrix):
    """The ffmpeg command making the proxy: same frame rate and times, a key frame every GOP_FRAMES frames."""
    vf = f"scale=-2:{lines}:in_color_matrix={matrix}:out_color_matrix=bt709:out_range=tv,format=yuv420p"
    return [find_ffmpeg(), "-v", "error", "-nostdin", "-y", "-i", path, "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", vf,
            "-fps_mode", "cfr", "-r", f"{fps:.6f}", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "27",
            "-g", str(GOP_FRAMES), "-bf", "0", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-color_range", "tv", "-movflags", "+faststart", "-f", "mp4", out]


def _work():
    while True:
        with _lock:
            if not _queue:
                _running[0] = False
                return
            path, out, inf, lines = _queue.pop(0)
        part = out + ".part"
        try:
            if not worth(inf, path):                     # (looked at here: the preview does not wait for ffprobe)
                with _lock:
                    _wanted[path] = False
                continue
            os.makedirs(os.path.dirname(out), exist_ok=True)
            cmd = command(path, part, inf["fps"], lines, inf["matrix"])
            if shutil.which("nice"):
                cmd = ["nice", "-n", "15"] + cmd
            r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
            if r.returncode == 0 and os.path.getsize(part) > 0:
                os.replace(part, out)
            else:
                raise OSError("ffmpeg failed")
        except (OSError, subprocess.SubprocessError):
            with _lock:
                _wanted[path] = False
            try:
                os.remove(part)
            except OSError:
                pass


def request(proxy_dir, path, inf):
    """Make a proxy of `path` in the background if it is worth one and there is none (once per file and session).
    Returns the finished proxy's path and its (w, h), or None."""
    if not enabled or not proxy_dir or not inf:
        return None
    out = proxy_path(proxy_dir, path)
    if out is None:
        return None
    lines = min(MAX_LINES, inf["h"])
    size = (round(inf["w"] * lines / inf["h"] / 2) * 2, lines)
    if os.path.exists(out):
        return out, size
    with _lock:
        if path in _wanted:
            return None
        _wanted[path] = True
        _queue.append((path, out, inf, lines))
        if not _running[0]:
            _running[0] = True
            threading.Thread(target=_work, daemon=True).start()
    return None


def busy():
    """Whether a proxy is being made (or waits to be)."""
    with _lock:
        return _running[0]
