"""The project folder (as in FL Studio): a project is a folder that holds everything of it.

    My Video/
        My Video.kiasecut.json    the project file (media paths stored relative to the folder)
        Media/                    the media library: its sub-folders are the library folders
        Cache/                    waveforms, proxies, temporary renders
        Exports/                  rendered videos
        Backup/                   copies of the project file from earlier saves

proj["info"] = {title, author, genre, url, comments, created, last_opened, last_saved,
                time_spent_s, opens}   the project information (File > Project info)
"""
import datetime
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


def cache_dir(root):
    return sub(root, CACHE)


def exports_dir(root):
    return sub(root, EXPORTS)


def ensure_layout(root):
    for d in (MEDIA, CACHE, EXPORTS, BACKUP):
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
                  and not any(f.endswith(" autosave" + e) for e in EXTS))
    for old in mine[:-BACKUPS_KEPT]:
        os.remove(os.path.join(folder, old))
    return dest


def autosave(proj, path):
    """Write the unsaved state beside the backups; the project file itself is left alone."""
    folder = sub(root_of(path), BACKUP)
    os.makedirs(folder, exist_ok=True)
    project.save(proj, os.path.join(folder, project_name(path) + " autosave" + EXT))


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
