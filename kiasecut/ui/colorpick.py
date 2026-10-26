"""Colour picking with a live preview: while the dialog is open, every colour the user tries
goes to `live` at once (the preview, the timeline, the thumbnails show it); OK keeps it,
Cancel calls `cancel` so what was there before shows again."""
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QDialog


def pick_color(parent, initial, title, alpha=True, live=None, cancel=None):
    """The colour picked (a QColor), or None when the dialog was cancelled."""
    dlg = QColorDialog(QColor(initial) if initial is not None else QColor("white"), parent)
    dlg.setWindowTitle(title)
    if alpha:
        dlg.setOption(QColorDialog.ShowAlphaChannel, True)
    if live is not None:
        dlg.currentColorChanged.connect(lambda col: col.isValid() and live(col))
    ok = dlg.exec() == QDialog.Accepted
    col = dlg.selectedColor() if ok else None
    if col is not None and not col.isValid():
        col = None
    if col is None and cancel is not None:
        cancel()
    dlg.deleteLater()
    return col


def qcolor(text, default="white"):
    """A QColor of #rrggbb or #rrggbbaa (Qt itself reads 8 digits as #aarrggbb)."""
    t = (text or "").strip()
    if len(t) == 9 and t.startswith("#"):
        col = QColor(t[:7])
        try:
            col.setAlpha(int(t[7:], 16))
        except ValueError:
            pass
        return col
    col = QColor(t)
    return col if col.isValid() else QColor(default)


def rgba(col):
    """[r, g, b, a] (0 - 1) of a QColor."""
    return [col.redF(), col.greenF(), col.blueF(), col.alphaF()]


def hex_of(col):
    """#rrggbb, or #rrggbbaa when not opaque."""
    return col.name() + (f"{col.alpha():02x}" if col.alpha() < 255 else "")
