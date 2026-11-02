"""The VFX tab: the filters by category, each category its own grid / list like the 內建素材 tab's."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut.ui import viewmode  # noqa: E402
from kiasecut.ui.vfx_panel import FX_MIME, ROLE_REF, VfxPanel  # noqa: E402

APP = QApplication.instance() or QApplication([])


class VfxPanelTests(unittest.TestCase):
    def test_categories_search_view_and_drag(self):
        was = viewmode.remembered("vfx", "grid")
        try:
            viewmode.remember("vfx", "grid")
            p = VfxPanel()
            p.resize(420, 700)
            self.assertGreater(len(p.cats), 3)
            head, lst = p.cats[0]
            self.assertTrue(lst.dragEnabled())
            ref = lst.item(0).data(ROLE_REF)
            self.assertEqual(bytes(lst.mimeData([lst.item(0)]).data(FX_MIME)).decode(), ref)
            p.search.setText("zzzz-no-such-filter")
            self.assertTrue(all(l.isHidden() for _h, l in p.cats))
            p.search.setText("")
            self.assertFalse(lst.isHidden())
            p.toggle.click()                                          # the other arrangement, for every category
            modes = {l.viewMode() for _h, l in p.cats}
            self.assertEqual(len(modes), 1)
            self.assertTrue(all(l.dragEnabled() for _h, l in p.cats))
        finally:
            viewmode.remember("vfx", was)


if __name__ == "__main__":
    unittest.main()
