"""Headless check of the preview handles: scale, rotate and the mask editor, through real
mouse events. Each drag must put the dragged point where the mouse let go.

  python tools/smoke_handles.py PROJECT.kiasecut.json out/
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, project, render  # noqa: E402
from kiasecut.ui.main_window import STYLE, MainWindow  # noqa: E402
from kiasecut.ui.preview import MaskGeo  # noqa: E402
from kiasecut.ui.timeline import US  # noqa: E402

app = QApplication(sys.argv)
app.setStyleSheet(STYLE)
win = MainWindow()
win.resize(1600, 940)
win.show()
win.path = sys.argv[1]
out = sys.argv[2]
win.set_project(project.load(win.path))
original = json.dumps(win.proj, sort_keys=True)
pv = win.preview
loads, checks = [0], []
win.player.worker.loaded.connect(lambda _: loads.__setitem__(0, loads[0] + 1))
T0 = time.time()


def say(m):
    print(f"{time.time() - T0:5.1f}s  {m}", flush=True)


def check(name, ok):
    checks.append(bool(ok))
    say(f"{'OK  ' if ok else 'FAIL'} {name}")


def screen(p):
    r = pv._rect()
    return QPoint(round(r.x() + p.x() / pv.W * r.width()), round(r.y() + p.y() / pv.H * r.height()))


def canvas(q):
    x, y = pv._to_canvas(QPointF(q))
    return QPointF(x, y)


def drag(a, b, steps=6):
    """Mouse drag on the preview from canvas point a to canvas point b; returns live count."""
    sa, sb = screen(a), screen(b)
    l0 = loads[0]
    QTest.mousePress(pv, Qt.LeftButton, Qt.NoModifier, sa)
    for s in range(1, steps + 1):
        QTest.mouseMove(pv, sa + (sb - sa) * s / steps)
        app.processEvents()
    QTest.mouseRelease(pv, Qt.LeftButton, Qt.NoModifier, sb)
    app.processEvents()
    return loads[0] - l0


def clip():
    return edit.find(win.proj, "c2")[1]


def dist(a, b):
    return math.hypot(a.x() - b.x(), a.y() - b.y())


def run():
    c = clip()
    win.timeline.select(c)
    win.seek(round((c["start_us"] + c["duration_us"] / 2) / US * win.fps))
    QTimer.singleShot(400, step_transform)


def step_transform():
    box = pv.selected_box()
    k = pv._k()
    ctr = QPointF(box.cx, box.cy)
    corner = box.corners()[2]
    target = ctr + (corner - ctr) * 0.8
    undo0 = len(win.history.undo_stack)
    live = drag(corner, target)
    s = clip()["transform"]["scale"]
    check(f"corner drag scaled the picture to {s:.3f} (want 0.8), {live} live frames, one undo step",
          abs(s - 0.8) < 0.01 and live >= 2 and len(win.history.undo_stack) == undo0 + 1)

    box = pv.selected_box()
    rh = box.rot_handle(k)
    r = dist(rh, ctr)
    drag(rh, ctr + QPointF(r * math.cos(math.radians(-2)), r * math.sin(math.radians(-2))))   # ~88° clockwise
    rot = clip()["transform"]["rotation"]
    check(f"rotation handle turned it to {rot}° (settles on 90)", rot == 90)
    win.grab().save(os.path.join(out, "handles_transform.png"))

    # zoom the view out to reach handles past the canvas edge, and drag it with the middle button
    from PySide6.QtGui import QWheelEvent
    at = QPointF(pv.width() * 0.7, pv.height() * 0.4)
    before = canvas(at)
    w0 = pv._rect().width()
    for _ in range(3):
        app.sendEvent(pv, QWheelEvent(at, QPointF(pv.mapToGlobal(at)), QPoint(), QPoint(0, -120),
                                      Qt.NoButton, Qt.ControlModifier, Qt.NoScrollPhase, False))
    check(f"Ctrl+wheel zoomed the view out ({w0:.0f} -> {pv._rect().width():.0f} px) around the mouse",
          pv._rect().width() < w0 * 0.65 and dist(canvas(at), before) < 1.0)
    p0 = QPointF(pv.pan)
    QTest.mousePress(pv, Qt.MiddleButton, Qt.NoModifier, QPoint(300, 300))
    QTest.mouseMove(pv, QPoint(340, 320))
    QTest.mouseRelease(pv, Qt.MiddleButton, Qt.NoModifier, QPoint(340, 320))
    check(f"middle-drag moved the view by {pv.pan - p0}", dist(pv.pan - p0, QPointF(40, 20)) < 1)
    box = pv.selected_box()
    corner = box.corners()[0]
    check("the rotated picture's corner, off the canvas, is on screen now",
          not (0 <= corner.y() <= pv.H) and pv.rect().contains(screen(corner)))
    target = QPointF(box.cx, box.cy) + (corner - QPointF(box.cx, box.cy)) * 0.5
    drag(corner, target)
    check(f"and dragging it scaled to {clip()['transform']['scale']:.3f} (want 0.4)",
          abs(clip()["transform"]["scale"] - 0.4) < 0.01)
    for _ in range(3):
        app.sendEvent(pv, QWheelEvent(at, QPointF(pv.mapToGlobal(at)), QPoint(), QPoint(0, 120),
                                      Qt.NoButton, Qt.ControlModifier, Qt.NoScrollPhase, False))
    check(f"zooming back in fits the canvas again ({pv.zoom:.2f})", pv.zoom == 1.0 and pv.pan == QPointF(0, 0))

    # a rectangle mask, edited on the canvas of the turned and scaled picture
    # the 遮罩 tab: the preview edits masks only
    mp = win.mask_panel
    win.side.setCurrentWidget(mp.parentWidget().parentWidget())
    app.processEvents()
    check("the 遮罩 tab turns the preview into the mask editor", pv.mask_mode)
    tf0 = dict(clip()["transform"])
    box = pv.selected_box()
    drag(QPointF(box.cx, box.cy), QPointF(box.cx + 100, box.cy + 40))
    drag(box.corners()[2], QPointF(box.cx, box.cy))
    check("there the clip itself cannot be moved or scaled", clip()["transform"] == tf0)
    mp.widgets["mask_on"].click()                    # no mask yet: switching on adds a rectangle
    app.processEvents()
    check("啟用遮罩 on a clip without one gives it a rectangle",
          (clip().get("mask") or {}).get("kind") == "rectangle" and "mask_invert" in mp.widgets)
    mp.widgets["mask_on"].click()
    app.processEvents()
    m = clip()["mask"]
    check("switching it off keeps the settings, and preview / export skip it",
          m.get("enabled") is False and m["kind"] == "rectangle" and project.active_mask(clip()) is None)
    mp.widgets["mask_on"].click()
    app.processEvents()
    check("and back on", project.active_mask(clip()) is not None)
    QTimer.singleShot(300, step_mask)


def step_mask():
    k = pv._k()
    g = MaskGeo(pv.selected_box())
    t = pv.selected_box().t
    # the overlay is the shape the renderer cuts with
    ren = pv.selected_box().xf().map(render.mask_path(clip()["mask"], t, (g.dw, g.dh))).boundingRect()
    ovl = g.outline().boundingRect()
    check(f"overlay matches the renderer's mask ({ovl.width():.1f}x{ovl.height():.1f})",
          all(abs(a - b) < 0.5 for a, b in zip(ren.getRect(), ovl.getRect())))

    target = g.centre() + QPointF(-160, 90)
    drag(g.centre(), target)
    g = MaskGeo(pv.selected_box())
    check(f"mask centre followed the mouse (off by {dist(g.centre(), target):.2f} px)", dist(g.centre(), target) < 1.5)

    hw = dict(g.handles(k))["w"]
    target = g.centre() + (hw - g.centre()) * 1.4
    w0 = g.mw
    drag(hw, target)
    g = MaskGeo(pv.selected_box())
    hw = dict(g.handles(k))["w"]
    check(f"width handle followed the mouse (w {w0:.3f} -> {g.mw:.3f}, off by {dist(hw, target):.2f} px)",
          dist(hw, target) < 1.5 and abs(g.mw / w0 - 1.4) < 0.01)

    rh = dict(g.handles(k))["rot"]
    ctr = g.centre()
    a = math.atan2(rh.y() - ctr.y(), rh.x() - ctr.x()) + math.radians(30)
    r = dist(rh, ctr)
    drag(rh, ctr + QPointF(r * math.cos(a), r * math.sin(a)))
    g = MaskGeo(pv.selected_box())
    check(f"mask rotation handle turned it to {g.rot}°", abs(g.rot - 30) < 0.5)

    u, _ = g.down()
    fh = dict(g.handles(k))["feather"]
    drag(fh, fh + u * 40 * k)
    g = MaskGeo(pv.selected_box())
    check(f"feather arrow dragged 40 px -> feather {g.feather}", abs(g.feather - 0.5) < 0.02)
    win.grab().save(os.path.join(out, "handles_mask.png"))
    finish()


def step_back():
    win.side.setCurrentIndex(0)
    app.processEvents()
    check("back on 屬性 the transform handles return", not pv.mask_mode)


def finish():
    step_back()
    while win.history.undo_stack:
        win.do_undo()
    check("undo restores the project", json.dumps(win.proj, sort_keys=True) == original)
    win.dirty = False
    app.quit()


QTimer.singleShot(800, run)
app.exec()
win.player.shutdown()
print("ALL OK" if checks and all(checks) else "SOME CHECKS FAILED", flush=True)
