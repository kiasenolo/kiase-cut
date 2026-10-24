"""The fonts installed on this computer, for the text font picker.

Text is drawn with the font *file* (textlayout.py), so the list holds files: for each the
family and style names read from it. Reading a few hundred fonts takes a moment, so the
program does it once in the background and keeps the result (fonts.json in its data folder).
"""
import json
import os
import sys

from PIL import ImageFont

EXTS = {".ttf", ".otf", ".ttc", ".otc"}
CACHE_DAYS = 7


def font_dirs():
    out = []
    if sys.platform == "win32":
        out.append(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
        local = os.environ.get("LOCALAPPDATA")
        if local:
            out.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    elif sys.platform == "darwin":
        out += ["/System/Library/Fonts", "/Library/Fonts", os.path.expanduser("~/Library/Fonts")]
    else:
        out += ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts"),
                os.path.expanduser("~/.local/share/fonts")]
    return [d for d in out if os.path.isdir(d)]


def describe(path):
    """{path, family, style, name} of a font file, or None when it cannot be read."""
    try:
        family, style = ImageFont.truetype(path, 20, index=0).getname()
    except (OSError, ValueError):
        return None
    style = style or ""
    name = family if style.lower() in ("", "regular", "normal") else f"{family} {style}"
    return {"path": path.replace("\\", "/"), "family": family, "style": style, "name": name}


def scan(dirs=None, progress=None, cancelled=lambda: False):
    """All fonts under the font folders, sorted by name (worker thread)."""
    files = []
    for d in dirs or font_dirs():
        for base, _, names in os.walk(d):
            files += [os.path.join(base, n) for n in names if os.path.splitext(n)[1].lower() in EXTS]
    out, seen = [], set()
    for i, p in enumerate(files):
        if cancelled():
            break
        info = describe(p)
        if info and info["name"].lower() not in seen:
            seen.add(info["name"].lower())
            out.append(info)
        if progress and i % 20 == 0:
            progress((i + 1) / len(files))
    return sorted(out, key=lambda f: f["name"].lower())


def load_cache(file, now):
    """The saved list when it is recent enough, else None."""
    try:
        with open(file, encoding="utf-8") as fh:
            data = json.load(fh)
        if now - data["time"] < CACHE_DAYS * 86400 and data["fonts"] and os.path.exists(data["fonts"][0]["path"]):
            return data["fonts"]
    except (OSError, ValueError, KeyError, IndexError):
        pass
    return None


def save_cache(file, fonts, now):
    try:
        os.makedirs(os.path.dirname(file), exist_ok=True)
        with open(file, "w", encoding="utf-8") as fh:
            json.dump({"time": now, "fonts": fonts}, fh, ensure_ascii=False)
    except OSError:
        pass
