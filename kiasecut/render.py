"""Live preview renderer: draws a frame straight from the project model with QPainter.

The export path (build.py -> MLT) is the reference; this one trades a little exactness
for speed so edits and drags show on the next frame without rebuilding anything. It
follows the same rules as build.py:
  * a clip covers frames round(start * fps) .. round(end * fps) - 1;
  * keyframe time is frame time minus the clip start;
  * position in half-canvas units (y up), clockwise rotation, uniform scale about the
    clip centre - or its pivot (中心點, project.centre_px); pictures are fitted into the canvas, texts are textlayout images;
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
    its own parameter values put in, at clip time; with 效果穿透 (project.passes_through)
    the layer has what is under the clip beside it (self.outer, mapped into the layer), and
    the 套用至背景 and filter clips drawn straight on it run their effects on that with the
    layer over it (seen) - what they give is kept in the layer where they cover, so it shows
    over what was under the clip wherever the compound is drawn (a static one live then);
  * a compound mask (kind "compound") cuts with a compound's picture (view["compounds"]):
    its alpha or luma, at clip time + its t_off (a static one: its still); an image mask
    (kind "image") the same way with a picture file, a video mask (kind "video") with a video's
    frame at clip time + its t_off. view["matte_preview"] =
    {clip, opacity} (the editor, while the mask is edited) draws that picture over the clip.
QPainter on QImage is usable from any thread, so the player renders off the UI thread.
glrender.py draws the same frames on the GPU (and is used when it can be); this one is the
reference and the fallback.
"""
import json
import math

import numpy as np
from PIL.ImageQt import ImageQt
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QImageIOHandler, QImageReader, QPainter, QPainterPath, QTransform

from . import assets, components, curves, fonts, fx, masks, nodegraph, project, propexpr, rack, svgimage, sysmem, textlayout, textvars, vector, viz

US = 1_000_000
TEXT_FIELDS = ("size", "color", "fill", "stroke_on", "stroke_color", "stroke", "stroke_align",
               "letter_spacing", "line_spacing", "italic_deg", "font_path", "align", "valign",
               "box_w", "box_h") + tuple(textlayout.DECOR)
BIG = 1e5
TEXT_CACHE_BYTES = sysmem.scaled(192 << 20, 48 << 20)
# clip blend modes (edit.BLEND_MODES) as the painter's composition modes
BLEND_OPS = {"normal": QPainter.CompositionMode_SourceOver, "multiply": QPainter.CompositionMode_Multiply,
             "screen": QPainter.CompositionMode_Screen, "overlay": QPainter.CompositionMode_Overlay,
             "darken": QPainter.CompositionMode_Darken, "lighten": QPainter.CompositionMode_Lighten,
             "color_dodge": QPainter.CompositionMode_ColorDodge, "color_burn": QPainter.CompositionMode_ColorBurn,
             "hard_light": QPainter.CompositionMode_HardLight, "soft_light": QPainter.CompositionMode_SoftLight,
             "difference": QPainter.CompositionMode_Difference, "exclusion": QPainter.CompositionMode_Exclusion,
             "add": QPainter.CompositionMode_Plus}


class Mips:
    """A picture file's mip levels: its size halved n times (level n), while both sides are
    over 64 px. Each is decoded when it is first needed: a JPEG straight at that level's size
    (about twice as quick as the whole, which a small preview never needs), others halved from
    the whole picture. A file that cannot be read is one magenta pixel."""

    def __init__(self, path):
        self.path = path
        self.levels = {}            # n -> QImage (premultiplied)
        r = QImageReader(path)
        s = r.size()
        self.turned = r.autoTransform() and bool(r.transformation() & QImageIOHandler.TransformationRotate90)
        self.partial = r.supportsOption(QImageIOHandler.ScaledSize)
        w, h = (s.height(), s.width()) if self.turned else (s.width(), s.height())
        self.sizes = [(w, h)] if s.isValid() else [(1, 1)]
        while self.sizes[-1][0] > 64 and self.sizes[-1][1] > 64:
            self.sizes.append((max(1, self.sizes[-1][0] // 2), max(1, self.sizes[-1][1] // 2)))
        if not s.isValid():
            self.levels[0] = self._missing()

    @staticmethod
    def _missing():
        im = QImage(1, 1, QImage.Format_ARGB32_Premultiplied)
        im.fill(QColor(255, 0, 255))
        return im

    def at(self, w, h):
        """The smallest level at least w x h (the whole picture when none is)."""
        n = next((i for i in range(len(self.sizes) - 1, -1, -1)
                  if self.sizes[i][0] >= w and self.sizes[i][1] >= h), 0)
        im = self.levels.get(n)
        if im is None:
            im = self.levels[n] = self._make(n)
        return im

    def _make(self, n):
        bigger = [m for m in self.levels if m < n]
        if not bigger and n and self.partial:
            r = QImageReader(self.path)
            w, h = self.sizes[n]
            r.setScaledSize(QSize(h, w) if self.turned else QSize(w, h))
            im = r.read()
            if not im.isNull():
                return im.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        if not bigger:
            src = QImage(self.path)
            if src.isNull():
                self.levels[0] = self._missing()
                return self.levels[0]
            self.levels[0] = src.convertToFormat(QImage.Format_ARGB32_Premultiplied)
            bigger = [0]
        m = max(bigger)
        im = self.levels[m]
        for w, h in self.sizes[m + 1:n + 1]:
            im = im.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        return im


MAX_VECTOR_PX = 4096                  # longest side of the picture a vector node is drawn into


class Renderer:
    def __init__(self, video_frame=None, cache_limit=600):
        """video_frame(path, source_us, w, h) -> QImage or None, for video clips."""
        self.video_frame = video_frame
        self.images = {}            # path -> Mips; (path or asset, size) -> QImage
        self.texts = {}             # (spec json, scale) -> QImage
        self.text_bytes = 0         # what they hold: an animated text makes a new picture every frame
        self.frames = {}            # (spec json, canvas height) -> a 文字框's (w, h)
        self.stills = {}            # (static compound content, scale) -> QImage
        self.cache_limit = cache_limit
        self.errors = []            # clips that could not be drawn, reported by the player
        self._fx = None             # filter engine (an OpenGL context of the thread that renders)
        self._fx_error = None
        self.compounds = {}         # the view's compounds (what compound masks cut with)
        self.matte_preview = None   # {clip, opacity}: show that clip's mask compound over it
        self.editing = False
        self.selected = set()
        self.thumbs = {}            # {effect id: nodegraph.thumb_tap store} of the node effects the editor shows thumbnails of
        self.want_thumbs = set()
        self.thumb_memo = {}        # {effect id: {(node id, output): (signature, thumbnail)}}: pictures of nodes that did not change are not read back again
        self.level = frozenset()    # ids of the tracks a 參考 track shows on (project.level_tracks)
        self._matting = set()       # compounds being drawn as a mask now (one cannot cut itself)
        self.outer = None           # (painter / layer, what is under it) of a 效果穿透 compound's layer
        self.names = {}             # the names expressions read besides their own (the parameter rack)
        self.cache_dir = None       # the project's cache: where the sound a visualizer looks at is decoded to
        self._probe = None

    # -- assets -----------------------------------------------------------------------------------
    def asset(self, p, w, h):
        """A built-in asset with parameters p (assets.at) drawn for about w x h px: at the next
        power of two at or above it, so it stays sharp (as SVG files are)."""
        side = 2 ** max(6, math.ceil(math.log2(max(w, h, 1))))
        text = assets.svg(p, self.editing)
        key = ("asset", text, side, round(assets.fade_distance(p), 3))      # (邊緣淡出 is not in the SVG's text)
        im = self.images.get(key)
        if im is None:
            k = side / max(p["w"], p["h"], 1)
            pad = 2 * assets.overflow(p)                 # (an outline reaching out of its frame)
            size = ((p["w"] + pad) * k, (p["h"] + pad) * k)
            reach = assets.fade_distance(p) * k
            if reach >= 0.5 and p.get("family") not in ("empty", "solid", "gradient"):    # 邊緣淡出: the fill, faded by the distance from the edge, then the outline over it
                im = svgimage.faded(svgimage.raster_text(assets.svg(p, part="fill"), *size),
                                    svgimage.raster_text(assets.svg(p, part="mask"), *size), reach)
                if assets.stroked(p):
                    painter = QPainter(im)
                    painter.drawImage(0, 0, svgimage.raster_text(assets.svg(p, part="stroke"), *size))
                    painter.end()
            else:
                im = svgimage.raster_text(text, *size)
            if len(self.images) >= 48:
                self.images.pop(next(iter(self.images)))
            self.images[key] = im
        return im

    canvas_h = 1080

    def text_source(self, e, nid, src, t, disp, unit, fps):
        """(picture, the source to place it by) of a node effect's text node: the words drawn as a text clip's are, at
        `unit` render px per canvas px, as big as they come out (the source's w / h are what they take up)."""
        node = e["graph"]["nodes"][nid]
        bound = nodegraph.binds(e["graph"])
        spec = textvars.spec_at(nodegraph.text_of(node, nid, e["params"], t, bound, src, e["graph"]), t, TEXT_FIELDS, fps)
        src = nodegraph.placed_by(src, e["params"], bound, nid, t)
        H = self.canvas_h
        em_unit = (spec.get("size") or 1.0) * textlayout.PX_PER_FONT_UNIT * H / 1080
        rs = quantize(max(unit, 1.0 / max(em_unit, 1e-6)))
        pic = self.text(spec, rs, H)
        placed = dict(src, w=pic.width() / rs / max(disp[0], 1e-6), h=pic.height() / rs / max(disp[1], 1e-6))
        return pic, placed

    def shape_source(self, e, nid, src, t, disp, paint=None, linked=(), unit=1.0, fps=30.0):
        """(picture, the source to place it by) of a node effect's shape node made from a built-in shape (assets.py), or
        None for the plain shapes. Drawn at the size of its frame on the clip (so corners and outlines keep their
        thickness), and as much larger as an outline reaching out of the frame needs. linked: the paints ("fill" /
        "stroke") a picture input takes over, left out of the shape; paint: instead the opaque area of one of them.
        A text node (unit: render px per canvas px) gives its words' picture; it has no paints."""
        node = e["graph"]["nodes"].get(nid)
        if node is not None and nodegraph.is_text(node):
            return None if paint else self.text_source(e, nid, src, t, disp, unit, fps)
        if node is None or not nodegraph.is_asset(node):
            return None
        bound = nodegraph.binds(e["graph"])
        q = nodegraph.asset_of(node, nid, e["params"], t, bound)
        src = nodegraph.placed_by(src, e["params"], bound, nid, t)         # (a position / size / turn fed by an effect parameter)
        v = lambda k: curves.value(src.get(k, 1.0), t)
        sw, sh = max(round(v("w") * disp[0], 2), 1), max(round(v("h") * disp[1], 2), 1)
        ratio = v("fit") if "fit" in src else 0.0
        if ratio > 0:                                    # (比例: the shape keeps its proportions inside the frame; 0 stretches it to the frame)
            sw, sh = (round(sh * ratio, 2), sh) if sw / sh > ratio else (sw, round(sw / ratio, 2))
        q["w"], q["h"] = sw, sh
        clear = "#00000000"                              # (hidden paint keeps the outline's reach: the same size for every variant)
        if paint == "fill":
            q.update(fill=True, fill_type="solid", color="#ffffff", stroke_color=clear, stroke_type="solid")
        elif paint == "stroke":
            q.update(fill=False, stroke_type="solid", stroke_color="#ffffff", stroke_on=True)
        else:
            if "fill" in linked:
                q["fill"] = False
            if "stroke" in linked:
                q.update(stroke_color=clear, stroke_type="solid")
        if paint == "stroke" and not assets.stroked(q):
            return None
        reach = 2 * assets.overflow(q)
        placed = dict(src, w=(sw + reach) / max(disp[0], 1e-6), h=(sh + reach) / max(disp[1], 1e-6))
        return self.asset(q, sw, sh), placed

    # -- vector nodes (vector.py) -------------------------------------------------------------------
    OUTLINE_FAMILIES = ("rect", "line", "ellipse", "star", "polygon", "arrow", "parallelogram", "heart")

    def vector_layers(self, e, graph, nid, t, disp, fps, seen=()):
        """The outlines (vector.Layer, canvas px centred on the clip's frame) node nid of effect e's graph gives at clip time t:
        a built-in shape's, a text's, an SVG picture's, or what a vector node makes of the nodes linked into it."""
        node = graph["nodes"].get(nid) or e["graph"]["nodes"].get(nid)
        if node is None or nid in seen:
            return []
        seen += (nid,)
        src = (e.get("sources") or {}).get(nid) or {}
        bound = nodegraph.binds(e["graph"])
        if nodegraph.is_vecop(node):
            links = {l["socket"]: l["from"] for l in graph["links"] if l["to"] == nid}
            groups = [self.vector_layers(e, graph, links[sock], t, disp, fps, seen) for sock in nodegraph.vecop_sockets(node) if sock in links]
            op = nodegraph.vecop_of(node, nid, e["params"], t, bound)
            if op == "move":
                off = curves.value(nodegraph.bound_value(e["params"], bound, nid, "offset", [0.0, 0.0]), t)
                return vector.moved(vector.add(groups), float(off[0]), float(off[1]))
            if op == "scale":
                k = curves.value(nodegraph.bound_value(e["params"], bound, nid, "factor", [1.0, 1.0]), t)
                about = curves.value(nodegraph.bound_value(e["params"], bound, nid, "about", nodegraph.ROTATE_ABOUT[0]), t)
                return vector.scaled(vector.add(groups), float(k[0]), float(k[1]), about == nodegraph.ROTATE_ABOUT[1])
            if op == "rotate":
                angle = curves.value(nodegraph.bound_value(e["params"], bound, nid, "angle", 0.0), t)
                about = curves.value(nodegraph.bound_value(e["params"], bound, nid, "about", nodegraph.ROTATE_ABOUT[0]), t)
                return vector.rotated(vector.add(groups), angle, about == nodegraph.ROTATE_ABOUT[1])
            return vector.add(groups) if op == "add" else vector.combine(op, groups)
        src = nodegraph.placed_by(src, e["params"], bound, nid, t)
        v = lambda k, d=0.0: curves.value(src.get(k, d), t)
        local = QTransform().translate(v("cx") * disp[0] / 2, -v("cy") * disp[1] / 2).rotate(v("rotation"))
        if nodegraph.is_asset(node):
            q = nodegraph.asset_of(node, nid, e["params"], t, bound)
            if q.get("family") not in self.OUTLINE_FAMILIES:
                return []
            sw, sh = max(v("w", 1.0) * disp[0], 1.0), max(v("h", 1.0) * disp[1], 1.0)
            ratio = v("fit") if "fit" in src else 0.0
            if ratio > 0:
                sw, sh = (sh * ratio, sh) if sw / sh > ratio else (sw, sw / ratio)
            path = vector.parse_d(assets.outline_d(q, sw, sh))
            path.translate(-sw / 2, -sh / 2)
            fill = vector.paint_of(q, "fill", sw, sh) if q.get("fill", True) else None
            stroke = vector.paint_of(q, "stroke", sw, sh) if assets.stroked(q) else None
            layer = vector.Layer(path, fill, stroke, float(q.get("stroke", 0.0)) if stroke else 0.0, q.get("join", "miter"),
                                 q.get("stroke_align", "inside"))
            return [layer.mapped(local)]
        if nodegraph.is_text(node):
            spec = textvars.spec_at(nodegraph.text_of(node, nid, e["params"], t, bound, src, e["graph"]), t, TEXT_FIELDS, fps)
            layers = vector.text_layers(spec, self.canvas_h)
            return [l.mapped(local) for l in layers]
        if node.get("type") == nodegraph.SOURCE and node.get("kind") == "image" and svgimage.is_svg(src.get("image")):
            layers, box = vector.load_svg(src["image"])
            if not layers or box.width() <= 0 or box.height() <= 0:
                return []
            sw, sh = max(v("w", 1.0) * disp[0], 1.0), max(v("h", 1.0) * disp[1], 1.0)
            k = min(sw / box.width(), sh / box.height())
            fit = QTransform().scale(k, k).translate(-box.center().x(), -box.center().y())      # (the picture keeps its proportions in its frame)
            return [l.mapped(QTransform(fit.m11(), fit.m12(), fit.m21(), fit.m22(), fit.dx(), fit.dy()) * local) for l in layers]
        return []

    def vector_source(self, e, nid, src, t, disp, unit=1.0, fps=30.0):
        """(picture, the source to place it by) of a vector node of a node effect: its outlines drawn over the whole clip at `unit`
        render px per canvas px (a few thousand px at most)."""
        graph = nodegraph.flatten(e["graph"])
        layers = self.vector_layers(e, graph, nid, t, disp, fps)
        k = min(max(unit, 1e-3), MAX_VECTOR_PX / max(disp[0], disp[1], 1.0))
        pw, ph = max(1, round(disp[0] * k)), max(1, round(disp[1] * k))
        key = ("vector", vector.signature(layers), pw, ph)
        im = self.images.get(key)
        if im is None:
            im = vector.render(layers, pw, ph, k)
            if len(self.images) >= 48:
                self.images.pop(next(iter(self.images)))
            self.images[key] = im
        return im, {"cx": 0.0, "cy": 0.0, "w": 1.0, "h": 1.0, "rotation": 0.0}

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
            levels = Mips(path)
            if len(self.images) >= 48:
                self.images.pop(next(iter(self.images)))
            self.images[path] = levels
        return levels.at(w, h)

    def text(self, spec, scale, canvas_h):
        """textlayout image at `scale` px per layout px; its centre is the text box centre."""
        key = (json.dumps(spec, sort_keys=True, default=str), round(scale, 3), canvas_h, fonts.map_key())
        im = self.texts.get(key)
        if im is None:
            im = QImage(ImageQt(textlayout.render(spec, scale, canvas_h))).convertToFormat(
                QImage.Format_ARGB32_Premultiplied)
            self.texts[key] = im
            self.text_bytes += im.sizeInBytes()
            while self.text_bytes > TEXT_CACHE_BYTES and len(self.texts) > 1 or len(self.texts) > self.cache_limit:
                self.text_bytes -= self.texts.pop(next(iter(self.texts))).sizeInBytes()    # (the oldest goes)
        return im

    def text_disp(self, spec, canvas_h, pic_size, k_size):
        """The size a text's mask and effect ranges are placed in at scale 1 (canvas px), as
        the editor outlines it: its 文字框 when it has one, else pic_size (what is drawn)."""
        if not textlayout.boxed(spec):
            return pic_size
        key = (json.dumps(spec, sort_keys=True, default=str), canvas_h, fonts.map_key())
        if key not in self.frames:
            self._remember(self.frames, key, textlayout.frame_size(spec, canvas_h))
        fw, fh = self.frames[key]
        return fw * k_size, fh * k_size

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
        self.want_thumbs = set(view.get("thumbs") or ()) if view.get("editing") else set()
        self.thumbs = {}
        self.editing = bool(view.get("editing"))            # (the editor's preview: a node effect shows the node picked with 預覽)
        self.selected = set(view.get("selected") or ())     # (the clips picked on the timeline: an 空物體 shows while it is)
        self.level = project.level_tracks(view)
        self.canvas_h = view.get("height") or 1080          # (a text node's size is in px of a 1080-high canvas, as a text clip's)

    track_ctx = None                    # (tracks, W, H, time) of the level being drawn: what 軌道 sources read

    def viz_picture(self, c, t, tw, th):
        """An Audio Visualizer clip's picture (viz.py) at clip time t, tw x th pixels."""
        if self._probe is None and self.cache_dir:
            self._probe = viz.Probe(self.cache_dir)
        tracks = self.track_ctx[0] if self.track_ctx else None
        return viz.paint(c["viz"], self._probe, c, t, max(1, round(tw)), max(1, round(th)), c["media"]["height"],
                         self.compounds, tracks)

    def matte_compound(self, mask, t=0):
        """What a picture mask cuts with: the compound of a compound mask, or for an image mask
        {image, width, height}; None when it is not one, has none (chosen, deleted, a file that
        is gone) or that compound is being drawn as a mask already."""
        kind = curves.value(mask.get("kind"), t) if mask else None
        if kind == "image":
            path, w, h = mask.get("image"), mask.get("img_w"), mask.get("img_h")
            return {"image": path, "width": w, "height": h} if path and w and h else None
        if kind == "video":
            path, w, h = mask.get("video"), mask.get("vid_w"), mask.get("vid_h")
            return ({"video": path, "width": w, "height": h, "duration_us": mask.get("vid_dur") or 0}
                    if path and w and h else None)
        if kind == "track":                              # 軌道: that track of this level, at this moment
            tracks, W, H, t_us = self.track_ctx or ((), 0, 0, 0)
            tid = mask.get("track_id")
            tr = next((x for x in project.all_tracks(tracks) if x["id"] == tid), None)
            if tr is None or "track:" + str(tid) in self._matting or not W:
                return None
            return {"width": W, "height": H, "tracks": [tr], "level_t": t_us, "track_id": tid}
        if kind != "compound":
            return None
        kid = mask.get("compound_id")
        return None if kid in self._matting else self.compounds.get(kid)

    def clip_mask(self, c, t):
        """The mask that cuts clip c now (None: none, off, or a picture mask without its picture)."""
        m = project.active_mask(c)
        if m and curves.value(m.get("kind"), t) in ("compound", "image", "video", "track") and self.matte_compound(m, t) is None:
            return None
        return m

    def matte_k(self, mask, t, disp, comp, world):
        """Px per compound unit for a mask's compound to be as sharp as it shows through world."""
        kd = math.sqrt(abs(world.determinant())) or 1.0
        return max(curves.value(mask.get("w", 1.0), t) * disp[0], 1.0) * kd / comp["width"]

    def matte_image(self, mask, comp, t, k, fps):
        """A mask's compound drawn at k px per compound unit: a static one's still, else its
        frame at clip time t + t_off (held at its first / last frame); an image mask's picture;
        a video mask's frame at clip time t + t_off (a white one while it cannot be had)."""
        if comp.get("image"):
            return self.image(comp["image"], comp["width"] * k, comp["height"] * k)
        if comp.get("video"):
            w, h = max(1, round(comp["width"] * k)), max(1, round(comp["height"] * k))
            pic = self.video_frame(comp["video"], matte_time(comp, t + mask.get("t_off", 0), fps), w, h) \
                if self.video_frame else None
            if pic is None:
                pic = QImage(1, 1, QImage.Format_ARGB32_Premultiplied)
                pic.fill(QColor("white"))
            return pic
        if comp.get("level_t") is not None:              # 軌道: the track drawn alone, at the level's moment
            key = "track:" + str(comp["track_id"])
            self._matting.add(key)
            try:
                cw, ch = comp["width"], comp["height"]
                k = min(k, self.MATTE_MAX_PX / max(cw, ch))
                im = QImage(max(1, math.ceil(cw * k)), max(1, math.ceil(ch * k)), QImage.Format_ARGB32_Premultiplied)
                im.fill(Qt.transparent)
                lp = QPainter(im)
                lp.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
                lp.scale(k, k)
                self.draw_tracks(lp, comp["tracks"], cw, ch, fps, comp["level_t"], k)
                lp.end()
                return im
            finally:
                self._matting.discard(key)
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
    def render(self, view, frame, width, height, alpha=False, margin=0.0):
        """RGB frame `frame` of a project-like view, drawn at width x height; on a transparent
        background instead of black with alpha (transparent exports). margin: the picture is
        given that fraction of width / height more on every side, the canvas in the middle
        (what lies outside the canvas, for the preview)."""
        mx, my = round(width * margin), round(height * margin)
        img = QImage(width + 2 * mx, height + 2 * my, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent if alpha else QColor("black"))
        p = QPainter(img)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        p.translate(mx, my)
        p.scale(width / view["width"], height / view["height"])
        self.begin(view)
        self.names = rack.values(view, frame / view["fps"] * US)
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
        tracks = project.matte_tracks(comp["tracks"])
        a = project.anchor_of(comp, t_us) if comp.get("group") else None
        shift = (a[1] * W / 2, -a[2] * H / 2) if a else (0.0, 0.0)      # (中心點跟隨最下層物件)
        if not matte.get("on") or len(tracks) < 2 or not isinstance(p.device(), QImage):
            i = next(i for i, t in enumerate(comp["tracks"]) if t is a[0]) + 1 if a else len(comp["tracks"])
            self.draw_tracks(p, comp["tracks"][:i], W, H, fps, t_us, px_per_unit)
            if a:
                p.save()
                p.translate(*shift)
                self.draw_tracks(p, comp["tracks"][i:], W, H, fps, t_us, px_per_unit)
                p.restore()
            return
        dev = p.device()

        def layer(trs, under=None, moved=False):
            if under is None:
                im = QImage(dev.width(), dev.height(), QImage.Format_ARGB32_Premultiplied)
                im.fill(Qt.transparent)
            else:
                im = under.copy()
            lp = QPainter(im)
            lp.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
            lp.setTransform(p.worldTransform())
            if moved:
                lp.translate(*shift)
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
            above = layer(tracks[1:], under, moved=True)
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

    def seen(self, p, img):
        """img (a copy of what p's device has) as 套用至背景 and filter clips see it: over what is
        under the compound clip when p draws that 效果穿透 compound's layer (self.outer)."""
        if not (self.outer and self.outer[0] is p):
            return img
        out = self.outer[1].copy()
        q = QPainter(out)
        q.drawImage(0, 0, img)
        q.end()
        return out

    def draw_tracks(self, p, tracks, W, H, fps, t_us, px_per_unit):
        """Draw every visible clip at time t_us (us) on a W x H canvas, bottom track first."""
        outer, self.track_ctx = self.track_ctx, (tracks, W, H, t_us)     # (what a 軌道 source reads)
        try:
            self._draw_tracks(p, tracks, W, H, fps, t_us, px_per_unit)
        finally:
            self.track_ctx = outer

    def _draw_tracks(self, p, tracks, W, H, fps, t_us, px_per_unit):
        for i, tr in enumerate(tracks):
            if tr["kind"] == "audio" or not project.visible(tr, self.level):
                continue
            for c in tr["clips"]:
                if on_frame(c, t_us, fps):
                    try:
                        times = project.shutter_times(c, t_us, fps) if isinstance(p.device(), QImage) else None
                        if times:
                            self.draw_blurred(p, c, times, W, H, fps, px_per_unit)
                            continue
                        c = propexpr.at(c, t_us - c["start_us"], self.names)
                        if c["type"] == "filter":
                            self.draw_filter_clip(p, c, W, H, fps, t_us, px_per_unit, tracks[:i])
                        else:
                            self.draw_clip(p, c, W, H, fps, t_us, px_per_unit)
                    except Exception as exc:          # one bad clip must not blank the preview
                        self.errors.append(f"{c.get('name') or c['type']}: {exc}")

    def draw_blurred(self, p, c, times, W, H, fps, px_per_unit):
        """動態模糊: clip c drawn as it is at each of times (project.shutter_times) on a clear layer
        the size of p's, and their average put on p in the clip's blend mode; when the first and
        the last drawing are the same nothing moves, and that one is the picture."""
        dev = p.device()
        plain = dict(c, blend="normal")
        acc = pic = None
        for i, u in enumerate([times[0], times[-1]] + times[1:-1]):
            layer = QImage(dev.width(), dev.height(), QImage.Format_ARGB32_Premultiplied)
            layer.fill(Qt.transparent)
            lp = QPainter(layer)
            lp.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
            lp.setTransform(p.worldTransform())
            try:
                self.draw_clip(lp, propexpr.at(plain, u - c["start_us"], self.names), W, H, fps, u, px_per_unit)
            finally:
                lp.end()
            arr = image_to_array(layer)
            if acc is None:
                acc, pic = arr.astype(np.float32), layer
                continue
            if i == 1 and np.array_equal(arr, acc):
                break
            acc += arr
            pic = None
        if pic is None:
            pic = array_to_image((acc / len(times)).round().clip(0, 255).astype(np.uint8))
        p.save()
        p.resetTransform()
        p.setCompositionMode(BLEND_OPS.get(curves.value(c.get("blend", "normal"), project.stepped(c, times[len(times) // 2]
                                                                                                    - c["start_us"])),
                                           QPainter.CompositionMode_SourceOver))
        p.drawImage(0, 0, pic)
        p.restore()

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
            animated = any(curves.is_animated(tx.get(k)) for k in TEXT_FIELDS if k != "size") or textvars.animated(tx) or (
                textlayout.boxed(tx) and curves.is_animated(size))      # (a 文字框 does not grow with the words)
            if animated:
                spec, k_size = textvars.spec_at(tx, t, TEXT_FIELDS, fps), 1.0
            else:
                ref = curves.max_abs(size) or 1.0
                spec = textvars.spec_at(tx, t, TEXT_FIELDS, fps)
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
            disp = self.text_disp(spec, H, (bw, bh), k_size)
        elif kind in ("image", "video"):
            m = c["media"]
            bw, bh = project.picture_size(c, W, H, t=t)
            tw, th = bw * abs(sx) * px_per_unit, bh * abs(sy) * px_per_unit
            rect = QRectF(-bw / 2, -bh / 2, bw, bh)
            if c.get("asset"):                       # drawn from its parameters at t
                q = assets.at(c["asset"], t)
                if q.get("family") == "empty" and not backdrop and not (self.editing and c["id"] in self.selected):
                    return                           # 空物體: nothing to see (its effects too); the preview's box shows it while it is selected
                pic = self.asset(q, tw, th)
                rect = asset_rect(q, bw, bh)
                if backdrop:
                    shape = self.asset(assets.cover(q), tw, th)
                    cover = lambda qq=p: qq.drawImage(rect, shape)
            elif c.get("viz"):                       # drawn from the sound at t (viz.py)
                pic = self.viz_picture(c, t, tw, th)
            elif kind == "image":
                pl = c.get("place") or {}
                pic = self.image(m["path"], tw * pl.get("w", 1.0), th * pl.get("h", 1.0))
            else:
                pic = self.video_frame(m["path"], project.source_time(c, t),
                                       max(1, round(tw)), max(1, round(th))) if self.video_frame else None
                if pic is None:
                    return
            rect = placed(rect, c.get("place"), bw, bh)
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
            # 效果穿透: what is under it now, for its clips that work on what is under them
            under = self.seen(p, p.device().copy().convertToFormat(QImage.Format_ARGB32_Premultiplied)) \
                if kind == "compound" and isinstance(p.device(), QImage) and project.passes_through(c) else None
            if comp.get("static") and under is None:
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
                vis = vis.adjusted(-pad, -pad, pad, pad)
                if kind != "group":                    # a group only gathers its clips: what reaches past the
                    vis = vis.intersected(full)        # canvas still shows where the group takes it
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
                outer = self.outer
                if under is not None:                  # (q's device is the size of p's, through the same world)
                    seen = QImage(layer.size(), QImage.Format_ARGB32_Premultiplied)
                    seen.fill(Qt.transparent)
                    up = QPainter(seen)
                    up.setRenderHints(QPainter.SmoothPixmapTransform)
                    up.setTransform(inv * QTransform.fromTranslate(-vis.left(), -vis.top()) * QTransform.fromScale(k / fit, k / fit))
                    up.drawImage(0, 0, under)
                    up.end()
                    self.outer = (lp, seen)
                try:
                    self.draw_content(lp, comp, cw, ch, fps, t if kind == "group" else 0 if comp.get("static")
                                      else project.source_time(c, t), k)
                finally:
                    self.outer = outer
                lp.end()
                q.drawImage(QRectF(vis.left(), vis.top(), layer.width() / k * fit, layer.height() / k * fit), layer)
            draw = draw or draw_live
            disp = (bw, bh)
        else:
            return
        radii = project.corner_radii(c, t, disp, H)
        if radii:                                          # 圓角: the picture cut round, before its effects
            square = draw

            def draw(q=p):
                q.save()
                q.setClipPath(rounded_path(disp, radii), Qt.IntersectClip)
                square(q)
                q.restore()
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
        p.translate(*project.centre_px(tf, t, W, H))       # (中心點: about its pivot)
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
        out = self.run_effects(c["effects"], self.seen(p, base), t, c["duration_us"], fps,
                               clip_world(c, t, W, H) * p.worldTransform(), disp, unit)
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

    def thumb_tap(self, e):
        return (nodegraph.thumb_tap(self.thumbs.setdefault(e["id"], {}), memo=self.thumb_memo.setdefault(e["id"], {}))
                if e["id"] in self.want_thumbs else None)

    def graph_effect(self, eng, e, arr, t, duration, fps, disp, wt, unit):
        """Node graph effect e over arr (H x W x 4, premultiplied) on the CPU renderer's engine: the
        result as such an array, or None when it cannot run."""
        h, w = arr.shape[:2]
        sources = e.get("sources") or {}
        pool = nodegraph.Pool(eng)
        texs = []
        with eng.ctx:
            def upload(a):
                tex = eng.ctx.texture((a.shape[1], a.shape[0]), 4, np.ascontiguousarray(a).tobytes())
                tex.filter = (eng.mgl.LINEAR, eng.mgl.LINEAR)
                tex.repeat_x = tex.repeat_y = False
                texs.append(tex)
                return tex

            def picture(nid, paint=None, linked=()):
                src = sources.get(nid)
                if src and src.get("kind") == nodegraph.VECTOR:
                    pic, placed = self.vector_source(e, nid, src, t, disp, unit, fps)
                    return upload(image_to_array(pic)), source_map(placed, t, disp, wt, w, h), None
                if src and src.get("kind") in ("shape", "text"):
                    got = self.shape_source(e, nid, src, t, disp, paint, linked, unit, fps)
                    if got is None and paint:
                        return None
                    pic, placed = got or (nodegraph.shape_image(src), src)
                    return upload(image_to_array(pic)), source_map(placed, t, disp, wt, w, h), None
                comp = self.matte_compound(src, t) if src else None
                if comp is None:
                    return None
                pic = self.matte_image(src, comp, t, self.matte_k(src, t, disp, comp, wt), fps)
                return upload(image_to_array(pic)), source_map(src, t, disp, wt, w, h), None
            errors = []
            try:
                tex, owner = nodegraph.evaluate(eng, e["graph"], e["params"], upload(arr), w, h, pool.alloc, pool.free,
                                                t=t, duration=duration, fps=fps, unit=unit, picture=picture, errors=errors,
                                                viewer=self.editing, tap=self.thumb_tap(e), overscan=e.get("overscan", "auto"))
                out = nodegraph.read_rgba8(tex).copy() if tex is not None else None
            except nodegraph.GraphError as exc:
                self.errors.append(f"節點效果：{exc}")
                out = None
            finally:
                for tex in texs:
                    tex.release()
                pool.close()
        self.errors += errors
        return out

    def run_effects(self, effects, img, t, duration, fps, wt, disp, unit):
        """Apply a chain of effects to img (QImage ARGB32 premultiplied, unit of its px per canvas
        px) at clip time t; each effect's own mask (clip-local, through world transform wt)
        limits where it shows, its 混合程度 how much."""
        todo = [e for e in effects if not e.get("disabled") and e.get("filter") not in project.PLACE_FILTERS]
        eng = self.engine() if todo else None
        if eng is None:
            return img
        arr = image_to_array(img)
        for e in todo:
            amount = fx.mix_at(e, t)
            if amount <= 0:
                continue
            d = fx.get(e["filter"])
            if e["filter"] == fx.GRAPH:                                  # a node graph (nodegraph.py)
                out = self.graph_effect(eng, e, arr, t, duration, fps, disp, wt, unit)
                if out is None:
                    continue
                mk = e.get("mask")
                if mk or amount < 1:
                    h, w = arr.shape[:2]
                    m = coverage(mk, t, disp, wt, w, h, curves.value(mk.get("feather", 0.0), t))[..., None] * amount \
                        if mk else amount
                    out = (arr * (1 - m) + out * m).round().astype(np.uint8)
                arr = np.ascontiguousarray(out)
                continue
            vals = {p.name: fx.uniform_value(p, e["params"].get(p.name), t) for p in d.params}
            h, w = arr.shape[:2]
            sources = {}
            for name, src in (e.get("sources") or {}).items():           # colours read from a picture
                comp = self.matte_compound(src, t)
                if comp is not None:
                    pic = self.matte_image(src, comp, t, self.matte_k(src, t, disp, comp, wt), fps)
                    sources[name] = (image_to_array(pic), source_map(src, t, disp, wt, w, h))
                    if any(q.name == name and q.type == "float" for q in d.params):
                        vals[name + fx.RANGE_MIN], vals[name + fx.RANGE_MAX] = fx.source_range(src, vals.get(name, 0.0), t)
            try:
                out = eng.run(d, vals, arr, time=t / US, progress=min(1.0, max(0.0, t / max(1, duration))),
                              frame=max(0, round(t * fps / US)), unit=unit, sources=sources)
            except fx.FilterError as exc:
                self.errors.append(f"濾鏡「{d.name}」：{exc}")
                continue
            mk = e.get("mask")
            if mk or amount < 1:
                h, w = arr.shape[:2]
                m = coverage(mk, t, disp, wt, w, h, curves.value(mk.get("feather", 0.0), t))[..., None] * amount \
                    if mk else amount
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

    def draw_filter_clip(self, p, c, W, H, fps, t_us, px_per_unit, below=None):
        """A filter clip: what has been drawn so far (the tracks below) goes through its
        effects, inside its mask and at its opacity. With 凍結 / 降低幀數 the tracks below
        (below) are drawn again at the moment it holds them to, and that goes through instead."""
        tf = c.get("transform") or {}
        t = t_us - c["start_us"]
        v = lambda k, d: curves.value(tf.get(k, d), t)
        strength = min(1.0, max(0.0, v("opacity", 1.0)))
        held = project.stepped(c, t)
        timed = below is not None and held != t
        if strength <= 0 or not (project.visual_effects(c) or timed):
            return
        dev = p.device()
        w, h = dev.width(), dev.height()
        p.save()
        p.translate(*project.centre_px(tf, t, W, H))
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
        under = base
        if timed:                                          # what is under it as it was at the held moment
            under = QImage(base.size(), QImage.Format_ARGB32_Premultiplied)
            under.fill(Qt.transparent)
            hp = QPainter(under)
            hp.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
            hp.setTransform(p.worldTransform())
            self.draw_tracks(hp, below, W, H, fps, c["start_us"] + held, px_per_unit)
            hp.end()
            t = held
        out = self.run_effects(c["effects"], self.seen(p, under), t, c["duration_us"], fps, wt, (W, H), px_per_unit)
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


def source_map(src, t, disp, world, w, h):
    """The 3 x 3 matrix (9 numbers, by columns) from the uv of a w x h layer that world maps a
    clip's frame onto, to the uv of an effect's colour source placed in that frame as a mask is
    (cx / cy in half-material units, y up; w / h fractions of the material disp; rotation)."""
    v = lambda k, d: curves.value(src.get(k, d), t)
    sw, sh = max(v("w", 1.0) * disp[0], 1e-6), max(v("h", 1.0) * disp[1], 1e-6)
    inv, _ = world.inverted()
    local = QTransform().translate(v("cx", 0.0) * disp[0] / 2, -v("cy", 0.0) * disp[1] / 2).rotate(v("rotation", 0.0))
    linv, _ = local.inverted()
    m = QTransform.fromScale(w, h) * inv * linv * QTransform.fromScale(1 / sw, 1 / sh) * QTransform.fromTranslate(0.5, 0.5)
    return (m.m11(), m.m12(), m.m13(), m.m21(), m.m22(), m.m23(), m.m31(), m.m32(), m.m33())


def placed(rect, place, bw, bh):
    """rect (a picture in its bw x bh frame, centred on 0) where a component's image parameter
    puts it (components.PLACE: centre in half-frame units, y up; size as fractions)."""
    if not place:
        return rect
    w, h = place.get("w", 1.0), place.get("h", 1.0)
    cx, cy = place.get("cx", 0.0) * bw / 2, -place.get("cy", 0.0) * bh / 2
    return QRectF(rect.left() * w + cx, rect.top() * h + cy, rect.width() * w, rect.height() * h)


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


def rounded_path(disp, radii):
    """A (w, h) frame round its centre with corners (top left, top right, bottom right, bottom
    left) of these radii, as a QPainterPath (y down)."""
    w, h = disp
    tl, tr, br, bl = radii
    x0, y0, x1, y1 = -w / 2, -h / 2, w / 2, h / 2
    path = QPainterPath()
    path.moveTo(x0 + tl, y0)
    path.lineTo(x1 - tr, y0)
    path.arcTo(x1 - 2 * tr, y0, 2 * tr, 2 * tr, 90, -90)
    path.lineTo(x1, y1 - br)
    path.arcTo(x1 - 2 * br, y1 - 2 * br, 2 * br, 2 * br, 0, -90)
    path.lineTo(x0 + bl, y1)
    path.arcTo(x0, y1 - 2 * bl, 2 * bl, 2 * bl, 270, -90)
    path.lineTo(x0, y0 + tl)
    path.arcTo(x0, y0, 2 * tl, 2 * tl, 180, -90)
    path.closeSubpath()
    return path


def group_content(g, W, H):
    """A group as compound-like content: its tracks on a canvas the size of its level."""
    return {"width": W, "height": H, "tracks": g["tracks"], "group": True, "matte": g.get("matte"),
            "anchor": g.get("anchor"), "duration_us": g["duration_us"]}


def clip_world(c, t, W, H):
    """Clip space (centre origin, y down) -> canvas, as draw_clip places a clip at clip time t."""
    tf = c.get("transform") or {}
    v = lambda k, d: curves.value(tf.get(k, d), t)
    return QTransform().translate(*project.centre_px(tf, t, W, H)).rotate(v("rotation", 0.0)) \
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
