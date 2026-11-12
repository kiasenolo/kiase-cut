"""Alt+Shift+R on the preview: how far the selected clips are moved, turned and stretched at random, with a seed. The
preview shows the result while the numbers are changed (live, nothing is edited); OK makes it one edit, Cancel puts it back."""
import math
import random

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QPushButton, QSpinBox,
                               QVBoxLayout)

DEFAULTS = {"move_x": 15.0, "move_y": 15.0, "rot": 20.0, "scale_lo": 75.0, "scale_hi": 130.0, "stretch": 0.0,
            "differ": True, "force": False, "gap": 20.0, "seed": 1}
_last = dict(DEFAULTS)                      # (what was asked for last is offered again)


TRIES = 300


def _roll(b, p, r):
    """One random placing of Box b: (x, y, rotation, scale, scale_y) values, and its rectangle on the canvas (left, top, right, bottom)
    around the turned, scaled clip."""
    u = r.uniform
    dx, dy, da = u(-1, 1), u(-1, 1), u(-1, 1)
    k = u(p["scale_lo"], p["scale_hi"]) / 100
    sx, sy = (1 + u(-1, 1) * p["stretch"] / 100, 1 + u(-1, 1) * p["stretch"] / 100)
    cx, cy = b.cx + dx * p["move_x"] / 100 * b.W, b.cy + dy * p["move_y"] / 100 * b.H
    deg, s, s_y = b.deg + da * p["rot"], b.s * k * sx, b.sy * k * sy
    w, h = b.bw * abs(s), b.bh * abs(s_y)
    c, sn = abs(math.cos(math.radians(deg))), abs(math.sin(math.radians(deg)))
    hw, hh = (w * c + h * sn) / 2, (w * sn + h * c) / 2
    vals = {"x": round(b.x_at(cx), 5), "y": round(b.y_at(cy), 5), "rotation": round(deg, 3), "scale": round(s, 4), "scale_y": round(s_y, 4)}
    return vals, (cx - hw, cy - hh, cx + hw, cy + hh)


def _overlap(a, rects, gap):
    """How much rectangle a, made gap px bigger all round, covers of the others (0: they are at least gap apart)."""
    t = 0.0
    for o in rects:
        w = min(a[2] + gap, o[2]) - max(a[0] - gap, o[0])
        h = min(a[3] + gap, o[3]) - max(a[1] - gap, o[1])
        if w > 0 and h > 0:
            t += w * h
    return t


def rolled(base, p):
    """{clip id: {x, y, rotation, scale, scale_y}} for base = [Box], by the settings p (seed included). With p["force"] (強制間隔)
    each clip, in turn, is rolled again (the same seed gives the same tries) till it is at least p["gap"] px (a 1080 high picture's)
    from the clips placed before it; if no try is clear it takes the one that covers the least."""
    out, rects = {}, []
    force = p.get("force") and len(base) > 1
    for i, b in enumerate(base):
        base_seed = p["seed"] * 1000003 + (i if p["differ"] or force else 0)
        best = None
        for n in range(TRIES if force else 1):
            vals, rect = _roll(b, p, random.Random(base_seed + n * 7919))
            miss = _overlap(rect, rects, p["gap"] * b.H / 1080) if force else 0.0
            if best is None or miss < best[0]:
                best = (miss, vals, rect)
            if miss <= 0:
                break
        out[b.clip["id"]] = best[1]
        rects.append(best[2])
    return out


class RandomDialog(QDialog):
    def __init__(self, parent, boxes, live, commit, cancel):
        super().__init__(parent)
        self.boxes, self.live, self.commit, self.cancel = boxes, live, commit, cancel
        self.done_ok = False
        self.setWindowTitle("隨機變形")
        p = _last
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.spins = {}

        def add(key, label, lo, hi, suffix, tip=""):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setDecimals(1)
            s.setSuffix(suffix)
            s.setValue(p[key])
            s.setKeyboardTracking(False)
            s.setToolTip(tip)
            s.valueChanged.connect(self.changed)
            self.spins[key] = s
            form.addRow(label, s)
        add("move_x", "左右移動（±）", 0, 200, " %", "畫面寬度的百分比")
        add("move_y", "上下移動（±）", 0, 200, " %", "畫面高度的百分比")
        add("rot", "旋轉（±）", 0, 360, " °")
        add("scale_lo", "縮放 最小", 1, 1000, " %", "相對於現在的大小")
        add("scale_hi", "縮放 最大", 1, 1000, " %", "相對於現在的大小")
        add("stretch", "形變（橫、縱各自 ±）", 0, 100, " %", "橫向、縱向再各自隨機多拉長或壓扁多少；0 則保持比例")
        self.differ = QCheckBox("每個片段都不一樣")
        self.differ.setChecked(p["differ"])
        self.differ.toggled.connect(self.changed)
        form.addRow("", self.differ)
        self.force = QCheckBox("強制間隔")
        self.force.setToolTip("選了多個片段時：隨機到片段重疊或靠太近就重抽，直到每個片段之間至少隔著下面的距離（同一個種子結果一樣）；"
                              "實在排不開就用重疊最少的")
        self.force.setChecked(p["force"] and len(boxes) > 1)
        self.force.setEnabled(len(boxes) > 1)
        self.gap = QDoubleSpinBox()
        self.gap.setRange(0, 2000)
        self.gap.setDecimals(1)
        self.gap.setSuffix(" px")
        self.gap.setValue(p["gap"])
        self.gap.setKeyboardTracking(False)
        self.gap.setToolTip("1080 高的畫面的像素")
        self.gap.valueChanged.connect(self.changed)
        self.force.toggled.connect(lambda on: (self.differ.setEnabled(not on), self.gap.setEnabled(on), self.changed()))
        self.differ.setEnabled(not self.force.isChecked())
        self.gap.setEnabled(self.force.isChecked())
        row = QHBoxLayout()
        row.addWidget(self.force)
        row.addWidget(self.gap, 1)
        form.addRow("", row)
        self.seed = QSpinBox()
        self.seed.setRange(0, 999999999)
        self.seed.setValue(p["seed"])
        self.seed.setKeyboardTracking(False)
        self.seed.valueChanged.connect(self.changed)
        dice = QPushButton("🎲 換一個")
        dice.clicked.connect(lambda: self.seed.setValue(random.randrange(1, 1000000)))
        row = QHBoxLayout()
        row.addWidget(self.seed, 1)
        row.addWidget(dice)
        form.addRow("種子", row)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.changed()

    def settings(self):
        p = {k: s.value() for k, s in self.spins.items()}
        p.update(differ=self.differ.isChecked(), force=self.force.isChecked(), gap=self.gap.value(), seed=self.seed.value())
        p["scale_hi"] = max(p["scale_hi"], p["scale_lo"])
        return p

    def changed(self, *_a):
        self.live(rolled(self.boxes, self.settings()))

    def accept(self):
        p = self.settings()
        _last.update(p)
        super().accept()
        self.commit(rolled(self.boxes, p))

    def reject(self):
        super().reject()
        self.cancel()
