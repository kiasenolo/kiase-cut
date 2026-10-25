"""GPU acceleration: what this computer's graphics card can do for us, and the switch for it.

Two jobs go to an NVIDIA card when there is one (and `enabled` is on, the 設定 switch):
  * encoding exports with NVENC (h264_nvenc) instead of x264 - several times faster;
  * decoding and scaling heavy videos (HEVC, AV1, VP9) in videoreader.py with CUDA, where
    the CPU is slow (for H.264 the CPU is faster here, so it stays there).
Filters already run on the GPU (fx.py). Everything falls back to the CPU on its own when
the card or its driver cannot do a job, so this never stops an export or the preview.
"""
import subprocess
import threading

from .build import find_ffmpeg

enabled = True                       # the user's switch (設定 > GPU 加速)
HEAVY_CODECS = {"hevc", "h265", "av1", "vp9"}
NVENC_MAX = 4096                     # NVENC's largest H.264 picture side
_lock = threading.Lock()
_found = {}                          # job -> bool, tested once per run


def _works(job, args):
    with _lock:
        if job not in _found:
            ffmpeg = find_ffmpeg()
            ok = False
            if ffmpeg:
                try:
                    r = subprocess.run([ffmpeg, "-v", "error", *args], capture_output=True, timeout=30,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    ok = r.returncode == 0
                except (OSError, subprocess.SubprocessError):
                    ok = False
            _found[job] = ok
        return _found[job]


def nvenc(codec="h264"):
    """Whether ffmpeg can encode H.264 (or codec: hevc) on an NVIDIA card here."""
    return enabled and _works("nvenc" if codec == "h264" else "nvenc_" + codec,
                              ["-f", "lavfi", "-i", "color=black:s=256x256:d=0.1", "-c:v", codec + "_nvenc",
                               "-f", "null", "-"])


def cuda():
    """Whether ffmpeg can decode and scale on an NVIDIA card here."""
    return enabled and _works("cuda", ["-init_hw_device", "cuda", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
                                       "-f", "null", "-"])


def decode_on_gpu(codec):
    return codec in HEAVY_CODECS and cuda()


def cq(crf):
    """NVENC's constant quality for an x264 CRF (NVENC needs a little more for the same look)."""
    return max(0, min(51, int(crf) + 2))


def nvenc_for(size, codec="h264"):
    return max(size) <= NVENC_MAX and nvenc(codec)


def ffmpeg_video_args(opts, size):
    """ffmpeg video encoder arguments for export options {crf, preset} at size (w, h)."""
    crf = opts.get("crf", 18)
    if nvenc_for(size):
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", str(cq(crf)),
                "-b:v", "0", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-crf", str(crf), "-preset", opts.get("preset", "medium"), "-pix_fmt", "yuv420p"]


def mlt_video_opts(opts, size):
    """Encoder properties for the MLT export (engine.py) with NVENC, or None to use x264."""
    if not nvenc_for(size):
        return None
    return {"vcodec": "h264_nvenc", "preset": "p5", "rc": "vbr", "cq": cq(opts.get("crf", 18)), "vb": 0}


def describe():
    """A line for the export dialog and the settings: which jobs the GPU does."""
    if not enabled:
        return "GPU 加速已關閉（設定）"
    jobs = (["匯出編碼 NVENC"] if nvenc() else []) + (["HEVC / AV1 / VP9 解碼"] if cuda() else [])
    return "GPU：" + "、".join(jobs) if jobs else "沒有可用的 NVIDIA GPU：使用 CPU"
