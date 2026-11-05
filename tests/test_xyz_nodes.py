"""The XYZ nodes' number boxes: @step, and Separate XYZ's own vector."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from kiasecut import fx  # noqa: E402
from kiasecut.ui.effects_panel import step_for  # noqa: E402


class XyzNodeTests(unittest.TestCase):
    def test_step_header_sets_the_step_of_the_boxes(self):
        d = fx.get("builtin:nodes/combine_xyz")
        self.assertIsNone(d.error)
        self.assertEqual([step_for(p) for p in d.params], [0.001, 0.001, 0.001])
        wide = fx.get("builtin:nodes/value").params[0]                    # (no @step: by the size of the range)
        self.assertEqual(step_for(wide), 1.0)

    def test_step_header_wants_number_parameters(self):
        d = fx.parse("// @param m menu a \"a|b\"\n// @step 0.1 m\nvec4 effect(vec2 uv) { return src(uv); }\n", "x")
        self.assertIsNotNone(d.error)

    def test_separate_xyz_has_a_vector_of_its_own(self):
        d = fx.get("builtin:nodes/separate_xyz")
        self.assertIsNone(d.error)
        p = next(q for q in d.params if q.name == "vec_in")
        self.assertEqual(p.type, "vec3")
        self.assertEqual(step_for(p), 0.001)

    def test_separate_xyz_gives_its_vector_when_nothing_is_linked(self):
        try:
            eng = fx.Engine()
        except fx.FilterError as exc:
            raise unittest.SkipTest(str(exc))
        d = fx.get("builtin:nodes/separate_xyz")
        W, H = 8, 6
        vals = {q.name: fx.uniform_value(q, (0.25, -2.0, 7.5), 0) for q in d.params}
        for index, want in enumerate((0.25, -2.0, 7.5)):
            with eng.ctx:
                src = eng.ctx.texture((W, H), 4, np.zeros((H, W, 4), np.float16).tobytes(), dtype="f2")
                dest = eng.ctx.texture((W, H), 4, dtype="f2")
                fb = eng.ctx.framebuffer(color_attachments=[dest])
                out = eng.run_tex(d, vals, src, W, H, output=index, dest=(dest, fb), src_on=False)
                got = np.frombuffer(out.read(), np.float16).reshape(H, W, 4)
            self.assertAlmostEqual(float(got[0, 0, 0]), want, places=2)


if __name__ == "__main__":
    unittest.main()
