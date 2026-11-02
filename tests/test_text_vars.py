"""文字變數: values written into a text's words as {name}, keyframed like any value."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from kiasecut import edit, project, render, textvars  # noqa: E402
from test_edit import S  # noqa: E402


class TextVarTests(unittest.TestCase):
    def setUp(self):
        self.p = project.new()
        self.c = edit.add_text(self.p, 0, "分數 {value}", duration_us=4 * S)
        self.tx = self.c["text"]

    def test_kinds_and_formats(self):
        v = edit.add_text_var(self.p, self.c["id"], "float")
        self.assertEqual(v["name"], "value")
        edit.set_param(self.p, self.c["id"], "tvar:value", "value", 3.14159)
        self.assertEqual(textvars.expand(self.tx, 0), "分數 3.14")
        self.tx["content"] = "{value:.4f} \\{value} {nothing}"
        self.assertEqual(textvars.expand(self.tx, 0), "3.1416 {value} {nothing}")
        edit.set_text_var(self.p, self.c["id"], "value", decimals=0)
        self.tx["content"] = "{value}"
        self.assertEqual(textvars.expand(self.tx, 0), "3")
        t = edit.add_text_var(self.p, self.c["id"], "time")
        edit.set_param(self.p, self.c["id"], "tvar:" + t["name"], "value", 3725.5)
        self.tx["content"] = "{value2} {value2:hh:mm:ss.SS} {value2:s}"
        self.assertEqual(textvars.expand(self.tx, 0), "62:05 01:02:05.50 3725")
        col = edit.add_text_var(self.p, self.c["id"], "color")
        edit.set_param(self.p, self.c["id"], "tvar:" + col["name"], "value", textvars.parse_hex("#FF8000"))
        self.tx["content"] = "{value3}"
        self.assertEqual(textvars.expand(self.tx, 0), "#ff8000")

    def test_keyframes_and_rename(self):
        edit.add_text_var(self.p, self.c["id"], "number")
        cid = self.c["id"]
        edit.toggle_key(self.p, cid, "tvar:value", "value", 0)
        edit.set_param(self.p, cid, "tvar:value", "value", 100, 2 * S)
        self.assertTrue(textvars.animated(self.tx))
        self.assertEqual(textvars.expand(self.tx, 2 * S), "分數 100")
        mid = int(textvars.expand(self.tx, S).split()[-1])
        self.assertTrue(0 < mid < 100)
        edit.set_text_var(self.p, cid, "value", new_name="score")
        self.assertEqual(self.tx["content"], "分數 {score}")                 # the words follow the name
        with self.assertRaises(edit.EditError):
            edit.set_text_var(self.p, cid, "score", new_name="1bad")
        edit.set_text_var(self.p, cid, "score", kind="text")                 # a new kind: keyframes gone
        self.assertEqual(self.tx["vars"][0]["value"], "")
        edit.remove_text_var(self.p, cid, "score")
        self.assertNotIn("vars", self.tx)

    def test_drawn(self):
        edit.add_text_var(self.p, self.c["id"], "number")
        edit.set_param(self.p, self.c["id"], "tvar:value", "value", 7)
        spec = textvars.spec_at(self.tx, 0, render.TEXT_FIELDS)
        self.assertEqual(spec["content"], "分數 7")
        self.assertNotIn("vars", spec)


class CurveEditorTests(unittest.TestCase):
    def test_a_keyframed_variable_is_in_the_curves(self):
        from PySide6.QtWidgets import QApplication
        from kiasecut.ui.curve_editor import CurveEditor
        APP = QApplication.instance() or QApplication([])
        p = project.new()
        c = edit.add_text(p, 0, "分數 {value}", duration_us=4 * S)
        edit.add_text_var(p, c["id"], "number")
        edit.add_text_var(p, c["id"], "color")
        edit.toggle_key(p, c["id"], "tvar:value", "value", 0)
        edit.set_param(p, c["id"], "tvar:value", "value", 50, S)
        edit.toggle_key(p, c["id"], "tvar:value2", "value", 0)
        ed = CurveEditor()
        ed.set_clip(c, S // 2, 30)
        names = {r[:2] for r in ed.rows}
        self.assertIn(("tvar:value", "value"), names)
        self.assertIn(("tvar:value2", "value"), names)
        self.assertTrue(ed.checked >= {("tvar:value", "value"), ("tvar:value2", "value")})     # (animated: shown at once)
        shown = [cv for cv in ed.canvas.curves if cv.get("keys")]
        self.assertGreaterEqual(len(shown), 2)


if __name__ == "__main__":
    unittest.main()
