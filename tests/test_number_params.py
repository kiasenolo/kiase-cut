"""Number parameters of a component: they set a layer's numbers (position, opacity, a shape's
size) through an expression of their own, per instance."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import assets, components, curves, edit, project, propexpr, renderexport  # noqa: E402
from test_edit import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


class NumberParamTests(unittest.TestCase):
    def setUp(self):
        p = proj()
        p["tracks"][0]["clips"] = p["tracks"][0]["clips"][:1]
        a = assets.make(assets.get("shape.rect"), "#ff0000", "#000000", 1920, 1080)
        edit.replace_media(p, "c1", assets.item(a, "/nowhere.svg"), a)
        clip = edit.make_compound(p, p, ["c1"], 0, static=True, component=True)
        self.p, self.cid, self.kid = p, clip["id"], clip["compound_id"]
        self.comp = p["compounds"][self.kid]
        self.inst = edit.find(p, self.cid)[1]

    def layer(self, t=0):
        return components.content(self.inst, t)["tracks"][0]["clips"][0]

    def test_a_shape_offers_its_numbers(self):
        props = components.props_of(self.comp["tracks"][0]["clips"][0])
        for want in ("transform.x", "transform.opacity", "asset.radius", "visible", "color"):
            self.assertIn(want, props)
        self.assertNotIn("text.size", props)

    def test_a_number_parameter_sets_the_layer(self):
        p = edit.add_param(self.p, self.kid, "number", "橫移", [("c1", "transform.x")])
        self.assertEqual(components.default(self.comp, p), 0.0)
        edit.set_param(self.p, self.cid, "params", p["id"], 0.25, 0)
        self.assertAlmostEqual(self.layer()["transform"]["x"], 0.25)

    def test_opacity_is_in_percent(self):
        p = edit.add_param(self.p, self.kid, "number", "透明", [("c1", "transform.opacity")])
        self.assertEqual(components.default(self.comp, p), 100.0)
        edit.set_param(self.p, self.cid, "params", p["id"], 40.0, 0)
        self.assertAlmostEqual(self.layer()["transform"]["opacity"], 0.4)
        edit.set_param(self.p, self.cid, "params", p["id"], 400.0, 0)
        self.assertAlmostEqual(self.layer()["transform"]["opacity"], 1.0)         # (kept in 0 - 100 %)

    def test_expression(self):
        p = edit.add_param(self.p, self.kid, "number", "橫移", [("c1", "transform.x")])
        edit.set_bind_expr(self.p, self.kid, p["id"], "c1", "transform.x", "input * 2 + 0.5")
        edit.set_param(self.p, self.cid, "params", p["id"], 0.25, 0)
        self.assertAlmostEqual(self.layer()["transform"]["x"], 1.0)

    def test_expression_follows_time(self):
        p = edit.add_param(self.p, self.kid, "number", "橫移", [("c1", "transform.x")])
        edit.set_bind_expr(self.p, self.kid, p["id"], "c1", "transform.x", "time")
        # (no value of its own: the expression still works, on the default)
        self.assertAlmostEqual(self.layer(500_000)["transform"]["x"], 0.5)
        self.assertTrue(renderexport.needs_renderer(self.p))

    def test_expression_with_cubic_bezier_and_keyframes(self):
        p = edit.add_param(self.p, self.kid, "number", "進度", [("c1", "transform.x")])
        edit.set_bind_expr(self.p, self.kid, p["id"], "c1", "transform.x", "cubicBezier(0, 0, 1, 1, input)")
        edit.set_param(self.p, self.cid, "params", p["id"], 0.0, 0)
        edit.toggle_key(self.p, self.cid, "params", p["id"], 0)
        edit.set_param(self.p, self.cid, "params", p["id"], 1.0, 1_000_000)
        self.assertTrue(curves.is_animated(self.inst["params"][p["id"]]))
        self.assertAlmostEqual(self.layer(500_000)["transform"]["x"], 0.5, places=2)

    def test_broken_expression_is_refused_and_a_failing_one_leaves_the_value(self):
        p = edit.add_param(self.p, self.kid, "number", "橫移", [("c1", "transform.x")])
        with self.assertRaises(edit.EditError):
            edit.set_bind_expr(self.p, self.kid, p["id"], "c1", "transform.x", "input *")
        edit.set_bind_expr(self.p, self.kid, p["id"], "c1", "transform.x", "nothing * 2")     # (reads like a name)
        edit.set_param(self.p, self.cid, "params", p["id"], 0.3, 0)
        self.assertAlmostEqual(self.layer()["transform"]["x"], 0.3)

    def test_unbinding_drops_the_expression(self):
        p = edit.add_param(self.p, self.kid, "number", "橫移", [("c1", "transform.x")])
        edit.set_bind_expr(self.p, self.kid, p["id"], "c1", "transform.x", "input * 2")
        edit.unbind_param(self.p, self.kid, [("c1", "transform.x")])
        self.assertFalse(p.get("exprs"))

    def test_only_numbers_take_numbers(self):
        with self.assertRaises(edit.EditError):
            edit.add_param(self.p, self.kid, "text", "字", [("c1", "transform.x")])
        with self.assertRaises(edit.EditError):
            edit.add_param(self.p, self.kid, "number", "字", [("c1", "visible")])

    def test_default_sets_the_layers(self):
        p = edit.add_param(self.p, self.kid, "number", "橫移", [("c1", "transform.x")])
        edit.set_param_default(self.p, self.kid, p["id"], 0.4)
        self.assertAlmostEqual(components.default(self.comp, p), 0.4)

    def test_asset_number(self):
        p = edit.add_param(self.p, self.kid, "number", "圓角", [("c1", "asset.radius")])
        edit.set_param(self.p, self.cid, "params", p["id"], 120.0, 0)
        self.assertEqual(self.layer()["asset"]["radius"], 120.0)


class InstanceNumberTests(NumberParamTests):
    def test_an_instances_own_number_takes_an_expression(self):
        p = edit.add_param(self.p, self.kid, "number", "橫移", [("c1", "transform.x")])
        self.assertIn(f"params.{p['id']}", components.instance_props(self.inst))
        edit.set_prop_expr(self.p, self.cid, f"params.{p['id']}", "time / 2")
        out = propexpr.at(self.inst, 1_000_000)
        self.assertAlmostEqual(out["params"][p["id"]], 0.5)
        content = components.content(out, 1_000_000)
        self.assertAlmostEqual(content["tracks"][0]["clips"][0]["transform"]["x"], 0.5)


class NumberParamUiTests(unittest.TestCase):
    """The inspector: a number row on the instance, 設為元件參數 on the layers' numbers, drag to bind."""

    setUp = NumberParamTests.setUp

    def test_instance_row(self):
        from kiasecut.ui.inspector import Inspector
        p = edit.add_param(self.p, self.kid, "number", "橫移", [("c1", "transform.x")])
        ins = Inspector()
        got = []
        ins.paramEdited.connect(lambda ids, g, k, v: got.append((g, k, v)))
        ins.show_clips([self.inst], 0, 60)
        spin = ins.widgets[("params", p["id"])]
        self.assertEqual(spin.value(), 0.0)
        spin.edited.emit(0.5)
        ins._flush()
        self.assertEqual(got, [("params", p["id"], 0.5)])
        edit.set_param(self.p, self.cid, "params", p["id"], 0.5)
        ins.show_clips([self.inst], 0, 60)
        self.assertEqual(ins.widgets[("params", p["id"])].value(), 0.5)

    def test_layer_numbers_bind_by_drop_and_show_it(self):
        from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
        from PySide6.QtGui import QDropEvent
        from kiasecut.ui.inspector import Inspector
        from kiasecut.ui.params import PARAM_MIME
        p = edit.add_param(self.p, self.kid, "number", "橫移", [("c1", "transform.y")])
        layer = self.comp["tracks"][0]["clips"][0]
        ins = Inspector()
        ins.component_of = lambda: self.comp
        asked = []
        ins.paramBindRequested.connect(lambda pid, prop, ids: asked.append((pid, prop, ids)))
        ins.show_clips([layer], 0, 60)
        self.assertTrue(ins.widgets[("transform", "y")].toolTip().startswith("元件參數"))        # (it sets this one)
        self.assertEqual(ins.widgets[("transform", "x")].toolTip(), "")
        md = QMimeData()
        md.setData(PARAM_MIME, p["id"].encode())
        spin = ins.widgets[("transform", "x")]
        ev = QDropEvent(QPointF(3, 3), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
        self.assertTrue(spin.eventFilter(spin.lineEdit(), ev))                  # (as the field's own filter gets it)
        self.assertEqual(asked, [(p["id"], "transform.x", [layer["id"]])])
        self.assertEqual(ins._number_prop(("params", p["id"])), "params." + p["id"])
        self.assertEqual(ins._number_prop(("asset", "radius")), "asset.radius")


if __name__ == "__main__":
    unittest.main()
