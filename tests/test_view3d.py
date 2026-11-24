"""The preview's 3D view (ui/view3d.py): a free camera to look at a 3D 場景 from outside, Blender's way."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import camera  # noqa: E402
from kiasecut.ui.preview import Preview  # noqa: E402
from test_edit import S, clip  # noqa: E402

APP = QApplication.instance() or QApplication([])


def scene_view(on=True):
    c1 = clip("c1", 0, 4 * S, transform={"x": -0.4, "y": 0.0, "scale": 0.5, "rotation": 0.0, "opacity": 1.0, "z": 0.3})
    c2 = clip("c2", 0, 4 * S, transform={"x": 0.4, "y": 0.0, "scale": 0.5, "rotation": 0.0, "opacity": 1.0, "rot_y": 40})
    v = {"width": 1920, "height": 1080, "fps": 30, "duration_us": 4 * S,
         "tracks": [{"id": "t0", "kind": "video", "name": "v", "clips": [c1]}, {"id": "t1", "kind": "video", "name": "v2", "clips": [c2]}]}
    if on:
        v["camera"] = {"on": True, "fov": 40.0, "z": -2.747}
    return v


class View3DTests(unittest.TestCase):
    def preview(self, **kw):
        pv = Preview()
        pv.resize(960, 540)
        pv.set_scene(scene_view(**kw), S, "c1")
        return pv

    def test_it_is_only_for_a_level_with_a_camera_on(self):
        self.assertFalse(self.preview(on=False).set_view3d(True))
        pv = self.preview()
        self.assertTrue(pv.set_view3d(True))
        self.assertIsNotNone(pv.render_camera())
        pv.set_scene(scene_view(on=False), S, "c1")                        # (the level lost its camera: flat again)
        self.assertFalse(pv.view3d_on)
        self.assertIsNone(pv.render_camera())

    def test_it_starts_round_the_side_and_farther_away(self):
        pv = self.preview()
        pv.set_view3d(True)
        cam = pv.render_camera()
        self.assertGreater(abs(cam["x"]), 0.3)
        self.assertLess(cam["z"] ** 2 + cam["x"] ** 2, 0.0 + 99)
        self.assertEqual((cam["tx"], cam["ty"], cam["tz"]), (0.0, 0.0, 0.0))

    def test_moving_about_changes_only_the_views_own_camera(self):
        pv = self.preview()
        pv.set_view3d(True)
        changed = []
        pv.view3dChanged.connect(lambda: changed.append(1))
        v = pv.view3d
        before = dict(pv.render_camera())
        v.orbit(30, 10)
        v.pan(40, -20)
        v.zoom(0.3)
        after = pv.render_camera()
        self.assertEqual(len(changed), 3)
        self.assertNotEqual(before, after)
        self.assertEqual(pv.view["camera"], {"on": True, "fov": 40.0, "z": -2.747})      # (the scene's camera is not touched)

    def test_the_number_pad_looks_from_the_sides_and_0_through_the_camera(self):
        pv = self.preview()
        pv.set_view3d(True)
        key = lambda k, mods=Qt.KeypadModifier: QKeyEvent(QEvent.KeyPress, k, mods)
        pv.view3d.key_action(key(Qt.Key_7))()
        top = pv.render_camera()
        self.assertGreater(top["y"], 2.0)
        self.assertAlmostEqual(top["x"], 0.0, 3)
        pv.view3d.key_action(key(Qt.Key_7, Qt.KeypadModifier | Qt.ControlModifier))()
        self.assertLess(pv.render_camera()["y"], -2.0)
        pv.view3d.key_action(key(Qt.Key_3))()
        self.assertGreater(pv.render_camera()["x"], 1.0)
        pv.view3d.key_action(key(Qt.Key_1))()
        front = pv.render_camera()
        self.assertAlmostEqual(front["x"], 0.0, 3)
        self.assertLess(front["z"], 0.0)
        pv.view3d.key_action(key(Qt.Key_0))()
        self.assertIsNone(pv.render_camera())                              # (looking through the scene's camera)
        pv.view3d.orbit(10, 0)                                             # (turning leaves it, from where the camera is)
        cam = pv.render_camera()
        self.assertIsNotNone(cam)
        self.assertAlmostEqual(cam["z"], -2.747, delta=0.2)

    def test_the_middle_button_turns_the_view_and_shift_slides_it(self):
        pv = self.preview()
        pv.set_view3d(True)
        a = dict(pv.render_camera())
        QTest.mousePress(pv, Qt.MiddleButton, Qt.NoModifier, QPoint(400, 250))
        QTest.mouseMove(pv, QPoint(440, 262))
        QTest.mouseRelease(pv, Qt.MiddleButton, Qt.NoModifier, QPoint(440, 262))
        b = dict(pv.render_camera())
        self.assertNotEqual(a["x"], b["x"])
        self.assertEqual((a["tx"], a["ty"]), (b["tx"], b["ty"]))          # (round the same point)
        QTest.mousePress(pv, Qt.MiddleButton, Qt.ShiftModifier, QPoint(400, 250))
        QTest.mouseMove(pv, QPoint(440, 262))
        QTest.mouseRelease(pv, Qt.MiddleButton, Qt.ShiftModifier, QPoint(440, 262))
        c = pv.render_camera()
        self.assertNotEqual(b["tx"], c["tx"])                             # (its point moved)

    def test_it_paints_the_grid_the_camera_and_the_planes(self):
        pv = self.preview()
        pv.set_view3d(True)
        pv.show()
        flat = self.preview()
        flat.show()
        a, b = pv.grab().toImage(), flat.grab().toImage()
        self.assertNotEqual(a, b)
        pv.view3d.camera_view()
        pv.grab()
        self.assertEqual(len(pv.view3d.plane_corners()), 2)


if __name__ == "__main__":
    unittest.main()
