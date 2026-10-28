"""參考 (reference) tracks: shown and heard while their level is edited (the editor's preview),
left out of exports and of the compounds and timelines that use them; set from the track's
right-click menu, the selected tracks together."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from kiasecut import audiomix, edit, project, render  # noqa: E402
from test_edit import S, clip, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
W, H = 64, 36


def red_png(folder):
    im = QImage(160, 90, QImage.Format_ARGB32_Premultiplied)
    p = QPainter(im)
    p.fillRect(QRectF(0, 0, 160, 90), QColor("#ff0000"))
    p.end()
    path = os.path.join(folder, "red.png")
    im.save(path)
    return path


def red_at_centre(view):
    img = render.Renderer().render(view, 15, W, H)
    return img.pixelColor(W // 2, H // 2).red() > 200


class ModelTests(unittest.TestCase):
    def test_flag_present_visible_sounds(self):
        p = proj()
        edit.set_track_flag(p, "t0", "reference", True)
        edit.set_track_flag(p, "t2", "reference", True)
        t0, t2 = edit.track_by_id(p, "t0"), edit.track_by_id(p, "t2")
        self.assertFalse(project.visible(t0))                            # an export's view
        self.assertEqual(project.sounds(t2, p["tracks"]), 0.0)
        level = project.level_tracks(dict(p, editing=True))              # the editor's preview
        self.assertTrue(project.visible(t0, level))
        self.assertEqual(project.sounds(t2, p["tracks"], level), 1.0)
        self.assertEqual(project.level_tracks(p), frozenset())
        edit.set_track_flag(p, "t0", "reference", False)
        self.assertNotIn("reference", t0)

    def test_solo_reference_does_not_silence_the_export(self):
        p = proj()
        p["tracks"].append({"id": "t3", "kind": "audio", "name": "ref", "clips": [], "solo": True, "reference": True})
        t2 = edit.track_by_id(p, "t2")
        self.assertEqual(project.sounds(t2, p["tracks"]), 1.0)           # out: its solo counts for nothing
        level = project.level_tracks(dict(p, editing=True))
        self.assertEqual(project.sounds(t2, p["tracks"], level), 0.0)    # edited: it is solo

    def test_sources_follow_the_level(self):
        p = proj()
        edit.set_track_flag(p, "t2", "reference", True)
        self.assertEqual(audiomix.sources(p["tracks"]), [])
        srcs = audiomix.sources(p["tracks"], level=project.level_tracks(dict(p, editing=True)))
        self.assertEqual([s.clip["id"] for s in srcs], ["c3"])
        self.assertEqual(audiomix.stem_tracks(p), [])                     # no stem of it either


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.p = project.new()
        self.p.update(width=W, height=H, fps=30)
        red = clip("r", 0, 2 * S, media={"path": red_png(self.dir), "width": 160, "height": 90})
        self.p["tracks"] = [{"id": "t0", "kind": "video", "name": "v", "clips": [red]}]
        project.refresh_duration(self.p)
        project.link(self.p)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_shown_while_edited_only(self):
        edit.set_track_flag(self.p, "t0", "reference", True)
        self.assertTrue(red_at_centre(dict(self.p, editing=True)))
        self.assertFalse(red_at_centre(self.p))                          # export

    def test_not_shown_where_a_compound_uses_it(self):
        edit.make_compound(self.p, self.p, ["r"])
        cc = next(project.walk_clips(self.p["tracks"]))
        inner = cc["compound"]["tracks"][0]
        self.assertTrue(red_at_centre(dict(self.p, editing=True)))
        inner["reference"] = True
        self.assertFalse(red_at_centre(dict(self.p, editing=True)))      # used: left out
        opened = {"width": W, "height": H, "fps": 30, "tracks": cc["compound"]["tracks"],
                  "compounds": self.p["compounds"], "editing": True}
        self.assertTrue(red_at_centre(opened))                           # the compound edited: shown


class TimelineTests(unittest.TestCase):
    def test_menu(self):
        from kiasecut.ui.timeline import Timeline
        tl = Timeline()
        tl.resize(1000, 400)
        p = proj()
        edit.set_track_flag(p, "t0", "reference", True)
        tl.set_project(p)
        acts = []
        tl.trackAction.connect(lambda a, tid: acts.append((a, tid)))
        tl.grab()                                                         # (paints the badge)
        shown = []

        class Picked(QMenu):                                              # opens without blocking
            def exec(self, *_):
                shown.extend(x.text() for x in self.actions())
                next(x for x in self.actions() if x.text().startswith("取消參考軌道")).trigger()
        from kiasecut.ui import timeline as tmod
        was, tmod.Menu = tmod.Menu, lambda parent=None: Picked(parent)
        try:
            row = next(i for i, t in enumerate(tl.rows) if t["id"] == "t0")
            pos = QPoint(20, int(tl.tops[row]) + 8)
            tl._menu(pos, tl.mapToGlobal(pos))
        finally:
            tmod.Menu = was
        self.assertTrue(any(t.startswith("取消參考軌道") for t in shown))
        self.assertEqual(acts, [("toggle:reference", "t0")])


if __name__ == "__main__":
    unittest.main()
