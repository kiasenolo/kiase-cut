"""The layout of the node editor's add menu, as Blender 5.2's compositor Add menu (scripts/startup/bl_ui/node_add_menu_compositor.py):
the same menus in the same order with the same separators, holding the nodes KiaseCut has (a node Blender has and KiaseCut has not
is left out). What Blender has no place for - KiaseCut's own effects - comes after them, grouped by their own categories.

An item is a filter name ("nodes/mix" is builtin:nodes/mix, "blur" builtin:blur), SEP, ("menu", label, [items]), ("node", label, node)
for the nodes that are not filters, or SHAPES (the built-in shapes, a submenu)."""
# Blender: https://github.com/blender/blender (the layout follows its node_add_menu_compositor.py)
# SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
# SPDX-License-Identifier: GPL-3.0-or-later
from . import nodegraph as ng

SEP = "-"
SHAPES = "@shapes"


def node(label, **kw):
    return ("node", label, kw)


def menu(label, items):
    return ("menu", label, items)


INPUT = [
    menu("常數", ["nodes/boolean", "nodes/rgb", "nodes/integer", "nodes/integer_vector", "nodes/menu", "nodes/value", "nodes/vector"]),
    SEP,
    node("輸入（片段的畫面）", type=ng.INPUT), node("參數輸入（效果自己的參數）", type=ng.PARAMS),
    node("圖片", type=ng.SOURCE, kind="image"), node("影片", type=ng.SOURCE, kind="video"),
    node("複合片段", type=ng.SOURCE, kind="compound"), node("時間線（軌道）", type=ng.SOURCE, kind="track"),
    node("文字", type=ng.SOURCE, kind="text"),
    "nodes/image_info", "nodes/coordinate", SHAPES,
    SEP,
    menu("場景", ["nodes/time"]),
]

OUTPUT = [node("預覽（編輯器的預覽看這裡）", type=ng.VIEWER)]

COLOR = [
    menu("調整", ["nodes/bright_contrast", "nodes/exposure", "nodes/gamma", "nodes/hue_sat_value"]),
    SEP,
    "nodes/alpha_over", "nodes/set_alpha",
    SEP,
    "nodes/combine", "nodes/separate_color",
    SEP,
    "nodes/mix",
    SEP,
    "nodes/blackbody", "blender_color_ramp",
    SEP,
    "invert", "nodes/rgb_to_bw",
]

CREATIVE = ["oil_paint", "pixelate", "posterize", "blender_vignette"]

FILTER = [
    menu("模糊", ["blur", "lens_blur", "motion_blur"]),
    SEP,
    "nodes/dilate_erode",
    SEP,
    "nodes/filter", "blender_glare",
]

KEYING = ["chroma_key", "value_key"]

MASK = ["nodes/rounded_square_mask"]

TEXTURE = ["blender_tex_brick", "blender_tex_checker", "blender_tex_gradient", "blender_tex_magic", "blender_tex_noise",
           "blender_tex_voronoi", "blender_tex_wave", "blender_tex_white_noise", "blender_sensor_noise"]

TRANSFORM = ["scale", "nodes/transform", "translate", SEP, "blender_lens_distortion"]

UTILITIES = [
    menu("數學", ["nodes/clamp", "nodes/float_curve", "nodes/map_range", "nodes/math", "nodes/mix"]),
    menu("向量", ["nodes/combine_xyz", "nodes/map_range", "nodes/mix", "nodes/separate_xyz", SEP,
                  "nodes/vector_curves", "nodes/vector_math", "nodes/vector_rotate"]),
    SEP,
    "nodes/normalize",
    SEP,
    "nodes/switch", "nodes/index_switch", "nodes/menu_switch",
]

LAYOUT = [node("繞線點", type=ng.REROUTE), node("框架／註解", type=ng.FRAME)]

# The root, as Blender's NODE_MT_compositor_node_all_base (Tracking has no node here, the empty menus are left out)
ROOT = [
    menu("輸入", INPUT), menu("輸出", OUTPUT),
    SEP,
    menu("色彩", COLOR), menu("創意", CREATIVE), menu("濾鏡", FILTER),
    SEP,
    menu("去背", KEYING), menu("遮罩", MASK),
    SEP,
    menu("紋理", TEXTURE), menu("變換", TRANSFORM), menu("工具", UTILITIES),
]
AFTER = [menu("佈局", LAYOUT)]            # (after KiaseCut's own: Blender's Group and Layout come last)


def ref_of(item):
    return "builtin:" + item


def placed(items=None):
    """The filter refs the layout holds."""
    out = set()
    for it in (ROOT + AFTER if items is None else items):
        if isinstance(it, str):
            if it != SEP and it != SHAPES:
                out.add(ref_of(it))
        elif it[0] == "menu":
            out |= placed(it[2])
    return out
