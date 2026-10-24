"""Headless check of shared compounds, timeline keyframe dragging and the time selection.

  python tools/smoke_reuse.py PROJECT.kiasecut.json out/
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
from PySide6.QtGui import QDropEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import edit, project  # noqa: E402
from kiasecut.ui.main_window import STYLE, MainWindow  # noqa: E402
from kiasecut.ui.timeline import US  # noqa: E402

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
checks, state = [], {}
T0 = time.time()


def say(m):
    print(f"{time.time() - T0:5.1f}s  {m}", flush=True)


def check(name, ok):
    checks.append(bool(ok))
    say(f"{'OK  ' if ok else 'FAIL'} {name}")


def kid_named(name):
    return next(k for k, v in win.proj["compounds"].items() if v.get("name") == name)


def instances(kid):
    return [c for _, _, c in project.compound_uses(win.proj)[kid]]


def linked():
    """Every compound clip points at its shared entry (the same dict)."""
    return all(c["compound"] is win.proj["compounds"][c["compound_id"]]
               for uses in project.compound_uses(win.proj).values() for _, _, c in uses)


def run():
    tree = win.compounds.tree
    win.left.setCurrentWidget(win.compounds)
    names = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
    tic = kid_named("TextInvColor")
    check(f"browser lists the shared compounds: {names}",
          len(names) == len(win.proj["compounds"]) + len(win.proj["timelines"])
          and any(n.endswith("TextInvColor  ×5") for n in names))

    # drag TextInvColor from the browser onto the timeline (a real drop event)
    it = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
              if tree.topLevelItem(i).data(0, Qt.UserRole) == ("def", tic))
    md = tree.mimeData([it])
    tl.px_per_s, tl.scroll_s = 10.0, 0.0
    at = QPointF(tl._x(150.0), tl.rows_end + 10)               # empty space: a new track
    ev = QDropEvent(at, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    tl.dropEvent(ev)                                         # (Qt drops need a real drag)
    app.processEvents()
    uses = instances(tic)
    new = tl.selected
    check(f"dropping it placed a 6th clip showing the same compound at {new['start_us'] / US:.1f}s",
          len(uses) == 6 and new["compound"] is win.proj["compounds"][tic] and abs(new["start_us"] - 150 * US) < US)

    # edit inside one clip: every clip showing it changes
    win.enter_compound(uses[0]["id"])
    app.processEvents()
    inner = next(c for t in win.container()["tracks"] for c in t["clips"] if c["type"] == "text")
    win.apply("修改文字", lambda lvl: edit.set_text(lvl, inner["id"], content="共用測試"))
    win.leave_compound()
    app.processEvents()
    seen = {next(k["text"]["content"] for t in c["compound"]["tracks"] for k in t["clips"] if k["id"] == inner["id"])
            for c in instances(tic)}
    check(f"an edit inside one shows in all {len(instances(tic))} ({seen})", seen == {"共用測試"})
    win.do_undo()
    check("undo relinks the shared compound", linked() and len(instances(tic)) == 6)

    # a compound cannot be placed inside itself
    win.enter_compound(uses[0]["id"])
    n0 = sum(len(t["clips"]) for t in win.container()["tracks"])
    win.place_compound(tic, "", 0)
    check("dropping a compound into itself is refused",
          sum(len(t["clips"]) for t in win.container()["tracks"]) == n0)
    win.leave_compound()

    # make one clip independent
    c = instances(tic)[1]
    tl.select(c)
    tl.clipAction.emit("unique", c["id"])
    app.processEvents()
    c = edit.find(win.proj, c["id"])[1]
    check(f"設為獨立 gives it its own compound ({c['compound_id']}, {win.proj['compounds'][c['compound_id']]['name']})",
          c["compound_id"] != tic and len(instances(tic)) == 5 and c["compound"] is not win.proj["compounds"][tic])

    # save / load keeps the sharing
    path = os.path.join(out, "reuse_test.kiasecut.json")
    project.save(win.proj, path)
    back = project.load(path)
    check("save / load keeps one shared entry per compound",
          project.dumps(back) == project.dumps(win.proj)
          and len({id(c["compound"]) for _, _, c in project.compound_uses(back)[tic]}) == 1)
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    check("on disk clips hold only compound_id", all("compound" not in c for tl in raw["timelines"] for t in tl["tracks"] for c in t["clips"])
          and "tracks" not in raw)
    step_timelines()


def step_timelines():
    # a second timeline: new tab, its own tracks, the shared compounds usable there too
    tabs = win.tl_tabs
    first = win.proj["active_timeline"]
    n_tracks = len(win.proj["tracks"])
    win.apply_root("新增時間線", edit.add_timeline)
    app.processEvents()
    second = win.proj["active_timeline"]
    check(f"新增時間線 opened a second, empty timeline (tabs {[tabs.tabText(i) for i in range(tabs.count())]})",
          tabs.count() == 2 and second != first and tabs.tabData(tabs.currentIndex()) == second
          and all(not t["clips"] for t in win.proj["tracks"]) and len(tl.rows) == 2)
    tic = kid_named("TextInvColor")
    win.place_compound(tic, "", 2 * US)
    uses = project.compound_uses(win.proj)[tic]
    check(f"a shared compound placed on it is used on both timelines ({len(uses)} uses)",
          {u[0] for u in uses} == {first, second})
    tabs.setCurrentIndex(0)
    app.processEvents()
    check("clicking the first tab switches back to it",
          win.proj["active_timeline"] == first and len(win.proj["tracks"]) == n_tracks
          and win.proj["tracks"] is project.timeline(win.proj)["tracks"])
    win.do_undo()                                   # the placing on the second timeline
    win.do_undo()                                   # the new timeline
    check("undo removes it again", len(win.proj["timelines"]) == 1 and tabs.count() == 1)
    step_keys()


def step_keys():
    # drag a keyframe diamond of the selected clip: every keyframe at that time moves
    c = next(c for t in win.proj["tracks"] for c in t["clips"]
             if c["type"] == "text" and c["text"]["content"] == "傻逼對話記錄")
    tl.select(c)
    k0 = edit.key_times(c)[0]
    tl.px_per_s = 200.0
    tl.scroll_s = (c["start_us"] + k0) / US - 2
    row = next(i for i, t in enumerate(tl.rows) if c in t["clips"])
    tl.vbar.setValue(tl.scroll_y + round(tl.tops[row]) - tl.vbar.y() - 4)
    app.processEvents()
    x = round(tl._x((c["start_us"] + k0) / US))
    y = round(tl.tops[row] + 3 + tl.row_h(row) - 8 - 5)
    undo0 = len(win.history.undo_stack)
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    for s in range(1, 5):
        QTest.mouseMove(tl, QPoint(x - 10 * s, y))
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x - 40, y))
    app.processEvents()
    c = edit.find(win.proj, c["id"])[1]
    xs, ys = c["transform"]["x"]["keys"][0][0], c["transform"]["y"]["keys"][0][0]
    want = k0 - 0.2 * US
    check(f"dragging the ◆ moved the x and y keys {k0 / US:.3f} -> {xs / US:.3f}s together, one undo step",
          xs == ys and abs(xs - want) <= US / 60 and len(win.history.undo_stack) == undo0 + 1)
    step_region()


def step_region():
    # right-drag on the tracks selects time; playback loops inside it
    tl.px_per_s, tl.scroll_s = 40.0, 0.0
    tl.update()
    y = round(tl.tops[0] + tl.row_h(0) / 2)
    a, b = QPoint(round(tl._x(10.0)), y), QPoint(round(tl._x(10.5)), y)
    QTest.mousePress(tl, Qt.RightButton, Qt.NoModifier, a)
    QTest.mouseMove(tl, (a + b) / 2)
    QTest.mouseMove(tl, b)
    QTest.mouseRelease(tl, Qt.RightButton, Qt.NoModifier, b)
    app.processEvents()
    state["loop"] = win.player.worker.loop
    check(f"right-drag selected frames {tl.mark_in}..{tl.mark_out}, loop {state['loop']}",
          tl.mark_in is not None and abs(tl.mark_in - 600) <= 4 and abs(tl.mark_out - 629) <= 4
          and state["loop"] == (tl.mark_in, tl.mark_out))
    win.grab().save(os.path.join(out, "reuse_region.png"))
    win.seek(0)
    QTimer.singleShot(300, lambda: (win.toggle_play(), QTimer.singleShot(1500, step_loop_check)))


def step_loop_check():
    a, b = state["loop"]
    pos = win.pos
    win.toggle_play()
    check(f"playback jumped into the selection and loops there (at {pos} after 1.5 s)", a <= pos <= b)
    tl.setFocus()
    QTest.keyClick(win, Qt.Key_D, Qt.ControlModifier | Qt.ShiftModifier)
    app.processEvents()
    check("Ctrl+Shift+D clears the selection and the loop",
          tl.mark_in is None and tl.mark_out is None and win.player.worker.loop is None)
    QTimer.singleShot(300, finish)


def finish():
    while win.history.undo_stack:
        win.do_undo()
    check("undo restores the project", project.dumps(win.proj) == original and linked())
    win.dirty = False
    app.quit()


QTimer.singleShot(800, run)
app.exec()
win.player.shutdown()
print("ALL OK" if checks and all(checks) else "SOME CHECKS FAILED", flush=True)
