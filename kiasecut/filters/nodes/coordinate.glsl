// @filter 影像座標
// @category 輸入
// @description 節點用：照 Blender 的「影像座標」：輸出每個像素的座標（紅＝X、綠＝Y，Y 向上）。統一：畫面中心是原點、長邊從 -1 到 1，不會被拉伸；正規化：左下 (0, 0) 到右上 (1, 1)；像素：以畫布像素計
// @output uniform "統一"
// @output normalized "正規化"
// @output pixel "像素"
// @socket out uniform vector
// @socket out normalized vector
// @socket out pixel vector

// Reimplementation of Blender's Image Coordinates compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec4 effect(vec2 uv) {
    vec2 R = resolution;
    vec2 n = vec2(uv.x, 1.0 - uv.y);
    if (output_index == 0) return vec4((n * 2.0 - 1.0) * R / max(R.x, R.y), 0.0, 1.0);
    if (output_index == 1) return vec4(n, 0.0, 1.0);
    return vec4(n * R, 0.0, 1.0);
}
