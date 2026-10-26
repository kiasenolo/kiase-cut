"""Wheel events that suit a touchpad as well as a mouse wheel.

A mouse wheel sends a few large steps (120 per notch); a touchpad, or a high-resolution wheel,
sends many small ones, a two-finger scroll moves both ways at once, and a gesture starts and
ends with events that move nothing. So nothing here acts once per event: zooms and scrolls go
as far as the event moved, counted in notches (fractions too), and a touchpad's scroll moves the
view by its own pixels.
"""

import math

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QAbstractItemView, QProxyStyle, QStyle

TOUCHPAD_NOTCH_PX = 100   # how far two fingers move for one notch's zoom


def touchpad(e):
    """Whether wheel event e comes from a touchpad (it has a phase and pixel motion)."""
    return e.phase() != Qt.NoScrollPhase and not e.pixelDelta().isNull()


def notches(e):
    """How far wheel event e moved, in mouse-wheel notches (x, y); up / left are positive."""
    if touchpad(e):
        p = e.pixelDelta()
        return p.x() / TOUCHPAD_NOTCH_PX, p.y() / TOUCHPAD_NOTCH_PX
    a = e.angleDelta()
    return a.x() / 120, a.y() / 120


def notch(e):
    """The notches of e along the way it moved most (for zooms: one direction only)."""
    x, y = notches(e)
    return y if abs(y) >= abs(x) else x


def pixels(e, notch_x, notch_y):
    """How far e scrolls the view in pixels (x, y): a touchpad's own motion, or for a wheel
    notch_x / notch_y pixels a notch."""
    if touchpad(e):
        p = e.pixelDelta()
        return float(p.x()), float(p.y())
    x, y = notches(e)
    return x * notch_x, y * notch_y


def pinch(e):
    """The zoom factor of a touchpad's pinch (a native gesture event), else None."""
    if e.type() == QEvent.NativeGesture and e.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
        return math.exp(e.value())   # (about 1 + value; never below zero)
    return None


class Style(QProxyStyle):
    """Lists and trees scroll by pixels, not whole rows, so a touchpad scrolls them smoothly."""

    def styleHint(self, hint, option=None, widget=None, data=None):
        if hint == QStyle.SH_ItemView_ScrollMode:
            return QAbstractItemView.ScrollPerPixel.value
        return super().styleHint(hint, option, widget, data)
