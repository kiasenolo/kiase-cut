"""The GPU compositor (glrender.py) draws what the CPU renderer (render.py) draws.

Every scene is rendered by both and compared: on average within a couple of levels, and
with only a sliver of pixels (anti-aliased edges, feathers) further apart. Skipped when this
computer has no OpenGL 3.3.
"""
import copy
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QRadialGradient  # noqa: E402

from kiasecut import fx, glrender, project, render  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])
S = 1_000_000
W, H = 320, 180

try:
    glrender.GL().ctx.release()
    HAVE_GL = True
except Exception:                                    # no OpenGL 3.3 / moderngl here
    HAVE_GL = False


def pixels(img):
    im = img.convertToFormat(QImage.Format_RGBA8888)
    return np.frombuffer(bytes(im.constBits()), np.uint8).reshape(im.height(), im.width(), 4)[..., :3].astype(int)


def tf(**kw):
    t = {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}
    t.update(kw)
    return t


@unittest.skipUnless(HAVE_GL, "needs OpenGL 3.3")
class GpuMatchesCpu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        grad = QImage(400, 225, QImage.Format_ARGB32_Premultiplied)
        p = QPainter(grad)
        g = QLinearGradient(0, 0, 400, 225)
        g.setColorAt(0, QColor("#1d4fd8"))
        g.setColorAt(0.5, QColor("#f5f5f5"))
        g.setColorAt(1, QColor("#e8590c"))
        p.fillRect(grad.rect(), g)
        p.setBrush(QColor("#2b8a3e"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(120, 110), 60, 60)
        p.end()
        cls.grad = os.path.join(cls.dir, "grad.png")
        grad.save(cls.grad)
        spot = QImage(200, 200, QImage.Format_ARGB32_Premultiplied)    # see-through edges
        spot.fill(Qt.transparent)
        p = QPainter(spot)
        r = QRadialGradient(QPointF(100, 100), 100)
        r.setColorAt(0, QColor(255, 220, 40, 255))
        r.setColorAt(1, QColor(255, 220, 40, 0))
        p.fillRect(spot.rect(), r)
        p.end()
        cls.spot = os.path.join(cls.dir, "spot.png")
        spot.save(cls.spot)
        cls.svg = os.path.join(cls.dir, "s.svg")
        with open(cls.svg, "w", encoding="utf-8") as fh:
            fh.write('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect x="10" y="10" '
                     'width="80" height="80" rx="20" fill="#7048e8"/></svg>')
        cls.cpu, cls.gpu = render.Renderer(), glrender.GLRenderer()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def pic(self, cid, path, w, h, **kw):
        c = {"id": cid, "type": "image", "name": cid, "start_us": 0, "duration_us": 2 * S, "source_start_us": 0,
             "media": {"path": path, "width": w, "height": h}, "transform": tf()}
        c.update(kw)
        return c

    def bg(self, **kw):
        return self.pic("bg", self.grad, 400, 225, **kw)

    def top(self, **kw):
        return self.pic("top", self.spot, 200, 200, **kw)

    def view(self, *layers, t=0):
        tracks = [{"id": f"t{i}", "kind": "video", "name": f"v{i}", "clips": list(cl)} for i, cl in enumerate(layers)]
        return {"width": 640, "height": 360, "fps": 30, "duration_us": 2 * S, "tracks": tracks}

    def check(self, name, view, frame=0, mean_max=2.0, far_max=0.01):
        a = pixels(self.cpu.render(copy.deepcopy(view), frame, W, H))
        b = pixels(self.gpu.render(copy.deepcopy(view), frame, W, H))
        d = np.abs(a - b).max(axis=2)
        mean, far = float(np.abs(a - b).mean()), float((d > 48).mean())
        self.assertEqual(self.cpu.errors + self.gpu.errors, [], name)
        self.assertLessEqual(mean, mean_max, f"{name}: mean difference {mean:.2f}")
        self.assertLessEqual(far, far_max, f"{name}: {far:.2%} of pixels differ a lot")
        return mean, far

    def test_pictures_and_transforms(self):
        self.check("plain", self.view([self.bg()]))
        self.check("moved", self.view([self.bg(transform=tf(x=0.3, y=-0.2, scale=0.6, rotation=33, opacity=0.7))]))
        self.check("flipped", self.view([self.bg(transform=dict(tf(scale=0.8, rotation=-20), flip_h=True))]))
        self.check("stretched", self.view([self.bg(transform=dict(tf(scale=0.5), scale_y=1.2))]))
        self.check("see-through", self.view([self.bg()], [self.top(transform=tf(scale=0.7, x=-0.3, opacity=0.8))]))
        self.check("svg", self.view([self.bg()], [self.pic("s", self.svg, 100, 100, transform=tf(scale=0.5))]))

    def test_a_camera_draws_the_clips_as_planes_in_space_the_same_by_both(self):
        cam = {"on": True}
        plain = self.view([self.bg()], [self.top(transform=tf(scale=0.6, x=-0.2))])
        seen = dict(plain, camera=cam)
        self.check("default camera", seen)                               # (the z = 0 plane fills the picture: nothing changes)
        for r in (self.cpu, self.gpu):
            a, b = pixels(r.render(copy.deepcopy(plain), 0, W, H)), pixels(r.render(copy.deepcopy(seen), 0, W, H))
            self.assertLess(float(np.abs(a - b).mean()), 2.0)
        turned = self.view([self.bg()], [self.top(transform=dict(tf(scale=0.8, x=0.1), rot_y=55, z=-0.3))])
        turned["camera"] = dict(cam, fov=60)
        self.check("turned", turned, mean_max=3.0, far_max=0.02)
        moved = dict(plain, camera={"on": True, "x": 0.4, "tx": 0.0})
        self.check("camera moved", moved, mean_max=3.0, far_max=0.02)
        for r in (self.cpu, self.gpu):                                   # (it does look different from the flat one)
            a, b = pixels(r.render(copy.deepcopy(plain), 0, W, H)), pixels(r.render(copy.deepcopy(turned), 0, W, H))
            self.assertGreater(float(np.abs(a - b).mean()), 3.0)

    def test_a_camera_object_is_what_the_scene_is_seen_with(self):
        plain = self.view([self.bg()], [self.top(transform=tf(scale=0.6, x=-0.2))])
        own = dict(plain, camera={"on": True, "x": 0.4, "tx": 0.3})
        obj = {"id": "cam", "type": "image", "name": "相機", "start_us": 0, "duration_us": 2 * S, "source_start_us": 0,
               "camera": {"fov": 40.0, "tx": 0.3, "ty": 0.0, "tz": 0.0, "aperture": 0.0}, "transform": tf(x=0.4, z=-2.7474774)}
        mine = copy.deepcopy(plain)                                                     # (no camera on the level: the object alone makes it a scene)
        mine["tracks"].append({"id": "tc", "kind": "video", "name": "c", "clips": [obj]})
        for r in (self.cpu, self.gpu):
            a, b = pixels(r.render(copy.deepcopy(own), 0, W, H)), pixels(r.render(copy.deepcopy(mine), 0, W, H))
            self.assertLess(float(np.abs(a - b).mean()), 0.8)
            self.assertEqual(r.errors, [])
        flat = pixels(self.gpu.render(copy.deepcopy(dict(plain, camera={"on": True})), 0, W, H))
        self.assertGreater(float(np.abs(flat - pixels(self.gpu.render(copy.deepcopy(mine), 0, W, H))).mean()), 3.0)     # (it does look different)
        later = copy.deepcopy(mine)                                                     # (not playing yet: the scene's own camera)
        later["tracks"][-1]["clips"][0]["start_us"] = S
        for r in (self.cpu, self.gpu):
            own_flat = pixels(r.render(copy.deepcopy(dict(plain, camera={"on": True})), 0, W, H))
            self.assertLess(float(np.abs(own_flat - pixels(r.render(copy.deepcopy(later), 0, W, H))).mean()), 0.3)

    def test_particles_in_a_scene_are_drawn_through_its_camera(self):
        from kiasecut import assets
        p = assets.make(assets.get("particle.system"), "#ffffff", "#000000", 640, 360)
        p.update(pt_count=1, pt_speed=0.0, pt_gravity=0.0, pt_drag=0.0, pt_life=30.0, pt_life_var=0.0, pt_size=120.0, pt_size_var=0.0,
                 pt_size_end=1.0, pt_fade_in=0.0, pt_fade_out=0.0, pt_look="實心圓", pt_glow=0.0, pt_origin_x=0.5, pt_origin_y=0.5)
        p = assets.normalize(p)

        def clip(**t):
            c = self.pic("pt", self.spot, 640, 360, transform=tf(**t))
            c["asset"] = p
            c["start_us"], c["duration_us"] = 0, 2 * S
            return c

        def lit(cam, **t):
            v = self.view([clip(**t)])
            v["camera"] = cam
            img = pixels(self.gpu.render(v, 30, W, H))
            self.assertEqual(self.gpu.errors, [])
            ys, xs = np.nonzero(img.max(axis=2) > 128)
            return len(xs), (float(xs.mean()) if len(xs) else None)
        n0, x0 = lit({"on": True})
        self.assertGreater(n0, 50)
        self.assertAlmostEqual(x0, W / 2, delta=3)
        far, _x = lit({"on": True}, z=1.5)                                  # (farther: smaller)
        self.assertLess(far, n0 * 0.5)
        _n, xs = lit({"on": True, "x": 0.5, "tx": 0.5}, z=0.0)             # (the camera slid right: it is left of the middle)
        self.assertLess(xs, x0 - 20)
        self.assertEqual(lit({"on": True}, z=-5.0)[0], 0)                   # (behind the camera)

    def test_a_particle_is_behind_or_in_front_of_a_plane_by_its_own_depth(self):
        from kiasecut import assets
        p = assets.make(assets.get("particle.system"), "#ffffff", "#000000", 640, 360)
        p.update(pt_count=1, pt_speed=0.0, pt_gravity=0.0, pt_drag=0.0, pt_life=30.0, pt_life_var=0.0, pt_size=120.0, pt_size_var=0.0,
                 pt_size_end=1.0, pt_fade_in=0.0, pt_fade_out=0.0, pt_look="實心圓", pt_glow=0.0, pt_origin_x=0.5, pt_origin_y=0.5,
                 pt_depth_on=True, pt_color=[1.0, 1.0, 1.0, 1.0])
        shot = {}
        for name, oz in (("behind", 600.0), ("front", -400.0)):
            q = assets.normalize(dict(p, pt_origin_z=oz))
            c = self.pic("pt", self.spot, 640, 360, transform=tf())             # (the system's own plane is at the same depth as the picture's)
            c["asset"], c["start_us"], c["duration_us"] = q, 0, 2 * S
            v = self.view([self.bg(transform=tf(scale=3.0))], [c])
            v["camera"] = {"on": True}
            shot[name] = pixels(self.gpu.render(v, 30, W, H))
            self.assertEqual(self.gpu.errors, [])
        v = self.view([self.bg(transform=tf(scale=3.0))])
        v["camera"] = {"on": True}
        plain = pixels(self.gpu.render(v, 0, W, H))
        mid = (H // 2, W // 2)
        self.assertLess(int(np.abs(shot["behind"][mid] - plain[mid]).max()), 12)       # (behind the picture: hidden)
        self.assertGreater(int(np.abs(shot["front"][mid] - plain[mid]).max()), 25)     # (in front of it: drawn)

    def test_a_solid_text_stands_where_the_flat_one_does_and_has_sides_when_turned(self):
        def shot(solid, camera=True, depth=150.0, **t):
            c = {"id": "tx", "type": "text", "name": "t", "start_us": 0, "duration_us": 2 * S, "source_start_us": 0, "transform": tf(**t),
                 "text": {"content": "KIASE", "size": 20.0, "color": [1.0, 1.0, 1.0], "align": "center", "stroke_on": False}}
            if solid:
                c["solid"] = {"on": True, "depth": depth, "bevel": 0.0}
            v = self.view([c])
            if camera:
                v["camera"] = {"on": True}
            img = pixels(self.gpu.render(v, 0, W, H))
            self.assertEqual(self.gpu.errors, [])
            return img.max(axis=2) > 100
        flat, solid = shot(False), shot(True, depth=0.0)
        self.assertGreater(int(flat.sum()), 200)
        both, either = int((flat & solid).sum()), int((flat | solid).sum())
        self.assertGreater(both / either, 0.8)                                    # (the same letters in the same place: only their anti-aliased edges differ)
        turned = shot(True, rot_y=50)
        thin = shot(False, rot_y=50)
        self.assertGreater(int(turned.sum()), int(thin.sum()) * 1.2)              # (its sides show)
        self.assertEqual(int((shot(True, camera=False) ^ shot(False, camera=False)).sum()), 0)    # (outside a scene it is the flat text)

    def test_a_filter_clip_in_a_scene_works_on_what_is_under_it(self):
        e = fx.new_effect("builtin:blur", "e1")
        e["params"].update(radius=30.0)
        flt = {"id": "f", "type": "filter", "name": "f", "start_us": 0, "duration_us": 2 * S, "source_start_us": 0, "effects": [e]}
        edge = lambda img: float((np.diff(img.astype(float), n=2, axis=1) ** 2).sum())
        for r in (self.cpu, self.gpu):
            v = self.view([self.top(transform=tf(scale=0.5))], [flt])
            v["camera"] = {"on": True}
            plain = self.view([self.top(transform=tf(scale=0.5))])
            plain["camera"] = {"on": True}
            self.assertLess(edge(pixels(r.render(v, 0, W, H))), 0.9 * edge(pixels(r.render(plain, 0, W, H))))
            self.assertEqual(r.errors, [])

    def solid_text(self, cid="tx", color=(1.0, 0.0, 1.0), depth=20.0, advanced=False, **t):
        return {"id": cid, "type": "text", "name": cid, "start_us": 0, "duration_us": 2 * S, "source_start_us": 0, "transform": tf(**t),
                "text": {"content": "MMMMMM", "size": 22.0, "color": list(color), "align": "center", "stroke_on": False},
                "solid": {"on": True, "depth": depth, "bevel": 0.0, "advanced": advanced}}

    def scene_shot(self, *layers):
        v = self.view(*[[c] for c in layers])
        v["camera"] = {"on": True}
        img = pixels(self.gpu.render(v, 0, W, H))
        self.assertEqual(self.gpu.errors, [])
        return img

    def test_a_plane_cuts_through_a_solid_by_the_pixel_whatever_their_order(self):
        magenta = lambda img: (img[..., 0] > 180) & (img[..., 2] > 180) & (img[..., 1] < 70)
        alone = magenta(self.scene_shot(self.solid_text()))
        self.assertGreater(int(alone[:, :W // 2].sum()), 150)
        wall = self.bg(transform=dict(tf(scale=1.4), rot_y=50))                   # (its left edge comes nearer, its right goes away)
        for layers in ((wall, self.solid_text()), (self.solid_text(), wall)):
            got = magenta(self.scene_shot(*layers))
            self.assertLess(int(got[:, :W // 2 - 4].sum()), 0.1 * alone[:, :W // 2 - 4].sum())     # (behind the picture: hidden)
            self.assertGreater(int(got[:, W // 2 + 4:].sum()), 0.9 * alone[:, W // 2 + 4:].sum())   # (in front of it: drawn)

    def test_solids_cut_through_each_other_and_a_see_through_one_shows_what_is_behind(self):
        a, b = self.solid_text("a", (1.0, 0.0, 0.0), rot_y=40), self.solid_text("b", (0.0, 0.0, 1.0), rot_y=-40)
        img = self.scene_shot(a, b)
        red = (img[..., 0] > 150) & (img[..., 2] < 80)
        blue = (img[..., 2] > 150) & (img[..., 0] < 80)
        self.assertGreater(int(red[:, :W // 2].sum()), 4 * int(blue[:, :W // 2].sum()))     # (a's left half is the nearer there, b's right)
        self.assertGreater(int(blue[:, W // 2:].sum()), 4 * int(red[:, W // 2:].sum()))
        faded = self.scene_shot(self.bg(transform=tf(scale=3.0, z=1.0)), self.solid_text(opacity=0.5))
        solid = self.scene_shot(self.bg(transform=tf(scale=3.0, z=1.0)), self.solid_text())
        self.assertGreater(int((np.abs(faded - solid).max(axis=2) > 40).sum()), 200)

    def test_simple_shading_shows_the_picked_colour_and_advanced_lighting_is_a_choice(self):
        simple = self.scene_shot(self.solid_text(color=(0.8, 0.4, 0.2), z=0.03))
        lit = self.scene_shot(self.solid_text(color=(0.8, 0.4, 0.2), z=0.03, advanced=True))
        hit = np.abs(simple - np.array([204, 102, 51])).max(axis=2) <= 2
        self.assertGreater(int(hit.sum()), 300)                                    # (the faces: exactly the picked colour)
        self.assertGreater(float(np.abs(simple - lit)[hit].mean()), 3.0)

    def test_basic_solids_and_shapes_are_solids_in_a_scene(self):
        from kiasecut import assets, mesh
        def thing(params, solid, **t):
            return {"id": "o", "type": "image", "name": "o", "start_us": 0, "duration_us": 2 * S, "source_start_us": 0, "transform": tf(**t),
                    "media": {"path": "o.png", "width": 100, "height": 100}, "asset": assets.normalize(params), "solid": solid}
        green = lambda img: int(((img[..., 1] > 90) & (img[..., 0] < 60) & (img[..., 2] < 60)).sum())
        box = {"family": "empty", "w": 400, "h": 400, "color": "#00ff00"}
        for kind in mesh.PRIMITIVES:
            got = self.scene_shot(thing(box, {"on": True, "prim": kind, "depth": 100.0, "bevel": 0.0}))
            self.assertGreater(green(got), 200, kind)
        star = {"family": "star", "w": 500, "h": 500, "color": "#00ff00", "points": 5, "inner": 40, "fill": True}
        flat = green(self.scene_shot(thing(star, {"on": False})))
        edge = lambda on: green(self.scene_shot(thing(star, {"on": on, "depth": 300.0, "bevel": 0.0}, rot_y=90)))
        self.assertGreater(flat, 100)
        self.assertGreater(edge(True), edge(False) + 100)                       # (seen from the side: flat is a line, solid has sides)

    def test_a_picture_or_video_on_a_solid_and_an_imported_model(self):
        import tempfile
        from kiasecut import assets, models
        def thing(solid, color="#808080"):
            return {"id": "o", "type": "image", "name": "o", "start_us": 0, "duration_us": 2 * S, "source_start_us": 0, "transform": tf(),
                    "media": {"path": "o.png", "width": 100, "height": 100},
                    "asset": assets.normalize({"family": "empty", "w": 700, "h": 700, "color": color}), "solid": solid}
        of = lambda img, rgb: (np.abs(img[..., :3].astype(int) - rgb).max(axis=2) < 60)
        def where(mask):
            ys, xs = np.nonzero(mask)
            self.assertGreater(len(ys), 100)
            return xs.mean(), ys.mean()
        with tempfile.TemporaryDirectory() as d:
            pic = QImage(64, 64, QImage.Format_ARGB32)                          # (green over blue, red on the left)
            pic.fill(QColor(0, 255, 0))
            painter = QPainter(pic)
            painter.fillRect(0, 32, 64, 32, QColor(0, 0, 255))
            painter.fillRect(0, 0, 20, 64, QColor(255, 0, 0))
            painter.end()
            pic.save(os.path.join(d, "p.png"))
            info = {"kind": "image", "width": 64, "height": 64}
            cube = {"on": True, "prim": "cube", "depth": 100.0, "bevel": 0.0, "surface": os.path.join(d, "p.png"), "surface_info": info}
            img = self.scene_shot(thing(cube))
            (rx, _), (_, gy), (_, by) = where(of(img, (255, 0, 0))), where(of(img, (0, 255, 0))), where(of(img, (0, 0, 255)))
            self.assertLess(rx, W / 2 - 5)                                      # (the right way round)
            self.assertLess(gy, by - 10)                                        # (and the right way up)
            # a video: the frame at the clip's time, from its start again when it is over
            asked = []
            def frame(path, t_us, w, h):
                asked.append(t_us)
                one = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
                one.fill(QColor(255, 255, 0))
                return one
            held, self.gpu.video_frame = self.gpu.video_frame, frame
            try:
                moving = dict(cube, surface="v.mp4", surface_info={"kind": "video", "width": 64, "height": 64, "duration_us": S // 2})
                v = self.view([thing(moving)])
                v["camera"] = {"on": True}
                got = pixels(self.gpu.render(v, 24, W, H))                 # (frame 24: 0.8 s)
            finally:
                self.gpu.video_frame = held
            self.assertEqual(self.gpu.errors, [])
            self.assertGreater(int(of(got, (255, 255, 0)).sum()), 500)
            self.assertAlmostEqual(asked[-1] / S, 0.3, 1)
            # an OBJ with a textured face, kept as one file: its texture shows after the files it was read from are gone
            with open(os.path.join(d, "m.mtl"), "w") as f:
                f.write("newmtl t\nKd 1 1 1\nmap_Kd p.png\n")
            with open(os.path.join(d, "m.obj"), "w") as f:
                f.write("mtllib m.mtl\nv -1 -1 0\nv 1 -1 0\nv 1 1 0\nv -1 1 0\nvt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\n"
                        "usemtl t\nf 1/1 2/2 3/3 4/4\n")
            kept, size = models.convert(os.path.join(d, "m.obj"), os.path.join(d, "kept"))
            self.assertEqual([round(x, 3) for x in size], [1.0, 1.0, 0.0])
            for name in ("m.obj", "m.mtl", "p.png"):
                os.remove(os.path.join(d, name))
            img = self.scene_shot(thing({"on": True, "prim": "model", "model": kept, "depth": 1.0}, "#ffffff"))
            (rx, _), (_, gy), (_, by) = where(of(img, (255, 0, 0))), where(of(img, (0, 255, 0))), where(of(img, (0, 0, 255)))
            self.assertLess(rx, W / 2 - 5)
            self.assertLess(gy, by - 10)

    def test_lights_cast_shadows_from_planes_and_solids_onto_both(self):
        from kiasecut import assets, camera
        def rect(cid, color, w, h, shade=None, **t):
            p = assets.make(assets.get("shape.rect"), color, "#000000", 640, 360)
            p.update(w=w, h=h)
            c = {"id": cid, "type": "image", "name": cid, "start_us": 0, "duration_us": 2 * S, "source_start_us": 0, "transform": tf(**t),
                 "media": {"path": cid + ".png", "width": 100, "height": 100}, "asset": assets.normalize(p)}
            if shade is not None:
                c["shade"] = shade
            return c
        def ball(shade=None):
            c = rect("ball", "#ff0000", 70, 70, shade, x=0.0, y=0.0, z=-0.2)
            c["asset"] = assets.normalize({"family": "empty", "w": 90, "h": 90, "color": "#ff0000"})
            c["solid"] = {"on": True, "prim": "sphere", "depth": 270.0, "bevel": 0.0, "advanced": False}
            return c
        def sun(shadow=True, soft=0.0):                                   # (from the left: what it shades is to the right)
            lamp = self.lamp("l", "sun", 100.0, **camera.looking(np.zeros(3), np.array([0.6, 0.0, 0.8])))
            lamp["light"].update(shadow=shadow, darkness=80.0, softness=soft)
            return lamp
        wall = lambda shade=None: rect("wall", "#c0c0c0", 600, 340, shade, z=0.8)
        dark = lambda img: (img[..., :3].max(axis=2) > 20) & (img[..., :3].max(axis=2) < 90) & (np.ptp(img[..., :3], axis=2) < 20)
        lit = self.scene_shot(wall(), ball(), sun(False))
        self.assertLess(int(dark(lit).sum()), 20)
        got = self.scene_shot(wall(), ball(), sun())
        ys, xs = np.nonzero(dark(got))
        self.assertGreater(len(xs), 150)                                        # (the ball's shadow on the wall ...)
        self.assertGreater(float(xs.mean()), W / 2 + 10)                        # (... away from the light)
        corner = np.abs(got[40:60, 60:90].astype(int) - lit[40:60, 60:90])
        self.assertEqual(int(corner.max()), 0)                                  # (a plane does not shade itself)
        for off in ((wall({"receive": False}), ball()), (wall(), ball({"cast": False}))):
            self.assertLess(int(dark(self.scene_shot(*off, sun())).sum()), 20)
        # a plane's shadow, where its picture is (not its whole layer), on another plane
        card = rect("card", "#00ff00", 90, 90, z=-0.1)
        got = self.scene_shot(wall(), card, sun())
        ys, xs = np.nonzero(dark(got))
        self.assertGreater(len(xs), 150)
        self.assertLess(len(xs), 0.2 * W * H)
        self.assertGreater(float(xs.mean()), W / 2 + 10)
        # on a solid: a card between the light and the ball
        screen = rect("screen", "#0000ff", 200, 340, x=-0.55, z=-0.8)
        red = lambda img: float(img[..., 0][(img[..., 0] > 20) & (img[..., 1] < 40) & (img[..., 2] < 40)].mean())
        self.assertLess(red(self.scene_shot(ball(), screen, sun())), red(self.scene_shot(ball(), screen, sun(False))) - 20)
        # a soft edge has shades between
        between = lambda img: int(((img[..., 0] > 70) & (img[..., 0] < 150) & (np.ptp(img[..., :3], axis=2) < 40)).sum())
        self.assertGreater(between(self.scene_shot(wall(), card, sun(soft=60.0))), between(got) + 200)
        # a point light casts from its place
        lamp = self.lamp("p", "point", 100.0, x=-0.7, y=0.0, z=-1.2)
        lamp["light"].update(shadow=True, darkness=80.0, softness=0.0)
        ys, xs = np.nonzero(dark(self.scene_shot(wall(), card, lamp)))
        self.assertGreater(len(xs), 150)
        self.assertGreater(float(xs.mean()), W / 2 + 10)

    def lamp(self, cid, kind, power=100.0, color=(1.0, 1.0, 1.0), **t):
        from kiasecut import lights
        return {"id": cid, "type": "image", "name": cid, "start_us": 0, "duration_us": 2 * S, "source_start_us": 0,
                "light": {"kind": kind, "power": power, "color": list(color)}, "transform": dict(tf(**dict(lights.new_transform(kind), **t)))}

    def test_light_objects_light_the_advanced_solids_instead_of_the_scenes_own_lamps(self):
        word = lambda adv=True: self.solid_text(color=(0.8, 0.8, 0.8), z=0.03, advanced=adv)
        own = self.scene_shot(word())
        face = own.max(axis=2) > 60
        self.assertGreater(int(face.sum()), 300)
        level = lambda img: float(img[face].mean())
        red = self.scene_shot(word(), self.lamp("l", "sun", 150.0, (1.0, 0.0, 0.0)))
        self.assertGreater(float(red[face][:, 0].mean()), float(red[face][:, 2].mean()) + 20)           # (lit red)
        dim = self.scene_shot(word(), self.lamp("l", "sun", 0.0), self.lamp("a", "ambient", 0.0))
        self.assertLess(level(dim), 0.6 * level(own))
        bright = self.scene_shot(word(), self.lamp("l", "sun", 0.0), self.lamp("a", "ambient", 300.0))
        self.assertGreater(level(bright), level(dim) + 40)
        point = lambda z: level(self.scene_shot(word(), self.lamp("l", "point", 100.0, x=0.0, y=0.0, z=z), self.lamp("a", "ambient", 0.0)))
        self.assertGreater(point(-1.5), point(-6.0) + 20)                                               # (farther: weaker)
        later = self.lamp("l", "sun", 150.0, (1.0, 0.0, 0.0))
        later["start_us"] = S
        self.assertEqual(int(np.abs(self.scene_shot(word(), later) - own).max()), 0)                   # (not playing: the scene's own lamps)
        simple = self.scene_shot(word(False))
        self.assertEqual(int(np.abs(self.scene_shot(word(False), self.lamp("l", "sun", 150.0, (1.0, 0.0, 0.0))) - simple).max()), 0)

    def test_depth_of_field_blurs_what_is_out_of_focus_the_same_by_both(self):
        near, far = self.bg(transform=tf(scale=0.5, x=-0.4)), self.bg(transform=tf(scale=0.5, x=0.4, z=1.5))
        v = self.view([near, far])
        v["camera"] = {"on": True, "aperture": 0.0}
        sharp = copy.deepcopy(v)
        v["camera"] = {"on": True, "aperture": 6.0}
        self.check("dof", v, mean_max=3.0, far_max=0.03)
        edge = lambda img, x0, x1: float((np.diff(img[:, x0:x1].astype(float), n=2, axis=1) ** 2).sum())
        for r in (self.cpu, self.gpu):
            a, b = pixels(r.render(copy.deepcopy(sharp), 0, W, H)), pixels(r.render(copy.deepcopy(v), 0, W, H))
            self.assertLess(edge(b, W // 2, W), 0.8 * edge(a, W // 2, W))          # (the far one, on the right, is softer)
            self.assertAlmostEqual(edge(b, 0, W // 2), edge(a, 0, W // 2), delta=0.05 * edge(a, 0, W // 2))   # (the one in focus is as it was)

    def test_a_nearer_clip_is_drawn_over_a_farther_one_whatever_their_order(self):
        far = self.bg(transform=tf(scale=0.4, z=0.5))
        near = self.top(transform=tf(scale=0.5, z=-0.3))
        for order in ([[far], [near]], [[near], [far]]):
            v = self.view(*order)
            v["camera"] = {"on": True}
            for r in (self.cpu, self.gpu):
                img = pixels(r.render(copy.deepcopy(v), 0, W, H))
                yellow = img[H // 2, W // 2]
                self.assertGreater(yellow[0], 200)                         # (the yellow spot's middle, not the bg's)
                self.assertGreater(yellow[1], 150)
                self.assertLess(yellow[2], 120)

    def test_a_shadow_is_drawn_under_the_clip_and_the_same_by_both(self):
        shadow = dict(shadow_on=True, shadow_x=20.0, shadow_y=20.0, shadow_blur=6.0, shadow_opacity=1.0, shadow_color=[1.0, 0.0, 0.0])
        view = self.view([self.bg()], [self.top(transform=dict(tf(scale=0.5), **shadow))])
        plain = self.view([self.bg()], [self.top(transform=tf(scale=0.5))])
        self.check("shadow", view)
        for r in (self.cpu, self.gpu):
            a, b = pixels(r.render(copy.deepcopy(view), 0, W, H)), pixels(r.render(copy.deepcopy(plain), 0, W, H))
            self.assertGreater(int((np.abs(a - b).max(axis=2) > 20).sum()), 500)
        wide = self.view([self.bg()], [self.top(transform=dict(tf(scale=0.5), **dict(shadow, shadow_spread=12.0)))])
        self.check("spread", wide)
        for r in (self.cpu, self.gpu):                                   # (a grown shadow covers more)
            n = lambda v: int((np.abs(pixels(r.render(copy.deepcopy(v), 0, W, H)) - pixels(r.render(copy.deepcopy(plain), 0, W, H))).max(axis=2) > 20).sum())
            self.assertGreater(n(wide), n(view) + 300)

    def test_a_region_is_the_same_part_of_the_whole_picture(self):
        view = self.view([self.bg(transform=tf(x=0.2, scale=0.8, rotation=15))], [self.top(transform=tf(scale=0.5, x=-0.3))])
        region = (0.25, 0.1, 0.75, 0.6)
        for name, r in (("cpu", self.cpu), ("gpu", self.gpu)):
            whole = r.render(copy.deepcopy(view), 0, W, H)
            part = r.render(copy.deepcopy(view), 0, W, H, region=region)
            self.assertEqual((part.width(), part.height()), (round(0.5 * W), round(0.5 * H)), name)
            self.assertEqual(part.text("rect"), repr(region), name)
            crop = whole.copy(round(0.25 * W), round(0.1 * H), part.width(), part.height())
            self.assertLessEqual(float(np.abs(pixels(crop) - pixels(part)).mean()), 1.0, name)

    def test_a_margin_draws_what_is_outside_the_canvas_round_it(self):
        view = self.view([self.bg(transform=tf(x=0.3, scale=1.4))])                  # (runs over the canvas on the right and the top and bottom)
        for name, r in (("cpu", self.cpu), ("gpu", self.gpu)):
            plain = r.render(copy.deepcopy(view), 0, W, H)
            wide = r.render(copy.deepcopy(view), 0, W, H, margin=0.5)
            self.assertEqual((wide.width(), wide.height()), (2 * W, 2 * H), name)
            inner = pixels(wide.copy(W // 2, H // 2, W, H))
            self.assertLessEqual(float(np.abs(inner - pixels(plain)).mean()), 1.0, name)      # (the canvas is where it was, in the middle)
            outside = pixels(wide.copy(W // 2 + W, H // 2, W // 2, H))                        # (right of the canvas)
            self.assertGreater(float(outside.mean()), 20.0, name)                              # (the picture goes on there)
        self.assertEqual(self.gpu.render(copy.deepcopy(view), 0, W, H, margin=0.0).width(), W)

    def test_blend_modes(self):
        for mode in glrender.BLEND_INDEX:
            self.check(f"blend {mode}", self.view([self.bg()], [self.top(blend=mode, transform=tf(scale=0.9))]))

    def test_masks(self):
        for kind in ("line", "mirror", "circle", "rectangle"):
            for feather, invert, rot in ((0.0, False, 0.0), (0.3, True, 25.0)):
                mask = {"kind": kind, "invert": invert, "cx": 0.2, "cy": -0.1, "w": 0.6, "h": 0.5,
                        "rotation": rot, "feather": feather}
                self.check(f"mask {kind} {feather} {invert}",
                           self.view([self.top(transform=tf(scale=1.2))], [self.bg(mask=mask, transform=tf(rotation=10))]))

    def test_a_big_filter_in_a_node_graph_draws_without_an_error(self):
        """A filter long enough to be compiled first through ctypes (fx.BIG: Noise Texture) leaves this renderer's context
        current: a nested `with ctx` let go of an EGL context as it ended, and every program and texture after it failed."""
        self.assertGreater(len(fx.get("builtin:nodes/tex_noise").code), fx.BIG)
        g = {"nodes": {"input": {"type": "input"}, "output": {"type": "output"},
                       "noise": {"type": "filter", "ref": "builtin:nodes/tex_noise"}, "mix": {"type": "filter", "ref": "builtin:nodes/mix"}},
             "links": [{"from": "input", "to": "mix", "socket": "src"}, {"from": "noise", "to": "mix", "socket": "b"},
                       {"from": "mix", "to": "output", "socket": "src"}]}
        r = glrender.GLRenderer()
        try:
            fx.compiled.clear()
            r.render(self.view([self.bg(effects=[{"id": "e1", "filter": fx.GRAPH, "enabled": True, "params": {"mix.fac": 0.5}, "graph": g}])]),
                     0, W, H)
            self.assertEqual(r.errors, [])
        finally:
            r.gl.ctx.release()

    def test_text(self):
        if not project.DEFAULT_FONT:
            self.skipTest("no default font")
        text = {"id": "tx", "type": "text", "name": "tx", "start_us": 0, "duration_us": 2 * S, "source_start_us": 0,
                "text": {"content": "KiaseCut 剪輯", "font_path": project.DEFAULT_FONT, "size": 12.0,
                         "color": [1.0, 0.9, 0.2], "letter_spacing": 0.0, "line_spacing": 0.0, "italic_deg": 0},
                "transform": tf(y=0.3, rotation=-8)}
        self.check("text", self.view([self.bg()], [text]), mean_max=2.5, far_max=0.02)
        text["mask"] = {"kind": "circle", "invert": False, "cx": 0.2, "cy": 0.0, "w": 0.5, "h": 1.5,
                        "rotation": 15.0, "feather": 0.2}
        self.check("masked text", self.view([self.bg()], [text]), mean_max=2.5, far_max=0.02)
        text["text"]["box_w"] = 40.0
        self.check("masked boxed text", self.view([self.bg()], [text]), mean_max=2.5, far_max=0.02)

    def test_zero_scale_and_font_size(self):
        """縮放 0 and 字號 0 draw nothing, without an error, on both renderers."""
        text = {"id": "tx", "type": "text", "name": "tx", "start_us": 0, "duration_us": 2 * S, "source_start_us": 0,
                "text": {"content": "KiaseCut", "font_path": project.DEFAULT_FONT, "size": 0.0}, "transform": tf()}
        for name, layer in (("scale 0", self.top(transform=dict(tf(scale=0.0), scale_y=0.0))),
                            ("scale x 0", self.top(transform=dict(tf(scale=0.0), scale_y=1.0))),
                            ("font size 0", text)):
            self.check(name, self.view([self.bg()], [layer]))
            self.check(name + " alone", self.view([layer]))

    def compound(self, static=False):
        comp = {"name": "k", "width": 640, "height": 360, "duration_us": 2 * S,
                "tracks": [{"id": "i0", "kind": "video", "name": "v", "clips": [self.bg(transform=tf(scale=0.7))]},
                           {"id": "i1", "kind": "video", "name": "v", "clips": [self.top(transform=tf(x=0.4))]}]}
        if static:
            comp["static"] = True
        return {"id": "k", "type": "compound", "name": "k", "start_us": 0, "duration_us": 2 * S, "source_start_us": 0,
                "compound_id": "k1", "compound": comp, "transform": tf(scale=1.4, rotation=12, x=0.1, opacity=0.9)}

    def test_a_static_clip_reads_the_time_when_asked(self):
        clip = self.compound(static=True)
        clip["duration_us"] = 30 * S                                                        # (longer than the 2 s its layers last)
        clip["compound"]["tracks"][0]["clips"][0]["effects"] = [fx.new_effect("builtin:hue_cycle", "e9")]
        for r in (self.cpu, self.gpu):
            def at(frame, live):
                c = copy.deepcopy(clip)
                c["static_live"] = live
                return pixels(r.render(self.view([self.top()], [c]), frame, W, H))
            self.assertEqual(float(np.abs(at(0, False) - at(30, False)).mean()), 0.0)       # (a still: the same at any time)
            self.assertGreater(float(np.abs(at(0, True) - at(30, True)).mean()), 1.0)       # (drawn afresh: the colours turn)
            for frame in (60, 75, 600):                                                     # (and on, at and past the 2 s its layers last)
                self.assertGreater(float(np.abs(at(0, True) - at(frame, True)).mean()), 1.0, frame)
                self.assertGreater(float(at(frame, True).mean()), 20.0, frame)               # (and still there)

    def test_a_scroll_in_a_big_static_clip_loops_over_all_of_it_and_only_the_part_that_shows_is_worked_out(self):
        view_w = 4 * W
        clip = self.compound(static=True)
        comp = clip["compound"]
        comp["width"], comp["height"] = view_w, H
        bg = self.bg(transform=dict(tf(scale=4.0), scale_y=1.0))                 # (all of the strip)
        bg["effects"] = [fx.new_effect("builtin:scroll", "e8")]
        bg["effects"][0]["params"].update(speed_x=float(view_w) / 4, loop=True)
        comp["tracks"] = [{"id": "i0", "kind": "video", "name": "v", "clips": [bg]}]
        clip.update(static_live=True, duration_us=30 * S, transform=tf(scale=4.0))          # (at 1:1: a quarter of it shows)
        view = self.view([], [clip])
        gl = self.gpu.gl
        whole = {}
        for name, window in (("window", True), ("whole", False)):
            if not window:
                real = type(gl.fx)._chain
                type(gl.fx)._chain = lambda self, *a, **k: (setattr(self, "window", None), real(self, *a, **k))[1]
            try:
                whole[name] = pixels(self.gpu.render(copy.deepcopy(view), 45, W, H))
            finally:
                if not window:
                    type(gl.fx)._chain = real
        self.assertEqual(self.gpu.errors, [])
        self.assertLessEqual(float(np.abs(whole["window"] - whole["whole"]).mean()), 0.5)
        self.assertGreater(float(whole["window"].mean()), 20.0)
        bg["effects"][0]["params"]["speed_x"] = float(view_w)             # (a whole turn of the strip a second: it is where it began, as all of it loops)
        turn = self.view([], [clip])
        self.assertLessEqual(float(np.abs(pixels(self.gpu.render(copy.deepcopy(turn), 30, W, H))
                                          - pixels(self.gpu.render(copy.deepcopy(turn), 0, W, H))).mean()), 1.0)

    def test_a_static_strip_is_drawn_at_the_size_it_is_shown_up_to_the_cards_textures(self):
        if int(self.gpu.gl.ctx.info["GL_MAX_TEXTURE_SIZE"]) < 16384:
            self.skipTest("small textures here")
        comp = {"name": "s", "width": 15360, "height": 1080, "static": True, "duration_us": 2 * S,
                "tracks": [{"id": "i0", "kind": "video", "name": "v", "clips": [self.bg()]}]}
        with self.gpu.gl.ctx:
            lay = self.gpu.gl_still(comp, 1.0, 30)
            size = (lay.w, lay.h)
        self.assertEqual(size, (15360, 1080))                    # (it was cut down to 4096 wide and blown up again)

    def test_dot_matrix_is_dots_on_a_background(self):
        bg = self.bg()
        bg["effects"] = [fx.new_effect("builtin:dot_matrix", "e7")]
        bg["effects"][0]["params"].update(size=16.0, dot_size=0.5, background=[0.0, 0.0, 0.0, 1.0])
        view = self.view([bg])
        self.check("dot matrix", view, far_max=0.02)
        img = pixels(self.gpu.render(copy.deepcopy(view), 0, W, H))
        dark = float((img.max(axis=2) < 3).mean())                                         # (dots of 8 px on 16 px cells: about 80% is the background)
        self.assertGreater(dark, 0.6)
        self.assertLess(dark, 0.95)

    def test_compounds(self):
        self.check("compound", self.view([self.top()], [self.compound()]))
        self.check("static", self.view([self.top()], [self.compound(static=True)]))

    def test_compound_masks(self):
        for static in (False, True):
            comp = self.compound(static)["compound"]
            for matte, invert, rot in (("alpha", False, 0.0), ("luma", True, 20.0)):
                mask = {"kind": "compound", "compound_id": "k1", "matte": matte, "invert": invert,
                        "cx": 0.1, "cy": 0.05, "w": 0.8, "h": 0.8, "rotation": rot, "feather": 0.0}
                view = self.view([self.top(transform=tf(scale=1.2))], [self.bg(mask=mask, transform=tf(rotation=10))])
                view["compounds"] = {"k1": comp}
                self.check(f"compound mask {static} {matte}", view, far_max=0.02)
        view = self.view([self.bg(mask={"kind": "compound", "compound_id": "k1", "cx": 0.0, "cy": 0.0, "w": 1.0,
                                        "h": 1.0, "rotation": 0.0})])
        view["compounds"] = {"k1": comp}
        view["matte_preview"] = {"clip": "bg", "opacity": 0.5}
        self.check("compound mask shown", view, far_max=0.02)

    def test_effects(self):
        e = fx.new_effect("builtin:invert", "e1")
        e["mask"] = {"kind": "circle", "invert": False, "cx": 0.0, "cy": 0.0, "w": 0.5, "h": 0.8, "rotation": 0.0,
                     "feather": 0.2}
        self.check("effect with mask", self.view([self.top()], [self.bg(effects=[e], transform=tf(scale=0.8, rotation=15),
                                                                         blend="screen")]))
        blur = fx.new_effect("builtin:blur", "e2")
        self.check("two effects", self.view([self.bg(effects=[blur, fx.new_effect("builtin:invert", "e3")],
                                                     transform=tf(scale=0.7, opacity=0.6))]))
        clip = {"id": "f", "type": "filter", "name": "f", "start_us": 0, "duration_us": 2 * S, "source_start_us": 0,
                "transform": tf(opacity=0.5, rotation=20), "effects": [fx.new_effect("builtin:invert", "e4")],
                "mask": {"kind": "rectangle", "invert": False, "cx": 0.1, "cy": 0.0, "w": 0.5, "h": 0.5,
                         "rotation": 0.0, "feather": 0.1}}
        self.check("filter clip", self.view([self.bg()], [clip]))


@unittest.skipUnless(HAVE_GL, "needs OpenGL 3.3")
class BuiltinFilters(unittest.TestCase):
    def test_every_builtin_compiles_and_runs(self):
        eng = fx.Engine()
        rgba = np.zeros((36, 64, 4), np.uint8)
        rgba[..., 1], rgba[..., 3] = 200, 255
        for ref in fx.builtin_refs(nodes=True):
            self.assertIsNone(fx.check(ref), ref)
            d = fx.get(ref)
            out = eng.run(d, {p.name: fx.uniform_value(p, None, 0) for p in d.params}, rgba, 0.5, 0.5, 15)
            self.assertEqual(out.shape, rgba.shape, ref)
            self.assertTrue((out[..., :3] <= out[..., 3:4]).all(), f"{ref}: not premultiplied")


@unittest.skipUnless(HAVE_GL, "needs OpenGL 3.3")
class TextureCache(unittest.TestCase):
    def test_pictures_of_one_frame_over_the_budget_are_not_uploaded_again_next_frame(self):
        gl = glrender.GL()
        old = glrender.TEX_CACHE_BYTES
        glrender.TEX_CACHE_BYTES = 3 * 64 * 64 * 4              # room for three of the six pictures
        try:
            pics = [QImage(64, 64, QImage.Format_ARGB32_Premultiplied) for _ in range(6)]
            for frame in range(3):
                gl.new_frame()
                tex = [gl.picture(p)[0] for p in pics]
                if frame:
                    self.assertEqual([t.glo for t in tex], [t.glo for t in first], "uploaded again")
                first = tex
            gl.new_frame()                                      # a later frame of one picture lets the idle ones go
            gl.picture(QImage(64, 64, QImage.Format_ARGB32_Premultiplied))
            self.assertLessEqual(len(gl.textures), 3 + 1)
        finally:
            glrender.TEX_CACHE_BYTES = old
            gl.ctx.release()


if __name__ == "__main__":
    unittest.main()
