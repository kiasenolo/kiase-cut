// @filter 透明度覆蓋
// @category 色彩
// @description 節點用：照 Blender 的 Alpha Over：前景 B 蓋在背景（圖像）上，兩邊的透明度都算進去
// @source 背景
// @input b "前景"
// @param fac float 1 0 1 "係數"

// Reimplementation of Blender's Alpha Over compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec4 effect(vec2 uv) {
    vec4 bg = src(uv), fg = input_b(uv) * clamp(fac, 0.0, 1.0);
    return fg + bg * (1.0 - fg.a);
}
