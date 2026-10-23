"""Headless check of the keyframe curve editor through real mouse / keyboard events.

  python tools/smoke_curves.py PROJECT.tesetoa.json out/
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from tesetoa import curves, project  # noqa: E402
from tesetoa.ui.main_window import STYLE, MainWindow  # noqa: E402
from tesetoa.ui.timeline import US  # noqa: E402

app = QApplication(sys.argv)
app.setStyleSheet(STYLE)
win = MainWindow()
win.resize(1600, 940)
win.show()
win.path = sys.argv[1]
out = sys.argv[2]
win.set_project(project.load(win.path))
original = json.dumps(win.proj, sort_keys=True)
loads, checks = [0], []
win.player.worker.loaded.connect(lambda _: loads.__setitem__(0, loads[0] + 1))
T0 = time.time()


def say(m):
    print(f"{time.time() - T0:5.1f}s  {m}", flush=True)


def check(name, ok):
    checks.append(bool(ok))
    say(f"{'OK  ' if ok else 'FAIL'} {name}")


def clip():
    return next(c for t in win.proj["tracks"] for c in t["clips"]
                if c["type"] == "text" and c["text"]["content"] == "傻逼對話記錄")


def keys(name):
    return clip()["transform"][name]["keys"]


cv = win.curves
canvas = cv.canvas
state = {}


def tick(names):
    """Show exactly these transform parameters."""
    for i in range(cv.params.count()):
        it = cv.params.item(i)
        want = tuple(it.data(Qt.UserRole)) in {("transform", n) for n in names}
        if (it.checkState() == Qt.Checked) != want:
            it.setCheckState(Qt.Checked if want else Qt.Unchecked)
    app.processEvents()


def pt(ci, i):
    p = canvas.key_point(ci, i)
    return QPoint(round(p.x()), round(p.y()))


def run():
    c = clip()
    win.timeline.select(c)
    win.side.setCurrentWidget(cv)
    tick(["y"])
    n0 = len(keys("y"))
    check(f"curve editor shows 位置 Y with its {n0} keyframes",
          len(canvas.curves) == 1 and len(canvas.curves[0]["keys"]) == n0 and n0 >= 2)

    # double-click to add a keyframe at a quarter of the clip, half way up
    x = round(canvas.x(c["duration_us"] / 4))
    y = round(canvas.height() / 2)
    QTest.mouseDClick(canvas, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    app.processEvents()
    ks = keys("y")
    px = (canvas.t1 - canvas.t0) / max(1, canvas.width() - canvas.L - canvas.R)     # us per pixel
    added = next((k for k in ks if abs(k[0] - c["duration_us"] / 4) < 1.5 * px), None)
    check(f"double-click added a keyframe ({len(ks)} keys)", len(ks) == n0 + 1 and added is not None)
    i = ks.index(added)
    v0 = added[1]

    # drag it up 40 px: the preview gets live states while dragging
    k0 = pt(0, i)
    l0 = loads[0]
    QTest.mousePress(canvas, Qt.LeftButton, Qt.NoModifier, k0)
    for s in range(1, 9):
        QTest.mouseMove(canvas, k0 - QPoint(0, 5 * s))
        app.processEvents()
    live = loads[0] - l0
    QTest.mouseRelease(canvas, Qt.LeftButton, Qt.NoModifier, k0 - QPoint(0, 40))
    app.processEvents()
    v1 = keys("y")[i][1]
    check(f"dragging the key raised its value ({v0:.3f} -> {v1:.3f}), {live} live previews", v1 > v0 and live >= 3)

    # type a cubic-bezier for the segment from this key to the next
    canvas.sel = {(0, i)}
    cv.bezier.setText("cubic-bezier(0.68, -0.55, 0.27, 1.55)")
    QTest.keyClick(cv.bezier, Qt.Key_Return)
    app.processEvents()
    ks = keys("y")
    got = curves.segment_bezier(ks[i], ks[i + 1])
    check(f"typed cubic-bezier applied: {tuple(round(g, 3) for g in got)}",
          all(abs(a - b) < 1e-6 for a, b in zip(got, (0.68, -0.55, 0.27, 1.55))))

    # the ease-in-out preset button
    canvas.sel = {(0, i)}
    preset = next(b for b in cv.findChildren(QPushButton) if b.text() == "緩入緩出")
    preset.click()
    app.processEvents()
    ks = keys("y")
    got = curves.segment_bezier(ks[i], ks[i + 1])
    check("preset 緩入緩出 applied", all(abs(a - b) < 1e-6 for a, b in zip(got, (0.42, 0.0, 0.58, 1.0))))

    # Delete removes the selected key
    canvas.setFocus()
    canvas.sel = {(0, i)}
    QTest.keyClick(canvas, Qt.Key_Delete)
    app.processEvents()
    check("Delete removed the keyframe", len(keys("y")) == n0)

    # two curves at once: X and Y
    tick(["x", "y"])
    check("位置 X and 位置 Y shown together", [cc["label"] for cc in canvas.curves] == ["位置 X", "位置 Y"])

    # wheel over the last keys zooms time around the mouse
    span0 = canvas.t1 - canvas.t0
    at = pt(1, len(keys("y")) - 1)
    t_at = canvas.t_of(at.x())
    for _ in range(12):
        ev = QWheelEvent(QPointF(at), QPointF(canvas.mapToGlobal(at)), QPoint(), QPoint(0, 120),
                         Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        app.sendEvent(canvas, ev)
    app.processEvents()
    span1 = canvas.t1 - canvas.t0
    check(f"wheel zoomed time {span0 / US:.1f}s -> {span1 / US:.2f}s around the mouse",
          span1 < span0 / 5 and abs(canvas.t_of(at.x()) - t_at) < 1000)
    win.grab().save(os.path.join(out, "curves_multi.png"))

    # box-select every key (both curves), then drag them one frame-snapped step together
    w, h = canvas.width(), canvas.height()
    QTest.mousePress(canvas, Qt.LeftButton, Qt.NoModifier, QPoint(canvas.L + 2, canvas.T + 2))
    QTest.mouseMove(canvas, QPoint(w // 2, h // 2))
    QTest.mouseMove(canvas, QPoint(w - 1, h - canvas.B - 1))
    QTest.mouseRelease(canvas, Qt.LeftButton, Qt.NoModifier, QPoint(w - 1, h - canvas.B - 1))
    app.processEvents()
    visible = sum(1 for ci, cc in enumerate(canvas.curves) for j in range(len(cc["keys"]))
                  if canvas.t0 <= cc["keys"][j][0] <= canvas.t1)
    check(f"box selected {len(canvas.sel)} keyframes on two curves",
          len(canvas.sel) == visible >= 2 and {ci for ci, _ in canvas.sel} == {0, 1})
    before = {n: [k[0] for k in keys(n)] for n in ("x", "y")}
    undo0 = len(win.history.undo_stack)
    ci, j = sorted(canvas.sel)[0]
    a = pt(ci, j)
    dx = round(canvas.x(canvas.t0 + 0.05 * US) - canvas.x(canvas.t0))     # 50 ms to the left
    QTest.mousePress(canvas, Qt.LeftButton, Qt.NoModifier, a)
    for s in range(1, 6):
        QTest.mouseMove(canvas, a - QPoint(dx * s // 5, 0))
    QTest.mouseRelease(canvas, Qt.LeftButton, Qt.NoModifier, a - QPoint(dx, 0))
    app.processEvents()
    after = {n: [k[0] for k in keys(n)] for n in ("x", "y")}
    shifts = {round((b - a_) / 1000) for n in ("x", "y") for a_, b in zip(before[n], after[n]) if b != a_}
    check(f"dragging moved keys of both curves together by {shifts} ms in one undo step",
          len(shifts) == 1 and -60 <= next(iter(shifts)) <= -40 and before["x"] != after["x"]
          and before["y"] != after["y"] and len(win.history.undo_stack) == undo0 + 1)

    # Ctrl+A then a preset: every segment of both curves eases
    canvas.setFocus()
    QTest.keyClick(canvas, Qt.Key_A, Qt.ControlModifier)
    app.processEvents()
    n_all = len(keys("x")) + len(keys("y"))
    preset = next(b for b in cv.findChildren(QPushButton) if b.text() == "緩出")
    preset.click()
    app.processEvents()
    segs = [curves.segment_bezier(a_, b) for n in ("x", "y") for a_, b in zip(keys(n), keys(n)[1:])]
    check(f"Ctrl+A ({len(canvas.sel)}/{n_all}) and 緩出 eased all {len(segs)} segments",
          len(canvas.sel) == n_all and all(abs(s[2] - 0.58) < 1e-6 for s in segs))

    # click the time ruler: the playhead goes there
    canvas.fit()
    target = c["duration_us"] / 2
    QTest.mouseClick(canvas, Qt.LeftButton, Qt.NoModifier, QPoint(round(canvas.x(target)), canvas.height() - 6))
    state["want"] = round((c["start_us"] + target) / US * win.fps)
    QTimer.singleShot(600, finish)


def finish():
    check(f"clicking the ruler moved the playhead ({win.pos} ~ {state['want']})", abs(win.pos - state["want"]) <= 2)
    while win.history.undo_stack:
        win.do_undo()
    check("undo restores the project", json.dumps(win.proj, sort_keys=True) == original)
    win.dirty = False
    app.quit()


QTimer.singleShot(1500, run)
app.exec()
win.player.shutdown()
print("ALL OK" if checks and all(checks) else "SOME CHECKS FAILED", flush=True)
