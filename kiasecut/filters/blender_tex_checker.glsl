// @filter [Blender] Texture / Checker
// @category Blender
// @description Blender 的棋盤格紋理：兩種顏色交錯的方格（3D：Z 每過一格就黑白反轉）
// @param color1 color #cccccc "顏色 1"
// @param color2 color #333333 "顏色 2"
// @param z float 0 -1000 1000 "Z"
// @param tex_scale float 5 0.001 1000 "比例"
// @param offset vec2 0,0 -1000 1000 "位置"
// @param amount float 1 0 1 "強度"

// Source: the Checker Texture shader node of Blender (source/blender/gpu/shaders/material/
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
    vec3 p = tex_co(uv) + vec3(0.0, 0.0, z);
    // Blender: p = (p * scale + 0.000001) * 0.999999
    p = (p + 0.000001) * 0.999999;
    int xi = int(abs(floor(p.x))), yi = int(abs(floor(p.y))), zi = int(abs(floor(p.z)));
    bool one = ((xi % 2) == (yi % 2)) == ((zi % 2) == 0);
    return finish(uv, one ? color2.rgb : color1.rgb);
}
