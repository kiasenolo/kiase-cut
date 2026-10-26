"""The project folder (as in FL Studio): a project is a folder that holds everything of it.

    My Video/
        My Video.kiasecut.json    the project file (media paths stored relative to the folder)
        Media/                    the media library: its sub-folders are the library folders
        Cache/                    waveforms, proxies, temporary renders (設定 > 緩存位置: here, or
                                  outside the project so it moves light)
        Exports/                  rendered videos
        Backup/                   copies of the project file from earlier saves

proj["info"] = {title, author, genre, url, comments, created, last_opened, last_saved,
                time_spent_s, opens}   the project information (File > Project info)
"""
import datetime
import hashlib
import json
import os
import re
import shutil

from . import project

EXT = ".kiasecut.json"
OLD_EXTS = (".tesetoa.json",)  # project files of the program's earlier name
EXTS = (EXT,) + OLD_EXTS
MEDIA, CACHE, EXPORTS, BACKUP = "Media", "Cache", "Exports", "Backup"
BACKUPS_KEPT = 20
BACKUP_EVERY_S = 30             # saves closer together than this share one backup
STAMP = "%Y-%m-%d %H:%M:%S"


def now():
    return datetime.datetime.now().astimezone().replace(microsecond=0)


def now_iso():
    return now().isoformat()


def parse_time(s):
    try:
        return datetime.datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def show_time(s):
    t = parse_time(s)
    return t.astimezone().strftime(STAMP) if t else "—"


def show_duration(sec):
    sec = int(sec or 0)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def safe_name(name, fallback="新專案"):
    """A file / folder name that works on every system."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name or "").strip().strip(".")
    return name or fallback


# -- layout -----------------------------------------------------------------------------------------
def root_of(path):
    return os.path.dirname(os.path.abspath(path)).replace("\\", "/")


def sub(root, name):
    return os.path.join(root, name).replace("\\", "/")


def media_dir(root):
    return sub(root, MEDIA)


# where a project's cache goes (設定 > 緩存位置): the user's cache folder, the project's Cache/, or
# a folder the user picked; outside the project each project folder has its own sub-folder there
CACHE_DEFAULT, CACHE_PROJECT, CACHE_CUSTOM = "default", "project", "custom"
CACHE_MODES = (CACHE_DEFAULT, CACHE_PROJECT, CACHE_CUSTOM)


def cache_id(proj, root):
    """The name of a project's cache folder outside it: from when the project was started, so it
    stays the project's when the project is moved or renamed (a copy of the project shares it:
    what is cached is named by its content)."""
    key = (proj.get("info") or {}).get("created") or os.path.normcase(os.path.abspath(root))
    return hashlib.sha1(str(key).encode()).hexdigest()[:16]


def cache_dir(root, base=None, ident=None):
    """The project folder root's cache: base/ident when a base is given (outside the project),
    else its Cache/."""
    return sub(base, ident) if base else sub(root, CACHE)


def cache_dirs(root, ident, bases=()):
    """Every place a project's cache can be: its folder's Cache/ and its folder in each base."""
    return [cache_dir(root)] + [cache_dir(root, b, ident) for b in bases if b]


def clear_cache(dirs):
    """Delete these cache folders (what is in them is made again when needed). Returns the
    bytes freed."""
    freed = 0
    for d in dirs:
        if os.path.isdir(d):
            freed += folder_size(d)
            shutil.rmtree(d, ignore_errors=True)
    return freed


def exports_dir(root):
    return sub(root, EXPORTS)


def ensure_layout(root):
    for d in (MEDIA, EXPORTS, BACKUP):             # (Cache/ is made when something is cached in it)
        os.makedirs(sub(root, d), exist_ok=True)


def project_file(root, name):
    return sub(root, safe_name(name) + EXT)


def project_name(path):
    base = os.path.basename(path)
    ext = next((e for e in EXTS if base.endswith(e)), None)
    return base[:-len(ext)] if ext else os.path.splitext(base)[0]


def other_projects(root):
    """The project files in a folder (several can share the media, as FL projects do)."""
    return sorted(f for f in os.listdir(root) if f.endswith(EXTS))


def stored_title(path):
    """The title in a project file's info (File > Project info), "" when it has none or the
    file cannot be read."""
    try:
        with open(path, encoding="utf-8") as fh:
            title = (json.load(fh).get("info") or {}).get("title")
    except (OSError, ValueError, AttributeError):
        return ""
    return title.strip() if isinstance(title, str) else ""


def thumbnail_file(path):
    """Where the project file path's thumbnail picture goes (thumbnail.py)."""
    return sub(root_of(path), project_name(path) + ".thumbnail.png")


def find_projects(location, extra=()):
    """Every project file in location (in it and in its project folders, one level down)
    plus the existing ones of extra (the recent list), newest first; each once."""
    found = []
    try:
        entries = sorted(os.scandir(location), key=lambda e: e.name) if os.path.isdir(location) else []
    except OSError:
        entries = []
    for e in entries:
        if e.is_file() and e.name.endswith(EXTS):
            found.append(e.path)
        elif e.is_dir() and e.name not in (MEDIA, CACHE, EXPORTS, BACKUP):
            try:
                found += [os.path.join(e.path, f) for f in other_projects(e.path)]
            except OSError:
                pass
    found += [p for p in extra if os.path.isfile(p)]
    seen, out = set(), []
    for p in found:
        key = os.path.normcase(os.path.abspath(p))
        if key not in seen:
            seen.add(key)
            out.append(os.path.abspath(p).replace("\\", "/"))
    return sorted(out, key=lambda p: -os.path.getmtime(p))


# -- the project manager's folders (專案管理器): folders that group projects ------------------------------
SPECIAL = (MEDIA, CACHE, EXPORTS, BACKUP)


def is_project_dir(path):
    """Whether a folder is a project folder (it holds a project file)."""
    try:
        return bool(other_projects(path))
    except OSError:
        return False


def browse(folder):
    """(folders, project files) shown in a folder of the projects folder: sub-folders that
    hold no project file are folders that group projects (opened to see inside); a project
    folder shows as its project files, as do project files lying in folder itself. Folders by
    name, projects newest first."""
    folders, found = [], []
    try:
        entries = sorted(os.scandir(folder), key=lambda e: e.name.lower()) if os.path.isdir(folder) else []
    except OSError:
        entries = []
    for e in entries:
        if e.is_file() and e.name.endswith(EXTS):
            found.append(e.path)
        elif e.is_dir() and e.name not in SPECIAL and not e.name.startswith("."):
            if is_project_dir(e.path):
                found += [os.path.join(e.path, f) for f in other_projects(e.path)]
            else:
                folders.append(e.path.replace("\\", "/"))
    found = [os.path.abspath(p).replace("\\", "/") for p in found]
    return folders, sorted(found, key=lambda p: -os.path.getmtime(p))


def find_all(location, depth=4):
    """Every project file under location, into folders of folders (depth levels), newest first."""
    out, todo = [], [(location, 0)]
    while todo:
        folder, d = todo.pop()
        folders, found = browse(folder)
        out += found
        if d < depth:
            todo += [(f, d + 1) for f in folders]
    return sorted(set(out), key=lambda p: -os.path.getmtime(p))


def owns_folder(path):
    """Whether a project file is the only one in its folder (its folder is the project: it is
    moved, renamed, copied and deleted with it)."""
    root = root_of(path)
    try:
        return other_projects(root) == [os.path.basename(path)]
    except OSError:
        return False


def _unique(folder, name):
    """name, or "name 2", "name 3"... - whichever is free in folder."""
    out, n = name, 1
    while os.path.exists(os.path.join(folder, out)):
        n += 1
        out = f"{name} {n}"
    return out


def new_folder(parent, name="新資料夾"):
    """A new folder for grouping projects. Returns its path."""
    path = os.path.join(parent, _unique(parent, safe_name(name, "新資料夾")))
    os.makedirs(path)
    return path.replace("\\", "/")


def _project_files(path):
    """The project file and the files that go with it in its folder (its thumbnail)."""
    thumb = thumbnail_file(path)
    return [path] + ([thumb] if os.path.exists(thumb) else [])


def rename_project(path, name):
    """Rename a project: its folder too when it owns one (the file inside follows the
    folder's new name). Returns the project file's new path."""
    name = safe_name(name)
    if owns_folder(path):
        root = root_of(path)
        parent = os.path.dirname(root)
        if os.path.basename(root) != name:
            new_root = os.path.join(parent, _unique(parent, name))
            os.rename(root, new_root)
        else:
            new_root = root
        path = os.path.join(new_root, os.path.basename(path))
        root = new_root
    else:
        root = root_of(path)
    new = project_file(root, name)
    if os.path.abspath(new) != os.path.abspath(path):
        if os.path.exists(new):
            raise FileExistsError(f"「{name}」已經有了")
        old_thumb = thumbnail_file(path)
        os.rename(path, new)
        if os.path.exists(old_thumb):
            os.rename(old_thumb, thumbnail_file(new))
    return new.replace("\\", "/")


def move_project(path, folder):
    """Move a project that owns its folder into another folder. Returns its new path."""
    if not owns_folder(path):
        raise ValueError("這個專案和其他專案共用資料夾，只能在檔案總管裡搬移")
    root = root_of(path)
    if os.path.abspath(os.path.dirname(root)) == os.path.abspath(folder):
        return path
    if os.path.abspath(folder).startswith(os.path.abspath(root) + os.sep):
        raise ValueError("不能移到專案自己的資料夾裡")
    dst = os.path.join(folder, _unique(folder, os.path.basename(root)))
    shutil.move(root, dst)
    return os.path.join(dst, os.path.basename(path)).replace("\\", "/")


def move_folder(path, folder):
    """Move a grouping folder into another one. Returns its new path."""
    if os.path.abspath(folder) == os.path.abspath(path) or \
            os.path.abspath(folder).startswith(os.path.abspath(path) + os.sep):
        raise ValueError("不能把資料夾移到它自己裡面")
    if os.path.abspath(os.path.dirname(path)) == os.path.abspath(folder):
        return path
    dst = os.path.join(folder, _unique(folder, os.path.basename(path)))
    shutil.move(path, dst)
    return dst.replace("\\", "/")


def copy_project(path):
    """A copy of a project next to it ("… 副本"): its whole folder when it owns one (the
    backups and the cache left out), else the file. Returns the copy's project file."""
    name = project_name(path) + " 副本"
    if owns_folder(path):
        root = root_of(path)
        parent = os.path.dirname(root)
        dst = os.path.join(parent, _unique(parent, safe_name(name)))
        shutil.copytree(root, dst, ignore=lambda d, names: [n for n in names if d == root and n in (CACHE, BACKUP)])
        copied = os.path.join(dst, os.path.basename(path))
        return rename_project(copied, os.path.basename(dst))
    root = root_of(path)
    new = project_file(root, _unique(root, safe_name(name)))
    for src in _project_files(path):
        dst = new if src == path else thumbnail_file(new)
        shutil.copy2(src, dst)
    return new.replace("\\", "/")


def remove_project(path, trash):
    """Delete a project with trash(path) (to the recycle bin): its whole folder when it owns
    one, else the file and its thumbnail."""
    if owns_folder(path):
        trash(root_of(path))
    else:
        for f in _project_files(path):
            trash(f)


# -- project info -----------------------------------------------------------------------------------
def new_info(title):
    t = now_iso()
    return {"title": title, "author": "", "genre": "", "url": "", "comments": "",
            "created": t, "last_opened": t, "last_saved": None, "time_spent_s": 0, "opens": 1}


def info(proj):
    return proj.setdefault("info", new_info(""))


def ensure_info(proj, path=None):
    """Info for a project that has none (saved by an older version): the file's age tells
    when it was started."""
    if "info" not in proj:
        proj["info"] = new_info(project_name(path) if path else "")
        if path and os.path.exists(path):
            st = os.stat(path)
            made = datetime.datetime.fromtimestamp(min(st.st_ctime, st.st_mtime)).astimezone().replace(microsecond=0)
            proj["info"].update(created=made.isoformat(),
                                last_saved=datetime.datetime.fromtimestamp(st.st_mtime).astimezone()
                                .replace(microsecond=0).isoformat())
    return proj["info"]


def opened(proj, path):
    """Called when a project has been opened: stamps the info."""
    i = ensure_info(proj, path)
    i["last_opened"] = now_iso()
    i["opens"] = int(i.get("opens", 0)) + 1
    return i


def title_of(proj, path=None):
    t = (proj.get("info") or {}).get("title")
    return t or (project_name(path) if path else "")


# -- create / save ----------------------------------------------------------------------------------
def create(parent_dir, name, width=1920, height=1080, fps=60.0):
    """A new project folder parent_dir/name with an empty project. Returns (proj, project file)."""
    name = safe_name(name)
    root = sub(os.path.abspath(parent_dir), name)
    if os.path.isdir(root) and os.listdir(root):
        raise FileExistsError(f"「{name}」這個資料夾已經存在，而且不是空的")
    ensure_layout(root)
    proj = project.new(width, height, fps)
    proj["info"] = new_info(name)
    path = project_file(root, name)
    project.save(proj, path)
    return proj, path


def adopt(proj, parent_dir, name):
    """Make an existing project (a Jianying draft, say) a project folder. Returns its file."""
    name = safe_name(name)
    root = sub(os.path.abspath(parent_dir), name)
    if os.path.isdir(root) and os.listdir(root):
        raise FileExistsError(f"「{name}」這個資料夾已經存在，而且不是空的")
    ensure_layout(root)
    proj["info"] = new_info(name)
    path = project_file(root, name)
    project.save(proj, path)
    return path


def save(proj, path, backup=True):
    """Write the project file. The file it replaces is first copied to Backup/."""
    root = root_of(path)
    ensure_layout(root)
    if backup and os.path.exists(path):
        make_backup(path)
    ensure_info(proj, path)["last_saved"] = now_iso()
    project.save(proj, path)


def make_backup(path, tag=None):
    """Copy the project file to Backup/ (not again within BACKUP_EVERY_S of the last copy)."""
    folder = sub(root_of(path), BACKUP)
    os.makedirs(folder, exist_ok=True)
    stem = project_name(path)
    mine = sorted(f for f in os.listdir(folder) if f.startswith(stem + " ") and f.endswith(EXTS))
    if tag is None and mine:
        last = os.path.getmtime(os.path.join(folder, mine[-1]))
        if now().timestamp() - last < BACKUP_EVERY_S:
            return None
    stamp = now().strftime("%Y-%m-%d %H-%M-%S")
    dest = os.path.join(folder, f"{stem} {stamp}{' ' + tag if tag else ''}{EXT}")
    shutil.copy2(path, dest)
    mine = sorted(f for f in os.listdir(folder) if f.startswith(stem + " ") and f.endswith(EXTS)
                  and not any(f.endswith(" autosave" + e) for e in EXTS))     # (autosaves of older versions)
    for old in mine[:-BACKUPS_KEPT]:
        os.remove(os.path.join(folder, old))
    return dest


# -- statistics -------------------------------------------------------------------------------------
def folder_size(folder):
    total = 0
    for d, _, files in os.walk(folder):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(d, f))
            except OSError:
                pass
    return total


def show_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
