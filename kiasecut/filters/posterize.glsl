// @filter 色階分離
// @category 色彩
// @description 每個通道只留幾個色階。照 Blender 的「色階分離」：向下取整（floor(顏色 × 色階數) / 色階數），色階數最少 2、最多 1024，透明度不變
// @param levels float 8 2 1024 "色階數"

// Reimplementation of Blender's Posterize compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec4 effect(vec2 uv) {
    vec4 c = unpremultiply(src(uv));
    float steps = clamp(levels, 2.0, 1024.0);
    vec3 rgb = floor(c.rgb * steps) / steps;
    return premultiply(vec4(rgb, c.a));
}
