"""Live preview renderer: draws a frame straight from the project model with QPainter.

The export path (build.py -> MLT) is the reference; this one trades a little exactness
for speed so edits and drags show on the next frame without rebuilding anything. It
follows the same rules as build.py:
  * a clip covers frames round(start * fps) .. round(end * fps) - 1;
  * keyframe time is frame time minus the clip start;
  * position in half-canvas units (y up), clockwise rotation, uniform scale about the
    clip centre; pictures are fitted into the canvas, texts are textlayout images;
  * masks live in material space (they move with the clip), drawn as clip paths;
  * compound clips render their tracks into a layer first, at time - start + source start.
QPainter on QImage is usable from any thread, so the player renders off the UI thread.
"""
import json
import math

import numpy as np
from PIL.ImageQt import ImageQt
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QTransform

from . import curves, fx, masks, project, textlayout

US = 1_000_000
TEXT_FIELDS = ("size", "color", "letter_spacing", "line_spacing", "italic_deg")
BIG = 1e5


class Renderer:
    def __init__(self, video_frame=None, cache_limit=600):
        """video_frame(path, source_us, w, h) -> QImage or None, for video clips."""
        self.video_frame = video_frame
        self.images = {}            # path -> [QImage halved per level] (a mipmap)
        self.texts = {}             # (spec json, scale) -> QImage
        self.cache_limit = cache_limit
        self.errors = []            # clips that could not be drawn, reported by the player
        self._fx = None             # filter engine (an OpenGL context of the thread that renders)
        self._fx_error = None

    # -- assets -----------------------------------------------------------------------------------
    def image(self, path, w, h):
        """The image at the smallest mip level at least w x h; the painter scales it the rest
        of the way (less than 2x, so bilinear stays clean). Decoding and smooth scaling happen
        once per file: animated sizes (zooming compounds) used to redo them every frame."""
        levels = self.images.get(path)
        if levels is None:
            src = QImage(path)
            if src.isNull():
                src = QImage(1, 1, QImage.Format_ARGB32_Premultiplied)
                src.fill(QColor(255, 0, 255))
            levels = [src.convertToFormat(QImage.Format_ARGB32_Premultiplied)]
            while levels[-1].width() > 64 and levels[-1].height() > 64:
                im = levels[-1]
                levels.append(im.scaled(max(1, im.width() // 2), max(1, im.height() // 2),
                                        Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
            if len(self.images) >= 48:
                self.images.pop(next(iter(self.images)))
            self.images[path] = levels
        for im in reversed(levels):
            if im.width() >= w and im.height() >= h:
                return im
        return levels[0]

    def text(self, spec, scale, canvas_h):
        """textlayout image at `scale` px per layout px; its centre is the text box centre."""
        key = (json.dumps(spec, sort_keys=True, default=str), round(scale, 3), canvas_h)
        im = self.texts.get(key)
        if im is None:
            im = QImage(ImageQt(textlayout.render(spec, scale, canvas_h))).convertToFormat(
                QImage.Format_ARGB32_Premultiplied)
            self._remember(self.texts, key, im)
        return im

    def _remember(self, cache, key, value):
        if len(cache) >= self.cache_limit:
            cache.pop(next(iter(cache)))
        cache[key] = value

    # -- frames -----------------------------------------------------------------------------------
    def render(self, view, frame, width, height):
        """RGB frame `frame` of a project-like view, drawn at width x height."""
        img = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        img.fill(QColor("black"))
        p = QPainter(img)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        p.scale(width / view["width"], height / view["height"])
        self.draw_tracks(p, view["tracks"], view["width"], view["height"], view["fps"],
                         frame / view["fps"] * US, width / view["width"])
        p.end()
        return img

    def draw_tracks(self, p, tracks, W, H, fps, t_us, px_per_unit):
        """Draw every visible clip at time t_us (us) on a W x H canvas, bottom track first."""
        f = round(t_us * fps / US)
        for tr in tracks:
            if tr["kind"] == "audio" or not project.visible(tr):
                continue
            for c in tr["clips"]:
                if round(c["start_us"] * fps / US) <= f < round((c["start_us"] + c["duration_us"]) * fps / US):
                    try:
                        if c["type"] == "filter":
                            self.draw_filter_clip(p, c, W, H, fps, t_us)
                        else:
                            self.draw_clip(p, c, W, H, fps, t_us, px_per_unit)
                    except Exception as exc:          # one bad clip must not blank the preview
                        self.errors.append(f"{c.get('name') or c['type']}: {exc}")

    def draw_clip(self, p, c, W, H, fps, t_us, px_per_unit):
        tf = c.get("transform") or {}
        t = t_us - c["start_us"]
        v = lambda k, d: curves.value(tf.get(k, d), t)
        opacity = min(1.0, max(0.0, v("opacity", 1.0)))
        if opacity <= 0:
            return
        sx = v("scale", 1.0)
        sy = curves.value(tf.get("scale_y", tf.get("scale", 1.0)), t)
        kind = c["type"]
        if kind == "text":
            tx = c["text"]
            size = tx.get("size", 5.0)
            animated = any(curves.is_animated(tx.get(k)) for k in TEXT_FIELDS if k != "size")
            if animated:
                spec, k_size = curves.static(tx, t, TEXT_FIELDS), 1.0
            else:
                ref = curves.max_abs(size) or 1.0
                spec = curves.static(tx, t, TEXT_FIELDS)
                spec["size"] = ref
                k_size = curves.value(size, t) / ref
            # draw at the target resolution so text stays sharp at any preview size, but
            # never below 1 px per em (fonts refuse that; it is invisible anyway)
            em_unit = (curves.value(spec.get("size", 5.0), 0) or 1.0) * textlayout.PX_PER_FONT_UNIT * H / 1080
            rs = max(max(abs(sx), abs(sy)) * k_size * px_per_unit, 1.0 / em_unit)
            rs = quantize(rs)                   # animated scales reuse a few renderings
            pic = self.text(spec, rs, H)
            bw, bh = pic.width() / rs * k_size, pic.height() / rs * k_size
            draw = lambda q=p: q.drawImage(QRectF(-bw / 2, -bh / 2, bw, bh), pic)
            disp = (bw, bh)
        elif kind in ("image", "video"):
            m = c["media"]
            fit = min(W / m["width"], H / m["height"])
            bw, bh = m["width"] * fit, m["height"] * fit
            tw, th = bw * abs(sx) * px_per_unit, bh * abs(sy) * px_per_unit
            if kind == "image":
                pic = self.image(m["path"], tw, th)
            else:
                pic = self.video_frame(m["path"], c.get("source_start_us", 0) + t,
                                       max(1, round(tw)), max(1, round(th))) if self.video_frame else None
                if pic is None:
                    return
            draw = lambda q=p: q.drawImage(QRectF(-bw / 2, -bh / 2, bw, bh), pic)
            disp = (bw, bh)
        elif kind == "compound":
            comp = c["compound"]
            cw, ch = comp["width"], comp["height"]
            fit = min(W / cw, H / ch)
            bw, bh = cw * fit, ch * fit
            k = fit * max(abs(sx), abs(sy), 0.01) * px_per_unit       # layer px per compound unit

            def draw(q=p):
                # only the part that lands on the target: a compound zoomed in 6x used to
                # get a 6000 px layer of which a 960 px window was shown
                inv, ok = q.worldTransform().inverted()
                dev = q.device()
                full = QRectF(-bw / 2, -bh / 2, bw, bh)
                vis = inv.mapRect(QRectF(0, 0, dev.width(), dev.height())) if ok else full
                pad = 2 * fit / k
                vis = vis.adjusted(-pad, -pad, pad, pad).intersected(full)
                if vis.isEmpty():
                    return
                ux, uy = (vis.left() + bw / 2) / fit, (vis.top() + bh / 2) / fit      # compound units
                layer = QImage(max(1, math.ceil(vis.width() / fit * k)), max(1, math.ceil(vis.height() / fit * k)),
                               QImage.Format_ARGB32_Premultiplied)
                layer.fill(Qt.transparent)
                lp = QPainter(layer)
                lp.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
                lp.scale(k, k)
                lp.translate(-ux, -uy)
                self.draw_tracks(lp, comp["tracks"], cw, ch, fps, t + c.get("source_start_us", 0), k)
                lp.end()
                q.drawImage(QRectF(vis.left(), vis.top(), layer.width() / k * fit, layer.height() / k * fit), layer)
            disp = (bw, bh)
        else:
            return
        if any(not e.get("disabled") for e in c.get("effects") or []):
            plain = draw

            def draw(q=p):
                self.draw_filtered(q, plain, c, t, disp, fps)
        p.save()
        p.setOpacity(p.opacity() * opacity)
        p.translate(W / 2 + v("x", 0.0) * W / 2, H / 2 - v("y", 0.0) * H / 2)
        p.rotate(v("rotation", 0.0))                       # clockwise on a y-down canvas
        p.scale(sx * (-1 if tf.get("flip_h") else 1), sy * (-1 if tf.get("flip_v") else 1))
        mask = c["mask"] if project.active_mask(c) else None
        feather = curves.value(mask.get("feather", 0.0), t) if mask else 0.0
        if mask and feather > 1e-3:
            self.draw_soft(p, mask, t, disp, feather, draw)      # a clip path has no soft edge
        else:
            if mask:
                p.setClipPath(mask_path(mask, t, disp))
            draw()
        p.restore()

    def draw_soft(self, p, mask, t, disp, feather, draw):
        """Draw the clip through a feathered mask: the clip goes to a layer the size of the
        target, which is multiplied by the mask's coverage (masks.alpha) and drawn back."""
        dev = p.device()
        W, H = dev.width(), dev.height()
        wt = p.worldTransform()
        if not wt.isInvertible():
            return
        layer = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
        layer.fill(Qt.transparent)
        lp = QPainter(layer)
        lp.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        lp.setTransform(wt)
        draw(lp)
        lp.end()
        m8 = (coverage(mask, t, disp, wt, W, H, feather) * 255 + 0.5).astype(np.uint16)
        px = np.ndarray((H, W, 4), np.uint8, buffer=layer.bits(), strides=(layer.bytesPerLine(), 4, 1))
        px[...] = ((px.astype(np.uint16) * m8[..., None] + 127) // 255).astype(np.uint8)
        p.save()
        p.resetTransform()
        p.drawImage(0, 0, layer)
        p.restore()

    # -- filters ----------------------------------------------------------------------------------
    def engine(self):
        """The filter engine of this thread, or None (the reason goes to errors, once)."""
        if self._fx is None and self._fx_error is None:
            try:
                self._fx = fx.Engine()
            except fx.FilterError as exc:
                self._fx_error = str(exc)
                self.errors.append(f"濾鏡：{exc}")
        return self._fx

    def run_effects(self, effects, img, t, duration, fps, wt, disp):
        """Apply a chain of effects to img (QImage ARGB32 premultiplied) at clip time t; each
        effect's own mask (clip-local, through world transform wt) limits where it shows."""
        todo = [e for e in effects if not e.get("disabled")]
        eng = self.engine() if todo else None
        if eng is None:
            return img
        arr = image_to_array(img)
        for e in todo:
            d = fx.get(e["filter"])
            vals = {p.name: fx.uniform_value(p, e["params"].get(p.name), t) for p in d.params}
            try:
                out = eng.run(d, vals, arr, time=t / US, progress=min(1.0, max(0.0, t / max(1, duration))),
                              frame=max(0, round(t * fps / US)))
            except fx.FilterError as exc:
                self.errors.append(f"濾鏡「{d.name}」：{exc}")
                continue
            mk = e.get("mask")
            if mk:
                h, w = arr.shape[:2]
                m = coverage(mk, t, disp, wt, w, h, curves.value(mk.get("feather", 0.0), t))[..., None]
                out = (arr * (1 - m) + out * m).round().astype(np.uint8)
            arr = np.ascontiguousarray(out)
        return array_to_image(arr)

    def draw_filtered(self, q, plain, c, t, disp, fps):
        """Draw a clip's picture, run its effects over it, and put the result on q."""
        dev = q.device()
        W, H = dev.width(), dev.height()
        wt = q.worldTransform()
        layer = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
        layer.fill(Qt.transparent)
        lp = QPainter(layer)
        lp.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        lp.setTransform(wt)
        plain(lp)
        lp.end()
        layer = self.run_effects(c["effects"], layer, t, c["duration_us"], fps, wt, disp)
        q.save()
        q.resetTransform()
        q.drawImage(0, 0, layer)
        q.restore()

    def draw_filter_clip(self, p, c, W, H, fps, t_us):
        """A filter clip: what has been drawn so far (the tracks below) goes through its
        effects, inside its mask and at its opacity."""
        tf = c.get("transform") or {}
        t = t_us - c["start_us"]
        v = lambda k, d: curves.value(tf.get(k, d), t)
        strength = min(1.0, max(0.0, v("opacity", 1.0)))
        if strength <= 0 or not any(not e.get("disabled") for e in c.get("effects") or []):
            return
        dev = p.device()
        w, h = dev.width(), dev.height()
        p.save()
        p.translate(W / 2 + v("x", 0.0) * W / 2, H / 2 - v("y", 0.0) * H / 2)
        p.rotate(v("rotation", 0.0))
        p.scale(v("scale", 1.0), curves.value(tf.get("scale_y", tf.get("scale", 1.0)), t))
        wt = p.worldTransform()
        p.restore()
        if not wt.isInvertible():
            return
        base = dev.copy() if isinstance(dev, QImage) else None
        if base is None:
            return
        base = base.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        out = self.run_effects(c["effects"], base, t, c["duration_us"], fps, wt, (W, H))
        cov = np.full((h, w), strength, np.float32)
        if project.active_mask(c):
            mk = c["mask"]
            cov = cov * coverage(mk, t, (W, H), wt, w, h, curves.value(mk.get("feather", 0.0), t))
        a, b = image_to_array(base).astype(np.float32), image_to_array(out).astype(np.float32)
        res = np.ascontiguousarray((a + (b - a) * cov[..., None]).round().astype(np.uint8))
        p.save()
        p.resetTransform()
        p.setClipping(False)
        p.setOpacity(1.0)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawImage(0, 0, array_to_image(res))
        p.restore()


def coverage(mask, t, disp, wt, W, H, feather):
    """How much of each device pixel (H x W) a mask lets through, 0..1. The mask lives in the
    clip's own space (centre origin, y up, disp = the clip's size there); wt maps that space
    to the device."""
    inv, ok = wt.inverted()
    v = lambda k, d: curves.value(mask.get(k, d), t)
    dw, dh = disp
    gx, gy = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
    lx = inv.m11() * gx + inv.m21() * gy + inv.dx()                 # clip-local, y down
    ly = inv.m12() * gx + inv.m22() * gy + inv.dy()
    mx, my = lx - v("cx", 0.0) * dw / 2, ly + v("cy", 0.0) * dh / 2
    b = math.radians(v("rotation", 0.0))
    fx_ = mx * math.cos(b) + my * math.sin(b)                       # the mask's own frame
    fy_ = -mx * math.sin(b) + my * math.cos(b)
    m = masks.alpha(mask["kind"], v("w", 1.0) * dw, v("h", 1.0) * dh, feather, fx_, -fy_)
    if mask.get("invert"):
        m = 1 - m
    return m.astype(np.float32)


def image_to_array(img):
    """QImage -> H x W x 4 uint8 RGBA, premultiplied (a copy)."""
    im = img.convertToFormat(QImage.Format_RGBA8888_Premultiplied)
    w, h = im.width(), im.height()
    return np.ndarray((h, w, 4), np.uint8, buffer=im.constBits(), strides=(im.bytesPerLine(), 4, 1)).copy()


def array_to_image(arr):
    h, w = arr.shape[:2]
    im = QImage(np.ascontiguousarray(arr).data, w, h, w * 4, QImage.Format_RGBA8888_Premultiplied).copy()
    return im.convertToFormat(QImage.Format_ARGB32_Premultiplied)


def quantize(scale):
    """The next step of 2^(1/4) at or above scale: text drawn at most 19% larger than shown."""
    return 2 ** (math.ceil(math.log2(scale) * 4 - 1e-9) / 4)


def mask_path(mask, t, disp):
    """The visible area of a mask in the clip's own coordinates (centre origin, y down)."""
    v = lambda k, d: curves.value(mask.get(k, d), t)
    dw, dh = disp
    w, h = v("w", 1.0) * dw, v("h", 1.0) * dh
    shape = QPainterPath()
    kind = mask["kind"]
    if kind == "line":                                  # keeps the side above the line
        shape.addRect(QRectF(-BIG, -BIG, 2 * BIG, BIG))
    elif kind == "mirror":
        shape.addRect(QRectF(-BIG, -h / 2, 2 * BIG, h))
    elif kind == "circle":
        shape.addEllipse(QPointF(0, 0), w / 2, h / 2)
    else:
        shape.addRect(QRectF(-w / 2, -h / 2, w, h))
    xf = QTransform().translate(v("cx", 0.0) * dw / 2, -v("cy", 0.0) * dh / 2).rotate(v("rotation", 0.0))
    path = xf.map(shape)
    if mask.get("invert"):
        everything = QPainterPath()
        everything.addRect(QRectF(-BIG, -BIG, 2 * BIG, 2 * BIG))
        path = everything.subtracted(path)
    return path


def frame_count(view):
    return max(1, round(view["duration_us"] * view["fps"] / US))


def qimage_rgba_bytes(img):
    """Bytes of an image as RGBA8888 (for tests and comparisons)."""
    im = img.convertToFormat(QImage.Format_RGBA8888)
    return bytes(im.constBits())[: im.width() * im.height() * 4], im.width(), im.height()
