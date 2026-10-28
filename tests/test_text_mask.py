"""Masks on text clips: set like a picture's, cut the words in the preview, and send the export
through the program's own renderer (renderexport.needs_renderer)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402

from kiasecut import edit, project, render, renderexport, textlayout  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])
S = 1_000_000
W, H = 320, 180


def text_clip(**text):
    tx = {"content": "MMMMMMMM", "font_path": project.DEFAULT_FONT, "size": 14.0, "color": [1.0, 1.0, 1.0]}
    tx.update(text)
    return {"id": "tx", "type": "text", "name": "tx", "start_us": 0, "duration_us": 2 * S, "source_start_us": 0,
            "text": tx, "transform": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}}


def view(c):
    return {"width": 640, "height": 360, "fps": 30, "duration_us": 2 * S,
            "tracks": [{"id": "t0", "kind": "video", "name": "v", "clips": [c]}]}


def alpha(img):
    im = img.convertToFormat(QImage.Format_RGBA8888)
    return np.frombuffer(bytes(im.constBits()), np.uint8).reshape(im.height(), im.width(), 4)[..., :3].max(axis=2)


@unittest.skipUnless(project.DEFAULT_FONT, "no default font")
class TextMaskTests(unittest.TestCase):
    def proj(self, c):
        p = project.new()
        p["tracks"] = [{"id": "t0", "kind": "video", "name": "v", "clips": [c]}]
        project.refresh_duration(p)
        return project.link(p)

    def test_set_mask_on_text(self):
        p = self.proj(text_clip())
        c = edit.find(p, "tx")[1]
        edit.set_mask(p, "tx", "circle")
        self.assertEqual(c["mask"]["kind"], "circle")
        self.assertGreater(c["mask"]["h"], c["mask"]["w"])          # round on a wide line of text
        self.assertTrue(renderexport.needs_renderer(p))
        edit.set_mask_enabled(p, "tx", False)
        self.assertFalse(renderexport.needs_renderer(p))

    def test_mask_cuts_the_words(self):
        r = render.Renderer()
        whole = alpha(r.render(view(text_clip()), 0, W, H))
        c = text_clip()
        # the left half of the text's frame (mask space: w a fraction of its width, cx of half of it)
        c["mask"] = {"kind": "rectangle", "invert": False, "cx": -0.5, "cy": 0.0, "w": 0.5, "h": 2.0,
                     "rotation": 0.0, "feather": 0.0}
        cut = alpha(r.render(view(c), 0, W, H))
        self.assertEqual(r.errors, [])
        self.assertGreater(whole[:, W // 2 + 4:].sum(), 0)
        self.assertGreater(cut[:, :W // 2 - 4].sum(), 0.8 * whole[:, :W // 2 - 4].sum())
        self.assertEqual(cut[:, W // 2 + 4:].sum(), 0)

    def test_boxed_text_mask_uses_its_frame(self):
        """A 文字框's mask is placed in the frame the editor outlines (preview.text_size), not in
        the drawn picture (which has a margin around it); other texts' in the picture."""
        r = render.Renderer()
        spec = dict(text_clip(box_w=60.0)["text"], box_w=60.0)
        self.assertEqual(r.text_disp(spec, 1080, (999, 999), 1.0), textlayout.frame_size(spec, 1080))
        self.assertEqual(r.text_disp(text_clip()["text"], 1080, (999, 999), 1.0), (999, 999))


if __name__ == "__main__":
    unittest.main()
