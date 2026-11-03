// @filter 亮度／對比
// @category 色彩
// @description 節點用：照 Blender 的「亮度／對比」節點（Werner D. Streidt 的算法）
// @source 顏色
// @param bright float 0 -100 100 "亮度"
// @param contrast float 0 -100 100 "對比"

// Reimplementation of Blender's Brightness/Contrast compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec4 effect(vec2 uv) {
    vec4 c = unpremultiply(src(uv));
    float br = bright / 100.0;
    float delta = contrast / 200.0;
    float a = 1.0 - delta * 2.0;
    float b;
    if (contrast > 0.0) {
        a = a > 0.0 ? 1.0 / a : 0.0;
        b = a * (br - delta);
    } else {
        delta = -delta;
        a = 1.0 - delta * 2.0;
        b = a * br + delta;
    }
    return premultiply(vec4(a * c.rgb + b, c.a));
}
