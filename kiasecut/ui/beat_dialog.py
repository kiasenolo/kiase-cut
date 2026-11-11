"""進階對齊編輯器: the window for a sound clip's BPM alignment in detail (opened from the 節拍 panel's
進階設定… or Alt+Shift+B). All its times are the sound's own (source time, us), not the timeline's.

Stage 1: the empty window - it names the clip and follows it (closing when the clip is gone)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

from .. import edit


class BeatDialog(QDialog):
    """Not modal: the timeline stays usable beside it. One window for one clip."""

    def __init__(self, clip_id, parent=None):
        super().__init__(parent)
        self.clip_id = clip_id
        self.setWindowTitle("進階對齊編輯器")
        self.setModal(False)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(900, 520)
        lay = QVBoxLayout(self)
        self.title = QLabel()
        lay.addWidget(self.title)
        lay.addStretch(1)

    def show_clip(self, proj):
        """Refresh from the project; False when the clip no longer exists (or has no sound)."""
        try:
            _, c = edit.find(proj, self.clip_id)
        except Exception:
            return False
        if not edit.has_sound(c):
            return False
        self.title.setText(f"片段：{c.get('name', '')}")
        return True
