"""Build an MLT XML file or a Kdenlive project from timeline.json.

  python jy_mlt.py OUT_DIR/timeline.json OUT_DIR/project.kdenlive  [--text title|png] [--remap OLD=NEW]
  python jy_mlt.py OUT_DIR/timeline.json OUT_DIR/project.mlt       (plain MLT, renders with melt)

timeline.json comes from jianying_to_blender.py stage 1 (same text layouts and mattes).
Mapping, verified with melt 7.43 against the Jianying export:
  transform/opacity -> qtblend effect (rect "x y w h opacity", rotation clockwise deg)
  mask              -> shape effect after qtblend, RGBA matte, alpha_operation=minimum
  text              -> kdenlivetitle (editable), or the pre-rendered PNG with --text png
  compound clip     -> nested tractor; in a .kdenlive file a nested sequence
  volume            -> volume effect, level in dB
Effects sit on timeline entries (as Kdenlive stores them); keyframe positions are media frames.
MLT keyframes only offer fixed easings, so Jianying's bezier curves are baked per frame.
"""
import argparse
import json
import math
import os
import subprocess
import uuid
from xml.sax.saxutils import escape, quoteattr

import numpy as np
from PIL import Image, ImageFont

ap = argparse.ArgumentParser()
ap.add_argument("timeline")
ap.add_argument("out")
ap.add_argument("--text", choices=("title", "png"), default="title",
                help="title: editable Kdenlive titles (default); png: pre-rendered images")
ap.add_argument("--remap", action="append", default=[],
                help="OLD=NEW path prefix rewrite, e.g. C:/Users/me/=/home/me/ for Linux")
args = ap.parse_args()

tl = json.load(open(args.timeline, encoding="utf-8"))
FPS, W, H = tl["fps"], tl["width"], tl["height"]
KDENLIVE = args.out.lower().endswith(".kdenlive")
OUT_DIR = os.path.dirname(os.path.abspath(args.out))
ASSETS = os.path.join(OUT_DIR, "mlt_assets")
os.makedirs(ASSETS, exist_ok=True)
REMAP = [r.split("=", 1) for r in args.remap]
NS = uuid.uuid5(uuid.NAMESPACE_URL, os.path.abspath(args.timeline))


def path(p):
    p = p.replace("\\", "/")
    for old, new in REMAP:
        if p.startswith(old):
            p = new + p[len(old):]
    return p


def new_uuid(name):
    return "{" + str(uuid.uuid5(NS, name)) + "}"


# --- curves (timeline.json keys: [frame, value, l_dframe, l_dvalue, r_dframe, r_dvalue]) ------
def ev(prop, f):
    if not isinstance(prop, list):
        return prop
    if f <= prop[0][0]:
        return prop[0][1]
    if f >= prop[-1][0]:
        return prop[-1][1]
    for a, b in zip(prop, prop[1:]):
        if a[0] <= f <= b[0]:
            break
    x0, y0, x3, y3 = a[0], a[1], b[0], b[1]
    x1, y1, x2, y2 = x0 + a[4], y0 + a[5], x3 + b[2], y3 + b[3]
    lo, hi = 0.0, 1.0
    for _ in range(40):
        s = (lo + hi) / 2
        x = (1 - s) ** 3 * x0 + 3 * (1 - s) ** 2 * s * x1 + 3 * (1 - s) * s * s * x2 + s ** 3 * x3
        lo, hi = (s, hi) if x < f else (lo, s)
    s = (lo + hi) / 2
    return (1 - s) ** 3 * y0 + 3 * (1 - s) ** 2 * s * y1 + 3 * (1 - s) * s * s * y2 + s ** 3 * y3


def anim(props, keys, start, end, fmt, off=0):
    """Bake props over [start, end) into an MLT animation string.

    Key positions are relative to start, plus off: effects on a clip trimmed to in>0
    see the media's own frame numbers.
    """
    span = [p for p in (props.get(k) for k in keys) if isinstance(p, list)]
    if not span:
        return fmt(start)
    a = max(start, math.floor(min(p[0][0] for p in span)))
    b = min(end - 1, math.ceil(max(p[-1][0] for p in span)))
    frames = sorted({start, end - 1} | set(range(a, b + 1)))
    vals = [fmt(f) for f in frames]
    # keep a key wherever the value changes on either side, so linear interpolation
    # between the kept keys reproduces every baked frame
    out = [f"{f - start + off}={v}" for i, (f, v) in enumerate(zip(frames, vals))
           if i in (0, len(vals) - 1) or v != vals[i - 1] or v != vals[i + 1]]
    return ";".join(out)


# --- assets ------------------------------------------------------------------------------------
_starts = {}


def media_start(p):
    """First audio timestamp (MP3 encoder delay); MLT honours it, Blender needed it added."""
    if p not in _starts:
        try:
            r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                                "stream=start_time", "-of", "csv=p=0", p],
                               capture_output=True, text=True, timeout=30)
            _starts[p] = float(r.stdout.strip() or 0)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            _starts[p] = 0.0
    return _starts[p]


def text_canvas(png):
    """Pad a text PNG to a 16:9 canvas >= the profile so MLT's fit maps it predictably."""
    im = Image.open(png)
    c = max(1.0, im.width / W, im.height / H)
    cw, ch = math.ceil(W * c), math.ceil(H * c)
    out = os.path.join(ASSETS, "t_" + os.path.basename(png))
    if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(png):
        canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        canvas.paste(im, ((cw - im.width) // 2, (ch - im.height) // 2))
        canvas.save(out, compress_level=1)
    return out, min(cw / W, ch / H)


def matte_resource(mk):
    """Screen-space L mattes -> one RGBA resource (alpha = matte) the shape filter can read."""
    files = mk["files"]
    tag = os.path.basename(mk["dir"])
    if len(files) == 1:
        out = os.path.join(ASSETS, f"matte_{tag}.png")
        if not os.path.exists(out):
            m = np.asarray(Image.open(os.path.join(mk["dir"], files[0])))
            rgba = np.full(m.shape + (4,), 255, np.uint8)
            rgba[..., 3] = m
            Image.fromarray(rgba, "RGBA").save(out)
        return out
    out = os.path.join(ASSETS, f"matte_{tag}.mov")
    if not os.path.exists(out):
        # numbered PNG sequence in, white picture whose alpha is the matte's luma out
        # (the concat demuxer duplicated leading frames and put the mask 2 frames late)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS),
                        "-start_number", os.path.splitext(files[0])[0],
                        "-i", os.path.join(mk["dir"], "%06d.png"),
                        "-filter_complex", "[0:v]format=gray,split[m][c];[c]lutyuv=y=255[w];"
                        "[w][m]alphamerge,format=rgba",
                        "-c:v", "png", "-pix_fmt", "rgba", out], check=True)
    return out


# --- XML helpers ---------------------------------------------------------------------------------
xml = []
uid = [0]


def new_id(prefix):
    uid[0] += 1
    return f"{prefix}{uid[0]}"


def prop_xml(props):
    return "".join(f'<property name="{k}">{escape(str(v))}</property>' for k, v in props.items())


def filter_xml(service, props):
    return f'<filter>{prop_xml({"mlt_service": service, **props})}</filter>'


def visual_filters(n, start, end, size_k):
    """qtblend (+ shape) for a node; size_k converts timeline scale to profile-relative scale."""
    p = n.get("props", {})

    def rect(f):
        sx = ev(p.get("transform.scale_x", 1.0), f) * size_k
        sy = ev(p.get("transform.scale_y", 1.0), f) * size_k
        w, h = W * sx, H * sy
        x = W / 2 + ev(p.get("transform.offset_x", 0.0), f) - w / 2
        y = H / 2 - ev(p.get("transform.offset_y", 0.0), f) - h / 2
        o = max(0.0, min(1.0, ev(p.get("blend_alpha", 1.0), f)))
        return f"{x:.3f} {y:.3f} {w:.3f} {h:.3f} {o:.4f}"

    keys = ("transform.scale_x", "transform.scale_y", "transform.offset_x",
            "transform.offset_y", "blend_alpha")
    out = [filter_xml("qtblend", {
        "rect": anim(p, keys, start, end, rect),
        "rotation": anim(p, ("transform.rotation",), start, end,
                         lambda f: f"{-math.degrees(ev(p.get('transform.rotation', 0.0), f)):.4f}"),
        "rotate_center": 1, "compositing": 0, "distort": 1, "kdenlive_id": "qtblend"})]
    out += mask_filter(n)
    return "".join(out)


def mask_filter(n):
    if not n.get("mask"):
        return []
    return [filter_xml("shape", {
        "resource": path(matte_resource(n["mask"])), "use_luminance": 0, "use_mix": 0,
        "alpha_operation": "minimum", "audio_match": 0, "kdenlive_id": "shape"})]


# --- editable text (Kdenlive titles) -------------------------------------------------------------
# Qt text metrics for the title producer, measured with melt 7.43 / Kdenlive 26.08:
QT_BASELINE = 0.94      # first baseline below the item's y, in font px
QT_LINE = 1.12          # line pitch = round(QT_LINE * px) + line-spacing attribute
_families = {}


def qt_family(font_path):
    """Family name Qt resolves for a font file (non-standard styles are part of the name)."""
    if font_path not in _families:
        try:
            name, style = ImageFont.truetype(font_path, 10, index=0).getname()
        except OSError:
            name, style = "Sans", "Regular"
        std = style.lower() in ("regular", "normal", "book", "roman")
        _families[font_path] = name if std else f"{name} {style}"
    return _families[font_path]


def pick_scale(L, sc, s_min, s_max=3.0):
    """Title units per screen px: Kdenlive only takes integer font px / letter spacing /
    line spacing, so choose the multiplier where they all land closest to integers."""
    n_ls = max(len(line) for line in L["text"].split("\n")) - 1
    n_ln = L["text"].count("\n")
    best = None
    S = s_min
    while S <= s_max:
        em = L["em"] * sc * S
        k = round(em) / L["em"]
        ls = L["ls_px"] * k
        pitch = L["step"] * k - round(QT_LINE * round(em))
        err = (abs(em - round(em)) / em * L["box_w"] * sc
               + abs(ls - round(ls)) / S * n_ls + abs(pitch - round(pitch)) / S * n_ln)
        if best is None or err < best[0] - 1e-3:
            best = (err, S)
        S += 0.0025
    return best[1]


def title_xml(L, S, cx, cy, sc, rot_deg, cw, ch):
    """kdenlivetitle document drawing layout L centred at (cx, cy) title units."""
    em_t = round(L["em"] * sc * S)
    k = em_t / L["em"]                                  # title units per layout px
    ls_t = round(L["ls_px"] * k)
    line_sp = round(L["step"] * k - round(QT_LINE * em_t))
    x = cx - L["box_w"] * k / 2
    y = cy - L["box_h"] * k / 2 + (L["ext_top"] + L["asc"]) * k - QT_BASELINE * em_t
    # italic shear then clockwise rotation, both about the box centre
    sh = math.tan(math.radians(L["italic"]))
    r = math.radians(rot_deg)
    c, s = math.cos(r), math.sin(r)
    m = [[c, -c * sh - s], [s, -s * sh + c]]
    dx, dy = x - cx, y - cy
    tx = cx + m[0][0] * dx + m[0][1] * dy - x
    ty = cy + m[1][0] * dx + m[1][1] * dy - y
    tf = f"{m[0][0]:.6f},{m[1][0]:.6f},0,{m[0][1]:.6f},{m[1][1]:.6f},0,{tx:.3f},{ty:.3f},1"
    rgba = ",".join(str(v) for v in L["rgba"])
    body = escape(L["text"])
    return (f'<kdenlivetitle width="{cw}" height="{ch}" out="0">'
            f'<item z-index="0" type="QGraphicsTextItem"><position x="{x:.3f}" y="{y:.3f}">'
            f'<transform>{tf}</transform></position>'
            f'<content font-color="{rgba}" font-pixel-size="{em_t}" font-italic="0" '
            f'font-underline="0" font-weight="50" font={quoteattr(qt_family(L["font_path"]))} '
            f'letter-spacing="{ls_t}" line-spacing="{line_sp}" alignment="4">{body}</content></item>'
            f'<startviewport rect="0,0,{cw},{ch}"/><endviewport rect="0,0,{cw},{ch}"/>'
            f'<background color="0,0,0,0"/></kdenlivetitle>')


def title_parts(n, start, end):
    """(xmldata, filters). Static text is drawn in place at final size (sharp, and editable
    where it shows); animated text is drawn centred and moved by qtblend."""
    L, p = n["text"], n.get("props", {})
    tkeys = ("transform.offset_x", "transform.offset_y", "transform.scale_x",
             "transform.scale_y", "transform.rotation")
    if not any(isinstance(p.get(k), list) for k in tkeys):
        sc = p.get("transform.scale_x", 1.0) * L["rs"]
        S = pick_scale(L, sc, 1.0)
        doc = title_xml(L, S, (W / 2 + p.get("transform.offset_x", 0.0)) * S,
                        (H / 2 - p.get("transform.offset_y", 0.0)) * S, sc,
                        -math.degrees(p.get("transform.rotation", 0.0)),
                        round(W * S), round(H * S))
        alpha = p.get("blend_alpha", 1.0)
        rect = anim(p, ("blend_alpha",), start, end,
                    lambda f: f"0 0 {W} {H} {max(0.0, min(1.0, ev(alpha, f))):.4f}")
        filt = filter_xml("qtblend", {"rect": rect, "compositing": 0, "distort": 1,
                                      "kdenlive_id": "qtblend"}) + "".join(mask_filter(n))
        return doc, filt
    rs = L["rs"]
    sh = abs(math.tan(math.radians(L["italic"])))
    need = max(1.0, (L["box_w"] + L["box_h"] * sh) * rs * 1.05 / W, L["box_h"] * rs * 1.05 / H)
    S = pick_scale(L, rs / need, 1.0)
    doc = title_xml(L, S, W * S / 2, H * S / 2, rs / need, 0.0, round(W * S), round(H * S))
    return doc, visual_filters(n, start, end, need)


# --- clips ---------------------------------------------------------------------------------------
bin_clips = []          # (bin producer id, kdenlive:id) for main_bin
bin_ids = {}            # source key -> kdenlive:id
track_producers = {}    # (source key, track id) -> producer id reused along one track
FOLDERS = {"text": 2, "compound": 3}


def bin_id(key, make_bin_copy):
    """kdenlive:id for a source; the first time, also emit the bin's own producer copy."""
    if key not in bin_ids:
        bin_ids[key] = len(bin_ids) + 4
        if KDENLIVE and make_bin_copy:
            pid = make_bin_copy(bin_ids[key])
            bin_clips.append((pid, bin_ids[key]))
    return bin_ids[key]


def media_producer(n, track, kind):
    """Shared producer for a media file on one track; returns its id."""
    res = path(n["path"])
    key = (res, kind)
    if (key, track) in track_producers:
        return track_producers[(key, track)]
    t = n["type"]

    def body(kid):
        if t == "image":
            props = {"mlt_service": "qimage", "resource": res, "length": 2147483647, "ttl": 1,
                     "eof": "pause"}
            tag = "producer"
        else:
            props = {"mlt_service": "avformat-novalidate", "resource": res, "eof": "pause"}
            tag = "chain"
        props.update({"kdenlive:clipname": os.path.basename(res), "kdenlive:id": kid,
                      "kdenlive:folderid": -1, "kdenlive:clip_type": 0})
        return tag, props

    def emit(kid, extra=None):
        tag, props = body(kid)
        props.update(extra or {})
        pid = new_id("clip")
        xml.append(f'<{tag} id="{pid}">{prop_xml(props)}</{tag}>')
        return pid

    kid = bin_id(key, emit)
    extra = {"set.test_image": 1, "set.test_audio": 0} if kind == "audio" else {}
    if kind == "video" and t != "image":
        extra = {"set.test_audio": 1, "set.test_image": 0}
    pid = emit(kid, extra)
    track_producers[(key, track)] = pid
    return pid


def clip(n, track):
    """Return (producer id, src_in, entry filters xml, kdenlive:id) for node n on a track."""
    start, end = n["start"], n["end"]
    length = end - start
    t = n["type"]
    if t == "image" and n.get("text") and n["text"]["uniform"] and args.text == "title":
        doc, filt = title_parts(n, start, end)
        name = n["name"] or "text"

        def emit(kid, own=None):
            pid = new_id("title")
            xml.append(f'<producer id="{pid}" in="0" out="{length - 1}">' + prop_xml({
                "mlt_service": "kdenlivetitle", "length": length, "xmldata": doc,
                "force_reload": 0, "kdenlive:clipname": name, "kdenlive:id": kid,
                "kdenlive:folderid": FOLDERS["text"], "kdenlive:duration": length}) + "</producer>")
            return pid

        kid = bin_id(("title", id(n)), emit)
        return emit(kid), 0, filt, kid
    if t == "image":
        if "/text/" in n["path"].replace("\\", "/"):
            res, c = text_canvas(n["path"])
            n = {**n, "path": res}
            k = c                       # canvas was fit down by c; undo it in the rect
        else:
            k = 1.0
        pid = media_producer(n, track, "video")
        return pid, 0, visual_filters(n, start, end, k), bin_ids[(path(n["path"]), "video")]
    if t == "movie":
        src_in = start - n["content_start"]
        pid = media_producer(n, track, "video")
        return pid, src_in, visual_filters(n, start, end, 1.0), bin_ids[(path(n["path"]), "video")]
    if t == "sound":
        # MLT places media by its own timestamps (honouring an MP3's start_time), so
        # undo the shift stage 1 added for Blender; sub-frame offsets cannot be expressed
        t0 = n["content_start"] / FPS + n["props"].get("sound_offset", 0.0) - media_start(n["path"])
        src_in = start - round(t0 * FPS)
        vol = n["props"].get("volume", 1.0)
        level = anim(n["props"], ("volume",), start, end,
                     lambda f: f"{20 * math.log10(max(ev(vol, f), 1e-5)):.3f}", src_in)
        pid = media_producer(n, track, "audio")
        return (pid, src_in, filter_xml("volume", {"level": level, "kdenlive_id": "volume"}),
                bin_ids[(path(n["path"]), "audio")])
    if t == "meta":
        seq = container(n["children"], start, end, nested=True, name=n["name"])
        return seq, 0, visual_filters(n, start, end, 1.0), bin_ids[("seq", seq)]
    return None, 0, "", None


# --- tracks and containers -----------------------------------------------------------------------
def lanes(nodes):
    """Assign each node a track: one block per layer, extra lanes only where clips overlap."""
    tracks = []
    for layer in sorted({tuple(n["layer"]) for n in nodes}):
        group = sorted([n for n in nodes if tuple(n["layer"]) == layer], key=lambda n: n["start"])
        mine = []
        for n in group:
            for lane in mine:
                if lane[-1]["end"] <= n["start"]:
                    lane.append(n)
                    break
            else:
                mine.append([n])
        tracks += mine
    return tracks


def track(lane, base, kind):
    """One timeline track -> producer id usable as a <track> of a tractor."""
    tid = new_id("track")
    entries, cur = [], base
    for n in lane:
        pid, src_in, filt, kid = clip(n, tid)
        if pid is None:
            continue
        if n["start"] > cur:
            entries.append(f'<blank length="{n["start"] - cur}"/>')
        ln = n["end"] - n["start"]
        kprop = prop_xml({"kdenlive:id": kid}) if KDENLIVE else ""
        entries.append(f'<entry producer="{pid}" in="{src_in}" out="{src_in + ln - 1}">'
                       f'{kprop}{filt}</entry>')
        cur = n["end"]
    audio = kind == "audio"
    flag = prop_xml({"kdenlive:audio_track": 1}) if audio and KDENLIVE else ""
    pl = new_id("playlist")
    xml.append(f'<playlist id="{pl}">{flag}{"".join(entries)}</playlist>')
    if not KDENLIVE:
        return pl
    # Kdenlive tracks are tractors holding two playlists (the second for same-track mixes)
    pl2 = new_id("playlist")
    xml.append(f'<playlist id="{pl2}">{flag}</playlist>')
    hide = "video" if audio else "audio"
    xml.append(f'<tractor id="{tid}">{flag}'
               + prop_xml({"kdenlive:trackheight": 67, "kdenlive:timeline_active": 1})
               + f'<track hide="{hide}" producer="{pl}"/><track hide="{hide}" producer="{pl2}"/>'
               + "</tractor>")
    return tid


def container(nodes, base, end, nested=False, name="Sequence"):
    """Timeline (or compound clip) -> tractor id. base/end: absolute frames it covers."""
    length = end - base
    bg = new_id("black")
    xml.append(f'<producer id="{bg}" in="0" out="{length - 1}">'
               + prop_xml({"mlt_service": "color", "length": 2147483647, "eof": "continue",
                           "resource": "#00000000" if nested else "#ff000000",
                           "kdenlive:playlistid": "black_track", "mlt_image_format": "rgba",
                           "set.test_audio": 0})
               + "</producer>")
    if KDENLIVE:
        bgt = bg
    else:
        bgt = new_id("playlist")
        xml.append(f'<playlist id="{bgt}"><entry producer="{bg}" in="0" out="{length - 1}"/></playlist>')
    vis = [n for n in nodes if n["type"] != "sound"]
    aud = [n for n in nodes if n["type"] == "sound"]
    ids, kinds = [bgt], ["video"]
    for kind, group in (("audio", aud), ("video", vis)):
        for lane in lanes(group):
            ids.append(track(lane, base, kind))
            kinds.append(kind)
    trans = []
    for i, k in enumerate(kinds[1:], 1):
        common = {"a_track": 0, "b_track": i, "always_active": 1, "internal_added": 237}
        if k == "video":
            trans.append(prop_xml({"mlt_service": "qtblend", "kdenlive_id": "qtblend",
                                   "compositing": 0, **common}))
        trans.append(prop_xml({"mlt_service": "mix", "kdenlive_id": "mix", "sum": 1,
                               "accepts_blanks": 1, **common}))
    trans_xml = "".join(f"<transition>{t}</transition>" for t in trans)
    tracks_xml = "".join(
        f'<track producer="{t}"{" hide=\"video\"" if k == "audio" and not KDENLIVE else ""}/>'
        for t, k in zip(ids, kinds))
    if not KDENLIVE:
        tid = new_id("tractor")
        xml.append(f'<tractor id="{tid}" in="0" out="{length - 1}">{tracks_xml}{trans_xml}</tractor>')
        bin_ids[("seq", tid)] = None
        return tid
    tid = new_uuid(f"seq-{len(bin_ids)}-{name}-{base}")
    kid = len(bin_ids) + 4
    bin_ids[("seq", tid)] = kid
    n_a, n_v = kinds.count("audio"), kinds.count("video") - 1
    props = {
        "kdenlive:uuid": tid, "kdenlive:clipname": name, "kdenlive:producer_type": 17,
        "kdenlive:id": kid, "kdenlive:clip_type": 0, "kdenlive:duration": length,
        "kdenlive:maxduration": length,
        "kdenlive:folderid": FOLDERS["compound"] if nested else -1,
        "kdenlive:sequenceproperties.hasAudio": int(n_a > 0),
        "kdenlive:sequenceproperties.hasVideo": 1,
        "kdenlive:sequenceproperties.tracks": n_a + n_v,
        "kdenlive:sequenceproperties.tracksCount": n_a + n_v,
        "kdenlive:sequenceproperties.activeTrack": n_a,
        "kdenlive:sequenceproperties.audioTarget": 0 if n_a else -1,
        "kdenlive:sequenceproperties.videoTarget": n_a if n_v else -1,
        "kdenlive:sequenceproperties.documentuuid": DOC_UUID,
        "kdenlive:sequenceproperties.groups": "[]", "kdenlive:sequenceproperties.guides": "[]",
        "kdenlive:sequenceproperties.position": 0, "kdenlive:sequenceproperties.zoom": 8,
        "kdenlive:sequenceproperties.verticalzoom": 1, "kdenlive:sequenceproperties.scrollPos": 0,
        "kdenlive:sequenceproperties.zonein": 0, "kdenlive:sequenceproperties.zoneout": length,
        "kdenlive:sequenceproperties.disablepreview": 0,
    }
    xml.append(f'<tractor id="{tid}" in="0" out="{length - 1}">{prop_xml(props)}'
               f'{tracks_xml}{trans_xml}</tractor>')
    bin_clips.append((tid, kid))
    return tid


DOC_UUID = new_uuid("document")
main = container(tl["nodes"], 0, tl["frame_end"], name="Jianying import")
fps_num = round(FPS * 1000)
profile = (f'<profile description="HD 1080p {FPS:g} fps" width="{W}" height="{H}" '
           f'frame_rate_num="{fps_num}" frame_rate_den="1000" progressive="1" '
           f'sample_aspect_num="1" sample_aspect_den="1" display_aspect_num="{W}" '
           f'display_aspect_den="{H}" colorspace="709"/>')
if KDENLIVE:
    docprops = {
        "kdenlive:folder.-1.2": "Texts", "kdenlive:folder.-1.3": "Compound clips",
        "kdenlive:docproperties.activetimeline": main,
        "kdenlive:docproperties.opensequences": main,
        "kdenlive:docproperties.uuid": DOC_UUID,
        "kdenlive:docproperties.documentid": int(uuid.UUID(DOC_UUID[1:-1]).int % 10 ** 13),
        "kdenlive:docproperties.version": "1.1",
        "kdenlive:docproperties.kdenliveversion": "26.08.2",
        "kdenlive:docproperties.profile": f"atsc_1080p_{FPS:g}",
        "kdenlive:docproperties.compositing": 1,
        "kdenlive:docproperties.seekOffset": 30000,
        "xml_retain": 1,
    }
    entries = "".join(f'<entry producer="{pid}" in="0" out="0"/>' for pid, _ in bin_clips)
    xml.append(f'<playlist id="main_bin">{prop_xml(docprops)}{entries}</playlist>')
    xml.append(f'<tractor id="project" in="0" out="{tl["frame_end"] - 1}">'
               + prop_xml({"kdenlive:projectTractor": 1})
               + f'<track producer="{main}" in="0" out="{tl["frame_end"] - 1}"/></tractor>')
    root_producer = "main_bin"
else:
    root_producer = main
doc = (f'<?xml version="1.0" encoding="utf-8"?>\n<mlt LC_NUMERIC="C" producer="{root_producer}" '
       f'version="7.43.0" root={quoteattr(OUT_DIR.replace(os.sep, "/"))}>\n{profile}\n'
       + "\n".join(xml) + "\n</mlt>\n")
open(args.out, "w", encoding="utf-8").write(doc)
print("wrote", args.out, "elements:", len(xml), "bin clips:", len(bin_clips))
