"""Live preview renderer: draws a frame straight from the project model with QPainter.

The export path (build.py -> MLT) is the reference; this one trades a little exactness
for speed so edits and drags show on the next frame without rebuilding anything. It
follows the same rules as build.py:
  * a clip covers frames round(start * fps) .. round(end * fps) - 1;
  * keyframe time is frame time minus the clip start;
  * position in half-canvas units (y up), clockwise rotation, uniform scale about the
    clip centre; pictures are fitted into the canvas, texts are textlayout images;
  * masks live in material space (they move with the clip), drawn as clip paths;
  * a clip whose effects go to the background (project.backdrop_of) runs them on what is
    under it, inside its shape (a built-in asset's: where it is, not its colours' alpha nor
    its opacity, assets.cover), then draws itself on top unless its body is hidden;
  * a group (群組) is drawn like a compound the size of its level: its tracks go to a layer
    at group time (draw_content: with its matte on, the bottom track's clips cut the ones
    above), which goes through the group's transform, effects and mask;
  * compound clips render their tracks into a layer first, at time - start + source start;
    a static compound (靜態片段) always at time 0 (its first frame), drawn once and reused
    like a picture; a component's instance (元件, components.py) draws the component with
    its own parameter values put in, at clip time;
  * a compound mask (kind "compound") cuts with a compound's picture (view["compounds"]):
    its alpha or luma, at clip time + its t_off (a static one: its still); an image mask
    (kind "image") the same way with a picture file. view["matte_preview"] =
    {clip, opacity} (the editor, while the mask is edited) draws that picture over the clip.
QPainter on QImage is usable from any thread, so the player renders off the UI thread.
glrender.py draws the same frames on the GPU (and is used when it can be); this one is the
reference and the fallback.
"""
import json
import math

import numpy as np
from PIL.ImageQt import ImageQt
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QTransform

from . import assets, components, curves, fonts, fx, masks, project, svgimage, textlayout

US = 1_000_000
TEXT_FIELDS = ("size", "color", "letter_spacing", "line_spacing", "italic_deg", "font_path", "align")
BIG = 1e5
# clip blend modes (edit.BLEND_MODES) as the painter's composition modes
BLEND_OPS = {"normal": QPainter.CompositionMode_SourceOver, "multiply": QPainter.CompositionMode_Multiply,
             "screen": QPainter.CompositionMode_Screen, "overlay": QPainter.CompositionMode_Overlay,
             "darken": QPainter.CompositionMode_Darken, "lighten": QPainter.CompositionMode_Lighten,
             "color_dodge": QPainter.CompositionMode_ColorDodge, "color_burn": QPainter.CompositionMode_ColorBurn,
             "hard_light": QPainter.CompositionMode_HardLight, "soft_light": QPainter.CompositionMode_SoftLight,
             "difference": QPainter.CompositionMode_Difference, "exclusion": QPainter.CompositionMode_Exclusion,
             "add": QPainter.CompositionMode_Plus}


class Renderer:
    def __init__(self, video_frame=None, cache_limit=600):
        """video_frame(path, source_us, w, h) -> QImage or None, for video clips."""
        self.video_frame = video_frame
        self.images = {}            # path -> [QImage halved per level] (a mipmap)
        self.texts = {}             # (spec json, scale) -> QImage
        self.stills = {}            # (static compound content, scale) -> QImage
        self.cache_limit = cache_limit
        self.errors = []            # clips that could not be drawn, reported by the player
        self._fx = None             # filter engine (an OpenGL context of the thread that renders)
        self._fx_error = None
        self.compounds = {}         # the view's compounds (what compound masks cut with)
        self.matte_preview = None   # {clip, opacity}: show that clip's mask compound over it
        self._matting = set()       # compounds being drawn as a mask now (one cannot cut itself)

    # -- assets -----------------------------------------------------------------------------------
    def asset(self, p, w, h):
        """A built-in asset with parameters p (assets.at) drawn for about w x h px: at the next
        power of two at or above it, so it stays sharp (as SVG files are)."""
        side = 2 ** max(6, math.ceil(math.log2(max(w, h, 1))))
        text = assets.svg(p)
        key = ("asset", text, side)
        im = self.images.get(key)
        if im is None:
            k = side / max(p["w"], p["h"], 1)
            pad = 2 * assets.overflow(p)                 # (an outline reaching out of its frame)
            im = svgimage.raster_text(text, (p["w"] + pad) * k, (p["h"] + pad) * k)
            if len(self.images) >= 48:
                self.images.pop(next(iter(self.images)))
            self.images[key] = im
        return im

    def image(self, path, w, h):
        """The image at the smallest mip level at least w x h; the painter scales it the rest
        of the way (less than 2x, so bilinear stays clean). Decoding and smooth scaling happen
        once per file: animated sizes (zooming compounds) used to redo them every frame.
        An SVG is drawn afresh at the next power of two at or above the size asked for, so it
        stays sharp however far it is zoomed."""
        if svgimage.is_svg(path):
            side = 2 ** max(6, math.ceil(math.log2(max(w, h, 1))))
            key = (path, side)
            im = self.images.get(key)
            if im is None:
                try:
                    sw, sh = svgimage.size(path)
                    k = side / max(sw, sh)
                    im = svgimage.raster(path, sw * k, sh * k)
                except ValueError:
                    im = QImage(1, 1, QImage.Format_ARGB32_Premultiplied)
                    im.fill(QColor(255, 0, 255))
                if len(self.images) >= 48:
                    self.images.pop(next(iter(self.images)))
                self.images[key] = im
            return im
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
        key = (json.dumps(spec, sort_keys=True, default=str), round(scale, 3), canvas_h, fonts.map_key())
        im = self.texts.get(key)
        if im is None:
            im = QImage(ImageQt(textlayout.render(spec, scale, canvas_h))).convertToFormat(
                QImage.Format_ARGB32_Premultiplied)
            self._remember(self.texts, key, im)
        return im

    STILL_MAX_PX = 4096

    def still(self, comp, k, fps):
        """A static compound's picture at k px per compound unit (rounded up to a few steps,
        at most STILL_MAX_PX on its long side): drawn once, then reused while it is unchanged."""
        cw, ch = comp["width"], comp["height"]
        k = min(quantize(k), self.STILL_MAX_PX / max(cw, ch))
        key = (json.dumps(comp["tracks"], sort_keys=True, default=str), cw, ch, round(k, 4))
        im = self.stills.get(key)
        if im is None:
            im = QImage(max(1, math.ceil(cw * k)), max(1, math.ceil(ch * k)), QImage.Format_ARGB32_Premultiplied)
            im.fill(Qt.transparent)
            lp = QPainter(im)
            lp.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
            lp.scale(k, k)
            self.draw_tracks(lp, comp["tracks"], cw, ch, fps, 0, k)
            lp.end()
            if len(self.stills) >= 24:
                self.stills.pop(next(iter(self.stills)))
            self.stills[key] = im
        return im

    def _remember(self, cache, key, value):
        if len(cache) >= self.cache_limit:
            cache.pop(next(iter(cache)))
        cache[key] = value

    # -- compound masks ---------------------------------------------------------------------------
    MATTE_MAX_PX = 2048

    def begin(self, view):
        """Take what a frame of view needs besides its tracks."""
        self.compounds = view.get("compounds") or {}
        self.matte_preview = view.get("matte_preview")

    def matte_compound(self, mask, t=0):
        """What a picture mask cuts with: the compound of a compound mask, or for an image mask
        {image, width, height}; None when it is not one, has none (chosen, deleted, a file that
        is gone) or that compound is being drawn as a mask already."""
        kind = curves.value(mask.get("kind"), t) if mask else None
        if kind == "image":
            path, w, h = mask.get("image"), mask.get("img_w"), mask.get("img_h")
            return {"image": path, "width": w, "height": h} if path and w and h else None
        if kind != "compound":
            return None
        kid = mask.get("compound_id")
        return None if kid in self._matting else self.compounds.get(kid)

    def clip_mask(self, c, t):
        """The mask that cuts clip c now (None: none, off, or a picture mask without its picture)."""
        m = project.active_mask(c)
        if m and curves.value(m.get("kind"), t) in ("compound", "image") and self.matte_compound(m, t) is None:
            return None
        return m

    def matte_k(self, mask, t, disp, comp, world):
        """Px per compound unit for a mask's compound to be as sharp as it shows through world."""
        kd = math.sqrt(abs(world.determinant())) or 1.0
        return max(curves.value(mask.get("w", 1.0), t) * disp[0], 1.0) * kd / comp["width"]

    def matte_image(self, mask, comp, t, k, fps):
        """A mask's compound drawn at k px per compound unit: a static one's still, else its
        frame at clip time t + t_off (held at its first / last frame); an image mask's picture."""
        if comp.get("image"):
            return self.image(comp["image"], comp["width"] * k, comp["height"] * k)
        kid = mask.get("compound_id")
        self._matting.add(kid)
        try:
            if comp.get("static"):
                return self.still(comp, k, fps)
            cw, ch = comp["width"], comp["height"]
            k = min(k, self.MATTE_MAX_PX / max(cw, ch))
            im = QImage(max(1, math.ceil(cw * k)), max(1, math.ceil(ch * k)), QImage.Format_ARGB32_Premultiplied)
            im.fill(Qt.transparent)
            lp = QPainter(im)
            lp.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
            lp.scale(k, k)
            self.draw_tracks(lp, comp["tracks"], cw, ch, fps, matte_time(comp, t + mask.get("t_off", 0), fps), k)
            lp.end()
            return im
        finally:
            self._matting.discard(kid)

    def mask_coverage(self, mask, t, disp, wt, W, H, fps):
        """coverage() of any mask, compound masks included."""
        comp = self.matte_compound(mask, t)
        if comp is None:
            return coverage(mask, t, disp, wt, W, H, curves.value(mask.get("feather", 0.0), t))
        img = self.matte_image(mask, comp, t, self.matte_k(mask, t, disp, comp, wt), fps)
        return matte_coverage(mask, t, disp, wt, W, H, img)

    def draw_matte_ghost(self, p, mask, t, disp, fps, opacity):
        """A compound mask's picture over the clip (p: in the clip's own space), to place it."""
        comp = self.matte_compound(mask, t)
        if comp is None:
            return
        img = self.matte_image(mask, comp, t, self.matte_k(mask, t, disp, comp, p.worldTransform()), fps)
        v = lambda k, d: curves.value(mask.get(k, d), t)
        w, h = v("w", 1.0) * disp[0], v("h", 1.0) * disp[1]
        p.save()
        p.setClipping(False)
        p.setOpacity(opacity)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.translate(v("cx", 0.0) * disp[0] / 2, -v("cy", 0.0) * disp[1] / 2)
        p.rotate(v("rotation", 0.0))
        p.drawImage(QRectF(-w / 2, -h / 2, w, h), img)
        p.restore()

    # -- frames -----------------------------------------------------------------------------------
    def render(self, view, frame, width, height, alpha=False):
        """RGB frame `frame` of a project-like view, drawn at width x height; on a transparent
        background instead of black with alpha (transparent exports)."""
        img = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent if alpha else QColor("black"))
        p = QPainter(img)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        p.scale(width / view["width"], height / view["height"])
        self.begin(view)
        self.draw_tracks(p, view["tracks"], view["width"], view["height"], view["fps"],
                         frame / view["fps"] * US, width / view["width"])
        p.end()
        return img

    def draw_content(self, p, comp, W, H, fps, t_us, px_per_unit, through=False):
        """A compound's or a group's tracks; a group with its matte on: its bottom track's clips
        cut the clips above them (by their alpha) - with invert, cut them out of them - and are
        drawn too with show; the clips above are left out with body off (顯示主體). through
        (穿透): what p has is under them, not a clear layer."""
        matte = (comp.get("matte") or {}) if comp.get("group") else {}
        tracks = [tr for tr in comp["tracks"] if tr["kind"] != "audio"]
        if not matte.get("on") or len(tracks) < 2 or not isinstance(p.device(), QImage):
            self.draw_tracks(p, comp["tracks"], W, H, fps, t_us, px_per_unit)
            return
        dev = p.device()

        def layer(trs, under=None):
            if under is None:
                im = QImage(dev.width(), dev.height(), QImage.Format_ARGB32_Premultiplied)
                im.fill(Qt.transparent)
            else:
                im = under.copy()
            lp = QPainter(im)
            lp.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
            lp.setTransform(p.worldTransform())
            self.draw_tracks(lp, trs, W, H, fps, t_us, px_per_unit)
            lp.end()
            return im
        cut = layer(tracks[:1])
        under = dev.copy().convertToFormat(QImage.Format_ARGB32_Premultiplied) if through else None
        if matte.get("show"):
            if under is None:
                under = cut
            else:
                up = QPainter(under)
                up.drawImage(0, 0, cut)
                up.end()
        if under is None:
            under = layer([])
        out = under
        if matte.get("body", True):
            # as Photoshop's clipping masks: the clips above are drawn on what is under them (the
            # shown mask object), so their blend modes mix with it, and kept where the mask object
            # is (inverted: where it is not)
            above = layer(tracks[1:], under)
            a = image_to_array(cut)[..., 3:4].astype(np.float32) / 255
            if matte.get("invert"):
                a = 1 - a
            b0, b1 = image_to_array(under).astype(np.float32), image_to_array(above).astype(np.float32)
            out = array_to_image(np.ascontiguousarray((b0 + (b1 - b0) * a).round().astype(np.uint8)))
        p.save()
        p.resetTransform()
        if through:
            p.setClipping(False)
            p.setOpacity(1.0)
            p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawImage(0, 0, out)
        p.restore()

    def draw_through(self, p, c, comp, t, fps, opacity, disp, fit, k, W, H):
        """穿透 (as Photoshop's pass-through groups): group c's clips drawn straight on p, so their
        blend modes mix with what is under the group; its opacity and mask fade between that and
        what was there."""
        dev = p.device()
        world = clip_world(c, t, W, H) * p.worldTransform()
        mask = self.clip_mask(c, t)
        fade = opacity < 1 or mask is not None
        before = dev.copy().convertToFormat(QImage.Format_ARGB32_Premultiplied) if fade else None
        p.save()
        p.setTransform(QTransform(fit, 0, 0, fit, -disp[0] / 2, -disp[1] / 2) * world)
        self.draw_content(p, comp, comp["width"], comp["height"], fps, t, k, through=True)
        p.restore()
        if not fade:
            return
        a = np.full((dev.height(), dev.width(), 1), opacity, np.float32)
        if mask is not None:
            a *= self.mask_coverage(mask, t, disp, world, dev.width(), dev.height(), fps)[..., None]
        now = dev.copy().convertToFormat(QImage.Format_ARGB32_Premultiplied)
        b0, b1 = image_to_array(before).astype(np.float32), image_to_array(now).astype(np.float32)
        p.save()
        p.resetTransform()
        p.setClipping(False)
        p.setOpacity(1.0)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawImage(0, 0, array_to_image(np.ascontiguousarray((b0 + (b1 - b0) * a).round().astype(np.uint8))))
        p.restore()

    def draw_tracks(self, p, tracks, W, H, fps, t_us, px_per_unit):
        """Draw every visible clip at time t_us (us) on a W x H canvas, bottom track first."""
        for tr in tracks:
            if tr["kind"] == "audio" or not project.visible(tr):
                continue
            for c in tr["clips"]:
                if on_frame(c, t_us, fps):
                    try:
                        if c["type"] == "filter":
                            self.draw_filter_clip(p, c, W, H, fps, t_us, px_per_unit)
                        else:
                            self.draw_clip(p, c, W, H, fps, t_us, px_per_unit)
                    except Exception as exc:          # one bad clip must not blank the preview
                        self.errors.append(f"{c.get('name') or c['type']}: {exc}")

    def draw_clip(self, p, c, W, H, fps, t_us, px_per_unit):
        tf = c.get("transform") or {}
        t = project.stepped(c, t_us - c["start_us"])           # (降低幀數: in steps)
        v = lambda k, d: curves.value(tf.get(k, d), t)
        opacity = min(1.0, max(0.0, v("opacity", 1.0)))
        backdrop, hide = project.backdrop_of(c)
        if opacity <= 0 and not (backdrop and c.get("asset")):    # (a shape's: not faded by it)
            return
        sx = v("scale", 1.0)
        sy = curves.value(tf.get("scale_y", tf.get("scale", 1.0)), t)
        kind = c["type"]
        cover = None                                       # what 套用至背景 covers, when not draw
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
            bw, bh = project.picture_size(c, W, H, t=t)
            tw, th = bw * abs(sx) * px_per_unit, bh * abs(sy) * px_per_unit
            rect = QRectF(-bw / 2, -bh / 2, bw, bh)
            if c.get("asset"):                       # drawn from its parameters at t
                q = assets.at(c["asset"], t)
                pic = self.asset(q, tw, th)
                rect = asset_rect(q, bw, bh)
                if backdrop:
                    shape = self.asset(assets.cover(q), tw, th)
                    cover = lambda qq=p: qq.drawImage(rect, shape)
            elif kind == "image":
                pic = self.image(m["path"], tw, th)
            else:
                pic = self.video_frame(m["path"], project.source_time(c, t),
                                       max(1, round(tw)), max(1, round(th))) if self.video_frame else None
                if pic is None:
                    return
            draw = lambda q=p: q.drawImage(rect, pic)
            disp = (bw, bh)
        elif kind in ("compound", "group"):
            comp = components.content(c, t) if kind == "compound" else group_content(c, W, H)
            cw, ch = comp["width"], comp["height"]
            fit = min(W / cw, H / ch)
            bw, bh = cw * fit, ch * fit
            k = fit * max(abs(sx), abs(sy), 0.01) * px_per_unit       # layer px per compound unit
            if kind == "group" and curves.value(c.get("blend", "normal"), t) == "pass_through" \
                    and not project.visual_effects(c) and isinstance(p.device(), QImage):
                self.draw_through(p, c, comp, t, fps, opacity, (bw, bh), fit, k, W, H)
                return
            if comp.get("static"):
                pic = self.still(comp, k, fps)
                draw = lambda q=p: q.drawImage(QRectF(-bw / 2, -bh / 2, bw, bh), pic)
                disp = (bw, bh)
            else:
                draw = None

            def draw_live(q=p):
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
                self.draw_content(lp, comp, cw, ch, fps, t if kind == "group" else project.source_time(c, t), k)
                lp.end()
                q.drawImage(QRectF(vis.left(), vis.top(), layer.width() / k * fit, layer.height() / k * fit), layer)
            draw = draw or draw_live
            disp = (bw, bh)
        else:
            return
        if backdrop:                                       # 套用至背景: the effects work on what is under it
            self.draw_backdrop(p, c, W, H, t, disp, fps, px_per_unit,
                               lambda q: self.paint_body(q, c, W, H, t, disp, cover or draw,
                                                         1.0 if cover else opacity, fps))
            if hide or opacity <= 0:
                return
        elif project.visual_effects(c):
            plain = draw

            def draw(q=p):
                self.draw_filtered(q, plain, c, t, disp, fps, px_per_unit)
        self.paint_body(p, c, W, H, t, disp, draw, opacity, fps)

    def paint_body(self, p, c, W, H, t, disp, draw, opacity, fps):
        """A clip's picture (draw(painter) in its own space) put on p: opacity, blend mode,
        transform and mask."""
        tf = c.get("transform") or {}
        v = lambda k, d: curves.value(tf.get(k, d), t)
        sx = v("scale", 1.0)
        sy = curves.value(tf.get("scale_y", tf.get("scale", 1.0)), t)
        p.save()
        p.setOpacity(p.opacity() * opacity)
        p.setCompositionMode(BLEND_OPS.get(curves.value(c.get("blend", "normal"), t), QPainter.CompositionMode_SourceOver))
        p.translate(W / 2 + v("x", 0.0) * W / 2, H / 2 - v("y", 0.0) * H / 2)
        p.rotate(v("rotation", 0.0))                       # clockwise on a y-down canvas
        p.scale(sx * (-1 if tf.get("flip_h") else 1), sy * (-1 if tf.get("flip_v") else 1))
        mask = self.clip_mask(c, t)
        feather = curves.value(mask.get("feather", 0.0), t) if mask else 0.0
        if mask and (feather > 1e-3 or self.matte_compound(mask, t)):
            self.draw_soft(p, mask, t, disp, draw, fps)      # a clip path has no soft edge (nor a picture)
        else:
            if mask:
                p.setClipPath(mask_path(mask, t, disp))
            draw(p)
        if self.matte_preview and self.matte_preview.get("clip") == c["id"]:
            self.draw_matte_ghost(p, c.get("mask"), t, disp, fps, self.matte_preview.get("opacity", 0.4))
        p.restore()

    def draw_backdrop(self, p, c, W, H, t, disp, fps, unit, body):
        """套用至背景: what has been drawn so far goes through the clip's effects inside the clip's
        coverage (body(painter) paints the clip as it would show: its alpha, mask, opacity;
        unit: device px per canvas px)."""
        dev = p.device()
        if not isinstance(dev, QImage):
            return
        dw, dh = dev.width(), dev.height()
        cov = QImage(dw, dh, QImage.Format_ARGB32_Premultiplied)
        cov.fill(Qt.transparent)
        cp = QPainter(cov)
        cp.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        cp.setTransform(p.worldTransform())
        body(cp)
        cp.end()
        base = dev.copy().convertToFormat(QImage.Format_ARGB32_Premultiplied)
        out = self.run_effects(c["effects"], base, t, c["duration_us"], fps, clip_world(c, t, W, H) * p.worldTransform(),
                               disp, unit)
        a = image_to_array(cov)[..., 3:4].astype(np.float32) / 255
        b0, b1 = image_to_array(base).astype(np.float32), image_to_array(out).astype(np.float32)
        res = np.ascontiguousarray((b0 + (b1 - b0) * a).round().astype(np.uint8))
        p.save()
        p.resetTransform()
        p.setClipping(False)
        p.setOpacity(1.0)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawImage(0, 0, array_to_image(res))
        p.restore()

    def draw_soft(self, p, mask, t, disp, draw, fps):
        """Draw the clip through a feathered (or compound) mask: the clip goes to a layer the
        size of the target, which is multiplied by the mask's coverage and drawn back."""
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
        m8 = (self.mask_coverage(mask, t, disp, wt, W, H, fps) * 255 + 0.5).astype(np.uint16)
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

    def run_effects(self, effects, img, t, duration, fps, wt, disp, unit):
        """Apply a chain of effects to img (QImage ARGB32 premultiplied, unit of its px per canvas
        px) at clip time t; each effect's own mask (clip-local, through world transform wt)
        limits where it shows."""
        todo = [e for e in effects if not e.get("disabled") and e.get("filter") != project.TIME_FILTER]
        eng = self.engine() if todo else None
        if eng is None:
            return img
        arr = image_to_array(img)
        for e in todo:
            d = fx.get(e["filter"])
            vals = {p.name: fx.uniform_value(p, e["params"].get(p.name), t) for p in d.params}
            try:
                out = eng.run(d, vals, arr, time=t / US, progress=min(1.0, max(0.0, t / max(1, duration))),
                              frame=max(0, round(t * fps / US)), unit=unit)
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

    def draw_filtered(self, q, plain, c, t, disp, fps, unit):
        """Draw a clip's picture, run its effects over it (unit: q's px per canvas px), and put
        the result on q."""
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
        layer = self.run_effects(c["effects"], layer, t, c["duration_us"], fps, wt, disp, unit)
        q.save()
        q.resetTransform()
        q.drawImage(0, 0, layer)
        q.restore()

    def draw_filter_clip(self, p, c, W, H, fps, t_us, px_per_unit):
        """A filter clip: what has been drawn so far (the tracks below) goes through its
        effects, inside its mask and at its opacity."""
        tf = c.get("transform") or {}
        t = t_us - c["start_us"]
        v = lambda k, d: curves.value(tf.get(k, d), t)
        strength = min(1.0, max(0.0, v("opacity", 1.0)))
        if strength <= 0 or not project.visual_effects(c):
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
        out = self.run_effects(c["effects"], base, t, c["duration_us"], fps, wt, (W, H), px_per_unit)
        cov = np.full((h, w), strength, np.float32)
        mk = self.clip_mask(c, t)
        if mk:
            cov = cov * self.mask_coverage(mk, t, (W, H), wt, w, h, fps)
        a, b = image_to_array(base).astype(np.float32), image_to_array(out).astype(np.float32)
        res = np.ascontiguousarray((a + (b - a) * cov[..., None]).round().astype(np.uint8))
        p.save()
        p.resetTransform()
        p.setClipping(False)
        p.setOpacity(1.0)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawImage(0, 0, array_to_image(res))
        p.restore()


def _mask_points(mask, t, disp, wt, W, H):
    """Each device pixel (H x W) in the mask's own frame (centre origin, y down)."""
    inv, ok = wt.inverted()
    v = lambda k, d: curves.value(mask.get(k, d), t)
    dw, dh = disp
    gx, gy = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
    lx = inv.m11() * gx + inv.m21() * gy + inv.dx()                 # clip-local, y down
    ly = inv.m12() * gx + inv.m22() * gy + inv.dy()
    mx, my = lx - v("cx", 0.0) * dw / 2, ly + v("cy", 0.0) * dh / 2
    b = math.radians(v("rotation", 0.0))
    return mx * math.cos(b) + my * math.sin(b), -mx * math.sin(b) + my * math.cos(b)


def coverage(mask, t, disp, wt, W, H, feather):
    """How much of each device pixel (H x W) a mask lets through, 0..1. The mask lives in the
    clip's own space (centre origin, y up, disp = the clip's size there); wt maps that space
    to the device."""
    v = lambda k, d: curves.value(mask.get(k, d), t)
    fx_, fy_ = _mask_points(mask, t, disp, wt, W, H)
    m = masks.alpha(v("kind", "rectangle"), v("w", 1.0) * disp[0], v("h", 1.0) * disp[1], feather, fx_, -fy_)
    if v("invert", False):
        m = 1 - m
    return m.astype(np.float32)


LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


def matte_coverage(mask, t, disp, wt, W, H, img):
    """coverage() of a compound mask whose picture is img, stretched over its w x h frame:
    the picture's alpha, or its brightness (matte "luma"); nothing outside the frame."""
    v = lambda k, d: curves.value(mask.get(k, d), t)
    fx_, fy_ = _mask_points(mask, t, disp, wt, W, H)
    u = fx_ / max(v("w", 1.0) * disp[0], 1e-6) + 0.5
    vv = fy_ / max(v("h", 1.0) * disp[1], 1e-6) + 0.5
    arr = image_to_array(img).astype(np.float32) / 255
    ih, iw = arr.shape[:2]
    inside = (u >= 0) & (u < 1) & (vv >= 0) & (vv < 1)
    px = arr[np.clip((vv * ih).astype(int), 0, ih - 1), np.clip((u * iw).astype(int), 0, iw - 1)]
    val = px[..., :3] @ LUMA if v("matte", "alpha") == "luma" else px[..., 3]      # (premultiplied: luma on black)
    m = np.where(inside, val, 0.0)
    if v("invert", False):
        m = 1 - m
    return m.astype(np.float32)


def matte_time(comp, t, fps):
    """Compound time for a mask at clip time t: the same, held at the compound's last frame."""
    return min(max(0.0, t), max(0.0, (comp.get("duration_us") or 0) - US / fps))


def image_to_array(img):
    """QImage -> H x W x 4 uint8 RGBA, premultiplied (a copy)."""
    im = img.convertToFormat(QImage.Format_RGBA8888_Premultiplied)
    w, h = im.width(), im.height()
    return np.ndarray((h, w, 4), np.uint8, buffer=im.constBits(), strides=(im.bytesPerLine(), 4, 1)).copy()


def array_to_image(arr):
    h, w = arr.shape[:2]
    im = QImage(np.ascontiguousarray(arr).data, w, h, w * 4, QImage.Format_RGBA8888_Premultiplied).copy()
    return im.convertToFormat(QImage.Format_ARGB32_Premultiplied)


def group_content(g, W, H):
    """A group as compound-like content: its tracks on a canvas the size of its level."""
    return {"width": W, "height": H, "tracks": g["tracks"], "group": True, "matte": g.get("matte"),
            "duration_us": g["duration_us"]}


def clip_world(c, t, W, H):
    """Clip space (centre origin, y down) -> canvas, as draw_clip places a clip at clip time t."""
    tf = c.get("transform") or {}
    v = lambda k, d: curves.value(tf.get(k, d), t)
    return QTransform().translate(W / 2 + v("x", 0.0) * W / 2, H / 2 - v("y", 0.0) * H / 2).rotate(v("rotation", 0.0)) \
        .scale(v("scale", 1.0) * (-1 if tf.get("flip_h") else 1),
               curves.value(tf.get("scale_y", tf.get("scale", 1.0)), t) * (-1 if tf.get("flip_v") else 1))


def asset_rect(q, bw, bh):
    """Where a built-in asset's picture (parameters q, as assets.at gives them) goes for a
    bw x bh frame centred on the origin: larger by the outline that reaches out of it."""
    pad = assets.overflow(q)
    kx, ky = bw / max(q["w"], 1e-9), bh / max(q["h"], 1e-9)
    return QRectF(-bw / 2 - pad * kx, -bh / 2 - pad * ky, bw + 2 * pad * kx, bh + 2 * pad * ky)


def quantize(scale):
    """The next step of 2^(1/4) at or above scale: text drawn at most 19% larger than shown."""
    return 2 ** (math.ceil(math.log2(scale) * 4 - 1e-9) / 4)


def mask_path(mask, t, disp):
    """The visible area of a mask in the clip's own coordinates (centre origin, y down)."""
    v = lambda k, d: curves.value(mask.get(k, d), t)
    dw, dh = disp
    w, h = v("w", 1.0) * dw, v("h", 1.0) * dh
    shape = QPainterPath()
    kind = v("kind", "rectangle")
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
    if v("invert", False):
        everything = QPainterPath()
        everything.addRect(QRectF(-BIG, -BIG, 2 * BIG, 2 * BIG))
        path = everything.subtracted(path)
    return path


def on_frame(c, t_us, fps):
    """Whether clip c shows at time t_us: both rounded to frames, so a clip that starts where
    the playhead is (start_us rounded to whole us) shows on that frame and not on its end one."""
    f = round(t_us * fps / US)
    return round(c["start_us"] * fps / US) <= f < round((c["start_us"] + c["duration_us"]) * fps / US)


def frame_count(view):
    return max(1, round(view["duration_us"] * view["fps"] / US))


def qimage_rgba_bytes(img):
    """Bytes of an image as RGBA8888 (for tests and comparisons)."""
    im = img.convertToFormat(QImage.Format_RGBA8888)
    return bytes(im.constBits())[: im.width() * im.height() * 4], im.width(), im.height()
