"""Headless keyframe / mask smoke test through the real window.

  python tools/smoke_keys.py out/AlianShit.tesetoa.json out/

Animates a text's position with two keyframes set from the inspector, checks the
in-between frame, applies an easing preset, jumps between keyframes, changes a mask's
shape / inversion and keyframes its width, then undoes everything.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

import numpy as np  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tesetoa import curves, project  # noqa: E402
from tesetoa.ui.main_window import STYLE, MainWindow  # noqa: E402
from tesetoa.ui.timeline import US  # noqa: E402

proj_path, out = sys.argv[1], sys.argv[2]
app = QApplication(sys.argv)
app.setStyleSheet(STYLE)
win = MainWindow()
win.resize(1440, 900)
win.show()
win.path = proj_path
win.set_project(project.load(proj_path))
original = json.dumps(win.proj, sort_keys=True)     # as opened (the library may be filled in)
loads, frames, checks = [0], [], []
win.player.worker.loaded.connect(lambda _: loads.__setitem__(0, loads[0] + 1))
win.player.worker.frameReady.connect(lambda img, pos: frames.append((time.time(), pos)))
win.player.worker.failed.connect(lambda m: print("FAILED", m, flush=True))
T0 = time.time()
_seek = win.seek


def tracked_seek(frame):
    state["want"] = frame              # a "seek" step waits for exactly this frame
    _seek(frame)


win.seek = tracked_seek


def say(msg):
    print(f"{time.time() - T0:6.1f}s  {msg}", flush=True)


def clip_by(pred):
    for tr in win.proj["tracks"]:
        for c in tr["clips"]:
            if pred(c):
                return c
    raise SystemExit("clip not found")


def text_clip():
    return clip_by(lambda c: c["type"] == "text" and c["text"]["content"] == "傻逼對話記錄")


def white_clip():
    return clip_by(lambda c: c.get("mask") and c.get("media", {}).get("path", "").endswith("White.png"))


def frame_of(c, t_s):
    return round((c["start_us"] / US + t_s) * win.fps)


def ink_center():
    img = win.preview.img.convertToFormat(win.preview.img.Format.Format_Grayscale8)
    a = np.frombuffer(bytes(img.constBits()), np.uint8)[: img.width() * img.height()].reshape(img.height(), img.width())
    ys, xs = np.where(a > 30)
    return xs.mean() / img.width() if len(xs) else None


def check(name, ok):
    checks.append(bool(ok))
    say(f"{'OK  ' if ok else 'FAIL'} {name}")


# each step: (action, wait-for) ; wait-for is "seek" (a frame at the playhead) or "load"
def s_select():
    win.timeline.select(text_clip())
    win.seek(frame_of(text_clip(), 1.0))


def s_key1():
    win.inspector.widgets[("key", "transform", "x")].click()      # key at 1 s, current x


def s_seek2():
    win.seek(frame_of(text_clip(), 3.0))


def s_x2():
    win.inspector.widgets[("transform", "x")].setValue(0.6)      # adds a key at 3 s


def s_verify_keys():
    c = text_clip()
    keys = c["transform"]["x"]["keys"]
    at = {round(k[0] / US, 2) for k in keys}
    check("x keyframes added at 1 s and 3 s", {1.0, 3.0} <= at)
    check("value at 3 s is 0.6", abs(curves.value(c["transform"]["x"], 3 * US) - 0.6) < 1e-6)
    win.seek(frame_of(c, 2.0))


def s_mid():
    state["mid"] = ink_center()
    win.seek(frame_of(text_clip(), 1.0))


def s_start():
    state["start"] = ink_center()
    win.seek(frame_of(text_clip(), 3.0))


def s_end():
    a, m, b = state["start"], state["mid"], ink_center()
    x = text_clip()["transform"]["x"]
    check(f"text slides right (ink x {a:.3f} -> {m:.3f} -> {b:.3f}), x(2 s) = {curves.value(x, 2 * US):.3f}",
          a < m < b and abs(curves.value(x, 2 * US) - 0.3) < 1e-6)
    win.seek(frame_of(text_clip(), 1.0))


def s_ease():
    w = win.inspector.widgets["easing"]
    w.setCurrentIndex(w.findData("ease_in"))
    w.activated.emit(w.currentIndex())


def s_verify_ease():
    c = text_clip()
    check("ease-in starts slowly", curves.value(c["transform"]["x"], 2 * US) < 0.3)
    win.curves.keyJump.emit(1)                                   # (◀ ▶ live in the curve editor)


def s_jumped():
    c = text_clip()
    check("next keyframe jump lands on 3 s", abs(win.pos - frame_of(c, 3.0)) <= 1)
    c = white_clip()
    win.timeline.select(c)
    win.seek(frame_of(c, 1.5))


def s_mask_rect():
    win.side.setCurrentWidget(win.mask_panel.parentWidget().parentWidget())     # the 遮罩 tab
    w = win.mask_panel.widgets["mask_kind"]
    w.setCurrentIndex(w.findData("rectangle"))
    w.activated.emit(w.currentIndex())


def s_verify_rect():
    check("mask is now a rectangle", white_clip()["mask"]["kind"] == "rectangle")
    state["rect_img"] = win.preview.img.copy()
    win.grab().save(os.path.join(out, "keys_rect.png"))
    win.mask_panel.widgets["mask_invert"].click()


def s_verify_invert():
    check("mask inverted", white_clip()["mask"]["invert"] is True)
    win.mask_panel.widgets[("key", "mask", "w")].click()


def s_mask_seek():
    win.seek(frame_of(white_clip(), 2.5))


def s_mask_w():
    win.mask_panel.widgets[("mask", "w")].setValue(0.2)


def s_verify_mask_keys():
    c = white_clip()
    w = c["mask"]["w"]
    check(f"mask width keyframed: {w if not curves.is_animated(w) else [(round(k[0] / US, 2), round(k[1], 3)) for k in w['keys']]}",
          curves.is_animated(w) and {1.5, 2.5} <= {round(k[0] / US, 2) for k in w["keys"]}
          and abs(curves.value(w, 2.5 * US) - 0.2) < 1e-6)
    win.grab().save(os.path.join(out, "keys_mask.png"))
    while win.history.undo_stack:
        win.do_undo()


def s_verify_undo():
    check("undo restores the project", json.dumps(win.proj, sort_keys=True) == original)


state = {"i": 0, "mark": None}
steps = [
    (s_select, "seek"), (s_key1, "load"), (s_seek2, "seek"), (s_x2, "load"), (s_verify_keys, "seek"),
    (s_mid, "seek"), (s_start, "seek"), (s_end, "seek"), (s_ease, "load"), (s_verify_ease, "seek"),
    (s_jumped, "seek"), (s_mask_rect, "load"), (s_verify_rect, "load"), (s_verify_invert, "load"),
    (s_mask_seek, "seek"), (s_mask_w, "load"), (s_verify_mask_keys, "load"), (s_verify_undo, None),
]


def tick():
    if time.time() - state.setdefault("beat", 0) > 5:
        state["beat"] = time.time()
        say(f"status: step {state['i']} xml={win.xml is not None} loads={loads[0]} "
            f"building={win.building} frames={len(frames)} mark={state['mark'] and state['mark'][0]}")
    if state["mark"] is not None:
        kind, n0, t0 = state["mark"]
        # the counters are bumped on the worker thread; also wait for the window to have
        # handled that frame (win.pos), or a step can run against the previous state
        if kind == "load" and not (loads[0] > n0 and frames and frames[-1][0] > t0
                                   and win.pos == frames[-1][1]):
            return
        if kind == "seek" and not (frames and frames[-1][0] > t0 and frames[-1][1] == state.get("want")
                                   and win.pos == state.get("want")):
            return
        state["mark"] = None
    if time.time() - T0 > 300:
        say("TIMEOUT")
    elif state["i"] < len(steps) and win.xml is not None and loads[0] > 0 and frames:
        fn, wait = steps[state["i"]]
        state["i"] += 1
        state["mark"] = (wait, loads[0], time.time()) if wait else None
        fn()
        return
    elif state["i"] < len(steps):
        return
    win.dirty = False
    app.quit()


timer = QTimer()
timer.timeout.connect(tick)
timer.start(30)
app.exec()
win.player.shutdown()
print("ALL OK" if checks and all(checks) else "SOME CHECKS FAILED", flush=True)
