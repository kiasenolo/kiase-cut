"""The user's own Library: one folder shared by every project.

    <Library>/              default: Documents/KiaseCut/Library (the user can move it in the settings)
        videos/  images/  sounds/     media the user keeps for reuse
        filters/                       filter files (.glsl, see filters/FORMAT.md)
        textstyles/                    saved text looks (.json)

Inside a category the user can make folders as they like. A file inside the Library is not
copied into a project's Media folder: clips use it where it is (the project file stores it
as "@library/videos/x.mp4", so it follows the Library when that is moved or lives elsewhere
on another computer). Every category is a library mirror (see library.py): its folders are
directories, its items are files.
"""
import json
import os
import shutil

from . import library, project, workspace

APP_FOLDER = "KiaseCut"
CATEGORIES = (("videos", "影片"), ("images", "圖片"), ("sounds", "音效"), ("filters", "濾鏡"),
              ("textstyles", "文字樣式"))
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".ts", ".mts"}
SOUND_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
EXTS = {"videos": VIDEO_EXT, "images": library.IMAGE_EXT, "sounds": SOUND_EXT,
        "filters": {".glsl"}, "textstyles": {".json"}}
INDEX = ".index.json"


def default_root(documents):
    return os.path.join(documents, APP_FOLDER, "Library").replace("\\", "/")


def category_dir(root, key):
    return library.norm(os.path.join(root, key))


def ensure_layout(root):
    """Create the category folders, and put the filter format notes and an example filter
    where people look for them."""
    for key, _ in CATEGORIES:
        os.makedirs(category_dir(root, key), exist_ok=True)
    from . import fx
    folder = category_dir(root, "filters")
    for name, src in (("FORMAT.md", fx.DOC_PATH), ("Example.glsl", fx.TEMPLATE_PATH)):
        dst = os.path.join(folder, name)
        if not os.path.exists(dst) and os.path.exists(src):
            shutil.copyfile(src, dst)


def category_of(path, root):
    """Which category folder of the Library a path is in: its key, "" for elsewhere in the
    Library, None when it is not in the Library at all."""
    if not root or not library.within(path, library.norm(root)):
        return None
    rel = library.slash(library.norm(path))[len(library.norm(root)) + 1:]
    top = rel.split("/")[0]
    return top if top in dict(CATEGORIES) else ""


def inside(path, root):
    return category_of(path, root) is not None


# -- what is known about the files (probing a video takes a moment, so remember it) ---------------
class Prober:
    """probe() with a memory kept in <Library>/.index.json (path, size and time decide)."""

    def __init__(self, root):
        self.file = os.path.join(root, INDEX)
        try:
            with open(self.file, encoding="utf-8") as fh:
                self.cache = json.load(fh)
        except (OSError, ValueError):
            self.cache = {}
        self.dirty = False

    def __call__(self, path):
        st = os.stat(path)
        key = [st.st_size, round(st.st_mtime, 2)]
        hit = self.cache.get(path)
        if hit and hit["key"] == key:
            return dict(hit["info"])
        ext = os.path.splitext(path)[1].lower()
        if ext == ".glsl":
            info = {"kind": "filter"}
        elif ext == ".json":
            info = {"kind": "textstyle"}
        else:
            info = library.probe(path)
        self.cache[path] = {"key": key, "info": info}
        self.dirty = True
        return dict(info)

    def save(self):
        if self.dirty:
            try:
                with open(self.file, "w", encoding="utf-8") as fh:
                    json.dump(self.cache, fh)
            except OSError:
                pass
            self.dirty = False


class UserLibrary:
    """The Library as the program sees it: one mirror (library dict) per category."""

    def __init__(self, root):
        self.root = library.norm(root)
        self.cats = {}
        for key, _ in CATEGORIES:
            self.cats[key] = {"library": {"folders": [], "items": [], "prefix": "mu"}, "tracks": []}

    def mirror(self, key):
        return library.Mirror(category_dir(self.root, key))

    def lib(self, key):
        return self.cats[key]["library"]

    def proj(self, key):
        return self.cats[key]

    def find(self, item_id):
        """(category key, item) for an item id of any category, or (None, None)."""
        for key, _ in CATEGORIES:
            for it in self.lib(key)["items"]:
                if it["id"] == item_id:
                    return key, it
        return None, None

    def find_path(self, path):
        path = library.norm(path)
        for key, _ in CATEGORIES:
            for it in self.lib(key)["items"]:
                if it["path"] == path:
                    return key, it
        return None, None

    def scan(self, key, prober=None, known=None):
        """Worker thread: read a category's folder (`known`: paths already listed, taken on the UI thread)."""
        known = library.known_paths(self.cats[key]) if known is None else known
        prober = prober or Prober(self.root)
        res = library.scan(self.mirror(key), known, prober, EXTS[key])
        prober.save()
        return res

    def apply(self, key, res):
        return library.apply_scan(self.cats[key], self.mirror(key), res)

    def item_for_path(self, path):
        """An item dict for a file in the Library (probed now when it is not listed)."""
        key, it = self.find_path(path)
        if it is not None:
            return it
        info = Prober(self.root)(library.norm(path))
        return {"id": "mu" + library._id(""), "name": os.path.basename(path), "path": library.norm(path),
                "folder": None, **info}


# -- text styles ------------------------------------------------------------------------------------
STYLE_FIELDS = ("font_path", "size", "color", "letter_spacing", "line_spacing", "italic_deg")


def style_from_clip(clip):
    """The look of a text clip as a dict that can be saved and applied again."""
    tx = clip["text"]
    return {"format": "kiasecut-textstyle", "text": {k: tx[k] for k in STYLE_FIELDS if k in tx},
            "transform": {k: v for k, v in (clip.get("transform") or {}).items()
                          if k in ("scale", "scale_y")}}


def save_style(folder, name, clip):
    name = workspace.safe_name(name, "文字樣式")
    dst = os.path.join(folder, library.unique_name(folder, name + ".json"))
    os.makedirs(folder, exist_ok=True)
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(style_from_clip(clip), fh, ensure_ascii=False, indent=1)
    return dst


def load_style(path):
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    if d.get("format") not in ("kiasecut-textstyle", "tesetoa-textstyle") or not isinstance(d.get("text"), dict):
        raise ValueError("不是文字樣式檔")
    return d


# -- sorting files into categories ------------------------------------------------------------------
def category_for(path, prefer=None):
    """Which category a file belongs to by its extension (None: not for the Library). `prefer`
    wins when the file fits it, and is the only way a .json file counts (as a text style)."""
    ext = os.path.splitext(path)[1].lower()
    if prefer and ext in EXTS[prefer]:
        return prefer
    for key in ("videos", "images", "sounds", "filters"):
        if ext in EXTS[key]:
            return key
    return None


def expand(paths):
    """The files among dropped paths: folders are searched (hidden files left out)."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            for d, dirs, files in os.walk(p):
                dirs[:] = sorted(x for x in dirs if not x.startswith("."))
                out += [os.path.join(d, f) for f in sorted(files) if not f.startswith(".")]
        elif os.path.isfile(p):
            out.append(p)
    return out
