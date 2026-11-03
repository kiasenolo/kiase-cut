// @filter 數值
// @category 輸入
// @description 節點用：照 Blender 的「數值」節點：一個常數，整張圖都是這個數字（黑白的圖）。接到別的節點的數字輸入或參數；數字在節點上直接輸入或拖曳
// @param value float 0.5 -1000000 1000000 "數值"
// @socket out - float

// Reimplementation of Blender's Value compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec4 effect(vec2 uv) {
    return vec4(vec3(value), 1.0);
}
