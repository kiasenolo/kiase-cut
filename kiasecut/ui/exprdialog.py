"""The expression editor (表達式, expr.py): a text box that reads the expression as it is typed -
the reason when it cannot be read, else what it gives for a few sample values of `input` and
the moment - with the names and functions it can use listed under it."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout

from .. import expr

HELP = ("名稱：{names}\n"
        "運算：+ - * / % **　比較：< <= > >= == !=　邏輯：&& || !　條件：a ? b : c\n"
        "函式：Math.sin cos tan abs min max floor ceil round sqrt pow … 、clamp(x, 低, 高)、lerp(a, b, t)、\n"
        "smoothstep(低, 高, x)、remap(x, a, b, c, d)、cubicBezier(x1, y1, x2, y2, x)、noise(x)、random(種子)、wiggle(次數/秒, 幅度)")


def sample_text(text, env):
    """What the expression gives for the sample env, as one line (or why it cannot be worked out)."""
    why = expr.check(text)
    if why:
        return "✗ " + why
    out = []
    for label, sample in env:
        try:
            out.append(f"{label} → {expr.number(text, sample):.4g}")
        except expr.ExprError as e:
            return f"✗ {label}：{e}"
    return "✓ " + "　".join(out)


class ExprDialog(QDialog):
    """Edit one expression. `names` are the plain names it may read ({name: sample value});
    `samples` are the values of the first name to try."""

    def __init__(self, parent, title, text, names, default="input", note=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.names, self.default = dict(names), default
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        if note:
            lab = QLabel(note)
            lab.setWordWrap(True)
            lab.setStyleSheet("color: #9a9aa0;")
            lay.addWidget(lab)
        self.box = QPlainTextEdit(text or default)
        self.box.setFont(QFont("monospace"))
        self.box.setFixedHeight(96)
        self.box.setTabChangesFocus(True)
        lay.addWidget(self.box)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        help_ = QLabel(HELP.format(names="、".join(self.names)))
        help_.setStyleSheet("color: #8a8a90;")
        help_.setWordWrap(True)
        lay.addWidget(help_)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.RestoreDefaults).setText(f"還原（{default}）")
        self.buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(lambda: self.box.setPlainText(default))
        lay.addWidget(self.buttons)
        self.box.textChanged.connect(self._changed)
        self._changed()

    def _env(self):
        first = next(iter(self.names), None)
        out = []
        for v in (0.0, 0.5, 1.0):
            env = dict(self.names)
            if first:
                env[first] = v
            out.append((f"{first}={v:g}" if first else "", env))
        return out

    def _changed(self):
        text = self.box.toPlainText().strip()
        ok = expr.check(text) is None
        self.status.setText(sample_text(text, self._env()))
        self.status.setStyleSheet("color: #6fd08c;" if ok else "color: #ff7a7a;")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ok)

    def text(self):
        return self.box.toPlainText().strip()


def ask_expression(parent, title, text, names, default="input", note=""):
    """The expression typed, or None when cancelled."""
    d = ExprDialog(parent, title, text, names, default, note)
    d.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
    return d.text() if d.exec() == QDialog.Accepted else None
