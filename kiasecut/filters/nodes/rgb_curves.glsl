// @filter RGB 曲線
// @category 色彩
// @description 節點用：照 Blender 的「RGB 曲線」節點：先用黑色位準和白色位準把顏色拉到 0~1，再過「合併」曲線，最後三個色版各過自己的曲線。曲線的 X 是輸入、Y 是輸出，範圍 0~1，超出的部分沿著兩端的斜率直線延伸。色調「類似底片」只用合併曲線，依最亮和最暗的色版算，色相不會跑掉。係數是和原圖的混合（1 全走曲線，0 不變）。用「通道」切換要改哪一條曲線
// @source "圖像"
// @input in_fac "係數" fac
// @input black "黑色位準"
// @input white "白色位準"
// @param tone menu 標準 "標準|類似底片" "色調"
// @param tab menu 合併 "合併|紅|綠|藍" "通道"
// @param curve_c curve 0,0,1,1 "合併曲線"
// @param curve_r curve 0,0,1,1 "紅曲線"
// @param curve_g curve 0,0,1,1 "綠曲線"
// @param curve_b curve 0,0,1,1 "藍曲線"
// @param fac float 1 0 1 "係數"
// @param black_level color #000000 "黑色位準"
// @param white_level color #ffffff "白色位準"
// @show curve_c tab == 合併
// @show curve_r tab == 紅
// @show curve_g tab == 綠
// @show curve_b tab == 藍
// @show curve_r tone == 標準
// @show curve_g tone == 標準
// @show curve_b tone == 標準
// @show tab tone == 標準
// @socket in black color
// @socket in white color

// Reimplementation of Blender's RGB Curves compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

// Ported from gpu_shader_common_curves.glsl (curves_combined_rgb, curves_film_like): a curve is its samples, held at its ends and
// carried on by the slope of its first / last step beyond them.
float through(float c[128], float x) {
    float s0 = (c[1] - c[0]) * 127.0, s1 = (c[127] - c[126]) * 127.0;
    float v = curve_ease(c, clamp(x, 0.0, 1.0));
    return x < 0.0 ? v + x * s0 : x > 1.0 ? v + (x - 1.0) * s1 : v;
}

vec3 combined_rgb(vec3 p) {
    vec3 r = vec3(through(curve_c, p.r), through(curve_c, p.g), through(curve_c, p.b));
    return vec3(through(curve_r, r.r), through(curve_g, r.g), through(curve_b, r.b));
}

vec3 film_like(vec3 b) {
    float mn = min(b.r, min(b.g, b.b)), mx = max(b.r, max(b.g, b.b));
    float md = max(min(b.r, b.g), min(b.b, max(b.r, b.g)));
    float new_min = through(curve_c, mn), new_max = through(curve_c, mx);
    float ratio = (new_max - new_min) / (mx - mn);
    float new_med = new_min + (md - mn) * ratio;
    vec3 med_or_min = mix(vec3(new_med), vec3(new_min), equal(b, vec3(mn)));
    return mix(med_or_min, vec3(new_max), equal(b, vec3(mx)));
}

vec4 effect(vec2 uv) {
    vec4 color = unpremultiply(src(uv));
    float f = has_input_in_fac() ? dot(input_in_fac(uv).rgb, vec3(0.2126, 0.7152, 0.0722)) * (input_in_fac(uv).a > 0.0 ? 1.0 : 0.0) : fac;
    vec4 bl = has_input_black() ? unpremultiply(input_black(uv)) : black_level;
    vec4 wl = has_input_white() ? unpremultiply(input_white(uv)) : white_level;
    vec3 balanced = (color.rgb - bl.rgb) / max(wl.rgb - bl.rgb, vec3(1e-5));
    vec3 r = tone == 1 ? film_like(balanced) : combined_rgb(balanced);
    return premultiply(vec4(mix(color.rgb, r, tone == 1 ? clamp(f, 0.0, 1.0) : f), color.a));
}
