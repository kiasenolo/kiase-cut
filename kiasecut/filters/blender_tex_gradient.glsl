// @filter [Blender] Gradient Texture
// @category Blender
// @description Blender 的漸層紋理：線性、二次、平滑、對角、球形、放射
// @param type menu 線性 "線性|二次|平滑|對角|球形|二次球形|放射" "類型"
// @param color1 color #000000 "顏色 1"
// @param color2 color #ffffff "顏色 2"
// @param tex_scale float 1 0.001 1000 "比例"
// @param offset vec2 0,0 -1000 1000 "位置"
// @param amount float 1 0 1 "強度"

// Source: the Gradient Texture shader node of Blender (source/blender/gpu/shaders/material/
// gpu_shader_material_tex_*.glsl), rewritten by hand for KiaseCut - the same pattern and parameters,
// the cell/hash randomness is not bit-identical with Blender. The coordinates are Blender's image
// coordinates (the long side -1..1, y up) times 比例. Where the clip is transparent it stays so;
// 強度 mixes the pattern over the clip's own colours.
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec3 tex_co(vec2 uv) {
    vec2 R = resolution;
    return vec3(vec2(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0) * R / max(R.x, R.y) * tex_scale + offset, 0.0);
}
vec3 pcg3(uvec3 v) {
    v = v * 1664525u + 1013904223u;
    v.x += v.y * v.z; v.y += v.z * v.x; v.z += v.x * v.y;
    v ^= v >> 16u;
    v.x += v.y * v.z; v.y += v.z * v.x; v.z += v.x * v.y;
    return vec3(v) * (1.0 / 4294967295.0);
}
vec3 hash2(vec2 c) { return pcg3(uvec3(uint(int(c.x) + 65536), uint(int(c.y) + 65536), 7u)); }
vec4 finish(vec2 uv, vec3 rgb) {
    vec4 c = src(uv);
    vec3 base = c.a > 0.0 ? c.rgb / c.a : vec3(0.0);
    return vec4(mix(base, rgb, amount) * c.a, c.a);
}

vec4 effect(vec2 uv) {
    vec3 p = tex_co(uv) + vec3(0.5, 0.5, 0.0);    // Blender's generated coordinates: the picture is 0..1 (at 比例 1)
    float g;
    if (type == 0) g = p.x;
    else if (type == 1) g = max(p.x, 0.0) * max(p.x, 0.0);
    else if (type == 2) { float t = clamp(p.x, 0.0, 1.0); g = t * t * (3.0 - 2.0 * t); }
    else if (type == 3) g = (p.x + p.y) * 0.5;
    else if (type == 4) g = max(1.0 - length(p - 0.5) * 2.0, 0.0);
    else if (type == 5) { float r = max(1.0 - length(p - 0.5) * 2.0, 0.0); g = r * r; }
    else g = atan(p.y - 0.5, p.x - 0.5) / 6.28318530718 + 0.5;
    return finish(uv, mix(color1.rgb, color2.rgb, clamp(g, 0.0, 1.0)));
}
