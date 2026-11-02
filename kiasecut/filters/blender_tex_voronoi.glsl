// @filter [Blender] Voronoi Texture
// @category Blender
// @description Blender 的 Voronoi 紋理：F1、F2、平滑 F1、到邊緣的距離、N 球半徑；可以輸出距離或格子顏色
// @param feature menu F1 "F1|F2|平滑 F1|到邊緣距離|N 球半徑" "特徵"
// @param cell_color bool false "輸出格子顏色"
// @param color1 color #000000 "顏色 1"
// @param color2 color #ffffff "顏色 2"
// @param w float 0 -1000 1000 "W（隨時間變化）"
// @param smoothness float 1 0 1 "平滑度"
// @param randomness float 1 0 1 "隨機性"
// @param tex_scale float 5 0.001 1000 "比例"
// @param offset vec2 0,0 -1000 1000 "位置"
// @param amount float 1 0 1 "強度"

// Source: the Voronoi Texture shader node of Blender (source/blender/gpu/shaders/material/
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

// The cell point of cell c: the corner plus a hashed offset (the offset moves with w)
vec2 cell_pt(vec2 c) { vec3 h = hash2(c + vec2(floor(w), 0.0)); vec3 h2 = hash2(c + vec2(floor(w) + 1.0, 0.0)); return c + mix(h.xy, h2.xy, fract(w)) * randomness + (1.0 - randomness) * 0.5; }

vec4 effect(vec2 uv) {
    vec2 p = tex_co(uv).xy;
    vec2 ip = floor(p);
    float f1 = 8.0, f2 = 8.0;
    vec2 c1 = vec2(0.0), c2 = vec2(0.0), q1 = vec2(0.0), q2 = vec2(0.0);
    float sm = 8.0; vec2 smc = vec2(0.0);
    for (int j = -2; j <= 2; j++) for (int i = -2; i <= 2; i++) {
        vec2 c = ip + vec2(i, j);
        vec2 q = cell_pt(c);
        float d = distance(p, q);
        if (d < f1) { f2 = f1; c2 = c1; q2 = q1; f1 = d; c1 = c; q1 = q; }
        else if (d < f2) { f2 = d; c2 = c; q2 = q; }
        if (feature == 2) {         // smooth F1 (Blender: smoothstep weight, minus the correction term)
            float h = smoothstep(0.0, 1.0, 0.5 + 0.5 * (sm - d) / max(smoothness, 1e-4));
            sm = mix(sm, d, h) - smoothness * h * (1.0 - h);
            smc = mix(smc, c, h);
        }
    }
    float fac; vec2 cell;
    if (feature == 0) { fac = f1; cell = c1; }
    else if (feature == 1) { fac = f2; cell = c2; }
    else if (feature == 2) { fac = sm; cell = smc; }
    else if (feature == 3) {        // distance to the nearest edge between cells
        float e = 8.0;
        for (int j = -2; j <= 2; j++) for (int i = -2; i <= 2; i++) {
            vec2 q = cell_pt(ip + vec2(i, j));
            if (distance(q, q1) < 1e-5) continue;
            float de = dot(0.5 * (q1 + q) - p, normalize(q - q1));
            e = min(e, de);
        }
        fac = e; cell = c1;
    } else { fac = distance(q1, q2) * 0.5; cell = c1; }   // N-sphere radius
    vec3 rgb = cell_color ? hash2(cell + 31.0) : mix(color1.rgb, color2.rgb, clamp(fac, 0.0, 1.0));
    return finish(uv, rgb);
}
