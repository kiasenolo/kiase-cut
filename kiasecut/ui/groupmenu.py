"""A menu of choices in groups side by side (menugroups.of): a header over each column, the choices under it. A popup: a click picks,
Esc or a click elsewhere closes it."""
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QAbstractItemView, QFrame, QHBoxLayout, QLabel, QListWidget, QVBoxLayout, QWidget


class GroupMenu(QFrame):
    def __init__(self, parent, groups, current, pick):
        super().__init__(parent.window() if parent is not None else None, Qt.Popup)
        self.setObjectName("groupmenu")
        self.setFrameShape(QFrame.StyledPanel)
        self.pick = pick
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(8)
        self.lists = []
        for title, names in groups:
            col = QVBoxLayout()
            col.setSpacing(2)
            head = QLabel(title)
            head.setStyleSheet("font-weight: 600; padding: 2px 4px; border-bottom: 1px solid #4d4d4d;")
            col.addWidget(head)
            lst = QListWidget()
            lst.setFrameShape(QFrame.NoFrame)
            lst.setFocusPolicy(Qt.NoFocus)
            lst.setMouseTracking(True)
            lst.setUniformItemSizes(True)
            lst.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            lst.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            lst.setSelectionMode(QAbstractItemView.NoSelection)
            lst.addItems(names)
            for i, n in enumerate(names):
                if n == current:
                    lst.item(i).setSelected(True)
                    lst.setSelectionMode(QAbstractItemView.SingleSelection)
                    lst.setCurrentRow(i)
            lst.setFixedWidth(max(lst.sizeHintForColumn(0), head.sizeHint().width()) + 24)
            lst.setFixedHeight(len(names) * lst.sizeHintForRow(0) + 4)
            lst.itemClicked.connect(lambda item: self.choose(item.text()))
            col.addWidget(lst)
            col.addStretch(1)
            holder = QWidget()
            holder.setLayout(col)
            col.setContentsMargins(0, 0, 0, 0)
            row.addWidget(holder)
            self.lists.append(lst)

    def choose(self, name):
        self.close()
        self.pick(name)

    def show_at(self, pos):
        """Open with its top left corner at the global point `pos` (kept on the screen)."""
        self.adjustSize()
        screen = (QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()).availableGeometry()
        x = min(pos.x(), screen.right() - self.width())
        y = min(pos.y(), screen.bottom() - self.height())
        self.move(QPoint(max(screen.left(), x), max(screen.top(), y)))
        self.show()
