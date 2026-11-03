// @filter 伽瑪
// @category 色彩
// @description 節點用：照 Blender 的「伽瑪」節點：顏色取 1/伽瑪 次方（負的顏色不動）
// @source 顏色
// @param gamma float 1 0.001 10 "伽瑪"

// Reimplementation of Blender's Gamma compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec4 effect(vec2 uv) {
    vec4 a = unpremultiply(src(uv));
    vec3 r = mix(a.rgb, pow(max(a.rgb, vec3(0.0)), vec3(gamma)), greaterThan(a.rgb, vec3(0.0)));
    return premultiply(vec4(r, a.a));
}
