"""Effects dragged by their ⠿ grip: to another place in the clip's chain, or onto other clips
(a copy with its settings) or an empty spot (a filter clip of it)."""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit  # noqa: E402
from kiasecut.ui.effects_panel import EffectsPanel  # noqa: E402
from kiasecut.ui.main_window import MainWindow  # noqa: E402
from kiasecut.ui.vfx_panel import FX_MIME, dropped_fx, effect_mime  # noqa: E402
from test_edit import S, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


def chain(p, cid):
    return [e["filter"] for e in edit.find(p, cid)[1].get("effects") or []]


class EffectDragTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        for ref in ("builtin:blur", "builtin:invert", "builtin:sharpen"):
            edit.add_effect(self.p, "c1", ref)
        self.blur = edit.find(self.p, "c1")[1]["effects"][0]
        edit.set_param(self.p, "c1", "fx:" + self.blur["id"], "radius", 42.0)
        edit.set_effect_mask(self.p, "c1", self.blur["id"], "circle")

    def host(self):
        p = self.p
        return types.SimpleNamespace(container=lambda: p, apply=lambda _name, fn, *a: fn(p, *a))

    def test_move_effect_to(self):
        ids = [e["id"] for e in edit.find(self.p, "c1")[1]["effects"]]
        edit.move_effect_to(self.p, "c1", ids[0], 3)                        # to the end
        self.assertEqual(chain(self.p, "c1"), ["builtin:invert", "builtin:sharpen", "builtin:blur"])
        edit.move_effect_to(self.p, "c1", ids[2], 0)                        # to the front
        self.assertEqual(chain(self.p, "c1"), ["builtin:sharpen", "builtin:invert", "builtin:blur"])

    def test_copied_with_its_settings(self):
        payload = bytes(effect_mime(self.blur, "c1").data(FX_MIME)).decode("utf-8")
        ref, e, src = dropped_fx(payload)
        self.assertEqual((ref, src), ("builtin:blur", "c1"))
        self.assertEqual(dropped_fx("builtin:blur"), ("builtin:blur", None, None))
        got = edit.put_effect(self.p, "c2", e)
        self.assertNotEqual(got["id"], self.blur["id"])                     # an effect of its own
        self.assertEqual(got["params"]["radius"], 42.0)
        self.assertEqual(got["mask"]["kind"], "circle")
        got["params"]["radius"] = 1.0
        self.assertEqual(self.blur["params"]["radius"], 42.0)               # (not shared)
        edit.put_effect(self.p, "c2", "builtin:invert", 0)                  # a filter at its defaults, in front
        self.assertEqual(chain(self.p, "c2"), ["builtin:invert", "builtin:blur"])
        fc = edit.add_filter_clip(self.p, "builtin:blur", 8 * S, effect=e)  # onto an empty spot
        self.assertEqual(fc["effects"][0]["params"]["radius"], 42.0)

    def test_dropped_in_the_panel(self):
        panel = EffectsPanel()
        panel.resize(360, 1400)
        panel.show()
        panel.show_clips([edit.find(self.p, "c1")[1]], 0, 30)
        APP.processEvents()
        got = []
        panel.effectDropped.connect(lambda cid, payload, i: got.append((cid, payload, i)))
        payload = panel._drag_mime(self.blur["id"])
        self.assertEqual(dropped_fx(bytes(payload.data(FX_MIME)).decode())[1]["params"]["radius"], 42.0)
        boxes = panel.boxes
        self.assertEqual(len(boxes), 3)

        def drop_at(box, frac):
            y = box.mapTo(panel, box.rect().topLeft()).y() + box.height() * frac
            pos = QPointF(20, y)
            enter = QDragEnterEvent(pos.toPoint(), Qt.CopyAction, payload, Qt.LeftButton, Qt.NoModifier)
            QApplication.sendEvent(panel, enter)
            self.assertTrue(enter.isAccepted())
            QApplication.sendEvent(panel, QDropEvent(pos, Qt.CopyAction, payload, Qt.LeftButton, Qt.NoModifier))
            return got[-1][2]
        self.assertEqual(drop_at(boxes[2], 0.8), 3)                         # below the last one
        self.assertEqual(drop_at(boxes[1], 0.2), 1)                         # above the second one
        self.assertEqual(got[-1][0], "c1")
        # what the main window does with them
        host = self.host()
        MainWindow.effect_dropped(host, "c1", got[0][1], 3)
        self.assertEqual(chain(self.p, "c1"), ["builtin:invert", "builtin:sharpen", "builtin:blur"])
        MainWindow.effect_dropped(host, "c1", got[0][1], 3)                 # where it is: nothing
        self.assertEqual(len(chain(self.p, "c1")), 3)
        MainWindow.effect_dropped(host, "c2", got[0][1], 0)                 # another clip's list: a copy
        self.assertEqual(chain(self.p, "c2"), ["builtin:blur"])
        MainWindow.effect_dropped(host, "c2", "builtin:invert", 0)          # from the VFX tab
        self.assertEqual(chain(self.p, "c2"), ["builtin:invert", "builtin:blur"])
        panel.hide()


if __name__ == "__main__":
    unittest.main()
