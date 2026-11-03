// @filter 分離 XYZ
// @category 向量
// @description 節點用：照 Blender 的「分離 XYZ」：圖像的紅綠藍當成向量 (X, Y, Z)，各拆成一張灰階圖，各有一個輸出
// @output x "X"
// @output y "Y"
// @output z "Z"

// Reimplementation of Blender's Separate XYZ compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec4 effect(vec2 uv) {
    vec3 v = unpremultiply(src(uv)).rgb;
    float f = output_index == 0 ? v.x : output_index == 1 ? v.y : v.z;
    return vec4(vec3(f), 1.0);
}
