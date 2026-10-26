"""Alt-drop of a filter (or an effect) onto an effect: it takes that effect's place, keeping its
values when the parameters line up (as many, of the same kinds, in the same order)."""
import os
import shutil
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPointF, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDropEvent  # noqa: E402

from kiasecut import edit  # noqa: E402
from kiasecut.ui.effects_panel import EffectsPanel  # noqa: E402
from kiasecut.ui.main_window import MainWindow  # noqa: E402
from kiasecut.ui.vfx_panel import FX_MIME, effect_mime  # noqa: E402
from test_edit import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
LENS = "builtin:blender_lens_distortion"


def effect_of(p, cid, i=0):
    return edit.find(p, cid)[1]["effects"][i]


class EffectSwapTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.p = proj()
        # an effect of a Library filter whose file is gone (Blender's exported Lens Distortion)
        e = edit.put_effect(self.p, "c1", "builtin:invert")
        e.update(filter=os.path.join(self.dir, "gone", "Lens Distortion.glsl"), disabled=True,
                 mask={"kind": "circle"},
                 params={"IN_Type_m": "Radial", "IN_Distortion": {"keys": [[0, 0.1, 0, 0, 0, 0], [500000, 0.4, 0, 0, 0, 0]]},
                         "IN_Dispersion": 0.25, "IN_Jitter_b": True, "IN_Fit_b": False})
        self.eid = e["id"]

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def filter_file(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + "\nvec4 effect(vec2 uv) { return src(uv); }\n")
        return path

    def test_lined_up_values_kept(self):
        self.assertTrue(edit.swap_filter(self.p, "c1", self.eid, LENS))
        e = effect_of(self.p, "c1")
        self.assertEqual((e["id"], e["filter"], e.get("disabled"), e["mask"]), (self.eid, LENS, True, {"kind": "circle"}))
        self.assertEqual(list(e["params"]), ["mode", "distortion", "dispersion", "jitter", "fit"])
        self.assertEqual(e["params"]["distortion"]["keys"][1][1], 0.4)             # keyframes too
        self.assertEqual((e["params"]["dispersion"], e["params"]["jitter"], e["params"]["fit"]), (0.25, True, False))
        self.assertEqual(e["params"]["mode"], "放射")             # its file gone: a choice not in the new menu, the default

    def test_menu_choice_by_place(self):
        old = self.filter_file("old.glsl", '// @param kind menu A "A|B|C"\n// @param n int 2 0 9')
        new = self.filter_file("new.glsl", '// @param shape menu X "X|Y|Z"\n// @param count float 1 0 9')
        e = edit.put_effect(self.p, "c2", old)
        e["params"] = {"kind": {"keys": [[0, "B", 0, 0, 0, 0], [9, "C", 0, 0, 0, 0]]}, "n": 4}
        self.assertTrue(edit.swap_filter(self.p, "c2", e["id"], new))
        self.assertEqual([k[1] for k in e["params"]["shape"]["keys"]], ["Y", "Z"])
        self.assertEqual(e["params"]["count"], 4)
        back = edit.swap_filter(self.p, "c2", e["id"], old)                       # float -> int: rounded
        self.assertTrue(back)
        self.assertEqual(e["params"]["kind"]["keys"][0][1], "B")

    def test_not_lined_up(self):
        self.assertFalse(edit.swap_filter(self.p, "c1", self.eid, "builtin:blur"))     # one parameter, not five
        e = effect_of(self.p, "c1")
        self.assertEqual((e["filter"], e["params"], e["mask"]), ("builtin:blur", {"radius": 10.0}, {"kind": "circle"}))
        bool_first = self.filter_file("b.glsl", '// @param on bool true\n' + "\n".join(
            f"// @param p{i} float 0" for i in range(4)))
        e2 = edit.put_effect(self.p, "c2", LENS)
        self.assertFalse(edit.swap_filter(self.p, "c2", e2["id"], bool_first))         # menu vs bool: not alike

    def test_dropped_effect_settings_when_not_lined_up(self):
        blur = edit.put_effect(self.p, "c2", "builtin:blur")
        blur["params"]["radius"] = 33.0
        self.assertFalse(edit.swap_filter(self.p, "c1", self.eid, blur))
        self.assertEqual(effect_of(self.p, "c1")["params"], {"radius": 33.0})

    def test_alt_drop_in_the_panel(self):
        edit.put_effect(self.p, "c1", "builtin:sharpen")
        panel = EffectsPanel()
        panel.resize(360, 1400)
        panel.show()
        panel.show_clips([edit.find(self.p, "c1")[1]], 0, 30)
        APP.processEvents()
        swapped, dropped = [], []
        panel.effectSwapped.connect(lambda ids, eid, payload: swapped.append((ids, eid, payload)))
        panel.effectDropped.connect(lambda ids, payload, i: dropped.append(i))
        md = QMimeData()
        md.setData(FX_MIME, LENS.encode())

        def drop(box, mods):
            pos = QPointF(20, box.mapTo(panel, box.rect().topLeft()).y() + box.height() * 0.3)
            enter = QDragEnterEvent(pos.toPoint(), Qt.CopyAction, md, Qt.LeftButton, mods)
            QApplication.sendEvent(panel, enter)
            self.assertTrue(enter.isAccepted())
            if mods & Qt.AltModifier:
                self.assertTrue(panel.swap_frame.isVisible())
            QApplication.sendEvent(panel, QDropEvent(pos, Qt.CopyAction, md, Qt.LeftButton, mods))
        drop(panel.boxes[0], Qt.AltModifier)
        self.assertEqual(swapped, [(["c1"], self.eid, LENS)])
        self.assertFalse(panel.swap_frame.isVisible())
        drop(panel.boxes[0], Qt.NoModifier)                                       # no Alt: put before it
        self.assertEqual(dropped, [0])
        # what the main window does with it: the alike effect of every clip (批量)
        p = self.p
        e2 = edit.put_effect(p, "c2", dict(effect_of(p, "c1"), params=dict(effect_of(p, "c1")["params"])))
        status = types.SimpleNamespace(showMessage=lambda *a: None)
        host = types.SimpleNamespace(container=lambda: p, apply=lambda _name, fn, *a: fn(p, *a),
                                     statusBar=lambda: status)
        host.fx_each = MainWindow.fx_each.__get__(host)
        host.fx_targets = MainWindow.fx_targets.__get__(host)
        MainWindow.effect_swapped(host, ["c1", "c2"], self.eid, LENS)
        self.assertEqual((effect_of(p, "c1")["filter"], e2["filter"]), (LENS, LENS))
        self.assertEqual(e2["params"]["dispersion"], 0.25)
        payload = bytes(effect_mime(effect_of(p, "c1"), "c1").data(FX_MIME)).decode()
        MainWindow.effect_swapped(host, ["c1"], self.eid, payload)                 # onto itself: nothing
        self.assertEqual(effect_of(p, "c1")["filter"], LENS)
        panel.hide()


if __name__ == "__main__":
    unittest.main()
