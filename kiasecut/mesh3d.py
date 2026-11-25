"""Drawing the solid objects of a scene (mesh.py's meshes) with the GPU: a camera's view of them with a depth buffer, anti-aliased
(multisampled). They are shaded simply (the faces in their own colour, the sides darker) or, with 進階光照, as Blender's Principled
material in the main: a base colour, 金屬度 and 粗糙度 (GGX), two lamps and a studio round the scene to be lit by and to mirror.

Solids and the picture planes of a scene cut through each other by the pixel: the solids are drawn in passes, one before each plane
for what of them is behind it (and was not drawn yet), and one at the end for the rest (Drawer.draw's surfaces and current). Solids
drawn in one pass share the depth buffer, so they cut through each other too.

The lamps and the studio are fixed in the world (x right, y down, z away): the main lamp high on the left on the viewer's side.
"""
import numpy as np

from . import camera, curves, mesh, shadows

SAMPLES = 4
KEPT = 2                       # sizes the multisampled buffers are kept for
SURFACES = 32                  # the planes a scene's solids can be cut by
BIAS = 0.5                     # (px: a face lying on a plane is in front of it)

# what 立體 has when it is switched on (c["solid"]); depth and bevel: px of a 1080-high canvas
DEFAULTS = {"on": False, "advanced": False, "depth": 40.0, "bevel": 3.0, "metallic": 0.0, "roughness": 0.4}

VERTEX = """
#version 330
uniform mat3 turn;           // the object's own axes (with its scale) in the world
uniform mat3 normal_turn;    // ... and what takes its normals there
uniform vec3 place;          // its middle in the world (px)
uniform mat3 view;           // the camera's axes (rows: right, down, forward)
uniform vec3 eye;
uniform float focal;
uniform vec2 half_canvas;
uniform mat3 base;           // canvas px -> the target's px
uniform vec2 target;
uniform vec2 planes;         // near, far (px)
in vec3 in_pos;
in vec3 in_normal;
in vec4 in_color;
in vec2 in_uv;
out vec2 v_uv;
out vec3 v_local;            // the object's own place and normal: where a picture lies on it
out vec3 v_face;
out vec3 v_pos;
out vec3 v_normal;
out vec4 v_color;
out vec3 v_cam;
out float v_cap;
void main() {
    vec3 world = place + turn * in_pos;
    vec3 c = view * (world - eye);
    vec3 s = vec3(half_canvas * c.z + focal * c.xy, c.z);          // the canvas, homogeneous
    vec3 t = base * s;                                            // the target's px, homogeneous
    float a = (planes.y + planes.x) / (planes.y - planes.x), b = -2.0 * planes.y * planes.x / (planes.y - planes.x);
    gl_Position = vec4(2.0 * t.xy / target - t.z, a * c.z + b, c.z);
    v_pos = world;
    v_normal = normal_turn * in_normal;
    v_color = in_color;
    v_cam = c;
    v_cap = in_normal.z;                                          // (the object's own: +-1 on its two faces)
    v_uv = in_uv;
    v_local = in_pos;
    v_face = in_normal;
}
"""

FRAGMENT = """
#version 330
uniform vec3 eye;
uniform float metallic;
uniform float roughness;
uniform int advanced;
uniform int n_lamps;           // -1: the scene's own two lamps; else the 燈光 objects'
uniform vec4 lamp_at[8];       // a place (w 1) or the way to a lamp that shines one way (w 0)
uniform vec3 lamp_colour[8];
uniform vec3 around;           // how much the studio lights the scene
uniform float reach;           // px: where a lamp at a place is as strong as one that shines one way
uniform vec4 surfaces[32];     // planes in the camera's axes (normal, distance > 0): behind one is where dot(n, p) > distance
uniform int n_surfaces;
uniform int current;           // this pass draws what is behind surfaces[current] (n_surfaces: the rest) and behind none before it
uniform sampler2D picture;
uniform int wrap;              // how the picture lies on the object: 0 none, 1 on its two faces, 2 on the six sides of a box,
                               // 3 round a ball, 4 round a cylinder (and flat on its ends), 5 round a ring, 6 by the mesh's UVs
uniform int over;              // 1: over the object's colour; 0: times it (a model's texture)
uniform int straight;          // the texture's colours are not multiplied by its alpha
uniform float cutoff;          // (a model's) less see-through than this is not there
uniform vec3 box_lo;           // the box round the mesh
uniform vec3 box_size;
uniform float shape;           // the picture's width / height
in vec2 v_uv;
in vec3 v_local;
in vec3 v_face;
in vec3 v_cam;
in float v_cap;
in vec3 v_pos;
in vec3 v_normal;
in vec4 v_color;
out vec4 fragColor;

const float PI = 3.14159265;

// the studio round the scene, as seen in direction d (world: y down, z away); soft: 0 a mirror's sharp picture, 1 all spread out
vec3 studio(vec3 d, float soft) {
    float up = -d.y;
    vec3 c = mix(vec3(0.10, 0.095, 0.09), vec3(0.42, 0.45, 0.50), smoothstep(-0.25 - soft, 0.35 + soft, up));
    c += vec3(0.30, 0.30, 0.32) * smoothstep(0.35, 1.0, up);
    // two soft boxes and a strip: what a shiny letter mirrors
    float k = mix(60.0, 2.0, soft), g = mix(1.0, 0.25, soft);
    c += vec3(2.6, 2.5, 2.35) * g * pow(max(dot(d, normalize(vec3(-0.55, -0.55, -0.62))), 0.0), k);
    c += vec3(1.0, 1.15, 1.4) * g * pow(max(dot(d, normalize(vec3(0.80, -0.20, -0.55))), 0.0), k * 0.7);
    c += vec3(0.8) * g * exp(-pow((up - 0.12) * mix(14.0, 2.0, soft), 2.0)) * smoothstep(-0.2, 0.8, -d.z);
    return c;
}

vec3 lamp(vec3 N, vec3 V, vec3 L, vec3 colour, vec3 diffuse, vec3 f0, float a) {
    float nl = max(dot(N, L), 0.0);
    if (nl <= 0.0) return vec3(0.0);
    vec3 H = normalize(L + V);
    float nv = max(dot(N, V), 1e-4), nh = max(dot(N, H), 0.0), vh = max(dot(V, H), 0.0);
    float a2 = a * a;
    float q = nh * nh * (a2 - 1.0) + 1.0;
    float D = a2 / (PI * q * q);
    float k = a * 0.5;
    float G = (nl / (nl * (1.0 - k) + k)) * (nv / (nv * (1.0 - k) + k));
    vec3 F = f0 + (1.0 - f0) * pow(1.0 - vh, 5.0);
    return (diffuse * (1.0 - F) + F * min(D * G / (4.0 * nl * nv), 20.0)) * colour * nl;
}

// the part of the picture that covers a face `ratio` (width / height) wide, its middle kept
vec2 covering(vec2 q, float ratio) {
    vec2 k = ratio > shape ? vec2(1.0, shape / ratio) : vec2(ratio / shape, 1.0);
    return (q - 0.5) * k + 0.5;
}

// where on the picture this pixel is (false: it has none of it)
bool place_on_picture(out vec2 uv) {
    vec3 q = (v_local - box_lo) / max(box_size, vec3(1e-4));
    vec3 n = v_face;
    vec3 round_ = v_local / max(box_size * 0.5, vec3(1e-4));
    if (wrap == 6) { uv = v_uv; return true; }
    if (wrap == 1) {
        if (abs(n.z) < 0.5) return false;
        uv = covering(vec2(n.z < 0.0 ? q.x : 1.0 - q.x, q.y), box_size.x / max(box_size.y, 1e-4));
        return true;
    }
    if (wrap == 5) {
        vec2 out_ = normalize(v_local.xy + vec2(1e-5));
        uv = vec2(atan(round_.x, -round_.y) / (2.0 * PI), atan(dot(n.xy, out_), -n.z) / (2.0 * PI) + 0.5);
        return true;
    }
    if (wrap == 3) {
        uv = vec2(atan(round_.x, -round_.z) / (2.0 * PI) + 0.5, asin(clamp(round_.y, -1.0, 1.0)) / PI + 0.5);
        return true;
    }
    if (wrap == 4) {
        if (abs(n.y) > 0.99) uv = vec2(q.x, n.y < 0.0 ? 1.0 - q.z : q.z);
        else uv = vec2(atan(round_.x, -round_.z) / (2.0 * PI) + 0.5, q.y);
        return true;
    }
    vec3 a = abs(n);                                       // 2: a box, each side seen from outside it
    if (a.z >= a.x && a.z >= a.y) uv = covering(vec2(n.z < 0.0 ? q.x : 1.0 - q.x, q.y), box_size.x / max(box_size.y, 1e-4));
    else if (a.x >= a.y) uv = covering(vec2(n.x > 0.0 ? q.z : 1.0 - q.z, q.y), box_size.z / max(box_size.y, 1e-4));
    else uv = covering(vec2(q.x, n.y < 0.0 ? 1.0 - q.z : q.z), box_size.x / max(box_size.z, 1e-4));
    return true;
}

// the object's colour at this pixel, with the picture on it
vec4 coloured() {
    vec4 c = v_color;
    vec2 uv = vec2(0.0);
    bool there = wrap != 0 && place_on_picture(uv);
    // (the picture comes round again at 0 and 1: of the two ways to measure how fast uv changes, the one without that jump)
    vec2 other = fract(uv + 0.5);
    vec2 dx = dFdx(uv), dy = dFdy(uv), ex = dFdx(other), ey = dFdy(other);
    if (dot(ex, ex) + dot(ey, ey) < dot(dx, dx) + dot(dy, dy)) { dx = ex; dy = ey; }
    if (!there) return c;
    vec2 at = wrap == 6 || wrap == 3 || wrap == 5 || wrap == 4 ? fract(uv) : clamp(uv, 0.0, 1.0);
    vec4 t = textureGrad(picture, at, dx, dy);
    if (straight == 0 && t.a > 0.0) t.rgb /= t.a;
    if (over == 1) return vec4(mix(c.rgb, t.rgb, t.a), c.a);
    if (t.a < cutoff) discard;
    return vec4(c.rgb * t.rgb, c.a);
}

"""  + shadows.SAMPLE + """
uniform int receive;           // shadows fall on it
uniform int lamp_shadow[8];    // the shadow map of lamp i (-1: it casts none)

bool behind(int i) { return dot(surfaces[i].xyz, v_cam) - surfaces[i].w > 0.50; }

void main() {
    for (int i = 0; i < current; i++) {
        if (behind(i)) discard;
    }
    if (current < n_surfaces && !behind(current)) discard;
    vec4 own = coloured();
    vec3 N = normalize(v_normal);
    vec3 V = normalize(eye - v_pos);
    if (dot(N, V) < -0.2) N = -N;                          // (seen from inside: a mirrored object's faces)
    if (advanced == 0) {                                   // simple: the faces as picked, the rest darker, a little by where they look
        float side = 0.58 - 0.16 * N.y - 0.08 * N.x;
        float k = mix(side, 1.0, smoothstep(0.35, 0.98, abs(v_cap)));
        if (receive == 1) {
            for (int i = 0; i < smap_n; i++) k *= 1.0 - smap_p[i].w * blocked(i, v_pos, N, 0);
        }
        fragColor = vec4(own.rgb * k * own.a, own.a);
        return;
    }
    vec3 base = pow(own.rgb, vec3(2.2));
    float rough = clamp(roughness, 0.04, 1.0);
    vec3 f0 = mix(vec3(0.04), base, metallic);
    vec3 diffuse = base * (1.0 - metallic);
    vec3 c = vec3(0.0);
    vec3 lit = vec3(1.0), mirrored = vec3(1.0);
    if (n_lamps < 0) {
        c += lamp(N, V, normalize(vec3(-0.50, -0.65, -0.57)), vec3(0.85, 0.83, 0.80), diffuse, f0, rough * rough);
        c += lamp(N, V, normalize(vec3(0.75, -0.15, -0.45)), vec3(0.22, 0.26, 0.34), diffuse, f0, rough * rough);
    } else {
        for (int i = 0; i < n_lamps; i++) {
            vec3 L = lamp_at[i].xyz - v_pos * lamp_at[i].w;
            float far = max(length(L), 1.0);
            float fall = lamp_at[i].w > 0.5 ? min(reach * reach / (far * far), 4.0) : 1.0;
            float seen = 1.0;
            int map_ = lamp_shadow[i];
            if (receive == 1 && map_ >= 0 && map_ < smap_n) seen = 1.0 - smap_p[map_].w * blocked(map_, v_pos, N, 0);
            c += lamp(N, V, L / far, lamp_colour[i] * fall * seen, diffuse, f0, rough * rough);
        }
        lit = around;
        mirrored = max(around, vec3(0.25));                // (a metal with nothing to mirror is just black)
    }
    // lit by the studio, and mirroring it (Karis' fit of the split sum)
    c += diffuse * (studio(N, 1.0) * 0.36 + 0.11) * lit;
    float nv = max(dot(N, V), 1e-4);
    vec4 r = rough * vec4(-1.0, -0.0275, -0.572, 0.022) + vec4(1.0, 0.0425, 1.04, -0.04);
    float a004 = min(r.x * r.x, exp2(-9.28 * nv)) * r.x + r.y;
    vec2 ab = vec2(-1.04, 1.04) * a004 + r.zw;
    c += studio(reflect(-V, N), rough) * (f0 * ab.x + ab.y) * mix(0.8, 1.2, metallic) * mirrored;
    // the brightest rolls off
    vec3 over = max(c - 0.8, 0.0);
    c = min(c, vec3(0.8)) + over / (1.0 + over * 5.0);
    fragColor = vec4(pow(clamp(c, 0.0, 1.0), vec3(1.0 / 2.2)) * own.a, own.a);
}
"""


MODEL = "model"
# how a picture put on a solid's surface (c["solid"]["surface"]) lies on it (the shader's wrap): by what the solid is
WRAPS = {"cube": 2, "sphere": 3, "cylinder": 4, "cone": 4, "torus": 5, MODEL: 6}
FRONT, OWN_UV = 1, 6                  # (a text or a shape: on its faces)


class Skin:
    """A picture on rows first .. first + count of a solid's mesh: texture() gives (a GL texture, whether its colours are straight)
    or None; wrap: the shader's; over: over the colours (a picture put on a surface), else times them (a model's texture)."""

    def __init__(self, first, count, texture=None, wrap=0, over=False, cutoff=0.0, shape=1.0, metallic=None, roughness=None):
        self.first, self.count, self.texture, self.wrap, self.over = first, count, texture, wrap, over
        self.cutoff, self.shape, self.metallic, self.roughness = cutoff, shape, metallic, roughness


def primitive(clip):
    """The kind (mesh.PRIMITIVES, or MODEL: an imported model, c["solid"]["model"] its .kmodel) of the clip of a solid that is
    nothing else - an 空物體 with c["solid"]["prim"] - or None."""
    kind = (clip.get("solid") or {}).get("prim")
    return kind if clip.get("type") == "image" and clip.get("asset") and (kind in mesh.PRIMITIVES or kind == MODEL) else None


def can(clip):
    """Whether clip is something that can be a solid in a scene: a text, a shape or pen path, or a basic solid."""
    if clip.get("type") == "text":
        return True
    if clip.get("type") != "image" or not clip.get("asset") or clip.get("camera") or clip.get("light"):
        return False
    return clip["asset"].get("family") in mesh.SHAPES or primitive(clip) is not None


def on(clip):
    """Whether clip is drawn as a solid in a scene."""
    return bool((clip.get("solid") or {}).get("on")) and can(clip)


def setting(clip, key, t):
    return float(curves.value((clip.get("solid") or {}).get(key, DEFAULTS[key]), t))


class Drawer:
    """The program and buffers of one GL context (mgl, ctx)."""

    def __init__(self, mgl, ctx):
        self.mgl, self.ctx = mgl, ctx
        self.program = ctx.program(vertex_shader=VERTEX, fragment_shader=FRAGMENT)
        self.samples = min(SAMPLES, ctx.max_samples)
        self.targets = {}          # (w, h) -> (multisampled framebuffer, its renderbuffers)
        self.buffers = {}          # id of a mesh -> (the mesh, buffer, vertex array)

    def _target(self, w, h):
        got = self.targets.pop((w, h), None)
        if got is None:
            while len(self.targets) >= KEPT:
                fbo, bufs = self.targets.pop(next(iter(self.targets)))
                fbo.release()
                for b in bufs:
                    b.release()
            colour = self.ctx.renderbuffer((w, h), 4, samples=self.samples)
            depth = self.ctx.depth_renderbuffer((w, h), samples=self.samples)
            got = (self.ctx.framebuffer([colour], depth), (colour, depth))
        self.targets[(w, h)] = got
        return got[0]

    def _vao(self, data):
        got = self.buffers.pop(id(data), None)
        if got is None or got[0] is not data:
            while len(self.buffers) >= 16:
                _m, buf, vao = self.buffers.pop(next(iter(self.buffers)))
                vao.release()
                buf.release()
            rows = data if data.shape[1] == 12 else np.concatenate([data, np.zeros((len(data), 2), "f4")], axis=1)
            buf = self.ctx.buffer(rows.astype("f4").tobytes())
            layout = (buf, "3f 3f 4f 2f", "in_pos", "in_normal", "in_color", "in_uv")
            if "in_uv" not in self.program:
                layout = (buf, "3f 3f 4f 2x4", "in_pos", "in_normal", "in_color")
            vao = self.ctx.vertex_array(self.program, [layout])
            got = (data, buf, vao)
        self.buffers[id(data)] = got
        return got[2]

    def _uniform(self, name, value):
        if name in self.program:                          # (one the compiler left out is not there to set)
            self.program[name].value = value

    def _lights(self, rig):
        """rig: lights.rig's, or None for the scene's own lamps."""
        lamps = rig["lamps"] if rig else []
        self._uniform("n_lamps", len(lamps) if rig else -1)
        if not rig:
            return
        self._uniform("around", tuple(float(x) for x in rig["ambient"]))
        self._uniform("reach", float(rig["reach"]))
        empty = [((0.0, 0.0, -1.0), 0.0, (0.0, 0.0, 0.0))] * (8 - len(lamps))
        if "lamp_at" in self.program:
            self.program["lamp_at"].write(np.array([(*p, w) for p, w, _c in lamps + empty], "f4").tobytes())
        if "lamp_colour" in self.program:
            self.program["lamp_colour"].write(np.array([c for _p, _w, c in lamps + empty], "f4").tobytes())

    def draw(self, tgt_fbo, w, h, parts, cam, W, H, base, tc, surfaces=(), current=0, lights=None, maps=None):
        """Draw parts (Part) seen by camera cam (at its time tc) into the w x h framebuffer tgt_fbo (which is cleared to nothing). base:
        the QTransform from the W x H canvas to its px. surfaces: [(nx, ny, nz, distance)] planes in the camera's axes; only what is
        behind surfaces[current] and behind none before it is drawn (current == len(surfaces): what is behind none)."""
        focal, eye, axes = camera._basis(cam, tc, W, H)

        def mat(m):                                       # (by columns)
            return tuple(float(x) for x in np.asarray(m).T.reshape(9))
        self._uniform("view", mat(axes))
        self._uniform("eye", tuple(float(x) for x in eye))
        self._uniform("focal", float(focal))
        self._uniform("half_canvas", (W / 2.0, H / 2.0))
        self._uniform("base", mat([[base.m11(), base.m21(), base.dx()], [base.m12(), base.m22(), base.dy()], [0.0, 0.0, 1.0]]))
        self._uniform("target", (float(w), float(h)))
        self._uniform("planes", (max(1.0, H * 0.01), H * 200.0))
        held = list(surfaces)[:SURFACES]
        if "surfaces" in self.program:
            self.program["surfaces"].write(np.array(held + [(0.0, 0.0, 0.0, 1.0)] * (SURFACES - len(held)), "f4").tobytes())
        self._uniform("n_surfaces", len(held))
        self._uniform("current", min(current, len(held)))
        self._lights(lights)
        mapped = maps is not None and maps.uniforms is not None
        if mapped:
            maps.use(self.program, 1)
        else:
            self._uniform("smap_n", 0)
            self._uniform("smap_grid", 1)
            self._uniform("smap", 1)
        if "lamp_shadow" in self.program:
            which = [-1] * 8
            for i, held_ in enumerate((lights or {}).get("shadows", [])[:shadows.MOST] if mapped else []):
                which[held_["lamp"]] = i
            self.program["lamp_shadow"].write(np.array(which, "i4").tobytes())
        ready = [(part, self._vao(part.data)) for part in parts]
        msaa = self._target(w, h)
        msaa.use()
        self.ctx.viewport = (0, 0, w, h)
        msaa.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        self.ctx.enable(self.mgl.DEPTH_TEST)
        try:
            for part, vao in ready:
                self._uniform("turn", mat(part.axes))
                self._uniform("normal_turn", mat(part.normals))
                self._uniform("place", tuple(float(x) for x in part.place))
                self._uniform("advanced", 1 if part.advanced else 0)
                self._uniform("receive", 1 if mapped and part.receive else 0)
                lo, hi = bounds(part.data)
                self._uniform("box_lo", tuple(float(x) for x in lo))
                self._uniform("box_size", tuple(float(x) for x in hi - lo))
                for skin in part.skins or [Skin(0, len(part.data))]:
                    held = skin.texture() if skin.texture is not None else None
                    if held is not None:
                        held[0].use(0)
                    self._uniform("picture", 0)
                    self._uniform("wrap", skin.wrap if held is not None else 0)
                    self._uniform("over", 1 if skin.over else 0)
                    self._uniform("straight", 1 if held is not None and held[1] else 0)
                    self._uniform("cutoff", float(skin.cutoff))
                    self._uniform("shape", float(skin.shape))
                    self._uniform("metallic", part.metallic if skin.metallic is None else float(skin.metallic))
                    self._uniform("roughness", part.roughness if skin.roughness is None else float(skin.roughness))
                    vao.render(self.mgl.TRIANGLES, vertices=skin.count, first=skin.first)
        finally:
            self.ctx.disable(self.mgl.DEPTH_TEST)
        self.ctx.copy_framebuffer(tgt_fbo, msaa)


class Part:
    """One solid as it stands now: mesh data (the object's own px; size: how much bigger than that it is - a text's keyframed 字號)
    with the clip's transform tf at clip time t, its material, and how it is put on what is under it (opacity, blend)."""

    def __init__(self, data, tf, t, W, H, size=1.0, advanced=False, metallic=0.0, roughness=0.4, opacity=1.0, blend=0, skins=None):
        v = lambda key, default: float(curves.value(tf.get(key, default), t))
        s = H / 2.0
        self.data, self.skins = data, skins          # (skins: [Skin] covering the mesh, or None: no pictures)
        self.cast = self.receive = True              # 投射陰影, 接收陰影
        self.place = np.array([v("x", 0.0) * W / 2.0, -v("y", 0.0) * s, v("z", 0.0) * s])
        sx = v("scale", 1.0)
        sy = float(curves.value(tf.get("scale_y", tf.get("scale", 1.0)), t))
        scale = np.array([sx * (-1 if tf.get("flip_h") else 1), sy * (-1 if tf.get("flip_v") else 1), sx]) * size
        scale = np.where(np.abs(scale) < 1e-6, 1e-6, scale)
        r = camera._rot(v("rot_x", 0.0), v("rot_y", 0.0), v("rotation", 0.0))
        self.axes, self.normals = r * scale, r / scale
        self.advanced, self.metallic, self.roughness = bool(advanced), float(metallic), float(roughness)
        self.opacity, self.blend = float(opacity), int(blend)

    def corners(self, cam, W, H, tc):
        """(8, 3): the corners of the box round the solid, in the camera's axes (px)."""
        _f, eye, axes = camera._basis(cam, tc, W, H)
        lo, hi = bounds(self.data)
        local = np.array([(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        return (self.place + local @ self.axes.T - eye) @ axes.T


_bounds = {}


def bounds(data):
    """(lowest, highest) corner of a mesh, kept."""
    got = _bounds.get(id(data))
    if got is None or got[0] is not data:
        if len(_bounds) > 128:
            _bounds.clear()
        got = _bounds[id(data)] = (data, data[:, :3].min(axis=0).astype(float), data[:, :3].max(axis=0).astype(float))
    return got[1], got[2]


def surface(matrix):
    """(nx, ny, nz, distance >= 0) in the camera's axes of the picture plane whose camera.scene_matrix is `matrix` (16 numbers)."""
    n = np.array(matrix[8:11], float)
    d = float(n @ np.array(matrix[12:15], float))
    if d < 0:
        n, d = -n, -d
    if d < 1e-6:                              # (seen edge on: nothing is behind it)
        return (0.0, 0.0, 0.0, 1.0)
    return (float(n[0]), float(n[1]), float(n[2]), d)


def needed(corners, surfaces, current):
    """Whether the pass `current` can have anything of a solid with these corners in it."""
    if current < len(surfaces):
        s = surfaces[current]
        if np.all(corners @ np.array(s[:3]) - s[3] <= BIAS):          # (all in front of this one)
            return False
    return not any(np.all(corners @ np.array(s[:3]) - s[3] > BIAS) for s in surfaces[:current])    # (not all drawn before)
