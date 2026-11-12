"""Alt+Shift+R on the preview: how far the selected clips are moved, turned and stretched at random, with a seed. The
preview shows the result while the numbers are changed (live, nothing is edited); OK makes it one edit, Cancel puts it back."""
import math
import random

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QPushButton, QSpinBox,
                               QVBoxLayout)

DEFAULTS = {"move_x": 15.0, "move_y": 15.0, "rot": 20.0, "scale_lo": 75.0, "scale_hi": 130.0, "stretch": 0.0,
            "differ": True, "keep": False, "seed": 1}
_last = dict(DEFAULTS)                      # (what was asked for last is offered again)


def rolled(base, p):
    """{clip id: {x, y, rotation, scale, scale_y}} for base = [Box], by the settings p (seed included). With p["keep"] (保持間隔)
    one roll is made for all of them and applied about their middle: the spaces between the clips stay, as a whole they move, turn and scale."""
    out = {}
    keep = p.get("keep") and len(base) > 1
    mx = sum(b.cx for b in base) / len(base)
    my = sum(b.cy for b in base) / len(base)
    for i, b in enumerate(base):
        r = random.Random(p["seed"] * 1000003 + (i if p["differ"] and not keep else 0))
        u = r.uniform
        dx, dy, da = u(-1, 1), u(-1, 1), u(-1, 1)
        k = u(p["scale_lo"], p["scale_hi"]) / 100
        sx, sy = (1 + u(-1, 1) * p["stretch"] / 100, 1 + u(-1, 1) * p["stretch"] / 100)
        ang = da * p["rot"]
        cx, cy = b.cx, b.cy
        if keep:
            c, sn = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            ox, oy = (cx - mx) * k * sx, (cy - my) * k * sy
            cx, cy = mx + ox * c - oy * sn, my + ox * sn + oy * c
        out[b.clip["id"]] = {"x": round(b.x_at(cx + dx * p["move_x"] / 100 * b.W), 5),
                             "y": round(b.y_at(cy + dy * p["move_y"] / 100 * b.H), 5),
                             "rotation": round(b.deg + ang, 3),
                             "scale": round(b.s * k * sx, 4), "scale_y": round(b.sy * k * sy, 4)}
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
        self.keep = QCheckBox("保持間隔")
        self.keep.setToolTip("選了多個片段時：片段之間的距離與排列不變，整批一起移動、旋轉、縮放")
        self.keep.setChecked(p["keep"] and len(boxes) > 1)
        self.keep.setEnabled(len(boxes) > 1)
        self.keep.toggled.connect(lambda on: (self.differ.setEnabled(not on), self.changed()))
        self.differ.setEnabled(not self.keep.isChecked())
        form.addRow("", self.keep)
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
        p.update(differ=self.differ.isChecked(), keep=self.keep.isChecked(), seed=self.seed.value())
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
