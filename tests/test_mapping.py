"""映射: how a bound number follows its parameter - as it is, linear between a minimum and a maximum,
along a cubic-bezier curve, or by JavaScript."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import assets, components, edit, mapping, project, propexpr, rack  # noqa: E402
from test_edit import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


class MappingTests(unittest.TestCase):
    def test_modes(self):
        self.assertEqual(mapping.apply(mapping.make("direct"), 7.5), 7.5)
        lin = mapping.make("linear", in_=(0, 10), out=(100, 0))
        self.assertEqual([mapping.apply(lin, x) for x in (-5, 0, 2.5, 10, 99)], [100, 100, 75, 0, 0])      # (held past the ends)
        bz = mapping.make("bezier", in_=(0, 1), out=(0, 200), bezier=(0.42, 0, 0.58, 1))
        self.assertLess(mapping.apply(bz, 0.25), 50)                                                       # (ease in)
        self.assertAlmostEqual(mapping.apply(bz, 0.5), 100, delta=1)
        js = mapping.make("js", in_=(0, 2), out=(10, 20), js="t > 0.5 ? hi : lo")
        self.assertEqual([mapping.apply(js, x) for x in (0.4, 1.6)], [10, 20])
        self.assertEqual(mapping.apply(mapping.make("js", js="input * 3 + other", in_=(0, 1)), 2.0, {"other": 1.0}), 7.0)
        self.assertEqual(mapping.apply(mapping.make("js", js="nothing_here"), 0.5, {}), 0.5)               # (broken: linear)

    def test_checks_and_preview_points(self):
        self.assertIsNone(mapping.check(mapping.make("linear")))
        self.assertIsNotNone(mapping.check(mapping.make("js", js="1 +")))
        self.assertIsNotNone(mapping.check(mapping.make("bezier", bezier=(1.5, 0, 0.5, 1))))
        self.assertIsNotNone(mapping.check({"mode": "nope"}))
        pts = mapping.curve_points(mapping.make("linear", in_=(0, 4), out=(0, 8)), 4)
        self.assertEqual(pts, [(0.0, 0.0), (1.0, 2.0), (2.0, 4.0), (3.0, 6.0), (4.0, 8.0)])
        self.assertEqual(mapping.names(mapping.make("js", src="speed", js="input + gain + t")), {"speed", "gain"})


class BoundNumberTests(unittest.TestCase):
    def setUp(self):
        p = proj()
        p["tracks"][0]["clips"] = p["tracks"][0]["clips"][:1]
        a = assets.make(assets.get("shape.rect"), "#ff0000", "#000000", 192, 108)
        edit.replace_media(p, "c1", assets.item(a, "/nowhere.svg"), a)
        self.p = p
        self.c = edit.find(p, "c1")[1]

    def test_a_rack_parameter_through_a_mapping(self):
        r = edit.add_rack_param(self.p, "level", 0.5)
        m = mapping.make("linear", src="level", in_=(0, 1), out=(-2, 2))
        edit.set_prop_expr(self.p, "c1", "transform.x", m)
        out = propexpr.at(self.c, 0, rack.values(self.p, 0))
        self.assertAlmostEqual(out["transform"]["x"], 0.0)
        edit.set_rack_value(self.p, r["id"], 1.0)
        self.assertAlmostEqual(propexpr.at(self.c, 0, rack.values(self.p, 0))["transform"]["x"], 2.0)
        self.assertEqual(rack.users(self.p, "level"), 1)
        edit.rename_rack_param(self.p, r["id"], "volume_knob")
        self.assertEqual(self.c["expr"]["transform.x"]["src"], "volume_knob")
        self.assertAlmostEqual(propexpr.at(self.c, 0, rack.values(self.p, 0))["transform"]["x"], 2.0)
        with self.assertRaises(edit.EditError):
            edit.set_prop_expr(self.p, "c1", "transform.x", mapping.make("js", js="1 +"))

    def test_a_deleted_parameter_leaves_the_number(self):
        edit.add_rack_param(self.p, "gone", 0.5)
        edit.set_prop_expr(self.p, "c1", "transform.x", mapping.make("linear", src="gone", out=(5, 6)))
        self.assertEqual(propexpr.at(self.c, 0, {})["transform"].get("x", 0.0), 0.0)

    def test_a_component_parameter_through_a_mapping(self):
        a = assets.make(assets.get("shape.rect"), "#ff0000", "#000000", 192, 108)
        p = proj()
        p["tracks"][0]["clips"] = p["tracks"][0]["clips"][:1]
        edit.replace_media(p, "c1", assets.item(a, "/nowhere.svg"), a)
        clip = edit.make_compound(p, p, ["c1"], 0, static=True, component=True)
        kid, cid = clip["compound_id"], clip["id"]
        prm = edit.add_param(p, kid, "number", "強度", [("c1", "transform.opacity")])
        edit.set_bind_expr(p, kid, prm["id"], "c1", "transform.opacity", mapping.make("linear", in_=(0, 10), out=(0, 100)))
        inst = edit.find(p, cid)[1]
        edit.set_param(p, cid, "params", prm["id"], 5.0, 0)
        layer = components.content(inst, 0)["tracks"][0]["clips"][0]
        self.assertAlmostEqual(layer["transform"]["opacity"], 0.5)                                         # (5 of 0 - 10: 50 %)
        edit.set_bind_expr(p, kid, prm["id"], "c1", "transform.opacity", mapping.make("direct"))           # (direct: nothing kept)
        self.assertNotIn("exprs", prm)
        comp = p["compounds"][kid]
        self.assertEqual(components.expr_of(prm, "c1", "transform.opacity"), "input")


class DialogTests(unittest.TestCase):
    def test_dialog_gives_the_mapping_and_checks_it(self):
        from PySide6.QtWidgets import QDialogButtonBox
        from kiasecut.ui.mapdialog import MapDialog
        d = MapDialog(None, "t", mapping.make(src="speed"), "全局參數「speed」", 0.25, {"speed": 0.25}, (0.0, 100.0))
        self.assertEqual(d.mapping()["mode"], "direct")
        self.assertEqual((d.out_lo.value(), d.out_hi.value()), (0.0, 100.0))                            # (the field's own range)
        d.mode.setCurrentIndex(d.mode.findData("linear"))
        d.out_lo.setValue(10)
        d.out_hi.setValue(20)
        m = d.mapping()
        self.assertEqual((m["mode"], m["src"], m["out"]), ("linear", "speed", [10.0, 20.0]))
        self.assertTrue(d.buttons.button(QDialogButtonBox.Ok).isEnabled())
        d.mode.setCurrentIndex(d.mode.findData("js"))
        d.js.setPlainText("1 +")
        self.assertFalse(d.buttons.button(QDialogButtonBox.Ok).isEnabled())
        self.assertIn("✗", d.status.text())
        d.mode.setCurrentIndex(d.mode.findData("bezier"))
        d.presets.activated.emit(d.presets.findText("緩入"))
        self.assertEqual([round(s.value(), 2) for s in d.bz], [0.42, 0.0, 1.0, 1.0])
        d.preview.grab()                                                                                # (it paints)


if __name__ == "__main__":
    unittest.main()
