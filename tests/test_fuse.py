"""Fused nodes (fuse.py): a group of pointwise nodes drawn in one pass gives the picture the nodes drawn one by one give."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from kiasecut import fuse, fx, nodegraph as ng  # noqa: E402


def engine():
    try:
        return fx.Engine()
    except fx.FilterError as exc:
        raise unittest.SkipTest(str(exc))


class FuseTests(unittest.TestCase):
    W, H = 64, 48

    def picture(self):
        rng = np.random.default_rng(3)
        img = (rng.random((self.H, self.W, 4)) * 255).astype(np.uint8)
        img[..., 3] = 255
        return img

    def draw(self, g, params, on):
        eng = engine()
        pool = ng.Pool(eng)
        was, fuse.enabled = fuse.enabled, on
        try:
            with eng.ctx:
                src = eng.ctx.texture((self.W, self.H), 4, self.picture().tobytes())
                src.filter = (eng.mgl.LINEAR, eng.mgl.LINEAR)
                errors = []
                tex, owner = ng.evaluate(eng, g, params, src, self.W, self.H, pool.alloc, pool.free, errors=errors)
                self.assertEqual(errors, [])
                return ng.read_rgba8(tex).copy()
        finally:
            fuse.enabled = was

    def chain(self, refs):
        g = ng.new_graph()
        prev = "input"
        for i, ref in enumerate(refs):
            n = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/" + ref}, i * 200, 0)
            ng.connect(g, prev, n, "src")
            prev = n
        ng.connect(g, prev, "output", "src")
        return g, prev

    def test_a_chain_is_the_same_fused_and_not(self):
        g, _ = self.chain(["exposure", "gamma", "bright_contrast", "hue_sat_value", "exposure", "clamp"])
        params = ng.default_params(g)
        for key, v in (("exposure1.exposure", 0.7), ("gamma2.gamma", 1.6), ("exposure5.exposure", -0.4)):
            if key in params:
                params[key] = v
        a, b = self.draw(g, params, False), self.draw(g, params, True)
        self.assertLessEqual(int(np.abs(a.astype(int) - b.astype(int)).max()), 2)

    def test_a_node_with_two_pictures_in_a_group(self):
        g, last = self.chain(["exposure", "mix", "math", "set_alpha"])
        other = ng.add_node(g, {"type": ng.FILTER, "ref": "builtin:nodes/gamma"}, 0, 300)
        ng.connect(g, "input", other, "src")
        ng.connect(g, other, "mix1", "b")
        params = ng.default_params(g)
        a, b = self.draw(g, params, False), self.draw(g, params, True)
        self.assertLessEqual(int(np.abs(a.astype(int) - b.astype(int)).max()), 2)

    def test_every_fusable_node_compiles_next_to_itself_and_another(self):
        import glob
        eng = engine()
        refs = ["builtin:nodes/" + os.path.basename(f)[:-5] for f in sorted(glob.glob(os.path.join(fx.PKG, "nodes", "*.glsl")))]
        other = fx.get("builtin:nodes/exposure")
        fusable = [fx.get(r) for r in refs if fuse.can_fuse(fx.get(r))]
        self.assertGreater(len(fusable), 20)
        for d in fusable:
            for second in (d, other):
                fused, _ = fuse.build([(d, {"src": ("ext", 0)}, 0), (second, {"src": ("node", 0)}, 0)])
                try:
                    eng._program(fused)
                except fx.FilterError as exc:
                    self.fail(f"{d.name} + {second.name}: {exc}")

    def test_groups_are_found(self):
        g, last = self.chain(["exposure", "gamma", "exposure"])
        d = fx.get("builtin:nodes/exposure")
        self.assertTrue(fuse.can_fuse(d))
        self.assertFalse(fuse.can_fuse(fx.get("builtin:nodes/rotate")))          # (it reads its picture somewhere else than at its pixel)
        self.assertFalse(fuse.can_fuse(fx.get("builtin:blender_glare")))


if __name__ == "__main__":
    unittest.main()
