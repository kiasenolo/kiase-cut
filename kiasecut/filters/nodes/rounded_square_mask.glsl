// @filter 圓角方形遮罩
// @category 轉換器
// @description 節點用：照 Blender「Essentials」裡的「Rounded Square Mask」：圖像大小的圓角方形遮罩（黑白的圖，裡面 1、外面 0）。縮放是方形的寬高（1 約是長邊的一半寬到圖的邊），圓角、羽化（柔邊）、位移（以圖中心為 0，X 向右、Y 向上，長邊的一半是 1）、角度（度）。圖像只用來決定大小
// @param size vec2 0.8,0.8 0 100 "縮放"
// @param roundness float 0 0 1 "圓角"
// @param feather float 0 0 1 "羽化"
// @param offset vec2 0,0 -100 100 "位移"
// @param angle float 0 -360 360 "角度"

// Source: the Rounded Square Mask node group of Blender's Essentials asset library (the mask of its Vignette), rewritten by hand for
// KiaseCut, as the Vignette filter is. Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Studio / Blender Foundation (original, CC0); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec4 effect(vec2 uv) {
    vec2 asp = resolution / max(resolution.x, resolution.y);
    vec2 p = (uv - 0.5) * 2.0 * asp - vec2(offset.x, -offset.y);
    float a = -radians(angle);
    p = abs(mat2(cos(a), sin(a), -sin(a), cos(a)) * p);
    vec2 box = asp * max(size, vec2(0.0));
    float r = min(roundness, min(box.x, box.y));
    vec2 d = p - box + r;
    float sd = length(max(d, 0.0)) + min(max(d.x, d.y), 0.0) - r;

    float f = feather + 1e-4;
    float lo = -0.5 * min(f, 1.0);
    float hi = clamp(1.0 - (f - 1.0) / (0.5 * f - 1.0), 0.0, 1.0);
    float k = 1.0 - smoothstep(0.0, 1.0, clamp((sd - lo) / max(hi - lo, 1e-6), 0.0, 1.0));
    return vec4(vec3(k), 1.0);
}
