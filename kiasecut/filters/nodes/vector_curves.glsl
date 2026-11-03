// @filter 向量曲線
// @category 向量
// @description 節點用：照 Blender 的「向量曲線」節點（Vector Curves）：圖像的紅綠藍當成向量 (X, Y, Z)，三個軸各過自己的一條曲線。曲線的 X 是輸入、Y 是輸出，範圍 -1~1（曲線編輯器的 0~1 對應 -1~1，原本是一條斜線就不變）；超出範圍的部分沿著兩端的斜率直線延伸。係數是和原向量的混合（1 全走曲線，0 不變），可以接一張圖當遮罩
// @source "向量"
// @param curve_x curve 0,0,1,1 "X 曲線"
// @param curve_y curve 0,0,1,1 "Y 曲線"
// @param curve_z curve 0,0,1,1 "Z 曲線"
// @param fac float 1 0 1 "係數"

// Reimplementation of Blender's Vector Curves compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

float through(float c[128], float x) {
    if (x < 0.0) return c[0] + x * (c[1] - c[0]) * 127.0;
    if (x > 1.0) return c[127] + (x - 1.0) * (c[127] - c[126]) * 127.0;
    return curve_ease(c, x);
}

// a component v in -1 .. 1 along the curve (the editor's 0 - 1 square is -1 - 1 on both sides)
float along(float c[128], float v) { return 2.0 * through(c, (v + 1.0) * 0.5) - 1.0; }

vec4 effect(vec2 uv) {
    vec4 s = unpremultiply(src(uv));
    vec3 r = vec3(along(curve_x, s.x), along(curve_y, s.y), along(curve_z, s.z));
    return premultiply(vec4(mix(s.rgb, r, fac), s.a));
}
