"""A combo box with many items (the fonts: hundreds) opens a search box over a list with a scroll bar of its own, in place of Qt's list of
every item, which has to size them all each time and scrolls by arrows only. Any combo box (not editable: those have a search of their own, the
completer) with more than BIG items; polish() in look.py calls watch()."""
import shiboken6
from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QFrame, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

BIG = 24                                           # items: more than this opens the list below
ROWS = 14                                          # the list shows this many at a time


class Popup(QFrame):
    def __init__(self, combo):
        super().__init__(combo.window(), Qt.Popup)
        self.combo = combo
        self.setObjectName("bigcombo")
        self.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜尋…")
        self.search.setClearButtonEnabled(True)
        lay.addWidget(self.search)
        self.list = QListWidget()
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setFocusPolicy(Qt.NoFocus)       # (the keys stay in the search box)
        self.list.setMouseTracking(True)
        self.list.setUniformItemSizes(True)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lay.addWidget(self.list)
        model = combo.model()
        self.rows = []                             # the combo box's row of each list item
        names = []
        for i in range(combo.count()):
            names.append(combo.itemText(i))
        self.names = names
        self.fill("")
        self.list.itemEntered.connect(self.list.setCurrentItem)
        self.list.itemClicked.connect(self.pick)
        self.search.textChanged.connect(self.fill)
        self.search.returnPressed.connect(lambda: self.pick(self.list.currentItem()))
        self.search.installEventFilter(self)
        self.setFixedWidth(max(combo.width(), 260))
        height = min(self.list.count(), ROWS) * max(self.list.sizeHintForRow(0), 20) + 8 + self.search.sizeHint().height() + 8
        self.setFixedHeight(height)
        below = combo.mapToGlobal(QPoint(0, combo.height()))
        screen = QGuiApplication.screenAt(below) or QGuiApplication.primaryScreen()
        if below.y() + height > screen.availableGeometry().bottom():
            below = combo.mapToGlobal(QPoint(0, -height))
        self.move(below)
        current = combo.currentIndex()
        if current in self.rows:
            self.list.setCurrentRow(self.rows.index(current))
        self.show()
        self.search.setFocus()

    def fill(self, text):
        text = text.strip().lower()
        self.rows = [i for i, n in enumerate(self.names) if not text or text in n.lower()]
        self.list.setUpdatesEnabled(False)
        self.list.clear()
        self.list.addItems([self.names[i] for i in self.rows])
        model = self.combo.model()
        for r, i in enumerate(self.rows):          # (a disabled row of the combo box stays disabled)
            if not self.combo.model().flags(model.index(i, 0)) & Qt.ItemIsEnabled:
                self.list.item(r).setFlags(Qt.NoItemFlags)
        self.list.setUpdatesEnabled(True)
        if self.rows:
            self.list.setCurrentRow(0)

    def pick(self, item):
        if item is None or not item.flags() & Qt.ItemIsEnabled:
            return
        i = self.rows[self.list.row(item)]
        self.close()
        combo = self.combo
        combo.setCurrentIndex(i)
        combo.activated.emit(i)
        combo.textActivated.emit(combo.itemText(i))

    def eventFilter(self, _o, ev):
        if ev.type() == QEvent.KeyPress and ev.key() in (Qt.Key_Up, Qt.Key_Down):
            row = self.list.currentRow() + (1 if ev.key() == Qt.Key_Down else -1)
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
            return True
        return False


class Opener(QObject):
    """Watches the combo boxes: a press (or the keys that open the list) on a big one opens a Popup instead of Qt's list."""

    def eventFilter(self, o, ev):
        if not isinstance(o, QComboBox) or o.isEditable() or o.count() <= BIG or not o.isEnabled():
            return False
        t = ev.type()
        if t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton or (
                t == QEvent.KeyPress and (ev.key() in (Qt.Key_Space, Qt.Key_F4) or ev.key() == Qt.Key_Down and ev.modifiers() & Qt.AltModifier)):
            o.popup = Popup(o)
            return True
        return False


_opener = None


def watch(widget):
    global _opener
    if isinstance(widget, QComboBox) and not widget.property("kcBig"):
        widget.setProperty("kcBig", True)
        if _opener is None:
            _opener = Opener()
        widget.installEventFilter(_opener)
