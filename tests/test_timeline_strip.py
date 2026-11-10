"""The timeline repaints a strip (where the playhead was and is) as it paints the whole: a clip far longer than the view is
drawn only near what is repainted, the ruler's labels only where they reach it - the pixels are the same."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import project  # noqa: E402
from kiasecut.ui.timeline import Timeline  # noqa: E402
from test_tracks import proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


class StripTests(unittest.TestCase):
    def setUp(self):
        self.tl = Timeline()
        self.tl.resize(900, 300)
        p = proj()
        p["tracks"][0]["clips"][0]["duration_us"] = 600_000_000          # ten minutes: far past the view
        p["tracks"].insert(0, {"id": "t", "kind": "video", "name": "t", "clips": [
            {"id": f"t{i}", "type": "text", "start_us": i * 700_000, "duration_us": 600_000, "text": {"content": f"字幕 {i} ✦"},
             "transform": {}} for i in range(12)]})
        project.refresh_duration(p)
        self.tl.set_project(p)

    def same(self, why):
        whole = self.tl.grab().toImage()
        k = whole.devicePixelRatio()
        for x in (0, 60, 139, 141, 200, 333, 512, 700, 891):
            r = QRect(x, 0, 9, self.tl.height())
            strip = self.tl.grab(r).toImage()
            cut = whole.copy(QRect(round(r.x() * k), 0, strip.width(), strip.height()))
            self.assertEqual(strip.convertToFormat(cut.format()), cut, f"{why}: the strip at {x}")

    def test_a_strip_is_the_whole_there(self):
        for px, scroll in ((100.0, 0.0), (100.0, 3.3), (800.0, 1.0), (4.0, 0.0), (37.0, 250.0)):
            self.tl.px_per_s, self.tl.scroll_s = px, scroll
            self.same(f"{px} px a second from {scroll} s")

    def test_with_a_long_clip_selected_and_bars_on_the_ruler(self):
        self.tl.px_per_s, self.tl.scroll_s = 150.0, 2.0
        self.tl.selected_id = "vid"
        self.same("selected")
        self.tl.timebase = {"kind": "bpm", "bpm": 128.0, "div": 4, "meter": 4, "offset_us": 0}
        self.same("bars and beats")


if __name__ == "__main__":
    unittest.main()
