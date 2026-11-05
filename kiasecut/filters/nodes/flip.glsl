// @filter 翻轉
// @category 變換
// @description 節點用：照 Blender 的「翻轉」（Flip）：左右翻轉、上下翻轉，兩個可以一起開
// @param flip_x bool false "水平翻轉"
// @param flip_y bool false "垂直翻轉"

// Reimplementation of Blender's Flip compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

// Blender 5.2 (compositor_flip.glsl): a pixel is read from the mirrored pixel of the picture, so the picture is flipped exactly.
vec4 effect(vec2 uv) {
    return src(vec2(flip_x ? 1.0 - uv.x : uv.x, flip_y ? 1.0 - uv.y : uv.y));
}
