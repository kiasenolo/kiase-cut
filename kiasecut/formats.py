"""Export formats: containers, codecs and what each can carry (a picture with alpha, sound).

Every format but the default MP4 / H.264 is encoded by ffmpeg from frames of the live
renderer (renderexport.py); MP4 / H.264 keeps the MLT export when the project allows it.
A format is a row of FORMATS; its video and audio encoder arguments come from video_args
and audio_args. Quality is the export dialog's {crf, preset}: each codec maps it its way.
"""
from . import gpu

STEM_FORMATS = ("wav", "flac", "mp3", "m4a")      # what a stem file (one track's sound) can be


class Format:
    def __init__(self, key, label, ext, kind="video", alpha=None, audio=None, quality=True, gpu_codec=None):
        """kind: video, audio (sound only), gif or sequence (a folder of pictures).
        alpha: None when the format has no alpha, else whether transparency is on by default.
        audio: the audio codec in this container (None: the format has no sound)."""
        self.key, self.label, self.ext, self.kind = key, label, ext, kind
        self.alpha, self.audio, self.quality, self.gpu_codec = alpha, audio, quality, gpu_codec

    @property
    def has_video(self):
        return self.kind != "audio"

    @property
    def can_alpha(self):
        return self.alpha is not None

    @property
    def multitrack(self):
        """Whether the container holds several sound streams (each track's, besides the mix)."""
        return self.kind == "video" and self.audio is not None


FORMATS = (
    Format("mp4_h264", "MP4 · H.264（最通用）", ".mp4", audio="aac", gpu_codec="h264_nvenc"),
    Format("mp4_h265", "MP4 · H.265 / HEVC（檔案較小）", ".mp4", audio="aac", gpu_codec="hevc_nvenc"),
    Format("mov_prores", "MOV · ProRes 422（剪輯用）", ".mov", audio="pcm_s16le"),
    Format("mov_prores4444", "MOV · ProRes 4444（透明）", ".mov", alpha=True, audio="pcm_s16le", quality=False),
    Format("mov_qtrle", "MOV · Animation（透明，無損）", ".mov", alpha=True, audio="pcm_s16le", quality=False),
    Format("mov_png", "MOV · PNG（透明，無損）", ".mov", alpha=True, audio="pcm_s16le", quality=False),
    Format("webm_vp9", "WebM · VP9（網頁用，可透明）", ".webm", alpha=False, audio="libopus"),
    Format("mkv_ffv1", "MKV · FFV1（無損封存）", ".mkv", alpha=False, audio="flac", quality=False),
    Format("gif", "GIF 動圖", ".gif", kind="gif", quality=False),
    Format("png_seq", "PNG 圖片序列（透明）", ".png", kind="sequence", alpha=True, quality=False),
    Format("wav", "WAV 音訊（無損）", ".wav", kind="audio", audio="pcm_s16le", quality=False),
    Format("flac", "FLAC 音訊（無損壓縮）", ".flac", kind="audio", audio="flac", quality=False),
    Format("mp3", "MP3 音訊", ".mp3", kind="audio", audio="libmp3lame", quality=False),
    Format("m4a", "M4A / AAC 音訊", ".m4a", kind="audio", audio="aac", quality=False),
)
BY_KEY = {f.key: f for f in FORMATS}
DEFAULT = "mp4_h264"
EXTS = sorted({f.ext for f in FORMATS})


def get(key):
    return BY_KEY.get(key) or BY_KEY[DEFAULT]


def audio_args(codec):
    """ffmpeg arguments for a sound stream encoded with codec."""
    if codec == "aac":
        return ["-c:a", "aac", "-b:a", "320k"]
    if codec == "libmp3lame":
        return ["-c:a", "libmp3lame", "-b:a", "320k"]
    if codec == "libopus":
        return ["-c:a", "libopus", "-b:a", "256k"]
    return ["-c:a", codec]                     # pcm_s16le, flac: lossless


def stem_codec(ext):
    """The audio codec of a stem file with extension ext (wav, flac, mp3, m4a)."""
    return get(ext.lstrip(".")).audio


def video_args(fmt, opts, size, alpha):
    """ffmpeg arguments that encode the picture (rgba frames in) as fmt; alpha: keep transparency."""
    crf = int(opts.get("crf", 18))
    k = fmt.key
    if k == "mp4_h264":
        return gpu.ffmpeg_video_args(opts, size)
    if k == "mp4_h265":
        if gpu.nvenc_for(size, "hevc"):
            return ["-c:v", "hevc_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", str(gpu.cq(crf) + 2),
                    "-b:v", "0", "-pix_fmt", "yuv420p", "-tag:v", "hvc1"]
        return ["-c:v", "libx265", "-crf", str(crf + 4), "-preset", opts.get("preset", "medium"),
                "-pix_fmt", "yuv420p", "-tag:v", "hvc1", "-x265-params", "log-level=error"]
    if k == "mov_prores":
        profile = 3 if crf <= 16 else 2 if crf <= 20 else 1         # HQ, 422, LT
        return ["-c:v", "prores_ks", "-profile:v", str(profile), "-vendor", "apl0", "-pix_fmt", "yuv422p10le"]
    if k == "mov_prores4444":
        return ["-c:v", "prores_ks", "-profile:v", "4", "-vendor", "apl0",
                *(["-pix_fmt", "yuva444p10le", "-alpha_bits", "16"] if alpha else ["-pix_fmt", "yuv444p10le"])]
    if k == "mov_qtrle":
        return ["-c:v", "qtrle", "-pix_fmt", "argb" if alpha else "rgb24"]
    if k == "mov_png":
        return ["-c:v", "png", "-pix_fmt", "rgba" if alpha else "rgb24"]
    if k == "webm_vp9":
        return ["-c:v", "libvpx-vp9", "-crf", str(round(crf * 1.25 + 8)), "-b:v", "0", "-row-mt", "1",
                "-deadline", "good", "-cpu-used", "2", "-pix_fmt", "yuva420p" if alpha else "yuv420p"]
    if k == "mkv_ffv1":
        return ["-c:v", "ffv1", "-level", "3", "-pix_fmt", "bgra" if alpha else "yuv444p"]
    if k == "gif":
        return ["-filter_complex", "[0:v]split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a",
                "-loop", "0"]
    if k == "png_seq":
        return ["-c:v", "png", "-pix_fmt", "rgba" if alpha else "rgb24", "-start_number", "0"]
    raise ValueError(f"not a picture format: {k}")


def encoder_name(fmt, size):
    """For the export's report: which encoder made the picture."""
    if fmt.key == "mp4_h264":
        return "NVENC (GPU)" if gpu.nvenc_for(size) else "x264 (CPU)"
    if fmt.key == "mp4_h265":
        return "NVENC HEVC (GPU)" if gpu.nvenc_for(size, "hevc") else "x265 (CPU)"
    return fmt.label.split("（")[0]
