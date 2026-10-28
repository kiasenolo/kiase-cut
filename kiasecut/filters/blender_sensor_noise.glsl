// @filter [Blender] Sensor Noise
// @category Blender
// @description Blender 合成器的 Sensor Noise：感光元件的亮度雜訊和色彩雜訊（在線性光裡運算）
// @param luminance float 0.1 0 1 "亮度雜訊"
// @param chroma float 0.05 0 1 "色彩雜訊"
// @param animated bool false "每格不同"

// Source: the Sensor Noise node group of Blender's Essentials asset library, rewritten by hand
// for KiaseCut (exported first with tools/converters/compositor_to_hyprshade.py).
// Blender: https://github.com/blender/blender
//   datafiles/assets/nodes/compositing_nodes_essentials.blend (installed with Blender 5.2)
// SPDX-FileCopyrightText: Blender Studio / Blender Foundation (original, CC0); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec3 srgb_to_lin(vec3 c) { return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(vec3(0.04045), c)); }
vec3 lin_to_srgb(vec3 c) { c = clamp(c, 0.0, 1.0); return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(vec3(0.0031308), c)); }

vec3 rgb2hsv(vec3 c) {
    vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
    vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
    float d = q.x - min(q.w, q.y);
    return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + 1e-10)), d / (q.x + 1e-10), q.x);
}
vec3 hsv2rgb(vec3 c) {
    vec3 p = abs(fract(c.xxx + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
    return c.z * mix(vec3(1.0), clamp(p - 1.0, 0.0, 1.0), c.y);
}
float hash31(vec3 p) { p = fract(p * 0.1031); p += dot(p, p.zyx + 31.32); return fract((p.x + p.y) * p.z); }
float hash11(float p) { p = fract(p * 0.1031); p *= p + 33.33; p *= p + p; return fract(p); }
float white2(vec2 p) { return hash31(vec3(floor(p * 4096.0), 1.7)); }

vec4 effect(vec2 uv) {
    vec4 s = unpremultiply(src(uv));
    vec3 c = srgb_to_lin(s.rgb) * s.a;                        // Blender works on linear, premultiplied colour
    // one noise cell is about a canvas pixel: Blender's image coordinates (-1..1 on the long side) x 2048
    vec2 p = (vec2(uv.x, 1.0 - uv.y) * 2.0 - 1.0) * resolution / max(resolution.x, resolution.y);
    if (animated)
        p.y += hash11(float(frame) * 4096.0 * 0.0173 + 0.5);    // a new pattern each frame
    vec3 n = vec3(white2(p), white2(p + vec2(17.1, 3.7)), white2(p + vec2(5.3, 21.9)));

    vec3 hsv = rgb2hsv(c);
    hsv.x = fract(hsv.x + dot(n - 0.5, vec3(1.0 / 3.0)) * chroma);
    float v = hsv.z, b = n.x;                                 // overlay of the noise on the value
    float o = v < 0.5 ? 2.0 * v * b : 1.0 - 2.0 * (1.0 - v) * (1.0 - b);
    hsv.z = mix(v, o, clamp(luminance, 0.0, 1.0));
    vec3 rgb = hsv2rgb(hsv);

    float a = clamp(s.a, 0.0, 1.0);
    rgb = a > 0.0 ? lin_to_srgb(rgb / a) * a : vec3(0.0);
    return vec4(min(rgb, vec3(a)), a);
}
