"""Stress: drag a clip around the preview many times in a row, as fast as possible.

  python tools/stress_drag.py PROJECT.kiasecut.json
Reports errors, how long the window took to settle and the playback frame rate.
"""
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import project  # noqa: E402
from kiasecut.ui.main_window import MainWindow  # noqa: E402
from kiasecut.ui.timeline import US  # noqa: E402

app = QApplication(sys.argv)
win = MainWindow()
win.resize(1600, 940)
win.show()
win.path = sys.argv[1]
win.set_project(project.load(sys.argv[1]))
errors, frames = [], []
win.player.worker.failed.connect(errors.append)
win.player.worker.frameReady.connect(lambda img, pos: frames.append(time.time()))
c = next(c for t in win.proj["tracks"] for c in t["clips"] if c["type"] == "text" and c["text"]["content"] == "這是一隻有味道的影片")
random.seed(1)


def go():
    win.timeline.select(c)
    win.seek(round((c["start_us"] / US + 1.5) * win.fps))
    QTimer.singleShot(400, drag_storm)


def drag_storm():
    pv = win.preview
    t0 = time.time()
    for n in range(30):
        box = next(b for b in pv.visible_boxes() if b.clip["id"] == c["id"])
        r = pv._rect()
        sx = r.x() + box.cx / pv.W * r.width()
        sy = r.y() + box.cy / pv.H * r.height()
        QTest.mousePress(pv, Qt.LeftButton, Qt.NoModifier, QPoint(round(sx), round(sy)))
        for k in range(20):
            QTest.mouseMove(pv, QPoint(round(sx + random.uniform(-200, 200)), round(sy + random.uniform(-120, 120))))
            app.processEvents()
        QTest.mouseRelease(pv, Qt.LeftButton, Qt.NoModifier, QPoint(round(sx + 30), round(sy + 10)))
        app.processEvents()
    print(f"30 drags x 20 moves in {time.time() - t0:.2f} s, undo steps {len(win.history.undo_stack)}", flush=True)
    QTimer.singleShot(500, play)


def play():
    frames.clear()
    win.seek(round(100 * win.fps))
    QTimer.singleShot(300, lambda: (frames.clear(), win.toggle_play(), QTimer.singleShot(3000, stop)))


def stop():
    win.toggle_play()
    span = frames[-1] - frames[0] if len(frames) > 1 else 0
    print(f"playback: {len(frames)} frames in {span:.2f} s -> {len(frames) / span if span else 0:.1f} fps", flush=True)
    print("errors:", errors or "none", flush=True)
    win.dirty = False
    app.quit()


QTimer.singleShot(1500, go)
app.exec()
win.player.shutdown()
