"""批量裁切圖片至單一解析度 (工具 menu): crop many pictures to one resolution.

Drop pictures (or folders) on the window. Each one starts as "cover" (scaled to fill the
target frame, centred). Pick a picture in the list (mouse wheel over the list steps through
them), drag it in the preview to move it, wheel over the preview to zoom (never below cover)."""
import os
from dataclasses import dataclass

from PIL import Image, ImageOps
from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QIcon, QImageIOHandler, QImageReader, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QSpinBox,
    QSplitter, QVBoxLayout, QWidget,
)

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
PRESETS = [("1920×1080 (1080p)", 1920, 1080), ("3840×2160 (4K)", 3840, 2160),
           ("1080×1920 (9:16)", 1080, 1920), ("1080×1080 (1:1)", 1080, 1080),
           ("1280×720 (720p)", 1280, 720)]
MAX_ZOOM = 8.0
PREVIEW_SIDE = 3000


@dataclass
class Item:
    path: str
    w: int
    h: int
    zoom: float = 1.0   # relative to cover, >= 1
    cx: float = 0.5     # point of the picture under the frame centre, 0..1
    cy: float = 0.5
    edited: bool = False


def crop_box(w, h, tw, th, zoom, cx, cy):
    """The region of a w×h picture the tw×th frame shows: (x0, y0, fw, fh, scale)."""
    s = max(tw / w, th / h) * max(zoom, 1.0)
    fw, fh = min(tw / s, w), min(th / s, h)
    x0 = min(max(cx * w - fw / 2, 0.0), w - fw)
    y0 = min(max(cy * h - fh / 2, 0.0), h - fh)
    return x0, y0, fw, fh, s


def crop_file(src, dst, tw, th, zoom, cx, cy, keep_meta):
    """Write src cropped to tw×th at dst (same format as src). dst may equal src."""
    with Image.open(src) as im:
        fmt = im.format
        im.load()
        im = ImageOps.exif_transpose(im)
    w, h = im.size
    x0, y0, fw, fh, _ = crop_box(w, h, tw, th, zoom, cx, cy)
    if im.mode == "P":
        im = im.convert("RGBA" if "transparency" in im.info else "RGB")
    elif im.mode not in ("RGB", "RGBA", "L", "LA", "1", "I;16", "CMYK"):
        im = im.convert("RGBA" if "A" in im.mode else "RGB")
    out = im.resize((tw, th), Image.LANCZOS, box=(x0, y0, x0 + fw, y0 + fh))
    kw = {}
    if keep_meta:
        for k in ("exif", "icc_profile"):
            if im.info.get(k):
                kw[k] = im.info[k]
    if fmt == "JPEG":
        kw.update(quality=95, optimize=True)
        if out.mode not in ("RGB", "L", "CMYK"):
            out = out.convert("RGB")
    elif fmt == "WEBP":
        kw.update(quality=95)
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    base, ext = os.path.splitext(dst)
    tmp = base + ".kctmp" + ext
    try:
        out.save(tmp, format=fmt, **kw)
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def collect(paths):
    """Picture files in paths (folders are walked), natural order, no duplicates."""
    found = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs.sort()
                found += [os.path.join(root, f) for f in sorted(files)]
        else:
            found.append(p)
    seen, out = set(), []
    for f in found:
        f = os.path.abspath(f)
        if f not in seen and os.path.splitext(f)[1].lower() in EXTS and os.path.isfile(f):
            seen.add(f)
            out.append(f)
    return out


def dest_path(src, root, outdir):
    return os.path.join(outdir, os.path.relpath(src, root))


class Preview(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.item = None
        self.img = None
        self.tw, self.th = 1920, 1080
        self._drag = None
        self.setMinimumSize(320, 240)
        self.setCursor(Qt.OpenHandCursor)

    def set_target(self, tw, th):
        self.tw, self.th = tw, th
        self.update()

    def show_item(self, item, img):
        self.item, self.img = item, img
        self.update()

    def _frame(self):
        m = 24
        aw, ah = max(self.width() - 2 * m, 10), max(self.height() - 2 * m, 10)
        k = min(aw / self.tw, ah / self.th)
        fw, fh = self.tw * k, self.th * k
        return QRectF((self.width() - fw) / 2, (self.height() - fh) / 2, fw, fh)

    def _box(self):
        it = self.item
        return crop_box(it.w, it.h, self.tw, self.th, it.zoom, it.cx, it.cy)

    def _store(self, x0, y0, fw, fh, zoom):
        it = self.item
        it.zoom = min(max(zoom, 1.0), MAX_ZOOM)
        x0 = min(max(x0, 0.0), it.w - fw)
        y0 = min(max(y0, 0.0), it.h - fh)
        it.cx, it.cy = (x0 + fw / 2) / it.w, (y0 + fh / 2) / it.h
        it.edited = True
        self.update()
        self.changed.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(24, 24, 28))
        fr = self._frame()
        if self.item is None or self.img is None:
            p.setPen(QColor(140, 140, 150))
            p.drawText(self.rect(), Qt.AlignCenter, "把圖片或資料夾拖進來")
            return
        x0, y0, fw, fh, _s = self._box()
        d = fr.width() / fw
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        target = QRectF(0, 0, self.item.w, self.item.h)

        def draw():
            p.save()
            p.translate(fr.x() - x0 * d, fr.y() - y0 * d)
            p.scale(d, d)
            p.drawImage(target, self.img)
            p.restore()

        p.setOpacity(0.28)
        draw()
        p.setOpacity(1.0)
        p.save()
        p.setClipRect(fr)
        draw()
        p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 200), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(fr)

    def mousePressEvent(self, e):
        if self.item and e.button() == Qt.LeftButton:
            self._drag = e.position()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._drag is None or not self.item:
            return
        x0, y0, fw, fh, _s = self._box()
        d = self._frame().width() / fw
        delta = e.position() - self._drag
        self._drag = e.position()
        self._store(x0 - delta.x() / d, y0 - delta.y() / d, fw, fh, self.item.zoom)

    def mouseReleaseEvent(self, _):
        self._drag = None
        self.setCursor(Qt.OpenHandCursor)

    def wheelEvent(self, e):
        if not self.item:
            return
        steps = e.angleDelta().y() / 120.0
        if not steps:
            return
        fr = self._frame()
        x0, y0, fw, fh, s = self._box()
        pos = e.position()
        px = x0 + (pos.x() - fr.x()) / (fr.width() / fw)   # picture point under the cursor
        py = y0 + (pos.y() - fr.y()) / (fr.width() / fw)
        zoom = min(max(self.item.zoom * 1.1 ** steps, 1.0), MAX_ZOOM)
        s2 = s / self.item.zoom * zoom
        nfw, nfh = min(self.tw / s2, self.item.w), min(self.th / s2, self.item.h)
        u, v = (pos.x() - fr.x()) / fr.width(), (pos.y() - fr.y()) / fr.height()
        self._store(px - u * nfw, py - v * nfh, nfw, nfh, zoom)


class Worker(QThread):
    progress = Signal(int, str)
    finished_all = Signal(list)

    def __init__(self, jobs):
        super().__init__()
        self.jobs = jobs

    def run(self):
        fails = []
        for i, (src, dst, args) in enumerate(self.jobs):
            try:
                crop_file(src, dst, *args)
            except Exception as ex:  # report and carry on with the rest
                fails.append(f"{os.path.basename(src)}: {ex}")
            self.progress.emit(i + 1, os.path.basename(src))
        self.finished_all.emit(fails)


class BatchCropTool(QWidget):
    def __init__(self, root_of=None):
        super().__init__(None, Qt.Window)
        self.setWindowTitle("批量裁切圖片至單一解析度")
        self.resize(1180, 720)
        self.setAcceptDrops(True)
        self.items = []
        self.worker = None
        self.root_of = root_of
        self._wheel = 0

        self.list = QListWidget()
        self.list.setIconSize(QSize(72, 48))
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setUniformItemSizes(True)
        self.list.viewport().installEventFilter(self)
        self.list.currentRowChanged.connect(self._select)
        self.list.setMinimumWidth(240)
        add_f = QPushButton("加入檔案…")
        add_d = QPushButton("加入資料夾…")
        rm = QPushButton("移除所選")
        clr = QPushButton("清空")
        add_f.clicked.connect(self._pick_files)
        add_d.clicked.connect(self._pick_folder)
        rm.clicked.connect(self._remove)
        clr.clicked.connect(self._clear)
        row1, row2 = QHBoxLayout(), QHBoxLayout()
        row1.addWidget(add_f)
        row1.addWidget(add_d)
        row2.addWidget(rm)
        row2.addWidget(clr)
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(self.list, 1)
        left.addLayout(row1)
        left.addLayout(row2)
        lw = QWidget()
        lw.setLayout(left)

        self.info = QLabel("")
        self.preview = Preview()
        self.preview.changed.connect(self._edited)
        reset = QPushButton("重置此張（滿版置中）")
        reset_all = QPushButton("全部重置")
        reset.clicked.connect(self._reset_one)
        reset_all.clicked.connect(self._reset_all)
        rrow = QHBoxLayout()
        rrow.addWidget(self.info, 1)
        rrow.addWidget(reset)
        rrow.addWidget(reset_all)
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.addLayout(rrow)
        right.addWidget(self.preview, 1)
        rw = QWidget()
        rw.setLayout(right)

        split = QSplitter()
        split.addWidget(lw)
        split.addWidget(rw)
        split.setStretchFactor(1, 1)
        split.setSizes([300, 880])

        self.preset = QComboBox()
        for name, _, _ in PRESETS:
            self.preset.addItem(name)
        self.preset.addItem("自訂")
        self.wbox, self.hbox = QSpinBox(), QSpinBox()
        for b, v in ((self.wbox, 1920), (self.hbox, 1080)):
            b.setRange(1, 16384)
            b.setValue(v)
            b.valueChanged.connect(self._size_changed)
        self.preset.currentIndexChanged.connect(self._preset)
        self.mode = QComboBox()
        self.mode.addItems(["輸出到其他資料夾（保留資料夾結構）", "覆蓋原檔"])
        self.mode.currentIndexChanged.connect(self._mode)
        self.outdir = QLineEdit()
        self.outdir.setPlaceholderText("輸出資料夾")
        self.browse = QPushButton("選擇…")
        self.browse.clicked.connect(self._pick_out)
        self.meta = QCheckBox("保留圖片 metadata（EXIF／色彩描述檔）")
        self.meta.setChecked(True)
        self.go = QPushButton("開始處理")
        self.go.clicked.connect(self._start)
        self.bar = QProgressBar()
        self.bar.setVisible(False)

        s1, s2 = QHBoxLayout(), QHBoxLayout()
        s1.addWidget(QLabel("解析度"))
        s1.addWidget(self.preset)
        s1.addWidget(self.wbox)
        s1.addWidget(QLabel("×"))
        s1.addWidget(self.hbox)
        s1.addSpacing(16)
        s1.addWidget(self.meta)
        s1.addStretch(1)
        s2.addWidget(QLabel("輸出"))
        s2.addWidget(self.mode)
        s2.addWidget(self.outdir, 1)
        s2.addWidget(self.browse)
        s2.addWidget(self.go)
        root = QVBoxLayout(self)
        root.addWidget(split, 1)
        root.addLayout(s1)
        root.addLayout(s2)
        root.addWidget(self.bar)
        self._size_changed()

    def fill(self):
        pass                                      # (nothing is kept between openings)

    # ---- adding / removing
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self._add(collect([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]))

    def _pick_files(self):
        fs, _ = QFileDialog.getOpenFileNames(
            self, "加入圖片", "", "圖片 (" + " ".join("*" + x for x in sorted(EXTS)) + ")")
        self._add(collect(fs))

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "加入資料夾")
        if d:
            self._add(collect([d]))

    def _add(self, paths):
        have = {it.path for it in self.items}
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            first = len(self.items)
            for n, p in enumerate(paths):
                if p in have:
                    continue
                r = QImageReader(p)
                r.setAutoTransform(True)
                sz = r.size()
                if not sz.isValid():
                    continue
                turned = bool(r.transformation() & QImageIOHandler.Transformation.TransformationRotate90)
                if turned:
                    sz.transpose()
                small = sz.scaled(144, 96, Qt.KeepAspectRatio)
                r.setScaledSize(small.transposed() if turned else small)
                th = r.read()
                it = Item(p, sz.width(), sz.height())
                self.items.append(it)
                li = QListWidgetItem(QIcon(QPixmap.fromImage(th)), "")
                self.list.addItem(li)
                self._label(len(self.items) - 1)
                if n % 25 == 0:
                    QApplication.processEvents()
        finally:
            QApplication.restoreOverrideCursor()
        if self.list.currentRow() < 0 and self.items:
            self.list.setCurrentRow(first)

    def _remove(self):
        for r in sorted((self.list.row(i) for i in self.list.selectedItems()), reverse=True):
            self.list.takeItem(r)
            del self.items[r]
        if not self.items:
            self.preview.show_item(None, None)
            self.info.setText("")

    def _clear(self):
        self.list.clear()
        self.items.clear()
        self.preview.show_item(None, None)
        self.info.setText("")

    def _label(self, row):
        it = self.items[row]
        self.list.item(row).setText(
            f"{'✎ ' if it.edited else ''}{os.path.basename(it.path)}\n{it.w}×{it.h}")

    # ---- browsing
    def eventFilter(self, obj, ev):
        if obj is self.list.viewport() and ev.type() == QEvent.Wheel:
            self._wheel += ev.angleDelta().y()
            steps = int(self._wheel / 120)
            if steps:
                self._wheel -= steps * 120
                row = min(max(self.list.currentRow() - steps, 0), self.list.count() - 1)
                self.list.setCurrentRow(row)
            return True
        return super().eventFilter(obj, ev)

    def _select(self, row):
        if row < 0 or row >= len(self.items):
            return
        it = self.items[row]
        r = QImageReader(it.path)
        r.setAutoTransform(True)
        sz = QSize(it.w, it.h)
        if max(it.w, it.h) > PREVIEW_SIDE:
            r.setScaledSize(sz.scaled(PREVIEW_SIDE, PREVIEW_SIDE, Qt.KeepAspectRatio))
        self.preview.show_item(it, r.read())
        self._info()

    def _info(self):
        it = self.preview.item
        if not it:
            return
        s = crop_box(it.w, it.h, self.wbox.value(), self.hbox.value(),
                     it.zoom, it.cx, it.cy)[4]
        self.info.setText(f"{os.path.basename(it.path)}　原圖 {it.w}×{it.h}　縮放 {s * 100:.0f}%"
                          + ("　（放大）" if s > 1 else ""))

    def _edited(self):
        self._label(self.items.index(self.preview.item))
        self._info()

    def _reset_one(self):
        it = self.preview.item
        if it:
            it.zoom, it.cx, it.cy, it.edited = 1.0, 0.5, 0.5, False
            self._label(self.items.index(it))
            self.preview.update()
            self._info()

    def _reset_all(self):
        for i, it in enumerate(self.items):
            it.zoom, it.cx, it.cy, it.edited = 1.0, 0.5, 0.5, False
            self._label(i)
        self.preview.update()
        self._info()

    # ---- settings
    def _preset(self, i):
        if i < len(PRESETS):
            self.wbox.blockSignals(True)
            self.hbox.blockSignals(True)
            self.wbox.setValue(PRESETS[i][1])
            self.hbox.setValue(PRESETS[i][2])
            self.wbox.blockSignals(False)
            self.hbox.blockSignals(False)
            self._size_changed()

    def _size_changed(self):
        w, h = self.wbox.value(), self.hbox.value()
        match = next((i for i, (_, pw, ph) in enumerate(PRESETS) if (pw, ph) == (w, h)),
                     len(PRESETS))
        self.preset.blockSignals(True)
        self.preset.setCurrentIndex(match)
        self.preset.blockSignals(False)
        self.preview.set_target(w, h)
        self._info()

    def _mode(self, i):
        self.outdir.setEnabled(i == 0)
        self.browse.setEnabled(i == 0)

    def _pick_out(self):
        d = QFileDialog.getExistingDirectory(self, "輸出資料夾", self.outdir.text())
        if d:
            self.outdir.setText(d)

    # ---- export
    def _start(self):
        if not self.items:
            return
        overwrite = self.mode.currentIndex() == 1
        out = self.outdir.text().strip()
        if not overwrite and not out:
            QMessageBox.warning(self, "批量裁切", "請先選擇輸出資料夾。")
            return
        if overwrite and QMessageBox.question(
                self, "覆蓋原檔", f"將直接覆蓋 {len(self.items)} 個原檔，無法復原。繼續？"
        ) != QMessageBox.Yes:
            return
        root = os.path.commonpath([os.path.dirname(it.path) for it in self.items])
        w, h, keep = self.wbox.value(), self.hbox.value(), self.meta.isChecked()
        jobs = [(it.path, it.path if overwrite else dest_path(it.path, root, out),
                 (w, h, it.zoom, it.cx, it.cy, keep)) for it in self.items]
        self.bar.setRange(0, len(jobs))
        self.bar.setValue(0)
        self.bar.setVisible(True)
        self.go.setEnabled(False)
        self.worker = Worker(jobs)
        self.worker.progress.connect(lambda n, name: (self.bar.setValue(n),
                                                      self.bar.setFormat(f"%v / %m　{name}")))
        self.worker.finished_all.connect(self._done)
        self.worker.start()

    def _done(self, fails):
        self.go.setEnabled(True)
        self.bar.setVisible(False)
        if fails:
            QMessageBox.warning(self, "批量裁切", f"{len(fails)} 個失敗：\n" + "\n".join(fails[:20]))
        else:
            QMessageBox.information(self, "批量裁切", "完成。")

