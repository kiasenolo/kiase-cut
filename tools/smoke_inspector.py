"""Headless check of the inspector's number fields (drag to change, click to type), the
paired X / Y row, the curve editor's keyframe jumps and nesting a timeline in another.

  python tools/smoke_inspector.py PROJECT.tesetoa.json out/
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tesetoa import edit, project  # noqa: E402
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
original = project.dumps(win.proj)
tl = win.timeline
checks = []
T0 = time.time()


def say(m):
    print(f"{time.time() - T0:5.1f}s  {m}", flush=True)


def check(name, ok):
    checks.append(bool(ok))
    say(f"{'OK  ' if ok else 'FAIL'} {name}")


def text_clip():
    """A text clip with a fixed position (the first one)."""
    return next(c for t in win.proj["tracks"] for c in t["clips"]
                if c["type"] == "text" and not isinstance(c["transform"]["x"], dict)
                and not isinstance(c["transform"]["y"], dict) and c["duration_us"] > US)


def run():
    c = text_clip()
    tl.select(c)
    win.seek(round((c["start_us"] + c["duration_us"] / 2) / US * win.fps))
    QTimer.singleShot(300, step_fields)


def step_fields():
    ins = win.inspector
    sx, sy = ins.widgets[("transform", "x")], ins.widgets[("transform", "y")]
    check("位置 X and Y share one row", sx.parentWidget() is sy.parentWidget())
    # drag the X field up 20 px: +10 steps of 0.01
    le = sx.lineEdit()
    x0 = text_clip()["transform"]["x"]
    p0 = le.rect().center()
    undo0 = len(win.history.undo_stack)
    QTest.mousePress(le, Qt.LeftButton, Qt.NoModifier, p0)
    for s in range(1, 6):
        QTest.mouseMove(le, p0 - QPoint(0, 4 * s))
    QTest.mouseRelease(le, Qt.LeftButton, Qt.NoModifier, p0 - QPoint(0, 20))
    ins._flush()
    app.processEvents()
    x1 = text_clip()["transform"]["x"]
    check(f"dragging X up 20 px changed it {x0:.3f} -> {x1:.3f} in one undo step, without typing",
          abs(x1 - x0 - 0.10) < 1e-6 and not le.hasFocus() and len(win.history.undo_stack) == undo0 + 1)
    # a click (no drag) starts typing
    QTest.mouseClick(sy.lineEdit(), Qt.LeftButton, Qt.NoModifier, sy.lineEdit().rect().center())
    app.processEvents()
    app.processEvents()
    check("a click on Y starts typing (focus, all selected)",
          sy.lineEdit().hasFocus() and sy.lineEdit().selectedText() == sy.lineEdit().text())
    QTest.keyClicks(sy.lineEdit(), "0.25")
    QTest.keyClick(sy.lineEdit(), Qt.Key_Return)
    ins._flush()
    app.processEvents()
    check(f"typed Y = {text_clip()['transform']['y']}", abs(text_clip()["transform"]["y"] - 0.25) < 1e-6)
    win.timeline.setFocus()
    win.grab().save(os.path.join(out, "inspector_pairs.png"))

    # keyframe jumps live in the curve editor now
    check("the inspector has no 上一個 / 下一個 any more",
          not any(b.text().startswith("◀") for b in ins.findChildren(type(win.play_btn))))
    c = next(c for t in win.proj["tracks"] for c in t["clips"]
             if c["type"] == "text" and c["text"]["content"] == "傻逼對話記錄")
    tl.select(c)
    win.seek(round(c["start_us"] / US * win.fps))
    QTimer.singleShot(300, lambda: (win.curves.keyJump.emit(1), QTimer.singleShot(400, lambda: step_jump(c))))


def step_jump(c):
    want = round((c["start_us"] + edit.key_times(c)[0]) / US * win.fps)
    check(f"curve editor ▶ jumped to the first keyframe ({win.pos} ~ {want})", abs(win.pos - want) <= 1)
    step_nest()


def step_nest():
    main = win.proj["active_timeline"]
    win.apply_root("新增時間線", edit.add_timeline)
    second = win.proj["active_timeline"]
    tree = win.compounds.tree
    it = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
              if tree.topLevelItem(i).data(0, Qt.UserRole) == ("def", main))
    md = tree.mimeData([it])
    tl.px_per_s, tl.scroll_s = 10.0, 0.0
    ev = QDropEvent(QPointF(tl._x(1.0), tl.tops[0] + 5), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    tl.dropEvent(ev)
    app.processEvents()
    nested = tl.selected
    check(f"dropping 時間線 1 into 時間線 2 nests it ({nested and nested.get('timeline_id')}, "
          f"{nested and nested['duration_us'] / US:.1f}s)",
          nested is not None and nested.get("timeline_id") == main
          and nested["compound"] is project.timeline(win.proj, main))
    win.seek(round(12 * win.fps))
    QTimer.singleShot(400, lambda: step_nest_check(main, second))


def step_nest_check(main, second):
    check("the nested timeline renders without errors", not win.player.worker.renderer.errors)
    n = sum(len(t["clips"]) for t in win.proj["tracks"])
    win.switch_timeline(main)
    win.place_compound(second, "", 0)               # 2 shows 1: 1 may not show 2
    check("putting 時間線 2 inside 時間線 1 is refused (it would show itself)",
          sum(len(t["clips"]) for t in project.timeline(win.proj, second)["tracks"]) == n
          and not any(c.get("timeline_id") == second for t in win.proj["tracks"] for c in t["clips"]))
    win.grab().save(os.path.join(out, "inspector_nested.png"))
    finish()


def finish():
    while win.history.undo_stack:
        win.do_undo()
    check("undo restores the project", project.dumps(win.proj) == original)
    win.dirty = False
    app.quit()


QTimer.singleShot(800, run)
app.exec()
win.player.shutdown()
print("ALL OK" if checks and all(checks) else "SOME CHECKS FAILED", flush=True)
