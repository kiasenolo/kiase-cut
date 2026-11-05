// @filter 分離 XYZ
// @category 向量
// @description 節點用：照 Blender 的「分離 XYZ」：圖像的紅綠藍當成向量 (X, Y, Z)（沒接線就用欄位裡的三個數字），各拆成一張灰階圖，各有一個輸出
// @source "向量"
// @output x "X"
// @output y "Y"
// @output z "Z"
// @param vec_in vec3 0,0,0 -1000000 1000000 "向量"
// @step 0.001 vec_in
// @socket in - vector
// @socket out x float
// @socket out y float
// @socket out z float

// Reimplementation of Blender's Separate XYZ compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec4 effect(vec2 uv) {
    vec3 v = has_src() ? unpremultiply(src(uv)).rgb : vec_in;
    float f = output_index == 0 ? v.x : output_index == 1 ? v.y : v.z;
    return vec4(vec3(f), 1.0);
}
