"""Menus open the way Kilo's do (data/components/ContextMenu/style.module.scss): from a little too big, blurred and clear to
what they are, in half a second on cubic-bezier(1, 0, 0, 1) - nearly nothing for a moment, then most of it at once.

A menu is a window of its own, so it is not the page's transform: its picture is taken (a QGraphicsEffect on it) and drawn
scaled about its middle, a little blurred (drawn small and scaled up) and see-through, the effect going when the animation ends.
Menus are made translucent for their round corners (the style sheet's QMenu radius).
install() watches for menus being made ready and being shown.
"""
from PySide6.QtCore import QEasingCurve, QEvent, QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QApplication, QGraphicsEffect, QMenu

from . import appevents

DURATION_MS = 500
SCALE_FROM = 1.1          # the size a menu starts at
BLUR_FROM = 6.0           # how many times smaller its picture is drawn at the start, before it is stretched back


def curve():
    c = QEasingCurve(QEasingCurve.BezierSpline)
    c.addCubicBezierSegment(QPointF(1, 0), QPointF(0, 1), QPointF(1, 1))      # cubic-bezier(1, 0, 0, 1)
    return c


class Pop(QGraphicsEffect):
    """The menu drawn at progress `t` (0: just begun, 1: as it is)."""

    def __init__(self, menu):
        super().__init__(menu)
        self.t = 0.0

    def draw(self, painter):
        pm = self.sourcePixmap(Qt.LogicalCoordinates)
        off = self.sourceBoundingRect(Qt.LogicalCoordinates).topLeft()
        if pm.isNull() or self.t >= 1.0:
            self.drawSource(painter)
            return
        t = self.t
        size = pm.deviceIndependentSize()
        rect = QRectF(off.x(), off.y(), size.width(), size.height())
        blur = 1.0 + (BLUR_FROM - 1.0) * (1.0 - t)
        if blur > 1.05:                               # (drawn small, then stretched back: a cheap blur)
            pm = pm.scaled(max(1, round(pm.width() / blur)), max(1, round(pm.height() / blur)),
                           Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        k = SCALE_FROM - (SCALE_FROM - 1.0) * t
        painter.save()
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setOpacity(t)
        painter.translate(rect.center())
        painter.scale(k, k)
        painter.translate(-rect.center())
        painter.drawPixmap(rect, pm, QRectF(pm.rect()))
        painter.restore()


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


def install():
    def made(obj, e):
        if isinstance(obj, QMenu) and obj.isWindow() and not obj.testAttribute(Qt.WA_TranslucentBackground):
            obj.setWindowFlags(obj.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
            obj.setAttribute(Qt.WA_TranslucentBackground)
        return False

    def shown(obj, e):
        if isinstance(obj, QMenu) and obj.isWindow():
            pop(obj)
        return False

    app = QApplication.instance()
    appevents.watch(app, [QEvent.Polish], made)
    appevents.watch(app, [QEvent.Show], shown)
