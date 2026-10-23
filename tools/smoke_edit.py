"""Headless editing smoke test: drives the real window with real mouse events.

  python tools/smoke_edit.py out/AlianShit.tesetoa.json out/

Edits a text through the inspector, nudges its position, splits, drags a clip, trims an
edge, adds a text, then undoes everything and checks the project is back to the original.
Reports how long each edit takes to reach the preview.
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
from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tesetoa import project  # noqa: E402
from tesetoa.ui.main_window import STYLE, MainWindow  # noqa: E402
from tesetoa.ui.timeline import HEADER_W, RULER_H, TRACK_H, US  # noqa: E402

proj_path, out = sys.argv[1], sys.argv[2]
original = json.dumps(project.load(proj_path), sort_keys=True)
app = QApplication(sys.argv)
app.setStyleSheet(STYLE)
win = MainWindow()
win.resize(1440, 900)
win.show()
win.path = proj_path
win.set_project(project.load(proj_path))
class Log(list):
    def append(self, line):
        super().append(line)
        print(line, flush=True)


log, loads, frames = Log(), [0], []
win.player.worker.loaded.connect(lambda _: loads.__setitem__(0, loads[0] + 1))
win.player.worker.frameReady.connect(lambda img, pos: frames.append((time.time(), img, pos)))
win.player.worker.failed.connect(lambda m: log.append("FAILED " + m))
check = []


def find_text(content):
    for tr in win.proj["tracks"]:
        for c in tr["clips"]:
            if c["type"] == "text" and c["text"]["content"] == content:
                return c
    raise SystemExit(f"text {content!r} not found")


def preview_array():
    img = win.preview.img.convertToFormat(win.preview.img.Format.Format_RGB888)
    return np.frombuffer(bytes(img.constBits()), np.uint8)[: img.width() * img.height() * 3].astype(int)


def clip_rect(c):
    tl = win.timeline
    row = next(i for i, t in enumerate(tl.rows) if c in t["clips"])
    x0 = tl._x(c["start_us"] / US)
    x1 = tl._x((c["start_us"] + c["duration_us"]) / US)
    return row, x0, x1, RULER_H + row * TRACK_H + TRACK_H // 2


def drag(x0, y, x1, y1=None):
    tl = win.timeline
    QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(x0), int(y)))
    for k in range(1, 11):
        QTest.mouseMove(tl, QPoint(int(x0 + (x1 - x0) * k / 10), int(y if y1 is None else y + (y1 - y) * k / 10)))
    QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(x1), int(y if y1 is None else y1)))


state = {"step": 0, "t": time.time(), "mark": None}
target = {}


def edit_step(name, action, verify=None):
    """Do action, then wait for a new preview load and the frame after it."""
    def run():
        state["mark"] = (loads[0], time.time(), preview_array() if win.preview.img is not None else None)
        action()
        state["pending"] = (name, verify)
    return run


def waited():
    n0, t0, before = state["mark"]
    if loads[0] > n0 and frames and frames[-1][0] > t0 and not win.building:
        name, verify = state["pending"]
        dt = frames[-1][0] - t0
        changed = before is not None and np.abs(preview_array() - before).mean() > 0.05
        win.grab().save(os.path.join(out, f"edit_{state['step']:02d}.png"))
        ok = verify() if verify else True
        log.append(f"{name:28s} preview after {dt:4.1f}s  frame changed={changed}  check={'OK' if ok else 'FAIL'}")
        check.append(ok)
        return True
    return False


def setup():
    c = find_text("講一次")
    target["text"] = c["id"]
    win.timeline.select(c)
    win.seek(round((c["start_us"] + c["duration_us"] / 2) / US * win.fps))


def set_content():
    win.inspector.widgets["content"].setPlainText("改過的字")


def nudge_y():
    win.inspector.widgets[("transform", "y")].setValue(-0.3)


def split():
    win.do_split()


def drag_move():
    c = find_text("傻逼對話記錄")              # free space on its left
    target["move"] = (c["id"], c["start_us"])
    row, x0, x1, y = clip_rect(c)
    win.timeline.select(c)
    mid = (x0 + x1) / 2
    drag(mid, y, mid - 40)


def drag_trim():
    c = find_text("改過的字")
    target["trim"] = (c["id"], c["start_us"] + c["duration_us"])
    win.timeline.px_per_s = 400
    win.timeline.scroll_s = c["start_us"] / US - 1
    row, x0, x1, y = clip_rect(c)
    drag(x1 - 2, y, x1 + 60)


def by_id(cid):
    for tr in win.proj["tracks"]:
        for c in tr["clips"]:
            if c["id"] == cid:
                return c


def undo_all():
    while win.history.undo_stack:
        win.do_undo()


steps = [
    (lambda: win.xml is not None and loads[0] > 0, setup, "loaded; select 講一次"),
    (lambda: frames and frames[-1][2] > 0, edit_step("edit text content", set_content,
                                                       lambda: by_id(target["text"])["text"]["content"] == "改過的字"), None),
    (None, edit_step("nudge position y", nudge_y,
                     lambda: abs(by_id(target["text"])["transform"]["y"] + 0.3) < 1e-9), None),
    (None, edit_step("split at playhead", split,
                     lambda: sum(c["text"]["content"] == "改過的字" for t in win.proj["tracks"]
                                 for c in t["clips"] if c["type"] == "text") == 2), None),
    (None, edit_step("drag a clip left", drag_move,
                     lambda: by_id(target["move"][0])["start_us"] < target["move"][1]), None),
    (None, edit_step("drag a right edge", drag_trim,
                     lambda: True), None),
    (None, edit_step("add text", win.do_text,
                     lambda: win.timeline.selected is not None and win.timeline.selected["type"] == "text"), None),
    (None, edit_step("undo everything", undo_all,
                     lambda: json.dumps(win.proj, sort_keys=True) == original), None),
]


def tick():
    if state.get("pending"):
        if waited():
            state["pending"] = None
            state["step"] += 1
        elif time.time() - state["t"] > 300:
            log.append("TIMEOUT")
            win.dirty = False
            app.quit()
        return
    if state["step"] >= len(steps):
        modal = QApplication.activeModalWidget()
        if modal is not None:                   # a dialog would block quitting forever
            log.append(f"OPEN DIALOG: {type(modal).__name__}: {getattr(modal, 'text', lambda: '')()}")
            modal.close()
        win.dirty = False      # Qt 6's quit() closes windows; skip the "save first?" prompt
        app.quit()
        return
    cond, act, name = steps[state["step"]]
    if cond is None or cond():
        act()
        if name:
            log.append(f"{time.time() - state['t']:6.1f}s  {name}")
            state["step"] += 1


timer = QTimer()
timer.timeout.connect(tick)
timer.start(30)
app.exec()
win.player.shutdown()
print("ALL OK" if check and all(check) else "SOME CHECKS FAILED")
