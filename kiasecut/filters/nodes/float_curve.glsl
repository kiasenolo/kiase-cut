// @filter 浮點曲線
// @category 轉換器
// @description 節點用：照 Blender 的「浮點曲線」節點（Float Curve）：數值（圖進來是黑白的明度）過一條曲線，結果是黑白的圖。曲線的 X 是輸入、Y 是輸出，範圍 0~1；超出 0~1 的部分沿著兩端的斜率直線延伸（像 Blender 的「外推」）。係數是和原來數值的混合（1 全走曲線，0 不變），可以接一張圖當遮罩。曲線的點用右邊面板的曲線編輯器改
// @source "數值" value
// @param value float 0 -1000000 1000000 "數值"
// @param curve curve 0,0,1,1 "曲線"
// @param fac float 1 0 1 "係數"

// Reimplementation of Blender's Float Curve compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

// Curve evaluation as Blender's Float Curve: inside 0 - 1 the curve, outside it the line of the end's slope (the end slope is
// read from the curve's samples).

float through(float c[128], float x) {
    if (x < 0.0) return c[0] + x * (c[1] - c[0]) * 127.0;
    if (x > 1.0) return c[127] + (x - 1.0) * (c[127] - c[126]) * 127.0;
    return curve_ease(c, x);
}

float bright(vec4 c) { return dot(c.rgb, vec3(0.2126, 0.7152, 0.0722)); }

vec4 effect(vec2 uv) {
    float v = has_src() ? bright(src(uv)) : value;
    return vec4(vec3(mix(v, through(curve, v), fac)), 1.0);
}
