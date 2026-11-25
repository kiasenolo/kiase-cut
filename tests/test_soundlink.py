"""Sound in node effects (design/sound-in-compositor.md): the sound links of a node graph, what a 電平 → 數值 node
measures, the analysis it asks for and the picture both renderers draw with its number."""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import shiboken6  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kiasecut import dsp, edit, fx, glrender, nodegraph as ng, project, render, soundmeter, stillspans  # noqa: E402
from kiasecut.ui.node_editor import NodeEditor  # noqa: E402
from tests.test_soundgraph import US, fx as sound_fx  # noqa: E402
from tests.test_soundmeter import BOX, Sounds, make_root  # noqa: E402

APP = QApplication.instance() or QApplication([])
W, H = 32, 18


def ids(e, kind):
    return [i for i, n in e["graph"]["nodes"].items() if n["type"] == kind]


class Graphs(unittest.TestCase):
    """A node effect with 聲音來源 → 電平 → 數值."""

    def setUp(self):
        self.p = project.new(W, H, 10)
        self.p["tracks"].append({"id": "vid", "kind": "video", "name": "V", "clips": [
            {"id": "pic", "type": "image", "name": "g", "start_us": 0, "duration_us": 4 * US, "source_start_us": 0,
             "media": {"path": ":shape:rect", "width": W, "height": H},
             "transform": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}}]})
        self.e = edit.add_effect(self.p, "pic", fx.GRAPH)
        self.g = self.e["graph"]
        self.src = self.add({"type": ng.SOUND_SOURCE})
        self.lvl = self.add({"type": ng.SOUND_LEVEL})

    def add(self, node):
        return edit.add_graph_node(self.p, "pic", self.e["id"], node)

    def blur(self):
        return self.add({"type": ng.FILTER, "ref": "builtin:nodes/exposure"})


class LinkTests(Graphs):
    def test_a_sound_goes_into_an_analysis_node_only(self):
        ex = self.blur()
        ng.connect(self.g, self.src, self.lvl, ng.SOUND_SOCKET)
        ng.connect(self.g, self.lvl, ex, ng.PARAM + "exposure")          # (its number goes wherever a number does)
        for a, b, socket in ((self.src, ex, "src"), (self.src, "output", "src"), ("input", self.lvl, ng.SOUND_SOCKET)):
            before = copy.deepcopy(self.g["links"])
            with self.assertRaises(ng.GraphError):
                ng.connect(self.g, a, b, socket)
            self.assertEqual(self.g["links"], before)

    def test_through_reroutes_in_either_order(self):
        ex, dot = self.blur(), self.add({"type": ng.REROUTE})
        ng.connect(self.g, dot, ex, "src")                                # (nothing feeds it yet: it may carry either)
        with self.assertRaises(ng.GraphError):
            ng.connect(self.g, self.src, dot, "src")
        ng.disconnect(self.g, ex, "src")
        ng.connect(self.g, dot, self.lvl, ng.SOUND_SOCKET)
        with self.assertRaises(ng.GraphError):
            ng.connect(self.g, "input", dot, "src")
        ng.connect(self.g, self.src, dot, "src")
        self.assertEqual(ng.sound_source(self.g, self.lvl), self.src)
        with self.assertRaises(ng.GraphError):
            ng.connect(self.g, dot, ex, "src")

    def test_node_spec(self):
        spec = lambda: soundmeter.node_spec(self.g, self.e.get("sources"), self.lvl)
        self.assertIsNone(spec())                                         # not wired
        ng.connect(self.g, self.src, self.lvl, ng.SOUND_SOCKET)
        self.assertIsNone(spec())                                         # nothing chosen
        edit.set_graph_sound(self.p, "pic", self.e["id"], self.src, "tl1", "t1")
        self.assertEqual(spec(), soundmeter.make("tl1", "t1"))
        edit.set_graph_meter(self.p, "pic", self.e["id"], self.lvl, {"lo_hz": 5000.0, "hi_hz": 1.0, "release": 99.0})
        self.assertEqual((spec()["lo_hz"], spec()["hi_hz"], spec()["release"]), (5000.0, 5000.0, soundmeter.MAX_RELEASE))
        for nid in (self.src, self.lvl):
            self.g["nodes"][nid]["mute"] = True
            self.assertIsNone(spec())
            del self.g["nodes"][nid]["mute"]
        edit.group_graph_nodes(self.p, "pic", self.e["id"], [self.lvl])   # (through a group's socket)
        self.assertIsNotNone(spec())
        self.assertFalse(ng.sounds_crossed(self.g))

    def test_removing_the_source_takes_its_setting(self):
        edit.remove_graph_node(self.p, "pic", self.e["id"], self.src)
        self.assertNotIn(self.src, self.e.get("sources") or {})

    def test_not_a_still_picture_and_nothing_to_preview_on_a_source(self):
        ex = self.blur()
        ng.connect(self.g, self.lvl, ex, ng.PARAM + "exposure")
        ng.connect(self.g, "input", ex, "src")
        ng.connect(self.g, ex, "output", "src")
        self.assertFalse(stillspans._effect_still(self.e))
        with self.assertRaises(edit.EditError):
            edit.set_graph_viewer(self.p, "pic", self.e["id"], self.src)


class PickTests(Graphs):
    """聲音來源 fed by an effect parameter: every clip chooses its own."""

    def params_node(self):
        return self.add({"type": ng.PARAMS})

    def chosen(self):
        return ng.sound_choice(self.g, self.e.get("sources"), self.e["params"], self.src)

    def test_exposing_starts_at_the_node_s_own_choice_and_gives_it_back(self):
        ng.connect(self.g, self.src, self.lvl, ng.SOUND_SOCKET)
        edit.set_graph_sound(self.p, "pic", self.e["id"], self.src, "tl1", "t1")
        name = edit.expose_graph_param(self.p, "pic", self.e["id"], self.params_node(), self.src, ng.SOUND_PICK)
        x = ng.exposed(self.g)[0]
        self.assertEqual((x["type"], x["label"], x["default"]), ("sound", "聲音來源", "tl1/t1"))
        self.assertEqual(self.e["params"][ng.expose_key(name)], "tl1/t1")
        self.assertIn(ng.expose_key(name), [q.name for q in fx.def_of(self.e).params])
        self.assertFalse(ng.sounds_crossed(self.g))
        edit.set_param(self.p, "pic", "fx:" + self.e["id"], ng.expose_key(name), "tl1/master", 0)
        self.assertEqual(self.chosen(), ("tl1", "master"))
        spec = soundmeter.node_spec(self.g, self.e["sources"], self.lvl, self.e["params"])
        self.assertEqual((spec["level"], spec["channel"]), ("tl1", "master"))
        edit.set_param(self.p, "pic", "fx:" + self.e["id"], ng.expose_key(name), "", 0)
        self.assertIsNone(soundmeter.node_spec(self.g, self.e["sources"], self.lvl, self.e["params"]))
        ng.remove_exposed(self.g, self.e["params"], name)
        self.assertEqual(self.chosen(), ("tl1", "t1"))

    def test_only_a_sound_parameter_goes_into_the_source(self):
        pn, ex = self.params_node(), self.blur()
        sound = ng.add_exposed(self.g, self.e["params"], "sound")
        number = ng.add_exposed(self.g, self.e["params"], "float")
        for a, b, socket, out in ((pn, self.src, ng.SOUND_PICK, number), ("input", self.src, ng.SOUND_PICK, None),
                                  (self.lvl, self.src, ng.SOUND_PICK, None), (pn, ex, ng.PARAM + "exposure", sound),
                                  (pn, self.lvl, ng.SOUND_SOCKET, sound)):
            before = copy.deepcopy(self.g["links"])
            with self.assertRaises(ng.GraphError):
                ng.connect(self.g, a, b, socket, out)
            self.assertEqual(self.g["links"], before)
        self.assertFalse(ng.takes_picture(self.g, self.src, ng.SOUND_PICK))
        ng.connect(self.g, pn, self.src, ng.SOUND_PICK, sound)
        self.assertEqual(self.chosen(), ("", ""))

    def test_a_parameter_node_made_by_dragging_out_of_the_socket(self):
        edit.set_graph_sound(self.p, "pic", self.e["id"], self.src, "tl1", "t1")
        edit.add_graph_node_feeding(self.p, "pic", self.e["id"], {"type": ng.PARAMS}, 0, 0, self.src, ng.SOUND_PICK)
        self.assertEqual([x["default"] for x in ng.exposed(self.g)], ["tl1/t1"])


class EditorTests(Graphs):
    def test_letting_go_of_the_box_does_not_delete_the_spectrum_under_the_mouse(self):
        """The edit lays the nodes out again, so it waits for the mouse event to end (else: a crash)."""
        ng.connect(self.g, self.src, self.lvl, ng.SOUND_SOCKET)
        clip = edit.find(self.p, "pic")[1]
        ed = NodeEditor()
        self.addCleanup(ed.deleteLater)
        ed.show_clip(clip)

        def apply(eid, nid, values):                  # (as the window does: the project changes and is shown again)
            edit.set_graph_meter(self.p, "pic", eid, nid, values)
            ed.show_clip(clip)
        ed.meterEdited.connect(apply)
        spectrum = ed.view.items_by_id[self.lvl].spectrum.widget()
        spectrum.done.emit({"lo_hz": 50.0, "hi_hz": 900.0, "floor_db": -30.0, "top_db": -10.0})
        self.assertTrue(shiboken6.isValid(spectrum))
        self.assertEqual(ed.meter_values(self.lvl)["hi_hz"], 900.0)
        APP.processEvents()
        self.assertEqual(self.g["nodes"][self.lvl]["meter"]["hi_hz"], 900.0)
        self.assertEqual(ed.view.items_by_id[self.lvl].spectrum.widget().box["hi_hz"], 900.0)


@unittest.skipUnless(dsp.available(), f"no sound library: {dsp.error()}")
class MeasureTests(Sounds):
    def setUp(self):
        soundmeter.forget()
        self.cache = os.path.join(self.tmp.name, "cache")

    def root(self, nodes=1, channel="t1", start=0.0):
        """Kicks on a muted track at 0.5 and 1.5 s; a white-ish picture from `start` whose exposure follows them."""
        root = make_root([{"clips": [self.kick_clip()], "muted": True}], rack=[])
        pic = os.path.join(self.tmp.name, "grey.png")
        img = QImage(W, H, QImage.Format_RGB32)
        img.fill(QColor(60, 60, 60))
        img.save(pic)
        clip = {"id": "pic", "type": "image", "name": "灰", "start_us": int(start * US), "duration_us": 2 * US,
                "source_start_us": 0, "media": {"path": pic, "width": W, "height": H},
                "transform": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}}
        root["tracks"].insert(0, {"id": "vid", "kind": "video", "name": "V", "clips": [clip]})
        root.update(width=W, height=H, duration_us=4 * US)
        e = edit.add_effect(root, "pic", fx.GRAPH)
        g, eid = e["graph"], e["id"]
        add = lambda node: edit.add_graph_node(root, "pic", eid, node)
        src = add({"type": ng.SOUND_SOURCE})
        edit.set_graph_sound(root, "pic", eid, src, "tl1", channel)
        levels = [add({"type": ng.SOUND_LEVEL}) for _ in range(nodes)]
        for lvl in levels:
            edit.set_graph_meter(root, "pic", eid, lvl, BOX)
            ng.connect(g, src, lvl, ng.SOUND_SOCKET)
        ex = add({"type": ng.FILTER, "ref": "builtin:nodes/exposure"})
        ng.connect(g, "input", ex, "src")
        ng.connect(g, ex, "output", "src")
        ng.connect(g, levels[0], ex, ng.PARAM + "exposure")
        return root, e, src, levels

    def read(self, e, lvl, seconds):
        return soundmeter.hearing(e, seconds * US)(lvl)

    def test_nodes_that_measure_the_same_share_one_job(self):
        root, e, _src, levels = self.root(nodes=3)
        self.assertTrue(soundmeter.wanted(root))
        todo = soundmeter.plan(root)
        self.assertEqual(len(todo.jobs), 1)
        self.assertEqual(self.read(e, levels[0], 0.6), 0.0)             # not measured yet
        self.assertEqual(soundmeter.run(todo, self.cache), {})
        for lvl in levels:
            self.assertAlmostEqual(self.read(e, lvl, 0.6), 1.0, delta=0.01)
            self.assertEqual(self.read(e, lvl, 1.0), 0.0)
        self.assertIsNotNone(soundmeter.node_sound(soundmeter.node_spec(e["graph"], e["sources"], levels[0])))
        self.assertFalse(soundmeter.plan(root).stale())

    def test_a_changed_box_reads_the_old_number_until_measured(self):
        root, e, _src, (lvl,) = self.root()
        soundmeter.prepare(root, self.cache)
        self.assertGreater(self.read(e, lvl, 0.6), 0.9)
        edit.set_graph_meter(root, "pic", e["id"], lvl, {"lo_hz": 2000.0, "hi_hz": 8000.0})
        self.assertGreater(self.read(e, lvl, 0.6), 0.9)
        self.assertTrue(soundmeter.plan(root).stale())
        soundmeter.prepare(root, self.cache)
        self.assertEqual(self.read(e, lvl, 0.6), 0.0)

    def test_a_missing_source_reads_0_and_stops_an_export(self):
        root, e, src, (lvl,) = self.root()
        soundmeter.prepare(root, self.cache)
        self.assertGreater(self.read(e, lvl, 0.6), 0.9)
        edit.set_graph_sound(root, "pic", e["id"], src, "tl1", "gone")
        said = []
        with self.assertRaisesRegex(RuntimeError, "找不到"):
            soundmeter.require(root, self.cache)
        soundmeter.require(root, self.cache, allow_errors=True, say=said.append)
        self.assertIn("找不到", said[0])
        self.assertEqual(self.read(e, lvl, 0.6), 0.0)                    # (not what it read before)

    def test_a_node_nothing_reads_does_not_stop_an_export(self):
        root, e, _src, (lvl,) = self.root(channel="gone")
        ex = next(i for i, n in e["graph"]["nodes"].items() if n.get("ref") == "builtin:nodes/exposure")
        ng.disconnect(e["graph"], ex, ng.PARAM + "exposure")
        soundmeter.require(root, self.cache)

    def test_a_switched_off_effect_asks_for_nothing(self):
        root, e, _src, _levels = self.root()
        e["disabled"] = True
        self.assertFalse(soundmeter.wanted(root))

    def test_after_the_parameters_its_sound_follows(self):
        root, e, _src, (lvl,) = self.root()
        root["tracks"].append({"id": "t2", "kind": "audio", "name": "A2", "clips": [self.kick_clip("k2")], "muted": True})
        edit.add_rack_param(root, "amount", 0.0)
        edit.set_rack_sound(root, root["rack"][0]["id"], soundmeter.make("tl1", "t2", **BOX))
        gain = sound_fx("gain", "g1", gain=0.0)
        gain["expr"] = {"gain": "amount * 60 - 60"}                      # (heard only while the other track hits)
        root["tracks"][1]["sound_effects"] = [gain]
        todo = soundmeter.plan(root)
        self.assertEqual([j.rid.partition(":")[0] for j in todo.jobs], [root["rack"][0]["id"], "node"])
        self.assertEqual(soundmeter.run(todo, self.cache), {})
        self.assertGreater(self.read(e, lvl, 0.65), 0.9)

    def test_forgotten_with_the_nodes(self):
        root, e, _src, _levels = self.root()
        soundmeter.prepare(root, self.cache)
        e["disabled"] = True
        self.assertTrue(soundmeter.stale_without(root))
        soundmeter.prepare(root, self.cache)
        self.assertFalse(soundmeter.stale_without(root))

    def test_each_effect_hears_what_it_chose(self):
        root, e, src, (lvl,) = self.root()
        root["tracks"].append({"id": "t2", "kind": "audio", "name": "A2", "muted": True, "clips": [
            self.clip("late", self.kicks, 1.0, 2.0)]})                  # (the same kicks a second later)
        root["tracks"][-1]["clips"][0]["media"]["duration_us"] = 2 * US
        pn = edit.add_graph_node(root, "pic", e["id"], {"type": ng.PARAMS})
        name = edit.expose_graph_param(root, "pic", e["id"], pn, src, ng.SOUND_PICK)
        other = copy.deepcopy(e)
        other["id"] = "e2"
        other["graph"], other["sources"] = e["graph"], e["sources"]      # (one graph, as a shared VFX Node's)
        other["params"][ng.expose_key(name)] = "tl1/t2"
        root["tracks"][0]["clips"][0]["effects"].append(other)
        self.assertEqual(len(soundmeter.plan(root).jobs), 2)
        soundmeter.require(root, self.cache)
        self.assertEqual((round(self.read(e, lvl, 0.6)), round(self.read(other, lvl, 0.6))), (1, 0))
        self.assertEqual((round(self.read(e, lvl, 2.6)), round(self.read(other, lvl, 2.6))), (0, 1))

    def brightness(self, renderer, root, *seconds):
        out = []
        for s in seconds:
            img = renderer.render(root, round(s * root["fps"]), W, H)
            self.assertEqual(renderer.errors, [])
            out.append(img.pixelColor(W // 2, H // 2).red())
        return out

    def draws(self, renderer):
        # the clip starts at 1.0 s: it reads the sound at 1.0 s + its own time, so the kick at 1.5 s shows at 1.6
        root, _e, _src, _levels = self.root(start=1.0)
        soundmeter.require(root, self.cache)
        quiet, hit, after = self.brightness(renderer, root, 1.2, 1.6, 2.2)
        self.assertEqual((quiet, after), (60, 60))
        self.assertAlmostEqual(hit, 120, delta=3)                        # exposure +1: twice as bright

    def test_the_cpu_renderer_draws_with_the_number(self):
        r = render.Renderer(lambda *a: None)
        if r.engine() is None:
            self.skipTest("no OpenGL")
        self.draws(r)

    def test_the_gpu_renderer_draws_with_the_number(self):
        r = glrender.make(lambda *a: None)
        if not isinstance(r, glrender.GLRenderer):
            self.skipTest("no OpenGL")
        self.draws(r)

class PictureTests(Graphs):
    """波形 and 頻譜: source nodes drawn of the sound wired into them."""

    def pictures(self):
        return [self.add({"type": ng.SOURCE, "kind": k}) for k in ng.SOUND_PICTURES]

    def test_a_new_one_has_a_place_and_its_fields(self):
        wave, spec = self.pictures()
        for nid in (wave, spec):
            self.assertEqual(self.e["sources"][nid]["kind"], self.g["nodes"][nid]["kind"])
            self.assertIn(ng.SOUND_SOCKET, [s for s, _label in ng.sockets(self.g["nodes"][nid])])
            self.assertEqual(ng.socket_kind(self.g, nid, ng.SOUND_SOCKET), "sound")
            self.assertFalse(ng.takes_picture(self.g, nid, ng.SOUND_SOCKET))
        self.assertEqual(self.e["params"][ng.param_key(wave, "style")], "線")
        self.assertEqual(self.e["params"][ng.param_key(spec, "style")], "長條")
        self.assertEqual([ng.title(self.g["nodes"][n]) for n in (wave, spec)], ["波形", "頻譜"])

    def test_it_takes_a_sound_and_gives_a_picture(self):
        wave, spec = self.pictures()
        ng.connect(self.g, self.src, wave, ng.SOUND_SOCKET)
        dot = self.add({"type": ng.REROUTE})
        ng.connect(self.g, self.src, dot, "src")
        ng.connect(self.g, dot, spec, ng.SOUND_SOCKET)
        with self.assertRaisesRegex(Exception, "聲音線"):
            ng.connect(self.g, "input", wave, ng.SOUND_SOCKET)
        ex = self.blur()
        ng.connect(self.g, wave, ex, "src")
        with self.assertRaisesRegex(Exception, "聲音線"):
            ng.connect(self.g, self.src, ex, "src")
        self.assertFalse(ng.sounds_crossed(self.g))

    def test_what_it_hears(self):
        wave, _spec = self.pictures()
        self.assertIsNone(soundmeter.picture_spec(self.g, self.e["sources"], wave))
        ng.connect(self.g, self.src, wave, ng.SOUND_SOCKET)
        self.assertIsNone(soundmeter.picture_spec(self.g, self.e["sources"], wave))      # (nothing chosen)
        edit.set_graph_sound(self.p, "pic", self.e["id"], self.src, "tl1", "t1")
        self.assertEqual(soundmeter.picture_spec(self.g, self.e["sources"], wave), {"level": "tl1", "channel": "t1"})

    def test_a_picture_of_a_sound_is_not_a_still(self):
        wave, _spec = self.pictures()
        ng.connect(self.g, wave, "output", "src")
        self.assertFalse(stillspans._effect_still(self.e))


class OutlineTests(unittest.TestCase):
    """The waveform line, drawn as the outline of what a round pen would cover."""

    def test_a_flat_line_is_as_thick_as_the_pen(self):
        from kiasecut import soundpictures
        for samples in (10, 1000):                               # (fewer samples than columns, and more)
            xs, top, bottom = soundpictures.outline(np.full(samples, 20.0), 100, 3.0)
            self.assertEqual((len(xs), float(top.min()), float(top.max()), float(bottom.min()), float(bottom.max())),
                             (100, 17.0, 17.0, 23.0, 23.0))

    def test_a_jump_leaves_no_gap(self):
        from kiasecut import soundpictures
        for y in (np.array([0.0] * 5 + [50.0] * 5), np.where(np.arange(5000) % 7 < 3, 0.0, 50.0)):
            _xs, top, bottom = soundpictures.outline(y, 100, 1.0)
            self.assertTrue(np.all(top[1:] <= bottom[:-1]) and np.all(bottom[1:] >= top[:-1]))      # (neighbours overlap)
            self.assertEqual((float(top.min()), float(bottom.max())), (-1.0, 51.0))


@unittest.skipUnless(dsp.available(), f"no sound library: {dsp.error()}")
class PictureDrawTests(Sounds):
    """Kicks on a muted track at 0.5 and 1.5 s, drawn by a 波形 or 頻譜 node."""

    def setUp(self):
        soundmeter.forget()
        self.cache = os.path.join(self.tmp.name, "cache")

    def root(self, kind, channel="t1", start=0.0, **values):
        root = make_root([{"clips": [self.kick_clip()], "muted": True}], rack=[])
        clip = {"id": "pic", "type": "image", "name": "圖", "start_us": int(start * US), "duration_us": 2 * US,
                "source_start_us": 0, "media": {"path": ":shape:rect", "width": W, "height": H},
                "transform": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}}
        root["tracks"].insert(0, {"id": "vid", "kind": "video", "name": "V", "clips": [clip]})
        root.update(width=160, height=90, duration_us=4 * US)
        e = edit.add_effect(root, "pic", fx.GRAPH)
        g, eid = e["graph"], e["id"]
        add = lambda node: edit.add_graph_node(root, "pic", eid, node)
        src = add({"type": ng.SOUND_SOURCE})
        edit.set_graph_sound(root, "pic", eid, src, "tl1", channel)
        pic = add({"type": ng.SOURCE, "kind": kind})
        ng.connect(g, src, pic, ng.SOUND_SOCKET)
        ng.connect(g, pic, "output", "src")
        e["sources"][pic]["h"] = 1.0
        for name, v in values.items():
            e["params"][ng.param_key(pic, name)] = v
        return root, e, pic

    def lit(self, renderer, root, seconds):
        """How many pixels of the frame are bright, and the rows the highest and lowest of them are in."""
        img = renderer.render(root, round(seconds * root["fps"]), 160, 90)
        self.assertEqual(renderer.errors, [])
        rows = [y for y in range(90) for x in range(160) if img.pixelColor(x, y).red() > 96]
        return len(rows), (min(rows), max(rows)) if rows else None

    def check_wave(self, renderer, **values):
        root, _e, _pic = self.root("waveform", start=1.0, length_ms=100.0, line_w=2.0, **values)
        soundmeter.require(root, self.cache)
        _n, quiet = self.lit(renderer, root, 1.2)
        n, hit = self.lit(renderer, root, 1.6)               # (the clip starts at 1 s: the kick at 1.5 s)
        self.assertLessEqual(quiet[1] - quiet[0], 3)         # a flat line
        self.assertGreater(hit[1] - hit[0], 15)              # +-0.25 of 90 rows
        self.assertAlmostEqual(sum(hit) / 2, 45, delta=3)
        return n

    def check_spectrum(self, renderer, **values):
        root, _e, _pic = self.root("spectrum", start=1.0, decay=0.0, **values)
        soundmeter.require(root, self.cache)
        self.assertEqual(self.lit(renderer, root, 1.2)[0] if values.get("style") != "曲線" else 0, 0)
        n, rows = self.lit(renderer, root, 1.6)
        self.assertGreater(n, 20)
        self.assertLess(rows[0], 70)                         # a tall low bar

    def draws(self, renderer):
        line = self.check_wave(renderer)
        self.assertGreater(self.check_wave(renderer, style="填滿"), line)
        self.check_spectrum(renderer)
        self.check_spectrum(renderer, style="曲線")

    def test_the_cpu_renderer_draws_them(self):
        r = render.Renderer(lambda *a: None)
        if r.engine() is None:
            self.skipTest("no OpenGL")
        self.draws(r)

    def test_the_gpu_renderer_draws_them(self):
        r = glrender.make(lambda *a: None)
        if not isinstance(r, glrender.GLRenderer):
            self.skipTest("no OpenGL")
        self.draws(r)

    def test_a_missing_source_draws_silence_and_stops_an_export(self):
        root, _e, _pic = self.root("waveform", channel="gone")
        with self.assertRaisesRegex(RuntimeError, "找不到"):
            soundmeter.require(root, self.cache)
        soundmeter.require(root, self.cache, allow_errors=True)
        r = render.Renderer(lambda *a: None)
        if r.engine() is None:
            self.skipTest("no OpenGL")
        _n, rows = self.lit(r, root, 0.6)
        self.assertLessEqual(rows[1] - rows[0], 5)

    def test_one_that_is_not_drawn_does_not_stop_an_export(self):
        root, e, pic = self.root("waveform", channel="gone")
        ng.disconnect(e["graph"], "output", "src")
        ng.connect(e["graph"], "input", "output", "src")
        soundmeter.require(root, self.cache)

    def test_a_changed_source_draws_the_old_sound_until_measured(self):
        root, e, pic = self.root("waveform")
        soundmeter.prepare(root, self.cache)
        spec = soundmeter.picture_spec(e["graph"], e["sources"], pic)
        sound, name = soundmeter.picture_sound((e["id"], pic), spec)
        self.assertIsNotNone(sound)
        root["tracks"].append({"id": "t2", "kind": "audio", "name": "A2", "clips": [self.kick_clip("k2")], "muted": True})
        other = {"level": "tl1", "channel": "t2"}
        soundmeter.plan(root)
        self.assertEqual(soundmeter.picture_sound((e["id"], pic), other)[1], name)
        self.assertEqual(soundmeter.picture_sound((e["id"], pic), None), (None, None))


if __name__ == "__main__":
    unittest.main()
