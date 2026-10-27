import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kiasecut import curves, edit, project  # noqa: E402

S = 1_000_000


def clip(cid, start, dur, **kw):
    c = {"id": cid, "type": "image", "name": cid, "start_us": start, "duration_us": dur,
         "source_start_us": 0, "media": {"path": "x.png", "width": 1920, "height": 1080},
         "transform": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}}
    c.update(kw)
    return c


def proj():
    p = project.new()
    p["tracks"] = [
        {"id": "t0", "kind": "video", "name": "v", "clips": [clip("c1", 0, 2 * S), clip("c2", 5 * S, 2 * S)]},
        {"id": "t1", "kind": "video", "name": "v2", "clips": []},
        {"id": "t2", "kind": "audio", "name": "a", "clips": [
            {"id": "c3", "type": "audio", "name": "a", "start_us": 2 * S, "duration_us": 4 * S,
             "source_start_us": 1 * S, "media": {"path": "a.mp3", "duration_us": 10 * S}, "volume": 1.0}]},
    ]
    project.refresh_duration(p)
    return project.link(p)                     # the tracks become the open timeline's


def animated(c):
    # x goes 0 -> 1 over the clip's first second, with a bezier ease
    c["transform"]["x"] = {"keys": [[0, 0.0, 0, 0, 300_000, 0.9], [S, 1.0, -400_000, 0, 0, 0]]}
    return c


class EditTests(unittest.TestCase):
    def test_move_clamps_into_gap(self):
        p = proj()
        edit.move(p, "c1", 4 * S)                 # would overlap c2 at 5 s
        self.assertEqual(edit.find(p, "c1")[1]["start_us"], 3 * S)

    def test_move_to_other_track_and_kind_guard(self):
        p = proj()
        edit.move(p, "c2", 1 * S, "t1")
        self.assertEqual(edit.find(p, "c2")[0]["id"], "t1")
        with self.assertRaises(edit.EditError):
            edit.move(p, "c1", 0, "t2")

    def test_split_keeps_animation_in_place(self):
        p = proj()
        c1 = animated(edit.find(p, "c1")[1])
        before = [curves.value(c1["transform"]["x"], t) for t in range(0, 2 * S, 50_000)]
        right = edit.split(p, "c1", 400_000)
        left = edit.find(p, "c1")[1]
        after = [curves.value(left["transform"]["x"], t) if t < 400_000
                 else curves.value(right["transform"]["x"], t - 400_000)
                 for t in range(0, 2 * S, 50_000)]
        for a, b in zip(before, after):
            self.assertAlmostEqual(a, b, places=9)
        self.assertEqual(right["source_start_us"], 400_000)
        self.assertNotEqual(right["id"], left["id"])

    def test_trim_start_shifts_keys_and_source(self):
        p = proj()
        c1 = animated(edit.find(p, "c1")[1])
        v = curves.value(c1["transform"]["x"], 700_000)
        edit.trim_start(p, "c1", 500_000)
        self.assertEqual(c1["start_us"], 500_000)
        self.assertEqual(c1["duration_us"], 1_500_000)
        self.assertAlmostEqual(curves.value(c1["transform"]["x"], 200_000), v, places=9)

    def test_audio_cannot_trim_past_source(self):
        p = proj()
        edit.trim_start(p, "c3", -5 * S)          # source starts 1 s in: only 1 s of head
        c3 = edit.find(p, "c3")[1]
        self.assertEqual((c3["start_us"], c3["source_start_us"]), (1 * S, 0))
        edit.trim_end(p, "c3", 60 * S)             # 10 s source
        self.assertEqual(c3["start_us"] + c3["duration_us"], c3["start_us"] + 10 * S)

    def test_trim_end_stops_at_neighbour(self):
        p = proj()
        edit.trim_end(p, "c1", 9 * S)
        self.assertEqual(edit.find(p, "c1")[1]["duration_us"], 5 * S)

    def test_undo_redo(self):
        p = proj()
        h = edit.History(p)
        snap = copy.deepcopy(p)
        h.do("split", edit.split, "c1", S)
        h.do("delete", edit.delete, "c2")
        self.assertEqual(len(p["tracks"][0]["clips"]), 2)
        h.undo()
        h.undo()
        self.assertEqual(p, snap)
        h.redo()
        self.assertEqual(len(p["tracks"][0]["clips"]), 3)

    def test_failed_edit_leaves_project_untouched(self):
        p = proj()
        h = edit.History(p)
        snap = copy.deepcopy(p)
        with self.assertRaises(edit.EditError):
            h.do("split", edit.split, "c1", 10 * S)
        self.assertEqual(p, snap)
        self.assertEqual(h.undo_stack, [])

    def test_add_text_and_edit(self):
        p = proj()
        c = edit.add_text(p, 1 * S, "你好")
        self.assertEqual(c["type"], "text")
        self.assertTrue(any(c in t["clips"] for t in p["tracks"] if t["kind"] == "text"))
        self.assertLess([t["kind"] for t in p["tracks"]].index("text"),
                        [t["kind"] for t in p["tracks"]].index("audio"))
        edit.set_text(p, c["id"], content="再見", letter_spacing=0.2)
        self.assertEqual(c["text"]["content"], "再見")
        edit.set_transform(p, c["id"], "y", -0.5)
        self.assertEqual(c["transform"]["y"], -0.5)

    def test_merged_edits_undo_together(self):
        p = proj()
        h = edit.History(p)
        for v in (0.1, 0.2, 0.3):
            h.do("x", edit.set_transform, "c1", "x", v, merge=("x", "c1"))
        self.assertEqual(len(h.undo_stack), 1)
        h.undo()
        self.assertEqual(edit.find(p, "c1")[1]["transform"]["x"], 0.0)

    def test_keyframed_value_edits_or_adds_key_at_playhead(self):
        p = proj()
        c1 = animated(edit.find(p, "c1")[1])
        with self.assertRaises(edit.EditError):
            edit.set_transform(p, "c1", "x", 0.3)          # needs a time
        edit.set_transform(p, "c1", "x", 0.5, t=S)          # existing key at 1 s
        self.assertEqual(c1["transform"]["x"]["keys"][1][1], 0.5)
        edit.set_transform(p, "c1", "x", 0.2, t=1_500_000)  # no key there: adds one
        self.assertEqual([k[0] for k in c1["transform"]["x"]["keys"]], [0, S, 1_500_000])
        self.assertAlmostEqual(curves.value(c1["transform"]["x"], 1_500_000), 0.2)

    def test_toggle_key(self):
        p = proj()
        c1 = edit.find(p, "c1")[1]
        edit.toggle_key(p, "c1", "transform", "y", 500_000)
        self.assertTrue(curves.is_animated(c1["transform"]["y"]))
        edit.set_transform(p, "c1", "y", 0.4, t=1_500_000)
        self.assertAlmostEqual(curves.value(c1["transform"]["y"], 1_000_000), 0.2)  # linear
        edit.toggle_key(p, "c1", "transform", "y", 500_000)
        edit.toggle_key(p, "c1", "transform", "y", 1_500_000)
        self.assertEqual(c1["transform"]["y"], 0.4)          # back to a plain value
        self.assertEqual(edit.key_times(c1), [])

    def test_easing_presets(self):
        p = proj()
        c1 = edit.find(p, "c1")[1]
        edit.toggle_key(p, "c1", "transform", "opacity", 0)
        edit.set_transform(p, "c1", "opacity", 0.0, t=S)
        x = c1["transform"]["opacity"]
        mid = lambda: curves.value(x, 250_000)
        self.assertAlmostEqual(mid(), 0.75)
        edit.set_easing(p, "c1", "transform", "opacity", 0, "ease_in")
        self.assertGreater(mid(), 0.75)                       # starts slowly
        self.assertEqual(edit.easing_at(x, 0), "ease_in")
        edit.set_easing(p, "c1", "transform", "opacity", 0, "ease_out")
        self.assertLess(mid(), 0.75)
        edit.set_easing(p, "c1", "transform", "opacity", 0, "linear")
        self.assertAlmostEqual(mid(), 0.75)

    def test_masks(self):
        p = proj()
        c1 = edit.find(p, "c1")[1]
        edit.set_mask(p, "c1", "circle")
        m = c1["mask"]
        self.assertAlmostEqual(m["w"] * 1920, m["h"] * 1080)  # round on a 16:9 picture
        edit.set_param(p, "c1", "mask", "cx", 0.3)
        edit.set_mask(p, "c1", "rectangle")                     # keeps the position
        self.assertEqual(c1["mask"]["cx"], 0.3)
        edit.toggle_key(p, "c1", "mask", "w", 0)
        edit.set_param(p, "c1", "mask", "w", 0.9, t=S)
        self.assertEqual(edit.key_times(c1), [0, S])
        edit.set_mask_invert(p, "c1", True)
        self.assertTrue(c1["mask"]["invert"])
        edit.set_mask(p, "c1", None)
        self.assertNotIn("mask", c1)
        with self.assertRaises(edit.EditError):
            edit.set_mask(p, "c3", "line")                      # audio


class CopyPasteTests(unittest.TestCase):
    def test_paste_keeps_spacing_and_picks_free_tracks(self):
        p = proj()
        payload = edit.copy_clips(p, ["c2", "c1"])           # c1 at 0, c2 at 5 s
        new = edit.paste_clips(p, p, payload, 10 * S)
        self.assertEqual([c["start_us"] for c in new], [10 * S, 15 * S])
        self.assertEqual(len({c["id"] for c in new} | {"c1", "c2"}), 4)
        self.assertTrue(all(c in edit.find(p, c["id"]) for c in new))
        self.assertEqual({edit.find(p, c["id"])[0]["id"] for c in new}, {"t0"})   # their own track
        again = edit.paste_clips(p, p, payload, 10 * S)         # now taken: another track, spaced the same
        self.assertEqual([c["start_us"] for c in again], [10 * S, 15 * S])
        self.assertNotEqual(edit.find(p, again[0]["id"])[0]["id"], "t0")

    def test_paste_into_a_new_track_when_none_is_free(self):
        p = proj()
        n = len(p["tracks"])
        payload = edit.copy_clips(p, ["c1"])
        edit.paste_clips(p, p, payload, 0)                      # c1 is there; t1 is free
        edit.paste_clips(p, p, payload, 0)                      # t0 and t1 are taken now
        self.assertEqual(len(p["tracks"]), n + 1)

    def test_duplicate_goes_after_the_last_clip(self):
        p = proj()
        new = edit.duplicate_clips(p, p, ["c1"])
        self.assertEqual(new[0]["start_us"], 2 * S)
        self.assertEqual(edit.find(p, new[0]["id"])[0]["id"], "t0")

    def test_audio_stays_on_audio(self):
        p = proj()
        new = edit.paste_clips(p, p, edit.copy_clips(p, ["c3"]), 0)
        self.assertEqual(edit.find(p, new[0]["id"])[0]["kind"], "audio")

    def test_delete_compound_with_its_uses(self):
        p = proj()
        tl2 = edit.add_timeline(p)                              # an empty second timeline, now open
        first = p["timelines"][0]["id"]
        clip_ = edit.place_compound(p, p, first, None, 0)
        edit.make_unique(p, p, clip_["id"])
        kid = next(iter(p["compounds"]))
        with self.assertRaises(edit.EditError):
            edit.delete_compound(p, kid)                        # used: needs force
        edit.delete_compound(p, kid, force=True)
        self.assertEqual(p["compounds"], {})
        self.assertFalse(any(c["type"] == "compound" for t in tl2["tracks"] for c in t["clips"]))

    def test_shuffle_keeps_the_places(self):
        import random
        p = proj()
        t1 = p["tracks"][1]["clips"]
        t1 += [clip("a", 0, S), clip("b", S, 2 * S), clip("c", 4 * S, S)]     # a gap of 1 s before c
        edit.shuffle_clips(p, ["a", "b", "c"], random.Random(1))
        got = [(c["id"], c["start_us"], edit.end(c)) for c in p["tracks"][1]["clips"]]
        self.assertNotEqual([g[0] for g in got], ["a", "b", "c"])
        self.assertEqual((got[0][1], got[-1][2]), (0, 5 * S))           # the same span
        self.assertEqual((got[1][1] - got[0][2], got[2][1] - got[1][2]), (0, S))   # the gaps kept

    def test_reverse_rows_turns_the_stack_over(self):
        p = proj()                                                   # t0: c1 0-2, c2 5-7; t1 empty
        p["tracks"].insert(2, {"id": "t9", "kind": "video", "name": "v3", "clips": [clip("d", 0, S)]})
        p["tracks"][1]["clips"].append(clip("b", 0, 2 * S))
        self.assertFalse(edit.can_reverse_rows(p, ["c1", "c2"]))     # (one track: nothing to turn)
        self.assertTrue(edit.can_reverse_rows(p, ["c1", "b", "d"]))
        edit.reverse_rows(p, ["c1", "b", "d"])
        on = lambda cid: edit.find(p, cid)[0]["id"]
        self.assertEqual((on("d"), on("b"), on("c1"), on("c2")), ("t0", "t1", "t9", "t0"))   # middle stays
        self.assertEqual((edit.find(p, "d")[1]["start_us"], edit.find(p, "c1")[1]["start_us"]), (0, 0))
        self.assertEqual(edit.find(p, "c3")[0]["id"], "t2")         # sound stays among sound

    def test_reverse_rows_refuses_without_room(self):
        p = proj()
        p["tracks"][1]["clips"].append(clip("b", 4 * S, 2 * S))     # c2 (5-7, stays) is in its way on t0
        before = [[c["id"] for c in t["clips"]] for t in p["tracks"]]
        with self.assertRaises(edit.EditError):
            edit.reverse_rows(p, ["c1", "b"])
        self.assertEqual([[c["id"] for c in t["clips"]] for t in p["tracks"]], before)

    def test_clone_compound_clip_and_entry(self):
        p = proj()
        edit.add_timeline(p)
        clip_ = edit.place_compound(p, p, p["timelines"][0]["id"], None, 0)
        edit.make_unique(p, p, clip_["id"])
        kid = clip_["compound_id"]
        new = edit.clone_clips(p, p, [clip_["id"]])             # 建立獨立副本: its own compound
        self.assertEqual(len(new), 1)
        self.assertNotEqual(new[0]["compound_id"], kid)
        self.assertEqual(new[0]["start_us"], clip_["start_us"] + clip_["duration_us"])
        self.assertIsNot(new[0]["compound"]["tracks"], clip_["compound"]["tracks"])
        k2 = edit.clone_compound(p, kid)                        # from the compound list
        self.assertEqual(p["compounds"][k2]["name"], p["compounds"][kid]["name"] + " 副本")
        self.assertFalse(project.compound_uses(p).get(k2))


if __name__ == "__main__":
    unittest.main()
