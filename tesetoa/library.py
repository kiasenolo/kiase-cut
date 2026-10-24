"""Media library: imported files organised in folders, stored in the project.

proj["library"] = {"folders": [{id, name, parent}], "items": [{id, name, path, kind, width,
height, duration_us, folder}]}. parent / folder is None at the top level. Every function
takes the project root and raises edit.EditError on bad input, so they run through the
same undo history as timeline edits.
"""
import json
import os
import subprocess
import uuid

from PIL import Image

from . import edit, project

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
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
        if not m or m["path"] in seen:
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
    it = item(root, item_id)
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
