"""Files with several sound streams (音軌): which one a clip plays, in the mix, the waveform,
the MLT export and 分離音訊."""
import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from kiasecut import audiomix, build, edit, project, waveform  # noqa: E402
from test_edit import S, proj  # noqa: E402

FFMPEG = build.find_ffmpeg()


class StreamEditTests(unittest.TestCase):
    def test_set_and_detach(self):
        p = proj()
        with self.assertRaises(edit.EditError):
            edit.set_audio_stream(p, "c1", 1)                       # an image has no sound
        edit.set_audio_stream(p, "c3", 2)
        self.assertEqual(edit.find(p, "c3")[1]["audio_stream"], 2)
        edit.set_audio_stream(p, "c3", 0)
        self.assertNotIn("audio_stream", edit.find(p, "c3")[1])

    def test_detach_every_stream(self):
        p = proj()
        v = edit.find(p, "c1")[1]
        v.update(type="video", media={"path": "v.mkv", "duration_us": 10 * S, "width": 64, "height": 64},
                 source_start_us=0, volume=1.0, fade_in_us=S // 2)
        first = edit.detach_audio(p, "c1", [0, 1, 2])
        sounds = [c for t in p["tracks"] if t["kind"] == "audio" for c in t["clips"] if c["media"]["path"] == "v.mkv"]
        self.assertEqual(sorted(c.get("audio_stream", 0) for c in sounds), [0, 1, 2])
        self.assertIs(first, sounds[0])
        self.assertEqual(len({edit.find(p, c["id"])[0]["id"] for c in sounds}), 3)    # a track each
        self.assertTrue(all(c["fade_in_us"] == S // 2 for c in sounds))
        self.assertEqual(v["volume"], 0.0)


@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class StreamMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.path = os.path.join(cls.dir, "two.mkv")
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "2",
                        "-map", "0:a", "-map", "1:a", "-metadata:s:a:0", "title=遊戲", "-metadata:s:a:1", "language=jpn",
                        "-c:a", "pcm_s16le", cls.path], check=True)

    def clip(self, n):
        c = {"id": "s", "type": "audio", "name": "x", "start_us": 0, "duration_us": S, "source_start_us": 0,
             "media": {"path": self.path, "duration_us": 2 * S}, "volume": 1.0}
        if n:
            c["audio_stream"] = n
        return c

    def test_streams_are_found(self):
        streams = build.audio_streams(self.path)
        self.assertEqual([s["index"] for s in streams], [0, 1])
        self.assertEqual(build.stream_label(streams, 0), "音軌 1：遊戲，1 聲道")
        self.assertEqual(build.stream_label(streams, 1), "音軌 2：jpn，2 聲道")
        self.assertEqual(build.audio_stream(self.clip(1)), 1)
        self.assertEqual(build.audio_stream(self.clip(5)), 0)              # not in the file: the first

    def test_the_mix_plays_the_chosen_stream(self):
        mix = audiomix.Mixer(self.dir)
        loud = [np.abs(mix._decode(audiomix.Source(self.clip(n), 0, (0, S)))[0]).max() for n in (0, 1)]
        self.assertGreater(loud[0], 1000)                                   # the sine
        self.assertEqual(loud[1], 0)                                        # the silent one

    def test_waveform_per_stream(self):
        peaks = waveform.Peaks(self.dir)
        self.assertGreater(peaks._decode(self.path, 0)[0].max(), 0.1)
        self.assertEqual(peaks._decode(self.path, 1)[0].max(), 0.0)

    def test_inspector_switches_streams(self):
        from PySide6.QtWidgets import QApplication
        from kiasecut.ui.inspector import Inspector
        QApplication.instance() or QApplication([])
        ins = Inspector()
        got = []
        ins.audioStreamChosen.connect(lambda ids, n: got.append((ids, n)))
        ins.show_clips([self.clip(1)], 0, 30)
        box = ins.widgets["audio_stream"]
        self.assertEqual((box.count(), box.currentIndex()), (2, 1))
        box.activated.emit(0)
        self.assertEqual(got, [(["s"], 0)])
        other = dict(self.clip(0), id="o", media={"path": "elsewhere.mp3"})
        ins.show_clips([self.clip(1), other], 0, 30)                       # not one file: no choice
        self.assertNotIn("audio_stream", ins.widgets)

    def test_mlt_picks_the_stream(self):
        p = project.link(dict(project.new(), tracks=[{"id": "a", "kind": "audio", "name": "a",
                                                       "clips": [self.clip(0), dict(self.clip(1), id="t", start_us=S)]}]))
        project.refresh_duration(p)
        xml = build.Builder(p, self.dir).document()
        self.assertEqual(xml.count('name="audio_index">1<'), 1)             # its own producer, MLT's stream number


if __name__ == "__main__":
    unittest.main()
