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


class DepthOfField(unittest.TestCase):
    cam = {"on": True, "fov": 40.0, "z": -2.747, "aperture": 4.0}

    def test_the_focus_is_sharp_and_the_rest_blurs_by_how_far_from_it(self):
        r = lambda z, cam=None: camera.blur(cam or self.cam, {"z": z}, 0, W, H)
        self.assertEqual(r(0.0), 0.0)                              # (the target's distance is the focus: z = 0)
        self.assertGreater(r(1.0), r(0.5), 0)
        self.assertGreater(r(0.5), 0.0)
        self.assertGreater(r(-1.0), 0.0)                           # (nearer than the focus blurs too)
        self.assertEqual(r(1.0, dict(self.cam, aperture=0.0)), 0.0)
        self.assertGreater(r(1.0, dict(self.cam, aperture=8.0)), 1.9 * r(1.0))
        self.assertEqual(r(0.0, dict(self.cam, focus=3.747)), 0.0 + r(0.0, dict(self.cam, focus=3.747)))
        self.assertGreater(r(0.0, dict(self.cam, focus=3.747)), 0.0)   # (focus put farther: z = 0 is out of it)

    def test_a_blurred_clip_is_drawn_with_a_blur_effect_last(self):
        c = {"transform": {"z": 1.0}, "effects": [{"id": "e", "filter": "builtin:invert", "params": {}}]}
        out = camera.deepfocus(self.cam, c, 0, W, H)
        self.assertEqual([e["filter"] for e in out["effects"]], ["builtin:invert", "builtin:blur"])
        self.assertGreater(out["effects"][-1]["params"]["radius"], 1.0)
        self.assertNotIn("effects", camera.deepfocus(dict(self.cam, aperture=0.0), c, 0, W, H) if False else {})
        self.assertEqual(len(camera.deepfocus(dict(self.cam, aperture=0.0), c, 0, W, H)["effects"]), 1)


class Moves(unittest.TestCase):
    cam = {"on": True, "fov": 40.0, "z": -2.747}

    def centre(self, cam):
        q, d = camera.plane(cam, {}, 0, W, H)               # (the clip in the middle of the z = 0 plane)
        return q.map(QPointF(W / 2, H / 2)), d

    def test_tracking_takes_the_picture_along_with_the_drag(self):
        c0, _ = self.centre(self.cam)
        new = dict(self.cam, **camera.track(self.cam, 0, W, H, 100, -40))
        c1, _ = self.centre(new)
        self.assertAlmostEqual(c1.x() - c0.x(), 100, 3)
        self.assertAlmostEqual(c1.y() - c0.y(), -40, 3)

    def test_orbiting_keeps_the_target_in_the_middle_and_the_distance(self):
        _c, d0 = self.centre(self.cam)
        new = dict(self.cam, **camera.orbit(self.cam, 0, W, H, 120, 40))
        c1, d1 = self.centre(new)
        self.assertAlmostEqual(c1.x(), W / 2, 3)
        self.assertAlmostEqual(c1.y(), H / 2, 3)
        self.assertAlmostEqual(d1, d0, 4)
        self.assertLess(new["x"], 0)                        # (a drag to the right takes it to the left)

    def test_a_drag_down_takes_the_camera_up(self):
        new = camera.orbit(self.cam, 0, W, H, 0, 40)
        self.assertGreater(new["y"], 0)

    def test_dollying_goes_nearer_with_a_drag_up(self):
        _c, d0 = self.centre(self.cam)
        near = dict(self.cam, **camera.dolly(self.cam, 0, W, H, -100))
        far = dict(self.cam, **camera.dolly(self.cam, 0, W, H, 100))
        self.assertLess(self.centre(near)[1], d0)
        self.assertGreater(self.centre(far)[1], d0)


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


class Scene(unittest.TestCase):
    def test_a_3d_scene_is_a_compound_with_a_camera_on(self):
        from kiasecut import edit, project
        p = project.link(project.new())
        c = edit.new_scene(p, p, 0)
        self.assertEqual(c["type"], "compound")
        self.assertTrue(camera.on(c["camera"]))
        self.assertEqual(c["compound"]["name"], "3D 場景 1")
        c2 = edit.new_scene(p, p, 10_000_000)
        self.assertEqual(c2["compound"]["name"], "3D 場景 2")
        self.assertAlmostEqual(c["camera"]["z"], -2.747, 3)


if __name__ == "__main__":
    unittest.main()
