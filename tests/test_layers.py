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


class GroupLayerTests(unittest.TestCase):
    """Groups in the layer list: opened in place, restacked inside, their mask marked."""

    def setUp(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        self.p = proj()
        self.p["tracks"][1]["clips"].append(clip("c4", 0, S))
        self.p["tracks"].insert(2, {"id": "t5", "kind": "video", "name": "v5", "clips": [clip("c5", 0, S)]})
        self.g = edit.make_group(self.p, self.p, ["c4", "c5"])

    def test_restack_inside_a_group(self):
        self.assertEqual(edit.layer_parent(self.p, "c5"), self.g["id"])
        self.assertIsNone(edit.layer_parent(self.p, self.g["id"]))
        self.assertEqual([c["id"] for c in edit.layers(self.g)], ["c5", "c4"])
        outer = [t["id"] for t in self.p["tracks"]]
        edit.set_layer_order(self.p, ["c4", "c5"], self.g["id"])
        self.assertEqual([c["id"] for c in edit.layers(self.g)], ["c4", "c5"])
        self.assertEqual([t["id"] for t in self.p["tracks"]], outer)               # the level is left alone
        with self.assertRaises(edit.EditError):
            edit.set_layer_order(self.p, ["c4"], self.g["id"])

    def test_list_opens_groups(self):
        from kiasecut.ui.layers import PARENT, LayerPanel, LayerRow
        from PySide6.QtWidgets import QLabel
        panel = LayerPanel()
        panel.set_layers(self.p, set(), None)
        rows = lambda: [panel.list.item(i).data(0x0100) for i in range(panel.list.count())]
        self.assertNotIn("c5", rows())
        panel.toggle_group(self.g["id"])                                          # ▸
        self.assertEqual(rows()[rows().index(self.g["id"]) + 1:][:2], ["c5", "c4"])
        self.assertEqual(panel.list.orders()[self.g["id"]], ["c5", "c4"])
        self.assertEqual(panel.list.item(rows().index("c5")).data(PARENT), self.g["id"])
        self.assertEqual(panel.list.orders()[""], [c["id"] for c in edit.layers(self.p)])
        edit.set_group_matte(self.p, self.g["id"], on=True)                       # the bottom one is the mask
        panel.set_layers(self.p, set(), None)
        marks = lambda cid: [w.text() for w in panel.list.itemWidget(panel.list.item(rows().index(cid)))
                             .findChildren(QLabel)]
        self.assertIn("遮罩", marks("c4"))
        self.assertNotIn("遮罩", marks("c5"))
        edit.set_group_matte(self.p, self.g["id"], invert=True)
        panel.set_layers(self.p, set(), None)
        self.assertIn("反轉遮罩", marks("c4"))
        self.assertIsInstance(panel.list.itemWidget(panel.list.item(0)), LayerRow)

    def test_menu_toggles_group_matte(self):
        from types import SimpleNamespace
        from kiasecut.ui.main_window import MainWindow
        h = edit.History(self.p)
        win = SimpleNamespace(container=lambda *_: self.p,
                              apply=lambda label, fn: h.do(label, fn))
        MainWindow.toggle_group_matte(win, [self.g["id"], "c1"])
        self.assertTrue(self.g["matte"]["on"])
        MainWindow.toggle_group_matte(win, [self.g["id"]], "invert")
        self.assertTrue(self.g["matte"]["invert"])
        MainWindow.toggle_group_matte(win, [self.g["id"]])
        self.assertFalse(edit.find(self.p, self.g["id"])[1]["matte"]["on"])

    def test_thumbnail(self):
        from types import SimpleNamespace
        from kiasecut import assets
        from kiasecut.ui.main_window import MainWindow
        p = proj()
        params = dict(assets.make(assets.get("shape.circle"), "#ff0000", "", 1920, 1080), w=1080, h=1080)
        c = {"id": "a1", "type": "image", "name": "圓形", "start_us": 0, "duration_us": S, "source_start_us": 0,
             "asset": params, "media": {"path": "nothere.svg", "width": 1080, "height": 1080},
             "transform": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}}
        win = SimpleNamespace(proj=p, devicePixelRatioF=lambda: 1.0, _thumb_video=lambda *a: None)
        level = {"width": 1920, "height": 1080, "tracks": []}
        pix = MainWindow.layer_thumb(win, c, level)
        img = pix.toImage()
        self.assertEqual((img.width(), img.height()), (46, 26))
        self.assertEqual(img.pixelColor(23, 13).name(), "#ff0000")                # the shape, in the middle
        self.assertNotEqual(img.pixelColor(2, 2).name(), "#ff0000")               # the checkerboard around it
        self.assertIs(MainWindow.layer_thumb(win, c, level), pix)                 # kept


class PreviewDropTests(unittest.TestCase):
    def test_drop_on_the_picture(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from types import SimpleNamespace
        from PySide6.QtCore import QMimeData, QPointF, Qt
        from PySide6.QtGui import QDropEvent
        from PySide6.QtWidgets import QApplication
        from kiasecut import library
        from kiasecut.ui.main_window import MainWindow
        from kiasecut.ui.preview import Preview
        from kiasecut.ui.timeline import MEDIA_MIME
        QApplication.instance() or QApplication([])
        p = proj()
        pv = Preview()
        pv.resize(960, 540)
        pv.set_scene(p, 0, None)
        got = []
        pv.mediaDropped.connect(lambda ids, paths, x, y: got.append((ids, x, y)))
        md = QMimeData()
        md.setData(MEDIA_MIME, b"m9")
        r = pv._rect()
        at = QPointF(r.x() + r.width() * 0.75, r.y() + r.height() * 0.25)       # right, up
        pv.dropEvent(QDropEvent(at, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
        self.assertEqual(got, [])                                                 # only while a static compound is open
        pv.accept_media = True
        pv.dropEvent(QDropEvent(at, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
        self.assertEqual(got[0][0], ["m9"])
        self.assertAlmostEqual(got[0][1], 0.5, places=2)
        self.assertAlmostEqual(got[0][2], 0.5, places=2)
        h = edit.History(p)
        it = {"id": "m9", "name": "n.png", "path": "n.png", "kind": "image", "width": 10, "height": 10, "folder": None}
        win = SimpleNamespace(proj=p, layer_drop_at=None, container=lambda *_: p, editing_static=lambda: True)

        def place_media(ident, track_id, start):
            h.do("加入素材", lambda q: library.place_item(q, it, track_id or None, start))
            MainWindow._place_dropped_layers(win)
        win.place_media = place_media
        MainWindow.layer_drop(win, ["m9"], [], 0, (got[0][1], got[0][2]))
        top = edit.layers(p)[0]
        self.assertEqual(top["media"]["path"], "n.png")                           # the top layer,
        self.assertEqual((top["transform"]["x"], top["transform"]["y"]), (got[0][1], got[0][2]))  # centred there
        self.assertEqual(len(h.undo_stack), 1)


class GroupInspectorTests(unittest.TestCase):
    def test_invert_shows_once_the_mask_is_on(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from kiasecut.ui.inspector import Inspector
        QApplication.instance() or QApplication([])
        p = proj()
        g = edit.make_group(p, p, ["c1"])
        ins = Inspector()
        ins.resize(400, 900)
        ins.show()
        got = []
        ins.groupMatteChosen.connect(lambda ids, on, show, invert: got.append((on, show, invert)))
        ins.show_clips([g], 0, 30)
        shown = lambda key: ins._group_form.isRowVisible(ins.widgets[key])
        self.assertTrue(shown("group_matte"))
        self.assertFalse(shown("group_invert"))                              # the mask is off: not offered
        self.assertFalse(shown("group_show"))
        edit.set_group_matte(p, g["id"], on=True)
        ins.show_clips([g], 0, 30)
        self.assertTrue(shown("group_invert"))
        self.assertFalse(ins.widgets["group_invert"].isChecked())
        ins.widgets["group_invert"].click()
        self.assertEqual(got, [(None, None, True)])
