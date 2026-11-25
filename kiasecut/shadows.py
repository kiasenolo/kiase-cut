"""投射陰影 in a scene: every 燈光 object that casts shadows draws a map of what it sees first - how far the nearest thing is, and
which - from the solids (mesh3d.py) and from the picture planes (where they are more than half there). A solid or a plane being
shaded asks the map whether something is between it and the light (SAMPLE, the GLSL both use), at a few places round it for a soft
edge.

A plane has a number of its own in the map and never shades itself; the solids share the number 0 and shade themselves and each
other. A 平行光 looks along its way, as wide as what casts; a 點光源 looks from its place at the middle of what casts, as wide as
150 degrees at most (what is farther round it than that casts no shadow)."""
import math

import numpy as np

MOST = 4                      # lights that cast shadows at once
SIZE_ONE, SIZE_EACH = 2048, 1536      # texels across a map: of the only light, of each of several
WIDEST = math.radians(150.0)

SAMPLE = """
uniform sampler2D smap;       // the maps, side by side: red how far, green whose (0: a solid's, n: plane n's)
uniform mat4 smap_m[4];       // world -> a light's picture (xy / w), how far (z), w
uniform vec4 smap_p[4];       // the soft edge's radius on the map x w (u, v), a texel's size in the world per w, how dark the shadow is
uniform vec4 smap_l[4];       // a place (w 1) or the way to a light that shines one way (w 0)
uniform int smap_n;
uniform int smap_grid;        // maps across the texture

// how much of the four texels round place `at` of map's tile is nearer the light than `deep` (and not the plane's own)
float covered(vec2 at, int tile, ivec2 corner, float deep, int me) {
    vec2 p = at * float(tile) - 0.5;
    ivec2 first = ivec2(floor(p));
    vec2 f = p - floor(p);
    float four[4];
    for (int j = 0; j < 4; j++) {
        ivec2 q = first + ivec2(j % 2, j / 2);
        four[j] = 0.0;
        if (q.x >= 0 && q.y >= 0 && q.x < tile && q.y < tile) {
            vec2 held = texelFetch(smap, corner + q, 0).rg;
            if (held.r < deep && (me == 0 || int(held.g + 0.5) != me)) four[j] = 1.0;
        }
    }
    return mix(mix(four[0], four[1], f.x), mix(four[2], four[3], f.x), f.y);
}

// how much of light i is kept from point `world` of a surface looking along N (N = 0: a plane, which never shades itself)
float blocked(int i, vec3 world, vec3 N, int me) {
    float slope = 0.0;
    vec3 from = world;
    if (dot(N, N) > 0.5) {
        float nl = dot(N, normalize(smap_l[i].xyz - world * smap_l[i].w));
        if (nl <= 0.0) return 1.0;                                 // (turned away from it)
        slope = min(sqrt(max(1.0 - nl * nl, 0.0)) / max(nl, 0.2), 4.0);
        // (looked at from a little off the surface - the farther the wider the soft edge, whose places lie on a flat disc)
        float w = max((smap_m[i] * vec4(world, 1.0)).w, 0.001);
        float wide = max(smap_p[i].x, smap_p[i].y) / w * float(textureSize(smap, 0).x / smap_grid);
        from = world + N * (smap_p[i].z * w * (1.5 + 0.4 * wide));
    }
    vec4 r = smap_m[i] * vec4(from, 1.0);
    if (r.w <= 0.001) return 0.0;
    vec2 uv = r.xy / r.w * 0.5 + 0.5;
    int tile = textureSize(smap, 0).x / smap_grid;
    ivec2 corner = ivec2(i % smap_grid, i / smap_grid) * tile;
    vec2 radius = max(smap_p[i].xy / r.w, vec2(1.25 / float(tile)));
    float bias = smap_p[i].z * r.w * (1.5 + slope * (1.0 + 0.7 * max(radius.x, radius.y) * float(tile))) + 0.5;
    // (the places are turned differently at every pixel: a wide soft edge is a fine grain, not rings)
    float start = 6.28318 * fract(52.9829189 * fract(dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715))));
    float sum = 0.0;
    int taken = 0;
    // first six places round the whole of the soft edge: where they agree it is all lit or all dark, and that is that
    for (int k = 0; k < 6; k++) {
        float turn = start + float(k) * 1.0472;
        float out_ = k % 2 == 0 ? 1.0 : 0.55;
        sum += covered(uv + radius * out_ * vec2(cos(turn), sin(turn)), tile, corner, r.z - bias, me);
    }
    if (sum <= 0.0) return 0.0;
    if (sum >= 6.0) return 1.0;
    for (int k = 0; k < 24; k++) {
        float turn = start + float(k) * 2.39996;
        sum += covered(uv + radius * sqrt((float(k) + 0.5) / 24.0) * vec2(cos(turn), sin(turn)), tile, corner, r.z - bias, me);
    }
    return sum / 30.0;
}
"""

CAST_VERTEX = """
#version 330
uniform mat4 light;           // world -> the light's picture (xy / w), how far (z), w
uniform vec2 planes;          // gl's z: z * w = planes.x * far + planes.y
uniform mat3 turn;
uniform vec3 place;
in vec3 in_pos;
in vec2 in_uv;
out float v_far;
out vec2 v_uv;
void main() {
    vec4 r = light * vec4(place + turn * in_pos, 1.0);
    gl_Position = vec4(r.xy, planes.x * r.z + planes.y, r.w);
    v_far = r.z;
    v_uv = in_uv;
}
"""

CAST_FRAGMENT = """
#version 330
uniform sampler2D picture;
uniform int cut;              // a plane: only where its picture is more than half there
uniform float me;
in float v_far;
in vec2 v_uv;
out vec4 fragColor;
void main() {
    if (cut == 1 && texture(picture, v_uv).a < 0.5) discard;
    fragColor = vec4(v_far, me, 0.0, 1.0);
}
"""

RECEIVE_VERTEX = """
#version 330
uniform vec2 size;
in vec2 pos;
void main() { gl_Position = vec4(pos / size * 2.0 - 1.0, 0.0, 1.0); }
"""

RECEIVE_FRAGMENT = """
#version 330
uniform sampler2D tex;        // the plane's layer: its pixels are the target's
uniform mat3 to_canvas;       // layer px -> the plane drawn flat, canvas px from its middle
uniform vec3 origin;          // the plane in the world
uniform vec3 across;
uniform vec3 down;
uniform int me;
""" + SAMPLE + """
out vec4 fragColor;
void main() {
    vec4 c = texelFetch(tex, ivec2(gl_FragCoord.xy), 0);
    if (c.a <= 0.0) { fragColor = c; return; }
    vec3 q = to_canvas * vec3(gl_FragCoord.xy, 1.0);
    vec3 world = origin + across * (q.x / q.z) + down * (q.y / q.z);
    float k = 1.0;
    for (int i = 0; i < smap_n; i++) k *= 1.0 - smap_p[i].w * blocked(i, world, vec3(0.0), me);
    fragColor = vec4(c.rgb * k, c.a);
}
"""


def fit(light, points, size):
    """(the matrix world -> the light's picture, gl's depth (a, b), the light's smap_p) for a light of lights.rig's "shadows" and
    what casts (points (n, 3), world px), on a map `size` texels across."""
    lo, hi = points.min(axis=0), points.max(axis=0)
    middle = (lo + hi) / 2.0
    at = np.array(light["from"], float)
    way = (middle - at) if light["w"] else -at
    way = way / max(np.linalg.norm(way), 1e-9)
    side = np.cross(way, (0.0, 1.0, 0.0) if abs(way[1]) < 0.99 else (1.0, 0.0, 0.0))
    side /= np.linalg.norm(side)
    other = np.cross(way, side)
    m = np.zeros((4, 4))
    soft = max(float(light["softness"]), 0.0)
    if not light["w"]:
        a, b, far = points @ side, points @ other, points @ way
        half = np.array([a.max() - a.min(), b.max() - b.min()]) / 2.0 + soft + 4.0
        centre = ((a.max() + a.min()) / 2.0, (b.max() + b.min()) / 2.0)
        m[0] = (*side / half[0], -centre[0] / half[0])
        m[1] = (*other / half[1], -centre[1] / half[1])
        m[2] = (*way, -(far.min() - 1.0))
        m[3] = (0.0, 0.0, 0.0, 1.0)
        deepest = float(far.max() - far.min()) + 2.0
        # (z * w = z: what is past the casters is drawn on all the same - nothing there casts)
        return m, (2.0 / deepest, -1.0), (soft / (2.0 * half[0]), soft / (2.0 * half[1]), 2.0 * float(half.max()) / size,
                                          float(light["darkness"]))
    rel = points - at
    ahead = rel @ way
    off = np.hypot(rel @ side, rel @ other)
    angle = min(WIDEST / 2.0, float(np.arctan2(off, ahead).max()) + 0.03)
    k = math.tan(max(angle, 0.05))
    m[0] = (*side / k, -float(side @ at) / k)
    m[1] = (*other / k, -float(other @ at) / k)
    m[2] = (*way, -float(way @ at))
    m[3] = m[2]
    deepest = max(float(np.linalg.norm(rel, axis=1).max()), 10.0) * 1.01
    near = max(deepest / 5000.0, 0.5)
    a, b = (deepest + near) / (deepest - near), -2.0 * deepest * near / (deepest - near)
    return m, (a, b), (soft / (2.0 * k), soft / (2.0 * k), 2.0 * k / size, float(light["darkness"]))


class Maps:
    """The shadow maps of one GL context (mgl, ctx), drawn anew for every frame (build)."""

    def __init__(self, mgl, ctx):
        self.mgl, self.ctx = mgl, ctx
        self.caster = ctx.program(vertex_shader=CAST_VERTEX, fragment_shader=CAST_FRAGMENT)
        self.receiver = ctx.program(vertex_shader=RECEIVE_VERTEX, fragment_shader=RECEIVE_FRAGMENT)
        self.target = None             # (size, texture, depth, framebuffer)
        self.solids = {}               # id of a mesh -> (the mesh, buffer, vertex array)
        self.quad = ctx.buffer(reserve=4 * 5 * 4, dynamic=True)
        self.quad_vao = ctx.vertex_array(self.caster, [(self.quad, "3f 2f", "in_pos", "in_uv")])
        self.screen = ctx.buffer(reserve=4 * 2 * 4, dynamic=True)
        self.screen_vao = ctx.vertex_array(self.receiver, [(self.screen, "2f", "pos")])
        self.uniforms = None           # of the maps last built
        self.texture = None

    def _target(self, side):
        if self.target is None or self.target[0] != side:
            if self.target is not None:
                for thing in self.target[3], self.target[1], self.target[2]:
                    thing.release()
            texture = self.ctx.texture((side, side), 2, dtype="f4")
            texture.filter = (self.mgl.NEAREST, self.mgl.NEAREST)
            texture.repeat_x = texture.repeat_y = False
            depth = self.ctx.depth_renderbuffer((side, side))
            self.target = (side, texture, depth, self.ctx.framebuffer([texture], depth))
        return self.target

    def _solid(self, data):
        got = self.solids.pop(id(data), None)
        if got is None or got[0] is not data:
            while len(self.solids) >= 16:
                _m, buf, vao = self.solids.pop(next(iter(self.solids)))
                vao.release()
                buf.release()
            buf = self.ctx.buffer(np.ascontiguousarray(data[:, :3], "f4").tobytes())
            vao = self.ctx.vertex_array(self.caster, [(buf, "3f", "in_pos")])
            got = (data, buf, vao)
        self.solids[id(data)] = got
        return got[2]

    def build(self, lights, solids, planes):
        """Draw the maps of `lights` (lights.rig's "shadows"). solids: [mesh3d.Part] that cast; planes: [(its number, 1 up,
        (4, 3) its corners in the world going round, [(u, v)] where they are on its texture, the texture)] that cast. False when
        nothing casts."""
        self.uniforms = None
        lights = lights[:MOST]
        points = [corners for _n, corners, _uv, _t in planes]
        for part in solids:
            data = part.data
            lo, hi = data[:, :3].min(axis=0), data[:, :3].max(axis=0)
            box = np.array([(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], float)
            points.append(part.place + box @ part.axes.T)
        if not lights or not points:
            return False
        points = np.concatenate(points)
        grid = 1 if len(lights) == 1 else 2
        tile = SIZE_ONE if grid == 1 else SIZE_EACH
        _side, texture, _depth, fbo = self._target(tile * grid)
        fbo.use()
        self.ctx.viewport = (0, 0, tile * grid, tile * grid)
        fbo.clear(1e20, 0.0, 0.0, 0.0, depth=1.0)
        self.ctx.disable(self.mgl.BLEND)
        self.ctx.enable(self.mgl.DEPTH_TEST)
        matrices, params, froms = [], [], []
        identity = tuple(float(x) for x in np.eye(3).reshape(9))
        try:
            for i, light in enumerate(lights):
                m, depth, p = fit(light, points, tile)
                matrices.append(m)
                params.append(p)
                froms.append((*light["from"], light["w"]))
                self.ctx.viewport = ((i % grid) * tile, (i // grid) * tile, tile, tile)
                self.caster["light"].write(np.ascontiguousarray(m.T, "f4").tobytes())
                self.caster["planes"].value = (float(depth[0]), float(depth[1]))
                self.caster["picture"].value = 0
                self.caster["cut"].value = 0
                self.caster["me"].value = 0.0
                for part in solids:
                    self.caster["turn"].value = tuple(float(x) for x in part.axes.T.reshape(9))
                    self.caster["place"].value = tuple(float(x) for x in part.place)
                    self._solid(part.data).render(self.mgl.TRIANGLES)
                self.caster["turn"].value = identity
                self.caster["place"].value = (0.0, 0.0, 0.0)
                self.caster["cut"].value = 1
                for number, corners, uv, held in planes:
                    rows = np.array([(*corners[j], *uv[j]) for j in (0, 1, 3, 2)], "f4")      # (as a strip)
                    self.quad.write(rows.tobytes())
                    held.use(0)
                    self.caster["me"].value = float(number)
                    self.quad_vao.render(self.mgl.TRIANGLE_STRIP)
        finally:
            self.ctx.disable(self.mgl.DEPTH_TEST)
        pad = [np.zeros((4, 4))] * (MOST - len(matrices))
        self.texture = texture
        self.uniforms = {"smap_m": np.array([m.T for m in matrices + pad], "f4").tobytes(),
                         "smap_p": np.array(params + [(0.0,) * 4] * len(pad), "f4").tobytes(),
                         "smap_l": np.array(froms + [(0.0, 0.0, -1.0, 0.0)] * len(pad), "f4").tobytes(),
                         "smap_n": len(matrices), "smap_grid": grid}
        return True

    def use(self, program, unit):
        """Give program (one with SAMPLE in it) the maps built last, on texture unit `unit`."""
        held = self.uniforms
        if "smap" in program:
            program["smap"].value = unit
        for name in ("smap_m", "smap_p", "smap_l"):
            if name in program:
                program[name].write(held[name])
        for name in ("smap_n", "smap_grid"):
            if name in program:
                program[name].value = held[name]
        self.texture.use(unit)

    def receive(self, target, source, w, h, to_canvas, origin, across, down, number):
        """Draw the plane's layer `source` (a w x h texture) into framebuffer target with the shadows that fall on it. to_canvas:
        9 numbers (by columns), layer px -> its flat drawing's canvas px from the middle; origin, across, down: where that is in
        the world."""
        prog = self.receiver
        self.screen.write(np.array([0, 0, w, 0, 0, h, w, h], "f4").tobytes())
        target.use()
        self.ctx.viewport = (0, 0, w, h)
        self.ctx.disable(self.mgl.BLEND)
        self.use(prog, 1)
        values = {"size": (float(w), float(h)), "to_canvas": to_canvas, "origin": tuple(float(x) for x in origin),
                  "across": tuple(float(x) for x in across), "down": tuple(float(x) for x in down), "me": int(number), "tex": 0}
        for name, value in values.items():
            if name in prog:
                prog[name].value = value
        source.use(0)
        self.screen_vao.render(self.mgl.TRIANGLE_STRIP)
