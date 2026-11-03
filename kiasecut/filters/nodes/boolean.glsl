// @filter 布林
// @category 輸入
// @description 節點用：照 Blender 的「布林」節點（Boolean）：一個開關，打開是 1（整張圖白），關掉是 0（黑）。接到別的節點的數字輸入或參數（例如切換）
// @param value bool false "布林"
// @socket out - bool

// Reimplementation of Blender's Boolean compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec4 effect(vec2 uv) {
    return vec4(vec3(value ? 1.0 : 0.0), 1.0);
}
