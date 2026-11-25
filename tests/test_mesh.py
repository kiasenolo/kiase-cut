"""mesh.py: the letters of a 立體 text cut into triangles and pushed out into solids."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from kiasecut import assets, mesh  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])


def area(tris):
    u, v = tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]
    return float(np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]).sum() / 2)


SQUARE = np.array([(0, 0), (10, 0), (10, 10), (0, 10)], float)
HOLE = np.array([(3, 3), (3, 7), (7, 7), (7, 3)], float)             # (wound the other way)


class Meshes(unittest.TestCase):
    def test_a_hole_is_left_open(self):
        self.assertAlmostEqual(area(mesh.triangulate([SQUARE])), 100.0, 6)
        self.assertAlmostEqual(area(mesh.triangulate([SQUARE, HOLE])), 84.0, 6)
        self.assertAlmostEqual(area(mesh.triangulate([SQUARE, HOLE[::-1]])), 100.0, 6)    # (wound the same way: filled, as TrueType does)

    def test_a_solid_has_two_faces_and_sides_that_look_outwards(self):
        m = mesh.extrude([SQUARE - 5, HOLE - 5], 6.0, 0.0, 3, (1, 0, 0, 1), (0, 1, 0, 1))
        self.assertEqual((float(m[:, 2].min()), float(m[:, 2].max())), (-3.0, 3.0))
        faces = m[np.abs(m[:, 5]) > 0.5]
        self.assertAlmostEqual(area(faces[:, :2].reshape(-1, 3, 2)), 168.0, 4)            # (front and back)
        sides = m[np.abs(m[:, 5]) < 0.5]
        outer = sides[np.abs(sides[:, :2]).max(axis=1) > 4.9]
        self.assertTrue(np.all(np.sum(outer[:, :2] * outer[:, 3:5], axis=1) > 0))          # (the outside's normals point away)
        inner = sides[np.abs(sides[:, :2]).max(axis=1) < 2.1]
        self.assertTrue(np.all(np.sum(inner[:, :2] * inner[:, 3:5], axis=1) < 0))          # (the hole's point into it)
        self.assertEqual(sides[0][7], 1.0)                                                 # (the sides' colour)

    def test_a_bevel_makes_the_faces_smaller_and_keeps_the_size(self):
        m = mesh.extrude([SQUARE - 5], 8.0, 1.0, 3, (1, 1, 1, 1), (1, 1, 1, 1))
        front = m[(np.abs(m[:, 2] + 4.0) < 1e-4) & (m[:, 5] < -0.999)]
        self.assertAlmostEqual(float(np.abs(front[:, :2]).max()), 4.0, 4)
        self.assertAlmostEqual(float(np.abs(m[:, :2]).max()), 5.0, 4)
        self.assertTrue(np.allclose(np.linalg.norm(m[:, 3:6], axis=1), 1.0, atol=1e-4))

    def test_text_becomes_a_mesh_about_its_middle(self):
        spec = {"content": "回 Aa", "size": 10.0, "color": [1.0, 0.5, 0.0], "align": "center"}
        letters = mesh.text_letters(spec, 1080)
        self.assertEqual(len(letters), 3)                                                  # (the space has no solid)
        m = mesh.text_mesh(spec, 1080, 40.0, 2.0)
        self.assertGreater(len(m), 300)
        lo, hi = m[:, :3].min(0), m[:, :3].max(0)
        self.assertLess(abs(lo[0] + hi[0]), 20.0)                                          # (centred)
        self.assertAlmostEqual(float(hi[2] - lo[2]), 40.0, 3)
        self.assertIs(mesh.text_mesh(spec, 1080, 40.0, 2.0), m)                            # (kept)

    def test_the_basic_solids_are_their_size_and_their_normals_look_out(self):
        for kind in mesh.PRIMITIVES:
            m = mesh.primitive_mesh(kind, 200.0, 300.0, 100.0, 4.0, (1, 1, 1))
            self.assertTrue(np.allclose(m[:, :3].max(0) - m[:, :3].min(0), (200, 300, 100), atol=0.5), kind)
            self.assertTrue(np.allclose(np.linalg.norm(m[:, 3:6], axis=1), 1.0, atol=1e-4), kind)
            pos, n = m[:, :3], m[:, 3:6]
            if kind == "torus":                             # (away from the middle of the tube: its tube is 50 px thick here)
                tri = len(pos) // 3
                out = np.sum(n * (pos * (1, 1, 1)), axis=1)
                self.assertGreater(int((out > 0).sum()), tri)
                self.assertGreater(int((out < 0).sum()), tri // 2)       # (round the hole they look inwards)
            else:
                self.assertGreater(float(np.sum(pos * n, axis=1).min()), -1e-3, kind)

    def test_a_shape_is_pushed_out_and_a_ring_keeps_its_hole(self):
        base = {"family": "ellipse", "color": "#ff0000", "w": 200, "h": 200, "fill": True, "arc_start": 0, "arc_sweep": 100, "ratio": 50}
        m = mesh.shape_mesh(assets.at(assets.normalize(base), 0), 40.0, 0.0)
        faces = m[np.abs(m[:, 5]) > 0.5]
        self.assertAlmostEqual(area(faces[:, :2].reshape(-1, 3, 2)), 2 * np.pi * (100 ** 2 - 50 ** 2), delta=500)
        self.assertEqual(tuple(m[0][6:9]), (1.0, 0.0, 0.0))

    def test_an_open_path_is_pushed_out_as_a_ribbon_of_its_stroke(self):
        p, _centre = assets.path_params([{"nodes": [[0, 0, 0, 0, 0, 0], [300, 0, 0, 0, 0, 0], [300, 200, 0, 0, 0, 0]], "closed": False}], "#00ff00")
        q = assets.at(p, 0)
        contours, _odd, colour = mesh.shape_contours(q)
        self.assertEqual(colour, "stroke_color")
        covered = area(mesh.triangulate(contours, True))
        self.assertAlmostEqual(covered, 500 * q["stroke"], delta=0.1 * 500 * q["stroke"])      # (not the corner it spans filled)
        q["stroke_on"] = False
        self.assertEqual(len(mesh.shape_mesh(q, 40.0, 0.0)), 0)


if __name__ == "__main__":
    unittest.main()
