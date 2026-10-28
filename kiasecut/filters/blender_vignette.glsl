// @filter [Blender] Vignette
// @category Blender
// @description Blender 合成器的 Vignette：圓角矩形的暗角，可以調大小、位置、角度（在線性光裡運算）
// @param factor float 1 0 1 "強度"
// @param feather float 0.4 0 1 "柔邊"
// @param roundness float 1 0 1 "圓角"
// @param size vec2 0.8,0.8 0 2 "大小"
// @param center vec2 0.5,0.5 0 1 "中心"
// @param angle float 0 -180 180 "角度"

// Source: the Vignette node group of Blender's Essentials asset library, rewritten by hand for
// KiaseCut (exported first with tools/converters/compositor_to_hyprshade.py).
// Blender: https://github.com/blender/blender
//   datafiles/assets/nodes/compositing_nodes_essentials.blend (installed with Blender 5.2)
// SPDX-FileCopyrightText: Blender Studio / Blender Foundation (original, CC0); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec3 srgb_to_lin(vec3 c) { return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(vec3(0.04045), c)); }
vec3 lin_to_srgb(vec3 c) { c = clamp(c, 0.0, 1.0); return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(vec3(0.0031308), c)); }

vec4 effect(vec2 uv) {
    // Blender's image coordinates: the long side -1..1; the box is the picture's own shape times size
    vec2 asp = resolution / max(resolution.x, resolution.y);
    vec2 p = (uv - center) * 2.0 * asp;
    float a = radians(angle);
    p = abs(mat2(cos(a), sin(a), -sin(a), cos(a)) * p);     // clockwise on the picture
    vec2 box = asp * max(size, vec2(0.0));
    float r = min(roundness, min(box.x, box.y));
    vec2 d = p - box + r;
    float sd = length(max(d, 0.0)) + min(max(d.x, d.y), 0.0) - r;     // rounded box, < 0 inside

    float f = feather + 1e-4;                                 // the soft edge runs from -f/2 to (as Blender's Map Range)
    float lo = -0.5 * min(f, 1.0);
    float hi = clamp(1.0 - (f - 1.0) / (0.5 * f - 1.0), 0.0, 1.0);
    float k = 1.0 - smoothstep(0.0, 1.0, clamp((sd - lo) / max(hi - lo, 1e-6), 0.0, 1.0));

    vec4 s = unpremultiply(src(uv));
    vec3 c = srgb_to_lin(s.rgb) * mix(1.0, k, clamp(factor, 0.0, 1.0));    // darkened in linear light
    return premultiply(vec4(lin_to_srgb(c), s.a));
}
