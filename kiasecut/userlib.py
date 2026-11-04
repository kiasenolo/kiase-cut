"""The user's own Library: one folder shared by every project.

    <Library>/              default: Documents/KiaseCut/Library (the user can move it in the settings)
        videos/  images/  sounds/     media the user keeps for reuse
        filters/                       filter files (.glsl, see filters/FORMAT.md)
        textstyles/                    saved text looks (.json)
        compounds/                     saved compounds (.kccomp): transitions, titles, …
            .media/                    files they use that were not in the Library (hidden)
        presets/                       效果預設: chains of effects made up already (.kcfx), a few to start

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
              ("textstyles", "文字樣式"), ("compounds", "複合片段"), ("presets", "效果預設"))
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".ts", ".mts"}
SOUND_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
EXTS = {"videos": VIDEO_EXT, "images": library.IMAGE_EXT, "sounds": SOUND_EXT,
        "filters": {".glsl"}, "textstyles": {".json"}, "compounds": {".kccomp"}, "presets": {".kcfx"}}
COMPOUND_EXT = ".kccomp"
PRESET_EXT = ".kcfx"
STARTER_PRESETS = (                 # (name, [(filter, its params)]): put in a new Library's presets/
    ("復古錄影帶", [("builtin:vhs", {}), ("builtin:grain", {}), ("builtin:vignette", {})]),
    ("電影感", [("builtin:split_tone", {}), ("builtin:grain", {"amount": 0.15}), ("builtin:letterbox", {})]),
    ("夢幻光暈", [("builtin:glow", {}), ("builtin:light_leak", {})]),
    ("老電視", [("builtin:crt", {}), ("builtin:rgb_shift", {}), ("builtin:scanlines", {})]),
    ("黑白老片", [("builtin:grayscale", {}), ("builtin:old_film", {})]),
)
COMPOUND_MEDIA = ".media"       # (a hidden folder: not listed in the Library)
INDEX = ".index.json"


def default_root(documents):
    return os.path.join(documents, APP_FOLDER, "Library").replace("\\", "/")


def category_dir(root, key):
    return library.norm(os.path.join(root, key))


EXAMPLE = "Example.glsl.txt"     # not .glsl, so the example is not listed (and used) as a filter


def ensure_layout(root):
    """Create the category folders, and put the filter format notes and an example filter
    where people look for them."""
    for key, _ in CATEGORIES:
        new = not os.path.isdir(category_dir(root, key))
        os.makedirs(category_dir(root, key), exist_ok=True)
        if new and key == "presets":                     # (once: the user may delete them)
            for name, chain in STARTER_PRESETS:
                save_preset(category_dir(root, key), name, [{"filter": ref, "params": params} for ref, params in chain],
                            root)
    from . import fx
    folder = category_dir(root, "filters")
    for name, src in (("FORMAT.md", fx.DOC_PATH), (EXAMPLE, fx.TEMPLATE_PATH)):
        dst = os.path.join(folder, name)
        if not os.path.exists(dst) and os.path.exists(src):
            shutil.copyfile(src, dst)
    old = os.path.join(folder, "Example.glsl")      # older versions put the example in as a filter
    try:
        with open(old, "rb") as a, open(fx.TEMPLATE_PATH, "rb") as b:
            untouched = a.read() == b.read()
        if untouched:
            os.remove(old)
    except OSError:
        pass


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
        elif ext == COMPOUND_EXT:
            info = {"kind": "compound"}
        elif ext == PRESET_EXT:
            info = {"kind": "preset"}
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
STYLE_FIELDS = ("font_path", "size", "color", "fill", "stroke_on", "stroke_color", "stroke", "stroke_align",
                "letter_spacing", "line_spacing", "italic_deg", "align", "shadow_on", "shadow_color", "shadow_x",
                "shadow_y", "shadow_blur", "bg_on", "bg_color", "bg_pad", "bg_pad_l", "bg_pad_r", "bg_pad_t", "bg_pad_b", "bg_radius")


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
    project.legacy_text_padding(d["text"])
    return d


# -- compounds ---------------------------------------------------------------------------------------
def compound_deps(proj, kid):
    """kid and every compound it shows, inside it as deep as they go (each once, kid first)."""
    out, todo = [], [kid]
    while todo:
        k = todo.pop(0)
        if k in out:
            continue
        if k.startswith("tl"):
            raise ValueError("複合片段裡面用到了時間線，不能存到 Library")
        out.append(k)
        for c in project.walk_clips(proj["compounds"][k]["tracks"]):
            if c.get("timeline_id"):
                todo.append(c["timeline_id"])
            todo += [h["compound_id"] for h in project.compound_holders(c)
                     if h["compound_id"] in proj["compounds"]]          # (masks and effect sources too)
    return out


def save_compound(root, folder, name, proj, kid):
    """Save compound kid of proj (with the compounds it shows) as a .kccomp file in folder of
    the Library's compounds. Files it uses that are not in the Library are copied into
    compounds/.media, so it works in any project and on another computer with the Library."""
    import hashlib
    root = library.norm(root)
    stored = project.inline_vfx(json.loads(project.dumps(proj))["compounds"], proj)
    comps = {k: stored[k] for k in compound_deps(proj, kid)}
    store = os.path.join(category_dir(root, "compounds"), COMPOUND_MEDIA)
    copied = {}

    def keep(path):
        p = library.norm(path)
        if library.within(p, root) or not os.path.isfile(p):
            return p                                     # (in the Library already, or missing)
        if p not in copied:
            st = os.stat(p)
            tag = hashlib.sha1(f"{p}|{st.st_size}|{st.st_mtime}".encode()).hexdigest()[:10]
            dst = os.path.join(store, tag, os.path.basename(p))
            if not os.path.exists(dst):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(p, dst)
            copied[p] = library.norm(dst)
        return copied[p]

    def portable(p):                                     # "@library/…" inside the Library
        p = library.norm(p)
        return project.LIB_TAG + p[len(root) + 1:] if library.within(p, root) else p
    pack = {"format": "kiasecut-compound", "root": kid, "name": name, "compounds": comps}
    project._map_paths(pack, lambda p: portable(keep(p)))
    name = workspace.safe_name(name, "複合片段")
    os.makedirs(folder, exist_ok=True)
    dst = os.path.join(folder, library.unique_name(folder, name + COMPOUND_EXT))
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(pack, fh, ensure_ascii=False, indent=1)
    return dst


def load_compound(path):
    """A saved compound (save_compound) with its paths made absolute again; "source" says
    which file (and version of it) it came from."""
    with open(path, encoding="utf-8") as fh:
        pack = json.load(fh)
    if pack.get("format") != "kiasecut-compound" or pack.get("root") not in (pack.get("compounds") or {}):
        raise ValueError("不是複合片段檔")
    project._map_paths(pack, lambda p: project.to_abs(p, os.path.dirname(path)))
    st = os.stat(path)
    pack["source"] = f"{library.norm(path)}|{st.st_size}|{round(st.st_mtime, 2)}"
    return pack


# -- 效果預設 ---------------------------------------------------------------------------------------
def _effect_holder(effects):
    """effects in the shape project._map_paths walks (one clip's)."""
    return {"tracks": [{"id": "t", "kind": "video", "clips": [{"id": "x", "type": "image", "effects": effects}]}]}


def save_preset(folder, name, effects, root=None):
    """A chain of effects (as clips keep them: filter, params, mask, mix, sources) as a .kcfx file
    in folder; files inside the Library (root) are stored as @library/… so it moves with it."""
    effects = json.loads(json.dumps([{k: v for k, v in e.items() if k != "id"} for e in effects]))
    if root:
        root = library.norm(root)
        project._map_paths(_effect_holder(effects), lambda p: project.LIB_TAG + library.norm(p)[len(root) + 1:]
                           if library.within(library.norm(p), root) else p)
    name = workspace.safe_name(name, "效果預設")
    os.makedirs(folder, exist_ok=True)
    dst = os.path.join(folder, library.unique_name(folder, name + PRESET_EXT))
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump({"format": "kiasecut-preset", "effects": effects}, fh, ensure_ascii=False, indent=1)
    return dst


def load_preset(path):
    """The effects of a .kcfx file, ready to go on a clip: every one complete (a filter's
    parameters it leaves out at their defaults) and its paths absolute."""
    from . import fx
    with open(path, encoding="utf-8") as fh:
        pack = json.load(fh)
    if pack.get("format") != "kiasecut-preset" or not isinstance(pack.get("effects"), list):
        raise ValueError("不是效果預設檔")
    effects = pack["effects"]
    project._map_paths(_effect_holder(effects), lambda p: project.to_abs(p, os.path.dirname(path)))
    out = []
    for e in effects:
        if not e.get("filter"):
            continue
        full = fx.new_effect(e["filter"], "")
        full["params"].update(e.get("params") or {})
        full.update({k: v for k, v in e.items() if k not in ("params", "id")})
        out.append(full)
    if not out:
        raise ValueError("這個預設沒有效果")
    return out


# -- sorting files into categories ------------------------------------------------------------------
def category_for(path, prefer=None):
    """Which category a file belongs to by its extension (None: not for the Library). `prefer`
    wins when the file fits it, and is the only way a .json file counts (as a text style)."""
    ext = os.path.splitext(path)[1].lower()
    if prefer and ext in EXTS[prefer]:
        return prefer
    for key in ("videos", "images", "sounds", "filters", "compounds", "presets"):
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
