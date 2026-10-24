"""Headless check of the volume line, snapping toggle, clip clicks, level meter and master
volume, through real mouse / keyboard events.

  python tools/smoke_volume.py PROJECT.tesetoa.json out/
"""
import math
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

from tesetoa import curves, edit, project  # noqa: E402
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
checks, state, peaks = [], {}, []
win.player.worker.levels.connect(lambda l, r: peaks.append(max(l, r)))
T0 = time.time()


def say(m):
    print(f"{time.time() - T0:5.1f}s  {m}", flush=True)


def check(name, ok):
    checks.append(bool(ok))
    say(f"{'OK  ' if ok else 'FAIL'} {name}")


def show_row(i):
    tl.vbar.setValue(tl.scroll_y + round(tl.tops[i]) - tl.vbar.y() - 4)
    app.processEvents()


def db(g):
    return 20 * math.log10(g)


def run():
    # a voice clip (static volume) on the second audio track
    rows = [i for i, t in enumerate(tl.rows) if t["kind"] == "audio"]
    row = rows[1]
    show_row(row)
    voice = tl.rows[row]["clips"][0]
    tl.px_per_s, tl.scroll_s = 100.0, voice["start_us"] / US - 0.5
    tl.update()
    v0 = curves.value(voice.get("volume", 1.0), 0)
    band = tl._vol_band(voice, row)
    x = round(tl._x((voice["start_us"] + voice["duration_us"] / 2) / US))
    y = round(tl._vol_y(v0, band))
    check(f"a volume line is drawn on the voice clip at {db(v0):+.1f} dB", tl._vol_hit(QPoint(x, y)) is not None)
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    QTest.mouseMove(tl, QPoint(x, y - 2))
    QTest.mouseMove(tl, QPoint(x, y - 4))
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x, y - 4))
    app.processEvents()
    v1 = edit.find(win.proj, voice["id"])[1]["volume"]
    want = db(v0) + 4 / (band[1] - band[0]) * 60
    check(f"dragging it up 4 px raised the volume {db(v0):+.1f} -> {db(v1):+.1f} dB (want {want:+.1f})",
          not isinstance(v1, dict) and abs(db(v1) - want) < 0.3)

    # the music has volume keyframes: dragging its line moves them all together
    row2 = rows[0]
    show_row(row2)
    c = tl.rows[row2]["clips"][0]
    tl.px_per_s = 400.0
    tl.scroll_s = c["start_us"] / US + 19.8
    tl.update()
    band = tl._vol_band(c, row2)
    keys0 = [k[1] for k in c["volume"]["keys"]]
    t_mid = 20 * US
    x = round(tl._x((c["start_us"] + t_mid) / US))
    y = round(tl._vol_y(curves.value(c["volume"], t_mid), band))
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    for s in range(1, 4):
        QTest.mouseMove(tl, QPoint(x, y + 2 * s))
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x, y + 6))
    app.processEvents()
    c = edit.find(win.proj, c["id"])[1]
    ratios = {round(db(a / b), 2) for a, b in zip([k[1] for k in c["volume"]["keys"]], keys0) if a > 1e-4 and b > 1e-4}
    check(f"dragging a keyframed line scaled all {len(keys0)} keys by the same {ratios} dB",
          len(ratios) == 1 and next(iter(ratios)) < -1)
    win.do_undo()
    c = edit.find(win.proj, c["id"])[1]
    k0 = next(k for k in c["volume"]["keys"] if k[0] >= 20 * US and k[1] < 2)
    # drag the first keyframe point up
    kx, ky = round(tl._x((c["start_us"] + k0[0]) / US)), round(tl._vol_y(k0[1], band))
    hit = tl._vol_hit(QPoint(kx, ky))
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(kx, ky))
    QTest.mouseMove(tl, QPoint(kx, ky - 5))
    QTest.mouseMove(tl, QPoint(kx, ky - 10))
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(kx, ky - 10))
    app.processEvents()
    k1 = next(k for k in edit.find(win.proj, c["id"])[1]["volume"]["keys"] if k[0] == k0[0])
    check(f"a keyframe point on the line is dragged on its own ({db(k0[1]):+.1f} -> {db(k1[1]):+.1f} dB, time kept)",
          hit is not None and hit[0] == "volkey" and k1[1] > k0[1] and k1[0] == k0[0])
    win.grab().save(os.path.join(out, "volume_line.png"))

    # clicking a clip selects it and leaves the playhead and the view alone
    win.seek(60)
    QTimer.singleShot(300, step_click)


def step_click():
    tl.px_per_s, tl.scroll_s = 40.0, 100.0
    tl.update()
    row = next(i for i, t in enumerate(tl.rows) if t["name"] == "text 3")
    show_row(row)
    c = tl.rows[row]["clips"][0]
    x = round(tl._x((c["start_us"] + c["duration_us"] / 2) / US))
    y = round(tl.tops[row] + 8)
    QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    QTimer.singleShot(300, lambda: step_click_check(c))


def step_click_check(c):
    check(f"clicking a clip selected it; playhead stayed at {win.pos}, view at {tl.scroll_s:.0f}s",
          tl.selected_id == c["id"] and win.pos == 60 and tl.scroll_s == 100.0)
    # snapping off: a move lands exactly where it is dropped
    win.snap_btn.setChecked(False)
    tl.setFocus()
    QTest.keyClick(win, Qt.Key_N)
    check("N toggles snapping back on", win.snap_btn.isChecked() and tl.snapping)
    QTest.keyClick(win, Qt.Key_N)
    row = next(i for i, t in enumerate(tl.rows) if t["name"] == "text 3")
    c = tl.rows[row]["clips"][-1]
    want = c["start_us"] + 3 * US
    snapped = tl._snap(c["start_us"] + c["duration_us"] + 2, c)
    tl.snapping = True
    snapped_on = tl._snap(c["start_us"] + c["duration_us"] + 2, None)
    tl.snapping = win.snap_btn.isChecked()
    check(f"with 吸附 off nothing snaps ({snapped - c['start_us'] - c['duration_us']} us off an edge), "
          f"with it on it does ({snapped_on - c['start_us'] - c['duration_us']})",
          not tl.snapping and snapped != snapped_on)
    win.snap_btn.setChecked(True)
    state["want"] = want
    # the meter follows playback, the fader is the master volume
    win.seek(round(12 * win.fps))
    QTimer.singleShot(300, lambda: (peaks.clear(), win.toggle_play(), QTimer.singleShot(800, step_meter)))


def step_meter():
    win.toggle_play()
    loud = max(peaks) if peaks else 0
    check(f"the meter got {len(peaks)} levels while playing (peak {db(max(loud, 1e-6)):+.1f} dB)",
          len(peaks) > 20 and loud > 0.01)
    check(f"the meter shows it ({win.meter.bars.hold[0]:+.1f} dB held)", win.meter.bars.hold[0] > -40)
    undo0 = len(win.history.undo_stack)
    fd = win.meter.fader
    fd.setSliderDown(True)
    for v in (-20, -40, -60):
        fd.setValue(v)
    fd.setSliderDown(False)
    fd.sliderReleased.emit()
    app.processEvents()
    g = win.proj.get("master_gain")
    check(f"dragging the fader to -6 dB set the master volume to {g} in one undo step "
          f"(mixer {win.player.worker.mixer.master:.3f}, label {win.meter.db_lbl.text()})",
          g is not None and abs(db(g) + 6) < 0.05 and len(win.history.undo_stack) == undo0 + 1
          and abs(win.player.worker.mixer.master - g) < 1e-6)
    win.do_undo()
    app.processEvents()
    check("undo puts the fader back at 0 dB", win.meter.fader.value() == 0 and "master_gain" not in win.proj)
    win.grab().save(os.path.join(out, "volume_meter.png"))
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
