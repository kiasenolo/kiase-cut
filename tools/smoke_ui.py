"""Headless UI smoke test: open a project, seek, play, save window screenshots.

  python tools/smoke_ui.py out/AlianShit.tesetoa.json out/
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":  # the offscreen platform has no font database of its own
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tesetoa import project  # noqa: E402
from tesetoa.ui.main_window import STYLE, MainWindow  # noqa: E402

proj_path, out = sys.argv[1], sys.argv[2]
app = QApplication(sys.argv)
app.setStyleSheet(STYLE)
win = MainWindow()
win.resize(1440, 900)
win.show()
win.path = proj_path
win.set_project(project.load(proj_path))
log = []
frames = []
win.player.worker.frameReady.connect(lambda img, pos: frames.append((time.time(), pos)))
win.player.worker.failed.connect(lambda m: log.append("FAILED " + m))
steps = [
    (lambda: win.xml is not None and win.length > 0, lambda: win.seek(270), "loaded; seek 4.5s"),
    (lambda: win.pos == 270, lambda: win.grab().save(os.path.join(out, "ui_270.png")), "shot at 4.5s"),
    (lambda: True, lambda: (win.timeline.clipSelected.emit(win.timeline.rows[4]["clips"][3]),
                            setattr(win.timeline, "selected", win.timeline.rows[4]["clips"][3]),
                            win.seek(7068)), "select clip; seek 117.8s"),
    (lambda: win.pos == 7068, lambda: win.grab().save(os.path.join(out, "ui_7068.png")), "shot at 117.8s"),
    (lambda: True, lambda: (frames.clear(), win.toggle_play()), "play"),
]
state = {"i": 0, "t": time.time(), "play_t": None}


def tick():
    i = state["i"]
    if i < len(steps):
        cond, act, name = steps[i]
        if cond():
            act()
            log.append(f"{time.time() - state['t']:6.1f}s  {name}")
            state["i"] += 1
        elif time.time() - state["t"] > 600:
            log.append("TIMEOUT at " + name)
            app.quit()
    else:
        if state["play_t"] is None:
            state["play_t"] = time.time()
        elif time.time() - state["play_t"] > 3:
            win.toggle_play()
            n = len(frames)
            span = frames[-1][0] - frames[0][0] if n > 1 else 0
            log.append(f"played {n} frames in {span:.2f}s -> {n / span if span else 0:.1f} fps")
            win.grab().save(os.path.join(out, "ui_play.png"))
            app.quit()


timer = QTimer()
timer.timeout.connect(tick)
timer.start(50)
app.exec()
win.player.shutdown()
print("\n".join(log))
