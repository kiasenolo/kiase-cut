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
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QPen, QPolygonF

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


class CamThing:
    """The scene's camera or its target as something the arrows move (stands where a plane's box does)."""
    clip_type = None

    def __init__(self, kind):
        self.kind = kind                                   # "camera" | "target"
        self.clip = {"id": "~" + kind, "type": "camera"}
        self.locked = False
        self.t = 0


class View3D:
    def __init__(self, preview):
        self.p = preview
        self.cam = None                  # the view's own camera (plain numbers), None until it is first used
        self.through = False             # looking through the scene's camera (nothing is changed then)
        self.nav = None                  # {"kind": "orbit" | "pan" | "zoom", "pos"}: a drag of the view
        self.live = {}                   # {clip id: {x, y, z, ...}} being dragged: the outlines follow before the edit is made
        self.drag = None                 # a drag of an arrow of the selected plane, or its middle
        self.modal = None                # G / R / S: the selected plane follows the pointer till a click (Esc puts it back)
        self.sel_cam = None              # "camera" | "target": the scene's camera or its target is what is selected (not a plane)

    # -- the cameras ------------------------------------------------------------------------------------------------------------
    def scene_camera(self):
        """The scene's camera (what is being dragged on top of it)."""
        cam = (self.p.view or {}).get("camera")
        if cam is None:
            return None
        for name in ("camera", "target"):
            live = self.live.get("~" + name)
            if live:
                cam = dict(cam, **{(("t" if name == "target" else "") + k): v for k, v in live.items() if k in "xyz"})
        return cam

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
        if self.cam is None:
            self.start()
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
            tf = dict(c["transform"], **self.live.get(c["id"], {}))
            sx, sy = abs(self.live.get(c["id"], {}).get("scale", b.s)), abs(self.live.get(c["id"], {}).get("scale_y", b.sy))
            hw, hh = b.bw * sx / 2.0, b.bh * sy / 2.0
            out[c["id"]] = camera.world_of(tf, t, W, H, [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)])
        return out

    # -- the selected plane: its arrows ---------------------------------------------------------------------------------------
    AXES = {"x": (1.0, 0.0, 0.0), "y": (0.0, -1.0, 0.0), "z": (0.0, 0.0, 1.0)}          # (y is up: the world's y goes down)
    COLORS = {"x": RED, "y": GREEN, "z": BLUE}
    ARROW_PX = 110                                  # screen px an arrow is long, whatever the distance

    def selected(self):
        """(box, clip) of the one plane that is selected and can be moved, or None."""
        if self.sel_cam and not self.through and camera.on(self.scene_camera()):
            return CamThing(self.sel_cam)
        if len(self.p.selected_ids) != 1:
            return None
        for b in self.p.visible_boxes():
            if b.clip["id"] == self.p.selected_id and not b.locked and b.clip.get("transform") is not None and b.clip["type"] != "audio":
                return b
        return None

    def values(self, b):
        """The plane's own numbers now (what is being dragged on top of the clip's)."""
        if isinstance(b, CamThing):
            _f, c, tg, _axes = camera._pose(self.scene_camera(), self.time(), self.p.W, self.p.H)
            u = camera._units(c if b.kind == "camera" else tg, self.p.W, self.p.H)
            return dict(u, rot_x=0.0, rot_y=0.0, rotation=0.0, scale=1.0, scale_y=1.0)
        tf, t = b.clip["transform"], project.stepped(b.clip, b.t)
        live = self.live.get(b.clip["id"], {})
        get = lambda key, default=0.0: float(live[key]) if key in live else float(curves.value(tf.get(key, default), t))
        out = {k: get(k, 1.0 if k == "scale" else 0.0) for k in ("x", "y", "z", "rot_x", "rot_y", "rotation", "scale")}
        out["scale_y"] = get("scale_y", out["scale"])                 # (without its own it follows the X scale)
        return out

    def origin(self, v):
        s = self.p.H / 2.0
        return np.array([v["x"] * self.p.W / 2.0, -v["y"] * s, v["z"] * s])

    def arrow_length(self, seen, o, k):
        z = seen.space(o)[2]
        return max(z, 1e-3) * self.ARROW_PX * k / seen.f

    def arrows(self, seen, o, k):
        """{axis: (tip world point, tip on the picture or None)} of the three arrows of a plane whose middle is at o."""
        n = self.arrow_length(seen, o, k)
        out = {}
        for a, d in self.AXES.items():
            tip = o + np.array(d) * n
            out[a] = (tip, seen.point(tip))
        return out

    def _canvas(self, pos):
        return QPointF(*self.p._to_canvas(pos))

    def _ray(self, pos):
        m = self._canvas(pos)
        return self.seen().ray(m.x(), m.y())

    @staticmethod
    def _on_axis(ray, o, axis):
        """How far along the axis (a unit vector) through o the point nearest the line of sight is, or None when they are parallel."""
        c, d = ray
        w = o - c
        b, dd, ee = float(axis @ d), float(axis @ w), float(d @ w)
        denom = 1.0 - b * b
        return None if denom < 1e-6 else (b * ee - dd) / denom

    @staticmethod
    def _in_plane(ray, o, n):
        """The point where the line of sight meets the plane through o with normal n, or None."""
        c, d = ray
        den = float(d @ n)
        if abs(den) < 1e-6:
            return None
        t = float((o - c) @ n) / den
        return c + d * t if t > 0 else None

    def hit_arrow(self, pos):
        """("x" | "y" | "z" | "plane", box) when the pointer is on an arrow of the selected plane or on its middle, else None."""
        b = self.selected()
        if b is None or self.through:
            return None
        seen, k = self.seen(), self.p._k()
        o = self.origin(self.values(b))
        mid = seen.point(o)
        if mid is None:
            return None
        m = self._canvas(pos)
        near = lambda q, r: q is not None and math.hypot(q[0] - m.x(), q[1] - m.y()) <= r * k
        for a, (_tip, at) in self.arrows(seen, o, k).items():
            if near(at, 9):
                return a, b
        if near(mid, 9):
            return "plane", b
        return None

    # -- events ---------------------------------------------------------------------------------------------------------------
    def mouse_press(self, e):
        if self.modal is not None:                            # (the click that keeps a G / R / S, or the right button that puts it back)
            if e.button() in (Qt.LeftButton, Qt.RightButton):
                self.modal_end(e.button() == Qt.LeftButton)
            return True
        if e.button() == Qt.LeftButton:
            hit = self.hit_arrow(e.position())
            if hit is not None:
                self.start_drag(hit[0], hit[1], e.position())
            else:
                self.pick(e.position(), bool(e.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier)))
            return True
        if e.button() == Qt.MiddleButton:
            mods = e.modifiers()
            kind = "zoom" if mods & Qt.ControlModifier else "pan" if mods & Qt.ShiftModifier else "orbit"
            self.nav = {"kind": kind, "pos": e.position()}
            self.p.setCursor(Qt.SizeVerCursor if kind == "zoom" else Qt.SizeAllCursor)
            return True
        return False

    def mouse_move(self, e):
        if self.modal is not None:
            self.modal_move(e.position())
            return True
        if self.drag is not None:
            self.drag_move(e.position())
            return True
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
        if self.drag is not None and e.button() == Qt.LeftButton:
            self.drag_end()
            return True
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
        grab = {Qt.Key_G: "move", Qt.Key_R: "rotate", Qt.Key_S: "scale"}.get(k)
        sel = self.selected() if grab and not self.through else None
        if sel is not None and isinstance(sel, CamThing) and grab != "move":
            return None                                        # (the camera is only moved)
        if grab and sel is not None and self.drag is None:
            return lambda: self.modal_begin(grab)
        if k == Qt.Key_0:
            return self.camera_view
        if k == Qt.Key_Home:
            return self.frame
        if k == Qt.Key_Period:
            return lambda: self.frame(self.plane_corners().get(self.p.selected_id))
        return None

    # -- picking and dragging the planes ------------------------------------------------------------------------------------------
    def pick(self, pos, add):
        """A click: the nearest plane the line of sight goes through is selected (none: nothing is)."""
        thing = self.pick_camera(pos)
        if thing is not None:
            self.sel_cam = thing
            self.p.selectionPicked.emit(set(), None)
            self.p.update()
            return
        self.sel_cam = None
        c, d = self._ray(pos)
        best = None
        for cid, pts in self.plane_corners().items():
            e1, e2 = pts[1] - pts[0], pts[3] - pts[0]
            n = np.cross(e1, e2)
            den = float(d @ n)
            if abs(den) < 1e-9:
                continue
            t = float((pts[0] - c) @ n) / den
            if t <= 0:
                continue
            q = c + d * t - pts[0]
            u, v = float(q @ e1) / float(e1 @ e1), float(q @ e2) / float(e2 @ e2)
            if 0.0 <= u <= 1.0 and 0.0 <= v <= 1.0 and (best is None or t < best[0]):
                best = (t, cid)
        clip = None
        if best is not None:
            clip = next((b.clip for b in self.p.visible_boxes() if b.clip["id"] == best[1]), None)
        if clip is None:
            if not add:
                self.p.selectionPicked.emit(set(), None)
        elif add:
            ids = set(self.p.selected_ids) ^ {clip["id"]}
            self.p.selectionPicked.emit(ids, clip["id"] if clip["id"] in ids else next(iter(ids), None))
        else:
            self.p.clipPicked.emit(clip)

    def pick_camera(self, pos):
        """"camera" when the pointer is on the scene's camera (its apex or a line of its pyramid), "target" on the point it looks at, else None."""
        real = self.scene_camera()
        if not camera.on(real) or self.through:
            return None
        seen, k = self.seen(), self.p._k()
        m = self._canvas(pos)
        c, corners, tg = camera.frustum(real, self.time(), self.p.W, self.p.H)
        at = seen.point(tg)
        if at is not None and math.hypot(at[0] - m.x(), at[1] - m.y()) <= 10 * k:
            return "target"
        edges = [(c, q) for q in corners] + [(corners[i], corners[(i + 1) % 4]) for i in range(4)]
        for a, b in edges:
            seg = seen.segment(a, b)
            if seg is None:
                continue
            (x0, y0), (x1, y1) = seg
            dx, dy = x1 - x0, y1 - y0
            n = dx * dx + dy * dy
            t = 0.0 if n < 1e-9 else min(1.0, max(0.0, ((m.x() - x0) * dx + (m.y() - y0) * dy) / n))
            if math.hypot(x0 + t * dx - m.x(), y0 + t * dy - m.y()) <= 7 * k:
                return "camera"
        return None

    def _emit_live(self, b, vals):
        self.live[b.clip["id"]] = dict(vals)
        if not isinstance(b, CamThing):
            self.p.paramsLive.emit(b.clip["id"], "transform", dict(vals))
        self.p.update()

    def _end_live(self, b, keep):
        vals = self.live.pop(b.clip["id"], None)
        if isinstance(b, CamThing):                          # (the camera: an edit of its own fields)
            if vals and keep:
                self.p.sceneCameraEdited.emit({(("t" if b.kind == "target" else "") + k): v for k, v in vals.items()})
            self.p.update()
        elif vals and keep:
            self.p.paramsCommitted.emit(b.clip["id"], "transform", vals)
        elif vals:
            self.p.grabCancelled.emit()
        self.p.update()

    def _moved(self, v0, dv, keys="xyz"):
        """The x, y, z that follow a move of dv (world px) from the numbers v0."""
        s = self.p.H / 2.0
        out = {}
        if "x" in keys:
            out["x"] = round(v0["x"] + dv[0] / (self.p.W / 2.0), 5)
        if "y" in keys:
            out["y"] = round(v0["y"] - dv[1] / s, 5)
        if "z" in keys:
            out["z"] = round(v0["z"] + dv[2] / s, 5)
        return out

    def start_drag(self, kind, b, pos):
        v0 = self.values(b)
        o0 = self.origin(v0)
        seen = self.seen()
        ray = self._ray(pos)
        if kind == "plane":
            n = seen.axes[2]
            self.drag = {"kind": kind, "b": b, "v0": v0, "start": self._in_plane(ray, o0, n), "n": n, "o0": o0, "moved": False}
        else:
            a = np.array(self.AXES[kind])
            self.drag = {"kind": kind, "b": b, "v0": v0, "start": self._on_axis(ray, o0, a), "a": a, "o0": o0, "moved": False}

    def drag_move(self, pos):
        d = self.drag
        ray = self._ray(pos)
        if d["start"] is None:
            return
        if d["kind"] == "plane":
            q = self._in_plane(ray, d["o0"], d["n"])
            if q is None:
                return
            vals = self._moved(d["v0"], q - d["start"])
        else:
            s = self._on_axis(ray, d["o0"], d["a"])
            if s is None:
                return
            vals = self._moved(d["v0"], d["a"] * (s - d["start"]), d["kind"])
        d["moved"] = True
        self._emit_live(d["b"], vals)

    def drag_end(self):
        d, self.drag = self.drag, None
        self._end_live(d["b"], d["moved"])

    # -- G / R / S: the plane follows the pointer ------------------------------------------------------------------------------
    def modal_begin(self, kind):
        b = self.selected()
        if b is None:
            return
        pos = QPointF(self.p.mapFromGlobal(QCursor.pos()))
        v0 = self.values(b)
        self.modal = {"kind": kind, "b": b, "v0": v0, "o0": self.origin(v0), "m0": pos, "axis": None}
        self._modal_anchor()
        self.p.setCursor(Qt.SizeAllCursor)
        self.p.update()

    def _modal_anchor(self):
        """Where the line of sight met the plane's axis (or the picture's plane) when the move began - what the move is measured from."""
        m = self.modal
        ray = self._ray(m["m0"])
        if m["axis"]:
            m["start"] = self._on_axis(ray, m["o0"], np.array(self.AXES[m["axis"]]))
        else:
            m["start"] = self._in_plane(ray, m["o0"], self.seen().axes[2])

    def modal_move(self, pos):
        m = self.modal
        ray = self._ray(pos)
        v0, kind = m["v0"], m["kind"]
        if kind == "move":
            if m["start"] is None:
                return
            if m["axis"]:
                s = self._on_axis(ray, m["o0"], np.array(self.AXES[m["axis"]]))
                if s is None:
                    return
                vals = self._moved(v0, np.array(self.AXES[m["axis"]]) * (s - m["start"]), m["axis"])
            else:
                q = self._in_plane(ray, m["o0"], self.seen().axes[2])
                if q is None:
                    return
                vals = self._moved(v0, q - m["start"])
        elif kind == "rotate":
            key = {"x": "rot_x", "y": "rot_y"}.get(m["axis"], "rotation")
            vals = {key: round(v0[key] + (pos.x() - m["m0"].x()) * 0.5, 3)}
        else:
            f = max(0.01, 1.0 + (pos.x() - m["m0"].x()) / 200.0)
            vals = {"scale": round(v0["scale"] * f, 5), "scale_y": round(v0["scale_y"] * f, 5)}
        m["moved"] = True
        self._emit_live(m["b"], vals)

    def modal_key(self, e, act):
        """A key while G / R / S is on; True when it takes it."""
        k = e.key()
        if e.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
            return False
        if k == Qt.Key_Escape:
            if act:
                self.modal_end(False)
            return True
        if k in (Qt.Key_Return, Qt.Key_Enter):
            if act:
                self.modal_end(True)
            return True
        axis = {Qt.Key_X: "x", Qt.Key_Y: "y", Qt.Key_Z: "z"}.get(k)
        if axis:
            if act:
                m = self.modal
                m["axis"] = None if m["axis"] == axis else axis
                if self.live.get(m["b"].clip["id"]):                 # (the other way of moving starts again from where it began)
                    self.live.pop(m["b"].clip["id"], None)
                    self.p.grabCancelled.emit()
                self._modal_anchor()
                self.p.update()
            return True
        return False

    def modal_end(self, keep):
        m, self.modal = self.modal, None
        self.p.unsetCursor()
        self._end_live(m["b"], keep and m.get("moved", False))

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
        self._paint_arrows(p, k, seen)

    def _paint_arrows(self, p, k, seen):
        """The three arrows (X red, Y green, Z blue) and the middle of the selected plane; while G / R is on the axis it is held to is drawn long."""
        b = self.selected()
        if b is None:
            return
        o = self.origin(self.values(b))
        mid = seen.point(o)
        if mid is None:
            return
        m0 = QPointF(*mid)
        axis = self.modal["axis"] if self.modal else None
        if axis:
            a = np.array(self.AXES[axis])
            seg = seen.segment(o - a * self.p.H * 6, o + a * self.p.H * 6)
            if seg is not None:
                p.setPen(QPen(self.COLORS[axis], 1.0 * k, Qt.DashLine))
                p.drawLine(QPointF(*seg[0]), QPointF(*seg[1]))
        if self.modal is not None:
            return
        for name, (_tip, at) in self.arrows(seen, o, k).items():
            if at is None:
                continue
            tip = QPointF(*at)
            p.setPen(QPen(self.COLORS[name], 2.0 * k))
            p.drawLine(m0, tip)
            p.setBrush(self.COLORS[name])
            p.drawRect(QRectF(tip.x() - 4 * k, tip.y() - 4 * k, 8 * k, 8 * k))
        p.setPen(QPen(QColor(255, 255, 255), 1.5 * k))
        p.setBrush(QColor(255, 255, 255, 90))
        p.drawEllipse(m0, 6 * k, 6 * k)
        p.setBrush(Qt.NoBrush)

    def _paint_camera(self, p, k, seen):
        real = self.scene_camera()
        if not camera.on(real):
            return
        c, corners, tg = camera.frustum(real, self.time(), self.p.W, self.p.H)

        color = SELECTED_COLOR if self.sel_cam == "camera" else CAMERA_COLOR

        def line(a, b, width=1.25):
            seg = seen.segment(a, b)
            if seg is not None:
                p.setPen(QPen(color, width * k))
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
            p.setPen(QPen(SELECTED_COLOR if self.sel_cam == "target" else CAMERA_COLOR, 1.5 * k))
            p.drawEllipse(QPointF(*at), 5 * k, 5 * k)
