// @filter RGB 轉灰階
// @category 轉換器
// @description 節點用：照 Blender 的「RGB 轉 BW」：用明度（0.2126 R + 0.7152 G + 0.0722 B）變成灰階圖，透明度不變
// @source 顏色
// @socket in - color
// @socket out - float

// Reimplementation of Blender's RGB to BW compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec4 effect(vec2 uv) {
    vec4 a = unpremultiply(src(uv));
    return premultiply(vec4(vec3(dot(a.rgb, vec3(0.2126, 0.7152, 0.0722))), a.a));
}
