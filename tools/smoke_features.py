"""Headless check of the library / compound / preview-drag / range-export features.

  python tools/smoke_features.py out/AlianShit.tesetoa.json out/ MEDIA_IMAGE MEDIA_AUDIO
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QColorDialog, QInputDialog  # noqa: E402

from tesetoa import build, curves, edit, library, project  # noqa: E402
from tesetoa.client import EngineClient  # noqa: E402
from tesetoa.ui.main_window import STYLE, MainWindow  # noqa: E402
from tesetoa.ui.timeline import US  # noqa: E402

proj_path, out, img_path, audio_path = sys.argv[1:5]
# dialogs would block a headless run: answer them
QInputDialog.getText = staticmethod(lambda *a, **k: ("測試名稱", True))
QColorDialog.getColor = staticmethod(lambda *a, **k: QColor("#ff3366"))

app = QApplication(sys.argv)
app.setStyleSheet(STYLE)
win = MainWindow()
win.resize(1600, 940)
win.show()
win.path = proj_path
win.set_project(project.load(proj_path))
loads, frames, checks = [0], [], []
win.player.worker.loaded.connect(lambda _: loads.__setitem__(0, loads[0] + 1))
win.player.worker.frameReady.connect(lambda img, pos: frames.append((time.time(), pos)))
win.player.worker.failed.connect(lambda m: print("FAILED", m, flush=True))
T0 = time.time()
state = {"i": 0, "mark": None}
_seek = win.seek


def tracked_seek(frame):
    state["want"] = frame
    _seek(frame)


win.seek = tracked_seek


def say(msg):
    print(f"{time.time() - T0:6.1f}s  {msg}", flush=True)


def check(name, ok):
    checks.append(bool(ok))
    say(f"{'OK  ' if ok else 'FAIL'} {name}")


def first(pred, tracks=None):
    for tr in tracks or win.container()["tracks"]:
        for c in tr["clips"]:
            if pred(c):
                return c
    raise SystemExit("clip not found")


def s_names():
    tid = win.container()["tracks"][0]["id"]
    win.on_track_action("rename", tid)
    win.on_track_action("color", tid)
    c = win.container()["tracks"][0]["clips"][0]
    win.on_clip_action("rename", c["id"])
    win.on_clip_action("color", c["id"])
    t = win.container()["tracks"][0]
    check("track renamed and coloured", t["name"] == "測試名稱" and t["color"] == "#ff3366")
    check("clip renamed and coloured", t["clips"][0]["name"] == "測試名稱" and t["clips"][0]["color"] == "#ff3366")


def s_wheel():
    win.timeline.select(first(lambda c: c["type"] == "text"))
    spin = win.inspector.widgets[("transform", "x")]
    before = spin.value()
    ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                     Qt.NoScrollPhase, False)
    QApplication.sendEvent(spin, ev)
    check("wheel does not change a number field", spin.value() == before)


def s_enter():
    comp = first(lambda c: c["type"] == "compound" and c["start_us"] > 117 * US)
    state["comp"] = comp["id"]
    win.timeline.select(comp)
    win.seek(round((comp["start_us"] / US + 0.5) * win.fps))


def s_enter2():
    win.on_clip_action("enter", state["comp"])


def s_inside():
    check("inside the compound: breadcrumb shown", "TextInvColor" in win.crumb.text())
    inner = win.container()["tracks"]
    check("timeline shows the compound's tracks", win.timeline.rows and win.timeline.rows[-1] in inner)
    win.grab().save(os.path.join(out, "feat_compound.png"))
    c = first(lambda c: c["type"] == "text")
    state["inner_text"] = c["id"]
    win.apply("修改文字", lambda lvl: edit.set_text(lvl, c["id"], content="複合內改字"))


def s_leave():
    win.leave_compound()


def s_left():
    comp = first(lambda c: c["id"] == state["comp"], win.proj["tracks"])
    inner = first(lambda c: c["id"] == state["inner_text"], comp["compound"]["tracks"])
    check("edit inside the compound is in the project", inner["text"]["content"] == "複合內改字")
    check("back on the main timeline", not win.path_ids and win.crumb.text() == "")


def s_library():
    win.apply_root("新資料夾", library.add_folder, "測試資料夾", None)
    f = next(x for x in library.lib(win.proj)["folders"] if x["name"] == "測試資料夾")
    probes = {p.replace("\\", "/"): library.probe(p) for p in (img_path, audio_path)}
    win.apply_root("匯入素材", library.add_files, list(probes), f["id"], probes)
    items = [i for i in library.lib(win.proj)["items"] if i["folder"] == f["id"]]
    check(f"two files imported into the folder ({[i['kind'] for i in items]})", len(items) == 2)
    img = next(i for i in items if i["kind"] == "image")
    n = sum(len(t["clips"]) for t in win.proj["tracks"])
    win.place_media(img["id"], "", 5 * US)
    check("library image placed on the timeline", sum(len(t["clips"]) for t in win.proj["tracks"]) == n + 1)
    check("library panel lists the folder", any(
        win.library.tree.topLevelItem(i).text(0) == "測試資料夾" for i in range(win.library.tree.topLevelItemCount())))


def s_text_keys():
    c = first(lambda c: c["type"] == "text" and c["text"]["content"] == "傻逼對話記錄")
    state["tk"] = c["id"]
    win.timeline.select(c)
    win.seek(round((c["start_us"] / US + 1) * win.fps))


def s_text_keys2():
    win.inspector.widgets[("key", "text", "size")].click()


def s_text_keys3():
    c = first(lambda c: c["id"] == state["tk"])
    win.seek(round((c["start_us"] / US + 2) * win.fps))


def s_text_keys4():
    win.inspector.widgets[("text", "size")].setValue(5.0)


def s_text_keys5():
    c = first(lambda c: c["id"] == state["tk"])
    sz = c["text"]["size"]
    check("font size keyframed from the inspector",
          curves.is_animated(sz) and abs(curves.value(sz, 2 * US) - 5.0) < 1e-6)
    win.seek(round((c["start_us"] / US + 1.5) * win.fps))


def s_drag():
    """Drag the selected text to 4 screen px right of the canvas centre: it should snap to x = 0."""
    c = first(lambda c: c["id"] == state["tk"])
    pv = win.preview
    r = pv._rect()
    box = next(b for b in pv.visible_boxes() if b.clip["id"] == c["id"])
    sx = r.x() + box.cx / pv.W * r.width()
    sy = r.y() + box.cy / pv.H * r.height()
    tx = r.x() + r.width() / 2 + 4
    QTest.mousePress(pv, Qt.LeftButton, Qt.NoModifier, QPoint(round(sx), round(sy)))
    for k in range(1, 11):
        QTest.mouseMove(pv, QPoint(round(sx + (tx - sx) * k / 10), round(sy + 40 * k / 10)))
    state["guides"] = list(pv.guides)
    QTest.mouseRelease(pv, Qt.LeftButton, Qt.NoModifier, QPoint(round(tx), round(sy + 40)))


def s_drag_done():
    c = first(lambda c: c["id"] == state["tk"])
    x = curves.value(c["transform"]["x"], 1.5 * US)
    y = curves.value(c["transform"]["y"], 1.5 * US)
    check(f"preview drag snapped to the centre line (x={x:.4f}, y={y:.3f}, guides {state['guides']})",
          abs(x) < 1e-6 and any(g[0] == "x" for g in state["guides"]))
    win.grab().save(os.path.join(out, "feat_drag.png"))


def s_fullscreen():
    win.toggle_fullscreen()
    ok = win.fullscreen is not None
    win.toggle_fullscreen()
    check("fullscreen opens and closes", ok and win.fullscreen is None)


def s_range_export():
    win.pos = round(120 * win.fps)
    win.set_mark("in")
    win.pos = round(122 * win.fps)
    win.set_mark("out")
    a, b = win.timeline.mark_in, win.timeline.mark_out
    xml = build.build(json.loads(json.dumps(win.proj)), win.cache_dir(), os.path.join(out, "range.mlt"))
    eng = EngineClient(16, 16)
    try:
        eng.export(xml, os.path.join(out, "range.mp4"), crf=26, preset="veryfast", **{"in": a, "out": b})
    finally:
        eng.close()
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                os.path.join(out, "range.mp4")], capture_output=True, text=True).stdout)
    check(f"range export is {dur:.2f} s (marks {a}..{b})", abs(dur - (b - a + 1) / win.fps) < 0.1)


steps = [
    (s_names, "load"), (s_wheel, None), (s_enter, "seek"), (s_enter2, "load"), (s_inside, "load"),
    (s_leave, "load"), (s_left, None), (s_library, "load"), (s_text_keys, "seek"), (s_text_keys2, "load"),
    (s_text_keys3, "seek"), (s_text_keys4, "load"), (s_text_keys5, "seek"), (s_drag, "load"),
    (s_drag_done, None), (s_fullscreen, None), (s_range_export, None),
]


def tick():
    if state["mark"] is not None:
        kind, n0, t0 = state["mark"]
        if kind == "load" and not (loads[0] > n0 and frames and frames[-1][0] > t0 and not win.building):
            return
        if kind == "seek" and not (frames and frames[-1][0] > t0 and frames[-1][1] == state.get("want")):
            return
        state["mark"] = None
    if time.time() - T0 > 400:
        say(f"TIMEOUT at step {state['i']}")
    elif state["i"] < len(steps):
        if not (win.xml and loads[0] and frames):
            return
        fn, wait = steps[state["i"]]
        state["i"] += 1
        state["mark"] = (wait, loads[0], time.time()) if wait else None
        try:
            fn()
        except Exception as exc:                 # a crashing step is a failed check
            check(f"step {fn.__name__} raised {type(exc).__name__}: {exc}", False)
            state["mark"] = None
        return
    win.dirty = False
    app.quit()


timer = QTimer()
timer.timeout.connect(tick)
timer.start(30)
app.exec()
win.player.shutdown()
print("ALL OK" if checks and all(checks) else "SOME CHECKS FAILED", flush=True)
