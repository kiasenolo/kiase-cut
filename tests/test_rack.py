"""The global parameter rack: named numbers of the project that clips' expressions read."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import assets, edit, rack, render  # noqa: E402
from test_edit import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
S = 1_000_000


class RackTests(unittest.TestCase):
    def setUp(self):
        p = proj()
        p["tracks"][0]["clips"] = p["tracks"][0]["clips"][:1]
        a = assets.make(assets.get("shape.rect"), "#ff0000", "#000000", 192, 108)
        a.update(w=40, h=40)
        edit.replace_media(p, "c1", assets.item(a, "/nowhere.svg"), a)
        self.p = p

    def test_names(self):
        edit.add_rack_param(self.p, "speed", 2)
        for bad in ("", "1a", "speed", "time", "sin", "a b", "input"):
            with self.assertRaises(edit.EditError, msg=bad):
                edit.add_rack_param(self.p, bad)

    def test_value_expression_and_keyframes(self):
        a = edit.add_rack_param(self.p, "a", 2)
        edit.set_rack_expr(self.p, a["id"], "input * 3 + time")
        self.assertAlmostEqual(rack.values(self.p, 2 * S)["a"], 8.0)
        edit.toggle_rack_key(self.p, a["id"], 0)
        edit.set_rack_value(self.p, a["id"], 10.0, S)                         # (a new key at 1 s)
        edit.set_rack_expr(self.p, a["id"], "")
        self.assertAlmostEqual(rack.values(self.p, S // 2)["a"], 6.0)

    def test_parameters_read_each_other(self):
        a, b = edit.add_rack_param(self.p, "a", 2), edit.add_rack_param(self.p, "b", 1)
        edit.set_rack_expr(self.p, b["id"], "a * 10 + input")
        self.assertEqual(rack.values(self.p, 0), {"a": 2.0, "b": 21.0})

    def test_circles_are_refused(self):
        a, b, c = (edit.add_rack_param(self.p, n, 1) for n in "abc")
        edit.set_rack_expr(self.p, a["id"], "b + 1")
        edit.set_rack_expr(self.p, b["id"], "c + 1")
        with self.assertRaises(edit.EditError) as cm:
            edit.set_rack_expr(self.p, c["id"], "a + 1")
        self.assertIn("循環", str(cm.exception))
        self.assertNotIn("expr", c)                                              # (left as it was)
        with self.assertRaises(edit.EditError):
            edit.set_rack_expr(self.p, a["id"], "a * 2")                        # (itself)
        self.assertEqual(a["expr"], "b + 1")
        self.assertIsNone(rack.cycle(self.p))

    def test_a_circle_that_got_in_does_not_hang_drawing(self):
        a, b = edit.add_rack_param(self.p, "a", 1), edit.add_rack_param(self.p, "b", 2)
        a["expr"], b["expr"] = "b + 1", "a + 1"                                  # (a file written by hand)
        self.assertEqual(rack.cycle(self.p), ["a", "b"])
        v = rack.values(self.p, 0)
        self.assertEqual(set(v), {"a", "b"})

    def test_a_clip_follows_a_parameter(self):
        r = edit.add_rack_param(self.p, "shift", 0.5)
        edit.set_prop_expr(self.p, "c1", "transform.x", "shift")
        im = render.Renderer().render(dict(self.p), 0, 192, 108)
        self.assertEqual(im.pixelColor(144, 54).red(), 255)
        self.assertEqual(im.pixelColor(48, 54).red(), 0)
        edit.set_rack_value(self.p, r["id"], -0.5)
        im = render.Renderer().render(dict(self.p), 0, 192, 108)
        self.assertEqual(im.pixelColor(48, 54).red(), 255)

    def test_the_gpu_renderer_reads_it_too(self):
        from kiasecut import glrender
        try:
            gl = glrender.GLRenderer()
        except Exception:
            self.skipTest("no OpenGL 3.3 here")
        edit.add_rack_param(self.p, "shift", 0.5)
        edit.set_prop_expr(self.p, "c1", "transform.x", "shift")
        im = gl.render(dict(self.p), 0, 192, 108)
        self.assertEqual(im.pixelColor(144, 54).red(), 255)

    def test_rename_follows_the_expressions(self):
        a = edit.add_rack_param(self.p, "speed", 1)
        b = edit.add_rack_param(self.p, "other", 1)
        edit.set_rack_expr(self.p, b["id"], "speed * 2 + Math.speed")
        edit.set_prop_expr(self.p, "c1", "transform.x", "speed + wiggle(speed, 3)")
        self.assertEqual(rack.users(self.p, "speed"), 1)
        edit.rename_rack_param(self.p, a["id"], "tempo")
        self.assertEqual(b["expr"], "tempo * 2 + Math.speed")
        self.assertEqual(edit.find(self.p, "c1")[1]["expr"]["transform.x"], "tempo + wiggle(tempo, 3)")
        with self.assertRaises(edit.EditError):
            edit.rename_rack_param(self.p, a["id"], "other")

    def test_delete_move_and_easing(self):
        a, b = edit.add_rack_param(self.p, "a", 0), edit.add_rack_param(self.p, "b", 0)
        edit.move_rack_param(self.p, b["id"], -1)
        self.assertEqual([p["name"] for p in rack.params(self.p)], ["b", "a"])
        edit.toggle_rack_key(self.p, a["id"], 0)
        edit.set_rack_value(self.p, a["id"], 1.0, S)
        edit.set_rack_easing(self.p, a["id"], 0, "ease_in_out")
        self.assertLess(rack.values(self.p, S // 4)["a"], 0.25)
        edit.delete_rack_param(self.p, a["id"])
        edit.delete_rack_param(self.p, b["id"])
        self.assertNotIn("rack", self.p)

    def test_export_and_import(self):
        a = edit.add_rack_param(self.p, "a", 3)
        edit.set_rack_expr(self.p, a["id"], "input + 1")
        text = rack.export_text(self.p)
        other = proj()
        edit.add_rack_param(other, "a", 9)
        n = edit.import_rack(other, rack.parse_import(text))
        self.assertEqual(n, 1)
        self.assertEqual([p["name"] for p in rack.params(other)], ["a", "a2"])
        self.assertEqual(rack.values(other, 0), {"a": 9.0, "a2": 4.0})
        for bad in ("nope", "{}", '{"format": "kiasecut-rack", "params": []}'):
            with self.assertRaises(ValueError):
                rack.parse_import(bad)


class RackPanelTests(unittest.TestCase):
    def test_rows_follow_the_project_and_report_edits(self):
        from kiasecut.ui.rack_panel import RackPanel
        p = proj()
        a = edit.add_rack_param(p, "speed", 1.5)
        w = RackPanel()
        got = []
        w.action.connect(lambda rid, act, arg: got.append((rid, act, arg)))
        w.fill(p, 0)
        row = w.rows[a["id"]]
        self.assertEqual(row.spin.value(), 1.5)
        row.spin.edited.emit(2.0)
        row.key.click()
        row.expr.click()
        self.assertEqual(got, [(a["id"], "value", 2.0), (a["id"], "key", None), (a["id"], "expr", None)])
        edit.set_rack_expr(p, a["id"], "input * 2")
        w.fill(p, 0)
        self.assertIn("= 3", row.result.text())
        edit.rename_rack_param(p, a["id"], "tempo")
        w.fill(p, 0)
        self.assertEqual(w.rows[a["id"]].name.text(), "tempo")
        edit.delete_rack_param(p, a["id"])
        w.fill(p, 0)
        self.assertEqual(w.rows, {})

    def test_inspector_binds_a_number_to_a_parameter(self):
        from kiasecut.ui.inspector import Inspector
        p = proj()
        c = edit.find(p, "c1")[1]
        ins = Inspector()
        ins.rack_names = lambda: ["speed"]
        got = []
        ins.exprChosen.connect(lambda ids, prop, text: got.append((ids, prop, text)))
        ins.show_clips([c], 0, 60)
        ins.exprChosen.emit(["c1"], "transform.x", "speed")
        self.assertEqual(got, [(["c1"], "transform.x", "speed")])


if __name__ == "__main__":
    unittest.main()
