"""Handles on the preview for an effect's centre, radius, angle and offset (gizmos.py, 編輯控制點)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, fx, gizmos  # noqa: E402
from kiasecut.ui.effects_panel import EffectsPanel  # noqa: E402
from kiasecut.ui.preview import Preview  # noqa: E402
from test_edit import S, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
NONE = Qt.KeyboardModifier.NoModifier
BW, BH = 1920.0, 1080.0


class ParticleHandleTests(unittest.TestCase):
    """A particle object's own handles: place, emitter size, the velocity and spread, the gravity arrow, the floor."""

    def object(self, **fields):
        from kiasecut import assets
        a = assets.make(assets.get("particle.system"), "#ffffff", "#000000", 1920, 1080)
        a.update({"pt_" + k: v for k, v in fields.items()})
        return {"id": "c1", "type": "image", "asset": assets.normalize(a)}

    def test_only_a_particle_object_has_them(self):
        self.assertIsNone(gizmos.particle_effect({"id": "c", "type": "image", "asset": {"family": "rect"}}))
        self.assertIsNone(gizmos.particle_effect({"id": "c", "type": "image"}))
        e = gizmos.particle_effect(self.object())
        self.assertEqual(e["filter"], "builtin:particle_system")

    def test_handles_follow_the_settings_and_a_drag_gives_the_fields_values(self):
        e = gizmos.particle_effect(self.object(origin_x=0.25, origin_y=0.75, emitter="矩形", ewidth=600.0, eheight=200.0, erot=0.0, angle=90.0,
                                               spread=60.0, speed=400.0, floor_on=True, floor_y=0.9))
        hs = {h["id"]: h for h in gizmos.handles(e, 0, BW, BH)}
        self.assertEqual(set(hs), {"origin", "ewidth", "eheight", "erot", "spread_a", "spread_b", "aim", "accel", "floor"})
        ox, oy = (0.25 - 0.5) * BW, (0.75 - 0.5) * BH
        self.assertEqual(hs["origin"]["local"], (ox, oy))
        self.assertAlmostEqual(hs["ewidth"]["local"][0], ox + 300.0)                 # (half the width, along the emitter)
        self.assertAlmostEqual(hs["eheight"]["local"][1], oy + 100.0)
        self.assertAlmostEqual(hs["aim"]["local"][0] - ox, 100.0)                    # (90 degrees: to the right, speed * 0.25 s long)
        self.assertAlmostEqual(hs["aim"]["local"][1], oy, places=6)
        self.assertEqual(gizmos.dragged(hs["origin"], (0.0, 0.0), BW, BH, {}), {"origin_x": 0.5, "origin_y": 0.5})
        self.assertEqual(gizmos.dragged(hs["ewidth"], (ox + 450.0, oy), BW, BH, {}), {"ewidth": 900.0})
        got = gizmos.dragged(hs["aim"], (ox, oy - 300.0), BW, BH, {}, snap=False)   # (up, 300 px: 1200 px/s)
        self.assertEqual((got["angle"], got["speed"]), (0.0, 1200.0))
        self.assertEqual(gizmos.dragged(hs["spread_a"], (ox + 100.0, oy - 100.0), BW, BH, {}), {"spread": 90.0})
        self.assertEqual(gizmos.dragged(hs["floor"], (0.0, 0.0), BW, BH, {}), {"floor_y": 0.5})
        got = gizmos.dragged(hs["accel"], (0.38 * BW + 100.0, -0.34 * BH + 50.0), BW, BH, {})
        self.assertEqual(got, {"wind": 400.0, "gravity": 200.0})

    def test_which_handles_there_are(self):
        e = gizmos.particle_effect(self.object(emitter="點", outward=True, floor_on=False))
        self.assertEqual({h["id"] for h in gizmos.handles(e, 0, BW, BH)}, {"origin", "speed", "accel"})
        e = gizmos.particle_effect(self.object(emitter="線"))
        self.assertEqual({h["id"] for h in gizmos.handles(e, 0, BW, BH)},
                         {"origin", "ewidth", "erot", "spread_a", "spread_b", "aim", "accel"})

    def test_the_canvas_size_scales_the_lengths(self):
        e = gizmos.particle_effect(self.object(emitter="線", ewidth=600.0, erot=0.0, origin_x=0.5, origin_y=0.5))
        h = next(h for h in gizmos.handles(e, 0, 960.0, 540.0) if h["id"] == "ewidth")       # (a 540-high canvas: half the px)
        self.assertAlmostEqual(h["local"][0], 150.0)


class GizmoMathTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()

    def effect(self, ref, **params):
        e = edit.add_effect(self.p, "c1", ref)
        e["params"].update(params)
        return e

    def test_every_spec_names_real_parameters(self):
        for ref, items in gizmos.SPECS.items():
            d = fx.get(ref)
            names = {q.name: q for q in d.params}
            for item in items:
                self.assertIn(item["param"], names, ref)
                self.assertEqual(names[item["param"]].type, "float" if item["kind"] in ("radius", "angle") else "vec2", ref)
                for other in (item.get("about"), item.get("origin"), item.get("reach_of")):
                    self.assertTrue(other is None or other in names, ref)

    def test_a_point_is_where_its_uv_is_and_dragged_back(self):
        e = self.effect("builtin:swirl", center=[0.25, 0.75])
        h = gizmos.handles(e, 0, BW, BH)
        pt = next(x for x in h if x["kind"] == "point")
        self.assertEqual(pt["local"], (-0.25 * BW, 0.25 * BH))
        got = gizmos.dragged(pt, (0.25 * BW, -0.25 * BH), BW, BH, {})
        self.assertEqual(got, {"center": [0.75, 0.25]})
        self.assertEqual(gizmos.dragged(pt, (3 * BW, 0), BW, BH, {})["center"][0], 1.0)           # (kept in its range)
        self.assertEqual(gizmos.dragged(pt, (0.004 * BW, 0), BW, BH, {})["center"][0], 0.5)       # (settles on the middle)
        self.assertNotEqual(gizmos.dragged(pt, (0.004 * BW, 0), BW, BH, {}, snap=False)["center"][0], 0.5)

    def test_sun_beams_point_counts_from_the_bottom_and_only_while_sun_beams(self):
        e = self.effect("builtin:blender_glare", sun_position=[0.5, 1.0])
        self.assertEqual(gizmos.handles(e, 0, BW, BH), [])                       # (the default type is Bloom)
        e["params"]["type"] = "Sun Beams"
        (h,) = gizmos.handles(e, 0, BW, BH)
        self.assertEqual(h["local"], (0.0, -0.5 * BH))                           # (1.0 = the top)
        self.assertEqual(gizmos.dragged(h, (0.0, 0.5 * BH), BW, BH, {})["sun_position"], [0.5, 0.0])

    def test_radius_is_in_picture_heights_round_the_centre(self):
        e = self.effect("builtin:bulge", center=[0.5, 0.5], radius=0.6)
        r = next(x for x in gizmos.handles(e, 0, BW, BH) if x["kind"] == "radius")
        self.assertAlmostEqual(r["local"][0], 0.6 * BH)
        self.assertEqual(gizmos.dragged(r, (0.0, 0.3 * BH), BW, BH, {}), {"radius": 0.3})
        self.assertEqual(gizmos.dragged(r, (0.0, 0.0), BW, BH, {}), {"radius": 0.05})            # (its smallest)

    def test_angle_goes_on_past_half_a_turn(self):
        e = self.effect("builtin:swirl", center=[0.5, 0.5], radius=0.5, angle=0.0)
        a = next(x for x in gizmos.handles(e, 0, BW, BH) if x["kind"] == "angle")
        state, last = {}, None
        for deg in range(0, 361, 45):                                              # a turn clockwise on the screen, in steps
            import math
            pt = (200 * math.cos(math.radians(deg)), 200 * math.sin(math.radians(deg)))
            last = gizmos.dragged(a, pt, BW, BH, state)
        self.assertAlmostEqual(last["angle"], 360.0, places=1)
        back = gizmos.dragged(a, (200.0, 0.0), BW, BH, state)
        self.assertAlmostEqual(back["angle"], 360.0, places=1)
        k = self.effect("builtin:kaleidoscope", rotation=0.0)
        a = next(x for x in gizmos.handles(k, 0, BW, BH) if x["kind"] == "angle")
        self.assertEqual(gizmos.dragged(a, (0.0, 100.0), BW, BH, {})["rotation"], -90.0)       # (it turns the other way)

    def test_an_offset_moves_from_the_anchor(self):
        e = self.effect("builtin:translate", offset=[100.0, -50.0])
        (h,) = gizmos.handles(e, 0, BW, BH)
        self.assertEqual(h["local"], (100.0, -50.0))
        self.assertEqual(gizmos.dragged(h, (300.0, 40.0), BW, BH, {}), {"offset": [300.0, 40.0]})
        t = self.effect("builtin:transform", position=[10.0, 0.0], anchor=[0.1, 0.0], rotation=0.0)
        off = next(x for x in gizmos.handles(t, 0, BW, BH) if x["kind"] == "offset")
        self.assertEqual(off["local"], (0.1 * BW + 10.0, 0.0))
        self.assertEqual(gizmos.dragged(off, (0.1 * BW + 50.0, 5.0), BW, BH, {}), {"position": [50.0, 5.0]})
        rot = next(x for x in gizmos.handles(t, 0, BW, BH) if x["kind"] == "angle")
        self.assertAlmostEqual(rot["local"][1], -0.35 * BH)                      # (straight up while the angle is 0)


class NodeGizmoTests(unittest.TestCase):
    def test_a_node_of_a_node_effect_has_handles_unless_a_link_sets_the_value(self):
        from kiasecut import nodegraph as ng
        p = proj()
        eff = edit.add_effect(p, "c1", fx.GRAPH)
        n = edit.add_graph_node(p, "c1", eff["id"], {"type": "filter", "ref": "builtin:swirl"})
        pseudo = gizmos.node_effect(eff, n)
        self.assertEqual({h["kind"] for h in gizmos.handles(pseudo, 0, BW, BH)}, {"point", "radius", "angle"})
        eff["graph"]["nodes"][n]["x"] = 0
        v = edit.add_graph_node(p, "c1", eff["id"], {"type": "filter", "ref": "builtin:nodes/value"})
        edit.connect_graph(p, "c1", eff["id"], v, n, "param:radius")
        self.assertEqual({h["kind"] for h in gizmos.handles(gizmos.node_effect(eff, n), 0, BW, BH)}, {"point", "angle"})
        self.assertIsNone(gizmos.node_effect(eff, v))
        pv = Preview()
        pv.resize(960, 540)
        pv.set_scene(p, S // 2, "c1")
        pv.set_gizmo(eff["id"], n)
        got = []
        pv.paramsCommitted.connect(lambda *a: got.append(a))
        QTest.mousePress(pv, Qt.LeftButton, NONE, QPoint(480, 270))
        QTest.mouseMove(pv, QPoint(540, 270))
        QTest.mouseMove(pv, QPoint(600, 270))
        QTest.mouseRelease(pv, Qt.LeftButton, NONE, QPoint(600, 270))
        (cid, group, vals), = got
        self.assertEqual(group, "fx:" + eff["id"])
        self.assertAlmostEqual(vals[n + ".center"][0], 0.625, places=2)


class GizmoPreviewTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()

    def preview(self, ref, **params):
        self.e = edit.add_effect(self.p, "c1", ref)
        self.e["params"].update(params)
        pv = Preview()
        pv.resize(960, 540)
        pv.set_scene(self.p, S // 2, "c1")
        pv.set_gizmo(self.e["id"])
        return pv

    def drag(self, pv, a, b):
        got, live = [], []
        pv.paramsCommitted.connect(lambda *args: got.append(args))
        pv.paramsLive.connect(lambda *args: live.append(args))
        QTest.mousePress(pv, Qt.LeftButton, NONE, a)
        QTest.mouseMove(pv, (a + b) / 2)
        QTest.mouseMove(pv, b)
        QTest.mouseRelease(pv, Qt.LeftButton, NONE, b)
        return got, live

    def test_the_centre_is_dragged_on_the_canvas(self):
        pv = self.preview("builtin:swirl", center=[0.5, 0.5], radius=0.2)
        got, live = self.drag(pv, QPoint(480, 270), QPoint(600, 135))
        self.assertTrue(live)
        (cid, group, vals), = got
        self.assertEqual((cid, group), ("c1", "fx:" + self.e["id"]))
        self.assertAlmostEqual(vals["center"][0], 0.625, places=2)
        self.assertAlmostEqual(vals["center"][1], 0.25, places=2)
        edit.set_param(self.p, cid, group, "center", vals["center"], 0)             # and it is a valid edit
        self.assertEqual(self.e["params"]["center"], vals["center"])

    def test_the_radius_handle_is_dragged_and_the_clip_stays_put(self):
        pv = self.preview("builtin:bulge", center=[0.5, 0.5], radius=0.3)
        x = 480 + round(0.3 * 540)                                                  # (0.3 picture heights right of the middle)
        got, _ = self.drag(pv, QPoint(x, 270), QPoint(480 + 216, 270))
        (cid, group, vals), = got
        self.assertEqual(group, "fx:" + self.e["id"])
        self.assertAlmostEqual(vals["radius"], 0.4, places=2)

    def test_a_particle_objects_handles_are_always_there_and_edit_its_fields(self):
        from kiasecut import assets
        params = assets.make(assets.get("particle.system"), "#ffffff", "#000000", 1920, 1080)
        edit.replace_media(self.p, "c1", assets.item(params, "/a.svg"), params)
        pv = Preview()
        pv.resize(960, 540)
        pv.set_scene(self.p, S // 2, "c1")                                          # (no effect picked: still its handles)
        self.assertEqual(pv.gizmo_effect(pv.selected_box())["filter"], "builtin:particle_system")
        got, live = self.drag(pv, QPoint(480, 270), QPoint(600, 135))
        self.assertTrue(live)
        (cid, group, vals), = got
        self.assertEqual((cid, group), ("c1", "asset"))
        self.assertAlmostEqual(vals["pt_origin_x"], 0.625, places=2)
        self.assertAlmostEqual(vals["pt_origin_y"], 0.25, places=2)
        for key, v in vals.items():                                                 # (and a valid edit)
            edit.set_param(self.p, cid, group, key, v, 0)
        self.assertAlmostEqual(edit.find(self.p, "c1")[1]["asset"]["pt_origin_x"], 0.625, places=2)

    def test_a_cameras_handles_are_on_the_selected_group_and_change_its_camera(self):
        g = edit.make_group(self.p, self.p, ["c1"])
        gid = g["id"] if isinstance(g, dict) else g
        edit.set_param(self.p, gid, "camera", "on", True)
        pv = Preview()
        pv.resize(960, 540)
        pv.set_scene(self.p, S // 2, gid)
        e = pv.gizmo_effect(pv.selected_box())
        self.assertEqual(e["filter"], "builtin:camera")
        self.assertEqual({h["id"] for h in gizmos.handles(e, 0, BW, BH)}, {"pan", "orbit", "dolly", "fov"})
        got, live = self.drag(pv, QPoint(480, 270), QPoint(540, 240))               # (the 平移 handle, in the middle)
        self.assertTrue(live)
        (cid, group, vals), = got
        self.assertEqual((cid, group), (gid, "camera"))
        self.assertLess(vals["x"], 0.0)                                              # (the picture follows the pointer, right and up: the camera goes left and down)
        self.assertLess(vals["y"], 0.0)
        for key, v in vals.items():
            edit.set_param(self.p, cid, group, key, v, 0)
        self.assertAlmostEqual(edit.find(self.p, gid)[1]["camera"]["x"], vals["x"], places=3)

    def test_without_a_picked_effect_the_clip_moves_as_before(self):
        pv = self.preview("builtin:swirl")
        pv.set_gizmo(None)
        got, _ = self.drag(pv, QPoint(480, 270), QPoint(580, 270))
        self.assertEqual(got[0][1], "transform")

    def test_the_effects_panel_picks_the_effect(self):
        e = edit.add_effect(self.p, "c1", "builtin:swirl")
        panel = EffectsPanel()
        changed = []
        panel.show_clips([edit.find(self.p, "c1")[1]], 0, 30)
        panel.maskEditChanged.connect(lambda: changed.append(panel.gizmo_edit))
        button = panel.widgets[("gizmo_edit", e["id"])]
        button.setChecked(True)
        self.assertEqual(panel.gizmo_edit, e["id"])
        button.setChecked(False)
        self.assertEqual(changed, [e["id"], None])
        self.assertNotIn(("gizmo_edit", edit.add_effect(self.p, "c1", "builtin:blur")["id"]), panel.widgets)


class BackdropGizmoTests(unittest.TestCase):
    """The handles are on the node editor's backdrop too: drawn over the picture, dragged there."""

    def setUp(self):
        from PySide6.QtGui import QImage
        from kiasecut.ui.preview import Box
        self.p = proj()
        self.e = edit.add_effect(self.p, "c1", "builtin:bulge")
        self.e["params"].update(center=[0.5, 0.5], radius=0.3)
        clip = edit.find(self.p, "c1")[1]
        self.box = Box(clip, 1920, 1080, 0)
        self.view = self.make_view()
        img = QImage(192, 108, QImage.Format_RGB32)
        img.fill(0)
        self.view.resize(400, 300)
        self.view.set_backdrop(img)
        self.view.set_backdrop_visible(True)
        self.view.gizmo_source = lambda: ("c1", self.e, self.box, None)
        self.live, self.done = [], []
        self.view.gizmoLive.connect(lambda *a: self.live.append(a))
        self.view.gizmoCommitted.connect(lambda *a: self.done.append(a))

    @staticmethod
    def make_view():
        from kiasecut.ui.node_editor import NodeEditor
        ed = NodeEditor()
        return ed.view

    def test_a_handle_dragged_on_the_backdrop_sets_its_parameter(self):
        v = self.view
        to_view = v._canvas_to_view(self.box)
        h = next(x for x in gizmos.handles(self.e, 0, self.box.bw, self.box.bh) if x["kind"] == "radius")
        a = to_view.map(self.box.xf().map(QPointF(*h["local"])))
        self.assertIsNotNone(v._gizmo_hit(a))
        far = to_view.map(QPointF(960 + 0.4 * 1080, 540))
        QTest.mousePress(v.viewport(), Qt.LeftButton, NONE, a.toPoint())
        QTest.mouseMove(v.viewport(), far.toPoint())
        QTest.mouseRelease(v.viewport(), Qt.LeftButton, NONE, far.toPoint())
        self.assertTrue(self.done)
        cid, group, vals = self.done[-1]
        self.assertEqual((cid, group), ("c1", "fx:" + self.e["id"]))
        self.assertAlmostEqual(vals["radius"], 0.4, places=1)


if __name__ == "__main__":
    unittest.main()
