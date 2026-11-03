// @filter 反相
// @category 色彩
// @description 顏色反轉。照 Blender 的「反轉顏色」：係數是原圖和反相之間的混合，顏色和透明度可以各自決定要不要反相
// @param amount float 1 0 1 "係數"
// @param invert_color bool true "反轉顏色"
// @param invert_alpha bool false "反轉透明度"

// Reimplementation of Blender's Invert Color compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec4 effect(vec2 uv) {
    vec4 c = unpremultiply(src(uv));
    vec3 rgb = invert_color ? mix(c.rgb, 1.0 - c.rgb, amount) : c.rgb;
    float a = invert_alpha ? mix(c.a, 1.0 - c.a, amount) : c.a;
    return premultiply(vec4(rgb, a));
}
