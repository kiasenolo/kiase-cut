"""Text presets of the 內建素材 tab (文字): a text clip's looks - colours, outline, background - to drag onto the timeline
(a new text clip with the words 輸入文字) or into the node editor (a text node set the same way). Their ident in the drag
data is "text:<key>"; fields are the ones of a clip's text (project.py), colours [r, g, b(, a)] (0 - 1)."""

PREFIX = "text:"
BLACK, WHITE = [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]
OUTLINE = {"stroke_on": True, "stroke": 4.0, "stroke_align": "outside"}
BOX = {"bg_on": True, "bg_radius": 8.0}

PRESETS = (
    ("white", "白字", {"color": WHITE}),
    ("black", "黑字", {"color": BLACK}),
    ("black_outline", "黑框白字", {"color": WHITE, "stroke_color": BLACK, **OUTLINE}),
    ("white_outline", "白框黑字", {"color": BLACK, "stroke_color": WHITE, **OUTLINE}),
    ("black_box", "黑底白字", {"color": WHITE, "bg_color": [0.0, 0.0, 0.0, 1.0], **BOX}),
    ("white_box", "白底黑字", {"color": BLACK, "bg_color": [1.0, 1.0, 1.0, 1.0], **BOX}),
    ("shadow", "白字陰影", {"color": WHITE, "shadow_on": True}),
)
_BY_KEY = {k: (name, fields) for k, name, fields in PRESETS}


def ident(key):
    return PREFIX + key


def fields(text):
    """A copy of the looks of the preset an ident() names, or None."""
    got = _BY_KEY.get(text[len(PREFIX):]) if text.startswith(PREFIX) else None
    return {k: list(v) if isinstance(v, list) else v for k, v in got[1].items()} if got else None
