"""Every built-in filter reads, compiles and runs at its defaults (and at every menu choice)."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kiasecut import fx  # noqa: E402


class BuiltinFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.eng = fx.Engine()
        except fx.FilterError:
            cls.eng = None

    def test_all_run(self):
        if self.eng is None:
            self.skipTest("no OpenGL for filters")
        pic = np.zeros((54, 96, 4), np.uint8)
        pic[10:40, 20:70] = (250, 240, 200, 255)
        for ref in fx.builtin_refs():
            d = fx.get(ref)
            with self.subTest(filter=ref):
                self.assertIsNone(d.error)
                vals = {p.name: fx.uniform_value(p, None, 0) for p in d.params}
                menus = [p for p in d.params if p.type == "menu"]
                for p in menus or [None]:
                    for k in range(len(p.items) if p else 1):
                        if p:
                            vals[p.name] = k
                        out = self.eng.run(d, vals, pic, time=0.5, progress=0.5, frame=3, unit=54 / 1080)
                        self.assertEqual(out.shape, pic.shape)
                    if p:
                        vals[p.name] = fx.uniform_value(p, None, 0)

    def test_blender_ones_named(self):
        names = {fx.get(ref).name for ref in fx.builtin_refs()}
        for n in ("Glare", "Lens Distortion", "Vignette", "Sensor Noise"):
            self.assertIn("[Blender] " + n, names)


if __name__ == "__main__":
    unittest.main()
