"""One event filter on the whole program for the parts that watch its key and mouse presses.

Qt hands every event in the program - a widget made, laid out, painted, a timer - to each filter
on the application, and each is a call into Python: three of them made building the inspector's
form for a selection two and a half times slower. This one filter passes on only the kinds of
event each watcher asked for, newest watcher first (as Qt orders its filters), until one takes it.
"""
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

_hub = None


class _Hub(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.watchers = {}          # event type -> [(key, fn)], newest first
        app.installEventFilter(self)

    def eventFilter(self, obj, e):
        fns = self.watchers.get(e.type())
        if fns:
            for _key, fn in list(fns):
                if fn(obj, e):
                    return True
        return False

    def drop(self, key):
        for t, fns in list(self.watchers.items()):
            fns[:] = [x for x in fns if x[0] != key]
            if not fns:
                del self.watchers[t]


def watch(owner, types, fn):
    """fn(obj, event) -> True to take it, for every event of these types in the program, while
    QObject owner lives."""
    global _hub
    app = QApplication.instance()
    if _hub is None or _hub.app is not app:
        _hub = _Hub(app)
    hub, key = _hub, id(owner)
    for t in types:
        hub.watchers.setdefault(t, []).insert(0, (key, fn))
    owner.destroyed.connect(lambda _o=None: hub.drop(key))
