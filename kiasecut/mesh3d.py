"""Drawing the solid objects of a scene (mesh.py's meshes) with the GPU: a camera's view of them with a depth buffer, anti-aliased
(multisampled), shaded as Blender's Principled material in the main: a base colour, 金屬 and 粗糙度 (GGX), two lamps and a studio
round the scene to be lit by and to mirror.

The lamps and the studio are fixed in the world (x right, y down, z away): the main lamp high on the left on the viewer's side.
"""
import numpy as np

from . import camera, curves

SAMPLES = 4
KEPT = 2                       # sizes the multisampled buffers are kept for

# what 立體 has when it is switched on (c["solid"]); depth and bevel: px of a 1080-high canvas
DEFAULTS = {"on": False, "depth": 40.0, "bevel": 3.0, "metallic": 0.0, "roughness": 0.4}

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
out vec3 v_pos;
out vec3 v_normal;
out vec4 v_color;
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
}
"""

FRAGMENT = """
#version 330
uniform vec3 eye;
uniform float metallic;
uniform float roughness;
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

void main() {
    vec3 N = normalize(v_normal);
    vec3 V = normalize(eye - v_pos);
    if (dot(N, V) < -0.2) N = -N;                          // (seen from inside: a mirrored object's faces)
    vec3 base = pow(v_color.rgb, vec3(2.2));
    float rough = clamp(roughness, 0.04, 1.0);
    vec3 f0 = mix(vec3(0.04), base, metallic);
    vec3 diffuse = base * (1.0 - metallic);
    vec3 c = lamp(N, V, normalize(vec3(-0.50, -0.65, -0.57)), vec3(0.85, 0.83, 0.80), diffuse, f0, rough * rough);
    c += lamp(N, V, normalize(vec3(0.75, -0.15, -0.45)), vec3(0.22, 0.26, 0.34), diffuse, f0, rough * rough);
    // lit by the studio, and mirroring it (Karis' fit of the split sum)
    c += diffuse * (studio(N, 1.0) * 0.36 + 0.11);
    float nv = max(dot(N, V), 1e-4);
    vec4 r = rough * vec4(-1.0, -0.0275, -0.572, 0.022) + vec4(1.0, 0.0425, 1.04, -0.04);
    float a004 = min(r.x * r.x, exp2(-9.28 * nv)) * r.x + r.y;
    vec2 ab = vec2(-1.04, 1.04) * a004 + r.zw;
    c += studio(reflect(-V, N), rough) * (f0 * ab.x + ab.y) * mix(0.8, 1.2, metallic);
    // the brightest rolls off
    vec3 over = max(c - 0.8, 0.0);
    c = min(c, vec3(0.8)) + over / (1.0 + over * 5.0);
    fragColor = vec4(pow(clamp(c, 0.0, 1.0), vec3(1.0 / 2.2)) * v_color.a, v_color.a);
}
"""


def on(clip):
    """Whether clip (a text) is drawn as a solid in a scene."""
    return clip.get("type") == "text" and bool((clip.get("solid") or {}).get("on"))


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
            buf = self.ctx.buffer(data.astype("f4").tobytes())
            vao = self.ctx.vertex_array(self.program, [(buf, "3f 3f 4f", "in_pos", "in_normal", "in_color")])
            got = (data, buf, vao)
        self.buffers[id(data)] = got
        return got[2]

    def draw(self, tgt_fbo, w, h, data, cam, tf, t, W, H, base, tc=None, size=1.0):
        """Draw mesh data (the object's own px; size: how much bigger than that it is - a text's keyframed 字號) with the clip's
        transform tf at clip time t, seen by camera cam, into the w x h framebuffer tgt_fbo (which is cleared to nothing). base: the
        QTransform from the W x H canvas to its px."""
        tc = t if tc is None else tc
        s = H / 2.0
        focal, eye, axes = camera._basis(cam, tc, W, H)
        v = lambda key, default: float(curves.value(tf.get(key, default), t))
        place = np.array([v("x", 0.0) * W / 2.0, -v("y", 0.0) * s, v("z", 0.0) * s])
        sx = v("scale", 1.0)
        sy = float(curves.value(tf.get("scale_y", tf.get("scale", 1.0)), t))
        scale = np.array([sx * (-1 if tf.get("flip_h") else 1), sy * (-1 if tf.get("flip_v") else 1), sx]) * size
        scale = np.where(np.abs(scale) < 1e-6, 1e-6, scale)
        r = camera._rot(v("rot_x", 0.0), v("rot_y", 0.0), v("rotation", 0.0))
        p = self.program

        def mat(m):                                       # (by columns)
            return tuple(float(x) for x in np.asarray(m).T.reshape(9))
        p["turn"].value = mat(r * scale)
        p["normal_turn"].value = mat(r / scale)
        p["place"].value = tuple(float(x) for x in place)
        p["view"].value = mat(axes)
        p["eye"].value = tuple(float(x) for x in eye)
        p["focal"].value = float(focal)
        p["half_canvas"].value = (W / 2.0, H / 2.0)
        p["base"].value = mat([[base.m11(), base.m21(), base.dx()], [base.m12(), base.m22(), base.dy()], [0.0, 0.0, 1.0]])
        p["target"].value = (float(w), float(h))
        p["planes"].value = (max(1.0, H * 0.01), H * 200.0)
        vao = self._vao(data)
        msaa = self._target(w, h)
        msaa.use()
        self.ctx.viewport = (0, 0, w, h)
        msaa.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        self.ctx.enable(self.mgl.DEPTH_TEST)
        try:
            vao.render(self.mgl.TRIANGLES)
        finally:
            self.ctx.disable(self.mgl.DEPTH_TEST)
        self.ctx.copy_framebuffer(tgt_fbo, msaa)
