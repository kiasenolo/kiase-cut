"""Components (元件): compounds with parameters.

A component is a compound marked component: true, with params: [param] - a live one (元件,
edited on its timeline) or a static one (靜態元件, project.is_static: edited as layers).
Every clip that shows it (an instance) draws it with its own values for those parameters,
kept in clip["params"] {param id: value}; a parameter it leaves out shows what the component
itself has. Instance values animate like any other parameter (curves.py), in the instance's
time: colours blend between keyframes, words, pictures and switches hold until the next one
- an animated static instance is drawn afresh for each frame. A value holds for the whole
content: it replaces the layer's own (keyframed or not).

param {id, name, kind: text | color | image | visible, binds: [[clip id, prop]]}
      binds: the clips of the component's content (inside its groups too) it sets and what
      of them (PROPS); one parameter can set several clips (a 主色 for three shapes). Its
      default is what its first clip has at that clip's start (a static one: at the
      picture's moment). A clip that was deleted leaves its binding behind, unused. Visibility
      only touches the picture (a hidden clip still sounds, as on a hidden track).

Values: text a str, color [r, g, b, a] (0 - 1), image a picture file's path, visible a bool.

An image parameter's picture can also be placed in its layer's frame, per instance:
clip["places"] {param id: {cx, cy, w, h}} - its centre in half-frame units (y up) and its size
as fractions of the frame, as a mask's are (each animates like any value; absent: the whole
frame). It reaches the layer as layer["place"] (the renderers draw the picture there).
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
PLACE = {"cx": 0.0, "cy": 0.0, "w": 1.0, "h": 1.0}     # an image parameter's placement (the whole frame)


def is_component(comp):
    return bool(comp) and bool(comp.get("component"))


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
    """What clip c has for prop at its start (a static component's layers: the picture's moment)."""
    if prop == "content":
        return c["text"].get("content", "")
    if prop == "text_color":
        col = curves.value(c["text"].get("color", [1.0, 1.0, 1.0]), 0)
        return [float(v) for v in col[:3]] + [1.0]
    if prop in ("color", "color2", "stroke_color"):
        return assets.clean(prop, curves.value(c["asset"].get(prop), 0))
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


def place_of(c, pid, t=None):
    """Instance c's placement of image parameter pid: its stored dict with what it leaves out
    filled in (kind "place", for the preview's box) - at clip time t: numbers."""
    own = (c.get("places") or {}).get(pid) or {}
    out = dict(PLACE, **own, kind="place")
    return out if t is None else {k: (curves.value(v, t) if k in PLACE else v) for k, v in out.items()}


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
    own = c.get("params") or {}
    places = c.get("places") or {}
    if not (own or places) or not is_component(comp):
        return comp
    over = {}
    for p in params(comp):
        if p["id"] in own:
            v = curves.value(own[p["id"]], t)
            for cid, prop in p.get("binds") or []:
                over.setdefault(cid, []).append((prop, v))
        if p["kind"] == "image" and places.get(p["id"]):
            pl = {k: float(curves.value(places[p["id"]].get(k, d), t)) for k, d in PLACE.items()}
            if pl != PLACE:
                for cid, prop in p.get("binds") or []:
                    if prop == "source":
                        over.setdefault(cid, []).append(("place", pl))
    if not over:
        return comp
    tracks = _subst(comp["tracks"], over)
    return comp if tracks is comp["tracks"] else dict(comp, tracks=tracks)


def _subst(tracks, over):
    """tracks with the values put in (the very list when nothing changed). A clip shown on a
    hidden track goes onto a shown copy of it, the others staying hidden."""
    out, changed = [], False
    for tr in tracks:
        clips, shown, moved = [], [], False
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
                    if tr.get("hidden"):
                        shown.append(c["id"])
                else:
                    k = _put(k, prop, v)
            if k is not c:
                moved = True
            if k is not None:
                clips.append(k)
        if shown:
            out.append(dict(tr, clips=[k for k in clips if k["id"] not in shown]))
            tr = dict(tr, id=tr["id"] + ":shown", clips=[k for k in clips if k["id"] in shown], hidden=False)
            changed = True
        elif moved:
            tr = dict(tr, clips=clips)
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
    if prop == "place":
        return dict(c, place=v) if c["type"] == "image" else c
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
