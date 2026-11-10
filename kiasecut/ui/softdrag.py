"""Drag and drop made by the program itself, for a finger.

Qt for Android hands a drag to the system (View.startDragAndDrop), which takes the finger over from the program: the touches
that touch.py turns into a mouse never come to it, and a library item held and moved onto the timeline went nowhere. Here the
drag runs inside the program: a picture of what is dragged follows the pointer, the widget under it is sent the drag-enter /
drag-move / drop events a window system would send, and the mouse events (the finger's, as touch.py makes them) are eaten
meanwhile, as Qt's own simple drag does.

exec_drag(drag, actions, default) is `drag.exec(...)` that picks the way; install() makes every item view (the library, the
素材, the VFX lists) start its drags that way. It is on for Android, and for a desktop when KIASECUT_SOFTDRAG is set.
"""
import os
import sys

import shiboken6
from PySide6.QtCore import QEvent, QEventLoop, QObject, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QPainter, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QApplication, QLabel

from . import appevents

FORCE = bool(os.environ.get("KIASECUT_SOFTDRAG"))
GHOST_OPACITY = 0.75
GHOST_MAX = (220, 120)              # a picture of the dragged rows is cut to this
GHOST_LIFT = 28                     # px: the picture floats this far above the pointer (a finger would hide it)


def active():
    return FORCE or sys.platform == "android"


def exec_drag(drag, actions=Qt.CopyAction, default=Qt.IgnoreAction):
    """`drag.exec(actions, default)`, or the program's own drag where the system's cannot be used."""
    if not active():
        return drag.exec(actions, default)
    return _Drag(drag, actions, default).run()


def proposed(actions, default):
    """The action a drop would be, as Qt picks it: the default one if it is allowed, else the first allowed."""
    if default != Qt.IgnoreAction and actions & default:
        return default
    for a in (Qt.CopyAction, Qt.MoveAction, Qt.LinkAction):
        if actions & a:
            return a
    return Qt.IgnoreAction


class _Drag(QObject):
    def __init__(self, drag, actions, default):
        super().__init__()
        self.drag, self.actions = drag, actions
        self.action = proposed(actions, default)
        self.mime = drag.mimeData()
        self.target = None                    # the widget the pointer is over that takes drops
        self.accepted = False                 # ... and has said it takes this
        self.result = Qt.IgnoreAction
        self.loop = QEventLoop()
        self.ghost = None
        self.window = None

    def run(self):
        source = self.drag.source()
        self.window = source.window() if isinstance(source, QObject) and hasattr(source, "window") else QApplication.activeWindow()
        self._make_ghost()
        app = QApplication.instance()
        app.installEventFilter(self)
        try:
            self.loop.exec()
        finally:
            if shiboken6.isValid(app):
                app.removeEventFilter(self)
            if self.ghost is not None and shiboken6.isValid(self.ghost):
                self.ghost.deleteLater()
        return self.result

    # -- the picture that follows the pointer -------------------------------------------------------------------------------
    def _make_ghost(self):
        pm = self.drag.pixmap()
        if self.window is None or pm.isNull():
            return
        faint = QPixmap(pm.size())
        faint.setDevicePixelRatio(pm.devicePixelRatio())
        faint.fill(Qt.transparent)
        p = QPainter(faint)
        p.setOpacity(GHOST_OPACITY)
        p.drawPixmap(0, 0, pm)
        p.end()
        self.ghost = QLabel(self.window)
        self.ghost.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.ghost.setAttribute(Qt.WA_TranslucentBackground)
        self.ghost.setStyleSheet("background: transparent;")
        self.ghost.setPixmap(faint)
        self.ghost.adjustSize()
        self.ghost.hide()                     # (shown at the first move: nothing is known of where the pointer is before)

    def _place_ghost(self, g):
        if self.ghost is None:
            return
        at = self.window.mapFromGlobal(g) - self.drag.hotSpot()
        self.ghost.move(at)
        if not self.ghost.isVisible():
            self.ghost.show()
        self.ghost.raise_()

    # -- the events the system would send ---------------------------------------------------------------------------------------
    def eventFilter(self, obj, e):
        t = e.type()
        if t == QEvent.MouseMove:
            self._move(e.globalPosition().toPoint(), e.buttons(), e.modifiers())
            return True                                       # (all mouse events are the drag's)
        if t == QEvent.MouseButtonRelease:
            self._drop(e.globalPosition().toPoint(), e.modifiers())
            return True
        if t in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick, QEvent.Wheel, QEvent.ContextMenu):
            return True
        if t == QEvent.KeyPress and e.key() == Qt.Key_Escape:
            self._leave()
            self._end(Qt.IgnoreAction)
            return True
        return False

    @staticmethod
    def _acceptor(widget):
        while widget is not None and not widget.acceptDrops():
            widget = widget.parentWidget()
        return widget

    def _send(self, widget, ev):
        QApplication.sendEvent(widget, ev)
        return ev

    def _move(self, g, buttons, mods):
        self._place_ghost(g)
        target = self._acceptor(QApplication.widgetAt(g))
        if target is not self.target:
            self._leave()
            self.target = target
            if target is not None:
                ev = QDragEnterEvent(target.mapFromGlobal(g), self.actions, self.mime, buttons, mods)
                ev.setDropAction(self.action)
                self._send(target, ev)
                self.accepted = ev.isAccepted()
                self.action = ev.dropAction() if self.accepted else self.action
        if self.target is not None:
            ev = QDragMoveEvent(self.target.mapFromGlobal(g), self.actions, self.mime, buttons, mods)
            ev.setDropAction(self.action)
            self._send(self.target, ev)
            self.accepted = ev.isAccepted()
            if self.accepted:
                self.action = ev.dropAction()

    def _leave(self):
        if self.target is not None and shiboken6.isValid(self.target):
            self._send(self.target, QDragLeaveEvent())
        self.target, self.accepted = None, False

    def _drop(self, g, mods):
        target, taken = self.target, self.accepted
        if target is None or not taken or not shiboken6.isValid(target):
            self._leave()
            self._end(Qt.IgnoreAction)
            return
        ev = QDropEvent(QPointF(target.mapFromGlobal(g)), self.actions, self.mime, Qt.NoButton, mods)
        ev.setDropAction(self.action)
        self._send(target, ev)
        self.target = None
        self._end(ev.dropAction() if ev.isAccepted() else Qt.IgnoreAction)

    def _end(self, action):
        self.result = action
        self.loop.quit()


def start_drag(view, supported):
    """QAbstractItemView.startDrag, made here: the selected rows that can be dragged, dragged by exec_drag."""
    sel = view.selectionModel()
    indexes = [i for i in (sel.selectedIndexes() if sel is not None else []) if i.flags() & Qt.ItemIsDragEnabled]
    if not indexes:
        return
    data = view.model().mimeData(indexes)
    if data is None:
        return
    rect = QRect()
    for i in indexes:
        rect = rect.united(view.visualRect(i))
    rect = rect.intersected(view.viewport().rect())
    pm = view.viewport().grab(rect) if not rect.isEmpty() else QPixmap()
    if pm.width() > GHOST_MAX[0] or pm.height() > GHOST_MAX[1]:
        pm = pm.copy(0, 0, min(pm.width(), GHOST_MAX[0]), min(pm.height(), GHOST_MAX[1]))
    from PySide6.QtGui import QDrag
    drag = QDrag(view)
    drag.setMimeData(data)
    drag.setPixmap(pm)
    drag.setHotSpot(QPoint(pm.width() // 2, pm.height() + GHOST_LIFT))
    default = view.defaultDropAction()
    if default == Qt.IgnoreAction or not supported & default:
        default = Qt.CopyAction if supported & Qt.CopyAction and view.dragDropMode() != QAbstractItemView.InternalMove \
            else Qt.IgnoreAction
    exec_drag(drag, supported, default)


class _Starter(QObject):
    """Starts the drags of the item views: a view (or its viewport) is a Python subclass whose startDrag cannot be replaced from
    here, so the press and the move that Qt would turn into a drag are watched for instead, and the drag is made here."""

    def __init__(self):
        super().__init__()
        self.press = None                                 # (the view, where the left button went down)

    @staticmethod
    def view_of(obj):
        view = obj.parent() if isinstance(obj, QObject) else None
        return view if isinstance(view, QAbstractItemView) and view.viewport() is obj else None

    TYPES = (QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.MouseButtonRelease)      # (the events eventFilter looks at: appevents hands it no others)

    def eventFilter(self, obj, e):
        t = e.type()
        if t == QEvent.MouseButtonPress and e.button() == Qt.LeftButton:
            view = self.view_of(obj)
            at = e.position().toPoint() if view is not None else None
            ok = view is not None and view.dragEnabled() and view.indexAt(at).isValid() \
                and view.indexAt(at).flags() & Qt.ItemIsDragEnabled
            self.press = (view, at) if ok else None
        elif t == QEvent.MouseMove and self.press is not None and e.buttons() & Qt.LeftButton:
            view, at = self.press
            if obj is view.viewport() and (e.position().toPoint() - at).manhattanLength() >= QApplication.startDragDistance():
                self.press = None
                start_drag(view, view.model().supportedDragActions())
                return True
        elif t == QEvent.MouseButtonRelease:
            self.press = None
        return False


_starter = None


def install():
    """Every item view starts its drags through exec_drag (when the system's drag is not to be used)."""
    global _starter
    if active() and _starter is None:
        _starter = _Starter()
        appevents.watch(_starter, _Starter.TYPES, _starter.eventFilter, first=True)


def uninstall():
    global _starter
    if _starter is not None:
        appevents.unwatch(_starter)
        _starter = None
