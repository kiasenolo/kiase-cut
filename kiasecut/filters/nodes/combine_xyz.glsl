// @filter 合併 XYZ
// @category 向量
// @description 節點用：照 Blender 的「合併 XYZ」：三個數值合成一個向量（圖像的紅綠藍是 X、Y、Z）。數值是數字（圖進來就是黑白的明度），沒接線就用欄位裡的數字
// @source "X" x
// @input y "Y" y
// @input z "Z" z
// @param x float 0 -1000000 1000000 "X"
// @param y float 0 -1000000 1000000 "Y"
// @param z float 0 -1000000 1000000 "Z"
// @socket out - vector

// Reimplementation of Blender's Combine XYZ compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

float bright(vec4 c) { return dot(c.rgb, vec3(0.2126, 0.7152, 0.0722)); }     // (a number input: the picture's brightness over black)

vec4 effect(vec2 uv) {
    return vec4(has_src() ? bright(src(uv)) : x, has_input_y() ? bright(input_y(uv)) : y, has_input_z() ? bright(input_z(uv)) : z, 1.0);
}
