"""The fonts installed on this computer, for the text font picker, and the font map.

Text is drawn with the font *file* (textlayout.py), so the list holds files: for each the
family and style names read from it. Reading a few hundred fonts takes a moment, so the
program does it once in the background and keeps the result (fonts.json in its data folder).

Font map: a project made on Windows names Windows font files, which Linux does not have (and
the other way round). project["font_map"] = {os_key(): {font file: font file to use}} says,
for each operating system on its own, which installed font stands in for a missing one;
clips keep the font they name, so each system draws with its own. use_map() makes this
system's part current; resolve() is what text drawing asks (textlayout.font), and map_key()
goes into every cache of drawn text, so a new choice is drawn at once.
"""
import json
import os
import re
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


# -- font map ----------------------------------------------------------------------------------------
_map = {}
_map_key = ""


def os_key():
    """This operating system's part of project["font_map"]."""
    return "windows" if sys.platform == "win32" else "mac" if sys.platform == "darwin" else "linux"


def norm(path):
    return path.replace("\\", "/") if isinstance(path, str) else path


def use_map(mapping):
    """Make {font file: stand-in file} this system's font map (resolve, map_key)."""
    global _map, _map_key
    clean = {norm(k): norm(v) for k, v in (mapping or {}).items() if isinstance(k, str) and isinstance(v, str) and v}
    _map, _map_key = clean, json.dumps(clean, sort_keys=True, ensure_ascii=False)


def map_key():
    """Text drawn with the current map (for cache keys)."""
    return _map_key


def resolve(path):
    """The font file to draw with: path itself when this system has it, else its stand-in
    from the font map, else path (textlayout then falls back to a default font)."""
    if not path or os.path.exists(path):
        return path
    return _map.get(norm(path), path)


def of_clip(c):
    """The font files a text clip names (keyframes and styled ranges too), as written with
    forward slashes."""
    from . import curves
    tx = c.get("text")
    if not tx:
        return set()
    p = tx.get("font_path")
    vals = [k[1] for k in p["keys"]] if curves.is_animated(p) else [p]
    vals += [st.get("font_path") for st in tx.get("styles") or []]
    return {norm(v) for v in vals if isinstance(v, str) and v}


def used(proj):
    """Every font file the project's texts name."""
    from . import project
    return set().union(*map(of_clip, project.all_clips(proj)))


def usage(proj):
    """{font file: how many texts use it}."""
    from . import project
    out = {}
    for c in project.all_clips(proj):
        for f in of_clip(c):
            out[f] = out.get(f, 0) + 1
    return out


def missing(proj, mapping):
    """The fonts the project names that this system cannot draw with: not here and without a
    stand-in in mapping (one that is here)."""
    m = {norm(k): v for k, v in (mapping or {}).items()}
    return sorted(p for p in used(proj)
                  if not os.path.exists(p) and not (m.get(p) and os.path.exists(m[p])))


def _words(s):
    return [w for w in re.split(r"[^0-9a-z\u3400-\u9fff]+", s.lower()) if len(w) > 1]


# common fonts of one system and what usually stands in for them on the others (by file
# name stem -> font names to look for, in order)
KNOWN = {
    "msjh": ["noto sans cjk tc", "noto sans tc", "source han sans tc", "microsoft jhenghei", "noto sans cjk"],
    "msjhbd": ["noto sans cjk tc bold", "noto sans tc bold", "microsoft jhenghei bold", "noto sans cjk"],
    "msyh": ["noto sans cjk sc", "noto sans sc", "source han sans sc", "microsoft yahei", "noto sans cjk"],
    "msyhbd": ["noto sans cjk sc bold", "noto sans sc bold", "microsoft yahei bold", "noto sans cjk"],
    "mingliu": ["noto serif cjk tc", "noto serif tc", "ar pl uming", "mingliu", "noto serif cjk"],
    "simsun": ["noto serif cjk sc", "noto serif sc", "ar pl uming", "simsun", "noto serif cjk"],
    "simhei": ["noto sans cjk sc", "wenquanyi zen hei", "simhei", "noto sans cjk"],
    "kaiu": ["ar pl ukai", "tw-kai", "dfkai-sb", "noto serif cjk"],
    "arial": ["liberation sans", "arimo", "dejavu sans", "arial"],
    "times": ["liberation serif", "tinos", "dejavu serif", "times new roman"],
    "cour": ["liberation mono", "cousine", "dejavu sans mono", "courier new"],
    "segoeui": ["noto sans", "dejavu sans", "segoe ui"],
    "notosanscjk-regular": ["microsoft jhenghei", "microsoft yahei", "noto sans cjk"],
    "notoserifcjk-regular": ["mingliu", "simsun", "noto serif cjk"],
    "dejavusans": ["segoe ui", "arial", "dejavu sans"],
    "liberationsans-regular": ["arial", "liberation sans"],
}


def guess(path, installed, remembered=None):
    """An installed font (path) to stand in for the missing font file path: the one chosen for
    it before on this computer, one with the same file name, a usual stand-in (KNOWN), or one
    whose name shares most words with it; None when nothing fits."""
    have = {f["path"] for f in installed}
    old = (remembered or {}).get(norm(path))
    if old in have:
        return old
    base = os.path.basename(norm(path)).lower()
    for f in installed:
        if os.path.basename(f["path"]).lower() == base:
            return f["path"]
    for want in KNOWN.get(os.path.splitext(base)[0], ()):
        hit = next((f["path"] for f in installed if f["name"].lower() == want), None) or \
            next((f["path"] for f in installed if f["name"].lower().startswith(want)), None)
        if hit:
            return hit
    want = set(_words(os.path.splitext(base)[0]))
    best, score = None, 0
    for f in installed:
        n = len(want & set(_words(f["name"]) + _words(os.path.splitext(os.path.basename(f["path"]))[0])))
        if n > score:
            best, score = f["path"], n
    return best
