"""點選來源: a picker's ◎ button, then one click on what to use - a picture or a video in 專案素材
or the user's Library, a clip on the timeline, or a compound in the compound list (whichever
kinds the picker takes). The window says what is under the click (MainWindow.media_at); a
click on nothing it can use, a right click or Esc ends it without a choice."""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QPushButton

_active = None


def _window():
    return next((w for w in QApplication.topLevelWidgets() if hasattr(w, "media_at")), None)


class TargetPick(QObject):
    def __init__(self, kinds, on_pick, button):
        super().__init__(button)
        self.kinds, self.on_pick, self.button = tuple(kinds), on_pick, button

    def start(self):
        global _active
        if _active is not None:
            _active.stop()
        win = _window()
        if win is None:
            return
        _active = self
        self.button.setChecked(True)
        QApplication.instance().installEventFilter(self)
        QApplication.setOverrideCursor(Qt.CrossCursor)
        what = "、".join({"image": "圖片", "video": "影片", "compound": "複合片段"}[k] for k in self.kinds)
        win.statusBar().showMessage(f"點一下要用的{what}：素材庫、Library 或時間線上的片段（Esc 取消）")

    def stop(self):
        global _active
        if _active is not self:
            return
        _active = None
        QApplication.instance().removeEventFilter(self)
        QApplication.restoreOverrideCursor()
        if self.button is not None:
            self.button.setChecked(False)
        win = _window()
        if win is not None:
            win.statusBar().clearMessage()

    def eventFilter(self, obj, e):
        t = e.type()
        if t == QEvent.KeyPress and e.key() == Qt.Key_Escape:
            self.stop()
            return True
        if t in (QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
            return True
        if t != QEvent.MouseButtonPress:
            return False
        gp = e.globalPosition().toPoint()
        self.stop()
        if e.button() != Qt.LeftButton or obj is self.button:
            return True
        win = _window()
        got = win.media_at(gp, self.kinds) if win is not None else None
        if got:
            self.on_pick(got)
        elif win is not None:
            win.statusBar().showMessage("那裡沒有可以用的來源", 3000)
        return True                                      # (the click picks; it does nothing else)


def pick_button(kinds, on_pick):
    """A ◎ button that starts picking kinds ("image", "video", "compound"); on_pick(path or
    compound id) gets what was clicked."""
    b = QPushButton("◎")
    b.setCheckable(True)
    b.setFixedWidth(28)
    b.setFocusPolicy(Qt.NoFocus)
    b.setToolTip("點選來源：按一下，再點素材庫、Library 或時間線上的片段")
    picker = TargetPick(kinds, on_pick, b)
    b.clicked.connect(lambda _on: picker.stop() if _active is picker else picker.start())
    return b
