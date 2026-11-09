"""A search box at the top of a menu with many entries: what is typed narrows them to a list with a scroll bar of its own, in place of
the categories (hundreds of menu actions made a menu taller than the screen and slow to lay out at every key).

    box = SearchBox(menu, pick)             # first: it adds the box (and the hidden list) to the menu
    box.add("色彩 ▸ 調整", "曝光", payload)   # every entry the search looks through (path, name, payload; a dict's ref, or the payload itself when it is a ref, is searched too)
    box.groups.append(action)               # what is hidden while a search is typed (the categories, the separators)
pick(payload) hears a choice (click, Enter on the highlighted one); Up / Down in the box move along the matches."""
import shiboken6
from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QAbstractItemView, QFrame, QLineEdit, QListWidget, QListWidgetItem, QWidgetAction

ROWS = 12                                          # the list shows this many matches at a time


def key_of(payload):
    """What of a payload is searched besides its name: a node's filter ref (or shape), a ref given as it is."""
    return (str(payload.get("ref", payload.get("shape", ""))) if isinstance(payload, dict) else str(payload)).lower()


class Steer(QObject):
    """Up and Down in the search box move along the matches."""

    def __init__(self, box):
        super().__init__(box.search)
        self.box = box

    def eventFilter(self, _o, ev):
        if ev.type() == QEvent.KeyPress and ev.key() in (Qt.Key_Up, Qt.Key_Down) and self.box.shown.isVisible():
            res = self.box.results
            row = res.currentRow() + (1 if ev.key() == Qt.Key_Down else -1)
            res.setCurrentRow(max(0, min(res.count() - 1, row)))
            return True
        return False


class SearchBox:
    def __init__(self, menu, pick, placeholder="搜尋…"):
        self.menu, self.pick = menu, pick
        self.entries, self.groups, self.found = [], [], []
        self.search = QLineEdit()
        self.search.setPlaceholderText(placeholder)
        self.search.setClearButtonEnabled(True)
        self.box = QWidgetAction(menu)
        self.box.setDefaultWidget(self.search)
        menu.addAction(self.box)
        res = self.results = QListWidget()
        res.setFrameShape(QFrame.NoFrame)
        res.setFocusPolicy(Qt.NoFocus)             # (the keys stay in the search box)
        res.setMouseTracking(True)
        res.setUniformItemSizes(True)
        res.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        res.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        res.setFixedWidth(max(320, self.search.sizeHint().width()))
        res.itemEntered.connect(res.setCurrentItem)
        res.itemClicked.connect(self.choose)
        self.shown = res                          # (what Steer asks whether the list is up)
        self.shown_action = QWidgetAction(menu)
        self.shown_action.setDefaultWidget(res)
        self.shown_action.setVisible(False)
        menu.addAction(self.shown_action)
        self.search.textChanged.connect(self.refresh)
        self.search.returnPressed.connect(self.first)
        self.search.installEventFilter(Steer(self))

    def add(self, path, name, payload):
        self.entries.append((path, name, payload))

    def reset(self, focus=False):
        """Back to the categories (the menu is about to be shown)."""
        self.search.clear()
        if focus:
            QTimer.singleShot(0, self.search.setFocus)

    def refresh(self, text):
        self.found.clear()
        self.results.clear()
        text = text.strip().lower()
        for act in self.groups:
            act.setVisible(not text)
        self.shown_action.setVisible(False)
        if not text:
            return
        names = [(f"{name}　（{path}）" if path else name, payload) for path, name, payload in self.entries
                 if text in name.lower() or text in path.lower() or text in key_of(payload)]
        res = self.results
        res.setUpdatesEnabled(False)
        if names:
            res.addItems([t for t, _ in names])
            self.found.extend((res.item(i), p) for i, (_, p) in enumerate(names))
            res.setCurrentRow(0)
        else:
            none = QListWidgetItem("沒有符合的項目")
            none.setFlags(Qt.NoItemFlags)
            res.addItem(none)
            self.found.append((none, None))
        res.setUpdatesEnabled(True)
        res.setFixedHeight(min(len(self.found), ROWS) * res.sizeHintForRow(0) + 2 * res.frameWidth() + 2)
        self.shown_action.setVisible(True)         # (the menu lays itself out again when an action appears, not when a widget is resized)
        self.menu.adjustSize()

    def choose(self, item):
        payload = next((p for it, p in self.found if it is item), None)
        if payload is not None:
            self.menu.close()
            self.pick(payload)

    def first(self):
        self.choose(self.results.currentItem() or (self.found[0][0] if self.found else None))


def install(menu, pick, placeholder="搜尋…"):
    """A SearchBox for a menu that is cleared and filled again as it is about to be shown (call it right after menu.clear()): a new
    one each time, so back to the categories, and it takes the keys."""
    box = menu._search_box = SearchBox(menu, pick, placeholder)       # (kept: the box is the menu's)
    QTimer.singleShot(0, lambda: shiboken6.isValid(box.search) and box.search.setFocus())
    return box


def finish(box):
    """Call it when the menu is filled: everything but the box is what a search hides."""
    own = (box.box, box.shown_action)
    box.groups.extend(a for a in box.menu.actions() if a not in own and a not in box.groups)
