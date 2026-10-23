"""Headless check of waveforms and track controls through real mouse events.

  python tools/smoke_audio.py PROJECT.tesetoa.json out/
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
from PySide6.QtWidgets import QApplication  # noqa: E402

from tesetoa import audiomix, project  # noqa: E402
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


def audio_rows():
    return [i for i, t in enumerate(tl.rows) if t["kind"] == "audio"]


def wait(cond, then, limit=60.0, t0=None):
    t0 = t0 or time.time()
    if cond():
        then()
    elif time.time() - t0 > limit:
        check("timed out waiting", False)
        finish()
    else:
        QTimer.singleShot(100, lambda: wait(cond, then, limit, t0))


def waves_drawn():
    tl.repaint()
    return len(tl._waves) > 0


def step_waves():
    check(f"waveforms drawn ({len(tl._waves)} clips)", True)
    tl.grab().save(os.path.join(out, "audio_waveforms.png"))
    # click the mute button of the first audio track
    i = audio_rows()[0]
    flag, r = tl.header_buttons(i)[0]
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, r.center().toPoint())
    app.processEvents()
    tr = tl.rows[i]
    srcs = [s.clip["id"] for s in audiomix.sources(win.proj["tracks"])]
    check(f"{flag} button muted '{tr['name']}'",
          flag == "muted" and tr.get("muted") and not any(c["id"] in srcs for c in tr["clips"]))
    # solo the second one: only it sounds
    j = audio_rows()[1]
    flag, r = tl.header_buttons(j)[1]
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, r.center().toPoint())
    app.processEvents()
    ids = {c["id"] for c in tl.rows[j]["clips"]}
    srcs = audiomix.sources(win.proj["tracks"])
    check(f"solo leaves only '{tl.rows[j]['name']}' sounding ({len(srcs)} sources)",
          flag == "solo" and srcs and all(s.clip["id"] in ids for s in srcs))
    # hide the top picture track
    flag, r = tl.header_buttons(0)[0]
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, r.center().toPoint())
    app.processEvents()
    check("eye button hid the top picture track", flag == "hidden" and tl.rows[0].get("hidden"))
    tl.grab().save(os.path.join(out, "audio_tracks.png"))

    # drag the last audio clip of the bottom row below it: a new audio track
    k = audio_rows()[-1]
    c = tl.rows[k]["clips"][-1]
    n0 = len(win.proj["tracks"])
    tl.scroll_s = max(0.0, c["start_us"] / US - 1)
    tl.update()
    x = round(tl._x((c["start_us"] + c["duration_us"] / 2) / US))
    y = round(tl.tops[k] + tl.row_h(k) / 2)
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    for s in range(1, 8):
        QTest.mouseMove(tl, QPoint(x, y + s * 8))
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x, y + 56))
    app.processEvents()
    last = win.proj["tracks"][-1]
    check(f"dragging below the last row made a new audio track ({n0} -> {len(win.proj['tracks'])})",
          len(win.proj["tracks"]) == n0 + 1 and last["kind"] == "audio" and last["clips"][0]["id"] == c["id"])

    # track menu actions
    tl.trackAction.emit("add:audio", last["id"])
    tl.trackAction.emit("up", last["id"])
    check("add / move track from the header menu",
          len(win.proj["tracks"]) == n0 + 2 and win.proj["tracks"][-2]["id"] == last["id"])
    finish()


def finish():
    while win.history.undo_stack:
        win.do_undo()
    check("undo restores the project", json.dumps(win.proj, sort_keys=True) == original)
    win.dirty = False
    app.quit()


QTimer.singleShot(500, lambda: wait(waves_drawn, step_waves))
app.exec()
win.player.shutdown()
print("ALL OK" if checks and all(checks) else "SOME CHECKS FAILED", flush=True)
