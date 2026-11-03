// @filter [Blender] Color Ramp
// @category Blender
// @description Blender 的 Color Ramp：輸入是數值（Fac），所以進來的圖都先變成黑白（明度），再把每個像素的明度對應到漸變上的顏色
// @param ramp gradient 0:#000000,1:#ffffff "色彩漸變"
// @param interp menu 線性 "線性|緩和|固定|基數|B 樣條" "插值"
// @param mode menu RGB "RGB|HSV|HSL" "色彩模式"
// @param hue menu 最近 "最近|最遠|順時針|逆時針" "色相插值"
// @enable hue mode != RGB

// Source: the Color Ramp node of Blender (source/blender/blenkernel/intern/colorband.cc), rewritten for
// KiaseCut with the same stops, interpolations (linear, ease, constant, cardinal, B-spline), colour modes
// and hue interpolations (as Blender's, HSV / HSL always blend linearly; past the last stop the splines
// hold its colour); the gradient itself is gradient_eval() of the filter engine. The picture,
// made a float as Blender does (its brightness, Rec. 709 weights), is the Factor at each pixel; the ramp's colour and alpha replace the
// pixel; where the clip is transparent it stays so, and the ramp's alpha is multiplied in.
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

const int INTERP[5] = int[5](2, 0, 4, 1, 3);

vec4 effect(vec2 uv) {
    vec4 c = src(uv);
    vec3 s = c.a > 0.0 ? c.rgb / c.a : vec3(0.0);
    float fac = dot(s, vec3(0.2126, 0.7152, 0.0722));          // (a float input: any picture goes in as its brightness)
    vec4 r = gradient_eval(ramp_p, ramp_c, ramp_n, fac, INTERP[interp], mode, hue);
    float a = r.a * c.a;
    return vec4(r.rgb * a, a);
}
