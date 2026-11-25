"""Measures the global parameters that follow a sound (soundmeter.py) behind the editor's back:
after edits have rested a moment, on a thread of its own. Until a new curve is there the old one
is read (0 before the first)."""
import threading

from PySide6.QtCore import QObject, QTimer, Signal

from .. import soundmeter

REST_MS = 600


class MeterWorker(QObject):
    changed = Signal()                      # the numbers the parameters read are new ones (or there are new problems)
    busy = Signal(bool)
    _ended = Signal(object, object)         # (the thread to the window's: the plan it ran, {id: why not} or None: given up)

    def __init__(self, project_of, cache_of, parent=None):
        """project_of() -> the project (or None), cache_of() -> its cache folder."""
        super().__init__(parent)
        self.project_of, self.cache_of = project_of, cache_of
        self.problems = {}                  # parameter id -> why it cannot be measured
        self.running = None                 # (thread, plan, cancel event)
        self.waiting = False                # asked again while running: look once more when done
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.look)
        self._ended.connect(self._done)

    def request(self, now=False):
        """The project may have changed."""
        self.timer.start(0 if now else REST_MS)

    def forget(self):
        """Another project is open."""
        self.cancel()
        soundmeter.forget()
        self.problems = {}

    def cancel(self):
        self.timer.stop()
        self.waiting = False
        if self.running:
            self.running[2].set()

    def look(self):
        root = self.project_of()
        if root is None:
            return
        if not soundmeter.sounding(root) and not soundmeter.stale_without(root):
            self.problems = {}
            return
        todo = soundmeter.plan(root)
        if self.running:
            if self.running[1].keys() != todo.keys():
                self.running[2].set()
                self.waiting = True
            return
        if not todo.stale():
            if todo.problems != self.problems:
                self.problems = dict(todo.problems)
                self.changed.emit()
            return
        cancel, cache = threading.Event(), self.cache_of()

        def work():
            try:
                found = soundmeter.run(todo, cache, cancel.is_set)
            except soundmeter.Cancelled:
                found = None
            except Exception as exc:                # (said in the rows; the next edit tries again)
                found = {j.rid: f"{type(exc).__name__}: {exc}" for j in todo.jobs}
            try:
                self._ended.emit(todo, found)
            except RuntimeError:                    # (the window is gone)
                pass

        thread = threading.Thread(target=work, daemon=True)
        self.running = (thread, todo, cancel)
        self.busy.emit(True)
        thread.start()

    def _done(self, todo, found):
        self.running = None
        self.busy.emit(False)
        if found is not None:
            self.problems = found
            self.changed.emit()
        if self.waiting:
            self.waiting = False
            self.look()
