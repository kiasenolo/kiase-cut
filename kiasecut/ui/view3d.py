"""3D 視角: the preview seen from outside the scene, as Blender's 3D viewport (the editor's view only: nothing of it is saved or rendered).

It is for a level whose camera is on (a 3D 場景 that is opened): the picture is drawn by the renderer from a free camera of the view's own
(Preview.view3d.render_camera(): the main window puts it into the copy it renders), and over it the view draws a floor grid, the three
axes (X red, Y green - up -, Z blue - away), the scene's own camera as a pyramid and the outline of every plane.

Moving about is Blender's: the middle button turns the view round what it looks at, with Shift it slides it, with Ctrl it goes nearer or
farther (the wheel too); the number pad's 1 / 3 / 7 look from the front / right / top (Ctrl: the opposite side), 0 looks through the
scene's camera (what is rendered), Home shows the whole scene, the pad's . puts the selected plane in the middle. Turning the view from
the camera's own view starts from where the camera is.
"""
import math

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPen, QPolygonF

from .. import camera, curves, project

ORBIT_PER_PX = 0.4            # degrees a screen px of drag turns the view
ZOOM_PER_PX = 0.006           # (exponent of the distance)
WHEEL_NOTCH = 0.14
GRID = 0.5                    # units (half heights) between grid lines
GRID_N = 8
RED, GREEN, BLUE = QColor(220, 70, 70), QColor(110, 190, 70), QColor(70, 130, 230)
GRID_COLOR = QColor(255, 255, 255, 38)
CAMERA_COLOR = QColor(255, 255, 255, 200)
PLANE_COLOR = QColor(120, 200, 255, 190)
SELECTED_COLOR = QColor(255, 170, 40)

NUMPAD = {Qt.Key_1: ("front", "back"), Qt.Key_3: ("right", "left"), Qt.Key_7: ("top", "bottom")}


class View3D:
    def __init__(self, preview):
        self.p = preview
        self.cam = None                  # the view's own camera (plain numbers), None until it is first used
        self.through = False             # looking through the scene's camera (nothing is changed then)
        self.nav = None                  # {"kind": "orbit" | "pan" | "zoom", "pos"}: a drag of the view

    # -- the cameras ------------------------------------------------------------------------------------------------------------
    def scene_camera(self):
        return (self.p.view or {}).get("camera")

    def available(self):
        return bool(self.p.view) and camera.on(self.scene_camera())

    def time(self):
        return self.p.t_us

    def _from_scene_camera(self):
        real = dict(self.scene_camera() or {"on": True})
        _f, c, tg, _axes = camera._pose(real, self.time(), self.p.W, self.p.H)
        cam = {"on": True, "fov": float(curves.value(real.get("fov", camera.FOV), self.time()))}
        cam.update(camera._units(c, self.p.W, self.p.H))
        cam.update(camera._units(tg, self.p.W, self.p.H, "t"))
        return cam

    def start(self):
        """From the scene's camera, a little round the side and farther away - where the whole scene shows."""
        cam = self._from_scene_camera()
        cam.update(camera.orbit(cam, 0, self.p.W, self.p.H, 35.0, 22.0, per_px=1.0))
        cam.update(camera.dolly(cam, 0, self.p.W, self.p.H, 200.0))
        self.cam, self.through = cam, False

    def render_camera(self):
        """The camera the renderer draws from, or None for the scene's own (looking through it)."""
        if self.cam is None:
            self.start()
        return None if self.through else dict(self.cam)

    def seen(self):
        cam = self.scene_camera() if self.through else self.cam
        return camera.Seen(cam, self.time() if self.through else 0, self.p.W, self.p.H)

    def _changed(self):
        self.p.view3dChanged.emit()
        self.p.update()

    # -- moving about ---------------------------------------------------------------------------------------------------------
    def _leave_camera_view(self):
        if self.cam is None:
            self.start()
        if self.through:
            self.cam = self._from_scene_camera()
            self.through = False

    def _apply(self, units):
        self.cam.update({k: round(float(v), 5) for k, v in units.items()})
        self._changed()

    def orbit(self, dx, dy):
        self._leave_camera_view()
        self._apply(camera.orbit(self.cam, 0, self.p.W, self.p.H, dx, dy, per_px=ORBIT_PER_PX))

    def pan(self, dx, dy):
        """dx, dy: canvas px at the plane the view looks at."""
        self._leave_camera_view()
        self._apply(camera.track(self.cam, 0, self.p.W, self.p.H, dx, dy))

    def zoom(self, amount):
        """amount > 0: nearer."""
        self._leave_camera_view()
        self._apply(camera.dolly(self.cam, 0, self.p.W, self.p.H, -amount, per_px=1.0))

    def look_from(self, name):
        self._leave_camera_view()
        self._apply(camera.look_from(self.cam, 0, self.p.W, self.p.H, name))

    def camera_view(self):
        self.through = True
        self._changed()

    def frame(self, points=None):
        """Put what the view looks at in the middle: the middle of the scene (or of the points), from the distance the whole of it shows."""
        self._leave_camera_view()
        s = self.p.H / 2.0
        pts = points if points else self.scene_points()
        if not pts:
            pts = [np.zeros(3)]
        lo, hi = np.min(pts, axis=0), np.max(pts, axis=0)
        mid, size = (lo + hi) / 2.0, max(float(np.linalg.norm(hi - lo)), s)
        _f, c, tg, _axes = camera._pose(self.cam, 0, self.p.W, self.p.H)
        v = c - tg
        n = float(np.linalg.norm(v)) or 1.0
        fov = float(curves.value(self.cam.get("fov", camera.FOV), 0))
        dist = size * 0.75 / math.tan(math.radians(fov) / 2.0)
        self.cam.update(camera._units(mid + v / n * dist, self.p.W, self.p.H))
        self.cam.update(camera._units(mid, self.p.W, self.p.H, "t"))
        self._changed()

    def scene_points(self):
        pts = []
        for corners in self.plane_corners().values():
            pts += corners
        return pts

    # -- the planes -----------------------------------------------------------------------------------------------------------
    def plane_corners(self):
        """{clip id: [4 world points]} of the clips showing now: the corners of each plane."""
        out = {}
        W, H = self.p.W, self.p.H
        for b in self.p.visible_boxes():
            c = b.clip
            if c["type"] == "audio" or c.get("transform") is None:
                continue
            t = project.stepped(c, b.t)
            hw, hh = b.bw * abs(b.s) / 2.0, b.bh * abs(b.sy) / 2.0
            out[c["id"]] = camera.world_of(c["transform"], t, W, H, [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)])
        return out

    # -- events ---------------------------------------------------------------------------------------------------------------
    def mouse_press(self, e):
        if e.button() == Qt.MiddleButton:
            mods = e.modifiers()
            kind = "zoom" if mods & Qt.ControlModifier else "pan" if mods & Qt.ShiftModifier else "orbit"
            self.nav = {"kind": kind, "pos": e.position()}
            self.p.setCursor(Qt.SizeVerCursor if kind == "zoom" else Qt.SizeAllCursor)
            return True
        return False

    def mouse_move(self, e):
        if self.nav is None:
            return False
        d = e.position() - self.nav["pos"]
        self.nav["pos"] = e.position()
        if self.nav["kind"] == "orbit":
            self.orbit(d.x(), d.y())
        elif self.nav["kind"] == "pan":
            k = self.p._k()
            self.pan(d.x() * k, d.y() * k)
        else:
            self.zoom(-d.y() * ZOOM_PER_PX)
        return True

    def mouse_release(self, e):
        if self.nav is not None and e.button() == Qt.MiddleButton:
            self.nav = None
            self.p.unsetCursor()
            return True
        return False

    def wheel(self, notches, shift=False, ctrl=False):
        k = self.p._k()
        if shift:
            self.pan(0.0, notches * 40 * k)
        elif ctrl:
            self.pan(notches * 40 * k, 0.0)
        else:
            self.zoom(notches * WHEEL_NOTCH)
        return True

    def key_action(self, e):
        """What key event e does in this view (a function to call), or None."""
        k, mods = e.key(), e.modifiers()
        if mods & (Qt.AltModifier | Qt.ShiftModifier):
            return None
        if k in NUMPAD:
            side = NUMPAD[k][1 if mods & Qt.ControlModifier else 0]
            return lambda: self.look_from(side)
        if mods & Qt.ControlModifier:
            return None
        if k == Qt.Key_0:
            return self.camera_view
        if k == Qt.Key_Home:
            return self.frame
        if k == Qt.Key_Period:
            return lambda: self.frame(self.plane_corners().get(self.p.selected_id))
        return None

    # -- painting -------------------------------------------------------------------------------------------------------------
    def paint(self, p, k):
        """The grid, axes, camera and planes over the picture. p: a painter in canvas px, k canvas px per screen px."""
        if self.cam is None:
            self.start()
        if self.through:
            return
        seen = self.seen()
        s = self.p.H / 2.0

        def line(a, b, color, width=1.0):
            seg = seen.segment(a, b)
            if seg is not None:
                p.setPen(QPen(color, width * k))
                p.drawLine(QPointF(*seg[0]), QPointF(*seg[1]))
        r = GRID * GRID_N * s
        for i in range(-GRID_N, GRID_N + 1):
            o = i * GRID * s
            if i:
                line((o, 0, -r), (o, 0, r), GRID_COLOR)
                line((-r, 0, o), (r, 0, o), GRID_COLOR)
        line((-r, 0, 0), (r, 0, 0), RED, 1.5)
        line((0, 0, -r), (0, 0, r), BLUE, 1.5)
        line((0, -r * 0.5, 0), (0, r * 0.5, 0), GREEN, 1.5)
        self._paint_camera(p, k, seen)
        for cid, pts in self.plane_corners().items():
            chosen = cid in self.p.selected_ids
            color, width = (SELECTED_COLOR, 2.0) if chosen else (PLANE_COLOR, 1.25)
            scr = [seen.point(q) for q in pts]
            if any(q is None for q in scr):                     # (a corner is behind the view: only the lines in front)
                for i in range(4):
                    line(pts[i], pts[(i + 1) % 4], color, width)
                continue
            p.setPen(QPen(color, width * k))
            p.setBrush(QColor(255, 170, 40, 30) if chosen else Qt.NoBrush)
            p.drawPolygon(QPolygonF([QPointF(*q) for q in scr]))
            p.setBrush(Qt.NoBrush)

    def _paint_camera(self, p, k, seen):
        real = self.scene_camera()
        if not camera.on(real):
            return
        c, corners, tg = camera.frustum(real, self.time(), self.p.W, self.p.H)

        def line(a, b, width=1.25):
            seg = seen.segment(a, b)
            if seg is not None:
                p.setPen(QPen(CAMERA_COLOR, width * k))
                p.drawLine(QPointF(*seg[0]), QPointF(*seg[1]))
        for q in corners:
            line(c, q)
        for i in range(4):
            line(corners[i], corners[(i + 1) % 4])
        line(c, tg, 0.8)
        top = (corners[0] + corners[1]) / 2.0 + (corners[0] - corners[3]) * 0.5       # (a triangle on the picture's top: which way is up)
        line(corners[0], top)
        line(corners[1], top)
        at = seen.point(tg)
        if at is not None:
            p.setPen(QPen(CAMERA_COLOR, 1.25 * k))
            p.drawEllipse(QPointF(*at), 3 * k, 3 * k)
