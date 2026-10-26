"""The static compound editor's layers: listed top first, restacked one per track, each
keeping its own track's switches; sound stays below."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kiasecut import edit  # noqa: E402
from test_edit import S, clip, proj  # noqa: E402


class LayerTests(unittest.TestCase):
    def test_order(self):
        p = proj()                                             # t0: c1, c2; t1 empty; audio
        p["tracks"][1]["clips"].append(clip("c4", 0, S))
        p["tracks"][1]["hidden"] = True
        tracks = p["tracks"]
        self.assertEqual([c["id"] for c in edit.layers(p)], ["c4", "c1", "c2"])
        edit.set_layer_order(p, ["c2", "c4", "c1"])
        self.assertIs(p["tracks"], tracks)                      # (the same list: the timeline's)
        self.assertEqual([c["id"] for c in edit.layers(p)], ["c2", "c4", "c1"])
        self.assertTrue(all(len(t["clips"]) == 1 for t in p["tracks"]))
        self.assertTrue(next(t for t in p["tracks"] if t["clips"][0]["id"] == "c4").get("hidden"))
        self.assertEqual(p["tracks"][-1]["kind"], "audio")
        self.assertEqual(len({t["id"] for t in p["tracks"]}), len(p["tracks"]))
        with self.assertRaises(edit.EditError):
            edit.set_layer_order(p, ["c2", "c4"])               # every layer, or none


if __name__ == "__main__":
    unittest.main()


class LayerDropTests(unittest.TestCase):
    """Media dropped on the layer list become layers where they were dropped (one undo step)."""

    def setUp(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])

    def level(self):
        p = proj()
        p["tracks"][1]["clips"].append(clip("c4", 0, S))
        edit.set_layer_order(p, ["c4", "c1", "c2"])
        return p

    def test_list_reports_where(self):
        from PySide6.QtCore import QMimeData, QPointF, Qt
        from PySide6.QtGui import QDropEvent
        from kiasecut.ui.layers import LayerPanel
        from kiasecut.ui.timeline import FX_MIME, MEDIA_MIME
        panel = LayerPanel()
        panel.resize(300, 300)
        panel.show()
        p = self.level()
        panel.set_layers(p, set(), None)
        got = []
        panel.mediaDropped.connect(lambda ids, paths, at: got.append((ids, paths, at)))
        panel.fxDropped.connect(lambda ref, cid, at: got.append((ref, cid, at)))
        lst = panel.list

        def drop(md, row, low):
            r = lst.visualItemRect(lst.item(row))
            pos = QPointF(r.center().x(), r.bottom() - 2 if low else r.top() + 2)
            lst.dropEvent(QDropEvent(pos, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
        md = QMimeData()
        md.setData(MEDIA_MIME, b"m1,m2")
        drop(md, 0, low=True)                                        # below the top layer
        fx = QMimeData()
        fx.setData(FX_MIME, "builtin:blur".encode())
        drop(fx, 2, low=False)
        self.assertEqual(got, [(["m1", "m2"], [], 1), ("builtin:blur", "c2", 2)])

    def test_new_layers_go_where_dropped(self):
        from types import SimpleNamespace
        from kiasecut import library
        from kiasecut.ui.main_window import MainWindow
        p = self.level()
        h = edit.History(p)
        it = {"id": "m9", "name": "n.png", "path": "n.png", "kind": "image", "width": 10, "height": 10,
              "folder": None}
        win = SimpleNamespace(proj=p, layer_drop_at=None, container=lambda *_: p, editing_static=lambda: True)

        def place_media(ident, track_id, start):                     # as the window does it
            h.do("加入素材", lambda q: library.place_item(q, it, track_id or None, start))
            MainWindow._place_dropped_layers(win)
        win.place_media = place_media
        MainWindow.layer_drop(win, ["m9"], [], 2)
        order = [c["id"] for c in edit.layers(p)]
        self.assertEqual(order[:2], ["c4", "c1"])
        self.assertEqual(edit.find(p, order[2])[1]["media"]["path"], "n.png")
        self.assertEqual(order[3:], ["c2"])
        self.assertIsNone(win.layer_drop_at)
        self.assertEqual(len(h.undo_stack), 1)
        h.undo()
        self.assertEqual([c["id"] for c in edit.layers(p)], ["c4", "c1", "c2"])
        h.redo()
        self.assertEqual(len(edit.layers(p)), 4)
        self.assertEqual(edit.layers(p)[2]["media"]["path"], "n.png")    # (redone in its place)
