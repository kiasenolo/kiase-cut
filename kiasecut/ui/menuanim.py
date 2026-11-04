"""Menus open the way Kilo's do: unrolled from the top, `clip-path: polygon(0 0, 100% 0, 100% 0, 0 0)` to
`polygon(0 0, 100% 0, 100% 100%, 0 100%)` in half a second on cubic-bezier(0, .5, 0, 1) - most of it at once, a long soft end.
They go away at once, without a fade.

A menu (the menu bar's, a context menu, a combo box's list) is a window of its own, so it is not the page's clip-path: a
QGraphicsEffect on it draws it clipped to the part from the top down that the animation has got to, the effect going when
the animation ends. A QMenu window is made frameless and without the window manager's shadow (square, flat).
install() watches for menus and combo lists being made ready and being shown.
"""
from PySide6.QtCore import QEvent, QRectF, Qt, QVariantAnimation
from PySide6.QtWidgets import QApplication, QGraphicsEffect, QMenu, QWidget

from . import appevents, motion

DURATION_MS = 500


def curve():
    return motion.out_curve()                         # cubic-bezier(0, .5, 0, 1)


class Pop(QGraphicsEffect):
    """The menu drawn from its top down to `t` of its height (0: nothing yet, 1: all of it)."""

    def __init__(self, menu):
        super().__init__(menu)
        self.t = 0.0

    def draw(self, painter):
        pm = self.sourcePixmap(Qt.LogicalCoordinates)
        if pm.isNull() or self.t >= 1.0:
            self.drawSource(painter)
            return
        t = max(0.0, self.t)
        off = self.sourceBoundingRect(Qt.LogicalCoordinates).topLeft()
        size = pm.deviceIndependentSize()
        if t > 0.0:                                          # (the top part of the picture: a clip, drawn as a piece of it)
            painter.drawPixmap(QRectF(off.x(), off.y(), size.width(), size.height() * t), pm,
                               QRectF(0, 0, pm.width(), pm.height() * t))


def pop(menu):
    """Start the opening of menu (shown just now)."""
    old = menu.property("kcPop")
    if old is not None:
        old.stop()
    effect = Pop(menu)
    menu.setGraphicsEffect(effect)
    anim = QVariantAnimation(menu)
    anim.setDuration(DURATION_MS)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(curve())

    def step(v):
        effect.t = float(v)
        effect.update()

    def done():
        if menu.graphicsEffect() is effect:
            menu.setGraphicsEffect(None)
        menu.setProperty("kcPop", None)

    anim.valueChanged.connect(step)
    anim.finished.connect(done)
    menu.setProperty("kcPop", anim)
    step(0.0)
    anim.start()


def popup_window(obj):
    """Whether obj is a menu window or the window of a combo box's list."""
    if not isinstance(obj, QWidget):                  # (Show events also come for a QWindow)
        return False
    if isinstance(obj, QMenu):
        return obj.isWindow()
    return obj.isWindow() and obj.metaObject().className() == "QComboBoxPrivateContainer"


def install():
    def made(obj, e):
        if isinstance(obj, QMenu) and obj.isWindow() and not obj.windowFlags() & Qt.FramelessWindowHint:
            obj.setWindowFlags(obj.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)     # (flat: no frame, no shadow)
        return False

    def shown(obj, e):
        if popup_window(obj):
            pop(obj)
        return False

    app = QApplication.instance()
    appevents.watch(app, [QEvent.Polish], made)
    appevents.watch(app, [QEvent.Show], shown)
