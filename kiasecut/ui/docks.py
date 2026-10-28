"""The main window's panels as dock widgets: each can be dragged elsewhere in the window,
put in tabs with others, split beside them or floated as a window of its own (dragged by
its title bar, or by its tab while it is in tabs; a floating window with several panels
can hold tabs too). Panels in tabs are one region: dragging the empty part of their tab bar
moves them all together (GroupGrip), dragging a tab takes that one panel out.

Panels arranges them (the built-in layouts, see layouts.py), keeps which side panel was
used last (`active`: the one whose tab was switched to or that was clicked in; the main
window's mask mode follows it) and shows a side panel only while the selection has a use
for it (set_usable): one in tabs leaves them, as a tab did before; one on its own stays and
says it has nothing to show. A panel closed on purpose (its X, or the 視窗 menu) stays closed.
"""
import shiboken6
from PySide6.QtCore import QEvent, QObject, QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QMouseEvent
from PySide6.QtWidgets import (QApplication, QDockWidget, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QStackedWidget, QTabBar, QTabWidget, QWidget)

from . import appevents, icons

STATE_VERSION = 1
LEFT = ("library", "assets", "userlib", "vfx", "compounds")
SIDE = ("inspector", "effects", "mask", "beats", "subtitles", "curves")
TITLES = {"library": "專案素材", "assets": "內建素材", "userlib": "Library", "vfx": "VFX", "compounds": "複合片段",
          "preview": "預覽", "inspector": "屬性", "effects": "效果", "mask": "遮罩", "beats": "節拍",
          "subtitles": "字幕", "curves": "關鍵幀曲線", "timeline": "時間線"}
ORDER = LEFT + ("preview",) + SIDE + ("timeline",)
NOTES = {"effects": "選取的片段沒有效果可用", "mask": "選取的片段不能加遮罩", "beats": "選取一個有聲音的片段",
         "subtitles": "選取文字片段", "curves": "選取一個片段"}


class DockTitle(QWidget):
    """A slim title bar: the name, float / dock back, close."""

    def __init__(self, dock):
        super().__init__(dock)
        self.setObjectName("docktitle")
        self.setAttribute(Qt.WA_StyledBackground)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 1, 2, 1)
        lay.setSpacing(0)
        lab = QLabel(dock.windowTitle())
        lab.setObjectName("title")
        lay.addWidget(lab)
        lay.addStretch()
        for name, tip, fn in (("float", "浮動視窗 / 放回主視窗（也可以雙擊標題）", lambda: dock.setFloating(not dock.isFloating())),
                              ("close", "關閉（視窗選單可以再打開）", dock.close)):
            b = QPushButton()
            b.setObjectName("tool")
            b.setIcon(icons.icon(name))
            b.setIconSize(QSize(12, 12))
            b.setFixedSize(18, 18)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(fn)
            lay.addWidget(b)

    def mouseDoubleClickEvent(self, e):
        d = self.parent()
        d.setFloating(not d.isFloating())

    def sizeHint(self):
        return QSize(80, 20)

    def minimumSizeHint(self):
        return QSize(40, 20)


class Blank(QWidget):
    """The title bar while in tabs: a line, only there for GroupGrip to start the drag of the
    tabs from (Qt drags a dock's tabs with it only from its title bar)."""

    def sizeHint(self):
        return QSize(0, 1)


class GroupGrip(QObject):
    """Dragging the empty part of a tab bar of the main window's panels drags all its panels as
    one: the press there is handed to the front panel's title bar, so Qt drags its tabs with it
    (QMainWindow.GroupedDragging)."""
    TIP = "拖分頁：只拿出這一頁；拖分頁旁的空白：整組一起移動"

    def __init__(self, panels):
        super().__init__(panels)
        self.panels = panels
        self.press = None                     # (tab bar, where) of a press on an empty part

    def eventFilter(self, bar, e):
        t = e.type()
        if t == QEvent.MouseButtonPress:
            pos = e.position().toPoint()
            if e.button() == Qt.LeftButton and bar.tabAt(pos) < 0:
                self.press = (bar, pos)
                return True
        elif t == QEvent.MouseMove and self.press and self.press[0] is bar:
            if (e.position().toPoint() - self.press[1]).manhattanLength() > QApplication.startDragDistance():
                self.press = None
                dock = self.front(bar)
                if dock is not None:
                    self.drag(dock, e)
            return True
        elif t == QEvent.MouseButtonRelease and self.press and self.press[0] is bar:
            self.press = None
            return True
        return False

    def front(self, bar):
        """The panel of the tab bar's current tab."""
        i = bar.currentIndex()
        if i < 0:
            return None
        ptr = bar.tabData(i)                  # (Qt keeps each tab's dock widget there)
        return next((d for d in self.panels.docks.values() if shiboken6.getCppPointer(d)[0] == ptr), None)

    def drag(self, dock, e):
        if not isinstance(dock.titleBarWidget(), Blank):
            return
        x = dock.width() / 2
        here, there = QPointF(x, 0), QPointF(x + QApplication.startDragDistance() + 2, 0)
        for kind, pos, buttons in ((QEvent.MouseButtonPress, here, Qt.LeftButton),
                                   (QEvent.MouseMove, there, Qt.NoButton)):
            QApplication.sendEvent(dock, QMouseEvent(kind, pos, e.globalPosition(), buttons, Qt.LeftButton,
                                                     e.modifiers()))
        # under Wayland the drag is over by now (a platform drag, done in the call above) and
        # the mouse grab Qt takes after it would be left on the panel
        if QGuiApplication.platformName().lower().startswith("wayland"):
            dock.releaseMouse()


class Dock(QDockWidget):
    closedByUser = Signal(str)

    def __init__(self, key, widget, parent=None):
        super().__init__(TITLES[key], parent)
        self.key = key
        self.setObjectName("dock_" + key)
        self.user_closed = False             # closed on purpose: set_usable leaves it closed
        self.auto_hidden = False             # out of its tabs only because the selection cannot use it
        self.stack = QStackedWidget()
        self.stack.addWidget(widget)
        note = QLabel(NOTES.get(key, ""))
        note.setAlignment(Qt.AlignCenter)
        note.setObjectName("viewer")
        self.stack.addWidget(note)
        self.setWidget(self.stack)
        self.title = DockTitle(self)
        self.blank = Blank(self)              # no title bar while in tabs: the tab is its handle
        self.blank.hide()
        self.setTitleBarWidget(self.title)
        self.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable
                         | QDockWidget.DockWidgetFloatable)

    def closeEvent(self, e):
        self.user_closed = True
        self.auto_hidden = False
        super().closeEvent(e)
        self.closedByUser.emit(self.key)

    def show_titlebar(self, on):
        want = self.title if on else self.blank
        if self.titleBarWidget() is not want:
            self.setTitleBarWidget(want)
            (self.blank if on else self.title).hide()
            want.show()


class Panels(QObject):
    """The dock widgets of a QMainWindow (see the module notes)."""
    activeChanged = Signal(str)               # the side panel used last
    changed = Signal()                        # a panel shown, hidden, moved, floated

    def __init__(self, win: QMainWindow, widgets):
        super().__init__(win)
        self.win = win
        self.restoring = False
        self.active = "inspector"
        win.setDockOptions(QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks
                           | QMainWindow.AnimatedDocks | QMainWindow.GroupedDragging)
        win.setTabPosition(Qt.AllDockWidgetAreas, QTabWidget.North)
        self.title_timer = QTimer(self, singleShot=True, interval=0)
        self.title_timer.timeout.connect(self.refresh_titles)
        self.grip = GroupGrip(self)
        self.docks = {}
        for key in ORDER:
            d = Dock(key, widgets[key], win)
            d.visibilityChanged.connect(lambda on, k=key: self._visibility(k, on))
            d.dockLocationChanged.connect(lambda _a: self._later())
            d.topLevelChanged.connect(lambda _f: self._later())
            d.closedByUser.connect(lambda _k: self._later())
            self.docks[key] = d
            win.addDockWidget(Qt.TopDockWidgetArea, d)
        appevents.watch(self, (QEvent.MouseButtonPress,), self.eventFilter)

    def __getitem__(self, key):
        return self.docks[key]

    # -- which side panel is in use -------------------------------------------------------------
    def _visibility(self, key, on):
        self._later()
        if self.restoring:
            return
        d = self.docks[key]
        # a tab switched to (side by side ones become the one in use by a click in them)
        if on and key in SIDE and self.tabbed(d):
            self.set_active(key)
        elif key in SIDE:
            self.activeChanged.emit(self.active)       # (it may have gone away)

    def set_active(self, key):
        if key != self.active:
            self.active = key
        self.activeChanged.emit(key)

    def is_active(self, key):
        return self.active == key and self.docks[key].isVisible()

    def eventFilter(self, obj, e):
        if e.type() == QEvent.MouseButtonPress and isinstance(obj, QWidget):
            w = obj
            while w is not None and not isinstance(w, Dock):
                w = w.parentWidget()
            if w is not None and w.key in SIDE and w.key != self.active and w in self.docks.values():
                self.set_active(w.key)
        return False

    # -- showing ----------------------------------------------------------------------------------
    def tabbed(self, d):
        return not d.isFloating() and any(o.isVisible() or o.auto_hidden for o in self.win.tabifiedDockWidgets(d)
                                          if o is not d and not o.user_closed)

    def show(self, key, raise_=True):
        """Open the panel (closed or not) and bring it to the front."""
        d = self.docks[key]
        d.user_closed = d.auto_hidden = False
        d.show()
        if raise_:
            d.raise_()
        if key in SIDE:
            self.set_active(key)

    def close(self, key):
        self.docks[key].close()

    def set_usable(self, key, on):
        """Whether the selection has use for the side panel."""
        d = self.docks[key]
        d.stack.setCurrentIndex(0 if on else 1)
        if d.user_closed:
            return
        if on and d.auto_hidden:
            d.auto_hidden = False
            d.show()
        elif not on and not d.auto_hidden and d.isVisible() and self.tabbed(d):
            d.auto_hidden = True
            d.hide()

    def _later(self):
        if not self.restoring:
            self.title_timer.start()
        self.changed.emit()

    def refresh_titles(self):
        """Title bars only on panels that are not in tabs (the tabs carry the names there)."""
        if QApplication.mouseButtons() != Qt.NoButton:        # not in the middle of a drag
            self.title_timer.start(150)
            return
        for d in self.docks.values():
            d.show_titlebar(not self.tabbed(d))
        for bar in self.win.findChildren(QTabBar):          # (Qt makes them as panels go into tabs)
            if bar.metaObject().className() == "QMainWindowTabBar":
                bar.installEventFilter(self.grip)          # (again on the same one: still once)
                bar.setToolTip(GroupGrip.TIP)

    # -- layouts -----------------------------------------------------------------------------------
    def closed(self):
        return [k for k, d in self.docks.items() if d.user_closed]

    def state(self):
        return bytes(self.win.saveState(STATE_VERSION))

    def arrange(self, ident):
        """Put the panels as the built-in layout ident (layouts.BUILTIN) has them."""
        self.restoring = True
        try:
            w, D = self.win, self.docks
            for d in D.values():
                d.setFloating(False)
                w.removeDockWidget(d)
                d.user_closed = d.auto_hidden = False
            closed = ()
            if ident == "design":                     # as in a drawing program: a big canvas
                w.addDockWidget(Qt.TopDockWidgetArea, D["assets"])
                w.splitDockWidget(D["assets"], D["preview"], Qt.Horizontal)
                w.splitDockWidget(D["preview"], D["inspector"], Qt.Horizontal)
                w.splitDockWidget(D["assets"], D["compounds"], Qt.Vertical)
                for k in ("library", "userlib", "vfx"):
                    w.tabifyDockWidget(D["assets"], D[k])
                for k in ("effects", "mask", "curves", "beats", "subtitles"):
                    w.tabifyDockWidget(D["inspector"], D[k])
                w.addDockWidget(Qt.BottomDockWidgetArea, D["timeline"])
                closed = ("curves", "beats", "subtitles")
                sizes = ((("assets", "preview", "inspector"), (290, 1000, 360), Qt.Horizontal),
                         (("assets", "compounds"), (430, 260), Qt.Vertical),
                         (("preview", "timeline"), (720, 220), Qt.Vertical))
                front = ("assets", "inspector")
            else:                                     # 一般剪片: the panels around the preview, the timeline below
                w.addDockWidget(Qt.TopDockWidgetArea, D["library"])
                w.splitDockWidget(D["library"], D["preview"], Qt.Horizontal)
                w.splitDockWidget(D["preview"], D["inspector"], Qt.Horizontal)
                for k in LEFT[1:]:
                    w.tabifyDockWidget(D["library"], D[k])
                for k in SIDE[1:]:
                    w.tabifyDockWidget(D["inspector"], D[k])
                w.addDockWidget(Qt.BottomDockWidgetArea, D["timeline"])
                sizes = ((("library", "preview", "inspector"), (360, 840, 420), Qt.Horizontal),
                         (("preview", "timeline"), (560, 360), Qt.Vertical))
                front = ("library", "inspector")
            for d in D.values():
                d.show()
            for k in closed:
                D[k].hide()
                D[k].user_closed = True
            for keys, px, how in sizes:
                w.resizeDocks([D[k] for k in keys], list(px), how)
            for k in front:
                D[k].raise_()
        finally:
            self.restoring = False
        self.active = "inspector"
        self.refresh_titles()
        self.activeChanged.emit(self.active)

    def restore(self, state, closed):
        """A saved layout (state(), closed()); False when the state could not be used (the
        panels stay as they were)."""
        self.restoring = True
        try:
            ok = self.win.restoreState(state, STATE_VERSION)
            if ok:
                for k, d in self.docks.items():
                    d.user_closed = k in closed
                    d.auto_hidden = False
                    if not d.user_closed and d.isHidden():    # hidden only for the selection then
                        d.show()
                    elif d.user_closed and not d.isHidden():
                        d.hide()
        finally:
            self.restoring = False
        self.active = "inspector"
        self.refresh_titles()
        self.activeChanged.emit(self.active)
        return ok
