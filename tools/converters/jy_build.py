"""Stage 2 of jianying_to_blender.py: build a VSE project from timeline.json.

  blender -b --factory-startup --python jy_build.py -- timeline.json out.blend
"""
import json
import os
import sys

import bpy
from bpy_extras import anim_utils

args = sys.argv[sys.argv.index("--") + 1:]
tl = json.load(open(args[0], encoding="utf-8"))
OUT = args[1]

scene = bpy.context.scene
scene.render.fps = int(round(tl["fps"]))
scene.render.fps_base = scene.render.fps / tl["fps"]
scene.render.resolution_x, scene.render.resolution_y = tl["width"], tl["height"]
scene.render.resolution_percentage = 100
scene.frame_start, scene.frame_end = 0, tl["frame_end"] - 1
# Jianying shows media as-is: no filmic/AgX tone mapping
scene.view_settings.view_transform = "Standard"
scene.view_settings.look = "None"
scene.sequencer_colorspace_settings.name = "sRGB"
scene.render.image_settings.media_type = "VIDEO"
scene.render.ffmpeg.format = "MPEG4"
scene.render.ffmpeg.codec = "H264"
scene.render.ffmpeg.audio_codec = "AAC"
se = scene.sequence_editor or scene.sequence_editor_create()
# media keeps its pixel size; stage 1 supplies Jianying's fit factor (Blender skips
# fitting inside meta strips, so it must not be relied on)
scene.tool_settings.sequencer_tool_settings.fit_method = "ORIGINAL"

ad = scene.animation_data or scene.animation_data_create()
if ad.action is None:
    ad.action = bpy.data.actions.new("Jianying")
if ad.action_slot is None:
    ad.action_slot = ad.action.slots.new(id_type="SCENE", name=scene.name)
fcurves = anim_utils.action_ensure_channelbag_for_slot(ad.action, ad.action_slot).fcurves

SCALE_PROPS = ("transform.scale_x", "transform.scale_y")


def resolve(strip, path):
    obj = strip
    parts = path.split(".")
    for p in parts[:-1]:
        obj = getattr(obj, p)
    return obj, parts[-1]


def set_range(strip, start, end):
    if start >= strip.right_handle:
        strip.right_handle = end
        strip.left_handle = start
    else:
        strip.left_handle = start
        strip.right_handle = end


def apply_props(strip, props, fit_scale):
    for path, val in props.items():
        k = fit_scale if path in SCALE_PROPS else 1.0
        obj, attr = resolve(strip, path)
        if not isinstance(val, list):
            setattr(obj, attr, val * k)
            continue
        setattr(obj, attr, val[0][1] * k)
        dp = f'sequence_editor.strips_all["{bpy.utils.escape_identifier(strip.name)}"].{path}'
        fc = fcurves.find(dp) or fcurves.new(dp)
        fc.keyframe_points.add(len(val))
        for kp, (f, v, ldf, ldv, rdf, rdv) in zip(fc.keyframe_points, val):
            kp.co = (f, v * k)
            kp.interpolation = "BEZIER"
            kp.handle_left_type = kp.handle_right_type = "FREE"
            kp.handle_left = (f + ldf, (v + ldv) * k)
            kp.handle_right = (f + rdf, (v + rdv) * k)
        fc.update()


class Channels:
    """Lowest free channel at or above a layer's base, one block per (render_index, track)."""

    def __init__(self, nodes):
        self.used = {}
        self.base = {}
        nxt = 1
        for layer in sorted({tuple(n["layer"]) for n in nodes}):
            self.base[layer] = nxt
            group = [n for n in nodes if tuple(n["layer"]) == layer]
            nxt += self._depth(group)

    @staticmethod
    def _depth(group):
        ev = sorted([(n["start"], 1) for n in group] + [(n["end"], -1) for n in group])
        cur = best = 0
        for _, d in ev:
            cur += d
            best = max(best, cur)
        return max(best, 1)

    def top(self):
        return max(self.base.values(), default=0) + 8

    def alloc(self, layer, a, b, ch=None):
        ch = ch or self.base[tuple(layer)]
        while any(not (b <= x or a >= y) for x, y in self.used.get(ch, [])):
            ch += 1
        self.used.setdefault(ch, []).append((a, b))
        return ch


def build(container, nodes):
    chans = Channels(nodes)
    matte_ch = chans.top()
    for n in sorted(nodes, key=lambda n: (tuple(n["layer"]), n["start"])):
        ch = chans.alloc(n["layer"], n["start"], n["end"])
        name = n["name"] or n["type"]
        t = n["type"]
        if t == "image":
            s = container.new_image(name, n["path"], ch, n["start"])
            set_range(s, n["start"], n["end"])
        elif t == "movie":
            s = container.new_movie(name, n["path"], ch, n["content_start"])
            set_range(s, n["start"], n["end"])
        elif t == "sound":
            s = container.new_sound(name, n["path"], ch, n["content_start"])
            set_range(s, n["start"], n["end"])
        elif t == "meta":
            s = container.new_meta(name, ch, n["start"])
            build(s.strips, n["children"])
            set_range(s, n["start"], n["end"])
        else:
            continue
        if t != "sound":
            s.blend_type = "ALPHA_OVER"
        apply_props(s, n.get("props", {}), n.get("fit_scale", 1.0))
        mk = n.get("mask")
        if mk:
            files = mk["files"]
            m = container.new_image(name + " matte", os.path.join(mk["dir"], files[0]),
                                    chans.alloc(None, mk["start"], mk["end"], matte_ch),
                                    mk["start"])
            for fn in files[1:]:
                m.elements.append(fn)
            set_range(m, mk["start"], mk["end"])
            m.mute = True
            mod = s.modifiers.new("Jianying mask", "MASK")
            mod.input_mask_type = "STRIP"
            mod.input_mask_strip = m


build(se.strips, tl["nodes"])
bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("saved", OUT, "strips:", len(se.strips_all))
