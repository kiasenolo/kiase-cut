// @filter 正規化
// @category 轉換器
// @description 節點用：照 Blender 的「正規化」節點（Normalize）：把圖像的明度（黑白的數值）整張圖找出最小和最大，再把它們線性對應到 0～1；整張圖一樣亮就全部是 0。輸出是黑白的圖
// @passes 15
// @levels 1 2 3 4 5 6 7 8 9 10 11 12 13 14

// Reimplementation of Blender's Normalize compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

// Checked against Blender 5.2: (v - min) / (max - min) of the luminance, 0 where max = min. The first 14 passes shrink the
// picture by half each time and keep (min, max) of every block (the first one takes it from the brightness of the pixels),
// the last pass reads that one pixel.

float bright(vec4 c) { return dot(c.rgb, vec3(0.2126, 0.7152, 0.0722)); }

vec4 effect(vec2 uv) {
    if (pass_index == 14) {
        vec2 mm = src(vec2(0.5)).rg;
        float range = mm.y - mm.x;
        return vec4(vec3(range > 0.0 ? (bright(original(uv)) - mm.x) / range : 0.0), 1.0);
    }
    vec2 cell = floor(uv * pass_px);
    vec2 lo = floor(cell * src_px / pass_px), hi = min(ceil((cell + 1.0) * src_px / pass_px), src_px);
    float mn = 1e30, mx = -1e30;
    for (int j = 0; j < 3; j++) {
        for (int i = 0; i < 3; i++) {
            vec2 p = lo + vec2(float(i), float(j));
            if (p.x >= hi.x || p.y >= hi.y) continue;
            vec4 c = src((p + 0.5) / src_px);
            float a = pass_index == 0 ? bright(c) : c.r, b = pass_index == 0 ? bright(c) : c.g;
            mn = min(mn, a);
            mx = max(mx, b);
        }
    }
    return vec4(mn, mx, 0.0, 1.0);
}
