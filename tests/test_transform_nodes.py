"""Flip, Crop, Rotate, Map UV and Split (nodes/*.glsl): Blender's sockets and results, checked against Blender 5.2 (the cases below are what it gave)."""
import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kiasecut import fx, nodemenu  # noqa: E402

W, H = 64, 40
NAMES = ["flip", "crop", "rotate", "map_uv", "split"]


def engine():
    try:
        return fx.Engine()
    except fx.FilterError as exc:
        raise unittest.SkipTest(str(exc))


def picture():
    """Rows top-down; red = x, green = y (down), blue a chequer: every pixel tells where it is."""
    y, x = np.mgrid[0:H, 0:W]
    a = np.ones((H, W, 4), np.float32)
    a[..., 0] = (x + 0.5) / W
    a[..., 1] = (y + 0.5) / H
    a[..., 2] = ((x // 8 + y // 8) % 2) * 0.8 + 0.1
    return a


class TransformNodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eng = engine()

    def tex(self, a):
        t = self.eng.ctx.texture((W, H), 4, a.astype(np.float16).tobytes(), dtype="f2")
        t.filter = (self.eng.mgl.LINEAR, self.eng.mgl.LINEAR)
        t.repeat_x = t.repeat_y = False
        return t

    def run_node(self, name, settings, src, inputs=None):
        d = fx.get("builtin:nodes/" + name)
        self.assertIsNone(d.error, name)
        vals = {p.name: fx.uniform_value(p, settings.get(p.name), 0) for p in d.params}
        eng = self.eng
        with eng.ctx:
            dest = eng.ctx.texture((W, H), 4, dtype="f2")
            fb = eng.ctx.framebuffer(color_attachments=[dest])
            out = eng.run_tex(d, vals, self.tex(src), W, H, inputs={k: self.tex(v) for k, v in (inputs or {}).items()}, dest=(dest, fb))
            return np.frombuffer(out.read(), np.float16).reshape(H, W, 4).astype(np.float32)

    def test_every_node_loads_and_is_in_the_menu(self):
        placed = nodemenu.placed()
        for name in NAMES:
            d = fx.get("builtin:nodes/" + name)
            self.assertIsNone(d.error, name)
            self.assertIn("builtin:nodes/" + name, placed, name)

    def test_sockets_and_menus_are_blenders(self):
        def menu(node, param):
            return next(p.items for p in fx.get("builtin:nodes/" + node).params if p.name == param)
        for node in ("rotate", "map_uv"):
            self.assertEqual(menu(node, "interp"), ["最近點", "雙線性", "雙三次", "各向異性"])
            self.assertEqual(menu(node, "ext_x"), ["裁切", "延伸", "重複"])
            self.assertEqual(menu(node, "ext_y"), ["裁切", "延伸", "重複"])
        self.assertEqual([p.name for p in fx.get("builtin:nodes/crop").params], ["x", "y", "width", "height", "alpha_crop"])
        self.assertEqual([n for n, _ in fx.get("builtin:nodes/split").inputs], ["b", "angle"])

    def test_flip_mirrors_the_picture(self):
        p = picture()
        np.testing.assert_allclose(self.run_node("flip", {"flip_x": True}, p), p[:, ::-1], atol=1e-2)
        np.testing.assert_allclose(self.run_node("flip", {"flip_y": True}, p), p[::-1], atol=1e-2)
        np.testing.assert_allclose(self.run_node("flip", {"flip_x": True, "flip_y": True}, p), p[::-1, ::-1], atol=1e-2)
        np.testing.assert_allclose(self.run_node("flip", {}, p), p, atol=1e-2)

    def test_crop_keeps_the_region_from_the_bottom_left(self):
        p = picture()
        got = self.run_node("crop", {"x": 10, "y": 5, "width": 30, "height": 20, "alpha_crop": True}, p)
        rows, cols = slice(H - 25, H - 5), slice(10, 40)             # (Y counts from the bottom)
        np.testing.assert_allclose(got[rows, cols], p[rows, cols], atol=1e-2)
        self.assertEqual(int((got[..., 3] > 0.5).sum()), 600)
        moved = self.run_node("crop", {"x": 10, "y": 5, "width": 30, "height": 20}, p)          # (Alpha Crop off: in the middle of the canvas)
        np.testing.assert_allclose(moved[10:30, 17:47], p[rows, cols], atol=1e-2)
        self.assertEqual(int((moved[..., 3] > 0.5).sum()), 600)

    def test_crop_is_at_least_a_pixel_and_inside_the_picture(self):
        p = picture()
        self.assertEqual(int((self.run_node("crop", {"x": 10, "y": 5, "width": 0, "height": 20, "alpha_crop": True}, p)[..., 3] > 0.5).sum()), 20)
        self.assertEqual(int((self.run_node("crop", {"x": 50, "y": 30, "width": 30, "height": 20, "alpha_crop": True}, p)[..., 3] > 0.5).sum()), 140)

    def test_split_takes_the_first_image_below_the_line(self):
        a, b = picture(), 1.0 - picture()
        b[..., 3] = 1.0
        got = self.run_node("split", {"position": (0.3, 0.6), "angle": math.degrees(0.3)}, a, {"b": b})
        y, x = np.mgrid[0:H, 0:W]
        texel_y = H - 1 - y
        first = (-math.sin(0.3)) * (0.3 * W - x) + math.cos(0.3) * (0.6 * H - texel_y) <= 0
        np.testing.assert_allclose(got[first], a[first], atol=1e-2)
        np.testing.assert_allclose(got[~first], b[~first], atol=1e-2)

    def test_rotate_a_quarter_turn_is_counter_clockwise(self):
        y, x = np.mgrid[0:H, 0:W]
        p = np.ones((H, W, 4), np.float32)
        p[..., 0] = (x + 0.5) / W
        p[..., 1] = (y + 0.5) / H
        p[..., 2] = 0.0
        got = self.run_node("rotate", {"angle": 90.0, "interp": 0}, p)
        centre = got[H // 2, W // 2]
        np.testing.assert_allclose(centre[:3], p[H // 2, W // 2][:3], atol=0.03)
        right = got[H // 2, W // 2 + 5]                                  # (counter-clockwise: the point right of the centre came from below it)
        self.assertGreater(right[1], 0.5)
        self.assertGreater(right[3], 0.5)

    def test_map_uv_with_the_identity_gives_the_picture_and_without_uv_nothing(self):
        p = picture()
        y, x = np.mgrid[0:H, 0:W]
        uvp = np.zeros((H, W, 4), np.float32)
        uvp[..., 0] = (x + 0.5) / W
        uvp[..., 1] = 1.0 - (y + 0.5) / H
        uvp[..., 2] = 1.0
        uvp[..., 3] = 1.0
        np.testing.assert_allclose(self.run_node("map_uv", {"interp": 1}, p, {"uv": uvp}), p, atol=1e-2)
        d = fx.get("builtin:nodes/map_uv")
        vals = {q.name: fx.uniform_value(q, None, 0) for q in d.params}
        with self.eng.ctx:
            out = self.eng.run_tex(d, vals, self.tex(p), W, H)
            self.assertEqual(float(np.frombuffer(out.read(), np.float16).max()), 0.0)


if __name__ == "__main__":
    unittest.main()
