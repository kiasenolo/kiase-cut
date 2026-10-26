"""Pictures dragged onto image pickers: an image mask's picture, a component clip's picture
parameter, and (in the 參數 list) a picture parameter's default."""
import os
import shutil
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import assets, edit  # noqa: E402
from kiasecut.ui.inspector import Inspector  # noqa: E402
from kiasecut.ui.main_window import MainWindow  # noqa: E402
from kiasecut.ui.params import ParamList  # noqa: E402
from kiasecut.ui.timeline import MEDIA_MIME  # noqa: E402
from test_edit import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


def files(*paths):
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(p) for p in paths])
    return md


def media(*ids):
    md = QMimeData()
    md.setData(MEDIA_MIME, ",".join(ids).encode("utf-8"))
    return md


def drop(widget, md, pos=None):
    """Drag md onto widget and let go at pos (its middle); whether it was taken."""
    pos = QPointF(widget.rect().center()) if pos is None else QPointF(pos)
    enter = QDragEnterEvent(pos.toPoint(), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(widget, enter)
    if not enter.isAccepted():
        return False
    e = QDropEvent(pos, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(widget, e)
    return e.isAccepted()


class PictureDropTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.png = os.path.join(self.dir, "g.png")
        im = QImage(40, 20, QImage.Format_ARGB32)
        im.fill(QColor("#00ff00"))
        im.save(self.png)
        self.txt = os.path.join(self.dir, "notes.txt")
        open(self.txt, "w").close()
        p = proj()
        p["tracks"][0]["clips"] = p["tracks"][0]["clips"][:1]
        a = assets.make(assets.get("shape.rect"), "#ff0000", "#000000", 1920, 1080)
        edit.replace_media(p, "c1", assets.item(a, "/nowhere.svg"), a)
        clip = edit.make_compound(p, p, ["c1"], 0, static=True, component=True)
        self.p, self.cid, self.kid = p, clip["id"], clip["compound_id"]
        self.comp = p["compounds"][self.kid]
        self.pic = edit.add_param(p, self.kid, "image", "圖", [("c1", "source")])
        self.vis = edit.add_param(p, self.kid, "visible", "顯示", [("c1", "visible")])
        self.lib = {"folders": [], "items": [{"id": "m1", "kind": "image", "path": self.png, "name": "g.png"},
                                             {"id": "m2", "kind": "audio", "path": "/x/a.wav", "name": "a.wav"}]}
        self.picture_of = lambda md: MainWindow.dropped_picture(self.host(), md)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def host(self):
        return types.SimpleNamespace(proj={"library": self.lib}, ulib=None)

    def test_what_a_drag_carries(self):
        self.assertEqual(self.picture_of(files(self.png)), self.png)
        self.assertEqual(self.picture_of(files(self.txt, self.png)), self.png)        # the first picture
        self.assertIsNone(self.picture_of(files(self.txt)))
        self.assertEqual(self.picture_of(media("m1")), self.png)                     # the media library's
        self.assertIsNone(self.picture_of(media("m2")))                              # a sound
        self.assertIsNone(self.picture_of(media("nope")))

    def test_params_list_drop_sets_the_default(self):
        box = ParamList()
        box.resize(300, 200)
        box.picture_of = self.picture_of
        box.set_component(self.comp)
        got = []
        box.defaultDropped.connect(lambda pid, path: got.append((pid, path)))
        view = box.list.viewport()
        at = lambda i: box.list.visualItemRect(box.list.item(i)).center()
        self.assertTrue(drop(view, media("m1"), at(0)))
        self.assertEqual(got, [(self.pic["id"], self.png)])
        self.assertFalse(drop(view, files(self.png), at(1)))                         # not a picture parameter
        self.assertFalse(drop(view, files(self.txt), at(0)))                         # not a picture
        self.assertEqual(len(got), 1)
        edit.set_param_default(self.p, self.kid, got[0][0], got[0][1])
        self.assertEqual(edit.find(self.comp, "c1")[1]["media"]["path"], self.png)

    def test_component_clip_picture(self):
        ins = Inspector()
        ins.picture_of = self.picture_of
        ins.show_clips([edit.find(self.p, self.cid)[1]], 0, 30)
        got = []
        ins.paramEdited.connect(lambda ids, group, key, v: got.append((ids, group, key, v)))
        w = ins.widgets[("params", self.pic["id"])]
        self.assertTrue(drop(w, files(self.png)))
        self.assertEqual(got, [([self.cid], "params", self.pic["id"], self.png)])
        self.assertFalse(drop(w, files(self.txt)))
        self.assertEqual(len(got), 1)

    def test_image_mask_picture(self):
        p = proj()
        edit.set_mask(p, "c1", "image")
        ins = Inspector(part="mask")
        ins.picture_of = self.picture_of
        ins.show_clips([edit.find(p, "c1")[1]], 0, 30)
        got = []
        ins.maskImageChosen.connect(lambda ids, path: got.append((ids, path)))
        self.assertTrue(drop(ins.widgets["mask_image"], media("m1")))
        self.assertEqual(got, [(["c1"], self.png)])


if __name__ == "__main__":
    unittest.main()
