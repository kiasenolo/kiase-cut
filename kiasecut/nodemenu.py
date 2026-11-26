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
PARTICLES = "@particles"                    # (the 粒子 settings, a submenu of 粒子系統 nodes that start with them)


def node(label, **kw):
    return ("node", label, kw)


def menu(label, items):
    return ("menu", label, items)


INPUT = [
    menu("常數", ["nodes/boolean", "nodes/rgb", node("字體", type=ng.FONT), "nodes/integer", "nodes/integer_vector", "nodes/menu", node("字串", type=ng.STRING), "nodes/value", "nodes/vector"]),
    SEP,
    node("輸入（片段的畫面）", type=ng.INPUT), node("參數輸入（效果自己的參數）", type=ng.PARAMS),
    node("圖片", type=ng.SOURCE, kind="image"), node("影片", type=ng.SOURCE, kind="video"),
    node("複合片段", type=ng.SOURCE, kind="compound"), node("時間線（軌道）", type=ng.SOURCE, kind="track"),
    node("文字", type=ng.SOURCE, kind="text"),
    "nodes/image_info", "nodes/coordinate", SHAPES, PARTICLES,
    SEP,
    menu("場景", ["nodes/time"]),
]

VECTOR = [SHAPES, node("文字", type=ng.SOURCE, kind="text"), node("SVG 圖片", type=ng.SOURCE, kind="image", svg=True),
          SEP,
          node("相加（把多個矢量疊在一起）", type=ng.SOURCE, kind="vector", op="add"),
          node("布林運算（聯集、差集、交集、排除）", type=ng.SOURCE, kind="vector", op="boolean"),
          node("旋轉（矢量）", type=ng.SOURCE, kind="vector", op="rotate"),
          node("移動（矢量）", type=ng.SOURCE, kind="vector", op="move"),
          node("縮放（矢量）", type=ng.SOURCE, kind="vector", op="scale")]

OUTPUT = [node("預覽（編輯器的預覽看這裡）", type=ng.VIEWER)]

COLOR = [
    menu("調整", ["nodes/bright_contrast", "nodes/exposure", "nodes/gamma", "nodes/hue_sat_value", "nodes/rgb_curves"]),
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

CREATIVE = ["oil_paint", "pixelate", "dot_matrix", "posterize", "blender_vignette"]

FILTER = [
    menu("模糊", ["blur", "lens_blur", "motion_blur"]),
    SEP,
    "nodes/dilate_erode",
    SEP,
    "nodes/filter", "blender_glare",
]

KEYING = ["chroma_key", "value_key"]

MASK = ["nodes/rounded_square_mask"]

TEXTURE = ["nodes/tex_brick", "nodes/tex_checker", "nodes/tex_fractal_noise", "nodes/tex_gabor", "nodes/tex_gradient",
           "nodes/tex_magic", "nodes/tex_noise", "nodes/tex_voronoi", "nodes/tex_wave", "nodes/tex_white_noise", "blender_sensor_noise"]

TRANSFORM = ["nodes/rotate", "scale", "nodes/transform", "translate", SEP, "nodes/crop", SEP, "nodes/flip", "nodes/map_uv", SEP, "blender_lens_distortion"]

UTILITIES = [
    menu("數學", ["nodes/clamp", "nodes/float_curve", "nodes/map_range", "nodes/math", "nodes/mix"]),
    menu("向量", ["nodes/combine_xyz", "nodes/map_range", "nodes/mix", "nodes/separate_xyz", SEP,
                  "nodes/vector_curves", "nodes/vector_math", "nodes/vector_rotate"]),
    SEP,
    "nodes/normalize",
    SEP,
    "nodes/split", "nodes/switch", "nodes/index_switch", "nodes/menu_switch",
]

SOUND = [node("聲音來源", type=ng.SOUND_SOURCE), node("電平 → 數值", type=ng.SOUND_LEVEL),
         node("波形", type=ng.SOURCE, kind="waveform"), node("頻譜", type=ng.SOURCE, kind="spectrum"),
         node("頻譜資料", type=ng.SOURCE, kind=ng.SPECTRUM_DATA)]       # (KiaseCut's own: nodegraph.py's sound links)

LAYOUT = [node("繞線點", type=ng.REROUTE), node("框架／註解", type=ng.FRAME)]

# The root, as Blender's NODE_MT_compositor_node_all_base (Tracking has no node here, the empty menus are left out)
ROOT = [
    menu("輸入", INPUT), menu("輸出", OUTPUT), menu("矢量", VECTOR),
    SEP,
    menu("色彩", COLOR), menu("創意", CREATIVE), menu("濾鏡", FILTER),
    SEP,
    menu("去背", KEYING), menu("遮罩", MASK),
    SEP,
    menu("紋理", TEXTURE), menu("變換", TRANSFORM), menu("工具", UTILITIES),
]
AFTER = [menu("聲音", SOUND), menu("佈局", LAYOUT)]            # (after KiaseCut's own: Blender's Group and Layout come last)


# What the add menu's search finds a node by besides its name and its menu: the names Blender and other programs call it by, and what
# one would type for what it does ("add" finds 混合 and 數學, "bloom" the 眩光). Keyed by the filter's name in the layout above.
ALIASES = {
    "nodes/mix": "add subtract multiply divide blend color mix 加 加法 相加 減 乘 除 混合 色彩混合",
    "nodes/math": "add subtract multiply divide math 加 減 乘 除 運算 計算 數學",
    "nodes/vector_math": "add subtract multiply divide vector math 加 減 乘 除 向量運算",
    "nodes/vector_rotate": "rotate euler axis 旋轉 歐拉",
    "nodes/map_range": "remap range rescale 重新映射 範圍 對應 重映射",
    "nodes/clamp": "limit min max 限制 夾住 範圍",
    "nodes/float_curve": "curve 曲線",
    "nodes/vector_curves": "curve 曲線",
    "nodes/rgb_curves": "curves color 色彩曲線 曲線",
    "nodes/bright_contrast": "brightness contrast 亮度 對比 明暗",
    "nodes/exposure": "brightness light 曝光 亮度",
    "nodes/gamma": "伽馬 gamma 中間調",
    "nodes/hue_sat_value": "hsv hue saturation value brightness 色相 飽和度 明度 色調",
    "nodes/alpha_over": "over overlay composite layer merge 合成 疊圖 疊加 圖層 蓋上",
    "nodes/set_alpha": "alpha transparent opacity 透明 透明度 不透明",
    "nodes/combine": "combine rgb hsv ycc channel 合併 組合 通道",
    "nodes/separate_color": "separate split rgb hsv ycc channel 分離 拆開 通道",
    "nodes/combine_xyz": "combine vector 合併 組合 向量",
    "nodes/separate_xyz": "separate split vector 分離 拆開 向量",
    "nodes/blackbody": "temperature kelvin color 色溫 黑體 溫度",
    "nodes/rgb_to_bw": "grayscale grey gray desaturate black white 灰階 灰度 黑白 去色",
    "invert": "negative inverse 反相 反色 負片",
    "blender_color_ramp": "gradient colorramp color ramp 色彩漸變 色階 漸變 漸層",
    "nodes/tex_gradient": "gradient ramp 漸變 漸層",
    "nodes/tex_noise": "noise perlin fbm cloud 雜訊 噪訊 噪點 雲",
    "nodes/tex_fractal_noise": "noise value simplex perlin fbm turbulence ridged ridge fractal fire lightning 雜訊 噪聲 分形 湍流 山脊 火焰 閃電",
    "nodes/tex_white_noise": "noise random 白雜訊 隨機 噪點",
    "nodes/tex_voronoi": "cell worley 細胞 沃羅諾伊",
    "nodes/tex_checker": "checkerboard chess 棋盤",
    "nodes/tex_brick": "tile wall 磚 瓷磚",
    "nodes/tex_wave": "wave band ring 波 條紋",
    "nodes/tex_magic": "psychedelic 魔法 迷幻",
    "nodes/rotate": "angle spin turn 旋轉 轉",
    "nodes/transform": "move scale rotate translate resize 移動 縮放 旋轉 變形 位移",
    "nodes/crop": "cut trim 裁切 剪裁 裁剪",
    "nodes/flip": "mirror reverse 翻轉 鏡像 水平 垂直",
    "nodes/map_uv": "displace warp uv 貼圖 扭曲",
    "nodes/dilate_erode": "grow shrink expand contract mask edge 擴張 侵蝕 膨脹 收縮 邊緣",
    "nodes/filter": "sharpen soften sobel laplace prewitt kirsch shadow edge 銳化 柔化 邊緣 陰影 濾波",
    "nodes/rounded_square_mask": "box mask rectangle 方形 矩形 遮罩 圓角",
    "nodes/normalize": "range 0 1 正規化 歸一化",
    "nodes/switch": "if select toggle condition 切換 開關 條件 選擇",
    "nodes/index_switch": "select choose number 索引 切換 選擇",
    "nodes/menu_switch": "select choose 選單 切換 選擇",
    "nodes/split": "compare side by side 分割 分屏 左右",
    "nodes/time": "frame seconds scene 時間 影格 秒 幀",
    "nodes/coordinate": "uv position coords texture coordinate 座標 位置",
    "nodes/image_info": "size resolution width height 大小 尺寸 解析度 寬 高",
    "nodes/value": "float number constant 浮點 數字 常數",
    "nodes/integer": "int number constant 整數 數字 常數",
    "nodes/vector": "xyz constant 向量 常數",
    "nodes/rgb": "color constant 顏色 色彩 常數",
    "nodes/boolean": "bool true false switch 布林 真 假 開關",
    "blender_glare": "bloom glow fog glow streaks star simple star ghosts lens flare light 光暈 泛光 輝光 眩光 星芒 條紋 鬼影 光線",
    "blender_lens_distortion": "distortion fisheye barrel chromatic aberration dispersion 鏡頭 畸變 魚眼 色差 色散",
    "blender_sensor_noise": "grain noise iso film 噪點 顆粒 底片 感光",
    "blender_vignette": "vignette darken edge corner 暗角 邊緣 變暗",
    "blur": "gaussian box soften smooth defocus 高斯 模糊 柔化 平滑",
    "lens_blur": "bokeh depth of field dof defocus aperture 景深 散景 失焦 光圈",
    "motion_blur": "directional trail streak 動態 方向 殘影 拖影",
    "oil_paint": "painting kuwahara 油畫 繪畫",
    "pixelate": "mosaic pixel 馬賽克 像素",
    "dot_matrix": "halftone dots 點陣 網點",
    "posterize": "levels reduce colors 色調分離 色階",
    "chroma_key": "green screen blue screen keying remove background 綠幕 藍幕 去背 摳圖 色鍵",
    "value_key": "luma key luminance brightness remove background 亮度 去背 摳圖 明度鍵",
    "scale": "resize zoom bigger smaller 縮放 放大 縮小 尺寸",
    "translate": "move position offset 位移 移動 平移 位置",
}


# The choices of a menu parameter that the search lists one by one (as Blender's does: Math > Floor), the node made with that choice
# set. ref: (the parameter, the choices' English names in the order of the parameter's menu).
PRESETS = {
    "nodes/tex_fractal_noise": ("basis", "value|simplex|perlin"),
    "nodes/math": ("op", "add|subtract|multiply|divide|multiply add|power|logarithm|square root|inverse square root|absolute|exponent|minimum|maximum|"
                         "less than|greater than|sign|compare|smooth minimum|smooth maximum|round|floor|ceil ceiling|truncate|fraction|truncated modulo|"
                         "floored modulo|wrap|snap|ping pong|sine sin|cosine cos|tangent tan|arcsine arcsin|arccosine arccos|arctangent arctan|"
                         "arctan2 atan2|hyperbolic sine sinh|hyperbolic cosine cosh|hyperbolic tangent tanh|to radians|to degrees"),
    "nodes/vector_math": ("op", "add|subtract|multiply|divide|multiply add|cross product|project|reflect|refract|faceforward|dot product|distance|length|"
                                "scale|normalize|absolute|power|sign|minimum|maximum|round|floor|ceil ceiling|fraction|modulo|wrap|snap|sine sin|"
                                "cosine cos|tangent tan"),
    "nodes/mix": ("blend", "mix|darken|multiply|color burn|lighten|screen|color dodge|add|overlay|soft light|linear light|difference|exclusion|"
                           "subtract|divide|hue|saturation|color|value"),
}


def aliases_of(ref):
    """The search words of a node's filter ref ("builtin:nodes/mix"), or ""."""
    return ALIASES.get(str(ref)[len("builtin:"):], "") if str(ref).startswith("builtin:") else ""


def ref_of(item):
    return "builtin:" + item


def placed(items=None):
    """The filter refs the layout holds."""
    out = set()
    for it in (ROOT + AFTER if items is None else items):
        if isinstance(it, str):
            if it not in (SEP, SHAPES, PARTICLES):
                out.add(ref_of(it))
        elif it[0] == "menu":
            out |= placed(it[2])
    return out
