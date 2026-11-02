"""Audio Visualizer: pictures drawn from the sound (viz.py), by both renderers."""
import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import build, edit, project, render, renderexport, viz  # noqa: E402

APP = QApplication.instance() or QApplication([])
FFMPEG = build.find_ffmpeg()
S = 1_000_000
W, H = 320, 180


def alpha_sum(img):
    return int(np.frombuffer(bytes(img.constBits()), np.uint8).reshape(img.height(), img.width(), 4)[..., 3].astype(int).sum())


def columns(img):
    """The alpha of each pixel column, summed."""
    a = np.frombuffer(bytes(img.constBits()), np.uint8).reshape(img.height(), img.width(), 4)[..., 3].astype(int)
    return a.sum(axis=0)


@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class VizTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.both = os.path.join(cls.dir, "both.wav")                    # 1 kHz in both ears for 1 s, then nothing for 1 s
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i",
                        "aevalsrc='if(lt(t,1),0.5*sin(2*PI*1000*t),0)|if(lt(t,1),0.5*sin(2*PI*1000*t),0)':s=48000:d=2",
                        "-c:a", "pcm_s16le", cls.both], check=True)
        cls.left = os.path.join(cls.dir, "left.wav")                    # 1 kHz in the left ear only
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i",
                        "aevalsrc='0.5*sin(2*PI*1000*t)|0':s=48000:d=2", "-c:a", "pcm_s16le", cls.left], check=True)

    def clip(self, path, **kw):
        v = viz.make("bars", {"type": "file", "path": path}, 180)
        v.update(kw)
        c = {"id": "v1", "type": "image", "name": "v", "start_us": 0, "duration_us": 2 * S, "source_start_us": 0,
             "media": {"path": "x.png", "width": W, "height": H}, "transform": {}, "viz": v}
        return c

    def paint(self, c, t_us, probe=None, w=W, h=H):
        probe = probe or viz.Probe(self.dir)
        return viz.paint(c["viz"], probe, c, t_us, w, h, H)

    def test_a_tone_lights_its_own_bar(self):
        c = self.clip(self.both, bar_w=4.0, gap=2.0, smooth=0.0, attack=0.0, decay=0.0)
        cols = columns(self.paint(c, S // 2))
        peak = int(np.argmax(cols))
        n = int((W + 2 * 1.0) / (4 * 1.0 + 2 * 1.0))
        bar = int(np.argmax(viz.band_levels(viz.spectrum(np.sin(2 * np.pi * 1000 * np.arange(viz.NFFT) / viz.RATE)),
                                            n, 30.0, 16000.0, True)))
        x0 = (W - (n * 4 + (n - 1) * 2)) / 2
        self.assertLess(abs(peak - (x0 + bar * 6 + 2)), 4)
        self.assertGreater(cols.max(), 2 * np.median(cols))

    def test_silence_draws_nothing_and_after_the_sound_it_falls(self):
        c = self.clip(self.both, attack=0.0, decay=0.0, smooth=0.0)
        self.assertGreater(alpha_sum(self.paint(c, S // 2)), 5000)
        self.assertEqual(alpha_sum(self.paint(c, int(1.5 * S))), 0)
        c = self.clip(self.both, attack=0.0, decay=0.5, smooth=0.0)
        probe = viz.Probe(self.dir)
        soon = alpha_sum(self.paint(c, int(1.1 * S), probe))
        later = alpha_sum(self.paint(c, int(1.8 * S), probe))
        self.assertGreater(soon, later)
        self.assertGreater(soon, 0)

    def test_channels(self):
        left = self.clip(self.left, channel="L", smooth=0.0, attack=0.0, decay=0.0)
        right = self.clip(self.left, channel="R", smooth=0.0, attack=0.0, decay=0.0)
        mid = self.clip(self.left, channel="M", smooth=0.0, attack=0.0, decay=0.0)
        side = self.clip(self.left, channel="S", smooth=0.0, attack=0.0, decay=0.0)
        a = {k: alpha_sum(self.paint(c, S // 2)) for k, c in (("L", left), ("R", right), ("M", mid), ("S", side))}
        self.assertEqual(a["R"], 0)
        self.assertGreater(a["L"], 0)
        self.assertGreater(a["M"], 0)
        self.assertGreater(a["S"], 0)
        self.assertGreater(a["L"], a["M"])                                  # (half the level in the middle)

    def test_every_kind_and_option_draws(self):
        for kind in viz.KINDS:
            for extra in ({}, {"mirror": True}, {"radial": True}, {"radial": True, "mirror": True},
                          {"gradient": True, "log": False}):
                c = self.clip(self.both)
                c["viz"] = viz.make(kind, {"type": "file", "path": self.both}, 180)
                c["viz"].update(extra)
                img = self.paint(c, S // 2)
                self.assertEqual((img.width(), img.height()), (W, H))
                self.assertGreater(alpha_sum(img), 0, (kind, extra))

    def test_the_vectorscope_shows_mono_as_a_vertical_line_and_side_as_a_horizontal_one(self):
        c = self.clip(self.both)
        c["viz"] = viz.make("vector", {"type": "file", "path": self.both}, 180)
        c["viz"].update(grid=False, decay=0.0)
        img = self.paint(c, S // 2)
        a = np.frombuffer(bytes(img.constBits()), np.uint8).reshape(H, W, 4)[..., 3]
        ys, xs = np.nonzero(a)
        self.assertGreater(ys.max() - ys.min(), 6 * (xs.max() - xs.min()))       # (same in both ears: straight up)
        c["viz"]["decay"] = 0.0
        side = os.path.join(self.dir, "side.wav")                                  # opposite in the ears: side only
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*1000*t)|-0.5*sin(2*PI*1000*t)':s=48000:d=2",
                        "-c:a", "pcm_s16le", side], check=True)
        c["viz"]["source"] = {"type": "file", "path": side}
        img = self.paint(c, S // 2)
        a = np.frombuffer(bytes(img.constBits()), np.uint8).reshape(H, W, 4)[..., 3]
        ys, xs = np.nonzero(a)
        self.assertGreater(xs.max() - xs.min(), 6 * (ys.max() - ys.min()))

    def test_sources_track_and_compound(self):
        audio = {"id": "a1", "type": "audio", "name": "a", "start_us": 0, "duration_us": 2 * S, "source_start_us": 0,
                 "media": {"path": self.both, "duration_us": 2 * S}, "volume": 1.0}
        other = dict(audio, id="a2", media={"path": self.left, "duration_us": 2 * S})
        p = project.link(dict(project.new(), tracks=[{"id": "ta", "kind": "audio", "name": "a", "clips": [audio]},
                                                     {"id": "tb", "kind": "audio", "name": "b", "clips": [other]}]))
        c = self.clip(self.both)
        c["viz"]["source"] = {"type": "track", "id": "ta"}
        c["viz"].update(attack=0.0, decay=0.0, channel="R")
        probe = viz.Probe(self.dir)
        loud = viz.paint(c["viz"], probe, c, S // 2, W, H, H, {}, p["tracks"])
        self.assertGreater(alpha_sum(loud), 0)                           # (track a is both ears)
        c["viz"]["source"] = {"type": "track", "id": "tb"}
        self.assertEqual(alpha_sum(viz.paint(c["viz"], probe, c, S // 2, W, H, H, {}, p["tracks"])), 0)   # (b has nothing in the right)
        c["viz"]["source"] = {"type": "track", "id": "nope"}
        self.assertEqual(alpha_sum(viz.paint(c["viz"], probe, c, S // 2, W, H, H, {}, p["tracks"])), 0)

    def test_edit_and_export(self):
        p = project.link(dict(project.new(), tracks=[]))
        c = edit.add_visualizer(p, "wave", {"type": "file", "path": self.both}, "x.png", S, 3 * S, 1920, 1080)
        self.assertEqual(c["viz"]["kind"], "wave")
        self.assertEqual(len(p["tracks"]), 1)
        edit.set_viz(p, c["id"], kind="scope", channel="L", bar_w=9999, color=[2, 0, 0, 1])
        self.assertEqual((c["viz"]["kind"], c["viz"]["channel"], c["viz"]["bar_w"], c["viz"]["color"][0]),
                         ("scope", "L", 400.0, 1.0))
        with self.assertRaises(edit.EditError):
            edit.set_viz(p, c["id"], source={"type": "ftp"})
        with self.assertRaises(edit.EditError):
            edit.set_viz(p, c["id"], nonsense=1)
        self.assertTrue(renderexport.needs_renderer(p))

    def test_rendered_in_the_cpu_renderer(self):
        c = self.clip(self.both, attack=0.0, decay=0.0)
        p = project.link(dict(project.new(), width=W, height=H, tracks=[{"id": "v", "kind": "video", "name": "v", "clips": [c]}]))
        r = render.Renderer()
        r.cache_dir = self.dir
        loud = r.render(p, int(0.5 * p["fps"]), W, H, alpha=True)
        quiet = r.render(p, int(1.5 * p["fps"]), W, H, alpha=True)
        self.assertGreater(alpha_sum(loud), 1000)
        self.assertEqual(alpha_sum(quiet), 0)

    def test_rendered_in_the_gpu_renderer(self):
        from kiasecut import glrender
        try:
            gl = glrender.GLRenderer()
        except Exception:
            self.skipTest("no OpenGL 3.3 here")
        c = self.clip(self.both, attack=0.0, decay=0.0)
        p = project.link(dict(project.new(), width=W, height=H, tracks=[{"id": "v", "kind": "video", "name": "v", "clips": [c]}]))
        gl.cache_dir = self.dir
        loud = gl.render(p, int(0.5 * p["fps"]), W, H, alpha=True)
        self.assertGreater(alpha_sum(loud), 1000)


class VizInspectorTests(unittest.TestCase):
    def test_rows_follow_the_kind_and_report_edits(self):
        from kiasecut.ui.inspector import Inspector
        p = project.link(dict(project.new(), tracks=[{"id": "ta", "kind": "audio", "name": "歌", "clips": []}]))
        c = edit.add_visualizer(p, "bars", {"type": "track", "id": "ta"}, "x.png", 0, S, 1920, 1080)
        ins = Inspector()
        ins.sound_tracks = [("ta", "歌")]
        got = []
        ins.vizEdited.connect(lambda ids, fields: got.append(fields))
        ins.show_clips([c], 0, 60)
        self.assertEqual(ins.widgets[("viz", "source_pick")].currentText(), "歌")
        self.assertEqual(ins.widgets[("viz", "bar_w")].value(), c["viz"]["bar_w"])
        self.assertNotIn(("viz", "grid"), ins.widgets)
        ins.widgets[("viz", "bar_w")].edited.emit(20.0)
        ins.widgets[("viz", "mirror")].click()
        ins.widgets[("viz", "channel")].activated.emit(1)
        self.assertEqual(got, [{"bar_w": 20.0}, {"mirror": True}, {"channel": "L"}])
        edit.set_viz(p, c["id"], kind="vector")
        ins.show_clips([c], 0, 60)                                           # (another kind, another set of rows)
        self.assertIn(("viz", "grid"), ins.widgets)
        self.assertNotIn(("viz", "bar_w"), ins.widgets)


if __name__ == "__main__":
    unittest.main()
