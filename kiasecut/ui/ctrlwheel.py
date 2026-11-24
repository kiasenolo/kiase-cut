"""Ctrl + the wheel over a value changes it, everywhere (the panels' wheel never edits otherwise: it scrolls what is under it):
a number goes up / down by 0.01 a notch (a whole number by one), a check box is ticked by up and cleared by down, a menu goes to
the previous / next choice. The node editor's own fields (drawn, not widgets) do the same through NodeEditor.ctrl_wheel."""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QSpinBox

from . import appevents, wheel

STEP = 0.01                                        # a notch of a decimal number


def target(w):
    """The value widget `w` is (or is part of): a number box, a check box or a combo box; else None."""
    for _ in range(4):
        if w is None:
            return None
        if isinstance(w, (QAbstractSpinBox, QCheckBox, QComboBox)):
            return w
        w = w.parentWidget()
    return None


def step_of(spin):
    if isinstance(spin, QDoubleSpinBox):
        return max(STEP, 10.0 ** -spin.decimals()) if spin.decimals() > 0 else 1.0
    return float(spin.singleStep()) if isinstance(spin, QSpinBox) else 1.0


def change(w, steps):
    """Move the value of widget w by `steps` notches (up positive)."""
    if isinstance(w, QCheckBox):
        if w.isChecked() != (steps > 0) and w.isEnabled():
            w.click()
    elif isinstance(w, QComboBox):
        i = w.currentIndex()
        direction = -1 if steps > 0 else 1                  # (up: the one before, as Qt's own wheel on a combo box)
        model = w.model()
        for _ in range(abs(steps)):
            j = i + direction
            while 0 <= j < w.count() and not model.flags(model.index(j, 0)) & Qt.ItemIsEnabled:
                j += direction
            if not 0 <= j < w.count():
                break
            i = j
        if i != w.currentIndex():
            w.setCurrentIndex(i)
            w.activated.emit(i)
            w.textActivated.emit(w.itemText(i))
    elif isinstance(w, QAbstractSpinBox):
        step = step_of(w)
        lo, hi = w.minimum(), w.maximum()
        soft = getattr(w, "soft", None)                     # (as dragging: inside the soft limits, or where it is when already past them)
        v = w.value()
        if soft:
            lo, hi = max(lo, min(soft[0], v)), min(hi, max(soft[1], v))
        new = min(max(v + steps * step, lo), hi)
        if isinstance(w, QDoubleSpinBox):
            new = round(new, max(w.decimals(), 2))
        if getattr(w, "mixed", False):
            w.mixed = False
        w.setValue(type(v)(new))


def _wheel(obj, e):
    if not e.modifiers() & Qt.ControlModifier or e.modifiers() & (Qt.ShiftModifier | Qt.AltModifier):
        return False
    w = target(obj if hasattr(obj, "parentWidget") else None)
    if w is None or not w.isEnabled():
        return False
    steps = wheel.whole_notches(e, w)
    if steps:
        change(w, steps)
    return True


_installed = False


def install():
    global _installed
    if not _installed:
        _installed = True
        appevents.watch(QApplication.instance(), [QEvent.Wheel], _wheel, first=True)
