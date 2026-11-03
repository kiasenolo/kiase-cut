"""Node effects keep the pictures of their costly nodes between evaluations (nodegraph.Cache): a node is drawn again only
when something it depends on changes - its settings, a picture that goes into it, the size, the time when it reads it -
and never from a picture of the clip it did not read at the time."""
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kiasecut import fx, nodegraph as ng  # noqa: E402

W = H = 8
GENERATOR = """// @filter Gen
// @passes 2
// @param k float 0.5 0 1 "k"
vec4 effect(vec2 uv) { return pass_index == 0 ? vec4(0.0) : vec4(k, uv.x, 0.0, 1.0); }
"""
READER = """// @filter Read
// @passes 2
// @param k float 0.5 0 1 "k"
vec4 effect(vec2 uv) { return pass_index == 0 ? src(uv) : src(uv) * k; }
"""
TIMED = """// @filter Timed
// @passes 2
vec4 effect(vec2 uv) { return pass_index == 0 ? vec4(0.0) : vec4(fract(time), 0.0, 0.0, 1.0); }
"""


class CacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.eng = fx.Engine()
        except fx.FilterError as exc:
            raise unittest.SkipTest(str(exc))
        cls.dir = tempfile.mkdtemp()
        cls.refs = {}
        for name, text in (("gen", GENERATOR), ("read", READER), ("timed", TIMED)):
            path = os.path.join(cls.dir, name + ".glsl")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            cls.refs[name] = path
        cls.draws = []
        real = cls.eng.run_outputs

        def counted(d, *a, **k):
            cls.draws.append(d.name)
            return real(d, *a, **k)
        cls.eng.run_outputs = counted

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.pool = ng.Pool(self.eng)
        self.cache = ng.Cache()
        self.draws.clear()

    def chain(self, *names):
        """input -> filters in a row -> output; the node ids."""
        g = ng.new_graph()
        prev, ids = "input", []
        for name in names:
            nid = ng.add_node(g, {"type": ng.FILTER, "ref": self.refs.get(name, name)})
            ng.connect(g, prev, nid, "src")
            prev = nid
            ids.append(nid)
        ng.connect(g, prev, "output", "src")
        return g, ids

    def go(self, g, params=None, rgba=(255, 0, 0, 255), t=0, tap=None, stamp=None, picture=None, cache="own", scope="e1"):
        cache = self.cache if cache == "own" else cache
        with self.eng.ctx:
            src = self.eng.ctx.texture((W, H), 4, np.tile(np.array(rgba, np.uint8), (H, W, 1)).tobytes())
            tex, owner = ng.evaluate(self.eng, g, params or {}, src, W, H, self.pool.alloc, self.pool.free, t=t, tap=tap, stamp=stamp,
                                     picture=picture, cache=cache, scope=scope)
            out = ng.read_rgba8(tex).copy()
            if owner is not None:
                self.pool.free(owner)
        return out

    def test_a_costly_node_is_drawn_once_while_nothing_changes(self):
        g, (a,) = self.chain("gen")
        params = {a + ".k": 0.25}
        first = self.go(g, params)
        self.assertEqual(self.draws, ["Gen"])
        again = self.go(g, params)
        self.assertEqual(self.draws, ["Gen"])                              # (kept: not drawn again)
        self.assertTrue(np.array_equal(first, again))
        self.assertEqual(len(self.cache.items), 1)
        self.go(g, {a + ".k": 0.75})
        self.assertEqual(self.draws, ["Gen", "Gen"])                       # (a setting changed)
        self.assertEqual(int(self.go(g, {a + ".k": 0.75})[0, 0, 0]), 191)
        self.assertEqual(self.draws, ["Gen", "Gen"])

    def test_without_a_cache_everything_is_drawn_every_time(self):
        g, _ = self.chain("gen")
        self.go(g, cache=None)
        self.go(g, cache=None)
        self.assertEqual(self.draws, ["Gen", "Gen"])

    def test_a_node_that_reads_the_clip_follows_the_clip(self):
        g, (a,) = self.chain("read")
        red = self.go(g, {a + ".k": 1.0}, rgba=(255, 0, 0, 255))
        blue = self.go(g, {a + ".k": 1.0}, rgba=(0, 0, 255, 255))
        self.assertEqual((tuple(red[0, 0]), tuple(blue[0, 0])), ((255, 0, 0, 255), (0, 0, 255, 255)))
        self.assertEqual(self.draws, ["Read", "Read"])
        self.assertEqual(len(self.cache.items), 0)

    def test_a_node_after_one_that_reads_the_clip_follows_it_too(self):
        g, (a, b) = self.chain("read", "gen")                              # (the generator ignores its input: kept)
        params = {a + ".k": 1.0, b + ".k": 0.5}
        self.go(g, params, rgba=(255, 0, 0, 255))
        self.go(g, params, rgba=(0, 0, 255, 255))
        self.assertEqual(self.draws.count("Gen"), 1)                       # (once: it does not read the clip)
        g2, (a2, b2, c2) = self.chain("gen", "read", "read")               # (the last two follow what the clip's pictures make of the first)
        self.draws.clear()
        params = {a2 + ".k": 0.3, b2 + ".k": 1.0, c2 + ".k": 1.0}
        self.go(g2, params, rgba=(255, 0, 0, 255))
        self.go(g2, params, rgba=(0, 0, 255, 255))
        self.assertEqual(self.draws, ["Gen", "Read", "Read"])              # (the others read the generator's picture only: kept too)

    def test_the_time_matters_to_a_filter_that_reads_it(self):
        g, _ = self.chain("timed")
        a = self.go(g, t=0)
        b = self.go(g, t=500_000)
        self.assertEqual(self.draws, ["Timed", "Timed"])
        self.assertNotEqual(int(a[0, 0, 0]), int(b[0, 0, 0]))
        self.go(g, t=500_000)
        self.assertEqual(self.draws, ["Timed", "Timed"])
        g2, _ = self.chain("gen")
        self.go(g2, t=0)
        self.go(g2, t=900_000)
        self.assertEqual(self.draws.count("Gen"), 1)                       # (one that does not read it keeps its picture)

    def test_what_is_upstream_stays_while_a_later_node_changes(self):
        g, (a, b) = self.chain("gen", "read")
        self.go(g, {a + ".k": 0.5, b + ".k": 1.0})
        self.assertEqual(self.draws, ["Gen", "Read"])
        self.draws.clear()
        self.go(g, {a + ".k": 0.5, b + ".k": 0.5})                        # (the last one changes: the generator is not drawn)
        self.assertEqual(self.draws, ["Read"])
        self.draws.clear()
        self.go(g, {a + ".k": 0.5, b + ".k": 0.5})
        self.assertEqual(self.draws, [])
        self.go(g, {a + ".k": 0.25, b + ".k": 0.5})                       # (the first changes: both are)
        self.assertEqual(self.draws, ["Gen", "Read"])

    def test_every_picture_still_goes_to_the_thumbnails(self):
        g, (a, b) = self.chain("gen", "read")
        params = {a + ".k": 0.5, b + ".k": 1.0}
        self.go(g, params)
        seen = []
        self.go(g, params, tap=lambda n, o, tex, sig: seen.append(n))
        self.assertEqual(self.draws, ["Gen", "Read"])                      # (nothing drawn again)
        self.assertTrue({"input", a, b} <= set(seen), seen)

    def test_a_thumbnail_is_read_back_again_only_when_its_picture_changed(self):
        g, (a, b) = self.chain("gen", "read")
        memo, taps, reads = {}, [], []
        real = ng.small_rgba8
        ng.small_rgba8 = lambda tex, size=96: (reads.append(1), real(tex, size))[1]
        self.addCleanup(setattr, ng, "small_rgba8", real)

        def frame(params):
            store = {}
            self.go(g, params, tap=ng.thumb_tap(store, memo=memo))
            return store
        first = frame({a + ".k": 0.5, b + ".k": 1.0})
        n = len(reads)
        self.assertEqual(frame({a + ".k": 0.5, b + ".k": 1.0}), first)    # (nothing changed: the copies of the last frame, nothing read)
        self.assertEqual(len(reads), n + 1)                                  # (the clip's own picture is read every time)
        again = frame({a + ".k": 0.5, b + ".k": 0.5})                       # (the last one changed: its thumbnail is read, the other's not)
        self.assertEqual(len(reads), n + 3)
        self.assertEqual(again[a], first[a])
        self.assertNotEqual(again[b], first[b])

    def test_what_the_effect_no_longer_draws_is_given_back(self):
        g, (a,) = self.chain("gen")
        self.go(g)
        spare = len(self.pool.spare)
        self.assertEqual(len(self.cache.items), 1)
        self.go(ng.new_graph())                                           # (the same effect, without the node)
        self.assertEqual(self.cache.items, {})
        self.assertEqual(self.cache.bytes, 0)
        self.assertGreater(len(self.pool.spare), spare)

    def test_pictures_no_frame_used_for_a_while_go(self):
        cache = ng.Cache(keep=3)
        g, _ = self.chain("gen")
        self.go(g, cache=cache)
        for _ in range(3):
            cache.frame()
        self.assertEqual(len(cache.items), 1)
        self.go(g, cache=cache)                                            # (used: it stays)
        for _ in range(3):
            cache.frame()
        self.assertEqual(len(cache.items), 1)
        cache.frame()
        self.assertEqual((cache.items, cache.bytes), ({}, 0))
        self.assertEqual(self.draws, ["Gen"])

    def test_a_cache_too_small_still_gives_the_picture(self):
        small = ng.Cache(limit=1)
        g, (a,) = self.chain("gen")
        first = self.go(g, cache=small)
        self.assertTrue(np.array_equal(first, self.go(g, cache=small)))
        self.assertEqual(self.draws, ["Gen", "Gen"])
        self.assertEqual(small.items, {})
        self.assertLessEqual(len(self.pool.spare), 3)                      # (and nothing leaks)

    def test_room_is_made_from_the_pictures_longest_unused_and_never_one_in_use(self):
        size = W * H * 8
        cache = ng.Cache(limit=2 * size)
        for i in range(3):                                                 # (three effects: the first one's picture goes)
            g, _ = self.chain("gen")
            self.go(g, cache=cache, scope=f"e{i}")
        self.assertEqual(sorted(k[0] for k in cache.items), ["e1", "e2"])
        g, (a, b) = self.chain("gen", "read")                              # (two pictures in one evaluation need 2 * size: they fit)
        self.go(g, cache=cache, scope="e9")
        self.assertEqual({k[0] for k in cache.items}, {"e9"})

    def test_a_source_with_no_stamp_is_never_kept_and_one_with_a_stamp_is_kept_while_it_is_the_same(self):
        g = ng.new_graph()
        s = ng.add_node(g, {"type": ng.SOURCE, "kind": "shape", "shape": "star"}, base="s")
        n = ng.add_node(g, {"type": ng.FILTER, "ref": self.refs["read"]})
        ng.connect(g, s, n, "src")
        ng.connect(g, n, "output", "src")
        params = {n + ".k": 1.0}
        shown = {"v": 0}

        def picture(nid, *rest):
            tex = self.eng.ctx.texture((W, H), 4, bytes([shown["v"] or 255, 0, 0, 255] * (W * H)))
            return tex, ng.IDENTITY, None
        self.go(g, params, picture=picture)
        self.go(g, params, picture=picture)
        self.assertEqual(self.draws.count("Read"), 2)                      # (no stamp: drawn every time)
        self.draws.clear()
        for _ in range(2):                                                 # (a stamp that says "not known" for this source is the same)
            self.go(g, params, picture=picture, stamp=lambda nid, *rest: None)
        self.assertEqual(self.draws.count("Read"), 2)
        self.draws.clear()
        stamp = lambda nid, *rest: ("same", shown["v"])  # noqa: E731
        self.go(g, params, picture=picture, stamp=stamp)
        self.go(g, params, picture=picture, stamp=stamp)
        self.assertEqual(self.draws.count("Read"), 1)
        shown["v"] = 100                                                   # (a different picture: drawn again)
        out = self.go(g, params, picture=picture, stamp=stamp)
        self.assertEqual(self.draws.count("Read"), 2)
        self.assertEqual(int(out[0, 0, 0]), 100)


if __name__ == "__main__":
    unittest.main()
