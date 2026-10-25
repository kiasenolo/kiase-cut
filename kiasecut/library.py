"""Media library: the files of the project's Media folder, organised in its sub-folders.

proj["library"] = {"folders": [{id, name, parent}], "items": [{id, name, path, kind, width,
height, duration_us, folder}]}. parent / folder is None at the top level. The library is a
mirror of <project folder>/Media (see "the Media folder" below): folders are directories,
items are files, and renaming, moving or deleting here does the same to the files. Imports
link files where they are; external_media() / collect() copy those into Media later. The
first group of functions only edits the dicts; the second one also touches the disk. Both raise edit.EditError on bad input.
"""
import json
import os
import shutil
import subprocess
import uuid

from PIL import Image

from . import edit, project, svgimage, workspace

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff", ".svg"}
IMAGE_DEFAULT_US = 5_000_000
MEDIA_EXT = IMAGE_EXT | {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".ts", ".mts",
                         ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}


def media_files(paths):
    """The media files among dropped paths: folders are searched, other files are skipped."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            for d, dirs, files in os.walk(p):
                dirs.sort()
                out += [os.path.join(d, f) for f in sorted(files) if os.path.splitext(f)[1].lower() in MEDIA_EXT]
        elif os.path.splitext(p)[1].lower() in MEDIA_EXT:
            out.append(p)
    return out


def lib(proj):
    return proj.setdefault("library", {"folders": [], "items": []})


def _id(prefix):
    return prefix + uuid.uuid4().hex[:10]


def probe(path):
    """kind / size / duration of a media file."""
    ext = os.path.splitext(path)[1].lower()
    if svgimage.is_svg(path):                        # vector: its own size, drawn sharp at any scale
        try:
            w, h = svgimage.size(path)
        except ValueError as exc:
            raise edit.EditError(str(exc)) from None
        return {"kind": "image", "width": w, "height": h}
    if ext in IMAGE_EXT:
        with Image.open(path) as im:
            return {"kind": "image", "width": im.width, "height": im.height}
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
                        "-show_streams", path], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise edit.EditError(f"cannot read {os.path.basename(path)}")
    info = json.loads(r.stdout)
    streams = info.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"
             and not (s.get("disposition") or {}).get("attached_pic")]
    dur = float(info.get("format", {}).get("duration") or 0)
    out = {"duration_us": int(dur * 1_000_000)}
    if video:
        out.update(kind="video", width=int(video[0]["width"]), height=int(video[0]["height"]))
    elif any(s.get("codec_type") == "audio" for s in streams):
        out["kind"] = "audio"
    else:
        raise edit.EditError(f"{os.path.basename(path)} has no picture or sound")
    return out


def folder(proj, folder_id):
    for f in lib(proj)["folders"]:
        if f["id"] == folder_id:
            return f
    raise edit.EditError("folder not found")


def item(proj, item_id):
    for it in lib(proj)["items"]:
        if it["id"] == item_id:
            return it
    raise edit.EditError("media not found")


def add_folder(proj, name, parent=None):
    if parent is not None:
        folder(proj, parent)
    f = {"id": _id("f"), "name": name.strip() or "新資料夾", "parent": parent}
    lib(proj)["folders"].append(f)
    return f


def rename(proj, ident, name):
    name = name.strip()
    if not name:
        raise edit.EditError("name is empty")
    target = folder(proj, ident) if ident.startswith("f") else item(proj, ident)
    target["name"] = name


def descendants(proj, folder_id):
    """Folder ids inside folder_id, itself included."""
    out, todo = set(), [folder_id]
    while todo:
        f = todo.pop()
        out.add(f)
        todo += [g["id"] for g in lib(proj)["folders"] if g["parent"] == f]
    return out


def move(proj, ident, to_folder):
    """Put an item or folder into to_folder (None = top level)."""
    if to_folder is not None:
        folder(proj, to_folder)
    if ident.startswith("f"):
        if to_folder is not None and to_folder in descendants(proj, ident):
            raise edit.EditError("a folder cannot go inside itself")
        folder(proj, ident)["parent"] = to_folder
    else:
        item(proj, ident)["folder"] = to_folder


def delete(proj, ident):
    """Remove an item, or a folder whose contents move up to its parent.
    Clips already on the timeline keep working: they hold their own media paths."""
    L = lib(proj)
    if ident.startswith("f"):
        f = folder(proj, ident)
        for g in L["folders"]:
            if g["parent"] == ident:
                g["parent"] = f["parent"]
        for it in L["items"]:
            if it["folder"] == ident:
                it["folder"] = f["parent"]
        L["folders"].remove(f)
    else:
        L["items"].remove(item(proj, ident))


def add_files(proj, paths, to_folder=None, probes=None, reuse=False):
    """Import files (probe results may be passed in when done off the UI thread). With reuse,
    a file that is already in the library is not added twice: its item is returned."""
    added = []
    for p in paths:
        p = os.path.abspath(p).replace("\\", "/")
        have = next((it for it in lib(proj)["items"] if it["path"] == p), None) if reuse else None
        if have is not None:
            added.append(have)
            continue
        info = (probes or {}).get(p) or probe(p)
        it = {"id": _id("m"), "name": os.path.basename(p), "path": p, "folder": to_folder, **info}
        lib(proj)["items"].append(it)
        added.append(it)
    return added


def add_from_project(proj, folder_name="匯入的素材"):
    """Fill the library with the media a project already uses (after importing a draft)."""
    seen = {it["path"] for it in lib(proj)["items"]}
    f = None
    for c in project.all_clips(proj):
        m = c.get("media")
        if not m or m["path"] in seen or in_user_library(m["path"]):
            continue
        seen.add(m["path"])
        if f is None:
            f = add_folder(proj, folder_name)
        kind = "audio" if c["type"] == "audio" else ("image" if c["type"] == "image" else "video")
        lib(proj)["items"].append({"id": _id("m"), "name": os.path.basename(m["path"]), "path": m["path"],
                                   "folder": f["id"], "kind": kind, "width": m.get("width"),
                                   "height": m.get("height"), "duration_us": m.get("duration_us")})


def clip_from(it, start_us):
    """A new timeline clip for library item `it`."""
    c = {"id": edit.new_clip_id(), "type": it["kind"], "name": it["name"], "start_us": int(start_us),
         "source_start_us": 0, "media": {"path": it["path"]}}
    if it["kind"] in ("image", "video"):
        c["media"].update(width=it["width"], height=it["height"])
        c["transform"] = {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}
    if it["kind"] in ("video", "audio"):
        c["media"]["duration_us"] = it.get("duration_us")
        c["volume"] = 1.0
        c["duration_us"] = it.get("duration_us") or IMAGE_DEFAULT_US
    else:
        c["duration_us"] = IMAGE_DEFAULT_US
    return c


def place(container, root, item_id, track_id, start_us):
    """Add a library item to a timeline (root or an open compound) at start_us on track_id,
    or on a new track when track_id is None or of the wrong kind. Returns the clip."""
    return place_item(container, item(root, item_id), track_id, start_us)


def place_item(container, it, track_id, start_us):
    """place() for an item dict that is not in the project's library (the user's Library)."""
    c = clip_from(it, max(0, start_us))
    want = "audio" if it["kind"] == "audio" else "video"
    track = None
    if track_id:
        t = edit.track_by_id(container, track_id)
        if (t["kind"] == "audio") == (want == "audio"):
            track = t
    if track is not None:
        # the free gap nearest to the drop point, as when moving a clip
        best = None
        for lo, hi in edit.gaps(track):
            if hi - lo >= c["duration_us"]:
                s = min(max(c["start_us"], lo), hi - c["duration_us"])
                if best is None or abs(s - c["start_us"]) < abs(best - c["start_us"]):
                    best = s
        if best is None:
            track = None
        else:
            c["start_us"] = int(best)
    if track is None:
        n = sum(1 for t in container["tracks"] if t["kind"] == want) + 1
        track = {"id": edit.new_track_id(container), "kind": want, "name": f"{want} {n}", "clips": []}
        if want == "audio":
            container["tracks"].append(track)
        else:
            at = next((i for i, t in enumerate(container["tracks"]) if t["kind"] == "audio"),
                      len(container["tracks"]))
            container["tracks"].insert(at, track)
    track["clips"].append(c)
    track["clips"].sort(key=lambda k: k["start_us"])
    return c


def place_items(container, items, track_id, start_us, across=False):
    """Several items dropped together, in order. Stacked (the default): all at the time the
    first one lands, each on its own track, pictures going up from the dropped track and
    sounds going down. Across (Alt): one after another on the track each kind lands on.
    Returns the clips."""
    clips, last = [], {}                      # kind -> the clip placed last
    t0 = None
    for it in items:
        want = "audio" if it["kind"] == "audio" else "video"
        prev = last.get(want)
        if prev is None:
            c = place_item(container, it, track_id, start_us if t0 is None or across else t0)
        elif across:
            c = place_item(container, it, edit.find(container, prev["id"])[0]["id"], edit.end(prev))
        else:
            c = _stack_on(container, it, edit.find(container, prev["id"])[0], t0)
        t0 = c["start_us"] if t0 is None else t0
        last[want] = c
        clips.append(c)
    return clips


def _stack_on(container, it, below, t0):
    """Place it at t0 on the first free track past `below` (above it on screen; for sounds,
    under it), or on a new track at the far end of those."""
    c = clip_from(it, max(0, t0))
    tracks = container["tracks"]
    audio = below["kind"] == "audio"
    same = [i for i, t in enumerate(tracks) if (t["kind"] == "audio") == audio]
    past = [i for i in same if i > tracks.index(below)]
    for i in past:
        t = tracks[i]
        if not project.locked(t) and all(edit.end(k) <= c["start_us"] or k["start_us"] >= edit.end(c)
                                         for k in t["clips"]):
            t["clips"].append(c)
            t["clips"].sort(key=lambda k: k["start_us"])
            return c
    want = "audio" if audio else "video"
    n = sum(1 for t in tracks if t["kind"] == want) + 1
    track = {"id": edit.new_track_id(container), "kind": want, "name": f"{want} {n}", "clips": [c]}
    tracks.insert((past or [tracks.index(below)])[-1] + 1, track)
    return c


# -- the Media folder -------------------------------------------------------------------------------
def slash(p):
    return p.replace("\\", "/")


def norm(p):
    return slash(os.path.abspath(p))


def within(path, folder):
    a, b = project._fold(slash(path)), project._fold(slash(folder)).rstrip("/")
    return a.startswith(b + "/")


class Mirror(str):
    """A folder that a library mirrors, given where a project root is expected (the global
    Library's category folders; a project's own is <root>/Media)."""


def mroot_of(root):
    return str(root) if isinstance(root, Mirror) else workspace.media_dir(root)


def folder_rel(proj, folder_id):
    """Path of a library folder below Media ("" for the top level)."""
    parts = []
    while folder_id:
        f = folder(proj, folder_id)
        parts.append(f["name"])
        folder_id = f["parent"]
    return "/".join(reversed(parts))


def folder_dir(proj, root, folder_id):
    rel = folder_rel(proj, folder_id)
    return mroot_of(root) + ("/" + rel if rel else "")


def unique_name(directory, name):
    """name, or "name (2).ext" … when the folder already has it."""
    if not os.path.exists(os.path.join(directory, name)):
        return name
    stem, ext = os.path.splitext(name)
    n = 2
    while os.path.exists(os.path.join(directory, f"{stem} ({n}){ext}")):
        n += 1
    return f"{stem} ({n}){ext}"


def import_copy(root, files, dest_dir, progress=None):
    """Copy files into dest_dir (a folder of Media). Files already inside Media stay where they
    are; a copy that was imported before (same name, size and time) is reused. Returns
    {source path: path in the project}. Runs on a worker thread."""
    mroot = mroot_of(root)
    os.makedirs(dest_dir, exist_ok=True)
    out = {}
    for i, f in enumerate(files):
        src = norm(f)
        if within(src, mroot):
            out[src] = src
        else:
            name = os.path.basename(src)
            dst = os.path.join(dest_dir, name)
            if os.path.exists(dst) and _same_file(src, dst):
                out[src] = norm(dst)
            else:
                dst = os.path.join(dest_dir, unique_name(dest_dir, name))
                shutil.copy2(src, dst)
                out[src] = norm(dst)
        if progress:
            progress((i + 1) / len(files))
    return out


def _same_file(a, b):
    sa, sb = os.stat(a), os.stat(b)
    return sa.st_size == sb.st_size and abs(sa.st_mtime - sb.st_mtime) < 2


def scan(root, known=(), prober=probe, exts=None):
    """Read the Media folder: {"dirs": [relative paths], "files": [paths], "probes": {path: info
    for files not in `known`}, "failed": [paths that could not be read]}. Runs on a worker thread."""
    mroot = norm(mroot_of(root))
    res = {"dirs": [], "files": [], "probes": {}, "failed": []}
    if not os.path.isdir(mroot):
        return res
    for d, dnames, fnames in os.walk(mroot):
        dnames[:] = sorted(x for x in dnames if not x.startswith("."))
        rel = slash(os.path.relpath(d, mroot))
        if rel != ".":
            res["dirs"].append(rel)
        for f in sorted(fnames):
            if os.path.splitext(f)[1].lower() not in (exts or MEDIA_EXT) or f.startswith("."):
                continue
            path = norm(os.path.join(d, f))
            res["files"].append(path)
            if path not in known:
                try:
                    res["probes"][path] = prober(path)
                except Exception:
                    res["failed"].append(path)       # maybe still being written
    res["dirs"].sort()
    return res


def known_paths(proj):
    return {it["path"] for it in lib(proj)["items"]}


def dedupe(proj):
    """One item per file (two appear when a file is copied in while the library is read)."""
    seen, keep = set(), []
    for it in lib(proj)["items"]:
        key = project._fold(slash(it["path"]))
        if key not in seen:
            seen.add(key)
            keep.append(it)
    changed = len(keep) != len(lib(proj)["items"])
    lib(proj)["items"][:] = keep
    return changed


def apply_scan(proj, root, res):
    """Make the library match a scan of Media. Returns whether anything changed. Items outside
    Media (older projects, until their media are collected) are left alone."""
    L = lib(proj)
    mroot = norm(mroot_of(root))
    changed = dedupe(proj)
    byrel = {folder_rel(proj, f["id"]): f for f in L["folders"]}
    for rel in res["dirs"]:
        if rel not in byrel:
            parent = rel.rpartition("/")[0]
            f = {"id": _id("f"), "name": rel.rpartition("/")[2], "parent": byrel[parent]["id"] if parent else None}
            L["folders"].append(f)
            byrel[rel] = f
            changed = True
    keep = set()                                   # folders that items outside Media still sit in
    for it in L["items"]:
        fid = it.get("folder")
        if fid and not within(it["path"], mroot):
            while fid and fid not in keep:
                keep.add(fid)
                fid = folder(proj, fid)["parent"]
    live = {f["id"] for r, f in byrel.items() if r in set(res["dirs"])} | keep
    for f in list(L["folders"]):
        if f["id"] not in live:
            L["folders"].remove(f)
            changed = True
    files = set(res["files"])
    have = {}
    for it in list(L["items"]):
        if within(it["path"], mroot):
            if it["path"] in files:
                have[it["path"]] = it
            else:
                L["items"].remove(it)
                changed = True
    for path in res["files"]:
        d = slash(os.path.dirname(path))
        rel = d[len(mroot) + 1:] if d != mroot else ""
        fid = byrel[rel]["id"] if rel else None
        it = have.get(path)
        if it is None:
            info = res["probes"].get(path)
            if not info:
                continue
            it = {"id": _id(L.get("prefix", "m")), "name": os.path.basename(path), "path": path, "folder": fid, **info}
            L["items"].append(it)
            changed = True
        if it.get("folder") != fid:
            it["folder"] = fid
            changed = True
        if it["name"] != os.path.basename(path):
            it["name"] = os.path.basename(path)
            changed = True
    return changed


def retarget(proj, old, new, is_dir=False):
    """The file (or folder) old is now at new: items and clips follow it."""
    old, new = slash(old), slash(new)

    def fix(path):
        p = slash(path)
        if is_dir:
            return new + p[len(old):] if project._fold(p).startswith(project._fold(old) + "/") else path
        return new if project._fold(p) == project._fold(old) else path
    for it in lib(proj)["items"]:
        it["path"] = fix(it["path"])
    for c in project.all_clips(proj):
        m = c.get("media")
        if m and m.get("path"):
            m["path"] = fix(m["path"])
        for e in c.get("effects") or []:                 # a filter file of the user's
            if not e["filter"].startswith("builtin:"):
                e["filter"] = fix(e["filter"])
    dedupe(proj)


def retarget_text(text, old, new, is_dir=False):
    """The same for an undo snapshot (JSON text)."""
    esc = lambda s: json.dumps(slash(s), ensure_ascii=False)[1:-1]
    tail = "/" if is_dir else '"'
    return text.replace(esc(old) + tail, esc(new) + tail)


def in_user_library(path):
    """Whether a file is in the user's Library folder (those are used where they are)."""
    return bool(path and project.LIBRARY_ROOT and within(norm(path), norm(project.LIBRARY_ROOT)))


def _outside(proj, root):
    """(path, library folder below Media) of the items and clips that use files from elsewhere,
    each path once."""
    mroot = norm(mroot_of(root))
    todo = [(it["path"], folder_rel(proj, it["folder"]) if it.get("folder") else "") for it in lib(proj)["items"]]
    todo += [(c["media"]["path"], "匯入的素材") for c in project.all_clips(proj) if c.get("media")]
    out = {}
    for path, rel in todo:
        path = slash(path or "")
        if path and path not in out and not within(path, mroot) and not in_user_library(path):
            out[path] = rel
    return out


def external_count(proj, root):
    """How many files from outside Media the project uses that could be copied in (they exist)."""
    return sum(1 for p in _outside(proj, root) if os.path.exists(p))


def external_media(proj, root):
    """{path outside Media: where a copy would go}: the library items and clips that use files
    from elsewhere. Items keep their library folder as a sub-folder of Media."""
    mroot = norm(mroot_of(root))
    plan, taken = {}, {}
    for path, rel in _outside(proj, root).items():
        d = mroot + ("/" + rel if rel else "")
        stem, ext = os.path.splitext(os.path.basename(path))
        cand, n = stem + ext, 1
        while True:
            dst = d + "/" + cand
            if dst in taken.values() or (os.path.exists(dst) and not (os.path.exists(path) and _same_file(path, dst))):
                n += 1
                cand = f"{stem} ({n}){ext}"
            else:
                break
        name = cand
        plan[path] = taken[path] = d + "/" + name
    return plan


def collect(plan, progress=None):
    """Copy the files of an external_media() plan. Runs on a worker thread; files that are
    missing are skipped. Returns {source: copy} for those that exist."""
    done = {}
    items = list(plan.items())
    for i, (src, dst) in enumerate(items):
        if os.path.exists(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
            done[src] = dst
        if progress:
            progress((i + 1) / len(items))
    return done


# -- file operations (the disk and the library together) -------------------------------------------
def make_folder(proj, root, name, parent=None):
    name = workspace.safe_name(name, "新資料夾")
    base = folder_dir(proj, root, parent)
    name = unique_name(base, name)
    os.makedirs(base + "/" + name)
    return add_folder(proj, name, parent)


def _inside(proj, root, ident):
    """Files and folders of the project's Media may be changed; others belong to the user."""
    mroot = norm(mroot_of(root))
    if ident.startswith("f"):
        ok = os.path.isdir(folder_dir(proj, root, ident))
    else:
        ok = within(item(proj, ident)["path"], mroot)
    if not ok:
        raise edit.EditError("這個素材不在素材資料夾裡，請先按「將不在素材資料夾的素材複製到素材資料夾」")


def rename_on_disk(proj, root, ident, name):
    """Rename a folder or file. Returns [(old, new, is_dir)] for the places that hold paths."""
    name = name.strip()
    if not name:
        raise edit.EditError("name is empty")
    _inside(proj, root, ident)
    if name != workspace.safe_name(name, ""):
        raise edit.EditError("名稱不能包含 \\ / : * ? \" < > |")
    if ident.startswith("f"):
        f = folder(proj, ident)
        old = folder_dir(proj, root, ident)
        new = slash(os.path.dirname(old)) + "/" + name
        if name != f["name"]:
            if os.path.exists(new):
                raise edit.EditError("已有同名的資料夾或檔案")
            os.rename(old, new)
            f["name"] = name
            retarget(proj, old, new, True)
            return [(old, new, True)]
        return []
    it = item(proj, ident)
    if not os.path.splitext(name)[1]:
        name += os.path.splitext(it["path"])[1]              # the extension stays
    new = slash(os.path.dirname(it["path"])) + "/" + name
    if new == it["path"]:
        return []
    if os.path.exists(new):
        raise edit.EditError("已有同名的檔案")
    old = it["path"]
    os.rename(old, new)
    it["name"] = name
    retarget(proj, old, new)
    return [(old, new, False)]


def move_on_disk(proj, root, ident, to_folder):
    """Move a folder or file into to_folder (None: top level of Media). A file from elsewhere
    only changes library folder (it is copied there when its media are collected)."""
    if to_folder is not None:
        folder(proj, to_folder)
    if not ident.startswith("f") and not within(item(proj, ident)["path"], norm(mroot_of(root))):
        item(proj, ident)["folder"] = to_folder
        return []
    _inside(proj, root, ident)
    dest_dir = folder_dir(proj, root, to_folder)
    if ident.startswith("f"):
        if to_folder is not None and to_folder in descendants(proj, ident):
            raise edit.EditError("a folder cannot go inside itself")
        old = folder_dir(proj, root, ident)
        new = dest_dir + "/" + folder(proj, ident)["name"]
        if slash(os.path.dirname(old)) == dest_dir:
            return []
        if os.path.exists(new):
            raise edit.EditError("目的地已有同名的資料夾或檔案")
        shutil.move(old, new)
        folder(proj, ident)["parent"] = to_folder
        retarget(proj, old, new, True)
        return [(old, new, True)]
    it = item(proj, ident)
    old = it["path"]
    new = dest_dir + "/" + os.path.basename(old)
    if slash(os.path.dirname(old)) == dest_dir:
        return []
    if os.path.exists(new):
        raise edit.EditError("目的地已有同名的檔案")
    os.makedirs(dest_dir, exist_ok=True)
    shutil.move(old, new)
    it["folder"] = to_folder
    retarget(proj, old, new)
    return [(old, new, False)]


def delete_on_disk(proj, root, ident, trash=None):
    """Delete a file, or a folder with everything in it (trash(path) puts it in the recycle bin).
    Clips that used the files stay on the timeline, offline."""
    trash = trash or (lambda p: shutil.rmtree(p) if os.path.isdir(p) else os.remove(p))
    L = lib(proj)
    if not ident.startswith("f") and not within(item(proj, ident)["path"], norm(mroot_of(root))):
        L["items"].remove(item(proj, ident))             # a link to a file elsewhere: only the link goes
        return
    if ident.startswith("f"):
        gone = descendants(proj, ident)
        path = folder_dir(proj, root, ident)
        if os.path.exists(path):
            trash(path)
        L["items"] = [it for it in L["items"] if it.get("folder") not in gone]
        L["folders"] = [f for f in L["folders"] if f["id"] not in gone]
    else:
        it = item(proj, ident)
        if os.path.exists(it["path"]):
            trash(it["path"])
        L["items"].remove(it)
