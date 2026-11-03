// @filter 向量
// @category 輸入
// @description 節點用：照 Blender 的「向量」節點（Vector）：一個常數向量，整張圖的紅綠藍是 X、Y、Z。接到別的節點的向量輸入
// @param vector vec3 0,0,0 -1000000 1000000 "向量"
// @socket out - vector

// Reimplementation of Blender's Vector compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec4 effect(vec2 uv) {
    return vec4(vector, 1.0);
}
