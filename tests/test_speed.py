"""Clip speed (速度), freeze frames (凍結幀) and the 降低幀數 time effect."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import audiomix, edit, project, renderexport  # noqa: E402
from test_edit import S, clip, proj  # noqa: E402

APP = QApplication.instance() or QApplication([])


def video(p):
    """c3 as a 10 s video clip of 4 s at 2 s, from source 1 s."""
    c = edit.find(p, "c3")[1]
    c["media"]["duration_us"] = 10 * S
    return c


class SpeedTests(unittest.TestCase):
    def test_speed_keeps_the_source_stretch(self):
        p = proj()
        c = video(p)
        c["transform"] = {"x": {"keys": [[0, 0.0, 0, 0, 0, 0], [4 * S, 1.0, 0, 0, 0, 0]]}}
        edit.set_speed(p, "c3", 2.0)
        self.assertEqual(c["duration_us"], 2 * S)                     # twice as fast: half as long
        self.assertEqual(c["transform"]["x"]["keys"][1][0], 2 * S)    # keyframes stretch with it
        self.assertEqual(project.source_time(c, S), S + 2 * S)        # source 1 s + 1 s x 2
        self.assertTrue(renderexport.needs_renderer(p))
        edit.set_speed(p, "c3", 1.0)
        self.assertNotIn("speed", c)
        self.assertEqual(c["duration_us"], 4 * S)

    def test_slower_is_held_by_the_room_and_the_source(self):
        p = proj()
        c = video(p)
        edit.set_speed(p, "c3", 0.25)                                 # would be 16 s; the source has 9 s left
        self.assertEqual(c["duration_us"], 16 * S)                   # the same 4 s of source at 1/4
        c["duration_us"] = 4 * S
        c.pop("speed")
        p["tracks"][2]["clips"].append({"id": "after", "type": "audio", "name": "x", "start_us": 7 * S,
                                        "duration_us": S, "source_start_us": 0,
                                        "media": {"path": "b.mp3", "duration_us": S}})
        edit.set_speed(p, "c3", 0.5)
        self.assertEqual(c["duration_us"], 5 * S)                    # up to the clip after it

    def test_trim_and_split_with_speed(self):
        p = proj()
        c = video(p)
        edit.set_speed(p, "c3", 2.0)                                 # 2 - 4 s, source 1 - 5 s
        right = edit.split(p, "c3", 3 * S)
        self.assertEqual(right["source_start_us"], 3 * S)            # 1 s in = 2 s of source
        edit.trim_start(p, "c3", 0)                                  # before the source's start: held
        self.assertEqual(c["start_us"], int(2 * S - S / 2))
        self.assertEqual(c["source_start_us"], 0)

    def test_freeze(self):
        p = proj()
        c = video(p)
        edit.set_freeze(p, "c3", True, 4 * S)
        self.assertEqual(project.source_time(c, 0), 4 * S)
        self.assertEqual(project.source_time(c, 3 * S), 4 * S)       # held for the whole clip
        edit.trim_end(p, "c3", 30 * S)                               # any length while frozen
        self.assertEqual(c["duration_us"], 28 * S)
        self.assertEqual(audiomix.sources(p["tracks"]), [])           # and silent
        edit.set_freeze(p, "c3", False)
        self.assertIsNone(project.frozen(c))
        with self.assertRaises(edit.EditError):
            edit.set_freeze(p, "c1", True)                           # a picture has no frames

    def test_beats_follow_the_speed(self):
        p = proj()
        c = edit.find(p, "c3")[1]
        edit.set_beat(p, "c3", on=True, bpm=60, offset_us=S)         # beat 0 at source 1 s = clip start (2 s)
        edit.set_speed(p, "c3", 2.0)
        self.assertEqual([round(t) for t in edit.beat_times(c)][:3], [2 * S, int(2.5 * S), 3 * S])

    def test_snap_to_beats(self):
        p = proj()
        edit.set_beat(p, "c3", on=True, bpm=60, offset_us=0)         # beats on whole seconds (2 s - 6 s)
        t1 = p["tracks"][1]["clips"]
        t1 += [clip("a", int(2.3 * S), int(1.3 * S)), clip("b", int(3.6 * S), int(0.8 * S))]
        edit.snap_to_beats(p, ["a", "b"])
        a, b = edit.find(p, "a")[1], edit.find(p, "b")[1]
        self.assertEqual((a["start_us"], edit.end(a)), (2 * S, 4 * S))
        self.assertEqual((b["start_us"], edit.end(b)), (4 * S, 5 * S))  # both ends on 4 s: the next beat
        edit.set_beat(p, "c3", on=False)
        with self.assertRaises(edit.EditError):
            edit.snap_to_beats(p, ["a"])

    def test_snap_to_beats_in_a_group(self):
        p = proj()
        edit.set_beat(p, "c3", on=True, bpm=60, offset_us=0)
        p["tracks"][1]["clips"] += [clip("a", int(2.3 * S), int(1.3 * S)), clip("b", int(3.6 * S), int(0.8 * S))]
        g = edit.make_group(p, p, ["a", "b"])                     # 2.3 - 4.4: both ends grow it
        edit.snap_to_beats(p, ["a", "b"])
        span = lambda k: (edit.abs_start(p, k), edit.abs_start(p, k) + edit.find(p, k)[1]["duration_us"])
        self.assertEqual((span("a"), span("b")), ((2 * S, 4 * S), (4 * S, 5 * S)))
        self.assertEqual((g["start_us"], g["duration_us"]), (2 * S, 3 * S))

    def test_sound_plays_faster(self):
        p = proj()
        c = edit.find(p, "c3")[1]
        c["speed"] = 2.0
        (src,) = audiomix.sources(p["tracks"])
        src.pcm = (np.arange(48000 * 8, dtype=np.int64) % 30000).astype(np.int16).repeat(2).reshape(-1, 2)
        src.offset = 0
        m = audiomix.Mixer.__new__(audiomix.Mixer)
        m.lock, m.sources, m.master = __import__("threading").Lock(), [src], 1.0
        out = np.frombuffer(m.mix(2 * 30 + 1, 30), np.int16).reshape(-1, 2)     # 1/30 s into the clip
        self.assertEqual(int(out[1, 0]) - int(out[0, 0]), 2)          # every other sample: twice as fast

    def test_nested_speed(self):
        p = proj()
        inner = edit.find(p, "c3")[1]
        p["tracks"][2]["clips"].remove(inner)
        inner["start_us"], inner["source_start_us"] = 0, 0
        p["compounds"]["k9"] = {"name": "n", "width": 1920, "height": 1080, "duration_us": 4 * S,
                                "tracks": [{"id": "a", "kind": "audio", "name": "a", "clips": [inner]}]}
        holder = {"id": "cc", "type": "compound", "name": "cc", "start_us": 10 * S, "duration_us": 2 * S,
                  "source_start_us": 0, "compound_id": "k9", "speed": 2.0,
                  "transform": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}}
        p["tracks"][0]["clips"].append(holder)
        project.link(p)
        (src,) = audiomix.sources(p["tracks"])
        self.assertEqual((src.start_us, src.rate), (10 * S, 2.0))
        self.assertEqual(src.win, (10 * S, 12 * S))


class FrameRateEffectTests(unittest.TestCase):
    def test_time_steps(self):
        p = proj()
        c = edit.find(p, "c1")[1]
        edit.add_effect(p, "c1", project.TIME_FILTER)
        self.assertEqual(project.stepped(c, int(0.13 * S)), int(S / 12))      # 12 fps: 1/12 s steps
        self.assertEqual(project.visual_effects(c), [])                      # nothing to draw for it
        c["effects"][0]["disabled"] = True
        self.assertEqual(project.stepped(c, int(0.13 * S)), int(0.13 * S))

    def test_keyframes_move_in_steps(self):
        from kiasecut import render
        p = proj()
        p["tracks"][0]["clips"] = p["tracks"][0]["clips"][:1]
        c = edit.find(p, "c1")[1]
        c["transform"]["scale"] = 0.1
        c["transform"]["x"] = {"keys": [[0, -0.5, 0, 0, 0, 0], [2 * S, 0.5, 0, 0, 0, 0]]}
        edit.add_effect(p, "c1", project.TIME_FILTER)
        c["effects"][0]["params"]["fps"] = 2.0                               # half-second steps
        r = render.Renderer()
        r.image = lambda path, w, h: __import__("PySide6.QtGui", fromlist=["QImage"]).QImage(4, 4, 5)
        seen = []
        orig = r.draw_clip

        def spy(pp, cc, *a):
            seen.append(project.stepped(cc, a[3] - cc["start_us"]))
            return orig(pp, cc, *a)
        r.draw_clip = spy
        for f in (6, 18, 29):                                                # 0.1 s, 0.3 s, 0.48 s
            r.render(p, f, 64, 36)
        self.assertEqual(seen, [0, 0, 0])


if __name__ == "__main__":
    unittest.main()
