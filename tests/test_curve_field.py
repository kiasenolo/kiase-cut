"""The curve widget (curvefield.py): a key dragged past others goes on past them and they stay, and a curve is
edited right inside its node."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import fx, nodegraph as ng  # noqa: E402
from kiasecut.ui.curvefield import CurveField  # noqa: E402

APP = QApplication.instance() or QApplication([])

KEYS = [[0.0, 0.0, 0, 0, 0, 0], [0.3, 0.8, 0, 0, 0, 0], [0.6, 0.2, 0, 0, 0, 0], [1.0, 1.0, 0, 0, 0, 0]]


def drag(cv, i, to_x, to_y=None, release=True):
    """Press key i of the canvas and drag it to plot x position to_x (pixels), moving in steps."""
    a = cv.key_point(0, i)
    y = a.y() if to_y is None else to_y
    QTest.mousePress(cv, Qt.LeftButton, Qt.NoModifier, a.toPoint())
    step = 4 if to_x > a.x() else -4
    x = a.x()
    while (x < to_x) if step > 0 else (x > to_x):
        x += step
        QTest.mouseMove(cv, QPointF(x, y).toPoint())
    QTest.mouseMove(cv, QPointF(to_x, y).toPoint())
    if release:
        QTest.mouseRelease(cv, Qt.LeftButton, Qt.NoModifier, QPointF(to_x, y).toPoint())


class DragPastTests(unittest.TestCase):
    def field(self, compact=False, keys=KEYS):
        f = CurveField(compact)
        self.addCleanup(f.close)
        f.resize(400, 400)
        f.show()
        f.set_value(keys)
        return f

    def test_a_key_dragged_right_past_another_leaves_it(self):
        f = self.field()
        done = []
        f.finished.connect(done.append)
        cv = f.canvas
        drag(cv, 1, cv.key_point(0, 2).x() + 30)
        self.assertEqual([round(k[0], 2) for k in f.keys][0], 0.0)
        self.assertEqual(len(f.keys), 4)                                       # (the key it passed is still there)
        self.assertEqual(sorted(round(k[1], 2) for k in f.keys), [0.0, 0.2, 0.8, 1.0])
        self.assertEqual([round(k[1], 2) for k in f.keys][1], 0.2)             # (it is the first of them now)
        self.assertGreater(f.keys[2][0], 0.6)                                  # (and the dragged one sits where it was let go)
        self.assertEqual([k[1] for k in f.keys][2], 0.8)
        self.assertEqual(len(done), 1)

    def test_and_left(self):
        f = self.field()
        cv = f.canvas
        drag(cv, 2, cv.key_point(0, 1).x() - 30)
        self.assertEqual(len(f.keys), 4)
        self.assertEqual(sorted(round(k[1], 2) for k in f.keys), [0.0, 0.2, 0.8, 1.0])
        self.assertLess(f.keys[1][0], 0.3)

    def test_the_order_comes_back_when_the_drag_goes_back(self):
        f = self.field()
        cv = f.canvas
        live = []
        f.live.connect(live.append)
        x0 = cv.key_point(0, 1).x()
        drag(cv, 1, cv.key_point(0, 2).x() + 30, release=False)
        self.assertEqual(len(live[-1]), 4)
        self.assertEqual([k[1] for k in live[-1]][2], 0.8)
        QTest.mouseMove(cv, QPointF(x0 + 4, cv.key_point(0, 1).y()).toPoint())
        QTest.mouseRelease(cv, Qt.LeftButton, Qt.NoModifier, QPointF(x0 + 4, 0).toPoint())
        self.assertEqual(len(f.keys), 4)

    def test_one_click_on_the_plot_adds_a_key_and_a_drag_moves_it(self):
        f = self.field()
        cv = f.canvas
        a, b = cv.key_point(0, 1), cv.key_point(0, 2)
        at = QPointF((a.x() + b.x()) / 2, a.y() - 20)
        QTest.mousePress(cv, Qt.LeftButton, Qt.NoModifier, at.toPoint())
        self.assertEqual(len(f.keys), 5)                                       # (at once, not after a second click)
        QTest.mouseMove(cv, (at + QPointF(10, 0)).toPoint())
        QTest.mouseRelease(cv, Qt.LeftButton, Qt.NoModifier, (at + QPointF(10, 0)).toPoint())
        self.assertEqual(len(f.keys), 5)
        xs = [k[0] for k in f.keys]
        self.assertEqual(xs, sorted(xs))

    def test_two_keys_stay_two(self):
        f = self.field(keys=[[0.0, 0.0, 0, 0, 0, 0], [1.0, 1.0, 0, 0, 0, 0]])
        cv = f.canvas
        drag(cv, 0, cv.key_point(0, 1).x() + 20)
        self.assertEqual(len(f.keys), 2)


class InlineTests(unittest.TestCase):
    def test_a_curve_is_edited_inside_its_node(self):
        from kiasecut.ui.node_editor import NodeEditor
        e = fx.new_effect(fx.GRAPH, "e1")
        n = ng.add_node(e["graph"], {"type": "filter", "ref": "builtin:nodes/float_curve"}, 0, 0, base="c")
        e["params"].update(ng.default_params(e["graph"]))
        ed = NodeEditor()
        self.addCleanup(ed.close)
        ed.resize(700, 600)
        ed.show()
        edited, live = [], []
        ed.paramEdited.connect(lambda eid, k, v: edited.append((k, v)))
        ed.paramLive.connect(lambda eid, g, k, v: live.append((k, v)))
        ed.show_clip({"id": "c1", "type": "image", "effects": [e]})
        item = ed.view.items_by_id[n]
        self.assertEqual(len(item.inline), 1)
        q, w = item.inline[0]
        self.assertEqual(q.name, "curve")
        cv = w.canvas
        a, b = cv.key_point(0, 0), cv.key_point(0, 1)
        QTest.mouseClick(cv, Qt.LeftButton, Qt.NoModifier, QPointF((a.x() + b.x()) / 2, a.y() - 30).toPoint())       # (a key added by one click)
        self.assertEqual(edited[-1][0], ng.param_key(n, "curve"))
        self.assertEqual(len(edited[-1][1]), 3)
        mid = cv.key_point(0, 1)                                                                                      # (and dragged)
        QTest.mousePress(cv, Qt.LeftButton, Qt.NoModifier, mid.toPoint())
        QTest.mouseMove(cv, QPointF(mid.x(), mid.y() + 15).toPoint())
        QTest.mouseMove(cv, QPointF(mid.x(), mid.y() + 30).toPoint())
        self.assertTrue(live)
        self.assertEqual(e["params"][ng.param_key(n, "curve")][1][1], live[-1][1][1][1])
        QTest.mouseRelease(cv, Qt.LeftButton, Qt.NoModifier, QPointF(mid.x(), mid.y() + 30).toPoint())
        # the node shows what the parameters hold again when they change from elsewhere
        e["params"][ng.param_key(n, "curve")] = [[0.0, 0.0, 0, 0, 0, 0], [0.5, 0.9, 0, 0, 0, 0], [0.8, 0.1, 0, 0, 0, 0], [1.0, 1.0, 0, 0, 0, 0]]
        ed.show_clip({"id": "c1", "type": "image", "effects": [e]})
        self.assertEqual(len(w.keys), 4)


if __name__ == "__main__":
    unittest.main()
