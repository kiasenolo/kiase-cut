"""A row of buttons that may be narrower than it needs: it scrolls sideways (a swipe, the wheel) instead of making the window - and
with it the screen of a tablet at 界面縮放 over 100 % - wider than it can be."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QSizePolicy, QWidget


class ToolbarScroll(QScrollArea):
    def __init__(self, layout, name="", parent=None):
        """name: the object name the row is styled by (look.py's QWidget#bar)."""
        super().__init__(parent)
        self.inner = QWidget()
        self.inner.setObjectName(name)
        self.inner.setLayout(layout)
        self.setWidget(self.inner)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.viewport().setAutoFillBackground(False)
        self.inner.setAutoFillBackground(False)

    def sizeHint(self):
        return QSize(self.inner.sizeHint().width(), self.inner.sizeHint().height() + 2 * self.frameWidth())

    def minimumSizeHint(self):
        return QSize(80, self.sizeHint().height())

    def wheelEvent(self, e):
        bar = self.horizontalScrollBar()
        d = e.angleDelta().x() or e.angleDelta().y()
        if bar.maximum() > 0 and d:
            bar.setValue(bar.value() - d)
            e.accept()
        else:
            super().wheelEvent(e)
