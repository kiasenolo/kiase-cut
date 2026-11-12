import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kiasecut import edit, fx, nodegraph  # noqa: E402
from tests.test_edit import proj  # noqa: E402


class MergeEffects(unittest.TestCase):
    def test_chosen_effects_become_one_node_effect(self):
        p = proj()
        a = edit.add_effect(p, "c1", "builtin:invert")
        b = edit.add_effect(p, "c1", "builtin:blur")
        c = edit.add_effect(p, "c1", "builtin:invert")
        b["enabled"] = False
        merged = edit.merge_effects(p, "c1", [a["id"], b["id"]])
        effects = edit.find(p, "c1")[1]["effects"]
        self.assertEqual([e["id"] for e in effects], [merged["id"], c["id"]])      # (where the first was; the other stays)
        self.assertEqual(merged["filter"], fx.GRAPH)
        g = merged["graph"]
        chain = [l["to"] for l in g["links"]]
        self.assertEqual(len(g["nodes"]), 4)                                       # input, two filters, output
        self.assertEqual(chain[-1], "output")
        blur = next(n for n in g["nodes"].values() if n.get("ref") == "builtin:blur")
        self.assertTrue(blur["mute"])                                              # (a disabled one: a muted node)
        nid = next(k for k, n in g["nodes"].items() if n.get("ref") == "builtin:blur")
        for k, v in b["params"].items():
            self.assertEqual(merged["params"][nodegraph.param_key(nid, k)], v)
        self.assertFalse(nodegraph.has_loop(g))

    def test_what_cannot_be_merged(self):
        p = proj()
        a = edit.add_effect(p, "c1", "builtin:invert")
        a["mix"] = 0.5
        self.assertIsNotNone(edit.merge_problem(a))
        with self.assertRaises(edit.EditError):
            edit.merge_effects(p, "c1", [a["id"]])


class VfxNodeDrag(unittest.TestCase):
    def test_a_merged_effect_can_be_a_vfx_node_and_be_dropped_as_a_filter_clip(self):
        p = proj()
        a = edit.add_effect(p, "c1", "builtin:invert")
        merged = edit.merge_effects(p, "c1", [a["id"]])
        vid = edit.vfx_from_effect(p, "c1", merged["id"], "我的")
        clip = edit.add_vfx_filter_clip(p, vid, 0)
        e = clip["effects"][0]
        self.assertEqual((e["vfx"], clip["type"], clip["name"]), (vid, "filter", "我的"))
        self.assertIs(e["graph"], p["vfx_nodes"][vid]["graph"])                  # (shared, not a copy)

    def test_the_drag_payload(self):
        from kiasecut.ui.vfxnodes import dropped_vfx
        self.assertEqual(dropped_vfx('{"vfx": "vn3"}'), "vn3")
        self.assertIsNone(dropped_vfx("builtin:blur"))
        self.assertIsNone(dropped_vfx('{"effect": {}, "clip": null}'))


if __name__ == "__main__":
    unittest.main()
