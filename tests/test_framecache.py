"""RAM preview (framecache.py): what an edit drops, the memory limit, and the player keeping and drawing ahead."""
import copy
import os
import pickle
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402

from kiasecut import framecache  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])
S = 1_000_000
MOVING = {"keys": [[0, 1.0, 0, 0, 0, 0], [S, 1.0, 0, 0, 0, 0]]}     # (keyframes: each frame its own, not a still stretch)


def shape(cid, start_s, dur_s, x=0.0, **kw):
    c = {"id": cid, "type": "image", "name": cid, "start_us": int(start_s * S), "duration_us": int(dur_s * S),
         "source_start_us": 0, "media": {"path": ":shape:rect", "width": 100, "height": 100},
         "transform": {"x": x, "y": 0.0, "scale": 0.5, "rotation": 0.0, "opacity": MOVING}}
    c.update(kw)
    return c


def view():
    return {"width": 320, "height": 180, "fps": 10.0, "play_fps": 10.0, "duration_us": 10 * S, "compounds": {},
            "rack": [], "tracks": [{"id": "t1", "kind": "video", "name": "v1", "clips": [shape("a", 0, 4), shape("b", 5, 3)]},
                                   {"id": "t2", "kind": "video", "name": "v2", "clips": [shape("c", 2, 2)]},
                                   {"id": "t3", "kind": "video", "name": "bg", "clips": [shape("bg", 0, 10)]}]}


def pic():
    return QImage(4, 4, QImage.Format_RGBA8888)


def filled(v):
    fc = framecache.FrameCache(1 << 30)
    fc.set_view(v)
    for p in range(100):
        fc.put(p, "g", pic())
    return fc


class Invalidation(unittest.TestCase):
    def kept_after(self, edit):
        v = view()
        fc = filled(v)
        w = pickle.loads(pickle.dumps(v))
        edit(w)
        fc.set_view(w)
        return set(fc.frames)

    def test_the_same_state_again_keeps_everything(self):
        self.assertEqual(len(self.kept_after(lambda w: None)), 100)

    def test_a_changed_clip_drops_its_own_frames_only(self):
        kept = self.kept_after(lambda w: w["tracks"][0]["clips"][1]["transform"].update(x=0.3))     # b: 5 - 8 s
        self.assertEqual(set(range(100)) - kept, set(range(49, 81)))

    def test_a_moved_clip_drops_where_it_was_and_where_it_went(self):
        def move(w):
            w["tracks"][1]["clips"][0]["start_us"] = 7 * S                # c: 2 - 4 s -> 7 - 9 s
        kept = self.kept_after(move)
        self.assertEqual(set(range(100)) - kept, set(range(19, 41)) | set(range(69, 91)))

    def test_selection_matters_only_to_an_empty_object(self):
        self.assertEqual(len(self.kept_after(lambda w: w.update(selected=["a"]))), 100)
        v = view()
        v["tracks"][0]["clips"][0]["media"]["path"] = ":shape:empty"
        fc = filled(v)
        w = copy.deepcopy(v)
        w["selected"] = ["a"]
        fc.set_view(w)
        self.assertEqual(set(range(100)) - set(fc.frames), set(range(0, 41)))

    def test_the_canvas_or_the_tracks_drop_everything(self):
        self.assertEqual(self.kept_after(lambda w: w.update(width=640)), set())
        self.assertEqual(self.kept_after(lambda w: w["tracks"][1].update(hidden=True)), set())
        self.assertEqual(self.kept_after(lambda w: w["tracks"].reverse()), set())

    def test_a_compound_named_by_a_clip_counts_as_part_of_it(self):
        v = view()
        v["compounds"] = {"k1": {"width": 320, "height": 180, "tracks": []}}
        v["tracks"][0]["clips"][1]["mask"] = {"kind": "compound", "compound_id": "k1"}
        fc = filled(v)
        w = copy.deepcopy(v)
        w["compounds"]["k1"]["tracks"].append({"id": "x", "kind": "video", "clips": []})
        fc.set_view(w)
        self.assertEqual(set(range(100)) - set(fc.frames), set(range(49, 81)))

    def test_markers_and_audio_do_not_drop_pictures_but_a_visualizer_hears_the_sound(self):
        def audio(w):
            w["tracks"].append({"id": "t9", "kind": "audio", "clips": [{"id": "s", "type": "audio", "start_us": 0, "duration_us": S,
                                                                        "media": {"path": "x.wav"}}]})
        v = view()
        v["tracks"].append({"id": "t9", "kind": "audio", "clips": []})
        fc = filled(v)
        w = copy.deepcopy(v)
        w["markers"] = [{"t": 1}]
        w["tracks"][3]["clips"].append({"id": "s", "type": "audio", "start_us": 0, "duration_us": S, "media": {"path": "x.wav"}})
        fc.set_view(w)
        self.assertEqual(len(fc.frames), 100)
        v["tracks"][1]["clips"][0]["viz"] = {"kind": "bars"}
        fc = filled(v)
        fc.set_view(copy.deepcopy(w) | {"tracks": [*copy.deepcopy(v["tracks"][:3]), w["tracks"][3]]})
        self.assertEqual(set(range(100)) - set(fc.frames), set(range(19, 41)))


class Memory(unittest.TestCase):
    def test_the_least_recently_used_go_first_and_drawing_ahead_stops_when_full(self):
        one = pic().sizeInBytes()
        fc = framecache.FrameCache(3 * one)
        for p in range(3):
            fc.put(p, "g", pic())
        self.assertFalse(fc.room_for(one))
        fc.get(0, "g")
        fc.put(3, "g", pic())
        self.assertEqual(sorted(fc.frames), [0, 2, 3])
        self.assertIsNone(fc.get(2, "other size"))
        fc.set_limit(one)
        self.assertEqual(sorted(fc.frames), [3])

    def test_runs(self):
        self.assertEqual(framecache.runs([5, 1, 2, 3, 9]), [(1, 4), (5, 6), (9, 10)])
        self.assertEqual(framecache.runs([0, 2, 4, 8], step=2), [(0, 6), (8, 10)])


class PlayerKeeps(unittest.TestCase):
    """The player's worker: a frame shown is kept, the ones after it are drawn while it rests, and an edit drops only
    the frames of the clip it changed."""

    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_keep_and_draw_ahead(self):
        from kiasecut import gpu
        from kiasecut.ui import player
        gpu.enabled = False                              # (the CPU renderer: no GL needed here)
        th = player.QThread()
        w = player.Worker()
        w.moveToThread(th)
        th.started.connect(w.run)
        bars, frames = [], []
        w.cacheChanged.connect(bars.append, player.Qt.DirectConnection)
        w.frameReady.connect(lambda img, pos: frames.append(pos), player.Qt.DirectConnection)
        errs = []
        w.failed.connect(errs.append, player.Qt.DirectConnection)
        w.set_render_width(160)
        w.set_cache(True, True, 0.05)
        from unittest import mock
        from kiasecut import sysmem
        free = mock.patch.object(sysmem, "available", lambda: (64 << 30, 128 << 30))     # (whatever this machine has free now)
        free.start()
        self.addCleanup(free.stop)
        th.start()
        try:
            v = view()
            w.set_view(v, self.dir)
            w.request_seek(30)
            self.wait(lambda: bars and bars[-1] == [(30, 100)], what=lambda: (bars[-3:], frames[-3:], errs))
            self.assertIn(30, frames)
            n = len(frames)
            w.request_seek(70)                           # (kept: shown without drawing)
            self.wait(lambda: len(frames) > n)
            self.assertEqual(frames[-1], 70)
            v2 = pickle.loads(pickle.dumps(v))
            v2["tracks"][0]["clips"][1]["transform"]["x"] = 0.4          # b: frames 50 - 80
            w.set_view(v2, self.dir)
            self.wait(lambda: bars and bars[-1] == [(30, 49), (70, 100)])     # (dropped round b, drawn again from the playhead on)
        finally:
            w.stop()
            th.quit()
            th.wait(5000)
            gpu.enabled = True

    def test_drawing_ahead_short_of_memory_keeps_what_is_behind(self):
        """The system short of memory before the RAM preview is full: drawing ahead stops there. It halved what was kept
        (the frames behind first) and drew on, so the kept frames walked off forward (20260705_1930_射京, 15 GB, 4 GB free)."""
        from unittest import mock
        from kiasecut import gpu, sysmem
        from kiasecut.ui import player
        gpu.enabled = False
        th = player.QThread()
        w = player.Worker()
        w.moveToThread(th)
        th.started.connect(w.run)
        bars = []
        w.cacheChanged.connect(bars.append, player.Qt.DirectConnection)
        w.set_render_width(160)
        w.set_cache(True, True, 0.5)
        frame = 160 * 90 * 4
        floor = 768 << 20                                # (the least the player leaves the system: 8 % of 1 GB is less)
        free = mock.patch.object(sysmem, "available", lambda: (floor + 25 * frame - w.cache.bytes, 1 << 30))
        free.start()
        th.start()
        try:
            w.set_view(view(), self.dir)
            w.request_seek(10)
            self.wait(lambda: bars and not w.fill_pending and w.cache.bytes, what=lambda: bars[-3:])
            first = bars[-1]
            self.assertEqual(first[0][0], 10)
            self.assertLess(first[-1][1], 40)            # (stopped where the memory ran short)
            w.request_seek(60)
            time.sleep(1.0)
            self.wait(lambda: not w.fill_pending)
            kept = set(w.cache.frames)
            self.assertGreaterEqual(len(kept & set(range(10, 30))), 15)      # (what was drawn before stays)
            self.assertFalse(kept & set(range(70, 100)))                     # (and nothing walked off forward)
        finally:
            free.stop()
            w.stop()
            th.quit()
            th.wait(5000)
            gpu.enabled = True

    def wait(self, cond, timeout=20.0, what=None):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            APP.processEvents()
            if cond():
                return
            time.sleep(0.01)
        self.fail(f"timed out {what() if what else ''}")


if __name__ == "__main__":
    unittest.main()
