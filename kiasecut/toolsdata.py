"""What the extra tools (工具 menu: ui/tools.py) keep, in the KiaseCut root folder (設定 > 根資料夾):

    tools/cubic-bezier-tools/curves.json   my curves: [{name, value: [x1, y1, x2, y2]}]
    tools/palette/<name>.json              colour cards: {name, info, colors: ["#rrggbb", …]}

A colour card is exported as the plain list of its colours (a JSON string[]), and a file like
that is imported as a new card named after the file."""
import json
import os
import re

from . import workspace

HEX = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def tools_dir(root):
    return os.path.join(root, "tools")


# -- cubic-bezier ---------------------------------------------------------------------------------
def curves_file(root):
    return os.path.join(tools_dir(root), "cubic-bezier-tools", "curves.json")


def bezier_text(v):
    return "cubic-bezier(%s)" % ", ".join(f"{x:.3g}" for x in v)


def load_curves(root):
    """[{name, value}] of the curves kept (bad entries left out)."""
    try:
        with open(curves_file(root), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    out = []
    for d in data if isinstance(data, list) else []:
        try:
            v = [float(x) for x in d["value"]]
        except (KeyError, TypeError, ValueError):
            continue
        if len(v) == 4 and isinstance(d.get("name"), str):
            out.append({"name": d["name"], "value": v})
    return out


def save_curves(root, curves):
    path = curves_file(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump([{"name": c["name"], "value": [round(float(x), 4) for x in c["value"]]} for c in curves], fh,
                  ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# -- colour cards ---------------------------------------------------------------------------------
def palette_dir(root):
    return os.path.join(tools_dir(root), "palette")


def clean_colors(values):
    """The colours of a list that are #rrggbb or #rrggbbaa (lower case), in order."""
    return [v.strip().lower() for v in values if isinstance(v, str) and HEX.match(v.strip())]


def load_cards(root):
    """[{name, info, colors, file}] of the colour cards, by name."""
    folder = palette_dir(root)
    out = []
    try:
        names = sorted(n for n in os.listdir(folder) if n.endswith(".json"))
    except OSError:
        return []
    for n in names:
        try:
            with open(os.path.join(folder, n), encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(d, dict):
            out.append({"name": str(d.get("name") or n[:-5]), "info": str(d.get("info") or ""),
                        "colors": clean_colors(d.get("colors") or []), "file": os.path.join(folder, n)})
    return out


def save_card(root, card):
    """Write a colour card (a new one gets a file of its own name); returns its file."""
    folder = palette_dir(root)
    os.makedirs(folder, exist_ok=True)
    path = card.get("file")
    if not path:
        base = workspace.safe_name(card["name"], "色卡")
        path, k = os.path.join(folder, base + ".json"), 2
        while os.path.exists(path):
            path, k = os.path.join(folder, f"{base} {k}.json"), k + 1
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"name": card["name"], "info": card.get("info", ""), "colors": clean_colors(card["colors"])}, fh,
                  ensure_ascii=False, indent=1)
    card["file"] = path
    return path


def delete_card(card):
    if card.get("file") and os.path.exists(card["file"]):
        os.remove(card["file"])


def export_colors(card, path):
    """A card's colours as a JSON string[] file."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(clean_colors(card["colors"]), fh, ensure_ascii=False, indent=1)


def import_colors(path):
    """The colours of a JSON string[] file (a card's {colors} is taken too)."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        data = data.get("colors") or []
    if not isinstance(data, list):
        raise ValueError("色卡檔要是顏色字串的陣列，例如 [\"#ff0000\", \"#00ff00\"]")
    colors = clean_colors(data)
    if not colors:
        raise ValueError("檔案裡沒有 #rrggbb 這樣的顏色")
    return colors
