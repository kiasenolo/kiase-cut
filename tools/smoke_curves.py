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

from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
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


def ykeys():
    return clip()["transform"]["y"]["keys"]


cv = win.curves
canvas = cv.canvas
state = {}


def run():
    c = clip()
    win.timeline.select(c)
    win.side.setCurrentWidget(cv)
    cv.select_param("transform", "y")
    app.processEvents()
    n0 = len(ykeys())
    check(f"curve editor shows 位置 Y with its {n0} keyframes", len(canvas.keys) == n0 and n0 >= 2)

    # double-click to add a keyframe at a quarter of the clip, half way up
    x = round(canvas.x(c["duration_us"] / 4))
    y = round(canvas.height() / 2)
    QTest.mouseDClick(canvas, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    app.processEvents()
    keys = ykeys()
    added = next((k for k in keys if abs(k[0] - c["duration_us"] / 4) < 0.02 * US), None)
    check(f"double-click added a keyframe ({len(keys)} keys)", len(keys) == n0 + 1 and added is not None)
    i = keys.index(added)
    canvas.sel = i
    v0 = added[1]

    # drag it up 40 px: the preview gets live states while dragging
    kx, ky = round(canvas.x(added[0])), round(canvas.y(added[1]))
    l0 = loads[0]
    QTest.mousePress(canvas, Qt.LeftButton, Qt.NoModifier, QPoint(kx, ky))
    for k in range(1, 9):
        QTest.mouseMove(canvas, QPoint(kx, ky - 5 * k))
        app.processEvents()
    live = loads[0] - l0
    QTest.mouseRelease(canvas, Qt.LeftButton, Qt.NoModifier, QPoint(kx, ky - 40))
    app.processEvents()
    v1 = ykeys()[i][1]
    check(f"dragging the key raised its value ({v0:.3f} -> {v1:.3f}), {live} live previews", v1 > v0 and live >= 3)

    # type a cubic-bezier for the segment from this key to the next
    cv.bezier.setText("cubic-bezier(0.68, -0.55, 0.27, 1.55)")
    QTest.keyClick(cv.bezier, Qt.Key_Return)
    app.processEvents()
    keys = ykeys()
    got = curves.segment_bezier(keys[i], keys[i + 1])
    check(f"typed cubic-bezier applied: {tuple(round(g, 3) for g in got)}",
          all(abs(a - b) < 1e-6 for a, b in zip(got, (0.68, -0.55, 0.27, 1.55))))
    win.grab().save(os.path.join(out, "curves_bezier.png"))

    # the ease-in-out preset button
    preset = next(b for b in cv.findChildren(QPushButton) if b.text() == "緩入緩出")
    preset.click()
    app.processEvents()
    keys = ykeys()
    got = curves.segment_bezier(keys[i], keys[i + 1])
    check("preset 緩入緩出 applied", all(abs(a - b) < 1e-6 for a, b in zip(got, (0.42, 0.0, 0.58, 1.0))))

    # Delete removes the selected key
    canvas.setFocus()
    canvas.sel = i
    QTest.keyClick(canvas, Qt.Key_Delete)
    app.processEvents()
    check("Delete removed the keyframe", len(ykeys()) == n0)

    # click on empty graph area seeks there
    target = c["duration_us"] / 2
    QTest.mouseClick(canvas, Qt.LeftButton, Qt.NoModifier, QPoint(round(canvas.x(target)), canvas.height() - canvas.B - 3))
    state["want"] = round((c["start_us"] + target) / US * win.fps)
    QTimer.singleShot(600, finish)


def finish():
    check(f"clicking the graph moved the playhead ({win.pos} ~ {state['want']})", abs(win.pos - state["want"]) <= 2)
    while win.history.undo_stack:
        win.do_undo()
    check("undo restores the project", json.dumps(win.proj, sort_keys=True) == original)
    win.dirty = False
    app.quit()


QTimer.singleShot(1500, run)
app.exec()
win.player.shutdown()
print("ALL OK" if checks and all(checks) else "SOME CHECKS FAILED", flush=True)
