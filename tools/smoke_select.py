"""Headless check of timeline multi-select, group moves, track heights and the compound list.

  python tools/smoke_select.py PROJECT.tesetoa.json out/
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
original = json.dumps(win.proj, sort_keys=True)
tl = win.timeline
checks = []
T0 = time.time()


def say(m):
    print(f"{time.time() - T0:5.1f}s  {m}", flush=True)


def check(name, ok):
    checks.append(bool(ok))
    say(f"{'OK  ' if ok else 'FAIL'} {name}")


def row_of(name):
    return next(i for i, t in enumerate(tl.rows) if t["name"] == name)


def show_row(i):
    tl.vbar.setValue(tl.scroll_y + round(tl.tops[i]) - tl.vbar.y() - 4)
    app.processEvents()


def mid(c, i):
    return QPoint(round(tl._x((c["start_us"] + c["duration_us"] / 2) / US)), round(tl.tops[i] + tl.row_h(i) / 2))


def wheel(widget, at, mods):
    ev = QWheelEvent(QPointF(at), QPointF(widget.mapToGlobal(at)), QPoint(), QPoint(0, 120),
                     Qt.NoButton, mods, Qt.NoScrollPhase, False)
    app.sendEvent(widget, ev)
    app.processEvents()


def run():
    # Ctrl+click on the two long clips of "text 3" and an image below, then drag them as one
    k = row_of("text 3")
    v = row_of("video 1")
    show_row(k)
    tl.px_per_s = 8.0
    tl.scroll_s = 100.0
    tl.update()
    t3 = tl.rows[k]["clips"]
    img = next(c for c in tl.rows[v]["clips"] if c["start_us"] + c["duration_us"] > 200 * US)
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, mid(t3[0], k))
    QTest.mouseClick(tl, Qt.LeftButton, Qt.ControlModifier, mid(t3[1], k))
    QTest.mouseClick(tl, Qt.LeftButton, Qt.ShiftModifier, mid(img, v))
    app.processEvents()
    ids = {t3[0]["id"], t3[1]["id"], img["id"]}
    check(f"Ctrl/Shift+click selected {len(tl.selected_ids)} clips", tl.selected_ids == ids)
    QTest.mouseClick(tl, Qt.LeftButton, Qt.ControlModifier, mid(img, v))
    check("Ctrl+click again removes one", tl.selected_ids == ids - {img["id"]})
    before = {c["id"]: c["start_us"] for c in t3}
    undo0 = len(win.history.undo_stack)
    a = mid(t3[1], k)
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, a)
    for s in range(1, 5):
        QTest.mouseMove(tl, a + QPoint(10 * s, 0))
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, a + QPoint(40, 0))
    app.processEvents()
    moved = {cid: edit.find(win.proj, cid)[1]["start_us"] - s0 for cid, s0 in before.items()}
    check(f"group drag moved both by {set(round(m / 1000) for m in moved.values())} ms in one undo step",
          len(set(moved.values())) == 1 and abs(next(iter(moved.values())) - 5 * US) < 0.3 * US
          and len(win.history.undo_stack) == undo0 + 1)
    win.do_undo()

    i = row_of("text 5")
    show_row(i)
    tl.px_per_s, tl.scroll_s = 40.0, 0.0
    tl.update()
    clips = tl.rows[i]["clips"][:4]

    # box select across two rows from empty space
    j = i + 1
    y0, y1 = tl.tops[i] + 4, tl.tops[j] + tl.row_h(j) - 4
    x0 = tl._x(clips[0]["start_us"] / US) - 2
    x1 = tl._x((clips[3]["start_us"] + clips[3]["duration_us"]) / US) + 1
    gap = next(x for x in range(int(x0) - 1, 140, -1) if tl._hit(QPointF(x, y0))[1] is None)
    t_lo, t_hi = tl._sec(gap) * US, tl._sec(x1) * US     # (the view may follow the playhead later)
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(gap, round(y0)))
    QTest.mouseMove(tl, QPoint(round((gap + x1) / 2), round(y1)))
    QTest.mouseMove(tl, QPoint(round(x1), round(y1)))
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(round(x1), round(y1)))
    app.processEvents()
    in_rows = {c["id"] for r in (i, j) for c in tl.rows[r]["clips"]
               if c["start_us"] <= t_hi and c["start_us"] + c["duration_us"] >= t_lo}
    check(f"selection box picked {len(tl.selected_ids)} clips on two rows",
          tl.selected_ids == in_rows and len({id(r) for r in (i, j)}) == 2 and len(in_rows) >= 4)
    win.grab().save(os.path.join(out, "select_box.png"))

    # the inspector with three text clips: shared values shown, differing ones "--"
    trio = [edit.find(win.proj, cid)[1] for cid in ("c43", "c44", "c45")]
    tl.set_selection({c["id"] for c in trio}, "c43")
    app.processEvents()
    ins = win.inspector
    sx, ss = ins.widgets[("transform", "x")], ins.widgets[("transform", "scale")]
    check(f"inspector: shared X shows '{sx.text()}', differing scale shows '{ss.text()}'",
          sx.text() == "0.000" and ss.text() == "--" and "3 個片段" in ins.widgets["類型"].text())
    undo0 = len(win.history.undo_stack)

    def type_into(spin, text):
        spin.setFocus()
        spin.lineEdit().selectAll()
        QTest.keyClicks(spin.lineEdit(), text)
        QTest.keyClick(spin.lineEdit(), Qt.Key_Return)
        ins._flush()
        app.processEvents()

    type_into(ss, "1.5")
    scales = [edit.find(win.proj, c["id"])[1]["transform"]["scale"] for c in trio]
    check(f"typing 1.5 over '--' set all three ({scales}) in one undo step",
          scales == [1.5] * 3 and len(win.history.undo_stack) == undo0 + 1)
    win.do_undo()
    tl.set_selection({c["id"] for c in trio}, "c43")
    app.processEvents()
    hidden = round(ss.value(), 3)
    type_into(ss, f"{hidden}")
    scales = [round(edit.find(win.proj, c["id"])[1]["transform"]["scale"], 3) for c in trio]
    check(f"typing the number hidden behind '--' ({hidden}) still sets all", scales == [hidden] * 3)
    win.do_undo()
    win.timeline.setFocus()
    QTest.keyClick(win, Qt.Key_D, Qt.ControlModifier)
    app.processEvents()
    check("Ctrl+D clears the selection", not tl.selected_ids and tl.selected is None)
    tl.set_selection({c["id"] for c in trio}, "c43")

    # Delete removes the whole selection; undo brings it back
    n = len(tl.selected_ids)
    total = sum(len(t["clips"]) for t in win.proj["tracks"])
    win.do_delete()
    app.processEvents()
    check(f"Delete removed the {n} selected clips",
          sum(len(t["clips"]) for t in win.proj["tracks"]) == total - n)
    win.do_undo()

    # vertical zoom: Alt+wheel and the slider; dragging a header edge
    h0 = tl.row_h(i)
    wheel(tl, QPoint(400, round(tl.tops[i]) + 5), Qt.AltModifier)
    h1 = tl.row_h(i)
    check(f"Alt+wheel made tracks taller ({h0} -> {h1} px), slider follows ({win.vzoom.value()}%)",
          h1 > h0 and abs(win.vzoom.value() - round(tl.vzoom * 100)) <= 1)
    win.vzoom.setValue(60 + 40)
    win.vzoom.setValue(200)
    check(f"slider at 200% gives {tl.row_h(i)} px rows", abs(tl.row_h(i) - 68) <= 1)
    show_row(i)
    edge = QPoint(60, round(tl.tops[i] + tl.row_h(i) - 1))
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, edge)
    QTest.mouseMove(tl, edge + QPoint(0, 20))
    QTest.mouseMove(tl, edge + QPoint(0, 40))
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, edge + QPoint(0, 40))
    other = tl.row_h(j)
    check(f"dragging the header edge resized only that track ({tl.row_h(i)} px, next stays {other})",
          abs(tl.row_h(i) - 108) <= 1 and other == 68)
    v0, s0, z0 = tl.scroll_y, tl.scroll_s, tl.px_per_s
    wheel(tl, QPoint(600, 300), Qt.NoModifier)
    wheel(tl, QPoint(600, 300), Qt.NoModifier)
    check(f"wheel scrolls the tracks up / down only ({v0} -> {tl.scroll_y})",
          tl.scroll_y != v0 and tl.scroll_s == s0 and tl.px_per_s == z0)
    tl.scroll_s = s0 = 30.0
    wheel(tl, QPoint(600, 300), Qt.ShiftModifier)
    check(f"Shift+wheel scrolls left / right ({s0} -> {tl.scroll_s:.1f} s)", tl.scroll_s < s0 and tl.px_per_s == z0)
    at = tl._sec(600)
    wheel(tl, QPoint(600, 300), Qt.ControlModifier)
    check(f"Ctrl+wheel zooms time around the mouse ({z0} -> {tl.px_per_s} px/s)",
          tl.px_per_s > z0 and abs(tl._sec(600) - at) < 1e-6)
    v0, s0 = tl.scroll_y, tl.scroll_s
    QTest.mousePress(tl, Qt.MiddleButton, Qt.NoModifier, QPoint(700, 300))
    QTest.mouseMove(tl, QPoint(650, 280))
    QTest.mouseMove(tl, QPoint(600, 260))
    QTest.mouseRelease(tl, Qt.MiddleButton, Qt.NoModifier, QPoint(600, 260))
    check(f"middle-drag pans the view ({s0:.1f} -> {tl.scroll_s:.1f} s, {v0} -> {tl.scroll_y} px)",
          tl.scroll_s > s0 and tl.scroll_y != v0)
    win.grab().save(os.path.join(out, "select_tall.png"))

    # the compound browser: one row per shared compound, its uses under it
    win.left.setCurrentWidget(win.compounds)
    tree = win.compounds.tree
    rows = [tree.topLevelItem(k) for k in range(tree.topLevelItemCount())]
    check(f"compound browser lists {len(rows)} shared compounds", len(rows) == len(win.proj["compounds"]))
    nested = next(r for r in rows if r.childCount() and r.child(0).data(0, Qt.UserRole)[2])
    win.compounds._double(nested.child(0), 0)
    app.processEvents()
    check(f"double-clicking a nested use opened it ({len(win.path_ids)} levels deep)", len(win.path_ids) == 2)
    rows = [tree.topLevelItem(k) for k in range(tree.topLevelItemCount())]     # (rebuilt on opening)
    top = next(r for r in rows if r.childCount() and not r.child(0).data(0, Qt.UserRole)[2])
    win.compounds._clicked(top.child(0), 0)
    app.processEvents()
    check("clicking a use went back to the main timeline with that compound selected",
          win.path_ids == [] and tl.selected is not None and tl.selected["type"] == "compound")
    finish()


def finish():
    while win.history.undo_stack:
        win.do_undo()
    check("undo restores the project", json.dumps(win.proj, sort_keys=True) == original)
    win.dirty = False
    app.quit()


QTimer.singleShot(800, run)
app.exec()
win.player.shutdown()
print("ALL OK" if checks and all(checks) else "SOME CHECKS FAILED", flush=True)
