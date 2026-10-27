"""Letter keys on menu items (刪除(E), 上移(U), 下移(D), 重新命名(R) ...) and F2 (rename what
has the focus, else the selected clip or track)."""
import os
import re
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QTreeWidgetItem  # noqa: E402

from kiasecut.ui import menukeys  # noqa: E402
from kiasecut.ui.library import ROLE_ID, LibraryPanel  # noqa: E402
from kiasecut.ui.main_window import MainWindow  # noqa: E402

APP = QApplication.instance() or QApplication([])
TRACK = ["選取軌道上的所有片段", "重新命名軌道…", "軌道顏色…", "預設顏色", "軌道音量…", "上移", "下移",
         "新增影片軌道", "新增文字軌道", "新增音訊軌道", "刪除 2 條軌道", "清除空軌道"]


def keyed(labels):
    m = menukeys.Menu()
    acts = [m.addAction(t) for t in labels]
    menukeys.apply(m)
    return m, acts


def key_of(text):
    k = re.search(r"\(&(.)\)", text)
    return k and k.group(1)


class MenuKeyTests(unittest.TestCase):
    def test_track_menu(self):
        _m, acts = keyed(TRACK)
        keys = {a.text().split("(")[0]: key_of(a.text()) for a in acts}
        self.assertEqual((keys["刪除 2 條軌道"], keys["上移"], keys["下移"], keys["重新命名軌道"]), ("E", "U", "D", "R"))
        self.assertEqual(acts[1].text(), "重新命名軌道(&R)…")             # before the …
        got = [key_of(a.text()) for a in acts]
        self.assertTrue(all(got))
        self.assertEqual(len(set(got)), len(got))                        # each letter once

    def test_once_and_names_left_alone(self):
        m, acts = keyed(["刪除", "高斯模糊", "R&D"])
        menukeys.apply(m)                                                # (opened again)
        self.assertEqual([a.text() for a in acts], ["刪除(&E)", "高斯模糊", "R&D"])

    def test_letter_picks_the_item(self):
        m, acts = keyed(TRACK)
        hit = []
        acts[-2].triggered.connect(lambda: hit.append("delete"))
        QTimer.singleShot(50, lambda: QTest.keyClick(m, Qt.Key_E))
        QTimer.singleShot(500, m.close)                                  # (in case it does not)
        m.exec(QPoint(10, 10))
        self.assertEqual(hit, ["delete"])


class F2Tests(unittest.TestCase):
    def win(self, selected=None, tracks=()):
        seen = []
        tl = SimpleNamespace(selected=selected, selected_tracks=set(tracks))
        w = SimpleNamespace(proj={"tracks": []}, timeline=tl,
                            on_clip_action=lambda a, cid: seen.append(("clip", a, cid)),
                            on_track_action=lambda a, tid: seen.append(("track", a, tid)),
                            statusBar=lambda: SimpleNamespace(showMessage=lambda *a: seen.append(a[0])))
        return w, seen

    def test_selected_clip_then_track(self):
        w, seen = self.win({"id": "c1"})
        MainWindow.do_rename(w)
        w2, seen2 = self.win(None, ["t3"])
        MainWindow.do_rename(w2)
        self.assertEqual((seen, seen2), ([("clip", "rename", "c1")], [("track", "rename", "t3")]))

    def test_focused_list_first(self):
        lib = LibraryPanel()
        it = QTreeWidgetItem(["a.mp4"])
        it.setData(0, ROLE_ID, "m7")
        lib.tree.addTopLevelItem(it)
        lib.show()
        QTest.qWaitForWindowExposed(lib)
        names = []
        lib.renameRequested.connect(names.append)
        w, seen = self.win({"id": "c1"})
        lib.tree.setFocus()
        MainWindow.do_rename(w)                          # nothing picked in the list: the clip
        lib.tree.setCurrentItem(it)
        lib.tree.setFocus()
        MainWindow.do_rename(w)
        lib.close()
        self.assertEqual((names, seen), (["m7"], [("clip", "rename", "c1")]))


if __name__ == "__main__":
    unittest.main()
