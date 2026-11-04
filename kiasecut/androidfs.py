"""Android's shared storage: where the user's videos and projects are, and whether this app may read them.

The system's own file chooser gives content:// addresses, which neither ffmpeg nor the project files can use, so the app
uses Qt's own file dialog (ui/androidfiles.py) on real paths - which needs "all files access" (MANAGE_EXTERNAL_STORAGE),
a switch the user turns on once in the app's settings page."""
import os

SHARED = "/storage/emulated/0"
FOLDERS = ("DCIM", "Movies", "Download", "Pictures", "Music", "Documents")


def can_read():
    """Whether the app may list the shared storage (DCIM is always there on a phone or tablet)."""
    try:
        os.listdir(os.path.join(SHARED, "DCIM"))
        return True
    except OSError:
        return False


def documents():
    """The Documents folder of the shared storage (where projects go by default), or None without access to it."""
    path = os.path.join(SHARED, "Documents")
    return path if can_read() and (os.path.isdir(path) or _make(path)) else None


def _make(path):
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except OSError:
        return False


def sidebar():
    """The folders the file dialog offers on its left."""
    return [os.path.join(SHARED, f) for f in ("",) + FOLDERS if os.path.isdir(os.path.join(SHARED, f))]


HOW_TO_ALLOW = ("KiaseCut 需要「管理所有檔案」的權限才能讀你的影片和存專案。\n\n"
                "到 設定 > 應用程式 > KiaseCut > 權限（或「特殊應用程式存取權」）> 檔案和媒體 / 所有檔案存取權，"
                "把 KiaseCut 打開，再回來。")
