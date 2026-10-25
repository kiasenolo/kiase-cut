"""Advanced export: every format, transparent backgrounds, stems and extra sound streams.

Real exports of a short project (a half-width picture over nothing, two tones on two
tracks), checked with ffprobe. Skipped without ffmpeg.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402

from kiasecut import audiomix, formats, glrender, gpu, project, render, renderexport  # noqa: E402
from kiasecut.build import find_ffmpeg  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])
S = 1_000_000
W, H, FPS = 160, 90, 10
SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="80" height="90" viewBox="0 0 80 90">
<rect width="80" height="90" fill="#ff0000"/></svg>"""
FFMPEG = find_ffmpeg()


def probe(path):
    ffprobe = os.path.join(os.path.dirname(FFMPEG), "ffprobe" + os.path.splitext(FFMPEG)[1])
    r = subprocess.run([ffprobe if os.path.exists(ffprobe) else "ffprobe", "-v", "error", "-show_streams",
                        "-of", "json", path], capture_output=True, text=True)
    return json.loads(r.stdout)["streams"]


def tf():
    return {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}


@unittest.skipUnless(FFMPEG, "no ffmpeg")
class ExportFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.pic = os.path.join(cls.dir, "pic.svg")
        with open(cls.pic, "w", encoding="utf-8") as fh:
            fh.write(SVG)
        cls.tones = []
        for hz in (440, 660):
            path = os.path.join(cls.dir, f"tone{hz}.wav")
            subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={hz}:duration=2",
                            path], check=True)
            cls.tones.append(path)
        cls.gpu = gpu.enabled
        gpu.enabled = False                       # the CPU renderer: the same on every computer

    @classmethod
    def tearDownClass(cls):
        gpu.enabled = cls.gpu
        shutil.rmtree(cls.dir, ignore_errors=True)

    def proj(self, muted=False):
        p = project.new(W, H, FPS)
        sound = lambda cid, path: {"id": cid, "type": "audio", "name": cid, "start_us": 0, "duration_us": S,
                                   "source_start_us": 0, "media": {"path": path, "duration_us": 2 * S},
                                   "volume": 1.0}
        p["tracks"] = [
            {"id": "t0", "kind": "video", "name": "畫面", "clips": [
                {"id": "c1", "type": "image", "name": "pic", "start_us": 0, "duration_us": S, "source_start_us": 0,
                 "media": {"path": self.pic, "width": 80, "height": 90}, "transform": tf()}]},
            {"id": "t1", "kind": "audio", "name": "旁白", "clips": [sound("a1", self.tones[0])]},
            {"id": "t2", "kind": "audio", "name": "音樂/BGM", "clips": [sound("a2", self.tones[1])],
             "muted": muted},
            {"id": "t3", "kind": "audio", "name": "空", "clips": []},
        ]
        project.refresh_duration(p)
        return project.link(p)

    def export(self, name, spec, p=None):
        out = os.path.join(self.dir, name)
        r = renderexport.export(p or self.proj(), out, (W, H), FPS, 0, FPS - 1, {"crf": 20, "preset": "fast"},
                                cache_dir=os.path.join(self.dir, "cache"), spec=spec)
        return out, r

    def test_transparent_movs(self):
        for key, pix in (("mov_prores4444", "yuva444p"), ("mov_qtrle", "argb"), ("mov_png", "rgba")):
            out, _ = self.export(key + ".mov", {"format": key, "alpha": True})
            v = [s for s in probe(out) if s["codec_type"] == "video"][0]
            self.assertTrue(v["pix_fmt"].startswith(pix), (key, v["pix_fmt"]))
            self.assertEqual(sum(s["codec_type"] == "audio" for s in probe(out)), 1)

    def test_opaque_when_off(self):
        out, _ = self.export("solid.mov", {"format": "mov_prores4444", "alpha": False})
        v = [s for s in probe(out) if s["codec_type"] == "video"][0]
        self.assertNotIn("yuva", v["pix_fmt"])

    def test_png_sequence_is_transparent_around_the_picture(self):
        out, r = self.export("seq.png", {"format": "png_seq", "alpha": True})
        folder = os.path.join(self.dir, "seq")
        self.assertEqual(r["done"], folder)
        files = sorted(os.listdir(folder))
        self.assertEqual(len(files), FPS)
        img = QImage(os.path.join(folder, files[0]))
        self.assertEqual(img.pixelColor(5, 45).alpha(), 0)           # nothing there: see-through
        c = img.pixelColor(W // 2, H // 2)
        self.assertEqual((c.alpha(), c.red()), (255, 255))

    def test_video_formats(self):
        for key, codec in (("mp4_h265", "hevc"), ("mov_prores", "prores"), ("webm_vp9", "vp9"),
                           ("mkv_ffv1", "ffv1"), ("gif", "gif")):
            out, _ = self.export(f"{key}{formats.get(key).ext}", {"format": key})
            streams = probe(out)
            self.assertEqual([s["codec_name"] for s in streams if s["codec_type"] == "video"], [codec])
            self.assertEqual(any(s["codec_type"] == "audio" for s in streams), key != "gif")

    def test_no_sound(self):
        out, _ = self.export("silent.mp4", {"format": "mp4_h265", "audio": False})
        self.assertFalse(any(s["codec_type"] == "audio" for s in probe(out)))

    def test_sound_only(self):
        for key, codec in (("wav", "pcm_s16le"), ("flac", "flac"), ("mp3", "mp3"), ("m4a", "aac")):
            out, _ = self.export("sound" + formats.get(key).ext, {"format": key})
            streams = probe(out)
            self.assertEqual([s["codec_name"] for s in streams if s["codec_type"] == "audio"], [codec])
            self.assertFalse(any(s["codec_type"] == "video" and s["codec_name"] not in ("mjpeg", "png")
                                 for s in streams))

    def test_stems(self):
        out, r = self.export("stems.wav", {"format": "wav", "stems": "flac"})
        folder = renderexport.stems_dir(out)
        self.assertEqual(sorted(os.listdir(folder)), ["01 旁白.flac", "02 音樂_BGM.flac"])   # (no empty track)
        self.assertEqual(len(r["stems"]), 2)
        out, r = self.export("muted.wav", {"format": "wav", "stems": "wav"}, self.proj(muted=True))
        self.assertEqual(os.listdir(renderexport.stems_dir(out)), ["01 旁白.wav"])  # as heard in the mix

    def test_multitrack(self):
        for key, tag in (("mov_prores", "handler_name"), ("mkv_ffv1", "title")):
            out, _ = self.export(f"multi{formats.get(key).ext}", {"format": key, "multitrack": True})
            titles = [s.get("tags", {}).get(tag) for s in probe(out) if s["codec_type"] == "audio"]
            self.assertEqual(titles, ["混音", "01 旁白", "02 音樂_BGM"])

    def test_stem_alone_is_its_track(self):
        p = self.proj()
        view = dict(p, fps=float(FPS))
        mix = audiomix.Mixer(os.path.join(self.dir, "cache"))
        tracks = audiomix.stem_tracks(view)
        self.assertEqual([t["id"] for t in tracks], ["t1", "t2"])
        mix.set_view(view, tracks[0])
        self.assertEqual(len(mix.sources), 1)
        self.assertEqual(mix.sources[0].clip["id"], "a1")

    def test_uses_mlt(self):
        self.assertTrue(renderexport.uses_mlt({"format": "mp4_h264"}))
        self.assertTrue(renderexport.uses_mlt({"format": "mp4_h264", "stems": "wav"}))
        self.assertFalse(renderexport.uses_mlt({"format": "mp4_h264", "audio": False}))
        self.assertFalse(renderexport.uses_mlt({"format": "mov_prores4444", "alpha": True}))

    def test_transparent_video_clips(self):
        """A transparent video over a red picture: red around its blue box, on the first
        frame (the engine's picture) and on later ones (the streaming reader's)."""
        red = os.path.join(self.dir, "red.png")
        bg = QImage(W, H, QImage.Format_RGB32)
        bg.fill(0xFFFF0000)
        bg.save(red)
        box = (f"color=c=black@0.0:s={W}x{H}:d=1:r={FPS},format=rgba[bg];color=c=blue:s=40x30:d=1:r={FPS},"
               "format=rgba[fg];[bg][fg]overlay=60:30,format=rgba[out0]")
        for name, args in (("prores4444.mov", ["-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le"]),
                           ("qtrle.mov", ["-c:v", "qtrle", "-pix_fmt", "argb"]),
                           ("vp9.webm", ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p"]),
                           ("vp8.webm", ["-c:v", "libvpx", "-auto-alt-ref", "0", "-pix_fmt", "yuva420p"])):
            src = os.path.join(self.dir, "in-" + name)
            subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", box, *args, src], check=True)
            p = project.new(W, H, FPS)
            p["tracks"] = [
                {"id": "t0", "kind": "video", "name": "bg", "clips": [
                    {"id": "bg", "type": "image", "name": "bg", "start_us": 0, "duration_us": S,
                     "source_start_us": 0, "media": {"path": red, "width": W, "height": H}, "transform": tf()}]},
                {"id": "t1", "kind": "video", "name": "fg", "clips": [
                    {"id": "fg", "type": "video", "name": "fg", "start_us": 0, "duration_us": S,
                     "source_start_us": 0, "media": {"path": src, "width": W, "height": H, "duration_us": S},
                     "transform": tf(), "volume": 1.0}]},
            ]
            project.refresh_duration(p)
            out, r = self.export(f"over-{name}.png", {"format": "png_seq"}, project.link(p))
            files = sorted(os.listdir(r["done"]))
            for f in (files[0], files[3]):
                img = QImage(os.path.join(r["done"], f))
                self.assertEqual(img.pixelColor(10, 10).red(), 255, (name, f))        # see-through
                self.assertGreater(img.pixelColor(80, 45).blue(), 240, (name, f))     # the box


class RendererAlphaTests(unittest.TestCase):
    def view(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        pic = os.path.join(d, "pic.svg")
        with open(pic, "w", encoding="utf-8") as fh:
            fh.write(SVG)
        c = {"id": "c", "type": "image", "name": "c", "start_us": 0, "duration_us": S, "source_start_us": 0,
             "media": {"path": pic, "width": 80, "height": 90}, "transform": tf()}
        return {"width": W, "height": H, "fps": FPS, "duration_us": S,
                "tracks": [{"id": "t", "kind": "video", "name": "v", "clips": [c]}]}

    def check(self, r):
        view = self.view()
        black = r.render(view, 0, W, H).convertToFormat(QImage.Format_RGBA8888)
        self.assertEqual(black.pixelColor(5, 45).alpha(), 255)
        clear = r.render(view, 0, W, H, alpha=True).convertToFormat(QImage.Format_RGBA8888)
        self.assertEqual(clear.pixelColor(5, 45).alpha(), 0)
        self.assertEqual(clear.pixelColor(W // 2, H // 2).name(), "#ff0000")
        self.assertEqual(clear.pixelColor(W // 2, H // 2).alpha(), 255)

    def test_cpu(self):
        self.check(render.Renderer())

    def test_gpu(self):
        try:
            r = glrender.GLRenderer()
        except Exception:
            self.skipTest("no OpenGL 3.3 here")
        self.check(r)


if __name__ == "__main__":
    unittest.main()
