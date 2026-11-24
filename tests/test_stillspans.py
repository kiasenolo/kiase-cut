"""Still stretches (stillspans.py): what counts as moving, where a stretch ends, and the RAM preview keeping one frame for it."""
import copy
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402

from kiasecut import framecache, lfo, mapping, render, stillspans  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])
S = 1_000_000
FPS = 10.0
KEYS = {"keys": [[0, 0.0, 0, 0, 0, 0], [S, 0.5, 0, 0, 0, 0]]}


def shape(cid, start_s, dur_s, **kw):
    c = {"id": cid, "type": "image", "name": cid, "start_us": int(start_s * S), "duration_us": int(dur_s * S),
         "source_start_us": 0, "media": {"path": ":shape:rect", "width": 100, "height": 100},
         "transform": {"x": 0.0, "y": 0.0, "scale": 0.5, "rotation": 0.0, "opacity": 1.0}}
    c.update(kw)
    return c


def text(cid, start_s, dur_s, words="字幕"):
    return {"id": cid, "type": "text", "name": cid, "start_us": int(start_s * S), "duration_us": int(dur_s * S),
            "source_start_us": 0, "text": {"content": words, "size": 8.0, "color": "#ffffff"},
            "transform": {"x": 0.0, "y": 0.5, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}}


def view(*clips, length_s=10):
    return {"width": 160, "height": 90, "fps": FPS, "duration_us": int(length_s * S), "compounds": {}, "rack": [],
            "tracks": [{"id": "t%d" % i, "kind": "video", "name": "v", "clips": [c]} for i, c in enumerate(clips)]}


def effect(ref, **params):
    return {"id": "e1", "filter": ref, "enabled": True, "params": params}


class Spans(unittest.TestCase):
    def spans(self, *clips, length_s=10):
        v = view(*clips, length_s=length_s)
        return stillspans.frame_spans(v, render.frame_count(v))

    def test_still_clips_make_stretches_that_end_where_a_clip_does(self):
        self.assertEqual(self.spans(shape("a", 0, 4), text("t1", 1, 2), text("t2", 3, 3)),
                         [(0, 10), (10, 30), (30, 40), (40, 60), (60, 100)])

    def test_nothing_on_the_level_is_one_stretch(self):
        self.assertEqual(self.spans(length_s=3), [(0, 30)])

    def test_a_clip_shows_from_its_rounded_frame(self):
        """on_frame rounds: a clip starting 1.4 frames in shows on frame 1 (at 0.1 s, before its start), so frames 0 and 1
        are not one picture though neither is past its start (The Looping Room: a filter clip at 0.02 s, 60 fps)."""
        spans = self.spans(shape("a", 0.14, 2))
        self.assertFalse([1 for a, b in spans if a <= 0 and b >= 2])
        self.assertIn(20, {f for a, b in spans for f in range(a, b)})
        self.assertFalse([1 for a, b in spans if a <= 20 < b and b > 21])      # (it shows to frame 20, round(21.4) - 1)

    def test_what_moves(self):
        cases = {
            "keyframes": shape("a", 0, 10, transform={"x": KEYS, "y": 0.0, "scale": 0.5, "rotation": 0.0, "opacity": 1.0}),
            "an effect's keyframes": shape("a", 0, 10, effects=[effect("builtin:blur", radius=KEYS)]),
            "an LFO": shape("a", 0, 10, expr={"transform.x": lfo.make()}),
            "an expression": shape("a", 0, 10, expr={"transform.x": "time * 2"}),
            "a mapping": shape("a", 0, 10, effects=[effect("builtin:blur", radius=mapping.make(src="p"))]),
            "a video": dict(shape("a", 0, 10), type="video", media={"path": "x.mp4", "width": 100, "height": 100}),
            "a visualizer": shape("a", 0, 10, viz={"kind": "bars"}),
            "a filter reading the time": shape("a", 0, 10, effects=[effect("builtin:shake")]),
            "a filter reading frame_phase()": shape("a", 0, 10, effects=[effect("builtin:glitch_effect", animated=True)]),
            "a node effect's Time node": shape("a", 0, 10, effects=[{"id": "e1", "filter": "nodes:graph", "params": {},
                                                                     "graph": {"nodes": {"n": {"type": "filter", "ref": "builtin:nodes/time"}},
                                                                               "links": []}}]),
            "a node effect's video": shape("a", 0, 10, effects=[{"id": "e1", "filter": "nodes:graph", "params": {},
                                                                 "graph": {"nodes": {"n": {"type": "source", "kind": "video"}}, "links": []},
                                                                 "sources": {"n": {"kind": "video", "path": "x.mp4"}}}]),
            "a video mask": shape("a", 0, 10, mask={"kind": "video", "video": "x.mp4", "vid_w": 10, "vid_h": 10}),
            "a keyframed mask": shape("a", 0, 10, mask={"kind": "rect", "cx": KEYS}),
            "a filter that cannot be read": shape("a", 0, 10, effects=[effect("/nowhere/gone.glsl")]),
        }
        for name, c in cases.items():
            with self.subTest(name):
                self.assertEqual(self.spans(c), [], name)

    def test_a_filter_reads_the_time_only_while_its_switch_is_on(self):
        """@time: 每格不同 off (Sensor Noise, Glitch Effect), 隨時間擴大 off and 每秒變化 0 (memory_*): one picture."""
        for ref, still, moving in (("builtin:blender_sensor_noise", {"animated": False}, {"animated": True}),
                                   ("builtin:glitch_effect", {"animated": False}, {"animated": True}),
                                   ("builtin:memory_blocks", {"spread": False, "rate": 0.0}, {"spread": False, "rate": 60.0}),
                                   ("builtin:memory_pull", {"spread": False, "rate": 0.0}, {"spread": True, "rate": 0.0})):
            with self.subTest(ref):
                self.assertEqual(self.spans(shape("a", 0, 10, effects=[effect(ref, **still)])), [(0, 100)])
                self.assertEqual(self.spans(shape("a", 0, 10, effects=[effect(ref, **moving)])), [])
        self.assertEqual(self.spans(shape("a", 0, 10, effects=[effect("builtin:memory_blocks")])), [])   # (its defaults move)

    def test_a_node_reads_the_time_by_its_own_values(self):
        def graph(params, links=(), nodes=None):
            nodes = nodes or {"n": {"type": "filter", "ref": "builtin:blender_sensor_noise"}}
            return shape("a", 0, 10, effects=[{"id": "e1", "filter": "nodes:graph", "params": params,
                                               "graph": {"nodes": nodes, "links": list(links)}}])
        self.assertEqual(self.spans(graph({"n.animated": False})), [(0, 100)])
        self.assertEqual(self.spans(graph({"n.animated": True})), [])
        fed = {"from": "v", "out": "value", "to": "n", "socket": "param:animated"}     # (its switch fed by another node)
        self.assertEqual(self.spans(graph({"n.animated": False}, [fed], {
            "n": {"type": "filter", "ref": "builtin:blender_sensor_noise"},
            "v": {"type": "filter", "ref": "builtin:nodes/value"}})), [])
        grouped = {"g": {"type": "group", "inputs": [], "outputs": []},
                   "t": {"type": "filter", "ref": "builtin:nodes/time", "group": "g"}}
        self.assertEqual(self.spans(graph({}, (), grouped)), [])                # (a Time node inside a node group)

    def test_a_compound_as_a_source_or_mask(self):
        """A static compound as an effect's picture or a mask: one picture, read at its own time (讀取時間) too while its
        layers are all there from 0 and still; a layer that moves in it, or comes later, makes it move."""
        still = {"width": 160, "height": 90, "static": True, "tracks": [{"id": "i", "kind": "video", "clips": [shape("x", 0, 0.1)]}]}
        moving = copy.deepcopy(still)
        moving["tracks"][0]["clips"][0]["effects"] = [effect("builtin:scroll", speed_x=5.0)]
        later = copy.deepcopy(still)
        later["tracks"].append({"id": "j", "kind": "video", "clips": [shape("y", 2, 0.1)]})

        def using(comp, live, how):
            v = view(shape("a", 0, 10, **({"effects": [effect("builtin:blur", radius=2.0) | {"sources": {"radius": {
                "kind": "compound", "compound_id": "k", "static_live": live}}}]} if how == "source" else
                {"mask": {"kind": "compound", "compound_id": "k", "static_live": live}})))
            v["compounds"] = {"k": comp}
            return stillspans.frame_spans(v, render.frame_count(v))
        for how in ("source", "mask"):
            with self.subTest(how):
                self.assertEqual(using(still, False, how), [(0, 100)])
                self.assertEqual(using(still, True, how), [(0, 100)])
                self.assertEqual(using(moving, True, how), [])
                self.assertEqual(using(later, True, how), [])
                self.assertEqual(using(later, False, how), [(0, 100)])    # (not read at its time: its first frame)
                self.assertEqual(using(dict(still, static=False), False, how), [])

    def test_a_time_header_names_a_parameter(self):
        from kiasecut import fx
        d = fx.parse('// @param on bool false\n// @time gone\nvec4 effect(vec2 uv) { return src(uv) * time; }', "t")
        self.assertIn("@time", d.error)
        d = fx.parse('// @param rate float 1\n// @time rate != 0\nvec4 effect(vec2 uv) { return src(uv) * time; }', "t")
        self.assertIsNone(d.error)
        self.assertFalse(fx.reads_time(d, {"rate": 0.0}))
        self.assertTrue(fx.reads_time(d, {"rate": 2.0}))

    def test_still_effects_and_masks_stay_still(self):
        c = shape("a", 0, 10, effects=[effect("builtin:blur", radius=5.0), effect("builtin:blender_glare")],
                  mask={"kind": "rect", "cx": 0.2})
        self.assertEqual(self.spans(c), [(0, 100)])

    def test_a_compound_moves_where_its_content_does(self):
        inner = {"width": 160, "height": 90, "tracks": [
            {"id": "i1", "kind": "video", "clips": [shape("x", 0, 2)]},
            {"id": "i2", "kind": "video", "clips": [shape("y", 2, 1, transform={"x": KEYS, "y": 0.0, "scale": 1.0,
                                                                                "rotation": 0.0, "opacity": 1.0})]}]}
        clip = {"id": "k", "type": "compound", "compound_id": "k1", "compound": inner, "start_us": 1 * S,
                "duration_us": 5 * S, "source_start_us": 0, "transform": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}}
        # (inner 0 - 2 s still, 2 - 3 s moving, after 3 s nothing: shown 1 s later)
        self.assertEqual(self.spans(clip), [(0, 10), (10, 30), (40, 60), (60, 100)])
        fast = dict(clip, speed=2.0)                     # (twice as fast: inner 2 - 3 s at 2 - 2.5 s)
        self.assertEqual(self.spans(fast), [(0, 10), (10, 20), (25, 60), (60, 100)])
        frozen = dict(clip, freeze={"on": True, "src_us": int(2.5 * S)})
        self.assertEqual(self.spans(frozen), [(0, 10), (60, 100)])

    def test_a_static_compound_is_still_unless_an_lfo_swings_it(self):
        inner = {"width": 160, "height": 90, "static": True, "tracks": [
            {"id": "i1", "kind": "video", "clips": [shape("x", 0, 1, transform={"x": KEYS, "y": 0.0, "scale": 1.0,
                                                                                "rotation": 0.0, "opacity": 1.0})]}]}
        clip = {"id": "k", "type": "compound", "compound_id": "k1", "compound": inner, "start_us": 0, "duration_us": 5 * S,
                "source_start_us": 0, "transform": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}}
        self.assertEqual(self.spans(clip, length_s=5), [(0, 50)])          # (its first frame, as a picture)
        swinging = copy.deepcopy(inner)
        swinging["tracks"][0]["clips"][0]["expr"] = {"transform.x": lfo.make()}
        self.assertEqual(self.spans(dict(clip, compound=swinging), length_s=5), [])

    def test_every_frame_of_a_stretch_is_drawn_the_same(self):
        r = render.Renderer()
        v = view(shape("a", 0, 4), text("t1", 1, 2, "一"), text("t2", 3, 3, "二"),
                 shape("m", 5, 2, transform={"x": KEYS, "y": 0.0, "scale": 0.3, "rotation": 0.0, "opacity": 1.0}))
        spans = stillspans.frame_spans(v, render.frame_count(v))
        self.assertTrue(spans)
        for a, b in spans:
            pics = [render.qimage_rgba_bytes(r.render(v, f, 80, 45))[0] for f in sorted({a, (a + b) // 2, b - 1})]
            self.assertTrue(all(p == pics[0] for p in pics), (a, b))
        self.assertNotIn(55, {f for a, b in spans for f in range(a, b)})     # (m moves: 5 - 7 s)


def pic():
    return QImage(4, 4, QImage.Format_RGBA8888)


class Cache(unittest.TestCase):
    def test_one_frame_stands_for_its_stretch(self):
        fc = framecache.FrameCache(1 << 30)
        fc.set_view(view(shape("a", 0, 4), text("t", 1, 2)))
        self.assertEqual(fc.still, [(0, 10), (10, 30), (30, 40), (40, 100)])
        fc.put(15, "g", pic())
        self.assertTrue(all(fc.has(p, "g") for p in range(10, 30)))
        self.assertFalse(fc.has(5, "g") or fc.has(30, "g") or fc.has(15, "other size"))
        fc.put(20, "g", pic())                          # (its stretch has its picture: nothing more kept)
        self.assertEqual(list(fc.frames), [15])
        self.assertIsNotNone(fc.get(29, "g"))
        self.assertEqual(framecache.runs(fc.positions("g")), [(10, 30)])
        fc.drop(14, 16)                                 # (the frame standing for it gone: the stretch is not kept)
        self.assertFalse(fc.has(20, "g"))

    def test_an_edit_that_makes_it_move_stops_it_standing_for_others(self):
        v = view(shape("a", 0, 4))
        fc = framecache.FrameCache(1 << 30)
        fc.set_view(v)
        fc.put(5, "g", pic())
        self.assertTrue(fc.has(30, "g"))
        w = copy.deepcopy(v)
        w["tracks"][0]["clips"][0]["transform"]["x"] = KEYS
        fc.set_view(w)
        self.assertFalse(any(fc.has(p, "g") for p in range(0, 40)))


class Player(unittest.TestCase):
    def test_drawing_ahead_draws_one_frame_of_a_stretch(self):
        import shutil
        import tempfile
        from kiasecut import gpu
        from kiasecut.ui import player
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        gpu.enabled = False
        th = player.QThread()
        w = player.Worker()
        w.moveToThread(th)
        th.started.connect(w.run)
        bars = []
        w.cacheChanged.connect(bars.append, player.Qt.DirectConnection)
        w.set_render_width(160)
        w.set_cache(True, True, 0.05)
        from unittest import mock
        from kiasecut import sysmem
        free = mock.patch.object(sysmem, "available", lambda: (64 << 30, 128 << 30))     # (whatever this machine has free now)
        free.start()
        self.addCleanup(free.stop)
        th.start()
        try:
            w.set_view(view(shape("a", 0, 4), text("t", 1, 2)), d)
            end = time.monotonic() + 20
            while time.monotonic() < end and not (bars and bars[-1] == [(0, 100)]):
                APP.processEvents()
                time.sleep(0.01)
            self.assertEqual(bars[-1], [(0, 100)])
            self.assertEqual(len(w.cache.frames), 4)    # (one frame for each stretch)
        finally:
            w.stop()
            th.quit()
            th.wait(5000)
            gpu.enabled = True


if __name__ == "__main__":
    unittest.main()
