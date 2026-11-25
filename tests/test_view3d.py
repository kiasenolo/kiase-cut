"""The preview's 3D view (ui/view3d.py): a free camera to look at a 3D 場景 from outside, Blender's way."""
import os
import sys
import unittest
import numpy as np

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


class Editing3D(unittest.TestCase):
    """Picking, the arrows and G / R / S of the planes in the 3D view."""

    def setUp(self):
        self.pv = Preview()
        self.pv.resize(960, 540)
        self.pv.set_scene(scene_view(), S, "c1")
        self.pv.set_view3d(True)
        self.picked, self.live, self.done, self.cancelled = [], [], [], []
        self.pv.clipPicked.connect(self.picked.append)
        self.pv.selectionPicked.connect(lambda ids, primary: self.picked.append(("sel", ids)))
        self.pv.paramsLive.connect(lambda *a: self.live.append(a))
        self.pv.paramsCommitted.connect(lambda *a: self.done.append(a))
        self.pv.grabCancelled.connect(lambda: self.cancelled.append(1))

    def at(self, world):
        """Screen point (QPoint) of a world point."""
        x, y = self.pv.view3d.seen().point(world)
        r = self.pv._rect()
        return QPoint(round(r.x() + x / self.pv.W * r.width()), round(r.y() + y / self.pv.H * r.height()))

    def middle_of(self, cid):
        pts = self.pv.view3d.plane_corners()[cid]
        return self.at(sum(pts) / 4.0)

    def test_a_click_selects_the_plane_it_lands_on(self):
        QTest.mouseClick(self.pv, Qt.LeftButton, Qt.NoModifier, self.middle_of("c2"))
        self.assertEqual(self.picked[-1]["id"], "c2")
        QTest.mouseClick(self.pv, Qt.LeftButton, Qt.NoModifier, QPoint(5, 5))
        self.assertEqual(self.picked[-1], ("sel", set()))

    def test_an_arrow_moves_the_plane_along_its_axis_only(self):
        pv, v = self.pv, self.pv.view3d
        b = v.selected()
        o = v.origin(v.values(b))
        seen = v.seen()
        tip = seen.point(v.arrows(seen, o, pv._k())["x"][0])
        r = pv._rect()
        start = QPoint(round(r.x() + tip[0] / pv.W * r.width()), round(r.y() + tip[1] / pv.H * r.height()))
        self.assertEqual(v.hit_arrow(QPointF(start))[0], "x")
        QTest.mousePress(pv, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(pv, start + QPoint(40, 0))
        QTest.mouseMove(pv, start + QPoint(80, 0))
        QTest.mouseRelease(pv, Qt.LeftButton, Qt.NoModifier, start + QPoint(80, 0))
        (cid, group, vals), = self.done
        self.assertEqual((cid, group, set(vals)), ("c1", "transform", {"x"}))
        self.assertNotEqual(vals["x"], -0.4)
        self.assertTrue(self.live)
        self.assertEqual(v.live, {})                                      # (nothing is left dragging)

    def test_dragging_the_plane_moves_it_in_the_pictures_plane(self):
        pv, v = self.pv, self.pv.view3d
        mid = self.at(v.origin(v.values(v.selected())))
        start = mid + QPoint(25, 20)                                      # (on the plane, off the handles)
        self.assertIsNone(v.hit_arrow(QPointF(start)))
        self.assertTrue(v.on_body(QPointF(start)))
        QTest.mousePress(pv, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(pv, start + QPoint(60, -30))
        QTest.mouseRelease(pv, Qt.LeftButton, Qt.NoModifier, start + QPoint(60, -30))
        (_cid, _g, vals), = self.done
        self.assertEqual(set(vals), {"x", "y", "z"})
        self.assertGreater(vals["y"], 0.0)                                # (it went up)

    def test_the_middle_box_scales_all_round(self):
        pv, v = self.pv, self.pv.view3d
        start = self.at(v.origin(v.values(v.selected())))
        self.assertEqual(v.hit_arrow(QPointF(start))[0], "su")
        QTest.mousePress(pv, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(pv, start + QPoint(40, 0))
        QTest.mouseMove(pv, start + QPoint(80, 0))
        QTest.mouseRelease(pv, Qt.LeftButton, Qt.NoModifier, start + QPoint(80, 0))
        (_cid, _g, vals), = self.done
        self.assertEqual(set(vals), {"scale", "scale_y"})
        self.assertGreater(vals["scale"], v.values(v.selected())["scale"])

    def test_the_x_box_scales_only_x(self):
        pv, v = self.pv, self.pv.view3d
        seen, k = v.seen(), pv._k()
        o = v.origin(v.values(v.selected()))
        n = v.arrow_length(seen, o, k)
        start = self.at(o + np.array(v.AXES["x"]) * n * v.BOX_AT)
        self.assertEqual(v.hit_arrow(QPointF(start))[0], "sx")
        v0 = v.values(v.selected())
        QTest.mousePress(pv, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(pv, start + QPoint(30, 0))
        QTest.mouseMove(pv, start + QPoint(60, 0))
        QTest.mouseRelease(pv, Qt.LeftButton, Qt.NoModifier, start + QPoint(60, 0))
        (_cid, _g, vals), = self.done
        self.assertGreater(vals["scale"], v0["scale"])
        self.assertEqual(vals["scale_y"], v0["scale_y"])

    def test_a_ring_turns_the_plane_the_way_the_pointer_goes_round(self):
        import math
        pv, v = self.pv, self.pv.view3d
        b = v.selected()
        o = v.origin(v.values(b))
        seen, k = v.seen(), pv._k()
        n = v.arrow_length(seen, o, k) * v.RING_AT
        pts = v.ring_points(o, "z", n)
        i0 = 6
        start = self.at(pts[i0])
        self.assertEqual(v.hit_arrow(QPointF(start))[0], "rz")
        corners = lambda: v.plane_corners()["c1"]
        edge = lambda: corners()[1] - corners()[0]
        a0 = math.atan2(edge()[1], edge()[0])
        QTest.mousePress(pv, Qt.LeftButton, Qt.NoModifier, start)
        for j in range(i0 + 1, i0 + 5):                       # (round the ring by 4 steps of 7.5 degrees: 30)
            QTest.mouseMove(pv, self.at(pts[j]))
        a1 = math.atan2(edge()[1], edge()[0])
        QTest.mouseRelease(pv, Qt.LeftButton, Qt.NoModifier, self.at(pts[i0 + 4]))
        (_cid, group, vals), = self.done
        self.assertEqual((group, set(vals)), ("transform", {"rotation"}))
        step = math.degrees((a1 - a0 + math.pi) % (2 * math.pi) - math.pi)
        self.assertAlmostEqual(step, 30.0, delta=6.0)           # (the plane went round with the pointer)

    def test_a_typed_number_gives_the_move_exactly(self):
        pv, v = self.pv, self.pv.view3d
        key = lambda k: QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier)
        v.key_action(key(Qt.Key_G))()
        x0 = v.values(v.selected())["x"]
        for k in (Qt.Key_X, Qt.Key_1, Qt.Key_Period, Qt.Key_5):
            v.modal_key(key(k), True)
        self.assertEqual(v.modal["typed"], "1.5")
        self.assertAlmostEqual(self.live[-1][2]["x"], x0 + 1.5, 4)
        v.modal_key(key(Qt.Key_Backspace), True)
        self.assertAlmostEqual(self.live[-1][2]["x"], x0 + 1.0, 4)
        v.modal_key(key(Qt.Key_Minus), True)
        self.assertAlmostEqual(self.live[-1][2]["x"], x0 - 1.0, 4)
        v.modal_key(key(Qt.Key_Return), True)
        self.assertAlmostEqual(self.done[-1][2]["x"], x0 - 1.0, 4)

    def test_typing_a_turn_or_a_scale(self):
        pv, v = self.pv, self.pv.view3d
        key = lambda k: QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier)
        v.key_action(key(Qt.Key_R))()
        v.modal_key(key(Qt.Key_Y), True)
        for k in (Qt.Key_4, Qt.Key_5):
            v.modal_key(key(k), True)
        self.assertEqual(self.live[-1][2], {"rot_y": 45.0})
        v.modal_key(key(Qt.Key_Escape), True)
        v.key_action(key(Qt.Key_S))()
        v.modal_key(key(Qt.Key_2), True)
        self.assertEqual(set(self.live[-1][2]), {"scale", "scale_y"})
        self.assertAlmostEqual(self.live[-1][2]["scale"], 1.0, 4)             # (c1's scale is 0.5)

    def test_g_then_z_moves_along_z_and_escape_puts_it_back(self):
        pv, v = self.pv, self.pv.view3d
        key = lambda k, mods=Qt.NoModifier: QKeyEvent(QEvent.KeyPress, k, mods)
        c = v.selected()
        v.key_action(key(Qt.Key_G))()
        self.assertIsNotNone(v.modal)
        o = v.origin(v.values(c))
        v.modal["m0"] = QPointF(self.at(o))                               # (the pointer is on the plane when the move begins)
        v.modal_key(key(Qt.Key_Z), True)
        far = self.at(o + [0, 0, 400])
        v.modal_move(QPointF(far))
        self.assertEqual(set(self.live[-1][2]), {"z"})
        self.assertGreater(self.live[-1][2]["z"], 0.3)
        v.modal_key(key(Qt.Key_Escape), True)
        self.assertIsNone(v.modal)
        self.assertEqual((self.done, v.live, len(self.cancelled)), ([], {}, 1))

    def test_r_turns_about_y_and_a_click_keeps_it(self):
        pv, v = self.pv, self.pv.view3d
        key = lambda k, mods=Qt.NoModifier: QKeyEvent(QEvent.KeyPress, k, mods)
        v.key_action(key(Qt.Key_R))()
        v.modal_key(key(Qt.Key_Y), True)
        m0 = v.modal["m0"]
        v.modal_move(m0 + QPointF(60, 0))
        self.assertEqual(self.live[-1][2], {"rot_y": 30.0})
        QTest.mouseClick(pv, Qt.LeftButton, Qt.NoModifier, QPoint(10, 10))
        self.assertEqual(self.done[-1], ("c1", "transform", {"rot_y": 30.0}))

    def test_s_scales_both_ways(self):
        v = self.pv.view3d
        v.key_action(QKeyEvent(QEvent.KeyPress, Qt.Key_S, Qt.NoModifier))()
        v.modal_move(v.modal["m0"] + QPointF(100, 0))
        vals = self.live[-1][2]
        self.assertAlmostEqual(vals["scale"], 0.5 * 1.5, 3)
        self.assertAlmostEqual(vals["scale_y"], 0.5 * 1.5, 3)
        v.modal_end(False)

    def test_the_outline_follows_a_drag_before_the_edit_is_made(self):
        v = self.pv.view3d
        before = v.plane_corners()["c1"][0].copy()
        v.live["c1"] = {"x": 0.0}
        self.assertNotEqual(float(before[0]), float(v.plane_corners()["c1"][0][0]))


class CameraThing(Editing3D):
    """The scene's camera and its target can be selected and moved in the view."""

    def test_the_camera_and_its_target_are_picked_by_clicking_them(self):
        v = self.pv.view3d
        real = v.scene_camera()
        c, corners, tg = camera.frustum(real, S, 1920, 1080)
        QTest.mouseClick(self.pv, Qt.LeftButton, Qt.NoModifier, self.at(tg))
        self.assertEqual(v.sel_cam, "target")
        self.assertEqual(self.picked[-1], ("sel", set()))                 # (no plane is selected then)
        QTest.mouseClick(self.pv, Qt.LeftButton, Qt.NoModifier, self.at((corners[0] + corners[1]) / 2.0))
        self.assertEqual(v.sel_cam, "camera")
        QTest.mouseClick(self.pv, Qt.LeftButton, Qt.NoModifier, self.middle_of("c2"))
        self.assertIsNone(v.sel_cam)

    def test_an_arrow_moves_the_camera_and_the_edit_is_its_fields(self):
        pv, v = self.pv, self.pv.view3d
        edited = []
        pv.sceneCameraEdited.connect(edited.append)
        v.sel_cam = "camera"
        b = v.selected()
        o = v.origin(v.values(b))
        seen = v.seen()
        tip = seen.point(v.arrows(seen, o, pv._k())["x"][0])
        r = pv._rect()
        start = QPoint(round(r.x() + tip[0] / pv.W * r.width()), round(r.y() + tip[1] / pv.H * r.height()))
        QTest.mousePress(pv, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(pv, start + QPoint(50, 0))
        self.assertNotEqual(v.scene_camera()["x"], 0.0)                   # (the pyramid follows)
        QTest.mouseRelease(pv, Qt.LeftButton, Qt.NoModifier, start + QPoint(50, 0))
        (vals,) = edited
        self.assertEqual(set(vals), {"x"})
        self.assertEqual(self.done, [])                                   # (not an edit of a plane)
        self.assertEqual(pv.view["camera"], {"on": True, "fov": 40.0, "z": -2.747})

    def test_the_target_edit_is_in_the_targets_fields(self):
        pv, v = self.pv, self.pv.view3d
        edited = []
        pv.sceneCameraEdited.connect(edited.append)
        v.sel_cam = "target"
        v.key_action(QKeyEvent(QEvent.KeyPress, Qt.Key_G, Qt.NoModifier))()
        v.modal["m0"] = QPointF(self.at(v.origin(v.values(v.selected()))))
        v.modal_key(QKeyEvent(QEvent.KeyPress, Qt.Key_Y, Qt.NoModifier), True)
        v.modal_move(v.modal["m0"] + QPointF(0, -40))
        v.modal_end(True)
        (vals,) = edited
        self.assertEqual(set(vals), {"ty"})
        self.assertGreater(vals["ty"], 0.0)
        self.assertIsNone(v.key_action(QKeyEvent(QEvent.KeyPress, Qt.Key_R, Qt.NoModifier)))      # (the camera is only moved)


if __name__ == "__main__":
    unittest.main()


class ParticleEditing(unittest.TestCase):
    """The emitter of a particle system in the 3D view: its outline and handles."""

    def setUp(self):
        from kiasecut import assets
        self.pv = Preview()
        self.pv.resize(960, 540)
        a = assets.make(assets.get("particle.magic"), "#ffffff", "#000000", 1920, 1080)
        a.update(pt_emitter="矩形", pt_origin_y=-0.05, pt_ewidth=600.0, pt_eheight=300.0, pt_depth_on=True, pt_ethick=400.0)
        c = clip("c1", 0, 4 * S, transform={"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0, "z": 0.0})
        c["type"], c["asset"] = "image", assets.normalize(a)
        v = {"width": 1920, "height": 1080, "fps": 30, "duration_us": 4 * S, "camera": {"on": True, "fov": 40.0, "z": -2.747},
             "tracks": [{"id": "t0", "kind": "video", "name": "v", "clips": [c]}]}
        self.pv.set_scene(v, S, "c1")
        self.pv.set_view3d(True)
        self.live, self.done = [], []
        self.pv.paramsLive.connect(lambda *a: self.live.append(a))
        self.pv.paramsCommitted.connect(lambda *a: self.done.append(a))

    def at(self, world):
        x, y = self.pv.view3d.seen().point(world)
        r = self.pv._rect()
        return QPoint(round(r.x() + x / self.pv.W * r.width()), round(r.y() + y / self.pv.H * r.height()))

    def test_a_box_emitter_has_an_outline_with_depth_and_handles(self):
        v = self.pv.view3d
        b, e = v.particle()
        loops, links = v.emitter_loops(e, b.t)
        self.assertEqual((len(loops), len(links)), (2, 4))                 # (two faces, four edges between them)
        ids = [h["id"] for h, _w in v.phandles()]
        for want in ("ewidth", "eheight", "ethick"):
            self.assertIn(want, ids)
        self.assertNotIn("origin", ids)

    def test_dragging_the_width_handle_edits_the_systems_width(self):
        pv, v = self.pv, self.pv.view3d
        w = dict((h["id"], wp) for h, wp in v.phandles())["ewidth"]
        start = self.at(w)
        self.assertTrue(v.start_phandle(QPointF(start)))
        v.pdrag = None
        QTest.mousePress(pv, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(pv, start + QPoint(40, 0))
        QTest.mouseMove(pv, start + QPoint(80, 0))
        QTest.mouseRelease(pv, Qt.LeftButton, Qt.NoModifier, start + QPoint(80, 0))
        (_cid, group, vals), = self.done
        self.assertEqual(group, "asset")
        self.assertEqual(set(vals), {"pt_ewidth"})
        self.assertGreater(vals["pt_ewidth"], 600.0)
        self.assertEqual(v.plive, {})

    def test_the_thickness_handle_is_dragged_along_the_planes_normal(self):
        pv, v = self.pv, self.pv.view3d
        z = dict((h["id"], wp) for h, wp in v.phandles())["ethick"]
        start = self.at(z)
        QTest.mousePress(pv, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(pv, start + QPoint(30, 0))
        QTest.mouseMove(pv, start + QPoint(70, 0))
        QTest.mouseRelease(pv, Qt.LeftButton, Qt.NoModifier, start + QPoint(70, 0))
        (_cid, group, vals), = self.done
        self.assertEqual(set(vals), {"pt_ethick"})
        self.assertNotEqual(vals["pt_ethick"], 400.0)


class CameraObject(unittest.TestCase):
    """A 相機 object of the scene is the camera that is drawn, picked as a clip and moved with the clip's arrows."""

    def setUp(self):
        self.pv = Preview()
        self.pv.resize(960, 540)
        v = scene_view()
        obj = clip("cam", 0, 4 * S, transform={"x": 0.3, "y": 0.1, "scale": 1.0, "rotation": 0.0, "opacity": 1.0, "z": -2.5})
        obj["type"] = "image"
        obj["asset"] = {"family": "empty", "w": 100, "h": 100}
        obj["camera"] = {"fov": 40.0, "tx": 0.0, "ty": 0.0, "tz": 0.0, "aperture": 0.0}
        v["tracks"].append({"id": "t2", "kind": "video", "name": "c", "clips": [obj]})
        self.pv.set_scene(v, S, "cam")
        self.pv.set_view3d(True)
        self.picked, self.done, self.edited = [], [], []
        self.pv.clipPicked.connect(self.picked.append)
        self.pv.paramsCommitted.connect(lambda *a: self.done.append(a))
        self.pv.sceneCameraEdited.connect(self.edited.append)

    def at(self, world):
        x, y = self.pv.view3d.seen().point(world)
        r = self.pv._rect()
        return QPoint(round(r.x() + x / self.pv.W * r.width()), round(r.y() + y / self.pv.H * r.height()))

    def test_the_scene_camera_is_the_object_and_it_has_no_plane_of_its_own(self):
        v = self.pv.view3d
        cam = v.scene_camera()
        self.assertEqual((cam["x"], cam["y"], cam["z"]), (0.3, 0.1, -2.5))
        self.assertNotIn("cam", v.plane_corners())
        self.assertIs(v.active_object()["id"] == "cam", True)

    def test_clicking_its_pyramid_picks_the_clip_and_its_arrows_move_the_clip(self):
        pv, v = self.pv, self.pv.view3d
        c, corners, _tg = camera.frustum(v.scene_camera(), S, 1920, 1080)
        QTest.mouseClick(pv, Qt.LeftButton, Qt.NoModifier, self.at((corners[0] + corners[1]) / 2.0))
        self.assertEqual(self.picked[-1]["id"], "cam")
        pv.set_scene(pv.view, S, "cam")                                   # (as the window selects it)
        b = v.selected()
        self.assertEqual(b.clip["id"], "cam")
        seen, k = v.seen(), pv._k()
        o = v.origin(v.values(b))
        self.assertEqual(v.hit_arrow(QPointF(self.at(o)))[0], "plane")      # (no scale box or rings on a camera)
        self.assertIsNone(v.key_action(QKeyEvent(QEvent.KeyPress, Qt.Key_S, Qt.NoModifier)))

    def test_dragging_its_arrow_in_the_3d_view_edits_the_clips_place(self):
        pv, v = self.pv, self.pv.view3d
        done = []
        pv.paramsCommitted.connect(lambda *a: done.append(a))
        b = v.selected()
        o = v.origin(v.values(b))
        seen = v.seen()
        start = self.at(v.arrows(seen, o, pv._k())["x"][0])
        self.assertEqual(v.hit_arrow(QPointF(start))[0], "x")
        QTest.mousePress(pv, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(pv, start + QPoint(30, 0))
        QTest.mouseMove(pv, start + QPoint(60, 0))
        QTest.mouseRelease(pv, Qt.LeftButton, Qt.NoModifier, start + QPoint(60, 0))
        (cid, group, vals), = done
        self.assertEqual((cid, group, set(vals)), ("cam", "transform", {"x"}))

    def test_the_target_is_edited_in_the_camera_objects_fields(self):
        pv, v = self.pv, self.pv.view3d
        _c, _corners, tg = camera.frustum(v.scene_camera(), S, 1920, 1080)
        QTest.mouseClick(pv, Qt.LeftButton, Qt.NoModifier, self.at(tg))
        self.assertEqual(v.sel_cam, "target")
        v.key_action(QKeyEvent(QEvent.KeyPress, Qt.Key_G, Qt.NoModifier))()
        v.modal_key(QKeyEvent(QEvent.KeyPress, Qt.Key_X, Qt.NoModifier), True)
        for k in (Qt.Key_1,):
            v.modal_key(QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier), True)
        v.modal_key(QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier), True)
        (vals,) = self.edited
        self.assertEqual(set(vals), {"tx"})

    def test_a_camera_object_alone_makes_the_level_a_scene(self):
        pv = Preview()
        pv.resize(960, 540)
        v = scene_view(on=False)
        obj = clip("cam", 0, 4 * S, transform={"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0, "z": -2.7})
        obj["type"], obj["asset"] = "image", {"family": "empty", "w": 100, "h": 100}
        obj["camera"] = {"fov": 40.0}
        v["tracks"].append({"id": "t2", "kind": "video", "name": "c", "clips": [obj]})
        pv.set_scene(v, S, None)
        self.assertTrue(pv.set_view3d(True))
        self.assertEqual(pv.view3d.active_object()["id"], "cam")


class CameraObjectHandles(unittest.TestCase):
    """A selected 相機 object has the camera's handles (平移 環繞 推拉 視角) over the picture in the flat view."""

    def setUp(self):
        self.pv = Preview()
        self.pv.resize(960, 540)
        v = scene_view()
        obj = clip("cam", 0, 4 * S, transform={"x": 0.3, "y": 0.1, "scale": 1.0, "rotation": 0.0, "opacity": 1.0, "z": -2.5})
        obj["type"], obj["asset"] = "image", {"family": "empty", "w": 100, "h": 100}
        obj["camera"] = {"fov": 40.0, "tx": 0.0, "ty": 0.0, "tz": 0.0}
        v["tracks"].append({"id": "t2", "kind": "video", "name": "c", "clips": [obj]})
        self.pv.set_scene(v, S, "cam")
        self.done, self.live = [], []
        self.pv.paramsCommitted.connect(lambda *a: self.done.append(a))
        self.pv.paramsLive.connect(lambda *a: self.live.append(a))

    def test_the_handles_are_there_and_a_drag_edits_the_object(self):
        from kiasecut import gizmos
        pv = self.pv
        box = pv.selected_box()
        self.assertIsNotNone(box)
        e = pv.gizmo_effect(box)
        self.assertIsNotNone(e)
        hs = gizmos.handles(e, box.t, pv.W, pv.H)
        self.assertEqual({h["id"] for h in hs}, {"pan", "orbit", "dolly", "fov"})
        h = next(h for h in hs if h["id"] == "orbit")
        r = pv._rect()
        at = lambda local: QPoint(round(r.x() + (pv.W / 2 + local[0]) / pv.W * r.width()), round(r.y() + (pv.H / 2 + local[1]) / pv.H * r.height()))
        start = at(h["local"])
        QTest.mousePress(pv, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(pv, start + QPoint(30, 0))
        QTest.mouseMove(pv, start + QPoint(60, 0))
        QTest.mouseRelease(pv, Qt.LeftButton, Qt.NoModifier, start + QPoint(60, 0))
        (cid, group, vals), = self.done
        self.assertEqual((cid, group), ("cam", "multi"))
        self.assertTrue(set(vals["transform"]) <= {"x", "y", "z"} and vals["transform"])
        self.assertNotIn("x", vals.get("camera", {}))

    def test_a_camera_object_without_a_target_turns_by_its_angles_and_its_handles_edit_them(self):
        pv = self.pv
        clipd = pv.view["tracks"][-1]["clips"][0]
        clipd["camera"] = {"fov": 40.0}
        pv.set_scene(pv.view, S, "cam")
        box = pv.selected_box()
        e = pv.gizmo_effect(box)
        self.assertIn("rot_y", e["camera"])
        h = next(h for h in __import__("kiasecut.gizmos", fromlist=["x"]).handles(e, box.t, pv.W, pv.H) if h["id"] == "orbit")
        r = pv._rect()
        at = lambda local: QPoint(round(r.x() + (pv.W / 2 + local[0]) / pv.W * r.width()), round(r.y() + (pv.H / 2 + local[1]) / pv.H * r.height()))
        start = at(h["local"])
        QTest.mousePress(pv, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(pv, start + QPoint(30, 0))
        QTest.mouseMove(pv, start + QPoint(60, 0))
        QTest.mouseRelease(pv, Qt.LeftButton, Qt.NoModifier, start + QPoint(60, 0))
        (cid, group, vals), = self.done
        self.assertEqual(group, "multi")
        self.assertIn("rot_y", vals["transform"])
        v3 = pv.view3d
        self.assertFalse(v3.has_target())


class LightObjects(unittest.TestCase):
    """燈光 objects in the 3D view: icons that are picked like clips and moved with their arrows."""

    def setUp(self):
        self.pv = Preview()
        self.pv.resize(960, 540)
        v = scene_view()
        lamp = clip("lamp", 0, 4 * S, transform={"x": -1.5, "y": 1.1, "scale": 1.0, "rotation": 0.0, "opacity": 1.0, "z": -0.5})
        lamp["type"], lamp["asset"] = "image", {"family": "empty", "w": 100, "h": 100}
        lamp["light"] = {"kind": "point", "power": 100.0, "color": [1, 1, 1]}
        v["tracks"].append({"id": "t2", "kind": "video", "name": "l", "clips": [lamp]})
        self.view_dict = v
        self.pv.set_scene(v, S, "c1")
        self.pv.set_view3d(True)
        self.picked, self.done = [], []
        self.pv.clipPicked.connect(self.picked.append)
        self.pv.paramsCommitted.connect(lambda *a: self.done.append(a))

    def at(self, world):
        x, y = self.pv.view3d.seen().point(world)
        r = self.pv._rect()
        return QPoint(round(r.x() + x / self.pv.W * r.width()), round(r.y() + y / self.pv.H * r.height()))

    def test_it_is_an_icon_not_a_plane_picked_by_a_click_and_moved_by_its_arrows(self):
        pv, v = self.pv, self.pv.view3d
        (c, place, _way), = v.light_objects()
        self.assertEqual(c["id"], "lamp")
        self.assertNotIn("lamp", v.plane_corners())
        QTest.mouseClick(pv, Qt.LeftButton, Qt.NoModifier, self.at(place))
        self.assertEqual(self.picked[-1]["id"], "lamp")
        pv.set_scene(self.view_dict, S, "lamp")
        b = v.selected()
        o = v.origin(v.values(b))
        self.assertEqual(v.hit_arrow(QPointF(self.at(o)))[0], "plane")
        self.assertIsNone(v.key_action(QKeyEvent(QEvent.KeyPress, Qt.Key_S, Qt.NoModifier)))
        start = self.at(v.arrows(v.seen(), o, pv._k())["x"][0])
        QTest.mousePress(pv, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(pv, start + QPoint(30, 0))
        QTest.mouseMove(pv, start + QPoint(60, 0))
        QTest.mouseRelease(pv, Qt.LeftButton, Qt.NoModifier, start + QPoint(60, 0))
        (cid, group, vals), = self.done
        self.assertEqual((cid, group, set(vals)), ("lamp", "transform", {"x"}))
        pv.grab()
