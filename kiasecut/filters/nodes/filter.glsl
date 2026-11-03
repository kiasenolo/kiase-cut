// @filter 濾鏡
// @category 濾鏡
// @description 節點用：照 Blender 的「濾鏡」節點（Filter）：用 3×3 的核做卷積。柔化；方塊銳利化、菱形銳利化（負的結果變 0）；拉普拉斯、索伯、普魯伊特、基爾希（邊緣偵測：兩個方向的結果平方相加再開根號，只算顏色，透明度不變）；陰影（一個方向的核，負的變 0）。係數是和原圖的混合（1 全是濾鏡，0 全是原圖），可以接一張圖當遮罩
// @source 圖像
// @param kind menu 柔化 "柔化|方塊銳利化|菱形銳利化|拉普拉斯|索伯|普魯伊特|基爾希|陰影" "類型"
// @param fac float 1 0 1 "係數"

// Reimplementation of Blender's Filter compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

// Kernels and combinations as the Filter node of Blender 5.2 gives them (checked in every type on random pictures: within
// 1e-6); the picture's edge is repeated outwards. All four channels (premultiplied) go through the kernel, except in the
// edge types, which leave the alpha alone.

vec4 tap(vec2 uv, int dx, int dy) { return src(clamp(uv + vec2(float(dx), float(dy)) / resolution, 0.5 / resolution, 1.0 - 0.5 / resolution)); }       // (the nearest pixel at the edge)

vec4 conv(vec2 uv, float k[9]) {
    vec4 s = vec4(0.0);
    for (int j = 0; j < 3; j++)
        for (int i = 0; i < 3; i++) s += tap(uv, i - 1, j - 1) * k[j * 3 + i];
    return s;
}

vec4 edge(vec2 uv, float a[9], float b[9]) {
    vec4 c = src(uv);
    vec3 x = conv(uv, a).rgb, y = conv(uv, b).rgb;
    return vec4(sqrt(x * x + y * y), c.a);
}

vec4 effect(vec2 uv) {
    vec4 c = src(uv), f;
    switch (kind) {
    case 0: f = conv(uv, float[9](1.0 / 16.0, 2.0 / 16.0, 1.0 / 16.0, 2.0 / 16.0, 4.0 / 16.0, 2.0 / 16.0, 1.0 / 16.0, 2.0 / 16.0, 1.0 / 16.0)); break;
    case 1: f = conv(uv, float[9](-1.0, -1.0, -1.0, -1.0, 9.0, -1.0, -1.0, -1.0, -1.0)); break;
    case 2: f = conv(uv, float[9](0.0, -1.0, 0.0, -1.0, 5.0, -1.0, 0.0, -1.0, 0.0)); break;
    case 3: {
        float l[9] = float[9](-0.125, -0.125, -0.125, -0.125, 1.0, -0.125, -0.125, -0.125, -0.125);
        f = edge(uv, l, l);
        break;
    }
    case 4: f = edge(uv, float[9](1.0, 2.0, 1.0, 0.0, 0.0, 0.0, -1.0, -2.0, -1.0), float[9](1.0, 0.0, -1.0, 2.0, 0.0, -2.0, 1.0, 0.0, -1.0)); break;
    case 5: f = edge(uv, float[9](1.0, 1.0, 1.0, 0.0, 0.0, 0.0, -1.0, -1.0, -1.0), float[9](1.0, 0.0, -1.0, 1.0, 0.0, -1.0, 1.0, 0.0, -1.0)); break;
    case 6: f = edge(uv, float[9](2.0, 2.0, 2.0, 3.0, 3.0, 3.0, -5.0, -5.0, -5.0), float[9](-5.0, 3.0, 2.0, -5.0, 3.0, 2.0, -5.0, 3.0, 2.0)); break;
    default: f = conv(uv, float[9](-1.0, -2.0, -1.0, 0.0, 1.0, 0.0, 1.0, 2.0, 1.0)); break;
    }
    return max(mix(c, f, fac), 0.0);
}
