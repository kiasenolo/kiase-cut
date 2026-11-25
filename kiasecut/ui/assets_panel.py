"""The 內建素材 tab: solid colours, gradients and basic shapes (see assets.py), the text presets (textpresets.py; ident "text:<key>") and the four Audio
Visualizers (viz.py; their ident is "viz:<kind>").

Drag one onto the timeline (hold Alt over a picture clip to replace its source), or
double-click to add it at the playhead. The two colours at the top paint the shapes and the
自訂 solid / gradients; presets keep their own colours. Once placed, everything about it
(size, colours, corners, outline…) is set in the inspector's 素材參數."""
import queue
import time

from PySide6.QtCore import QByteArray, QMimeData, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .. import assets, camera, fx, mesh, textlayout, textpresets, viz
from .colorpick import hex_of, pick_color, qcolor
from .timeline import MEDIA_MIME
from .menukeys import Menu
from .viewmode import list_toggle

ROLE_KEY = Qt.UserRole + 1
THUMB = (72, 40)


def thumbnail(a, c1, c2):
    """A small picture of asset a on a checkerboard (so clear parts show)."""
    w, h = THUMB
    img = QImage(QSize(w, h), QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("#2a2a2e"))
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    for y in range(0, h, 6):
        for x in range(0, w, 6):
            if (x // 6 + y // 6) % 2:
                p.fillRect(x, y, 6, 6, QColor("#38383d"))
    r = QSvgRenderer(QByteArray(assets.svg(assets.at(assets.make(a, c1, c2, 160, 90), 0), True).encode("utf-8")))
    r.setAspectRatioMode(Qt.KeepAspectRatio)
    pad = 5 if a.cat in ("shape", "empty") else 0
    r.render(p, QRectF(pad, pad, w - 2 * pad, h - 2 * pad))
    p.end()
    return QPixmap.fromImage(img)


TEXT_CAT = ("text", "文字")                      # (looks of a text clip, see textpresets.py)


def text_thumbnail(key):
    """A small picture of a text preset: its looks on 文字 over a checkerboard."""
    from PIL.ImageQt import ImageQt
    w, h = THUMB
    img = QImage(QSize(w, h), QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("#2a2a2e"))
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    for y in range(0, h, 6):
        for x in range(0, w, 6):
            if (x // 6 + y // 6) % 2:
                p.fillRect(x, y, 6, 6, QColor("#38383d"))
    spec = {"content": "文字", "font_path": None, "size": 5.0, **(textpresets.fields(textpresets.ident(key)) or {})}
    spec.pop("font_path")
    pic = QImage(ImageQt(textlayout.render(spec, 0.45))).convertToFormat(QImage.Format_ARGB32_Premultiplied)
    pic = pic.scaled(w - 6, h - 6, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    p.drawImage((w - pic.width()) // 2, (h - pic.height()) // 2, pic)
    p.end()
    return QPixmap.fromImage(img)


SCENE_CAT = ("scene3d", "3D")                   # (a 3D 場景: a compound with a camera)
VIZ_CAT = ("viz", "Audio Visualizer")           # (after the presets: drawn from sound, not from colours)


def particle_thumbnail(key):
    """A small picture of a particle object on a dark ground."""
    import math
    import random
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPen, QRadialGradient
    w, h = THUMB
    img = QImage(QSize(w, h), QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("#202024"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    rnd = random.Random(key)

    def glow(x, y, r, c, a=0.9):
        g = QRadialGradient(QPointF(x, y), r)
        c0, c1 = QColor(c), QColor(c)
        c0.setAlphaF(a)
        c1.setAlphaF(0.0)
        g.setColorAt(0, c0)
        g.setColorAt(1, c1)
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(x, y), r, r)

    if key in ("sparks", "fireworks", "shells"):
        for i in range(34 if key == "sparks" else 28):
            a = rnd.random() * math.tau
            r0, r1 = 3 + rnd.random() * 6, 10 + rnd.random() * 20
            p.setPen(QPen(QColor.fromHsvF(0.09 + 0.05 * rnd.random(), 0.7, 1.0), 1.4, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(w / 2 + math.cos(a) * r0, h * 0.55 + math.sin(a) * r0 * 0.8),
                       QPointF(w / 2 + math.cos(a) * r1, h * 0.55 + math.sin(a) * r1 * 0.8 + r1 * 0.15))
    elif key == "confetti":
        p.setPen(Qt.NoPen)
        for i in range(26):
            p.setBrush(QColor.fromHsvF(rnd.random(), 0.65, 1.0))
            p.save()
            p.translate(4 + rnd.random() * (w - 8), 4 + rnd.random() * (h - 8))
            p.rotate(rnd.random() * 180)
            p.drawRect(QRectF(-3, -1.6, 6, 3.2))
            p.restore()
    elif key == "bokeh":
        for i in range(11):
            c = QColor.fromHsvF(0.05 + 0.12 * rnd.random(), 0.45, 1.0, 0.5)
            r = 4 + rnd.random() * 9
            c2 = QColor(c)
            c2.setAlphaF(0.85)
            p.setBrush(c)
            p.setPen(QPen(c2, 1))
            p.drawEllipse(QPointF(8 + rnd.random() * (w - 16), 8 + rnd.random() * (h - 16)), r, r)
    elif key == "snow":
        for i in range(30):
            glow(3 + rnd.random() * (w - 6), 3 + rnd.random() * (h - 6), 1.5 + rnd.random() * 2.5, "#ffffff")
    elif key == "fire":
        for i in range(16):
            t = i / 15
            glow(w / 2 + rnd.uniform(-5, 5) * (1 - t) , h - 6 - t * (h - 8), 9 * (1 - 0.7 * t), QColor.fromHsvF(0.02 + 0.1 * (1 - t), 0.9, 1.0), 0.55)
    elif key == "smoke":
        for i in range(8):
            t = i / 7
            glow(w / 2 + rnd.uniform(-6, 6) + t * 6, h - 5 - t * (h - 6), 5 + 11 * t, "#9a9a9a", 0.35)
    elif key == "magic":
        p.setPen(QPen(QColor("#cfe6ff"), 1, Qt.SolidLine, Qt.RoundCap))
        for i in range(16):
            x, y, r = 6 + rnd.random() * (w - 12), 5 + rnd.random() * (h - 10), 1.5 + rnd.random() * 3.5
            glow(x, y, r * 1.8, "#a8c8ff", 0.5)
            p.setPen(QPen(QColor("#ffffff"), 1, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(x - r, y), QPointF(x + r, y))
            p.drawLine(QPointF(x, y - r), QPointF(x, y + r))
    elif key == "bounce":
        p.setPen(QPen(QColor(255, 200, 120, 90), 1))
        p.setBrush(Qt.NoBrush)
        for i in range(3):
            x0 = 8 + i * 20
            p.drawArc(QRectF(x0, h * 0.25, 26, h * 1.0), 0, 180 * 16)
        p.setPen(Qt.NoPen)
        for i in range(14):
            glow(6 + rnd.random() * (w - 12), h - 4 - abs(math.sin(i * 1.3)) * 24 * rnd.random(), 2.6, "#ffd28a")
    else:                                                  # the whole system: a cloud of glowing dots
        for i in range(34):
            a, r = rnd.random() * math.tau, rnd.random() ** 0.6 * 24
            glow(w / 2 + math.cos(a) * r * 1.5, h / 2 + math.sin(a) * r * 0.7, 2 + rnd.random() * 3.5, QColor.fromHsvF(0.08 + 0.06 * rnd.random(), 0.6, 1.0))
    p.end()
    return QPixmap.fromImage(img)


def scene_thumbnail():
    """3D 場景: two planes in perspective on a dark ground."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPolygonF
    w, h = THUMB
    img = QImage(QSize(w, h), QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("#202024"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(80, 140, 230, 200))
    p.drawPolygon(QPolygonF([QPointF(8, 14), QPointF(40, 8), QPointF(40, 32), QPointF(8, 28)]))
    p.setBrush(QColor(240, 170, 70, 220))
    p.drawPolygon(QPolygonF([QPointF(34, 12), QPointF(64, 15), QPointF(64, 31), QPointF(34, 36)]))
    p.end()
    return img


def light_thumbnail(kind):
    """燈光: a sun with rays, a glowing point, or a dome of light, on a dark ground."""
    import math
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QPen
    w, h = THUMB
    img = QImage(QSize(w, h), QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("#202024"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    warm = QColor(255, 214, 90)
    mid = QPointF(w / 2, h / 2)
    p.setPen(QPen(warm, 2.5))
    if kind == "ambient":
        p.setBrush(QColor(255, 214, 90, 70))
        p.drawChord(QRectF(w / 2 - 18, h / 2 - 12, 36, 36), 0, 180 * 16)
    else:
        p.setBrush(warm)
        p.drawEllipse(mid, 7, 7)
        for i in range(8):
            a = i * math.pi / 4
            far = 18 if kind == "sun" or i % 2 == 0 else 13
            p.drawLine(mid + QPointF(math.cos(a) * 11, math.sin(a) * 11), mid + QPointF(math.cos(a) * far, math.sin(a) * far))
    p.end()
    return img


def solid_thumbnail(kind):
    """基礎物件: its mesh seen a little from above and the side, the faces darker the more they turn away, on a dark ground."""
    import numpy as np
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPolygonF
    w, h = THUMB
    img = QImage(QSize(w, h), QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("#202024"))
    _name, bw, bh, depth, bevel = mesh.PRIMITIVES[kind]
    data = mesh.primitive_mesh(kind, bw, bh, depth, bevel * 3, (1.0, 1.0, 1.0))
    turn = camera._rot(-24.0, 32.0, 0.0)
    points = (data[:, :3] @ turn.T).reshape(-1, 3, 3)
    normals = (data[:, 3:6] @ turn.T).reshape(-1, 3, 3).mean(axis=1)
    k = (h - 8) / max(np.ptp(points[..., 1]), np.ptp(points[..., 0]) * (h - 8) / (w - 8))
    middle = (points.reshape(-1, 3).max(axis=0) + points.reshape(-1, 3).min(axis=0)) / 2.0
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    toward = np.array([-0.4, -0.6, -0.7]) / np.linalg.norm([-0.4, -0.6, -0.7])
    for i in np.argsort(-points[..., 2].mean(axis=1)):                  # (far first)
        if normals[i][2] > 0.2:                                         # (turned away)
            continue
        light = 0.3 + 0.7 * max(float(normals[i] @ toward), 0.0)
        colour = QColor.fromRgbF(light * 0.92, light * 0.92, light * 0.96)
        p.setPen(colour)
        p.setBrush(colour)
        p.drawPolygon(QPolygonF([QPointF(w / 2 + (x - middle[0]) * k, h / 2 + (y - middle[1]) * k) for x, y, _z in points[i]]))
    p.end()
    return img


def model_thumbnail():
    """匯入模型: a box drawn in lines with a plus, on a dark ground."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPen
    w, h = THUMB
    img = QImage(QSize(w, h), QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("#202024"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(230, 230, 235), 1.6))
    x, y, s, d = w / 2 - 18, h / 2 - 8, 22, 9
    front = [QPointF(x, y), QPointF(x + s, y), QPointF(x + s, y + s), QPointF(x, y + s)]
    back = [q + QPointF(d, -d) for q in front]
    for a, b in zip(front, front[1:] + front[:1]):
        p.drawLine(a, b)
    for a, b in ((front[0], back[0]), (front[1], back[1]), (front[2], back[2]), (back[0], back[1]), (back[1], back[2])):
        p.drawLine(a, b)
    p.setPen(QPen(QColor(255, 214, 90), 2.5))
    mid = QPointF(w / 2 + 22, h / 2 + 8)
    p.drawLine(mid - QPointF(6, 0), mid + QPointF(6, 0))
    p.drawLine(mid - QPointF(0, 6), mid + QPointF(0, 6))
    p.end()
    return img


def camera_thumbnail():
    """相機: a camera body and its lens on a dark ground."""
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QPolygonF
    w, h = THUMB
    img = QImage(QSize(w, h), QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("#202024"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(230, 230, 235))
    p.drawRoundedRect(QRectF(12, 12, 34, 24), 4, 4)
    p.drawPolygon(QPolygonF([QPointF(46, 20), QPointF(60, 12), QPointF(60, 36), QPointF(46, 28)]))
    p.setBrush(QColor("#202024"))
    p.drawEllipse(QPointF(24, 24), 6, 6)
    p.end()
    return img


def viz_thumbnail(kind):
    """A small picture of an Audio Visualizer kind (viz.py) on a dark ground."""
    import math
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath, QPen
    w, h = THUMB
    img = QImage(QSize(w, h), QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("#202024"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    col = QColor.fromRgbF(*viz.make(kind, {"type": "track", "id": ""})["color"])
    p.setPen(Qt.NoPen)
    p.setBrush(col)
    if kind == "bars":
        for i in range(11):
            ln = 6 + 22 * abs(math.sin(i * 0.9 + 0.4)) * (1 - abs(i - 5) / 9)
            p.drawRoundedRect(QRectF(6 + i * 5.6, h - 5 - ln, 3.6, ln), 1.5, 1.5)
    elif kind == "wave":
        top, bottom = QPainterPath(), QPainterPath()
        pts = [(6 + i * (w - 12) / 24, 14 * abs(math.sin(i * 0.55)) * (0.4 + 0.6 * math.sin(i * 0.13 + 0.5) ** 2) + 1) for i in range(25)]
        path = QPainterPath(QPointF(pts[0][0], h / 2 - pts[0][1]))
        for x, a in pts[1:]:
            path.lineTo(x, h / 2 - a)
        for x, a in reversed(pts):
            path.lineTo(x, h / 2 + a)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "scope":
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(col, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        path = QPainterPath(QPointF(6, h / 2))
        for i in range(1, 61):
            x = 6 + i * (w - 12) / 60
            path.lineTo(x, h / 2 - 13 * math.sin(i * 0.33) * math.sin(i * 0.07 + 0.3))
        p.drawPath(path)
    elif kind == "oscilloscope":
        p.setBrush(QColor(4, 16, 9))
        p.drawRoundedRect(QRectF(2, 2, w - 4, h - 4), 4, 4)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 55), 1))
        for i in range(1, 6):
            p.drawLine(QPointF(2 + i * (w - 4) / 6, 6), QPointF(2 + i * (w - 4) / 6, h - 6))
        for j in range(1, 4):
            p.drawLine(QPointF(6, 2 + j * (h - 4) / 4), QPointF(w - 6, 2 + j * (h - 4) / 4))
        path = QPainterPath(QPointF(6, h / 2))
        for i in range(1, 61):
            path.lineTo(6 + i * (w - 12) / 60, h / 2 - 11 * math.sin(i * 0.42))
        p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 80), 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)
        p.setPen(QPen(col, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)
    else:
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 70), 1))
        p.drawEllipse(QPointF(w / 2, h / 2), 15, 15)
        p.drawLine(QPointF(w / 2, 3), QPointF(w / 2, h - 3))
        p.setPen(QPen(col, 2, Qt.SolidLine, Qt.RoundCap))
        for i in range(60):
            m = (i / 60 - 0.5) * 2
            p.drawPoint(QPointF(w / 2 + 4 * math.sin(i * 2.7) * (1 - abs(m)), h / 2 + m * 13))
    p.end()
    return QPixmap.fromImage(img)


THUMB_SCALE = 2                                  # (the particle thumbnails are drawn this much larger than they show)
THUMB_LOOP = 6.0                                 # s: the hover animation plays this long, then again
STILL_T = 1.0                                    # s: the moment a still thumbnail shows


class ParticleThumbs(QThread):
    """Draws the particle objects' thumbnails with the real particle system, on a thread of its own (it has its own GL context):
    ask(key, t) wants the picture of preset `key` at time t; only the latest ask of each preset is drawn; frame(key, image) is the answer.
    Nothing is drawn where there is no OpenGL: the thumbnails keep their painted pictures."""
    frame = Signal(str, QImage)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.jobs = queue.Queue()
        self.latest = {}
        self.stopping = False

    def ask(self, key, t):
        self.latest[key] = t
        self.jobs.put(key)
        if not self.isRunning():
            self.start()

    def stop(self):
        self.stopping = True
        self.jobs.put(None)
        self.wait(3000)

    def run(self):
        import numpy as np
        try:
            eng = fx.Engine()
        except Exception:
            return
        w, h = THUMB[0] * THUMB_SCALE, THUMB[1] * THUMB_SCALE
        yy = np.linspace(0.0, 1.0, h, dtype="f4")[:, None, None]
        bg = np.empty((h, w, 4), np.uint8)
        bg[..., :3] = (np.array([24, 24, 32], "f4") * (1 - yy) + np.array([14, 14, 20], "f4") * yy).astype(np.uint8)
        bg[..., 3] = 255
        while not self.stopping:
            key = self.jobs.get()
            if key is None:
                break
            t = self.latest.pop(key, None)
            if t is None:                                  # (a newer ask of it has been drawn already)
                continue
            try:
                a = assets.get("particle." + key)
                e = assets.particle_effect(assets.make(a, "#ffffff", "#000000", w, h))
                d = fx.get(e["filter"])
                e["params"]["count"] = assets.particle_thumb_count(key)      # (the settings start with none: the thumbnail shows it as it looks)
                vals = {p.name: fx.uniform_value(p, e["params"].get(p.name), 0) for p in d.params}
                out = np.ascontiguousarray(eng.run(d, vals, bg, time=t, unit=1.0))
            except Exception:
                continue
            self.frame.emit(key, QImage(out.data, w, h, 4 * w, QImage.Format_RGBA8888).copy())
        eng.close()


class AssetList(QListWidget):
    left = Signal()                                   # the pointer left the list

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self.left.emit()

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.setViewMode(QListWidget.IconMode)
        self.setIconSize(QSize(*THUMB))
        self.setGridSize(QSize(THUMB[0] + 18, THUMB[1] + 34))
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setWordWrap(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def fit(self):
        """As tall as its items need: the tab scrolls, not each list."""
        g = self.gridSize()
        if self.viewMode() == QListWidget.IconMode and g.width() > 0:
            cols = max(1, self.viewport().width() // g.width())
            rows = max(1, -(-self.count() // cols))
            h = rows * g.height() + 2 * self.frameWidth() + 4
        else:                                               # 列表: one row each
            rows = [self.sizeHintForRow(i) for i in range(self.count())]
            h = sum(max(r, self.iconSize().height() + 8) for r in rows) + 2 * self.frameWidth() + 4
        if self.height() != h:
            self.setFixedHeight(h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit()

    def mimeTypes(self):
        return [MEDIA_MIME]

    def mimeData(self, items):
        md = QMimeData()
        keys = [i.data(ROLE_KEY) for i in items if i.data(ROLE_KEY)]
        if keys:
            md.setData(MEDIA_MIME, self.panel.ident(keys[0]).encode("utf-8"))
        return md


class AssetsPanel(QWidget):
    addRequested = Signal(str)              # asset ident: add at the playhead

    def __init__(self, parent=None):
        super().__init__(parent)
        self.colors = list(assets.DEFAULT_COLORS)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        row = QHBoxLayout()
        self.color_btns = []
        for i, title in enumerate(("顏色 1", "顏色 2")):
            row.addWidget(QLabel(title))
            b = QPushButton()
            b.setFixedSize(46, 22)
            b.setToolTip(f"選擇{title}")
            b.clicked.connect(lambda _=False, k=i: self._pick(k))
            row.addWidget(b)
            self.color_btns.append(b)
        swap = QPushButton("交換")
        swap.setToolTip("交換兩個顏色")
        swap.clicked.connect(self._swap)
        row.addWidget(swap)
        row.addStretch(1)
        self.view_row = row                                 # (網格 / 列表: added once the lists exist)
        lay.addLayout(row)
        body = QWidget()
        blay = QVBoxLayout(body)
        blay.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        lay.addWidget(scroll, 1)
        self.lists = {}
        for cat, title in assets.CATEGORIES:
            head = QLabel(title)
            head.setStyleSheet("font-weight: bold; margin-top: 4px;")
            lst = AssetList(self)
            lst.itemDoubleClicked.connect(lambda it: self.addRequested.emit(self.ident(it.data(ROLE_KEY))))
            lst.setContextMenuPolicy(Qt.CustomContextMenu)
            lst.customContextMenuRequested.connect(lambda pos, l=lst: self._menu(l, pos))
            for a in assets.ASSETS:
                if a.cat == cat:
                    it = QListWidgetItem(a.name)
                    it.setData(ROLE_KEY, a.key)
                    it.setToolTip(a.name + ("（用顏色 1 / 2）" if a.custom else ""))
                    lst.addItem(it)
            blay.addWidget(head)
            blay.addWidget(lst)
            self.lists[cat] = lst
        head = QLabel(TEXT_CAT[1])                          # 文字: drag one on, the words are typed afterwards
        head.setStyleSheet("font-weight: bold; margin-top: 4px;")
        lst = AssetList(self)
        lst.itemDoubleClicked.connect(lambda it: self.addRequested.emit(self.ident(it.data(ROLE_KEY))))
        lst.setContextMenuPolicy(Qt.CustomContextMenu)
        lst.customContextMenuRequested.connect(lambda pos, l=lst: self._menu(l, pos))
        for key, name, _fields in textpresets.PRESETS:
            it = QListWidgetItem(name)
            it.setData(ROLE_KEY, "text." + key)
            it.setToolTip(name + "（拖到時間線加入文字，或拖進節點編輯器；文字在屬性裡改）")
            it.setIcon(QIcon(text_thumbnail(key)))
            lst.addItem(it)
        blay.addWidget(head)
        blay.addWidget(lst)
        self.lists[TEXT_CAT[0]] = lst
        head = QLabel(SCENE_CAT[1])                         # 3D 場景: its clips are planes in space seen by a camera
        head.setStyleSheet("font-weight: bold; margin-top: 4px;")
        lst = AssetList(self)
        lst.itemDoubleClicked.connect(lambda it: self.addRequested.emit(self.ident(it.data(ROLE_KEY))))
        it = QListWidgetItem("3D 場景")
        it.setData(ROLE_KEY, "scene3d.scene")
        it.setToolTip("3D 場景（拖到時間線；雙擊進去放片段，片段有 3D 位置和旋轉，攝影機在屬性裡）")
        it.setIcon(QIcon(QPixmap.fromImage(scene_thumbnail())))
        lst.addItem(it)
        it = QListWidgetItem("相機")
        it.setData(ROLE_KEY, "scene3d.camera")
        it.setToolTip("相機（在 3D 場景裡用：拖到時間線，場景用最上面那台正在播的相機看；位置在 3D 位置，看向哪裡和鏡頭在屬性裡）")
        it.setIcon(QIcon(QPixmap.fromImage(camera_thumbnail())))
        lst.addItem(it)
        for kind, name, tip in (("sun", "平行光", "往同一個方向照（用 旋轉 決定方向）"), ("point", "點光源", "從它的位置往四面照，越遠越暗"),
                                ("ambient", "環境光", "場景周圍的光有多亮（位置沒有作用）")):
            it = QListWidgetItem(name)
            it.setData(ROLE_KEY, "scene3d." + kind)
            it.setToolTip(f"{name}：{tip}。放進 3D 場景，照亮開了「進階光照」的立體物件；有燈在播時，場景改用這些燈")
            it.setIcon(QIcon(QPixmap.fromImage(light_thumbnail(kind))))
            lst.addItem(it)
        for kind, spec in mesh.PRIMITIVES.items():
            it = QListWidgetItem(spec[0])
            it.setData(ROLE_KEY, "scene3d." + kind)
            it.setToolTip(f"{spec[0]}：基礎物件，在 3D 場景裡用（顏色用上面的第一個顏色，之後在屬性改）")
            it.setIcon(QIcon(QPixmap.fromImage(solid_thumbnail(kind))))
            lst.addItem(it)
        it = QListWidgetItem("匯入模型…")
        it.setData(ROLE_KEY, "scene3d.model")
        it.setToolTip("匯入 3D 模型（.obj、.gltf、.glb）：雙擊或拖到時間線後選檔案，也可以直接把模型檔拖進視窗")
        it.setIcon(QIcon(QPixmap.fromImage(model_thumbnail())))
        lst.addItem(it)
        blay.addWidget(head)
        blay.addWidget(lst)
        self.lists[SCENE_CAT[0]] = lst
        head = QLabel(VIZ_CAT[1])                           # Audio Visualizer: a picture drawn from sound
        head.setStyleSheet("font-weight: bold; margin-top: 4px;")
        lst = AssetList(self)
        lst.itemDoubleClicked.connect(lambda it: self.addRequested.emit(self.ident(it.data(ROLE_KEY))))
        for kind, name in viz.KINDS.items():
            it = QListWidgetItem(name)
            it.setData(ROLE_KEY, "viz." + kind)
            it.setToolTip(name + "（聽時間線上有聲音的軌道，或一個檔案；在屬性裡設定）")
            it.setIcon(QIcon(viz_thumbnail(kind)))
            lst.addItem(it)
        blay.addWidget(head)
        blay.addWidget(lst)
        self.lists[VIZ_CAT[0]] = lst
        blay.addStretch(1)
        toggles = [list_toggle("assets", lst, QSize(*THUMB), QSize(THUMB[0] + 18, THUMB[1] + 34), QSize(*THUMB))
                   for lst in self.lists.values()]
        for b in toggles[1:]:                               # (one button for all of them)
            b.hide()
            toggles[0].toggled.connect(b.setChecked)
        self.view_row.addWidget(toggles[0])
        self._thumbs_setup()
        self.refresh()
        self.setMinimumWidth(260)

    def _thumbs_setup(self):
        """The 粒子 list: real pictures of the particle system instead of the painted ones as soon as they are drawn, and an animation
        while the pointer is over one."""
        self.thumbs = ParticleThumbs(self)
        self.thumbs.frame.connect(self._thumb_frame)
        lst = self.lists.get("particle")
        if lst is None:
            return
        self.hover = None                                   # (key, when it began) of the preset the pointer is over
        self.hover_timer = QTimer(self)
        self.hover_timer.setInterval(70)
        self.hover_timer.timeout.connect(self._hover_tick)
        lst.setMouseTracking(True)
        lst.itemEntered.connect(self._hover_begin)
        lst.left.connect(self._hover_end)
        self.destroyed.connect(self.thumbs.stop)
        self.still_timer = QTimer(self)                      # (asked once the tab shows, one preset after another, not all at once)
        self.still_timer.setSingleShot(True)
        self.still_timer.timeout.connect(self._ask_stills)
        self.pending_stills = []

    def showEvent(self, e):
        super().showEvent(e)
        if getattr(self, "pending_stills", None) is not None and not getattr(self, "stills_asked", False):
            self.stills_asked = True
            self.pending_stills = [a.key.split(".", 1)[1] for a in assets.ASSETS if a.cat == "particle"]
            self.still_timer.start(200)

    def _ask_stills(self):
        if self.pending_stills:
            self.thumbs.ask(self.pending_stills.pop(0), STILL_T)
            self.still_timer.start(40)

    def _thumb_frame(self, key, img):
        lst = self.lists.get("particle")
        for i in range(lst.count()) if lst else ():
            it = lst.item(i)
            if it.data(ROLE_KEY) == "particle." + key:
                it.setIcon(QIcon(QPixmap.fromImage(img)))

    def _hover_begin(self, it):
        key = it.data(ROLE_KEY)
        self.hover = (key.split(".", 1)[1], time.monotonic()) if key and key.startswith("particle.") else None
        if self.hover:
            self.hover_timer.start()

    def _hover_end(self):
        was, self.hover = self.hover, None
        self.hover_timer.stop()
        if was:                                              # (back to the still one)
            self.thumbs.ask(was[0], STILL_T)

    def _hover_tick(self):
        if self.hover:
            key, t0 = self.hover
            self.thumbs.ask(key, (time.monotonic() - t0) % THUMB_LOOP)

    def ident(self, key):
        if key.startswith("viz."):
            return "viz:" + key[4:]
        if key.startswith("text."):
            return textpresets.ident(key[5:])
        if key.startswith("scene3d."):
            return "scene3d:" + key[8:]
        return assets.ident(key, *self.colors)

    def refresh(self):
        for b, c in zip(self.color_btns, self.colors):
            b.setStyleSheet(f"background: {c}; border: 1px solid #555;")
        for lst in self.lists.values():
            for i in range(lst.count()):
                it = lst.item(i)
                a = assets.get(it.data(ROLE_KEY))
                if a is None:                                   # (an Audio Visualizer: no colours of the panel's)
                    continue
                if a.cat == "particle":
                    if it.icon().isNull():
                        it.setIcon(QIcon(particle_thumbnail(a.key.split(".", 1)[1])))
                elif a.custom or it.icon().isNull():
                    it.setIcon(QIcon(thumbnail(a, *self.colors)))

    def _pick(self, k):
        was = self.colors[k]

        def show(col):
            self.colors[k] = hex_of(col)
            self.refresh()
        col = pick_color(self, qcolor(was), f"顏色 {k + 1}", live=show)
        self.colors[k] = hex_of(col) if col is not None else was
        self.refresh()

    def _swap(self):
        self.colors.reverse()
        self.refresh()

    def _menu(self, lst, pos):
        it = lst.itemAt(pos)
        if it is None:
            return
        menu = Menu(self)
        menu.addAction("在播放頭加入", lambda: self.addRequested.emit(self.ident(it.data(ROLE_KEY))))
        menu.exec(lst.viewport().mapToGlobal(pos))
