// @filter 場景時間
// @category 輸入
// @description 節點用：照 Blender 的「場景時間」：輸出現在的影格和秒數（整張同一個值，是片段的時間），另外加一個片段進度（0 到 1）。接到別的節點的數字參數就會隨時間變；要循環或來回，用「數學」的迴繞或來回
// @output frame "影格"
// @output seconds "秒"
// @output progress "片段進度"

// Reimplementation of Blender's Scene Time compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec4 effect(vec2 uv) {
    float v = output_index == 0 ? float(frame) : output_index == 1 ? time : progress;
    return vec4(vec3(v), 1.0);
}
