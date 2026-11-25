"""The outline on a field that is bound to a global parameter (racklinks.py): a frame laid over the field, so
whatever the field's own style sheet shows (a colour button's colour) stays."""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QFrame


class _Outline(QFrame):
    def __init__(self, field):
        super().__init__(field)
        self.setObjectName("linkmark")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet("QFrame#linkmark { border: 2px solid #e0a030; background: transparent; }")
        self.said = field.toolTip()                       # (the field's own tooltip, put back when it is unbound)
        self.follow = _Follow(self)
        field.installEventFilter(self.follow)
        self.setGeometry(field.rect())


class _Follow(QObject):
    def eventFilter(self, field, e):
        if e.type() == QEvent.Resize:
            self.parent().setGeometry(field.rect())
        return False


def outline_of(field):
    return next((c for c in field.children() if isinstance(c, _Outline)), None)


def mark(field, name):
    """Outline field as bound to the parameter `name`; None / "": not bound."""
    frame = outline_of(field)
    if not name:
        if frame is not None and not frame.isHidden():
            frame.hide()
            field.setToolTip(frame.said)
        return
    if frame is None:
        frame = _Outline(field)
    elif frame.isHidden():
        frame.said = field.toolTip()
    field.setToolTip(f"綁定全局參數：{name}（右鍵可以解除）")
    frame.setGeometry(field.rect())
    frame.show()
    frame.raise_()
