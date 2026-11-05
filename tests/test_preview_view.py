"""The preview's view moved about as in Blender's image editor: the wheel zooms around the
mouse, the middle button moves it (Ctrl: zooms), Home fits it, a ratio shows canvas pixels at
a size, numpad . frames the selection, Shift+B zooms into a box."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut.ui.preview import ZOOM_STEP, Preview  # noqa: E402
from test_edit import S, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])
NONE = Qt.KeyboardModifier.NoModifier


def wheel(pv, at, notches, mods=NONE):
    e = QWheelEvent(QPointF(at), QPointF(pv.mapToGlobal(at)), QPoint(), QPoint(0, 120 * notches),
                    Qt.NoButton, mods, Qt.NoScrollPhase, False)
    QApplication.sendEvent(pv, e)
    glide = getattr(pv, "_zoom_glide", None)
    while glide is not None and glide.left:           # (the wheel's zoom glides: let it end)
        glide.last -= 1.0
        glide.step()


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.pv = Preview()
        self.pv.resize(960, 540)                     # the 1920 x 1080 canvas at half size
        self.pv.set_scene(proj(), S // 2, "c1")

    def canvas_at(self, pt):
        return self.pv._to_canvas(QPointF(pt))

    def test_wheel_zooms_around_the_mouse_without_ctrl(self):
        at = QPoint(200, 150)
        before = self.canvas_at(at)
        wheel(self.pv, at, 1)
        self.assertAlmostEqual(self.pv.zoom, ZOOM_STEP)
        after = self.canvas_at(at)
        self.assertAlmostEqual(before[0], after[0], places=6)
        self.assertAlmostEqual(before[1], after[1], places=6)
        wheel(self.pv, at, -1)
        self.assertAlmostEqual(self.pv.zoom, 1.0)

    def test_middle_drag_moves_and_ctrl_middle_drag_zooms(self):
        QTest.mousePress(self.pv, Qt.MiddleButton, NONE, QPoint(400, 300))
        QTest.mouseMove(self.pv, QPoint(450, 320))
        QTest.mouseRelease(self.pv, Qt.MiddleButton, NONE, QPoint(450, 320))
        self.assertEqual((self.pv.pan.x(), self.pv.pan.y()), (50, 20))
        self.assertEqual(self.pv.zoom, 1.0)
        QTest.mousePress(self.pv, Qt.MiddleButton, Qt.ControlModifier, QPoint(400, 300))
        QTest.mouseMove(self.pv, QPoint(500, 300))
        QTest.mouseRelease(self.pv, Qt.MiddleButton, Qt.ControlModifier, QPoint(500, 300))
        self.assertGreater(self.pv.zoom, 1.2)

    def test_fit_and_ratio(self):
        self.pv.zoom_to(3.0)
        self.pv.view_fit()
        self.assertEqual((self.pv.zoom, self.pv.pan), (1.0, QPointF(0, 0)))
        self.pv.view_ratio(1)                        # 1:1: 1920 canvas px over 1920 device px
        dpr = self.pv.devicePixelRatioF()
        self.assertAlmostEqual(self.pv._rect().width() * dpr, 1920)
        self.pv.view_ratio(1 / 4)
        self.assertAlmostEqual(self.pv._rect().width() * dpr, 480)

    def test_frame_the_selection(self):
        self.pv.view_selected()
        box = self.pv.selected_box()
        l, r, t, b = box.extents()
        sr = self.pv._screen_rect(box)
        mid = sr.center()
        self.assertAlmostEqual(mid.x(), 480, places=3)            # in the middle of the view
        self.assertAlmostEqual(mid.y(), 270, places=3)
        self.assertTrue(sr.width() <= 960 + 1e-6 and sr.height() <= 540 + 1e-6)
        self.assertTrue(abs(sr.width() - 960 / 1.2) < 1 or abs(sr.height() - 540 / 1.2) < 1)

    def test_shift_b_box_zoom(self):
        self.pv._arm_box_zoom()
        a, b = QPoint(2, 2), QPoint(482, 272)        # a quarter of the canvas (QTest takes (0, 0) as the middle)
        QTest.mousePress(self.pv, Qt.LeftButton, NONE, a)
        QTest.mouseMove(self.pv, (a + b) / 2)
        QTest.mouseMove(self.pv, b)
        QTest.mouseRelease(self.pv, Qt.LeftButton, NONE, b)
        self.assertFalse(self.pv.box_zoom)
        self.assertAlmostEqual(self.pv.zoom, 2.0)
        x, y = self.canvas_at(QPoint(480, 270))
        self.assertAlmostEqual(x, 484, places=3)                   # that quarter's middle is in the middle
        self.assertAlmostEqual(y, 274, places=3)

    def test_box_zoom_does_not_select(self):
        got = []
        self.pv.selectionPicked.connect(lambda *a: got.append(a))
        self.pv._arm_box_zoom()
        QTest.mousePress(self.pv, Qt.LeftButton, NONE, QPoint(10, 10))
        QTest.mouseMove(self.pv, QPoint(60, 60))
        QTest.mouseMove(self.pv, QPoint(100, 100))
        QTest.mouseRelease(self.pv, Qt.LeftButton, NONE, QPoint(100, 100))
        self.assertEqual(got, [])


if __name__ == "__main__":
    unittest.main()


class OutsideTests(unittest.TestCase):
    """A frame drawn with the margin round the canvas (the 畫布外 button): the preview that edits shows all of it, dimmed outside."""
    def frame(self, margin):
        w, h = 200, 100
        mx, my = round(w * margin), round(h * margin)
        img = QImage(w + 2 * mx, h + 2 * my, QImage.Format_RGBA8888)
        img.fill(QColor("#ff0000"))
        for x in range(mx, mx + w):                  # (the canvas itself is green)
            for y in range(my, my + h):
                img.setPixelColor(x, y, QColor("#00ff00"))
        img.setText("margin", repr(margin))
        return img

    def test_the_editing_preview_keeps_it_and_dims_what_is_outside(self):
        pv = Preview()
        pv.resize(960, 540)
        pv.set_scene(proj(), S // 2, "c1")
        pv.zoom = 0.5                                  # (zoomed out: there is room round the canvas)
        pv.show_image(self.frame(0.5))
        self.assertEqual(pv.margin, 0.5)
        shot = pv.grab().toImage()
        r = pv._rect()
        inside = shot.pixelColor(int(r.center().x()), int(r.center().y()))
        outside = shot.pixelColor(int(r.left() - r.width() * 0.25), int(r.center().y()))
        self.assertGreater(inside.green(), 200)                              # (the canvas: the picture)
        self.assertGreater(outside.red(), outside.green())                   # (outside it: the red part of the frame ...
        self.assertLess(outside.red(), 200)                                  # ... dimmed)

    def test_a_preview_that_does_not_edit_shows_the_canvas_alone(self):
        pv = Preview(interactive=False)
        pv.show_image(self.frame(0.5))
        self.assertEqual(pv.margin, 0.0)
        self.assertEqual((pv.img.width(), pv.img.height()), (200, 100))
        self.assertEqual(pv.img.pixelColor(0, 0).green(), 255)

    def test_a_frame_without_a_margin_is_as_before(self):
        pv = Preview()
        pv.show_image(self.frame(0.0))
        self.assertEqual(pv.margin, 0.0)
        pv.show_image(None)
        self.assertEqual(pv.margin, 0.0)
