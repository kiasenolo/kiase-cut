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

from PIL.ImageQt import ImageQt
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QTransform

from . import curves, textlayout

US = 1_000_000
TEXT_FIELDS = ("size", "color", "letter_spacing", "line_spacing", "italic_deg")
BIG = 1e5


class Renderer:
    def __init__(self, video_frame=None, cache_limit=600):
        """video_frame(path, source_us, w, h) -> QImage or None, for video clips."""
        self.video_frame = video_frame
        self.images = {}            # (path, w, h) -> QImage pre-scaled for the target
        self.texts = {}             # (spec json, scale) -> QImage
        self.cache_limit = cache_limit
        self.errors = []            # clips that could not be drawn, reported by the player

    # -- assets -----------------------------------------------------------------------------------
    def image(self, path, w, h):
        """Image file scaled once to the size it is drawn at (cached)."""
        key = (path, max(1, round(w)), max(1, round(h)))
        im = self.images.get(key)
        if im is None:
            src = QImage(path)
            if src.isNull():
                src = QImage(1, 1, QImage.Format_ARGB32_Premultiplied)
                src.fill(QColor(255, 0, 255))
            im = src.scaled(key[1], key[2], Qt.IgnoreAspectRatio, Qt.SmoothTransformation) \
                .convertToFormat(QImage.Format_ARGB32_Premultiplied)
            self._remember(self.images, key, im)
        return im

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
            if tr["kind"] == "audio":
                continue
            for c in tr["clips"]:
                if round(c["start_us"] * fps / US) <= f < round((c["start_us"] + c["duration_us"]) * fps / US):
                    try:
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
            pic = self.text(spec, rs, H)
            bw, bh = pic.width() / rs * k_size, pic.height() / rs * k_size
            draw = lambda: p.drawImage(QRectF(-bw / 2, -bh / 2, bw, bh), pic)
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
            draw = lambda: p.drawImage(QRectF(-bw / 2, -bh / 2, bw, bh), pic)
            disp = (bw, bh)
        elif kind == "compound":
            comp = c["compound"]
            cw, ch = comp["width"], comp["height"]
            fit = min(W / cw, H / ch)
            bw, bh = cw * fit, ch * fit
            k = fit * max(abs(sx), abs(sy), 0.01) * px_per_unit       # layer px per compound unit
            layer = QImage(max(1, round(cw * k)), max(1, round(ch * k)), QImage.Format_ARGB32_Premultiplied)
            layer.fill(Qt.transparent)
            lp = QPainter(layer)
            lp.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
            lp.scale(k, k)
            self.draw_tracks(lp, comp["tracks"], cw, ch, fps, t + c.get("source_start_us", 0), k)
            lp.end()
            draw = lambda: p.drawImage(QRectF(-bw / 2, -bh / 2, bw, bh), layer)
            disp = (bw, bh)
        else:
            return
        p.save()
        p.setOpacity(p.opacity() * opacity)
        p.translate(W / 2 + v("x", 0.0) * W / 2, H / 2 - v("y", 0.0) * H / 2)
        p.rotate(v("rotation", 0.0))                       # clockwise on a y-down canvas
        p.scale(sx * (-1 if tf.get("flip_h") else 1), sy * (-1 if tf.get("flip_v") else 1))
        if c.get("mask"):
            p.setClipPath(mask_path(c["mask"], t, disp))
        draw()
        p.restore()


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
