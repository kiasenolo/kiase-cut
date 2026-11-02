"""標準化 (normalize): a clip's sound to a peak level over the part it plays, on top of 音量 -
in the preview's mix and the export's volume filter."""
import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from kiasecut import audiomix, build, edit, normalize, project  # noqa: E402
from test_edit import S  # noqa: E402

FFMPEG = build.find_ffmpeg()


@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class NormalizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.path = os.path.join(cls.dir, "quiet_loud.wav")             # 1 s at a quarter, then 1 s at a half
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i",
                        "aevalsrc='if(lt(t,1),0.25,0.5)*sin(2*PI*440*t)|if(lt(t,1),0.25,0.5)*sin(2*PI*440*t)'"
                        ":s=48000:d=2",
                        "-c:a", "pcm_s16le", cls.path], check=True)

    def proj(self, **kw):
        c = {"id": "s", "type": "audio", "name": "x", "start_us": 0, "duration_us": S, "source_start_us": 0,
             "media": {"path": self.path, "duration_us": 2 * S}, "volume": 1.0}
        c.update(kw)
        return project.link(dict(project.new(), tracks=[{"id": "a", "kind": "audio", "name": "a", "clips": [c]}]))

    def mixed_peak(self, p):
        mix = audiomix.Mixer(self.dir)
        mix.set_view(p)
        mix.thread.join()
        pcm = np.frombuffer(b"".join(mix.mix(f, 30) for f in range(3, 27)), np.int16)
        return np.abs(pcm.astype(np.int32)).max() / 32768

    def test_set_and_clear(self):
        p = self.proj()
        edit.set_normalize(p, "s", -3)
        self.assertEqual(edit.find(p, "s")[1]["normalize"], -3.0)
        edit.set_normalize(p, "s", None)
        self.assertNotIn("normalize", edit.find(p, "s")[1])

    def test_only_the_part_it_plays(self):
        quiet = self.proj(normalize=-1.0)
        self.assertAlmostEqual(normalize.gain(edit.find(quiet, "s")[1], self.dir), 10 ** (-1 / 20) / 0.25, delta=0.05)
        loud = self.proj(normalize=-1.0, source_start_us=S)
        self.assertAlmostEqual(normalize.gain(edit.find(loud, "s")[1], self.dir), 10 ** (-1 / 20) / 0.5, delta=0.02)

    def test_mix_reaches_the_peak_and_keeps_the_volume(self):
        self.assertAlmostEqual(self.mixed_peak(self.proj(normalize=-6.0)), 10 ** (-6 / 20), delta=0.01)
        self.assertAlmostEqual(self.mixed_peak(self.proj(normalize=-6.0, volume=0.5)), 0.5 * 10 ** (-6 / 20), delta=0.01)
        self.assertAlmostEqual(self.mixed_peak(self.proj()), 0.25, delta=0.01)        # off: as it was

    def test_export_volume_filter(self):
        p = self.proj(normalize=-1.0)
        project.refresh_duration(p)
        xml = build.Builder(p, self.dir).document()
        want = 20 * np.log10(10 ** (-1 / 20) / 0.25)
        self.assertIn(f"{want:.1f}", xml)


if __name__ == "__main__":
    unittest.main()
