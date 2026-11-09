"""Handles on the preview for an effect's centre, radius, angle and offset (gizmos.py, 編輯控制點)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, fx, gizmos  # noqa: E402
from kiasecut.ui.effects_panel import EffectsPanel  # noqa: E402
from kiasecut.ui.preview import Preview  # noqa: E402
from test_edit import S, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
NONE = Qt.KeyboardModifier.NoModifier
BW, BH = 1920.0, 1080.0


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


if __name__ == "__main__":
    unittest.main()
