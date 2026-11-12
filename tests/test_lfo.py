"""LFO: a number that swings along a wave (lfo.py), as a global parameter or on a clip's own number."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import assets, components, edit, lfo, propexpr, rack, render  # noqa: E402
from test_edit import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
S = 1_000_000


class MixedDialogTests(unittest.TestCase):
    def test_only_changed_fields_are_written(self):
        from kiasecut.ui import lfodialog
        a, b = lfo.make(rate=1, amp=5, offset=10), lfo.make(rate=2, amp=5, offset=20, wave="saw")
        d = lfodialog.LfoDialog(None, "x", a, "", True, [a, b])
        self.assertEqual(d.mixed, {"wave", "rate", "offset"})
        self.assertEqual(d.rate.lineEdit().text(), "--")
        d.amp.setValue(9)
        self.assertEqual(d.touched, {"amp"})
        self.assertEqual(d.spec()["rate"], 1.0)                      # (untouched: the preview uses the first's)


class WaveTests(unittest.TestCase):
    def test_sine_and_period(self):
        s = lfo.make("sine", rate=2, amp=3, offset=10)
        self.assertAlmostEqual(lfo.value(s, 0), 10.0)
        self.assertAlmostEqual(lfo.value(s, 0.125), 13.0)                      # (a quarter of a 0.5 s cycle)
        self.assertAlmostEqual(lfo.value(s, 0.5), 10.0)
        by_period = lfo.make("sine", unit="sec", rate=0.5, amp=3, offset=10)
        self.assertAlmostEqual(lfo.value(by_period, 0.125), 13.0)

    def test_phase_and_unipolar(self):
        s = lfo.make("saw", rate=1, phase=90, bipolar=False, amp=4)
        self.assertAlmostEqual(lfo.value(s, 0), 1.0)
        self.assertAlmostEqual(lfo.value(s, 0.75), 0.0, places=6)              # (wrapped round)

    def test_fade_in(self):
        s = lfo.make("square", rate=1, width=1.0, amp=2, fade=4)
        self.assertAlmostEqual(lfo.value(s, 1), 0.5)
        self.assertAlmostEqual(lfo.value(s, 8), 2.0)

    def test_repeat_and_mirror(self):
        rep = lfo.make("saw", bipolar=False)
        mir = lfo.make("saw", bipolar=False, loop="mirror")
        self.assertAlmostEqual(lfo.wave(rep, 0.75), 0.75)
        self.assertAlmostEqual(lfo.wave(mir, 0.25), 0.5)
        self.assertAlmostEqual(lfo.wave(mir, 0.75), 0.5)
        self.assertAlmostEqual(lfo.wave(mir, 0.5), 1.0)

    def test_bezier_and_curve(self):
        b = lfo.make("bezier", bezier=(0, 0, 1, 1), bipolar=False)
        self.assertAlmostEqual(lfo.wave(b, 0.5), 0.5, places=3)
        c = lfo.make("curve", curve=[[0, 1, 0, 0, 0, 0], [1, 1, 0, 0, 0, 0]], bipolar=False)
        self.assertAlmostEqual(lfo.wave(c, 0.3), 1.0)

    def test_random_holds_a_cycle(self):
        s = lfo.make("random", rate=1)
        self.assertEqual(lfo.value(s, 0.1), lfo.value(s, 0.9))
        self.assertNotEqual(lfo.value(s, 0.5), lfo.value(s, 1.5))

    def test_check(self):
        self.assertIsNone(lfo.check(lfo.make()))
        self.assertIsNotNone(lfo.check(lfo.make(unit="sec", rate=0)))
        self.assertIsNotNone(lfo.check(lfo.make("bezier", bezier=(2, 0, 0.5, 1))))
        self.assertEqual(lfo.safe(lfo.make(rate=float("nan")), 1.0, 7.0), 7.0)


class UseTests(unittest.TestCase):
    def setUp(self):
        p = proj()
        p["tracks"][0]["clips"] = p["tracks"][0]["clips"][:1]
        a = assets.make(assets.get("shape.rect"), "#ff0000", "#000000", 192, 108)
        a.update(w=40, h=40)
        edit.replace_media(p, "c1", assets.item(a, "/nowhere.svg"), a)
        self.p = p

    def test_rack_parameter(self):
        a = edit.add_rack_param(self.p, "a", 5)
        edit.set_rack_lfo(self.p, a["id"], lfo.make("sine", amp=2, offset=1))
        self.assertAlmostEqual(rack.values(self.p, S // 4)["a"], 3.0)
        edit.set_rack_expr(self.p, a["id"], "input * 2")                       # (the expression reads the LFO's output)
        self.assertAlmostEqual(rack.values(self.p, S // 4)["a"], 6.0)
        with self.assertRaises(edit.EditError):
            edit.set_rack_lfo(self.p, a["id"], lfo.make(unit="sec", rate=0))
        edit.set_rack_lfo(self.p, a["id"], None)
        self.assertNotIn("lfo", a)
        self.assertAlmostEqual(rack.values(self.p, S // 4)["a"], 10.0)

    def test_export_import_keeps_it(self):
        a = edit.add_rack_param(self.p, "a", 5)
        edit.set_rack_lfo(self.p, a["id"], lfo.make("triangle", rate=3))
        items = rack.parse_import(rack.export_text(self.p))
        self.assertEqual(items[0]["lfo"]["wave"], "triangle")

    def test_clip_number(self):
        c = edit.find(self.p, "c1")[1]
        prop = next(k for k in components.number_props_of(c) if k.endswith("rotation"))
        base = components.number_at(c, prop, 0)
        spec = lfo.make("square", rate=1, width=0.5, amp=10, offset=3, rel=True)
        edit.set_prop_expr(self.p, "c1", prop, spec)
        c = edit.find(self.p, "c1")[1]
        self.assertAlmostEqual(components.number_at(propexpr.at(c, S // 4), prop, 0), base + 3 + 10)
        self.assertAlmostEqual(components.number_at(propexpr.at(c, 3 * S // 4), prop, 0), base + 3 - 10)
        self.assertEqual(rack.users(self.p, "a"), 0)                          # (an LFO reads no names)
        edit.set_prop_expr(self.p, "c1", prop, "")
        self.assertNotIn("expr", edit.find(self.p, "c1")[1])

    def test_the_panel_shows_a_clip_whose_number_has_an_lfo_or_a_mapping(self):
        from kiasecut import mapping
        from kiasecut.ui.inspector import Inspector
        c = edit.find(self.p, "c1")[1]
        ins = Inspector()
        for spec, said in ((lfo.make("sine", rate=2), "LFO"), (mapping.make(src="a"), "映射：a"), ("value * 2", "表達式：value * 2")):
            c["expr"] = {"transform.rotation": spec}
            ins.show_clips([c], 0, 60)                                         # (the tip joined "表達式：" and a dict: TypeError)
            self.assertIn(said, ins.widgets[("transform", "rotation")].toolTip())

class RampTests(unittest.TestCase):
    def test_time_ramp_grows_the_speed_from_slow_to_full(self):
        s = lfo.make("sine", rate=4, ramp=2, ramp_from=0.25)
        self.assertAlmostEqual(lfo.cycles(s, 0), 0)
        self.assertAlmostEqual(lfo.cycles(s, 2), 1 * 2 + 3 * 2 / 2)         # 1 Hz -> 4 Hz over 2 s: 5 cycles
        self.assertAlmostEqual(lfo.cycles(s, 3), 5 + 4)                     # then 4 Hz
        self.assertAlmostEqual(lfo.cycles(lfo.make(rate=4), 3), 12)         # (no ramp: as before)

    def test_old_specs_without_ramp_still_work(self):
        s = lfo.make("sine", rate=2)
        del s["ramp"], s["ramp_from"]
        self.assertIsNone(lfo.check(s))
        self.assertAlmostEqual(lfo.value(s, 0.125), lfo.value(lfo.make("sine", rate=2), 0.125))

    def test_preview_zooms_and_resets(self):
        from kiasecut.ui.lfodialog import WavePreview
        w = WavePreview()
        w.resize(400, 200)
        auto = w.window()
        w.view = (0.0, auto[1] * 4)
        self.assertEqual(w.window()[1], auto[1] * 4)
        w.mouseDoubleClickEvent(None)
        self.assertEqual(w.window(), auto)
        w.grab()

    def test_dialog_has_the_ramp_fields(self):
        from kiasecut.ui.lfodialog import LfoDialog
        d = LfoDialog(None, "t", lfo.make(ramp=3, ramp_from=0.5))
        self.assertEqual((d.spec()["ramp"], d.spec()["ramp_from"]), (3.0, 0.5))
        self.assertTrue(d.ramp_from.isEnabled())


if __name__ == "__main__":
    unittest.main()
