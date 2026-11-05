"""Colour picking with a live preview: while the picker is open, every colour the user tries
goes to `live` at once (the preview, the timeline, the thumbnails show it); Enter or a click
elsewhere keeps it, Esc calls `cancel` so what was there before shows again.

The picker is a small popup right under what is being coloured (inplace.py: the swatch button,
the clip, the track), not a window in the middle of the screen: a row of colours, the last ones
picked, a saturation / brightness square with a hue strip, alpha when it has one, and the hex.
滴管 (the eyedropper) takes a colour from anywhere in the program's window - the preview, a
thumbnail, the timeline: the colour under the pointer shows as it moves, a click keeps it, Esc
goes back to what it was."""
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

from . import inplace

PRESETS = ["#e05252", "#e8893a", "#e8c547", "#6cc24a", "#3fb8a6", "#4a90e2", "#8b6be0", "#d461b4",
           "#ffffff", "#c0c0c4", "#888888", "#55555a", "#2b2b2f", "#000000", "#8a5a3c", "#3c6e8a"]
recent = []                     # the colours picked lately, newest first
cards = lambda: []              # () -> [{name, colors}]: the 調色盤's colour cards (set by the window)


def _checker(p, r, n=5):
    p.fillRect(r, QColor("#cfcfcf"))
    for yy in range(int(r.top()), int(r.bottom()) + 1, n):
        for xx in range(int(r.left()) + ((yy - int(r.top())) // n % 2) * n, int(r.right()) + 1, 2 * n):
            p.fillRect(QRectF(xx, yy, n, n).intersected(r), QColor("#9a9a9a"))


class _Swatch(QWidget):
    picked = Signal(QColor)

    def __init__(self, col=None):
        super().__init__()
        self.col = col
        self.setFixedSize(22, 18)
        self.setCursor(Qt.PointingHandCursor)

    def set(self, col):
        self.col = col
        self.setToolTip(hex_of(col) if col is not None else "")
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.col is None:
            p.setPen(QPen(QColor("#3a3a40"), 1, Qt.DotLine))
            p.drawRect(r)
            return
        if self.col.alpha() < 255:
            _checker(p, r)
        p.fillRect(r, self.col)
        p.setPen(QPen(QColor("#ffffff") if self.underMouse() else QColor(0, 0, 0, 120), 1))
        p.drawRect(r)

    def enterEvent(self, _e):
        self.update()

    def leaveEvent(self, _e):
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.col is not None:
            self.picked.emit(QColor(self.col))


class _Field(QWidget):
    """The saturation / brightness square (kind 'sv'), the hue strip ('h'), or alpha ('a')."""
    moved = Signal()

    def __init__(self, pop, kind, size):
        super().__init__()
        self.pop, self.kind = pop, kind
        self.setFixedSize(size)
        self.setCursor(Qt.CrossCursor)
        self._img, self._img_h = None, None

    def paintEvent(self, _e):
        p = QPainter(self)
        r = QRectF(self.rect())
        pop = self.pop
        if self.kind == "sv":
            if self._img is None or self._img_h != pop.h:
                self._img = QImage(self.size(), QImage.Format_RGB32)
                q = QPainter(self._img)
                q.fillRect(self._img.rect(), QColor.fromHsvF(pop.h, 1, 1))
                g = QLinearGradient(0, 0, self.width(), 0)
                g.setColorAt(0, QColor(255, 255, 255, 255))
                g.setColorAt(1, QColor(255, 255, 255, 0))
                q.fillRect(self._img.rect(), g)
                g = QLinearGradient(0, 0, 0, self.height())
                g.setColorAt(0, QColor(0, 0, 0, 0))
                g.setColorAt(1, QColor(0, 0, 0, 255))
                q.fillRect(self._img.rect(), g)
                q.end()
                self._img_h = pop.h
            p.drawImage(0, 0, self._img)
            c = QPointF(pop.s * (self.width() - 1), (1 - pop.v) * (self.height() - 1))
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(QPen(QColor("#000000"), 3))
            p.drawEllipse(c, 5, 5)
            p.setPen(QPen(QColor("#ffffff"), 1.5))
            p.drawEllipse(c, 5, 5)
            return
        if self.kind == "h":
            g = QLinearGradient(0, 0, 0, self.height())
            for k in range(7):
                g.setColorAt(k / 6, QColor.fromHsvF(min(k / 6, 0.9999), 1, 1))
            p.fillRect(r, g)
            y = pop.h * (self.height() - 1)
            mark = QRectF(0.5, y - 2, self.width() - 1, 4)
        else:
            _checker(p, r)
            g = QLinearGradient(0, 0, self.width(), 0)
            col = pop.color()
            g.setColorAt(0, QColor(col.red(), col.green(), col.blue(), 0))
            g.setColorAt(1, QColor(col.red(), col.green(), col.blue(), 255))
            p.fillRect(r, g)
            x = pop.a * (self.width() - 1)
            mark = QRectF(x - 2, 0.5, 4, self.height() - 1)
        p.setPen(QPen(QColor("#000000"), 1))
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawRect(mark)

    def _at(self, e):
        pos = e.position()
        fx = min(max(pos.x() / max(1, self.width() - 1), 0.0), 1.0)
        fy = min(max(pos.y() / max(1, self.height() - 1), 0.0), 1.0)
        pop = self.pop
        if self.kind == "sv":
            pop.s, pop.v = fx, 1 - fy
        elif self.kind == "h":
            pop.h = min(fy, 0.9999)
        else:
            pop.a = fx
        self.moved.emit()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._at(e)

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._at(e)


class ColorPopup(inplace.Overlay):
    """The picker; run() -> kept (bool), color() the colour shown."""
    changed = Signal(QColor)

    def __init__(self, widget, initial, title, alpha=True):
        super().__init__(widget)
        self.setObjectName("colorpop")
        self.setStyleSheet("QFrame#colorpop { background: #1a1a1a; border: 1px solid #4d4d4d; border-radius: 0; }"
                           "QLabel { color: #8e8e94; }")
        self.alpha, self.initial = alpha, QColor(initial)
        if not alpha:
            self.initial.setAlpha(255)
        self.h = self.s = self.v = 0.0
        self.a = 1.0
        self.touched = False                             # (closed untouched: nothing picked)
        self._take(self.initial)
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 6, 8, 8)
        box.setSpacing(6)
        top = QHBoxLayout()
        top.addWidget(QLabel(title))
        top.addStretch(1)
        self.dropper = QPushButton("滴管")
        self.dropper.setCheckable(True)
        self.dropper.setFocusPolicy(Qt.NoFocus)
        self.dropper.setToolTip("從視窗裡任何地方取色（預覽、縮圖、時間軸…）：移動看顏色，按一下取用，Esc 取消")
        self.dropper.setStyleSheet("QPushButton { padding: 0 6px; }")
        self.dropper.toggled.connect(self._sample)
        top.addWidget(self.dropper)
        box.addLayout(top)
        self.shot = None                                 # the window as it looked when 滴管 began
        self.before = None                               # the colour then (Esc goes back to it)
        self.follow = QTimer(self, interval=30)          # (most widgets get no mouse moves without a button)
        self.follow.timeout.connect(lambda: self._hover(QCursor.pos()))
        grid = QGridLayout()
        grid.setSpacing(3)
        for k, h in enumerate(PRESETS):
            sw = _Swatch()
            sw.set(QColor(h))
            sw.picked.connect(self._pick)
            grid.addWidget(sw, k // 8, k % 8)
        self.recent = []
        for k in range(8):
            sw = _Swatch()
            sw.set(recent[k] if k < len(recent) else None)
            sw.picked.connect(self._pick)
            self.recent.append(sw)
            grid.addWidget(sw, 2, k)
        box.addLayout(grid)
        try:
            mine = [c for c in cards() if c.get("colors")]
        except Exception:                                # (a card folder that cannot be read: none)
            mine = []
        if mine:                                         # 調色盤: a card's colours, the card picked above them
            pick = QComboBox()
            for c in mine:
                pick.addItem(c["name"], c["colors"])
            box.addWidget(pick)
            cg = QGridLayout()
            cg.setSpacing(3)
            box.addLayout(cg)

            def show_card(_i=0):
                while cg.count():
                    cg.takeAt(0).widget().deleteLater()
                for k, h in enumerate((pick.currentData() or [])[:32]):
                    sw = _Swatch()
                    sw.set(qcolor(h))
                    sw.picked.connect(self._pick)
                    cg.addWidget(sw, k // 8, k % 8)
            pick.currentIndexChanged.connect(show_card)
            show_card()
        row = QHBoxLayout()
        row.setSpacing(6)
        self.sv = _Field(self, "sv", QSize(176, 120))
        self.hue = _Field(self, "h", QSize(16, 120))
        row.addWidget(self.sv)
        row.addWidget(self.hue)
        box.addLayout(row)
        self.al = None
        if alpha:
            self.al = _Field(self, "a", QSize(198, 12))
            box.addWidget(self.al)
        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        self.was = _Swatch()
        self.was.set(self.initial)
        self.was.setToolTip("原本的顏色（按一下改回）")
        self.was.picked.connect(self._pick)
        self.now = _Swatch()
        self.now.setCursor(Qt.ArrowCursor)
        self.hex = QLineEdit()
        self.hex.setFixedWidth(96)
        self.hex.editingFinished.connect(self._typed)
        self.hex.textEdited.connect(lambda _t: setattr(self, "typing", True))
        self.typing = False                              # (what is typed there is not overwritten)
        bottom.addWidget(self.was)
        bottom.addWidget(self.now)
        bottom.addWidget(self.hex)
        bottom.addStretch(1)
        box.addLayout(bottom)
        for f in (self.sv, self.hue, self.al):
            if f is not None:
                f.moved.connect(self._show)
        self._show(emit=False)

    def _take(self, col):
        h, s, v, a = col.getHsvF()
        if h >= 0:                                       # (a grey keeps the hue it had)
            self.h = min(h, 0.9999)
        self.s, self.v = s, v
        self.a = a if self.alpha else 1.0

    def color(self):
        return QColor.fromHsvF(self.h, self.s, self.v, self.a)

    def _pick(self, col):
        self._take(col)
        self._show()

    def _typed(self):
        if not self.typing:
            return
        self.typing = False
        t = self.hex.text().strip()
        col = qcolor(t if t.startswith("#") or not t else "#" + t, None)    # (ff0000 too)
        if col.isValid():
            self._pick(col)

    def _show(self, emit=True):
        col = self.color()
        self.now.set(col)
        if not self.typing:
            self.hex.setText(hex_of(col))
            self.hex.selectAll()
        for f in (self.sv, self.hue, self.al):
            if f is not None:
                f.update()
        if emit:
            self.touched = True
            self.changed.emit(col)

    # -- 滴管 ---------------------------------------------------------------------------------------
    def _sample(self, on):
        if not on:
            if self.shot is not None:
                QApplication.restoreOverrideCursor()
            self.shot = None
            self.follow.stop()
            return
        win = self.parentWidget()
        self.hide()                                      # (the window without the picker over it)
        QApplication.processEvents()
        self.shot = win.grab().toImage()
        self.show()
        self.raise_()
        self.before = self.color()
        self.last = None
        QApplication.setOverrideCursor(Qt.CrossCursor)
        self.follow.start()

    def _hover(self, gp):
        """The colour under the pointer shown while 滴管 is on (not over the picker itself)."""
        if self.shot is None or gp == self.last or QRect(self.mapToGlobal(QPoint(0, 0)), self.size()).contains(gp):
            return
        self.last = gp
        col = self._sampled(gp)
        if col is not None:
            a = self.a
            self._take(col)
            self.a = a                                   # (the eyedropper takes the colour, not the alpha)
            self._show()

    def _sampled(self, gp):
        """The colour of the window at global point gp (None outside it)."""
        win = self.parentWidget()
        p = win.mapFromGlobal(gp)
        k = self.shot.devicePixelRatio()
        x, y = int(p.x() * k), int(p.y() * k)
        if not (0 <= x < self.shot.width() and 0 <= y < self.shot.height()):
            return None
        col = self.shot.pixelColor(x, y)
        col.setAlpha(255)
        return col

    def eventFilter(self, obj, e):
        if self.shot is None or self._done:
            return super().eventFilter(obj, e)
        t = e.type()
        if t in (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
            gp = e.globalPosition().toPoint()
            if QRect(self.mapToGlobal(QPoint(0, 0)), self.size()).contains(gp):
                return super().eventFilter(obj, e) if t != QEvent.MouseMove else False
            if t != QEvent.MouseButtonRelease:
                self.last = None
                self._hover(gp)
            if t == QEvent.MouseButtonPress:
                self.dropper.setChecked(False)           # kept: the picker stays open
            return True                                  # (nothing under it is clicked)
        if t == QEvent.KeyPress and e.key() == Qt.Key_Escape:
            self._pick(self.before)
            self.dropper.setChecked(False)
            return True
        return super().eventFilter(obj, e)

    def about_to_finish(self, ok):
        if self.shot is not None:
            self.dropper.setChecked(False)
        if ok:
            self._typed()                                # (Enter in the hex field)
        self.hex.blockSignals(True)                      # (nothing more once it closes)

    def place(self, widget, rect):
        """Under rect of widget (above when there is no room), at the pointer along a wide one."""
        self.adjustSize()
        win = self.parentWidget()
        r = inplace.window_rect(widget, rect.intersected(widget.rect()) if widget.rect().intersects(rect) else rect)
        w, h = self.width(), self.height()
        x = r.left()
        if r.width() > w:
            px = win.mapFromGlobal(QCursor.pos()).x()
            if r.left() <= px <= r.right():
                x = min(max(px - 24, r.left()), r.right() - w)
        y = r.bottom() + 4
        if y + h > win.height():
            y = r.top() - 4 - h if r.top() - 4 - h >= 0 else win.height() - h
        self.setGeometry(QRect(max(0, min(x, win.width() - w)), max(0, y), w, h))


def pick_color(parent, initial, title, alpha=True, live=None, cancel=None, anchor=None):
    """The colour picked (a QColor), or None when it was left with Esc or closed untouched.
    Opens at `anchor` (inplace.anchor_of: a hint, else this, else the button under the pointer)."""
    widget, rect = inplace.anchor_of(anchor)
    if widget is None:
        widget, rect = parent, parent.rect()
    pop = ColorPopup(widget, QColor(initial) if initial is not None else QColor("white"), title, alpha)
    pop.place(widget, rect)
    if live is not None:
        pop.changed.connect(live)
    ok = pop.run(pop.hex)
    col = pop.color() if ok and pop.touched else None
    if col is not None:
        name = hex_of(col)
        recent[:] = [col] + [c for c in recent if hex_of(c) != name][:7]
    elif cancel is not None:
        cancel()
    return col


def qcolor(text, default="white"):
    """A QColor of #rrggbb or #rrggbbaa (Qt itself reads 8 digits as #aarrggbb); default
    when it is no colour (None: an invalid QColor)."""
    t = (text or "").strip()
    if len(t) == 9 and t.startswith("#"):
        col = QColor(t[:7])
        try:
            col.setAlpha(int(t[7:], 16))
        except ValueError:
            pass
        return col
    col = QColor(t)
    return col if col.isValid() else QColor(default) if default is not None else QColor()


def rgba(col):
    """[r, g, b, a] (0 - 1) of a QColor."""
    return [col.redF(), col.greenF(), col.blueF(), col.alphaF()]


def hex_of(col):
    """#rrggbb, or #rrggbbaa when not opaque."""
    return col.name() + (f"{col.alpha():02x}" if col.alpha() < 255 else "")
