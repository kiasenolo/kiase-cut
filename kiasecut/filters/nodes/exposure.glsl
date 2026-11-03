// @filter 曝光
// @category 色彩
// @description 節點用：照 Blender 的「曝光」節點：顏色乘上 2 的曝光次方（以檔為單位，+1 亮一倍），透明度不動。曝光是數字輸入，也可以接別的節點
// @source 圖像
// @input amount "曝光" exposure
// @param exposure float 0 -10 10 "曝光"

// Reimplementation of Blender's Exposure compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec4 effect(vec2 uv) {
    vec4 a = unpremultiply(src(uv));
    float e = has_input_amount() ? dot(input_amount(uv).rgb, vec3(0.2126, 0.7152, 0.0722)) : exposure;
    return premultiply(vec4(a.rgb * exp2(e), a.a));
}
