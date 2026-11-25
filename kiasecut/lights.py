"""燈光 objects: clips of a scene that light its solids drawn with 進階光照 (mesh3d.py). They draw nothing themselves.

A light is an 空物體 clip with c["light"] = {"kind", "power" (%), "color" [r, g, b]}; its place is the clip's transform (x, y, z), the way
a 平行光 shines the clip's 旋轉 (as a camera object looks). While a scene has one playing, the scene's lights are the ones that light
it instead of the two lamps it has by itself:

    sun     平行光: shines one way everywhere; where it is changes nothing
    point   點光源: shines every way from its place, weaker the farther (at REACH half-heights it is as strong as a 平行光 of its power)
    ambient 環境光: how much the studio round the scene lights it (without one, AMBIENT of what it does with no lights at all)

A 平行光 or 點光源 with c["light"]["shadow"] casts shadows (shadows.py), "darkness" (%) dark and with an edge "softness" (px of a
1080-high canvas) soft: on solids and on picture planes, from both. A clip with c["shade"] = {"cast": False} casts none, with
{"receive": False} none falls on it.
"""
import numpy as np

from . import camera, curves
from . import shadows as shadows_

KINDS = {"sun": "平行光", "point": "點光源", "ambient": "環境光"}
MOST = 8                   # lamps (平行光 and 點光源) a scene is lit by
STRENGTH = 0.85            # a 100 % lamp (the main lamp a scene has by itself)
REACH = 2.0                # half-heights
AMBIENT = 0.35             # the studio's share with lamps and no 環境光
FROM = (-0.50, -0.65, -0.57)      # where a new 平行光 shines from: high on the left on the viewer's side


def is_clip(c):
    return bool(c.get("light")) and c.get("type") == "image"


DARKNESS, SOFTNESS = 70.0, 6.0     # %, px of a 1080-high canvas: a shadow's, unless the light says otherwise


def new_settings(kind):
    out = {"kind": kind, "power": 100.0, "color": [1.0, 1.0, 1.0]}
    if kind != "ambient":                          # (投射陰影: a light of an older project has none until it is switched on)
        out.update(shadow=True, darkness=DARKNESS, softness=SOFTNESS)
    return out


def shaded(c, key):
    """Whether clip c of a scene casts ("cast") / receives ("receive") shadows: every clip does, unless it says not."""
    return bool((c.get("shade") or {}).get(key, True))


def new_transform(kind):
    """The x, y, z and turns a new light of `kind` stands with."""
    if kind == "sun":
        from_ = np.array(FROM) / np.linalg.norm(FROM)
        return dict({"x": -0.9, "y": 0.9, "z": -0.9}, **camera.looking(np.zeros(3), -from_))
    if kind == "point":
        return {"x": -0.6, "y": 0.6, "z": -1.0}
    return {"x": 0.9, "y": 0.9, "z": 0.0}


def read(c, t, W, H):
    """What light clip c is at clip time t: {"kind", "color": (r, g, b) linear times its power, "place": world px, "to": the way to a
    平行光 from anywhere}."""
    light, tf = c.get("light") or {}, c.get("transform") or {}
    v = lambda d, key, default: float(curves.value(d.get(key, default), t))
    power = max(0.0, v(light, "power", 100.0)) / 100.0
    colour = np.clip(np.array((list(light.get("color") or [1.0, 1.0, 1.0]) + [1.0] * 3)[:3], float), 0.0, 1.0) ** 2.2
    s = H / 2.0
    place = (v(tf, "x", 0.0) * W / 2.0, -v(tf, "y", 0.0) * s, v(tf, "z", 0.0) * s)
    forward = camera._rot(v(tf, "rot_x", 0.0), v(tf, "rot_y", 0.0), v(tf, "rotation", 0.0))[:, 2]
    return {"kind": light.get("kind", "sun"), "color": tuple(colour * power), "place": place, "to": tuple(-forward),
            "shadow": bool(light.get("shadow")) and power > 0,
            "darkness": min(1.0, max(0.0, v(light, "darkness", DARKNESS) / 100.0)),
            "softness": max(0.0, v(light, "softness", SOFTNESS)) * H / 1080.0}


def rig(found, H):
    """What mesh3d.Drawer lights a scene with, from the lights `found` (read()) playing in it, or None for none (the scene's own
    lamps): {"lamps": [(place or the way to it, 1 for a place / 0 for a way, colour)], "ambient": (r, g, b)}."""
    if not found:
        return None
    lamps = [(f["place"] if f["kind"] == "point" else f["to"], 1.0 if f["kind"] == "point" else 0.0,
              tuple(x * STRENGTH for x in f["color"])) for f in found if f["kind"] in ("sun", "point")]
    around = [f for f in found if f["kind"] == "ambient"]
    ambient = tuple(np.sum([f["color"] for f in around], axis=0)) if around else (AMBIENT,) * 3
    cast = [(i, f) for i, f in enumerate([f for f in found if f["kind"] in ("sun", "point")][:MOST]) if f.get("shadow")]
    shadows = [{"lamp": i, "from": lamps[i][0], "w": lamps[i][1], "darkness": f["darkness"], "softness": f["softness"]}
               for i, f in cast[:shadows_.MOST]]
    return {"lamps": lamps[:MOST], "ambient": ambient, "reach": REACH * H / 2.0, "shadows": shadows}
