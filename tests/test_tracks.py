import json
import unittest

import numpy as np

from kiasecut import audiomix, build, edit, project, waveform


def proj():
    p = project.new()
    p["tracks"] = [
        {"id": "v", "kind": "video", "name": "v", "clips": [
            {"id": "vid", "type": "video", "name": "cam", "start_us": 0, "duration_us": 2_000_000,
             "source_start_us": 500_000, "media": {"path": "cam.mp4", "width": 1920, "height": 1080,
                                                   "duration_us": 9_000_000},
             "volume": 0.8, "fade_in_us": 100_000, "transform": {"x": 0.0, "y": 0.0}}]},
        {"id": "a1", "kind": "audio", "name": "a1", "clips": [
            {"id": "m", "type": "audio", "name": "m", "start_us": 0, "duration_us": 1_000_000,
             "source_start_us": 0, "media": {"path": "m.mp3", "duration_us": 5_000_000}}]},
        {"id": "a2", "kind": "audio", "name": "a2", "clips": [
            {"id": "n", "type": "audio", "name": "n", "start_us": 0, "duration_us": 1_000_000,
             "source_start_us": 0, "media": {"path": "n.mp3", "duration_us": 5_000_000}}]},
    ]
    project.refresh_duration(p)
    return p


class TrackTests(unittest.TestCase):
    def test_mute_solo_gain(self):
        p = proj()
        tr = p["tracks"]
        self.assertEqual([project.sounds(t, tr) for t in tr], [1.0, 1.0, 1.0])
        edit.set_track_flag(p, "a1", "muted", True)
        self.assertEqual(project.sounds(tr[1], tr), 0.0)
        edit.set_track_flag(p, "a2", "solo", True)
        self.assertEqual([project.sounds(t, tr) for t in tr], [0.0, 0.0, 1.0])
        edit.set_track_gain(p, "a2", 0.5)
        names = [s.clip["id"] for s in audiomix.sources(tr)]
        self.assertEqual(names, ["n"])
        self.assertEqual(audiomix.sources(tr)[0].gain, 0.5)
        edit.set_track_flag(p, "a2", "solo", False)
        edit.set_track_gain(p, "a2", 1.0)
        self.assertNotIn("gain", tr[2])
        self.assertNotIn("solo", tr[2])

    def test_add_move_delete_track(self):
        p = proj()
        t = edit.add_track(p, "text")
        self.assertEqual([x["kind"] for x in p["tracks"]], ["video", "text", "audio", "audio"])
        edit.move_track(p, t["id"], up=False)                     # below the video layer
        self.assertEqual(p["tracks"][0]["id"], t["id"])
        with self.assertRaises(edit.EditError):
            edit.move_track(p, t["id"], up=False)
        edit.move_track(p, "a2", up=True)
        self.assertEqual([x["id"] for x in p["tracks"][2:]], ["a2", "a1"])
        a = edit.add_track(p, "audio", near_id="a2")              # above a2 on screen
        self.assertEqual([x["id"] for x in p["tracks"][2:]], [a["id"], "a2", "a1"])
        edit.delete_track(p, t["id"])
        self.assertNotIn(t["id"], [x["id"] for x in p["tracks"]])

    def test_move_to_new_track(self):
        p = proj()
        edit.move_to_new_track(p, "m", 300_000, top=False)
        self.assertEqual(p["tracks"][-1]["clips"][0]["id"], "m")
        self.assertEqual(p["tracks"][-1]["clips"][0]["start_us"], 300_000)
        self.assertEqual(p["tracks"][1]["clips"], [])
        edit.move_to_new_track(p, "vid", 0, top=True)
        self.assertEqual(p["tracks"][1]["kind"], "video")         # above the old video track
        self.assertEqual(p["tracks"][1]["clips"][0]["id"], "vid")

    def test_detach_audio(self):
        p = proj()
        a = edit.detach_audio(p, "vid")
        _, v = edit.find(p, "vid")
        self.assertEqual(v["volume"], 0.0)
        self.assertNotIn("fade_in_us", v)
        self.assertEqual((a["start_us"], a["duration_us"], a["source_start_us"], a["volume"], a["fade_in_us"]),
                         (0, 2_000_000, 500_000, 0.8, 100_000))
        # a1 and a2 are taken at 0..1 s, so it lands on a new audio track
        self.assertEqual(len([t for t in p["tracks"] if t["kind"] == "audio"]), 3)
        with self.assertRaises(edit.EditError):
            edit.detach_audio(p, "m")

    def test_export_hides(self):
        p = proj()
        p["tracks"] = p["tracks"][1:]
        edit.set_track_flag(p, "a1", "muted", True)
        edit.set_track_gain(p, "a2", 0.5)
        b = build.Builder(p, ".")
        b.tractor(p["tracks"], 0, (0, 60))
        xml = "".join(b.xml)
        self.assertEqual(xml.count('hide="both"'), 1)
        self.assertIn('<property name="level">-6.021</property>', xml)

    def test_waveform_columns(self):
        per_s = round(1 / waveform.BIN_S)
        peaks = np.zeros((2 * per_s, 2), np.float32)
        peaks[per_s] = (0.8, -0.5)                                 # a click at 1 s
        hi, lo = waveform.columns(peaks, 0.0, 0.0, 2.0, 20)
        self.assertEqual(hi.argmax(), 10)
        self.assertEqual(lo.argmin(), 10)
        self.assertAlmostEqual(float(hi[10]), 0.8, places=6)
        self.assertAlmostEqual(float(lo[10]), -0.5, places=6)
        hi, lo = waveform.columns(peaks, 0.5, 0.0, 2.0, 20)        # stream starts 0.5 s late
        self.assertEqual(hi.argmax(), 15)


if __name__ == "__main__":
    unittest.main()


class MaskToggleTests(unittest.TestCase):
    def test_enable_disable(self):
        p = proj()
        edit.set_mask_enabled(p, "vid", True)                     # no mask yet: a rectangle
        _, c = edit.find(p, "vid")
        self.assertEqual(c["mask"]["kind"], "rectangle")
        b = build.Builder(p, ".")
        self.assertIn("rotoscoping", b.visual(c, 0, 60, 0, None, (1920, 1080)))
        edit.set_param(p, "vid", "mask", "w", 0.3)
        edit.set_mask_enabled(p, "vid", False)
        self.assertIsNone(project.active_mask(c))
        self.assertNotIn("rotoscoping", b.visual(c, 0, 60, 0, None, (1920, 1080)))
        edit.set_mask(p, "vid", "circle")                         # a new shape stays off
        self.assertIs(c["mask"]["enabled"], False)
        edit.set_mask_enabled(p, "vid", True)
        self.assertEqual((c["mask"]["kind"], c["mask"]["w"]), ("circle", 0.3))
        self.assertNotIn("enabled", c["mask"])


class TimelineTests(unittest.TestCase):
    def test_add_switch_delete(self):
        p = project.link(proj())
        h = edit.History(p)
        first = p["active_timeline"]
        h.do("new", edit.add_timeline)
        second = p["active_timeline"]
        self.assertNotEqual(first, second)
        self.assertEqual([t["kind"] for t in p["tracks"]], ["video", "audio"])   # V1 / A1
        self.assertIs(p["tracks"], project.timeline(p)["tracks"])
        edit.open_timeline(p, first)
        self.assertEqual(len(p["tracks"]), 3)
        h.do("copy", edit.add_timeline, None, first)
        copy_ = project.timeline(p)
        self.assertEqual(len(copy_["tracks"]), 3)
        self.assertNotEqual(copy_["tracks"][0]["clips"][0]["id"], project.timeline(p, first)["tracks"][0]["clips"][0]["id"])
        h.undo()
        h.undo()
        self.assertEqual([t["id"] for t in p["timelines"]], [first])
        self.assertIs(p["tracks"], p["timelines"][0]["tracks"])
        with self.assertRaises(edit.EditError):
            edit.delete_timeline(p, first)

    def test_stored_without_open_tracks(self):
        p = project.link(proj())
        edit.add_timeline(p, "B")
        raw = json.loads(project.dumps(p))
        self.assertNotIn("tracks", raw)
        back = project.normalize(raw)
        self.assertEqual(back["active_timeline"], p["active_timeline"])
        self.assertIs(back["tracks"], project.timeline(back)["tracks"])
