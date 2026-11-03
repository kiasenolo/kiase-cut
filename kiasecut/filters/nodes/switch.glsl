// @filter 切換
// @category 轉換器
// @description 節點用：照 Blender 的「切換」節點（Switch）：開關關著輸出「假」，打開輸出「真」。沒被選到的那一張圖不會被運算（像 Blender 只算用到的）。開關可以接一個數字（大於 0.5 就是真，像 Blender 的數字轉布林），也可以在效果面板做成參數
// @source 假
// @input yes "真"
// @param use_true bool false "開關"
// @use src !use_true
// @use yes use_true

// Reimplementation of Blender's Switch compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec4 effect(vec2 uv) {
    return use_true ? input_yes(uv) : src(uv);
}
