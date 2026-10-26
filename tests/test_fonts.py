"""Font map (字體對應): fonts a project names that this system lacks, their stand-ins per
operating system, guessing one, drawing with it, and the 字體對應 window."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, fonts, textlayout  # noqa: E402
from test_edit import S, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
GONE = "C:/Windows/Fonts/surely-not-here.ttc"


def some_font():
    """An installed font file that draws at 20 px, or None."""
    from PIL import ImageFont
    for d in fonts.font_dirs():
        for base, _, names in os.walk(d):
            for n in sorted(names):
                if n.lower().endswith((".ttf", ".otf")):
                    path = os.path.join(base, n).replace("\\", "/")
                    try:
                        ImageFont.truetype(path, 20)
                        return path
                    except OSError:
                        continue
    return None


def with_text(font_path, styles=None):
    p = proj()
    c = edit.add_text(p, 0, "字")
    c["text"]["font_path"] = font_path
    if styles:
        c["text"]["styles"] = styles
    return p, c


class FontMapTests(unittest.TestCase):
    def tearDown(self):
        fonts.use_map({})

    def test_resolve(self):
        here = some_font()
        if here is None:
            self.skipTest("no font files on this computer")
        self.assertEqual(fonts.resolve(GONE), GONE)                  # no stand-in: as it is
        fonts.use_map({GONE.replace("/", "\\"): here})               # either slash
        self.assertEqual(fonts.resolve(GONE), here)
        self.assertEqual(fonts.resolve(GONE.replace("/", "\\")), here)
        self.assertEqual(fonts.resolve(here), here)                 # present fonts are used as they are
        self.assertIn(here, fonts.map_key())
        self.assertEqual(textlayout.font(GONE, 20).path.replace("\\", "/"), here)   # drawn with it

    def test_used_and_missing(self):
        here = some_font() or __file__
        p, c = with_text(GONE, styles=[{"start": 0, "end": 1, "font_path": "D:/a.ttf"}])
        c["text"]["font_path"] = {"keys": [[0, GONE, 0, 0, 0, 0], [S // 2, here, 0, 0, 0, 0]]}
        self.assertEqual(fonts.used(p), {GONE, "D:/a.ttf", here})
        self.assertEqual(fonts.missing(p, {}), sorted([GONE, "D:/a.ttf"]))
        self.assertEqual(fonts.missing(p, {GONE: here}), ["D:/a.ttf"])
        self.assertEqual(fonts.missing(p, {GONE: "/also/gone.ttf"}), sorted([GONE, "D:/a.ttf"]))

    def test_guess(self):
        installed = [{"path": "/f/NotoSansCJK-Regular.ttc", "name": "Noto Sans CJK TC"},
                     {"path": "/f/msjh.ttc", "name": "Microsoft JhengHei"},
                     {"path": "/f/DejaVuSans.ttf", "name": "DejaVu Sans"}]
        self.assertEqual(fonts.guess("C:/Windows/Fonts/msjh.ttc", installed), "/f/msjh.ttc")     # same file
        self.assertEqual(fonts.guess("C:/x/dejavu-sans-bold.ttf", installed), "/f/DejaVuSans.ttf")
        self.assertEqual(fonts.guess("C:/x/msjh.ttc", installed, {"C:/x/msjh.ttc": "/f/DejaVuSans.ttf"}),
                         "/f/DejaVuSans.ttf")                       # chosen before on this computer
        self.assertIsNone(fonts.guess("C:/x/zzz.ttf", installed))
        noto = [{"path": "/f/NotoSansCJK-Regular.ttc", "name": "Noto Sans CJK JP"},
                {"path": "/f/NotoSansCJKtc.ttc", "name": "Noto Sans CJK TC"}]
        self.assertEqual(fonts.guess("C:/Windows/Fonts/msjh.ttc", noto), "/f/NotoSansCJKtc.ttc")   # its usual stand-in

    def test_not_undone(self):
        p, _ = with_text(GONE)
        h = edit.History(p)
        p["font_map"] = {fonts.os_key(): {GONE: "/x.ttf"}}
        h.do("move", edit.move, "c1", S)
        h.undo()
        self.assertEqual(p["font_map"], {fonts.os_key(): {GONE: "/x.ttf"}})

    def test_dialog(self):
        from kiasecut.ui.font_dialog import FontMapDialog
        installed = [{"path": "/f/a.ttf", "name": "Alpha"}, {"path": "/f/b.ttf", "name": "Beta Sans"}]
        dlg = FontMapDialog(None, [(GONE, "/f/b.ttf", "gone"), ("D:/c.ttf", None, "gone")], installed)
        self.assertFalse(dlg.isModal())
        self.assertEqual(dlg.choices(), {GONE: "/f/b.ttf", "D:/c.ttf": None})
        box = dlg.boxes["D:/c.ttf"]
        box.setEditText("alpha")                                    # typed, any case
        got = []
        dlg.applied.connect(got.append)
        dlg.replaced.connect(got.append)
        dlg._apply()
        self.assertEqual(got, [{GONE: "/f/b.ttf", "D:/c.ttf": "/f/a.ttf"}])

    def test_dialog_lists_fonts_that_are_here(self):
        from kiasecut.ui.font_dialog import FontMapDialog
        installed = [{"path": "/f/a.ttf", "name": "Alpha"}, {"path": "/f/b.ttf", "name": "Beta Sans"}]
        dlg = FontMapDialog(None, [(GONE, "/f/b.ttf", "mapped"), ("/f/a.ttf", None, "here")], installed,
                            {"/f/a.ttf": 3})
        box = dlg.boxes["/f/a.ttf"]
        self.assertEqual(box.findData("/f/a.ttf"), -1)              # (not swapped for itself)
        self.assertEqual(dlg.swaps(), {})                           # (不變) by default
        box.setEditText("beta sans")
        stand_ins, swaps = [], []
        dlg.applied.connect(stand_ins.append)
        dlg.replaced.connect(swaps.append)
        dlg._apply()
        self.assertEqual(stand_ins, [{GONE: "/f/b.ttf"}])
        self.assertEqual(swaps, [{"/f/a.ttf": "/f/b.ttf"}])

    def test_replace_fonts(self):
        p, c = with_text("/f/a.ttf", styles=[{"start": 0, "end": 1, "font_path": "C:\\f\\x.ttf"}])
        k = edit.add_text(p, 5 * S, "鍵")
        k["text"]["font_path"] = {"keys": [[0, "/f/a.ttf", 0, 0, 0, 0], [S, "/f/z.ttf", 0, 0, 0, 0]]}
        self.assertEqual(fonts.usage(p), {"/f/a.ttf": 2, "C:/f/x.ttf": 1, "/f/z.ttf": 1})
        h = edit.History(p)
        n = h.do("更換字體", edit.replace_fonts, {"/f/a.ttf": "/f/b.ttf", "C:/f/x.ttf": "/f/y.ttf"})
        self.assertEqual(n, 2)
        self.assertEqual(fonts.used(p), {"/f/b.ttf", "/f/y.ttf", "/f/z.ttf"})
        h.undo()
        self.assertEqual(fonts.used(p), {"/f/a.ttf", "C:/f/x.ttf", "/f/z.ttf"})
        with self.assertRaises(edit.EditError):
            edit.replace_fonts(p, {"/f/none.ttf": "/f/b.ttf"})

if __name__ == "__main__":
    unittest.main()
