"""GPU compositor: the live renderer's pictures (render.py), put together with OpenGL.

render.Renderer paints every layer with QPainter on the CPU and copies whole frames between
Qt, numpy and the filter engine. This one keeps the frame on the graphics card: pictures,
texts and video frames become textures; each clip is one quad drawn with its transform, and
its opacity, anti-aliased edges, mask (feather included) and blend mode are worked out per
pixel in a shader; compounds and static clips are drawn into layers; filters (fx.py) run on
those layers without leaving the card. Only the finished frame is read back.

The rules are render.py's (same clip order, sizes, transforms, mask geometry - masks.alpha -
and text / picture / video choices); tests/test_glrender.py compares the two frame by frame.
make() gives a GLRenderer, or the CPU Renderer when OpenGL 3.3 is not available.

Coordinates: device pixels with y down everywhere; textures hold their first row (the top)
at v = 0 and frame buffers are read back first row first, so nothing is ever flipped.
"""
import json
import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QImage, QTransform

from . import assets, curves, fx, project, render, textlayout
from .render import TEXT_FIELDS, US, quantize

BLEND_INDEX = {"normal": 0, "multiply": 1, "screen": 2, "overlay": 3, "darken": 4, "lighten": 5,
               "color_dodge": 6, "color_burn": 7, "hard_light": 8, "soft_light": 9, "difference": 10,
               "exclusion": 11, "add": 12}
MASK_INDEX = {"line": 1, "mirror": 2, "circle": 3, "rectangle": 4, "compound": 5, "image": 5}
MAX_LAYER = 8192
TEX_CACHE = 160

VERTEX = """#version 330
uniform vec2 size;
in vec2 pos;                                  // device px
void main() { gl_Position = vec4(pos / size * 2.0 - 1.0, 0.0, 1.0); }
"""

MASK_GLSL = """
uniform int mkind;           // 0: no mask; 1 line, 2 mirror, 3 circle, 4 rectangle (masks.alpha),
                             // 5 a compound's picture (mtex) over the w x h frame
uniform int minvert;
uniform mat3 dev_mask;       // device px -> mask space (origin at its centre, y up)
uniform vec2 mwh;            // mask width / height in clip units
uniform float msoft;         // feather half-width in clip units (at least half a device pixel)
uniform sampler2D mtex;      // kind 5: the compound's picture (premultiplied)
uniform int mluma;           // kind 5: its brightness lets the clip through, not its alpha
float mask_at(vec2 p) {
    if (mkind == 0) return 1.0;
    vec2 m = (dev_mask * vec3(p, 1.0)).xy;
    if (mkind == 5) {
        vec2 uv = vec2(m.x / mwh.x + 0.5, 0.5 - m.y / mwh.y);
        float c = 0.0;
        if (uv.x >= 0.0 && uv.x < 1.0 && uv.y >= 0.0 && uv.y < 1.0) {
            vec4 s = texture(mtex, uv);
            c = mluma == 1 ? dot(s.rgb, vec3(0.2126, 0.7152, 0.0722)) : s.a;
        }
        return minvert == 1 ? 1.0 - c : c;
    }
    float d;
    if (mkind == 1) d = m.y;
    else if (mkind == 2) d = mwh.y / 2.0 - abs(m.y);
    else if (mkind == 3) {
        vec2 r = max(mwh / 2.0, vec2(1e-6));
        d = (1.0 - length(m / r)) * min(r.x, r.y);
    } else d = min(mwh.x / 2.0 - abs(m.x), mwh.y / 2.0 - abs(m.y));
    vec2 fw = fwidth(m);
    float soft = max(msoft, 0.5 * max(fw.x, fw.y));
    float a = clamp(d / (2.0 * soft) + 0.5, 0.0, 1.0);
    return minvert == 1 ? 1.0 - a : a;
}
"""

COMPOSITE = """#version 330
uniform vec2 size;
uniform sampler2D tex;
uniform mat3 dev_uv;         // device px -> texture uv
uniform int straight;        // the texture holds straight (not premultiplied) alpha
uniform int edge;            // soften the picture's own border (a quad, not a whole layer)
uniform float opacity;
uniform int blend;           // 0 normal (GL blending does it), else BLEND_INDEX
uniform sampler2D backdrop;  // what was there, for the other blend modes
%(mask)s
out vec4 frag;

float soft_light_d(float cb) {
    return cb <= 0.25 ? ((16.0 * cb - 12.0) * cb + 4.0) * cb : sqrt(cb);
}
float mix1(int mode, float cs, float cb) {
    if (mode == 1) return cs * cb;
    if (mode == 2) return cs + cb - cs * cb;
    if (mode == 3) return cb <= 0.5 ? 2.0 * cs * cb : 1.0 - 2.0 * (1.0 - cs) * (1.0 - cb);
    if (mode == 4) return min(cs, cb);
    if (mode == 5) return max(cs, cb);
    if (mode == 6) return cb <= 0.0 ? 0.0 : (cs >= 1.0 ? 1.0 : min(1.0, cb / (1.0 - cs)));
    if (mode == 7) return cb >= 1.0 ? 1.0 : (cs <= 0.0 ? 0.0 : 1.0 - min(1.0, (1.0 - cb) / cs));
    if (mode == 8) return cs <= 0.5 ? 2.0 * cs * cb : 1.0 - 2.0 * (1.0 - cs) * (1.0 - cb);
    if (mode == 9) return cs <= 0.5 ? cb - (1.0 - 2.0 * cs) * cb * (1.0 - cb)
                                    : cb + (2.0 * cs - 1.0) * (soft_light_d(cb) - cb);
    if (mode == 10) return abs(cs - cb);
    if (mode == 11) return cs + cb - 2.0 * cs * cb;
    return cs;
}
vec4 blended(int mode, vec4 s, vec4 b) {
    if (mode == 12) return min(s + b, vec4(1.0));
    vec3 cs = s.a > 0.0 ? s.rgb / s.a : vec3(0.0);
    vec3 cb = b.a > 0.0 ? b.rgb / b.a : vec3(0.0);
    vec3 m = vec3(mix1(mode, cs.r, cb.r), mix1(mode, cs.g, cb.g), mix1(mode, cs.b, cb.b));
    return vec4(s.rgb * (1.0 - b.a) + b.rgb * (1.0 - s.a) + s.a * b.a * m, s.a + b.a - s.a * b.a);
}

void main() {
    vec2 p = gl_FragCoord.xy;
    vec2 uv = (dev_uv * vec3(p, 1.0)).xy;
    vec4 c = texture(tex, uv);
    if (straight == 1) c.rgb *= c.a;
    float a = opacity * mask_at(p);
    if (edge == 1) {
        vec2 fw = max(fwidth(uv), vec2(1e-7));
        vec2 e = min(uv, 1.0 - uv) / fw;
        a *= clamp(e.x + 0.5, 0.0, 1.0) * clamp(e.y + 0.5, 0.0, 1.0);
    }
    c *= a;
    frag = blend == 0 ? c : blended(blend, c, texture(backdrop, p / size));
}
""" % {"mask": MASK_GLSL}

MIX = """#version 330
uniform vec2 size;
uniform sampler2D a_tex;     // before
uniform sampler2D b_tex;     // after (filtered)
uniform float strength;
%(mask)s
out vec4 frag;
void main() {
    vec2 p = gl_FragCoord.xy;
    frag = mix(texture(a_tex, p / size), texture(b_tex, p / size), strength * mask_at(p));
}
""" % {"mask": MASK_GLSL}


MIX_COVER = """#version 330
uniform vec2 size;
uniform sampler2D a_tex;     // before
uniform sampler2D b_tex;     // after (filtered)
uniform sampler2D c_tex;     // the clip as it shows: its alpha says where b goes (套用至背景)
out vec4 frag;
void main() {
    vec2 uv = gl_FragCoord.xy / size;
    frag = mix(texture(a_tex, uv), texture(b_tex, uv), texture(c_tex, uv).a);
}
"""


def mat3(t):
    """A QTransform as a GLSL mat3 (column first)."""
    return (t.m11(), t.m12(), 0.0, t.m21(), t.m22(), 0.0, t.dx(), t.dy(), 1.0)


def rect_uv(r):
    """Clip-space rect (QRectF) -> texture uv."""
    return QTransform(1 / r.width(), 0, 0, 1 / r.height(), -r.left() / r.width(), -r.top() / r.height())


def mask_frame(mask, t, disp):
    """Clip space (centre origin, y down) -> mask space (centre origin, y up), as render.coverage."""
    v = lambda k, d: curves.value(mask.get(k, d), t)
    dw, dh = disp
    b = math.radians(v("rotation", 0.0))
    move = QTransform.fromTranslate(-v("cx", 0.0) * dw / 2, v("cy", 0.0) * dh / 2)
    turn = QTransform(math.cos(b), math.sin(b), math.sin(b), -math.cos(b), 0, 0)
    return move * turn


class Picture:
    """A texture where a layer is expected (an image mask's picture: never given back)."""

    def __init__(self, tex):
        self.tex = tex


class Layer:
    def __init__(self, gl, w, h):
        self.w, self.h = w, h
        self.tex = gl.ctx.texture((w, h), 4)
        self.tex.filter = (gl.mgl.LINEAR, gl.mgl.LINEAR)
        self.tex.repeat_x = self.tex.repeat_y = False
        self.fbo = gl.ctx.framebuffer(color_attachments=[self.tex])

    def release(self):
        self.fbo.release()
        self.tex.release()


class GL:
    """The OpenGL side: a context of this thread, the two programs, textures and layers."""

    def __init__(self):
        self.mgl, self.ctx = fx.make_context()
        mgl, ctx = self.mgl, self.ctx
        self.composite = ctx.program(vertex_shader=VERTEX, fragment_shader=COMPOSITE)
        self.mixer = ctx.program(vertex_shader=VERTEX, fragment_shader=MIX)
        self.coverer = ctx.program(vertex_shader=VERTEX, fragment_shader=MIX_COVER)
        self.vbo = ctx.buffer(reserve=4 * 2 * 4, dynamic=True)
        self.vao = {id(p): ctx.vertex_array(p, [(self.vbo, "2f", "pos")])
                    for p in (self.composite, self.mixer, self.coverer)}
        self.fx = fx.Engine(mgl, ctx)
        self.textures = {}              # QImage cacheKey -> texture (pictures, texts)
        self.moving = {}                # (w, h) -> [texture], reused every frame (video frames)
        self.moving_used = {}
        self.free = {}                  # (w, h) -> [Layer]
        self.backdrops = {}             # (w, h) -> Layer
        self.matte = None               # texture of the compound mask about to be drawn with (unit 2)

    # -- textures and layers --------------------------------------------------------------------
    def _upload(self, tex, img):
        fmt = img.format()
        if fmt in (QImage.Format_RGBA8888, QImage.Format_RGBA8888_Premultiplied):
            tex.swizzle = "RGBA"
        else:
            if fmt not in (QImage.Format_ARGB32_Premultiplied, QImage.Format_ARGB32):
                img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
            tex.swizzle = "BGRA"                     # ARGB32 is B, G, R, A in memory
        tex.write(bytes(img.constBits())[: img.width() * img.height() * 4])
        return img.format() in (QImage.Format_RGBA8888, QImage.Format_ARGB32)    # straight alpha?

    def picture(self, img, mipmap=False):
        """(texture, straight alpha) of a QImage that stays the same (pictures, texts)."""
        key = (img.cacheKey(), mipmap)
        hit = self.textures.pop(key, None)
        if hit is None:
            tex = self.ctx.texture((img.width(), img.height()), 4)
            straight = self._upload(tex, img)
            tex.repeat_x = tex.repeat_y = False
            if mipmap:
                tex.build_mipmaps()
                tex.filter = (self.mgl.LINEAR_MIPMAP_LINEAR, self.mgl.LINEAR)
            else:
                tex.filter = (self.mgl.LINEAR, self.mgl.LINEAR)
            hit = (tex, straight)
            while len(self.textures) >= TEX_CACHE:
                old = self.textures.pop(next(iter(self.textures)))
                old[0].release()
        self.textures[key] = hit                      # (most recently used last)
        return hit

    def frame_texture(self, img):
        """(texture, straight alpha) for a picture used once (a video frame): textures of each
        size are reused from frame to frame."""
        size = (img.width(), img.height())
        pool = self.moving.setdefault(size, [])
        n = self.moving_used.get(size, 0)
        if n >= len(pool):
            tex = self.ctx.texture(size, 4)
            tex.filter = (self.mgl.LINEAR, self.mgl.LINEAR)
            tex.repeat_x = tex.repeat_y = False
            pool.append(tex)
        self.moving_used[size] = n + 1
        tex = pool[n]
        return tex, self._upload(tex, img)

    def new_frame(self):
        self.moving_used.clear()

    def layer(self, w, h, clear=(0.0, 0.0, 0.0, 0.0)):
        pool = self.free.get((w, h))
        lay = pool.pop() if pool else Layer(self, w, h)
        lay.fbo.clear(*clear)
        return lay

    def release(self, lay):
        self.free.setdefault((lay.w, lay.h), []).append(lay)

    def backdrop(self, tgt):
        """A copy of what tgt shows now (the other blend modes read it)."""
        b = self.backdrops.get((tgt.w, tgt.h))
        if b is None:
            b = self.backdrops[(tgt.w, tgt.h)] = Layer(self, tgt.w, tgt.h)
        self.ctx.copy_framebuffer(b.tex, tgt.fbo)
        return b

    # -- drawing ----------------------------------------------------------------------------------
    def _mask_uniforms(self, prog, mask, t, disp, inv_world):
        if mask is None:
            prog["mkind"].value = 0
            return
        v = lambda k, d: curves.value(mask.get(k, d), t)
        kind = MASK_INDEX.get(v("kind", "rectangle"), 4)
        if kind == 5 and self.matte is None:             # (no picture to cut with: cut nothing)
            prog["mkind"].value = 0
            return
        prog["mkind"].value = kind
        prog["minvert"].value = 1 if v("invert", False) else 0
        prog["dev_mask"].value = mat3(inv_world * mask_frame(mask, t, disp))
        w, h = v("w", 1.0) * disp[0], v("h", 1.0) * disp[1]
        prog["mwh"].value = (max(w, 1e-6), max(h, 1e-6))
        feather = v("feather", 0.0)
        prog["msoft"].value = feather * min(w, h) / 2 if feather > 1e-3 and kind != 5 else 0.0
        if kind == 5:
            self.matte.use(2)
            prog["mtex"].value = 2
            prog["mluma"].value = 1 if v("matte", "alpha") == "luma" else 0

    def _quad(self, tgt, pts):
        self.vbo.write(np.array([c for q in pts for c in (q.x(), q.y())], "f4").tobytes())
        tgt.fbo.use()
        self.ctx.viewport = (0, 0, tgt.w, tgt.h)

    def draw(self, tgt, tex, straight, rect, world, opacity=1.0, mask=None, t=0, disp=None, blend=0):
        """Draw texture tex, which covers clip-space rect, onto layer tgt through world (clip ->
        device), with opacity, mask (in clip space, disp = the clip's size there) and blend."""
        inv, ok = world.inverted()
        if not ok:
            return
        prog = self.composite
        k = math.sqrt(abs(world.determinant())) or 1.0
        e = 1.5 / k                                       # a pixel and a half around, for the soft edge
        r = rect.adjusted(-e, -e, e, e)
        pts = [world.map(r.topLeft()), world.map(r.topRight()), world.map(r.bottomLeft()), world.map(r.bottomRight())]
        self._quad(tgt, pts)
        self._common(prog, tgt, tex, straight, inv * rect_uv(rect), opacity, 1, mask, t, disp, inv, blend)

    def draw_layer(self, tgt, lay, opacity=1.0, mask=None, t=0, disp=None, inv_world=None, blend=0):
        """A whole layer (the size of tgt) onto tgt, with opacity, mask and blend."""
        pts = [QPointF(0, 0), QPointF(tgt.w, 0), QPointF(0, tgt.h), QPointF(tgt.w, tgt.h)]
        self._quad(tgt, pts)
        to_uv = QTransform.fromScale(1 / tgt.w, 1 / tgt.h)
        self._common(self.composite, tgt, lay.tex, False, to_uv, opacity, 0, mask, t, disp, inv_world, blend)

    def _common(self, prog, tgt, tex, straight, dev_uv, opacity, edge, mask, t, disp, inv_world, blend):
        prog["size"].value = (tgt.w, tgt.h)
        prog["dev_uv"].value = mat3(dev_uv)
        prog["straight"].value = 1 if straight else 0
        prog["edge"].value = edge
        prog["opacity"].value = float(opacity)
        self._mask_uniforms(prog, mask, t, disp, inv_world)
        prog["tex"].value = 0
        prog["blend"].value = blend
        if blend:
            back = self.backdrop(tgt)
            tgt.fbo.use()
            back.tex.use(1)
            prog["backdrop"].value = 1
            self.ctx.disable(self.mgl.BLEND)
        else:
            self.ctx.enable(self.mgl.BLEND)
            self.ctx.blend_func = (self.mgl.ONE, self.mgl.ONE_MINUS_SRC_ALPHA)
        tex.use(0)
        self.vao[id(prog)].render(self.mgl.TRIANGLE_STRIP)
        self.ctx.disable(self.mgl.BLEND)

    def mix(self, dst, a, b, strength=1.0, mask=None, t=0, disp=None, inv_world=None):
        """dst = a and b mixed by strength x mask (whole layers of dst's size; no blending)."""
        prog = self.mixer
        self._quad(dst, [QPointF(0, 0), QPointF(dst.w, 0), QPointF(0, dst.h), QPointF(dst.w, dst.h)])
        prog["size"].value = (dst.w, dst.h)
        prog["strength"].value = float(strength)
        self._mask_uniforms(prog, mask, t, disp, inv_world)
        a.use(0)
        b.use(1)
        prog["a_tex"].value, prog["b_tex"].value = 0, 1
        self.ctx.disable(self.mgl.BLEND)
        self.vao[id(prog)].render(self.mgl.TRIANGLE_STRIP)


    def mix_cover(self, dst, a, b, cover):
        """dst = a and b mixed by cover's alpha (whole layers of dst's size; no blending)."""
        prog = self.coverer
        self._quad(dst, [QPointF(0, 0), QPointF(dst.w, 0), QPointF(0, dst.h), QPointF(dst.w, dst.h)])
        prog["size"].value = (dst.w, dst.h)
        a.use(0)
        b.use(1)
        cover.use(2)
        prog["a_tex"].value, prog["b_tex"].value, prog["c_tex"].value = 0, 1, 2
        self.ctx.disable(self.mgl.BLEND)
        self.vao[id(prog)].render(self.mgl.TRIANGLE_STRIP)


class GLRenderer(render.Renderer):
    """render.Renderer's pictures, composited on the GPU (same interface)."""

    def __init__(self, video_frame=None, cache_limit=600):
        super().__init__(video_frame, cache_limit)
        self.gl = GL()
        self.gl_stills = {}            # still key -> Layer (static compounds)

    def render(self, view, frame, width, height, alpha=False):
        """RGBA frame `frame` of a project-like view, drawn at width x height (RGBA8888); on a
        transparent background instead of black with alpha (premultiplied RGBA8888 then)."""
        gl = self.gl
        with gl.ctx:                    # (another renderer's filters may have made theirs current)
            gl.new_frame()
            tgt = gl.layer(width, height, (0.0, 0.0, 0.0, 0.0 if alpha else 1.0))
            self.begin(view)
            try:
                base = QTransform.fromScale(width / view["width"], height / view["height"])
                self.gl_tracks(tgt, base, view["tracks"], view["width"], view["height"], view["fps"],
                               frame / view["fps"] * US, width / view["width"])
                data = tgt.fbo.read(components=4)
            finally:
                gl.release(tgt)
        fmt = QImage.Format_RGBA8888_Premultiplied if alpha else QImage.Format_RGBA8888
        return QImage(data, width, height, width * 4, fmt).copy()

    def gl_content(self, tgt, base, comp, W, H, fps, t_us, ppu):
        """A compound's or a group's tracks (as render.draw_content: a group's matte)."""
        matte = (comp.get("matte") or {}) if comp.get("group") else {}
        tracks = [tr for tr in comp["tracks"] if tr["kind"] != "audio"]
        if not matte.get("on") or len(tracks) < 2:
            self.gl_tracks(tgt, base, comp["tracks"], W, H, fps, t_us, ppu)
            return
        gl = self.gl
        cut, above, kept, empty = (gl.layer(tgt.w, tgt.h) for _ in range(4))
        try:
            self.gl_tracks(cut, base, tracks[:1], W, H, fps, t_us, ppu)
            self.gl_tracks(above, base, tracks[1:], W, H, fps, t_us, ppu)
            if matte.get("invert"):                                  # kept where the bottom one is not
                gl.mix_cover(kept, above.tex, empty.tex, cut.tex)
            else:                                                    # kept where the bottom one is
                gl.mix_cover(kept, empty.tex, above.tex, cut.tex)
            if matte.get("show"):
                gl.draw_layer(tgt, cut)
            gl.draw_layer(tgt, kept)
        finally:
            for lay in (cut, above, kept, empty):
                gl.release(lay)

    def gl_tracks(self, tgt, base, tracks, W, H, fps, t_us, ppu):
        f = round(t_us * fps / US)
        for tr in tracks:
            if tr["kind"] == "audio" or not project.visible(tr):
                continue
            for c in tr["clips"]:
                if round(c["start_us"] * fps / US) <= f < round((c["start_us"] + c["duration_us"]) * fps / US):
                    try:
                        if c["type"] == "filter":
                            self.gl_filter_clip(tgt, base, c, W, H, fps, t_us)
                        else:
                            self.gl_clip(tgt, base, c, W, H, fps, t_us, ppu)
                    except fx.FilterError as exc:
                        self.errors.append(f"{c.get('name') or c['type']}: {exc}")
                    except Exception as exc:          # one bad clip must not blank the frame
                        self.errors.append(f"{c.get('name') or c['type']}: {exc}")

    def gl_clip(self, tgt, base, c, W, H, fps, t_us, ppu):
        gl = self.gl
        tf = c.get("transform") or {}
        t = project.stepped(c, t_us - c["start_us"])           # (降低幀數: in steps)
        v = lambda k, d: curves.value(tf.get(k, d), t)
        opacity = min(1.0, max(0.0, v("opacity", 1.0)))
        if opacity <= 0:
            return
        sx = v("scale", 1.0)
        sy = curves.value(tf.get("scale_y", tf.get("scale", 1.0)), t)
        local = QTransform()
        local.translate(W / 2 + v("x", 0.0) * W / 2, H / 2 - v("y", 0.0) * H / 2)
        local.rotate(v("rotation", 0.0))
        local.scale(sx * (-1 if tf.get("flip_h") else 1), sy * (-1 if tf.get("flip_v") else 1))
        world = local * base
        inv, ok = world.inverted()
        if not ok:
            return
        kind = c["type"]
        held = None                                     # a layer to give back when done
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
            em_unit = (curves.value(spec.get("size", 5.0), 0) or 1.0) * textlayout.PX_PER_FONT_UNIT * H / 1080
            rs = quantize(max(max(abs(sx), abs(sy)) * k_size * ppu, 1.0 / em_unit))
            pic = self.text(spec, rs, H)
            bw, bh = pic.width() / rs * k_size, pic.height() / rs * k_size
            tex, straight = gl.picture(pic)
            rect = QRectF(-bw / 2, -bh / 2, bw, bh)
        elif kind in ("image", "video"):
            m = c["media"]
            bw, bh = project.picture_size(c, W, H, t=t)
            tw, th = bw * abs(sx) * ppu, bh * abs(sy) * ppu
            rect = QRectF(-bw / 2, -bh / 2, bw, bh)
            if c.get("asset"):                       # drawn from its parameters at t
                q = assets.at(c["asset"], t)
                tex, straight = gl.picture(self.asset(q, tw, th), mipmap=True)
                rect = render.asset_rect(q, bw, bh)
            elif kind == "image":
                tex, straight = gl.picture(self.image(m["path"], tw, th), mipmap=True)
            else:
                pic = self.video_frame(m["path"], project.source_time(c, t),
                                       max(1, round(tw)), max(1, round(th))) if self.video_frame else None
                if pic is None:
                    return
                tex, straight = gl.frame_texture(pic)
        elif kind in ("compound", "group"):
            comp = c["compound"] if kind == "compound" else render.group_content(c, W, H)
            cw, ch = comp["width"], comp["height"]
            fit = min(W / cw, H / ch)
            bw, bh = cw * fit, ch * fit
            k = fit * max(abs(sx), abs(sy), 0.01) * ppu       # layer px per compound unit
            straight = False
            if comp.get("static"):
                tex = self.gl_still(comp, k, fps).tex
                rect = QRectF(-bw / 2, -bh / 2, bw, bh)
            else:
                # only the part that lands on the target (as render.py)
                full = QRectF(-bw / 2, -bh / 2, bw, bh)
                pad = 2 * fit / k
                vis = inv.mapRect(QRectF(0, 0, tgt.w, tgt.h)).adjusted(-pad, -pad, pad, pad).intersected(full)
                if vis.isEmpty():
                    return
                lw, lh = vis.width() / fit * k, vis.height() / fit * k
                if max(lw, lh) > MAX_LAYER:
                    k *= MAX_LAYER / max(lw, lh)
                    lw, lh = vis.width() / fit * k, vis.height() / fit * k
                held = gl.layer(max(1, math.ceil(lw)), max(1, math.ceil(lh)))
                inner = QTransform()
                inner.scale(k, k)
                inner.translate(-(vis.left() + bw / 2) / fit, -(vis.top() + bh / 2) / fit)
                self.gl_content(held, inner, comp, cw, ch, fps, t if kind == "group" else project.source_time(c, t), k)
                tex = held.tex
                rect = QRectF(vis.left(), vis.top(), held.w / k * fit, held.h / k * fit)
        else:
            return
        disp = (bw, bh)
        mask = self.clip_mask(c, t)
        blend = BLEND_INDEX.get(curves.value(c.get("blend", "normal"), t), 0)
        effects = project.visual_effects(c)
        backdrop, hide = project.backdrop_of(c)
        matte = self.gl_matte(mask, t, disp, world, fps)
        try:
            if backdrop:                                 # 套用至背景: the effects work on what is under it
                gl.matte = matte and matte[0].tex
                cover = gl.layer(tgt.w, tgt.h)
                snap = gl.layer(tgt.w, tgt.h)
                try:
                    gl.draw(cover, tex, straight, rect, world, opacity, mask, t, disp)
                    gl.ctx.copy_framebuffer(snap.tex, tgt.fbo)
                    out = self.gl_effects(effects, snap, t, c["duration_us"], fps, world, disp)
                    gl.mix_cover(tgt, snap.tex, out.tex, cover.tex)
                    if out is not snap:
                        gl.release(out)
                finally:
                    gl.release(cover)
                    gl.release(snap)
                if not hide:
                    gl.draw(tgt, tex, straight, rect, world, opacity, mask, t, disp, blend)
            elif effects:
                lay = gl.layer(tgt.w, tgt.h)
                try:
                    gl.draw(lay, tex, straight, rect, world)
                    out = self.gl_effects(effects, lay, t, c["duration_us"], fps, world, disp)
                    gl.matte = matte and matte[0].tex
                    gl.draw_layer(tgt, out, opacity, mask, t, disp, inv, blend)
                    if out is not lay:
                        gl.release(out)
                finally:
                    gl.release(lay)
            else:
                gl.matte = matte and matte[0].tex
                gl.draw(tgt, tex, straight, rect, world, opacity, mask, t, disp, blend)
        finally:
            gl.matte = None
            if matte and matte[1]:
                gl.release(matte[0])
            if held is not None:
                gl.release(held)
        if self.matte_preview and self.matte_preview.get("clip") == c["id"]:
            self.gl_matte_ghost(tgt, c.get("mask"), t, disp, world, fps, self.matte_preview.get("opacity", 0.4))

    def gl_matte(self, mask, t, disp, world, fps):
        """(layer, give it back after) with a compound mask's picture (see render.matte_image),
        or None for other masks."""
        comp = self.matte_compound(mask, t)
        if comp is None:
            return None
        k = self.matte_k(mask, t, disp, comp, world)
        if comp.get("image"):                            # an image mask: its picture as a texture
            tex, _straight = self.gl.picture(self.image(comp["image"], comp["width"] * k, comp["height"] * k),
                                             mipmap=True)
            return Picture(tex), False
        kid = mask.get("compound_id")
        self._matting.add(kid)
        try:
            if comp.get("static"):
                return self.gl_still(comp, k, fps), False
            cw, ch = comp["width"], comp["height"]
            k = min(k, self.MATTE_MAX_PX / max(cw, ch))
            lay = self.gl.layer(max(1, math.ceil(cw * k)), max(1, math.ceil(ch * k)))
            self.gl_tracks(lay, QTransform.fromScale(k, k), comp["tracks"], cw, ch, fps,
                           render.matte_time(comp, t + mask.get("t_off", 0), fps), k)
            return lay, True
        finally:
            self._matting.discard(kid)

    def gl_matte_ghost(self, tgt, mask, t, disp, world, fps, opacity):
        """A compound mask's picture over the clip, to place it (as render.draw_matte_ghost)."""
        matte = self.gl_matte(mask, t, disp, world, fps)
        if matte is None:
            return
        v = lambda k, d: curves.value(mask.get(k, d), t)
        w, h = v("w", 1.0) * disp[0], v("h", 1.0) * disp[1]
        local = QTransform().translate(v("cx", 0.0) * disp[0] / 2, -v("cy", 0.0) * disp[1] / 2).rotate(v("rotation", 0.0))
        try:
            if w > 1e-6 and h > 1e-6:
                self.gl.draw(tgt, matte[0].tex, False, QRectF(-w / 2, -h / 2, w, h), local * world, opacity)
        finally:
            if matte[1]:
                self.gl.release(matte[0])

    def gl_still(self, comp, k, fps):
        """A static compound's picture as a layer (drawn once, kept while unchanged)."""
        cw, ch = comp["width"], comp["height"]
        k = min(quantize(k), self.STILL_MAX_PX / max(cw, ch))
        key = (json.dumps(comp["tracks"], sort_keys=True, default=str), cw, ch, round(k, 4))
        lay = self.gl_stills.pop(key, None)
        if lay is None:
            lay = Layer(self.gl, max(1, math.ceil(cw * k)), max(1, math.ceil(ch * k)))
            lay.fbo.clear(0.0, 0.0, 0.0, 0.0)
            self.gl_tracks(lay, QTransform.fromScale(k, k), comp["tracks"], cw, ch, fps, 0, k)
            while len(self.gl_stills) >= 24:
                self.gl_stills.pop(next(iter(self.gl_stills))).release()
        self.gl_stills[key] = lay
        return lay

    def gl_effects(self, effects, lay, t, duration, fps, world, disp):
        """Run a chain of effects over layer lay; returns the layer with the result (lay itself
        when nothing ran, else a new one the caller gives back)."""
        gl = self.gl
        inv, _ = world.inverted()
        cur = lay
        for e in effects:
            d = fx.get(e["filter"])
            vals = {p.name: fx.uniform_value(p, e["params"].get(p.name), t) for p in d.params}
            try:
                out = gl.fx.run_tex(d, vals, cur.tex, cur.w, cur.h, time=t / US,
                                    progress=min(1.0, max(0.0, t / max(1, duration))), frame=max(0, round(t * fps / US)))
            except fx.FilterError as exc:
                self.errors.append(f"濾鏡「{d.name}」：{exc}")
                continue
            nxt = gl.layer(cur.w, cur.h)
            gl.mix(nxt, cur.tex, out, 1.0, e.get("mask"), t, disp, inv)       # the effect's own mask limits it
            if cur is not lay:
                gl.release(cur)
            cur = nxt
        return cur

    def gl_filter_clip(self, tgt, base, c, W, H, fps, t_us):
        """A filter clip: what has been drawn so far goes through its effects, inside its mask
        and at its opacity (as render.draw_filter_clip)."""
        gl = self.gl
        tf = c.get("transform") or {}
        t = t_us - c["start_us"]
        v = lambda k, d: curves.value(tf.get(k, d), t)
        strength = min(1.0, max(0.0, v("opacity", 1.0)))
        effects = project.visual_effects(c)
        if strength <= 0 or not effects:
            return
        local = QTransform()
        local.translate(W / 2 + v("x", 0.0) * W / 2, H / 2 - v("y", 0.0) * H / 2)
        local.rotate(v("rotation", 0.0))
        local.scale(v("scale", 1.0), curves.value(tf.get("scale_y", tf.get("scale", 1.0)), t))
        wt = local * base
        inv, ok = wt.inverted()
        if not ok:
            return
        snap = gl.layer(tgt.w, tgt.h)
        mask = self.clip_mask(c, t)
        matte = None
        try:
            gl.ctx.copy_framebuffer(snap.tex, tgt.fbo)
            out = self.gl_effects(effects, snap, t, c["duration_us"], fps, wt, (W, H))
            matte = self.gl_matte(mask, t, (W, H), wt, fps)
            gl.matte = matte and matte[0].tex
            gl.mix(tgt, snap.tex, out.tex, strength, mask, t, (W, H), inv)
            if out is not snap:
                gl.release(out)
        finally:
            gl.matte = None
            if matte and matte[1]:
                gl.release(matte[0])
            gl.release(snap)


def make(video_frame=None):
    """A GPU renderer, or the CPU one when this computer has no OpenGL 3.3 (or moderngl)."""
    try:
        return GLRenderer(video_frame)
    except Exception:
        return render.Renderer(video_frame)
