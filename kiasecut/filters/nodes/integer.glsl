// @filter 整數
// @category 輸入
// @description 節點用：照 Blender 的「整數」節點（Integer）：一個整數常數，整張圖都是這個數字（黑白的圖）。接到別的節點的數字輸入或參數（例如索引切換的索引）
// @param value int 0 -1000000 1000000 "整數"

// Reimplementation of Blender's Integer compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec4 effect(vec2 uv) {
    return vec4(vec3(float(value)), 1.0);
}
