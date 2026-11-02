"""網格 / 列表: the panels that list things (專案素材, 內建素材, Library, VFX, 複合片段, the project
manager) switch between a grid of large pictures and a list, with a button in their bar; each
panel remembers its own (QSettings view/<key>).

A tree panel (TreeView) keeps its QTreeWidget as the list and adds a TreeGrid: a QListView on
the same model and selection, showing one level at a time (a folder or a category opens with a
double-click, 上一層 goes back), whose drags are the tree's own (the model asks the tree for its
mime data) and whose double-clicks and right-clicks go to the panel as the tree's would. A plain
list (an icon QListWidget) just changes its view mode."""
from PySide6.QtCore import QModelIndex, QSettings, QSize, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QListView, QListWidget, QPushButton,
                               QStackedWidget, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QToolButton,
                               QVBoxLayout, QWidget)

SETTINGS = ("KiaseCut", "KiaseCut")


def remembered(key, default="list"):
    v = QSettings(*SETTINGS).value("view/" + key, default)
    return v if v in ("grid", "list") else default


def remember(key, mode):
    QSettings(*SETTINGS).setValue("view/" + key, mode)


def toggle_button(mode, on_change):
    """▦ / ☰: on_change("grid" or "list") when pressed."""
    b = QToolButton()
    b.setAutoRaise(True)
    b.setCheckable(True)
    b.setFocusPolicy(Qt.NoFocus)

    def show(grid):
        b.setText("☰" if grid else "▦")
        b.setToolTip("切換成列表檢視" if grid else "切換成網格檢視")
    b.setChecked(mode == "grid")
    show(mode == "grid")
    b.toggled.connect(lambda on: (show(on), on_change("grid" if on else "list")))
    return b


class _FolderIcons(QStyledItemDelegate):
    """A folder (or a category) without a picture of its own shows a folder in the grid."""

    def __init__(self, grid):
        super().__init__(grid)
        self.grid = grid

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        it = self.grid.item(index)
        if it is not None and it.icon(0).isNull() and self.grid.folder(it):
            option.icon = self.grid.style().standardIcon(QStyle.SP_DirIcon)
            option.features |= QStyleOptionViewItem.HasDecoration


class TreeGrid(QListView):
    """A QTreeWidget's items as a grid, one level at a time."""
    levelChanged = Signal()

    def __init__(self, tree, folder, open_item, menu, icon):
        super().__init__()
        self.tree, self.folder, self.open_item, self.menu = tree, folder, open_item, menu
        self.setModel(tree.model())
        self.setSelectionModel(tree.selectionModel())
        self.setViewMode(QListView.IconMode)
        self.setIconSize(icon)
        self.setGridSize(QSize(icon.width() + 24, icon.height() + 40))
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setWordWrap(True)
        self.setUniformItemSizes(True)
        self.setSelectionMode(tree.selectionMode())
        self.setDragEnabled(tree.dragEnabled())
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.doubleClicked.connect(self._double)
        self.setItemDelegate(_FolderIcons(self))
        m = tree.model()
        for sig in (m.rowsInserted, m.rowsRemoved, m.modelReset, m.layoutChanged):
            sig.connect(self._model_changed)         # (a method: let go of when the grid is gone)

    def _model_changed(self, *_args):
        self.sync()

    def item(self, index):
        return self.tree.itemFromIndex(index) if index.isValid() else None

    def level(self):
        """The item whose children show (None: the top level)."""
        return self.item(self.rootIndex())

    def enter(self, it):
        self.setRootIndex(self.tree.indexFromItem(it) if it is not None else QModelIndex())
        self.sync()
        self.levelChanged.emit()

    def up(self):
        it = self.level()
        self.enter(it.parent() if it is not None else None)

    def sync(self):
        """Rows the tree hides (a search) are hidden here too; a level that is gone goes back to the top."""
        root = self.rootIndex()
        if root.isValid() and self.item(root) is None:
            self.setRootIndex(QModelIndex())
            root = self.rootIndex()
        for r in range(self.model().rowCount(root)):
            self.setRowHidden(r, self.tree.isRowHidden(r, root))

    def _double(self, index):
        it = self.item(index)
        if it is None:
            return
        if self.folder(it):
            self.enter(it)
        else:
            self.open_item(it)

    def _menu(self, pos):
        if self.menu is not None:
            self.menu(self.item(self.indexAt(pos)), self.viewport().mapToGlobal(pos))


class TreeView(QWidget):
    """A tree panel's list (the tree) and its grid, one showing at a time; .button switches."""

    def __init__(self, key, tree, folder=lambda it: it.childCount() > 0, open_item=None, menu=None,
                 icon=QSize(96, 54)):
        super().__init__()
        self.key, self.tree = key, tree
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.crumb = QWidget()
        cl = QHBoxLayout(self.crumb)
        cl.setContentsMargins(0, 0, 0, 0)
        up = QPushButton("上一層")
        self.where = QLabel()
        self.where.setStyleSheet("color: #9a9aa0;")
        cl.addWidget(up)
        cl.addWidget(self.where, 1)
        lay.addWidget(self.crumb)
        self.stack = QStackedWidget()
        self.grid = TreeGrid(tree, folder, open_item or (lambda it: tree.itemDoubleClicked.emit(it, 0)), menu, icon)
        up.clicked.connect(self.grid.up)
        self.grid.levelChanged.connect(self._crumb)
        self.stack.addWidget(tree)
        self.stack.addWidget(self.grid)
        lay.addWidget(self.stack, 1)
        mode = remembered(key)
        self.button = toggle_button(mode, self.set_mode)
        self.set_mode(mode)

    def set_mode(self, mode):
        remember(self.key, mode)
        grid = mode == "grid"
        self.stack.setCurrentWidget(self.grid if grid else self.tree)
        if grid:
            self.grid.sync()
        self._crumb()

    def _crumb(self):
        it = self.grid.level() if self.stack.currentWidget() is self.grid else None
        self.crumb.setVisible(it is not None)
        names = []
        while it is not None:
            names.append(it.text(0))
            it = it.parent()
        self.where.setText(" / ".join(reversed(names)))


def list_toggle(key, lst, grid_icon, grid_size, list_icon=QSize(40, 24)):
    """A button switching an icon QListWidget / QListView between its grid and a list."""
    drag = (lst.dragEnabled(), lst.dragDropMode(), lst.acceptDrops(), lst.defaultDropAction())

    def apply(mode):
        remember(key, mode)
        if mode == "grid":
            lst.setViewMode(QListView.IconMode)
            lst.setIconSize(grid_icon)
            lst.setGridSize(grid_size)
            lst.setWordWrap(True)
        else:
            lst.setViewMode(QListView.ListMode)
            lst.setIconSize(list_icon)
            lst.setGridSize(QSize())
            lst.setWordWrap(False)
        lst.setResizeMode(QListView.Adjust)
        lst.setMovement(QListView.Static if isinstance(lst, QListWidget) and not drag[2] else lst.movement())
        lst.setDragEnabled(drag[0])                      # (Qt turns dragging off when the view mode changes)
        lst.setDragDropMode(drag[1])
        lst.setAcceptDrops(drag[2])
        lst.setDefaultDropAction(drag[3])
        lst.doItemsLayout()
    mode = remembered(key, "grid")
    apply(mode)
    return toggle_button(mode, apply)
