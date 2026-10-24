bl_info = {
    "name": "Compositor to Hyprshade (GLSL)",
    "author": "Claude",
    "version": (2, 2, 0),
    "blender": (4, 2, 0),
    "location": "Compositor > Node menu > Export as Shader / Filter",
    "description": "Convert compositor node trees / node groups into screen shaders (Hyprshade, OBS, ShaderGlass) or KiaseCut filters",
    "category": "Node",
}

# ---------------------------------------------------------------------------
# Compositor -> Hyprshade converter
#
#  * Every node output becomes a GLSL function   T f<ctx>_<node>_<out>(vec2 uv)
#    so spatial nodes (Blur, Translate, Transform, Displace ...) just call
#    their upstream functions with a different uv.  Single pass, no buffers.
#  * Node groups are inlined; every instance gets its own context so group
#    inputs are bound to the parent's expressions.
#  * Menu / bool inputs that decide structure (Interpolation, Menu Switch, ...)
#    are resolved statically at export time, dead Switch branches are dropped.
#    A Switch / Index Switch driven by a computed value or a group input
#    (a KiaseCut parameter) stays switchable: it becomes a GLSL branch.
#  * The screen texture `tex` is: an Image node called "Input"; the group-input
#    color socket "Image" or "Input" of the exported tree / group (else its
#    first color input); and the "Image" / "Input" color socket of a group
#    node left unconnected.  So no image has to stay loaded in Blender.
#  * The result is taken from the Group Output node.
#
# Internal convention: uv in [0,1]^2 with Y UP (like Blender). Hyprland's
# v_texcoord is flipped with FLIP_Y (see the generated header).
#
# KiaseCut format: the same code wrapped as a filter for the KiaseCut editor.  The exported node group's
# inputs (other than the picture) become parameters you can change and keyframe in the editor:
#   Float -> float,  Integer -> int (IN_x_i),  Boolean -> bool (IN_x_b),  Color -> color (IN_x_c),
#   Vector -> vec3 (2D vector -> vec2, IN_x_v).  Min / Max of the group socket become the range of the editor's field.
#   Put the .glsl in <KiaseCut Library>/filters.  See kiasecut/filters/FORMAT.md in KiaseCut.
# ---------------------------------------------------------------------------

import re
import math

GLSL_TYPE = {"RGBA": "vec4", "VALUE": "float", "INT": "float",
             "BOOLEAN": "float", "VECTOR": "vec3", "INT_VECTOR": "vec3"}


def gtype(sock):
    return GLSL_TYPE.get(sock.type, "float")


def fl(v):
    s = "%.6f" % float(v)
    return s


def T(tpl, **kw):
    """Tiny template: replaces $name by kw[name] (longest names first)."""
    for k in sorted(kw, key=len, reverse=True):
        tpl = tpl.replace("$" + k, str(kw[k]))
    return tpl


def zero(t):
    return {"vec4": "vec4(0.0)", "vec3": "vec3(0.0)"}.get(t, "0.0")


def literal_value(v, t):
    if v is None or isinstance(v, str):
        return zero(t)
    if t == "float":
        try:
            return fl(v)
        except TypeError:
            return fl(sum(v) / max(len(v), 1))
    try:
        vals = [float(x) for x in v]
    except TypeError:
        vals = [float(v)] * 3
    if t == "vec4":
        while len(vals) < 3:
            vals.append(0.0)
        while len(vals) < 4:
            vals.append(1.0)
        return "vec4(%s)" % ", ".join(fl(x) for x in vals[:4])
    while len(vals) < 3:
        vals.append(0.0)
    return "vec3(%s)" % ", ".join(fl(x) for x in vals[:3])


def literal(sock):
    return literal_value(getattr(sock, "default_value", None), gtype(sock))


LUMA = "vec3(0.2126, 0.7152, 0.0722)"


def scene_fps():
    """Scene frame rate (fps / fps_base) as a GLSL float literal; 24 if there is no scene."""
    try:
        import bpy
        r = bpy.context.scene.render
        return fl(round(r.fps / (r.fps_base or 1.0), 4))
    except Exception:
        return "24.0"


# Export settings: (key, GLSL define, default, label, description).  "auto" values are decided at export.
SETTING_DEFS = [
    ("flip_y", "FLIP_Y", True, "Flip Y", "Hyprland's texture coordinates start at the top-left; turn off if the effect looks mirrored"),
    ("linearize", "LINEARIZE", True, "Linear light", "Run the effect in linear light like Blender does (screen is sRGB)"),
    ("composite", "COMPOSITE_OVER_SCREEN", "AUTO", "Transparent shows screen", "AUTO: on for generators that never read Input, off otherwise"),
    ("scene_fps", "SCENE_FPS", 0.0, "FPS", "Frame rate for the Scene Time node (0 = the scene's FPS)"),
    ("blur_samples", "BLUR_SAMPLES", 32, "Blur samples", "Upper limit of samples per pixel for Blur (chains and large radii use fewer automatically)"),
    ("blur_adapt", "BLUR_ADAPT", True, "Fewer blur samples for big radii", "Use fewer samples as the blur radius grows (faster, grainier)"),
    ("bloom_samples", "BLOOM_SAMPLES", 32, "Bloom samples", "Upper limit of samples per pixel for Bloom / Fog Glow"),
    ("sun_steps", "SUN_STEPS", 24, "Sun Beams steps", "Samples along each Sun Beams ray"),
    ("dilate_k", "DILATE_K", 5, "Dilate/Erode taps", "Taps per side for Dilate / Erode"),
    ("pixelate_taps", "PIXELATE_TAPS", 3, "Pixelate taps", "Samples per axis averaged inside a Pixelate block"),
    ("frame_rate", "FRAME_RATE", 60.0, "FrameCount rate (ShaderGlass)", "ShaderGlass only: how many frames per second its FrameCount advances (used by Scene Time)"),
    ("tex_scale", "TEX_SCALE", 1.0, "Texture scale", "Procedural texture coordinate scale (coordinates are -1..1 * scale)"),
]
DEFAULT_SETTINGS = {k: d for k, _, d, _, _ in SETTING_DEFS}


def apply_settings(code, st, auto_fps):
    """Rewrite the '#define NAME value' lines of the generated shader from the export settings."""
    for key, define, default, _, _ in SETTING_DEFS:
        v = st.get(key, default)
        if key == "composite" and str(v).upper() == "AUTO":
            continue
        if key == "composite":
            v = 1 if str(v).upper() in ("ON", "1", "TRUE") else 0
        if key == "scene_fps":
            v = float(v) or auto_fps
            v = "%.6f" % v
        elif isinstance(v, bool):
            v = int(v)
        elif isinstance(v, float):
            v = "%.6f" % v
        code = re.sub(r"(?m)^(#define %s )\S+" % define, lambda m_: m_.group(1) + str(v), code, count=1)
    return code


def coerce(expr, src, dst):
    if src == dst:
        return expr
    if src == "vec4":
        return ("dot((%s).rgb, %s)" % (expr, LUMA)) if dst == "float" else "(%s).rgb" % expr
    if src == "vec3":
        return ("dot(%s, vec3(1.0 / 3.0))" % expr) if dst == "float" else "vec4(%s, 1.0)" % expr
    # float
    return "vec4(vec3(%s), 1.0)" % expr if dst == "vec4" else "vec3(%s)" % expr


def norm(s):
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


def is_picture_name(name):
    """Group-input sockets called 'Image' or 'Input' carry the picture (screen / clip)."""
    return norm(name) in ("image", "input")


def valid_link(sock):
    for l in sock.links:
        if getattr(l, "is_muted", False) or not getattr(l, "is_valid", True):
            continue
        return l
    return None


def _bound(v):
    """A socket's min / max value, or None when Blender has none (it stores +-3.4e38 for 'unbounded')."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if abs(v) > 1.0e6 else v


def param_spec(it, name, t, val):
    """Description of a node-group input as an adjustable parameter (KiaseCut filters), or None.
    kind: float / int / bool / color / vec2 / vec3 (see kiasecut/filters/FORMAT.md)."""
    st = it.socket_type
    spec = {"name": name, "label": it.name, "t": t}
    if st.startswith("NodeSocketFloat"):
        spec["kind"] = "float"
    elif st.startswith("NodeSocketInt"):
        spec["kind"] = "int"
    elif st == "NodeSocketBool":
        spec["kind"] = "bool"
    elif st == "NodeSocketColor":
        spec["kind"] = "color"
    elif st.startswith("NodeSocketVector") and t == "vec3":
        spec["kind"] = "vec2" if isinstance(val, (tuple, list)) and len(val) == 2 else "vec3"   # Blender 5: 2D vectors
    else:
        return None
    spec["default"] = val
    spec["lo"], spec["hi"] = _bound(getattr(it, "min_value", None)), _bound(getattr(it, "max_value", None))
    return spec


class Ctx:
    """One instance of a node tree (root, or an inlined node group)."""
    def __init__(self, cid, tree, parent=None, pnode=None):
        self.id = cid
        self.tree = tree
        self.parent = parent
        self.pnode = pnode
        self.index = {n.name: i for i, n in enumerate(tree.nodes)}


class Bind:
    """Handler helper bound to (converter, ctx, node)."""
    def __init__(self, c, ctx, node):
        self.c, self.ctx, self.node = c, ctx, node

    def i(self, key, t="vec4", uv="uv"):
        return self.c.inp(self.ctx, self.node, key, t, uv)

    def has(self, key):
        return self.c.find_input(self.node, key) is not None

    def linked(self, key):
        s = self.c.find_input(self.node, key)
        return s is not None and valid_link(s) is not None

    def s(self, key, default=None):
        s = self.c.find_input(self.node, key)
        if s is None:
            return default
        v = self.c.static_sock(self.ctx, s)
        return default if v is None else v

    def menu(self, key, default=""):
        v = self.s(key, None)
        if v is None:
            v = getattr(self.node, norm(key), default)
        return norm(v)

    def flag(self, key, default=False):
        v = self.s(key, None)
        if v is None:
            return bool(getattr(self.node, norm(key), default))
        try:
            return bool(v)
        except Exception:
            return default

    def heavy(self):
        """Mark this node as running a sampling loop; returns a placeholder for its sample cap
        (filled in at assembly from how many such loops are chained with it)."""
        key = (self.ctx.id, self.node.name)
        tok = self.c.heavy_keys.setdefault(key, "@CAP%d@" % len(self.c.heavy_keys))
        return tok

    def warn(self, msg):
        self.c.warn("%s: %s" % (self.node.name, msg))


class Converter:
    def __init__(self, tree, hypr=True):
        self.tree = tree
        self.nid = 0
        self.funcs = []
        self.settings = dict(DEFAULT_SETTINGS)
        self.done = set()
        self.stack = []           # emit stack of (ctx.id, node.name)
        self.edges = {}           # consumer key -> set(producer keys)
        self.heavy_keys = {}      # key -> placeholder token (nodes that run a sampling loop)
        self.warnings = []
        self._warned = set()
        self.consts = []          # (name, decl) global constants (root group inputs, LUTs)
        self.params = []          # root group inputs that are not the image: dicts, see param_spec()
        self.root = self.new_ctx(tree)
        self.root_exprs = {}
        self.uses_input = False

    # -- infrastructure -----------------------------------------------------
    def new_ctx(self, tree, parent=None, pnode=None):
        self.nid += 1
        return Ctx(self.nid, tree, parent, pnode)

    def warn(self, msg):
        if msg not in self._warned:
            self._warned.add(msg)
            self.warnings.append(msg)

    @staticmethod
    def find_input(node, key):
        if isinstance(key, int):
            return node.inputs[key] if key < len(node.inputs) else None
        k = norm(key)
        for s in node.inputs:
            if s.name == key or s.identifier == key:
                return s
        for s in node.inputs:
            if norm(s.name) == k:
                return s
        for s in node.inputs:
            if norm(s.name).startswith(k):
                return s
        return None

    def fn(self, ctx, node, out_i):
        return "f%d_%d_%d" % (ctx.id, ctx.index[node.name], out_i)

    # -- link resolution ----------------------------------------------------
    def resolve_link(self, sock):
        """Follow the first valid link through reroutes. -> (link, src_node) or (None, None)."""
        link = valid_link(sock)
        if link is None:
            return None, None
        src = link.from_node
        while src.bl_idname == "NodeReroute":
            nxt = valid_link(src.inputs[0])
            if nxt is None:
                return None, src
            link, src = nxt, nxt.from_node
        return link, src

    def static_sock(self, ctx, sock):
        """Python value of a socket if it is constant at export time."""
        link, src = self.resolve_link(sock)
        if link is None:
            if src is not None:  # dangling reroute
                return self._dv(src.inputs[0])
            return self._dv(sock)
        if src.bl_idname == "NodeGroupInput":
            j = list(src.outputs).index(link.from_socket)
            if ctx.parent is not None:
                ps = ctx.pnode.inputs[j] if j < len(ctx.pnode.inputs) else None
                return self.static_sock(ctx.parent, ps) if ps is not None else None
            return self.root_defaults.get(j, self._dv(sock))
        if src.bl_idname in SWITCHES and not src.mute and link.from_socket == src.outputs[0]:
            k = switch_pick(self, ctx, src)
            if k is not None and k >= 0:
                return self.static_sock(ctx, src.inputs[k])
        return self._dv(sock)

    def const_sock(self, ctx, sock):
        """Like static_sock(), but None when the value is computed per pixel or comes from a parameter
        (a root group input, adjustable in the KiaseCut editor)."""
        link, src = self.resolve_link(sock)
        if link is None:
            return self._dv(src.inputs[0] if src is not None else sock)
        if src.bl_idname == "NodeGroupInput":
            j = list(src.outputs).index(link.from_socket)
            if ctx.parent is not None:
                ps = ctx.pnode.inputs[j] if j < len(ctx.pnode.inputs) else None
                if ps is None or self.screen_sock(ps):
                    return None
                return self.const_sock(ctx.parent, ps)
            expr = self.root_exprs.get(j)          # the picture, a parameter, or zero (menus, strings)
            return self.root_defaults.get(j) if expr in (None, zero(gtype(link.from_socket))) else None
        if src.mute:
            return None
        if src.bl_idname in ("CompositorNodeValue", "ShaderNodeValue"):
            return self._dv(link.from_socket)
        if src.bl_idname in SWITCHES and link.from_socket == src.outputs[0]:
            k = switch_pick(self, ctx, src)
            if k is not None:
                return self.const_sock(ctx, src.inputs[k]) if k >= 0 else 0.0
        return None

    def screen_sock(self, sock):
        """An unconnected 'Image' / 'Input' color socket of a group node: the group reads the picture."""
        return (sock.node.bl_idname == "CompositorNodeGroup" and sock.type == "RGBA"
                and is_picture_name(sock.name) and self.resolve_link(sock)[0] is None)

    @staticmethod
    def _dv(sock):
        v = getattr(sock, "default_value", None)
        if v is None:
            return None
        if isinstance(v, (str, bool, int, float)):
            return v
        try:
            return tuple(v)
        except TypeError:
            return v

    # -- input resolution -> GLSL expression ----------------------------------
    def inp(self, ctx, node, key, want, uv="uv"):
        sock = self.find_input(node, key)
        if sock is None:
            return zero(want)
        link, src = self.resolve_link(sock)
        if link is None:
            tgt = src.inputs[0] if src is not None else sock
            return coerce(literal(tgt), gtype(tgt), want)
        out_i = list(src.outputs).index(link.from_socket)
        if self.stack:
            self.edges.setdefault(self.stack[-1], set()).add((ctx.id, src.name))
        self.emit(ctx, src)
        call = "%s(%s)" % (self.fn(ctx, src, out_i), uv)
        return coerce(call, gtype(link.from_socket), want)

    # -- emission -------------------------------------------------------------
    def emit(self, ctx, node):
        key = (ctx.id, node.name)
        if key in self.done:
            return
        self.done.add(key)
        h = Bind(self, ctx, node)
        handler = HANDLERS.get(node.bl_idname)
        self.stack.append(key)
        try:
            if getattr(node, "mute", False) and node.bl_idname != "NodeReroute":
                bodies = self.passthrough(h)
            elif handler is None:
                self.warn("Unsupported node '%s' (%s): output is 0" % (node.name, node.bl_idname))
                bodies = ["return %s;" % zero(gtype(o)) for o in node.outputs]
            else:
                bodies = handler(h)
        except Exception as e:  # keep exporting, but tell the user
            self.warn("Node '%s' (%s) failed: %s" % (node.name, node.bl_idname, e))
            bodies = ["return %s;" % zero(gtype(o)) for o in node.outputs]
        self.stack.pop()
        for i, body in enumerate(bodies):
            if body is None or i >= len(node.outputs):
                continue
            t = gtype(node.outputs[i])
            if "return" not in body:
                body = "return %s;" % body
            code = "// %s [%s]\n%s %s(vec2 uv) {\n    %s\n}\n" % (
                node.name.encode("ascii", "replace").decode(), node.bl_idname, t,
                self.fn(ctx, node, i), body.replace("\n", "\n    "))
            self.funcs.append(code)

    def passthrough(self, h):
        res = []
        for o in h.node.outputs:
            t = gtype(o)
            pick = None
            for k, s in enumerate(h.node.inputs):
                if s.enabled and s.type == o.type:
                    pick = k
                    break
            res.append("return %s;" % (h.i(pick, t) if pick is not None else zero(t)))
        return res

    # -- top level --------------------------------------------------------------
    root_defaults = {}

    def prepare_root(self):
        """Bind group-input sockets of the root tree (when it is a node group)."""
        tree = self.tree
        self.root_defaults = {}
        if not hasattr(tree, "interface"):
            return
        items = [i for i in tree.interface.items_tree
                 if i.item_type == "SOCKET" and i.in_out == "INPUT"]
        gin = next((n for n in tree.nodes if n.bl_idname == "NodeGroupInput"), None)
        image_j = None
        for j, it in enumerate(items):
            if it.socket_type == "NodeSocketColor":
                if image_j is None or is_picture_name(it.name):
                    image_j = j
                    if is_picture_name(it.name):
                        break
        used = set()
        for j, it in enumerate(items):
            dv = getattr(it, "default_value", None)
            try:
                dv = tuple(dv)
            except TypeError:
                pass
            self.root_defaults[j] = dv
            if gin is None or j >= len(gin.outputs):
                continue
            out = gin.outputs[j]
            t = gtype(out)
            if j == image_j:
                self.root_exprs[j] = coerce("input_tex(uv)", "vec4", t)
                self.uses_input = True
                continue
            if out.type in ("MENU", "STRING", "CUSTOM") or it.socket_type in ("NodeSocketFont", "NodeSocketString", "NodeSocketMenu"):
                self.root_exprs[j] = zero(t)
                continue
            name = "IN_" + re.sub(r"\W", "_", it.name.encode("ascii", "ignore").decode() or "x")
            base, k = name, 1
            while name in used:
                k += 1
                name = "%s_%d" % (base, k)
            used.add(name)
            val = dv
            if isinstance(val, bool):
                val = float(val)
            line = "const %s %s = %s;  // group input '%s'" % (t, name, literal_value(val, t), it.name)
            self.consts.append(line)
            self.root_exprs[j] = name
            spec = param_spec(it, name, t, val)
            if spec is not None:
                spec["const_line"] = line
                self.params.append(spec)

    def find_output(self):
        tree = self.tree
        outs = [n for n in tree.nodes if n.bl_idname == "NodeGroupOutput"]
        if outs:
            act = [n for n in outs if getattr(n, "is_active_output", True)]
            return (act or outs)[0]
        for pref in ("CompositorNodeComposite", "CompositorNodeViewer"):
            for n in tree.nodes:
                if n.bl_idname == pref:
                    return n
        raise RuntimeError("No Group Output / Composite / Viewer node found")

    def convert(self):
        self.prepare_root()
        out = self.find_output()
        key = 0
        for j, s in enumerate(out.inputs):
            if s.type != "CUSTOM":
                key = j
                if norm(s.name) in ("image", "result"):
                    break
        final = self.inp(self.root, out, key, "vec4")
        return self.assemble(final)

    def assemble(self, final):
        head = ["#version 300 es", "precision highp float;", "precision highp int;", "",
                "// Generated by Compositor to Hyprshade (Blender node tree -> GLSL ES 3.00)",
                "// Warnings:" if self.warnings else "// No warnings."]
        head += ["//   - " + w for w in self.warnings]
        head += ["", "in vec2 v_texcoord;", "uniform sampler2D tex;", "uniform float time;   // Hyprland: seconds since start (Scene Time node)", "out vec4 fragColor;", ""]
        body = "\n".join(self.consts) + "\n" if self.consts else ""
        main = ("\nvoid main() {\n"
                "    vec2 uv = vec2(v_texcoord.x, (FLIP_Y != 0) ? 1.0 - v_texcoord.y : v_texcoord.y);\n"
                "    vec4 c = %s;\n"
                "#if COMPOSITE_OVER_SCREEN\n"
                "    c.rgb += input_tex(uv).rgb * (1.0 - clamp(c.a, 0.0, 1.0));   // premultiplied 'over' the screen\n"
                "#endif\n"
                "#if LINEARIZE\n"
                "    c.rgb = lin_to_srgb(c.rgb);\n"
                "#endif\n"
                "    fragColor = vec4(clamp(c.rgb, 0.0, 1.0), 1.0);\n}\n") % final
        prelude = PRELUDE.replace("$COMP", "0" if self.uses_input else "1").replace("$FPS", scene_fps())
        text = "\n".join(head) + prelude + "\n" + body + "\n" + "\n".join(self.funcs) + main
        return self.fill_caps(text)

    def fill_caps(self, text):
        """Sample budget: a blur whose result is blurred again (or feeds a glare, ...) is evaluated once per
        downstream sample, so the cost multiplies along a chain.  Spread a fixed budget over the longest
        chain of sampling loops that passes through each node."""
        if not self.heavy_keys:
            return text
        memo_up, memo_dn = {}, {}
        cons = {}
        for c, ps in self.edges.items():
            for p in ps:
                cons.setdefault(p, set()).add(c)

        def up(k):
            if k not in memo_up:
                memo_up[k] = 0
                memo_up[k] = (1 if k in self.heavy_keys else 0) + max([up(p) for p in self.edges.get(k, ())] or [0])
            return memo_up[k]

        def dn(k):
            if k not in memo_dn:
                memo_dn[k] = 0
                memo_dn[k] = (1 if k in self.heavy_keys else 0) + max([dn(c) for c in cons.get(k, ())] or [0])
            return memo_dn[k]
        for k, tok in self.heavy_keys.items():
            depth = max(1, up(k) + dn(k) - 1)
            budget = 16.0 * max(self.settings.get("blur_samples", 32), 1)   # product of samples allowed along a chain of loops
            cap = int(max(6, round(budget ** (1.0 / depth))))
            text = text.replace(tok, str(cap))
        return text


# ---------------------------------------------------------------------------
# GLSL prelude
# ---------------------------------------------------------------------------
PRELUDE = r"""
// ---- tunables ---------------------------------------------------------------
#define FLIP_Y 1          // Hyprland's v_texcoord is top-left origin. Set 0 if Y effects look mirrored.
#define COMPOSITE_OVER_SCREEN $COMP   // 1: transparent parts of the result show the screen, 0: black
#define LINEARIZE 1               // screen is sRGB; run the effect in linear light like Blender, then encode again
#define PIXELATE_TAPS 3    // samples per axis averaged inside a pixelate block
#define SCENE_FPS $FPS     // Scene Time node: Frame = floor(time * SCENE_FPS)  (taken from the Blender scene's FPS at export)
#define BLOOM_SAMPLES 32   // bloom: samples per pixel
#define BLUR_ADAPT 1       // 1: blur uses fewer samples as its radius grows (faster, a bit grainier); 0: always the full budget
#define BLUR_SAMPLES 32    // blur: samples per pixel (cost ~ linear; 16 = fast/grainy, 64 = smooth)
#define DILATE_K 5        // dilate/erode taps per side
#define SUN_STEPS 24      // sun beams samples
#define TEX_SCALE 1.0     // procedural texture coordinate scale (coords are -1..1 * TEX_SCALE)

vec2 res() { return vec2(textureSize(tex, 0)); }

vec3 srgb_to_lin(vec3 c) { return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(vec3(0.04045), c)); }
vec3 lin_to_srgb(vec3 c) { c = clamp(c, 0.0, 1.0); return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(vec3(0.0031308), c)); }

vec4 input_tex(vec2 uv) {
    if (uv.x < 0.0 || uv.y < 0.0 || uv.x > 1.0 || uv.y > 1.0) return vec4(0.0);
    vec2 t = vec2(uv.x, (FLIP_Y != 0) ? 1.0 - uv.y : uv.y);
    vec4 c = texture(tex, t);
#if LINEARIZE
    c.rgb = srgb_to_lin(c.rgb);   // Blender's compositor works in scene-linear
#endif
    return c;
}

float inside(vec2 uv) { return (uv.x >= 0.0 && uv.y >= 0.0 && uv.x <= 1.0 && uv.y <= 1.0) ? 1.0 : 0.0; }

// extension modes: 0 clip, 1 extend, 2 repeat, 3 mirror. returns (uv', insideMask)
float ext1(float t, int m) {
    if (m == 1) return clamp(t, 0.0, 1.0);
    if (m == 2) return fract(t);
    if (m == 3) { float k = mod(t, 2.0); return k > 1.0 ? 2.0 - k : k; }
    return t;
}
vec3 ext_uv(vec2 uv, int mx, int my) {
    float mask = ((mx == 0 && (uv.x < 0.0 || uv.x > 1.0)) || (my == 0 && (uv.y < 0.0 || uv.y > 1.0))) ? 0.0 : 1.0;
    return vec3(ext1(uv.x, mx), ext1(uv.y, my), mask);
}
vec2 snap_px(vec2 uv) { return (floor(uv * res()) + 0.5) / res(); }

float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }

// glare highlight extraction (soft knee on max channel; fitted against Blender)
vec3 glare_hl(vec3 c, float thr, float sm) {
    float m = max(c.r, max(c.g, c.b));
    float knee = max(min(thr, sm), 0.0);
    float soft = clamp(m - thr + knee, 0.0, 2.0 * knee);
    soft = soft * soft / (4.0 * knee + 1e-5);
    float contrib = max(soft, m - thr) / max(m, 1e-5);
    return c * contrib;
}

vec3 rgb2hsv(vec3 c) {
    vec4 K = vec4(0.0, -1.0/3.0, 2.0/3.0, -1.0);
    vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
    float d = q.x - min(q.w, q.y);
    float e = 1.0e-10;
    return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}
vec3 hsv2rgb(vec3 c) {
    vec3 p = abs(fract(c.xxx + vec3(0.0, 2.0/3.0, 1.0/3.0)) * 6.0 - 3.0);
    return c.z * mix(vec3(1.0), clamp(p - 1.0, 0.0, 1.0), c.y);
}
vec3 rgb2hsl(vec3 c) {
    float mx = max(c.r, max(c.g, c.b)), mn = min(c.r, min(c.g, c.b));
    float l = 0.5 * (mx + mn);
    vec3 hsv = rgb2hsv(c);
    float s = (mx == mn) ? 0.0 : (mx - mn) / (1.0 - abs(2.0 * l - 1.0) + 1e-10);
    return vec3(hsv.x, s, l);
}
vec3 hsl2rgb(vec3 c) {
    float a = c.y * min(c.z, 1.0 - c.z);
    vec3 k = mod(vec3(0.0, 8.0, 4.0) + c.x * 12.0, 12.0);
    return c.z - a * clamp(min(k - 3.0, 9.0 - k), -1.0, 1.0);
}

float safe_div(float a, float b) { return b != 0.0 ? a / b : 0.0; }
float safe_pow(float a, float b) { return (a >= 0.0) ? pow(a, b) : 0.0; }
float safe_log(float a, float b) { return (a > 0.0 && b > 0.0) ? log(a) / log(b) : 0.0; }
float safe_mod(float a, float b) { return b != 0.0 ? a - b * trunc(a / b) : 0.0; }
float fl_mod(float a, float b) { return b != 0.0 ? a - b * floor(a / b) : 0.0; }
float wrap_v(float v, float mx, float mn) { float r = mx - mn; return r != 0.0 ? v - r * floor((v - mn) / r) : mn; }
float ping_pong(float v, float s) { return s != 0.0 ? abs(fract((v - s) / (s * 2.0)) * s * 2.0 - s) : 0.0; }
float snap_v(float v, float s) { return s != 0.0 ? floor(v / s) * s : 0.0; }
vec3 safe_div3(vec3 a, vec3 b) { return vec3(safe_div(a.x, b.x), safe_div(a.y, b.y), safe_div(a.z, b.z)); }

// ---- procedural noise (not bit-identical with Blender) ------------------------
float hash11(float p) { p = fract(p * 0.1031); p *= p + 33.33; p *= p + p; return fract(p); }
float hash31(vec3 p) { p = fract(p * 0.1031); p += dot(p, p.zyx + 31.32); return fract((p.x + p.y) * p.z); }
vec3 hash33(vec3 p) {
    p = fract(p * vec3(0.1031, 0.1030, 0.0973));
    p += dot(p, p.yxz + 33.33);
    return fract((p.xxy + p.yxx) * p.zyx);
}
float white1(float x) { return hash11(floor(x * 4096.0) * 0.0173 + 0.5); }
float white2(vec2 p) { return hash31(vec3(floor(p * 4096.0), 1.7)); }
float white3(vec3 p) { return hash31(floor(p * 4096.0)); }
float white4(vec4 p) { return hash31(floor(p.xyz * 4096.0) + floor(p.w * 4096.0) * 7.31); }

// Blender's perlin noise (Jenkins lookup3 hash + gradient noise), 3D and 4D
uint rotl(uint x, uint k) { return (x << k) | (x >> (32u - k)); }
void jmix(inout uint a, inout uint b, inout uint c) {
    a -= c; a ^= rotl(c, 4u);  c += b;
    b -= a; b ^= rotl(a, 6u);  a += c;
    c -= b; c ^= rotl(b, 8u);  b += a;
    a -= c; a ^= rotl(c, 16u); c += b;
    b -= a; b ^= rotl(a, 19u); a += c;
    c -= b; c ^= rotl(b, 4u);  b += a;
}
void jfinal(inout uint a, inout uint b, inout uint c) {
    c ^= b; c -= rotl(b, 14u);
    a ^= c; a -= rotl(c, 11u);
    b ^= a; b -= rotl(a, 25u);
    c ^= b; c -= rotl(b, 16u);
    a ^= c; a -= rotl(c, 4u);
    b ^= a; b -= rotl(a, 14u);
    c ^= b; c -= rotl(b, 24u);
}
uint hash3(int x, int y, int z) {
    uint a, b, c; a = b = c = 0xdeadbeefu + (3u << 2u) + 13u;
    a += uint(x); b += uint(y); c += uint(z);
    jfinal(a, b, c); return c;
}
uint hash4(int x, int y, int z, int w) {
    uint a, b, c; a = b = c = 0xdeadbeefu + (4u << 2u) + 13u;
    a += uint(x); b += uint(y); c += uint(z);
    jmix(a, b, c);
    a += uint(w);
    jfinal(a, b, c); return c;
}
float nfade(float t) { return t * t * t * (t * (t * 6.0 - 15.0) + 10.0); }
float ngrad3(uint h, float x, float y, float z) {
    h &= 15u;
    float u = h < 8u ? x : y;
    float vt = (h == 12u || h == 14u) ? x : z;
    float v = h < 4u ? y : vt;
    return (((h & 1u) != 0u) ? -u : u) + (((h & 2u) != 0u) ? -v : v);
}
float ngrad4(uint h, float x, float y, float z, float w) {
    h &= 31u;
    float u = h < 24u ? x : y;
    float v = h < 16u ? y : z;
    float s = h < 8u ? z : w;
    return (((h & 1u) != 0u) ? -u : u) + (((h & 2u) != 0u) ? -v : v) + (((h & 4u) != 0u) ? -s : s);
}
float gnoise3(vec3 p) {
    vec3 fl3 = floor(p);
    ivec3 i = ivec3(fl3);
    vec3 f = p - fl3;
    float u = nfade(f.x), v = nfade(f.y), w = nfade(f.z);
    float r = mix(
        mix(mix(ngrad3(hash3(i.x, i.y, i.z), f.x, f.y, f.z), ngrad3(hash3(i.x + 1, i.y, i.z), f.x - 1.0, f.y, f.z), u),
            mix(ngrad3(hash3(i.x, i.y + 1, i.z), f.x, f.y - 1.0, f.z), ngrad3(hash3(i.x + 1, i.y + 1, i.z), f.x - 1.0, f.y - 1.0, f.z), u), v),
        mix(mix(ngrad3(hash3(i.x, i.y, i.z + 1), f.x, f.y, f.z - 1.0), ngrad3(hash3(i.x + 1, i.y, i.z + 1), f.x - 1.0, f.y, f.z - 1.0), u),
            mix(ngrad3(hash3(i.x, i.y + 1, i.z + 1), f.x, f.y - 1.0, f.z - 1.0), ngrad3(hash3(i.x + 1, i.y + 1, i.z + 1), f.x - 1.0, f.y - 1.0, f.z - 1.0), u), v), w);
    return 0.9820 * r;
}
float gnoise4(vec4 p) {
    vec4 fl4 = floor(p);
    ivec4 i = ivec4(fl4);
    vec4 f = p - fl4;
    float u = nfade(f.x), v = nfade(f.y), t = nfade(f.z), s = nfade(f.w);
    float c[16];
    for (int k = 0; k < 16; k++) {
        int dx = k & 1, dy = (k >> 1) & 1, dz = (k >> 2) & 1, dw = (k >> 3) & 1;
        c[k] = ngrad4(hash4(i.x + dx, i.y + dy, i.z + dz, i.w + dw), f.x - float(dx), f.y - float(dy), f.z - float(dz), f.w - float(dw));
    }
    float r0 = mix(mix(mix(c[0], c[1], u), mix(c[2], c[3], u), v), mix(mix(c[4], c[5], u), mix(c[6], c[7], u), v), t);
    float r1 = mix(mix(mix(c[8], c[9], u), mix(c[10], c[11], u), v), mix(mix(c[12], c[13], u), mix(c[14], c[15], u), v), t);
    return 0.8344 * mix(r0, r1, s);
}
float fbm3(vec3 p, float detail, float rough, float lac, bool normalize_) {
    float sum = 0.0, amp = 1.0, maxamp = 0.0;
    detail = clamp(detail, 0.0, 15.0);
    int n = int(floor(detail));
    for (int i = 0; i <= 15; i++) {
        if (i > n) break;
        float t = gnoise3(p);
        sum += t * amp; maxamp += amp; amp *= rough; p *= lac;
    }
    float rmd = detail - floor(detail);
    if (rmd > 0.0) {
        float t = gnoise3(p);
        float s2 = sum + t * amp, m2 = maxamp + amp;
        return normalize_ ? mix(0.5 * sum / maxamp + 0.5, 0.5 * s2 / m2 + 0.5, rmd) : mix(sum, s2, rmd);
    }
    return normalize_ ? 0.5 * sum / maxamp + 0.5 : sum;
}
float fbm4(vec4 p, float detail, float rough, float lac, bool normalize_) {
    float sum = 0.0, amp = 1.0, maxamp = 0.0;
    detail = clamp(detail, 0.0, 15.0);
    int n = int(floor(detail));
    for (int i = 0; i <= 15; i++) {
        if (i > n) break;
        float t = gnoise4(p);
        sum += t * amp; maxamp += amp; amp *= rough; p *= lac;
    }
    float rmd = detail - floor(detail);
    if (rmd > 0.0) {
        float t = gnoise4(p);
        float s2 = sum + t * amp, m2 = maxamp + amp;
        return normalize_ ? mix(0.5 * sum / maxamp + 0.5, 0.5 * s2 / m2 + 0.5, rmd) : mix(sum, s2, rmd);
    }
    return normalize_ ? 0.5 * sum / maxamp + 0.5 : sum;
}

vec3 tex_co(vec2 uv) { vec2 R = res(); return vec3((uv * 2.0 - 1.0) * R / max(R.x, R.y) * TEX_SCALE, 0.0); }

float lut_eval(float lut[64], float x) {
    float t = clamp(x, 0.0, 1.0) * 63.0;
    int i = int(floor(t));
    int j = min(i + 1, 63);
    return mix(lut[i], lut[j], t - float(i));
}
"""


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _group_input(h):
    c, ctx = h.c, h.ctx
    res = []
    for j, o in enumerate(h.node.outputs):
        t = gtype(o)
        if o.type == "CUSTOM":
            res.append(None)
        elif ctx.parent is not None:
            ps = ctx.pnode.inputs[j] if j < len(ctx.pnode.inputs) else None
            if ps is not None and c.screen_sock(ps):
                c.uses_input = True
                res.append("return %s;" % coerce("input_tex(uv)", "vec4", t))
            else:
                res.append("return %s;" % c.inp(ctx.parent, ctx.pnode, j, t))
        else:
            res.append("return %s;" % c.root_exprs.get(j, zero(t)))
    return res


def _group(h):
    c = h.c
    tree = getattr(h.node, "node_tree", None)
    if tree is None:
        h.warn("empty node group")
        return ["return %s;" % zero(gtype(o)) for o in h.node.outputs]
    # guard against recursion
    p = h.ctx
    while p is not None:
        if p.tree == tree:
            h.warn("recursive node group '%s'" % tree.name)
            return ["return %s;" % zero(gtype(o)) for o in h.node.outputs]
        p = p.parent
    sub = c.new_ctx(tree, h.ctx, h.node)
    outs = [n for n in tree.nodes if n.bl_idname == "NodeGroupOutput"]
    if not outs:
        return ["return %s;" % zero(gtype(o)) for o in h.node.outputs]
    gout = ([n for n in outs if getattr(n, "is_active_output", True)] or outs)[0]
    res = []
    for j, o in enumerate(h.node.outputs):
        if o.type == "CUSTOM":
            res.append(None)
        else:
            res.append("return %s;" % c.inp(sub, gout, j, gtype(o)))
    return res


def _reroute(h):
    return [h.i(0, gtype(h.node.outputs[0]))]


SWITCHES = ("GeometryNodeSwitch", "CompositorNodeSwitch", "GeometryNodeIndexSwitch", "GeometryNodeMenuSwitch",
            "CompositorNodeSwitchView")


def _num(v):
    if isinstance(v, (tuple, str)) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _switch_items(node):
    """Indices of the data inputs of an Index / Menu Switch (without the selector and the '+' socket)."""
    return [k for k, s in enumerate(node.inputs) if k > 0 and s.type != "CUSTOM"]


def switch_pick(c, ctx, node):
    """Input index a switch-type node passes to its output when the choice is known at export time;
    -1 when it passes nothing (output 0), None when the choice is made per pixel / by a parameter."""
    idn = node.bl_idname
    if idn == "CompositorNodeSwitchView":
        return 0                                  # no multi-view in a screen shader: the first (left) view
    if idn == "GeometryNodeMenuSwitch":
        v = c.static_sock(ctx, node.inputs[0])    # menus are always fixed at export
        names = [it.name for it in node.enum_items]
        items = _switch_items(node)
        if v in names and names.index(v) < len(items):
            return items[names.index(v)]
        return -1
    if idn == "GeometryNodeIndexSwitch":
        v = _num(c.const_sock(ctx, node.inputs[0]))
        if v is None:
            return None
        items = _switch_items(node)
        k = int(math.floor(v + 0.5))
        return items[k] if 0 <= k < len(items) else -1
    sw = c.find_input(node, "Switch")
    if sw is None:                                # Blender < 4.5: 'check' property, inputs Off / On
        return 1 if getattr(node, "check", False) else 0
    v = _num(c.const_sock(ctx, sw))
    if v is None:
        return None
    j = list(node.inputs).index(sw)
    return j + 2 if v > 0.0 else j + 1


def _switch(h):
    """Switch (bool), Index Switch, Menu Switch, Switch View.  A choice fixed at export only emits the chosen
    branch; one made by a computed value or a group-input parameter becomes a GLSL branch."""
    node, t = h.node, gtype(h.node.outputs[0])
    k = switch_pick(h.c, h.ctx, node)
    flags = []
    if node.bl_idname == "GeometryNodeMenuSwitch":   # extra outputs: one boolean per item, 1 for the chosen one
        flags = ["1.0" if k == j else "0.0" for j in _switch_items(node)]
    if k is not None:
        return [h.i(k, t) if k >= 0 else zero(t)] + flags
    if node.bl_idname == "GeometryNodeIndexSwitch":
        lines = ["int i = int(floor(%s + 0.5));" % h.i(0, "float")]
        lines += ["if (i == %d) return %s;" % (n, h.i(j, t)) for n, j in enumerate(_switch_items(node))]
        lines.append("return %s;" % zero(t))
        return ["\n".join(lines)]
    j = list(node.inputs).index(h.c.find_input(node, "Switch"))
    return ["(%s) > 0.0 ? %s : %s" % (h.i(j, "float"), h.i(j + 2, t), h.i(j + 1, t))]


# ---- inputs -----------------------------------------------------------------

def _is_input_name(node):
    img = getattr(node, "image", None)
    names = [getattr(img, "name", ""), node.name, getattr(node, "label", "")]
    return any(n == "Input" for n in names)


def _image_node(h):
    if _is_input_name(h.node):
        h.c.uses_input = True
        return ["input_tex(uv)", "input_tex(uv).a"]
    h.warn("Image node '%s' is not named 'Input' -> transparent" % h.node.name)
    return ["vec4(0.0)", "0.0"]


def _render_layers(h):
    res = []
    h.c.uses_input = True
    for o in h.node.outputs:
        if o.name == "Image":
            res.append("input_tex(uv)")
        elif o.name == "Alpha":
            res.append("input_tex(uv).a")
        else:
            res.append("return %s;" % zero(gtype(o)))
    return res


def _rgb(h):
    return [literal(h.node.outputs[0])]


_value = _rgb


def _scene_time(h):
    return ["time", "floor(time * SCENE_FPS)"]


def _imageinfo(h):
    r = "vec3(res(), 0.0)"
    return [r, r, "vec3(0.0)", "0.0", "vec3(1.0)"]


def _string_to_image(h):
    h.warn("Text rendering (String to Image) cannot be done in a shader -> transparent")
    return ["return %s;" % zero(gtype(o)) for o in h.node.outputs]


# ---- color / mixing -------------------------------------------------------------

BLEND = {
    "mix": "b",
    "add": "a + b",
    "multiply": "a * b",
    "subtract": "a - b",
    "screen": "vec3(1.0) - (vec3(1.0) - b) * (vec3(1.0) - a)",
    "divide": "safe_div3(a, b)",
    "difference": "abs(a - b)",
    "darken": "min(a, b)",
    "lighten": "max(a, b)",
    "overlay": "mix(2.0*a*b, vec3(1.0) - 2.0*(vec3(1.0)-a)*(vec3(1.0)-b), step(vec3(0.5), a))",
    "dodge": "mix(a, min(a / max(vec3(1.0) - b, vec3(1e-6)), vec3(1e4)), step(vec3(1e-6), a))",
    "color_dodge": "mix(a, min(a / max(vec3(1.0) - b, vec3(1e-6)), vec3(1e4)), step(vec3(1e-6), a))",
    "burn": "vec3(1.0) - min((vec3(1.0) - a) / max(b, vec3(1e-6)), vec3(1e4))",
    "color_burn": "vec3(1.0) - min((vec3(1.0) - a) / max(b, vec3(1e-6)), vec3(1e4))",
    "soft_light": "mix(2.0*a*b + a*a*(vec3(1.0)-2.0*b), sqrt(a)*(2.0*b-vec3(1.0)) + 2.0*a*(vec3(1.0)-b), step(vec3(0.5), b))",
    "linear_light": "a + 2.0*b - vec3(1.0)",
    "exclusion": "a + b - 2.0*a*b",
    "hue": "hsv_hue(a, b)",
    "saturation": "hsv_sat(a, b)",
    "value": "hsv_val(a, b)",
    "color": "hsv_col(a, b)",
}

BLEND_FUNCS = """vec3 hsv_hue(vec3 a, vec3 b) { vec3 ha = rgb2hsv(a), hb = rgb2hsv(b); return hb.y != 0.0 ? hsv2rgb(vec3(hb.x, ha.y, ha.z)) : a; }
vec3 hsv_sat(vec3 a, vec3 b) { vec3 ha = rgb2hsv(a), hb = rgb2hsv(b); return ha.y != 0.0 ? hsv2rgb(vec3(ha.x, hb.y, ha.z)) : a; }
vec3 hsv_val(vec3 a, vec3 b) { vec3 ha = rgb2hsv(a), hb = rgb2hsv(b); return hsv2rgb(vec3(ha.x, ha.y, hb.z)); }
vec3 hsv_col(vec3 a, vec3 b) { vec3 ha = rgb2hsv(a), hb = rgb2hsv(b); return hb.y != 0.0 ? hsv2rgb(vec3(hb.x, hb.y, ha.z)) : a; }
"""


def _mix_body(h, fac, c1, c2, bt, clamp_fac, clamp_res, use_alpha=False):
    expr = BLEND.get(bt)
    if expr is None:
        h.warn("blend mode '%s' not implemented, using Mix" % bt)
        expr = "b"
    if bt in ("hue", "saturation", "value", "color"):
        h.c.need_blend_funcs = True
    lines = ["vec4 c1 = %s;" % c1, "vec4 c2 = %s;" % c2, "float f = %s;" % fac]
    if clamp_fac:
        lines.append("f = clamp(f, 0.0, 1.0);")
    if use_alpha:
        lines.append("f *= c2.a;")
    lines.append("vec3 a = c1.rgb, b = c2.rgb;")
    lines.append("vec3 r = mix(a, %s, f);" % expr)
    if clamp_res:
        lines.append("r = clamp(r, 0.0, 1.0);")
    lines.append("return vec4(r, c1.a);")
    return "\n".join(lines)


def _mix_rgb(h):
    return [_mix_body(h, h.i(0, "float"), h.i(1), h.i(2), norm(getattr(h.node, "blend_type", "MIX")),
                      True, getattr(h.node, "use_clamp", False), getattr(h.node, "use_alpha", False))]


def _mix_shader(h):
    dt = getattr(h.node, "data_type", "RGBA")
    if dt != "RGBA":
        h.warn("Mix node: only RGBA mode supported")
    body = _mix_body(h, h.i(0, "float"), h.i(6), h.i(7), norm(getattr(h.node, "blend_type", "MIX")),
                     getattr(h.node, "clamp_factor", True), getattr(h.node, "clamp_result", False))
    return [None, None, body]


def _invert(h):
    col = h.i("Color", "vec4")
    fac = h.i("Factor", "float")
    rgb = h.flag("Invert Color", True)
    al = h.flag("Invert Alpha", False)
    return ["vec4 c = %s;\nvec4 inv = vec4(%s, %s);\nreturn mix(c, inv, clamp(%s, 0.0, 1.0));" % (
        col, "vec3(1.0) - c.rgb" if rgb else "c.rgb", "1.0 - c.a" if al else "c.a", fac)]


def _posterize(h):
    # Blender: steps clamped to [2, 1024], rgb = floor(rgb * steps) / steps, alpha untouched
    return ["vec4 c = %s;\nfloat st = clamp(%s, 2.0, 1024.0);\nreturn vec4(floor(c.rgb * st) / st, c.a);" % (
        h.i("Image", "vec4"), h.i("Steps", "float"))]


def _exposure(h):
    return ["vec4 c = %s;\nreturn vec4(c.rgb * exp2(%s), c.a);" % (h.i("Image", "vec4"), h.i("Exposure", "float"))]


def _gamma(h):
    return ["vec4 c = %s;\nreturn vec4(pow(max(c.rgb, vec3(0.0)), vec3(%s)), c.a);" % (
        h.i("Image", "vec4"), h.i("Gamma", "float"))]


def _bright(h):
    return [T("""vec4 c = $img;
float br = ($br) / 100.0;
float delta = ($ct) / 200.0;
float a, b;
if (delta > 0.0) { a = 1.0 / max(1.0 - delta * 2.0, 1e-5); b = a * (br - delta); }
else { a = max(1.0 + delta * 2.0, 0.0); b = a * br - delta; }
return vec4(a * c.rgb + b, c.a);""", img=h.i("Image"), br=h.i("Bright", "float"), ct=h.i("Contrast", "float"))]


def _huesat(h):
    fac = h.i("Fac", "float") if h.has("Fac") else (h.i("Factor", "float") if h.has("Factor") else "1.0")
    hue = h.i("Hue", "float") if h.has("Hue") else fl(getattr(h.node, "color_hue", 0.5))
    sat = h.i("Saturation", "float") if h.has("Saturation") else fl(getattr(h.node, "color_saturation", 1.0))
    val = h.i("Value", "float") if h.has("Value") else fl(getattr(h.node, "color_value", 1.0))
    return [T("""vec4 c = $img;
vec3 hsv = rgb2hsv(c.rgb);
hsv.x = fract(hsv.x + ($hue) - 0.5);
hsv.y = clamp(hsv.y * ($sat), 0.0, 1.0);
hsv.z = hsv.z * ($val);
return vec4(mix(c.rgb, hsv2rgb(hsv), clamp($fac, 0.0, 1.0)), c.a);""",
               img=h.i("Image"), hue=hue, sat=sat, val=val, fac=fac)]


def _colorbalance(h):
    node = h.node
    fac = h.i("Fac", "float") if h.has("Fac") else (h.i("Factor", "float") if h.has("Factor") else "1.0")
    img = h.i("Image") if h.has("Image") else h.i("Color")

    def v(n, d):
        x = getattr(node, n, d)
        return "vec3(%s, %s, %s)" % tuple(fl(t) for t in list(x)[:3])
    if getattr(node, "correction_method", "LIFT_GAMMA_GAIN") == "LIFT_GAMMA_GAIN":
        return [T("""vec4 c = $img;
vec3 r = ((c.rgb - 1.0) * (vec3(2.0) - $lift) + 1.0) * $gain;
r = pow(max(r, vec3(0.0)), 1.0 / max($gamma, vec3(1e-4)));
return vec4(mix(c.rgb, r, clamp($fac, 0.0, 1.0)), c.a);""", img=img, lift=v("lift", (1, 1, 1)),
                   gain=v("gain", (1, 1, 1)), gamma=v("gamma", (1, 1, 1)), fac=fac)]
    return [T("""vec4 c = $img;
vec3 r = pow(max(c.rgb * $slope + $offset, vec3(0.0)), $power);
return vec4(mix(c.rgb, r, clamp($fac, 0.0, 1.0)), c.a);""", img=img, slope=v("slope", (1, 1, 1)),
               offset=v("offset", (0, 0, 0)), power=v("power", (1, 1, 1)), fac=fac)]


def _set_alpha(h):
    img = h.i("Image", "vec4")
    al = h.i("Alpha", "float")
    mode = h.menu("Type", norm(getattr(h.node, "mode", "apply_mask")))
    if "replace" in mode:
        return ["vec4((%s).rgb, %s)" % (img, al)]
    return ["(%s) * (%s)" % (img, al)]


def _alpha_over(h):
    bg = h.i("Background", "vec4")
    fg = h.i("Foreground", "vec4")
    fac = h.i("Factor", "float")
    if h.menu("Type", "over") != "over":
        h.warn("Alpha Over type '%s' approximated as Over" % h.menu("Type"))
    straight = h.flag("Straight Alpha", False)
    return [T("""vec4 b = $bg; vec4 f = $fg; float k = clamp($fac, 0.0, 1.0);
$prem
if (f.a <= 0.0) return b;
if (k >= 1.0 && f.a >= 1.0) return f;
float m = max(1.0 - k * f.a, 0.0);
return m * b + k * f;""", bg=bg, fg=fg, fac=fac,
              prem="f.rgb *= f.a;" if straight else "")]


def _ramp_expr(node, fac):
    ramp = node.color_ramp
    els = [(e.position, tuple(e.color)) for e in ramp.elements]
    interp = ramp.interpolation
    col = lambda e: "vec4(%s)" % ", ".join(fl(x) for x in e[1])
    lines = ["float t = %s;" % fac, "vec4 r = %s;" % col(els[0])]
    for i in range(len(els) - 1):
        p0, p1 = els[i][0], els[i + 1][0]
        if interp == "CONSTANT":
            lines.append("if (t >= %s) r = %s;" % (fl(p1), col(els[i + 1])))
        else:
            w = "clamp((t - %s) / %s, 0.0, 1.0)" % (fl(p0), fl(max(p1 - p0, 1e-6)))
            if interp in ("EASE", "CARDINAL", "B_SPLINE"):
                w = "smoothstep(0.0, 1.0, %s)" % w
            lines.append("if (t >= %s) r = mix(%s, %s, %s);" % (fl(p0), col(els[i]), col(els[i + 1]), w))
    lines.append("return r;")
    return lines


def _colorramp(h):
    lines = _ramp_expr(h.node, h.i(0, "float"))
    a = "\n".join(lines)
    return [a, a.replace("return r;", "return r.a;")]


# ---- math / vector ------------------------------------------------------------

MATH = {
    "ADD": "({0} + {1})", "SUBTRACT": "({0} - {1})", "MULTIPLY": "({0} * {1})",
    "DIVIDE": "safe_div({0}, {1})", "MULTIPLY_ADD": "({0} * {1} + {2})",
    "POWER": "safe_pow({0}, {1})", "LOGARITHM": "safe_log({0}, {1})",
    "SQRT": "sqrt(max({0}, 0.0))", "INVERSE_SQRT": "inversesqrt(max({0}, 1e-6))",
    "ABSOLUTE": "abs({0})", "EXPONENT": "exp({0})",
    "MINIMUM": "min({0}, {1})", "MAXIMUM": "max({0}, {1})",
    "LESS_THAN": "float({0} < {1})", "GREATER_THAN": "float({0} > {1})",
    "SIGN": "sign({0})", "COMPARE": "float(abs({0} - {1}) <= max({2}, 1e-5))",
    "ROUND": "(sign({0}) * floor(abs({0}) + 0.5))", "FLOOR": "floor({0})", "CEIL": "ceil({0})",
    "TRUNC": "trunc({0})", "FRACT": "({0} - floor({0}))",
    "MODULO": "safe_mod({0}, {1})", "FLOORED_MODULO": "fl_mod({0}, {1})",
    "WRAP": "wrap_v({0}, {1}, {2})", "SNAP": "snap_v({0}, {1})", "PINGPONG": "ping_pong({0}, {1})",
    "SINE": "sin({0})", "COSINE": "cos({0})", "TANGENT": "tan({0})",
    "ARCSINE": "asin(clamp({0}, -1.0, 1.0))", "ARCCOSINE": "acos(clamp({0}, -1.0, 1.0))",
    "ARCTANGENT": "atan({0})", "ARCTAN2": "atan({0}, {1})",
    "SINH": "sinh({0})", "COSH": "cosh({0})", "TANH": "tanh({0})",
    "RADIANS": "radians({0})", "DEGREES": "degrees({0})",
    "SMOOTH_MIN": "min({0}, {1})", "SMOOTH_MAX": "max({0}, {1})",
}


def _math(h):
    op = h.node.operation
    tpl = MATH.get(op)
    if tpl is None:
        h.warn("Math operation %s unsupported" % op)
        return ["0.0"]
    args = [h.i(k, "float") if h.has(k) else "0.0" for k in range(3)]
    expr = tpl.format(*args)
    if getattr(h.node, "use_clamp", False):
        expr = "clamp(%s, 0.0, 1.0)" % expr
    return [expr]


VMATH = {
    "ADD": "({0} + {1})", "SUBTRACT": "({0} - {1})", "MULTIPLY": "({0} * {1})",
    "DIVIDE": "safe_div3({0}, {1})", "SCALE": "({0} * {3})", "CROSS_PRODUCT": "cross({0}, {1})",
    "NORMALIZE": "normalize({0})", "ABSOLUTE": "abs({0})", "MINIMUM": "min({0}, {1})",
    "MAXIMUM": "max({0}, {1})", "FLOOR": "floor({0})", "CEIL": "ceil({0})", "FRACTION": "fract({0})",
    "SINE": "sin({0})", "COSINE": "cos({0})", "TANGENT": "tan({0})", "SNAP": "(floor({0} / {1}) * {1})",
    "MULTIPLY_ADD": "({0} * {1} + {2})", "REFLECT": "reflect({0}, normalize({1}))",
    "MODULO": "mod({0}, {1})", "WRAP": "{0}",
}
VMATH_SCALAR = {"DOT_PRODUCT": "dot({0}, {1})", "LENGTH": "length({0})", "DISTANCE": "distance({0}, {1})"}


def _vector_math(h):
    op = h.node.operation
    args = [h.i(0, "vec3"), h.i(1, "vec3"), h.i(2, "vec3"), h.i(3, "float") if len(h.node.inputs) > 3 else "1.0"]
    if op in VMATH_SCALAR:
        return [zero("vec3"), VMATH_SCALAR[op].format(*args)]
    tpl = VMATH.get(op)
    if tpl is None:
        h.warn("Vector Math operation %s unsupported" % op)
        return ["vec3(0.0)", "0.0"]
    return [tpl.format(*args), "0.0"]


def _sep_xyz(h):
    v = h.i(0, "vec3")
    return ["(%s).x" % v, "(%s).y" % v, "(%s).z" % v]


def _comb_xyz(h):
    return ["vec3(%s, %s, %s)" % (h.i(0, "float"), h.i(1, "float"), h.i(2, "float"))]


def _sep_color(h):
    mode = getattr(h.node, "mode", "RGB")
    img = h.i(0, "vec4")
    conv = {"RGB": "c.rgb", "HSV": "rgb2hsv(c.rgb)", "HSL": "rgb2hsl(c.rgb)",
            "YCC": _ycc_fwd(h.node), "YUV": "rgb2yuv(c.rgb)"}.get(mode, "c.rgb")
    pre = "vec4 c = %s;\nvec3 v = %s;\n" % (img, conv)
    return [pre + "return v.x;", pre + "return v.y;", pre + "return v.z;", "(%s).a" % img]


def _comb_color(h):
    mode = getattr(h.node, "mode", "RGB")
    v = "vec3(%s, %s, %s)" % (h.i(0, "float"), h.i(1, "float"), h.i(2, "float"))
    conv = {"RGB": "v", "HSV": "hsv2rgb(v)", "HSL": "hsl2rgb(v)",
            "YCC": _ycc_bwd(h.node), "YUV": "yuv2rgb(v)"}.get(mode, "v")
    return ["vec3 v = %s;\nreturn vec4(%s, %s);" % (v, conv, h.i(3, "float"))]


def _ycc_fwd(node):
    m = getattr(node, "ycc_mode", "ITUBT709")
    kr, kb = {"ITUBT601": (0.299, 0.114), "ITUBT709": (0.2126, 0.0722), "JFIF": (0.299, 0.114)}.get(m, (0.2126, 0.0722))
    return "vec3(dot(c.rgb, vec3(%s, %s, %s)), (c.b - dot(c.rgb, vec3(%s, %s, %s))) / %s + 0.5, (c.r - dot(c.rgb, vec3(%s, %s, %s))) / %s + 0.5)" % (
        fl(kr), fl(1 - kr - kb), fl(kb), fl(kr), fl(1 - kr - kb), fl(kb), fl(2 * (1 - kb)),
        fl(kr), fl(1 - kr - kb), fl(kb), fl(2 * (1 - kr)))


def _ycc_bwd(node):
    m = getattr(node, "ycc_mode", "ITUBT709")
    kr, kb = {"ITUBT601": (0.299, 0.114), "ITUBT709": (0.2126, 0.0722), "JFIF": (0.299, 0.114)}.get(m, (0.2126, 0.0722))
    kg = 1 - kr - kb
    return "vec3(v.x + (v.z - 0.5) * %s, v.x - (v.y - 0.5) * %s - (v.z - 0.5) * %s, v.x + (v.y - 0.5) * %s)" % (
        fl(2 * (1 - kr)), fl(2 * (1 - kb) * kb / kg), fl(2 * (1 - kr) * kr / kg), fl(2 * (1 - kb)))


YUV_FUNCS = """vec3 rgb2yuv(vec3 c) { float y = dot(c, vec3(0.299, 0.587, 0.114)); return vec3(y, 0.492 * (c.b - y), 0.877 * (c.r - y)); }
vec3 yuv2rgb(vec3 v) { float r = v.x + v.z / 0.877; float b = v.x + v.y / 0.492; float g = (v.x - 0.299 * r - 0.114 * b) / 0.587; return vec3(r, g, b); }
"""


def _rgb_to_bw(h):
    return ["dot((%s).rgb, %s)" % (h.i(0, "vec4"), LUMA)]


def _map_range(h):
    v, a, b, d, e = [h.i(k, "float") for k in range(5)]
    kind = h.menu("interpolation_type", "linear")
    f = "safe_div(%s - %s, %s - %s)" % (v, a, b, a)
    if kind == "stepped":
        st = h.i("Steps", "float") if h.has("Steps") else "4.0"
        f = "((%s) > 0.0 ? floor((%s) * ((%s) + 1.0)) / (%s) : 0.0)" % (st, f, st, st)
        return ["(%s) + (%s) * ((%s) - (%s))" % (d, f, e, d)]
    if kind in ("smoothstep", "smootherstep"):
        sm = ("(f * f * (3.0 - 2.0 * f))" if kind == "smoothstep" else "(f * f * f * (f * (f * 6.0 - 15.0) + 10.0))")
        return ["float f = clamp(%s, 0.0, 1.0);\nreturn (%s) + %s * ((%s) - (%s));" % (f, d, sm, e, d)]
    expr = "%s * (%s - %s) + %s" % (f, e, d, d)
    if getattr(h.node, "use_clamp", False) or h.flag("Clamp", False):
        expr = "clamp(%s, min(%s, %s), max(%s, %s))" % (expr, d, e, d, e)
    return [expr]


def _clamp_node(h):
    v, lo, hi = h.i("Value", "float"), h.i("Min", "float"), h.i("Max", "float")
    if h.menu("clamp_type", "minmax") == "range":
        return ["clamp(%s, min(%s, %s), max(%s, %s))" % (v, lo, hi, lo, hi)]
    return ["min(max(%s, %s), %s)" % (v, lo, hi)]


def _vector_rotate(h):
    kind = h.menu("rotation_type", "axis_angle")
    inv = h.flag("invert", False)
    vec, cen = h.i("Vector", "vec3"), h.i("Center", "vec3")
    if kind == "euler_xyz":
        rot = h.i("Rotation", "vec3")
        # Blender: Rz * Ry * Rx applied to the vector (X first); invert = transpose
        return [T("""vec3 e = $rot;
float cx = cos(e.x), sx = sin(e.x), cy = cos(e.y), sy = sin(e.y), cz = cos(e.z), sz = sin(e.z);
vec3 c0 = vec3(cy * cz, cy * sz, -sy);
vec3 c1 = vec3(sx * sy * cz - cx * sz, sx * sy * sz + cx * cz, sx * cy);
vec3 c2 = vec3(cx * sy * cz + sx * sz, cx * sy * sz - sx * cz, cx * cy);
vec3 d = $vec - $cen;
return $cen + ($inv ? vec3(dot(c0, d), dot(c1, d), dot(c2, d)) : c0 * d.x + c1 * d.y + c2 * d.z);""", rot=rot, vec=vec, cen=cen, inv="true" if inv else "false")]
    axis = {"x_axis": "vec3(1.0, 0.0, 0.0)", "y_axis": "vec3(0.0, 1.0, 0.0)",
            "z_axis": "vec3(0.0, 0.0, 1.0)"}.get(kind)
    ang = h.i("Angle", "float")
    args = dict(vec=vec, cen=cen, ang=("-(%s)" % ang) if inv else ang)
    if axis is None:
        args["axis"] = h.i("Axis", "vec3")
        axis = "normalize($axis)"
    # Rodrigues rotation around an axis through `center`
    return [T("""vec3 k = %s;
float a = $ang;
vec3 d = $vec - $cen;
return $cen + d * cos(a) + cross(k, d) * sin(a) + k * dot(k, d) * (1.0 - cos(a));""" % axis, **args)]


def _image_coords(h):
    return ["vec3((uv * 2.0 - 1.0) * res() / max(res().x, res().y), 0.0)",
            "vec3(uv, 0.0)",
            "vec3(floor(uv * res()), 0.0)"]


def _tex_checker(h):
    v = "vec3 p = %s * %s + vec3(0.0000001 * 0.999999);\n" % (_vec_in(h), h.i("Scale", "float"))
    chk = ("ivec3 q = ivec3(abs(floor(p)));\n"
           "float f = (((q.x % 2) == (q.y % 2)) == ((q.z % 2) == 1)) ? 1.0 : 0.0;\n")
    return [v + chk + "return mix(%s, %s, f);" % (h.i("Color2", "vec4"), h.i("Color1", "vec4")),
            v + chk + "return f;"]


# ---- curves ---------------------------------------------------------------------

def _lut(curvemap, outer=None, n=64):
    vals = []
    for i in range(n):
        x = i / (n - 1)
        if outer is not None:
            x = outer.evaluate(curvemap_owner_eval, x) if False else x
        vals.append(x)
    return vals


def _curve_luts(mapping, n=64):
    """sample[(combined -> channel)] LUTs for R, G, B."""
    try:
        mapping.initialize()
    except Exception:
        pass
    ev = mapping.evaluate
    cs = mapping.curves
    luts = []
    for ch in (0, 1, 2):          # curves[0..2] = R, G, B; curves[3] = combined (C)
        vals = []
        for i in range(n):
            x = i / (n - 1)
            xc = ev(cs[3], x)
            vals.append(max(-10.0, min(10.0, ev(cs[ch], min(max(xc, 0.0), 1.0)))))
        luts.append(vals)
    return luts


def _emit_lut(c, name, vals):
    c.consts.append("const float %s[64] = float[64](%s);" % (name, ", ".join(fl(v) for v in vals)))


def _curve_rgb(h):
    luts = _curve_luts(h.node.mapping)
    base = "CURVE_%d_%d" % (h.ctx.id, h.ctx.index[h.node.name])
    for k, v in zip("RGB", luts):
        _emit_lut(h.c, base + k, v)
    fac = h.i("Fac", "float") if h.has("Fac") else (h.i("Factor", "float") if h.has("Factor") else "1.0")
    img = h.i("Image") if h.has("Image") else h.i("Color")
    bl = h.i("Black Level", "vec4") if h.has("Black Level") else "vec4(0.0)"
    wl = h.i("White Level", "vec4") if h.has("White Level") else "vec4(1.0)"
    return [T("""vec4 c = $img;
vec3 bl = ($bl).rgb, wl = ($wl).rgb;
vec3 x = (c.rgb - bl) / max(wl - bl, vec3(1e-6));
vec3 r = vec3(lut_eval($R, x.r), lut_eval($G, x.g), lut_eval($B, x.b));
return vec4(mix(c.rgb, r, clamp($fac, 0.0, 1.0)), c.a);""", img=img, bl=bl, wl=wl, fac=fac,
               R=base + "R", G=base + "G", B=base + "B")]


def _curve_float(h):
    mapping = h.node.mapping
    try:
        mapping.initialize()
    except Exception:
        pass
    vals = [max(-10.0, min(10.0, mapping.evaluate(mapping.curves[0], i / 63.0))) for i in range(64)]
    name = "CURVE_%d_%d" % (h.ctx.id, h.ctx.index[h.node.name])
    _emit_lut(h.c, name, vals)
    fac = h.i("Factor", "float") if h.has("Factor") else "1.0"
    val = h.i("Value", "float")
    return ["mix(%s, lut_eval(%s, %s), clamp(%s, 0.0, 1.0))" % (val, name, val, fac)]


# ---- spatial -------------------------------------------------------------------------

def _interp_snap(mode, uvexpr):
    return "snap_px(%s)" % uvexpr if mode in ("nearest", "") else uvexpr


EXT_ID = {"clip": 0, "extend": 1, "repeat": 2, "mirror": 3, "wrap": 2}


def _ext(h, kx="Extension X", ky="Extension Y"):
    ex = EXT_ID.get(h.menu(kx, "clip"), 0)
    ey = EXT_ID.get(h.menu(ky, "clip"), 0)
    return ex, ey


def _translate(h):
    x, y = h.i("X", "float"), h.i("Y", "float")
    interp = h.menu("Interpolation", "nearest")
    wx = h.flag("Wrap X", False) if h.has("Wrap X") else False
    q = "uv - vec2(%s, %s) / res()" % (x, y)
    q = _interp_snap(interp, q)
    src = h.i("Image", "vec4", uv="q.xy")
    return [T("""vec3 q = ext_uv($q, $mx, $my);
return $src * q.z;""", q=q, mx=2 if wx else 0, my=2 if (h.flag("Wrap Y", False) if h.has("Wrap Y") else False) else 0, src=src)]


def _transform(h):
    interp = h.menu("Interpolation", "bilinear")
    mx, my = _ext(h)
    src = h.i("Image", "vec4", uv="q.xy")
    pre = T("""vec2 R = res();
vec2 p = uv * R - 0.5 * R - vec2($x, $y);
float a = $ang;
p = vec2(cos(a) * p.x + sin(a) * p.y, -sin(a) * p.x + cos(a) * p.y) / max(abs($sc), 1e-6);
vec2 qq = (p + 0.5 * R) / R;
$snap
vec3 q = ext_uv(qq, $mx, $my);""", x=h.i("X", "float"), y=h.i("Y", "float"), ang=h.i("Angle", "float"),
            sc=h.i("Scale", "float"), mx=mx, my=my,
            snap="qq = snap_px(qq);" if interp == "nearest" else "")
    return [pre + "\nreturn %s * q.z;" % src]


def _scale(h):
    kind = h.menu("Type", "relative")
    interp = h.menu("Interpolation", "bilinear")
    mx, my = _ext(h)
    if kind == "relative":
        sx, sy = h.i("X", "float"), h.i("Y", "float")
    elif kind == "absolute":
        sx, sy = "(%s / res().x)" % h.i("X", "float"), "(%s / res().y)" % h.i("Y", "float")
    else:
        h.warn("Scale type '%s' treated as Relative 1.0" % kind)
        sx = sy = "1.0"
    if h.menu("Frame Type", "stretch") not in ("stretch", ""):
        h.warn("Scale frame type approximated as Stretch")
    src = h.i("Image", "vec4", uv="q.xy")
    pre = T("""vec2 s = vec2($sx, $sy);
vec2 qq = (uv - 0.5) / max(abs(s), vec2(1e-6)) + 0.5;
$snap
vec3 q = ext_uv(qq, $mx, $my);""", sx=sx, sy=sy, mx=mx, my=my,
            snap="qq = snap_px(qq);" if interp == "nearest" else "")
    return [pre + "\nreturn %s * q.z;" % src]


def _flip(h):
    if h.has("Flip X") or h.has("Flip Y"):          # newer Blender: two Boolean inputs
        fx_, fy_ = h.flag("Flip X"), h.flag("Flip Y")
        ax = "xy" if (fx_ and fy_) else "x" if fx_ else "y" if fy_ else ""
    else:
        ax = h.menu("Axis", norm(getattr(h.node, "axis", "X")))
    u = {"": "uv", "x": "vec2(1.0 - uv.x, uv.y)", "y": "vec2(uv.x, 1.0 - uv.y)"}.get(ax, "vec2(1.0) - uv")
    return [h.i("Image", "vec4", uv=u)]


def _displace(h):
    interp = h.menu("Interpolation", "bilinear")
    mx, my = _ext(h)
    d = h.i("Displacement", "vec3")
    src = h.i("Image", "vec4", uv="q.xy")
    return [T("""vec2 qq = uv - ($d).xy / res();
$snap
vec3 q = ext_uv(qq, $mx, $my);
return $src * q.z;""", d=d, mx=mx, my=my, src=src, snap="qq = snap_px(qq);" if interp == "nearest" else "")]


def _pixelate(h):
    h.heavy()
    src = h.i("Color", "vec4", uv="q") if h.has("Color") else h.i(0, "vec4", uv="q")
    return [T("""float s = max(floor($size), 1.0);
vec2 R = res();
vec2 base = floor(uv * R / s) * s;       // block origin in pixels
vec4 acc = vec4(0.0);
for (int i = 0; i < PIXELATE_TAPS; i++) {
    for (int j = 0; j < PIXELATE_TAPS; j++) {
        vec2 q = (base + (vec2(float(i), float(j)) + 0.5) / float(PIXELATE_TAPS) * s) / R;
        acc += $src;
    }
}
return acc / float(PIXELATE_TAPS * PIXELATE_TAPS);""", size=h.i("Size", "float"), src=src)]


def _blur(h):
    """Blur with a fixed sample budget (BLUR_SAMPLES) instead of a (2K+1)^2 grid.
    Gaussian: Gaussian-distributed radius + uniform angle from an R2 lattice (importance sampling, equal weights).
    Flat / triangle: R2 low-discrepancy points with box / tent distribution.  Per-pixel rotation hides the pattern."""
    node = h.node
    size = h.i("Size", "vec3") if h.has("Size") else "vec3(%s, %s, 0.0)" % (
        fl(getattr(node, "size_x", 0)), fl(getattr(node, "size_y", 0)))
    kind = h.menu("Type", norm(getattr(node, "filter_type", "gauss")))
    extend = h.flag("Extend Bounds", getattr(node, "use_extended_bounds", False))
    if "box" in kind or "flat" in kind:
        shape = "vec2 t = q * 2.0 - 1.0;"
    elif "tri" in kind or "quad" in kind:
        shape = ("vec2 t = vec2(q.x < 0.5 ? sqrt(2.0 * q.x) - 1.0 : 1.0 - sqrt(2.0 * (1.0 - q.x)),\n"
                 "              q.y < 0.5 ? sqrt(2.0 * q.y) - 1.0 : 1.0 - sqrt(2.0 * (1.0 - q.y)));")
    else:
        shape = ("float rr = sqrt(-2.0 * log(max(1.0 - q.x, 1e-4))) / 3.0;   // sigma = 1/3 of the radius -> exp(-4.5 t^2)\n"
                 "    float an = 6.2831853 * q.y;\n"
                 "    vec2 t = rr * vec2(cos(an), sin(an));\n"
                 "    if (abs(t.x) > 1.0 || abs(t.y) > 1.0) continue;")
    pos = "uv + off" if extend else "clamp(uv + off, 0.0, 1.0)"
    src = h.i("Image", "vec4", uv="p")
    return [T("""vec2 R = res();
vec2 rad = max(($size).xy, vec2(0.0));
if (rad.x < 0.25 && rad.y < 0.25) return $src0;
float rot = hash31(vec3(gl_FragCoord.xy, 1.0)) * 6.2831853;
float jr = hash31(vec3(gl_FragCoord.xy, 2.0));
float cap = float(min(BLUR_SAMPLES, $cap));
#if BLUR_ADAPT
// the bigger the blur, the fewer samples (large blurs are expensive and hide detail anyway): 100% below ~3% of the
// short screen side, down to 40% from ~25% of it
cap *= 1.0 - 0.6 * smoothstep(0.03, 0.25, max(rad.x, rad.y) / min(R.x, R.y));
#endif
int ns = int(clamp(2.5 * rad.x * rad.y, 5.0, max(cap, 5.0)));
vec4 acc = vec4(0.0); float wsum = 0.0;
for (int i = 0; i < ns; i++) {
    vec2 q = fract(vec2(0.7548776662, 0.5698402910) * float(i + 1) + vec2(jr, rot * 0.159155));   // R2 lattice, shifted per pixel
    """ + shape + """
    vec2 off = t * rad / R;
    vec2 p = $pos;
    acc += $src;
    wsum += 1.0;
}
return acc / max(wsum, 1.0);""", size=size, src0=h.i("Image", "vec4"), src=src, pos=pos, cap=h.heavy())]


def _dilate_erode(h):
    h.heavy()
    kind = h.menu("Type", "threshold")
    size = h.i("Size", "float")
    src = h.i("Mask", "float", uv="p")
    post = "m = step(0.5, m);" if kind in ("threshold", "step") else ""
    if kind not in ("threshold", "step", "distance"):
        h.warn("Dilate/Erode type '%s' approximated as Distance" % kind)
    return [T("""float s = $size;
float r = abs(s);
if (r < 0.5) return $src0;
bool dil = s > 0.0;
float lim = dil ? max(r - 0.4, 0.0) / r : 1.0;   // Blender's dilate disk is ~0.4px smaller than the nominal radius
float m = dil ? 0.0 : 1.0;
for (int i = -DILATE_K; i <= DILATE_K; i++) {
    for (int j = -DILATE_K; j <= DILATE_K; j++) {
        vec2 t = vec2(float(i), float(j)) / float(DILATE_K);
        if (dot(t, t) > lim * lim) continue;
        vec2 p = uv + t * r / res();
        float v = $src;
        m = dil ? max(m, v) : min(m, v);
    }
}
$post
return m;""", size=size, src0=h.i("Mask", "float"), src=src, post=post)]


def _lens_distortion(h):
    h.heavy()
    kind = h.menu("Type", "radial")
    fit = h.flag("Fit", False)
    if kind != "radial":
        h.warn("Lens Distortion type '%s' approximated as Radial" % kind)
    s = lambda k: h.i("Image", "vec4", uv=k)
    # Formula fitted against Blender's own output (distortion exact, dispersion approximate).
    return [T("""float k = clamp($dist, -0.999, 1.0);
float dp = clamp($disp, 0.0, 1.0);
float ke = k + 0.25 * dp;
float sc = ($fit && ke > 0.0) ? 1.0 / (1.0 + 2.0 * ke) : 1.0 / (1.0 + ke);
vec2 p = (uv * 2.0 - 1.0) * sc;
float r2 = dot(p, p);
float kr = 4.0 * k + 0.7 * dp, kg = 4.0 * k, kb = 4.0 * k - 0.7 * dp;
vec2 pr = p / (1.0 + sqrt(max(1.0 - kr * r2, 0.0))) + 0.5;
vec2 pg = p / (1.0 + sqrt(max(1.0 - kg * r2, 0.0))) + 0.5;
vec2 pb = p / (1.0 + sqrt(max(1.0 - kb * r2, 0.0))) + 0.5;
vec4 cg = $sg;
if (dp <= 0.0) return cg;
vec3 acc = vec3(0.0), wsum = vec3(0.0);
for (int i = 0; i < 8; i++) {
    float t = (float(i) + 0.5) / 8.0;
    float kk = mix(kr, kb, t);
    vec2 pp = p / (1.0 + sqrt(max(1.0 - kk * r2, 0.0))) + 0.5;
    vec4 c = $sx;
    vec3 w = vec3(max(1.0 - 2.0 * t, 0.0), 1.0 - abs(2.0 * t - 1.0), max(2.0 * t - 1.0, 0.0));
    acc += c.rgb * w; wsum += w;
}
vec3 o = acc / max(wsum, vec3(1e-4));
return vec4(o, cg.a);""", dist=h.i("Distortion", "float"), disp=h.i("Dispersion", "float"),
               fit="true" if fit else "false", sg=s("pg"), sx=s("pp"))]


def _glare(h):
    cap = h.heavy()
    kind = h.menu("Type", norm(getattr(h.node, "glare_type", "fog_glow")))
    img = h.i("Image", "vec4")
    strength = h.i("Strength", "float") if h.has("Strength") else "1.0"
    tint = h.i("Tint", "vec4") if h.has("Tint") else "vec4(1.0)"
    thr = h.i("Threshold", "float") if h.has("Threshold") else "0.0"
    smooth = h.i("Smoothness", "float") if h.has("Smoothness") else "0.1"
    sat = h.i("Saturation", "float") if h.has("Saturation") else "1.0"
    if "sun" in kind:
        pos = h.i("Sun Position", "vec3")
        size = h.i("Size", "float") if h.has("Size") else "0.5"
        src = h.i("Image", "vec4", uv="p / R")
        # Formula fitted against Blender: path length = size * image diagonal, weight (1 - t)^2,
        # path stops at the sun.
        glare = T("""vec2 R = res();
vec2 P = uv * R;
vec2 v = ($pos).xy * R - P;
float dist = length(v);
vec2 dir = v / max(dist, 1e-6);
float L = min(max($size, 0.0) * length(R), dist);
float jit = hash31(vec3(gl_FragCoord.xy, 3.0));
vec4 acc = vec4(0.0); float wsum = 0.0;
for (int i = 0; i < SUN_STEPS; i++) {
    float t = (float(i) + jit) / float(SUN_STEPS);
    float w = (1.0 - t) * (1.0 - t);
    vec2 p = P + dir * t * L;
    vec4 s = $src;
    acc += w * vec4(glare_hl(s.rgb, $thr, $smooth), s.a);
    wsum += w;
}
vec4 g = acc / max(wsum, 1e-6) * ($strength) * ($tint);
float gl = luma(g.rgb);
g.rgb = mix(vec3(gl), g.rgb, $sat);
""", pos=pos, size=size, src=src, thr=thr, smooth=smooth, strength=strength, tint=tint, sat=sat)
    elif "bloom" in kind or "fog" in kind:
        size = h.i("Size", "float") if h.has("Size") else "0.5"
        src = h.i("Image", "vec4", uv="p")
        # Blender's bloom is a down/up-sample chain with floor(log2(min(w,h) * size)) levels, energy preserving.
        # Fitted against Blender: equal-weight mix of Gaussians with sigma = 1.2 * 2^level (px).  Sampled by
        # importance (level + Gaussian radius per sample) with a per-pixel rotated R2 lattice, so cost is fixed.
        glare = T("""vec2 R = res();
float Lf = floor(log2(max(min(R.x, R.y) * clamp($size, 0.0, 1.0), 1.0)));
vec4 g = vec4(0.0);
if (Lf < 1.0) {
    vec4 s = $src0;
    g = vec4(glare_hl(s.rgb, $thr, $smooth), s.a);
} else {
    int nl = int(clamp(Lf, 3.0, 10.0));
    float rot = hash31(vec3(gl_FragCoord.xy, 5.0));
    float jr = hash31(vec3(gl_FragCoord.xy, 6.0));
    int ns = int(max(float(min(BLOOM_SAMPLES, $cap)), float(nl)));
    vec4 acc = vec4(0.0);
    for (int i = 0; i < ns; i++) {
        vec2 q = fract(vec2(0.7548776662, 0.5698402910) * float(i + 1) + vec2(jr, rot));
        float lv = floor(float(i) / float(ns) * float(nl) + 0.5 * 0.0);   // stratified: every level gets ~ns/nl samples
        lv = min(floor((float(i) + jr) / float(ns) * float(nl)), float(nl - 1));
        float sg = (Lf < 3.0 ? 0.9 : 1.2) * exp2(lv);
        float rr = sg * sqrt(-2.0 * log(max(1.0 - q.x, 1e-4)));
        float an = 6.2831853 * q.y;
        vec2 p = uv + rr * vec2(cos(an), sin(an)) / R;
        vec4 s = $src;
        acc += vec4(glare_hl(s.rgb, $thr, $smooth), s.a);
    }
    g = acc / float(ns);
}
g *= ($strength) * ($tint);
float gl = luma(g.rgb);
g.rgb = mix(vec3(gl), g.rgb, $sat);
""", size=size, src0=h.i("Image", "vec4"), src=src, thr=thr, smooth=smooth, strength=strength, tint=tint, sat=sat, cap=cap)
    else:
        h.warn("Glare type '%s' not implemented -> no glare" % kind)
        glare = "vec4 g = vec4(0.0);\n"
    return [glare + "vec4 c = %s;\nreturn c + g;" % img,
            glare + "return g;",
            "(%s)" % img]


# ---- procedural textures ----------------------------------------------------------------

def _vec_in(h, key="Vector"):
    return h.i(key, "vec3") if h.linked(key) else "tex_co(uv)"


def _tex_gradient(h):
    typ = getattr(h.node, "gradient_type", "LINEAR")
    v = "vec3 p = %s;\n" % _vec_in(h)
    fac = {
        "LINEAR": "p.x",
        "QUADRATIC": "max(p.x, 0.0) * max(p.x, 0.0)",
        "EASING": "smoothstep(0.0, 1.0, clamp(p.x, 0.0, 1.0))",
        "DIAGONAL": "(p.x + p.y) * 0.5",
        "RADIAL": "atan(p.y, p.x) / 6.2831853 + 0.5",
        "QUADRATIC_SPHERE": "pow(max(1.0 - length(p), 0.0), 2.0)",
        "SPHERICAL": "max(1.0 - length(p), 0.0)",
    }.get(typ, "p.x")
    return [v + "float f = %s;\nreturn vec4(vec3(clamp(f, 0.0, 1.0)), 1.0);" % fac,
            v + "return %s;" % fac]


def _tex_noise(h):
    n = h.node
    dims = getattr(n, "noise_dimensions", "3D")
    vec = _vec_in(h)
    scale = h.i("Scale", "float")
    w = h.i("W", "float") if (dims == "4D" and h.has("W")) else "0.0"
    detail = h.i("Detail", "float")
    rough = h.i("Roughness", "float")
    lac = h.i("Lacunarity", "float")
    norm_ = "true" if getattr(n, "normalize", True) else "false"
    if getattr(n, "noise_type", "FBM") != "FBM":
        h.warn("Noise type %s approximated by FBM" % getattr(n, "noise_type", ""))
    if dims in ("1D", "2D"):
        h.warn("Noise %s is evaluated as 3D" % dims)
    pre = T("""vec3 p = $vec * ($scale);
float w = ($w) * ($scale);
float D = $detail, Rh = $rough, L = $lac;
""", vec=vec, scale=scale, w=w, detail=detail, rough=rough, lac=lac)
    if dims == "4D":
        f = "fbm4(vec4(p, w), D, Rh, L, %s)" % norm_
        f2 = "fbm4(vec4(p + vec3(31.7, 11.3, 5.9), w), D, Rh, L, %s)" % norm_
        f3 = "fbm4(vec4(p + vec3(7.1, 47.3, 23.9), w), D, Rh, L, %s)" % norm_
    else:
        f = "fbm3(p, D, Rh, L, %s)" % norm_
        f2 = "fbm3(p + vec3(31.7, 11.3, 5.9), D, Rh, L, %s)" % norm_
        f3 = "fbm3(p + vec3(7.1, 47.3, 23.9), D, Rh, L, %s)" % norm_
    return [pre + "return %s;" % f, pre + "return vec4(%s, %s, %s, 1.0);" % (f, f2, f3)]


def _tex_white_noise(h):
    dims = getattr(h.node, "noise_dimensions", "3D")
    vec = _vec_in(h)
    w = h.i("W", "float") if h.has("W") else "0.0"
    pre = "vec3 p = %s;\nfloat w = %s;\n" % (vec, w)
    fn = {"1D": "white1(w)", "2D": "white2(p.xy)", "3D": "white3(p)", "4D": "white4(vec4(p, w))"}.get(dims, "white3(p)")
    if dims == "1D":
        alt = lambda k: "white1(w + %s)" % k
    elif dims == "2D":
        alt = lambda k: "white2(p.xy + %s)" % k
    elif dims == "4D":
        alt = lambda k: "white4(vec4(p + %s, w))" % k
    else:
        alt = lambda k: "white3(p + %s)" % k
    o1, o2 = {"1D": ("17.1", "23.7"), "2D": ("vec2(17.1, 3.7)", "vec2(5.3, 21.9)")}.get(
        dims, ("vec3(17.1, 3.7, 9.3)", "vec3(5.3, 21.9, 1.3)"))
    return [pre + "return %s;" % fn,
            pre + "return vec4(%s, %s, %s, 1.0);" % (fn, alt(o1), alt(o2))]


def _tex_wave(h):
    n = h.node
    wtype = getattr(n, "wave_type", "BANDS")
    prof = getattr(n, "wave_profile", "SIN")
    bdir = getattr(n, "bands_direction", "X")
    rdir = getattr(n, "rings_direction", "X")
    vec = _vec_in(h)
    scale = h.i("Scale", "float")
    dist = h.i("Distortion", "float")
    detail = h.i("Detail", "float")
    dscale = h.i("Detail Scale", "float")
    drough = h.i("Detail Roughness", "float")
    phase = h.i("Phase Offset", "float")
    if wtype == "BANDS":
        nexpr = {"X": "p.x * 20.0", "Y": "p.y * 20.0", "Z": "p.z * 20.0", "DIAGONAL": "(p.x + p.y + p.z) * 10.0"}.get(bdir, "p.x * 20.0")
    else:
        rp = {"X": "vec3(0.0, p.y, p.z)", "Y": "vec3(p.x, 0.0, p.z)", "Z": "vec3(p.x, p.y, 0.0)", "SPHERICAL": "p"}.get(rdir, "p")
        nexpr = "length(%s) * 20.0" % rp
    prof_e = {"SIN": "0.5 + 0.5 * sin(n - 1.5707963)",
              "SAW": "(n / 6.2831853) - floor(n / 6.2831853)",
              "TRI": "abs((n / 6.2831853) - floor(n / 6.2831853 + 0.5)) * 2.0"}.get(prof, "0.5 + 0.5 * sin(n - 1.5707963)")
    body = T("""vec3 p = ($vec) * ($scale);
p = (p + 0.000001) * 0.999999;
float n = $nexpr;
n += $phase;
float dist = $dist;
if (dist != 0.0) n += dist * (fbm3(p * ($dscale), $detail, $drough, 2.0, true) * 2.0 - 1.0);
float f = $prof;
""", vec=vec, scale=scale, nexpr=nexpr, phase=phase, dist=dist, dscale=dscale, detail=detail,
             drough=drough, prof=prof_e)
    return [body + "return vec4(vec3(f), 1.0);", body + "return f;"]


# ---------------------------------------------------------------------------
HANDLERS = {
    "NodeGroupInput": _group_input,
    "CompositorNodeGroup": _group,
    "NodeReroute": _reroute,
    **{k: _switch for k in SWITCHES},
    "CompositorNodeImage": _image_node,
    "CompositorNodeRLayers": _render_layers,
    "CompositorNodeRGB": _rgb,
    "CompositorNodeValue": _value,
    "ShaderNodeValue": _value,
    "CompositorNodeSceneTime": _scene_time,
    "CompositorNodeImageInfo": _imageinfo,
    "CompositorNodeStringToImage": _string_to_image,
    "CompositorNodeMixRGB": _mix_rgb,
    "ShaderNodeMix": _mix_shader,
    "CompositorNodeInvert": _invert,
    "CompositorNodePosterize": _posterize,
    "CompositorNodeExposure": _exposure,
    "CompositorNodeGamma": _gamma,
    "CompositorNodeBrightContrast": _bright,
    "CompositorNodeHueSat": _huesat,
    "CompositorNodeColorBalance": _colorbalance,
    "CompositorNodeSetAlpha": _set_alpha,
    "CompositorNodeAlphaOver": _alpha_over,
    "ShaderNodeValToRGB": _colorramp,
    "CompositorNodeValToRGB": _colorramp,
    "ShaderNodeMath": _math,
    "CompositorNodeMath": _math,
    "ShaderNodeVectorMath": _vector_math,
    "ShaderNodeSeparateXYZ": _sep_xyz,
    "ShaderNodeCombineXYZ": _comb_xyz,
    "CompositorNodeSeparateColor": _sep_color,
    "CompositorNodeCombineColor": _comb_color,
    "CompositorNodeRGBToBW": _rgb_to_bw,
    "CompositorNodeMapRange": _map_range,
    "ShaderNodeMapRange": _map_range,
    "ShaderNodeClamp": _clamp_node,
    "CompositorNodeImageCoordinates": _image_coords,
    "ShaderNodeTexChecker": _tex_checker,
    "ShaderNodeVectorRotate": _vector_rotate,
    "CompositorNodeCurveRGB": _curve_rgb,
    "ShaderNodeRGBCurve": _curve_rgb,
    "ShaderNodeFloatCurve": _curve_float,
    "CompositorNodeTranslate": _translate,
    "CompositorNodeTransform": _transform,
    "CompositorNodeScale": _scale,
    "CompositorNodeFlip": _flip,
    "CompositorNodeDisplace": _displace,
    "CompositorNodePixelate": _pixelate,
    "CompositorNodeBlur": _blur,
    "CompositorNodeDilateErode": _dilate_erode,
    "CompositorNodeLensdist": _lens_distortion,
    "CompositorNodeGlare": _glare,
    "ShaderNodeTexGradient": _tex_gradient,
    "ShaderNodeTexNoise": _tex_noise,
    "ShaderNodeTexWhiteNoise": _tex_white_noise,
    "ShaderNodeTexWave": _tex_wave,
}

Converter.need_blend_funcs = False


def _finish(c, code):
    extra = ""
    if c.need_blend_funcs:
        extra += BLEND_FUNCS
    if any("rgb2yuv" in f or "yuv2rgb" in f for f in c.funcs):
        extra += YUV_FUNCS
    if extra:
        code = code.replace("\n// ---- procedural noise", "\n" + extra + "\n// ---- procedural noise", 1)
    return code


FORMATS = [
    ("KIASECUT", "KiaseCut filter (.glsl)", "Filter for the KiaseCut video editor: group inputs become adjustable (keyframe-able) parameters. Put the file in <Library>/filters"),
    ("HYPRSHADE", "Hyprshade / Hyprland (.glsl)", "GLSL ES 3.00 screen shader for Hyprland (hyprshade or decoration:screen_shader)"),
    ("HLSL", "OBS obs-shaderfilter (.shader, HLSL)", "OBS HLSL pixel shader for the obs-shaderfilter plugin (experimental: not machine-tested on OBS)"),
    ("SHADERGLASS", "ShaderGlass / RetroArch (.slang + .slangp)", "Slang shader plus a preset, for ShaderGlass (Windows) and other RetroArch slang front-ends"),
]


def to_slang(code, frame_rate=60.0):
    """Re-wrap the generated GLSL ES shader as a RetroArch 'slang' shader (Vulkan GLSL 450, vertex + fragment stage)."""
    out = []
    drop = ("#version", "precision ", "in vec2 v_texcoord;", "uniform sampler2D tex;", "uniform float time;", "out vec4 fragColor;")
    for line in code.splitlines():
        if line.startswith(drop):
            continue
        out.append(line)
    body = "\n".join(out).replace("// Generated by Compositor to Hyprshade (Blender node tree -> GLSL ES 3.00)",
                                  "// Generated by Compositor to Hyprshade (Blender node tree -> RetroArch slang)", 1)
    head = """#version 450

layout(push_constant) uniform Push
{
    vec4 SourceSize;
    vec4 OriginalSize;
    vec4 OutputSize;
    uint FrameCount;
} params;

layout(std140, set = 0, binding = 0) uniform UBO
{
    mat4 MVP;
} global;

#pragma stage vertex
layout(location = 0) in vec4 Position;
layout(location = 1) in vec2 TexCoord;
layout(location = 0) out vec2 vTexCoord;

void main()
{
    gl_Position = global.MVP * Position;
    vTexCoord = TexCoord;
}

#pragma stage fragment
layout(location = 0) in vec2 v_texcoord;
layout(location = 0) out vec4 fragColor;
layout(set = 0, binding = 2) uniform sampler2D Source;
#define tex Source
#define FRAME_RATE %s   // ShaderGlass: FrameCount advances at this many frames per second (drives Scene Time)
#define time (float(params.FrameCount) / FRAME_RATE)
""" % ("%.6f" % float(frame_rate))
    return head + "\n" + body


HLSL_HELPERS = """// ---- GLSL-style helpers ----------------------------------------------------------
#define time elapsed_time
"""


def _balanced_args(text, i):
    """text[i] == '(' -> (list of top-level argument strings, index after the closing paren)."""
    depth, args, cur = 0, [], ""
    j = i
    while j < len(text):
        ch = text[j]
        if ch == "(":
            depth += 1
            if depth > 1:
                cur += ch
        elif ch == ")":
            depth -= 1
            if depth == 0:
                args.append(cur)
                return args, j + 1
            cur += ch
        elif ch == "," and depth == 1:
            args.append(cur)
            cur = ""
        else:
            cur += ch
        j += 1
    raise ValueError("unbalanced parentheses")


def _rewrite_calls(text, rules):
    """Rewrite calls name(args...) -> rules[name](list of already rewritten args), innermost first."""
    pat = re.compile(r"\b(%s)\(" % "|".join(sorted(rules, key=len, reverse=True)))
    out, i = [], 0
    for m_ in pat.finditer(text):
        if m_.start() < i:
            continue
        args, end = _balanced_args(text, m_.end() - 1)
        args = [_rewrite_calls(a, rules) for a in args]
        out.append(text[i:m_.start()])
        out.append(rules[m_.group(1)](args))
        i = end
    out.append(text[i:])
    return "".join(out)


def _ctor(typ):
    def f(args):
        if len(args) == 1:
            return "((%s)(%s))" % (typ, args[0])      # scalar splat / same-size / truncating cast
        return "%s(%s)" % (typ, ",".join(args))
    return f


HLSL_RULES = {
    "atan": lambda a: ("atan2(%s)" if len(a) == 2 else "atan(%s)") % ",".join(a),
    "mod": lambda a: "((%s) - (%s) * floor((%s) / (%s)))" % (a[0], a[1], a[0], a[1]),
    "vec2": _ctor("float2"), "vec3": _ctor("float3"), "vec4": _ctor("float4"),
    "ivec2": _ctor("int2"), "ivec3": _ctor("int3"), "ivec4": _ctor("int4"),
}


HLSL_RESERVED = ["linear", "point", "line", "triangle", "centroid", "sample", "precise", "shared", "export", "half",
                 "pass", "texture", "string", "vector", "matrix", "fixed", "snorm", "unorm", "smooth", "extern"]


def to_hlsl(code):
    """Translate the generated GLSL ES shader into OBS-flavoured HLSL for the obs-shaderfilter plugin (a '.shader')."""
    lib, main = code.split("\nvoid main() {", 1)
    lines = []
    for line in lib.splitlines():
        if line.startswith(("#version", "precision ", "in vec2 v_texcoord;", "uniform sampler2D tex;",
                            "uniform float time;", "out vec4 fragColor;")):
            continue
        lines.append(line)
    lib = "\n".join(lines)
    lib = lib.replace("// Generated by Compositor to Hyprshade (Blender node tree -> GLSL ES 3.00)",
                      "// Generated by Compositor to Hyprshade (Blender node tree -> OBS HLSL, for obs-shaderfilter)", 1)
    lib = lib.replace("vec2 res() { return vec2(textureSize(tex, 0)); }", "vec2 res() { return uv_size; }")
    lib = lib.replace("vec4 c = texture(tex, t);", "vec4 c = image.SampleLevel(textureSampler, t, 0);")
    main = "void main() {" + main
    text = lib + "\n" + "\n@@MAIN@@\n" + main

    def native_const(m_):
        n = int(m_.group(1))
        args = _balanced_args("(" + m_.group(3) + ")", 0)[0]
        args = [a.strip() for a in args]
        if len(args) == 1:
            args = args * n
        return "const vec%d %s = float%d(%s);%s" % (n, m_.group(2), n, ", ".join(args), m_.group(4))
    # constants initialised with constructor helpers crash some HLSL front-ends: use the native constructor
    text = re.sub(r"(?m)^const vec([234]) (\w+) = vec[234]\((.*)\);(.*)$", native_const, text)

    def tr(t):
        t = re.sub(r"\bgl_FragCoord\.xy\b", "(floor(uv * uv_size) + 0.5)", t)
        t = _rewrite_calls(t, HLSL_RULES)
        t = re.sub(r"\bivec([234])\b", r"int\1", t)
        t = re.sub(r"\bvec([234])\b", r"float\1", t)
        t = re.sub(r"\bfract\(", "frac(", t)
        t = re.sub(r"\bmix\(", "lerp(", t)
        t = re.sub(r"\binversesqrt\(", "rsqrt(", t)
        t = re.sub(r"\bfloatBitsToUint\(", "asuint(", t)
        t = re.sub(r"\buintBitsToFloat\(", "asfloat(", t)
        t = re.sub(r"(?m)^const float (\w+)\[(\d+)\] = float\[\d+\]\((.*)\);", r"static const float \1[\2] = {\3};", t)
        t = re.sub(r"(?m)^const (float|int|uint|float2|float3|float4|vec2|vec3|vec4) ", r"static const \1 ", t)
        for w in HLSL_RESERVED:
            t = re.sub(r"\b%s\b(?!\s*\()" % w, w + "_", t) if w not in ("texture",) else t
        return t
    text = tr(text)
    text = re.sub(r"(?m)^static const (float|int|uint|float2|float3|float4) ", lambda m_: "static const %s " % m_.group(1), text)
    # OBS's effect parser has no `static`, no array parameters and cannot take initialised global
    # arrays/vectors reliably: LUTs become functions with a local table, constants become macros.
    def lut_fn(m_):
        return ("float lut_%s(float x) {\n    const float L[%s] = {%s};\n"
                "    float p = clamp(x, 0.0, 1.0) * %d.0;\n    int i = (int)floor(p);\n"
                "    int j = min(i + 1, %d);\n    return lerp(L[i], L[j], p - (float)i);\n}"
                % (m_.group(1), m_.group(2), m_.group(3), int(m_.group(2)) - 1, int(m_.group(2)) - 1))
    text = re.sub(r"(?m)^static const float (\w+)\[(\d+)\] = \{(.*)\};", lut_fn, text)
    text = re.sub(r"\blut_eval\((\w+),\s*", r"lut_\1(", text)
    text = re.sub(r"(?s)float lut_eval\(float lut\[\d+\], float x\) \{.*?\n\}\n", "", text)
    text = re.sub(r"(?m)^static const (?:float|int|uint|float2|float3|float4) (\w+) = (.*?);(.*)$",
                  lambda m_: "#define %s (%s)%s" % (m_.group(1), m_.group(2), (" " + m_.group(3)) if m_.group(3).strip() else ""), text)
    lib_part, main_part = text.split("@@MAIN@@", 1)
    main_part = main_part.replace("void main() {", "float4 mainImage(VertData v_in) : TARGET\n{", 1)
    main_part = main_part.replace("v_texcoord", "v_in.uv")
    main_part = re.sub(r"fragColor = (.*);", r"return \1;", main_part)
    main_part = main_part.replace("vec2 uv", "float2 uv").replace("vec4 c", "float4 c")
    return HLSL_HELPERS + "\n" + lib_part + main_part


# ---- KiaseCut --------------------------------------------------------------------------------------
# The editor runs the filter as an `effect(vec2 uv)` function (kiasecut/filters/FORMAT.md): `source` is the
# picture below (premultiplied), `time` the seconds since the clip started.  The generated code is the same
# as for Hyprshade except for the wrapper, and the node group's inputs, which become `// @param` lines.

KC_INPUT_TEX = """vec4 input_tex(vec2 uv) {
    if (uv.x < 0.0 || uv.y < 0.0 || uv.x > 1.0 || uv.y > 1.0) return vec4(0.0);
    vec2 t = vec2(uv.x, (FLIP_Y != 0) ? 1.0 - uv.y : uv.y);
    vec4 c = unpremultiply(src(t));
#if LINEARIZE
    c.rgb = srgb_to_lin(c.rgb);   // Blender's compositor works in scene-linear
#endif
    c.rgb *= c.a;                 // Blender's images are premultiplied
    return c;
}
"""

KC_EFFECT = """
vec4 effect(vec2 uv_in) {
    vec2 uv = vec2(uv_in.x, (FLIP_Y != 0) ? 1.0 - uv_in.y : uv_in.y);
    vec4 c = %s;
    float a = clamp(c.a, 0.0, 1.0);
    vec3 rgb = c.rgb;
#if COMPOSITE_OVER_SCREEN
    vec4 s = input_tex(uv);
    rgb += s.rgb * (1.0 - a);   // 'over' the picture below
    a = a + s.a * (1.0 - a);
#endif
#if LINEARIZE
    rgb = (a > 0.0) ? lin_to_srgb(rgb / a) * a : vec3(0.0);
#endif
    return vec4(min(clamp(rgb, 0.0, 1.0), vec3(a)), a);
}
"""


def _lin_to_srgb_py(x):
    x = min(max(float(x), 0.0), 1.0)
    return 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1.0 / 2.4) - 0.055


def _kc_label(s):
    return re.sub(r'["\\\n]', "", str(s)) or "value"


def kc_param(p):
    """(`// @param` line, GLSL macro line or '') for one node-group input (see param_spec())."""
    n, kind, d, lo, hi = p["name"], p["kind"], p["default"], p["lo"], p["hi"]
    lab = _kc_label(p["label"])
    if kind in ("float", "int"):
        d = float(d if not isinstance(d, (tuple, list)) else d[0])
        m = max(10.0, 10.0 * abs(d))
        lo = -m if lo is None else lo
        hi = m if hi is None else hi
        if hi <= lo:
            hi = lo + 1.0
        if kind == "int":                       # the shader works on floats: int uniform plus a macro
            return ('// @param %s_i int %d %d %d "%s"' % (n, round(d), round(lo), round(hi), lab),
                    "#define %s float(%s_i)" % (n, n))
        return '// @param %s float %s %s %s "%s"' % (n, ("%.6g" % d), ("%.6g" % lo), ("%.6g" % hi), lab), ""
    if kind == "bool":
        return ('// @param %s_b bool %s "%s"' % (n, "1" if float(d) else "0", lab),
                "#define %s (%s_b ? 1.0 : 0.0)" % (n, n))
    if kind == "color":
        v = list(d) + [1.0] * (4 - len(d))
        hexv = "#" + "".join("%02x" % round(_lin_to_srgb_py(x) * 255) for x in v[:3]) + "%02x" % round(min(max(v[3], 0.0), 1.0) * 255)
        return ('// @param %s_c color %s "%s"' % (n, hexv, lab),
                "#if LINEARIZE\n#define %s vec4(srgb_to_lin(%s_c.rgb), %s_c.a)\n#else\n#define %s %s_c\n#endif" % (n, n, n, n, n))
    v = ([float(x) for x in d] + [0.0, 0.0, 0.0])[:2 if kind == "vec2" else 3]     # vec2 / vec3
    m = max(10.0, 10.0 * max(abs(x) for x in v))
    lo = -m if lo is None else lo
    hi = m if hi is None else hi
    vals = "%s %s %s" % (",".join("%.6g" % x for x in v), "%.6g" % lo, "%.6g" % hi)
    if kind == "vec2":                                    # the shader works on vec3: vec2 uniform plus a macro
        return ('// @param %s_v vec2 %s "%s"' % (n, vals, lab), "#define %s vec3(%s_v, 0.0)" % (n, n))
    return '// @param %s vec3 %s "%s"' % (n, vals, lab), ""


def to_kiasecut(code, conv, name):
    """Re-wrap the generated GLSL ES shader as a KiaseCut filter (a .glsl with `// @param` header lines)."""
    lib, _main = code.split("\nvoid main() {", 1)
    drop = ("#version", "precision ", "in vec2 v_texcoord;", "uniform sampler2D tex;", "uniform float time;",
            "out vec4 fragColor;")
    lib = "\n".join(l for l in lib.splitlines() if not l.startswith(drop))
    lib = lib.replace("// Generated by Compositor to Hyprshade (Blender node tree -> GLSL ES 3.00)",
                      "// Generated by Compositor to Hyprshade (Blender node tree -> KiaseCut filter)", 1)
    lib = lib.replace("vec2 res() { return vec2(textureSize(tex, 0)); }", "vec2 res() { return resolution; }")
    lib, n = re.subn(r"vec4 input_tex\(vec2 uv\) \{.*?\n\}\n", lambda m_: KC_INPUT_TEX, lib, count=1, flags=re.S)
    head, macros = [], []
    for p in conv.params:
        h, mc = kc_param(p)
        head.append(h)
        if mc:
            macros.append(mc)
        lib = lib.replace(p["const_line"] + "\n", "", 1)       # the constant is now a parameter
    final = re.search(r"vec4 c = (.*);\n#if COMPOSITE_OVER_SCREEN", "\nvoid main() {" + _main, re.S)
    if final is None:
        raise RuntimeError("could not find the result expression")
    desc = re.sub(r"\s+", " ", "Blender compositor '%s'. Group inputs are parameters; Linear light / Flip Y / sample counts "
                  "are the #define lines below." % name)
    top = ["// @filter %s" % re.sub(r"\s+", " ", str(name)), "// @category Blender", "// @description " + desc] + head
    body = "\n".join(macros)
    marker = "// ---- tunables"
    if marker not in lib:
        raise RuntimeError("unexpected shader layout")
    lib = lib.replace(marker, (body + "\n\n" if body else "") + marker, 1)
    return "\n".join(top) + "\n" + lib + "\n" + KC_EFFECT % final.group(1)


def slangp_for(name):
    return ('shaders = 1\n\n'
            'shader0 = "%s.slang"\n'
            'filter_linear0 = "true"\n'
            'wrap_mode0 = "clamp_to_edge"\n'
            'scale_type0 = "source"\n'
            'scale0 = "1.0"\n' % name)


def convert_tree(tree, settings=None, fmt="HYPRSHADE"):
    c = Converter(tree)
    c.settings.update(settings or {})
    code = _finish(c, c.convert())
    code = apply_settings(code, c.settings, float(scene_fps()))
    if fmt == "SHADERGLASS":
        code = to_slang(code, c.settings.get("frame_rate", 60.0))
    elif fmt == "HLSL":
        code = to_hlsl(code)
    elif fmt == "KIASECUT":
        code = to_kiasecut(code, c, getattr(tree, "name", "filter"))
    return code, c.warnings


# ---------------------------------------------------------------------------
# Blender UI / CLI
# ---------------------------------------------------------------------------
try:
    import bpy
    from bpy.props import StringProperty, EnumProperty, BoolProperty, IntProperty, FloatProperty
except ImportError:
    bpy = None


def compositor_trees():
    res = []
    for s in bpy.data.scenes:
        t = getattr(s, "compositing_node_group", None) or getattr(s, "node_tree", None)
        if t is not None and t not in res:
            res.append(t)
    for g in bpy.data.node_groups:
        if g.bl_idname == "CompositorNodeTree" and g not in res:
            res.append(g)
    return res


def write_shader(tree, path, settings=None, fmt="HYPRSHADE"):
    """Convert one tree and write it.  Hyprshade: .glsl; ShaderGlass: .slang plus a .slangp preset; OBS: .shader.
    Returns (list of written files, warnings)."""
    import os
    code, warns = convert_tree(tree, settings, fmt)
    stem = os.path.splitext(path)[0]
    if fmt == "SHADERGLASS":
        files = {stem + ".slang": code, stem + ".slangp": slangp_for(os.path.basename(stem))}
    elif fmt == "HLSL":
        files = {stem + ".shader": code}
    else:
        files = {stem + ".glsl": code}
    for p, text in files.items():
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return list(files), warns


def export_all(folder, settings=None, fmt="HYPRSHADE"):
    import os
    os.makedirs(folder, exist_ok=True)
    report = {}
    for t in compositor_trees():
        try:
            fn = re.sub(r'[\\/:*?"<>|]+', "_", t.name)
            if fmt == "SHADERGLASS":
                fn = re.sub(r"\s+", "_", fn)       # RetroArch preset paths are happier without spaces
            _, warns = write_shader(t, os.path.join(folder, fn), settings, fmt)
        except Exception as e:
            report[t.name] = ["skipped: %s" % e]
            continue
        report[t.name] = warns
    return report


_DEFAULT_GROUP_NAME = re.compile(r"^(Group|Node ?Group)([ .]\d+)?$", re.I)


def child_groups(parent):
    """Group nodes directly inside `parent` (one per distinct node tree, unmuted), as (export name, node tree).
    The name is the node's label, else its name, else (default 'Group.001' names) the node tree's name."""
    res, seen_trees, seen_names = [], set(), set()
    for n in parent.nodes:
        if n.bl_idname != "CompositorNodeGroup" or getattr(n, "mute", False):
            continue
        sub = getattr(n, "node_tree", None)
        if sub is None or sub.name in seen_trees:
            continue
        seen_trees.add(sub.name)
        name = n.label or (sub.name if _DEFAULT_GROUP_NAME.match(n.name) else n.name)
        name = re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or sub.name
        base, k = name, 1
        while name.lower() in seen_names:
            k += 1
            name = "%s_%d" % (base, k)
        seen_names.add(name.lower())
        res.append((name, sub))
    return res


def export_children(parent, folder, settings=None, fmt="HYPRSHADE"):
    """Batch export: every effect group node inside `parent` becomes its own shader file in `folder`.
    Returns {name: warnings}."""
    import os
    os.makedirs(folder, exist_ok=True)
    report = {}
    for name, sub in child_groups(parent):
        fn = re.sub(r"\s+", "_", name) if fmt == "SHADERGLASS" else name
        try:
            _, warns = write_shader(sub, os.path.join(folder, fn), settings, fmt)
        except Exception as e:
            report[name] = ["skipped: %s" % e]
            continue
        report[name] = warns
    return report


if bpy:
    _enum_cache = []
    _D = {k: d for k, _, _, _, d in SETTING_DEFS}

    def _tree_items(self, context):
        global _enum_cache
        _enum_cache = [(t.name, t.name, "") for t in compositor_trees()]
        return _enum_cache or [("", "(none)", "")]

    class NODE_OT_export_hyprshade(bpy.types.Operator):
        bl_idname = "node.export_hyprshade"
        bl_label = "Export to Hyprshade"
        bl_description = "Convert a compositor node tree / node group to a Hyprland screen shader"

        filepath: StringProperty(subtype="FILE_PATH", default="//shader.glsl")
        format: EnumProperty(name="Format", default="HYPRSHADE", items=FORMATS,
                             description="Which program the shader is for. The file extension is set automatically")
        tree: EnumProperty(name="Tree / Group", items=_tree_items)
        all_groups: BoolProperty(name="Export every tree to a folder", default=False,
                                 description="Use the folder of the file path; one .glsl per tree")
        batch_children: BoolProperty(name="Batch: export each group inside the tree", default=False,
                                     description="Export every group node inside the selected tree / group as its own shader "
                                                 "(use the folder of the file path; files are named after the node's label / name)")
        # ---- shader settings (written into the #define block of the shader) ----
        flip_y: BoolProperty(name="Flip Y", default=True, description=_D["flip_y"])
        linearize: BoolProperty(name="Linear light", default=True, description=_D["linearize"])
        composite: EnumProperty(name="Transparent shows screen", default="AUTO", description=_D["composite"],
                                items=[("AUTO", "Auto", ""), ("ON", "On", ""), ("OFF", "Off", "")])
        scene_fps: FloatProperty(name="FPS (0 = scene)", default=0.0, min=0.0, soft_max=240.0, description=_D["scene_fps"])
        blur_samples: IntProperty(name="Blur samples", default=32, min=4, max=256, description=_D["blur_samples"])
        blur_adapt: BoolProperty(name="Fewer blur samples for big radii", default=True, description=_D["blur_adapt"])
        bloom_samples: IntProperty(name="Bloom samples", default=32, min=4, max=256, description=_D["bloom_samples"])
        sun_steps: IntProperty(name="Sun Beams steps", default=24, min=4, max=256, description=_D["sun_steps"])
        dilate_k: IntProperty(name="Dilate/Erode taps", default=5, min=1, max=32, description=_D["dilate_k"])
        pixelate_taps: IntProperty(name="Pixelate taps", default=3, min=1, max=16, description=_D["pixelate_taps"])
        frame_rate: FloatProperty(name="FrameCount rate (ShaderGlass)", default=60.0, min=1.0, soft_max=240.0, description=_D["frame_rate"])
        tex_scale: FloatProperty(name="Texture scale", default=1.0, min=0.001, soft_max=100.0, description=_D["tex_scale"])

        def settings(self):
            return {k: getattr(self, k) for k in DEFAULT_SETTINGS}

        def draw(self, context):
            col = self.layout.column()
            col.prop(self, "format", expand=True)
            col.prop(self, "tree")
            col.prop(self, "batch_children")
            col.prop(self, "all_groups")
            box = self.layout.box()
            box.label(text="Shader settings")
            for k in DEFAULT_SETTINGS:
                box.prop(self, k)

        def execute(self, context):
            import os
            path = bpy.path.abspath(self.filepath)
            if self.batch_children:
                parent = bpy.data.node_groups.get(self.tree)
                if parent is None:
                    parent = next((t for t in compositor_trees() if t.name == self.tree), None)
                if parent is None:
                    self.report({"ERROR"}, "No compositor tree selected")
                    return {"CANCELLED"}
                report = export_children(parent, os.path.dirname(path) or ".", self.settings(), self.format)
                if not report:
                    self.report({"WARNING"}, "No group nodes found inside '%s'" % parent.name)
                    return {"CANCELLED"}
                for name, ws in report.items():
                    for w in ws:
                        self.report({"WARNING"}, "%s: %s" % (name, w))
                self.report({"INFO"}, "Exported %d effects from '%s'" % (len(report), parent.name))
                return {"FINISHED"}
            if self.all_groups:
                report = export_all(os.path.dirname(path) or ".", self.settings(), self.format)
                for name, ws in report.items():
                    for w in ws:
                        self.report({"WARNING"}, "%s: %s" % (name, w))
                self.report({"INFO"}, "Exported %d trees" % len(report))
                return {"FINISHED"}
            tree = bpy.data.node_groups.get(self.tree)
            if tree is None:
                for t in compositor_trees():
                    if t.name == self.tree:
                        tree = t
            if tree is None:
                self.report({"ERROR"}, "No compositor tree selected")
                return {"CANCELLED"}
            try:
                files, warns = write_shader(tree, path, self.settings(), self.format)
            except Exception as e:
                self.report({"ERROR"}, str(e))
                return {"CANCELLED"}
            path = ", ".join(files)
            for w in warns:
                self.report({"WARNING"}, w)
            self.report({"INFO"}, "Wrote %s" % path)
            return {"FINISHED"}

        def invoke(self, context, event):
            tree = getattr(context.space_data, "node_tree", None)
            if tree is not None:
                try:
                    self.tree = tree.name
                except TypeError:
                    pass
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}

    def menu_func(self, context):
        self.layout.separator()
        self.layout.operator(NODE_OT_export_hyprshade.bl_idname, text="Export as Shader / Filter (Hyprshade, OBS, ShaderGlass, KiaseCut)")

    def register():
        bpy.utils.register_class(NODE_OT_export_hyprshade)
        bpy.types.NODE_MT_node.append(menu_func)

    def unregister():
        bpy.types.NODE_MT_node.remove(menu_func)
        bpy.utils.unregister_class(NODE_OT_export_hyprshade)


def _cli():
    import sys
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        return False
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", help="tree / group name (default: scene compositor)")
    ap.add_argument("--out", required=True, help="output .glsl file, or folder with --all")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--children", action="store_true",
                    help="batch: export every group node inside --tree (default: scene compositor) as its own shader into the folder --out")
    ap.add_argument("--format", choices=[f[0].lower() for f in FORMATS], default="hyprshade",
                    help="kiasecut (.glsl filter for the KiaseCut editor), hyprshade (.glsl), shaderglass (.slang + .slangp) or hlsl (.shader for obs-shaderfilter)")
    for key, define, default, label, desc in SETTING_DEFS:
        opt = "--" + key.replace("_", "-")
        if isinstance(default, bool):
            ap.add_argument(opt, type=lambda x: x.lower() in ("1", "true", "yes", "on"), default=default, help=desc)
        elif isinstance(default, str):
            ap.add_argument(opt, default=default, help=desc)
        else:
            ap.add_argument(opt, type=type(default), default=default, help=desc)
    a = ap.parse_args(argv)
    st = {k: getattr(a, k) for k in DEFAULT_SETTINGS}
    if a.children:
        parent = bpy.data.node_groups.get(a.tree) if a.tree else compositor_trees()[0]
        for k, v in export_children(parent, a.out, st, a.format.upper()).items():
            print(k, "->", len(v), "warnings")
        return True
    if a.all:
        for k, v in export_all(a.out, st, a.format.upper()).items():
            print(k, "->", len(v), "warnings")
        return True
    tree = bpy.data.node_groups.get(a.tree) if a.tree else compositor_trees()[0]
    files, warns = write_shader(tree, a.out, st, a.format.upper())
    print("wrote", ", ".join(files))
    print("\n".join(warns))
    return True


if bpy and __name__ == "__main__":
    if not _cli():
        register()
