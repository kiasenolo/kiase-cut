"""gles.py: the part of moderngl KiaseCut uses, on OpenGL ES 3 (Android's GPUs speak nothing else).

The shader rewrite is tried everywhere; what needs a context (textures, framebuffers, programs, uniforms)
is skipped on a computer with no OpenGL ES 3.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from kiasecut import gles  # noqa: E402

try:
    gles.create_standalone_context().release()
    HAVE_GLES = True
except Exception:
    HAVE_GLES = False

VERTEX = "#version 330\nin vec2 pos;\nout vec2 uv_;\nvoid main() { uv_ = pos * 0.5 + 0.5; gl_Position = vec4(pos, 0.0, 1.0); }\n"


class ConvertTest(unittest.TestCase):
    def test_version_and_precision(self):
        out = gles.converted("#version 330\nvoid main() {}\n")
        self.assertTrue(out.startswith("#version 300 es\nprecision highp float;"))
        self.assertNotIn("#version 330", out)

    def test_macro_not_defined_yet_is_zero_in_an_if(self):
        out = gles.converted("#version 330\n#if LINEARIZE\nint a;\n#endif\n#define LINEARIZE 1\n#if LINEARIZE\nint b;\n#endif\n")
        self.assertIn("#if 0", out)
        self.assertEqual(out.count("#if LINEARIZE"), 1)

    def test_integers_in_float_array_constructors_are_floats(self):
        out = gles.converted("#version 330\nconst float A[4] = float[4](0, -755.9907, 4.87202079e-06, 12);\nint k = 3;\n")
        self.assertIn("float[4](0.0, -755.9907, 4.87202079e-06, 12.0)", out)
        self.assertIn("int k = 3;", out)

    def test_token_pasting_macro_is_written_out(self):
        out = gles.converted("#version 330\n#define DIM(F) { if (d == 0) F##_1d(ARGS); else F##_2d(ARGS); }\nvoid f() { DIM(noise) }\n")
        self.assertNotIn("##", out)
        self.assertIn("noise_1d(ARGS)", out)
        self.assertIn("noise_2d(ARGS)", out)

    def test_not_a_330_shader_is_refused(self):
        with self.assertRaises(gles.GLError):
            gles.converted("#version 450\nvoid main() {}\n")


@unittest.skipUnless(HAVE_GLES, "no OpenGL ES 3 here")
class ContextTest(unittest.TestCase):
    def setUp(self):
        try:
            self.ctx = gles.create_standalone_context()
        except gles.GLError as e:
            if "0x3002" not in str(e):                                # (EGL_BAD_ACCESS: a desktop OpenGL context another test file made
                raise                                                 #  is still bound in this process - run this file by itself then)
            self.skipTest(str(e))
        self.addCleanup(self.ctx.release)

    def draw(self, fragment, size=(8, 4), dtype="f1", **uniforms):
        ctx = self.ctx
        prog = ctx.program(vertex_shader=VERTEX, fragment_shader="#version 330\nin vec2 uv_;\nout vec4 fragColor;\n" + fragment)
        for k, v in uniforms.items():
            prog[k].value = v
        quad = ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], "f4").tobytes())
        tex = ctx.texture(size, 4, dtype=dtype)
        fbo = ctx.framebuffer(color_attachments=[tex])
        fbo.use()
        ctx.vertex_array(prog, [(quad, "2f", "pos")]).render(gles.TRIANGLE_STRIP)
        return np.frombuffer(fbo.read(components=4, dtype=dtype), {"f1": np.uint8, "f2": np.float16, "f4": np.float32}[dtype]
                             ).reshape(size[1], size[0], 4)

    def test_uniforms_of_every_kind(self):
        px = self.draw("uniform float a; uniform int n; uniform bool on; uniform vec3 v; uniform mat3 m;\n"
                       "void main() { vec3 t = m * vec3(1.0, 0.0, 0.0);"
                       " fragColor = vec4(a, float(n) / 255.0, on ? 1.0 : 0.0, t.y + v.z); }",
                       a=0.5, n=255, on=True, v=(0.0, 0.0, 0.25), m=(0.0, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0))
        self.assertEqual(px[0, 0].tolist(), [128, 255, 255, 191])

    def test_array_uniform_written_from_bytes(self):
        px = self.draw("uniform float c[3];\nvoid main() { fragColor = vec4(c[0], c[1], c[2], 1.0); }")
        self.assertEqual(px.shape, (4, 8, 4))
        prog = self.ctx.program(vertex_shader=VERTEX, fragment_shader="#version 330\nin vec2 uv_;\nout vec4 fragColor;\n"
                                "uniform float c[3];\nvoid main() { fragColor = vec4(c[0], c[1], c[2], 1.0); }")
        self.assertIn("c", prog)
        prog["c"].write(np.array([0.0, 0.5, 1.0], "f4").tobytes())

    def test_float_targets_keep_what_8_bit_cannot(self):
        px = self.draw("void main() { fragColor = vec4(2.5, -1.0, 0.25, 1.0); }", dtype="f4")
        self.assertEqual(px[0, 0].tolist(), [2.5, -1.0, 0.25, 1.0])
        px = self.draw("void main() { fragColor = vec4(2.5, -1.0, 0.25, 1.0); }", dtype="f2")
        self.assertEqual(px[0, 0].tolist(), [2.5, -1.0, 0.25, 1.0])

    def test_texture_write_read_swizzle_and_copy(self):
        ctx = self.ctx
        data = bytes(range(0, 32))                                   # 4 x 2 pixels, with zero bytes in it
        tex = ctx.texture((4, 2), 4, data)
        self.assertEqual(tex.read(), data)
        tex.write(bytes(reversed(data)))
        self.assertEqual(tex.read(), bytes(reversed(data)))
        other = ctx.texture((4, 2), 4)
        ctx.copy_framebuffer(other, tex.framebuffer())
        self.assertEqual(other.read(), bytes(reversed(data)))
        tex.swizzle = "BGRA"
        self.assertEqual(tex.swizzle, "BGRA")

    def test_mip_level_read(self):
        tex = self.ctx.texture((8, 8), 4, bytes([100, 150, 200, 255]) * 64)
        tex.build_mipmaps(0, 2)
        small = np.frombuffer(tex.read(level=2), np.uint8).reshape(2, 2, 4)
        self.assertLessEqual(int(np.abs(small.astype(int) - [100, 150, 200, 255]).max()), 1)

    def test_blend_and_viewport(self):
        ctx = self.ctx
        prog = ctx.program(vertex_shader=VERTEX, fragment_shader="#version 330\nin vec2 uv_;\nout vec4 fragColor;\n"
                           "void main() { fragColor = vec4(0.5, 0.0, 0.0, 0.5); }")
        quad = ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], "f4").tobytes())
        vao = ctx.vertex_array(prog, [(quad, "2f", "pos")])
        tex = ctx.texture((4, 4), 4)
        fbo = ctx.framebuffer(color_attachments=[tex])
        fbo.clear(0.0, 0.0, 1.0, 1.0)
        fbo.use()
        ctx.viewport = (0, 0, 2, 4)                                  # the left half only
        ctx.enable(gles.BLEND)
        ctx.blend_func = (gles.ONE, gles.ONE_MINUS_SRC_ALPHA)
        vao.render(gles.TRIANGLE_STRIP)
        ctx.disable(gles.BLEND)
        px = np.frombuffer(fbo.read(components=4), np.uint8).reshape(4, 4, 4)
        self.assertLessEqual(int(np.abs(px[0, 0].astype(int) - [128, 0, 128, 255]).max()), 1)
        self.assertEqual(px[0, 3].tolist(), [0, 0, 255, 255])

    def test_compile_error_names_the_shader(self):
        with self.assertRaises(gles.GLError) as cm:
            self.ctx.program(vertex_shader=VERTEX, fragment_shader="#version 330\nvoid main() { nonsense; }\n")
        self.assertIn("fragment shader", str(cm.exception))

    def test_context_made_current_for_a_block(self):
        a, b = self.ctx, gles.create_standalone_context()
        self.addCleanup(b.release)
        with a:
            tex = a.texture((2, 2), 4, bytes(16))
            with b:
                b.texture((2, 2), 4, bytes(16))
            self.assertEqual(tex.read(), bytes(16))                  # (a is current again)


if __name__ == "__main__":
    unittest.main()
