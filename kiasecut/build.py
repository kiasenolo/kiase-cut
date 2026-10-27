"""Project -> MLT XML.

Mapping (each verified against a Jianying export with melt 7.43):
  transform / opacity -> qtblend effect on the timeline entry: rect "x y w h opacity",
                         rotation in clockwise degrees about the clip centre (a pivot,
                         中心點, moves the rect: project.centre_px)
  mask                -> shape effect after qtblend, RGBA matte, alpha_operation=minimum;
                         mattes are baked in screen space from the mask + transform params
  text                -> PNG rendered by textlayout (Jianying's exact layout), padded to a
                         16:9 canvas so MLT's fit-to-frame maps it predictably
  compound clip       -> nested tractor with its own transform / mask
  volume and fades    -> volume effect, level in dB
Effect keyframe positions are media frames (entry in point + offset). MLT keyframes only
offer fixed easings, so the bezier curves are sampled per frame where they move.
Rendered texts and mattes are cached by content hash in the project's cache folder.
"""
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from xml.sax.saxutils import escape

import numpy as np
from PIL import Image

from . import assets, curves, fonts, masks, project, svgimage, textlayout

US = 1_000_000
TEXT_LAYOUT_FIELDS = ("color", "letter_spacing", "line_spacing", "italic_deg", "font_path", "align")


def _hash(*parts):
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


_ffmpeg = []


def find_ffmpeg():
    """ffmpeg's path, or None. Searching PATH takes ~30 ms on Windows, so a find is kept."""
    if not _ffmpeg:
        for c in ("ffmpeg", r"C:\Program Files\Kdenlive\bin\ffmpeg.exe", "/usr/bin/ffmpeg"):
            if shutil.which(c) or os.path.exists(c):
                _ffmpeg.append(shutil.which(c) or c)
                break
    return _ffmpeg[0] if _ffmpeg else None


_starts = {}


def media_start(p, stream=0):
    """First audio timestamp (an MP3's encoder delay) of the file's stream-th sound. MLT
    honours it like Jianying does."""
    key = (p, stream)
    if key not in _starts:
        try:
            r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", f"a:{stream}", "-show_entries",
                                "stream=start_time", "-of", "csv=p=0", p],
                               capture_output=True, text=True, timeout=30)
            _starts[key] = float(r.stdout.strip() or 0)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            _starts[key] = 0.0
    return _starts[key]


_streams = {}


def audio_streams(p):
    """The sound streams of a media file (a recording with game, voice and music on tracks
    of their own has several): [{index (in the whole file), title, lang, channels}], cached."""
    if p not in _streams:
        try:
            r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-print_format", "json",
                                "-show_entries", "stream=index,channels:stream_tags=title,name,language,handler_name",
                                p],
                               capture_output=True, text=True, timeout=30)
            out = []
            for s in json.loads(r.stdout or "{}").get("streams", []):
                tags = {k.lower(): v for k, v in (s.get("tags") or {}).items()}
                handler = tags.get("handler_name") or ""
                if "handler" in handler.lower() or handler.strip().lower() == "core media audio":
                    handler = ""                                 # (a program's default, the same on every stream)
                title = (tags.get("title") or tags.get("name") or handler).strip()
                if re.fullmatch(r"(track|audio)\s*\d*", title, re.I):
                    title = ""                                   # (OBS names them Track1...: no more than 音軌 1)
                out.append({"index": int(s["index"]), "title": title, "channels": int(s.get("channels") or 0),
                            "lang": "" if tags.get("language") in (None, "und") else tags["language"]})
            _streams[p] = out
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
            _streams[p] = []
    return _streams[p]


def stream_label(streams, n):
    """音軌 n+1, with its name, language and channels when it has them."""
    s = streams[n]
    extra = [x for x in (s["title"], s["lang"], f"{s['channels']} 聲道" if s["channels"] else "") if x]
    return f"音軌 {n + 1}" + (f"：{'，'.join(extra)}" if extra else "")


def audio_stream(c):
    """Which of its file's sound streams a clip plays (0: the first); one the file does not
    have (it was replaced) falls back to the first."""
    n = c.get("audio_stream", 0)
    if not n:
        return 0
    return n if n < len(audio_streams(c["media"]["path"])) else 0


class Builder:
    def __init__(self, proj, cache_dir, mask_mode="native", preview=False, size=None, fps=None):
        """mask_mode: "native" draws masks with MLT's rotoscoping filter (instant, follows
        the clip like Jianying's); "baked" rasterises screen-space mattes (reference).
        preview: use frame-sized proxies of larger images (exports use the originals).
        size / fps: render at another (width, height) or frame rate than the project's.
        Nothing in a project is in pixels or frames (positions are canvas fractions, text
        sizes follow the canvas height, times are microseconds), so this only changes the
        output grid; size should keep the project's shape."""
        self.p = proj
        self.mask_mode = mask_mode
        self.preview = preview
        self.W, self.H = size or (proj["width"], proj["height"])
        self.fps = float(fps or proj["fps"])
        self.cache = os.path.abspath(cache_dir)
        for sub in ("text", "matte", "proxy"):
            os.makedirs(os.path.join(cache_dir, sub), exist_ok=True)
        self.xml = []
        self.n = 0
        self._raster = None
        self._shared = {}       # (media path, kind, track, sound stream) -> producer id

    # -- helpers ------------------------------------------------------------------------------
    def fr(self, us):
        return int(round(us * self.fps / US))

    def us(self, frame):
        return frame * US / self.fps

    def new_id(self, prefix):
        self.n += 1
        return f"{prefix}{self.n}"

    @staticmethod
    def props(d):
        return "".join(f'<property name="{k}">{escape(str(v))}</property>' for k, v in d.items())

    def filt(self, service, d):
        return f'<filter>{self.props({"mlt_service": service, **d})}</filter>'

    def anim(self, params, f0, f1, fn, tol, clip_start_us, off=0, digits=4):
        """Sample fn(t_rel) -> tuple over frames [f0, f1) into an MLT animation string.

        Keys are thinned (Ramer-Douglas-Peucker) to those MLT's linear interpolation needs
        to stay within tol per component: one key per frame made the volume effect spend
        ~30 ms a frame re-reading a 2000-key curve."""
        spans = [curves.span(p) for p in params if curves.span(p)]
        t_of = lambda f: self.us(f) - clip_start_us
        fmt = lambda v: " ".join(f"{x:.{digits}f}" for x in v)
        if not spans:
            return fmt(fn(t_of(f0)))
        a = max(f0, math.floor(self.fr(clip_start_us + min(s[0] for s in spans))))
        b = min(f1 - 1, math.ceil(self.fr(clip_start_us + max(s[1] for s in spans))))
        frames = sorted({f0, f1 - 1} | set(range(a, b + 1)))
        vals = np.array([fn(t_of(f)) for f in frames], dtype=float)
        tol = np.broadcast_to(np.asarray(tol, dtype=float), vals.shape[1:])
        keep = {0, len(frames) - 1}
        stack = [(0, len(frames) - 1)]
        while stack:
            i, j = stack.pop()
            if j - i < 2:
                continue
            fi, fj = frames[i], frames[j]
            w = (np.array(frames[i + 1:j]) - fi) / (fj - fi)
            interp = vals[i] + (vals[j] - vals[i]) * w[:, None]
            err = (np.abs(vals[i + 1:j] - interp) / tol).max(axis=1)
            k = int(err.argmax())
            if err[k] > 1:
                m = i + 1 + k
                keep.add(m)
                stack += [(i, m), (m, j)]
        return ";".join(f"{frames[i] - f0 + off}={fmt(vals[i])}" for i in sorted(keep))

    # -- assets -----------------------------------------------------------------------------------
    def text_png(self, spec, rs):
        """Text rendered at render scale rs, cropped to its own canvas (centre = box centre).
        Returns (path, width, height). Tight images keep project loading fast: padding every
        text to a full frame made MLT decode ~340 frame-sized PNGs on each load."""
        key = _hash("text2", spec, rs, self.H, textlayout.PX_PER_FONT_UNIT, fonts.map_key())
        out = os.path.join(self.cache, "text", key + ".png")
        if not os.path.exists(out):
            textlayout.render(spec, rs, self.H).save(out + ".tmp.png", compress_level=1)
            os.replace(out + ".tmp.png", out)
        with Image.open(out) as im:
            return out, im.width, im.height

    def text_sequence(self, tx, rs, f0, f1, clip_start_us):
        """Render a text with animated drawing properties frame by frame (identical frames
        once) into an RGBA movie. Returns (path, width, height); centre = box centre."""
        specs = [curves.static(tx, self.us(f) - clip_start_us, TEXT_LAYOUT_FIELDS + ("size",))
                 for f in range(f0, f1)]
        for sp in specs:
            sp["color"] = [round(v, 4) for v in sp["color"]] if isinstance(sp.get("color"), list) else sp.get("color")
        key = _hash("textseq", specs, rs, self.H, textlayout.PX_PER_FONT_UNIT, self.fps, fonts.map_key())
        out = os.path.join(self.cache, "text", key + ".mov")
        meta = out + ".json"
        if not os.path.exists(meta):
            pngs = [self.text_png(sp, rs) for sp in specs]
            cw = max(w for _, w, _ in pngs) + 2
            ch = max(h for _, _, h in pngs) + 2
            cw, ch = cw + cw % 2, ch + ch % 2
            tmp = os.path.join(self.cache, "text", key + "_frames")
            os.makedirs(tmp, exist_ok=True)
            for i, (png, w, h) in enumerate(pngs):
                canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
                with Image.open(png) as im:
                    canvas.paste(im, ((cw - w) // 2, (ch - h) // 2))
                canvas.save(os.path.join(tmp, f"{i:06d}.png"), compress_level=1)
            subprocess.run([find_ffmpeg(), "-v", "error", "-y", "-framerate", str(self.fps),
                            "-i", os.path.join(tmp, "%06d.png"), "-c:v", "png", "-pix_fmt", "rgba", out],
                           check=True)
            shutil.rmtree(tmp, ignore_errors=True)
            with open(meta, "w") as fh:
                json.dump({"w": cw, "h": ch}, fh)
        with open(meta) as fh:
            m = json.load(fh)
        return out.replace("\\", "/"), m["w"], m["h"]

    def matte(self, mask, transform, disp, clip_start_us, f0, f1):
        """Bake a mask to an RGBA resource (white, alpha = coverage) covering frames [f0, f1)."""
        animated = masks.Rasterizer.animated(mask, transform)
        frames = list(range(f0, f1)) if animated else [f0]
        key = _hash("matte", mask, transform, disp, clip_start_us, frames[0], frames[-1],
                    self.W, self.H, self.fps)
        single = os.path.join(self.cache, "matte", key + ".png")
        movie = os.path.join(self.cache, "matte", key + ".mov")
        if os.path.exists(single if not animated else movie):
            return single if not animated else movie
        if self._raster is None:
            self._raster = masks.Rasterizer(self.W, self.H)
        tmpdir = os.path.join(self.cache, "matte", key + "_frames")
        os.makedirs(tmpdir, exist_ok=True)
        for i, f in enumerate(frames):
            m = self._raster.matte(mask, transform, disp[0], disp[1], self.us(f) - clip_start_us)
            rgba = np.full(m.shape + (4,), 255, np.uint8)
            rgba[..., 3] = m
            Image.fromarray(rgba, "RGBA").save(
                single if not animated else os.path.join(tmpdir, f"{i:06d}.png"), compress_level=1)
        if animated:
            subprocess.run([find_ffmpeg(), "-v", "error", "-y", "-framerate", str(self.fps),
                            "-i", os.path.join(tmpdir, "%06d.png"), "-c:v", "png",
                            "-pix_fmt", "rgba", movie], check=True)
        shutil.rmtree(tmpdir, ignore_errors=True)
        return single if not animated else movie

    # -- effects ----------------------------------------------------------------------------------
    def visual(self, c, f0, f1, clip_start_us, base=None, disp=None, off=0, size=None):
        """qtblend (+ shape) effects for a visual clip covering frames [f0, f1).
        base: on-screen size at scale 1 (default: the frame, which MLT fits media into)."""
        tf = c.get("transform", {})
        x, y, sc = tf.get("x", 0.0), tf.get("y", 0.0), tf.get("scale", 1.0)
        scy = tf.get("scale_y", sc)
        op, rot = tf.get("opacity", 1.0), tf.get("rotation", 0.0)
        W, H = self.W, self.H
        bw, bh = base or (W, H)

        size_ref = curves.max_abs(size) if curves.is_animated(size) else None

        def rect(t):
            k = curves.value(size, t) / size_ref if size_ref else 1.0   # animated font size
            w = bw * curves.value(sc, t) * k
            h = bh * curves.value(scy, t) * k
            cx, cy = project.centre_px(tf, t, W, H)            # (中心點: turned about its pivot)
            px, py = cx - w / 2, cy - h / 2
            o = min(1.0, max(0.0, curves.value(op, t)))
            return px, py, w, h, o

        out = ""
        if project.active_mask(c) and self.mask_mode == "native":
            out += self.native_mask(c["mask"], disp or (W, H), f0, f1, clip_start_us, off)
        out += self.filt("qtblend", {
            "rect": self.anim([x, y, sc, scy, op, size, rot, tf.get("pivot_x", 0.0), tf.get("pivot_y", 0.0)],
                              f0, f1, rect, (0.02, 0.02, 0.02, 0.02, 0.0005),
                              clip_start_us, off),
            "rotation": self.anim([rot], f0, f1, lambda t: (curves.value(rot, t),), 0.005,
                                  clip_start_us, off),
            "rotate_center": 1, "compositing": 0, "distort": 1, "kdenlive_id": "qtblend"})
        if project.active_mask(c) and self.mask_mode == "baked":
            res = self.matte(c["mask"], tf, disp or (W, H), clip_start_us, f0, f1)
            out += self.filt("shape", {"resource": res.replace("\\", "/"), "use_luminance": 0,
                                       "use_mix": 0, "alpha_operation": "minimum",
                                       "audio_match": 0, "kdenlive_id": "shape"})
        return out

    def native_mask(self, mask, disp, f0, f1, clip_start_us, off=0):
        """rotoscoping effect, placed before qtblend so the mask lives in material space."""
        W, H = self.W, self.H
        spl = lambda t: masks.spline(mask, t, disp[0], disp[1], W, H)
        params = [mask.get(k) for k in ("cx", "cy", "w", "h", "rotation")]
        if not any(curves.is_animated(p) for p in params):
            data = json.dumps(spl(self.us(f0) - clip_start_us))
        else:
            flat = lambda t: tuple(c for pt in spl(t) for xy in pt for c in xy)
            tol = 0.05 / max(W, H)            # 0.05 px
            keys = self.anim(params, f0, f1, flat, tol, clip_start_us, off, digits=7).split(";")
            frames = {}
            for k in keys:
                pos, vals = k.split("=")
                v = [float(x) for x in vals.split()]
                frames[pos] = [[v[i:i + 2], v[i + 2:i + 4], v[i + 4:i + 6]] for i in range(0, len(v), 6)]
            data = json.dumps(frames)
        return self.filt("rotoscoping", {
            "spline": data, "mode": "alpha", "alpha_operation": "min", "invert": int(bool(mask.get("invert"))),
            "feather": round(curves.value(mask.get("feather", 0.0), 0) * min(disp) / 2),
            "feather_passes": 1, "kdenlive_id": "rotoscoping"})

    def audio(self, c, f0, f1, clip_start_us, src_in):
        vol = c.get("volume", 1.0)
        fi, fo = c.get("fade_in_us", 0), c.get("fade_out_us", 0)
        dur = c["duration_us"]

        def gain(t):
            g = curves.value(vol, t)
            if fi and t < fi:
                g *= max(0.0, t / fi)
            if fo and t > dur - fo:
                g *= max(0.0, (dur - t) / fo)
            return (20 * math.log10(max(g, 1e-5)),)

        params = [vol]
        if fi or fo:            # fades move the gain even when the volume is constant
            params.append({"keys": [[0, 0, 0, 0, 0, 0], [dur, 0, 0, 0, 0, 0]]})
        return self.filt("volume", {"level": self.anim(params, f0, f1, gain, 0.02, clip_start_us, src_in),
                                    "kdenlive_id": "volume"})

    # -- structure --------------------------------------------------------------------------------
    def proxy(self, path, w, h):
        """A copy of a large image scaled to fit the frame; decoding nine 4K stills a frame
        was the main cost of some compound clips during playback."""
        if not self.preview or (w <= self.W and h <= self.H):
            return path
        try:
            st = os.stat(path)
        except OSError:
            return path
        out = os.path.join(self.cache, "proxy", _hash(path, st.st_size, st.st_mtime, self.W, self.H) + ".png")
        if not os.path.exists(out):
            k = min(self.W / w, self.H / h)
            with Image.open(path) as im:
                im.resize((max(1, round(w * k)), max(1, round(h * k))), Image.LANCZOS)                     .save(out + ".tmp.png", compress_level=1)
            os.replace(out + ".tmp.png", out)
        return out.replace("\\", "/")

    def svg_png(self, path, w, h, k):
        """An SVG drawn as a PNG at the size it is shown (k: px per SVG unit: its size on the
        frame times the clip's largest scale), so MLT gets a sharp picture."""
        st = os.stat(path)
        out = os.path.join(self.cache, "proxy", _hash("svg", path, st.st_size, st.st_mtime, round(w * k), round(h * k))
                           + ".png")
        if not os.path.exists(out):
            svgimage.raster(path, w * k, h * k).save(out + ".tmp.png")
            os.replace(out + ".tmp.png", out)
        return out.replace("\\", "/")

    def asset_svg(self, p):
        """A built-in asset's SVG file, drawn from its parameters (static ones: an asset with
        keyframes goes to renderexport, which draws every frame)."""
        text = assets.svg(assets.at(p, 0))
        out = os.path.join(self.cache, "proxy", _hash("asset", text) + ".svg")
        if not os.path.exists(out):
            with open(out + ".tmp", "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(out + ".tmp", out)
        return out.replace("\\", "/")

    def media_producer(self, path, kind, track, stream=0):
        """One producer per media file per track (and sound stream); entries cut it with
        in/out. Opening a long recording once per clip made loading take ~30 s."""
        key = (path, kind, track, stream)
        if key not in self._shared:
            pid = self.new_id("m")
            props = {"mlt_service": "qimage" if kind == "image" else "avformat", "resource": path}
            if kind == "image":
                props.update(length=2147483647, ttl=1)
            if kind == "audio":
                props["video_index"] = -1
            if stream:                                       # (MLT counts all the file's streams)
                props["audio_index"] = audio_streams(path)[stream]["index"]
            self.xml.append(f'<producer id="{pid}">' + self.props(props) + "</producer>")
            self._shared[key] = pid
        return self._shared[key]

    def clip(self, c, offset_us, win, track):
        """Entry XML pieces for clip c placed at offset_us, cut to window win (frames)."""
        s_us = offset_us + c["start_us"]
        f0 = max(self.fr(s_us), win[0])
        f1 = min(self.fr(s_us + c["duration_us"]), win[1])
        if f1 <= f0:
            return None
        length = f1 - f0
        head = f0 - self.fr(s_us)                 # frames cut off the clip's start
        t = c["type"]
        pid = self.new_id("p")
        if t == "text":
            tf = c.get("transform", {})
            rs = max(curves.max_abs(tf.get("scale", 1.0)), curves.max_abs(tf.get("scale_y", 1.0)), 1.0)
            tx = c["text"]
            if any(curves.is_animated(tx.get(k)) for k in TEXT_LAYOUT_FIELDS):
                # colour / spacing / italic keyframes change the drawing: a frame sequence
                res, iw, ih = self.text_sequence(tx, rs, f0, f1, s_us)
                self.xml.append(f'<producer id="{pid}">' + self.props({
                    "mlt_service": "avformat", "resource": res, "kdenlive:clipname": c.get("name", "text")})
                                + "</producer>")
                return pid, 0, length, f0, self.visual(c, f0, f1, s_us, (iw / rs, ih / rs))
            # font size scales the whole layout linearly, so its keyframes become scale
            size = tx.get("size", 5.0)
            spec = curves.static(tx, 0, TEXT_LAYOUT_FIELDS)
            spec["size"] = curves.max_abs(size)
            png, iw, ih = self.text_png(spec, rs)
            self.xml.append(f'<producer id="{pid}" in="0" out="{length - 1}">' + self.props({
                "mlt_service": "qimage", "resource": png.replace("\\", "/"), "length": length,
                "ttl": 1, "kdenlive:clipname": c.get("name", "text")}) + "</producer>")
            return pid, 0, length, f0, self.visual(c, f0, f1, s_us, (iw / rs, ih / rs), size=size)
        if t == "image":
            m = c["media"]
            bw, bh = project.picture_size(c, self.W, self.H, self.W / self.p["width"])
            path = self.asset_svg(c["asset"]) if c.get("asset") else m["path"]
            if svgimage.is_svg(path):
                tf = c.get("transform", {})
                zoom = max(curves.max_abs(tf.get("scale", 1.0)), curves.max_abs(tf.get("scale_y", 1.0)))
                w, h = svgimage.size(path)
                src = self.svg_png(path, w, h, bw / w * max(1.0, zoom))
            else:
                src = self.proxy(m["path"], m["width"], m["height"])
            pid = self.media_producer(src, "image", track)
            return pid, 0, length, f0, self.visual(c, f0, f1, s_us, None, (bw, bh))
        if t in ("video", "audio"):
            m = c["media"]
            src_in = self.fr(c["source_start_us"]) + head
            pid = self.media_producer(m["path"], t, track, audio_stream(c))
            fx = self.audio(c, f0, f1, s_us, src_in)
            if t == "video":
                fit = min(self.W / m["width"], self.H / m["height"])
                fx = self.visual(c, f0, f1, s_us, None, (m["width"] * fit, m["height"] * fit),
                                 src_in) + fx
            return pid, src_in, length, f0, fx
        if t == "compound":
            comp = c["compound"]
            inner = self.tractor(comp["tracks"], s_us - c["source_start_us"], (f0, f1), True)
            k = min(self.W / comp["width"], self.H / comp["height"])
            return inner, 0, length, f0, self.visual(c, f0, f1, s_us, None,
                                                     (comp["width"] * k, comp["height"] * k))
        return None

    def tractor(self, tracks, offset_us, win, transparent=False):
        """Tracks placed at offset_us, cut to frames win -> tractor covering win (0-based)."""
        length = win[1] - win[0]
        bg = self.new_id("bg")
        self.xml.append(f'<producer id="{bg}" in="0" out="{length - 1}">' + self.props({
            "mlt_service": "color", "length": length,
            "resource": "#00000000" if transparent else "#ff000000"}) + "</producer>")
        ids, kinds, hides = [], [], []
        bgpl = self.new_id("pl")
        self.xml.append(f'<playlist id="{bgpl}"><entry producer="{bg}" in="0" out="{length - 1}"/></playlist>')
        ids.append(bgpl)
        kinds.append("video")
        hides.append("")
        for tr in tracks:
            gain, shown = project.sounds(tr, tracks), project.visible(tr)
            entries, cur = [], win[0]
            for c in sorted(tr["clips"], key=lambda c: c["start_us"]):
                r = self.clip(c, offset_us, win, id(tr))
                if not r:
                    continue
                pid, src_in, ln, f0, fx = r
                if f0 > cur:
                    entries.append(f'<blank length="{f0 - cur}"/>')
                elif f0 < cur:                  # rounding overlap: trim the head
                    cut = cur - f0
                    src_in, ln, f0 = src_in + cut, ln - cut, cur
                    if ln <= 0:
                        continue
                entries.append(f'<entry producer="{pid}" in="{src_in}" out="{src_in + ln - 1}">{fx}</entry>')
                cur = f0 + ln
            pl = self.new_id("pl")
            if gain > 0 and abs(gain - 1.0) > 1e-6:          # track volume
                entries.append(self.filt("volume", {"level": f"{20 * math.log10(gain):.3f}"}))
            self.xml.append(f'<playlist id="{pl}">{"".join(entries)}</playlist>')
            ids.append(pl)
            sound = any(c["type"] in ("audio", "video", "compound") for c in tr["clips"])
            kind = "audio" if tr["kind"] == "audio" else ("av" if sound else "video")
            kinds.append(kind)
            # MLT's track hide: what of video / audio this track does not contribute
            no_video = kind == "audio" or not shown
            no_audio = kind == "video" or gain <= 0
            hides.append(' hide="both"' if no_video and no_audio else ' hide="video"' if no_video
                         else ' hide="audio"' if no_audio else "")
        # mix only tracks that can carry sound: asking every image/text track for silence
        # and mixing it cost ~30 ms per frame, too slow for playback
        trans = []
        for i, k in enumerate(kinds[1:], 1):
            if k != "audio":
                trans.append(self.props({"mlt_service": "qtblend", "a_track": 0, "b_track": i,
                                         "compositing": 0, "always_active": 1}))
            if k != "video":
                trans.append(self.props({"mlt_service": "mix", "a_track": 0, "b_track": i,
                                         "sum": 1, "always_active": 1}))
        tid = self.new_id("tractor")
        tracks_xml = "".join(f'<track producer="{t}"{h}/>' for t, h in zip(ids, hides))
        self.xml.append(f'<tractor id="{tid}" in="0" out="{length - 1}">{tracks_xml}'
                        + "".join(f"<transition>{t}</transition>" for t in trans) + "</tractor>")
        return tid

    def document(self):
        total = self.fr(self.p["duration_us"])
        main = self.tractor(self.p["tracks"], 0, (0, total))
        master = float(self.p.get("master_gain", 1.0))
        if abs(master - 1.0) > 1e-6:                  # the master volume, on the whole mix
            self.xml[-1] = self.xml[-1].replace("</tractor>", self.filt("volume", {"gain": f"{master:.5f}"})
                                                + "</tractor>")
        fps_num = round(self.fps * 1000)
        profile = (f'<profile description="{self.W}x{self.H} {self.fps:g}fps" width="{self.W}" '
                   f'height="{self.H}" frame_rate_num="{fps_num}" frame_rate_den="1000" '
                   f'progressive="1" sample_aspect_num="1" sample_aspect_den="1" '
                   f'display_aspect_num="{self.W}" display_aspect_den="{self.H}" colorspace="709"/>')
        return (f'<?xml version="1.0" encoding="utf-8"?>\n<mlt LC_NUMERIC="C" producer="{main}">\n'
                f'{profile}\n' + "\n".join(self.xml) + "\n</mlt>\n")


def build(proj, cache_dir, out_path, mask_mode="native", preview=False, size=None, fps=None):
    """Write the MLT XML for proj to out_path; returns out_path."""
    doc = Builder(proj, cache_dir, mask_mode, preview, size, fps).document()
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(doc)
    os.replace(tmp, out_path)
    return out_path
