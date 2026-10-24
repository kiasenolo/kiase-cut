import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kiasecut import curves, edit, project  # noqa: E402

S = 1_000_000


def css(x1, y1, x2, y2, x):
    """Reference CSS cubic-bezier easing: progress at time fraction x."""
    lo, hi = 0.0, 1.0
    for _ in range(60):
        s = (lo + hi) / 2
        bx = 3 * (1 - s) ** 2 * s * x1 + 3 * (1 - s) * s * s * x2 + s ** 3
        lo, hi = (s, hi) if bx < x else (lo, s)
    s = (lo + hi) / 2
    return 3 * (1 - s) ** 2 * s * y1 + 3 * (1 - s) * s * s * y2 + s ** 3


class CurveTests(unittest.TestCase):
    def test_bezier_matches_css(self):
        for spec in ((0.42, 0, 0.58, 1), (0.25, 0.1, 0.25, 1), (0.68, -0.55, 0.27, 1.55)):
            a, b = [0, 10.0, 0, 0, 0, 0], [2 * S, 30.0, 0, 0, 0, 0]
            curves.apply_bezier(a, b, *spec)
            p = {"keys": [a, b]}
            for x in (0.1, 0.3, 0.5, 0.8):
                self.assertAlmostEqual(curves.value(p, x * 2 * S), 10 + 20 * css(*spec, x), places=6)
            back = curves.segment_bezier(a, b)
            for u, v in zip(back, spec):
                self.assertAlmostEqual(u, v, places=9)

    def test_parse(self):
        self.assertEqual(curves.parse_bezier("cubic-bezier(0.42, 0, .58, 1)"), (0.42, 0.0, 0.58, 1.0))
        self.assertEqual(curves.parse_bezier("0.1 0.2 0.3 0.4"), (0.1, 0.2, 0.3, 0.4))
        with self.assertRaises(ValueError):
            curves.parse_bezier("0.1, 0.2")

    def test_set_keys_sanitises(self):
        p = project.new()
        p["tracks"] = [{"id": "t0", "kind": "video", "name": "v", "clips": [
            {"id": "c1", "type": "image", "start_us": 0, "duration_us": 2 * S, "source_start_us": 0,
             "media": {"path": "x", "width": 10, "height": 10}, "transform": {"x": 0.0}}]}]
        edit.set_keys(p, "c1", "transform", "x", [[3 * S, 1, 0, 0, 0, 0], [-5, 0, -9, 0, 9 * S, 0]])
        keys = p["tracks"][0]["clips"][0]["transform"]["x"]["keys"]
        self.assertEqual([k[0] for k in keys], [0, 2 * S])        # clamped into the clip
        self.assertEqual(keys[0][4], 2 * S)                         # handle stops at the next key
        self.assertEqual(keys[0][2], 0.0)
        with self.assertRaises(edit.EditError):
            edit.set_keys(p, "c1", "transform", "x", [[0, 0, 0, 0, 0, 0], [3000, 1, 0, 0, 0, 0]])


if __name__ == "__main__":
    unittest.main()
