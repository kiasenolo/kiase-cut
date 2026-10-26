"""Components (元件): compounds - live or static - whose clips' words, colours, pictures and
visibility are parameters each clip showing one sets for itself, keyframes included."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import assets, components, curves, edit, glrender, project, render, renderexport  # noqa: E402
from test_edit import S, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
RED, BLUE = [1.0, 0.0, 0.0, 1.0], [0.0, 0.0, 1.0, 1.0]


class ComponentTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        p = proj()
        p["tracks"][0]["clips"] = p["tracks"][0]["clips"][:1]
        a = assets.make(assets.get("shape.rect"), "#ff0000", "#000000", 1920, 1080)
        a.update(w=1920, h=1080)                           # the whole picture
        edit.replace_media(p, "c1", assets.item(a, "/nowhere.svg"), a)
        clip = edit.make_compound(p, p, ["c1"], 0, static=True, component=True)
        self.p, self.cid, self.kid = p, clip["id"], clip["compound_id"]
        self.comp = p["compounds"][self.kid]

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def colour(self, frame=0, x=96, renderer=None):
        view = dict(self.p, tracks=self.p["tracks"])
        im = (renderer or render.Renderer()).render(view, frame, 192, 108)
        return im.pixelColor(x, 54)

    def test_made_as_a_component(self):
        self.assertTrue(components.is_component(self.comp))
        self.assertTrue(self.comp["name"].startswith("靜態元件"))
        self.assertTrue(project.is_static(edit.find(self.p, self.cid)[1]))

    def test_instance_colour_and_default(self):
        pr = edit.add_param(self.p, self.kid, "color", "主色", [("c1", "color")])
        self.assertEqual(components.default(self.comp, pr)[:3], [1.0, 0.0, 0.0])
        self.assertEqual(self.colour().name(), "#ff0000")
        edit.set_param(self.p, self.cid, "params", pr["id"], BLUE)
        self.assertEqual(self.colour().name(), "#0000ff")
        self.assertEqual(curves.value(self.comp["tracks"][0]["clips"][0]["asset"]["color"], 0)[:3],
                         [1.0, 0.0, 0.0])                  # the component itself is left alone
        edit.reset_params(self.p, self.cid)
        self.assertEqual(self.colour().name(), "#ff0000")

    def test_gpu_draws_the_instance(self):
        try:
            gpu_ = glrender.GLRenderer()
            gpu_.render(dict(self.p, tracks=self.p["tracks"]), 0, 16, 16)
        except Exception as exc:                            # (no OpenGL 3.3 here)
            self.skipTest(f"no OpenGL: {exc}")
        pr = edit.add_param(self.p, self.kid, "color", "主色", [("c1", "color")])
        edit.set_param(self.p, self.cid, "params", pr["id"], BLUE)
        self.assertEqual(self.colour(renderer=gpu_).name(), "#0000ff")

    def test_instance_values_animate(self):
        pr = edit.add_param(self.p, self.kid, "color", "主色", [("c1", "color")])
        edit.toggle_key(self.p, self.cid, "params", pr["id"], 0)
        edit.set_param(self.p, self.cid, "params", pr["id"], BLUE, S)
        c = edit.find(self.p, self.cid)[1]
        self.assertEqual(curves.value(c["params"][pr["id"]], 0)[:3], [1.0, 0.0, 0.0])
        self.assertIn(S, edit.key_times(c))
        fps = self.p["fps"]
        self.assertEqual(self.colour(0).name(), "#ff0000")
        self.assertEqual(self.colour(round(fps)).name(), "#0000ff")

    def test_visible_and_one_param_per_property(self):
        pv = edit.add_param(self.p, self.kid, "visible", "顯示方塊", [("c1", "visible")])
        edit.set_param(self.p, self.cid, "params", pv["id"], False)
        self.assertEqual(self.colour().name(), "#000000")
        p1 = edit.add_param(self.p, self.kid, "color", "a", [("c1", "color")])
        p2 = edit.add_param(self.p, self.kid, "color", "b", [("c1", "color")])
        self.assertEqual(p1["binds"], [])
        self.assertEqual(p2["binds"], [["c1", "color"]])
        with self.assertRaises(edit.EditError):
            edit.add_param(self.p, self.kid, "text", "字", [("c1", "color")])     # not words

    def test_text_and_picture(self):
        txt = {"id": "tx", "type": "text", "name": "", "start_us": 0, "duration_us": S,
               "text": {"content": "原本", "size": 5.0, "color": [1, 1, 1]},
               "transform": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}}
        self.comp["tracks"].append({"id": "tt", "kind": "text", "name": "t", "clips": [txt]})
        pt = edit.add_param(self.p, self.kid, "text", "標題", [("tx", "content")])
        pi = edit.add_param(self.p, self.kid, "image", "圖", [("c1", "source")])
        png = os.path.join(self.dir, "g.png")
        im = QImage(40, 20, QImage.Format_ARGB32)
        im.fill(QColor("#00ff00"))
        im.save(png)
        edit.set_param(self.p, self.cid, "params", pt["id"], "新的字")
        edit.set_param(self.p, self.cid, "params", pi["id"], png)
        c = edit.find(self.p, self.cid)[1]
        got = components.content(c, 0)
        index = components.layer_index(got)
        self.assertEqual(index["tx"][1]["text"]["content"], "新的字")
        self.assertEqual(index["c1"][1]["media"], {"path": png, "width": 40, "height": 20})
        self.assertNotIn("asset", index["c1"][1])
        self.assertEqual(self.comp["tracks"][1]["clips"][0]["text"]["content"], "原本")
        self.assertEqual(self.colour(x=10).name(), "#00ff00")              # (beside the words)

    def test_saved_paths_and_round_trip(self):
        pi = edit.add_param(self.p, self.kid, "image", "圖", [("c1", "source")])
        png = os.path.join(self.dir, "media", "g.png")
        os.makedirs(os.path.dirname(png))
        QImage(4, 4, QImage.Format_ARGB32).save(png)
        edit.set_param(self.p, self.cid, "params", pi["id"], png)
        path = os.path.join(self.dir, "x.kiasecut.json")
        project.save(self.p, path)
        with open(path, encoding="utf-8") as fh:
            stored = json.load(fh)
        clip = next(c for t in stored["timelines"][0]["tracks"] for c in t["clips"] if c["id"] == self.cid)
        self.assertEqual(clip["params"][pi["id"]], "media/g.png")
        back = project.load(path)
        c = edit.find(back, self.cid)[1]
        self.assertEqual(os.path.normpath(c["params"][pi["id"]]), os.path.normpath(png))

    def test_defaults_set_and_params_deleted(self):
        pr = edit.add_param(self.p, self.kid, "color", "主色", [("c1", "color")])
        edit.set_param(self.p, self.cid, "params", pr["id"], BLUE)
        edit.set_param_default(self.p, self.kid, pr["id"], [0.0, 1.0, 0.0, 1.0])
        self.assertEqual(components.default(self.comp, pr)[:3], [0.0, 1.0, 0.0])
        edit.delete_param(self.p, self.kid, pr["id"])
        self.assertNotIn("params", edit.find(self.p, self.cid)[1])
        self.assertEqual(self.colour().name(), "#00ff00")

    def test_back_to_static(self):
        pr = edit.add_param(self.p, self.kid, "color", "主色", [("c1", "color")])
        edit.set_param(self.p, self.cid, "params", pr["id"], BLUE)
        edit.unmake_component(self.p, self.kid)
        self.assertFalse(components.is_component(self.comp))
        self.assertNotIn("params", edit.find(self.p, self.cid)[1])
        edit.make_component(self.p, self.kid)
        self.assertTrue(components.is_component(self.comp))


class LiveComponentTests(unittest.TestCase):
    """A live component (not static): played like any compound, its clips set at any time."""

    def setUp(self):
        p = proj()
        p["tracks"][0]["clips"] = p["tracks"][0]["clips"][:1]
        a = assets.make(assets.get("shape.rect"), "#ff0000", "#000000", 1920, 1080)
        a.update(w=1920, h=1080)
        edit.replace_media(p, "c1", assets.item(a, "/nowhere.svg"), a)
        clip = edit.make_compound(p, p, ["c1"], component=True)
        self.p, self.cid, self.kid = p, clip["id"], clip["compound_id"]
        self.comp = p["compounds"][self.kid]

    def colour(self, frame=0):
        view = dict(self.p, tracks=self.p["tracks"])
        return render.Renderer().render(view, frame, 192, 108).pixelColor(96, 54).name()

    def test_live_instance(self):
        self.assertTrue(components.is_component(self.comp))
        self.assertFalse(self.comp.get("static"))
        self.assertTrue(self.comp["name"].startswith("元件"))
        self.assertFalse(project.is_static(edit.find(self.p, self.cid)[1]))
        pr = edit.add_param(self.p, self.kid, "color", "主色", [("c1", "color")])
        self.assertFalse(renderexport.needs_renderer(self.p))
        edit.set_param(self.p, self.cid, "params", pr["id"], BLUE)
        self.assertEqual(self.colour(), "#0000ff")
        self.assertTrue(renderexport.needs_renderer(self.p))     # (MLT would show the component's own)

    def test_shown_on_a_hidden_track(self):
        c2 = dict(edit.find(self.comp, "c1")[1], id="c9", start_us=S)
        tr = self.comp["tracks"][0]
        tr["clips"].append(c2)
        tr["hidden"] = True
        pv = edit.add_param(self.p, self.kid, "visible", "顯示", [("c1", "visible")])
        with self.assertRaises(edit.EditError):                 # (the default would hide c9 too)
            edit.set_param_default(self.p, self.kid, pv["id"], True)
        edit.set_param(self.p, self.cid, "params", pv["id"], True)
        got = components.content(edit.find(self.p, self.cid)[1], 0)["tracks"]
        self.assertEqual([([c["id"] for c in t["clips"]], bool(t.get("hidden"))) for t in got[:2]],
                         [(["c9"], True), (["c1"], False)])

    def test_any_compound_converts(self):
        edit.unmake_component(self.p, self.kid)
        self.assertFalse(components.is_component(self.comp))
        edit.make_component(self.p, self.kid)
        self.assertTrue(components.is_component(self.comp))
        with self.assertRaises(edit.EditError):
            edit.make_component(self.p, "tl1")                   # (a timeline is not one)

    def test_timeline_menu(self):
        from PySide6.QtWidgets import QMenu
        from kiasecut.ui.timeline import Timeline
        tl = Timeline()
        view = {"width": 1920, "height": 1080, "fps": 60.0, "duration_us": 2 * S, "tracks": self.comp["tracks"],
                "compounds": self.p["compounds"], "open_component": self.comp}
        tl.set_project(view)
        edit.add_param(self.p, self.kid, "color", "主色", [("c1", "color")])
        self.assertIn("c1", tl._bound())
        got = []
        tl.paramBind.connect(lambda *a: got.append(a))
        from kiasecut.ui.params import param_menu
        menu = QMenu()
        param_menu(menu, self.comp, [self.comp["tracks"][0]["clips"][0]], tl.paramBind.emit, tl.paramUnbind.emit)
        next(a for a in menu.actions()[0].menu().actions() if a.text() == "新參數：外框顏色").trigger()
        self.assertEqual(got, [("", "stroke_color", ["c1"])])


class ComponentUiTests(unittest.TestCase):
    """The layer panel's 參數 and 設為參數, the inspector's 元件參數."""

    def setUp(self):
        t = ComponentTests("test_made_as_a_component")
        t.setUp()
        self.addCleanup(t.tearDown)
        self.p, self.cid, self.kid, self.comp = t.p, t.cid, t.kid, t.comp
        self.pr = edit.add_param(self.p, self.kid, "color", "主色", [("c1", "color")])

    def test_layer_panel(self):
        from PySide6.QtWidgets import QMenu
        from kiasecut.ui.layers import LayerPanel
        panel = LayerPanel()
        panel.set_layers(self.comp, set(), None)
        self.assertFalse(panel.params_box.isHidden())
        self.assertTrue(panel.to_component.isHidden())
        self.assertIn("主色", panel.params.item(0).text())
        got = []
        panel.paramBind.connect(lambda pid, prop, ids: got.append((pid, prop, ids)))
        panel.paramUnbind.connect(got.append)
        menu = QMenu()
        from kiasecut.ui.params import param_menu
        param_menu(menu, self.comp, [self.comp["tracks"][0]["clips"][0]], panel.paramBind.emit, panel.paramUnbind.emit)
        sub = {a.text(): a for a in menu.actions()}
        bind = {a.text(): a for a in sub["設為參數"].menu().actions()}
        self.assertIn("新參數：填充顏色", bind)
        bind["　交給「主色」：外框顏色"].trigger()
        sub["解除參數"].menu().actions()[0].trigger()
        self.assertEqual(got, [(self.pr["id"], "stroke_color", ["c1"]), [("c1", "color")]])
        edit.unmake_component(self.p, self.kid)
        panel.set_layers(self.comp, set(), None)
        self.assertTrue(panel.params_box.isHidden())
        self.assertFalse(panel.to_component.isHidden())

    def test_inspector(self):
        from kiasecut.ui.inspector import Inspector
        ins = Inspector()
        got = []
        ins.paramEdited.connect(lambda ids, g, k, v: got.append((ids, g, k, v)))
        c = edit.find(self.p, self.cid)[1]
        ins.show_clips([c], 0, 60)
        self.assertEqual(ins.widgets["類型"].text(), "靜態元件")
        self.assertEqual(ins.widgets[("params", self.pr["id"])].text(), "#ff0000")
        self.assertFalse(ins.widgets[("reset", self.pr["id"])].isEnabled())
        ins._queue("params", self.pr["id"], BLUE)
        ins._flush()
        self.assertEqual(got, [([self.cid], "params", self.pr["id"], BLUE)])
        edit.set_param(self.p, self.cid, "params", self.pr["id"], BLUE)
        ins.show_clips([c], 0, 60)
        self.assertEqual(ins.widgets[("params", self.pr["id"])].text(), "#0000ff")
        self.assertTrue(ins.widgets[("reset", self.pr["id"])].isEnabled())


if __name__ == "__main__":
    unittest.main()
