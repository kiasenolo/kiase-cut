"""Several media library items dragged onto the timeline together: picked with Shift / Ctrl,
dragged in list order, stacked on tracks of their own by default, one after another with Alt;
one undo step either way."""
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
from PySide6.QtWidgets import QAbstractItemView, QApplication  # noqa: E402

from kiasecut import edit, library  # noqa: E402
from kiasecut.ui.library import MIME, LibraryPanel  # noqa: E402
from kiasecut.ui.main_window import MainWindow  # noqa: E402
from kiasecut.ui.timeline import HEADER_W, MEDIA_MIME, US, Timeline  # noqa: E402
from test_edit import S, clip, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


def items():
    return [{"id": "ma", "name": "a.mp4", "path": "a.mp4", "kind": "video", "width": 1920, "height": 1080,
             "duration_us": 3 * S, "folder": None},
            {"id": "mb", "name": "b.png", "path": "b.png", "kind": "image", "width": 640, "height": 480,
             "folder": None},
            {"id": "mc", "name": "c.mp4", "path": "c.mp4", "kind": "video", "width": 1920, "height": 1080,
             "duration_us": 4 * S, "folder": None}]


def where(p, clips):
    return [(edit.find(p, c["id"])[0]["id"], c["start_us"]) for c in clips]


class PlaceItemsTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()                 # t0: c1 0-2 s, c2 5-7 s; t1 empty; t2 audio 2-6 s

    def test_stacked_by_default(self):
        cs = library.place_items(self.p, items(), "t1", 10 * S)
        self.assertEqual([c["start_us"] for c in cs], [10 * S] * 3)          # all at the same time
        rows = [self.p["tracks"].index(edit.find(self.p, c["id"])[0]) for c in cs]
        self.assertEqual(rows, sorted(rows))                                 # going up a layer each
        self.assertEqual(len(set(rows)), 3)
        self.assertEqual(rows[0], 1)                                         # the first on the dropped track
        self.assertEqual(self.p["tracks"][-1]["kind"], "audio")             # new picture tracks stay above the audio

    def test_stacked_uses_free_tracks_above(self):
        cs = library.place_items(self.p, items()[:2], "t0", 0)               # t0 is taken at 0: nearest gap
        self.assertEqual(where(self.p, cs), [("t0", 2 * S), ("t1", 2 * S)])

    def test_stacked_skips_taken_and_locked_tracks(self):
        self.p["tracks"][1]["clips"].append(clip("k", 9 * S, 2 * S))        # t1 busy at 10 s
        self.p["tracks"].insert(2, {"id": "tl", "kind": "video", "name": "l", "locked": True, "clips": []})
        self.p["tracks"].insert(3, {"id": "tf", "kind": "video", "name": "f", "clips": []})
        cs = library.place_items(self.p, items()[:2], "t0", 10 * S)
        self.assertEqual(where(self.p, cs), [("t0", 10 * S), ("tf", 10 * S)])

    def test_across_with_alt(self):
        cs = library.place_items(self.p, items(), "t1", 1 * S, across=True)
        self.assertEqual(where(self.p, cs), [("t1", 1 * S), ("t1", 4 * S), ("t1", 9 * S)])

    def test_sounds_stack_downwards(self):
        snd = [{"id": f"m{i}", "name": f"{i}.mp3", "path": f"{i}.mp3", "kind": "audio", "duration_us": 2 * S,
                "folder": None} for i in range(2)]
        cs = library.place_items(self.p, snd, "t2", 7 * S)
        self.assertEqual(where(self.p, cs)[0], ("t2", 7 * S))
        self.assertEqual(self.p["tracks"].index(edit.find(self.p, cs[1]["id"])[0]), len(self.p["tracks"]) - 1)

    def test_one_undo_step(self):
        h = edit.History(self.p)
        before = [len(t["clips"]) for t in self.p["tracks"]]
        h.do("加入素材", library.place_items, items(), "t1", 10 * S)
        self.assertEqual(len(h.undo_stack), 1)
        h.undo()
        self.assertEqual([len(t["clips"]) for t in self.p["tracks"]], before)

    def test_one_item_is_a_plain_place(self):
        cs = library.place_items(self.p, items()[:1], "t1", 3 * S)
        self.assertEqual(where(self.p, cs), [("t1", 3 * S)])


class LibrarySelectionTests(unittest.TestCase):
    def test_shift_ctrl_select_and_list_order(self):
        panel = LibraryPanel()
        panel.set_library({"folders": [], "items": items()})
        tree = panel.tree
        self.assertEqual(tree.selectionMode(), QAbstractItemView.ExtendedSelection)
        nodes = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]   # a, b, c by name
        md = tree.mimeData([nodes[2], nodes[0]])                                 # picked c first
        self.assertEqual(bytes(md.data(MIME)).decode(), "ma,mc")


class TimelineDropTests(unittest.TestCase):
    def setUp(self):
        self.p = proj()
        self.tl = Timeline()
        self.tl.resize(1200, 400)
        self.tl.set_project(self.p)
        self.tl.px_per_s, self.tl.scroll_s = 50.0, 0.0
        self.tl._layout()
        self.got, self.single, self.replaced = [], [], []
        self.tl.mediaManyDropped.connect(lambda *a: self.got.append(a))
        self.tl.mediaDropped.connect(lambda *a: self.single.append(a))
        self.tl.replaceDropped.connect(lambda *a: self.replaced.append(a))

    def drop(self, ids, sec, mods=Qt.KeyboardModifier.NoModifier):
        md = QMimeData()
        md.setData(MEDIA_MIME, ids.encode())
        row = next(i for i, t in enumerate(self.tl.rows) if t["id"] == "t0")
        pos = QPointF(HEADER_W + sec * self.tl.px_per_s, self.tl.tops[row] + 10)
        self.tl.dropEvent(QDropEvent(pos, Qt.CopyAction, md, Qt.MouseButton.LeftButton, mods))

    def test_several_go_as_one_drop(self):
        self.drop("ma,mb", 10)
        self.assertEqual(self.got, [(["ma", "mb"], "t0", 10 * US, False)])
        self.assertEqual(self.single, [])

    def test_alt_lines_them_up_instead_of_replacing(self):
        self.drop("ma,mb", 1, Qt.KeyboardModifier.AltModifier)                  # over clip c1
        self.assertEqual(self.got, [(["ma", "mb"], "t0", 1 * US, True)])
        self.assertEqual(self.replaced, [])

    def test_one_item_with_alt_still_replaces(self):
        self.drop("ma", 1, Qt.KeyboardModifier.AltModifier)
        self.assertEqual(self.replaced, [("ma", "c1")])
        self.assertEqual(self.got, [])

    def drop_files(self, names, mods=Qt.KeyboardModifier.NoModifier):
        files = []
        self.tl.filesDropped.connect(lambda *a: files.append(a))
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(os.path.abspath(n)) for n in names])
        row = next(i for i, t in enumerate(self.tl.rows) if t["id"] == "t1")
        pos = QPointF(HEADER_W + 10 * self.tl.px_per_s, self.tl.tops[row] + 10)
        self.tl.dropEvent(QDropEvent(pos, Qt.CopyAction, md, Qt.MouseButton.LeftButton, mods))
        return files

    def test_files_from_the_file_manager_carry_alt(self):
        self.assertEqual(self.drop_files(["a.png", "b.png"])[0][1:], ("t1", 10 * US, False))
        self.assertEqual(self.drop_files(["a.png", "b.png"], Qt.KeyboardModifier.AltModifier)[0][1:],
                         ("t1", 10 * US, True))


class FileManagerDropTests(unittest.TestCase):
    """Files dragged in from the file manager: linked where they are, then laid out like library items."""
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.src = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.src, True)
        self.files = []
        for name in ("a.png", "b.png", "c.png"):
            path = os.path.join(self.src, name)
            Image.new("RGB", (8, 8)).save(path)
            self.files.append(path)
        self.p = proj()
        self.h = edit.History(self.p)
        self.selected = []
        self.win = SimpleNamespace(
            ensure_project=lambda: True, root=self.root, proj=self.p, fs_epoch=0,
            statusBar=lambda: mock.MagicMock(), library=mock.MagicMock(), panels=mock.MagicMock(),
            ulpanel=mock.MagicMock(), refresh_library=lambda: None, request_sync=lambda delay=0: None, container=lambda root=None: root or self.p,
            run_task=lambda work, done, err, prog: done(work(lambda _p: None)),
            apply_root=lambda label, fn, *a, select=None: self.h.do(label, fn, *a),
            _select_new=lambda clips: self.selected.append([c["id"] for c in clips]))

    def placed(self):
        out = []
        for t in self.p["tracks"]:
            out += [(t["id"], c["name"], c["start_us"]) for c in t["clips"] if c["name"].endswith(".png")]
        return sorted(out, key=lambda x: x[1])

    def import_(self, across):
        MainWindow.import_files(self.win, self.files, None, ("t1", 10 * S, across))

    def test_stacked_by_default(self):
        self.import_(False)
        got = self.placed()
        self.assertEqual([s for _t, _n, s in got], [10 * S] * 3)
        self.assertEqual(len({t for t, _n, _s in got}), 3)
        self.assertEqual(got[0][0], "t1")
        self.assertEqual(len(self.selected[0]), 3)                      # all of them end up selected
        self.assertEqual(len(self.h.undo_stack), 1)
        self.h.undo()
        self.assertEqual(self.placed(), [])

    def test_across_with_alt(self):
        self.import_(True)
        d = library.IMAGE_DEFAULT_US
        self.assertEqual(self.placed(), [("t1", "a.png", 10 * S), ("t1", "b.png", 10 * S + d),
                                         ("t1", "c.png", 10 * S + 2 * d)])

    def test_files_stay_where_they_are(self):
        self.import_(False)
        paths = sorted(it["path"] for it in library.lib(self.p)["items"])
        self.assertEqual(paths, sorted(library.norm(f) for f in self.files))
        self.assertFalse(os.path.exists(os.path.join(self.root, "Media")))         # nothing copied
        self.import_(False)                                                        # no second item
        self.assertEqual(len(library.lib(self.p)["items"]), 3)

    def test_files_already_in_the_library(self):
        its = [{"id": f"mu{i}", "name": os.path.basename(f), "path": library.norm(f), "kind": "image",
                "width": 8, "height": 8, "folder": None} for i, f in enumerate(self.files)]
        self.win.ulib = SimpleNamespace(root=self.src, item_for_path=lambda f: its[self.files.index(f)])
        MainWindow.ul_use_files(self.win, self.files, ("t1", 10 * S, True))
        self.assertEqual([t for t, _n, _s in self.placed()], ["t1"] * 3)
        MainWindow.ul_use_files(self.win, self.files, ("t1", 30 * S, False))
        self.assertEqual(len({t for t, _n, s in self.placed() if s == 30 * S}), 3)
        self.assertEqual(len(self.h.undo_stack), 2)


if __name__ == "__main__":
    unittest.main()
