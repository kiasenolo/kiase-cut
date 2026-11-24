"""camera.py: the planes the camera sees."""
import unittest

from PySide6.QtCore import QPointF

from kiasecut import camera

W, H = 1920, 1080


class Planes(unittest.TestCase):
    def test_the_middle_plane_is_drawn_as_it_is(self):
        for fov in (20, 40, 90):
            q, d = camera.plane({"on": True, "fov": fov}, {}, 0, W, H)
            for pt in (QPointF(0, 0), QPointF(100, 200), QPointF(W, H)):
                m = q.map(pt)
                self.assertAlmostEqual(m.x(), pt.x(), 4)
                self.assertAlmostEqual(m.y(), pt.y(), 4)
            self.assertGreater(d, 0)

    def test_a_far_plane_is_smaller_a_near_one_bigger(self):
        far, _ = camera.plane({"on": True}, {"z": 1.0}, 0, W, H)
        near, _ = camera.plane({"on": True}, {"z": -0.5}, 0, W, H)
        self.assertLess(far.map(QPointF(W, 0)).x() - far.map(QPointF(0, 0)).x(), W)
        self.assertGreater(near.map(QPointF(W, 0)).x() - near.map(QPointF(0, 0)).x(), W)

    def test_a_turn_about_y_takes_the_right_edge_away(self):
        q, _ = camera.plane({"on": True}, {"rot_y": 40}, 0, W, H)
        left, right = q.map(QPointF(0, 0)), q.map(QPointF(W, 0))
        self.assertLess(right.y(), 0.0 + H / 2)
        self.assertGreater(q.map(QPointF(0, H)).y() - left.y(), q.map(QPointF(W, H)).y() - right.y())      # (the near edge is taller)

    def test_depth_orders_the_planes(self):
        cam = {"on": True}
        d = lambda z: camera.depth(cam, {"z": z}, 0, W, H)
        self.assertLess(d(-0.2), d(0.0))
        self.assertLess(d(0.0), d(0.7))

    def test_a_camera_behind_a_plane_cannot_see_it(self):
        _q, d = camera.plane({"on": True}, {"z": -5.0}, 0, W, H)
        self.assertLess(d, camera.NEAR)

    def test_the_flat_drawing_is_in_the_middle_and_not_turned(self):
        c = {"transform": {"x": 0.3, "y": 0.1, "rotation": 20, "scale": 0.5, "rot_y": 10}}
        tf = camera.flat(c)["transform"]
        self.assertEqual(tf, {"scale": 0.5, "rot_y": 10})
        self.assertEqual(c["transform"]["x"], 0.3)


class Editing(unittest.TestCase):
    def test_a_group_gets_a_camera_and_keeps_its_keyframes(self):
        from kiasecut import edit, project
        S = 1_000_000
        p = project.new()
        g = {"id": "g", "type": "group", "name": "g", "start_us": 0, "duration_us": 4 * S, "transform": {}, "tracks": []}
        p["tracks"] = [{"id": "t0", "kind": "video", "name": "v", "clips": [g]}]
        project.refresh_duration(p)
        p = project.link(p)
        edit.set_param(p, "g", "camera", "on", True)
        cam = edit.find(p, "g")[1]["camera"]
        self.assertTrue(camera.on(cam))
        self.assertAlmostEqual(cam["z"], -2.747, 3)                  # (it stands where the z = 0 plane fills the picture)
        edit.set_param(p, "g", "camera", "x", 0.5)
        edit.toggle_key(p, "g", "camera", "x", S)
        edit.set_param(p, "g", "camera", "x", 1.5, S)
        self.assertEqual(edit.key_at(edit.find(p, "g")[1]["camera"]["x"], S), 0)
        with self.assertRaises(edit.EditError):
            edit.holder({"type": "image"}, "camera")
        self.assertIn("rot_y", edit.GROUP_FIELDS["transform"])


if __name__ == "__main__":
    unittest.main()
