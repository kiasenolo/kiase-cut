"""Rendering from the command line (cli.py): ranges between marks, where the output goes, and
what a failed render leaves. Real renders of a short project; those are skipped without ffmpeg.
"""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication  # noqa: E402

from kiasecut import cli, edit, gpu, project  # noqa: E402
from kiasecut.build import find_ffmpeg  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])
S = 1_000_000


class CliTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.gpu = gpu.enabled
        gpu.enabled = False                       # the CPU renderer: the same on every computer
        p = project.new(160, 90, 10)
        edit.add_text(p, 0, "開機", 3 * S)
        for t, name in ((0, "開頭"), (S, "循環"), (2 * S, "結尾")):
            edit.add_marker(p, t, name)
        project.refresh_duration(p)
        self.path = os.path.join(self.dir, "boot.kiasecut.json")
        project.save(p, self.path)

    def tearDown(self):
        gpu.enabled = self.gpu
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_cli(self, *args):
        text = io.StringIO()
        with contextlib.redirect_stderr(text), contextlib.redirect_stdout(text):
            code = cli.main(list(args))
        return code, text.getvalue()

    def render(self, out, *args):
        return self.run_cli("render", self.path, "-o", os.path.join(self.dir, out), *args)

    def frames(self, folder):
        return sorted(os.listdir(os.path.join(self.dir, folder)))

    def test_ranges_between_marks_meet(self):
        view, marks = cli.level(cli.load(self.path))
        self.assertEqual(cli.frame_range(view, marks, 10, end="循環"), (0, 9))
        self.assertEqual(cli.frame_range(view, marks, 10, "循環", "結尾"), (10, 19))
        self.assertEqual(cli.frame_range(view, marks, 10, "結尾"), (20, 29))

    def test_marks_lists_them(self):
        code, text = self.run_cli("marks", self.path)
        self.assertEqual(code, 0)
        self.assertIn("循環", text)

    def test_wrong_mark_order_and_compound(self):
        for args, says in ((["--from", "沒有"], "沒有標記叫"), (["--from", "結尾", "--to", "循環"], "沒有任何畫格"),
                           (["--compound", "沒有"], "沒有複合片段叫")):
            code, text = self.render("out.mp4", *args)
            self.assertEqual(code, 1, text)
            self.assertIn(says, text)
        self.assertEqual(os.listdir(self.dir), ["boot.kiasecut.json"])

    def test_set_global_parameters(self):
        view = {"rack": [{"id": "r1", "name": "label", "kind": "text", "value": "a"},
                         {"id": "r2", "name": "n", "value": 1.0, "expr": "input * 2"},
                         {"id": "r3", "name": "on", "kind": "bool", "value": False},
                         {"id": "r4", "name": "c", "kind": "color", "value": [0, 0, 0, 1]},
                         {"id": "r5", "name": "v", "kind": "vec2", "value": [0, 0]}]}
        cli.set_params(view, [("label", " x=y "), ("n", "3.5"), ("on", "開"), ("c", "#ff000080"), ("v", "1, 2")])
        got = [p["value"] for p in view["rack"]]
        self.assertEqual(got[:3] + got[4:], [" x=y ", 3.5, True, [1.0, 2.0]])
        self.assertEqual(got[3][:3], [1.0, 0.0, 0.0])
        self.assertNotIn("expr", view["rack"][1])
        for bad in (("none", "1"), ("n", "abc"), ("on", "maybe"), ("c", "red"), ("v", "1")):
            with self.assertRaises(cli.CliError, msg=bad):
                cli.set_params(view, [bad])

    def test_set_needs_a_parameter_that_exists(self):
        code, text = self.render("out.mp4", "--set", "label=x")
        self.assertEqual(code, 1, text)
        self.assertIn("沒有全局參數叫", text)
        self.assertEqual(os.listdir(self.dir), ["boot.kiasecut.json"])

    def test_out_must_fit_the_format(self):
        code, text = self.render("out.mov")
        self.assertEqual(code, 1)
        self.assertIn(".mp4", text)

    @unittest.skipUnless(find_ffmpeg(), "no ffmpeg")
    def test_sequence_replaces_its_own_frames_only(self):
        with open(self.path, "rb") as fh:
            before = fh.read()
        code, text = self.render("v.2/loop", "-f", "png_seq", "--from", "循環", "--to", "結尾")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.frames("v.2/loop"), [f"loop_{n:05d}.png" for n in range(10)])
        open(os.path.join(self.dir, "v.2/loop/keep.txt"), "w").close()
        code, text = self.render("v.2/loop", "-f", "png_seq", "--from", "循環", "--to", "結尾", "--fps", "5")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.frames("v.2/loop"), ["keep.txt"] + [f"loop_{n:05d}.png" for n in range(5)])
        self.assertEqual(self.frames("v.2"), ["loop"])                  # (nothing left beside it)
        with open(self.path, "rb") as fh:
            self.assertEqual(fh.read(), before)

    @unittest.skipUnless(find_ffmpeg(), "no ffmpeg")
    def test_missing_media_keeps_the_old_output(self):
        p = project.load(self.path)
        p["tracks"][0]["clips"].append({"id": "gone", "type": "image", "name": "gone", "start_us": 3 * S,
                                        "duration_us": S, "source_start_us": 0,
                                        "media": {"path": os.path.join(self.dir, "gone.png"), "width": 8, "height": 8},
                                        "transform": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0,
                                                      "opacity": 1.0}})
        project.refresh_duration(p)
        project.save(p, self.path)
        out = os.path.join(self.dir, "out.mp4")
        with open(out, "w") as fh:
            fh.write("old")
        code, text = self.render("out.mp4")
        self.assertEqual(code, 1)
        self.assertIn("gone.png", text)
        with open(out) as fh:
            self.assertEqual(fh.read(), "old")


if __name__ == "__main__":
    unittest.main()
