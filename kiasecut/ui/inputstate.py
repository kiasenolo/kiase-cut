"""When the mouse stops reaching the program (clicks dead while the wheel, the keyboard and the pointer's shape still work: seen
after a screen was plugged in under Wayland), this says why and tries to put it right.

Ctrl+Alt+Shift+R (works with the keyboard alone): writes what holds the mouse - a widget's grab, a popup, a modal window, the
cursor overrides, a drag of ours still on, the screens and where the windows are - to a text file (named in the status bar),
then lets go of what it finds. The same runs by itself, a moment after a screen is added or removed (the report is kept
in the file: before and after).
"""
import os
import tempfile
import time

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QWidget

PATH = os.path.join(tempfile.gettempdir(), "kiasecut-input-state.txt")


def describe():
    app = QApplication.instance()
    lines = [f"time {time.strftime('%H:%M:%S')}",
             f"mouseGrabber {QWidget.mouseGrabber()}", f"keyboardGrabber {QWidget.keyboardGrabber()}",
             f"activePopup {app.activePopupWidget()}  activeModal {app.activeModalWidget()}",
             f"overrideCursor {QGuiApplication.overrideCursor()}",
             f"mouseButtons {QGuiApplication.mouseButtons()}  state {QGuiApplication.applicationState()}",
             f"focusWindow {QGuiApplication.focusWindow()}  activeWindow {app.activeWindow()}",
             "screens " + ", ".join(f"{s.name()}{s.geometry().getRect()}" for s in QGuiApplication.screens())]
    for w in app.topLevelWidgets():
        if w.isVisible():
            lines.append(f"top {type(w).__name__} '{w.windowTitle() or w.objectName()}' {w.geometry().getRect()} "
                         f"screen {w.screen().name() if w.screen() else None} modality {w.windowModality().name} enabled {w.isEnabled()}")
    try:
        from . import middledrag, wrapdrag
        lines.append(f"middledrag area {getattr(middledrag._drag, 'area', None)}  pointer hidden {wrapdrag.hider().hidden}")
    except Exception as exc:                                   # (a report must not fail)
        lines.append(f"middledrag? {exc}")
    return "\n".join(lines)


def recover():
    """Let go of what can hold the mouse; returns what was done, in words."""
    done = []
    app = QApplication.instance()
    w = QWidget.mouseGrabber()
    if w is not None:
        w.releaseMouse()
        done.append(f"releaseMouse {type(w).__name__}")
    w = QWidget.keyboardGrabber()
    if w is not None:
        w.releaseKeyboard()
        done.append(f"releaseKeyboard {type(w).__name__}")
    p = app.activePopupWidget()
    if p is not None:
        p.close()
        done.append(f"closed popup {type(p).__name__}")
    n = 0
    while QGuiApplication.overrideCursor() is not None and n < 50:
        QGuiApplication.restoreOverrideCursor()
        n += 1
    if n:
        done.append(f"{n} cursor overrides")
    try:
        from . import middledrag, wrapdrag
        if getattr(middledrag._drag, "area", None) is not None:
            middledrag._drag._end(None)
            done.append("middle drag ended")
        wrapdrag.hider().show()
    except Exception:
        pass
    return done


def report(why):
    before = describe()
    done = recover()
    after = describe()
    try:
        with open(PATH, "a", encoding="utf-8") as f:
            f.write(f"=== {why} ===\n{before}\n--- done: {', '.join(done) or 'nothing'} ---\n{after}\n\n")
    except OSError:
        pass
    return done


def install(win):
    """Ctrl+Alt+Shift+R on the main window, and a report when the screens change."""
    def manual():
        done = report("Ctrl+Alt+Shift+R")
        win.statusBar().showMessage(f"已解除輸入卡住（{', '.join(done) or '沒有東西抓著滑鼠'}）；狀態寫在 {PATH}", 8000)

    sc = QShortcut(QKeySequence("Ctrl+Alt+Shift+R"), win)
    sc.setContext(Qt_ApplicationShortcut())
    sc.activated.connect(manual)
    app = QApplication.instance()
    for sig, why in ((app.screenAdded, "screen added"), (app.screenRemoved, "screen removed")):
        sig.connect(lambda *_a, why=why: QTimer.singleShot(400, lambda: report(why)))


def Qt_ApplicationShortcut():
    from PySide6.QtCore import Qt
    return Qt.ApplicationShortcut
