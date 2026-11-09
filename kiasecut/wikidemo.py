"""示範圖 for the 說明 Wiki: what a node does, shown by running the real filter on a sample picture. tools/make_wiki_demos.py draws them
into kiasecut/wikiimg/ (one folder per node, a JPEG per tile, the sample inputs in _in/); the wiki shows the ones that exist (wiki.demo).

DEMOS says what to show for a node: {"in": sample picture the node's main input gets ("none": a generator, there is no input to show),
"inputs": {@input name: sample}, "tiles": [(caption, {parameter: value}, output name or None)]}. A node not in it is shown at its defaults on
the "scene" picture, one tile for each output. A menu parameter's value is the choice's name."""
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import fx

W, H = 400, 224                    # a tile is drawn this big and kept at half of it
TILE = (W // 2, H // 2)
DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wikiimg")


def slug(ref):
    return ref.replace("builtin:", "").replace("/", "_").replace(":", "_")


# -- the sample pictures --------------------------------------------------------------------------------------------------------------
def _lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def scene():
    """A sunset: sky, sun, mountains, a hill with trees, two balloons - colour, detail and a bright spot for the nodes to work on."""
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        d.line([(0, y), (W, y)], fill=_lerp((38, 52, 110), (255, 178, 112), min(1.0, y / (H * 0.62))))
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse((262, 70, 342, 150), fill=255)
    img.paste((255, 236, 170), (0, 0), glow.filter(ImageFilter.GaussianBlur(26)).point(lambda v: v * 0.6))
    d = ImageDraw.Draw(img)
    d.ellipse((282, 90, 322, 130), fill=(255, 248, 215))
    d.polygon([(0, 150), (70, 96), (130, 140), (190, 84), (270, 150), (270, 224), (0, 224)], fill=(92, 62, 112))
    d.polygon([(150, 160), (240, 110), (330, 156), (400, 118), (400, 224), (150, 224)], fill=(64, 44, 92))
    d.polygon([(0, 190), (90, 168), (200, 182), (300, 164), (400, 184), (400, 224), (0, 224)], fill=(46, 124, 84))
    for x, y, s in ((40, 186, 16), (70, 192, 12), (330, 182, 15), (360, 190, 11)):
        d.polygon([(x, y - s * 2), (x - s // 2, y), (x + s // 2, y)], fill=(24, 74, 52))
    d.ellipse((92, 52, 132, 96), fill=(226, 52, 60))
    d.line([(112, 96), (112, 116)], fill=(255, 255, 255), width=1)
    d.ellipse((150, 28, 180, 62), fill=(250, 208, 50))
    d.line([(165, 62), (165, 78)], fill=(255, 255, 255), width=1)
    for x, y in ((196, 40), (214, 34), (230, 44)):
        d.arc((x, y, x + 12, y + 8), 200, 340, fill=(255, 255, 255), width=1)
    for x in range(0, W, 20):                                    # a row of small marks along the bottom: fine detail
        d.rectangle((x + 4, 208, x + 8, 216), fill=_lerp((255, 255, 255), (255, 120, 140), (x // 20) / 20))
    return img


def scene2():
    img = Image.new("RGB", (W, H), (20, 120, 130))
    d = ImageDraw.Draw(img)
    for i in range(-H, W, 36):
        d.polygon([(i, 0), (i + 18, 0), (i + 18 + H, H), (i + H, H)], fill=(214, 70, 150))
    for cx, cy in ((80, 70), (200, 120), (320, 60), (300, 170)):
        d.ellipse((cx - 28, cy - 28, cx + 28, cy + 28), fill=(255, 226, 120), outline=(40, 40, 70), width=3)
    return img


def mask():
    img = Image.new("L", (W, H), 0)
    ImageDraw.Draw(img).rounded_rectangle((70, 40, 330, 184), radius=44, fill=255)
    return img.filter(ImageFilter.GaussianBlur(2)).convert("RGB")


def ramp():
    """A smooth ramp on top, five steps under it."""
    a = np.zeros((H, W, 3), np.uint8)
    a[: H // 2] = (np.linspace(0, 255, W)[None, :, None]).astype(np.uint8)
    a[H // 2:] = (np.floor(np.linspace(0, 5, W, endpoint=False))[None, :, None] / 4 * 255).clip(0, 255).astype(np.uint8)
    return Image.fromarray(a)


def uvmap():
    """A UV picture (red = x, green = y) with a ripple in it: what Map UV bends the picture by."""
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    u, v = x / (W - 1), 1 - y / (H - 1)
    u2 = u + 0.03 * np.sin(v * math.pi * 6)
    v2 = v + 0.03 * np.sin(u * math.pi * 6)
    a = np.stack([u2, v2, np.ones_like(u)], -1).clip(0, 1)
    return Image.fromarray((a * 255).astype(np.uint8))


def badge():
    """A picture with transparency: a ring and a dot on nothing."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((120, 40, 280, 184), fill=(230, 60, 80, 200), outline=(255, 255, 255, 255), width=8)
    d.ellipse((176, 84, 224, 140), fill=(255, 255, 255, 230))
    return img


SAMPLES = {"scene": scene, "scene2": scene2, "mask": mask, "ramp": ramp, "uvmap": uvmap, "badge": badge}
CAPTIONS = {"scene": "輸入", "scene2": "B", "mask": "遮罩", "ramp": "輸入", "uvmap": "UV 圖", "badge": "前景"}


def premultiplied(img):
    a = np.asarray(img.convert("RGBA"), np.float32)
    a[..., :3] *= a[..., 3:] / 255.0
    return np.ascontiguousarray(a.round().astype(np.uint8))


def checker(w=W, h=H, size=16):
    y, x = np.mgrid[0:h, 0:w]
    c = np.where(((x // size) + (y // size)) % 2 == 0, 200, 150).astype(np.uint8)
    return np.stack([c, c, c], -1)


def shown(premult):
    """A premultiplied RGBA array as a picture to show: over a checkerboard where it is see-through."""
    p = premult.astype(np.float32)
    a = p[..., 3:] / 255.0
    rgb = p[..., :3] + (1 - a) * checker(premult.shape[1], premult.shape[0]).astype(np.float32)
    return Image.fromarray(rgb.clip(0, 255).astype(np.uint8))


def tile(img):
    return img.resize(TILE, Image.LANCZOS)


# -- what to show ----------------------------------------------------------------------------------------------------------------------
def _t(caption, **over):
    return (caption, over, None)


NO_DEMO = ("boolean", "integer", "integer_vector", "menu", "value", "vector", "image_info", "time")      # (a number or a vector is no picture to look at)
DEMOS = {
    "blur": {"tiles": [_t("大小 4", radius=4, radius_y=4), _t("大小 12", radius=12, radius_y=12), _t("大小 32", radius=32, radius_y=32)]},
    "motion_blur": {"tiles": [_t("距離 15", amount=15, angle=0), _t("距離 40", amount=40, angle=0), _t("距離 80，角度 30", amount=80, angle=30)]},
    "lens_blur": {"tiles": [_t("半徑 6", radius=6), _t("半徑 14", radius=14), _t("半徑 28", radius=28)]},
    "posterize": {"tiles": [_t("色階 8", levels=8), _t("色階 4", levels=4), _t("色階 2", levels=2)]},
    "pixelate": {"tiles": [_t("方塊 6", size=6), _t("方塊 12", size=12), _t("方塊 28", size=28)]},
    "nodes/mix": {"inputs": {"b": "scene2"}, "tiles": [_t("係數 0.3", fac=0.3), _t("係數 0.7", fac=0.7), _t("相乘", blend="相乘")]},
    "nodes/alpha_over": {"inputs": {"b": "badge"}, "tiles": [_t("疊上去")]},
    "nodes/set_alpha": {"inputs": {"alpha_img": "mask"}, "tiles": [_t("透明度接遮罩")]},
    "nodes/split": {"inputs": {"b": "scene2"}, "tiles": [_t("位置在中間")]},
    "nodes/switch": {"inputs": {"yes": "scene2"}, "tiles": [_t("開關關：假", use_true=False), _t("開關開：真", use_true=True)]},
    "nodes/index_switch": {"inputs": {"i2": "scene2"}, "tiles": [_t("索引 0", index=0), _t("索引 1", index=1)]},
    "nodes/menu_switch": {"inputs": {"i2": "scene2"}, "tiles": [_t("選項 1", choice="選項 1"), _t("選項 2", choice="選項 2")]},
    "nodes/map_uv": {"inputs": {"uv": "uvmap"}, "tiles": [_t("用 UV 圖取色")]},
    "nodes/dilate_erode": {"in": "mask", "tiles": [_t("擴張 6", size=6), _t("擴張 16", size=16), _t("侵蝕 16", size=-16)]},
    "nodes/clamp": {"in": "ramp", "tiles": [_t("0.3 ~ 0.7", lo=0.3, hi=0.7), _t("0.2 ~ 0.5", lo=0.2, hi=0.5), _t("0.5 ~ 0.8", lo=0.5, hi=0.8)]},
    "nodes/map_range": {"in": "ramp", "tiles": [_t("對應到 0.25 ~ 0.75", to_min=0.25, to_max=0.75), _t("對應到 0.5 ~ 1", to_min=0.5, to_max=1.0), _t("對應到 1 ~ 0（反過來）", to_min=1.0, to_max=0.0)]},
    "nodes/float_curve": {"in": "ramp"},
    "nodes/math": {"in": "ramp", "tiles": [_t("相乘，B = 0.5", op="相乘", value=0.5), _t("相加，B = 0.4", op="相加", value=0.4),
                                          _t("次方，B = 2", op="次方", value=2.0)]},
    "nodes/filter": {"tiles": [_t("柔化", kind="柔化"), _t("方塊銳利化", kind="方塊銳利化"), _t("索伯（邊緣）", kind="索伯")]},
    "nodes/flip": {"tiles": [_t("水平翻轉", flip_x=True, flip_y=False), _t("垂直翻轉", flip_x=False, flip_y=True), _t("兩個都開", flip_x=True, flip_y=True)]},
    "nodes/rotate": {"tiles": [_t("15°", angle=15), _t("45°", angle=45), _t("90°", angle=90)]},
    "nodes/blackbody": {"in": "none", "tiles": [_t("1800 K", temperature=1800), _t("5000 K", temperature=5000), _t("12000 K", temperature=12000)]},
    "nodes/rgb": {"in": "none", "tiles": [_t("紅", color=[0.9, 0.2, 0.25, 1.0]), _t("綠", color=[0.2, 0.7, 0.35, 1.0]), _t("藍", color=[0.2, 0.4, 0.9, 1.0])]},
    "nodes/rounded_square_mask": {"tiles": [_t("圓角 0", size=[0.6, 0.5], roundness=0.0), _t("圓角 0.4", size=[0.6, 0.5], roundness=0.4), _t("圓角 0.8，羽化", size=[0.6, 0.5], roundness=0.8, feather=0.3)]},
    "nodes/normalize": {"in": "ramp"},
    "nodes/rgb_to_bw": {"in": "scene"},
    "blender_glare": {"tiles": [("Bloom", {"type": "Bloom", "threshold": 0.6}, "image"), ("Streaks", {"type": "Streaks", "threshold": 0.6}, "image"),
                                ("Fog Glow", {"type": "Fog Glow", "threshold": 0.6}, "image")]},
    "nodes/exposure": {"tiles": [_t("-1 檔", exposure=-1), _t("+1 檔", exposure=1), _t("+2 檔", exposure=2)]},
    "nodes/gamma": {"tiles": [_t("0.5", gamma=0.5), _t("1.5", gamma=1.5), _t("2.5", gamma=2.5)]},
    "nodes/hue_sat_value": {"tiles": [_t("色相 0.25", hue=0.25), _t("色相 0.75", hue=0.75), _t("飽和度 2", sat=2.0)]},
}


CONSTANTS = ("boolean", "rgb", "integer", "integer_vector", "menu", "value", "vector", "image_info", "coordinate", "time", "blackbody")


def is_generator(ref, d):
    """A node that makes a picture from nothing - a texture (its main input is a vector), a constant, a "產生" effect: there is no input to show."""
    name = ref.replace("builtin:", "", 1)
    return (d.socket_type("in", "src") == "vector" or name.startswith("blender_tex_") or d.category == "產生"
            or (name.startswith("nodes/") and name.split("/", 1)[1] in CONSTANTS))


def spec(ref, d):
    got = DEMOS.get(ref.replace("builtin:", "", 1), {})
    out = {"in": "scene", "inputs": {}, "tiles": None}
    out.update(got)
    if not out["tiles"]:
        names = [(n, l) for n, l in d.outputs][:4]
        out["tiles"] = [(l, {}, n) for n, l in names] if names else [("結果", {}, None)]
    if "in" not in got and is_generator(ref, d):
        out["in"] = "none"
    for name, _label in d.inputs:                         # (a picture is given only to a socket that takes one - not a number's or a colour's)
        if name not in d.input_param and d.socket_type("in", name) == "image" and not name.startswith("fac"):
            out["inputs"].setdefault(name, "scene2")
    return out


def values_for(d, over):
    vals = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
    by = {p.name: p for p in d.params}
    for k, v in over.items():
        p = by[k]
        vals[k] = fx.menu_index(p, v) if p.type == "menu" and isinstance(v, str) else v
    return vals


def run(eng, d, vals, src, inputs, output, src_on=True):
    """One draw of filter d: src and the inputs are premultiplied RGBA arrays of the same size; returns the result as an array."""
    h, w = src.shape[:2]
    with eng.ctx:
        (ta, _), _, _ = eng._targets(w, h)
        ta.write(np.ascontiguousarray(src).tobytes())
        texs = {}
        try:
            for name, pic in inputs.items():
                t = eng.ctx.texture((w, h), 4, np.ascontiguousarray(pic).tobytes())
                t.filter = (eng.mgl.LINEAR, eng.mgl.LINEAR)
                texs[name] = t
            outs = eng.run_tex(d, vals, ta, w, h, 1.0, 0.5, 30, h / 1080, None, texs, None, output, src_on)
            data = outs.read()
        finally:
            for t in texs.values():
                t.release()
    return np.frombuffer(data, np.uint8).reshape(h, w, 4)


def got_tiles(ref):
    return bool(DEMOS.get(ref.replace("builtin:", "", 1), {}).get("tiles"))


def difference(a, b):
    return float(np.abs(a[..., :3].astype(np.int16) - b[..., :3].astype(np.int16)).mean())


def visible_variant(eng, d, src, inputs):
    """Three tiles, low / middle / high, of the number parameter whose raising changes the picture most (two steps are hard to tell apart;
    three show which way it goes); none when no parameter does."""
    best = None
    for p in d.params:
        if p.type != "float" or not p.lo < p.hi <= 1000 or p.panel:
            continue
        v = p.lo + (p.hi - p.lo) * 0.6
        try:
            out = run(eng, d, values_for(d, {p.name: v}), src, inputs, 0)
        except Exception:
            continue
        gain = difference(out, src)
        if gain > 4 and (best is None or gain > best[0]) and difference(out, np.zeros_like(out)) > 8:
            best = (gain, p)
    if best is None:
        return []
    p = best[1]
    return [(f"{p.label} = {v:g}", {p.name: v}, None) for v in (p.lo + (p.hi - p.lo) * k for k in (0.2, 0.45, 0.7))]


def make(eng, ref):
    """[(caption, picture, "in" or "out")] of the demo of filter `ref`: the input(s) it was given first, then each result."""
    d = fx.get(ref)
    if d.error or ref.replace("builtin:", "", 1).replace("nodes/", "", 1) in NO_DEMO and ref.startswith("builtin:nodes/"):
        return []
    s = spec(ref, d)
    cache = {}

    def sample(name):
        if name not in cache:
            cache[name] = SAMPLES[name]()
        return cache[name]
    src_name = s["in"]
    blank = np.zeros((H, W, 4), np.uint8)
    src = blank if src_name == "none" else premultiplied(sample(src_name))
    inputs = {n: premultiplied(sample(sn)) for n, sn in s["inputs"].items()}
    tiles = []
    if src_name != "none":
        tiles.append((CAPTIONS.get(src_name, "輸入"), shown(src), "in"))
    for n, sn in s["inputs"].items():
        label = next((l for k, l in d.inputs if k == n), n)
        tiles.append((label, shown(inputs[n]), "in"))
    names = [n for n, _ in d.outputs]
    tiles_spec = list(s["tiles"])
    if not got_tiles(ref) and s["in"] != "none" and not names:
        tiles_spec = visible_variant(eng, d, src, inputs) or tiles_spec
    for caption, over, out in tiles_spec:
        vals = values_for(d, over)
        index = names.index(out) if out in names else 0
        tiles.append((caption, shown(run(eng, d, vals, src, inputs, index, src_name != "none")), "out"))
    return tiles


def index():
    """{slug: [[caption, "in" | "out"], ...]} of the demos that are drawn (kiasecut/wikiimg/index.json)."""
    import json
    try:
        with open(os.path.join(DIR, "index.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}
