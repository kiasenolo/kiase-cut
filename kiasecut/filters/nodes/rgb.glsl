// @filter 顏色
// @category 輸入
// @description 節點用：照 Blender 的「RGB」節點：一個常數顏色，整張圖都是這個顏色。接到別的節點的圖片輸入（像「混合」）當顏色用
// @param color color #ffffff "顏色"

// Reimplementation of Blender's RGB compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec4 effect(vec2 uv) {
    return vec4(color.rgb * color.a, color.a);
}
