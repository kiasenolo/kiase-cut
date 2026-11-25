"""The kinds of global parameter besides numbers (整數、開關、選單、向量、顏色、文字、字體): made, edited,
keyframed, saved, read by expressions, and followed by clips' fields through links (racklinks.py)."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import assets, edit, fonts, fx, project, propexpr, rack, racklinks, render, stillspans  # noqa: E402
from test_edit import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
S = 1_000_000
SAMPLE = {"number": 1.5, "int": 3, "bool": True, "menu": "b", "vec2": [1.0, 2.0], "vec3": [1.0, 2.0, 3.0],
          "color": [1.0, 0.0, 0.0, 1.0], "text": "哈囉", "font": "/fonts/a.ttf"}
OTHER = {"number": 3.5, "int": 7, "bool": False, "menu": "c", "vec2": [3.0, 4.0], "vec3": [3.0, 4.0, 5.0],
         "color": [0.0, 0.0, 1.0, 1.0], "text": "再見", "font": "/fonts/b.ttf"}


def add(p, kind, name=None, value=None):
    return edit.add_rack_param(p, name or "p_" + kind, SAMPLE[kind] if value is None else value, kind,
                               ["a", "b", "c"] if kind == "menu" else None)


def shape_project():
    p = proj()
    p["tracks"][0]["clips"] = p["tracks"][0]["clips"][:1]
    a = assets.make(assets.get("shape.rect"), "#ff0000", "#000000", 192, 108)
    a.update(w=40, h=40)
    edit.replace_media(p, "c1", assets.item(a, "/nowhere.svg"), a)
    return p


def text_project():
    p = proj()
    edit.add_text(p, 0, "自己的字", S)
    c = next(c for t in p["tracks"] for c in t["clips"] if c["type"] == "text")
    return p, c["id"]


class KindTests(unittest.TestCase):
    def test_every_kind_has_a_default_and_a_value(self):
        self.assertEqual(set(SAMPLE), set(rack.KINDS))
        p = proj()
        for kind in rack.KINDS:
            made = edit.add_rack_param(p, "d_" + kind, kind=kind)
            self.assertEqual(rack.clean(kind, made["value"], made.get("items") or ()), made["value"], kind)
            edit.set_rack_value(p, made["id"], SAMPLE[kind] if kind != "menu" else rack.DEFAULT_ITEMS[1])

    def test_a_number_is_stored_as_before(self):
        p = proj()
        self.assertEqual(edit.add_rack_param(p, "a", 2), {"id": "r1", "name": "a", "value": 2.0})
        old = {"rack": [{"id": "r1", "name": "a", "value": 2.0, "expr": "input * 2"}]}
        self.assertEqual(rack.values(old, 0), {"a": 4.0})

    def test_wrong_values_are_refused(self):
        p = proj()
        for kind, bad in (("int", "x"), ("bool", "yes"), ("menu", "z"), ("vec2", [1.0]), ("vec3", 2),
                          ("color", [1.0]), ("text", 3), ("font", None), ("number", float("nan"))):
            made = add(p, kind)
            with self.assertRaises(edit.EditError, msg=kind):
                edit.set_rack_value(p, made["id"], bad)
            self.assertEqual(made["value"], SAMPLE[kind])
        with self.assertRaises(edit.EditError):
            edit.add_rack_param(p, "m2", kind="menu", items=["", " "])
        with self.assertRaises(edit.EditError):
            edit.add_rack_param(p, "k2", kind="image")

    def test_what_expressions_read(self):
        p = proj()
        for kind in rack.KINDS:
            add(p, kind)
        v = rack.values(p, 0)
        self.assertEqual(v["p_int"], 3)
        self.assertIs(v["p_bool"], True)
        self.assertEqual(v["p_menu"], 1)
        self.assertEqual(v["p_vec3"], [1.0, 2.0, 3.0])
        self.assertEqual(v["p_text"], "哈囉")
        self.assertEqual(v.typed["p_menu"], ("menu", "b"))
        n = edit.add_rack_param(p, "sum", 0)
        edit.set_rack_expr(p, n["id"], "p_vec2[1] + p_menu + (p_bool ? 10 : 0) + len(p_text) + p_color[0] + p_int")
        self.assertAlmostEqual(rack.values(p, 0)["sum"], 2 + 1 + 10 + 2 + 1 + 3)

    def test_expressions_and_lfos_are_for_numbers_only(self):
        p = proj()
        for kind in rack.KINDS:
            made = add(p, kind)
            if kind in rack.DRIVEN:
                edit.set_rack_expr(p, made["id"], "input + 0.4")
                self.assertEqual(rack.values(p, 0)[made["name"]], {"number": 1.9, "int": 3}[kind])
            else:
                with self.assertRaises(edit.EditError):
                    edit.set_rack_expr(p, made["id"], "1")
                with self.assertRaises(edit.EditError):
                    edit.set_rack_lfo(p, made["id"], {})

    def test_keyframes_blend_or_hold(self):
        for kind in rack.KINDS:
            p = proj()
            made = add(p, kind)
            edit.toggle_rack_key(p, made["id"], 0)
            edit.set_rack_value(p, made["id"], OTHER[kind], 2 * S)
            at = lambda t: rack.values(p, t).typed[made["name"]][1]
            self.assertEqual(at(0), SAMPLE[kind], kind)
            self.assertEqual(at(2 * S), OTHER[kind], kind)
            half = at(S)
            if kind in rack.BLENDING:
                self.assertNotIn(half, (SAMPLE[kind], OTHER[kind]), kind)
                edit.set_rack_easing(p, made["id"], 0, "ease_in")
                self.assertNotEqual(at(S), half, kind)
            else:
                self.assertEqual(half, SAMPLE[kind], kind)
                with self.assertRaises(edit.EditError):
                    edit.set_rack_easing(p, made["id"], 0, "ease_in")
            edit.toggle_rack_key(p, made["id"], 0)
            edit.toggle_rack_key(p, made["id"], 2 * S)
            self.assertEqual(made["value"], OTHER[kind], kind)

    def test_menu_choices_change(self):
        p = proj()
        made = add(p, "menu")
        edit.toggle_rack_key(p, made["id"], 0)
        edit.set_rack_value(p, made["id"], "c", S)
        edit.set_rack_items(p, made["id"], ["a", "B"])                  # (b renamed, c gone)
        self.assertEqual([k[1] for k in made["value"]["keys"]], ["B", "B"])
        with self.assertRaises(edit.EditError):
            edit.set_rack_items(p, made["id"], [])

    def test_saved_and_opened_again(self):
        p = proj()
        for kind in rack.KINDS:
            add(p, kind)
        edit.toggle_rack_key(p, "r8", 0)                                 # (the words, keyframed)
        before = rack.values(p, 0).typed
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.json")
            project.save(p, path)
            got = project.load(path)
        self.assertEqual(rack.values(got, 0).typed, before)

    def test_export_and_import_keep_the_kinds(self):
        p = proj()
        for kind in rack.KINDS:
            add(p, kind)
        edit.toggle_rack_key(p, "r7", 0)                                 # (the colour, keyframed)
        other = proj()
        self.assertEqual(edit.import_rack(other, rack.parse_import(rack.export_text(p))), len(rack.KINDS))
        self.assertEqual(rack.values(other, 0).typed, rack.values(p, 0).typed)
        broken = json.dumps({"format": rack.FORMAT, "params": [
            {"name": "v", "kind": "vec2", "value": "no"}, {"name": "w", "kind": "later", "value": 1},
            {"name": "m", "kind": "menu", "items": [], "value": 1}, {"name": "c", "kind": "color", "value": 1, "expr": "1"}]})
        got = rack.parse_import(broken)
        self.assertEqual([(d["name"], d["value"]) for d in got], [("v", [0.0, 0.0]), ("c", [1.0] * 4)])
        self.assertNotIn("expr", got[1])


class LinkTests(unittest.TestCase):
    def at(self, p, cid, t=0):
        return propexpr.at(edit.find(p, cid)[1], 0, rack.values(p, t))

    def test_words_colours_and_font_of_a_text(self):
        p, cid = text_project()
        for kind in ("text", "color", "font", "menu"):
            add(p, kind)
        for prop, name in (("content", "p_text"), ("text_color", "p_color"), ("font", "p_font"),
                           ("tc:stroke_color", "p_color"), ("tc:shadow_color", "p_color"), ("tc:bg_color", "p_color")):
            edit.set_prop_link(p, cid, prop, name)
        tx = self.at(p, cid)["text"]
        self.assertEqual(tx["content"], "哈囉")
        self.assertEqual(tx["color"], [1.0, 0.0, 0.0])
        self.assertEqual(tx["font_path"], "/fonts/a.ttf")
        for k in ("stroke_color", "shadow_color", "bg_color"):
            self.assertEqual(tx[k], [1.0, 0.0, 0.0, 1.0])
        self.assertEqual(edit.find(p, cid)[1]["text"]["content"], "自己的字")          # (the clip keeps its own)
        edit.set_prop_link(p, cid, "content", "p_menu")
        self.assertEqual(self.at(p, cid)["text"]["content"], "b")
        edit.set_prop_link(p, cid, "content", "p_color")                              # (another kind: nothing)
        self.assertEqual(self.at(p, cid)["text"]["content"], "自己的字")
        edit.set_prop_link(p, cid, "content", "")
        self.assertNotIn("content", edit.find(p, cid)[1]["links"])

    def test_current_value_makes_a_fitting_parameter(self):
        p, cid = text_project()
        c = edit.find(p, cid)[1]
        for prop, kind in (("content", "text"), ("text_color", "color"), ("font", "font"), ("tc:bg_color", "color")):
            got = racklinks.current(c, prop, 0)
            self.assertEqual(got[0], kind)
            edit.add_rack_param(p, "n_" + prop.replace(":", "_"), got[1], got[0])

    def test_a_shapes_colour_is_drawn(self):
        p = shape_project()
        add(p, "color", "tint", [0.0, 1.0, 0.0, 1.0])
        edit.set_prop_link(p, "c1", "ac:color", "tint")
        im = render.Renderer().render(dict(p), 0, 192, 108)
        self.assertEqual((im.pixelColor(96, 54).red(), im.pixelColor(96, 54).green()), (0, 255))
        edit.toggle_rack_key(p, "r1", 0)
        edit.set_rack_value(p, "r1", [0.0, 0.0, 1.0, 1.0], S)
        im = render.Renderer().render(dict(p), p["fps"], 192, 108)
        self.assertEqual((im.pixelColor(96, 54).green(), im.pixelColor(96, 54).blue()), (0, 255))

    def test_the_gpu_renderer_draws_it_too(self):
        from kiasecut import glrender
        try:
            gl = glrender.GLRenderer()
        except Exception:
            self.skipTest("no OpenGL 3.3 here")
        p = shape_project()
        add(p, "color", "tint", [0.0, 1.0, 0.0, 1.0])
        edit.set_prop_link(p, "c1", "ac:color", "tint")
        im = gl.render(dict(p), 0, 192, 108)
        self.assertEqual((im.pixelColor(96, 54).red(), im.pixelColor(96, 54).green()), (0, 255))

    def test_a_vector_component_drives_a_number(self):
        p = shape_project()
        add(p, "vec2", "at", [0.5, 0.0])
        edit.set_prop_expr(p, "c1", "transform.x", "at[0]")
        im = render.Renderer().render(dict(p), 0, 192, 108)
        self.assertEqual(im.pixelColor(144, 54).red(), 255)

    def test_a_mapping_leaves_a_vector_alone(self):
        from kiasecut import mapping
        p = shape_project()
        add(p, "vec2", "at", [0.5, 0.0])
        edit.set_prop_expr(p, "c1", "transform.x", mapping.make("linear", "at", out=(0, 5)))
        self.assertEqual(self.at(p, "c1")["transform"]["x"], edit.find(p, "c1")[1]["transform"].get("x", 0.0))

    def test_filters_switches_menus_colours_and_vectors(self):
        p = shape_project()
        found = {}
        for ref, d in ((ref, fx.get(ref)) for ref in fx.builtin_refs()):
            for q in d.params:
                if q.type in ("bool", "menu", "color", "vec2") and q.type not in found:
                    found[q.type] = (ref, q)
        self.assertTrue(found)
        for kind, (ref, q) in found.items():
            e = edit.add_effect(p, "c1", ref)
            prop = (f"fxb:{e['id']}.{q.name}" if kind == "bool" else f"fxp:{e['id']}.{q.name}")
            self.assertEqual(racklinks.kinds(edit.find(p, "c1")[1], prop), (kind,), prop)
            c = edit.find(p, "c1")[1]
            have = racklinks.current(c, prop, 0)
            self.assertEqual(have[0], kind)
            name = f"fx_{kind}"
            if kind == "menu":
                edit.add_rack_param(p, name, q.items[-1], "menu", q.items)
                want = q.items[-1]
            else:
                want = {"bool": not have[1], "color": [0.0, 1.0, 0.0, 1.0], "vec2": [0.25, 0.75]}[kind]
                edit.add_rack_param(p, name, want, kind)
            edit.set_prop_link(p, "c1", prop, name)
            got = next(x for x in self.at(p, "c1")["effects"] if x["id"] == e["id"])
            self.assertEqual(got["params"][q.name], want, kind)
            add(p, "bool", "off_" + kind, False)
            edit.set_prop_link(p, "c1", "fxon:" + e["id"], "off_" + kind)
            got = next(x for x in self.at(p, "c1")["effects"] if x["id"] == e["id"])
            self.assertTrue(got.get("disabled"))

    def test_rename_delete_and_users(self):
        p, cid = text_project()
        made = add(p, "text", "words")
        edit.set_prop_link(p, cid, "content", "words")
        self.assertEqual(rack.users(p, "words"), 1)
        edit.rename_rack_param(p, made["id"], "title")
        self.assertEqual(edit.find(p, cid)[1]["links"], {"content": "title"})
        edit.delete_rack_param(p, made["id"])
        self.assertEqual(self.at(p, cid)["text"]["content"], "自己的字")

    def test_a_linked_clip_is_not_still_and_fonts_are_counted(self):
        p, cid = text_project()
        add(p, "font", "face")
        c = edit.find(p, cid)[1]
        self.assertTrue(stillspans._own_still(c))
        edit.set_prop_link(p, cid, "font", "face")
        self.assertFalse(stillspans._own_still(edit.find(p, cid)[1]))
        self.assertIn("/fonts/a.ttf", fonts.used(p))
        static = {"static": True, "tracks": [{"clips": [edit.find(p, cid)[1]]}]}
        self.assertFalse(stillspans._compound_still(static))
        self.assertFalse(stillspans._compound_still({"static": True, "tracks": [{"clips": [{"compound": static}]}]}))
        self.assertTrue(stillspans._compound_still({"static": True, "tracks": [{"clips": [{"id": "x"}]}]}))
        edit.replace_fonts(p, {"/fonts/a.ttf": "/fonts/z.ttf"})
        self.assertEqual(rack.values(p, 0)["face"], "/fonts/z.ttf")


class PanelTests(unittest.TestCase):
    def test_a_row_of_every_kind_shows_and_reports(self):
        from kiasecut.ui.rack_panel import RackPanel
        p = proj()
        for kind in rack.KINDS:
            add(p, kind)
        w = RackPanel()
        w.set_fonts([{"name": "B", "path": "/fonts/b.ttf"}])
        got, asked = [], []
        w.action.connect(lambda rid, act, arg: got.append((rid, act, arg)))
        w.addRequested.connect(asked.append)
        w.fill(p, 0)
        rows = {r.kind: r for r in w.rows.values()}
        self.assertEqual(set(rows), set(rack.KINDS))
        self.assertEqual(rows["color"].color.text(), "#ff0000")
        self.assertEqual(rows["menu"].combo.currentText(), "b")
        self.assertEqual(rows["text"].words.toPlainText(), "哈囉")
        self.assertEqual(rows["font"].combo.currentData(), "/fonts/a.ttf")
        self.assertEqual([s.value() for s in rows["vec3"].spins], [1.0, 2.0, 3.0])
        self.assertTrue(rows["bool"].check.isChecked())
        self.assertIsNone(rows["color"].expr)
        self.assertEqual(got, [])                                                    # (showing reports nothing)
        rows["bool"].check.click()
        rows["menu"].combo.activated.emit(2)
        rows["vec2"].spins[1].edited.emit(9.0)
        rows["int"].spin.edited.emit(4.0)
        rows["text"].words.setPlainText("新的")
        rows["font"].combo.activated.emit(rows["font"].combo.findData("/fonts/b.ttf"))
        rows["color"].key.click()
        self.assertEqual([(a, v) for _r, a, v in got],
                         [("value", False), ("value", "c"), ("value", [1.0, 9.0]), ("value", 4), ("value", "新的"),
                          ("value", "/fonts/b.ttf"), ("key", None)])
        for rid, act, v in got[:-1]:
            edit.set_rack_value(p, rid, v)
        w.fill(p, 0)
        w.add_menu.actions()[1].trigger()
        self.assertEqual(asked, [list(rack.KINDS)[1]])
        self.assertEqual([a.text() for a in w.add_menu.actions()], list(rack.KINDS.values()))

    def test_fields_bound_to_a_parameter_are_outlined(self):
        from kiasecut.ui.effects_panel import EffectsPanel
        from kiasecut.ui.inspector import Inspector
        from kiasecut.ui.linkmark import outline_of
        p, cid = text_project()
        add(p, "text", "words")
        ins = Inspector()
        edit.set_prop_link(p, cid, "content", "words")
        ins.show_clips([edit.find(p, cid)[1]], 0, 60)
        field = ins.widgets["content"]
        self.assertFalse(outline_of(field).isHidden())
        self.assertIn("words", field.toolTip())
        edit.set_prop_link(p, cid, "content", "")
        ins.show_clips([edit.find(p, cid)[1]], 0, 60)
        self.assertTrue(outline_of(field).isHidden())
        self.assertNotIn("words", field.toolTip())

        p = shape_project()
        ref, q = next((ref, q) for ref in fx.builtin_refs() for q in fx.get(ref).params if q.type == "color")
        e = edit.add_effect(p, "c1", ref)
        add(p, "color", "tint")
        panel = EffectsPanel()
        offered = []
        panel.menu_extender = lambda menu, ids, prop: offered.append(prop)
        edit.set_prop_link(p, "c1", f"fxp:{e['id']}.{q.name}", "tint")
        panel.show_clips([edit.find(p, "c1")[1]], 0, 60)
        field = panel.widgets[("fx:" + e["id"], q.name)]
        self.assertFalse(outline_of(field).isHidden())
        field.customContextMenuRequested.emit(field.rect().center())
        self.assertEqual(offered, [f"fxp:{e['id']}.{q.name}"])
        edit.set_prop_link(p, "c1", f"fxp:{e['id']}.{q.name}", "")
        panel.show_clips([edit.find(p, "c1")[1]], 0, 60)
        self.assertTrue(outline_of(field).isHidden())


class WindowTests(unittest.TestCase):
    """The window's side: 新增參數 of each kind, and a field's right-click menu."""

    def setUp(self):
        from kiasecut.ui import main_window
        self.mw = main_window
        self.win = main_window.MainWindow()
        self.addCleanup(self.win.close)
        self.addCleanup(setattr, self.win, "dirty", False)
        self.win.relink = lambda pr: True
        p, self.cid = text_project()
        self.win.set_project(p)
        dialog = main_window.QInputDialog
        self.addCleanup(setattr, dialog, "getText", dialog.getText)
        self.addCleanup(setattr, dialog, "getMultiLineText", dialog.getMultiLineText)
        dialog.getText = staticmethod(lambda *a, text="", **k: (text, True))
        dialog.getMultiLineText = staticmethod(lambda *a, **k: ("甲\n乙\n\n甲", True))

    def test_add_each_kind(self):
        for kind in rack.KINDS:
            self.win.rack_panel.addRequested.emit(kind)
        ps = rack.params(self.win.proj)
        self.assertEqual([rack.kind_of(p) for p in ps], list(rack.KINDS))
        self.assertEqual(next(p for p in ps if rack.kind_of(p) == "menu")["items"], ["甲", "乙"])
        self.win.show()
        self.win.panels.show("rack")
        self.win.show_rack()
        self.assertEqual(len(self.win.rack_panel.rows), len(rack.KINDS))
        color = next(p for p in ps if rack.kind_of(p) == "color")
        self.win.rack_panel.action.emit(color["id"], "value", [0.0, 1.0, 0.0, 1.0])
        self.assertEqual(rack.find(self.win.proj, color["id"])["value"], [0.0, 1.0, 0.0, 1.0])

    def menu(self, prop):
        from PySide6.QtWidgets import QMenu
        m = QMenu()
        self.win.number_menu(m, [self.cid], prop)
        self.menus = m
        return {a.text(): a for a in m.actions() if a.text()}

    def test_bind_and_unbind_from_a_fields_menu(self):
        top = self.menu("content")
        sub = top["綁定全局參數"].menu()
        sub.actions()[0].trigger()                                       # (新增全局參數並綁定…)
        c = edit.find(self.win.container(), self.cid)[1]
        self.assertEqual(c["links"], {"content": "param1"})
        self.assertEqual(rack.values(self.win.proj, 0)["param1"], "自己的字")
        top = self.menu("content")
        top["解除全局參數「param1」"].trigger()
        self.assertNotIn("links", edit.find(self.win.container(), self.cid)[1])
        top = self.menu("content")
        fit = [a for a in top["綁定全局參數"].menu().actions() if a.text().startswith("param1")]
        fit[0].trigger()
        self.assertEqual(edit.find(self.win.container(), self.cid)[1]["links"], {"content": "param1"})

    def test_a_numbers_menu_offers_numbers_and_vector_parts(self):
        add(self.win.proj, "color", "tint")
        add(self.win.proj, "vec2", "at")
        add(self.win.proj, "int", "n")
        sub = self.menu("transform.x")["綁定全局參數"].menu()
        texts = [a.text() for a in sub.actions() if a.text()]
        self.assertIn("n", texts)
        self.assertIn("at", texts)
        self.assertNotIn("tint", texts)
        next(a for a in sub.actions() if a.text() == "at").menu().actions()[1].trigger()
        self.assertEqual(edit.find(self.win.container(), self.cid)[1]["expr"]["transform.x"], "at[1]")


if __name__ == "__main__":
    unittest.main()
