"""The extra tools (工具 menu): built into the program, each opened from the menu in a window of
its own that stays open beside the editor. What they keep is in toolsdata.py.

  * cubic-bezier 編輯器: drag the two handles (or type the value), press ▶ 播放 to watch a ball move
    along it (for 時間長度 seconds) against a linear one, keep curves under names, copy their value (cubic-bezier(x1, y1, x2, y2)); the
    curves kept here are also offered by the curve editor's 我的曲線.
  * 調色盤: colour cards - each with a name, an Info text and its colours (added with the
    picker, its eyedropper included); a card is imported / exported as a JSON string[] of
    colours. The colour picker shows the cards too."""
import os
import time

from PySide6.QtCore import QPointF, QRectF, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
                               QVBoxLayout, QWidget)

from .. import curves, toolsdata
from .colorpick import pick_color, qcolor
from .curve_editor import PRESETS
from .menukeys import Menu


SETTINGS = ("KiaseCut", "KiaseCut")


def ease(v, x):
    """y of cubic-bezier v at x (0 - 1)."""
    x1, y1, x2, y2 = v
    lo, hi = 0.0, 1.0
    for _ in range(40):                                  # the curve's t for this x, by halving
        t = (lo + hi) / 2
        bx = 3 * (1 - t) ** 2 * t * x1 + 3 * (1 - t) * t * t * x2 + t ** 3
        lo, hi = (t, hi) if bx < x else (lo, t)
    t = (lo + hi) / 2
    return 3 * (1 - t) ** 2 * t * y1 + 3 * (1 - t) * t * t * y2 + t ** 3


class BezierField(QWidget):
    """The curve in its square (y from -0.5 to 1.5 shows overshoot); the two handles drag - with Shift held,
    along one direction only: across or up and down, whichever it has gone further."""
    changed = Signal(list)

    def __init__(self):
        super().__init__()
        self.v = [0.42, 0.0, 0.58, 1.0]
        self.drag = None
        self.start = None
        self.setMinimumSize(260, 300)

    def frame(self):
        side = min(self.width() - 40, (self.height() - 40) / 2)
        x0 = (self.width() - side) / 2
        y0 = (self.height() - 2 * side) / 2 + side * 1.5      # where y = 0 is (y up to 1.5, down to -0.5)
        return x0, y0, side

    def at(self, x, y):
        x0, y0, side = self.frame()
        return QPointF(x0 + x * side, y0 - y * side)

    def set_value(self, v):
        self.v = [float(a) for a in v]
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#18181b"))
        x0, y0, side = self.frame()
        p.fillRect(QRectF(x0, y0 - side, side, side), QColor("#232327"))
        p.setPen(QPen(QColor("#3a3a40"), 1, Qt.DotLine))
        for k in range(1, 4):
            p.drawLine(self.at(k / 4, 0), self.at(k / 4, 1))
            p.drawLine(self.at(0, k / 4), self.at(1, k / 4))
        p.setPen(QPen(QColor("#55555c"), 1))
        p.drawLine(self.at(0, 0), self.at(1, 1))
        x1, y1, x2, y2 = self.v
        p.setPen(QPen(QColor("#8e8e94"), 1.5))
        p.drawLine(self.at(0, 0), self.at(x1, y1))
        p.drawLine(self.at(1, 1), self.at(x2, y2))
        path = QPainterPath(self.at(0, 0))
        path.cubicTo(self.at(x1, y1), self.at(x2, y2), self.at(1, 1))
        p.setPen(QPen(QColor("#6fb3ff"), 3))
        p.drawPath(path)
        for (hx, hy), col in (((x1, y1), "#ff6b9a"), ((x2, y2), "#5ad6a0")):
            p.setPen(QPen(QColor("#ffffff"), 1.5))
            p.setBrush(QColor(col))
            p.drawEllipse(self.at(hx, hy), 7, 7)

    def mousePressEvent(self, e):
        pos = e.position()
        d = [(pos - self.at(self.v[0], self.v[1])).manhattanLength(), (pos - self.at(self.v[2], self.v[3])).manhattanLength()]
        self.drag = 0 if d[0] <= d[1] else 1
        self.start = (pos, list(self.v[2 * self.drag:2 * self.drag + 2]))      # (where it was: Shift keeps one of the two)
        self.mouseMoveEvent(e)

    def mouseMoveEvent(self, e):
        if self.drag is None:
            return
        x0, y0, side = self.frame()
        x = min(1.0, max(0.0, (e.position().x() - x0) / side))
        y = min(1.5, max(-0.5, (y0 - e.position().y()) / side))
        if e.modifiers() & Qt.ShiftModifier:                # Shift: one direction only - whichever way it has gone further
            if abs(e.position().x() - self.start[0].x()) >= abs(e.position().y() - self.start[0].y()):
                y = self.start[1][1]
            else:
                x = self.start[1][0]
        self.v[2 * self.drag:2 * self.drag + 2] = [round(x, 3), round(y, 3)]
        self.update()
        self.changed.emit(list(self.v))

    def mouseReleaseEvent(self, _e):
        self.drag = None


class BezierPreview(QWidget):
    """Two balls going across: the curve's on top, a linear one under it. It rests at the start until play()
    is called, goes across once in `seconds`, and rests at the end."""
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.v = [0.42, 0.0, 0.58, 1.0]
        self.seconds = 1.6
        self.k = 0.0                                     # how far along (0 - 1) it is
        self.t0 = None                                   # when it was started (None: not going)
        self.setMinimumHeight(70)
        self.timer = QTimer(self, interval=16)
        self.timer.timeout.connect(self._tick)

    def play(self):
        self.k, self.t0 = 0.0, time.monotonic()
        self.timer.start()
        self.update()

    def reset(self):
        self.timer.stop()
        self.k, self.t0 = 0.0, None
        self.update()

    def playing(self):
        return self.t0 is not None

    def _tick(self):
        self.k = min(1.0, (time.monotonic() - self.t0) / max(self.seconds, 0.05))
        if self.k >= 1.0:
            self.timer.stop()
            self.t0 = None
            self.finished.emit()
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#18181b"))
        w = self.width() - 40
        for row, (x, col) in enumerate(((ease(self.v, self.k), "#6fb3ff"), (self.k, "#55555c"))):
            y = self.height() * (0.33 + 0.36 * row)
            p.setPen(QPen(QColor("#2e2e33"), 2))
            p.drawLine(QPointF(20, y), QPointF(20 + w, y))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(col))
            p.drawEllipse(QPointF(20 + w * x, y), 9, 9)


class BezierTool(QWidget):
    def __init__(self, root_of):
        super().__init__(None, Qt.Window)
        self.root_of = root_of                           # () -> the KiaseCut root folder (設定 > 根資料夾)
        self.setWindowTitle("cubic-bezier 編輯器")
        self.resize(760, 560)
        self.field = BezierField()
        self.preview = BezierPreview()
        self.text = QLineEdit()
        self.text.editingFinished.connect(self._typed)
        copy = QPushButton("複製")
        copy.clicked.connect(lambda: self._copy(self.field.v))
        left = QVBoxLayout()
        left.addWidget(self.field, 1)
        left.addWidget(self.preview)
        play = QHBoxLayout()                             # (nothing moves until 播放 is pressed)
        self.play_btn = QPushButton("▶ 播放")
        self.play_btn.setToolTip("讓下面的球照這條曲線跑一次（上面藍色的是曲線，下面灰色的是等速）")
        self.play_btn.clicked.connect(self.preview.play)
        play.addWidget(self.play_btn)
        play.addWidget(QLabel("時間長度"))
        self.seconds = QDoubleSpinBox()
        self.seconds.setRange(0.1, 30.0)
        self.seconds.setDecimals(2)
        self.seconds.setSingleStep(0.1)
        self.seconds.setSuffix(" 秒")
        self.seconds.setValue(self.preview.seconds)
        self.seconds.valueChanged.connect(self._seconds)
        play.addWidget(self.seconds)
        play.addStretch(1)
        left.addLayout(play)
        row = QHBoxLayout()
        row.addWidget(self.text, 1)
        row.addWidget(copy)
        left.addLayout(row)
        grid = QGridLayout()
        for i, (name, spec) in enumerate(PRESETS):
            b = QPushButton(name)
            b.clicked.connect(lambda _=False, s=spec: self.set_value(s))
            grid.addWidget(b, 0, i)
        left.addLayout(grid)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda it: self.set_value(it.data(Qt.UserRole)["value"]))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        save = QPushButton("儲存目前的曲線…")
        save.clicked.connect(self._save)
        right = QVBoxLayout()
        right.addWidget(QLabel("我的曲線（按兩下套用，右鍵：複製數值、重新命名、刪除）"))
        right.addWidget(self.list, 1)
        right.addWidget(save)
        lw, rw = QWidget(), QWidget()
        lw.setLayout(left)
        rw.setLayout(right)
        split = QSplitter()
        split.addWidget(lw)
        split.addWidget(rw)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay = QVBoxLayout(self)
        lay.addWidget(split)
        self.field.changed.connect(self._show)
        try:                                              # (the length last used)
            self.seconds.setValue(float(QSettings(*SETTINGS).value("tools/bezier_seconds", 1.6)))
        except (TypeError, ValueError):
            pass
        self.set_value([0.42, 0.0, 0.58, 1.0])
        self.fill()

    def _seconds(self, v):
        self.preview.seconds = v
        QSettings(*SETTINGS).setValue("tools/bezier_seconds", v)

    def set_value(self, v):
        self.field.set_value(v)
        self._show(list(v))

    def _show(self, v):
        self.preview.v = list(v)
        self.text.setText(toolsdata.bezier_text(v))

    def _typed(self):
        try:
            self.set_value(curves.parse_bezier(self.text.text()))
        except ValueError as exc:
            QMessageBox.information(self, "cubic-bezier", str(exc))

    def _copy(self, v):
        QGuiApplication.clipboard().setText(toolsdata.bezier_text(v))

    def fill(self):
        self.list.clear()
        for c in toolsdata.load_curves(self.root_of()):
            it = QListWidgetItem(f"{c['name']}    {toolsdata.bezier_text(c['value'])}")
            it.setData(Qt.UserRole, c)
            self.list.addItem(it)

    def _saved(self, change):
        cs = toolsdata.load_curves(self.root_of())
        change(cs)
        toolsdata.save_curves(self.root_of(), cs)
        self.fill()

    def _save(self):
        name, ok = QInputDialog.getText(self, "儲存曲線", "名稱", text="我的曲線")
        if ok and name.strip():
            self._saved(lambda cs: cs.append({"name": name.strip(), "value": list(self.field.v)}))

    def _menu(self, pos):
        it = self.list.itemAt(pos)
        if it is None:
            return
        row = self.list.row(it)
        c = it.data(Qt.UserRole)
        menu = Menu(self)
        menu.addAction("套用", lambda: self.set_value(c["value"]))
        menu.addAction("複製數值", lambda: self._copy(c["value"]))
        menu.addAction("用目前的曲線覆寫", lambda: self._saved(lambda cs: cs[row].update(value=list(self.field.v))))

        def rename():
            name, ok = QInputDialog.getText(self, "重新命名", "名稱", text=c["name"])
            if ok and name.strip():
                self._saved(lambda cs: cs[row].update(name=name.strip()))
        menu.addAction("重新命名…", rename)
        menu.addAction("刪除", lambda: self._saved(lambda cs: cs.pop(row)))
        menu.exec(self.list.viewport().mapToGlobal(pos))


class Swatch(QPushButton):
    def __init__(self, col):
        super().__init__()
        self.col = col
        self.setFixedSize(40, 40)
        self.setToolTip(col + "（按一下複製；右鍵：修改、刪除）")
        c = qcolor(col)
        self.setStyleSheet(f"background: {c.name()}; border: 1px solid #555; border-radius: 3px;")


class PaletteTool(QWidget):
    def __init__(self, root_of):
        super().__init__(None, Qt.Window)
        self.root_of = root_of
        self.setWindowTitle("調色盤")
        self.resize(720, 480)
        self.cards = []
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._shown)
        buttons = QHBoxLayout()
        for text, fn in (("新增色卡", self._new), ("匯入…", self._import), ("匯出…", self._export), ("刪除", self._delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            buttons.addWidget(b)
        left = QVBoxLayout()
        left.addWidget(self.list, 1)
        left.addLayout(buttons)
        self.name = QLineEdit()
        self.name.editingFinished.connect(self._renamed)
        self.info = QPlainTextEdit()
        self.info.setPlaceholderText("Info：這張色卡的說明（用在哪裡、出處…）")
        self.info.setFixedHeight(80)
        self.info.textChanged.connect(self._info_changed)
        self.colors = QWidget()
        self.grid = QGridLayout(self.colors)
        self.grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        add = QPushButton("＋ 新增顏色")
        add.clicked.connect(self._add_color)
        right = QVBoxLayout()
        right.addWidget(QLabel("名稱"))
        right.addWidget(self.name)
        right.addWidget(QLabel("Info"))
        right.addWidget(self.info)
        right.addWidget(QLabel("顏色"))
        right.addWidget(self.colors, 1)
        right.addWidget(add)
        lw, rw = QWidget(), QWidget()
        lw.setLayout(left)
        rw.setLayout(right)
        split = QSplitter()
        split.addWidget(lw)
        split.addWidget(rw)
        split.setStretchFactor(1, 2)
        lay = QVBoxLayout(self)
        lay.addWidget(split)
        self.info_timer = QTimer(self, singleShot=True, interval=500)
        self.info_timer.timeout.connect(self._keep)
        self.fill()

    def card(self):
        i = self.list.currentRow()
        return self.cards[i] if 0 <= i < len(self.cards) else None

    def fill(self, select=None):
        self.cards = toolsdata.load_cards(self.root_of())
        self.list.blockSignals(True)
        self.list.clear()
        for c in self.cards:
            self.list.addItem(f"{c['name']}  ({len(c['colors'])})")
        self.list.blockSignals(False)
        i = next((k for k, c in enumerate(self.cards) if c["file"] == select), 0 if self.cards else -1)
        self.list.setCurrentRow(i)
        self._shown(i)

    def _shown(self, _i):
        c = self.card()
        for w in (self.name, self.info):
            w.blockSignals(True)
        self.name.setText(c["name"] if c else "")
        self.info.setPlainText(c["info"] if c else "")
        for w in (self.name, self.info):
            w.blockSignals(False)
        for w in (self.name, self.info, self.colors):
            w.setEnabled(c is not None)
        while self.grid.count():
            self.grid.takeAt(0).widget().deleteLater()
        for k, col in enumerate(c["colors"] if c else []):
            s = Swatch(col)
            s.clicked.connect(lambda _=False, col=col: QGuiApplication.clipboard().setText(col))
            s.setContextMenuPolicy(Qt.CustomContextMenu)
            s.customContextMenuRequested.connect(lambda pos, k=k, s=s: self._color_menu(k, s, pos))
            self.grid.addWidget(s, k // 10, k % 10)

    def _keep(self, refill=False):
        c = self.card()
        if c is None:
            return
        toolsdata.save_card(self.root_of(), c)
        if refill:
            self.fill(c["file"])

    def _new(self):
        name, ok = QInputDialog.getText(self, "新增色卡", "名稱", text="我的色卡")
        if ok and name.strip():
            path = toolsdata.save_card(self.root_of(), {"name": name.strip(), "info": "", "colors": []})
            self.fill(path)

    def _renamed(self):
        c = self.card()
        if c is not None and self.name.text().strip() and self.name.text().strip() != c["name"]:
            c["name"] = self.name.text().strip()
            self._keep(refill=True)

    def _info_changed(self):
        c = self.card()
        if c is not None:
            c["info"] = self.info.toPlainText()
            self.info_timer.start()

    def _add_color(self):
        c = self.card()
        if c is None:
            return
        col = pick_color(self, QColor(c["colors"][-1] if c["colors"] else "#ffffff"), "新增顏色", alpha=True)
        if col is not None:
            c["colors"].append(col.name(QColor.HexRgb) if col.alpha() == 255 else
                               col.name(QColor.HexRgb) + f"{col.alpha():02x}")
            self._keep(refill=True)

    def _color_menu(self, k, swatch, pos):
        c = self.card()
        menu = Menu(self)
        menu.addAction("複製 HEX", lambda: QGuiApplication.clipboard().setText(c["colors"][k]))

        def change():
            col = pick_color(self, qcolor(c["colors"][k]), "修改顏色", alpha=True, anchor=swatch)
            if col is not None:
                c["colors"][k] = col.name(QColor.HexRgb) + ("" if col.alpha() == 255 else f"{col.alpha():02x}")
                self._keep(refill=True)
        menu.addAction("修改…", change)
        menu.addAction("刪除", lambda: (c["colors"].pop(k), self._keep(refill=True)))
        menu.exec(swatch.mapToGlobal(pos))

    def _delete(self):
        c = self.card()
        if c is not None and QMessageBox.question(self, "刪除色卡", f"刪除色卡「{c['name']}」？") == QMessageBox.Yes:
            toolsdata.delete_card(c)
            self.fill()

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "匯入色卡", "", "色卡 (*.json);;All files (*)")
        if not path:
            return
        try:
            colors = toolsdata.import_colors(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "匯入色卡", str(exc))
            return
        name = os.path.splitext(os.path.basename(path))[0]
        self.fill(toolsdata.save_card(self.root_of(), {"name": name, "info": "", "colors": colors}))

    def _export(self):
        c = self.card()
        if c is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "匯出色卡", c["name"] + ".json", "色卡 (*.json)")
        if path:
            try:
                toolsdata.export_colors(c, path)
            except OSError as exc:
                QMessageBox.warning(self, "匯出色卡", str(exc))

