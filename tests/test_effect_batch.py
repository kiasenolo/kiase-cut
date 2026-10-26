"""Effects of several selected clips (批量): when they are the same filters in the same order the
panel edits them all together (a value they do not share shows as --); when not, 新增效果
replaces all their effects with the new one."""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox  # noqa: E402

from kiasecut import edit  # noqa: E402
from kiasecut.ui.effects_panel import EffectsPanel  # noqa: E402
from kiasecut.ui.main_window import MainWindow  # noqa: E402
from kiasecut.ui.vfx_panel import FX_MIME, effect_mime  # noqa: E402
from test_edit import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


def chain(p, cid):
    return [e["filter"] for e in edit.find(p, cid)[1].get("effects") or []]


def effects(p, cid):
    return edit.find(p, cid)[1].get("effects") or []


class EffectBatchTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.names = []
        self.panel = EffectsPanel()

    def host(self):
        p = self.p
        h = types.SimpleNamespace(container=lambda: p, clip_time=lambda cid: 0,
                                  apply=lambda name, fn, *a, merge=None: (self.names.append(name), fn(p, *a)))
        for name in ("add_effects_to", "fx_targets", "fx_each", "on_fx_param_edited", "effect_dropped",
                     "effects_dropped", "on_backdrop_chosen"):
            setattr(h, name, getattr(MainWindow, name).__get__(h))
        return h

    def show(self, *ids):
        self.panel.show_clips([edit.find(self.p, cid)[1] for cid in ids], 0, 30)

    def alike(self):
        """c1 and c2 both with blur then invert, blur's radius 10 and 20."""
        for cid, r in (("c1", 10.0), ("c2", 20.0)):
            for ref in ("builtin:blur", "builtin:invert"):
                edit.add_effect(self.p, cid, ref)
            edit.set_param(self.p, cid, "fx:" + effects(self.p, cid)[0]["id"], "radius", r)

    def test_add_for_a_multi_selection(self):
        got = []
        self.panel.addRequested.connect(lambda ids, ref: got.append((ids, ref)))
        self.show("c1", "c2", "c3")                                         # c3 is a sound
        self.assertTrue(self.panel.add_btn.isEnabled())
        self.assertEqual(self.panel.targets(), ["c1", "c2"])
        self.panel._add("builtin:blur")
        self.assertEqual(got, [(["c1", "c2"], "builtin:blur")])
        self.show("c3")
        self.assertFalse(self.panel.add_btn.isEnabled())
        host = self.host()
        host.add_effects_to(["c1", "c2"], ["builtin:blur", "builtin:invert"])     # alike (none): added
        host.add_effects_to(["c1", "c2"], ["builtin:sharpen"])
        self.assertEqual(chain(self.p, "c1"), ["builtin:blur", "builtin:invert", "builtin:sharpen"])
        self.assertEqual(chain(self.p, "c2"), chain(self.p, "c1"))
        self.assertNotEqual(effects(self.p, "c1")[0]["id"], effects(self.p, "c2")[0]["id"])
        self.assertEqual(self.names, ["新增效果（2 個片段）"] * 2)

    def test_not_alike_add_replaces_them(self):
        edit.add_effect(self.p, "c1", "builtin:blur")
        edit.add_effect(self.p, "c1", "builtin:invert")
        edit.add_effect(self.p, "c2", "builtin:invert")
        edit.add_effect(self.p, "c2", "builtin:blur")                       # the same, another order
        self.show("c1", "c2")
        self.assertIsNone(self.panel.clip)                                  # no form, just the note
        self.assertTrue(self.panel.add_btn.isEnabled())
        self.host().add_effects_to(["c1", "c2"], ["builtin:sharpen"])
        self.assertEqual(chain(self.p, "c1"), ["builtin:sharpen"])
        self.assertEqual(chain(self.p, "c2"), ["builtin:sharpen"])
        self.assertEqual(self.names, ["覆寫效果（2 個片段）"])

    def test_alike_values_edited_together(self):
        self.alike()
        self.show("c1", "c2")
        blur = effects(self.p, "c1")[0]["id"]
        spin = self.panel.widgets[("fx:" + blur, "radius")]
        self.assertTrue(spin.mixed)                                         # 10 and 20: --
        got = []
        self.panel.paramEdited.connect(lambda *a: got.append(a))
        self.panel._queue("fx:" + blur, "radius", 5.0)
        self.panel._flush()
        self.assertEqual(got, [(["c1", "c2"], "fx:" + blur, "radius", 5.0)])
        self.host().on_fx_param_edited(*got[0])
        self.assertEqual([effects(self.p, c)[0]["params"]["radius"] for c in ("c1", "c2")], [5.0, 5.0])
        self.assertEqual(self.names, ["調整效果（2 個片段）"])
        self.show("c1", "c2")
        self.assertFalse(spin.mixed)
        self.assertEqual(spin.value(), 5.0)

    def test_switch_and_order_together(self):
        self.alike()
        inv2 = effects(self.p, "c2")[1]["id"]
        edit.set_effect_enabled(self.p, "c2", inv2, False)                  # on in c1, off in c2
        self.show("c1", "c2")
        inv = effects(self.p, "c1")[1]["id"]
        got = []
        self.panel.enabledChosen.connect(lambda *a: got.append(a))
        on = self.panel.boxes[1].findChildren(QCheckBox)[0]
        self.assertEqual(on.checkState(), Qt.PartiallyChecked)
        on.click()                                                          # half: all on
        self.assertEqual(got, [(["c1", "c2"], inv, True)])
        host = self.host()
        host.fx_each("啟用效果", *got[0][:2], lambda lvl, cid, e: edit.set_effect_enabled(lvl, cid, e, True))
        self.assertFalse(effects(self.p, "c2")[1].get("disabled"))
        payload = bytes(effect_mime(effects(self.p, "c1")[1], "c1").data(FX_MIME)).decode()
        host.effect_dropped(["c1", "c2"], payload, 0)                       # invert to the front, in both
        self.assertEqual(chain(self.p, "c1"), ["builtin:invert", "builtin:blur"])
        self.assertEqual(chain(self.p, "c2"), ["builtin:invert", "builtin:blur"])
        host.effect_dropped(["c1", "c2"], "builtin:sharpen", 1)             # from the VFX tab, in both
        self.assertEqual(chain(self.p, "c2"), ["builtin:invert", "builtin:sharpen", "builtin:blur"])

    def test_range_only_when_every_clip_has_one(self):
        self.alike()
        blur = effects(self.p, "c1")[0]["id"]
        edit.set_effect_mask(self.p, "c1", blur, "circle")
        self.show("c1", "c2")
        w = self.panel.widgets
        self.assertEqual(w[("fxmask:" + blur, "kind")].currentIndex(), -1)  # circle and none
        self.assertNotIn(("fxmask:" + blur, "cx"), w)
        self.assertNotIn(("mask_edit", blur), w)
        edit.set_effect_mask(self.p, "c2", effects(self.p, "c2")[0]["id"], "rectangle")
        self.show("c1", "c2")
        self.assertIn(("fxmask:" + blur, "cx"), self.panel.widgets)
        self.assertNotIn(("mask_edit", blur), self.panel.widgets)          # (the preview drags one clip's)

    def test_dropped_in_the_panel_when_not_alike(self):
        edit.add_effect(self.p, "c1", "builtin:blur")
        blur = effects(self.p, "c1")[0]
        edit.set_param(self.p, "c1", "fx:" + blur["id"], "radius", 42.0)
        edit.add_effect(self.p, "c2", "builtin:invert")
        self.panel.resize(360, 600)
        self.panel.show()
        self.show("c1", "c2")
        APP.processEvents()
        got = []
        self.panel.effectsDropped.connect(lambda ids, payload: got.append((ids, payload)))
        md = effect_mime(blur, "c1")
        pos = QPointF(20, 60)
        enter = QDragEnterEvent(pos.toPoint(), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(self.panel, enter)
        self.assertTrue(enter.isAccepted())
        QApplication.sendEvent(self.panel, QDropEvent(pos, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
        self.assertEqual(got[0][0], ["c1", "c2"])
        self.host().effects_dropped(*got[0])
        self.assertEqual(chain(self.p, "c1"), ["builtin:blur"])
        self.assertEqual(chain(self.p, "c2"), ["builtin:blur"])
        self.assertEqual(effects(self.p, "c2")[0]["params"]["radius"], 42.0)
        self.assertEqual(self.names, ["覆寫效果（2 個片段）"])
        self.panel.hide()


if __name__ == "__main__":
    unittest.main()
