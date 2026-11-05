// @filter 分割
// @category 轉換器
// @description 節點用：照 Blender 的「分割」（Split）：一條線把畫面分成兩半，線的一邊是圖像 1、另一邊是圖像 2。位置是線經過的點（畫面的比例，左下角是 0,0），旋轉是線的方向（欄位用度；從別的節點接進來的數字當弧度，像 Blender）
// @source "圖像 1"
// @input b "圖像 2"
// @input angle "旋轉" angle
// @param position vec2 0.5,0.5 0 1 "位置"
// @param angle float 45 -36000 36000 "旋轉（度）"

// Reimplementation of Blender's Split compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

float bright(vec4 c) { return dot(c.rgb, vec3(0.2126, 0.7152, 0.0722)); }

// Blender 5.2 (compositor_split.glsl): the line goes through position (in pixels, Y up) with the normal (-sin, cos) of the rotation;
// a pixel whose direction to that point has a projection on the normal of 0 or less takes the first image, the others the second.
vec4 effect(vec2 uv) {
    vec2 res = resolution;
    vec2 texel = vec2(floor(uv.x * res.x), res.y - 1.0 - floor(uv.y * res.y));
    float a = has_input_angle() ? bright(input_angle(uv)) : radians(angle);
    vec2 normal = vec2(-sin(a), cos(a));
    float projection = dot(normal, position * res - texel);
    return projection <= 0.0 ? src(uv) : input_b(uv);
}
