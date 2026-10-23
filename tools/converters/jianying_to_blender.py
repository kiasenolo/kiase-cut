"""Convert a decrypted Jianying (剪映) draft_content.json into a Blender VSE project.

  python jianying_to_blender.py draft_content.dec.json OUT_DIR [--blender PATH]

Stage 1 (this script, needs Pillow + numpy) flattens the draft into timeline.json,
renders every text as a PNG (font size, letter/line spacing, italic, colour) and
bakes every mask (line/circle/rect/mirror, animated, inverted) into matte frames.
Stage 2 (jy_build.py, run inside Blender) builds strips, meta strips for compound
clips, keyframes with Jianying's exact bezier handles, opacity and mask modifiers.

Conventions below were calibrated against a Jianying export of the same draft.
"""
import argparse
import glob
import hashlib
import json
import math
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# --- calibrated constants -----------------------------------------------------------------
PX_PER_FONT_UNIT = 11.13   # Jianying font_size 1.0 -> em px on a 1080p canvas
FALLBACK_FONTS = [r"C:\Windows\Fonts\GenSekiGothic2-M.ttc", r"C:\Windows\Fonts\msjh.ttc"]

US = 1_000_000


# --- keyframe curves ------------------------------------------------------------------------
def seg_keyframes(seg):
    return {k["property_type"]: k["keyframe_list"]
            for k in seg.get("common_keyframes", []) if k.get("keyframe_list")}


def make_curve(kf_list, t0_us, conv, slope):
    """Jianying keyframes -> [(t_us, value, (ldt, ldv), (rdt, rdv))] on the parent timeline.

    conv maps a Jianying value to the target unit; slope is d(conv)/dv for handle offsets.
    """
    out = []
    for k in kf_list:
        lc, rc = k.get("left_control", {}), k.get("right_control", {})
        out.append((t0_us + k.get("time_offset", 0), conv(k["values"][0]),
                    (lc.get("x", 0.0), lc.get("y", 0.0) * slope),
                    (rc.get("x", 0.0), rc.get("y", 0.0) * slope)))
    out.sort(key=lambda x: x[0])
    return out


def eval_curve(curve, t):
    if t <= curve[0][0]:
        return curve[0][1]
    if t >= curve[-1][0]:
        return curve[-1][1]
    for a, b in zip(curve, curve[1:]):
        if a[0] <= t <= b[0]:
            break
    x0, y0, x3, y3 = a[0], a[1], b[0], b[1]
    x1, y1 = x0 + a[3][0], y0 + a[3][1]
    x2, y2 = x3 + b[2][0], y3 + b[2][1]
    lo, hi = 0.0, 1.0
    for _ in range(50):
        s = (lo + hi) / 2
        x = (1 - s) ** 3 * x0 + 3 * (1 - s) ** 2 * s * x1 + 3 * (1 - s) * s * s * x2 + s ** 3 * x3
        lo, hi = (s, hi) if x < t else (lo, s)
    s = (lo + hi) / 2
    return (1 - s) ** 3 * y0 + 3 * (1 - s) ** 2 * s * y1 + 3 * (1 - s) * s * s * y2 + s ** 3 * y3


class Prop:
    """A static value or a keyframed curve."""

    def __init__(self, static, curve=None):
        self.static, self.curve = static, curve

    def at(self, t):
        return eval_curve(self.curve, t) if self.curve else self.static

    def max_abs(self):
        return max(abs(c[1]) for c in self.curve) if self.curve else abs(self.static)

    def export(self, fps, scale=1.0):
        if not self.curve:
            return self.static * scale
        f = fps / US
        return [[c[0] * f, c[1] * scale, c[2][0] * f, c[2][1] * scale, c[3][0] * f, c[3][1] * scale]
                for c in self.curve]


# --- text rendering -------------------------------------------------------------------------
_fonts = {}


def get_font(path, size):
    key = (path, round(size * 100))
    if key not in _fonts:
        for p in [path] + FALLBACK_FONTS:
            if p and os.path.exists(p):
                _fonts[key] = ImageFont.truetype(p, size, index=0)
                break
    return _fonts[key]


def render_text(mat, render_scale, canvas_h, out_path):
    """Render one Jianying text material at render_scale; the PNG centre is the box centre."""
    c = json.loads(mat["content"])
    text = c["text"]
    styles = c.get("styles") or [{}]
    unit = PX_PER_FONT_UNIT * canvas_h / 1080 * render_scale

    def style_at(i):
        for s in styles:
            r = s.get("range", [0, len(text)])
            if r[0] <= i < r[1]:
                return s
        return styles[0]

    ls = mat.get("letter_spacing", 0.0)
    lsp = mat.get("line_spacing", 0.0)
    italic = mat.get("italic_degree", 0) if any(s.get("italic") for s in styles) else 0
    alpha = mat.get("global_alpha", 1.0)

    # lay out glyphs per line: [(x, char, font, rgba)], line width
    base_em = mat.get("font_size", styles[0].get("size", 5)) * unit
    lines, cur, x, i = [], [], 0.0, 0
    for ch in text:
        st = style_at(i)
        i += 1
        if ch == "\n":
            lines.append((cur, x))
            cur, x = [], 0.0
            continue
        em = st.get("size", mat.get("font_size", 5)) * unit
        font = get_font(st.get("font", {}).get("path") or mat.get("font_path"), em)
        col = st.get("fill", {}).get("content", {}).get("solid", {}).get("color", [1, 1, 1])
        rgba = tuple(int(round(v * 255)) for v in col[:3]) + (255,)
        if cur:
            x += ls * base_em
        cur.append((x, ch, font, rgba))
        # unhinted advance: small sizes round each glyph and drift across a long line
        x += get_font(font.path, 1000).getlength(ch) / 1000 * em
    lines.append((cur, x))

    # PIL rounds metrics up to whole pixels; Jianying's line pitch is exactly em * (1 + lsp)
    asc, desc = (m / 1000 * base_em for m in get_font(mat.get("font_path"), 1000).getmetrics())
    line_h = asc + desc
    step = line_h + lsp * base_em
    box_w = max(w for _, w in lines)

    # the box grows to fit glyphs poking past the font's ascent (first line) / descent (last)
    def ink(glyphs, edge):
        vals = [(-g[2].getbbox(g[1], anchor="ls")[1]) if edge == "top" else
                g[2].getbbox(g[1], anchor="ls")[3] for g in glyphs if g[1].strip()]
        return max(vals, default=0)

    ext_top = max(0.0, ink(lines[0][0], "top") - asc)
    ext_bot = max(0.0, ink(lines[-1][0], "bottom") - desc)
    box_h = ext_top + line_h + step * (len(lines) - 1) + ext_bot
    shear = math.tan(math.radians(italic))
    pad = int(base_em * (0.3 + abs(shear))) + 4
    W = int(math.ceil(box_w)) + 2 * pad
    H = int(math.ceil(box_h)) + 2 * pad
    W += W % 2
    H += H % 2
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    for li, (glyphs, lw) in enumerate(lines):
        ox = (W - lw) / 2
        top = (H - box_h) / 2 + ext_top + li * step
        for gx, ch, font, rgba in glyphs:
            dr.text((ox + gx, top + asc), ch, font=font, fill=rgba, anchor="ls")
    if shear:
        # lean right around the box centre
        im = im.transform(im.size, Image.AFFINE, (1, shear, -shear * H / 2, 0, 1, 0),
                          resample=Image.BICUBIC)
    im.save(out_path)
    # the same layout in unscaled px, so other engines can set the text natively
    glyphs = [g for gl, _ in lines for g in gl]
    k = 1 / render_scale
    layout = {
        "text": text, "font_path": mat.get("font_path"), "italic": italic,
        "uniform": len({(g[2].size, g[3]) for g in glyphs}) <= 1,
        "rgba": glyphs[0][3] if glyphs else (255, 255, 255, 255),
        "em": base_em * k, "ls_px": ls * base_em * k, "lsp": lsp,
        "asc": asc * k, "ext_top": ext_top * k, "step": step * k,
        "box_w": box_w * k, "box_h": box_h * k, "rs": render_scale,
    }
    return W, H, alpha, layout


# --- media probing ----------------------------------------------------------------------------
_starts = {}


def media_start(path):
    """First audio sample's timestamp (e.g. MP3 encoder delay); 0 if ffprobe is unavailable."""
    if path not in _starts:
        try:
            r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                                "stream=start_time", "-of", "csv=p=0", path],
                               capture_output=True, text=True, timeout=30)
            _starts[path] = float(r.stdout.strip() or 0)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            _starts[path] = 0.0
    return _starts[path]


# --- masks -----------------------------------------------------------------------------------
def mask_alpha(kind, cfg, xs, ys):
    """xs/ys: pixel coords in mask space (origin at mask centre, y up, mask-rotated)."""
    w, h = cfg["w"], cfg["h"]
    if kind == "line":
        d = ys
    elif kind == "mirror":
        d = h / 2 - np.abs(ys)
    elif kind == "circle":
        rx, ry = max(w / 2, 1e-6), max(h / 2, 1e-6)
        r = np.sqrt((xs / rx) ** 2 + (ys / ry) ** 2)
        d = (1 - r) * min(rx, ry)
    elif kind == "rectangle":
        d = np.minimum(w / 2 - np.abs(xs), h / 2 - np.abs(ys))
    else:
        return None
    feather = cfg.get("feather", 0.0) * max(min(w, h) if kind != "line" else 0, 1) / 2
    soft = max(feather, 0.5)
    return np.clip(d / (2 * soft) + 0.5, 0, 1)


# --- draft walking ----------------------------------------------------------------------------
class Converter:
    def __init__(self, draft, out_dir):
        self.d = draft
        self.out = out_dir
        self.fps = draft["fps"]
        self.W = draft["canvas_config"]["width"]
        self.H = draft["canvas_config"]["height"]
        self.n_text = 0
        self.n_mask = 0
        self.warnings = []
        # nested compound clips may live in any ancestor's material lists
        self.registry = {}
        self._collect(draft)
        os.makedirs(os.path.join(out_dir, "text"), exist_ok=True)
        os.makedirs(os.path.join(out_dir, "matte"), exist_ok=True)

    def _collect(self, draft):
        for kind, lst in draft.get("materials", {}).items():
            if isinstance(lst, list):
                for x in lst:
                    if isinstance(x, dict) and "id" in x:
                        self.registry.setdefault(kind, {}).setdefault(x["id"], x)
                        if kind == "drafts" and x.get("draft"):
                            self._collect(x["draft"])

    def materials(self, draft, kind):
        return {**self.registry.get(kind, {}),
                **{v["id"]: v for v in draft["materials"].get(kind, [])}}

    def fr(self, us):
        return int(round(us * self.fps / US))

    def seg_props(self, seg, t0, is_text):
        """Transform/opacity props (Jianying units) for a visual segment."""
        clip = seg.get("clip") or {}
        sc = clip.get("scale", {})
        tf = clip.get("transform", {})
        kfs = seg_keyframes(seg)
        ident = lambda v: v

        def prop(ptype, static):
            if ptype in kfs:
                return Prop(static, make_curve(kfs[ptype], t0, ident, 1.0))
            return Prop(static)

        uniform = (seg.get("uniform_scale") or {}).get("on", True)
        p = {
            "x": prop("KFTypePositionX", tf.get("x", 0.0)),
            "y": prop("KFTypePositionY", tf.get("y", 0.0)),
            "sx": prop("KFTypeScaleX", sc.get("x", 1.0)),
            "rot": prop("KFTypeRotation", clip.get("rotation", 0.0)),
            "alpha": prop("KFTypeGlobalAlpha" if is_text else "KFTypeAlpha",
                          clip.get("alpha", 1.0)),
        }
        p["sy"] = p["sx"] if uniform else prop("KFTypeScaleY", sc.get("y", 1.0))
        p["flip"] = (clip.get("flip") or {})
        p["kfs"] = kfs
        return p

    def export_transform(self, p, size_scale=1.0, alpha_mul=1.0):
        fps, W, H = self.fps, self.W, self.H
        return {
            "transform.offset_x": p["x"].export(fps, W / 2),
            "transform.offset_y": p["y"].export(fps, H / 2),
            "transform.scale_x": p["sx"].export(fps, size_scale),
            "transform.scale_y": p["sy"].export(fps, size_scale),
            "transform.rotation": p["rot"].export(fps, -math.pi / 180),
            "blend_alpha": p["alpha"].export(fps, alpha_mul),
        }

    def bake_mask(self, mask, seg, p, t0, start_us, end_us, disp_w, disp_h):
        """Bake a Jianying mask (material space) to screen-space matte frames."""
        kind = mask.get("resource_type")
        if kind not in ("line", "circle", "rectangle", "mirror"):
            self.warnings.append(f"mask type {kind!r} ({mask.get('name')}) not supported")
            return None
        cfg = mask.get("config", {})
        kfs = p["kfs"]
        ident = lambda v: v

        def mprop(name, static):
            k = "KFTypeCommonMask" + name
            return Prop(static, make_curve(kfs[k], t0, ident, 1.0)) if k in kfs else Prop(static)

        mp = {"cx": mprop("PositionX", cfg.get("centerX", 0.0)),
              "cy": mprop("PositionY", cfg.get("centerY", 0.0)),
              "w": mprop("SizeWidth", cfg.get("width", 1.0)),
              "h": mprop("SizeHeight", cfg.get("height", 1.0)),
              "rot": mprop("Rotation", cfg.get("rotation", 0.0)),
              "feather": mprop("Feather", cfg.get("feather", 0.0))}
        animated = any(v.curve for v in mp.values()) or any(
            p[k].curve for k in ("x", "y", "sx", "sy", "rot"))
        self.n_mask += 1
        f0, f1 = self.fr(start_us), self.fr(end_us)
        frames = range(f0, f1) if animated else [f0]
        W, H = self.W, self.H
        # cache by everything that shapes the matte, so re-runs skip unchanged masks
        sig = repr((kind, cfg, [(v.static, v.curve) for v in mp.values()],
                    [(p[k].static, p[k].curve) for k in ("x", "y", "sx", "sy", "rot")],
                    p["flip"], f0, f1, animated, disp_w, disp_h, W, H))
        mdir = os.path.join(self.out, "matte", hashlib.md5(sig.encode()).hexdigest()[:12])
        files = [f"{f:06d}.png" for f in frames]
        if all(os.path.exists(os.path.join(mdir, fn)) for fn in files):
            return {"dir": mdir, "files": files, "start": f0, "end": f1}
        os.makedirs(mdir, exist_ok=True)
        gx, gy = np.meshgrid(np.arange(W) + 0.5 - W / 2, H / 2 - (np.arange(H) + 0.5))
        for f in frames:
            t = f * US / self.fps
            # screen -> clip local (undo position, rotation (cw deg), scale)
            px, py = p["x"].at(t) * W / 2, p["y"].at(t) * H / 2
            a = math.radians(p["rot"].at(t))
            sx, sy = p["sx"].at(t), p["sy"].at(t)
            dx, dy = gx - px, gy - py
            lx = (dx * math.cos(a) - dy * math.sin(a)) / (sx or 1e-6)
            ly = (dx * math.sin(a) + dy * math.cos(a)) / (sy or 1e-6)
            if p["flip"].get("horizontal"):
                lx = -lx
            if p["flip"].get("vertical"):
                ly = -ly
            # local -> mask space
            cx, cy = mp["cx"].at(t) * disp_w / 2, mp["cy"].at(t) * disp_h / 2
            b = math.radians(mp["rot"].at(t))
            mx, my = lx - cx, ly - cy
            rx = mx * math.cos(b) - my * math.sin(b)
            ry = mx * math.sin(b) + my * math.cos(b)
            cfg_t = {"w": mp["w"].at(t) * disp_w, "h": mp["h"].at(t) * disp_h,
                     "feather": mp["feather"].at(t)}
            m = mask_alpha(kind, cfg_t, rx, ry)
            if cfg.get("invert"):
                m = 1 - m
            Image.fromarray((m * 255 + 0.5).astype(np.uint8), "L").save(
                os.path.join(mdir, f"{f:06d}.png"), compress_level=1)
        return {"dir": mdir, "files": files, "start": f0, "end": f1}

    def walk(self, draft, offset_us, win, depth=0):
        """Return strip nodes for one (sub)draft. offset_us: draft t=0 on the scene timeline."""
        vid = self.materials(draft, "videos")
        aud = self.materials(draft, "audios")
        txt = self.materials(draft, "texts")
        drf = self.materials(draft, "drafts")
        masks = self.materials(draft, "common_mask")
        fades = self.materials(draft, "audio_fades")
        nodes = []
        for ti, track in enumerate(draft["tracks"]):
            for seg in track.get("segments", []):
                tr = seg["target_timerange"]
                src_start = (seg.get("source_timerange") or {}).get("start", 0)
                s_us = offset_us + tr.get("start", 0)
                e_us = s_us + tr["duration"]
                a, b = max(s_us, win[0]), min(e_us, win[1])
                if b <= a:
                    continue
                t0 = s_us - src_start          # keyframe/material time zero
                mid = seg["material_id"]
                refs = seg.get("extra_material_refs", [])
                # stacking follows track order (later tracks on top), not render_index:
                # verified against an export where a video track covers earlier text tracks
                layer = (ti, 0)
                node = {"start": self.fr(a), "end": self.fr(b), "layer": layer}
                if track["type"] in ("video", "text") and (mid in vid or mid in txt):
                    is_text = mid in txt
                    p = self.seg_props(seg, t0, is_text)
                    sub = [drf[r] for r in refs if r in drf]
                    disp_w, disp_h = self.W, self.H
                    if is_text:
                        mat = txt[mid]
                        # never rasterise below 1:1; Blender scales the PNG down instead
                        rs = max(p["sx"].max_abs(), p["sy"].max_abs(), 1.0)
                        self.n_text += 1
                        png = os.path.join(self.out, "text", f"t{self.n_text:04d}.png")
                        w, h, ga, layout = render_text(mat, rs, self.H, png)
                        node["text"] = layout
                        if not p["alpha"].curve:
                            p["alpha"] = Prop(p["alpha"].static * ga)
                        node.update(type="image", path=png,
                                    name=json.loads(mat["content"])["text"].replace("\n", " ")[:16])
                        node["props"] = self.export_transform(p, 1 / rs)
                    elif sub:
                        inner = sub[0]["draft"]
                        node.update(type="meta", name=vid[mid].get("material_name") or "compound")
                        node["children"] = self.walk(inner, t0, (a, b), depth + 1)
                        node["props"] = self.export_transform(p)
                        cw = inner.get("canvas_config", {}).get("width", self.W)
                        ch = inner.get("canvas_config", {}).get("height", self.H)
                        k = min(self.W / cw, self.H / ch)
                        disp_w, disp_h = cw * k, ch * k
                    else:
                        v = vid[mid]
                        if not v.get("path") or not os.path.exists(v["path"]):
                            self.warnings.append(f"missing media {v.get('path')!r}")
                            continue
                        k = min(self.W / v["width"], self.H / v["height"])
                        disp_w, disp_h = v["width"] * k, v["height"] * k
                        node.update(name=os.path.basename(v["path"]), path=v["path"], fit_scale=k)
                        if v["type"] == "photo":
                            node["type"] = "image"
                        else:
                            node.update(type="movie", content_start=self.fr(t0),
                                        volume=seg.get("volume", 1.0))
                        node["props"] = self.export_transform(p)
                    for r in refs:
                        if r in masks:
                            mk = self.bake_mask(masks[r], seg, p, t0, a, b, disp_w, disp_h)
                            if mk:
                                node["mask"] = mk
                    nodes.append(node)
                elif track["type"] == "audio" and mid in aud:
                    v = aud[mid]
                    if not os.path.exists(v["path"]):
                        self.warnings.append(f"missing audio {v['path']!r}")
                        continue
                    vol = seg.get("volume", 1.0)
                    kfs = seg_keyframes(seg)
                    if "KFTypeVolume" in kfs:
                        volp = Prop(vol, make_curve(kfs["KFTypeVolume"], t0, lambda x: x, 1.0))
                    else:
                        fd = [fades[r] for r in refs if r in fades]
                        fi = fd[0].get("fade_in_duration", 0) if fd else 0
                        fo = fd[0].get("fade_out_duration", 0) if fd else 0
                        if fi or fo:
                            z = (0, 0)
                            curve = []
                            if fi:
                                curve += [(s_us, 0.0, z, z), (s_us + fi, vol, z, z)]
                            else:
                                curve += [(s_us, vol, z, z)]
                            if fo:
                                curve += [(e_us - fo, vol, z, z), (e_us, 0.0, z, z)]
                            volp = Prop(vol, curve)
                        else:
                            volp = Prop(vol)
                    # Jianying honours the stream start_time (MP3 encoder delay) and places
                    # audio with µs precision; Blender wants a whole frame + sound_offset
                    t0_s = t0 / US + media_start(v["path"])
                    cs = math.floor(t0_s * self.fps)
                    node.update(type="sound", name=v.get("name") or os.path.basename(v["path"]),
                                path=v["path"], content_start=cs)
                    node["props"] = {"volume": volp.export(self.fps),
                                     "sound_offset": t0_s - cs / self.fps}
                    nodes.append(node)
                elif track["type"] in ("effect", "filter", "sticker", "adjust"):
                    self.warnings.append(f"track type {track['type']} not converted")
        return nodes

    def run(self):
        dur = self.d["duration"]
        nodes = self.walk(self.d, 0, (0, dur))
        tl = {"fps": self.fps, "width": self.W, "height": self.H,
              "frame_end": self.fr(dur), "nodes": nodes}
        path = os.path.join(self.out, "timeline.json")
        json.dump(tl, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        self._prune(nodes)
        return path

    def _prune(self, nodes):
        """Drop text PNGs and matte caches left over from earlier runs."""
        keep = set()

        def walk(ns):
            for n in ns:
                if n.get("path"):
                    keep.add(os.path.normcase(os.path.abspath(n["path"])))
                if n.get("mask"):
                    keep.add(os.path.normcase(os.path.abspath(n["mask"]["dir"])))
                walk(n.get("children", []))

        walk(nodes)
        for sub in ("text", "matte"):
            root = os.path.join(self.out, sub)
            for name in os.listdir(root):
                p = os.path.join(root, name)
                if os.path.normcase(os.path.abspath(p)) not in keep:
                    if os.path.isdir(p):
                        for f in os.listdir(p):
                            os.remove(os.path.join(p, f))
                        os.rmdir(p)
                    else:
                        os.remove(p)


def remap_media(draft, rules):
    """Rewrite video/audio paths in a draft and all nested compound drafts."""
    if not rules:
        return
    for kind in ("videos", "audios"):
        for m in draft.get("materials", {}).get(kind, []):
            p = (m.get("path") or "").replace("\\", "/")
            for old, new in rules:
                if p.startswith(old):
                    m["path"] = new + p[len(old):]
    for sub in draft.get("materials", {}).get("drafts", []):
        if sub.get("draft"):
            remap_media(sub["draft"], rules)


def find_blender():
    cands = sorted(glob.glob(r"C:\Program Files\Blender Foundation\Blender *\blender.exe"))
    return cands[-1] if cands else "blender"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("draft")
    ap.add_argument("out_dir")
    ap.add_argument("--blender", default=find_blender())
    ap.add_argument("--name", default=None)
    ap.add_argument("--remap", action="append", default=[],
                    help="OLD=NEW media path prefix rewrite, e.g. for a copied or moved drive")
    args = ap.parse_args()
    draft = json.load(open(args.draft, encoding="utf-8"))
    remap_media(draft, [r.split("=", 1) for r in args.remap])
    out = os.path.abspath(args.out_dir)
    os.makedirs(out, exist_ok=True)
    conv = Converter(draft, out)
    tl = conv.run()
    print(f"texts rendered: {conv.n_text}, masks baked: {conv.n_mask}")
    for w in sorted(set(conv.warnings)):
        print("WARN", w)
    name = args.name or os.path.splitext(os.path.basename(args.draft))[0].replace(".dec", "")
    blend = os.path.join(out, name + ".blend")
    build = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jy_build.py")
    r = subprocess.run([args.blender, "-b", "--factory-startup", "--python", build, "--", tl, blend],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    lines = [l for l in (r.stdout + r.stderr).splitlines()
             if "Deprecat" not in l and "cannot be made relative" not in l]
    print("\n".join(lines[-15:]))
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
