"""Project thumbnails, shown by the project manager.

A project has none at first. Two ways to give it one:
  * 檔案 > 把目前畫面設為專案縮圖: the frame the preview shows is saved (save_image);
  * a static compound named _thumbnail (project.thumbnail_compound): its picture - like any
    static compound, its first frame - is drawn into the thumbnail every time the project is
    saved (render_compound), and it wins over a saved frame. A compound of that name that is
    not static does not count.
The picture is <project name>.thumbnail.png beside the project file (workspace.thumbnail_file).

拿掉縮圖 in the project manager deletes the picture; when the project has a _thumbnail compound
it also leaves <project name>.thumbnail.off beside it (workspace.thumbnail_off_file), so saving
does not draw the compound back - 套用縮圖 on the compound (in the editor) takes that away again.
"""
import json
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from . import project, render, workspace

WIDTH = 480                      # px across: plenty for a card in the manager


def save_image(img, path):
    """Save a picture (QImage) as the project file path's thumbnail, WIDTH px across."""
    if img is None or img.isNull():
        raise ValueError("沒有畫面可以存成縮圖")
    if img.width() > WIDTH:
        img = img.scaledToWidth(WIDTH, Qt.SmoothTransformation)
    out = workspace.thumbnail_file(path)
    if not img.save(out, "PNG"):
        raise OSError(f"無法寫入 {out}")
    return out


def render_compound(proj, comp, video_frame=None):
    """A static compound's picture (its first frame), WIDTH px across."""
    cw, ch = comp["width"], comp["height"]
    view = {"width": cw, "height": ch, "fps": proj.get("fps", 30.0), "duration_us": 1,
            "tracks": comp["tracks"], "compounds": proj.get("compounds", {})}
    r = render.Renderer(video_frame)
    img = r.render(view, 0, WIDTH, max(1, round(WIDTH * ch / cw)))
    return img, r.errors


def update(proj, path, video_frame=None):
    """When the project has a _thumbnail static compound, draw it into the thumbnail.
    Returns what happened: "compound", "not static" (a _thumbnail that does not count), or
    None (nothing to do: a saved frame, if any, stays)."""
    comp = project.thumbnail_compound(proj)
    if comp is None:
        named = any(c.get("name") == project.THUMBNAIL for c in proj.get("compounds", {}).values())
        return "not static" if named else None
    if is_off(path):
        return "off"
    img, _errors = render_compound(proj, comp, video_frame)
    save_image(img, path)
    return "compound"


def load(path):
    """The thumbnail of a project file as a QImage, or None."""
    f = workspace.thumbnail_file(path)
    if not os.path.exists(f):
        return None
    img = QImage(f)
    return None if img.isNull() else img


def remove(path):
    """Delete the thumbnail; a project with a _thumbnail compound is also marked so that saving
    does not draw it back (until 套用縮圖)."""
    f = workspace.thumbnail_file(path)
    if os.path.exists(f):
        os.remove(f)
    if has_compound(path):
        with open(workspace.thumbnail_off_file(path), "w", encoding="utf-8") as fh:
            fh.write("_thumbnail is not drawn into the thumbnail (套用縮圖 in KiaseCut brings it back)\n")


def is_off(path):
    return bool(path) and os.path.exists(workspace.thumbnail_off_file(path))


def turn_on(path):
    """套用縮圖: the _thumbnail compound is the thumbnail again (draw it with update)."""
    f = workspace.thumbnail_off_file(path)
    if os.path.exists(f):
        os.remove(f)


def has_compound(path):
    """Whether the project file has a _thumbnail static compound (read without loading it all)."""
    try:
        with open(path, encoding="utf-8") as fh:
            comps = json.load(fh).get("compounds") or {}
    except (OSError, ValueError, AttributeError):
        return False
    return project.thumbnail_compound({"compounds": comps}) is not None
