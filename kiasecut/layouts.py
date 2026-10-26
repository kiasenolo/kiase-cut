"""Panel layouts (佈局): how the main window's panels are arranged.

Two are built in, arranged by code (ui/docks.py): 一般剪片 and 製圖. The user's own are files

    Documents/KiaseCut/preset/layout/<name>.json
        {"kiasecut_layout": 1, "name": ..., "state": ..., "closed": [...]}

state: QMainWindow.saveState() in base64 (where every panel is, floating ones included);
closed: the panels closed on purpose (others may be hidden only because the selection has
no use for them, and come back by themselves). Files put into the folder by hand are
listed too. A layout is named by its key: "builtin:<id>" or "user:<file name>".
"""
import base64
import json
import os

SUBDIR = os.path.join("KiaseCut", "preset", "layout")
EXT = ".json"
FORMAT = 1
BUILTIN = (("edit", "一般剪片"), ("design", "製圖"))
BAD_CHARS = '\\/:*?"<>|'


def folder(documents):
    return os.path.join(documents, SUBDIR)


def builtin_key(ident):
    return "builtin:" + ident


def user_key(name):
    return "user:" + name


def title(key):
    kind, _, rest = key.partition(":")
    if kind == "builtin":
        return dict(BUILTIN).get(rest, rest)
    return rest


def clean_name(name):
    """A layout name fit for a file name, or ValueError."""
    name = "".join("_" if ch in BAD_CHARS or ord(ch) < 32 else ch for ch in name).strip().strip(".")
    if not name:
        raise ValueError("佈局名稱不能是空的")
    if name in dict(BUILTIN).values():
        raise ValueError(f"「{name}」是內建佈局的名稱")
    return name


def path_of(where, name):
    return os.path.join(where, name + EXT)


def list_user(where):
    """Names of the user's layouts in the folder, in order."""
    try:
        names = [f[:-len(EXT)] for f in os.listdir(where) if f.lower().endswith(EXT) and not f.startswith(".")]
    except OSError:
        return []
    return sorted(names, key=str.casefold)


def pack(state, closed):
    """The stored form of a layout: state (bytes), closed (panel keys)."""
    return {"state": base64.b64encode(bytes(state)).decode("ascii"), "closed": sorted(closed)}


def unpack(data):
    """(state bytes, closed panel keys) from pack()'s form, or ValueError."""
    try:
        return base64.b64decode(data["state"]), list(data.get("closed", []))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"佈局資料有誤：{exc}") from exc


def read(where, name):
    """(state bytes, closed panel keys) of the user's layout, or ValueError."""
    try:
        with open(path_of(where, name), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"讀不到佈局「{name}」：{exc}") from exc
    if not isinstance(data, dict) or data.get("kiasecut_layout") != FORMAT:
        raise ValueError(f"「{name}」不是 KiaseCut 的佈局檔")
    return unpack(data)


def write(where, name, state, closed):
    os.makedirs(where, exist_ok=True)
    data = {"kiasecut_layout": FORMAT, "name": name, **pack(state, closed)}
    path = path_of(where, name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return path


def rename(where, old, new):
    src, dst = path_of(where, old), path_of(where, new)
    if os.path.exists(dst):
        raise ValueError(f"已經有叫「{new}」的佈局")
    os.replace(src, dst)


def remove(where, name):
    os.remove(path_of(where, name))
