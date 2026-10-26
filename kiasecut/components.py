"""Components (元件): static compounds with parameters.

A component is a static compound (靜態片段, project.is_static) that is also marked
component: true and has params: [param]. Every clip that shows it (an instance) draws its
picture with its own values for those parameters, kept in clip["params"] {param id: value};
a parameter it leaves out shows what the component itself has. Instance values animate like
any other parameter (curves.py): colours blend between keyframes, words, pictures and
switches hold until the next one - an animated instance is drawn afresh for each frame.

param {id, name, kind: text | color | image | visible, binds: [[clip id, prop]]}
      binds: the layers (clips of the component's content, inside its groups too) it sets
      and what of them (PROPS); one parameter can set several layers (a 主色 for three
      shapes). Its default is what its first layer has at the picture's moment. A layer that
      was deleted leaves its binding behind, unused.

Values: text a str, color [r, g, b, a] (0 - 1), image a picture file's path, visible a bool.
"""
import os

from . import assets, curves, project, svgimage

ICON = "❖"
KINDS = {"text": "文字", "color": "顏色", "image": "圖片", "visible": "顯示"}
PROPS = {                         # prop: (kind, label)
    "content": ("text", "文字內容"),
    "text_color": ("color", "文字顏色"),
    "color": ("color", "顏色"),           # a built-in asset's (fill) colour
    "color2": ("color", "顏色 2"),
    "stroke_color": ("color", "外框顏色"),
    "source": ("image", "圖片"),
    "visible": ("visible", "顯示"),
}
FALLBACK = {"text": "", "color": [1.0, 1.0, 1.0, 1.0], "image": "", "visible": True}


def is_component(comp):
    return bool(comp) and bool(comp.get("static")) and bool(comp.get("component"))


def of_clip(c):
    """The component clip c shows, or None."""
    comp = c.get("compound") if c.get("type") == "compound" else None
    return comp if is_component(comp) else None


def params(comp):
    return (comp or {}).get("params") or []


def param(comp, pid):
    return next((p for p in params(comp) if p["id"] == pid), None)


def props_of(c):
    """What of layer c a parameter can set."""
    out = []
    if c["type"] == "text":
        out += ["content", "text_color"]
    a = c.get("asset")
    if a:
        out += [f for f in ("color", "color2", "stroke_color") if f in assets.fields_of(a.get("family"))]
    if c["type"] == "image":
        out.append("source")
    if c["type"] != "filter":
        out.append("visible")
    return out


def prop_label(c, prop):
    """What prop of layer c is called (a shape's colour is its 填充顏色)."""
    if prop == "color" and c is not None and "fill" in assets.fields_of((c.get("asset") or {}).get("family")):
        return "填充顏色"
    return PROPS[prop][1]


def layer_index(comp):
    """{clip id: (track, clip)} of the component's content, its groups' clips included."""
    return {c["id"]: (t, c) for t in project.all_tracks(comp["tracks"]) for c in t["clips"]}


def layer_value(track, c, prop):
    """What layer c has for prop at the picture's moment (time 0 of the component)."""
    t = max(0, -c["start_us"])
    if prop == "content":
        return c["text"].get("content", "")
    if prop == "text_color":
        col = curves.value(c["text"].get("color", [1.0, 1.0, 1.0]), t)
        return [float(v) for v in col[:3]] + [1.0]
    if prop in ("color", "color2", "stroke_color"):
        return assets.clean(prop, curves.value(c["asset"].get(prop), t))
    if prop == "source":
        return (c.get("media") or {}).get("path", "")
    return not track.get("hidden")


def default(comp, p, index=None):
    """A parameter's default: what its first (still there) layer has."""
    index = layer_index(comp) if index is None else index
    for cid, prop in p.get("binds") or []:
        if cid in index:
            t, c = index[cid]
            return layer_value(t, c, prop)
    return FALLBACK[p["kind"]]


def value(c, p, t):
    """Instance c's value of parameter p at clip time t (the default when it has none)."""
    own = (c.get("params") or {}).get(p["id"])
    return default(c["compound"], p) if own is None else curves.value(own, t)


def bound(comp):
    """{clip id: [(param, prop)]}: what sets each layer."""
    out = {}
    for p in params(comp):
        for cid, prop in p.get("binds") or []:
            out.setdefault(cid, []).append((p, prop))
    return out


# -- an instance's picture --------------------------------------------------------------------------
def content(c, t):
    """What compound clip c draws at clip time t: its compound, or for a component instance
    with values of its own a copy of the component with them put into its layers (only what
    they change is copied; the renderers key their stills on the content)."""
    comp = c.get("compound")
    own = c.get("params")
    if not own or not is_component(comp):
        return comp
    over = {}
    for p in params(comp):
        if p["id"] in own:
            v = curves.value(own[p["id"]], t)
            for cid, prop in p.get("binds") or []:
                over.setdefault(cid, []).append((prop, v))
    if not over:
        return comp
    tracks = _subst(comp["tracks"], over)
    return comp if tracks is comp["tracks"] else dict(comp, tracks=tracks)


def _subst(tracks, over):
    """tracks with the values put in (the very list when nothing changed)."""
    out, changed = [], False
    for tr in tracks:
        clips, hidden, moved = [], tr.get("hidden"), False
        for c in tr["clips"]:
            k = c
            if project.is_group(c):
                inner = _subst(c["tracks"], over)
                if inner is not c["tracks"]:
                    k = dict(c, tracks=inner)
            for prop, v in over.get(c["id"], ()):
                if prop == "visible":
                    if not v:
                        k = None
                        break
                    hidden = False
                else:
                    k = _put(k, prop, v)
            if k is not c:
                moved = True
            if k is not None:
                clips.append(k)
        if moved or hidden != tr.get("hidden"):
            tr = dict(tr, clips=clips, hidden=bool(hidden))
            changed = True
        out.append(tr)
    return out if changed else tracks


def _put(c, prop, v):
    """A copy of layer c with prop set to v."""
    if prop == "content":
        return dict(c, text=dict(c["text"], content=str(v)))
    if prop == "text_color":
        styles = [{k: x for k, x in st.items() if k != "color"} for st in c["text"].get("styles") or []]
        return dict(c, text=dict(c["text"], color=[float(x) for x in v[:3]], styles=styles))
    if prop in ("color", "color2", "stroke_color"):
        return dict(c, asset=dict(c["asset"], **{prop: assets.clean(prop, v)})) if c.get("asset") else c
    if prop == "source":
        size = media_size(v) if v else None
        if size is None:
            return c                                     # (no picture, or one that cannot be read)
        out = {k: x for k, x in c.items() if k != "asset"}
        out["media"] = {"path": v, "width": size[0], "height": size[1]}
        return out
    return c


_sizes = {}


def media_size(path):
    """(width, height) of a picture file, or None when it cannot be read."""
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return None
    if key not in _sizes:
        try:
            if svgimage.is_svg(path):
                w, h = svgimage.size(path)
            else:
                from PIL import Image
                with Image.open(path) as im:
                    w, h = im.size
            _sizes[key] = (int(round(w)), int(round(h)))
        except Exception:
            _sizes[key] = None
    return _sizes[key]


def clean(p, v):
    """A value as stored for parameter p."""
    kind = p["kind"]
    if kind == "color":
        return [float(x) for x in assets.clean("color", v)]
    if kind == "visible":
        return bool(v)
    return "" if v is None else str(v)
